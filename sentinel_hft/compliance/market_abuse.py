"""
MAR (Market Abuse Regulation) Art. 12 spoofing / layering detector.

This is a *pattern-alert* module, not a pre-gate: it ingests every
intent the strategy emits (NEW + CANCEL) and raises an alert when it
sees a pattern matching the Art. 12 definition of a spoofing/layering
abuse:

    *N* same-side NEW orders on one instrument that are cancelled
    within *T* ms without any fill on the same side over a rolling
    window.

Parameters default to the most-cited ESMA guidance numbers (5 orders
/ 1 second) but are configurable per deployment.  This host
implementation logs the alert; the RTL counterpart is out of scope
for v1.0 (spoofing-alert windows are more naturally pushed to the
host tier anyway).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple


@dataclass
class MARAlert:
    """One spoofing/layering alert."""

    trader_id: int
    symbol_id: int
    side: int
    n_orders: int
    window_ns: int
    first_order_ns: int
    last_cancel_ns: int

    def as_dict(self) -> Dict[str, object]:
        return {
            "trader_id": self.trader_id,
            "symbol_id": self.symbol_id,
            "side": self.side,
            "n_orders": self.n_orders,
            "window_ns": self.window_ns,
            "first_order_ns": self.first_order_ns,
            "last_cancel_ns": self.last_cancel_ns,
        }


@dataclass
class _OrderEvent:
    ts_ns: int
    order_id: int
    filled: bool = False
    cancelled_ns: Optional[int] = None


@dataclass
class SpoofLayerDetector:
    """Flag ``min_cancelled`` same-side NEW-then-CANCEL events within
    ``window_ns`` that produced zero fills on that side.

    Defaults are tuned to fire on abusive layering while tolerating a
    legitimate MM's re-papering cadence.  A real MM re-papers every
    few ms but keeps total orders-per-second per symbol per side in
    the low dozens; a layering attacker typically places 50-200
    same-side cancels in a burst.  Tune via ``min_cancelled`` and
    ``window_ns``.
    """

    #: Number of consecutive same-side cancelled NEWs to trip the alert.
    min_cancelled: int = 30

    #: Time window in nanoseconds (default 200 ms).
    window_ns: int = 200_000_000

    #: Orders cancelled in under this many ns are ignored as MM
    #: re-papering noise rather than layering.
    min_time_on_book_ns: int = 5_000_000   # 5 ms

    #: Max orders retained per (trader, symbol, side) key (memory cap).
    max_history: int = 128

    # (trader_id, symbol_id, side) -> deque of _OrderEvent
    _hist: Dict[Tuple[int, int, int], Deque[_OrderEvent]] = field(
        default_factory=dict
    )
    _alerts: List[MARAlert] = field(default_factory=list)
    _orders_seen: int = 0
    _cancels_seen: int = 0
    _fills_seen: int = 0

    # ---- observers --------------------------------------------------

    def _bucket(self, trader_id: int, symbol_id: int, side: int) -> Deque[_OrderEvent]:
        key = (trader_id, symbol_id, side)
        dq = self._hist.get(key)
        if dq is None:
            dq = deque(maxlen=self.max_history)
            self._hist[key] = dq
        return dq

    def on_new(
        self,
        *,
        trader_id: int,
        symbol_id: int,
        side: int,
        order_id: int,
        ts_ns: int,
    ) -> None:
        """Record a NEW order event."""
        self._orders_seen += 1
        self._bucket(trader_id, symbol_id, side).append(
            _OrderEvent(ts_ns=ts_ns, order_id=order_id)
        )

    def on_cancel(
        self,
        *,
        trader_id: int,
        symbol_id: int,
        side: int,
        order_id: int,
        ts_ns: int,
    ) -> Optional[MARAlert]:
        """Record a CANCEL; raise an alert if the pattern trips."""
        self._cancels_seen += 1
        dq = self._bucket(trader_id, symbol_id, side)
        # Mark the matching NEW as cancelled.
        for ev in reversed(dq):
            if ev.order_id == order_id and ev.cancelled_ns is None:
                ev.cancelled_ns = ts_ns
                break
        return self._maybe_fire(trader_id, symbol_id, side, ts_ns)

    def on_fill(
        self,
        *,
        trader_id: int,
        symbol_id: int,
        side: int,
        order_id: int,
    ) -> None:
        """A resting order got filled - suppresses pending alerts."""
        self._fills_seen += 1
        dq = self._bucket(trader_id, symbol_id, side)
        for ev in dq:
            if ev.order_id == order_id:
                ev.filled = True
                break

    # ---- alert logic ------------------------------------------------

    def _maybe_fire(
        self, trader_id: int, symbol_id: int, side: int, now_ns: int,
    ) -> Optional[MARAlert]:
        dq = self._hist.get((trader_id, symbol_id, side)) or deque()
        # Collect consecutive-cancelled-no-fill events inside the window.
        # Ignore micro-life cancels (MM re-papering): require the order
        # sat on the book for at least ``min_time_on_book_ns``.
        window_start = now_ns - self.window_ns
        cancelled: List[_OrderEvent] = [
            e for e in dq
            if e.cancelled_ns is not None
            and e.cancelled_ns >= window_start
            and not e.filled
            and (e.cancelled_ns - e.ts_ns) >= self.min_time_on_book_ns
        ]
        if len(cancelled) < self.min_cancelled:
            return None
        alert = MARAlert(
            trader_id=trader_id,
            symbol_id=symbol_id,
            side=side,
            n_orders=len(cancelled),
            window_ns=self.window_ns,
            first_order_ns=cancelled[0].ts_ns,
            last_cancel_ns=now_ns,
        )
        self._alerts.append(alert)
        # Reset the bucket so the same cluster doesn't fire repeatedly.
        self._hist[(trader_id, symbol_id, side)] = deque(
            maxlen=self.max_history
        )
        return alert

    # ---- stats ------------------------------------------------------

    def alerts(self) -> List[MARAlert]:
        return list(self._alerts)

    def snapshot(self) -> Dict[str, object]:
        return {
            "min_cancelled": self.min_cancelled,
            "window_ns": self.window_ns,
            "orders_seen": self._orders_seen,
            "cancels_seen": self._cancels_seen,
            "fills_seen": self._fills_seen,
            "alerts": len(self._alerts),
            "last_alerts": [a.as_dict() for a in self._alerts[-5:]],
        }
