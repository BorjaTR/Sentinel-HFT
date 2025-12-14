"""
Base classes for trace adapters.

TraceAdapter is the abstract base class that all format-specific adapters inherit.
StandardTrace is the normalized trace format used internally by the analyzer.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional


@dataclass
class StandardTrace:
    """
    Normalized trace format used internally.

    All adapters convert their native format to StandardTrace objects.
    This provides a consistent interface for the analyzer regardless of
    the source trace format.

    Attributes:
        version: Trace format version (0 for legacy v1.0, 1 for v1.1)
        record_type: Type of record (see RecordType constants)
        core_id: Source core identifier (for multi-core systems)
        seq_no: Monotonic sequence number (for drop detection)
        t_ingress: Ingress timestamp in cycles
        t_egress: Egress timestamp in cycles
        data: Transaction payload/data
        flags: Status flags (risk events, backpressure, etc.)
        tx_id: Transaction identifier
    """
    version: int
    record_type: int
    core_id: int
    seq_no: int
    t_ingress: int
    t_egress: int
    data: int
    flags: int
    tx_id: int

    @property
    def latency(self) -> int:
        """Compute latency in cycles."""
        return self.t_egress - self.t_ingress

    def __repr__(self) -> str:
        return (
            f"StandardTrace(seq={self.seq_no}, "
            f"latency={self.latency}, "
            f"type={self.record_type}, "
            f"flags=0x{self.flags:04x})"
        )


class TraceAdapter(ABC):
    """
    Abstract base class for trace format adapters.

    Each adapter handles decoding of a specific trace format.
    Adapters are stateless - they just decode bytes to StandardTrace objects.
    """

    @abstractmethod
    def record_size(self) -> int:
        """
        Size of one trace record in bytes.

        Returns:
            Record size. Return 0 for variable-size formats (e.g., CSV).
        """
        pass

    @abstractmethod
    def decode(self, raw: bytes) -> StandardTrace:
        """
        Decode a single trace record from raw bytes.

        Args:
            raw: Raw bytes of exactly record_size() length

        Returns:
            Decoded StandardTrace

        Raises:
            ValueError: If bytes cannot be decoded
        """
        pass

    def validate(self, trace: StandardTrace) -> Optional[str]:
        """
        Validate a decoded trace.

        Args:
            trace: Decoded trace to validate

        Returns:
            Error message if invalid, None if valid
        """
        if trace.t_egress < trace.t_ingress:
            return f"Egress before ingress: {trace.t_egress} < {trace.t_ingress}"

        latency = trace.latency
        if latency > 10_000_000:  # Sanity check: >10M cycles seems wrong
            return f"Suspiciously high latency: {latency}"

        return None

    def decode_file(self, path: Path, skip_bytes: int = 0) -> Iterator[StandardTrace]:
        """
        Decode all traces from a file.

        This is a convenience method. For files with headers, use TraceReader
        which properly handles the header offset.

        Args:
            path: Path to trace file
            skip_bytes: Bytes to skip at start (e.g., header size)

        Yields:
            Decoded StandardTrace objects
        """
        record_size = self.record_size()

        if record_size == 0:
            raise NotImplementedError(
                "Variable-size formats must override decode_file()"
            )

        with open(path, 'rb') as f:
            if skip_bytes > 0:
                f.seek(skip_bytes)

            while True:
                raw = f.read(record_size)
                if len(raw) < record_size:
                    break
                yield self.decode(raw)

    def decode_bytes(self, data: bytes, offset: int = 0) -> Iterator[StandardTrace]:
        """
        Decode traces from a byte buffer.

        Args:
            data: Byte buffer containing trace records
            offset: Starting offset in buffer

        Yields:
            Decoded StandardTrace objects
        """
        record_size = self.record_size()

        if record_size == 0:
            raise NotImplementedError(
                "Variable-size formats must override decode_bytes()"
            )

        while offset + record_size <= len(data):
            yield self.decode(data[offset:offset + record_size])
            offset += record_size
