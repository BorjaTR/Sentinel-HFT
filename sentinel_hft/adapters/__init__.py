"""
Trace format adapters.

Adapters decode raw trace bytes into StandardTrace objects.
Each adapter handles a specific trace format version.
"""

from pathlib import Path
from typing import Optional, Tuple, Union

from .base import TraceAdapter, StandardTrace
from .sentinel_adapter import SentinelV10Adapter, SentinelV11Adapter
from .csv_adapter import CSVAdapter

# Import from formats package
from ..formats.file_header import FileHeader, HEADER_SIZE, MAGIC


def auto_detect(path: Union[Path, str]) -> Tuple[TraceAdapter, Optional[FileHeader]]:
    """
    Auto-detect trace format based on file header or extension.

    Detection order:
    1. CSV files by extension (.csv)
    2. Files with SNTL magic header (v1.1 format)
    3. Legacy binary files (v1.0 format, 32-byte records)

    Args:
        path: Path to trace file

    Returns:
        Tuple of (adapter, header) where header is None for legacy/CSV files

    Raises:
        ValueError: If format cannot be detected
    """
    path = Path(path)

    if not path.exists():
        raise ValueError(f"File not found: {path}")

    # CSV by extension
    if path.suffix.lower() == '.csv':
        return CSVAdapter(), None

    # Try to read file header
    header = FileHeader.probe(path)

    if header:
        # Modern format with header
        if header.version == 1 and header.record_size == 48:
            return SentinelV11Adapter(), header
        elif header.version == 1 and header.record_size == 32:
            # Hypothetical: header with v1.0 records
            return SentinelV10Adapter(), header
        else:
            raise ValueError(
                f"Unknown format: version={header.version}, "
                f"record_size={header.record_size}"
            )

    # Legacy v1.0 format (no header, 32-byte records)
    file_size = path.stat().st_size
    if file_size > 0 and file_size % 32 == 0:
        return SentinelV10Adapter(), None

    # Could be v1.1 without header (48-byte records)
    if file_size > 0 and file_size % 48 == 0:
        return SentinelV11Adapter(), None

    raise ValueError(
        f"Cannot detect format for {path}: "
        f"size {file_size} not divisible by 32 or 48"
    )


__all__ = [
    'TraceAdapter',
    'StandardTrace',
    'SentinelV10Adapter',
    'SentinelV11Adapter',
    'CSVAdapter',
    'auto_detect',
]
