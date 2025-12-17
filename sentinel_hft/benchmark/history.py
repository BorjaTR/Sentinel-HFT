"""
Local benchmark history storage and trend analysis.
"""

import json
import statistics
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any


@dataclass
class BenchmarkSnapshot:
    """A point-in-time benchmark."""
    timestamp: str
    commit: Optional[str]
    version: Optional[str]

    # Core metrics
    p50: float
    p90: float
    p99: float
    p999: float
    mean: float
    throughput: float
    drop_rate: float

    # Attribution (optional)
    attribution: Optional[Dict[str, float]] = None

    # Metadata
    tags: List[str] = field(default_factory=list)
    trace_file: Optional[str] = None
    provenance_hash: Optional[str] = None


@dataclass
class StabilityScore:
    """
    Single number that executives understand.

    Combines:
    - Variance (lower is better)
    - Tail events (fewer is better)
    - Regressions per period (fewer is better)
    """
    score: int  # 0-100
    components: Dict[str, int]
    trend: str  # "improving", "stable", "degrading"
    summary: str


class BenchmarkHistory:
    """
    Manage local benchmark history.

    Storage: ~/.sentinel-hft/benchmarks/history.json
    """

    def __init__(self, storage_dir: Path = None):
        self.storage_dir = storage_dir or (Path.home() / ".sentinel-hft" / "benchmarks")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = self.storage_dir / "history.json"
        self._snapshots: List[BenchmarkSnapshot] = []
        self._load()

    def _load(self):
        """Load history from disk."""
        if self.history_file.exists():
            try:
                with open(self.history_file) as f:
                    data = json.load(f)
                self._snapshots = []
                for s in data.get('snapshots', []):
                    # Handle missing fields
                    snap = BenchmarkSnapshot(
                        timestamp=s.get('timestamp', ''),
                        commit=s.get('commit'),
                        version=s.get('version'),
                        p50=s.get('p50', 0),
                        p90=s.get('p90', 0),
                        p99=s.get('p99', 0),
                        p999=s.get('p999', 0),
                        mean=s.get('mean', 0),
                        throughput=s.get('throughput', 0),
                        drop_rate=s.get('drop_rate', 0),
                        attribution=s.get('attribution'),
                        tags=s.get('tags', []),
                        trace_file=s.get('trace_file'),
                        provenance_hash=s.get('provenance_hash'),
                    )
                    self._snapshots.append(snap)
            except Exception:
                self._snapshots = []
        else:
            self._snapshots = []

    def _save(self):
        """Save history to disk."""
        data = {
            'version': '1.0',
            'snapshots': [asdict(s) for s in self._snapshots]
        }
        with open(self.history_file, 'w') as f:
            json.dump(data, f, indent=2)

    def record(self, analysis: Dict[str, Any],
               commit: str = None,
               tags: List[str] = None,
               trace_file: str = None) -> BenchmarkSnapshot:
        """
        Record a benchmark snapshot.

        Args:
            analysis: Output from analyzer.get_summary()
            commit: Git commit hash
            tags: Tags like "release", "baseline"
            trace_file: Source trace file path

        Returns:
            Created snapshot
        """
        from ..trace.provenance import Provenance

        latency = analysis.get('latency', {})
        throughput_data = analysis.get('throughput', {})
        drops = analysis.get('drops', {})

        # Extract metrics
        snapshot = BenchmarkSnapshot(
            timestamp=datetime.utcnow().isoformat() + "Z",
            commit=commit or Provenance._get_git_sha(),
            version=self._get_sentinel_version(),
            p50=latency.get('p50', 0),
            p90=latency.get('p90', 0),
            p99=latency.get('p99', 0),
            p999=latency.get('p999', 0),
            mean=latency.get('mean', 0),
            throughput=throughput_data.get('per_second', 0),
            drop_rate=drops.get('rate', 0),
            attribution=analysis.get('attribution'),
            tags=tags or [],
            trace_file=trace_file,
        )

        self._snapshots.append(snapshot)
        self._save()

        return snapshot

    def set_baseline(self, name: str, analysis: Dict[str, Any],
                     commit: str = None) -> BenchmarkSnapshot:
        """Set a named baseline."""
        return self.record(
            analysis,
            commit=commit,
            tags=['baseline', name]
        )

    def get_baseline(self, name: str) -> Optional[BenchmarkSnapshot]:
        """Get a named baseline."""
        for snap in reversed(self._snapshots):
            if 'baseline' in snap.tags and name in snap.tags:
                return snap
        return None

    def get_latest(self) -> Optional[BenchmarkSnapshot]:
        """Get most recent snapshot."""
        return self._snapshots[-1] if self._snapshots else None

    def get_range(self, days: int = 90) -> List[BenchmarkSnapshot]:
        """Get snapshots from last N days."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        cutoff_str = cutoff.isoformat() + "Z"

        return [s for s in self._snapshots if s.timestamp >= cutoff_str]

    def calculate_stability_score(self, days: int = 30) -> StabilityScore:
        """
        Calculate stability score for executives.

        Score 0-100 based on:
        - Variance (40 points): Low variance = stable
        - Tail events (30 points): P99.9/P99 ratio
        - Regressions (30 points): Fewer regression events
        """
        snapshots = self.get_range(days)

        if len(snapshots) < 2:
            return StabilityScore(
                score=50,
                components={'variance': 50, 'tails': 50, 'regressions': 50},
                trend="unknown",
                summary="Insufficient data (need at least 2 snapshots)"
            )

        p99_values = [s.p99 for s in snapshots]

        # Variance score (40 points)
        # CV (coefficient of variation) < 5% = full points
        mean_p99 = statistics.mean(p99_values)
        std_p99 = statistics.stdev(p99_values) if len(p99_values) > 1 else 0
        cv = (std_p99 / mean_p99) if mean_p99 > 0 else 0
        variance_score = max(0, min(40, int(40 * (1 - cv / 0.20))))

        # Tail score (30 points)
        # P99.9/P99 ratio < 1.5 = full points
        tail_ratios = [
            s.p999 / s.p99 if s.p99 > 0 else 1.0
            for s in snapshots if s.p999 > 0
        ]
        avg_tail_ratio = statistics.mean(tail_ratios) if tail_ratios else 1.0
        tail_score = max(0, min(30, int(30 * (1 - (avg_tail_ratio - 1) / 1.0))))

        # Regression score (30 points)
        # Count significant increases (>10%)
        regressions = 0
        for i in range(1, len(p99_values)):
            if p99_values[i] > p99_values[i-1] * 1.10:
                regressions += 1

        regression_rate = regressions / (len(p99_values) - 1)
        regression_score = max(0, min(30, int(30 * (1 - regression_rate))))

        total_score = variance_score + tail_score + regression_score

        # Trend
        recent = p99_values[-min(5, len(p99_values)):]
        older = p99_values[:min(5, len(p99_values))]

        if statistics.mean(recent) < statistics.mean(older) * 0.95:
            trend = "improving"
        elif statistics.mean(recent) > statistics.mean(older) * 1.05:
            trend = "degrading"
        else:
            trend = "stable"

        # Summary
        if total_score >= 80:
            summary = f"Excellent stability. P99 variance {cv:.1%}, minimal tail events."
        elif total_score >= 60:
            summary = f"Good stability with some variance. {regressions} regression events."
        elif total_score >= 40:
            summary = f"Moderate stability. Consider investigating variance sources."
        else:
            summary = f"Poor stability. High variance ({cv:.1%}) and {regressions} regressions."

        return StabilityScore(
            score=total_score,
            components={
                'variance': variance_score,
                'tails': tail_score,
                'regressions': regression_score,
            },
            trend=trend,
            summary=summary,
        )

    def _get_sentinel_version(self) -> str:
        try:
            from .. import __version__
            return __version__
        except Exception:
            return "unknown"

    def get_all_baselines(self) -> List[BenchmarkSnapshot]:
        """Get all baseline snapshots."""
        return [s for s in self._snapshots if 'baseline' in s.tags]

    def clear_history(self):
        """Clear all history."""
        self._snapshots = []
        self._save()
