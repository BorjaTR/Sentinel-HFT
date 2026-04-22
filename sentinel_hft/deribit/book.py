"""Minimal top-of-book state keyed by symbol.

The demo strategy only needs best-bid/best-offer per instrument, so
this module deliberately stops short of a full order book. Anything
more would be a strategy concern, not a risk-gate/audit concern.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from .fixture import TickEvent, TickKind
from .instruments import Instrument


@dataclass
class TopOfBook:
    """Best-bid / best-offer snapshot for one instrument."""

    instrument: Instrument
    bid: float = 0.0
    ask: float = 0.0
    bid_size: float = 0.0
    ask_size: float = 0.0
    last_trade: float = 0.0
    last_trade_ts_ns: int = 0
    updated_at_ns: int = 0

    @property
    def mid(self) -> float:
        if self.bid <= 0 or self.ask <= 0:
            return 0.0
        return 0.5 * (self.bid + self.ask)

    @property
    def spread(self) -> float:
        if self.bid <= 0 or self.ask <= 0:
            return 0.0
        return self.ask - self.bid


class BookState:
    """Holds a :class:`TopOfBook` per instrument."""

    def __init__(self):
        self._books: Dict[int, TopOfBook] = {}

    def apply(self, ev: TickEvent) -> TopOfBook:
        """Apply a tick event and return the updated top-of-book."""
        book = self._books.get(ev.instrument.symbol_id)
        if book is None:
            book = TopOfBook(instrument=ev.instrument)
            self._books[ev.instrument.symbol_id] = book

        # Both QUOTE and TRADE carry a current best-bid/offer snapshot.
        book.bid = ev.bid_price
        book.ask = ev.ask_price
        book.bid_size = ev.bid_size
        book.ask_size = ev.ask_size
        book.updated_at_ns = ev.host_ts_ns

        if ev.kind == TickKind.TRADE:
            book.last_trade = ev.trade_price
            book.last_trade_ts_ns = ev.host_ts_ns

        return book

    def get(self, symbol_id: int) -> Optional[TopOfBook]:
        return self._books.get(symbol_id)

    def snapshot(self) -> Dict[int, TopOfBook]:
        return dict(self._books)


__all__ = ["TopOfBook", "BookState"]
