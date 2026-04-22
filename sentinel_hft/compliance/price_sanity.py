"""
FINRA 15c3-5 fat-finger / price-sanity check.

Rejects any order whose price deviates from the latest observed trade
on the same instrument by more than ``max_deviation_bps`` (default
500 bps = 5 %).  The RTL stub ``rtl/price_sanity.sv`` implements the
same check in one cycle.

This module is **observational**: it records rejects but does not flip
the decision bit on the audit log.  The host stack in ``stack.py``
exposes the counter to the UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class FatFingerGuard:
    """Per-symbol price-deviation check."""

    #: Deviation window in basis points.  500 bps = +/-5%.
    max_deviation_bps: float = 500.0

    _last_px: Dict[int, float] = field(default_factory=dict)
    _rejects: int = 0
    _checked: int = 0
    _max_observed_bps: float = 0.0

    # ----- updates ---------------------------------------------------

    def on_trade(self, symbol_id: int, price: float) -> None:
        """Update the reference price after an executed trade."""
        if price > 0:
            self._last_px[symbol_id] = price

    def seed(self, symbol_id: int, price: float) -> None:
        """Seed the reference price without counting a trade."""
        self.on_trade(symbol_id, price)

    # ----- the check -------------------------------------------------

    def check(self, symbol_id: int, price: float) -> bool:
        """
        Return True if the order would trip the fat-finger guard.
        Unknown symbols (no reference price yet) always pass.
        """
        self._checked += 1
        last = self._last_px.get(symbol_id)
        if last is None or last <= 0 or price <= 0:
            return False
        dev_bps = abs(price - last) / last * 10_000.0
        if dev_bps > self._max_observed_bps:
            self._max_observed_bps = dev_bps
        if dev_bps > self.max_deviation_bps:
            self._rejects += 1
            return True
        return False

    # ----- stats -----------------------------------------------------

    def rejects(self) -> int:
        return self._rejects

    def checked(self) -> int:
        return self._checked

    def snapshot(self) -> Dict[str, object]:
        return {
            "max_deviation_bps": self.max_deviation_bps,
            "checked": self._checked,
            "rejected": self._rejects,
            "reject_rate": round(
                self._rejects / self._checked, 6
            ) if self._checked else 0.0,
            "worst_deviation_bps": round(self._max_observed_bps, 2),
            "symbols_tracked": len(self._last_px),
        }
