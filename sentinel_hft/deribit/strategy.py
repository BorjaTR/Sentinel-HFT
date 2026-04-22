"""Spread-based market-maker strategy used by the demo.

The strategy is deliberately thin -- the demo is about demonstrating
the full tick-to-audit path, not about alpha. On every tick the
strategy decides whether to emit a *paired* quote intent (a buy at
bid_skew and a sell at ask_skew) for the updated instrument. It
does so when:

1. We don't already have an outstanding quote pair within the tick
   window (``repaper_ns``), or
2. The mid has moved by more than ``repaper_tick_mult`` instrument
   ticks since the last quote pair was posted.

The strategy carries no PnL logic -- it just emits intents. The risk
gate is the thing that decides whether the intent can be sent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional

from .book import TopOfBook
from .instruments import Instrument, InstrumentKind


class Side(IntEnum):
    BUY = 1
    SELL = 2


class IntentAction(IntEnum):
    """What the strategy wants the risk gate to do with this intent."""

    NEW = 1       # new order (charge rate + position + notional)
    CANCEL = 2    # cancel of a prior order (pass-through, refund notional)


@dataclass
class QuoteIntent:
    """One side of a paired quote (or a cancel) the strategy wants sent."""

    order_id: int
    symbol_id: int
    side: Side
    price: float
    quantity: float
    notional: float
    generated_ts_ns: int
    action: IntentAction = IntentAction.NEW
    replaces_order_id: int = 0  # non-zero on a CANCEL

    @property
    def side_name(self) -> str:
        return "buy" if self.side == Side.BUY else "sell"


@dataclass
class _OutstandingQuote:
    """Record of a live order the strategy still has on the book."""

    order_id: int
    side: Side
    quantity: float
    notional: float


@dataclass
class _SymbolState:
    """Per-symbol strategy state."""

    last_mid: float = 0.0
    last_paper_ns: int = 0
    order_counter: int = 0
    outstanding: List[_OutstandingQuote] = field(default_factory=list)


class SpreadMMStrategy:
    """Posts bid/ask pairs around mid on meaningful moves.

    Parameters
    ----------
    skew_mult
        Half-width of the posted quote relative to the instrument
        ``tick_size``. For perps this is ~2 ticks; for options we
        widen to give the strategy some buffer against mis-pricing.
    base_quantity
        Order size in the instrument's lot units.
    repaper_ns
        Minimum elapsed time between re-papering a symbol, even if
        the mid has moved. Prevents the strategy from hammering the
        risk gate on every tick during a burst.
    repaper_tick_mult
        Re-paper immediately if mid has moved by more than this many
        instrument ticks since the last quote.
    """

    def __init__(
        self,
        skew_mult_perp: float = 2.0,
        skew_mult_option: float = 4.0,
        base_quantity_perp: float = 1.0,
        base_quantity_option: float = 0.1,
        repaper_ns: int = 2_000_000,      # 2ms between repapers
        repaper_tick_mult: float = 3.0,
    ):
        self._state: Dict[int, _SymbolState] = {}
        self._skew_perp = skew_mult_perp
        self._skew_opt = skew_mult_option
        self._qty_perp = base_quantity_perp
        self._qty_opt = base_quantity_option
        self._repaper_ns = repaper_ns
        self._repaper_mult = repaper_tick_mult
        self._global_order_id = 1_000_000  # offset to avoid colliding with seq

    def on_tick(self, book: TopOfBook, now_ns: int
                ) -> List[QuoteIntent]:
        """Return a list of quote intents in response to ``book``.

        Empty list == strategy declines to quote. When re-papering,
        the previous pair is cancelled before the new pair is posted
        so the risk gate sees the correct net exposure.
        """
        ins = book.instrument
        mid = book.mid
        if mid <= 0:
            return []

        st = self._state.setdefault(ins.symbol_id, _SymbolState())

        if st.last_paper_ns:
            if (now_ns - st.last_paper_ns) < self._repaper_ns:
                # Only re-paper inside the min window if mid moved a lot.
                if st.last_mid > 0:
                    move_ticks = abs(mid - st.last_mid) / ins.tick_size
                    if move_ticks < self._repaper_mult:
                        return []
                else:
                    return []

        if ins.kind == InstrumentKind.OPTION:
            skew_mult = self._skew_opt
            qty = self._qty_opt
        else:
            skew_mult = self._skew_perp
            qty = self._qty_perp

        half = ins.tick_size * skew_mult
        bid_px = mid - half
        ask_px = mid + half
        if bid_px <= 0:
            return []

        notional_per_lot = ins.lot_size
        # For perps/futures the displayed notional is USD; for options
        # we compute premium * lot_size (coin-denominated).
        notional_bid = bid_px * qty * notional_per_lot
        notional_ask = ask_px * qty * notional_per_lot

        intents: List[QuoteIntent] = []

        # First emit a cancel for any outstanding quotes on this symbol.
        # Cancels are free from a rate/position perspective (they
        # release exposure rather than acquire it).
        for out in st.outstanding:
            intents.append(QuoteIntent(
                order_id=out.order_id,
                symbol_id=ins.symbol_id,
                side=out.side,
                price=0.0,
                quantity=out.quantity,
                notional=out.notional,
                generated_ts_ns=now_ns,
                action=IntentAction.CANCEL,
                replaces_order_id=out.order_id,
            ))
        st.outstanding.clear()

        self._global_order_id += 1
        oid_buy = self._global_order_id
        self._global_order_id += 1
        oid_sell = self._global_order_id

        intents.extend([
            QuoteIntent(
                order_id=oid_buy,
                symbol_id=ins.symbol_id,
                side=Side.BUY,
                price=bid_px,
                quantity=qty,
                notional=notional_bid,
                generated_ts_ns=now_ns,
            ),
            QuoteIntent(
                order_id=oid_sell,
                symbol_id=ins.symbol_id,
                side=Side.SELL,
                price=ask_px,
                quantity=qty,
                notional=notional_ask,
                generated_ts_ns=now_ns,
            ),
        ])
        st.last_paper_ns = now_ns
        st.last_mid = mid
        st.order_counter += 1
        # Outstanding is updated by confirm_new() once the gate has
        # spoken -- a rate-limited NEW must not appear on the book,
        # otherwise the next cancel would try to release exposure
        # that never landed.
        return intents

    def confirm_new(self, intent: QuoteIntent) -> None:
        """Strategy callback: the gate accepted a NEW order.

        The pipeline calls this only when the risk gate returns
        passed=True so the strategy's notion of "what's on the book"
        stays in sync with the gate's position tracker.
        """
        st = self._state.get(intent.symbol_id)
        if st is None:
            return
        st.outstanding.append(_OutstandingQuote(
            order_id=intent.order_id,
            side=intent.side,
            quantity=intent.quantity,
            notional=intent.notional,
        ))


__all__ = ["Side", "IntentAction", "QuoteIntent", "SpreadMMStrategy"]
