"""
Operational-resilience log formatter (Swiss FINMA + Singapore MAS).

Same shape on both sides of the globe: an immutable daily JSON
envelope containing incidents, recovery-time / recovery-point
objectives, a head-hash reference to the audit chain and a jurisdiction
tag.  The UI dashboard and the ``docs/COMPLIANCE.md`` crosswalk both
consume this shape.

Flip ``jurisdiction='CH'`` for FINMA Circ. 2023/1 §49-58 and
``jurisdiction='SG'`` for MAS Notice TRM §6.4.  Extra jurisdiction
tags are allowed; they propagate through the envelope.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional


@dataclass
class ResilienceIncident:
    """One recorded incident on the trading-day."""

    started_at: str           # ISO8601
    ended_at: Optional[str]   # ISO8601 (null while still open)
    severity: str             # "low" | "medium" | "high" | "critical"
    component: str            # "kill_switch" | "risk_gate" | ...
    description: str
    rto_seconds: Optional[float] = None   # recovery-time objective met?
    rpo_records: Optional[int] = None     # recovery-point objective met?

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass
class ResilienceLog:
    """Daily ops-resilience envelope formatter."""

    trading_date: str                       # "YYYY-MM-DD"
    jurisdiction: str = "CH"                # CH | SG | EU | US | ...
    subject: str = "sentinel-hft-hl"
    environment: str = "sim"

    #: SLA targets the deployment committed to (informational).
    rto_target_seconds: float = 30.0
    rpo_target_records: int = 1

    #: Last audit-chain head hash (lo 128) - anchors this log to the
    #: immutable trade audit stream.
    audit_head_hash_lo_hex: str = ""
    audit_record_count: int = 0

    _incidents: List[ResilienceIncident] = field(default_factory=list)

    # ---- recorders --------------------------------------------------

    def record_incident(self, inc: ResilienceIncident) -> None:
        self._incidents.append(inc)

    def record(
        self,
        *,
        severity: str,
        component: str,
        description: str,
        started_at: Optional[str] = None,
        ended_at: Optional[str] = None,
        rto_seconds: Optional[float] = None,
        rpo_records: Optional[int] = None,
    ) -> ResilienceIncident:
        inc = ResilienceIncident(
            started_at=started_at or datetime.now(timezone.utc).isoformat(),
            ended_at=ended_at,
            severity=severity,
            component=component,
            description=description,
            rto_seconds=rto_seconds,
            rpo_records=rpo_records,
        )
        self.record_incident(inc)
        return inc

    def bind_audit(self, head_hash_lo_hex: str, record_count: int) -> None:
        self.audit_head_hash_lo_hex = head_hash_lo_hex
        self.audit_record_count = record_count

    # ---- queries ----------------------------------------------------

    def incidents(self) -> List[ResilienceIncident]:
        return list(self._incidents)

    def count(self) -> int:
        return len(self._incidents)

    def worst_severity(self) -> str:
        rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        worst = 0
        worst_label = "ok"
        for inc in self._incidents:
            if rank.get(inc.severity, 0) > worst:
                worst = rank[inc.severity]
                worst_label = inc.severity
        return worst_label

    # ---- envelope ---------------------------------------------------

    def as_envelope(self) -> Dict[str, object]:
        """Return the immutable envelope dict (JSON-safe)."""
        generated_at = datetime.now(timezone.utc).isoformat()
        body: Dict[str, object] = {
            "trading_date": self.trading_date,
            "jurisdiction": self.jurisdiction,
            "subject": self.subject,
            "environment": self.environment,
            "generated_at": generated_at,
            "rto_target_seconds": self.rto_target_seconds,
            "rpo_target_records": self.rpo_target_records,
            "incidents": [i.as_dict() for i in self._incidents],
            "incident_count": len(self._incidents),
            "worst_severity": self.worst_severity(),
            "audit": {
                "head_hash_lo_hex": self.audit_head_hash_lo_hex,
                "record_count": self.audit_record_count,
            },
        }
        # Head-hash of the envelope itself makes it independently
        # tamper-evident at the file level; doesn't replace the audit
        # chain, but lets a regulator verify the envelope in isolation.
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
        body["envelope_hash_sha256"] = hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()
        return body

    def write(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        env = self.as_envelope()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(env, f, indent=2, sort_keys=True)

    def snapshot(self) -> Dict[str, object]:
        return {
            "jurisdiction": self.jurisdiction,
            "trading_date": self.trading_date,
            "incidents": self.count(),
            "worst_severity": self.worst_severity(),
            "audit_anchored": bool(self.audit_head_hash_lo_hex),
        }
