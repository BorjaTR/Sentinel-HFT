"""
Sentinel-HFT v2.2 - Production-ready latency verification for FPGA trading systems.

This package provides:
- formats: File header and record type definitions
- adapters: Format-specific decoders (v1.0, v1.1, CSV)
- streaming: Real-time trace processing with sequence tracking
- config: YAML configuration with environment variable support
- core: Analysis reports with evidence bundles
- api: REST API for analysis
- exporters: Prometheus and Slack integrations
- cli: Command-line interface
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
from .streaming import StreamingMetrics, StreamingConfig, SequenceTracker
from .config import SentinelConfig, load_config
from .core import AnalysisReport, ReportStatus, EvidenceBundle

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
    # Streaming
    'StreamingMetrics',
    'StreamingConfig',
    'SequenceTracker',
    # Config
    'SentinelConfig',
    'load_config',
    # Core
    'AnalysisReport',
    'ReportStatus',
    'EvidenceBundle',
]
