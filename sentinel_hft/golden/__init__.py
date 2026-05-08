"""
sentinel_hft.golden
-------------------

Behavioral golden models for the Sentinel-HFT risk gate. These are the
single source of truth for V-Floor (RTL must match the golden on a
randomized corpus) and for the metamorphic relation suite (V-Meta).

Do NOT optimize this code for speed. Optimize for clarity. The RTL is
the fast path; the golden exists to be obviously correct.
"""

from .risk_gate import (
    GoldenRiskGate,
    GateConfig,
    Order,
    OrderSide,
    OrderType,
    Decision,
    RejectReason,
    Fill,
    evaluate_stream,
)

__all__ = [
    "GoldenRiskGate",
    "GateConfig",
    "Order",
    "OrderSide",
    "OrderType",
    "Decision",
    "RejectReason",
    "Fill",
    "evaluate_stream",
]
