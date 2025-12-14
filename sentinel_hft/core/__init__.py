"""Core analysis engine for Sentinel-HFT."""

from .errors import ErrorCode, SentinelError, ERROR_METADATA
from .evidence import (
    TraceEvidence,
    DropEvidence,
    AnomalyEvidence,
    OverflowEvidence,
    EvidenceBundle,
)
from .report import (
    ReportStatus,
    LatencyStats,
    DropStats,
    ThroughputStats,
    RiskStats,
    RecordTypeStats,
    AnomalyStats,
    AnalysisReport,
)

__all__ = [
    # Errors
    'ErrorCode',
    'SentinelError',
    'ERROR_METADATA',
    # Evidence
    'TraceEvidence',
    'DropEvidence',
    'AnomalyEvidence',
    'OverflowEvidence',
    'EvidenceBundle',
    # Report
    'ReportStatus',
    'LatencyStats',
    'DropStats',
    'ThroughputStats',
    'RiskStats',
    'RecordTypeStats',
    'AnomalyStats',
    'AnalysisReport',
]
