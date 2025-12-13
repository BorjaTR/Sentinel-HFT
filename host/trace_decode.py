#!/usr/bin/env python3
"""Decode binary trace records to JSONL.

This module decodes binary trace records emitted by the Sentinel Shell
RTL instrumentation wrapper.

Trace Record Binary Format (32 bytes, little-endian):
  Offset  Size  Field
  0       8     tx_id      (uint64)
  8       8     t_ingress  (uint64)
  16      8     t_egress   (uint64)
  24      2     flags      (uint16)
  26      2     opcode     (uint16)
  28      4     meta       (uint32)

Usage:
    python trace_decode.py <trace.bin>

    Output is JSONL (one JSON object per line) to stdout.
"""

import struct
import json
import sys
from dataclasses import dataclass, asdict
from typing import Iterator, BinaryIO, List, Optional


# Trace record size in bytes (256 bits)
TRACE_RECORD_SIZE = 32

# Struct format: little-endian, 3x uint64, uint16, uint16, uint32
TRACE_FORMAT = '<QQQHHI'


# Flag bit definitions (must match trace_pkg.sv)
class TraceFlags:
    NONE           = 0x0000
    TRACE_DROPPED  = 0x0001
    CORE_ERROR     = 0x0002
    INFLIGHT_UNDER = 0x0004
    RESERVED       = 0x8000


@dataclass
class TraceRecord:
    """Decoded trace record from Sentinel Shell."""
    tx_id: int
    t_ingress: int
    t_egress: int
    flags: int
    opcode: int
    meta: int

    @property
    def latency_cycles(self) -> int:
        """Compute latency in clock cycles."""
        return self.t_egress - self.t_ingress

    @property
    def has_error(self) -> bool:
        """Check if core reported an error."""
        return bool(self.flags & TraceFlags.CORE_ERROR)

    @property
    def trace_dropped(self) -> bool:
        """Check if trace was dropped due to FIFO overflow."""
        return bool(self.flags & TraceFlags.TRACE_DROPPED)

    @property
    def inflight_underflow(self) -> bool:
        """Check if egress occurred without matching ingress."""
        return bool(self.flags & TraceFlags.INFLIGHT_UNDER)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'tx_id': self.tx_id,
            't_ingress': self.t_ingress,
            't_egress': self.t_egress,
            'latency_cycles': self.latency_cycles,
            'flags': self.flags,
            'opcode': self.opcode,
            'meta': self.meta,
        }

    def to_bytes(self) -> bytes:
        """Serialize to binary format."""
        return struct.pack(
            TRACE_FORMAT,
            self.tx_id,
            self.t_ingress,
            self.t_egress,
            self.flags,
            self.opcode,
            self.meta
        )


def decode_trace(data: bytes) -> TraceRecord:
    """Decode a single trace record from bytes.

    Args:
        data: 32 bytes of trace record data

    Returns:
        TraceRecord object

    Raises:
        struct.error: If data is malformed
    """
    if len(data) != TRACE_RECORD_SIZE:
        raise ValueError(f"Expected {TRACE_RECORD_SIZE} bytes, got {len(data)}")

    tx_id, t_ingress, t_egress, flags, opcode, meta = struct.unpack(TRACE_FORMAT, data)
    return TraceRecord(tx_id, t_ingress, t_egress, flags, opcode, meta)


def decode_trace_file(f: BinaryIO) -> Iterator[TraceRecord]:
    """Decode all trace records from a binary file.

    Args:
        f: Binary file object opened for reading

    Yields:
        TraceRecord objects
    """
    while True:
        data = f.read(TRACE_RECORD_SIZE)
        if len(data) == 0:
            break
        if len(data) < TRACE_RECORD_SIZE:
            # Partial record at end of file
            print(f"Warning: Incomplete record ({len(data)} bytes) at end of file",
                  file=sys.stderr)
            break
        yield decode_trace(data)


def decode_trace_list(data: bytes) -> List[TraceRecord]:
    """Decode multiple trace records from bytes.

    Args:
        data: Binary data containing one or more trace records

    Returns:
        List of TraceRecord objects
    """
    records = []
    for i in range(0, len(data), TRACE_RECORD_SIZE):
        chunk = data[i:i + TRACE_RECORD_SIZE]
        if len(chunk) == TRACE_RECORD_SIZE:
            records.append(decode_trace(chunk))
    return records


def main():
    """Command-line interface for trace decoding."""
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <trace.bin>", file=sys.stderr)
        print("\nDecodes binary trace records and outputs JSONL to stdout.",
              file=sys.stderr)
        sys.exit(1)

    filepath = sys.argv[1]

    try:
        with open(filepath, 'rb') as f:
            for record in decode_trace_file(f):
                print(json.dumps(record.to_dict()))
    except FileNotFoundError:
        print(f"Error: File not found: {filepath}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
