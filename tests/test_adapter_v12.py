"""Tests for v1.2 adapter."""

import struct
import pytest
from pathlib import Path
import tempfile

from sentinel_hft.adapters.sentinel_adapter_v12 import (
    SentinelV12Adapter,
    TraceRecordV12,
    AttributedLatency,
    V12_STRUCT,
    V12_SIZE,
)


class TestAttributedLatency:
    """Tests for AttributedLatency dataclass."""

    def test_from_cycles_basic(self):
        """Test basic cycle to nanosecond conversion."""
        attr = AttributedLatency.from_cycles(
            t_ingress=0,
            t_egress=100,
            d_ingress=10,
            d_core=50,
            d_risk=20,
            d_egress=10,
            clock_mhz=100.0,  # 10ns per cycle
        )

        assert attr.total_ns == 1000.0  # 100 cycles * 10ns
        assert attr.ingress_ns == 100.0
        assert attr.core_ns == 500.0
        assert attr.risk_ns == 200.0
        assert attr.egress_ns == 100.0
        assert attr.overhead_ns == 100.0  # 100 - (10+50+20+10) = 10 cycles

    def test_bottleneck_detection(self):
        """Test that bottleneck is correctly identified."""
        attr = AttributedLatency.from_cycles(
            t_ingress=0,
            t_egress=100,
            d_ingress=5,
            d_core=60,  # Highest
            d_risk=20,
            d_egress=5,
            clock_mhz=100.0,
        )

        assert attr.bottleneck == 'core'
        assert attr.bottleneck_pct == pytest.approx(0.6, rel=0.01)

    def test_zero_latency(self):
        """Test handling of zero total latency."""
        attr = AttributedLatency.from_cycles(
            t_ingress=100,
            t_egress=100,  # Same
            d_ingress=0,
            d_core=0,
            d_risk=0,
            d_egress=0,
            clock_mhz=100.0,
        )

        assert attr.total_ns == 0.0
        assert attr.bottleneck_pct == 0.0

    def test_to_dict(self):
        """Test conversion to dict."""
        attr = AttributedLatency.from_cycles(
            t_ingress=0,
            t_egress=100,
            d_ingress=10,
            d_core=50,
            d_risk=20,
            d_egress=10,
            clock_mhz=100.0,
        )

        d = attr.to_dict()
        assert 'total_ns' in d
        assert 'bottleneck' in d
        assert 'bottleneck_pct' in d


class TestSentinelV12Adapter:
    """Tests for v1.2 adapter."""

    def create_test_file(self, records: list) -> Path:
        """Create a temporary trace file with given records."""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.bin')

        # Write file header (32 bytes)
        header = struct.pack(
            '<4sHHIIIIII',
            b'SNTL',     # magic
            1,           # version
            64,          # record_size (v1.2)
            0,           # flags
            0,           # reserved1
            0,           # reserved2
            0,           # reserved3
            0,           # reserved4
            0,           # reserved5
        )
        tmp.write(header)

        # Write records
        for rec in records:
            data = V12_STRUCT.pack(
                rec.get('version', 2),
                rec.get('record_type', 1),
                rec.get('core_id', 0),
                rec.get('seq_no', 0),
                rec.get('t_ingress', 0),
                rec.get('t_egress', 100),
                rec.get('t_host', 0),
                rec.get('tx_id', 0),
                rec.get('flags', 1),
                rec.get('d_ingress', 5),
                rec.get('d_core', 50),
                rec.get('d_risk', 20),
                rec.get('d_egress', 5),
            )
            tmp.write(data)

        tmp.close()
        return Path(tmp.name)

    def test_decode_single_record(self):
        """Test decoding a single record."""
        adapter = SentinelV12Adapter(clock_mhz=100.0)

        data = V12_STRUCT.pack(
            2,      # version
            1,      # record_type (TX_EVENT)
            42,     # core_id
            1000,   # seq_no
            500,    # t_ingress
            600,    # t_egress
            0,      # t_host
            123,    # tx_id
            1,      # flags
            10,     # d_ingress
            50,     # d_core
            25,     # d_risk
            10,     # d_egress
        )

        record = adapter.decode_record(data)

        assert record.version == 2
        assert record.record_type == 1
        assert record.core_id == 42
        assert record.seq_no == 1000
        assert record.t_ingress == 500
        assert record.t_egress == 600
        assert record.tx_id == 123
        assert record.d_ingress == 10
        assert record.d_core == 50
        assert record.d_risk == 25
        assert record.d_egress == 10
        assert record.latency_cycles == 100

    def test_iterate_file(self):
        """Test iterating over a trace file."""
        path = self.create_test_file([
            {'seq_no': 0, 't_ingress': 0, 't_egress': 100, 'd_core': 50},
            {'seq_no': 1, 't_ingress': 100, 't_egress': 200, 'd_core': 60},
            {'seq_no': 2, 't_ingress': 200, 't_egress': 300, 'd_core': 70},
        ])

        try:
            adapter = SentinelV12Adapter()
            records = list(adapter.iterate_file(path))

            assert len(records) == 3
            assert records[0].seq_no == 0
            assert records[1].seq_no == 1
            assert records[2].seq_no == 2
            assert records[0].d_core == 50
            assert records[1].d_core == 60
            assert records[2].d_core == 70
        finally:
            path.unlink()

    def test_iterate_with_attribution(self):
        """Test iteration with attribution data."""
        path = self.create_test_file([
            {
                'seq_no': 0,
                't_ingress': 0,
                't_egress': 100,
                'd_ingress': 5,
                'd_core': 50,
                'd_risk': 20,
                'd_egress': 5,
            },
        ])

        try:
            adapter = SentinelV12Adapter(clock_mhz=100.0)
            results = list(adapter.iterate_with_attribution(path))

            assert len(results) == 1
            trace, attr = results[0]

            # Check trace
            assert trace.seq_no == 0

            # Check attribution
            assert attr.core_ns == 500.0
            assert attr.overhead_ns == 200.0  # 100 - 80 = 20 cycles
            assert attr.bottleneck == 'core'
        finally:
            path.unlink()

    def test_record_size(self):
        """Test record size method."""
        adapter = SentinelV12Adapter()
        assert adapter.record_size() == 64


class TestFormatSize:
    """Tests for format size verification."""

    def test_v12_struct_size(self):
        """Test that v1.2 struct size is exactly 64 bytes."""
        assert V12_SIZE == 64
        assert V12_STRUCT.size == 64
