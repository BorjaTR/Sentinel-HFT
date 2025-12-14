"""
UDP collector for receiving traces from FPGA hardware.

Packet format:
    Header (24 bytes):
        magic:        u32  'SNTL' = 0x4C544E53
        version:      u16  Protocol version
        core_id:      u16  Source core
        seq_start:    u32  First seq_no in packet
        seq_end:      u32  Last seq_no in packet
        record_count: u16  Number of trace records
        reserved:     u16  Alignment padding
        crc32:        u32  CRC32 of payload (not header)

    Payload:
        N trace records (48 bytes each for v1.1)
"""

import socket
import struct
import zlib
import threading
import logging
from dataclasses import dataclass
from typing import Callable, Optional, List

from ..adapters.base import StandardTrace
from ..adapters.sentinel_adapter import SentinelV11Adapter
from ..streaming.sequence import SequenceTracker

logger = logging.getLogger(__name__)


@dataclass
class UDPPacketHeader:
    """
    Header for UDP trace packets.

    Layout (24 bytes):
        Offset  Size  Field
        0       4     magic (0x4C544E53 = 'SNTL')
        4       2     version
        6       2     core_id
        8       4     seq_start
        12      4     seq_end
        16      2     record_count
        18      2     reserved
        20      4     crc32
    """
    magic: int
    version: int
    core_id: int
    seq_start: int
    seq_end: int
    record_count: int
    reserved: int
    crc32: int

    # <IHHIIHHI = 4+2+2+4+4+2+2+4 = 24 bytes
    FORMAT = '<IHHIIHHI'
    SIZE = 24
    MAGIC = 0x4C544E53  # 'SNTL' little-endian

    @classmethod
    def decode(cls, data: bytes) -> 'UDPPacketHeader':
        """Decode header from bytes."""
        if len(data) < cls.SIZE:
            raise ValueError(f"Header too small: {len(data)} < {cls.SIZE}")

        values = struct.unpack(cls.FORMAT, data[:cls.SIZE])
        return cls(
            magic=values[0],
            version=values[1],
            core_id=values[2],
            seq_start=values[3],
            seq_end=values[4],
            record_count=values[5],
            reserved=values[6],
            crc32=values[7],
        )

    def encode(self) -> bytes:
        """Encode header to bytes."""
        return struct.pack(
            self.FORMAT,
            self.magic,
            self.version,
            self.core_id,
            self.seq_start,
            self.seq_end,
            self.record_count,
            self.reserved,
            self.crc32,
        )

    def is_valid(self) -> bool:
        """Check magic number."""
        return self.magic == self.MAGIC

    @staticmethod
    def compute_crc(payload: bytes) -> int:
        """Compute CRC32 for payload."""
        return zlib.crc32(payload) & 0xFFFFFFFF

    def verify_payload(self, payload: bytes) -> bool:
        """Verify CRC32 of payload matches header."""
        return self.compute_crc(payload) == self.crc32


# Verify struct size at import
_computed = struct.calcsize(UDPPacketHeader.FORMAT)
assert _computed == UDPPacketHeader.SIZE, \
    f"UDP header size mismatch: {_computed} != {UDPPacketHeader.SIZE}"


class UDPCollector:
    """
    Collect traces from FPGA over UDP.

    Example:
        def on_traces(traces):
            for trace in traces:
                analyzer.add(trace)

        collector = UDPCollector(port=5000, on_traces=on_traces)
        collector.start()
        # ... later ...
        collector.stop()
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 5000,
        on_traces: Optional[Callable[[List[StandardTrace]], None]] = None,
        on_drop: Optional[Callable[[int, int, int], None]] = None,
    ):
        self.host = host
        self.port = port
        self.on_traces = on_traces
        self.on_drop = on_drop

        self.socket: Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Statistics
        self.packets_received = 0
        self.packets_invalid = 0
        self.packets_crc_failed = 0
        self.traces_received = 0

        # Packet-level sequence tracking
        self.sequence_tracker = SequenceTracker()

        # Trace adapter
        self.adapter = SentinelV11Adapter()

    def start(self) -> None:
        """Start the collector."""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((self.host, self.port))
        self.socket.settimeout(1.0)

        self._running = True
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()

        logger.info(f"UDP collector listening on {self.host}:{self.port}")

    def stop(self) -> None:
        """Stop the collector."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        if self.socket:
            self.socket.close()
        logger.info("UDP collector stopped")

    def _receive_loop(self) -> None:
        """Main receive loop."""
        while self._running:
            try:
                data, addr = self.socket.recvfrom(65535)
                self._handle_packet(data)
            except socket.timeout:
                continue
            except Exception as e:
                logger.error(f"Receive error: {e}")

    def _handle_packet(self, data: bytes) -> None:
        """Handle a received UDP packet."""
        self.packets_received += 1

        if len(data) < UDPPacketHeader.SIZE:
            logger.warning(f"Packet too small: {len(data)} bytes")
            self.packets_invalid += 1
            return

        try:
            header = UDPPacketHeader.decode(data)
        except Exception as e:
            logger.warning(f"Failed to decode header: {e}")
            self.packets_invalid += 1
            return

        if not header.is_valid():
            logger.warning(f"Invalid magic: 0x{header.magic:08X}")
            self.packets_invalid += 1
            return

        payload = data[UDPPacketHeader.SIZE:]

        if not header.verify_payload(payload):
            logger.warning("CRC mismatch")
            self.packets_crc_failed += 1
            return

        # Check for dropped packets
        drop = self.sequence_tracker.check(
            header.core_id, header.seq_start, 0
        )
        if drop and self.on_drop:
            self.on_drop(header.core_id, drop.expected_seq, drop.actual_seq)

        # Decode traces
        traces = self._decode_traces(payload)
        self.traces_received += len(traces)

        if self.on_traces and traces:
            self.on_traces(traces)

    def _decode_traces(self, payload: bytes) -> List[StandardTrace]:
        """Decode trace records from payload."""
        traces = []
        rec_size = self.adapter.record_size()
        offset = 0

        while offset + rec_size <= len(payload):
            try:
                trace = self.adapter.decode(payload[offset:offset + rec_size])
                traces.append(trace)
            except Exception as e:
                logger.warning(f"Failed to decode trace at offset {offset}: {e}")
            offset += rec_size

        return traces

    def stats(self) -> dict:
        """Get collector statistics."""
        return {
            'packets_received': self.packets_received,
            'packets_invalid': self.packets_invalid,
            'packets_crc_failed': self.packets_crc_failed,
            'traces_received': self.traces_received,
            'drops': self.sequence_tracker.summary(),
        }
