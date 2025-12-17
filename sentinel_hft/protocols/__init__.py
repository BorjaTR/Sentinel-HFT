"""
Protocol awareness module for HFT-specific protocols.

Provides decoders and latency budgets for:
- FIX protocol (Financial Information eXchange)
- ITCH (NASDAQ market data)
- OUCH (NASDAQ order entry)
- SBE (Simple Binary Encoding)
- Custom binary protocols
"""

from .analyzer import (
    ProtocolType,
    ProtocolConfig,
    ProtocolAnalyzer,
    LatencyBudget,
    ProtocolMetrics,
)
from .fix import FIXDecoder
from .itch import ITCHDecoder

__all__ = [
    'ProtocolType',
    'ProtocolConfig',
    'ProtocolAnalyzer',
    'LatencyBudget',
    'ProtocolMetrics',
    'FIXDecoder',
    'ITCHDecoder',
]
