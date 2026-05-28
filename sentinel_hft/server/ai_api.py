"""ai_api.py -- FastAPI router for Workstream 4 (RCA digests) and
Workstream 5 (online triage alerts).

Mounted by ``sentinel_hft.server.app`` under ``/api`` so the routes
become:

    GET  /api/ai/rca/list
    GET  /api/ai/rca/{date}
    POST /api/ai/rca/run
    GET  /api/ai/triage/alerts
    POST /api/ai/triage/eval

The router is intentionally read-mostly. The only mutating endpoints
are ``rca/run`` (regenerates today's digest from on-disk artifacts)
and ``triage/eval`` (runs the evaluation harness with the default
scripted scenario). Neither closes a control loop into the engine.
"""

from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from sentinel_hft.ai.config_proposer import (
    PROPOSAL_SCHEMA_VERSION,
    propose_config_patch,
)
from sentinel_hft.ai.rca_features import (
    RcaFeatures,
    Anomaly,
    AttributionRecord,
    DrillFeatures,
)
from sentinel_hft.ai.rca_nightly import (
    DIGEST_SCHEMA_VERSION,
    NIGHTLY_PROMPT,
    list_digests,
    load_digest,
    run_nightly,
    _format_prompt,
    _prompt_hash,
    _template_digest,
)
from sentinel_hft.ai.triage_eval import run_evaluation
from sentinel_hft.audit.alert_log import (
    read_alerts,
    verify_chain,
)


# ---------------------------------------------------------------------
# Defaults (overridable by env -- keeps the router stateless)
# ---------------------------------------------------------------------


def _default_artifacts_root() -> Path:
    return Path(os.environ.get("SENTINEL_ARTIFACTS", "out/hl"))


def _default_digest_dir() -> Path:
    return Path(os.environ.get("SENTINEL_DIGEST_DIR", "out/digests"))


def _default_alert_log() -> Path:
    return Path(os.environ.get("SENTINEL_ALERT_LOG", "out/triage/alerts.alog"))


# ---------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------


class DigestSummary(BaseModel):
    # ``schema`` would shadow ``BaseModel.schema`` in pydantic v2, so we
    # alias and serialize the wire-name explicitly. ``populate_by_name``
    # lets list_digests() pass ``schema=`` straight through.
    model_config = ConfigDict(populate_by_name=True)

    date: str
    backend: str
    anomaly_count: int = 0
    prompt_sha256: Optional[str] = None
    digest_schema: Optional[str] = Field(default=None, alias="schema")
    model: Optional[str] = None


class DigestDetail(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    digest_schema: str = Field(alias="schema")
    date: str
    markdown: str
    backend: str
    model: Optional[str] = None
    prompt_sha256: str
    generated_at: str
    features: Dict[str, Any]


class RunDigestRequest(BaseModel):
    artifacts_root: Optional[str] = Field(
        default=None,
        description="Path to the drill artifacts root (defaults to "
                    "SENTINEL_ARTIFACTS or 'out/hl')",
    )
    digest_dir: Optional[str] = Field(
        default=None,
        description="Path where the digest archive is written (defaults to "
                    "SENTINEL_DIGEST_DIR or 'out/digests')",
    )
    date: Optional[str] = Field(
        default=None,
        description="ISO date for the digest. Defaults to today (UTC).",
    )
    backend: str = Field(
        default="template",
        description="LLM backend: 'auto', 'anthropic', or 'template'.",
    )
    model: Optional[str] = None


class RunDigestResponse(BaseModel):
    date: str
    backend: str
    markdown_path: str
    json_path: str
    anomaly_count: int


class RcaPromptView(BaseModel):
    """Exact prompt that was (or would have been) sent to the backend.

    Reconstructed from the stored ``features`` dict, so the bytes are
    byte-identical to what ``rca_nightly.generate_digest`` passed in.
    """

    date: str
    backend: str
    model: Optional[str] = None
    prompt_template: str = NIGHTLY_PROMPT
    prompt: str
    prompt_sha256: str
    prompt_sha256_matches_stored: bool


class ConfigPatchOp(BaseModel):
    op: str
    path: str
    value: Any
    rationale: str
    anomaly_kind: str


class ProposedPatchView(BaseModel):
    """Review-only JSON patch proposed from the day's anomalies."""

    schema_version: str = Field(alias="schema")
    date: str
    review_only: bool
    patch: List[ConfigPatchOp]
    summary: str
    patch_hash_sha256: str

    model_config = ConfigDict(populate_by_name=True)


class RcaCompareView(BaseModel):
    """Side-by-side deterministic-vs-live digest for a single date.

    ``live_markdown`` is whatever the archive contains (template OR
    anthropic). ``deterministic_markdown`` is the template digest
    regenerated from the same stored features -- so identical bytes
    mean the live run was also deterministic and diffs mean the LLM
    added prose of its own.
    """

    date: str
    backend: str
    model: Optional[str] = None
    live_markdown: str
    deterministic_markdown: str
    identical: bool
    anomaly_count: int
    prompt_sha256: str


class AttributionRecordView(BaseModel):
    """One row from ``RcaFeatures.attribution``.

    The UI renders ``headline`` as the card title, ``detail`` as the
    expanded explanation, and ``cited_records`` verbatim as a list of
    source citations (file + field path + seq-no range). ``passes`` is
    the green/red traffic light; null means "not applicable".
    """

    kind: str
    drill: str
    metric: str
    value: Optional[float] = None
    baseline: Optional[float] = None
    passes: Optional[bool] = None
    headline: str = ""
    detail: str = ""
    cited_records: List[str] = Field(default_factory=list)


class AttributionView(BaseModel):
    """Response of ``GET /api/ai/rca/{date}/attribution``."""

    date: str
    backend: str
    records: List[AttributionRecordView]
    pass_count: int
    fail_count: int


class AlertSummary(BaseModel):
    seq_no: int
    timestamp_ns: int
    severity: str
    detector: str
    stage: Optional[str]
    detail: str
    score: float
    window_n: int
    full_hash_lo: str


class AlertChainView(BaseModel):
    chain_ok: bool
    n_records: int
    head_hash_lo: str
    bad_index: Optional[int] = None
    bad_reason: Optional[str] = None
    alerts: List[AlertSummary]


class TriageEvalResponse(BaseModel):
    events: int
    labelled_anomalies: int
    alerts_fired: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    anomaly_windows: List[Dict[str, Any]]
    alerts: List[Dict[str, Any]]


# ---------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------


router = APIRouter(prefix="/api/ai", tags=["ai"])


# ---- RCA -------------------------------------------------------------


@router.get(
    "/rca/list",
    response_model=List[DigestSummary],
    response_model_by_alias=True,
)
def rca_list(
    digest_dir: Optional[str] = Query(
        None, description="Override digest directory."
    ),
) -> List[DigestSummary]:
    """List archived nightly digests, newest first."""
    dd = Path(digest_dir) if digest_dir else _default_digest_dir()
    if not dd.exists():
        return []
    return [DigestSummary(**row) for row in list_digests(dd)]


@router.get(
    "/rca/{iso_date}",
    response_model=DigestDetail,
    response_model_by_alias=True,
)
def rca_get(
    iso_date: str,
    digest_dir: Optional[str] = Query(None),
) -> DigestDetail:
    """Load one archived digest by ISO date."""
    dd = Path(digest_dir) if digest_dir else _default_digest_dir()
    payload = load_digest(dd, iso_date)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"no digest for {iso_date}")
    # `load_digest` returns the persisted JSON shape, which already
    # matches DigestDetail. Be defensive about missing keys.
    return DigestDetail(
        digest_schema=payload.get("schema", DIGEST_SCHEMA_VERSION),
        date=payload.get("date", iso_date),
        markdown=payload.get("markdown", ""),
        backend=payload.get("backend", "template"),
        model=payload.get("model"),
        prompt_sha256=payload.get("prompt_sha256", ""),
        generated_at=payload.get("generated_at", ""),
        features=payload.get("features", {}),
    )


def _rehydrate_features(feats: Dict[str, Any]) -> RcaFeatures:
    """Turn a persisted ``RcaFeatures.to_dict()`` back into the dataclass.

    The JSON on disk uses ``{"window": {"start": ..., "end": ...}}`` but
    the dataclass fields are ``window_start`` / ``window_end`` -- flatten
    here. Drill and anomaly rows are the canonical asdict shape and
    unpack cleanly.
    """
    window = feats.get("window") or {}
    drills_raw = feats.get("drills") or []
    anomalies_raw = feats.get("anomalies") or []
    drills: List[DrillFeatures] = []
    for d in drills_raw:
        try:
            drills.append(DrillFeatures(
                drill=str(d.get("drill", "unknown")),
                schema=str(d.get("schema", "")),
                throughput=dict(d.get("throughput") or {}),
                reject_histogram=dict(d.get("reject_histogram") or {}),
                latency_ns=dict(d.get("latency_ns") or {}),
                stage_latency_p99_ns=dict(d.get("stage_latency_p99_ns") or {}),
                audit=dict(d.get("audit") or {}),
                compliance=dict(d.get("compliance") or {}),
                raw_path=str(d.get("raw_path", "")),
            ))
        except (TypeError, ValueError):
            continue
    anomalies: List[Anomaly] = []
    for a in anomalies_raw:
        try:
            anomalies.append(Anomaly(
                kind=str(a.get("kind", "")),
                drill=str(a.get("drill", "")),
                stage=a.get("stage"),
                value=a.get("value"),
                baseline=a.get("baseline"),
                z=a.get("z"),
                detail=str(a.get("detail", "")),
            ))
        except (TypeError, ValueError):
            continue
    attribution: List[AttributionRecord] = []
    for rec in (feats.get("attribution") or []):
        try:
            attribution.append(AttributionRecord(
                kind=str(rec.get("kind", "")),
                drill=str(rec.get("drill", "")),
                metric=str(rec.get("metric", "")),
                value=rec.get("value"),
                baseline=rec.get("baseline"),
                passes=rec.get("passes"),
                headline=str(rec.get("headline", "")),
                detail=str(rec.get("detail", "")),
                cited_records=list(rec.get("cited_records") or []),
            ))
        except (TypeError, ValueError):
            continue
    return RcaFeatures(
        schema=str(feats.get("schema", "")),
        window_start=str(window.get("start", "")),
        window_end=str(window.get("end", "")),
        drills=drills,
        aggregate=dict(feats.get("aggregate") or {}),
        anomalies=anomalies,
        attribution=attribution,
        provenance=list(feats.get("provenance") or []),
    )


@router.get(
    "/rca/{iso_date}/prompt",
    response_model=RcaPromptView,
)
def rca_prompt(
    iso_date: str,
    digest_dir: Optional[str] = Query(None),
) -> RcaPromptView:
    """Return the exact prompt string that was (or would have been) sent
    to the backend for the archived digest.

    The prompt is regenerated from the persisted ``features`` dict using
    the same ``_format_prompt`` routine ``rca_nightly`` uses, so the
    bytes are byte-identical and the sha256 MUST match the one stored
    with the digest -- the ``prompt_sha256_matches_stored`` flag lets
    the UI surface any drift (schema change, tampering, etc.).
    """
    dd = Path(digest_dir) if digest_dir else _default_digest_dir()
    payload = load_digest(dd, iso_date)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"no digest for {iso_date}")
    feats = payload.get("features") or {}
    rca = _rehydrate_features(feats)
    prompt = _format_prompt(rca)
    phash = _prompt_hash(prompt)
    stored = str(payload.get("prompt_sha256") or "")
    return RcaPromptView(
        date=iso_date,
        backend=str(payload.get("backend", "template")),
        model=payload.get("model"),
        prompt_template=NIGHTLY_PROMPT,
        prompt=prompt,
        prompt_sha256=phash,
        prompt_sha256_matches_stored=bool(stored) and stored == phash,
    )


@router.get(
    "/rca/{iso_date}/proposed-patch",
    response_model=ProposedPatchView,
    response_model_by_alias=True,
)
def rca_proposed_patch(
    iso_date: str,
    digest_dir: Optional[str] = Query(None),
) -> ProposedPatchView:
    """Return the review-only JSON patch the RCA agent would propose.

    Deterministic for a given day's feature bundle. Never applied --
    the ``review_only`` field is hardcoded ``True`` and the UI renders
    the panel with a matching "review-only, never auto-applied" badge.
    """
    dd = Path(digest_dir) if digest_dir else _default_digest_dir()
    payload = load_digest(dd, iso_date)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"no digest for {iso_date}")
    rca = _rehydrate_features(payload.get("features") or {})
    proposal = propose_config_patch(rca)
    return ProposedPatchView(
        schema=proposal.schema or PROPOSAL_SCHEMA_VERSION,
        date=proposal.date or iso_date,
        review_only=True,
        patch=[ConfigPatchOp(**op) for op in proposal.patch],
        summary=proposal.summary,
        patch_hash_sha256=proposal.patch_hash_sha256,
    )


@router.get(
    "/rca/{iso_date}/compare",
    response_model=RcaCompareView,
)
def rca_compare(
    iso_date: str,
    digest_dir: Optional[str] = Query(None),
) -> RcaCompareView:
    """Side-by-side deterministic-vs-live for a single day.

    ``live_markdown`` is whatever backend was archived that day.
    ``deterministic_markdown`` is the template digest regenerated from
    the same stored features. The UI can diff the two; identical bytes
    mean the archived run was the template path and any diff is the
    LLM's contribution.
    """
    dd = Path(digest_dir) if digest_dir else _default_digest_dir()
    payload = load_digest(dd, iso_date)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"no digest for {iso_date}")
    rca = _rehydrate_features(payload.get("features") or {})
    deterministic = _template_digest(rca)
    live = str(payload.get("markdown") or "")
    anomalies = rca.anomalies or []
    return RcaCompareView(
        date=iso_date,
        backend=str(payload.get("backend", "template")),
        model=payload.get("model"),
        live_markdown=live,
        deterministic_markdown=deterministic,
        identical=(live == deterministic),
        anomaly_count=len(anomalies),
        prompt_sha256=str(payload.get("prompt_sha256") or ""),
    )


@router.get(
    "/rca/{iso_date}/attribution",
    response_model=AttributionView,
)
def rca_attribution(
    iso_date: str,
    digest_dir: Optional[str] = Query(None),
) -> AttributionView:
    """Return the alpha-attribution panel for one archived digest.

    Rehydrates the persisted features and returns the stored
    attribution list as a typed view. If the archived digest predates
    Phase 7 (no attribution key in features), the records list is
    empty -- the UI shows a "no attribution stored for this digest"
    banner and offers to regenerate.
    """
    dd = Path(digest_dir) if digest_dir else _default_digest_dir()
    payload = load_digest(dd, iso_date)
    if payload is None:
        raise HTTPException(
            status_code=404, detail=f"no digest for {iso_date}"
        )
    rca = _rehydrate_features(payload.get("features") or {})
    records = [
        AttributionRecordView(
            kind=r.kind,
            drill=r.drill,
            metric=r.metric,
            value=r.value,
            baseline=r.baseline,
            passes=r.passes,
            headline=r.headline,
            detail=r.detail,
            cited_records=list(r.cited_records),
        )
        for r in rca.attribution
    ]
    pass_count = sum(1 for r in records if r.passes is True)
    fail_count = sum(1 for r in records if r.passes is False)
    return AttributionView(
        date=iso_date,
        backend=str(payload.get("backend", "template")),
        records=records,
        pass_count=pass_count,
        fail_count=fail_count,
    )


@router.post("/rca/run", response_model=RunDigestResponse)
def rca_run(req: RunDigestRequest) -> RunDigestResponse:
    """Regenerate one digest on demand.

    Uses the deterministic template backend by default so the call is
    safe from any environment (no API key required).
    """
    artifacts = Path(req.artifacts_root) if req.artifacts_root \
        else _default_artifacts_root()
    digest_dir = Path(req.digest_dir) if req.digest_dir \
        else _default_digest_dir()
    iso_date = req.date or _dt.date.today().isoformat()
    try:
        result = run_nightly(
            artifacts_root=artifacts,
            digest_dir=digest_dir,
            run_date=iso_date,
            backend=req.backend,
            model=req.model,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    md = digest_dir / f"{iso_date}.md"
    js = digest_dir / f"{iso_date}.json"
    # ``DigestResult.features`` is a dict (see rca_nightly.generate_digest
    # line 367 -- ``features=features.to_dict()``). Anomalies are listed
    # under the "anomalies" key.
    feats = result.features or {}
    anomaly_count = len(feats.get("anomalies", []))
    return RunDigestResponse(
        date=iso_date,
        backend=result.backend,
        markdown_path=str(md),
        json_path=str(js),
        anomaly_count=anomaly_count,
    )


# ---- Triage ----------------------------------------------------------


@router.get("/triage/alerts", response_model=AlertChainView)
def triage_alerts(
    log_path: Optional[str] = Query(
        None, description="Override sidecar alert-log path."
    ),
    limit: int = Query(
        100, ge=1, le=10_000,
        description="Most-recent N alerts to include in the response.",
    ),
) -> AlertChainView:
    """Read and verify the BLAKE2b-chained sidecar alert log."""
    p = Path(log_path) if log_path else _default_alert_log()
    if not p.exists():
        return AlertChainView(
            chain_ok=True, n_records=0,
            head_hash_lo="", alerts=[],
        )
    res = verify_chain(p)
    summaries: List[AlertSummary] = []
    # Re-read to surface the records themselves; verify_chain already
    # walked the file for integrity, so this second pass is a flat
    # decode without re-checking hashes.
    try:
        all_recs = list(read_alerts(p))
    except Exception:                    # noqa: BLE001 -- chain may be torn
        all_recs = []
    for r in all_recs[-limit:]:
        summaries.append(AlertSummary(
            seq_no=r.seq_no,
            timestamp_ns=r.timestamp_ns,
            severity=r.severity_name,
            detector=r.detector,
            stage=r.stage,
            detail=r.detail,
            score=r.score,
            window_n=r.window_n,
            full_hash_lo=r.full_hash_lo.hex(),
        ))
    return AlertChainView(
        chain_ok=res.chain_ok,
        n_records=res.n_records,
        head_hash_lo=res.head_hash_lo_hex,
        bad_index=res.bad_index,
        bad_reason=res.bad_reason,
        alerts=summaries,
    )


@router.post("/triage/eval", response_model=TriageEvalResponse)
def triage_eval() -> TriageEvalResponse:
    """Run the deterministic scripted evaluation harness."""
    report = run_evaluation()
    return TriageEvalResponse(**report)


__all__ = ["router"]
