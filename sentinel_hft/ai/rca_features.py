"""Feature pipeline for the nightly RCA agent (Workstream 4).

Reads a day's drill artifacts (JSON reports + DORA bundles + audit
chains) and produces a canonical feature dict that the LLM prompt
template consumes. The feature dict is *deterministic* for a given
set of inputs so nightly digests are reproducible.

Feature schema (top level keys):

* ``window``        -- ISO date range covered.
* ``drills``        -- list of per-drill feature blocks.
* ``aggregate``     -- day-level rollups (p99 latency, total rejects,
                       chain-integrity, compliance alerts).
* ``anomalies``     -- list of detector hits, each a dict of
                       ``{kind, drill, stage, value, baseline, z}``.
* ``provenance``    -- file paths, hashes, and size metadata so the
                       digest can cite its source artifacts.

Per-drill feature block:

* Throughput        -- ticks, intents, decisions, passed, rejected.
* Reject histogram  -- reason → count (rate, position, notional,
                       kill, toxic, order_size, ...).
* Latency           -- per-stage p50/p99/mean_ns.
* Audit chain       -- record_count, chain_ok, head_hash_lo_hex.
* Compliance        -- OTR, self-trade, fat-finger, CAT, MAR rollups
                       (when the drill exposed them).

The pipeline is pure-Python stdlib; no numpy / pandas -- the nightly
job runs on a minimal container.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


FEATURE_SCHEMA_VERSION = "sentinel-hft/rca-features/1"


# ---------------------------------------------------------------------
# Deterministic detector thresholds. The LLM reads the anomaly list
# and explains *candidate* root causes; it does not set thresholds.
# ---------------------------------------------------------------------

# p99 stage latency that triggers an anomaly (nanoseconds). 10 µs is
# a generous bar for the software-simulation pipeline. Real FPGA
# numbers are ~1 µs; this gets tightened when traces come from
# hardware.
P99_STAGE_NS_WARN = 10_000

# Reject rate above which a drill triggers a "reject spike" anomaly.
REJECT_RATE_WARN = 0.25

# Toxic flow fraction of rejects above which we flag adverse
# selection as a candidate root cause.
TOXIC_FRACTION_WARN = 0.40

# Compliance thresholds.
MIFID_OTR_WOULD_TRIP_KEY = "would_trip"
FAT_FINGER_WORST_BPS_WARN = 150
MAR_ALERTS_WARN = 1

# ---------------------------------------------------------------------
# Phase 7 alpha-attribution thresholds. The attribution pipeline is
# observational: it never reshapes decisions, only explains what
# happened and cites the trace records that back each claim. All
# thresholds below are surfaced on the RCA UI so the trading desk
# can tune them per-asset-class without touching code.
# ---------------------------------------------------------------------

# Pass-rate floor below which fill-quality is flagged as
# "latency-dominated" -- the intents that did get through are a small
# fraction of what the strategy wanted to do.
PASS_RATE_FLOOR = 0.70

# Kill-drill survival: fraction of post-kill intents that MUST land on
# KILL_SWITCH. Anything less is a real-world blast-radius leak.
KILL_SURVIVAL_FLOOR = 1.0

# Reject-survival: if the risk gate is catching <5% of intents it is
# either over-calibrated or the flow is unusually clean. Either way
# the operator should look.
REJECT_SURVIVAL_FLOOR = 0.05


# ---------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------


@dataclass
class Anomaly:
    """One detector hit surfaced to the LLM."""

    kind: str        # e.g. "stage_latency_p99", "toxic_dominant"
    drill: str       # toxic_flow / kill_drill / latency / daily_evidence
    stage: Optional[str] = None  # ingress/core/risk/egress when relevant
    value: Optional[float] = None
    baseline: Optional[float] = None
    z: Optional[float] = None
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None or k == "detail"}


@dataclass
class DrillFeatures:
    """Per-drill feature block."""

    drill: str
    schema: str
    throughput: Dict[str, int]
    reject_histogram: Dict[str, int]
    latency_ns: Dict[str, Optional[float]]
    stage_latency_p99_ns: Dict[str, Optional[float]]
    audit: Dict[str, Any]
    compliance: Dict[str, Any]
    raw_path: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AttributionRecord:
    """One alpha-attribution claim.

    Every claim names a metric, gives the numeric value + its baseline,
    and lists the exact trace records / fields / seq-no ranges that
    back the claim. The UI renders the ``cited_records`` list
    verbatim; this is how a compliance engineer or FPGA designer can
    chase a claim back to the raw artifact without trusting the LLM.
    """

    kind: str                  # "fill_quality_vs_latency" | ...
    drill: str                 # toxic_flow / kill_drill / latency / aggregate
    metric: str                # human-readable metric name
    value: Optional[float] = None
    baseline: Optional[float] = None
    passes: Optional[bool] = None
    headline: str = ""         # one-line summary for the UI panel
    detail: str = ""           # multi-line explanation
    cited_records: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items()
                if v is not None or k in ("detail", "headline", "cited_records")}


@dataclass
class RcaFeatures:
    """Top-level feature bundle for a day."""

    schema: str = FEATURE_SCHEMA_VERSION
    window_start: str = ""
    window_end: str = ""
    drills: List[DrillFeatures] = field(default_factory=list)
    aggregate: Dict[str, Any] = field(default_factory=dict)
    anomalies: List[Anomaly] = field(default_factory=list)
    attribution: List[AttributionRecord] = field(default_factory=list)
    provenance: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "window": {"start": self.window_start, "end": self.window_end},
            "drills": [d.to_dict() for d in self.drills],
            "aggregate": self.aggregate,
            "anomalies": [a.to_dict() for a in self.anomalies],
            "attribution": [a.to_dict() for a in self.attribution],
            "provenance": self.provenance,
        }


# ---------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_get(d: Optional[Dict[str, Any]], *keys: str, default: Any = None) -> Any:
    """Nested dict get, tolerating missing intermediate keys."""
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def _extract_drill_kind(report: Dict[str, Any], path: Path) -> str:
    schema = str(report.get("schema", ""))
    if "toxic-flow" in schema:
        return "toxic_flow"
    if "kill-drill" in schema or "kill-switch" in schema:
        return "kill_drill"
    if "latency" in schema:
        return "latency"
    if "daily-evidence" in schema or "daily" in schema:
        return "daily_evidence"
    # Fall back to directory name.
    name = path.parent.name.lower()
    if name in {"toxic_flow", "kill_drill", "latency", "daily_evidence"}:
        return name
    return "unknown"


def _reject_histogram(report: Dict[str, Any]) -> Dict[str, int]:
    """Flat reject histogram: reason -> count, across the fields the
    demo reports emit. Canonical keys mirror ``RejectReason.name``."""
    tp = report.get("throughput", {}) or {}
    hist: Dict[str, int] = {}
    mapping = {
        "rejected_toxic": "TOXIC_FLOW",
        "rejected_rate": "RATE_LIMITED",
        "rejected_pos": "POSITION_LIMIT",
        "rejected_notional": "NOTIONAL_LIMIT",
        "rejected_order_size": "ORDER_SIZE",
        "rejected_kill": "KILL_SWITCH",
    }
    for src, dst in mapping.items():
        v = int(tp.get(src, 0) or 0)
        if v:
            hist[dst] = v
    # ``rejected`` (total) is not added as a bucket; we keep buckets
    # mutually exclusive.
    return hist


def _latency_block(report: Dict[str, Any]) -> Dict[str, Optional[float]]:
    lat = report.get("latency_ns", {}) or {}
    out = {}
    for k in ("p50", "p99", "p999", "max", "mean"):
        v = lat.get(k)
        out[k] = float(v) if v is not None else None
    return out


def _stage_p99_block(report: Dict[str, Any]) -> Dict[str, Optional[float]]:
    stages = report.get("stage_p99_ns", {}) or {}
    out = {}
    for s in ("ingress", "core", "risk", "egress"):
        v = stages.get(s)
        out[s] = float(v) if v is not None else None
    return out


def _audit_block(report: Dict[str, Any]) -> Dict[str, Any]:
    aud = report.get("audit", {}) or {}
    return {
        "chain_ok": bool(aud.get("chain_ok", True)),
        "head_hash_lo_hex": str(aud.get("head_hash_lo_hex", "")),
        "record_count": int(
            report.get("throughput", {}).get("decisions", 0)
            or report.get("throughput", {}).get("intents", 0)
            or 0
        ),
    }


def _compliance_block(report: Dict[str, Any]) -> Dict[str, Any]:
    """Pull the observational compliance counters if the drill surfaced
    them. Robust to legacy reports that predate Workstream 3."""
    comp = report.get("compliance")
    if not isinstance(comp, dict):
        return {}
    # Keep only the snapshot subsystems the UI knows about. This keeps
    # the LLM's input surface stable.
    subsystems = ("mifid_otr", "cftc_self_trade", "finra_fat_finger",
                  "sec_cat", "mar_abuse")
    return {k: comp[k] for k in subsystems if k in comp and comp[k]}


def _detect_anomalies_from_drill(d: DrillFeatures) -> List[Anomaly]:
    out: List[Anomaly] = []

    # Stage p99 latency
    for stage, v in d.stage_latency_p99_ns.items():
        if v is not None and v > P99_STAGE_NS_WARN:
            out.append(Anomaly(
                kind="stage_latency_p99",
                drill=d.drill,
                stage=stage,
                value=v,
                baseline=float(P99_STAGE_NS_WARN),
                z=(v - P99_STAGE_NS_WARN) / max(1.0, P99_STAGE_NS_WARN),
                detail=f"{stage} p99={v:.0f}ns above {P99_STAGE_NS_WARN}ns threshold",
            ))

    # Reject rate
    tp = d.throughput
    intents = int(tp.get("intents", tp.get("decisions", 0)) or 0)
    rejected = int(tp.get("rejected", 0) or 0)
    if intents >= 50:
        rate = rejected / intents
        if rate >= REJECT_RATE_WARN:
            out.append(Anomaly(
                kind="reject_rate_high",
                drill=d.drill,
                value=rate,
                baseline=REJECT_RATE_WARN,
                detail=f"{rejected}/{intents} intents rejected "
                       f"({rate:.1%} > {REJECT_RATE_WARN:.0%})",
            ))

    # Toxic dominance among rejects
    tox = int(d.reject_histogram.get("TOXIC_FLOW", 0))
    total_rej = sum(d.reject_histogram.values())
    if total_rej >= 10 and tox / total_rej >= TOXIC_FRACTION_WARN:
        out.append(Anomaly(
            kind="toxic_dominant",
            drill=d.drill,
            value=tox / total_rej,
            baseline=TOXIC_FRACTION_WARN,
            detail=f"{tox}/{total_rej} rejects are TOXIC_FLOW",
        ))

    # Audit chain integrity
    if not d.audit.get("chain_ok", True):
        out.append(Anomaly(
            kind="audit_chain_break",
            drill=d.drill,
            detail=f"audit chain broken on {d.drill}",
        ))

    # Compliance
    mifid = d.compliance.get("mifid_otr") or {}
    if mifid.get(MIFID_OTR_WOULD_TRIP_KEY):
        out.append(Anomaly(
            kind="mifid_otr_would_trip",
            drill=d.drill,
            value=float(mifid.get("global_ratio", 0.0) or 0.0),
            baseline=float(mifid.get("max_ratio_per_symbol", 0.0) or 0.0),
            detail="MiFID II RTS 6 OTR would trip under live enforcement",
        ))

    ff = d.compliance.get("finra_fat_finger") or {}
    worst_bps = float(ff.get("worst_deviation_bps", 0.0) or 0.0)
    if worst_bps > FAT_FINGER_WORST_BPS_WARN:
        out.append(Anomaly(
            kind="fat_finger_excursion",
            drill=d.drill,
            value=worst_bps,
            baseline=float(FAT_FINGER_WORST_BPS_WARN),
            detail=f"FINRA 15c3-5 worst-deviation {worst_bps:.0f}bps > "
                   f"{FAT_FINGER_WORST_BPS_WARN}bps guard",
        ))

    mar = d.compliance.get("mar_abuse") or {}
    mar_alerts = int(mar.get("alerts", 0) or 0)
    if mar_alerts >= MAR_ALERTS_WARN:
        out.append(Anomaly(
            kind="mar_spoofing_alerts",
            drill=d.drill,
            value=float(mar_alerts),
            baseline=float(MAR_ALERTS_WARN),
            detail=f"MAR Art. 12 spoofing detector fired {mar_alerts}x",
        ))

    return out


# ---------------------------------------------------------------------
# Phase 7 alpha-attribution features. Three canonical attribution
# lenses run against every drill feature set:
#
#   1. fill_quality_vs_latency -- did the pipeline actually land the
#      intents the strategy wanted to fill? Pass rate per drill,
#      correlated with the bottleneck stage's p99 latency. An
#      FPGA that is "fast" but drops 40% of intents on pre-gate
#      checks has no alpha; surface it.
#
#   2. reject_survival -- of the intents that got rejected, how many
#      would have hit a hard limit on the venue (toxic, notional,
#      position)? We count the rejects by reason and treat that as
#      the "blow-up averted" ledger. Zero rejects in a toxic-flow
#      drill is an anomaly, not a win.
#
#   3. kill_drill_survival -- once the kill switch tripped, every
#      subsequent decision must carry reason=KILL_SWITCH. One
#      mismatched record is a blast-radius leak worth escalating.
#      Cites kill_latency_ns and kill_intent_idx so the hardware
#      reviewer can locate the exact cycle in the trace.
#
# Each attribution record names the source file, field path, and
# where applicable the seq_no range that backs the claim, so the UI
# panel can render "Source: toxic_flow.json::reject_histogram" next
# to every number.
# ---------------------------------------------------------------------


def _attrib_fill_quality_vs_latency(d: DrillFeatures) -> AttributionRecord:
    """Attribution #1: pipeline pass rate vs worst stage p99.

    A pipeline that is fast (low p99) but drops 40% of the strategy's
    intents has no alpha -- it's a fast veto. Pairs the pass-rate
    with the bottleneck stage so the UI can call out which stage
    owns the latency budget.
    """
    tp = d.throughput
    intents = int(tp.get("intents", tp.get("decisions", 0)) or 0)
    passed = int(tp.get("passed", 0) or 0)
    rejected = int(tp.get("rejected", 0) or 0)

    if intents <= 0:
        return AttributionRecord(
            kind="fill_quality_vs_latency",
            drill=d.drill,
            metric="pass_rate",
            headline="no intents recorded -- attribution skipped",
            cited_records=[f"{Path(d.raw_path).name}::throughput"],
        )

    pass_rate = passed / intents if intents else 0.0

    # Bottleneck stage.
    worst_stage = None
    worst_p99: Optional[float] = None
    for stage, v in d.stage_latency_p99_ns.items():
        if v is None:
            continue
        if worst_p99 is None or v > worst_p99:
            worst_p99 = v
            worst_stage = stage
    p99 = d.latency_ns.get("p99")

    passes = pass_rate >= PASS_RATE_FLOOR
    headline = (
        f"{passed}/{intents} intents landed "
        f"({pass_rate:.1%}); bottleneck: "
        f"{worst_stage or 'n/a'} @ "
        f"{int(worst_p99) if worst_p99 else 0} ns p99"
    )
    detail = (
        "Fill-quality = passed / intents. Below "
        f"{PASS_RATE_FLOOR:.0%} the pipeline is a fast veto, not a fast "
        "executor. p99 in isolation does not imply alpha -- a sub-10µs "
        "pipeline that rejects 50% of the strategy's intents is leaking "
        "selection."
    )
    raw = Path(d.raw_path).name
    cited = [
        f"{raw}::throughput.intents={intents}",
        f"{raw}::throughput.passed={passed}",
        f"{raw}::throughput.rejected={rejected}",
    ]
    if p99 is not None:
        cited.append(f"{raw}::latency_ns.p99={int(p99)}")
    if worst_stage is not None and worst_p99 is not None:
        cited.append(
            f"{raw}::stage_p99_ns.{worst_stage}={int(worst_p99)}"
        )
    head = d.audit.get("head_hash_lo_hex")
    if head:
        cited.append(f"audit.aud::head_hash_lo={head[:16]}…")

    return AttributionRecord(
        kind="fill_quality_vs_latency",
        drill=d.drill,
        metric="pass_rate",
        value=pass_rate,
        baseline=PASS_RATE_FLOOR,
        passes=passes,
        headline=headline,
        detail=detail,
        cited_records=cited,
    )


def _attrib_reject_survival(d: DrillFeatures) -> AttributionRecord:
    """Attribution #2: rejects broken down by the harm they averted.

    TOXIC_FLOW      -- adverse selection avoided
    NOTIONAL_LIMIT  -- fat-finger / runaway order blocked
    POSITION_LIMIT  -- inventory guard held
    RATE_LIMITED    -- venue rate-limit breach pre-empted
    ORDER_SIZE      -- per-order quantity guard held
    KILL_SWITCH     -- reported separately in attribution #3

    The "survival rate" is rejects / intents -- the fraction of flow
    that the risk gate kept from reaching the venue. Low numbers in
    a toxic-flow drill are a calibration warning, not a celebration.
    """
    tp = d.throughput
    intents = int(tp.get("intents", tp.get("decisions", 0)) or 0)
    rejected = int(tp.get("rejected", 0) or 0)
    hist = dict(d.reject_histogram)

    raw = Path(d.raw_path).name
    if intents <= 0:
        return AttributionRecord(
            kind="reject_survival",
            drill=d.drill,
            metric="survival_rate",
            headline="no intents recorded -- attribution skipped",
            cited_records=[f"{raw}::throughput"],
        )

    survival_rate = rejected / intents

    # Which harm class dominates?
    if hist:
        dominant = max(hist, key=lambda k: hist[k])
        dominant_count = hist[dominant]
    else:
        dominant = None
        dominant_count = 0

    # For the toxic-flow drill specifically, the survival floor is the
    # *toxic share* of rejects, not overall rejects, since that's the
    # harm the drill is engineered to exercise.
    if d.drill == "toxic_flow":
        passes = hist.get("TOXIC_FLOW", 0) > 0
    else:
        passes = survival_rate >= REJECT_SURVIVAL_FLOOR

    parts = [f"{rejected}/{intents} intents blocked "
             f"({survival_rate:.1%})"]
    if dominant:
        parts.append(
            f"dominant reason: {dominant} ({dominant_count})"
        )
    headline = "; ".join(parts)

    detail_lines = [
        "Reject-survival ledger. Each rejected intent is an "
        "averted hit -- either adverse selection (TOXIC_FLOW), a "
        "bad-size guard (NOTIONAL_LIMIT / POSITION_LIMIT / "
        "ORDER_SIZE), a venue-rate guard (RATE_LIMITED), or the "
        "kill switch (attributed separately in #3).",
    ]
    for reason, count in sorted(hist.items(), key=lambda kv: -kv[1]):
        detail_lines.append(f"  {reason}: {count}")
    detail = "\n".join(detail_lines)

    cited = [
        f"{raw}::throughput.intents={intents}",
        f"{raw}::throughput.rejected={rejected}",
    ]
    for reason, count in hist.items():
        cited.append(f"{raw}::reject_histogram.{reason}={count}")
    head = d.audit.get("head_hash_lo_hex")
    if head:
        cited.append(f"audit.aud::head_hash_lo={head[:16]}…")

    return AttributionRecord(
        kind="reject_survival",
        drill=d.drill,
        metric="survival_rate",
        value=survival_rate,
        baseline=REJECT_SURVIVAL_FLOOR,
        passes=passes,
        headline=headline,
        detail=detail,
        cited_records=cited,
    )


def _attrib_kill_survival(d: DrillFeatures) -> Optional[AttributionRecord]:
    """Attribution #3: kill-drill blast-radius leak check.

    Only meaningful for drills that trip the kill switch. Reads the
    kill-drill-specific report fields (``kill_triggered``,
    ``decisions_before_kill``, ``decisions_after_kill``,
    ``rejects_after_kill_mismatch``, ``kill_latency_ns``,
    ``kill_intent_idx``) and turns them into an attribution claim
    with exact seq-no citations a hardware reviewer can hit.

    Reads the raw report (``raw_path``) directly because the
    kill-specific fields are not in the normalised DrillFeatures
    envelope.
    """
    if d.drill != "kill_drill":
        return None

    raw_path = Path(d.raw_path)
    try:
        with raw_path.open("r", encoding="utf-8") as f:
            report = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    if not bool(report.get("kill_triggered", False)):
        return AttributionRecord(
            kind="kill_drill_survival",
            drill=d.drill,
            metric="survival_rate",
            headline="kill switch did not trigger in this run",
            cited_records=[f"{raw_path.name}::kill_triggered=false"],
        )

    before = int(report.get("decisions_before_kill", 0) or 0)
    after = int(report.get("decisions_after_kill", 0) or 0)
    mismatch = int(report.get("rejects_after_kill_mismatch", 0) or 0)
    kill_latency_ns = int(report.get("kill_latency_ns", 0) or 0)
    kill_intent_idx = int(report.get("kill_intent_idx", -1))
    within_slo = bool(report.get("kill_latency_within_slo", False))

    if after > 0:
        survival_rate = 1.0 - (mismatch / after)
    else:
        survival_rate = 1.0

    passes = (mismatch == 0) and within_slo

    headline = (
        f"kill trip at intent #{kill_intent_idx} "
        f"({kill_latency_ns} ns); "
        f"{after - mismatch}/{after} post-kill intents caught "
        f"({survival_rate:.1%})"
    )
    detail = (
        "Kill-switch survival = (post_kill_rejects) / "
        "(decisions_after_kill). Any record with reason != "
        "KILL_SWITCH after the kill trip is a blast-radius leak and "
        "must be escalated to the hardware reviewer. "
        f"SLO check: kill_latency_within_slo = {within_slo}."
    )
    cited = [
        f"{raw_path.name}::kill_triggered=true",
        f"{raw_path.name}::kill_intent_idx={kill_intent_idx}",
        f"{raw_path.name}::kill_latency_ns={kill_latency_ns}",
        f"{raw_path.name}::kill_latency_within_slo={within_slo}",
        f"{raw_path.name}::decisions_before_kill={before}",
        f"{raw_path.name}::decisions_after_kill={after}",
        f"{raw_path.name}::rejects_after_kill_mismatch={mismatch}",
        (
            f"audit.aud::seq_no range post-kill "
            f"[{kill_intent_idx + 1},{kill_intent_idx + after}]"
        ),
    ]
    head = d.audit.get("head_hash_lo_hex")
    if head:
        cited.append(f"audit.aud::head_hash_lo={head[:16]}…")

    return AttributionRecord(
        kind="kill_drill_survival",
        drill=d.drill,
        metric="kill_survival_rate",
        value=survival_rate,
        baseline=KILL_SURVIVAL_FLOOR,
        passes=passes,
        headline=headline,
        detail=detail,
        cited_records=cited,
    )


def _build_attribution(drills: List[DrillFeatures]) -> List[AttributionRecord]:
    """Run the three attribution lenses across every drill."""
    out: List[AttributionRecord] = []
    for d in drills:
        out.append(_attrib_fill_quality_vs_latency(d))
        out.append(_attrib_reject_survival(d))
        kill = _attrib_kill_survival(d)
        if kill is not None:
            out.append(kill)
    return out


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------


def extract_drill_features(report_path: Path) -> DrillFeatures:
    """Extract the per-drill feature block from one report JSON."""
    report_path = Path(report_path)
    with report_path.open("r", encoding="utf-8") as f:
        report = json.load(f)

    kind = _extract_drill_kind(report, report_path)
    return DrillFeatures(
        drill=kind,
        schema=str(report.get("schema", "")),
        throughput=dict(report.get("throughput", {}) or {}),
        reject_histogram=_reject_histogram(report),
        latency_ns=_latency_block(report),
        stage_latency_p99_ns=_stage_p99_block(report),
        audit=_audit_block(report),
        compliance=_compliance_block(report),
        raw_path=str(report_path),
    )


def _aggregate(drills: List[DrillFeatures]) -> Dict[str, Any]:
    """Day-level rollups across all drills."""
    if not drills:
        return {"drills": 0}

    total_intents = sum(int(d.throughput.get("intents", 0) or 0) for d in drills)
    total_rejected = sum(int(d.throughput.get("rejected", 0) or 0) for d in drills)
    total_toxic = sum(int(d.reject_histogram.get("TOXIC_FLOW", 0)) for d in drills)
    total_kill = sum(int(d.reject_histogram.get("KILL_SWITCH", 0)) for d in drills)
    chain_ok = all(d.audit.get("chain_ok", True) for d in drills)

    # Worst p99 across stages.
    worst_stage = None
    worst_p99: Optional[float] = None
    for d in drills:
        for stage, v in d.stage_latency_p99_ns.items():
            if v is None:
                continue
            if worst_p99 is None or v > worst_p99:
                worst_p99 = v
                worst_stage = f"{d.drill}.{stage}"

    return {
        "drills": len(drills),
        "intents_total": total_intents,
        "rejected_total": total_rejected,
        "reject_rate": (total_rejected / total_intents) if total_intents else 0.0,
        "toxic_flow_rejects": total_toxic,
        "kill_switch_events": total_kill,
        "audit_chains_ok": chain_ok,
        "worst_stage_p99_ns": worst_p99,
        "worst_stage_label": worst_stage,
    }


def discover_drill_reports(root: Path) -> List[Path]:
    """Find canonical drill report JSON files under a root directory.

    Looks for ``<drill>.json`` siblings of ``audit.aud`` files. Falls
    back to any JSON matching the drill-schema prefix if the pairing
    heuristic misses.
    """
    root = Path(root)
    if not root.exists():
        return []
    found: List[Path] = []
    # Look for audit.aud + sibling *.json
    for aud in root.rglob("audit.aud"):
        parent = aud.parent
        for name in ("toxic_flow", "kill_drill", "latency", "daily_evidence"):
            cand = parent / f"{name}.json"
            if cand.exists():
                found.append(cand)
        # Fallback: any JSON in directory with drill schema.
        if not any(p.parent == parent for p in found):
            for jp in parent.glob("*.json"):
                try:
                    with jp.open("r", encoding="utf-8") as f:
                        head = f.read(256)
                    if "sentinel-hft/usecase/" in head:
                        found.append(jp)
                except OSError:
                    continue
    # Dedup while preserving order.
    seen = set()
    unique = []
    for p in found:
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return unique


def build_features(
    report_paths: Iterable[Path],
    window_start: Optional[str] = None,
    window_end: Optional[str] = None,
) -> RcaFeatures:
    """Build a full ``RcaFeatures`` bundle from a list of report JSONs."""
    today = date.today().isoformat()
    ws = window_start or today
    we = window_end or today

    drills: List[DrillFeatures] = []
    provenance: List[Dict[str, Any]] = []
    for p in report_paths:
        p = Path(p)
        try:
            d = extract_drill_features(p)
        except (OSError, json.JSONDecodeError) as e:
            provenance.append({
                "path": str(p),
                "status": "error",
                "error": str(e),
            })
            continue
        drills.append(d)
        provenance.append({
            "path": str(p),
            "status": "ok",
            "sha256": _sha256_of(p),
            "bytes": p.stat().st_size,
        })

    agg = _aggregate(drills)

    anomalies: List[Anomaly] = []
    for d in drills:
        anomalies.extend(_detect_anomalies_from_drill(d))

    attribution = _build_attribution(drills)

    return RcaFeatures(
        schema=FEATURE_SCHEMA_VERSION,
        window_start=ws,
        window_end=we,
        drills=drills,
        aggregate=agg,
        anomalies=anomalies,
        attribution=attribution,
        provenance=provenance,
    )


def build_features_from_root(root: Path, **kwargs: Any) -> RcaFeatures:
    """Convenience: discover + extract in one call."""
    return build_features(discover_drill_reports(root), **kwargs)


__all__ = [
    "FEATURE_SCHEMA_VERSION",
    "Anomaly",
    "AttributionRecord",
    "DrillFeatures",
    "RcaFeatures",
    "build_features",
    "build_features_from_root",
    "discover_drill_reports",
    "extract_drill_features",
]
