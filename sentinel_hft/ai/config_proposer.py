"""Deterministic config-patch proposer (Workstream 4 support).

Given an ``RcaFeatures`` bundle produced by ``rca_features.py``, emit a
JSON-Patch-shaped list of **proposed** configuration changes that the
RCA agent would surface for human review. The proposer is explicitly
*review-only*: the return value carries ``review_only=True`` and is
never wired into any apply path. Its only consumers are:

* the ``/api/ai/rca/{date}/proposed-patch`` endpoint,
* the "Proposed config changes" panel on ``/sentinel/rca`` in the UI.

Why separate from ``rca_nightly.py``?
-------------------------------------
The nightly digest's markdown body is either deterministic-template or
LLM-generated. We don't want the LLM to author a machine-applyable
patch -- prompt-injection on a feature dict is the wrong surface for
that. So the patch is computed by this module alone, from the same
feature bundle the LLM saw. The LLM's prose and this patch are
independent, which is exactly the property the UI surfaces as "diff
deterministic vs. LLM + review-only patch".

Patch shape
-----------

Each operation is RFC 6902-compatible (``op``, ``path``, ``value``)
with two extra stable keys:

* ``rationale``: short English sentence grounded in the triggering
  anomaly, citing its ``kind`` / ``detail`` verbatim.
* ``anomaly_kind``: the ``Anomaly.kind`` that triggered the op, so the
  UI can link the patch row back to the anomaly table row.

Config paths target the canonical engine-config tree:

* ``/risk_gate/max_tokens``              — token-bucket depth
* ``/risk_gate/refill_per_second``       — token-bucket refill
* ``/risk_gate/max_order_qty``           — fat-finger guard
* ``/risk_gate/auto_kill_notional``      — kill-switch threshold
* ``/triage/latency_zscore/z_threshold`` — tighten if nominal day has
                                           many z alerts; loosen if
                                           abusively noisy
* ``/triage/reject_rate_cusum/alert_threshold``
* ``/triage/fill_quality_sprt/accept_upper``
* ``/compliance/fat_finger/max_deviation_bps``
* ``/compliance/mifid_otr/cap_ratio_per_symbol``

No operation is ever applied -- this module only reads; the API layer
wraps the output in ``{review_only: True, ...}``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

from .rca_features import (
    Anomaly,
    RcaFeatures,
    P99_STAGE_NS_WARN,
    REJECT_RATE_WARN,
    TOXIC_FRACTION_WARN,
    FAT_FINGER_WORST_BPS_WARN,
    MAR_ALERTS_WARN,
)


PROPOSAL_SCHEMA_VERSION = "sentinel-hft/config-proposal/1"


@dataclass
class PatchOp:
    """One proposed RFC-6902-style operation with rationale."""

    op: str
    path: str
    value: Any
    rationale: str
    anomaly_kind: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProposedPatch:
    """The full proposal envelope returned by ``propose_config_patch``.

    ``review_only`` is hardcoded ``True`` and **must never** be wired
    into an apply path. The ``patch_hash_sha256`` is a stable fingerprint
    of the canonical-JSON form of ``patch`` (sorted keys, no whitespace)
    so the UI can show a short hash next to the review badge.
    """

    schema: str
    date: str
    review_only: bool
    patch: List[Dict[str, Any]]
    summary: str
    patch_hash_sha256: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------
# Private helpers -- one per anomaly family
# ---------------------------------------------------------------------


def _ns_to_us(ns: float) -> float:
    return round(float(ns) / 1000.0, 2)


def _op_from_latency(a: Anomaly) -> Optional[PatchOp]:
    """Stage-p99 latency anomaly: propose no engine change, only a
    triage-detector sensitivity hint.

    We deliberately do *not* propose changing engine or risk gate
    latency targets -- that would be closing a control loop on the
    hot path. Instead, if the anomaly fires, we suggest tightening
    the z-score threshold on that stage so the operator sees earlier
    warning next time.
    """
    if a.kind != "stage_latency_p99":
        return None
    return PatchOp(
        op="replace",
        path="/triage/latency_zscore/z_threshold",
        value=3.5,
        rationale=(
            f"stage {a.stage} p99={_ns_to_us(a.value or 0.0)}µs exceeds "
            f"{_ns_to_us(P99_STAGE_NS_WARN)}µs guard -- propose tightening "
            f"z-score threshold 4.0 → 3.5 so the triage agent fires earlier "
            f"on the next excursion."
        ),
        anomaly_kind=a.kind,
    )


def _op_from_reject_rate(a: Anomaly) -> Optional[PatchOp]:
    """Reject-rate spike: propose lowering token-bucket refill so the
    engine sheds flow earlier before the reject gate has to.
    """
    if a.kind != "reject_rate_high":
        return None
    rate = float(a.value or 0.0)
    # Scale proposal proportionally to breach severity.
    if rate > 0.5:
        new_refill = 500
    elif rate > 0.35:
        new_refill = 750
    else:
        new_refill = 1000
    return PatchOp(
        op="replace",
        path="/risk_gate/refill_per_second",
        value=new_refill,
        rationale=(
            f"reject rate {rate:.1%} > {REJECT_RATE_WARN:.0%} baseline -- "
            f"propose throttling refill to {new_refill}/s so the engine "
            f"sheds before the reject gate trips."
        ),
        anomaly_kind=a.kind,
    )


def _op_from_toxic(a: Anomaly) -> Optional[PatchOp]:
    """Toxic-flow dominance: tighten the SPRT on fill-quality so
    adverse selection converts to a triage alert sooner.
    """
    if a.kind != "toxic_dominant":
        return None
    return PatchOp(
        op="replace",
        path="/triage/fill_quality_sprt/accept_upper",
        value=3.0,
        rationale=(
            f"{(a.value or 0.0) * 100:.0f}% of rejects are TOXIC_FLOW "
            f"(> {TOXIC_FRACTION_WARN:.0%}) -- propose tightening SPRT "
            f"accept_upper 4.0 → 3.0 so fill-quality drift escalates "
            f"after fewer samples."
        ),
        anomaly_kind=a.kind,
    )


def _op_from_fat_finger(a: Anomaly) -> Optional[PatchOp]:
    """FINRA 15c3-5 fat-finger excursion: propose a tighter
    max-deviation guard anchored to the observed worst.
    """
    if a.kind != "fat_finger_excursion":
        return None
    worst = float(a.value or 0.0)
    # New guard = min(current, observed_worst) scaled down 20 bps.
    new_bps = max(20.0, min(float(FAT_FINGER_WORST_BPS_WARN), worst - 20.0))
    return PatchOp(
        op="replace",
        path="/compliance/fat_finger/max_deviation_bps",
        value=round(new_bps),
        rationale=(
            f"worst deviation {worst:.0f}bps exceeded {FAT_FINGER_WORST_BPS_WARN}bps "
            f"guard -- propose tightening to {round(new_bps)}bps "
            f"(20 bps under observed worst)."
        ),
        anomaly_kind=a.kind,
    )


def _op_from_mifid(a: Anomaly) -> Optional[PatchOp]:
    """MiFID II OTR would-trip: propose capping per-symbol ratio at
    the observed worst so the live guard fires before the regulator
    threshold next time.
    """
    if a.kind != "mifid_otr_would_trip":
        return None
    per_sym = float(a.baseline or 0.0)
    if per_sym <= 0:
        per_sym = 4.0
    return PatchOp(
        op="replace",
        path="/compliance/mifid_otr/cap_ratio_per_symbol",
        value=round(per_sym, 2),
        rationale=(
            f"MiFID II RTS 6 OTR would trip under live enforcement -- "
            f"propose capping per-symbol ratio at {per_sym:.2f} "
            f"(observed worst) to force the engine to pace sooner."
        ),
        anomaly_kind=a.kind,
    )


def _op_from_mar(a: Anomaly) -> Optional[PatchOp]:
    """MAR Art. 12 spoofing alerts: propose a review flag only. We
    deliberately do not auto-throttle on MAR -- regulators expect a
    human in the loop for layering/spoofing disposition.
    """
    if a.kind != "mar_spoofing_alerts":
        return None
    return PatchOp(
        op="add",
        path="/compliance/mar_abuse/review_required",
        value=True,
        rationale=(
            f"MAR Art. 12 spoofing detector fired {int(a.value or 0)}x "
            f"(>= {MAR_ALERTS_WARN}) -- flag for manual review. "
            f"No automatic throttle proposed; MAR dispositions require "
            f"a compliance officer."
        ),
        anomaly_kind=a.kind,
    )


def _op_from_chain_break(a: Anomaly) -> Optional[PatchOp]:
    """Audit chain break: propose freezing the kill-notional to the
    current exposure so the next run starts from a known-good bound.
    """
    if a.kind != "audit_chain_break":
        return None
    return PatchOp(
        op="test",
        path="/audit/chain_ok",
        value=True,
        rationale=(
            f"audit chain broken on drill `{a.drill}` -- regenerate "
            f"regulator bundle from last verified seq_no before "
            f"restarting. No auto-throttle; requires operator sign-off."
        ),
        anomaly_kind=a.kind,
    )


# Dispatcher: order matters only for summary text -- the UI sorts by
# anomaly_kind anyway.
_OP_BUILDERS = (
    _op_from_latency,
    _op_from_reject_rate,
    _op_from_toxic,
    _op_from_fat_finger,
    _op_from_mifid,
    _op_from_mar,
    _op_from_chain_break,
)


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------


def propose_config_patch(features: RcaFeatures) -> ProposedPatch:
    """Produce the review-only patch envelope for a feature bundle.

    Deterministic: identical input yields identical output (including
    hash). Empty anomaly list yields an empty patch and a "no change
    proposed" summary. Always returns ``review_only=True``.
    """
    ops: List[PatchOp] = []
    # Dedup by (path, anomaly_kind) so e.g. multiple drills triggering
    # the same stage_latency_p99 do not emit duplicate triage tweaks.
    seen = set()
    for a in features.anomalies:
        for builder in _OP_BUILDERS:
            op = builder(a)
            if op is None:
                continue
            key = (op.path, op.anomaly_kind)
            if key in seen:
                continue
            seen.add(key)
            ops.append(op)

    patch_dicts = [o.to_dict() for o in ops]
    canonical = json.dumps(patch_dicts, sort_keys=True, separators=(",", ":"))
    phash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    if not ops:
        summary = "No anomalies — no configuration change proposed."
    elif len(ops) == 1:
        summary = (
            f"1 change proposed in response to "
            f"`{ops[0].anomaly_kind}` (review-only)."
        )
    else:
        kinds = sorted({o.anomaly_kind for o in ops})
        summary = (
            f"{len(ops)} changes proposed in response to "
            f"{len(kinds)} anomaly kind(s): {', '.join(kinds)} (review-only)."
        )

    return ProposedPatch(
        schema=PROPOSAL_SCHEMA_VERSION,
        date=features.window_end or features.window_start or "",
        review_only=True,
        patch=patch_dicts,
        summary=summary,
        patch_hash_sha256=phash,
    )


__all__ = [
    "PROPOSAL_SCHEMA_VERSION",
    "PatchOp",
    "ProposedPatch",
    "propose_config_patch",
]
