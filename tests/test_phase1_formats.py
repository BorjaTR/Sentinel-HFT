"""
Tests for Phase 1: Core Formats.

These tests verify:
1. File header encoding/decoding
2. Struct format sizes are correct
3. Header files decode correctly (header is skipped)
4. Legacy v1.0 files still work
"""

import pytest
import struct
import tempfile
from pathlib import Path

# Adjust imports based on actual package structure
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from sentinel_hft.formats.file_header import FileHeader, HEADER_SIZE, MAGIC
from sentinel_hft.formats.record_types import RecordType
from sentinel_hft.formats.reader import TraceReader, TraceFile
from sentinel_hft.adapters import auto_detect, SentinelV10Adapter, SentinelV11Adapter
from sentinel_hft.adapters.base import StandardTrace


class TestFileHeader:
    """Test file header functionality."""

    def test_header_size(self):
        """Header is exactly 32 bytes."""
        assert HEADER_SIZE == 32
        assert struct.calcsize(FileHeader.FORMAT) == 32

    def test_header_roundtrip(self):
        """Header encodes and decodes correctly."""
        original = FileHeader(
            version=1,
            record_size=48,
            clock_mhz=200,
            run_id=12345,
            record_count=1000,
        )

        encoded = original.encode()
        assert len(encoded) == HEADER_SIZE

        decoded = FileHeader.decode(encoded)
        assert decoded.version == original.version
        assert decoded.record_size == original.record_size
        assert decoded.clock_mhz == original.clock_mhz
        assert decoded.run_id == original.run_id
        assert decoded.record_count == original.record_count

    def test_magic_detection(self):
        """Magic bytes are detected correctly."""
        header = FileHeader()
        encoded = header.encode()

        assert encoded[:4] == MAGIC
        assert encoded[:4] == b'SNTL'

    def test_probe_valid_file(self, tmp_path):
        """probe() detects valid header files."""
        header = FileHeader(version=1, record_size=48)

        test_file = tmp_path / "with_header.bin"
        test_file.write_bytes(header.encode() + b'\x00' * 48)

        probed = FileHeader.probe(test_file)
        assert probed is not None
        assert probed.version == 1
        assert probed.record_size == 48

    def test_probe_no_header(self, tmp_path):
        """probe() returns None for files without header."""
        # Write some data that doesn't start with SNTL
        test_file = tmp_path / "no_header.bin"
        test_file.write_bytes(b'\x00' * 64)

        probed = FileHeader.probe(test_file)
        assert probed is None

    def test_header_validation(self):
        """Header validation catches invalid fields."""
        # Valid header
        valid = FileHeader()
        assert len(valid.validate()) == 0

        # Invalid magic
        invalid_magic = FileHeader(magic=b'XXXX')
        errors = invalid_magic.validate()
        assert any('magic' in e.lower() for e in errors)

    def test_header_with_string_magic(self):
        """Header accepts string magic and converts to bytes."""
        header = FileHeader(magic='SNTL')
        assert header.magic == b'SNTL'

    def test_decode_invalid_magic_raises(self):
        """Decoding invalid magic raises ValueError."""
        invalid_data = b'XXXX' + b'\x00' * 28
        with pytest.raises(ValueError, match="Invalid magic"):
            FileHeader.decode(invalid_data)

    def test_decode_too_small_raises(self):
        """Decoding too-small buffer raises ValueError."""
        with pytest.raises(ValueError, match="too small"):
            FileHeader.decode(b'SNTL')


class TestStructFormats:
    """Test that struct formats are correct sizes."""

    def test_v10_format_size(self):
        """v1.0 format is exactly 32 bytes."""
        adapter = SentinelV10Adapter()
        assert adapter.record_size() == 32
        assert struct.calcsize('<QQQHHI') == 32

    def test_v11_format_size(self):
        """v1.1 format is exactly 48 bytes."""
        adapter = SentinelV11Adapter()
        assert adapter.record_size() == 48

        # Decode format (first 36 bytes)
        assert struct.calcsize('<BBHIQQQHH') == 36

    def test_v10_roundtrip(self):
        """v1.0 encode/decode roundtrip works."""
        original = StandardTrace(
            version=0, record_type=1, core_id=0, seq_no=0,
            t_ingress=1000, t_egress=1005, data=0xDEADBEEF,
            flags=0x0100, tx_id=42,
        )

        adapter = SentinelV10Adapter()
        encoded = adapter.encode(original)
        assert len(encoded) == 32

        decoded = adapter.decode(encoded)
        assert decoded.t_ingress == original.t_ingress
        assert decoded.t_egress == original.t_egress
        assert decoded.data == original.data
        assert decoded.flags == original.flags
        assert decoded.tx_id == original.tx_id

    def test_v11_roundtrip(self):
        """v1.1 encode/decode roundtrip works."""
        original = StandardTrace(
            version=1, record_type=1, core_id=3, seq_no=12345,
            t_ingress=1000, t_egress=1005, data=0xDEADBEEF,
            flags=0x0100, tx_id=42,
        )

        adapter = SentinelV11Adapter()
        encoded = adapter.encode(original)
        assert len(encoded) == 48

        decoded = adapter.decode(encoded)
        assert decoded.version == original.version
        assert decoded.record_type == original.record_type
        assert decoded.core_id == original.core_id
        assert decoded.seq_no == original.seq_no
        assert decoded.t_ingress == original.t_ingress
        assert decoded.t_egress == original.t_egress
        assert decoded.data == original.data
        assert decoded.flags == original.flags
        assert decoded.tx_id == original.tx_id

    def test_v10_decode_too_small_raises(self):
        """v1.0 decode with too-small buffer raises ValueError."""
        adapter = SentinelV10Adapter()
        with pytest.raises(ValueError, match="too small"):
            adapter.decode(b'\x00' * 16)

    def test_v11_decode_too_small_raises(self):
        """v1.1 decode with too-small buffer raises ValueError."""
        adapter = SentinelV11Adapter()
        with pytest.raises(ValueError, match="too small"):
            adapter.decode(b'\x00' * 32)


class TestTraceReader:
    """Test TraceReader with headers."""

    def _create_v11_records(self, count: int) -> bytes:
        """Create v1.1 format records."""
        adapter = SentinelV11Adapter()
        records = []

        for i in range(count):
            trace = StandardTrace(
                version=1, record_type=1, core_id=0, seq_no=i,
                t_ingress=i * 100, t_egress=i * 100 + 5,
                data=0xDEADBEEF, flags=0, tx_id=i,
            )
            records.append(adapter.encode(trace))

        return b''.join(records)

    def test_header_file_decodes_correctly(self, tmp_path):
        """File with header decodes same records as without."""
        # Use 99 records: 99 * 48 = 4752 bytes, NOT divisible by 32
        # This ensures auto-detect picks v1.1 format for the no-header file
        record_data = self._create_v11_records(99)

        # Write file WITHOUT header
        no_header_file = tmp_path / "no_header.bin"
        no_header_file.write_bytes(record_data)

        # Write file WITH header
        header = FileHeader(version=1, record_size=48, record_count=99)
        with_header_file = tmp_path / "with_header.bin"
        with_header_file.write_bytes(header.encode() + record_data)

        # Read both
        traces_no_header = list(TraceReader.read_path(no_header_file))
        traces_with_header = list(TraceReader.read_path(with_header_file))

        # Must have same count
        assert len(traces_no_header) == 99
        assert len(traces_with_header) == 99

        # Must have identical records
        for t1, t2 in zip(traces_no_header, traces_with_header):
            assert t1.seq_no == t2.seq_no
            assert t1.t_ingress == t2.t_ingress
            assert t1.t_egress == t2.t_egress
            assert t1.data == t2.data

    def test_v10_file_still_decodes(self, tmp_path):
        """Legacy v1.0 files without header still work."""
        adapter = SentinelV10Adapter()
        records = []

        for i in range(10):
            trace = StandardTrace(
                version=0, record_type=1, core_id=0, seq_no=0,
                t_ingress=i * 100, t_egress=i * 100 + 5,
                data=0xDEADBEEF, flags=0, tx_id=i,
            )
            records.append(adapter.encode(trace))

        v10_file = tmp_path / "legacy.bin"
        v10_file.write_bytes(b''.join(records))

        # auto_detect should identify as v1.0
        detected_adapter, detected_header = auto_detect(v10_file)
        assert isinstance(detected_adapter, SentinelV10Adapter)
        assert detected_header is None

        # Should read all records
        traces = list(TraceReader.read_path(v10_file))
        assert len(traces) == 10

        # Verify data
        for i, trace in enumerate(traces):
            assert trace.t_ingress == i * 100
            assert trace.t_egress == i * 100 + 5

    def test_header_not_decoded_as_record(self, tmp_path):
        """Header bytes are not incorrectly decoded as a record."""
        # Create file with header + 1 record
        header = FileHeader(version=1, record_size=48)

        adapter = SentinelV11Adapter()
        record = adapter.encode(StandardTrace(
            version=1, record_type=1, core_id=0, seq_no=42,
            t_ingress=1000, t_egress=1005, data=0xCAFEBABE,
            flags=0, tx_id=99,
        ))

        test_file = tmp_path / "one_record.bin"
        test_file.write_bytes(header.encode() + record)

        traces = list(TraceReader.read_path(test_file))

        # Should have exactly 1 trace
        assert len(traces) == 1

        # And it should be the real record, not garbage from header
        assert traces[0].seq_no == 42
        assert traces[0].t_ingress == 1000
        assert traces[0].data == 0xCAFEBABE
        assert traces[0].tx_id == 99

    def test_trace_file_properties(self, tmp_path):
        """TraceFile properties work correctly."""
        header = FileHeader(version=1, record_size=48, clock_mhz=200)
        record_data = self._create_v11_records(10)

        test_file = tmp_path / "test.bin"
        test_file.write_bytes(header.encode() + record_data)

        trace_file = TraceReader.open(test_file)

        assert trace_file.has_header is True
        assert trace_file.clock_mhz == 200
        assert trace_file.record_size == 48
        assert trace_file.data_offset == HEADER_SIZE

    def test_count_records(self, tmp_path):
        """count() returns correct record count."""
        # Use 49 records: 49 * 48 = 2352 bytes, NOT divisible by 32
        record_data = self._create_v11_records(49)

        # Without header
        no_header_file = tmp_path / "no_header.bin"
        no_header_file.write_bytes(record_data)
        assert TraceReader.count(no_header_file) == 49

        # With header
        header = FileHeader(version=1, record_size=48, record_count=49)
        with_header_file = tmp_path / "with_header.bin"
        with_header_file.write_bytes(header.encode() + record_data)
        assert TraceReader.count(with_header_file) == 49

    def test_file_not_found_raises(self):
        """Reading non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            TraceReader.open(Path("/nonexistent/file.bin"))


class TestRecordTypes:
    """Test record type constants."""

    def test_type_values(self):
        """Record types have expected values."""
        assert RecordType.TX_EVENT == 0x01
        assert RecordType.OVERFLOW == 0x02
        assert RecordType.HEARTBEAT == 0x03

    def test_type_names(self):
        """Record type names are correct."""
        assert RecordType.name(0x01) == 'TX_EVENT'
        assert RecordType.name(0x02) == 'OVERFLOW'
        assert RecordType.name(0xFF) == 'UNKNOWN(255)'

    def test_type_validation(self):
        """is_valid() correctly identifies known types."""
        assert RecordType.is_valid(0x01) is True
        assert RecordType.is_valid(0x02) is True
        assert RecordType.is_valid(0xFF) is False
        assert RecordType.is_valid(0x00) is False


class TestAutoDetect:
    """Test format auto-detection."""

    def test_detect_v10_by_size(self, tmp_path):
        """Detect v1.0 format by file size divisibility."""
        # 32 * 10 = 320 bytes, divisible by 32
        test_file = tmp_path / "v10.bin"
        test_file.write_bytes(b'\x00' * 320)

        adapter, header = auto_detect(test_file)
        assert isinstance(adapter, SentinelV10Adapter)
        assert header is None

    def test_detect_v11_by_header(self, tmp_path):
        """Detect v1.1 format by SNTL header."""
        header = FileHeader(version=1, record_size=48)
        test_file = tmp_path / "v11.bin"
        test_file.write_bytes(header.encode() + b'\x00' * 48)

        adapter, header_result = auto_detect(test_file)
        assert isinstance(adapter, SentinelV11Adapter)
        assert header_result is not None
        assert header_result.record_size == 48

    def test_detect_csv_by_extension(self, tmp_path):
        """Detect CSV format by .csv extension."""
        from sentinel_hft.adapters import CSVAdapter

        test_file = tmp_path / "test.csv"
        test_file.write_text("t_ingress,t_egress,data\n1000,1005,0xDEAD\n")

        adapter, header = auto_detect(test_file)
        assert isinstance(adapter, CSVAdapter)
        assert header is None

    def test_detect_fails_for_invalid_size(self, tmp_path):
        """Detection fails for files with invalid size."""
        # 33 bytes - not divisible by 32 or 48
        test_file = tmp_path / "invalid.bin"
        test_file.write_bytes(b'\x00' * 33)

        with pytest.raises(ValueError, match="Cannot detect format"):
            auto_detect(test_file)

    def test_detect_fails_for_nonexistent(self):
        """Detection fails for non-existent files."""
        with pytest.raises(ValueError, match="not found"):
            auto_detect(Path("/nonexistent/file.bin"))


class TestStandardTrace:
    """Test StandardTrace dataclass."""

    def test_latency_property(self):
        """latency property computes correctly."""
        trace = StandardTrace(
            version=1, record_type=1, core_id=0, seq_no=0,
            t_ingress=1000, t_egress=1005, data=0, flags=0, tx_id=0,
        )
        assert trace.latency == 5

    def test_repr(self):
        """__repr__ returns useful string."""
        trace = StandardTrace(
            version=1, record_type=1, core_id=0, seq_no=42,
            t_ingress=1000, t_egress=1005, data=0, flags=0x0100, tx_id=0,
        )
        repr_str = repr(trace)
        assert 'seq=42' in repr_str
        assert 'latency=5' in repr_str
        assert '0x0100' in repr_str


class TestAdapterValidation:
    """Test adapter validation."""

    def test_validate_egress_before_ingress(self):
        """Validation catches egress before ingress."""
        adapter = SentinelV10Adapter()
        trace = StandardTrace(
            version=0, record_type=1, core_id=0, seq_no=0,
            t_ingress=1000, t_egress=500,  # Invalid: egress < ingress
            data=0, flags=0, tx_id=0,
        )
        error = adapter.validate(trace)
        assert error is not None
        assert 'Egress before ingress' in error

    def test_validate_high_latency(self):
        """Validation catches suspiciously high latency."""
        adapter = SentinelV10Adapter()
        trace = StandardTrace(
            version=0, record_type=1, core_id=0, seq_no=0,
            t_ingress=0, t_egress=100_000_000,  # Very high latency
            data=0, flags=0, tx_id=0,
        )
        error = adapter.validate(trace)
        assert error is not None
        assert 'high latency' in error.lower()

    def test_validate_normal_trace(self):
        """Validation passes for normal trace."""
        adapter = SentinelV10Adapter()
        trace = StandardTrace(
            version=0, record_type=1, core_id=0, seq_no=0,
            t_ingress=1000, t_egress=1005,
            data=0, flags=0, tx_id=0,
        )
        error = adapter.validate(trace)
        assert error is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
