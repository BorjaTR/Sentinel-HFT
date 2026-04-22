"""Hyperliquid demo use-cases.

Four concrete end-to-end demonstrations layered on top of the HL
ingestion adapter (``sentinel_hft.hyperliquid``) and the shared
book -> strategy -> risk -> audit pipeline.

Each use-case is a **single-file runner** that:

1. Configures an :class:`~sentinel_hft.hyperliquid.HLRunConfig` for
   its specific scenario (toxic-heavy population, forced vol spike,
   clean-baseline run, etc.).
2. Drives :class:`~sentinel_hft.hyperliquid.HyperliquidRunner`
   through a fixture stream.
3. Post-processes the runner's artifacts into a use-case-specific
   JSON + Markdown report.
4. Emits a self-contained HTML page (inline SVG charts, no external
   JS) ready to be opened in a browser.

The top-level :mod:`sentinel_hft.usecases.dashboard` assembles a
cover page linking to whichever use-case outputs exist on disk.

The HTML output is intentionally minimal -- a Keyrock interviewer
should be able to open a single file, see the story, and drill into
the raw artifacts without needing a local web server.
"""

from .toxic_flow import (
    ToxicFlowConfig,
    ToxicFlowReport,
    run_toxic_flow,
)
from .kill_drill import (
    KillDrillConfig,
    KillDrillReport,
    run_kill_drill,
)
from .latency import (
    LatencyConfig,
    LatencyReport,
    run_latency,
)
from .daily_evidence import (
    DailyEvidenceConfig,
    DailyEvidenceReport,
    run_daily_evidence,
)
from .dashboard import build_dashboard


__all__ = [
    "ToxicFlowConfig",
    "ToxicFlowReport",
    "run_toxic_flow",
    "KillDrillConfig",
    "KillDrillReport",
    "run_kill_drill",
    "LatencyConfig",
    "LatencyReport",
    "run_latency",
    "DailyEvidenceConfig",
    "DailyEvidenceReport",
    "run_daily_evidence",
    "build_dashboard",
]
