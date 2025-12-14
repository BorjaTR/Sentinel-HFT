"""
TraceReader - High-level interface for reading trace files.

TraceReader handles:
- Format auto-detection
- Header parsing and skipping
- Streaming record iteration

This is the primary interface for reading trace files. It ensures headers
are properly skipped so records decode correctly.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from .file_header import FileHeader, HEADER_SIZE
from ..adapters.base import TraceAdapter, StandardTrace
from ..adapters import auto_detect


@dataclass
class TraceFile:
    """
    Metadata about an opened trace file.

    Attributes:
        path: Path to the trace file
        header: File header (None for legacy/CSV files)
        adapter: Adapter for decoding records
        data_offset: Byte offset where record data starts
    """
    path: Path
    header: Optional[FileHeader]
    adapter: TraceAdapter
    data_offset: int  # 0 for headerless, HEADER_SIZE for files with header

    @property
    def has_header(self) -> bool:
        """Check if file has a header."""
        return self.header is not None

    @property
    def clock_mhz(self) -> int:
        """Get clock frequency from header or default."""
        if self.header:
            return self.header.clock_mhz
        return 100  # Default 100 MHz

    @property
    def record_size(self) -> int:
        """Get record size from adapter."""
        return self.adapter.record_size()


class TraceReader:
    """
    High-level interface for reading trace files.

    Usage:
        # Option 1: Open and read separately
        trace_file = TraceReader.open(path)
        for trace in TraceReader.read(trace_file):
            process(trace)

        # Option 2: Convenience method
        for trace in TraceReader.read_path(path):
            process(trace)

    The reader properly handles file headers, ensuring they are skipped
    before reading records.
    """

    @classmethod
    def open(cls, path: Path) -> TraceFile:
        """
        Open a trace file and detect its format.

        Args:
            path: Path to trace file

        Returns:
            TraceFile with metadata about the file

        Raises:
            ValueError: If format cannot be detected
            FileNotFoundError: If file doesn't exist
        """
        path = Path(path)

        if not path.exists():
            raise FileNotFoundError(f"Trace file not found: {path}")

        # Detect format and get adapter
        adapter, header = auto_detect(path)

        # Determine where records start
        # CRITICAL: Must skip header bytes when reading records
        if header is not None:
            data_offset = HEADER_SIZE
        else:
            data_offset = 0

        return TraceFile(
            path=path,
            header=header,
            adapter=adapter,
            data_offset=data_offset,
        )

    @classmethod
    def read(cls, trace_file: TraceFile) -> Iterator[StandardTrace]:
        """
        Read all traces from an opened file.

        This method properly skips the file header (if present) before
        reading records.

        Args:
            trace_file: Previously opened TraceFile

        Yields:
            StandardTrace objects
        """
        record_size = trace_file.adapter.record_size()

        # CSV files have variable record size
        if record_size == 0:
            yield from trace_file.adapter.decode_file(trace_file.path)
            return

        # Binary files: skip header and read records
        with open(trace_file.path, 'rb') as f:
            # CRITICAL: Skip header if present
            if trace_file.data_offset > 0:
                f.seek(trace_file.data_offset)

            while True:
                raw = f.read(record_size)
                if len(raw) < record_size:
                    break
                yield trace_file.adapter.decode(raw)

    @classmethod
    def read_path(cls, path: Path) -> Iterator[StandardTrace]:
        """
        Convenience method: open and read in one call.

        Args:
            path: Path to trace file

        Yields:
            StandardTrace objects
        """
        trace_file = cls.open(path)
        yield from cls.read(trace_file)

    @classmethod
    def count(cls, path: Path) -> int:
        """
        Count records in a trace file without loading all into memory.

        Args:
            path: Path to trace file

        Returns:
            Number of trace records
        """
        trace_file = cls.open(path)

        # For files with header, use the record count if available
        if trace_file.header and trace_file.header.record_count > 0:
            return trace_file.header.record_count

        # Otherwise, compute from file size
        file_size = trace_file.path.stat().st_size
        data_size = file_size - trace_file.data_offset
        record_size = trace_file.adapter.record_size()

        if record_size == 0:
            # CSV: have to count lines
            return sum(1 for _ in cls.read(trace_file))

        return data_size // record_size
