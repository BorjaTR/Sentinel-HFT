"""Correlate HFT events with protocol events."""

from dataclasses import dataclass
from typing import Optional, List

from .context import ProtocolContext, GovernanceEvent


@dataclass
class CorrelatedEvent:
    """An HFT event correlated with protocol context."""
    hft_pattern: 'Pattern'
    protocol_event: Optional[GovernanceEvent]
    correlation_type: str           # 'temporal', 'causal', 'contextual', 'coincidental'
    correlation_confidence: float   # 0-1
    explanation: str

    def to_dict(self) -> dict:
        return {
            'hft_pattern': self.hft_pattern.to_dict(),
            'protocol_event': self.protocol_event.to_dict() if self.protocol_event else None,
            'correlation': {
                'type': self.correlation_type,
                'confidence': self.correlation_confidence,
                'explanation': self.explanation,
            },
        }


@dataclass
class CorrelationResult:
    """Results from correlation analysis."""
    correlated_events: List[CorrelatedEvent]
    protocol_risk_during_analysis: str
    governance_active: bool
    warnings: List[str]

    def to_dict(self) -> dict:
        return {
            'correlated_events': [e.to_dict() for e in self.correlated_events],
            'protocol_risk': self.protocol_risk_during_analysis,
            'governance_active': self.governance_active,
            'warnings': self.warnings,
        }


class RiskCorrelator:
    """Correlate HFT patterns with protocol events."""

    def __init__(self, time_window_hours: float = 24.0):
        """
        Initialize correlator.

        Args:
            time_window_hours: How far back to look for protocol events
        """
        self.time_window_hours = time_window_hours

    def correlate(
        self,
        patterns: list,
        protocol_context: ProtocolContext,
    ) -> CorrelationResult:
        """
        Find correlations between HFT patterns and protocol events.

        Args:
            patterns: Detected HFT patterns
            protocol_context: Protocol context including governance events

        Returns:
            CorrelationResult with matched events
        """
        correlated = []
        warnings = []

        for pattern in patterns:
            correlation = self._find_correlation(pattern, protocol_context)
            if correlation:
                correlated.append(correlation)

        # Check for high-risk conditions
        if protocol_context.health.risk_level in ('high', 'critical'):
            warnings.append(
                f"Protocol is in {protocol_context.health.risk_level} risk state: "
                f"{', '.join(protocol_context.health.risk_flags)}"
            )

        if protocol_context.has_active_governance():
            warnings.append(
                f"Active governance: {protocol_context.health.active_proposals} proposal(s) in progress"
            )

        return CorrelationResult(
            correlated_events=correlated,
            protocol_risk_during_analysis=protocol_context.health.risk_level,
            governance_active=protocol_context.has_active_governance(),
            warnings=warnings,
        )

    def _find_correlation(
        self,
        pattern,
        context: ProtocolContext,
    ) -> Optional[CorrelatedEvent]:
        """Find correlation for a single pattern."""

        # Import here to avoid circular import
        from ai.pattern_detector import PatternType

        # Look for temporal correlation with governance events
        for event in context.recent_events:
            correlation = self._check_temporal_correlation(pattern, event)
            if correlation:
                return correlation

        # Check for protocol risk correlation
        if pattern.severity in ('high', 'critical') and context.health.risk_level in ('high', 'critical'):
            return CorrelatedEvent(
                hft_pattern=pattern,
                protocol_event=None,
                correlation_type='contextual',
                correlation_confidence=0.6,
                explanation=(
                    f"High-severity HFT event during high-risk protocol state. "
                    f"Protocol risk flags: {', '.join(context.health.risk_flags)}"
                ),
            )

        return None

    def _check_temporal_correlation(
        self,
        pattern,
        event: GovernanceEvent,
    ) -> Optional[CorrelatedEvent]:
        """Check if pattern is temporally correlated with governance event."""

        # Import here to avoid circular import
        from ai.pattern_detector import PatternType

        # For patterns that might be affected by governance
        if pattern.pattern_type in (
            PatternType.LATENCY_SPIKE,
            PatternType.THROUGHPUT_DROP,
            PatternType.RATE_LIMIT_BURST,
        ):
            # Check if governance event is high impact
            if event.impact_level == 'high':
                return CorrelatedEvent(
                    hft_pattern=pattern,
                    protocol_event=event,
                    correlation_type='temporal',
                    correlation_confidence=0.7,
                    explanation=(
                        f"HFT {pattern.pattern_type.name} occurred near governance event: "
                        f"'{event.title}'. Market activity may have increased around vote."
                    ),
                )

        # Kill switch during treasury event
        if pattern.pattern_type == PatternType.KILL_SWITCH_TRIGGER:
            if event.treasury_impact_usd and abs(event.treasury_impact_usd) > 1_000_000:
                return CorrelatedEvent(
                    hft_pattern=pattern,
                    protocol_event=event,
                    correlation_type='causal',
                    correlation_confidence=0.85,
                    explanation=(
                        f"Kill switch triggered near major treasury event: "
                        f"'{event.title}' (${event.treasury_impact_usd/1e6:.1f}M impact). "
                        f"This may indicate protective response to protocol instability."
                    ),
                )

        return None
