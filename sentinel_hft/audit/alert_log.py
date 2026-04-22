"""Sidecar BLAKE2b-chained log of triage *alerts* (Workstream 5).

Background
----------

The on-chain risk-audit log (``rtl/risk_audit_log.sv`` mirrored in
``sentinel_hft.audit.record``) is a 96-byte fixed-layout per-decision
record. Its layout is RTL-frozen: extending it to carry software-only
triage alerts would force a hardware respin and break the existing
verifier.

Triage alerts are different in kind:

* They originate in software (Workstream 5 detectors), not in the
  risk gate.
* They are observational -- the alert does not block trades; it
  pages a human.
* They have a different schema: detector name, severity, free-text
  detail, score.

So we keep them in a *sidecar* file, ``alerts.alog``, which lives
next to the risk audit log in the same drill-output directory and
uses the same hash-chain discipline (BLAKE2b-256, low-128-bit prev
pointer). A combined verifier can therefore confirm both chains in
one sweep.

File format
-----------

Header (16 bytes)::

    magic       : 4 bytes  = b"SALT"   ("Sentinel ALerT")
    version     : u16
    record_size : u16  = 0  (variable-length records)
    reserved    : 8 bytes

Each record::

    framing     : u32   = total record size on disk (incl. these 4 bytes)
    seq_no      : u64
    timestamp_ns: u64
    severity    : u8    (0=info, 1=warn, 2=alert)
    detector_len: u8
    stage_len   : u8
    detail_len  : u16
    score_q32   : i64   (score * 2**32, fixed-point)
    window_n    : u32
    flags       : u32
    prev_hash_lo: 16 bytes
    detector    : detector_len bytes (UTF-8)
    stage       : stage_len bytes    (UTF-8, may be 0 length)
    detail      : detail_len bytes   (UTF-8)
    full_hash_lo: 16 bytes  (hash of all preceding bytes EXCLUDING this)

Hash chain
----------

For record ``i``::

    h_i = BLAKE2b-256(record_i_payload)         # payload excludes prev_hash_lo and full_hash_lo
    record_{i+1}.prev_hash_lo == low128(h_i)
    record_i.full_hash_lo  == low128(h_i)

So a verifier walks the file, recomputes ``h_i``, asserts the
in-record ``full_hash_lo`` matches and the *next* record's
``prev_hash_lo`` equals it. A tampered, deleted, or reordered
record fails one of those checks.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List, Optional


ALERT_MAGIC = b"SALT"
ALERT_FORMAT_VERSION = 1
ALERT_HEADER_STRUCT = struct.Struct("<4sHH8x")
ALERT_HEADER_SIZE = 16

# Fixed prefix laid out before the variable-length tail.
#  framing(u32) seq(u64) ts(u64) sev(u8) dlen(u8) stlen(u8) dtlen(u16)
#  score_q32(i64) window_n(u32) flags(u32) prev_hash_lo(16)
ALERT_PREFIX_STRUCT = struct.Struct("<IQQBBBHqII16s")
ALERT_PREFIX_SIZE = ALERT_PREFIX_STRUCT.size  # 56 bytes
ALERT_TRAILER_SIZE = 16                       # full_hash_lo

SEVERITY_INFO = 0
SEVERITY_WARN = 1
SEVERITY_ALERT = 2

_SEVERITY_BY_NAME = {
    "info": SEVERITY_INFO,
    "warn": SEVERITY_WARN,
    "alert": SEVERITY_ALERT,
}
_SEVERITY_BY_CODE = {v: k for k, v in _SEVERITY_BY_NAME.items()}


def severity_from_str(name: str) -> int:
    try:
        return _SEVERITY_BY_NAME[name.lower()]
    except KeyError as e:
        raise ValueError(f"unknown severity {name!r}") from e


def severity_to_str(code: int) -> str:
    return _SEVERITY_BY_CODE.get(code, f"unknown_{code}")


# ---------------------------------------------------------------------
# AlertRecord
# ---------------------------------------------------------------------


@dataclass
class AlertRecord:
    """One software-emitted triage alert.

    All strings are UTF-8 and length-prefixed. ``score`` is stored
    as a Q32 fixed-point signed 64-bit integer (``score * 2**32``)
    so the wire format is bit-stable across hosts.
    """

    seq_no: int
    timestamp_ns: int
    severity: int                      # 0 info / 1 warn / 2 alert
    detector: str
    stage: Optional[str]
    detail: str
    score: float
    window_n: int = 0
    flags: int = 0
    prev_hash_lo: bytes = b"\x00" * 16
    full_hash_lo: bytes = b"\x00" * 16

    # ----- helpers -----------------------------------------------------

    @staticmethod
    def _enc(s: Optional[str]) -> bytes:
        if s is None:
            return b""
        return s.encode("utf-8")

    @staticmethod
    def _score_q32(v: float) -> int:
        q = int(round(v * (1 << 32)))
        # clamp to signed 64
        max_q = (1 << 63) - 1
        min_q = -(1 << 63)
        if q > max_q:
            q = max_q
        elif q < min_q:
            q = min_q
        return q

    # ----- payload that gets hashed (excludes both hash slots) ---------

    def payload_bytes(self) -> bytes:
        det = self._enc(self.detector)
        stg = self._enc(self.stage)
        dtl = self._enc(self.detail)
        if len(det) > 255:
            raise ValueError("detector name too long (max 255 bytes utf-8)")
        if len(stg) > 255:
            raise ValueError("stage name too long (max 255 bytes utf-8)")
        if len(dtl) > 65535:
            raise ValueError("detail too long (max 65535 bytes utf-8)")
        framing = ALERT_PREFIX_SIZE + len(det) + len(stg) + len(dtl) + ALERT_TRAILER_SIZE
        prefix = ALERT_PREFIX_STRUCT.pack(
            framing,
            self.seq_no,
            self.timestamp_ns,
            self.severity & 0xFF,
            len(det),
            len(stg),
            len(dtl),
            self._score_q32(self.score),
            self.window_n & 0xFFFFFFFF,
            self.flags & 0xFFFFFFFF,
            b"\x00" * 16,                 # prev_hash slot zeroed for hash
        )
        return prefix + det + stg + dtl

    def encode(self) -> bytes:
        """Serialise to wire format with prev_hash_lo + full_hash_lo populated."""
        det = self._enc(self.detector)
        stg = self._enc(self.stage)
        dtl = self._enc(self.detail)
        framing = ALERT_PREFIX_SIZE + len(det) + len(stg) + len(dtl) + ALERT_TRAILER_SIZE
        prefix = ALERT_PREFIX_STRUCT.pack(
            framing,
            self.seq_no,
            self.timestamp_ns,
            self.severity & 0xFF,
            len(det),
            len(stg),
            len(dtl),
            self._score_q32(self.score),
            self.window_n & 0xFFFFFFFF,
            self.flags & 0xFFFFFFFF,
            self.prev_hash_lo,
        )
        return prefix + det + stg + dtl + self.full_hash_lo

    @classmethod
    def decode(cls, buf: bytes) -> "AlertRecord":
        if len(buf) < ALERT_PREFIX_SIZE + ALERT_TRAILER_SIZE:
            raise ValueError("alert record too short")
        u = ALERT_PREFIX_STRUCT.unpack_from(buf, 0)
        (
            framing, seq, ts, sev, dlen, stlen, dtlen,
            score_q, win, flags, prev_lo,
        ) = u
        if framing != len(buf):
            raise ValueError(
                f"alert record framing mismatch: {framing} != {len(buf)}"
            )
        off = ALERT_PREFIX_SIZE
        det = buf[off : off + dlen].decode("utf-8")
        off += dlen
        stg_raw = buf[off : off + stlen]
        off += stlen
        dtl = buf[off : off + dtlen].decode("utf-8")
        off += dtlen
        full_lo = buf[off : off + ALERT_TRAILER_SIZE]
        return cls(
            seq_no=seq,
            timestamp_ns=ts,
            severity=sev,
            detector=det,
            stage=stg_raw.decode("utf-8") if stlen else None,
            detail=dtl,
            score=score_q / (1 << 32),
            window_n=win,
            flags=flags,
            prev_hash_lo=prev_lo,
            full_hash_lo=full_lo,
        )

    # ----- hash --------------------------------------------------------

    def full_hash(self) -> bytes:
        return hashlib.blake2b(self.payload_bytes(), digest_size=32).digest()

    def hash_lo(self) -> bytes:
        return self.full_hash()[:16]

    # ----- accessors ---------------------------------------------------

    @property
    def severity_name(self) -> str:
        return severity_to_str(self.severity)

    def to_dict(self) -> dict:
        return {
            "seq_no": self.seq_no,
            "timestamp_ns": self.timestamp_ns,
            "severity": self.severity_name,
            "detector": self.detector,
            "stage": self.stage,
            "detail": self.detail,
            "score": self.score,
            "window_n": self.window_n,
            "flags": self.flags,
            "prev_hash_lo": self.prev_hash_lo.hex(),
            "full_hash_lo": self.full_hash_lo.hex(),
        }


# ---------------------------------------------------------------------
# AlertChain -- append-only writer, maintains hash chain
# ---------------------------------------------------------------------


class AlertChain:
    """Append-only writer that maintains the BLAKE2b chain.

    Usage::

        chain = AlertChain.open(path)
        chain.append(detector="latency_zscore", severity="warn",
                     detail="...", score=4.7, stage="core",
                     timestamp_ns=now_ns())
        chain.close()

    Or as a context manager.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._fp = None  # type: ignore[assignment]
        self._seq_no = 0
        self._prev_hash_lo = b"\x00" * 16

    @classmethod
    def open(cls, path) -> "AlertChain":
        c = cls(Path(path))
        c._open()
        return c

    def _open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and self.path.stat().st_size >= ALERT_HEADER_SIZE:
            # Re-open existing chain: walk to the tail to recover seq + prev hash.
            recs = list(read_alerts(self.path))
            if recs:
                self._seq_no = recs[-1].seq_no + 1
                self._prev_hash_lo = recs[-1].full_hash_lo
            self._fp = self.path.open("ab")
        else:
            self._fp = self.path.open("wb")
            self._fp.write(ALERT_HEADER_STRUCT.pack(
                ALERT_MAGIC, ALERT_FORMAT_VERSION, 0,
            ))
            self._fp.flush()

    # -- public API ----------------------------------------------------

    def append(
        self,
        *,
        detector: str,
        severity,
        detail: str,
        score: float,
        timestamp_ns: int,
        stage: Optional[str] = None,
        window_n: int = 0,
        flags: int = 0,
    ) -> AlertRecord:
        sev = severity if isinstance(severity, int) else severity_from_str(severity)
        rec = AlertRecord(
            seq_no=self._seq_no,
            timestamp_ns=timestamp_ns,
            severity=sev,
            detector=detector,
            stage=stage,
            detail=detail,
            score=float(score),
            window_n=window_n,
            flags=flags,
            prev_hash_lo=self._prev_hash_lo,
        )
        rec.full_hash_lo = rec.hash_lo()
        buf = rec.encode()
        assert self._fp is not None
        self._fp.write(buf)
        self._fp.flush()
        self._seq_no += 1
        self._prev_hash_lo = rec.full_hash_lo
        return rec

    def close(self) -> None:
        if self._fp is not None:
            self._fp.close()
            self._fp = None

    def __enter__(self) -> "AlertChain":
        if self._fp is None:
            self._open()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


# ---------------------------------------------------------------------
# Reader + verifier
# ---------------------------------------------------------------------


def read_alerts(path) -> Iterator[AlertRecord]:
    """Iterate AlertRecords from an on-disk chain. Does not verify."""
    p = Path(path)
    with p.open("rb") as f:
        head = f.read(ALERT_HEADER_SIZE)
        if len(head) < ALERT_HEADER_SIZE:
            raise ValueError(f"alert log too small: {p}")
        magic, version, _rec_size = ALERT_HEADER_STRUCT.unpack(head)
        if magic != ALERT_MAGIC:
            raise ValueError(f"not an alert log (magic={magic!r}): {p}")
        if version != ALERT_FORMAT_VERSION:
            raise ValueError(
                f"unsupported alert log version {version} in {p}"
            )
        while True:
            head4 = f.read(4)
            if not head4:
                return
            if len(head4) != 4:
                raise ValueError(f"truncated alert framing in {p}")
            (framing,) = struct.unpack("<I", head4)
            rest = f.read(framing - 4)
            if len(rest) != framing - 4:
                raise ValueError(f"truncated alert record in {p}")
            yield AlertRecord.decode(head4 + rest)


@dataclass
class AlertVerifyResult:
    chain_ok: bool
    n_records: int
    head_hash_lo_hex: str
    bad_index: Optional[int] = None
    bad_reason: Optional[str] = None


def verify_chain(path) -> AlertVerifyResult:
    """Walk the chain, recompute hashes, confirm prev pointers.

    Tolerates malformed records by reporting them as a chain failure
    instead of letting the decoder raise.
    """
    prev_lo = b"\x00" * 16
    last_hash_lo = b""
    n = 0
    it = read_alerts(path)
    i = 0
    while True:
        try:
            rec = next(it)
        except StopIteration:
            break
        except (ValueError, UnicodeDecodeError, struct.error) as e:
            return AlertVerifyResult(
                chain_ok=False, n_records=n,
                head_hash_lo_hex=last_hash_lo.hex(),
                bad_index=i, bad_reason=f"decode error: {e}",
            )
        # 1. Embedded prev pointer matches running prev hash.
        if rec.prev_hash_lo != prev_lo:
            return AlertVerifyResult(
                chain_ok=False, n_records=n,
                head_hash_lo_hex=last_hash_lo.hex(),
                bad_index=i, bad_reason="prev_hash mismatch",
            )
        # 2. In-record full_hash_lo matches recomputed hash.
        h = rec.hash_lo()
        if rec.full_hash_lo != h:
            return AlertVerifyResult(
                chain_ok=False, n_records=n,
                head_hash_lo_hex=last_hash_lo.hex(),
                bad_index=i, bad_reason="full_hash mismatch",
            )
        # 3. Chain step.
        prev_lo = h
        last_hash_lo = h
        n += 1
        i += 1
    return AlertVerifyResult(
        chain_ok=True, n_records=n,
        head_hash_lo_hex=last_hash_lo.hex(),
    )


__all__ = [
    "ALERT_MAGIC",
    "ALERT_FORMAT_VERSION",
    "ALERT_HEADER_STRUCT",
    "ALERT_HEADER_SIZE",
    "ALERT_PREFIX_STRUCT",
    "ALERT_PREFIX_SIZE",
    "ALERT_TRAILER_SIZE",
    "SEVERITY_INFO",
    "SEVERITY_WARN",
    "SEVERITY_ALERT",
    "AlertRecord",
    "AlertChain",
    "AlertVerifyResult",
    "severity_from_str",
    "severity_to_str",
    "read_alerts",
    "verify_chain",
]
