"""
Streaming trace analyzer.

CRITICAL: Only TX_EVENT records affect latency statistics!
Other record types (OVERFLOW, HEARTBEAT, RESET) are counted but don't
contribute to percentiles or mean/variance.

Why? OVERFLOW records have `data` = count of traces lost. If we included
them in latency stats, a value like 1000000 would completely corrupt P99.
"""

from dataclasses import dataclass, field
from collections import deque
from typing import List, Optional, Iterator
from pathlib import Path
import math

from .sequence import SequenceTracker
from .quantiles import TDigestWrapper
from .rolling_window import RollingWindowStats
from ..formats.record_types import RecordType
from ..formats.reader import TraceReader
from ..adapters.base import StandardTrace


@dataclass
class StreamingConfig:
    """Configuration for streaming analysis."""
    window_seconds: float = 60.0
    anomaly_zscore: float = 3.0
    max_anomalies_tracked: int = 1000
    clock_hz: float = 100_000_000  # MUST be set from config, not hardcoded!


class StreamingMetrics:
    """
    Memory-efficient streaming metrics computation.

    CRITICAL: Only TX_EVENT records affect latency statistics!

    Example:
        config = StreamingConfig(clock_hz=200_000_000)  # 200 MHz
        metrics = StreamingMetrics(config)

        for trace in traces:
            metrics.add(trace)

        result = metrics.snapshot()
        print(f"P99: {result['latency']['p99_cycles']}")
    """

    def __init__(self, config: StreamingConfig = None):
        self.config = config or StreamingConfig()

        # === Global latency stats (Welford's online algorithm) ===
        self.global_count: int = 0
        self.global_mean: float = 0.0
        self.global_m2: float = 0.0  # Sum of squared differences
        self.global_min: float = float('inf')
        self.global_max: float = float('-inf')

        # === Percentile estimation ===
        self.global_digest = TDigestWrapper()

        # === Rolling window ===
        self.rolling_window = RollingWindowStats(
            window_seconds=self.config.window_seconds,
            clock_hz=self.config.clock_hz,
        )

        # === Sequence tracking ===
        self.sequence_tracker = SequenceTracker()

        # === Anomaly tracking ===
        self.anomalies: deque = deque(maxlen=self.config.max_anomalies_tracked)

        # === Record type counters ===
        self.tx_count: int = 0
        self.overflow_count: int = 0
        self.overflow_traces_lost: int = 0
        self.heartbeat_count: int = 0
        self.reset_count: int = 0
        self.unknown_type_count: int = 0

        # === Risk control counters ===
        self.rate_limit_rejects: int = 0
        self.position_limit_rejects: int = 0
        self.notional_limit_rejects: int = 0
        self.kill_switch_triggered: bool = False

        # === Timing ===
        self.first_timestamp: Optional[int] = None
        self.last_timestamp: Optional[int] = None

    def add(self, trace: StandardTrace) -> None:
        """
        Add a trace. Routes to appropriate handler by record type.

        CRITICAL: Only TX_EVENT affects latency stats!
        """
        if trace.record_type == RecordType.TX_EVENT:
            self._add_transaction(trace)
        elif trace.record_type == RecordType.OVERFLOW:
            self._add_overflow(trace)
        elif trace.record_type == RecordType.HEARTBEAT:
            self._add_heartbeat(trace)
        elif trace.record_type == RecordType.RESET:
            self._add_reset(trace)
        else:
            self.unknown_type_count += 1

    def _add_transaction(self, trace: StandardTrace) -> None:
        """
        Process TX_EVENT - the ONLY type affecting latency stats.
        """
        latency = trace.latency
        timestamp = trace.t_egress

        self.tx_count += 1

        # Track timing
        if self.first_timestamp is None:
            self.first_timestamp = timestamp
        self.last_timestamp = timestamp

        # Check sequence (drops)
        self.sequence_tracker.check(trace.core_id, trace.seq_no, timestamp)

        # === Update global stats (Welford's algorithm) ===
        self.global_count += 1

        # Numerically stable incremental mean/variance
        delta = latency - self.global_mean
        self.global_mean += delta / self.global_count
        delta2 = latency - self.global_mean
        self.global_m2 += delta * delta2

        self.global_min = min(self.global_min, latency)
        self.global_max = max(self.global_max, latency)

        # Percentile digest
        self.global_digest.add(latency)

        # Rolling window
        self.rolling_window.add(latency, timestamp)

        # === Anomaly detection ===
        if self.global_count > 30:
            stddev = self.global_stddev()
            if stddev > 0:
                zscore = (latency - self.global_mean) / stddev
                if zscore > self.config.anomaly_zscore:
                    self.anomalies.append((timestamp, trace.tx_id, latency, zscore))

        # Risk flags
        self._track_risk_flags(trace.flags)

    def _add_overflow(self, trace: StandardTrace) -> None:
        """
        Process OVERFLOW - does NOT affect latency stats!

        The data field contains count of traces lost, not latency.
        """
        self.overflow_count += 1
        self.overflow_traces_lost += trace.data

    def _add_heartbeat(self, trace: StandardTrace) -> None:
        """Process HEARTBEAT - does NOT affect latency stats."""
        self.heartbeat_count += 1
        if trace.t_egress > 0:
            self.last_timestamp = trace.t_egress

    def _add_reset(self, trace: StandardTrace) -> None:
        """Process RESET - resets sequence tracking."""
        self.reset_count += 1
        self.sequence_tracker.handle_reset(
            trace.core_id, trace.seq_no, trace.t_egress
        )

    def _track_risk_flags(self, flags: int) -> None:
        """Track risk control events from trace flags."""
        if flags & 0x0100:
            self.rate_limit_rejects += 1
        if flags & 0x0200:
            self.position_limit_rejects += 1
        if flags & 0x0400:
            self.notional_limit_rejects += 1
        if flags & 0x0800:
            self.kill_switch_triggered = True

    def global_stddev(self) -> float:
        """Compute standard deviation from Welford's algorithm."""
        if self.global_count < 2:
            return 0.0
        return math.sqrt(self.global_m2 / (self.global_count - 1))

    def global_percentile(self, p: float) -> float:
        """Get global percentile."""
        return self.global_digest.percentile(p)

    def snapshot(self) -> dict:
        """Get current metrics snapshot for JSON serialization."""
        duration = 0.0
        if self.first_timestamp is not None and self.last_timestamp is not None:
            duration = (self.last_timestamp - self.first_timestamp) / self.config.clock_hz

        seq = self.sequence_tracker

        return {
            'latency': {
                'count': self.global_count,
                'min_cycles': int(self.global_min) if self.global_count > 0 else 0,
                'max_cycles': int(self.global_max) if self.global_count > 0 else 0,
                'mean_cycles': round(self.global_mean, 2),
                'stddev_cycles': round(self.global_stddev(), 2),
                'p50_cycles': int(self.global_percentile(0.50)),
                'p75_cycles': int(self.global_percentile(0.75)),
                'p90_cycles': int(self.global_percentile(0.90)),
                'p95_cycles': int(self.global_percentile(0.95)),
                'p99_cycles': int(self.global_percentile(0.99)),
                'p999_cycles': int(self.global_percentile(0.999)),
            },
            'throughput': {
                'tx_per_second': round(self.global_count / duration, 2) if duration > 0 else 0,
                'duration_seconds': round(duration, 4),
            },
            'drops': {
                'total_dropped': seq.total_dropped,
                'drop_rate': seq.total_dropped / (self.global_count + seq.total_dropped) if self.global_count > 0 else 0,
                'drop_events': len(seq.drop_events),
                'reorder_count': seq.total_reorders,
            },
            'overflow': {
                'overflow_records': self.overflow_count,
                'traces_lost': self.overflow_traces_lost,
            },
            'risk': {
                'rate_limit_rejects': self.rate_limit_rejects,
                'position_limit_rejects': self.position_limit_rejects,
                'notional_limit_rejects': self.notional_limit_rejects,
                'kill_switch_triggered': self.kill_switch_triggered,
            },
            'anomalies': {
                'count': len(self.anomalies),
                'threshold_zscore': self.config.anomaly_zscore,
            },
            'record_types': {
                'tx_events': self.tx_count,
                'overflow': self.overflow_count,
                'heartbeat': self.heartbeat_count,
                'reset': self.reset_count,
                'unknown': self.unknown_type_count,
            },
        }


class StreamingAnalyzer:
    """High-level analyzer that processes trace files."""

    def __init__(self, config: StreamingConfig = None):
        self.config = config or StreamingConfig()
        self.metrics = StreamingMetrics(self.config)

    def analyze_file(self, path: Path) -> dict:
        """Analyze a trace file and return metrics."""
        for trace in TraceReader.read_path(path):
            self.metrics.add(trace)
        return self.metrics.snapshot()

    def reset(self) -> None:
        """Reset for reuse."""
        self.metrics = StreamingMetrics(self.config)
