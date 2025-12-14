"""
Adapters for Sentinel-HFT native trace formats.

Two formats are supported:
- v1.0: Legacy 32-byte format without sequence numbers
- v1.1: Modern 48-byte format with sequence numbers and record types

CRITICAL: The struct formats must be exactly correct or traces will be garbage.
"""

import struct
from .base import TraceAdapter, StandardTrace


class SentinelV10Adapter(TraceAdapter):
    """
    Adapter for legacy v1.0 32-byte format.

    This format does NOT have sequence numbers, so drop detection is not possible.

    Layout (32 bytes):
        Bytes 0-7:   t_ingress  (u64) Ingress timestamp
        Bytes 8-15:  t_egress   (u64) Egress timestamp
        Bytes 16-23: data       (u64) Transaction data
        Bytes 24-25: flags      (u16) Status flags
        Bytes 26-27: tx_id      (u16) Transaction ID
        Bytes 28-31: padding    (u32) Unused padding

    Total: 8 + 8 + 8 + 2 + 2 + 4 = 32 bytes

    CRITICAL: Format is '<QQQHHI' (NOT '<QQQHHQ' which would be 36 bytes!)
    """

    # Q=u64, Q=u64, Q=u64, H=u16, H=u16, I=u32
    FORMAT = '<QQQHHI'
    SIZE = 32

    def __init__(self):
        # Verify format at instantiation
        computed = struct.calcsize(self.FORMAT)
        assert computed == self.SIZE, \
            f"v1.0 format size mismatch: {computed} != {self.SIZE}"

    def record_size(self) -> int:
        return self.SIZE

    def decode(self, raw: bytes) -> StandardTrace:
        if len(raw) < self.SIZE:
            raise ValueError(f"Buffer too small: {len(raw)} < {self.SIZE}")

        t_ingress, t_egress, data, flags, tx_id, _pad = struct.unpack(
            self.FORMAT, raw[:self.SIZE]
        )

        return StandardTrace(
            version=0,
            record_type=0x01,  # Assume TX_EVENT for legacy format
            core_id=0,         # No core ID in v1.0
            seq_no=0,          # No sequence number in v1.0
            t_ingress=t_ingress,
            t_egress=t_egress,
            data=data,
            flags=flags,
            tx_id=tx_id,
        )

    @staticmethod
    def encode(trace: StandardTrace) -> bytes:
        """Encode a trace to v1.0 format."""
        return struct.pack(
            SentinelV10Adapter.FORMAT,
            trace.t_ingress,
            trace.t_egress,
            trace.data,
            trace.flags,
            trace.tx_id,
            0,  # padding
        )


class SentinelV11Adapter(TraceAdapter):
    """
    Adapter for v1.1 48-byte format with sequence numbers.

    This format includes sequence numbers for drop detection and record types
    for distinguishing between transaction events, overflow markers, etc.

    Layout (48 bytes):
        Byte 0:      version    (u8)  Format version (1)
        Byte 1:      type       (u8)  Record type (TX_EVENT=1, OVERFLOW=2, etc.)
        Bytes 2-3:   core_id    (u16) Source core ID
        Bytes 4-7:   seq_no     (u32) Monotonic sequence number
        Bytes 8-15:  t_ingress  (u64) Ingress timestamp
        Bytes 16-23: t_egress   (u64) Egress timestamp
        Bytes 24-31: data       (u64) Transaction data
        Bytes 32-33: flags      (u16) Status flags
        Bytes 34-35: tx_id      (u16) Transaction ID
        Bytes 36-47: reserved   (12 bytes) Reserved for future use

    Total: 1 + 1 + 2 + 4 + 8 + 8 + 8 + 2 + 2 + 12 = 48 bytes

    The decode format unpacks the first 36 bytes; the 12 reserved bytes are ignored.
    """

    # B=u8, B=u8, H=u16, I=u32, Q=u64, Q=u64, Q=u64, H=u16, H=u16
    DECODE_FORMAT = '<BBHIQQQHH'
    DECODE_SIZE = 36  # First 36 bytes contain all fields

    SIZE = 48  # Total record size including reserved bytes

    def __init__(self):
        # Verify format at instantiation
        computed = struct.calcsize(self.DECODE_FORMAT)
        assert computed == self.DECODE_SIZE, \
            f"v1.1 decode format size mismatch: {computed} != {self.DECODE_SIZE}"

    def record_size(self) -> int:
        return self.SIZE

    def decode(self, raw: bytes) -> StandardTrace:
        if len(raw) < self.SIZE:
            raise ValueError(f"Buffer too small: {len(raw)} < {self.SIZE}")

        # Unpack first 36 bytes (ignore 12 reserved bytes)
        (
            version,
            record_type,
            core_id,
            seq_no,
            t_ingress,
            t_egress,
            data,
            flags,
            tx_id,
        ) = struct.unpack(self.DECODE_FORMAT, raw[:self.DECODE_SIZE])

        return StandardTrace(
            version=version,
            record_type=record_type,
            core_id=core_id,
            seq_no=seq_no,
            t_ingress=t_ingress,
            t_egress=t_egress,
            data=data,
            flags=flags,
            tx_id=tx_id,
        )

    @staticmethod
    def encode(trace: StandardTrace) -> bytes:
        """Encode a trace to v1.1 format."""
        packed = struct.pack(
            SentinelV11Adapter.DECODE_FORMAT,
            trace.version,
            trace.record_type,
            trace.core_id,
            trace.seq_no,
            trace.t_ingress,
            trace.t_egress,
            trace.data,
            trace.flags,
            trace.tx_id,
        )
        # Add 12 bytes of padding for reserved field
        return packed + b'\x00' * 12


# Verify struct sizes at module load
assert struct.calcsize(SentinelV10Adapter.FORMAT) == SentinelV10Adapter.SIZE, \
    "v1.0 adapter format verification failed"
assert struct.calcsize(SentinelV11Adapter.DECODE_FORMAT) == SentinelV11Adapter.DECODE_SIZE, \
    "v1.1 adapter format verification failed"
