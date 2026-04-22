"""Deribit instrument universe used by the demo.

A prop desk running Deribit typically concentrates risk across three
product classes: perpetual inverse swaps, dated futures, and European
cash-settled options. This module exposes a small but realistically
shaped subset of that universe -- enough to exercise the pipeline's
per-symbol state without making the demo noisy.

The goal is *shape*, not coverage. The pipeline assigns a stable
``symbol_id`` to each instrument so the trace and audit record
streams can be decoded without carrying the full string name.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Dict, List, Tuple


class InstrumentKind(enum.IntEnum):
    """High-level instrument category."""

    PERPETUAL = 1
    FUTURE = 2
    OPTION = 3


class OptionType(enum.IntEnum):
    """Option right; NONE for non-option instruments."""

    NONE = 0
    CALL = 1
    PUT = 2


@dataclass(frozen=True)
class Instrument:
    """One tradeable Deribit instrument.

    * ``symbol_id``  -- stable integer handle used in trace + audit
                        records. Must fit in a u16 to match the RTL
                        risk gate's symbol field.
    * ``symbol``     -- human-readable Deribit symbol.
    * ``underlying`` -- BTC or ETH (keeps things simple for the demo).
    * ``kind``       -- perp/future/option.
    * ``tick_size``  -- minimum price increment (USD for linear,
                        coin for inverse; here we use USD-quoted
                        notional throughout).
    * ``lot_size``   -- contract size in USD (perp/future) or coins
                        per contract (options). The field is labeled
                        descriptively rather than by venue convention
                        so the demo stays readable.
    * ``base_price`` -- a seed mid used by the fixture generator so
                        each instrument moves around a plausible level.
    * ``quote_rate`` -- mean quote-update rate per second (used to
                        drive the fixture's Poisson arrivals).
    """

    symbol_id: int
    symbol: str
    underlying: str
    kind: InstrumentKind
    tick_size: float
    lot_size: float
    base_price: float
    quote_rate: float
    option_type: OptionType = OptionType.NONE
    strike: float = 0.0
    expiry_days: int = 0


# Universe -------------------------------------------------------------
#
# We keep this tight: two perps and a handful of BTC/ETH options so
# the demo surfaces both dense-quote and sparse-quote behaviour.
# Quote rates are approximate 2026 baselines observed on Deribit's
# public feed and scaled to keep the demo fixture manageable.

DERIBIT_UNIVERSE: Tuple[Instrument, ...] = (
    Instrument(
        symbol_id=1,
        symbol="BTC-PERPETUAL",
        underlying="BTC",
        kind=InstrumentKind.PERPETUAL,
        tick_size=0.5,
        lot_size=10.0,           # $10 per contract (inverse)
        base_price=68_000.0,
        quote_rate=2_500.0,       # ~2.5k quote updates/sec
    ),
    Instrument(
        symbol_id=2,
        symbol="ETH-PERPETUAL",
        underlying="ETH",
        kind=InstrumentKind.PERPETUAL,
        tick_size=0.05,
        lot_size=1.0,
        base_price=3_400.0,
        quote_rate=1_800.0,
    ),
    Instrument(
        symbol_id=3,
        symbol="BTC-26DEC26-80000-C",
        underlying="BTC",
        kind=InstrumentKind.OPTION,
        option_type=OptionType.CALL,
        tick_size=0.0005,          # coin-denominated
        lot_size=0.1,              # 0.1 BTC contract size
        base_price=0.082,          # ~8.2% of BTC at $80k strike
        quote_rate=60.0,
        strike=80_000.0,
        expiry_days=250,
    ),
    Instrument(
        symbol_id=4,
        symbol="BTC-26DEC26-60000-P",
        underlying="BTC",
        kind=InstrumentKind.OPTION,
        option_type=OptionType.PUT,
        tick_size=0.0005,
        lot_size=0.1,
        base_price=0.031,
        quote_rate=45.0,
        strike=60_000.0,
        expiry_days=250,
    ),
    Instrument(
        symbol_id=5,
        symbol="ETH-26JUN26-4000-C",
        underlying="ETH",
        kind=InstrumentKind.OPTION,
        option_type=OptionType.CALL,
        tick_size=0.0005,
        lot_size=1.0,
        base_price=0.058,
        quote_rate=25.0,
        strike=4_000.0,
        expiry_days=65,
    ),
    Instrument(
        symbol_id=6,
        symbol="ETH-26JUN26-3000-P",
        underlying="ETH",
        kind=InstrumentKind.OPTION,
        option_type=OptionType.PUT,
        tick_size=0.0005,
        lot_size=1.0,
        base_price=0.041,
        quote_rate=20.0,
        strike=3_000.0,
        expiry_days=65,
    ),
)


# Default universe used when the CLI / tests don't specify anything
# else. Kept as a separate alias so callers can pass a shorter list
# into the pipeline if they want a narrower demo.
DEFAULT_UNIVERSE: Tuple[Instrument, ...] = DERIBIT_UNIVERSE


def by_id(universe: Tuple[Instrument, ...] = DERIBIT_UNIVERSE
          ) -> Dict[int, Instrument]:
    """Index a universe by ``symbol_id``."""
    return {ins.symbol_id: ins for ins in universe}


def by_symbol(universe: Tuple[Instrument, ...] = DERIBIT_UNIVERSE
              ) -> Dict[str, Instrument]:
    """Index a universe by human symbol."""
    return {ins.symbol: ins for ins in universe}


__all__ = [
    "Instrument",
    "InstrumentKind",
    "OptionType",
    "DERIBIT_UNIVERSE",
    "DEFAULT_UNIVERSE",
    "by_id",
    "by_symbol",
]
