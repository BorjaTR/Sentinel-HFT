"""Hyperliquid perp universe used by the demo.

Hyperliquid is a public perpetuals DEX with native order-book
matching. The demo models the three perps where a market-maker
typically concentrates risk: BTC-USD, ETH-USD and SOL-USD. All three
are USD-collateralised linear perps, which simplifies the notional
bookkeeping (notional = price * qty in USD, no inverse quirks).

Every instrument carries:

* a stable ``symbol_id`` (must fit in a u16 to match the RTL risk
  gate's symbol field),
* a ``tick_size`` and ``lot_size`` matching Hyperliquid's published
  instrument metadata at the 2026-Q2 cutover,
* a ``base_price`` seed used by the fixture's mean-reverting random
  walk (rough mid-2026 levels; the fixture tolerates drift),
* a ``quote_rate`` approximating the mean quote-update rate observed
  on Hyperliquid's public book feed.

Wrapping :class:`~sentinel_hft.deribit.instruments.Instrument` rather
than redefining the dataclass means the book / strategy / risk
reference from the Deribit module work unchanged on HL ticks.
"""

from __future__ import annotations

from typing import Dict, Tuple

from ..deribit.instruments import Instrument, InstrumentKind, OptionType


# ---------------------------------------------------------------------
# Instrument subclass alias
# ---------------------------------------------------------------------


# Exposed for callers that want a stronger type name; it is the same
# dataclass as :class:`sentinel_hft.deribit.instruments.Instrument`
# with ``kind == PERPETUAL``. Defining it as an alias keeps the book /
# strategy / risk modules that type on ``Instrument`` compatible.
HyperliquidInstrument = Instrument


# ---------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------
#
# symbol_ids here intentionally start at 0x1001 so they never collide
# with Deribit's ids (which start at 1). A mixed-venue trace would
# therefore be unambiguous when decoded back.


HL_UNIVERSE: Tuple[HyperliquidInstrument, ...] = (
    HyperliquidInstrument(
        symbol_id=0x1001,
        symbol="BTC-USD-PERP",
        underlying="BTC",
        kind=InstrumentKind.PERPETUAL,
        tick_size=0.5,
        lot_size=1.0,             # lot == 1 BTC (linear)
        base_price=68_500.0,
        quote_rate=3_200.0,        # ~3.2k quote updates / sec
        option_type=OptionType.NONE,
    ),
    HyperliquidInstrument(
        symbol_id=0x1002,
        symbol="ETH-USD-PERP",
        underlying="ETH",
        kind=InstrumentKind.PERPETUAL,
        tick_size=0.05,
        lot_size=1.0,
        base_price=3_450.0,
        quote_rate=2_400.0,
        option_type=OptionType.NONE,
    ),
    HyperliquidInstrument(
        symbol_id=0x1003,
        symbol="SOL-USD-PERP",
        underlying="SOL",
        kind=InstrumentKind.PERPETUAL,
        tick_size=0.01,
        lot_size=1.0,
        base_price=148.0,
        quote_rate=1_600.0,
        option_type=OptionType.NONE,
    ),
)


HL_DEFAULT_UNIVERSE: Tuple[HyperliquidInstrument, ...] = HL_UNIVERSE


def hl_by_id(
    universe: Tuple[HyperliquidInstrument, ...] = HL_UNIVERSE,
) -> Dict[int, HyperliquidInstrument]:
    """Index an HL universe by ``symbol_id``."""
    return {ins.symbol_id: ins for ins in universe}


def hl_by_symbol(
    universe: Tuple[HyperliquidInstrument, ...] = HL_UNIVERSE,
) -> Dict[str, HyperliquidInstrument]:
    """Index an HL universe by human symbol."""
    return {ins.symbol: ins for ins in universe}


__all__ = [
    "HyperliquidInstrument",
    "HL_UNIVERSE",
    "HL_DEFAULT_UNIVERSE",
    "hl_by_id",
    "hl_by_symbol",
]
