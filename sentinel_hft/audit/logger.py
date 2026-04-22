"""Reference implementation of the hash-chained audit logger.

This Python class matches the semantics of ``rtl/risk_audit_log.sv``
(module ``risk_audit_log``) at the record level. In simulation it
stands in for the DPI sink; in software-only mode (no FPGA) it is
what produces the audit trail the regulator sees.

The logger enforces exactly one invariant: every emitted record's
``prev_hash_lo`` equals the low 128 bits of the BLAKE2b hash of the
previous record's payload. The seed (record 0) uses 16 zero bytes.

No durability contract here -- callers hand the records to
``write_records`` or to their preferred sink.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

from .record import (
    AUDIT_RECORD_SIZE,
    AuditRecord,
    FLAG_KILL_TRIGGERED,
    FLAG_PASSED,
    FLAG_POS_HIT,
    FLAG_RATE_HIT,
    RejectReason,
)


# 16 zero bytes; the first record's prev hash.
SEED_PREV_HASH = b"\x00" * 16


@dataclass
class RiskDecision:
    """Decision the risk gate produced for one order.

    Captures the minimum state needed to reconstruct what happened
    and why. The logger ingests this and emits an ``AuditRecord``.
    """

    timestamp_ns: int
    order_id: int
    symbol_id: int
    quantity: int
    price: int
    notional: int
    passed: bool
    reject_reason: int = RejectReason.OK
    kill_triggered: bool = False
    tokens_remaining: int = 0
    position_after: int = 0
    notional_after: int = 0


class AuditLogger:
    """Stateful hash-chained audit logger.

    Typical use::

        log = AuditLogger()
        for decision in stream:
            rec = log.log(decision)
            sink(rec)
        log.flush()

    Not thread-safe; wrap externally if you're emitting from multiple
    cores. For a single risk gate this doesn't matter because every
    decision funnels through one in-order pipe.
    """

    def __init__(self, sink: Optional[Callable[[AuditRecord], None]] = None):
        self._seq = 0
        self._prev_hash_lo = SEED_PREV_HASH
        self._sink = sink
        self._records: List[AuditRecord] = []

    # -- ingestion ----------------------------------------------------------

    def log(self, decision: RiskDecision) -> AuditRecord:
        """Emit a record for ``decision`` and advance the chain."""
        flags = 0
        if decision.passed:
            flags |= FLAG_PASSED
        if decision.kill_triggered:
            flags |= FLAG_KILL_TRIGGERED
        if decision.reject_reason == int(RejectReason.RATE_LIMITED):
            flags |= FLAG_RATE_HIT
        if decision.reject_reason in (
            int(RejectReason.POSITION_LIMIT),
            int(RejectReason.NOTIONAL_LIMIT),
            int(RejectReason.ORDER_SIZE),
        ):
            flags |= FLAG_POS_HIT

        rec = AuditRecord(
            seq_no=self._seq,
            timestamp_ns=decision.timestamp_ns,
            order_id=decision.order_id,
            symbol_id=decision.symbol_id,
            reject_reason=int(decision.reject_reason),
            flags=flags,
            quantity=decision.quantity,
            price=decision.price,
            notional=decision.notional,
            position_after=decision.position_after,
            notional_after=decision.notional_after,
            tokens_remaining=decision.tokens_remaining,
            reserved=0,
            prev_hash_lo=self._prev_hash_lo,
        )

        # Advance the chain using this record's hash.
        self._prev_hash_lo = rec.hash_lo()
        self._seq += 1
        self._records.append(rec)
        if self._sink is not None:
            self._sink(rec)
        return rec

    # -- output -------------------------------------------------------------

    @property
    def records(self) -> List[AuditRecord]:
        """All records emitted so far, in order."""
        return list(self._records)

    @property
    def head_hash_lo(self) -> bytes:
        """Low 128 bits of the most recent record's hash. A regulator
        only needs this and the record count to pin the audit log's
        head; everything before it is committed."""
        return self._prev_hash_lo

    @property
    def count(self) -> int:
        return self._seq


__all__ = [
    "AuditLogger",
    "RiskDecision",
    "SEED_PREV_HASH",
]
