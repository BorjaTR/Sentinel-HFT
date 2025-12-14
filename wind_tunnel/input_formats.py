"""Input format parsing for Sentinel-HFT replay.

Supports CSV and binary input formats for transaction data.
"""

import csv
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator, TextIO, Union


@dataclass
class InputTransaction:
    """A single transaction to replay."""
    timestamp_ns: int      # When to inject (relative to start)
    data: int              # 64-bit data payload
    opcode: int            # 16-bit opcode
    meta: int              # 32-bit metadata

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            'timestamp_ns': self.timestamp_ns,
            'data': self.data,
            'opcode': self.opcode,
            'meta': self.meta,
        }

    def to_binary(self) -> bytes:
        """Convert to binary format (24 bytes).

        Format: timestamp_ns(8) + data(8) + opcode(2) + meta(4) + padding(2)
        """
        return struct.pack('<QQHIxx',
                          self.timestamp_ns,
                          self.data,
                          self.opcode,
                          self.meta)


# Binary record format: 24 bytes
# <Q: timestamp_ns (8 bytes, little-endian uint64)
# <Q: data (8 bytes, little-endian uint64)
# <H: opcode (2 bytes, little-endian uint16)
# <I: meta (4 bytes, little-endian uint32)
# xx: padding (2 bytes)
STIMULUS_STRUCT = struct.Struct('<QQHIxx')
STIMULUS_RECORD_SIZE = 24


def parse_csv(file: TextIO) -> Iterator[InputTransaction]:
    """Parse CSV input file.

    Expected columns: timestamp_ns, data, opcode, meta
    Data can be hex (0x...) or decimal.

    Lines starting with # are treated as comments.
    Empty lines are skipped.

    Args:
        file: Text file object to read from

    Yields:
        InputTransaction objects
    """
    # Read lines and filter comments/empty
    lines = []
    for line in file:
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            lines.append(stripped)

    if not lines:
        return

    # Parse as CSV
    reader = csv.DictReader(lines)

    for row in reader:
        try:
            # Parse values, handling hex format
            timestamp_ns = _parse_int(row['timestamp_ns'])
            data = _parse_int(row['data'])
            opcode = _parse_int(row['opcode'])
            meta = _parse_int(row['meta'])

            yield InputTransaction(
                timestamp_ns=timestamp_ns,
                data=data,
                opcode=opcode,
                meta=meta,
            )
        except (KeyError, ValueError) as e:
            raise ValueError(f"Error parsing CSV row {row}: {e}") from e


def parse_binary(file: BinaryIO) -> Iterator[InputTransaction]:
    """Parse binary input file.

    Each record is 24 bytes (see StimulusRecord struct in sim_main.cpp).

    Args:
        file: Binary file object to read from

    Yields:
        InputTransaction objects
    """
    while True:
        data = file.read(STIMULUS_RECORD_SIZE)
        if not data:
            break
        if len(data) < STIMULUS_RECORD_SIZE:
            raise ValueError(
                f"Incomplete record: expected {STIMULUS_RECORD_SIZE} bytes, "
                f"got {len(data)}"
            )

        timestamp_ns, data_val, opcode, meta = STIMULUS_STRUCT.unpack(data)

        yield InputTransaction(
            timestamp_ns=timestamp_ns,
            data=data_val,
            opcode=opcode,
            meta=meta,
        )


def detect_format(path: Path) -> str:
    """Detect input file format from extension or magic bytes.

    Args:
        path: Path to input file

    Returns:
        'csv' or 'binary'

    Raises:
        ValueError: If format cannot be determined
    """
    suffix = path.suffix.lower()

    if suffix in ('.csv', '.txt'):
        return 'csv'
    elif suffix in ('.bin', '.dat', '.stim'):
        return 'binary'
    else:
        # Try to detect from content
        with open(path, 'rb') as f:
            header = f.read(100)

        # Check if it looks like CSV (ASCII text with commas)
        try:
            text = header.decode('utf-8')
            if ',' in text and ('timestamp' in text.lower() or 'data' in text.lower()):
                return 'csv'
        except UnicodeDecodeError:
            pass

        # Default to binary
        return 'binary'


def load_input(path: Path) -> list[InputTransaction]:
    """Load input file, auto-detecting format.

    Returns list (not iterator) for random access during replay.
    The list is sorted by timestamp_ns.

    Args:
        path: Path to input file

    Returns:
        List of InputTransaction objects, sorted by timestamp
    """
    fmt = detect_format(path)

    if fmt == 'csv':
        with open(path, 'r') as f:
            transactions = list(parse_csv(f))
    else:
        with open(path, 'rb') as f:
            transactions = list(parse_binary(f))

    # Sort by timestamp
    transactions.sort(key=lambda t: t.timestamp_ns)

    return transactions


def write_stimulus_binary(transactions: list[InputTransaction], path: Path) -> None:
    """Write transactions to binary stimulus file.

    Args:
        transactions: List of transactions to write
        path: Output file path
    """
    with open(path, 'wb') as f:
        for tx in transactions:
            f.write(tx.to_binary())


def _parse_int(value: str) -> int:
    """Parse integer from string, handling hex format.

    Args:
        value: String value (decimal or hex with 0x prefix)

    Returns:
        Parsed integer
    """
    value = value.strip()
    if value.lower().startswith('0x'):
        return int(value, 16)
    return int(value)
