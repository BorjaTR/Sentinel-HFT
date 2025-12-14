"""Tests for H5: Protocol Context Provider."""

import pytest
import json
from pathlib import Path
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from protocol import (
    ProtocolHealth,
    GovernanceEvent,
    ProtocolContext,
    ProtocolContextProvider,
)


class TestProtocolHealth:
    """Tests for ProtocolHealth dataclass."""

    def test_create_protocol_health(self):
        """Test basic creation of ProtocolHealth."""
        health = ProtocolHealth(
            protocol_id="arbitrum",
            protocol_name="Arbitrum One",
            overall_score=85,
            health_tier="A",
            treasury_usd=2_500_000_000,
            burn_rate_monthly=4_000_000,
            runway_months=48.0,
            active_proposals=2,
            governance_participation=0.12,
            recent_votes=5,
            risk_flags=[],
            risk_level="low",
            fetched_at="2024-01-15T10:00:00",
            data_staleness_hours=0,
        )

        assert health.protocol_id == "arbitrum"
        assert health.overall_score == 85
        assert health.health_tier == "A"
        assert health.treasury_usd == 2_500_000_000

    def test_to_dict(self):
        """Test ProtocolHealth serialization."""
        health = ProtocolHealth(
            protocol_id="optimism",
            protocol_name="Optimism",
            overall_score=78,
            health_tier="B",
            treasury_usd=800_000_000,
            burn_rate_monthly=2_200_000,
            runway_months=36.0,
            active_proposals=1,
            governance_participation=0.08,
            recent_votes=3,
            risk_flags=[],
            risk_level="low",
            fetched_at="2024-01-15T10:00:00",
            data_staleness_hours=0,
        )

        d = health.to_dict()
        assert d['protocol_name'] == "Optimism"
        assert d['health']['tier'] == "B"
        assert d['financial']['treasury_usd'] == 800_000_000
        assert d['governance']['active_proposals'] == 1

    def test_health_tier_boundaries(self):
        """Test health tier determination."""
        # A-tier: 80+
        health_a = ProtocolHealth(
            protocol_id="test", protocol_name="Test", overall_score=80,
            health_tier="A", treasury_usd=0, burn_rate_monthly=0,
            runway_months=0, active_proposals=0, governance_participation=0,
            recent_votes=0, risk_flags=[], risk_level="low",
            fetched_at="2024-01-15T10:00:00", data_staleness_hours=0,
        )
        assert health_a.health_tier == "A"

        # B-tier: 60-79
        health_b = ProtocolHealth(
            protocol_id="test", protocol_name="Test", overall_score=65,
            health_tier="B", treasury_usd=0, burn_rate_monthly=0,
            runway_months=0, active_proposals=0, governance_participation=0,
            recent_votes=0, risk_flags=[], risk_level="low",
            fetched_at="2024-01-15T10:00:00", data_staleness_hours=0,
        )
        assert health_b.health_tier == "B"

    def test_to_summary(self):
        """Test to_summary method."""
        health = ProtocolHealth(
            protocol_id="test",
            protocol_name="Test Protocol",
            overall_score=75,
            health_tier="B",
            treasury_usd=100_000_000,
            burn_rate_monthly=2_000_000,
            runway_months=50.0,
            active_proposals=1,
            governance_participation=0.10,
            recent_votes=3,
            risk_flags=[],
            risk_level="low",
            fetched_at="2024-01-15T10:00:00",
            data_staleness_hours=0,
        )

        summary = health.to_summary()
        assert "Test Protocol" in summary
        assert "B-tier" in summary


class TestGovernanceEvent:
    """Tests for GovernanceEvent dataclass."""

    def test_create_governance_event(self):
        """Test basic creation of GovernanceEvent."""
        event = GovernanceEvent(
            event_type="proposal_created",
            event_id="prop-123",
            title="Increase staking rewards",
            timestamp="2024-01-14T12:00:00",
            impact_level="high",
        )

        assert event.event_id == "prop-123"
        assert event.event_type == "proposal_created"
        assert event.impact_level == "high"

    def test_to_dict(self):
        """Test GovernanceEvent serialization."""
        event = GovernanceEvent(
            event_type="vote_executed",
            event_id="vote-456",
            title="Fee reduction passed",
            timestamp="2024-01-15T08:00:00",
            impact_level="medium",
            vote_outcome="passed",
            treasury_impact_usd=1_000_000,
        )

        d = event.to_dict()
        assert d['id'] == "vote-456"
        assert d['impact'] == "medium"
        assert d['vote_outcome'] == "passed"

    def test_event_with_treasury_impact(self):
        """Test GovernanceEvent with treasury impact."""
        event = GovernanceEvent(
            event_type="execution",
            event_id="exec-789",
            title="Grant allocation",
            timestamp="2024-01-15T10:00:00",
            impact_level="high",
            treasury_impact_usd=5_000_000,
        )

        d = event.to_dict()
        assert d['treasury_impact_usd'] == 5_000_000


class TestProtocolContext:
    """Tests for ProtocolContext dataclass."""

    def test_create_protocol_context(self):
        """Test creation of ProtocolContext with health and events."""
        health = ProtocolHealth(
            protocol_id="arbitrum",
            protocol_name="Arbitrum One",
            overall_score=85,
            health_tier="A",
            treasury_usd=2_500_000_000,
            burn_rate_monthly=4_000_000,
            runway_months=48.0,
            active_proposals=2,
            governance_participation=0.12,
            recent_votes=5,
            risk_flags=[],
            risk_level="low",
            fetched_at="2024-01-15T10:00:00",
            data_staleness_hours=0,
        )

        events = [
            GovernanceEvent(
                event_type="proposal_created",
                event_id="prop-1",
                title="Proposal 1",
                timestamp="2024-01-14T12:00:00",
                impact_level="high",
            ),
        ]

        context = ProtocolContext(
            health=health,
            recent_events=events,
            analysis_start="2024-01-08T00:00:00",
            analysis_end="2024-01-15T00:00:00",
            warnings=[],
        )

        assert context.health.protocol_id == "arbitrum"
        assert len(context.recent_events) == 1
        assert context.analysis_start == "2024-01-08T00:00:00"

    def test_to_dict(self):
        """Test ProtocolContext serialization."""
        health = ProtocolHealth(
            protocol_id="optimism", protocol_name="Optimism",
            overall_score=78, health_tier="B", treasury_usd=800_000_000,
            burn_rate_monthly=2_200_000, runway_months=36.0,
            active_proposals=1, governance_participation=0.08, recent_votes=3,
            risk_flags=[], risk_level="low",
            fetched_at="2024-01-15T10:00:00", data_staleness_hours=0,
        )

        context = ProtocolContext(
            health=health,
            recent_events=[],
            analysis_start="2024-01-08T00:00:00",
            analysis_end="2024-01-15T00:00:00",
            warnings=["Test warning"],
        )

        d = context.to_dict()
        assert d['health']['protocol_name'] == "Optimism"
        assert d['warnings'] == ["Test warning"]

    def test_has_active_governance(self):
        """Test has_active_governance method."""
        health_active = ProtocolHealth(
            protocol_id="test", protocol_name="Test", overall_score=75,
            health_tier="B", treasury_usd=100_000_000, burn_rate_monthly=2_000_000,
            runway_months=50.0, active_proposals=2, governance_participation=0.10,
            recent_votes=3, risk_flags=[], risk_level="low",
            fetched_at="2024-01-15T10:00:00", data_staleness_hours=0,
        )

        context = ProtocolContext(
            health=health_active,
            recent_events=[],
            analysis_start="2024-01-08T00:00:00",
            analysis_end="2024-01-15T00:00:00",
        )

        assert context.has_active_governance() is True

    def test_has_risk_flags(self):
        """Test has_risk_flags method."""
        health_risky = ProtocolHealth(
            protocol_id="test", protocol_name="Test", overall_score=40,
            health_tier="D", treasury_usd=10_000_000, burn_rate_monthly=5_000_000,
            runway_months=2.0, active_proposals=0, governance_participation=0.01,
            recent_votes=0, risk_flags=["low_runway", "low_participation"],
            risk_level="high", fetched_at="2024-01-15T10:00:00", data_staleness_hours=0,
        )

        context = ProtocolContext(
            health=health_risky,
            recent_events=[],
            analysis_start="",
            analysis_end="",
        )

        assert context.has_risk_flags() is True


class TestProtocolContextProvider:
    """Tests for ProtocolContextProvider."""

    def test_create_provider_no_sentinel(self):
        """Test creating provider without Sentinel integration."""
        provider = ProtocolContextProvider(sentinel_path=None)
        assert provider.sentinel_path is None

    def test_load_static_config_arbitrum(self):
        """Test loading Arbitrum static config."""
        provider = ProtocolContextProvider(sentinel_path=None)
        context = provider.get_context("arbitrum")

        assert context is not None
        assert context.health.protocol_id == "arbitrum"
        assert context.health.protocol_name == "Arbitrum"
        assert context.health.health_tier == "A"
        assert context.health.treasury_usd == 2_500_000_000

    def test_load_static_config_optimism(self):
        """Test loading Optimism static config."""
        provider = ProtocolContextProvider(sentinel_path=None)
        context = provider.get_context("optimism")

        assert context is not None
        assert context.health.protocol_id == "optimism"
        assert context.health.protocol_name == "Optimism"
        assert context.health.health_tier == "B"

    def test_load_default_config(self):
        """Test loading default config for unknown protocol."""
        provider = ProtocolContextProvider(sentinel_path=None)
        context = provider.get_context("unknown_protocol")

        assert context is not None
        assert context.health.protocol_id == "unknown"
        assert context.health.health_tier == "C"
        assert "unknown_protocol" in context.health.risk_flags

    def test_list_available_static_configs(self):
        """Test that static configs exist."""
        configs_dir = Path(__file__).parent.parent / 'protocol' / 'configs'
        assert (configs_dir / 'arbitrum.json').exists()
        assert (configs_dir / 'optimism.json').exists()
        assert (configs_dir / 'default.json').exists()


class TestProtocolHealthRiskFlags:
    """Tests for risk flag handling in ProtocolHealth."""

    def test_with_risk_flags(self):
        """Test ProtocolHealth with risk flags."""
        health = ProtocolHealth(
            protocol_id="risky",
            protocol_name="Risky Protocol",
            overall_score=45,
            health_tier="D",
            treasury_usd=10_000_000,
            burn_rate_monthly=5_000_000,
            runway_months=2.0,
            active_proposals=0,
            governance_participation=0.01,
            recent_votes=0,
            risk_flags=["low_runway", "low_participation", "governance_stall"],
            risk_level="high",
            fetched_at="2024-01-15T10:00:00",
            data_staleness_hours=0,
        )

        assert len(health.risk_flags) == 3
        assert "low_runway" in health.risk_flags
        assert health.risk_level == "high"

    def test_runway_calculation(self):
        """Test runway months calculation."""
        health = ProtocolHealth(
            protocol_id="test",
            protocol_name="Test",
            overall_score=70,
            health_tier="B",
            treasury_usd=100_000_000,
            burn_rate_monthly=5_000_000,
            runway_months=20.0,  # 100M / 5M = 20 months
            active_proposals=0,
            governance_participation=0,
            recent_votes=0,
            risk_flags=[],
            risk_level="low",
            fetched_at="2024-01-15T10:00:00",
            data_staleness_hours=0,
        )

        # Verify runway calculation
        expected_runway = health.treasury_usd / health.burn_rate_monthly
        assert abs(health.runway_months - expected_runway) < 0.1


class TestProtocolContextProviderEdgeCases:
    """Edge case tests for ProtocolContextProvider."""

    def test_empty_events_list(self):
        """Test context with empty events list."""
        provider = ProtocolContextProvider()
        context = provider.get_context("optimism")

        assert context.recent_events == []

    def test_context_with_warnings(self):
        """Test context includes warnings from config."""
        provider = ProtocolContextProvider()
        context = provider.get_context("unknown")

        # Default config has a warning about unavailable data
        assert len(context.warnings) > 0
