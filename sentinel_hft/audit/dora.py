"""DORA-aligned export of an audit log.

The EU Digital Operational Resilience Act (DORA, Regulation (EU)
2022/2554) requires in-scope firms to produce, on request, an
auditable record of ICT-related operational events. For a prop desk
running an FPGA risk gate the meaningful population of such events is
the set of risk-gate decisions -- especially the kill-switch trips
and hard-rejects that prevented an order going to market.

This module emits a JSON bundle that is *shaped* to fit the kind of
evidence a compliance team would hand to a regulator under Articles
17-23 (ICT-related incident management, reporting, and testing).
This is deliberately **not** a claim that the format is a substitute
for an official ICT risk management policy -- it is a machine-
verifiable attachment that back-references the audit chain.

Contents of a DORA bundle
-------------------------

* ``metadata``
  - ``generated_at``        -- ISO-8601 UTC timestamp
  - ``schema_version``      -- "dora-bundle/1"
  - ``producer``            -- "sentinel-hft"
  - ``subject``             -- operator-supplied entity identifier (LEI,
                                firm ID, or free-form)
  - ``environment``         -- operator-supplied ("prod", "uat", etc.)

* ``audit_chain``
  - ``record_count``        -- number of records in the bundle
  - ``head_hash_lo_hex``    -- commitment to the full stream (low 128
                                bits of BLAKE2b over the last record)
  - ``seed_hex``            -- initial seed (16 zero bytes by default)
  - ``verification``        -- result of running ``verifier.verify``

* ``kill_switch_events``   -- every record where kill_triggered=True
* ``hard_rejections``      -- every record where ``passed=False`` but
                              not a rate-limit (rate limits are noisy)
* ``summary``
  - counts of passed / rejected / kill
  - unique symbols seen
  - time span (min -> max timestamp)

Everything else (the full record list) is embedded under ``records``
encoded as hex strings so a regulator can replay the chain without
needing our binary parser.
"""

from __future__ import annotations

import base64
import datetime as _dt
import json
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

from .record import AuditRecord, RejectReason, FLAG_KILL_TRIGGERED
from .verifier import VerificationResult, verify


SCHEMA_VERSION = "dora-bundle/1"
PRODUCER = "sentinel-hft"


def _iso_utc(ts_ns: int) -> str:
    """Format a ns-resolution wall-clock timestamp as ISO-8601 UTC."""
    secs = ts_ns // 1_000_000_000
    nanos = ts_ns % 1_000_000_000
    dt = _dt.datetime.fromtimestamp(secs, tz=_dt.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{nanos:09d}Z"


def _record_to_public(rec: AuditRecord) -> dict:
    """Emit the subset of record fields a regulator needs to see.

    We include the raw encoded bytes (hex) so the chain can be re-
    verified by re-hashing without needing our Python dataclass. We
    also include human-friendly fields for quick scanning.
    """
    return {
        "seq_no": rec.seq_no,
        "timestamp_ns": rec.timestamp_ns,
        "timestamp_iso": _iso_utc(rec.timestamp_ns),
        "order_id": rec.order_id,
        "symbol_id": rec.symbol_id,
        "passed": rec.passed,
        "reject_reason": rec.reason_name,
        "kill_triggered": rec.kill_triggered,
        "quantity": rec.quantity,
        "price": rec.price,
        "notional": rec.notional,
        "position_after": rec.position_after,
        "notional_after": rec.notional_after,
        "tokens_remaining": rec.tokens_remaining,
        "prev_hash_lo_hex": rec.prev_hash_lo.hex(),
        "self_hash_hex": rec.full_hash().hex(),
        "record_bytes_hex": rec.encode().hex(),
    }


def build_bundle(records: List[AuditRecord], *,
                 subject: str = "unspecified",
                 environment: str = "unspecified",
                 verification: Optional[VerificationResult] = None
                 ) -> dict:
    """Produce a DORA bundle dict ready to serialise to JSON."""
    if verification is None:
        verification = verify(records)

    # Filter highlights.
    kill_events = [_record_to_public(r) for r in records if r.kill_triggered]
    hard_rejects = [
        _record_to_public(r) for r in records
        if (not r.passed and r.reject_reason not in (
            int(RejectReason.OK), int(RejectReason.RATE_LIMITED),
        ))
    ]

    symbols = sorted({r.symbol_id for r in records})
    if records:
        ts_min = min(r.timestamp_ns for r in records)
        ts_max = max(r.timestamp_ns for r in records)
    else:
        ts_min = ts_max = 0

    passed = sum(1 for r in records if r.passed)
    rejected = sum(1 for r in records if not r.passed)
    kill_count = sum(1 for r in records if r.kill_triggered)

    head_hash_lo = verification.head_hash_lo or b""

    generated_at = _dt.datetime.now(tz=_dt.timezone.utc).isoformat()

    bundle = {
        "metadata": {
            "generated_at": generated_at,
            "schema_version": SCHEMA_VERSION,
            "producer": PRODUCER,
            "subject": subject,
            "environment": environment,
        },
        "audit_chain": {
            "record_count": len(records),
            "seed_hex": "00" * 16,
            "head_hash_lo_hex": head_hash_lo.hex(),
            "verification": verification.to_dict(),
        },
        "summary": {
            "passed": passed,
            "rejected": rejected,
            "kill_switch_events": kill_count,
            "unique_symbols": len(symbols),
            "time_span": {
                "min_iso": _iso_utc(ts_min) if records else None,
                "max_iso": _iso_utc(ts_max) if records else None,
            },
        },
        "kill_switch_events": kill_events,
        "hard_rejections": hard_rejects,
        "records": [_record_to_public(r) for r in records],
    }
    return bundle


def dump_bundle(records: Iterable[AuditRecord], path,
                *, subject: str = "unspecified",
                environment: str = "unspecified") -> str:
    """Build and write a DORA bundle to ``path`` as JSON. Returns the
    head hash hex for operator logging.
    """
    from pathlib import Path

    records_list = list(records)
    verification = verify(records_list)
    bundle = build_bundle(
        records_list, subject=subject, environment=environment,
        verification=verification,
    )

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(bundle, indent=2, sort_keys=False))
    return bundle["audit_chain"]["head_hash_lo_hex"]


__all__ = [
    "SCHEMA_VERSION",
    "PRODUCER",
    "build_bundle",
    "dump_bundle",
]
