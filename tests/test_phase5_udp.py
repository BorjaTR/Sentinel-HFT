"""
Tests for Phase 5: UDP Collector.

Tests verify:
1. UDP header struct is correct size (24 bytes)
2. CRC verification works
3. Packet decoding works
"""

import pytest
import struct
import zlib
from sentinel_hft.collectors.udp_collector import UDPPacketHeader, UDPCollector
from sentinel_hft.adapters.sentinel_adapter import SentinelV11Adapter
from sentinel_hft.adapters.base import StandardTrace


class TestUDPHeader:
    """Test UDP packet header."""

    def test_header_size_exactly_24(self):
        """Header must be exactly 24 bytes."""
        assert UDPPacketHeader.SIZE == 24
        assert struct.calcsize(UDPPacketHeader.FORMAT) == 24

    def test_header_roundtrip(self):
        """Header encodes and decodes correctly."""
        original = UDPPacketHeader(
            magic=UDPPacketHeader.MAGIC,
            version=1,
            core_id=3,
            seq_start=100,
            seq_end=109,
            record_count=10,
            reserved=0,
            crc32=0x12345678,
        )

        encoded = original.encode()
        assert len(encoded) == 24

        decoded = UDPPacketHeader.decode(encoded)
        assert decoded.magic == original.magic
        assert decoded.version == original.version
        assert decoded.core_id == original.core_id
        assert decoded.seq_start == original.seq_start
        assert decoded.seq_end == original.seq_end
        assert decoded.record_count == original.record_count
        assert decoded.crc32 == original.crc32

    def test_magic_validation(self):
        """Magic number is validated correctly."""
        valid = UDPPacketHeader(
            magic=UDPPacketHeader.MAGIC,
            version=1, core_id=0, seq_start=0, seq_end=0,
            record_count=0, reserved=0, crc32=0,
        )
        assert valid.is_valid()

        invalid = UDPPacketHeader(
            magic=0xDEADBEEF,
            version=1, core_id=0, seq_start=0, seq_end=0,
            record_count=0, reserved=0, crc32=0,
        )
        assert not invalid.is_valid()

    def test_crc_verification(self):
        """CRC verification works."""
        payload = b'test payload data 123'
        expected_crc = zlib.crc32(payload) & 0xFFFFFFFF

        header = UDPPacketHeader(
            magic=UDPPacketHeader.MAGIC,
            version=1, core_id=0, seq_start=0, seq_end=0,
            record_count=0, reserved=0, crc32=expected_crc,
        )

        assert header.verify_payload(payload)
        assert not header.verify_payload(b'wrong payload')


class TestPacketDecoding:
    """Test full packet decoding."""

    def test_decode_packet_with_traces(self):
        """Full packet with traces decodes correctly."""
        adapter = SentinelV11Adapter()
        traces_data = []

        for i in range(3):
            trace = StandardTrace(
                version=1, record_type=1, core_id=0, seq_no=i,
                t_ingress=i*100, t_egress=i*100+10,
                data=0xCAFE, flags=0, tx_id=i,
            )
            traces_data.append(adapter.encode(trace))

        payload = b''.join(traces_data)
        crc = zlib.crc32(payload) & 0xFFFFFFFF

        header = UDPPacketHeader(
            magic=UDPPacketHeader.MAGIC,
            version=1, core_id=0, seq_start=0, seq_end=2,
            record_count=3, reserved=0, crc32=crc,
        )

        assert header.is_valid()
        assert header.verify_payload(payload)

        # Decode traces from payload
        decoded = list(adapter.decode_bytes(payload))
        assert len(decoded) == 3

        for i, trace in enumerate(decoded):
            assert trace.seq_no == i
            assert trace.data == 0xCAFE

    def test_header_decode_too_small(self):
        """Decoding too-small header raises ValueError."""
        with pytest.raises(ValueError, match="too small"):
            UDPPacketHeader.decode(b'\x00' * 10)


class TestUDPCollector:
    """Test UDPCollector initialization."""

    def test_collector_initialization(self):
        """Collector initializes correctly."""
        collector = UDPCollector(port=5555)

        assert collector.port == 5555
        assert collector.packets_received == 0
        assert collector.traces_received == 0

    def test_collector_stats(self):
        """Stats returns expected format."""
        collector = UDPCollector()
        stats = collector.stats()

        assert 'packets_received' in stats
        assert 'packets_invalid' in stats
        assert 'packets_crc_failed' in stats
        assert 'traces_received' in stats
        assert 'drops' in stats


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
