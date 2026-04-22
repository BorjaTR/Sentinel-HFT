"""Hyperliquid tick ingestion + use-case runners.

This package is the real-life ingestion adapter layered on top of the
same book -> strategy -> risk -> audit pipeline used by the Deribit
LD4 demo. Hyperliquid is a public perps DEX with a documented
WebSocket feed; in this demo we replay a deterministic, seeded
fixture that has the same *shape* as that feed (quote + trade
snapshots, a trader hash carried through to the risk gate) without
hitting the network.

Four concrete use cases consume this stream (see
``sentinel_hft.usecases``):

* ``toxic_flow``     -- adverse-selection scoring + pre-gate rejection
                        of quote intents exposed to toxic takers.
* ``kill_drill``     -- controlled volatility injection and kill-switch
                        verification with a tamper-evident transcript.
* ``latency``        -- wire-to-wire latency attribution with per-stage
                        histogram + SLO violation count.
* ``daily_evidence`` -- combined DORA evidence bundle spanning multiple
                        sessions of the same trading day.

The fixture is deterministic (seeded RNG, fixed base_ts) so the four
use-case runners produce byte-identical artifacts across machines.
That is what lets the demo be regression-tested in CI.

Import policy
-------------

The live WebSocket collector lives in
:mod:`sentinel_hft.hyperliquid.collector` and lazy-imports the
optional ``websockets`` dependency. This package does not import it
eagerly, so `import sentinel_hft.hyperliquid` works in CI with only
stdlib installed.
"""

from .instruments import (
    HyperliquidInstrument,
    HL_UNIVERSE,
    HL_DEFAULT_UNIVERSE,
    hl_by_id,
    hl_by_symbol,
)
from .fixture import (
    HLTickEvent,
    HyperliquidFixture,
    TakerProfile,
    VolSpike,
    generate_hl_ticks,
)
from .scorer import (
    TakerOutcome,
    TakerScorecard,
    ToxicFlowScorer,
    ToxicFlowGuard,
)
from .reader import (
    HL_TICK_HEADER_SIZE,
    HL_TICK_RECORD_SIZE,
    HLTickFileHeader,
    pack_event,
    unpack_event,
    write_events,
    read_events,
    count_events,
)
from .runner import (
    HLRunConfig,
    HLRunArtifacts,
    HyperliquidRunner,
    run_hl,
)


__all__ = [
    # instruments
    "HyperliquidInstrument",
    "HL_UNIVERSE",
    "HL_DEFAULT_UNIVERSE",
    "hl_by_id",
    "hl_by_symbol",
    # fixture
    "HLTickEvent",
    "HyperliquidFixture",
    "TakerProfile",
    "VolSpike",
    "generate_hl_ticks",
    # scorer
    "TakerOutcome",
    "TakerScorecard",
    "ToxicFlowScorer",
    "ToxicFlowGuard",
    # reader
    "HL_TICK_HEADER_SIZE",
    "HL_TICK_RECORD_SIZE",
    "HLTickFileHeader",
    "pack_event",
    "unpack_event",
    "write_events",
    "read_events",
    "count_events",
    # runner
    "HLRunConfig",
    "HLRunArtifacts",
    "HyperliquidRunner",
    "run_hl",
]
