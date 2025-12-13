"""Sentinel-HFT host tools.

This package provides Python utilities for decoding and analyzing
trace records from the Sentinel Shell RTL instrumentation.
"""

from .trace_decode import TraceRecord, decode_trace, decode_trace_file
from .metrics import compute_metrics, LatencyMetrics

__all__ = [
    'TraceRecord',
    'decode_trace',
    'decode_trace_file',
    'compute_metrics',
    'LatencyMetrics',
]
