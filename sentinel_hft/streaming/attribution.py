"""
attribution.py - Latency attribution tracking for streaming analysis.

Tracks per-stage latency distributions using streaming quantile estimation.
"""

from dataclasses import dataclass, field
from typing import Optional, List

from .quantiles import TDigestWrapper


@dataclass
class StageMetrics:
    """Metrics for a single pipeline stage."""
    stage: str
    p50: float
    p90: float
    p99: float
    mean: float
    pct_of_total: float  # Fraction of total latency

    def to_dict(self) -> dict:
        return {
            'stage': self.stage,
            'p50': round(self.p50, 2),
            'p90': round(self.p90, 2),
            'p99': round(self.p99, 2),
            'mean': round(self.mean, 2),
            'pct_of_total': round(self.pct_of_total, 4),
        }


@dataclass
class LatencyAttribution:
    """Complete latency attribution breakdown."""
    stages: List[StageMetrics]
    bottleneck: str
    bottleneck_pct: float
    total_p99: float

    def to_dict(self) -> dict:
        return {
            'stages': [s.to_dict() for s in self.stages],
            'bottleneck': self.bottleneck,
            'bottleneck_pct': round(self.bottleneck_pct, 4),
            'total_p99': round(self.total_p99, 2),
        }


class AttributionTracker:
    """Tracks per-stage latency distributions."""

    STAGES = ['ingress', 'core', 'risk', 'egress', 'overhead']

    def __init__(self):
        self.digests: dict = {
            stage: TDigestWrapper() for stage in self.STAGES
        }
        self.total_digest = TDigestWrapper()
        self.count = 0
        self.sums: dict = {stage: 0.0 for stage in self.STAGES}
        self.total_sum = 0.0

    def update(self, attribution) -> None:
        """Update with a new attribution sample.

        Args:
            attribution: AttributedLatency from v1.2 adapter
        """
        self.count += 1

        # Update per-stage
        for stage in self.STAGES:
            value = getattr(attribution, f'{stage}_ns')
            self.digests[stage].add(value)
            self.sums[stage] += value

        # Update total
        self.total_digest.add(attribution.total_ns)
        self.total_sum += attribution.total_ns

    def get_metrics(self) -> Optional[LatencyAttribution]:
        """Compute attribution metrics."""
        if self.count == 0:
            return None

        # Get total p99 for percentage calculation
        total_p99 = self.total_digest.percentile(0.99)
        if total_p99 == 0:
            total_p99 = 1.0  # Avoid division by zero

        # Compute per-stage metrics
        stages = []
        for stage in self.STAGES:
            digest = self.digests[stage]
            mean = self.sums[stage] / self.count if self.count > 0 else 0.0
            p99 = digest.percentile(0.99)

            stages.append(StageMetrics(
                stage=stage,
                p50=digest.percentile(0.50),
                p90=digest.percentile(0.90),
                p99=p99,
                mean=mean,
                pct_of_total=p99 / total_p99 if total_p99 > 0 else 0.0,
            ))

        # Find bottleneck (excluding overhead)
        compute_stages = [s for s in stages if s.stage != 'overhead']
        bottleneck = max(compute_stages, key=lambda s: s.p99) if compute_stages else stages[0]

        return LatencyAttribution(
            stages=stages,
            bottleneck=bottleneck.stage,
            bottleneck_pct=bottleneck.pct_of_total,
            total_p99=self.total_digest.percentile(0.99),
        )

    def reset(self) -> None:
        """Reset all trackers."""
        for stage in self.STAGES:
            self.digests[stage] = TDigestWrapper()
            self.sums[stage] = 0.0
        self.total_digest = TDigestWrapper()
        self.total_sum = 0.0
        self.count = 0
