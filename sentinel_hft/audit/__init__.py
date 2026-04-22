"""Tamper-evident audit log for risk-gate decisions.

The audit package serves two demo-critical roles:

1. **Local reference**. A Python ``AuditLogger`` hash-chains every
   risk decision the gate produces. In simulation it stands in for
   the DPI sink of ``rtl/risk_audit_log.sv``; in software-only mode
   it is the record of truth.

2. **DORA-aligned evidence**. The ``dora`` module turns a verified
   chain into a JSON bundle shaped to match the kind of evidence a
   regulator would request under EU DORA Articles 17-23 (ICT
   incident management and reporting). It is not a legal substitute
   for a firm's ICT policy, but a machine-verifiable attachment.

Everything is offline and dependency-free. There is no phone-home,
no cloud sink, no third-party audit service.
"""

from .record import (
    AUDIT_RECORD_SIZE,
    AUDIT_MAGIC,
    AUDIT_STRUCT,
    AuditRecord,
    RejectReason,
    FLAG_PASSED,
    FLAG_KILL_TRIGGERED,
    FLAG_RATE_HIT,
    FLAG_POS_HIT,
    FLAG_TOXIC_FLOW,
    write_records,
    read_records,
)
from .logger import AuditLogger, RiskDecision, SEED_PREV_HASH
from .verifier import verify, VerificationResult, ChainBreak, BreakKind
from .dora import build_bundle, dump_bundle, SCHEMA_VERSION

__all__ = [
    # record
    "AUDIT_RECORD_SIZE",
    "AUDIT_MAGIC",
    "AUDIT_STRUCT",
    "AuditRecord",
    "RejectReason",
    "FLAG_PASSED",
    "FLAG_KILL_TRIGGERED",
    "FLAG_RATE_HIT",
    "FLAG_POS_HIT",
    "FLAG_TOXIC_FLOW",
    "write_records",
    "read_records",
    # logger
    "AuditLogger",
    "RiskDecision",
    "SEED_PREV_HASH",
    # verifier
    "verify",
    "VerificationResult",
    "ChainBreak",
    "BreakKind",
    # dora
    "build_bundle",
    "dump_bundle",
    "SCHEMA_VERSION",
]
