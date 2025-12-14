"""Protocol health integration for trading analysis."""

from dataclasses import dataclass
from typing import Optional

from .context import ProtocolHealth


@dataclass
class TradingRiskAssessment:
    """Combined trading + protocol risk assessment."""

    # HFT metrics
    hft_health: str                 # 'healthy', 'degraded', 'critical'
    latency_acceptable: bool
    risk_controls_active: bool
    anomalies_detected: int

    # Protocol metrics
    protocol_health: str            # 'A', 'B', 'C', 'D', 'F', 'unknown'
    protocol_runway_months: float
    governance_risk: bool

    # Combined assessment
    combined_risk: str              # 'low', 'medium', 'high', 'critical'
    recommendation: str

    def to_dict(self) -> dict:
        return {
            'hft': {
                'health': self.hft_health,
                'latency_acceptable': self.latency_acceptable,
                'risk_controls_active': self.risk_controls_active,
                'anomalies': self.anomalies_detected,
            },
            'protocol': {
                'health': self.protocol_health,
                'runway_months': self.protocol_runway_months,
                'governance_risk': self.governance_risk,
            },
            'combined': {
                'risk_level': self.combined_risk,
                'recommendation': self.recommendation,
            },
        }


class HealthIntegrator:
    """Integrate HFT and protocol health into unified assessment."""

    def __init__(
        self,
        latency_threshold_cycles: int = 10,
        anomaly_threshold: int = 5,
        min_runway_months: float = 6.0,
    ):
        self.latency_threshold_cycles = latency_threshold_cycles
        self.anomaly_threshold = anomaly_threshold
        self.min_runway_months = min_runway_months

    def assess(
        self,
        hft_metrics: dict,
        protocol_health: Optional[ProtocolHealth],
    ) -> TradingRiskAssessment:
        """
        Create combined risk assessment.

        Args:
            hft_metrics: Metrics from H2 analysis
            protocol_health: Protocol health from Sentinel

        Returns:
            TradingRiskAssessment with combined analysis
        """
        # HFT assessment
        latency = hft_metrics.get('latency', {})
        p99 = latency.get('p99_cycles', 0)
        anomalies = hft_metrics.get('anomalies', {}).get('count', 0)

        latency_ok = p99 <= self.latency_threshold_cycles
        anomalies_ok = anomalies <= self.anomaly_threshold

        if latency_ok and anomalies_ok:
            hft_health = 'healthy'
        elif latency_ok or anomalies_ok:
            hft_health = 'degraded'
        else:
            hft_health = 'critical'

        # Protocol assessment
        if protocol_health:
            protocol_tier = protocol_health.health_tier
            runway = protocol_health.runway_months
            gov_risk = (
                protocol_health.active_proposals > 0 or
                protocol_health.governance_participation < 0.1
            )
        else:
            protocol_tier = 'unknown'
            runway = 0
            gov_risk = False

        # Combined assessment
        combined_risk, recommendation = self._compute_combined(
            hft_health=hft_health,
            protocol_tier=protocol_tier,
            runway=runway,
            gov_risk=gov_risk,
        )

        return TradingRiskAssessment(
            hft_health=hft_health,
            latency_acceptable=latency_ok,
            risk_controls_active=True,  # Assume if we got here, controls are active
            anomalies_detected=anomalies,
            protocol_health=protocol_tier,
            protocol_runway_months=runway,
            governance_risk=gov_risk,
            combined_risk=combined_risk,
            recommendation=recommendation,
        )

    def _compute_combined(
        self,
        hft_health: str,
        protocol_tier: str,
        runway: float,
        gov_risk: bool,
    ) -> tuple:
        """Compute combined risk level and recommendation."""

        # Risk matrix
        hft_score = {'healthy': 0, 'degraded': 1, 'critical': 2}.get(hft_health, 2)
        protocol_score = {
            'A': 0, 'B': 0, 'C': 1, 'D': 2, 'F': 3, 'unknown': 1
        }.get(protocol_tier, 2)

        # Adjust for runway
        if 0 < runway < self.min_runway_months:
            protocol_score += 1

        # Adjust for governance risk
        if gov_risk:
            protocol_score += 0.5

        combined_score = hft_score + protocol_score

        # Determine risk level
        if combined_score <= 1:
            risk = 'low'
            rec = "System healthy. Continue normal operations."
        elif combined_score <= 2.5:
            risk = 'medium'
            rec = "Monitor closely. Review anomalies and protocol governance."
        elif combined_score <= 4:
            risk = 'high'
            rec = "Reduce exposure. Consider tightening risk limits."
        else:
            risk = 'critical'
            rec = "Immediate action required. Consider halting trading."

        return risk, rec
