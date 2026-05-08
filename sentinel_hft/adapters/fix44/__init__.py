"""
FIX 4.4 wire-protocol adapter.

Phase-2 deliverable. See `roadmap/pre_reg/phase_02.yml` for scope and
ship criteria.

Public API:

    from sentinel_hft.adapters.fix44 import (
        FixMessage,
        FixParseError,
        parse,
        emit,
        FixSession,
        SessionState,
        SentinelGateAdapter,
    )

    sess = FixSession(sender="SENDER", target="TARGET")
    adapter = SentinelGateAdapter(sess, gate)
    for msg in adapter.feed(raw_bytes):
        ...   # outbound messages from adapter (heartbeats, exec reports)
"""

from .messages import FixMessage, FixParseError, parse, emit
from .session import FixSession, SessionState
from .gate_adapter import SentinelGateAdapter

__all__ = [
    "FixMessage",
    "FixParseError",
    "parse",
    "emit",
    "FixSession",
    "SessionState",
    "SentinelGateAdapter",
]
