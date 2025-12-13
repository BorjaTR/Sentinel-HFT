#!/usr/bin/env python3
"""Compute latency metrics from trace records.

This module computes statistical metrics from trace records,
including latency distributions, throughput, and error counts.

Usage:
    python metrics.py <traces.jsonl>

    Output is JSON with metric summaries.
"""

import json
import sys
from dataclasses import dataclass, asdict
from typing import List, Optional, Sequence

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


@dataclass
class LatencyMetrics:
    """Latency distribution metrics."""
    count: int
    min_cycles: int
    max_cycles: int
    mean_cycles: float
    p50_cycles: float
    p95_cycles: float
    p99_cycles: float
    p999_cycles: float
    stddev_cycles: float

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'count': self.count,
            'min_cycles': self.min_cycles,
            'max_cycles': self.max_cycles,
            'mean_cycles': round(self.mean_cycles, 2),
            'p50_cycles': round(self.p50_cycles, 2),
            'p95_cycles': round(self.p95_cycles, 2),
            'p99_cycles': round(self.p99_cycles, 2),
            'p999_cycles': round(self.p999_cycles, 2),
            'stddev_cycles': round(self.stddev_cycles, 2),
        }


@dataclass
class TraceMetrics:
    """Complete metrics from trace analysis."""
    latency: LatencyMetrics
    total_transactions: int
    error_count: int
    dropped_count: int
    underflow_count: int
    first_tx_id: Optional[int]
    last_tx_id: Optional[int]

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'latency': self.latency.to_dict(),
            'total_transactions': self.total_transactions,
            'error_count': self.error_count,
            'dropped_count': self.dropped_count,
            'underflow_count': self.underflow_count,
            'first_tx_id': self.first_tx_id,
            'last_tx_id': self.last_tx_id,
        }


def _percentile_pure_python(values: List[float], p: float) -> float:
    """Compute percentile without numpy (for minimal dependencies)."""
    if not values:
        return 0.0
    sorted_values = sorted(values)
    n = len(sorted_values)
    k = (n - 1) * (p / 100.0)
    f = int(k)
    c = f + 1
    if c >= n:
        return sorted_values[-1]
    return sorted_values[f] * (c - k) + sorted_values[c] * (k - f)


def compute_metrics(latencies: Sequence[int]) -> LatencyMetrics:
    """Compute latency distribution metrics.

    Args:
        latencies: Sequence of latency values in clock cycles

    Returns:
        LatencyMetrics object with distribution statistics
    """
    if not latencies:
        return LatencyMetrics(
            count=0,
            min_cycles=0,
            max_cycles=0,
            mean_cycles=0.0,
            p50_cycles=0.0,
            p95_cycles=0.0,
            p99_cycles=0.0,
            p999_cycles=0.0,
            stddev_cycles=0.0,
        )

    if HAS_NUMPY:
        arr = np.array(latencies)
        return LatencyMetrics(
            count=len(arr),
            min_cycles=int(arr.min()),
            max_cycles=int(arr.max()),
            mean_cycles=float(arr.mean()),
            p50_cycles=float(np.percentile(arr, 50)),
            p95_cycles=float(np.percentile(arr, 95)),
            p99_cycles=float(np.percentile(arr, 99)),
            p999_cycles=float(np.percentile(arr, 99.9)),
            stddev_cycles=float(arr.std()),
        )
    else:
        # Pure Python fallback
        lat_list = list(latencies)
        n = len(lat_list)
        mean = sum(lat_list) / n
        variance = sum((x - mean) ** 2 for x in lat_list) / n
        stddev = variance ** 0.5

        return LatencyMetrics(
            count=n,
            min_cycles=min(lat_list),
            max_cycles=max(lat_list),
            mean_cycles=mean,
            p50_cycles=_percentile_pure_python(lat_list, 50),
            p95_cycles=_percentile_pure_python(lat_list, 95),
            p99_cycles=_percentile_pure_python(lat_list, 99),
            p999_cycles=_percentile_pure_python(lat_list, 99.9),
            stddev_cycles=stddev,
        )


def compute_trace_metrics(records: List[dict]) -> TraceMetrics:
    """Compute complete metrics from trace records.

    Args:
        records: List of trace record dictionaries

    Returns:
        TraceMetrics object with all metrics
    """
    if not records:
        return TraceMetrics(
            latency=compute_metrics([]),
            total_transactions=0,
            error_count=0,
            dropped_count=0,
            underflow_count=0,
            first_tx_id=None,
            last_tx_id=None,
        )

    # Flag bit definitions (must match trace_pkg.sv)
    FLAG_TRACE_DROPPED  = 0x0001
    FLAG_CORE_ERROR     = 0x0002
    FLAG_INFLIGHT_UNDER = 0x0004

    latencies = []
    error_count = 0
    dropped_count = 0
    underflow_count = 0
    first_tx_id = None
    last_tx_id = None

    for rec in records:
        latencies.append(rec['latency_cycles'])
        flags = rec.get('flags', 0)

        if flags & FLAG_CORE_ERROR:
            error_count += 1
        if flags & FLAG_TRACE_DROPPED:
            dropped_count += 1
        if flags & FLAG_INFLIGHT_UNDER:
            underflow_count += 1

        tx_id = rec['tx_id']
        if first_tx_id is None:
            first_tx_id = tx_id
        last_tx_id = tx_id

    return TraceMetrics(
        latency=compute_metrics(latencies),
        total_transactions=len(records),
        error_count=error_count,
        dropped_count=dropped_count,
        underflow_count=underflow_count,
        first_tx_id=first_tx_id,
        last_tx_id=last_tx_id,
    )


def main():
    """Command-line interface for metrics computation."""
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <traces.jsonl>", file=sys.stderr)
        print("\nComputes latency metrics from JSONL trace records.",
              file=sys.stderr)
        sys.exit(1)

    filepath = sys.argv[1]

    try:
        records = []
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

        if not records:
            print("No traces found", file=sys.stderr)
            sys.exit(1)

        metrics = compute_trace_metrics(records)
        print(json.dumps(metrics.to_dict(), indent=2))

    except FileNotFoundError:
        print(f"Error: File not found: {filepath}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
