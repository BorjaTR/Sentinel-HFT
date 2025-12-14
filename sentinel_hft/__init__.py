"""
Sentinel-HFT v2.2 - Production-ready latency verification for FPGA trading systems.

This package provides:
- formats: File header and record type definitions
- adapters: Format-specific decoders (v1.0, v1.1, CSV)
- streaming: Real-time trace processing
- core: Analysis engine and metrics
"""

__version__ = "2.2.0"

from .formats import FileHeader, HEADER_SIZE, MAGIC, RecordType, TraceReader, TraceFile
from .adapters import (
    TraceAdapter,
    StandardTrace,
    SentinelV10Adapter,
    SentinelV11Adapter,
    CSVAdapter,
    auto_detect,
)

__all__ = [
    # Version
    '__version__',
    # Formats
    'FileHeader',
    'HEADER_SIZE',
    'MAGIC',
    'RecordType',
    'TraceReader',
    'TraceFile',
    # Adapters
    'TraceAdapter',
    'StandardTrace',
    'SentinelV10Adapter',
    'SentinelV11Adapter',
    'CSVAdapter',
    'auto_detect',
]
