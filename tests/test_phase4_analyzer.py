"""
Tests for Phase 4: Streaming Analyzer.

CRITICAL TESTS:
1. test_overflow_not_in_latency - OVERFLOW must NOT corrupt percentiles
2. test_only_tx_event_affects_latency - Other types don't affect stats
"""

import pytest
from sentinel_hft.streaming.analyzer import StreamingMetrics, StreamingConfig
from sentinel_hft.adapters.base import StandardTrace
from sentinel_hft.formats.record_types import RecordType


def make_trace(
    seq_no: int,
    t_ingress: int = 0,
    t_egress: int = 10,
    record_type: int = RecordType.TX_EVENT,
    data: int = 0,
    flags: int = 0,
) -> StandardTrace:
    """Helper to create test traces."""
    return StandardTrace(
        version=1,
        record_type=record_type,
        core_id=0,
        seq_no=seq_no,
        t_ingress=t_ingress,
        t_egress=t_egress,
        data=data,
        flags=flags,
        tx_id=seq_no,
    )


class TestRecordTypeFiltering:
    """Test that only TX_EVENT affects latency stats."""

    def test_tx_event_counted(self):
        """TX_EVENT records are counted in latency stats."""
        metrics = StreamingMetrics()

        for i in range(100):
            metrics.add(make_trace(seq_no=i, t_egress=10))

        assert metrics.global_count == 100
        assert metrics.tx_count == 100

    def test_overflow_not_in_latency(self):
        """
        CRITICAL TEST: OVERFLOW records do NOT affect latency stats.

        If OVERFLOW were included, the data field (count of lost traces)
        would be interpreted as latency and corrupt P99.
        """
        metrics = StreamingMetrics()

        # Add 10 TX_EVENTs with latency 10
        for i in range(10):
            metrics.add(make_trace(seq_no=i, t_egress=10))

        # Add OVERFLOW with data=1000000 (traces lost count)
        # If this were counted as latency, P99 would be ~1000000!
        metrics.add(make_trace(
            seq_no=10,
            t_egress=0,
            record_type=RecordType.OVERFLOW,
            data=1000000,
        ))

        # Latency stats should only reflect the 10 TX_EVENTs
        assert metrics.global_count == 10, f"Count = {metrics.global_count}, expected 10"
        assert metrics.overflow_count == 1
        assert metrics.overflow_traces_lost == 1000000

        # P99 should be ~10, NOT corrupted by overflow data (would be ~1000000)
        p99 = metrics.global_percentile(0.99)
        # Allow small approximation error from DDSketch
        assert 9 <= p99 <= 11, f"P99 = {p99}, should be ~10 (not corrupted by overflow)"

    def test_heartbeat_not_in_latency(self):
        """HEARTBEAT records don't affect latency stats."""
        metrics = StreamingMetrics()

        metrics.add(make_trace(seq_no=0, t_egress=10))
        metrics.add(make_trace(
            seq_no=1,
            record_type=RecordType.HEARTBEAT,
        ))

        assert metrics.global_count == 1
        assert metrics.heartbeat_count == 1

    def test_reset_handled_correctly(self):
        """RESET records reset sequence tracking."""
        metrics = StreamingMetrics()

        # Normal sequence 0-9
        for i in range(10):
            metrics.add(make_trace(seq_no=i, t_egress=10))

        # RESET record
        metrics.add(make_trace(
            seq_no=0,
            record_type=RecordType.RESET,
        ))

        # Continue from 1 - should NOT be counted as drop
        metrics.add(make_trace(seq_no=1, t_egress=10))

        assert metrics.sequence_tracker.total_dropped == 0
        assert metrics.reset_count == 1


class TestLatencyComputation:
    """Test latency statistics computation."""

    def test_mean_computation(self):
        """Mean is computed correctly via Welford's algorithm."""
        metrics = StreamingMetrics()

        # Add traces with latencies 10, 20, 30
        for latency in [10, 20, 30]:
            metrics.add(make_trace(seq_no=latency, t_egress=latency))

        assert metrics.global_mean == 20.0

    def test_stddev_with_identical_values(self):
        """Stddev is 0 for identical values."""
        metrics = StreamingMetrics()

        for i in range(100):
            metrics.add(make_trace(seq_no=i, t_egress=10))

        assert metrics.global_stddev() == 0.0

    def test_min_max_tracking(self):
        """Min and max are tracked correctly."""
        metrics = StreamingMetrics()

        for latency in [50, 10, 100, 30]:
            metrics.add(make_trace(seq_no=latency, t_egress=latency))

        assert metrics.global_min == 10
        assert metrics.global_max == 100


class TestRiskTracking:
    """Test risk control event tracking."""

    def test_rate_limit_flag(self):
        """Rate limit flag is tracked."""
        metrics = StreamingMetrics()

        metrics.add(make_trace(seq_no=0, t_egress=10, flags=0x0100))

        assert metrics.rate_limit_rejects == 1

    def test_kill_switch_flag(self):
        """Kill switch flag is tracked."""
        metrics = StreamingMetrics()

        assert not metrics.kill_switch_triggered

        metrics.add(make_trace(seq_no=0, t_egress=10, flags=0x0800))

        assert metrics.kill_switch_triggered


class TestSnapshot:
    """Test snapshot output format."""

    def test_snapshot_contains_all_sections(self):
        """Snapshot contains all expected fields."""
        metrics = StreamingMetrics()

        for i in range(100):
            metrics.add(make_trace(seq_no=i, t_egress=10 + i))

        snap = metrics.snapshot()

        # Check required sections
        assert 'latency' in snap
        assert 'throughput' in snap
        assert 'drops' in snap
        assert 'risk' in snap
        assert 'anomalies' in snap
        assert 'record_types' in snap

        # Check latency fields
        lat = snap['latency']
        assert 'count' in lat
        assert 'p99_cycles' in lat
        assert 'mean_cycles' in lat


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
