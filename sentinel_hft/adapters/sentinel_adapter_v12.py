"""
sentinel_adapter_v12.py - Decoder for v1.2 trace records with attribution

v1.2 format: 64 bytes
- Bytes 0-47:  v1.1 header (unchanged)
- Bytes 48-51: d_ingress (u32 cycles)
- Bytes 52-55: d_core (u32 cycles)
- Bytes 56-59: d_risk (u32 cycles)
- Bytes 60-63: d_egress (u32 cycles)
"""

import struct
from dataclasses import dataclass
from typing import Iterator, Optional
from pathlib import Path

from .base import TraceAdapter, StandardTrace


# v1.2 struct format: v1.1 header (36 bytes) + reserved (12 bytes) + 4x u32 deltas (16 bytes) = 64 bytes
# <  = little-endian
# BB = version (u8), record_type (u8)
# H  = core_id (u16)
# I  = seq_no (u32)
# Q  = t_ingress (u64)
# Q  = t_egress (u64)
# Q  = t_host/data (u64)
# H  = tx_id (u16)
# H  = flags (u16)
# 12x = reserved padding (12 bytes, for v1.1 compatibility)
# IIII = d_ingress, d_core, d_risk, d_egress (4x u32)
V12_STRUCT = struct.Struct('<BBHIQQQHH12xIIII')
V12_SIZE = 64

assert V12_STRUCT.size == V12_SIZE, f"v1.2 struct size mismatch: {V12_STRUCT.size} != {V12_SIZE}"


@dataclass
class AttributedLatency:
    """Breakdown of latency by pipeline stage."""
    total_ns: float
    ingress_ns: float
    core_ns: float
    risk_ns: float
    egress_ns: float
    overhead_ns: float  # Queueing between stages

    @property
    def stages(self) -> dict:
        return {
            'ingress': self.ingress_ns,
            'core': self.core_ns,
            'risk': self.risk_ns,
            'egress': self.egress_ns,
            'overhead': self.overhead_ns,
        }

    @property
    def bottleneck(self) -> str:
        """Return the stage with highest latency contribution."""
        return max(self.stages.items(), key=lambda x: x[1])[0]

    @property
    def bottleneck_pct(self) -> float:
        """Percentage of total latency from bottleneck stage."""
        if self.total_ns == 0:
            return 0.0
        return self.stages[self.bottleneck] / self.total_ns

    def to_dict(self) -> dict:
        return {
            'total_ns': self.total_ns,
            'ingress_ns': self.ingress_ns,
            'core_ns': self.core_ns,
            'risk_ns': self.risk_ns,
            'egress_ns': self.egress_ns,
            'overhead_ns': self.overhead_ns,
            'bottleneck': self.bottleneck,
            'bottleneck_pct': round(self.bottleneck_pct, 4),
        }

    @classmethod
    def from_cycles(
        cls,
        t_ingress: int,
        t_egress: int,
        d_ingress: int,
        d_core: int,
        d_risk: int,
        d_egress: int,
        clock_mhz: float = 100.0
    ) -> 'AttributedLatency':
        """Create from cycle counts, converting to nanoseconds."""
        ns_per_cycle = 1000.0 / clock_mhz

        total_cycles = t_egress - t_ingress
        stage_sum = d_ingress + d_core + d_risk + d_egress
        overhead_cycles = max(0, total_cycles - stage_sum)

        return cls(
            total_ns=total_cycles * ns_per_cycle,
            ingress_ns=d_ingress * ns_per_cycle,
            core_ns=d_core * ns_per_cycle,
            risk_ns=d_risk * ns_per_cycle,
            egress_ns=d_egress * ns_per_cycle,
            overhead_ns=overhead_cycles * ns_per_cycle,
        )


@dataclass
class TraceRecordV12:
    """Parsed v1.2 trace record."""
    version: int
    record_type: int
    core_id: int
    seq_no: int
    t_ingress: int
    t_egress: int
    t_host: int
    tx_id: int
    flags: int
    d_ingress: int
    d_core: int
    d_risk: int
    d_egress: int

    @property
    def latency_cycles(self) -> int:
        return self.t_egress - self.t_ingress

    def get_attribution(self, clock_mhz: float = 100.0) -> AttributedLatency:
        """Get latency breakdown in nanoseconds."""
        return AttributedLatency.from_cycles(
            t_ingress=self.t_ingress,
            t_egress=self.t_egress,
            d_ingress=self.d_ingress,
            d_core=self.d_core,
            d_risk=self.d_risk,
            d_egress=self.d_egress,
            clock_mhz=clock_mhz,
        )

    def to_standard(self, clock_mhz: float = 100.0) -> StandardTrace:
        """Convert to StandardTrace format."""
        return StandardTrace(
            version=self.version,
            record_type=self.record_type,
            core_id=self.core_id,
            seq_no=self.seq_no,
            t_ingress=self.t_ingress,
            t_egress=self.t_egress,
            data=0,
            flags=self.flags,
            tx_id=self.tx_id,
        )


class SentinelV12Adapter(TraceAdapter):
    """Adapter for v1.2 trace files."""

    FORMAT_NAME = "sentinel_v1.2"
    RECORD_SIZE = V12_SIZE

    def __init__(self, clock_mhz: float = 100.0):
        self.clock_mhz = clock_mhz

    def record_size(self) -> int:
        """Return record size in bytes."""
        return V12_SIZE

    def decode(self, data: bytes) -> StandardTrace:
        """Decode a single record to StandardTrace."""
        record = self.decode_record(data)
        return record.to_standard(self.clock_mhz)

    def encode(self, trace: StandardTrace) -> bytes:
        """Encode a StandardTrace to bytes."""
        return V12_STRUCT.pack(
            trace.version,
            trace.record_type,
            trace.core_id,
            trace.seq_no,
            trace.t_ingress,
            trace.t_egress,
            0,  # t_host
            trace.tx_id,
            trace.flags,
            0,  # d_ingress
            0,  # d_core
            0,  # d_risk
            0,  # d_egress
        )

    def decode_record(self, data: bytes) -> TraceRecordV12:
        """Decode a single 64-byte record."""
        if len(data) != V12_SIZE:
            raise ValueError(f"Expected {V12_SIZE} bytes, got {len(data)}")

        unpacked = V12_STRUCT.unpack(data)

        return TraceRecordV12(
            version=unpacked[0],
            record_type=unpacked[1],
            core_id=unpacked[2],
            seq_no=unpacked[3],
            t_ingress=unpacked[4],
            t_egress=unpacked[5],
            t_host=unpacked[6],
            tx_id=unpacked[7],
            flags=unpacked[8],
            d_ingress=unpacked[9],
            d_core=unpacked[10],
            d_risk=unpacked[11],
            d_egress=unpacked[12],
        )

    def iterate_file(self, path: Path) -> Iterator[TraceRecordV12]:
        """Iterate over records in a trace file."""
        from ..formats.file_header import HEADER_SIZE, MAGIC

        with open(path, 'rb') as f:
            # Check for file header
            header = f.read(HEADER_SIZE)
            if not header.startswith(MAGIC):
                # No header, reset to beginning
                f.seek(0)

            while True:
                data = f.read(V12_SIZE)
                if len(data) == 0:
                    break
                if len(data) != V12_SIZE:
                    raise ValueError(f"Incomplete record: {len(data)} bytes")

                yield self.decode_record(data)

    def iterate_with_attribution(
        self,
        path: Path
    ) -> Iterator[tuple]:
        """Iterate yielding both standard trace and attribution."""
        for record in self.iterate_file(path):
            yield (
                record.to_standard(self.clock_mhz),
                record.get_attribution(self.clock_mhz),
            )
