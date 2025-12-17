"""
Demo module for Sentinel-HFT.

Provides end-to-end demonstration of:
- Latency analysis
- Regression detection
- Pattern identification
- Fix generation
- Verification
"""

from .runner import DemoRunner
from .trace_generator import (
    TraceGenerator,
    TraceRecord,
    TraceConfig,
    LatencyProfile,
    generate_scenario_traces,
    load_scenario,
)

__all__ = [
    'DemoRunner',
    'TraceGenerator',
    'TraceRecord',
    'TraceConfig',
    'LatencyProfile',
    'generate_scenario_traces',
    'load_scenario',
]
