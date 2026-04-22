"""
MiFID II RTS 6 - order-to-trade ratio counter.

Observes every order the engine produces and every executed trade and
maintains a running ratio.  When the ratio exceeds
``max_ratio_per_symbol`` the counter exposes a ``would_reject`` flag so
an upstream gate can act on it; this host implementation itself never
blocks (observation-only).

The matching synthesizable stub is ``rtl/otr_counter.sv``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class OTRCounter:
    """Per-symbol order-to-trade ratio counter."""

    #: threshold above which the counter raises ``would_reject``.
    #: Keyrock's live config uses 100:1 per symbol on-venue.
    max_ratio_per_symbol: float = 100.0

    _orders: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    _trades: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    _rejects_would_trip: int = 0

    # ----- observers --------------------------------------------------

    def on_order(self, symbol_id: int) -> None:
        """Record one new order (NEW + MODIFY are both in the numerator)."""
        self._orders[symbol_id] += 1

    def on_trade(self, symbol_id: int) -> None:
        """Record one executed trade (the denominator)."""
        self._trades[symbol_id] += 1

    def observe(self, symbol_id: int, filled: bool) -> bool:
        """
        Convenience: record a single order event and return True if the
        resulting ratio *would* trip the per-symbol limit (caller can
        decide to reject; we never do).
        """
        self.on_order(symbol_id)
        if filled:
            self.on_trade(symbol_id)
        ratio = self.ratio(symbol_id)
        if ratio > self.max_ratio_per_symbol:
            self._rejects_would_trip += 1
            return True
        return False

    # ----- queries ----------------------------------------------------

    def ratio(self, symbol_id: int) -> float:
        """O / max(T, 1) for one symbol.  Returns 0.0 if untouched."""
        o = self._orders.get(symbol_id, 0)
        t = self._trades.get(symbol_id, 0)
        if o == 0:
            return 0.0
        return o / max(t, 1)

    def per_symbol_ratios(self) -> Dict[int, float]:
        return {sid: self.ratio(sid) for sid in self._orders}

    def total_orders(self) -> int:
        return sum(self._orders.values())

    def total_trades(self) -> int:
        return sum(self._trades.values())

    def global_ratio(self) -> float:
        o = self.total_orders()
        t = self.total_trades()
        if o == 0:
            return 0.0
        return o / max(t, 1)

    def would_trip(self) -> int:
        return self._rejects_would_trip

    def max_symbol_ratio(self) -> float:
        """Largest per-symbol ratio we've seen so far."""
        ratios = self.per_symbol_ratios()
        return max(ratios.values()) if ratios else 0.0

    def snapshot(self) -> Dict[str, object]:
        """JSON-friendly snapshot for the demo API."""
        return {
            "max_ratio_per_symbol": self.max_ratio_per_symbol,
            "total_orders": self.total_orders(),
            "total_trades": self.total_trades(),
            "global_ratio": round(self.global_ratio(), 4),
            "worst_symbol_ratio": round(self.max_symbol_ratio(), 4),
            "would_trip": self.would_trip(),
        }
