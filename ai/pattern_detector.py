"""Pattern detection for trace analysis."""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, List, Any
import numpy as np


class PatternType(Enum):
    """Types of patterns we can detect."""
    LATENCY_SPIKE = auto()          # Sudden increase in latency
    LATENCY_BIMODAL = auto()        # Two distinct latency populations
    RATE_LIMIT_BURST = auto()       # Burst hit rate limiter
    POSITION_LIMIT_APPROACH = auto() # Getting close to position limit
    BACKPRESSURE_EPISODE = auto()   # Sustained backpressure period
    KILL_SWITCH_TRIGGER = auto()    # Kill switch was activated
    THROUGHPUT_DROP = auto()        # Sudden throughput reduction
    PERIODIC_ANOMALY = auto()       # Regularly occurring anomalies
    CORRELATED_REJECTS = auto()     # Multiple rejects at same time


@dataclass
class Pattern:
    """A detected pattern in the trace data."""
    pattern_type: PatternType
    confidence: float               # 0.0 to 1.0
    start_cycle: int
    end_cycle: int
    affected_tx_ids: List[int]
    severity: str                   # 'low', 'medium', 'high', 'critical'

    # Pattern-specific details
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'type': self.pattern_type.name,
            'confidence': round(self.confidence, 3),
            'start_cycle': self.start_cycle,
            'end_cycle': self.end_cycle,
            'affected_transactions': len(self.affected_tx_ids),
            'severity': self.severity,
            'details': self.details,
        }


@dataclass
class PatternDetectionResult:
    """Results from pattern detection."""
    patterns: List[Pattern]
    analysis_window_cycles: int
    total_transactions: int

    def to_dict(self) -> dict:
        return {
            'patterns_detected': len(self.patterns),
            'analysis_window_cycles': self.analysis_window_cycles,
            'total_transactions': self.total_transactions,
            'patterns': [p.to_dict() for p in self.patterns],
        }


class PatternDetector:
    """Detect meaningful patterns in trace data."""

    def __init__(
        self,
        latency_zscore_threshold: float = 3.0,
        burst_window_cycles: int = 100,
        min_pattern_confidence: float = 0.7,
    ):
        self.latency_zscore_threshold = latency_zscore_threshold
        self.burst_window_cycles = burst_window_cycles
        self.min_pattern_confidence = min_pattern_confidence

    def detect_all(
        self,
        traces: list,
        risk_events: Optional[dict] = None,
    ) -> PatternDetectionResult:
        """Run all pattern detectors and return combined results."""
        patterns = []

        patterns.extend(self._detect_latency_spikes(traces))
        patterns.extend(self._detect_bimodal_latency(traces))
        patterns.extend(self._detect_backpressure_episodes(traces))

        if risk_events:
            patterns.extend(self._detect_rate_limit_bursts(traces, risk_events))
            patterns.extend(self._detect_position_approaches(traces, risk_events))
            patterns.extend(self._detect_kill_switch_events(traces, risk_events))

        patterns.extend(self._detect_periodic_anomalies(traces))

        # Filter by confidence
        patterns = [p for p in patterns if p.confidence >= self.min_pattern_confidence]

        # Sort by severity, then by start_cycle
        severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        patterns.sort(key=lambda p: (severity_order.get(p.severity, 4), p.start_cycle))

        return PatternDetectionResult(
            patterns=patterns,
            analysis_window_cycles=self._get_window(traces),
            total_transactions=len(traces),
        )

    def _detect_latency_spikes(self, traces: list) -> List[Pattern]:
        """Detect sudden latency increases."""
        if len(traces) < 10:
            return []

        latencies = np.array([t.latency_cycles for t in traces])
        mean = np.mean(latencies)
        std = np.std(latencies)

        if std == 0:
            return []

        patterns = []
        spike_indices = np.where((latencies - mean) / std > self.latency_zscore_threshold)[0]

        if len(spike_indices) == 0:
            return []

        # Group consecutive spikes
        groups = self._group_consecutive(spike_indices)

        for group in groups:
            affected = [traces[i] for i in group]
            avg_latency = np.mean([t.latency_cycles for t in affected])

            patterns.append(Pattern(
                pattern_type=PatternType.LATENCY_SPIKE,
                confidence=min(1.0, (avg_latency - mean) / (std * 3)),
                start_cycle=affected[0].t_ingress,
                end_cycle=affected[-1].t_egress,
                affected_tx_ids=[t.tx_id for t in affected],
                severity=self._latency_severity(avg_latency, mean, std),
                details={
                    'mean_latency': round(float(mean), 2),
                    'spike_latency': round(float(avg_latency), 2),
                    'zscore': round(float((avg_latency - mean) / std), 2),
                }
            ))

        return patterns

    def _detect_bimodal_latency(self, traces: list) -> List[Pattern]:
        """Detect if latency has two distinct populations."""
        if len(traces) < 50:
            return []

        latencies = np.array([t.latency_cycles for t in traces])

        # Simple bimodality check: look for gap in histogram
        hist, bin_edges = np.histogram(latencies, bins='auto')

        # Find valleys (potential separation points)
        valleys = []
        for i in range(1, len(hist) - 1):
            if hist[i] < hist[i-1] and hist[i] < hist[i+1]:
                if hist[i] < 0.1 * max(hist):  # Significant valley
                    valleys.append(i)

        if not valleys:
            return []

        # Use first significant valley as split point
        split_idx = valleys[0]
        split_value = bin_edges[split_idx + 1]

        low_pop = latencies[latencies < split_value]
        high_pop = latencies[latencies >= split_value]

        if len(low_pop) < 10 or len(high_pop) < 10:
            return []

        return [Pattern(
            pattern_type=PatternType.LATENCY_BIMODAL,
            confidence=0.8,
            start_cycle=traces[0].t_ingress,
            end_cycle=traces[-1].t_egress,
            affected_tx_ids=[t.tx_id for t in traces if t.latency_cycles >= split_value],
            severity='medium',
            details={
                'low_population_mean': round(float(np.mean(low_pop)), 2),
                'low_population_count': len(low_pop),
                'high_population_mean': round(float(np.mean(high_pop)), 2),
                'high_population_count': len(high_pop),
                'split_point': round(float(split_value), 2),
            }
        )]

    def _detect_rate_limit_bursts(self, traces: list, risk_events: dict) -> List[Pattern]:
        """Detect bursts that triggered rate limiting."""
        rate_rejects = risk_events.get('rate_limit_rejects', [])

        if not rate_rejects:
            return []

        patterns = []

        # Group rejects by time window
        groups = self._group_by_time_window(rate_rejects, self.burst_window_cycles)

        for group in groups:
            if len(group) < 3:  # Ignore isolated rejects
                continue

            patterns.append(Pattern(
                pattern_type=PatternType.RATE_LIMIT_BURST,
                confidence=0.95,
                start_cycle=group[0]['cycle'],
                end_cycle=group[-1]['cycle'],
                affected_tx_ids=[r['tx_id'] for r in group],
                severity='high' if len(group) > 10 else 'medium',
                details={
                    'burst_size': len(group),
                    'burst_duration_cycles': group[-1]['cycle'] - group[0]['cycle'],
                    'tokens_at_start': group[0].get('tokens_remaining', 'unknown'),
                }
            ))

        return patterns

    def _detect_backpressure_episodes(self, traces: list) -> List[Pattern]:
        """Detect sustained backpressure periods."""
        if len(traces) < 20:
            return []

        latencies = [t.latency_cycles for t in traces]
        baseline = float(np.median(latencies))

        # Find runs of elevated latency
        elevated = [lat > baseline * 1.5 for lat in latencies]

        patterns = []
        in_episode = False
        episode_start = 0

        for i, is_elevated in enumerate(elevated):
            if is_elevated and not in_episode:
                in_episode = True
                episode_start = i
            elif not is_elevated and in_episode:
                if i - episode_start >= 5:  # At least 5 transactions
                    affected = traces[episode_start:i]
                    patterns.append(Pattern(
                        pattern_type=PatternType.BACKPRESSURE_EPISODE,
                        confidence=0.85,
                        start_cycle=affected[0].t_ingress,
                        end_cycle=affected[-1].t_egress,
                        affected_tx_ids=[t.tx_id for t in affected],
                        severity='medium',
                        details={
                            'episode_length': len(affected),
                            'avg_latency_during': round(float(np.mean([t.latency_cycles for t in affected])), 2),
                            'baseline_latency': round(baseline, 2),
                        }
                    ))
                in_episode = False

        return patterns

    def _detect_kill_switch_events(self, traces: list, risk_events: dict) -> List[Pattern]:
        """Detect kill switch activations."""
        kill_events = risk_events.get('kill_switch_triggers', [])

        patterns = []
        for event in kill_events:
            patterns.append(Pattern(
                pattern_type=PatternType.KILL_SWITCH_TRIGGER,
                confidence=1.0,
                start_cycle=event['cycle'],
                end_cycle=event['cycle'],
                affected_tx_ids=event.get('blocked_tx_ids', []),
                severity='critical',
                details={
                    'trigger_reason': event.get('reason', 'manual'),
                    'orders_blocked': event.get('orders_blocked', 0),
                    'pnl_at_trigger': event.get('pnl', 'unknown'),
                }
            ))

        return patterns

    def _detect_position_approaches(self, traces: list, risk_events: dict) -> List[Pattern]:
        """Detect when position approached limits."""
        position_events = risk_events.get('position_limit_approaches', [])

        patterns = []
        for event in position_events:
            utilization = event.get('utilization', 0)
            if utilization > 0.8:  # 80% of limit
                patterns.append(Pattern(
                    pattern_type=PatternType.POSITION_LIMIT_APPROACH,
                    confidence=utilization,
                    start_cycle=event['cycle'],
                    end_cycle=event['cycle'],
                    affected_tx_ids=[event.get('tx_id', -1)],
                    severity='high' if utilization > 0.95 else 'medium',
                    details={
                        'position': event.get('position', 0),
                        'limit': event.get('limit', 0),
                        'utilization_pct': round(utilization * 100, 1),
                    }
                ))

        return patterns

    def _detect_periodic_anomalies(self, traces: list) -> List[Pattern]:
        """Detect regularly occurring anomalies (e.g., every N cycles)."""
        # Advanced: FFT analysis on anomaly timing
        # For now, simple periodicity check
        return []

    # Helper methods

    def _group_consecutive(self, indices: np.ndarray, gap: int = 2) -> List[List[int]]:
        """Group consecutive indices with small gaps."""
        if len(indices) == 0:
            return []

        groups = [[int(indices[0])]]
        for idx in indices[1:]:
            if idx - groups[-1][-1] <= gap:
                groups[-1].append(int(idx))
            else:
                groups.append([int(idx)])
        return groups

    def _group_by_time_window(self, events: list, window: int) -> List[list]:
        """Group events that occur within time window."""
        if not events:
            return []

        sorted_events = sorted(events, key=lambda e: e['cycle'])
        groups = [[sorted_events[0]]]

        for event in sorted_events[1:]:
            if event['cycle'] - groups[-1][0]['cycle'] <= window:
                groups[-1].append(event)
            else:
                groups.append([event])

        return groups

    def _get_window(self, traces: list) -> int:
        if not traces:
            return 0
        return traces[-1].t_egress - traces[0].t_ingress

    def _latency_severity(self, latency: float, mean: float, std: float) -> str:
        zscore = (latency - mean) / std if std > 0 else 0
        if zscore > 5:
            return 'critical'
        elif zscore > 4:
            return 'high'
        elif zscore > 3:
            return 'medium'
        return 'low'
