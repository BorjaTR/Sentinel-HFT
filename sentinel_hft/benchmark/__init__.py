"""
Benchmark module for Sentinel-HFT.

Includes:
- Benchmark history tracking and trend analysis
- HFT benchmark suite for generating test workloads
"""

from .history import (
    BenchmarkHistory,
    BenchmarkSnapshot,
    StabilityScore,
)
from .suite import (
    WorkloadType,
    MessagePattern,
    WorkloadConfig,
    BenchmarkEvent,
    BenchmarkResult,
    HFTBenchmarkSuite,
)

__all__ = [
    # History
    'BenchmarkHistory',
    'BenchmarkSnapshot',
    'StabilityScore',
    # Suite
    'WorkloadType',
    'MessagePattern',
    'WorkloadConfig',
    'BenchmarkEvent',
    'BenchmarkResult',
    'HFTBenchmarkSuite',
]
