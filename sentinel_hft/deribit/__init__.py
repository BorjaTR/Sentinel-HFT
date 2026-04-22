"""Deribit LD4 options/perps tick-to-trade demo pipeline.

This package models an end-to-end Deribit market-making path that
would run on an FPGA colocated at Equinix LD4. The demo is Python-
only and deterministic, but every component mirrors the shape of
what the hardware pipeline does:

* ``instruments`` -- Deribit instrument universe (perps + options).
* ``fixture``     -- seeded tick fixture (quote updates + trades).
* ``book``        -- per-instrument top-of-book state.
* ``strategy``    -- a minimal spread-based market-maker that emits
                      order intents on mid-price moves.
* ``risk``        -- Python reference of the risk gate (rate bucket,
                      position tracker, kill switch) matching
                      ``rtl/risk_*.sv`` semantics.
* ``pipeline``    -- runs the full loop and writes the four demo
                      artifacts: v1.2 trace, audit log, DORA bundle,
                      markdown summary.

Nothing in here talks to a live Deribit endpoint. The point is to
produce a realistic, reproducible artifact set that an interviewer
can diff against a reference run and that a regulator could verify
without network access.
"""

from .instruments import (
    Instrument,
    InstrumentKind,
    OptionType,
    DERIBIT_UNIVERSE,
    DEFAULT_UNIVERSE,
)
from .fixture import (
    TickEvent,
    TickKind,
    DeribitFixture,
    generate_ticks,
)
from .book import TopOfBook, BookState
from .strategy import IntentAction, QuoteIntent, Side, SpreadMMStrategy
from .risk import (
    TokenBucket,
    PositionTracker,
    KillSwitch,
    RiskGate,
    RiskGateConfig,
)
from .pipeline import (
    DeribitDemo,
    DemoConfig,
    DemoArtifacts,
    run_demo,
)

__all__ = [
    "Instrument",
    "InstrumentKind",
    "OptionType",
    "DERIBIT_UNIVERSE",
    "DEFAULT_UNIVERSE",
    "TickEvent",
    "TickKind",
    "DeribitFixture",
    "generate_ticks",
    "TopOfBook",
    "BookState",
    "IntentAction",
    "QuoteIntent",
    "Side",
    "SpreadMMStrategy",
    "TokenBucket",
    "PositionTracker",
    "KillSwitch",
    "RiskGate",
    "RiskGateConfig",
    "DeribitDemo",
    "DemoConfig",
    "DemoArtifacts",
    "run_demo",
]
