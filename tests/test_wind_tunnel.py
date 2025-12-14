"""Tests for Wind Tunnel (H2) components.

Tests input format parsing, trace pipeline, and metrics engine.
"""

import io
import struct
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'host'))
sys.path.insert(0, str(Path(__file__).parent.parent / 'wind_tunnel'))

from wind_tunnel.input_formats import (
    InputTransaction,
    parse_csv,
    parse_binary,
    detect_format,
    load_input,
    write_stimulus_binary,
    STIMULUS_RECORD_SIZE,
)

from wind_tunnel.trace_pipeline import (
    EnrichedTrace,
    ValidationResult,
    TracePipeline,
)

from host.metrics import (
    MetricsEngine,
    LatencyMetrics,
    ThroughputMetrics,
    AnomalyReport,
    FullMetrics,
    compute_metrics,
)

from host.report import (
    ReportGenerator,
    generate_json_report,
)


class TestInputTransaction:
    """Test InputTransaction dataclass."""

    def test_create_transaction(self):
        """Test basic transaction creation."""
        tx = InputTransaction(
            timestamp_ns=1000,
            data=0xDEADBEEF,
            opcode=0x0001,
            meta=100,
        )
        assert tx.timestamp_ns == 1000
        assert tx.data == 0xDEADBEEF
        assert tx.opcode == 0x0001
        assert tx.meta == 100

    def test_to_dict(self):
        """Test conversion to dictionary."""
        tx = InputTransaction(1000, 0xABCD, 1, 50)
        d = tx.to_dict()
        assert d['timestamp_ns'] == 1000
        assert d['data'] == 0xABCD

    def test_to_binary(self):
        """Test binary serialization."""
        tx = InputTransaction(1000, 0xDEADBEEF, 0x0001, 100)
        binary = tx.to_binary()
        assert len(binary) == STIMULUS_RECORD_SIZE  # 24 bytes

        # Verify structure
        timestamp, data, opcode, meta = struct.unpack('<QQHIxx', binary)
        assert timestamp == 1000
        assert data == 0xDEADBEEF
        assert opcode == 0x0001
        assert meta == 100


class TestCSVParsing:
    """Test CSV input parsing."""

    def test_parse_simple_csv(self):
        """Test parsing basic CSV."""
        csv_content = """timestamp_ns,data,opcode,meta
100,1234,1,50
200,5678,2,100
"""
        transactions = list(parse_csv(io.StringIO(csv_content)))
        assert len(transactions) == 2
        assert transactions[0].timestamp_ns == 100
        assert transactions[0].data == 1234
        assert transactions[1].opcode == 2

    def test_parse_hex_values(self):
        """Test parsing hex values."""
        csv_content = """timestamp_ns,data,opcode,meta
0,0xDEADBEEF,0x0001,0xFF
"""
        transactions = list(parse_csv(io.StringIO(csv_content)))
        assert transactions[0].data == 0xDEADBEEF
        assert transactions[0].opcode == 0x0001
        assert transactions[0].meta == 0xFF

    def test_parse_comments(self):
        """Test that comments are skipped."""
        csv_content = """# This is a comment
timestamp_ns,data,opcode,meta
# Another comment
100,1234,1,50
"""
        transactions = list(parse_csv(io.StringIO(csv_content)))
        assert len(transactions) == 1

    def test_parse_empty_lines(self):
        """Test that empty lines are skipped."""
        csv_content = """timestamp_ns,data,opcode,meta

100,1234,1,50

200,5678,2,100

"""
        transactions = list(parse_csv(io.StringIO(csv_content)))
        assert len(transactions) == 2


class TestBinaryParsing:
    """Test binary input parsing."""

    def test_parse_binary_records(self):
        """Test parsing binary stimulus file."""
        # Create binary records
        tx1 = InputTransaction(100, 0xABCD, 1, 50)
        tx2 = InputTransaction(200, 0xEF01, 2, 100)

        binary_data = tx1.to_binary() + tx2.to_binary()

        transactions = list(parse_binary(io.BytesIO(binary_data)))
        assert len(transactions) == 2
        assert transactions[0].timestamp_ns == 100
        assert transactions[0].data == 0xABCD
        assert transactions[1].timestamp_ns == 200

    def test_incomplete_record_error(self):
        """Test error on incomplete binary record."""
        incomplete = b'\x00' * 10  # Less than 24 bytes
        with pytest.raises(ValueError, match="Incomplete record"):
            list(parse_binary(io.BytesIO(incomplete)))


class TestFormatDetection:
    """Test input format detection."""

    def test_detect_csv_by_extension(self):
        """Test CSV detection by extension."""
        with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as f:
            f.write(b"timestamp_ns,data,opcode,meta\n")
            path = Path(f.name)

        try:
            assert detect_format(path) == 'csv'
        finally:
            path.unlink()

    def test_detect_binary_by_extension(self):
        """Test binary detection by extension."""
        with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as f:
            f.write(b'\x00' * 24)
            path = Path(f.name)

        try:
            assert detect_format(path) == 'binary'
        finally:
            path.unlink()


class TestLoadInput:
    """Test loading and sorting input files."""

    def test_load_csv_sorted(self):
        """Test that loaded CSV is sorted by timestamp."""
        csv_content = """timestamp_ns,data,opcode,meta
300,3,1,0
100,1,1,0
200,2,1,0
"""
        with tempfile.NamedTemporaryFile(suffix='.csv', mode='w', delete=False) as f:
            f.write(csv_content)
            path = Path(f.name)

        try:
            transactions = load_input(path)
            assert len(transactions) == 3
            assert transactions[0].timestamp_ns == 100
            assert transactions[1].timestamp_ns == 200
            assert transactions[2].timestamp_ns == 300
        finally:
            path.unlink()


class TestStimulusBinary:
    """Test stimulus binary writing."""

    def test_write_read_roundtrip(self):
        """Test write and read roundtrip."""
        transactions = [
            InputTransaction(100, 0xABCD, 1, 50),
            InputTransaction(200, 0xEF01, 2, 100),
        ]

        with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as f:
            path = Path(f.name)

        try:
            write_stimulus_binary(transactions, path)

            with open(path, 'rb') as f:
                loaded = list(parse_binary(f))

            assert len(loaded) == 2
            assert loaded[0].timestamp_ns == transactions[0].timestamp_ns
            assert loaded[0].data == transactions[0].data
        finally:
            path.unlink()


class TestMetricsEngine:
    """Test MetricsEngine class."""

    def test_compute_latency_empty(self):
        """Test latency computation with empty list."""
        engine = MetricsEngine()
        metrics = engine.compute_latency([])
        assert metrics.count == 0
        assert metrics.mean_cycles == 0

    def test_compute_latency_basic(self):
        """Test basic latency computation."""
        engine = MetricsEngine(clock_period_ns=10.0)
        latencies = [3, 4, 5, 3, 4, 5, 3, 4, 5, 6]
        metrics = engine.compute_latency(latencies)

        assert metrics.count == 10
        assert metrics.min_cycles == 3
        assert metrics.max_cycles == 6
        assert 4.0 <= metrics.mean_cycles <= 4.3
        assert metrics.clock_period_ns == 10.0

    def test_compute_latency_time_conversion(self):
        """Test time domain conversion."""
        engine = MetricsEngine(clock_period_ns=5.0)
        metrics = engine.compute_latency([10])

        assert metrics.min_cycles == 10
        assert metrics.min_ns == 50.0  # 10 cycles * 5 ns

    def test_compute_throughput(self):
        """Test throughput computation."""
        engine = MetricsEngine()
        ingress = [0, 10, 20, 30, 40]
        egress = [5, 15, 25, 35, 45]

        tp = engine.compute_throughput(ingress, egress)
        assert tp.total_transactions == 5
        assert tp.total_cycles == 45  # 45 - 0

    def test_detect_anomalies(self):
        """Test anomaly detection."""
        engine = MetricsEngine(anomaly_zscore=2.0)
        latencies = [3, 3, 3, 3, 3, 3, 3, 3, 3, 100]  # 100 is anomaly
        tx_ids = list(range(10))

        report = engine.detect_anomalies(latencies, tx_ids)
        assert report.count > 0
        assert report.anomalies[0].tx_id == 9  # The outlier
        assert report.anomalies[0].latency_cycles == 100

    def test_compute_full(self):
        """Test full metrics computation."""
        engine = MetricsEngine()

        # Create mock trace objects
        class MockTrace:
            def __init__(self, tx_id, t_in, t_out):
                self.tx_id = tx_id
                self.t_ingress = t_in
                self.t_egress = t_out
                self.latency_cycles = t_out - t_in

        traces = [
            MockTrace(0, 0, 5),
            MockTrace(1, 10, 14),
            MockTrace(2, 20, 25),
        ]

        metrics = engine.compute_full(traces)
        assert isinstance(metrics, FullMetrics)
        assert metrics.latency.count == 3
        assert metrics.throughput.total_transactions == 3


class TestBackwardsCompatibility:
    """Test H1 backwards compatibility."""

    def test_compute_metrics_function(self):
        """Test that H1 compute_metrics still works."""
        latencies = [3, 4, 5, 3, 4]
        metrics = compute_metrics(latencies, clock_period_ns=10.0)

        assert isinstance(metrics, LatencyMetrics)
        assert metrics.count == 5
        assert metrics.min_cycles == 3
        assert metrics.max_cycles == 5


class TestReportGenerator:
    """Test report generation."""

    def test_to_json(self):
        """Test JSON report generation."""
        engine = MetricsEngine()
        metrics = FullMetrics(
            latency=engine.compute_latency([3, 4, 5]),
            throughput=engine.compute_throughput([0, 10, 20], [5, 14, 25]),
            anomalies=AnomalyReport(),
            trace_count=3,
        )

        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = Path(f.name)

        try:
            gen = ReportGenerator()
            gen.to_json(metrics, path)

            # Read and verify
            import json
            with open(path) as f:
                data = json.load(f)

            assert 'latency' in data
            assert 'throughput' in data
            assert data['latency']['count'] == 3
        finally:
            path.unlink()

    def test_to_markdown(self):
        """Test Markdown report generation."""
        engine = MetricsEngine()
        metrics = FullMetrics(
            latency=engine.compute_latency([3, 4, 5]),
            throughput=engine.compute_throughput([0, 10, 20], [5, 14, 25]),
            anomalies=AnomalyReport(),
            trace_count=3,
        )

        with tempfile.NamedTemporaryFile(suffix='.md', delete=False) as f:
            path = Path(f.name)

        try:
            gen = ReportGenerator()
            gen.to_markdown(metrics, path)

            content = path.read_text()
            assert '# Sentinel-HFT' in content
            assert 'Latency' in content
            assert 'Throughput' in content
        finally:
            path.unlink()

    def test_histogram_data(self):
        """Test histogram data generation."""
        gen = ReportGenerator()
        latencies = list(range(10, 20))  # 10 to 19

        hist = gen.generate_histogram_data(latencies, num_bins=5)
        assert 'bins' in hist
        assert 'counts' in hist
        assert sum(hist['counts']) == 10

    def test_histogram_empty(self):
        """Test histogram with empty data."""
        gen = ReportGenerator()
        hist = gen.generate_histogram_data([])
        assert hist['bins'] == []
        assert hist['counts'] == []


class TestTracePipeline:
    """Test trace pipeline."""

    def test_create_pipeline(self):
        """Test pipeline creation."""
        pipeline = TracePipeline(clock_period_ns=5.0)
        assert pipeline.clock_period_ns == 5.0

    def test_filter_by_latency(self):
        """Test trace filtering by latency."""
        pipeline = TracePipeline()

        traces = [
            EnrichedTrace(tx_id=0, t_ingress=0, t_egress=5, latency_cycles=5,
                         latency_ns=50.0, flags=0, opcode=1, meta=0),
            EnrichedTrace(tx_id=1, t_ingress=10, t_egress=20, latency_cycles=10,
                         latency_ns=100.0, flags=0, opcode=1, meta=0),
            EnrichedTrace(tx_id=2, t_ingress=30, t_egress=33, latency_cycles=3,
                         latency_ns=30.0, flags=0, opcode=1, meta=0),
        ]

        filtered = list(pipeline.filter(traces, min_latency=4, max_latency=8))
        assert len(filtered) == 1
        assert filtered[0].tx_id == 0

    def test_filter_by_opcode(self):
        """Test filtering by opcode."""
        pipeline = TracePipeline()

        traces = [
            EnrichedTrace(tx_id=0, t_ingress=0, t_egress=5, latency_cycles=5,
                         latency_ns=50.0, flags=0, opcode=1, meta=0),
            EnrichedTrace(tx_id=1, t_ingress=10, t_egress=15, latency_cycles=5,
                         latency_ns=50.0, flags=0, opcode=2, meta=0),
        ]

        filtered = list(pipeline.filter(traces, opcodes=[1]))
        assert len(filtered) == 1
        assert filtered[0].opcode == 1


class TestSampleDataFile:
    """Test the sample market data file."""

    def test_load_sample_data(self):
        """Test loading sample market data."""
        sample_path = Path(__file__).parent.parent / 'wind_tunnel' / 'data' / 'sample_market.csv'

        if sample_path.exists():
            transactions = load_input(sample_path)
            assert len(transactions) == 20
            assert transactions[0].timestamp_ns == 0
            assert transactions[-1].timestamp_ns == 1900
