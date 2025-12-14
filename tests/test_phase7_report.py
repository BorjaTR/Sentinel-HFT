"""
Tests for Phase 7: Report Schema with Evidence.

CRITICAL TESTS:
1. test_report_json_roundtrip - Reports must survive JSON serialization
2. test_evidence_compression - Evidence compresses correctly
3. test_status_computation - Status computed correctly from thresholds
"""

import pytest
import json

from sentinel_hft.core import (
    ErrorCode,
    SentinelError,
    TraceEvidence,
    DropEvidence,
    AnomalyEvidence,
    OverflowEvidence,
    EvidenceBundle,
    ReportStatus,
    AnalysisReport,
)


class TestErrorCodes:
    """Test error code system."""

    def test_error_code_format(self):
        """Error codes follow E{category}{number} format."""
        for code in ErrorCode:
            assert code.value.startswith('E')
            assert len(code.value) == 5

    def test_sentinel_error_to_dict(self):
        """SentinelError converts to dict."""
        error = SentinelError(
            code=ErrorCode.E2001_SEQUENCE_GAP,
            context={'core_id': 0, 'expected': 100, 'actual': 105},
        )

        d = error.to_dict()

        assert d['code'] == 'E2001'
        assert d['severity'] == 'warning'
        assert d['context']['expected'] == 100

    def test_error_message(self):
        """Error message includes context."""
        error = SentinelError(
            code=ErrorCode.E2001_SEQUENCE_GAP,
            context={'dropped': 5},
        )

        assert 'Gap detected' in error.message
        assert 'dropped' in error.message


class TestTraceEvidence:
    """Test trace evidence."""

    def test_trace_evidence_to_dict(self):
        """TraceEvidence serializes correctly."""
        trace = TraceEvidence(
            timestamp=1000000,
            seq_no=42,
            core_id=0,
            latency_cycles=15,
            record_type=1,
        )

        d = trace.to_dict()

        assert d['seq_no'] == 42
        assert d['latency_cycles'] == 15


class TestDropEvidence:
    """Test drop evidence."""

    def test_drop_evidence_with_traces(self):
        """DropEvidence includes surrounding traces."""
        drop = DropEvidence(
            timestamp=1000000,
            core_id=0,
            expected_seq=100,
            actual_seq=105,
            dropped_count=5,
            event_type='gap',
            traces_before=[TraceEvidence(0, 99, 0, 10, 1)],
            traces_after=[TraceEvidence(0, 105, 0, 10, 1)],
        )

        d = drop.to_dict()

        assert d['dropped_count'] == 5
        assert len(d['traces_before']) == 1
        assert len(d['traces_after']) == 1


class TestEvidenceBundle:
    """Test evidence bundle."""

    def test_evidence_bundle_json_roundtrip(self):
        """Evidence bundle survives JSON serialization."""
        bundle = EvidenceBundle(
            source_file='/path/to/traces.bin',
            source_format='sentinel',
            source_version=11,
        )

        bundle.add_trace_sample(TraceEvidence(0, 0, 0, 10, 1), 'head')
        bundle.add_trace_sample(TraceEvidence(0, 99, 0, 10, 1), 'tail')
        bundle.add_drop(DropEvidence(0, 0, 50, 55, 5, 'gap'))
        bundle.add_anomaly(AnomalyEvidence(0, 42, 0, 1000, 5.5, 0.999))
        bundle.add_overflow(OverflowEvidence(0, 0, 1000))

        json_str = bundle.to_json()
        restored = EvidenceBundle.from_json(json_str)

        assert restored.source_file == '/path/to/traces.bin'
        assert len(restored.sample_traces_head) == 1
        assert len(restored.sample_traces_tail) == 1
        assert len(restored.drop_events) == 1
        assert len(restored.anomaly_events) == 1
        assert len(restored.overflow_events) == 1

    def test_evidence_compression(self):
        """
        CRITICAL TEST: Evidence compresses correctly.

        Large evidence bundles must compress for efficient storage.
        """
        bundle = EvidenceBundle()

        # Add many traces
        for i in range(100):
            bundle.add_trace_sample(
                TraceEvidence(i * 1000, i, 0, 10 + i, 1),
                'head' if i < 50 else 'tail',
            )

        compressed = bundle.to_compressed()
        restored = EvidenceBundle.from_compressed(compressed)

        assert len(restored.sample_traces_head) == 50
        assert len(restored.sample_traces_tail) == 50

        # Compression should reduce size significantly
        json_size = len(bundle.to_json().encode())
        assert len(compressed) < json_size

    def test_evidence_base64_roundtrip(self):
        """Evidence survives base64 encoding."""
        bundle = EvidenceBundle(source_file='test.bin')
        bundle.add_anomaly(AnomalyEvidence(0, 42, 0, 500, 4.2, 0.99))

        b64 = bundle.to_base64()
        restored = EvidenceBundle.from_base64(b64)

        assert restored.source_file == 'test.bin'
        assert len(restored.anomaly_events) == 1

    def test_evidence_summary(self):
        """Summary counts are correct."""
        bundle = EvidenceBundle()
        bundle.add_trace_sample(TraceEvidence(0, 0, 0, 10, 1), 'head')
        bundle.add_drop(DropEvidence(0, 0, 50, 55, 5, 'gap'))
        bundle.add_drop(DropEvidence(0, 0, 100, 110, 10, 'gap'))

        summary = bundle.summary()

        assert summary['sample_traces'] == 1
        assert summary['drop_events'] == 2


class TestAnalysisReport:
    """Test analysis report."""

    def test_report_default_status(self):
        """Default report status is OK."""
        report = AnalysisReport()
        assert report.status == ReportStatus.OK

    def test_report_json_roundtrip(self):
        """
        CRITICAL TEST: Reports must survive JSON serialization.

        Reports are stored and transmitted as JSON.
        """
        report = AnalysisReport(
            source_file='/path/to/traces.bin',
            source_format='sentinel',
            source_format_version=11,
        )

        report.latency.count = 1000000
        report.latency.p99_cycles = 45
        report.latency.mean_cycles = 12.5
        report.drops.total_drops = 100
        report.drops.drop_rate = 0.0001

        json_str = report.to_json()
        restored = AnalysisReport.from_json(json_str)

        assert restored.source_file == '/path/to/traces.bin'
        assert restored.latency.count == 1000000
        assert restored.latency.p99_cycles == 45
        assert restored.drops.total_drops == 100

    def test_status_computation(self):
        """
        CRITICAL TEST: Status computed correctly from thresholds.
        """
        report = AnalysisReport()

        # OK case
        report.latency.p99_cycles = 5
        report.drops.drop_rate = 0.0
        report.anomalies.anomaly_rate = 0.0
        report.compute_status()
        assert report.status == ReportStatus.OK

        # WARNING case - P99 warning
        report.latency.p99_cycles = 15
        report.compute_status(p99_warning=10, p99_error=50)
        assert report.status == ReportStatus.WARNING

        # ERROR case - P99 error
        report.latency.p99_cycles = 60
        report.compute_status(p99_warning=10, p99_error=50)
        assert report.status == ReportStatus.ERROR

        # CRITICAL case - P99 critical
        report.latency.p99_cycles = 150
        report.compute_status(p99_critical=100)
        assert report.status == ReportStatus.CRITICAL

    def test_kill_switch_is_critical(self):
        """Kill switch trigger is always CRITICAL."""
        report = AnalysisReport()
        report.latency.p99_cycles = 5  # Good latency
        report.risk.kill_switch_triggered = True

        report.compute_status()

        assert report.status == ReportStatus.CRITICAL
        assert 'kill switch' in report.status_reason.lower()

    def test_cycles_to_ns_conversion(self):
        """Cycle to nanosecond conversion is correct."""
        report = AnalysisReport(clock_frequency_mhz=100.0)

        # 100 MHz = 10 ns period
        # 100 cycles * 10 ns = 1000 ns
        assert report.cycles_to_ns(100) == 1000.0

        report.clock_frequency_mhz = 200.0
        # 200 MHz = 5 ns period
        # 100 cycles * 5 ns = 500 ns
        assert report.cycles_to_ns(100) == 500.0

    def test_populate_ns_values(self):
        """NS values are populated correctly."""
        report = AnalysisReport(clock_frequency_mhz=100.0)
        report.latency.mean_cycles = 10.0
        report.latency.p99_cycles = 50.0
        report.latency.p999_cycles = 100.0

        report.populate_ns_values()

        assert report.latency.mean_ns == 100.0
        assert report.latency.p99_ns == 500.0
        assert report.latency.p999_ns == 1000.0

    def test_add_error(self):
        """Errors can be added to report."""
        report = AnalysisReport()

        error = SentinelError(
            code=ErrorCode.E2001_SEQUENCE_GAP,
            context={'dropped': 5},
        )
        report.add_error(error)

        assert len(report.errors) == 1
        assert report.errors[0]['code'] == 'E2001'

    def test_report_with_evidence(self):
        """Report can include evidence bundle."""
        report = AnalysisReport()
        report.evidence = EvidenceBundle(source_file='test.bin')
        report.include_evidence = True

        d = report.to_dict()

        assert 'evidence' in d
        assert d['evidence']['source']['file'] == 'test.bin'

    def test_report_summary(self):
        """Summary is human readable."""
        report = AnalysisReport()
        report.latency.count = 1000000
        report.latency.p99_cycles = 45
        report.status = ReportStatus.WARNING
        report.status_reason = "P99 above warning threshold"

        summary = report.summary()

        assert 'WARNING' in summary
        assert '1,000,000' in summary
        assert '45' in summary


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
