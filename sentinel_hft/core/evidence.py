"""
Evidence bundle for Sentinel-HFT reports.

Evidence provides the raw data to support analysis conclusions,
enabling verification and debugging of reported issues.
"""

import json
import gzip
import base64
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from datetime import datetime


@dataclass
class TraceEvidence:
    """
    Raw trace evidence for a specific event.

    Example: Evidence for a sequence gap includes the traces
    before and after the gap.
    """
    timestamp: int  # Cycle count when captured
    seq_no: int
    core_id: int
    latency_cycles: int
    record_type: int
    flags: int = 0
    data: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DropEvidence:
    """Evidence for a drop event."""
    timestamp: int
    core_id: int
    expected_seq: int
    actual_seq: int
    dropped_count: int
    event_type: str  # 'gap' or 'wrap'
    traces_before: List[TraceEvidence] = field(default_factory=list)
    traces_after: List[TraceEvidence] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp,
            'core_id': self.core_id,
            'expected_seq': self.expected_seq,
            'actual_seq': self.actual_seq,
            'dropped_count': self.dropped_count,
            'event_type': self.event_type,
            'traces_before': [t.to_dict() for t in self.traces_before],
            'traces_after': [t.to_dict() for t in self.traces_after],
        }


@dataclass
class AnomalyEvidence:
    """Evidence for a latency anomaly."""
    timestamp: int
    seq_no: int
    core_id: int
    latency_cycles: int
    zscore: float
    percentile: float  # Where this falls in the distribution

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OverflowEvidence:
    """Evidence for FPGA overflow events."""
    timestamp: int
    core_id: int
    traces_lost: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EvidenceBundle:
    """
    Complete evidence bundle for a report.

    Contains all raw data supporting the analysis conclusions.
    Can be compressed for efficient storage.
    """
    # Metadata
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    version: int = 1

    # Source information
    source_file: Optional[str] = None
    source_format: Optional[str] = None
    source_version: Optional[int] = None

    # Sample traces (first N and last N)
    sample_traces_head: List[TraceEvidence] = field(default_factory=list)
    sample_traces_tail: List[TraceEvidence] = field(default_factory=list)

    # Drop evidence
    drop_events: List[DropEvidence] = field(default_factory=list)

    # Anomaly evidence
    anomaly_events: List[AnomalyEvidence] = field(default_factory=list)

    # Overflow evidence
    overflow_events: List[OverflowEvidence] = field(default_factory=list)

    # Raw histogram buckets (for verification)
    histogram_buckets: Optional[Dict[str, int]] = None

    def add_trace_sample(self, trace: TraceEvidence, position: str = 'head') -> None:
        """Add a sample trace. Position is 'head' or 'tail'."""
        if position == 'head':
            self.sample_traces_head.append(trace)
        else:
            self.sample_traces_tail.append(trace)

    def add_drop(self, drop: DropEvidence) -> None:
        """Add drop event evidence."""
        self.drop_events.append(drop)

    def add_anomaly(self, anomaly: AnomalyEvidence) -> None:
        """Add anomaly evidence."""
        self.anomaly_events.append(anomaly)

    def add_overflow(self, overflow: OverflowEvidence) -> None:
        """Add overflow evidence."""
        self.overflow_events.append(overflow)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            'version': self.version,
            'created_at': self.created_at,
            'source': {
                'file': self.source_file,
                'format': self.source_format,
                'format_version': self.source_version,
            },
            'sample_traces': {
                'head': [t.to_dict() for t in self.sample_traces_head],
                'tail': [t.to_dict() for t in self.sample_traces_tail],
            },
            'drops': [d.to_dict() for d in self.drop_events],
            'anomalies': [a.to_dict() for a in self.anomaly_events],
            'overflows': [o.to_dict() for o in self.overflow_events],
            'histogram_buckets': self.histogram_buckets,
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def to_compressed(self) -> bytes:
        """Compress evidence bundle for storage."""
        json_bytes = self.to_json(indent=None).encode('utf-8')
        return gzip.compress(json_bytes)

    def to_base64(self) -> str:
        """Compress and encode as base64 for embedding."""
        compressed = self.to_compressed()
        return base64.b64encode(compressed).decode('ascii')

    @classmethod
    def from_dict(cls, data: dict) -> 'EvidenceBundle':
        """Create from dictionary."""
        bundle = cls(
            version=data.get('version', 1),
            created_at=data.get('created_at', datetime.utcnow().isoformat()),
        )

        source = data.get('source', {})
        bundle.source_file = source.get('file')
        bundle.source_format = source.get('format')
        bundle.source_version = source.get('format_version')

        samples = data.get('sample_traces', {})
        for t in samples.get('head', []):
            bundle.sample_traces_head.append(TraceEvidence(**t))
        for t in samples.get('tail', []):
            bundle.sample_traces_tail.append(TraceEvidence(**t))

        for d in data.get('drops', []):
            traces_before = [TraceEvidence(**t) for t in d.pop('traces_before', [])]
            traces_after = [TraceEvidence(**t) for t in d.pop('traces_after', [])]
            bundle.drop_events.append(DropEvidence(
                **d,
                traces_before=traces_before,
                traces_after=traces_after,
            ))

        for a in data.get('anomalies', []):
            bundle.anomaly_events.append(AnomalyEvidence(**a))

        for o in data.get('overflows', []):
            bundle.overflow_events.append(OverflowEvidence(**o))

        bundle.histogram_buckets = data.get('histogram_buckets')

        return bundle

    @classmethod
    def from_json(cls, json_str: str) -> 'EvidenceBundle':
        """Create from JSON string."""
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def from_compressed(cls, compressed: bytes) -> 'EvidenceBundle':
        """Create from compressed bytes."""
        json_bytes = gzip.decompress(compressed)
        return cls.from_json(json_bytes.decode('utf-8'))

    @classmethod
    def from_base64(cls, b64_str: str) -> 'EvidenceBundle':
        """Create from base64-encoded compressed bundle."""
        compressed = base64.b64decode(b64_str)
        return cls.from_compressed(compressed)

    def summary(self) -> dict:
        """Get summary counts."""
        return {
            'sample_traces': len(self.sample_traces_head) + len(self.sample_traces_tail),
            'drop_events': len(self.drop_events),
            'anomaly_events': len(self.anomaly_events),
            'overflow_events': len(self.overflow_events),
        }
