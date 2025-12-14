"""Protocol context package for Sentinel-HFT.

This package integrates protocol health analysis from Sentinel into
Sentinel-HFT reports, providing unified trading risk assessment.

Key components:
- ProtocolContextProvider: Fetches and caches protocol health data
- ProtocolHealth: Protocol health snapshot
- RiskCorrelator: Correlates HFT events with protocol events
- HealthIntegrator: Combines HFT and protocol health assessment
"""

from .context import (
    ProtocolHealth,
    GovernanceEvent,
    ProtocolContext,
    ProtocolContextProvider,
)

from .health import (
    TradingRiskAssessment,
    HealthIntegrator,
)

from .risk_correlation import (
    CorrelatedEvent,
    CorrelationResult,
    RiskCorrelator,
)

__all__ = [
    # Context
    'ProtocolHealth',
    'GovernanceEvent',
    'ProtocolContext',
    'ProtocolContextProvider',
    # Health
    'TradingRiskAssessment',
    'HealthIntegrator',
    # Correlation
    'CorrelatedEvent',
    'CorrelationResult',
    'RiskCorrelator',
]
