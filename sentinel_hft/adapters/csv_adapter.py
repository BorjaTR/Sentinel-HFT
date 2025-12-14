"""
Adapter for CSV trace files.

CSV format is primarily used for testing and demos. It's human-readable
but much slower than binary formats.

Expected columns:
- timestamp_ns or t_ingress: Ingress timestamp
- t_egress: Egress timestamp (optional, defaults to t_ingress + 100)
- data: Transaction data (hex string starting with 0x, or integer)
- flags: Status flags (optional, defaults to 0)
- tx_id: Transaction ID (optional, auto-generated if missing)
- core_id: Core ID (optional, defaults to 0)
- seq_no: Sequence number (optional, auto-generated if missing)
"""

import csv
from pathlib import Path
from typing import Iterator

from .base import TraceAdapter, StandardTrace


class CSVAdapter(TraceAdapter):
    """
    Adapter for CSV trace files.

    Variable record size (text-based), so record_size() returns 0.
    Must use decode_file() instead of decode().
    """

    def record_size(self) -> int:
        """CSV has variable record size."""
        return 0

    def decode(self, raw: bytes) -> StandardTrace:
        """Not supported for CSV - use decode_file() instead."""
        raise NotImplementedError(
            "CSV adapter requires decode_file(), not decode()"
        )

    def decode_file(self, path: Path, skip_bytes: int = 0) -> Iterator[StandardTrace]:
        """
        Decode traces from a CSV file.

        Args:
            path: Path to CSV file
            skip_bytes: Ignored for CSV files

        Yields:
            Decoded StandardTrace objects
        """
        seq = 0  # Auto-generate sequence numbers

        with open(path, 'r', newline='') as f:
            # Skip comment lines
            lines = (line for line in f if not line.startswith('#'))
            reader = csv.DictReader(lines)

            for row in reader:
                # Parse timestamp
                if 't_ingress' in row:
                    t_ingress = int(row['t_ingress'])
                elif 'timestamp_ns' in row:
                    t_ingress = int(row['timestamp_ns'])
                else:
                    raise ValueError(f"Row missing timestamp: {row}")

                # Parse egress (optional)
                if 't_egress' in row and row['t_egress']:
                    t_egress = int(row['t_egress'])
                else:
                    t_egress = t_ingress + 100  # Default latency

                # Parse data (hex or int)
                data_str = row.get('data', '0')
                if data_str.startswith('0x') or data_str.startswith('0X'):
                    data = int(data_str, 16)
                else:
                    data = int(data_str) if data_str else 0

                # Parse optional fields
                flags = int(row.get('flags', 0))
                tx_id = int(row.get('tx_id', seq))
                core_id = int(row.get('core_id', 0))
                seq_no = int(row.get('seq_no', seq))
                record_type = int(row.get('record_type', 0x01))

                yield StandardTrace(
                    version=1,
                    record_type=record_type,
                    core_id=core_id,
                    seq_no=seq_no,
                    t_ingress=t_ingress,
                    t_egress=t_egress,
                    data=data,
                    flags=flags,
                    tx_id=tx_id,
                )

                seq += 1
