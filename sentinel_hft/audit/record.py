"""Binary layout of a tamper-evident risk-gate audit record.

The on-chip RTL (``rtl/risk_audit_log.sv``) emits a 96-byte packed
record for every risk-gate decision. This module is the canonical
Python mirror of that layout plus the hash-chain discipline used to
make the stream tamper-evident.

Integrity model
---------------

Each record carries the low 128 bits of BLAKE2b(prev_record_payload)
in its ``prev_hash_lo`` field. The host verifier walks the stream,
recomputing each record's hash and confirming that the *next* record
embeds it correctly. The chain is therefore:

    h_0 = BLAKE2b(payload_0)       -- seed: all zeros
    h_i = BLAKE2b(payload_i)
    record_i.prev_hash_lo == low128(h_{i-1})  for all i > 0

A mutated record breaks its own hash; a deleted record breaks the
next record's prev pointer; an inserted record fails the same check.

Why 128-bit prev and full 256-bit hash?
  Storing the full 256-bit hash in the on-chip record costs wiring and
  BRAM footprint; 128 bits of second-preimage resistance is
  overwhelming for a non-adversarial audit trail, and the verifier
  still uses a 256-bit hash internally. This mirrors how Ethereum-
  tangent L2s truncate receipts while keeping the full preimage for
  settlement.
"""

from __future__ import annotations

import enum
import hashlib
import struct
from dataclasses import dataclass
from typing import Iterable, Iterator, List, Optional


AUDIT_RECORD_SIZE = 96

# See rtl/risk_audit_log.sv for the byte-level layout.
# Layout:  Q Q Q I H H Q Q Q Q Q I I 16s  = 8+8+8+4+2+2+8+8+8+8+8+4+4+16 = 96
AUDIT_STRUCT = struct.Struct("<QQQIHHQQQQQII16s")
assert AUDIT_STRUCT.size == AUDIT_RECORD_SIZE, (
    f"audit struct size mismatch: {AUDIT_STRUCT.size} != {AUDIT_RECORD_SIZE}"
)

# File format wrapper: 4-byte magic + u16 version + u16 record_size + 8 reserved.
AUDIT_MAGIC = b"SAUD"  # Sentinel AUDit
AUDIT_FORMAT_VERSION = 1
AUDIT_FILE_HEADER_STRUCT = struct.Struct("<4sHH8x")
AUDIT_FILE_HEADER_SIZE = 16


class RejectReason(enum.IntEnum):
    """Mirror of ``risk_pkg::risk_reject_e``.

    Codes 0x00..0x06 mirror the original on-chip risk-gate enum. 0x07
    (``TOXIC_FLOW``) is a software-only pre-gate reason used by the
    Hyperliquid use-cases: it surfaces when a prospective quote is
    blocked because the recent opposite-side flow is toxic-dominated.
    The RTL risk gate never produces this code today -- it is carried
    in the audit record so DORA highlights can break out adverse-
    selection rejections from rate/position/kill rejections.
    """

    OK = 0x00
    RATE_LIMITED = 0x01
    POSITION_LIMIT = 0x02
    NOTIONAL_LIMIT = 0x03
    ORDER_SIZE = 0x04
    KILL_SWITCH = 0x05
    INVALID_ORDER = 0x06
    TOXIC_FLOW = 0x07
    DISABLED = 0xFF


# Flag bits.
FLAG_PASSED = 0x0001
FLAG_KILL_TRIGGERED = 0x0002
FLAG_RATE_HIT = 0x0004
FLAG_POS_HIT = 0x0008
FLAG_TOXIC_FLOW = 0x0010


@dataclass
class AuditRecord:
    """One on-chain risk-gate decision, serialisable to 96 bytes.

    All fields map one-to-one to the RTL record layout (see
    ``rtl/risk_audit_log.sv``) and therefore should not be reordered
    or resized without updating the RTL in lockstep.
    """

    seq_no: int
    timestamp_ns: int
    order_id: int
    symbol_id: int
    reject_reason: int
    flags: int
    quantity: int
    price: int
    notional: int
    position_after: int            # signed 64
    notional_after: int
    tokens_remaining: int
    reserved: int
    prev_hash_lo: bytes            # 16 bytes

    # -- Encoding -----------------------------------------------------------

    def encode(self) -> bytes:
        """Pack to the on-wire/on-disk 96-byte representation."""
        if len(self.prev_hash_lo) != 16:
            raise ValueError(
                f"prev_hash_lo must be 16 bytes, got {len(self.prev_hash_lo)}"
            )
        # position_after is signed; struct 'q' expects signed, but our
        # struct declares 'Q'. We normalise to unsigned two's complement
        # to match the RTL's logic signed [63:0] wire treatment.
        pos = self.position_after & 0xFFFFFFFFFFFFFFFF
        return AUDIT_STRUCT.pack(
            self.seq_no,
            self.timestamp_ns,
            self.order_id,
            self.symbol_id,
            self.reject_reason,
            self.flags,
            self.quantity,
            self.price,
            self.notional,
            pos,
            self.notional_after,
            self.tokens_remaining,
            self.reserved,
            self.prev_hash_lo,
        )

    @classmethod
    def decode(cls, data: bytes) -> "AuditRecord":
        """Decode a 96-byte buffer into an ``AuditRecord``."""
        if len(data) != AUDIT_RECORD_SIZE:
            raise ValueError(
                f"Expected {AUDIT_RECORD_SIZE} bytes, got {len(data)}"
            )
        u = AUDIT_STRUCT.unpack(data)
        pos = u[9]
        if pos >= (1 << 63):
            pos -= (1 << 64)
        return cls(
            seq_no=u[0], timestamp_ns=u[1], order_id=u[2],
            symbol_id=u[3], reject_reason=u[4], flags=u[5],
            quantity=u[6], price=u[7], notional=u[8],
            position_after=pos, notional_after=u[10],
            tokens_remaining=u[11], reserved=u[12], prev_hash_lo=u[13],
        )

    # -- Hash chaining ------------------------------------------------------

    def payload_bytes(self) -> bytes:
        """Bytes hashed to produce this record's fingerprint.

        Excludes ``prev_hash_lo`` itself -- that would be a cycle. We
        hash the first 80 bytes (everything except the prev-hash
        pointer).
        """
        return self.encode()[:80]

    def full_hash(self) -> bytes:
        """BLAKE2b-256 of ``payload_bytes``. 32 bytes."""
        return hashlib.blake2b(self.payload_bytes(), digest_size=32).digest()

    def hash_lo(self) -> bytes:
        """Low 128 bits of ``full_hash`` -- what appears in the next
        record's ``prev_hash_lo`` field."""
        return self.full_hash()[:16]

    # -- Accessors ----------------------------------------------------------

    @property
    def passed(self) -> bool:
        return bool(self.flags & FLAG_PASSED)

    @property
    def kill_triggered(self) -> bool:
        return bool(self.flags & FLAG_KILL_TRIGGERED)

    @property
    def reason_name(self) -> str:
        try:
            return RejectReason(self.reject_reason).name
        except ValueError:
            return f"UNKNOWN_0x{self.reject_reason:02x}"


# --- File I/O helpers ------------------------------------------------------


def write_records(path, records: Iterable[AuditRecord]) -> int:
    """Write a header + stream of records to disk. Returns bytes written."""
    from pathlib import Path

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with p.open("wb") as f:
        f.write(AUDIT_FILE_HEADER_STRUCT.pack(
            AUDIT_MAGIC, AUDIT_FORMAT_VERSION, AUDIT_RECORD_SIZE,
        ))
        n += AUDIT_FILE_HEADER_SIZE
        for r in records:
            buf = r.encode()
            f.write(buf)
            n += len(buf)
    return n


def read_records(path) -> Iterator[AuditRecord]:
    """Iterate records from an on-disk audit log."""
    from pathlib import Path

    p = Path(path)
    with p.open("rb") as f:
        head = f.read(AUDIT_FILE_HEADER_SIZE)
        if len(head) < AUDIT_FILE_HEADER_SIZE:
            raise ValueError(f"file too small to contain header: {path}")
        magic, version, rec_size = AUDIT_FILE_HEADER_STRUCT.unpack(head)
        if magic != AUDIT_MAGIC:
            raise ValueError(
                f"not an audit log (magic={magic!r}): {path}"
            )
        if rec_size != AUDIT_RECORD_SIZE:
            raise ValueError(
                f"unexpected audit record size {rec_size} in {path}"
            )
        while True:
            buf = f.read(AUDIT_RECORD_SIZE)
            if not buf:
                return
            if len(buf) != AUDIT_RECORD_SIZE:
                raise ValueError(
                    f"truncated audit record in {path}: got {len(buf)}"
                )
            yield AuditRecord.decode(buf)


__all__ = [
    "AUDIT_RECORD_SIZE",
    "AUDIT_STRUCT",
    "AUDIT_MAGIC",
    "AUDIT_FORMAT_VERSION",
    "AUDIT_FILE_HEADER_STRUCT",
    "AUDIT_FILE_HEADER_SIZE",
    "AuditRecord",
    "RejectReason",
    "FLAG_PASSED",
    "FLAG_KILL_TRIGGERED",
    "FLAG_RATE_HIT",
    "FLAG_POS_HIT",
    "FLAG_TOXIC_FLOW",
    "write_records",
    "read_records",
]
