"""
CFTC Reg AT self-trade guard.

Maintains a small register of live resting orders per ``trader_id`` and
rejects any incoming intent that would cross against them.  The RTL
stub in ``rtl/self_trade_guard.sv`` implements the same check at line
rate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass
class _RestingOrder:
    order_id: int
    symbol_id: int
    side: int              # 1 = buy, 2 = sell (matches risk_pkg.sv)
    price: float
    quantity: float


@dataclass
class SelfTradeGuard:
    """Reject intents that would self-cross against the same trader."""

    _book: Dict[int, List[_RestingOrder]] = field(default_factory=dict)
    _rejects: int = 0
    _checked: int = 0

    # ---- book maintenance -------------------------------------------

    def add_resting(
        self,
        trader_id: int,
        order_id: int,
        symbol_id: int,
        side: int,
        price: float,
        quantity: float,
    ) -> None:
        self._book.setdefault(trader_id, []).append(
            _RestingOrder(order_id, symbol_id, side, price, quantity)
        )

    def cancel(self, trader_id: int, order_id: int) -> None:
        lst = self._book.get(trader_id)
        if not lst:
            return
        self._book[trader_id] = [o for o in lst if o.order_id != order_id]

    # ---- the actual check -------------------------------------------

    def check(
        self,
        trader_id: int,
        symbol_id: int,
        side: int,
        price: float,
        quantity: float,
    ) -> bool:
        """
        Return True if accepting this intent would self-cross against
        one of the trader's own resting orders on the opposite side.

        Crossing rule (matches CFTC Reg AT commentary):

            incoming BUY  crosses resting SELL if buy_px  >= sell_px
            incoming SELL crosses resting BUY  if sell_px <= buy_px
        """
        self._checked += 1
        own = self._book.get(trader_id) or []
        for r in own:
            if r.symbol_id != symbol_id:
                continue
            if r.side == side:
                # same side -> not a self-cross, only stacks depth
                continue
            crosses = (
                (side == 1 and r.side == 2 and price >= r.price)
                or (side == 2 and r.side == 1 and price <= r.price)
            )
            if crosses:
                self._rejects += 1
                return True
        return False

    # ---- stats -------------------------------------------------------

    def rejects(self) -> int:
        return self._rejects

    def checked(self) -> int:
        return self._checked

    def snapshot(self) -> Dict[str, object]:
        return {
            "checked": self._checked,
            "rejected": self._rejects,
            "reject_rate": round(
                self._rejects / self._checked, 6
            ) if self._checked else 0.0,
            "traders_tracked": len(self._book),
            "resting_orders": sum(len(v) for v in self._book.values()),
        }
