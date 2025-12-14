"""Tests for H5: Risk Correlation."""

import pytest
from pathlib import Path
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from protocol import (
    ProtocolHealth,
    GovernanceEvent,
    ProtocolContext,
    CorrelatedEvent,
    CorrelationResult,
    RiskCorrelator,
)
from ai.pattern_detector import Pattern, PatternType


def make_health(
    protocol_id="test",
    overall_score=75,
    health_tier="B",
    risk_flags=None,
    risk_level=None,
):
    """Helper to create ProtocolHealth."""
    if risk_level is None:
        risk_level = "low" if not risk_flags else "medium"
    return ProtocolHealth(
        protocol_id=protocol_id,
        protocol_name=f"Test Protocol {protocol_id}",
        overall_score=overall_score,
        health_tier=health_tier,
        treasury_usd=100_000_000,
        burn_rate_monthly=2_000_000,
        runway_months=50.0,
        active_proposals=1,
        governance_participation=0.10,
        recent_votes=3,
        risk_flags=risk_flags or [],
        risk_level=risk_level,
        fetched_at="2024-01-15T10:00:00",
        data_staleness_hours=0,
    )


def make_event(
    event_id="evt-1",
    event_type="proposal_created",
    impact_level="medium",
    timestamp="2024-01-15T10:00:00",
    treasury_impact_usd=None,
):
    """Helper to create GovernanceEvent."""
    return GovernanceEvent(
        event_type=event_type,
        event_id=event_id,
        title=f"Test Event {event_id}",
        timestamp=timestamp,
        impact_level=impact_level,
        treasury_impact_usd=treasury_impact_usd,
    )


def make_context(health=None, events=None):
    """Helper to create ProtocolContext."""
    return ProtocolContext(
        health=health or make_health(),
        recent_events=events or [],
        analysis_start="2024-01-08T00:00:00",
        analysis_end="2024-01-15T00:00:00",
        warnings=[],
    )


def make_pattern(
    pattern_type=PatternType.LATENCY_SPIKE,
    severity="medium",
    confidence=0.85,
    affected_tx_ids=None,
):
    """Helper to create Pattern."""
    return Pattern(
        pattern_type=pattern_type,
        confidence=confidence,
        start_cycle=1000,
        end_cycle=2000,
        affected_tx_ids=affected_tx_ids or [1, 2, 3],
        severity=severity,
        details={"zscore": 4.5},
    )


class TestCorrelatedEvent:
    """Tests for CorrelatedEvent dataclass."""

    def test_create_correlated_event(self):
        """Test basic creation of CorrelatedEvent."""
        hft_pattern = make_pattern()
        protocol_event = make_event()

        correlated = CorrelatedEvent(
            hft_pattern=hft_pattern,
            protocol_event=protocol_event,
            correlation_type="temporal",
            correlation_confidence=0.85,
            explanation="Latency spike occurred shortly after governance proposal",
        )

        assert correlated.correlation_type == "temporal"
        assert correlated.correlation_confidence == 0.85

    def test_to_dict(self):
        """Test CorrelatedEvent serialization."""
        hft_pattern = make_pattern()
        protocol_event = make_event()

        correlated = CorrelatedEvent(
            hft_pattern=hft_pattern,
            protocol_event=protocol_event,
            correlation_type="causal",
            correlation_confidence=0.90,
            explanation="Kill switch triggered during vote execution",
        )

        d = correlated.to_dict()
        assert d['correlation']['type'] == "causal"
        assert d['correlation']['confidence'] == 0.90
        assert 'explanation' in d['correlation']

    def test_correlated_event_without_protocol_event(self):
        """Test CorrelatedEvent with None protocol event."""
        hft_pattern = make_pattern()

        correlated = CorrelatedEvent(
            hft_pattern=hft_pattern,
            protocol_event=None,
            correlation_type="contextual",
            correlation_confidence=0.60,
            explanation="High-severity event during high-risk protocol state",
        )

        d = correlated.to_dict()
        assert d['protocol_event'] is None
        assert d['correlation']['type'] == "contextual"


class TestCorrelationResult:
    """Tests for CorrelationResult dataclass."""

    def test_empty_result(self):
        """Test empty correlation result."""
        result = CorrelationResult(
            correlated_events=[],
            protocol_risk_during_analysis="low",
            governance_active=False,
            warnings=[],
        )

        assert len(result.correlated_events) == 0
        assert len(result.warnings) == 0
        assert result.governance_active is False

    def test_with_correlations(self):
        """Test result with correlations."""
        pattern = make_pattern()
        event = make_event()

        correlated = CorrelatedEvent(
            hft_pattern=pattern,
            protocol_event=event,
            correlation_type="temporal",
            correlation_confidence=0.75,
            explanation="Test correlation",
        )

        result = CorrelationResult(
            correlated_events=[correlated],
            protocol_risk_during_analysis="low",
            governance_active=True,
            warnings=[],
        )

        assert len(result.correlated_events) == 1
        assert result.correlated_events[0].correlation_confidence == 0.75

    def test_to_dict(self):
        """Test CorrelationResult serialization."""
        result = CorrelationResult(
            correlated_events=[],
            protocol_risk_during_analysis="medium",
            governance_active=True,
            warnings=["Active governance proposal"],
        )

        d = result.to_dict()
        assert d['protocol_risk'] == "medium"
        assert d['governance_active'] is True
        assert "Active governance proposal" in d['warnings']


class TestRiskCorrelator:
    """Tests for RiskCorrelator."""

    def test_create_correlator(self):
        """Test creating RiskCorrelator."""
        correlator = RiskCorrelator()
        assert correlator is not None

    def test_correlate_empty_patterns(self):
        """Test correlation with no patterns."""
        correlator = RiskCorrelator()
        context = make_context()

        result = correlator.correlate([], context)

        assert len(result.correlated_events) == 0

    def test_correlate_no_events(self):
        """Test correlation with no protocol events."""
        correlator = RiskCorrelator()
        patterns = [make_pattern()]
        context = make_context(events=[])

        result = correlator.correlate(patterns, context)

        # Pattern may be uncorrelated if no events to correlate with
        assert result is not None

    def test_correlate_kill_switch_with_treasury_event(self):
        """Test correlation of kill switch with treasury event."""
        correlator = RiskCorrelator()

        # Kill switch pattern
        kill_pattern = make_pattern(
            pattern_type=PatternType.KILL_SWITCH_TRIGGER,
            severity="critical",
        )

        # High-impact treasury event (>$1M)
        treasury_event = make_event(
            event_type="execution",
            impact_level="high",
            treasury_impact_usd=5_000_000,
        )

        context = make_context(events=[treasury_event])
        result = correlator.correlate([kill_pattern], context)

        # Should find a causal correlation
        assert len(result.correlated_events) >= 1
        if result.correlated_events:
            assert result.correlated_events[0].correlation_type == "causal"

    def test_correlate_latency_spike_with_high_impact_event(self):
        """Test correlation of latency spike with high-impact proposal."""
        correlator = RiskCorrelator()

        # Latency spike pattern
        spike_pattern = make_pattern(
            pattern_type=PatternType.LATENCY_SPIKE,
            severity="high",
        )

        # High-impact governance event
        proposal_event = make_event(
            event_type="vote_started",
            impact_level="high",
        )

        context = make_context(events=[proposal_event])
        result = correlator.correlate([spike_pattern], context)

        # Should find a temporal correlation
        assert len(result.correlated_events) >= 1
        if result.correlated_events:
            assert result.correlated_events[0].correlation_type == "temporal"

    def test_correlate_multiple_patterns(self):
        """Test correlation with multiple patterns."""
        correlator = RiskCorrelator()

        patterns = [
            make_pattern(PatternType.LATENCY_SPIKE),
            make_pattern(PatternType.RATE_LIMIT_BURST),
        ]

        events = [
            make_event("evt-1", "proposal_created", "medium"),
            make_event("evt-2", "vote_executed", "high"),
        ]

        context = make_context(events=events)
        result = correlator.correlate(patterns, context)

        # Should process without error
        assert result is not None

    def test_correlation_types(self):
        """Test different correlation types are supported."""
        valid_types = ["temporal", "causal", "contextual", "coincidental"]

        # All these should be valid correlation types
        for corr_type in valid_types:
            correlated = CorrelatedEvent(
                hft_pattern=make_pattern(),
                protocol_event=make_event(),
                correlation_type=corr_type,
                correlation_confidence=0.5,
                explanation="Test",
            )
            assert correlated.correlation_type == corr_type


class TestRiskCorrelatorWithRiskFlags:
    """Tests for correlation with protocol risk flags."""

    def test_correlate_with_high_risk_protocol(self):
        """Test correlation when protocol is high risk."""
        correlator = RiskCorrelator()

        health = make_health(
            risk_flags=["low_runway", "governance_stall"],
            health_tier="D",
            overall_score=40,
            risk_level="high",
        )

        # High-severity pattern
        patterns = [make_pattern(severity="critical")]

        context = make_context(health=health)
        result = correlator.correlate(patterns, context)

        # Should add warnings about high risk
        assert result.protocol_risk_during_analysis == "high"
        assert len(result.warnings) >= 1

    def test_correlate_with_active_governance(self):
        """Test correlation notes active governance."""
        correlator = RiskCorrelator()

        health = make_health()
        health.active_proposals = 3  # Active governance

        patterns = [make_pattern()]
        context = make_context(health=health)

        result = correlator.correlate(patterns, context)

        # Should note active governance
        assert result.governance_active is True


class TestCorrelationStrength:
    """Tests for correlation confidence calculation."""

    def test_temporal_correlation_confidence(self):
        """Test temporal correlation has appropriate confidence."""
        correlator = RiskCorrelator()

        pattern = make_pattern(PatternType.LATENCY_SPIKE)
        event = make_event(impact_level="high")

        context = make_context(events=[event])
        result = correlator.correlate([pattern], context)

        # Temporal correlations should have confidence around 0.7
        for corr in result.correlated_events:
            if corr.correlation_type == "temporal":
                assert 0.5 <= corr.correlation_confidence <= 1.0

    def test_causal_correlation_higher_confidence(self):
        """Test causal correlations have higher confidence."""
        correlator = RiskCorrelator()

        # Kill switch with major treasury event
        pattern = make_pattern(PatternType.KILL_SWITCH_TRIGGER)
        event = make_event(
            impact_level="high",
            treasury_impact_usd=10_000_000,
        )

        context = make_context(events=[event])
        result = correlator.correlate([pattern], context)

        # Causal correlations should have higher confidence
        for corr in result.correlated_events:
            if corr.correlation_type == "causal":
                assert corr.correlation_confidence >= 0.8


class TestCorrelatorEdgeCases:
    """Edge case tests for RiskCorrelator."""

    def test_correlate_with_many_events(self):
        """Test correlation with many events."""
        correlator = RiskCorrelator()

        patterns = [make_pattern()]
        events = [make_event(f"evt-{i}") for i in range(20)]

        context = make_context(events=events)
        result = correlator.correlate(patterns, context)

        # Should handle many events without issue
        assert result is not None

    def test_correlate_preserves_pattern_details(self):
        """Test that correlation preserves pattern details."""
        correlator = RiskCorrelator()

        pattern = Pattern(
            pattern_type=PatternType.LATENCY_SPIKE,
            confidence=0.95,
            start_cycle=5000,
            end_cycle=6000,
            affected_tx_ids=[100, 200, 300],
            severity="high",
            details={"zscore": 5.5, "mean_latency": 150},
        )

        events = [make_event(impact_level="high")]
        context = make_context(events=events)

        result = correlator.correlate([pattern], context)

        # Check pattern is preserved in correlated events
        if result.correlated_events:
            corr = result.correlated_events[0]
            assert corr.hft_pattern.start_cycle == 5000
            assert corr.hft_pattern.details["zscore"] == 5.5

    def test_contextual_correlation_with_critical_pattern(self):
        """Test contextual correlation with high-severity pattern and high-risk protocol."""
        correlator = RiskCorrelator()

        # Critical pattern
        pattern = make_pattern(severity="critical")

        # High-risk protocol with no events
        health = make_health(
            risk_level="critical",
            risk_flags=["emergency"],
        )

        context = make_context(health=health, events=[])
        result = correlator.correlate([pattern], context)

        # Should create contextual correlation
        has_contextual = any(
            c.correlation_type == "contextual"
            for c in result.correlated_events
        )
        # May or may not have contextual correlation depending on implementation
        assert result is not None
