"""
Report schema for Sentinel-HFT analysis results.

Reports are structured JSON documents containing:
- Metadata (version, timestamp, source)
- Latency statistics
- Drop/sequence analysis
- Risk control events
- Anomaly detection results
- Evidence bundle (optional, for debugging)
"""

import json
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum

from .evidence import EvidenceBundle
from .errors import SentinelError


class ReportStatus(Enum):
    """Overall report status."""
    OK = 'ok'
    WARNING = 'warning'
    ERROR = 'error'
    CRITICAL = 'critical'


@dataclass
class LatencyStats:
    """Latency statistics section."""
    count: int = 0
    mean_cycles: float = 0.0
    stddev_cycles: float = 0.0
    min_cycles: int = 0
    max_cycles: int = 0

    # Percentiles
    p50_cycles: float = 0.0
    p75_cycles: float = 0.0
    p90_cycles: float = 0.0
    p95_cycles: float = 0.0
    p99_cycles: float = 0.0
    p999_cycles: float = 0.0

    # Converted to nanoseconds (requires clock config)
    mean_ns: Optional[float] = None
    p99_ns: Optional[float] = None
    p999_ns: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DropStats:
    """Drop/sequence statistics section."""
    total_drops: int = 0
    drop_events: int = 0
    drop_rate: float = 0.0
    reorders: int = 0
    resets: int = 0

    # Per-core breakdown
    per_core: Dict[int, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'total_drops': self.total_drops,
            'drop_events': self.drop_events,
            'drop_rate': self.drop_rate,
            'reorders': self.reorders,
            'resets': self.resets,
            'per_core': self.per_core,
        }


@dataclass
class ThroughputStats:
    """Throughput statistics section."""
    total_traces: int = 0
    tx_events: int = 0
    duration_seconds: float = 0.0
    traces_per_second: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RiskStats:
    """Risk control statistics section."""
    rate_limit_rejects: int = 0
    position_limit_rejects: int = 0
    kill_switch_triggered: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RecordTypeStats:
    """Record type breakdown section."""
    tx_events: int = 0
    overflows: int = 0
    heartbeats: int = 0
    clock_syncs: int = 0
    resets: int = 0
    overflow_traces_lost: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AnomalyStats:
    """Anomaly detection statistics section."""
    total_anomalies: int = 0
    anomaly_rate: float = 0.0
    zscore_threshold: float = 3.0
    max_latency_zscore: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AnalysisReport:
    """
    Complete analysis report.

    Example:
        report = AnalysisReport(
            source_file='/path/to/traces.bin',
        )
        report.latency.count = 1000000
        report.latency.p99_cycles = 45
        report.compute_status(config.thresholds)
        print(report.to_json())
    """
    # Metadata
    version: int = 1
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    sentinel_version: str = '2.2.0'

    # Source information
    source_file: Optional[str] = None
    source_format: Optional[str] = None
    source_format_version: Optional[int] = None

    # Clock configuration
    clock_frequency_mhz: float = 100.0

    # Statistics sections
    latency: LatencyStats = field(default_factory=LatencyStats)
    drops: DropStats = field(default_factory=DropStats)
    throughput: ThroughputStats = field(default_factory=ThroughputStats)
    risk: RiskStats = field(default_factory=RiskStats)
    record_types: RecordTypeStats = field(default_factory=RecordTypeStats)
    anomalies: AnomalyStats = field(default_factory=AnomalyStats)

    # Status
    status: ReportStatus = ReportStatus.OK
    status_reason: Optional[str] = None

    # Errors encountered
    errors: List[dict] = field(default_factory=list)

    # Evidence bundle (optional)
    evidence: Optional[EvidenceBundle] = None
    include_evidence: bool = False

    def add_error(self, error: SentinelError) -> None:
        """Add an error to the report."""
        self.errors.append(error.to_dict())

    def compute_status(
        self,
        p99_warning: int = 10,
        p99_error: int = 50,
        p99_critical: int = 100,
        drop_rate_warning: float = 0.001,
        drop_rate_error: float = 0.01,
        anomaly_rate_warning: float = 0.01,
        anomaly_rate_error: float = 0.05,
    ) -> None:
        """
        Compute overall status based on thresholds.

        Priority: CRITICAL > ERROR > WARNING > OK
        """
        reasons = []

        # Check latency thresholds
        if self.latency.p99_cycles >= p99_critical:
            self.status = ReportStatus.CRITICAL
            reasons.append(f"P99 latency {self.latency.p99_cycles} >= {p99_critical} cycles")
        elif self.latency.p99_cycles >= p99_error:
            if self.status.value not in ['critical']:
                self.status = ReportStatus.ERROR
            reasons.append(f"P99 latency {self.latency.p99_cycles} >= {p99_error} cycles")
        elif self.latency.p99_cycles >= p99_warning:
            if self.status.value not in ['critical', 'error']:
                self.status = ReportStatus.WARNING
            reasons.append(f"P99 latency {self.latency.p99_cycles} >= {p99_warning} cycles")

        # Check drop rate
        if self.drops.drop_rate >= drop_rate_error:
            if self.status.value not in ['critical']:
                self.status = ReportStatus.ERROR
            reasons.append(f"Drop rate {self.drops.drop_rate:.4f} >= {drop_rate_error}")
        elif self.drops.drop_rate >= drop_rate_warning:
            if self.status.value not in ['critical', 'error']:
                self.status = ReportStatus.WARNING
            reasons.append(f"Drop rate {self.drops.drop_rate:.4f} >= {drop_rate_warning}")

        # Check anomaly rate
        if self.anomalies.anomaly_rate >= anomaly_rate_error:
            if self.status.value not in ['critical']:
                self.status = ReportStatus.ERROR
            reasons.append(f"Anomaly rate {self.anomalies.anomaly_rate:.4f} >= {anomaly_rate_error}")
        elif self.anomalies.anomaly_rate >= anomaly_rate_warning:
            if self.status.value not in ['critical', 'error']:
                self.status = ReportStatus.WARNING
            reasons.append(f"Anomaly rate {self.anomalies.anomaly_rate:.4f} >= {anomaly_rate_warning}")

        # Check kill switch
        if self.risk.kill_switch_triggered:
            self.status = ReportStatus.CRITICAL
            reasons.append("Kill switch was triggered")

        if reasons:
            self.status_reason = '; '.join(reasons)

    def cycles_to_ns(self, cycles: float) -> float:
        """Convert cycles to nanoseconds."""
        period_ns = 1000.0 / self.clock_frequency_mhz
        return cycles * period_ns

    def populate_ns_values(self) -> None:
        """Populate nanosecond values from cycle counts."""
        self.latency.mean_ns = self.cycles_to_ns(self.latency.mean_cycles)
        self.latency.p99_ns = self.cycles_to_ns(self.latency.p99_cycles)
        self.latency.p999_ns = self.cycles_to_ns(self.latency.p999_cycles)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        result = {
            'version': self.version,
            'created_at': self.created_at,
            'sentinel_version': self.sentinel_version,
            'source': {
                'file': self.source_file,
                'format': self.source_format,
                'format_version': self.source_format_version,
            },
            'clock_frequency_mhz': self.clock_frequency_mhz,
            'status': self.status.value,
            'status_reason': self.status_reason,
            'latency': self.latency.to_dict(),
            'drops': self.drops.to_dict(),
            'throughput': self.throughput.to_dict(),
            'risk': self.risk.to_dict(),
            'record_types': self.record_types.to_dict(),
            'anomalies': self.anomalies.to_dict(),
            'errors': self.errors,
        }

        if self.include_evidence and self.evidence:
            result['evidence'] = self.evidence.to_dict()

        return result

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict) -> 'AnalysisReport':
        """Create from dictionary."""
        report = cls(
            version=data.get('version', 1),
            created_at=data.get('created_at', datetime.utcnow().isoformat()),
            sentinel_version=data.get('sentinel_version', '2.2.0'),
        )

        source = data.get('source', {})
        report.source_file = source.get('file')
        report.source_format = source.get('format')
        report.source_format_version = source.get('format_version')

        report.clock_frequency_mhz = data.get('clock_frequency_mhz', 100.0)
        report.status = ReportStatus(data.get('status', 'ok'))
        report.status_reason = data.get('status_reason')

        # Populate stats sections
        if 'latency' in data:
            for k, v in data['latency'].items():
                if hasattr(report.latency, k):
                    setattr(report.latency, k, v)

        if 'drops' in data:
            for k, v in data['drops'].items():
                if hasattr(report.drops, k):
                    setattr(report.drops, k, v)

        if 'throughput' in data:
            for k, v in data['throughput'].items():
                if hasattr(report.throughput, k):
                    setattr(report.throughput, k, v)

        if 'risk' in data:
            for k, v in data['risk'].items():
                if hasattr(report.risk, k):
                    setattr(report.risk, k, v)

        if 'record_types' in data:
            for k, v in data['record_types'].items():
                if hasattr(report.record_types, k):
                    setattr(report.record_types, k, v)

        if 'anomalies' in data:
            for k, v in data['anomalies'].items():
                if hasattr(report.anomalies, k):
                    setattr(report.anomalies, k, v)

        report.errors = data.get('errors', [])

        if 'evidence' in data:
            report.evidence = EvidenceBundle.from_dict(data['evidence'])
            report.include_evidence = True

        return report

    @classmethod
    def from_json(cls, json_str: str) -> 'AnalysisReport':
        """Create from JSON string."""
        return cls.from_dict(json.loads(json_str))

    def summary(self) -> str:
        """Get human-readable summary."""
        lines = [
            f"Sentinel-HFT Analysis Report",
            f"Status: {self.status.value.upper()}",
            f"",
            f"Latency:",
            f"  Count: {self.latency.count:,}",
            f"  P99:   {self.latency.p99_cycles} cycles",
            f"  P99.9: {self.latency.p999_cycles} cycles",
            f"  Mean:  {self.latency.mean_cycles:.1f} cycles",
            f"",
            f"Drops:",
            f"  Total: {self.drops.total_drops:,}",
            f"  Rate:  {self.drops.drop_rate:.4%}",
            f"",
        ]

        if self.status_reason:
            lines.append(f"Reason: {self.status_reason}")

        return '\n'.join(lines)
