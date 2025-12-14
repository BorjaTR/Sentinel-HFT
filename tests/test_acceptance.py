"""
Final acceptance tests - all critical paths.

These tests must ALL pass before release.
They verify the core requirements that fix the original bugs:
1. Correct struct sizes
2. File header handling
3. Sequence wrap handling
4. Record type filtering
"""

import pytest
import json
import struct
from pathlib import Path

from sentinel_hft.formats.file_header import FileHeader, HEADER_SIZE
from sentinel_hft.formats.reader import TraceReader
from sentinel_hft.adapters.sentinel_adapter import SentinelV10Adapter, SentinelV11Adapter
from sentinel_hft.adapters.base import StandardTrace
from sentinel_hft.streaming.sequence import u32, u32_distance, SequenceTracker, U32_MAX
from sentinel_hft.streaming.quantiles import TDigestWrapper
from sentinel_hft.streaming.analyzer import StreamingMetrics, StreamingConfig
from sentinel_hft.formats.record_types import RecordType


class TestStructSizes:
    """
    CRITICAL: All struct sizes must be exact.

    Wrong sizes were the root cause of the original bugs.
    """

    def test_header_is_32_bytes(self):
        """File header must be exactly 32 bytes."""
        assert HEADER_SIZE == 32
        assert struct.calcsize(FileHeader.FORMAT) == 32

        # Verify by encoding
        header = FileHeader()
        encoded = header.encode()
        assert len(encoded) == 32

    def test_v10_is_32_bytes(self):
        """v1.0 records must be exactly 32 bytes."""
        adapter = SentinelV10Adapter()
        assert adapter.record_size() == 32
        assert struct.calcsize('<QQQHHI') == 32

    def test_v11_is_48_bytes(self):
        """v1.1 records must be exactly 48 bytes."""
        adapter = SentinelV11Adapter()
        assert adapter.record_size() == 48

    def test_v11_decode_format_is_36_bytes(self):
        """v1.1 decode format (without reserved) is 36 bytes."""
        assert struct.calcsize('<BBHIQQQHH') == 36


class TestHeaderHandling:
    """
    CRITICAL: Files with headers must decode correctly.

    Headers must be skipped - NOT decoded as garbage trace records.
    """

    def test_header_magic_correct(self):
        """Header magic must be 'SNTL'."""
        from sentinel_hft.formats.file_header import MAGIC
        assert MAGIC == b'SNTL'

    def test_header_file_not_garbage(self, tmp_path):
        """Header bytes must NOT be decoded as a trace record."""
        adapter = SentinelV11Adapter()

        # Create one real trace with known values
        trace = StandardTrace(
            version=1, record_type=1, core_id=0, seq_no=42,
            t_ingress=1000, t_egress=1010, data=0xDEADBEEF,
            flags=0, tx_id=99,
        )

        # Write file with header
        header = FileHeader(version=1, record_size=48)
        test_file = tmp_path / "test.bin"
        with open(test_file, 'wb') as f:
            f.write(header.encode())
            f.write(adapter.encode(trace))

        # Read and verify ONLY ONE trace is returned
        traces = list(TraceReader.read_path(test_file))

        assert len(traces) == 1, f"Expected 1 trace, got {len(traces)}"
        assert traces[0].seq_no == 42, f"seq_no = {traces[0].seq_no}, expected 42"
        assert traces[0].data == 0xDEADBEEF, f"data = {traces[0].data}, expected 0xDEADBEEF"
        assert traces[0].t_ingress == 1000
        assert traces[0].t_egress == 1010

    def test_headerless_file_works(self, tmp_path):
        """Files without headers still work (with ambiguity)."""
        adapter = SentinelV10Adapter()  # Use v1.0 for clarity

        # Create traces without header using v1.0 format
        test_file = tmp_path / "no_header.bin"
        with open(test_file, 'wb') as f:
            for i in range(10):
                trace = StandardTrace(
                    version=1, record_type=1, core_id=0, seq_no=i,
                    t_ingress=i*100, t_egress=i*100+10,
                    data=0, flags=0, tx_id=i,
                )
                f.write(adapter.encode(trace))

        # File size = 10 * 32 = 320 bytes
        # Not divisible by 48, so will be detected as v1.0
        traces = list(TraceReader.read_path(test_file))
        assert len(traces) == 10

    def test_header_probe(self, tmp_path):
        """Header.probe detects files with headers."""
        # File with header
        with_header = tmp_path / "with_header.bin"
        header = FileHeader(version=1, record_size=48)
        with_header.write_bytes(header.encode() + b'\x00' * 48)

        assert FileHeader.probe(with_header) is not None

        # File without header
        without_header = tmp_path / "without_header.bin"
        without_header.write_bytes(b'\x00' * 80)

        assert FileHeader.probe(without_header) is None


class TestSequenceTracking:
    """
    CRITICAL: Sequence tracking must handle wrap correctly.

    u32 wrap at 0xFFFFFFFF -> 0 must NOT produce billions of fake drops.
    """

    def test_clean_wrap_zero_drops(self):
        """
        CRITICAL: Wrap at 0xFFFFFFFF -> 0 produces ZERO drops.

        This is the core bug fix - Python ints don't wrap naturally.
        """
        tracker = SequenceTracker()

        # Cross the wrap boundary
        for seq in [0xFFFFFFFD, 0xFFFFFFFE, 0xFFFFFFFF, 0, 1, 2]:
            drop = tracker.check(0, seq, 0)
            assert drop is None, f"Unexpected drop at seq 0x{seq:08X}"

        assert tracker.total_dropped == 0, \
            f"Clean wrap produced {tracker.total_dropped} fake drops!"

    def test_u32_function(self):
        """u32() correctly masks to 32 bits."""
        assert u32(0) == 0
        assert u32(100) == 100
        assert u32(U32_MAX) == U32_MAX
        assert u32(U32_MAX + 1) == 0  # Wrap
        assert u32(U32_MAX + 100) == 99  # Wrap with offset

    def test_u32_distance_wrap(self):
        """u32_distance handles wrap correctly."""
        # Simple forward distance
        assert u32_distance(0, 10) == 10
        assert u32_distance(100, 105) == 5

        # Wrap: 0xFFFFFFFF -> 0 is distance 1
        assert u32_distance(U32_MAX, 0) == 1
        assert u32_distance(U32_MAX - 1, 0) == 2

    def test_reorder_not_counted_as_drop(self):
        """Reordered packets must NOT be counted as drops."""
        tracker = SequenceTracker()

        tracker.check(0, 0, 0)
        tracker.check(0, 1, 0)
        tracker.check(0, 3, 0)  # Gap - 1 drop
        tracker.check(0, 2, 0)  # Late arrival - reorder, NOT drop

        assert tracker.total_dropped == 1, "Gap should cause 1 drop"
        assert tracker.total_reorders == 1, "Late arrival should be 1 reorder"

    def test_actual_gap_detected(self):
        """Actual gaps are properly detected."""
        tracker = SequenceTracker()

        tracker.check(0, 0, 0)
        tracker.check(0, 1, 0)
        tracker.check(0, 5, 0)  # Gap of 3 (missing 2, 3, 4)

        assert tracker.total_dropped == 3


class TestQuantiles:
    """
    CRITICAL: Percentiles must be accurate.

    Streaming algorithms have error bounds that must be verified.
    """

    def test_p99_accuracy(self):
        """P99 must be within 5% of true value."""
        digest = TDigestWrapper()

        for i in range(10001):
            digest.add(i)

        p99 = digest.percentile(0.99)
        true_p99 = 9900

        error = abs(p99 - true_p99) / true_p99
        assert error < 0.05, f"P99 = {p99}, error = {error:.2%}"

    def test_p50_accuracy(self):
        """P50 (median) must be within 5% of true value."""
        digest = TDigestWrapper()

        for i in range(10001):
            digest.add(i)

        p50 = digest.percentile(0.50)
        true_p50 = 5000

        error = abs(p50 - true_p50) / true_p50
        assert error < 0.05, f"P50 = {p50}, error = {error:.2%}"

    def test_empty_digest(self):
        """Empty digest returns 0."""
        digest = TDigestWrapper()
        assert digest.percentile(0.99) == 0


class TestRecordFiltering:
    """
    CRITICAL: Only TX_EVENT affects latency stats.

    OVERFLOW data field contains count of lost traces - NOT latency!
    Including it would corrupt percentiles.
    """

    def test_overflow_not_in_percentiles(self):
        """
        OVERFLOW records must NOT corrupt percentiles.

        OVERFLOW.data = number of traces lost (can be millions).
        This must NEVER be included in latency statistics.
        """
        metrics = StreamingMetrics()

        # Add 10 TX_EVENTs with latency 10
        for i in range(10):
            metrics.add(StandardTrace(
                version=1, record_type=RecordType.TX_EVENT, core_id=0,
                seq_no=i, t_ingress=0, t_egress=10, data=0, flags=0, tx_id=i,
            ))

        # Add OVERFLOW with data=1000000 (traces lost, NOT latency!)
        metrics.add(StandardTrace(
            version=1, record_type=RecordType.OVERFLOW, core_id=0,
            seq_no=10, t_ingress=0, t_egress=0, data=1000000, flags=0, tx_id=10,
        ))

        assert metrics.global_count == 10, "OVERFLOW should not be counted in latency stats!"

        p99 = metrics.global_percentile(0.99)
        # Allow small approximation error from DDSketch
        assert 9 <= p99 <= 11, f"P99 = {p99}, should be ~10 (OVERFLOW corrupted it!)"

    def test_heartbeat_not_in_percentiles(self):
        """HEARTBEAT records not counted in latency."""
        metrics = StreamingMetrics()

        # Add TX_EVENTs
        for i in range(5):
            metrics.add(StandardTrace(
                version=1, record_type=RecordType.TX_EVENT, core_id=0,
                seq_no=i, t_ingress=0, t_egress=20, data=0, flags=0, tx_id=i,
            ))

        # Add HEARTBEAT
        metrics.add(StandardTrace(
            version=1, record_type=RecordType.HEARTBEAT, core_id=0,
            seq_no=5, t_ingress=0, t_egress=0, data=0, flags=0, tx_id=5,
        ))

        assert metrics.global_count == 5
        assert metrics.heartbeat_count == 1

    def test_only_tx_event_in_mean(self):
        """Only TX_EVENT contributes to mean latency."""
        metrics = StreamingMetrics()

        # Add TX_EVENTs with known latency
        for i in range(4):
            metrics.add(StandardTrace(
                version=1, record_type=RecordType.TX_EVENT, core_id=0,
                seq_no=i, t_ingress=0, t_egress=100, data=0, flags=0, tx_id=i,
            ))

        # Add non-TX records
        metrics.add(StandardTrace(
            version=1, record_type=RecordType.OVERFLOW, core_id=0,
            seq_no=4, t_ingress=0, t_egress=0, data=1000, flags=0, tx_id=4,
        ))

        assert metrics.global_count == 4
        assert metrics.global_mean == 100.0


class TestEndToEnd:
    """End-to-end integration tests."""

    def test_full_pipeline(self, tmp_path):
        """Full analysis pipeline works correctly."""
        adapter = SentinelV11Adapter()

        # Create traces with known latencies
        traces_data = []
        for i in range(100):
            trace = StandardTrace(
                version=1, record_type=1, core_id=0, seq_no=i,
                t_ingress=i*100, t_egress=i*100+5+i%10,  # Latency 5-14
                data=0, flags=0, tx_id=i,
            )
            traces_data.append(adapter.encode(trace))

        # Write with header
        header = FileHeader(version=1, record_size=48, clock_mhz=100)
        test_file = tmp_path / "traces.bin"
        with open(test_file, 'wb') as f:
            f.write(header.encode())
            for t in traces_data:
                f.write(t)

        # Analyze
        metrics = StreamingMetrics()
        for trace in TraceReader.read_path(test_file):
            metrics.add(trace)

        # Verify results
        assert metrics.global_count == 100
        assert metrics.sequence_tracker.total_dropped == 0
        assert 5 <= metrics.global_percentile(0.50) <= 15
        assert 5 <= metrics.global_mean <= 15

    def test_mixed_record_types(self, tmp_path):
        """File with mixed record types processed correctly."""
        adapter = SentinelV11Adapter()

        test_file = tmp_path / "mixed.bin"
        with open(test_file, 'wb') as f:
            header = FileHeader(version=1, record_size=48)
            f.write(header.encode())

            # TX_EVENTs
            for i in range(50):
                trace = StandardTrace(
                    version=1, record_type=RecordType.TX_EVENT, core_id=0,
                    seq_no=i, t_ingress=0, t_egress=10,
                    data=0, flags=0, tx_id=i,
                )
                f.write(adapter.encode(trace))

            # OVERFLOW
            trace = StandardTrace(
                version=1, record_type=RecordType.OVERFLOW, core_id=0,
                seq_no=50, t_ingress=0, t_egress=0,
                data=1000, flags=0, tx_id=50,
            )
            f.write(adapter.encode(trace))

            # More TX_EVENTs
            for i in range(51, 100):
                trace = StandardTrace(
                    version=1, record_type=RecordType.TX_EVENT, core_id=0,
                    seq_no=i, t_ingress=0, t_egress=10,
                    data=0, flags=0, tx_id=i,
                )
                f.write(adapter.encode(trace))

        metrics = StreamingMetrics()
        for trace in TraceReader.read_path(test_file):
            metrics.add(trace)

        # Only TX_EVENTs in latency stats
        assert metrics.global_count == 99
        assert metrics.overflow_count == 1
        assert metrics.overflow_traces_lost == 1000


class TestCLIIntegration:
    """CLI integration tests."""

    def test_cli_demo(self, tmp_path):
        """CLI demo command works."""
        pytest.importorskip("typer")

        from typer.testing import CliRunner
        from sentinel_hft.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["demo", "-o", str(tmp_path)])

        assert result.exit_code == 0
        assert (tmp_path / "demo_traces.bin").exists()
        assert (tmp_path / "demo_report.json").exists()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
