"""Binary record format for on-chain latency traces.

Layout (little-endian, 80 bytes total):

    offset  size  field            notes
    ------  ----  ---------------  -----------------------------------------
    0       1     version          0x01 for this layout
    1       1     venue            see OnchainVenue enum below
    2       1     action           see OnchainAction enum below
    3       1     flags            bit 0: rejected; bit 1: timeout;
                                   bit 2: reorg; bit 3: tx landed
    4       4     seq_no           client sequence number
    8       8     client_ts_ns     t0 -- market event observed (wall clock)
    16      8     signed_ts_ns     t1 -- signature complete
    24      8     submitted_ts_ns  t2 -- submit() returned
    32      8     included_ts_ns   t3 -- seen on-chain / sequencer ack
    40      8     symbol_hash      xxhash64 of symbol (e.g. "BTC-USD")
    48      4     d_rpc_ns         market-data handoff latency
    52      4     d_quote_ns       strategy decision latency
    56      4     d_sign_ns        signing latency
    60      4     d_submit_ns      submit syscall / RPC latency
    64      4     d_inclusion_ns   submit -> on-chain ack
    68      4     notional_usd_e4  notional in USD * 1e4
    72      4     slippage_bps     realised slippage in basis points (signed)
    76      4     reserved

Design notes
------------

All deltas are u32 nanoseconds -- sufficient up to 4.29 seconds per stage,
which is far beyond what any reasonable implementation would tolerate.
Timestamps are u64 ns wall clock so absolute correlation with exchange
sequencer logs is possible.

We deliberately do NOT reuse the v1.1/v1.2 FPGA trace layout: different
semantics (wall-clock ns vs FPGA cycles), different stage vocabulary,
different provenance (signed tx, not a trace frame).

This is a *client-side* trace: the block time ``d_inclusion`` is the
floor on latency for sequencer-based venues (Hyperliquid sequencer,
Arbitrum Nova, Solana leader slot). Interview point: this is where
the FPGA stops mattering and the venue starts -- Sentinel quantifies the
boundary.
"""

from __future__ import annotations

import enum
import struct
from dataclasses import dataclass
from typing import Optional


# 4-byte magic at the head of a file means "on-chain trace, not v1.x FPGA".
ONCHAIN_MAGIC = b"SOCH"  # Sentinel On-CHain
ONCHAIN_FORMAT_VERSION = 1

# Header layout: MAGIC + u16 version + u16 record_size + 8-byte reserved.
ONCHAIN_FILE_HEADER_STRUCT = struct.Struct("<4sHH8x")
ONCHAIN_FILE_HEADER_SIZE = 16
assert ONCHAIN_FILE_HEADER_STRUCT.size == ONCHAIN_FILE_HEADER_SIZE

# Record struct: see docstring for byte-level layout.
# Fields (in order):
#   BBBB  version, venue, action, flags         (4 bytes)
#   I     seq_no                                (4 bytes; total 8)
#   QQQQQ client_ts, signed_ts, submitted_ts,
#         included_ts, symbol_hash              (40 bytes; total 48)
#   IIIII d_rpc, d_quote, d_sign,
#         d_submit, d_inclusion                 (20 bytes; total 68)
#   I     notional_usd_e4                       (4 bytes; total 72)
#   i     slippage_bps (signed)                 (4 bytes; total 76)
#   I     reserved                              (4 bytes; total 80)
ONCHAIN_STRUCT = struct.Struct("<BBBBIQQQQQIIIIIIiI")
ONCHAIN_RECORD_SIZE = 80
assert ONCHAIN_STRUCT.size == ONCHAIN_RECORD_SIZE, (
    f"onchain struct size mismatch: {ONCHAIN_STRUCT.size} != {ONCHAIN_RECORD_SIZE}"
)


class OnchainStage(enum.IntEnum):
    """Pipeline stages in order."""

    RPC = 0
    QUOTE = 1
    SIGN = 2
    SUBMIT = 3
    INCLUSION = 4


class OnchainVenue(enum.IntEnum):
    """Supported on-chain / off-exchange venues.

    These are the venues we have realistic latency models for; unknown
    is allowed so arbitrary test fixtures don't fail validation.
    """

    UNKNOWN = 0
    HYPERLIQUID = 1
    LIGHTER = 2
    SOLANA_JITO = 3
    DYDX_V4 = 4
    JUPITER = 5


class OnchainAction(enum.IntEnum):
    """High-level action the trace represents."""

    UNKNOWN = 0
    QUOTE = 1        # passive maker quote placement
    TAKE = 2         # aggressive take
    CANCEL = 3       # order cancel
    MODIFY = 4       # order modify
    WITHDRAWAL = 5   # settlement / transfer


# Flag bits. Values are u8 flags.
FLAG_REJECTED = 0x01
FLAG_TIMEOUT = 0x02
FLAG_REORG = 0x04
FLAG_LANDED = 0x08


@dataclass
class OnchainRecord:
    """In-memory representation of a single on-chain trace record.

    Instances are created either by synthetic fixture generators
    (see ``onchain.fixtures``) or by decoding bytes with ``decode``.
    """

    version: int
    venue: int
    action: int
    flags: int
    seq_no: int
    client_ts_ns: int
    signed_ts_ns: int
    submitted_ts_ns: int
    included_ts_ns: int
    symbol_hash: int
    d_rpc_ns: int
    d_quote_ns: int
    d_sign_ns: int
    d_submit_ns: int
    d_inclusion_ns: int
    notional_usd_e4: int
    slippage_bps: int
    reserved: int = 0

    # -- Encoding --------------------------------------------------------

    def encode(self) -> bytes:
        """Pack to on-wire/on-disk bytes."""
        return ONCHAIN_STRUCT.pack(
            self.version,
            self.venue,
            self.action,
            self.flags,
            self.seq_no,
            self.client_ts_ns,
            self.signed_ts_ns,
            self.submitted_ts_ns,
            self.included_ts_ns,
            self.symbol_hash,
            self.d_rpc_ns,
            self.d_quote_ns,
            self.d_sign_ns,
            self.d_submit_ns,
            self.d_inclusion_ns,
            self.notional_usd_e4,
            self.slippage_bps,
            self.reserved,
        )

    @classmethod
    def decode(cls, data: bytes) -> "OnchainRecord":
        """Decode 80 bytes to a record."""
        if len(data) != ONCHAIN_RECORD_SIZE:
            raise ValueError(
                f"Expected {ONCHAIN_RECORD_SIZE} bytes, got {len(data)}"
            )
        u = ONCHAIN_STRUCT.unpack(data)
        return cls(
            version=u[0], venue=u[1], action=u[2], flags=u[3],
            seq_no=u[4],
            client_ts_ns=u[5], signed_ts_ns=u[6],
            submitted_ts_ns=u[7], included_ts_ns=u[8],
            symbol_hash=u[9],
            d_rpc_ns=u[10], d_quote_ns=u[11],
            d_sign_ns=u[12], d_submit_ns=u[13],
            d_inclusion_ns=u[14],
            notional_usd_e4=u[15], slippage_bps=u[16], reserved=u[17],
        )

    # -- Derived metrics -------------------------------------------------

    @property
    def total_ns(self) -> int:
        """End-to-end latency: market event -> inclusion.

        Uses wall-clock timestamps because wall-clock jitter between
        threads can exceed the sum of per-stage deltas when the
        scheduler descheduled the thread between stages.
        """
        return max(0, int(self.included_ts_ns - self.client_ts_ns))

    @property
    def stage_sum_ns(self) -> int:
        """Sum of explicit per-stage deltas. Difference from ``total_ns``
        indicates scheduler / queueing overhead between stages."""
        return (
            self.d_rpc_ns + self.d_quote_ns + self.d_sign_ns
            + self.d_submit_ns + self.d_inclusion_ns
        )

    @property
    def overhead_ns(self) -> int:
        """Unaccounted-for latency: ``total - sum(stages)``.

        Positive overhead means the stages don't cover the wall clock
        -- typically thread preemption, GC pause, or NUMA miss.
        """
        return max(0, self.total_ns - self.stage_sum_ns)

    @property
    def landed(self) -> bool:
        return bool(self.flags & FLAG_LANDED)

    @property
    def rejected(self) -> bool:
        return bool(self.flags & FLAG_REJECTED)

    @property
    def timed_out(self) -> bool:
        return bool(self.flags & FLAG_TIMEOUT)

    @property
    def reorged(self) -> bool:
        return bool(self.flags & FLAG_REORG)

    def stage_ns(self, stage: OnchainStage) -> int:
        """Access a single stage latency by enum."""
        return (
            self.d_rpc_ns, self.d_quote_ns, self.d_sign_ns,
            self.d_submit_ns, self.d_inclusion_ns,
        )[int(stage)]


def symbol_hash(sym: str) -> int:
    """Stable 64-bit hash of a symbol for use as ``OnchainRecord.symbol_hash``.

    Uses Python's built-in hash of the utf-8 bytes modulo 2**64. Not
    cryptographically strong -- only used for grouping traces by symbol
    without shipping the symbol string in every record.
    """
    import hashlib
    h = hashlib.blake2b(sym.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(h, "little", signed=False)


__all__ = [
    "OnchainStage",
    "OnchainVenue",
    "OnchainAction",
    "OnchainRecord",
    "ONCHAIN_STRUCT",
    "ONCHAIN_RECORD_SIZE",
    "ONCHAIN_MAGIC",
    "ONCHAIN_FORMAT_VERSION",
    "ONCHAIN_FILE_HEADER_STRUCT",
    "ONCHAIN_FILE_HEADER_SIZE",
    "FLAG_REJECTED",
    "FLAG_TIMEOUT",
    "FLAG_REORG",
    "FLAG_LANDED",
    "symbol_hash",
]
