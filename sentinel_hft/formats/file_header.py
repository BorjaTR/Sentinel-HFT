"""
File header for Sentinel-HFT trace files.

The header provides:
- Magic number for reliable format detection
- Version for schema evolution
- Clock frequency for timestamp interpretation
- Record count for validation

Layout (32 bytes):
    Bytes 0-3:   magic      "SNTL" (0x4C544E53 little-endian)
    Byte 4:      version    Format version (1 for v1.1)
    Byte 5:      endian     Endianness (0=little, 1=big)
    Bytes 6-7:   rec_size   Record size in bytes
    Bytes 8-11:  clock_mhz  Clock frequency in MHz
    Bytes 12-15: run_id     Unique run identifier
    Bytes 16-23: rec_count  Total record count (0=unknown)
    Bytes 24-31: reserved   Reserved for future use
"""

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List


# Magic bytes: "SNTL" as bytes
MAGIC = b'SNTL'

# Header size in bytes
HEADER_SIZE = 32


@dataclass
class FileHeader:
    """File header for trace files."""

    magic: bytes = MAGIC
    version: int = 1           # Trace format version
    endianness: int = 0        # 0 = little-endian, 1 = big-endian
    record_size: int = 48      # Bytes per trace record
    clock_mhz: int = 100       # Clock frequency in MHz
    run_id: int = 0            # Unique run identifier (for reset detection)
    record_count: int = 0      # Total records (0 = unknown/streaming)

    # Struct format: 4s=magic, B=version, B=endian, H=rec_size,
    #                I=clock_mhz, I=run_id, Q=rec_count, 8x=padding
    FORMAT = '<4sBBHIIQ8x'

    def __post_init__(self):
        """Validate header fields."""
        if isinstance(self.magic, str):
            self.magic = self.magic.encode('ascii')
        if len(self.magic) != 4:
            raise ValueError(f"Magic must be 4 bytes, got {len(self.magic)}")

    def encode(self) -> bytes:
        """Encode header to bytes."""
        return struct.pack(
            self.FORMAT,
            self.magic,
            self.version,
            self.endianness,
            self.record_size,
            self.clock_mhz,
            self.run_id,
            self.record_count,
        )

    @classmethod
    def decode(cls, data: bytes) -> 'FileHeader':
        """Decode header from bytes."""
        if len(data) < HEADER_SIZE:
            raise ValueError(f"Header too small: {len(data)} < {HEADER_SIZE}")

        magic, version, endian, rec_size, clock, run_id, count = struct.unpack(
            cls.FORMAT, data[:HEADER_SIZE]
        )

        if magic != MAGIC:
            raise ValueError(f"Invalid magic: {magic!r} (expected {MAGIC!r})")

        return cls(
            magic=magic,
            version=version,
            endianness=endian,
            record_size=rec_size,
            clock_mhz=clock,
            run_id=run_id,
            record_count=count,
        )

    @classmethod
    def probe(cls, path: Path) -> Optional['FileHeader']:
        """
        Try to read header from file.

        Returns:
            FileHeader if file has valid header, None otherwise.
        """
        try:
            path = Path(path)
            if not path.exists():
                return None
            if path.stat().st_size < HEADER_SIZE:
                return None

            with open(path, 'rb') as f:
                data = f.read(HEADER_SIZE)

            # Check magic before full decode
            if len(data) >= 4 and data[:4] == MAGIC:
                return cls.decode(data)

            return None

        except Exception:
            return None

    def validate(self) -> List[str]:
        """
        Validate header fields.

        Returns:
            List of validation error messages (empty if valid).
        """
        errors = []

        if self.magic != MAGIC:
            errors.append(f"Invalid magic: {self.magic!r}")

        if self.version < 1:
            errors.append(f"Invalid version: {self.version}")

        if self.record_size not in (32, 48, 64):
            errors.append(f"Unusual record size: {self.record_size}")

        if self.clock_mhz <= 0:
            errors.append(f"Invalid clock frequency: {self.clock_mhz}")

        return errors


# Verify struct size at module load
_computed_size = struct.calcsize(FileHeader.FORMAT)
assert _computed_size == HEADER_SIZE, \
    f"FileHeader format size mismatch: {_computed_size} != {HEADER_SIZE}"
