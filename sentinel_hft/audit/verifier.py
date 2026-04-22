"""Walk an audit record stream and verify the hash chain.

The verifier accepts records in order and returns a structured
``VerificationResult``. It does not raise on the first failure --
regulators and operators want the full picture (how many records
verified, exactly which seq number broke, what kind of break it was).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, List, Optional

from .logger import SEED_PREV_HASH
from .record import AuditRecord


class BreakKind(str, Enum):
    """Kinds of integrity failures the verifier recognises."""

    OK = "ok"
    PREV_HASH_MISMATCH = "prev_hash_mismatch"
    NON_MONOTONIC_SEQ = "non_monotonic_seq"
    NON_MONOTONIC_TIMESTAMP = "non_monotonic_timestamp"
    TRUNCATED_SEED = "truncated_seed"


@dataclass
class ChainBreak:
    """One integrity failure located in the stream."""

    seq_no: int
    kind: BreakKind
    detail: str

    def to_dict(self) -> dict:
        return {
            "seq_no": self.seq_no,
            "kind": self.kind.value,
            "detail": self.detail,
        }


@dataclass
class VerificationResult:
    """Summary of a full walk over an audit stream."""

    total_records: int = 0
    verified_records: int = 0
    breaks: List[ChainBreak] = field(default_factory=list)
    head_hash_lo: Optional[bytes] = None

    @property
    def ok(self) -> bool:
        return not self.breaks and self.total_records >= 0

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "total_records": self.total_records,
            "verified_records": self.verified_records,
            "breaks": [b.to_dict() for b in self.breaks],
            "head_hash_lo_hex": (
                self.head_hash_lo.hex() if self.head_hash_lo else None
            ),
        }


def verify(records: Iterable[AuditRecord],
           expected_seed: bytes = SEED_PREV_HASH) -> VerificationResult:
    """Walk ``records`` and return a :class:`VerificationResult`.

    We check three things per record:

    1. ``prev_hash_lo`` equals the expected chained hash. For record
       0 the expected value is the seed (zeros by default). For
       record N it is the low 128 bits of BLAKE2b of record N-1's
       payload.
    2. ``seq_no`` is strictly monotonic. A gap or out-of-order seq is
       recorded as a break but verification continues so we can count
       how much downstream material still verifies.
    3. ``timestamp_ns`` is non-decreasing. A backwards clock is
       suspicious but not fatal -- it's common across reboots without
       PTP. We flag it separately from the hash break.
    """
    result = VerificationResult()
    expected_prev = expected_seed
    last_seq: Optional[int] = None
    last_ts: int = -1

    for rec in records:
        result.total_records += 1

        # -- prev-hash check ---------------------------------------------
        if rec.prev_hash_lo != expected_prev:
            if result.total_records == 1 and rec.prev_hash_lo == SEED_PREV_HASH:
                # This is record 0 with the standard seed -- just a
                # mismatch between caller's expected_seed override.
                result.breaks.append(ChainBreak(
                    seq_no=rec.seq_no,
                    kind=BreakKind.TRUNCATED_SEED,
                    detail=(
                        f"record 0 uses default seed but caller expected "
                        f"{expected_seed.hex()}"
                    ),
                ))
            else:
                result.breaks.append(ChainBreak(
                    seq_no=rec.seq_no,
                    kind=BreakKind.PREV_HASH_MISMATCH,
                    detail=(
                        f"prev_hash_lo {rec.prev_hash_lo.hex()} != "
                        f"expected {expected_prev.hex()}"
                    ),
                ))

        # -- seq monotonicity --------------------------------------------
        if last_seq is not None and rec.seq_no != last_seq + 1:
            result.breaks.append(ChainBreak(
                seq_no=rec.seq_no,
                kind=BreakKind.NON_MONOTONIC_SEQ,
                detail=f"expected seq {last_seq + 1}, got {rec.seq_no}",
            ))
        last_seq = rec.seq_no

        # -- timestamp monotonicity --------------------------------------
        if rec.timestamp_ns < last_ts:
            result.breaks.append(ChainBreak(
                seq_no=rec.seq_no,
                kind=BreakKind.NON_MONOTONIC_TIMESTAMP,
                detail=(
                    f"ts {rec.timestamp_ns} < previous {last_ts}"
                ),
            ))
        last_ts = rec.timestamp_ns

        # Advance expected chain state using the *actual* hash of this
        # record (not the one it claims to chain to). This way a later
        # break can still be caught even after an earlier one.
        expected_prev = rec.hash_lo()

        if not any(
            b.seq_no == rec.seq_no and b.kind == BreakKind.PREV_HASH_MISMATCH
            for b in result.breaks
        ):
            result.verified_records += 1

    result.head_hash_lo = expected_prev if result.total_records > 0 else None
    return result


__all__ = [
    "verify",
    "VerificationResult",
    "ChainBreak",
    "BreakKind",
]
