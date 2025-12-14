#!/usr/bin/env python3
"""Compute latency metrics from trace records.

This module computes statistical metrics from trace records,
including latency distributions, throughput, anomaly detection, and error counts.

Usage:
    python metrics.py <traces.jsonl>

    Output is JSON with metric summaries.
"""

import json
import sys
from dataclasses import dataclass, field
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
    median_cycles: float
    stddev_cycles: float

    # Percentiles
    p50_cycles: float
    p75_cycles: float
    p90_cycles: float
    p95_cycles: float
    p99_cycles: float
    p999_cycles: float

    # Time-domain (using clock period)
    clock_period_ns: float = 10.0

    @property
    def min_ns(self) -> float:
        """Minimum latency in nanoseconds."""
        return self.min_cycles * self.clock_period_ns

    @property
    def max_ns(self) -> float:
        """Maximum latency in nanoseconds."""
        return self.max_cycles * self.clock_period_ns

    @property
    def mean_ns(self) -> float:
        """Mean latency in nanoseconds."""
        return self.mean_cycles * self.clock_period_ns

    @property
    def p99_ns(self) -> float:
        """P99 latency in nanoseconds."""
        return self.p99_cycles * self.clock_period_ns

    @property
    def p999_ns(self) -> float:
        """P99.9 latency in nanoseconds."""
        return self.p999_cycles * self.clock_period_ns

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'count': self.count,
            'min_cycles': self.min_cycles,
            'max_cycles': self.max_cycles,
            'mean_cycles': round(self.mean_cycles, 2),
            'median_cycles': round(self.median_cycles, 2),
            'stddev_cycles': round(self.stddev_cycles, 2),
            'p50_cycles': round(self.p50_cycles, 2),
            'p75_cycles': round(self.p75_cycles, 2),
            'p90_cycles': round(self.p90_cycles, 2),
            'p95_cycles': round(self.p95_cycles, 2),
            'p99_cycles': round(self.p99_cycles, 2),
            'p999_cycles': round(self.p999_cycles, 2),
            'clock_period_ns': self.clock_period_ns,
            'min_ns': round(self.min_ns, 2),
            'max_ns': round(self.max_ns, 2),
            'mean_ns': round(self.mean_ns, 2),
            'p99_ns': round(self.p99_ns, 2),
            'p999_ns': round(self.p999_ns, 2),
        }


@dataclass
class ThroughputMetrics:
    """Throughput statistics."""
    total_transactions: int
    total_cycles: int
    transactions_per_cycle: float
    transactions_per_second: float  # At given clock rate

    # Burst analysis
    max_burst_size: int             # Max consecutive transactions
    avg_inter_arrival_cycles: float

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'total_transactions': self.total_transactions,
            'total_cycles': self.total_cycles,
            'transactions_per_cycle': round(self.transactions_per_cycle, 6),
            'transactions_per_second': round(self.transactions_per_second, 2),
            'max_burst_size': self.max_burst_size,
            'avg_inter_arrival_cycles': round(self.avg_inter_arrival_cycles, 2),
        }


@dataclass
class Anomaly:
    """A single anomaly detection."""
    tx_id: int
    latency_cycles: int
    zscore: float
    description: str

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'tx_id': self.tx_id,
            'latency_cycles': self.latency_cycles,
            'zscore': round(self.zscore, 2),
            'description': self.description,
        }


@dataclass
class AnomalyReport:
    """Detected anomalies in trace data."""
    anomalies: list = field(default_factory=list)
    threshold_zscore: float = 3.0
    baseline_mean: float = 0.0
    baseline_stddev: float = 0.0

    @property
    def count(self) -> int:
        """Number of anomalies detected."""
        return len(self.anomalies)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'count': self.count,
            'threshold_zscore': self.threshold_zscore,
            'baseline_mean': round(self.baseline_mean, 2),
            'baseline_stddev': round(self.baseline_stddev, 2),
            'anomalies': [a.to_dict() for a in self.anomalies[:100]],  # Limit to 100
        }


@dataclass
class TraceMetrics:
    """Complete metrics from trace analysis (H1 compatible)."""
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


@dataclass
class FullMetrics:
    """Complete metrics report (H2)."""
    latency: LatencyMetrics
    throughput: ThroughputMetrics
    anomalies: AnomalyReport

    # Metadata
    trace_file: str = ""
    trace_count: int = 0
    trace_drops: int = 0
    validation_errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'metadata': {
                'trace_file': self.trace_file,
                'trace_count': self.trace_count,
                'trace_drops': self.trace_drops,
                'validation_errors': self.validation_errors,
            },
            'latency': self.latency.to_dict(),
            'throughput': self.throughput.to_dict(),
            'anomalies': self.anomalies.to_dict(),
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


def _stddev_pure_python(values: List[float], mean: float) -> float:
    """Compute standard deviation without numpy."""
    if len(values) < 2:
        return 0.0
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return variance ** 0.5


class MetricsEngine:
    """Compute comprehensive metrics from traces."""

    def __init__(self, clock_period_ns: float = 10.0, anomaly_zscore: float = 3.0):
        """Initialize metrics engine.

        Args:
            clock_period_ns: Clock period for time conversion (default: 10ns = 100MHz)
            anomaly_zscore: Z-score threshold for anomaly detection
        """
        self.clock_period_ns = clock_period_ns
        self.anomaly_zscore = anomaly_zscore

    def compute_latency(self, latencies: Sequence[int]) -> LatencyMetrics:
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
                median_cycles=0.0,
                stddev_cycles=0.0,
                p50_cycles=0.0,
                p75_cycles=0.0,
                p90_cycles=0.0,
                p95_cycles=0.0,
                p99_cycles=0.0,
                p999_cycles=0.0,
                clock_period_ns=self.clock_period_ns,
            )

        if HAS_NUMPY:
            arr = np.array(latencies)
            return LatencyMetrics(
                count=len(arr),
                min_cycles=int(arr.min()),
                max_cycles=int(arr.max()),
                mean_cycles=float(arr.mean()),
                median_cycles=float(np.median(arr)),
                stddev_cycles=float(arr.std()),
                p50_cycles=float(np.percentile(arr, 50)),
                p75_cycles=float(np.percentile(arr, 75)),
                p90_cycles=float(np.percentile(arr, 90)),
                p95_cycles=float(np.percentile(arr, 95)),
                p99_cycles=float(np.percentile(arr, 99)),
                p999_cycles=float(np.percentile(arr, 99.9)),
                clock_period_ns=self.clock_period_ns,
            )
        else:
            # Pure Python fallback
            lat_list = list(latencies)
            n = len(lat_list)
            mean = sum(lat_list) / n
            stddev = _stddev_pure_python(lat_list, mean)
            sorted_lat = sorted(lat_list)
            median = sorted_lat[n // 2] if n % 2 == 1 else (
                sorted_lat[n // 2 - 1] + sorted_lat[n // 2]) / 2

            return LatencyMetrics(
                count=n,
                min_cycles=min(lat_list),
                max_cycles=max(lat_list),
                mean_cycles=mean,
                median_cycles=median,
                stddev_cycles=stddev,
                p50_cycles=_percentile_pure_python(lat_list, 50),
                p75_cycles=_percentile_pure_python(lat_list, 75),
                p90_cycles=_percentile_pure_python(lat_list, 90),
                p95_cycles=_percentile_pure_python(lat_list, 95),
                p99_cycles=_percentile_pure_python(lat_list, 99),
                p999_cycles=_percentile_pure_python(lat_list, 99.9),
                clock_period_ns=self.clock_period_ns,
            )

    def compute_throughput(
        self,
        ingress_times: list[int],
        egress_times: list[int],
        clock_hz: float = 100e6,
    ) -> ThroughputMetrics:
        """Compute throughput metrics.

        Args:
            ingress_times: List of ingress cycle timestamps
            egress_times: List of egress cycle timestamps
            clock_hz: Clock frequency in Hz

        Returns:
            ThroughputMetrics object
        """
        n = len(ingress_times)
        if n == 0:
            return ThroughputMetrics(
                total_transactions=0,
                total_cycles=0,
                transactions_per_cycle=0.0,
                transactions_per_second=0.0,
                max_burst_size=0,
                avg_inter_arrival_cycles=0.0,
            )

        # Total cycles from first ingress to last egress
        min_ingress = min(ingress_times)
        max_egress = max(egress_times)
        total_cycles = max(1, max_egress - min_ingress)

        # Transactions per cycle
        tx_per_cycle = n / total_cycles

        # Transactions per second
        tx_per_sec = tx_per_cycle * clock_hz

        # Burst analysis: count consecutive ingresses on same cycle
        sorted_ingress = sorted(ingress_times)
        max_burst = 1
        current_burst = 1
        inter_arrivals = []

        for i in range(1, len(sorted_ingress)):
            diff = sorted_ingress[i] - sorted_ingress[i - 1]
            if diff == 0:
                current_burst += 1
                max_burst = max(max_burst, current_burst)
            else:
                current_burst = 1
                inter_arrivals.append(diff)

        avg_inter_arrival = (sum(inter_arrivals) / len(inter_arrivals)
                            if inter_arrivals else 0.0)

        return ThroughputMetrics(
            total_transactions=n,
            total_cycles=total_cycles,
            transactions_per_cycle=tx_per_cycle,
            transactions_per_second=tx_per_sec,
            max_burst_size=max_burst,
            avg_inter_arrival_cycles=avg_inter_arrival,
        )

    def detect_anomalies(
        self,
        latencies: list[int],
        tx_ids: list[int],
    ) -> AnomalyReport:
        """Detect latency anomalies using z-score.

        Args:
            latencies: List of latency values
            tx_ids: Corresponding transaction IDs

        Returns:
            AnomalyReport with detected anomalies
        """
        if len(latencies) < 2:
            return AnomalyReport(
                anomalies=[],
                threshold_zscore=self.anomaly_zscore,
                baseline_mean=latencies[0] if latencies else 0,
                baseline_stddev=0,
            )

        # Compute baseline statistics
        if HAS_NUMPY:
            arr = np.array(latencies)
            mean = float(arr.mean())
            stddev = float(arr.std())
        else:
            mean = sum(latencies) / len(latencies)
            stddev = _stddev_pure_python(latencies, mean)

        # Avoid division by zero
        if stddev == 0:
            return AnomalyReport(
                anomalies=[],
                threshold_zscore=self.anomaly_zscore,
                baseline_mean=mean,
                baseline_stddev=0,
            )

        # Find anomalies
        anomalies = []
        for lat, tx_id in zip(latencies, tx_ids):
            zscore = (lat - mean) / stddev
            if abs(zscore) >= self.anomaly_zscore:
                desc = f"High latency" if zscore > 0 else "Low latency"
                anomalies.append(Anomaly(
                    tx_id=tx_id,
                    latency_cycles=lat,
                    zscore=zscore,
                    description=f"{desc}: {lat} cycles (z={zscore:.2f})",
                ))

        # Sort by z-score magnitude (most anomalous first)
        anomalies.sort(key=lambda a: abs(a.zscore), reverse=True)

        return AnomalyReport(
            anomalies=anomalies,
            threshold_zscore=self.anomaly_zscore,
            baseline_mean=mean,
            baseline_stddev=stddev,
        )

    def compute_full(self, traces: list) -> FullMetrics:
        """Compute all metrics from trace list.

        Args:
            traces: List of trace objects with tx_id, t_ingress, t_egress, latency_cycles

        Returns:
            FullMetrics with all computed statistics
        """
        if not traces:
            return FullMetrics(
                latency=self.compute_latency([]),
                throughput=self.compute_throughput([], []),
                anomalies=AnomalyReport(),
                trace_count=0,
            )

        # Extract data
        latencies = []
        tx_ids = []
        ingress_times = []
        egress_times = []

        for t in traces:
            if hasattr(t, 'latency_cycles'):
                latencies.append(t.latency_cycles)
            elif isinstance(t, dict):
                lat = t.get('latency_cycles', t.get('t_egress', 0) - t.get('t_ingress', 0))
                latencies.append(lat)

            if hasattr(t, 'tx_id'):
                tx_ids.append(t.tx_id)
            elif isinstance(t, dict):
                tx_ids.append(t.get('tx_id', 0))

            if hasattr(t, 't_ingress'):
                ingress_times.append(t.t_ingress)
            elif isinstance(t, dict):
                ingress_times.append(t.get('t_ingress', 0))

            if hasattr(t, 't_egress'):
                egress_times.append(t.t_egress)
            elif isinstance(t, dict):
                egress_times.append(t.get('t_egress', 0))

        return FullMetrics(
            latency=self.compute_latency(latencies),
            throughput=self.compute_throughput(ingress_times, egress_times),
            anomalies=self.detect_anomalies(latencies, tx_ids),
            trace_count=len(traces),
        )


# Backwards-compatible function from H1
def compute_metrics(latencies: Sequence[int], clock_period_ns: float = 10.0) -> LatencyMetrics:
    """Compute latency distribution metrics.

    Args:
        latencies: Sequence of latency values in clock cycles
        clock_period_ns: Clock period for time conversion

    Returns:
        LatencyMetrics object with distribution statistics
    """
    engine = MetricsEngine(clock_period_ns=clock_period_ns)
    return engine.compute_latency(latencies)


def compute_trace_metrics(records: List[dict]) -> TraceMetrics:
    """Compute complete metrics from trace records (H1 compatible).

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
