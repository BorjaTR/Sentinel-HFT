"""Tests for H5: Health Integration."""

import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from protocol import (
    ProtocolHealth,
    TradingRiskAssessment,
    HealthIntegrator,
)


def make_health(
    health_tier="B",
    overall_score=75,
    runway_months=24.0,
    active_proposals=1,
    governance_participation=0.10,
    risk_flags=None,
):
    """Helper to create ProtocolHealth."""
    return ProtocolHealth(
        protocol_id="test",
        protocol_name="Test Protocol",
        overall_score=overall_score,
        health_tier=health_tier,
        treasury_usd=100_000_000,
        burn_rate_monthly=4_000_000,
        runway_months=runway_months,
        active_proposals=active_proposals,
        governance_participation=governance_participation,
        recent_votes=3,
        risk_flags=risk_flags or [],
        risk_level="low" if not risk_flags else "medium",
        fetched_at="2024-01-15T10:00:00",
        data_staleness_hours=0,
    )


def make_hft_metrics(
    p50_cycles=50,
    p99_cycles=100,
    anomaly_count=0,
    rate_limit_rejects=0,
    kill_switch_triggered=False,
):
    """Helper to create HFT metrics dict."""
    return {
        "latency": {
            "count": 1000,
            "p50_cycles": p50_cycles,
            "p99_cycles": p99_cycles,
            "p999_cycles": p99_cycles * 2,
        },
        "anomalies": {
            "count": anomaly_count,
        },
        "risk": {
            "rate_limit_rejects": rate_limit_rejects,
            "position_limit_rejects": 0,
            "kill_switch_triggered": kill_switch_triggered,
        },
    }


class TestTradingRiskAssessment:
    """Tests for TradingRiskAssessment dataclass."""

    def test_create_assessment(self):
        """Test basic creation of TradingRiskAssessment."""
        assessment = TradingRiskAssessment(
            hft_health="healthy",
            latency_acceptable=True,
            risk_controls_active=True,
            anomalies_detected=0,
            protocol_health="B",
            protocol_runway_months=24.0,
            governance_risk=False,
            combined_risk="low",
            recommendation="Normal trading operations",
        )

        assert assessment.hft_health == "healthy"
        assert assessment.protocol_health == "B"
        assert assessment.combined_risk == "low"

    def test_to_dict(self):
        """Test TradingRiskAssessment serialization."""
        assessment = TradingRiskAssessment(
            hft_health="degraded",
            latency_acceptable=False,
            risk_controls_active=True,
            anomalies_detected=5,
            protocol_health="C",
            protocol_runway_months=12.0,
            governance_risk=True,
            combined_risk="medium",
            recommendation="Reduce position sizes",
        )

        d = assessment.to_dict()
        assert d['hft']['health'] == "degraded"
        assert d['protocol']['health'] == "C"
        assert d['combined']['risk_level'] == "medium"
        assert "Reduce position sizes" in d['combined']['recommendation']


class TestHealthIntegrator:
    """Tests for HealthIntegrator."""

    def test_create_integrator(self):
        """Test creating HealthIntegrator."""
        integrator = HealthIntegrator()
        assert integrator is not None

    def test_assess_healthy_system(self):
        """Test assessment of healthy HFT + healthy protocol."""
        integrator = HealthIntegrator()

        metrics = make_hft_metrics(
            p50_cycles=5,
            p99_cycles=8,
            anomaly_count=0,
        )

        health = make_health(
            health_tier="A",
            overall_score=85,
            runway_months=48,
        )

        result = integrator.assess(metrics, health)

        assert result.hft_health == "healthy"
        assert result.combined_risk in ("low", "medium")

    def test_assess_degraded_hft(self):
        """Test assessment of degraded HFT system."""
        integrator = HealthIntegrator()

        # High latency, some anomalies
        metrics = make_hft_metrics(
            p50_cycles=50,
            p99_cycles=100,
            anomaly_count=10,
        )

        health = make_health(health_tier="A")

        result = integrator.assess(metrics, health)

        assert result.hft_health in ("degraded", "critical")
        assert result.combined_risk in ("medium", "high", "critical")

    def test_assess_weak_protocol(self):
        """Test assessment with weak protocol health."""
        integrator = HealthIntegrator()

        metrics = make_hft_metrics(
            p50_cycles=5,
            p99_cycles=8,
        )

        health = make_health(
            health_tier="D",
            overall_score=35,
            runway_months=3,
            risk_flags=["low_runway", "low_participation"],
        )

        result = integrator.assess(metrics, health)

        assert result.protocol_health == "D"
        assert result.combined_risk in ("medium", "high", "critical")

    def test_assess_both_weak(self):
        """Test assessment when both HFT and protocol are weak."""
        integrator = HealthIntegrator()

        # Degraded HFT
        metrics = make_hft_metrics(
            p99_cycles=50,
            anomaly_count=10,
        )

        # Weak protocol
        health = make_health(
            health_tier="D",
            overall_score=30,
            runway_months=2,
            risk_flags=["low_runway"],
        )

        result = integrator.assess(metrics, health)

        # Should be high or critical risk
        assert result.combined_risk in ("high", "critical")

    def test_assess_with_governance_activity(self):
        """Test assessment considers governance activity."""
        integrator = HealthIntegrator()

        metrics = make_hft_metrics(p50_cycles=5, p99_cycles=8)

        # Active governance with low participation (triggers governance_risk)
        health = make_health(
            health_tier="B",
            active_proposals=5,
            governance_participation=0.05,  # Below 0.1 threshold
        )

        result = integrator.assess(metrics, health)

        # Should note governance risk
        assert result.governance_risk is True


class TestHealthIntegratorRiskMatrix:
    """Tests for risk matrix calculations."""

    def test_healthy_hft_a_tier_protocol(self):
        """Test: Healthy HFT + A-tier protocol = Low risk."""
        integrator = HealthIntegrator()

        metrics = make_hft_metrics(p50_cycles=5, p99_cycles=8)
        health = make_health(health_tier="A", overall_score=90, runway_months=60)

        result = integrator.assess(metrics, health)
        assert result.combined_risk == "low"

    def test_healthy_hft_c_tier_protocol(self):
        """Test: Healthy HFT + C-tier protocol."""
        integrator = HealthIntegrator()

        metrics = make_hft_metrics(p50_cycles=5, p99_cycles=8)
        health = make_health(health_tier="C", overall_score=55)

        result = integrator.assess(metrics, health)
        # C-tier adds 1 to score, so combined may be low or medium
        assert result.combined_risk in ("low", "medium")

    def test_degraded_hft_b_tier_protocol(self):
        """Test: Degraded HFT + B-tier protocol."""
        integrator = HealthIntegrator()

        metrics = make_hft_metrics(
            p99_cycles=50,  # Above default threshold of 10
            anomaly_count=10,  # Above default threshold of 5
        )
        health = make_health(health_tier="B")

        result = integrator.assess(metrics, health)
        assert result.combined_risk in ("medium", "high")


class TestHealthIntegratorRecommendations:
    """Tests for recommendation generation."""

    def test_low_risk_recommendation(self):
        """Test recommendation for low risk."""
        integrator = HealthIntegrator()

        metrics = make_hft_metrics(p50_cycles=5, p99_cycles=8)
        health = make_health(health_tier="A", overall_score=90)

        result = integrator.assess(metrics, health)

        # Low risk should have positive recommendation
        assert result.recommendation is not None
        assert len(result.recommendation) > 0

    def test_high_risk_recommendation(self):
        """Test recommendation for high risk."""
        integrator = HealthIntegrator()

        metrics = make_hft_metrics(
            p99_cycles=50,
            anomaly_count=10,
        )
        health = make_health(
            health_tier="D",
            runway_months=3,
            risk_flags=["low_runway"],
        )

        result = integrator.assess(metrics, health)

        # High risk should have cautious recommendation
        assert result.recommendation is not None
        assert result.combined_risk in ("medium", "high", "critical")


class TestHealthIntegratorEdgeCases:
    """Edge case tests for HealthIntegrator."""

    def test_empty_metrics(self):
        """Test handling of minimal metrics."""
        integrator = HealthIntegrator()

        metrics = {}
        health = make_health()

        result = integrator.assess(metrics, health)
        assert result is not None

    def test_missing_latency_data(self):
        """Test handling of missing latency data."""
        integrator = HealthIntegrator()

        metrics = {"risk": {"kill_switch_triggered": False}}
        health = make_health()

        result = integrator.assess(metrics, health)
        assert result is not None

    def test_zero_values(self):
        """Test handling of zero values."""
        integrator = HealthIntegrator()

        metrics = make_hft_metrics(
            p50_cycles=0,
            p99_cycles=0,
        )
        health = make_health()

        result = integrator.assess(metrics, health)
        assert result is not None

    def test_extreme_latency(self):
        """Test handling of extreme latency values."""
        integrator = HealthIntegrator()

        metrics = make_hft_metrics(
            p50_cycles=10000,
            p99_cycles=100000,
        )
        health = make_health()

        result = integrator.assess(metrics, health)
        # Should detect as degraded or critical
        assert result.hft_health in ("degraded", "critical")

    def test_f_tier_protocol(self):
        """Test handling of F-tier protocol."""
        integrator = HealthIntegrator()

        metrics = make_hft_metrics(p50_cycles=5, p99_cycles=8)
        health = make_health(
            health_tier="F",
            overall_score=10,
            runway_months=0.5,
            risk_flags=["critical_runway", "governance_failure"],
        )

        result = integrator.assess(metrics, health)
        # Should be high risk due to protocol
        assert result.combined_risk in ("high", "critical")

    def test_none_protocol_health(self):
        """Test handling of None protocol health."""
        integrator = HealthIntegrator()

        metrics = make_hft_metrics(p50_cycles=5, p99_cycles=8)

        result = integrator.assess(metrics, None)

        assert result is not None
        assert result.protocol_health == "unknown"


class TestHealthIntegratorIntegration:
    """Integration tests for HealthIntegrator with real scenarios."""

    def test_normal_trading_day(self):
        """Test typical healthy trading scenario."""
        integrator = HealthIntegrator()

        metrics = make_hft_metrics(
            p50_cycles=5,
            p99_cycles=8,
            anomaly_count=0,
            rate_limit_rejects=2,
        )

        health = make_health(
            health_tier="B",
            overall_score=72,
            runway_months=30,
            active_proposals=1,
        )

        result = integrator.assess(metrics, health)

        assert result.hft_health == "healthy"
        assert result.combined_risk == "low"

    def test_market_stress_scenario(self):
        """Test scenario with market stress indicators."""
        integrator = HealthIntegrator()

        # High activity, some anomalies
        metrics = make_hft_metrics(
            p50_cycles=50,
            p99_cycles=100,
            anomaly_count=8,
            rate_limit_rejects=100,
        )

        health = make_health(
            health_tier="B",
            active_proposals=2,
        )

        result = integrator.assess(metrics, health)

        # Should show elevated risk
        assert result.combined_risk in ("medium", "high", "critical")

    def test_protocol_crisis_scenario(self):
        """Test scenario with protocol in crisis."""
        integrator = HealthIntegrator()

        metrics = make_hft_metrics(p50_cycles=5, p99_cycles=8)  # HFT is fine

        health = make_health(
            health_tier="D",
            overall_score=25,
            runway_months=1,
            active_proposals=0,
            governance_participation=0.01,
            risk_flags=["critical_runway", "governance_stall", "depeg_risk"],
        )

        result = integrator.assess(metrics, health)

        # Should recommend caution despite healthy HFT
        assert result.combined_risk in ("high", "critical")
