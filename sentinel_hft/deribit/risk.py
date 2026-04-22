"""Python reference for the FPGA risk gate used in the demo.

The three primitives here mirror the SystemVerilog modules in
``rtl/``:

* :class:`TokenBucket`     -- ``rtl/rate_limit.sv``
* :class:`PositionTracker` -- ``rtl/position_limit.sv``
* :class:`KillSwitch`      -- ``rtl/kill_switch.sv``

They are intentionally simple (no dataframes, no numpy) so that the
pipeline stays allocation-light and easy to audit. The
:class:`RiskGate` composes the three and returns a
:class:`~sentinel_hft.audit.RiskDecision` -compatible tuple.

Semantic parity with ``tests/test_risk.py`` is asserted by the Deribit
test suite: the same reference is imported there to cross-check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

from ..audit import RejectReason, RiskDecision
from .strategy import IntentAction, QuoteIntent, Side


# ---------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------


@dataclass
class TokenBucket:
    """Leaky-bucket rate limiter driven by wall-clock ns.

    Unlike ``tests/test_risk.py``'s cycle-driven version, this
    variant advances the bucket in real time so the pipeline can
    call it without knowing the clock period.
    """

    max_tokens: int = 1000
    refill_per_second: float = 500.0  # tokens / s
    tokens: float = field(init=False)
    last_refill_ns: int = 0

    def __post_init__(self):
        self.tokens = float(self.max_tokens)

    def _refill(self, now_ns: int) -> None:
        if self.last_refill_ns == 0:
            self.last_refill_ns = now_ns
            return
        dt_s = max(0, now_ns - self.last_refill_ns) / 1_000_000_000.0
        self.tokens = min(
            self.max_tokens,
            self.tokens + dt_s * self.refill_per_second,
        )
        self.last_refill_ns = now_ns

    def try_consume(self, now_ns: int, n: int = 1) -> bool:
        self._refill(now_ns)
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False

    def remaining(self) -> int:
        return int(self.tokens)


@dataclass
class PositionTracker:
    """Per-symbol position + notional limits."""

    max_long_qty: float = 50.0
    max_short_qty: float = 50.0
    max_notional: float = 5_000_000.0     # total across all symbols
    max_order_qty: float = 10.0

    long_qty: float = 0.0
    short_qty: float = 0.0
    notional: float = 0.0

    def check(self, side: Side, qty: float, notional: float
              ) -> RejectReason:
        if qty > self.max_order_qty:
            return RejectReason.ORDER_SIZE

        if side == Side.BUY:
            projected = self.long_qty + qty
            if projected > self.max_long_qty:
                return RejectReason.POSITION_LIMIT
        else:
            projected = self.short_qty + qty
            if projected > self.max_short_qty:
                return RejectReason.POSITION_LIMIT

        if self.notional + notional > self.max_notional:
            return RejectReason.NOTIONAL_LIMIT
        return RejectReason.OK

    def apply(self, side: Side, qty: float, notional: float) -> None:
        if side == Side.BUY:
            self.long_qty += qty
        else:
            self.short_qty += qty
        self.notional += notional

    def release(self, side: Side, qty: float, notional: float) -> None:
        """Release exposure from a prior order (cancel-ack path)."""
        if side == Side.BUY:
            self.long_qty = max(0.0, self.long_qty - qty)
        else:
            self.short_qty = max(0.0, self.short_qty - qty)
        self.notional = max(0.0, self.notional - notional)

    @property
    def net(self) -> float:
        return self.long_qty - self.short_qty


@dataclass
class KillSwitch:
    """Gates everything; trips permanently until operator resets."""

    armed: bool = True
    triggered: bool = False
    auto_notional_drop: float = 10_000_000.0  # trip if notional > this

    def on_notional(self, total_notional: float) -> None:
        if self.armed and total_notional >= self.auto_notional_drop:
            self.triggered = True

    def trip(self) -> None:
        if self.armed:
            self.triggered = True

    def reset(self) -> None:
        self.triggered = False

    def check(self) -> bool:
        return not self.triggered


# ---------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------


@dataclass
class RiskGateConfig:
    """Operator-supplied knobs for the risk gate.

    Defaults are calibrated so that a 20k-tick demo run produces a
    recognisable mix of outcomes: most orders pass, the occasional
    burst trips the rate limit, and a slow-burn accumulation of
    notional eventually exercises the position/notional paths. Real
    prop-desk limits would come from the firm's risk policy.
    """

    max_tokens: int = 5_000
    refill_per_second: float = 3_000.0
    max_long_qty: float = 5_000.0
    max_short_qty: float = 5_000.0
    max_notional: float = 500_000_000.0
    max_order_qty: float = 100.0
    auto_kill_notional: float = 2_000_000_000.0


class RiskGate:
    """Composed rate + position + kill check, returns a RiskDecision."""

    def __init__(self, cfg: Optional[RiskGateConfig] = None):
        self.cfg = cfg or RiskGateConfig()
        self.bucket = TokenBucket(
            max_tokens=self.cfg.max_tokens,
            refill_per_second=self.cfg.refill_per_second,
        )
        self.positions = PositionTracker(
            max_long_qty=self.cfg.max_long_qty,
            max_short_qty=self.cfg.max_short_qty,
            max_notional=self.cfg.max_notional,
            max_order_qty=self.cfg.max_order_qty,
        )
        self.kill = KillSwitch(auto_notional_drop=self.cfg.auto_kill_notional)

        # Audit counters surfaced to the pipeline for the summary.
        self.total = 0
        self.passed = 0
        self.rejected_rate = 0
        self.rejected_pos = 0
        self.rejected_notional = 0
        self.rejected_order_size = 0
        self.rejected_kill = 0

    def evaluate(self, intent: QuoteIntent, now_ns: int) -> RiskDecision:
        """Run the gate on one :class:`QuoteIntent` and record state.

        Cancels are modelled as a free pass-through that releases the
        exposure previously tracked for the original order. They do
        not charge a rate-limit token and are not short-circuited by
        the kill switch (the gate should still accept cancels when
        killed so open quotes can be pulled).
        """
        self.total += 1

        # Cancels: release exposure, always pass, don't consume tokens.
        if intent.action == IntentAction.CANCEL:
            self.positions.release(intent.side, intent.quantity,
                                   intent.notional)
            self.passed += 1
            return self._build(intent, now_ns, passed=True,
                               reason=RejectReason.OK)

        # 1. Kill switch first (shorts everything).
        if not self.kill.check():
            self.rejected_kill += 1
            return self._build(intent, now_ns, passed=False,
                               reason=RejectReason.KILL_SWITCH,
                               kill_triggered=True)

        # 2. Rate limiter.
        if not self.bucket.try_consume(now_ns):
            self.rejected_rate += 1
            return self._build(intent, now_ns, passed=False,
                               reason=RejectReason.RATE_LIMITED)

        # 3. Position / notional / order size.
        reason = self.positions.check(intent.side, intent.quantity,
                                      intent.notional)
        if reason != RejectReason.OK:
            if reason == RejectReason.ORDER_SIZE:
                self.rejected_order_size += 1
            elif reason == RejectReason.POSITION_LIMIT:
                self.rejected_pos += 1
            elif reason == RejectReason.NOTIONAL_LIMIT:
                self.rejected_notional += 1
            return self._build(intent, now_ns, passed=False,
                               reason=reason)

        # 4. Passed -> apply + check kill-on-notional.
        self.positions.apply(intent.side, intent.quantity, intent.notional)
        self.kill.on_notional(self.positions.notional)
        self.passed += 1
        kill_triggered = self.kill.triggered  # may trip from this decision
        return self._build(intent, now_ns, passed=True,
                           reason=RejectReason.OK,
                           kill_triggered=kill_triggered)

    # ------------------------------------------------------------------

    def _build(self, intent: QuoteIntent, now_ns: int,
               *, passed: bool, reason: RejectReason,
               kill_triggered: bool = False) -> RiskDecision:
        # Scale to integer fixed-point to match the RTL record's fields.
        price_fp = int(round(intent.price * 1e8))
        notional_fp = int(round(intent.notional * 1e8))
        quantity_fp = int(round(intent.quantity * 1e6))
        long_qty_fp = int(round(self.positions.long_qty * 1e6))
        short_qty_fp = int(round(self.positions.short_qty * 1e6))
        net_fp = long_qty_fp - short_qty_fp
        notional_after_fp = int(round(self.positions.notional * 1e8))

        return RiskDecision(
            timestamp_ns=now_ns,
            order_id=intent.order_id,
            symbol_id=intent.symbol_id,
            quantity=quantity_fp,
            price=price_fp,
            notional=notional_fp,
            passed=passed,
            reject_reason=int(reason),
            kill_triggered=kill_triggered,
            tokens_remaining=self.bucket.remaining(),
            position_after=net_fp,
            notional_after=notional_after_fp,
        )


__all__ = [
    "TokenBucket",
    "PositionTracker",
    "KillSwitch",
    "RiskGate",
    "RiskGateConfig",
]
