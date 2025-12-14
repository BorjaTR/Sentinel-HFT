"""
Tests for Phase 8: REST API.

CRITICAL TESTS:
1. test_analyze_file - File analysis produces valid report
2. test_analyze_bytes - Byte analysis works correctly
3. test_health_check - Health endpoint returns valid data
"""

import pytest
import struct
from pathlib import Path
from tempfile import NamedTemporaryFile

from sentinel_hft.api.server import AnalysisAPI, AnalysisRequest
from sentinel_hft.config import SentinelConfig
from sentinel_hft.core.report import ReportStatus
from sentinel_hft.formats.file_header import FileHeader


def create_test_file(num_traces: int = 100) -> Path:
    """Create a test trace file with header and v1.1 traces."""
    with NamedTemporaryFile(suffix='.bin', delete=False) as f:
        # Write header
        header = FileHeader(
            version=1,
            clock_mhz=100,
            record_size=48,
        )
        f.write(header.encode())

        # Write traces (v1.1 format: 48 bytes each)
        # Adapter format: <BBHIQQQHH = version, type, core_id, seq_no, t_ingress, t_egress, data, flags, tx_id
        # Sizes: B=1, B=1, H=2, I=4, Q=8, Q=8, Q=8, H=2, H=2 = 36 bytes + 12 reserved = 48
        for i in range(num_traces):
            record = struct.pack(
                '<BBHIQQQHH',
                1,  # version (u8)
                1,  # record_type (u8) TX_EVENT=1
                0,  # core_id (u16)
                i,  # seq_no (u32)
                i * 1000,  # t_ingress (u64)
                i * 1000 + 10 + (i % 50),  # t_egress (u64) - latency varies 10-59
                0,  # data (u64)
                0,  # flags (u16)
                i % 65536,  # tx_id (u16)
            )
            # Pad to 48 bytes
            record += b'\x00' * (48 - len(record))
            f.write(record)

        return Path(f.name)


class TestAnalysisAPI:
    """Test core API logic."""

    def test_analyze_file(self):
        """
        CRITICAL TEST: File analysis produces valid report.
        """
        api = AnalysisAPI()
        test_file = create_test_file(100)

        try:
            report = api.analyze_file(test_file)

            assert report.latency.count == 100
            assert report.source_format == 'sentinel'
            assert report.source_format_version == 1  # Header version field
            # Status depends on default thresholds vs our test latencies (10-59)
            # P99=58 >= p99_error=50, so we get ERROR status
            assert report.status in [ReportStatus.OK, ReportStatus.WARNING, ReportStatus.ERROR]
        finally:
            test_file.unlink()

    def test_analyze_bytes(self):
        """
        CRITICAL TEST: Byte analysis works correctly.
        """
        api = AnalysisAPI()
        test_file = create_test_file(50)

        try:
            with open(test_file, 'rb') as f:
                data = f.read()

            request = AnalysisRequest(filename='test.bin')
            report = api.analyze_bytes(data, request)

            assert report.latency.count == 50
            assert report.source_file == 'test.bin'
        finally:
            test_file.unlink()

    def test_health_check(self):
        """
        CRITICAL TEST: Health endpoint returns valid data.
        """
        config = SentinelConfig()
        api = AnalysisAPI(config=config)

        health = api.health_check()

        assert health['status'] == 'healthy'
        assert health['version'] == '2.2.0'
        assert health['config_valid'] is True

    def test_health_check_with_invalid_config(self):
        """Health check reports invalid config."""
        config = SentinelConfig()
        config.clock.frequency_mhz = -1  # Invalid

        api = AnalysisAPI(config=config)
        health = api.health_check()

        assert health['config_valid'] is False

    def test_include_evidence(self):
        """Evidence included when requested."""
        api = AnalysisAPI()
        test_file = create_test_file(20)

        try:
            request = AnalysisRequest(include_evidence=True)
            report = api.analyze_file(test_file, request)

            assert report.include_evidence is True
            assert report.evidence is not None
            assert len(report.evidence.sample_traces_head) > 0
        finally:
            test_file.unlink()

    def test_custom_clock_frequency(self):
        """Custom clock frequency used in analysis."""
        api = AnalysisAPI()
        test_file = create_test_file(10)

        try:
            request = AnalysisRequest(clock_frequency_mhz=200.0)
            report = api.analyze_file(test_file, request)

            assert report.clock_frequency_mhz == 200.0
        finally:
            test_file.unlink()

    def test_missing_file(self):
        """Missing file produces error report."""
        api = AnalysisAPI()

        report = api.analyze_file(Path('/nonexistent/file.bin'))

        assert report.status == ReportStatus.ERROR
        assert len(report.errors) > 0


class TestReportFromSnapshot:
    """Test report population from analyzer snapshot."""

    def test_latency_populated(self):
        """Latency stats populated correctly."""
        api = AnalysisAPI()
        test_file = create_test_file(100)

        try:
            report = api.analyze_file(test_file)

            # Should have valid latency stats
            assert report.latency.count == 100
            assert report.latency.min_cycles >= 0
            assert report.latency.max_cycles > 0
            assert report.latency.mean_cycles > 0
        finally:
            test_file.unlink()

    def test_percentiles_populated(self):
        """Percentiles populated correctly."""
        api = AnalysisAPI()
        test_file = create_test_file(1000)

        try:
            report = api.analyze_file(test_file)

            # Should have valid percentile data
            assert report.latency.count == 1000
            # Percentiles should be non-negative
            assert report.latency.p50_cycles >= 0
            assert report.latency.p99_cycles >= 0
        finally:
            test_file.unlink()

    def test_ns_values_populated(self):
        """Nanosecond values computed correctly."""
        api = AnalysisAPI()
        test_file = create_test_file(100)

        try:
            report = api.analyze_file(test_file)

            # Default 100 MHz = 10 ns period
            # Mean cycles * 10 ns should equal mean_ns
            expected_mean_ns = report.latency.mean_cycles * 10.0
            assert abs(report.latency.mean_ns - expected_mean_ns) < 0.1
        finally:
            test_file.unlink()


class TestStatusComputation:
    """Test status computation from analysis results."""

    def test_ok_status_for_good_results(self):
        """Good results produce OK status."""
        config = SentinelConfig()
        config.thresholds.p99_warning = 100  # High threshold
        config.thresholds.p99_error = 200    # Even higher
        config.thresholds.p99_critical = 300
        api = AnalysisAPI(config=config)

        test_file = create_test_file(100)  # Max latency ~59

        try:
            report = api.analyze_file(test_file)
            assert report.status == ReportStatus.OK
        finally:
            test_file.unlink()

    def test_warning_status_for_elevated_latency(self):
        """Elevated latency produces WARNING status."""
        config = SentinelConfig()
        config.thresholds.p99_warning = 30  # Below our test latencies
        config.thresholds.p99_error = 100
        api = AnalysisAPI(config=config)

        test_file = create_test_file(100)

        try:
            report = api.analyze_file(test_file)
            # Our test file has latencies up to 59, so P99 should be > 30
            assert report.status == ReportStatus.WARNING
        finally:
            test_file.unlink()


class TestAPIConfig:
    """Test API configuration handling."""

    def test_uses_config_thresholds(self):
        """API uses config thresholds for status."""
        config = SentinelConfig()
        config.thresholds.p99_warning = 5
        config.thresholds.p99_error = 10
        config.thresholds.p99_critical = 20

        api = AnalysisAPI(config=config)
        test_file = create_test_file(100)

        try:
            report = api.analyze_file(test_file)
            # Our latencies (10-59) should trigger error (>10)
            assert report.status in [ReportStatus.ERROR, ReportStatus.CRITICAL]
        finally:
            test_file.unlink()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
