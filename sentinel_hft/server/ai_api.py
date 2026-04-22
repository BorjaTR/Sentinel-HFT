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

from sentinel_hft.ai.rca_nightly import (
    DIGEST_SCHEMA_VERSION,
    list_digests,
    load_digest,
    run_nightly,
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
