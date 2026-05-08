"""
Behavioral golden model for the Sentinel-HFT pre-trade risk gate.

This module mirrors the semantics of `rtl/risk_gate.sv` exactly, but in
straight-line Python. It is the reference against which:

  - V-Floor compares Verilator outputs on a randomized 10^6 corpus.
  - V-Meta exercises metamorphic relations.
  - V-Contract verifies register-map round-trips.

Conventions:
  - All quantities and notionals are non-negative integers (uint64-domain).
  - Prices are fixed-point integers with 8 decimal digits implied.
  - Net position is signed: positive=long, negative=short.
  - Reject precedence (matches rtl/risk_gate.sv):
        kill > rate > position-family > fat-finger > allowlist
    (the RTL composes them via `if !kill then check rate then ...`)
  - Reasons map to risk_pkg.sv `risk_reject_e` values 1:1.

Wave-1 audit fixes that the RTL applied are mirrored here:
  - Signed net position, no monotonic ratchet on opposite-side orders.
  - Buy-on-short unwinds short before contributing to the long cap; same
    for sell-on-long.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Iterable, List, Optional, Tuple


# -------------------------------------------------------------------------
# Enumerations — values mirror rtl/risk_pkg.sv exactly.
# -------------------------------------------------------------------------

class OrderSide(IntEnum):
    BUY = 0b01
    SELL = 0b10


class OrderType(IntEnum):
    NEW = 0x1
    CANCEL = 0x2
    MODIFY = 0x3
    HEARTBEAT = 0xF  # never counted against limits


class RejectReason(IntEnum):
    OK = 0x00
    RATE_LIMITED = 0x01
    POSITION_LIMIT = 0x02
    NOTIONAL_LIMIT = 0x03
    ORDER_SIZE = 0x04
    KILL_SWITCH = 0x05
    INVALID_ORDER = 0x06
    FAT_FINGER = 0x07          # NEW for Phase 1
    ALLOWLIST_BLOCK = 0x08     # NEW for Phase 1
    DISABLED = 0xFF


# -------------------------------------------------------------------------
# Data types
# -------------------------------------------------------------------------

@dataclass(frozen=True)
class Order:
    order_id: int
    symbol_id: int
    side: OrderSide
    order_type: OrderType
    quantity: int           # uint64
    price: int              # uint64, fixed-point (8 decimals implied)
    notional: int           # uint64; pre-computed (qty * price / 1e8 in caller)


@dataclass(frozen=True)
class Fill:
    side: OrderSide
    quantity: int           # uint64
    notional: int           # uint64


@dataclass(frozen=True)
class Decision:
    passed: bool
    reason: RejectReason
    tokens_remaining: int
    current_position: int   # signed: long-positive, short-negative
    current_notional: int   # uint64

    @property
    def reject_code(self) -> int:
        return int(self.reason)


@dataclass
class GateConfig:
    # Rate limiter
    rate_max_tokens: int = 1024
    rate_refill_rate: int = 32
    rate_refill_period: int = 100   # cycles between refills
    rate_enabled: bool = True

    # Position limiter (aggregated; see ARCHITECTURE.md amendment AM-01)
    pos_max_long: int = 10_000_000
    pos_max_short: int = 10_000_000
    pos_max_notional: int = 10**14
    pos_max_order_qty: int = 1_000_000
    pos_enabled: bool = True

    # Kill switch
    kill_armed: bool = True
    kill_auto_enabled: bool = False
    kill_loss_threshold: int = -10**12   # signed
    kill_force_trigger: bool = False     # cmd_kill_trigger pulse-equivalent

    # Fat finger
    ff_enabled: bool = True
    ff_band_bps: int = 300               # 3.00%
    ff_ref_price: int = 0                # 0 disables (no reference)

    # Allowlist
    allowlist_enabled: bool = True
    allowlist: Tuple[int, ...] = field(default_factory=tuple)


# -------------------------------------------------------------------------
# Gate
# -------------------------------------------------------------------------

class GoldenRiskGate:
    """Cycle-accurate enough for decision sequencing; not bit-accurate to
    the RTL's pipelining. The two share the same DECISION FUNCTION; the
    RTL pipelines that decision. V-Floor compares decision outputs only.
    """

    def __init__(self, cfg: GateConfig) -> None:
        self.cfg = cfg
        # Live state
        self._tokens = cfg.rate_max_tokens
        self._cycles_since_refill = 0
        self._long_qty = 0
        self._short_qty = 0
        self._notional = 0
        self._kill_tripped = False
        self._kill_trip_count = 0
        self._current_pnl = 0  # signed; updated via update_pnl
        # Counters
        self.total_orders = 0
        self.total_passed = 0
        self.total_rejected_rate = 0
        self.total_rejected_position = 0
        self.total_rejected_kill = 0
        self.total_rejected_ff = 0
        self.total_rejected_allowlist = 0

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------

    def tick(self) -> None:
        """Advance one clock cycle (refills the bucket if it's time)."""
        self._cycles_since_refill += 1
        if self._cycles_since_refill >= self.cfg.rate_refill_period:
            self._cycles_since_refill = 0
            self._tokens = min(
                self.cfg.rate_max_tokens,
                self._tokens + self.cfg.rate_refill_rate,
            )

    def update_pnl(self, pnl_signed: int) -> None:
        """Push P&L (signed) into the kill-switch auto-trigger circuit."""
        self._current_pnl = pnl_signed
        if (
            self.cfg.kill_armed
            and self.cfg.kill_auto_enabled
            and pnl_signed < self.cfg.kill_loss_threshold
        ):
            self._trip_kill()

    def fill(self, fill_event: Fill) -> None:
        """Apply a fill notification to the position book.
        Mirrors position_limiter.sv's signed unwind logic.
        """
        if fill_event.side == OrderSide.BUY:
            # Unwind short before adding long.
            unwind = min(self._short_qty, fill_event.quantity)
            self._short_qty -= unwind
            extra_long = fill_event.quantity - unwind
            self._long_qty += extra_long
        else:
            unwind = min(self._long_qty, fill_event.quantity)
            self._long_qty -= unwind
            extra_short = fill_event.quantity - unwind
            self._short_qty += extra_short
        # Notional accumulates gross (matches RTL semantics).
        self._notional += fill_event.notional

    def trip_kill(self) -> None:
        """External (cmd_kill_trigger-equivalent) manual kill."""
        self._trip_kill()

    def reset_kill(self) -> None:
        """cmd_kill_reset-equivalent."""
        self._kill_tripped = False

    @property
    def kill_active(self) -> bool:
        return self._kill_tripped

    @property
    def net_position(self) -> int:
        return self._long_qty - self._short_qty

    # ---------------------------------------------------------------------
    # Decision
    # ---------------------------------------------------------------------

    def decide(self, order: Order) -> Decision:
        """Evaluate one order. Mutates state (token bucket, counters).
        Does NOT mutate position book — that happens on Fill, not Order.
        """
        self.total_orders += 1

        # Heartbeats / cancels: don't count against limits, always pass.
        if order.order_type in (OrderType.HEARTBEAT,):
            self.total_passed += 1
            return Decision(
                passed=True,
                reason=RejectReason.OK,
                tokens_remaining=self._tokens,
                current_position=self.net_position,
                current_notional=self._notional,
            )

        # ----- Kill switch (highest precedence) -----
        if self.cfg.kill_armed and self._kill_tripped:
            self.total_rejected_kill += 1
            return self._reject(RejectReason.KILL_SWITCH)
        if self.cfg.kill_force_trigger:
            self._trip_kill()
            self.total_rejected_kill += 1
            return self._reject(RejectReason.KILL_SWITCH)

        # ----- Rate limiter -----
        if self.cfg.rate_enabled:
            tokens_required = (
                0 if order.order_type == OrderType.HEARTBEAT else 1
            )
            if self._tokens < tokens_required:
                self.total_rejected_rate += 1
                return self._reject(RejectReason.RATE_LIMITED)
            self._tokens -= tokens_required

        # ----- Position-family checks -----
        if self.cfg.pos_enabled:
            # Per-order max quantity
            if order.quantity > self.cfg.pos_max_order_qty:
                self.total_rejected_position += 1
                return self._reject(RejectReason.ORDER_SIZE)

            # Projected aggregated notional
            projected_notional = self._notional + order.notional
            if projected_notional > self.cfg.pos_max_notional:
                self.total_rejected_position += 1
                return self._reject(RejectReason.NOTIONAL_LIMIT)

            # Projected aggregated qty (audit-fix: signed unwind)
            if order.side == OrderSide.BUY:
                unwind = min(self._short_qty, order.quantity)
                projected_long = self._long_qty + (order.quantity - unwind)
                if projected_long > self.cfg.pos_max_long:
                    self.total_rejected_position += 1
                    return self._reject(RejectReason.POSITION_LIMIT)
            else:
                unwind = min(self._long_qty, order.quantity)
                projected_short = self._short_qty + (order.quantity - unwind)
                if projected_short > self.cfg.pos_max_short:
                    self.total_rejected_position += 1
                    return self._reject(RejectReason.POSITION_LIMIT)

        # ----- Fat-finger band -----
        if self.cfg.ff_enabled and self.cfg.ff_ref_price > 0:
            ref = self.cfg.ff_ref_price
            band = (ref * self.cfg.ff_band_bps) // 10_000
            lo = ref - band
            hi = ref + band
            if order.price < lo or order.price > hi:
                self.total_rejected_ff += 1
                return self._reject(RejectReason.FAT_FINGER)

        # ----- Allowlist -----
        if self.cfg.allowlist_enabled and self.cfg.allowlist:
            if order.symbol_id not in self.cfg.allowlist:
                self.total_rejected_allowlist += 1
                return self._reject(RejectReason.ALLOWLIST_BLOCK)

        # ----- Pass -----
        self.total_passed += 1
        return Decision(
            passed=True,
            reason=RejectReason.OK,
            tokens_remaining=self._tokens,
            current_position=self.net_position,
            current_notional=self._notional,
        )

    # ---------------------------------------------------------------------
    # Internals
    # ---------------------------------------------------------------------

    def _reject(self, reason: RejectReason) -> Decision:
        return Decision(
            passed=False,
            reason=reason,
            tokens_remaining=self._tokens,
            current_position=self.net_position,
            current_notional=self._notional,
        )

    def _trip_kill(self) -> None:
        if not self._kill_tripped:
            self._kill_tripped = True
            self._kill_trip_count += 1


# -------------------------------------------------------------------------
# Convenience helper
# -------------------------------------------------------------------------

def evaluate_stream(
    cfg: GateConfig,
    orders: Iterable[Order],
    fills: Optional[List[Tuple[int, Fill]]] = None,
    pnl_updates: Optional[List[Tuple[int, int]]] = None,
) -> List[Decision]:
    """Run a stream of orders through a fresh gate instance.

    Args:
        cfg: gate configuration.
        orders: iterable of Orders.
        fills: optional list of (after_order_idx, Fill) — fills applied
               after the order at index N is decided.
        pnl_updates: optional list of (after_order_idx, signed_pnl).

    Returns:
        list of Decisions, one per order in input order.
    """
    gate = GoldenRiskGate(cfg)
    fills = fills or []
    pnl_updates = pnl_updates or []
    f_iter = iter(fills)
    p_iter = iter(pnl_updates)
    next_fill = next(f_iter, None)
    next_pnl = next(p_iter, None)
    decisions: List[Decision] = []

    for idx, order in enumerate(orders):
        gate.tick()
        d = gate.decide(order)
        decisions.append(d)

        # Apply any fill or pnl scheduled after this index.
        while next_fill is not None and next_fill[0] == idx:
            gate.fill(next_fill[1])
            next_fill = next(f_iter, None)
        while next_pnl is not None and next_pnl[0] == idx:
            gate.update_pnl(next_pnl[1])
            next_pnl = next(p_iter, None)

    return decisions
