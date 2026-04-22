"""
demo_api.py - interactive-demo FastAPI router.

Exposes the four Hyperliquid drills + audit-chain verifier + config
editor endpoints consumed by the web UI. The router is mounted by
``sentinel_hft.server.app`` on the main FastAPI app.

Endpoints
---------

    GET  /api/drills                         -- drill catalog + defaults
    GET  /api/config/defaults                -- default RiskGateConfig
    POST /api/drills/toxic_flow/run          -- sync run, return JSON report
    POST /api/drills/kill_drill/run          -- sync run, return JSON report
    POST /api/drills/latency/run             -- sync run, return JSON report
    POST /api/drills/daily_evidence/run      -- sync run, return JSON report
    WS   /api/drills/{kind}/stream           -- run + stream progress events
    POST /api/audit/verify                   -- upload .aud, walk hash chain
    POST /api/audit/tamper-demo              -- inject byte flip, return break
    GET  /api/artifacts/{kind}/{filename}    -- serve generated artifact files
    GET  /api/compliance/crosswalk           -- regulation crosswalk (static)
    GET  /api/compliance/live-counter-keys   -- keys the UI binds live to
    GET  /api/compliance/snapshot-shape      -- empty ComplianceSnapshot schema
"""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import (
    APIRouter,
    Body,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse

from sentinel_hft.audit.record import (
    AUDIT_FILE_HEADER_SIZE,
    AUDIT_RECORD_SIZE,
    read_records,
)
from sentinel_hft.audit.verifier import verify as verify_chain
from sentinel_hft.compliance import ComplianceStack, crosswalk_as_dict
from sentinel_hft.compliance.crosswalk import live_counter_keys
from sentinel_hft.deribit.risk import RiskGateConfig
from sentinel_hft.usecases import (
    DailyEvidenceConfig,
    KillDrillConfig,
    LatencyConfig,
    ToxicFlowConfig,
    run_daily_evidence,
    run_kill_drill,
    run_latency,
    run_toxic_flow,
)

from .streaming import (
    build_daily_evidence_stream,
    build_kill_drill_stream,
    build_latency_stream,
    build_toxic_flow_stream,
    report_to_json,
)


router = APIRouter(prefix="/api", tags=["demo"])


# ---------------------------------------------------------------------
# Drill metadata
# ---------------------------------------------------------------------


DRILLS: Dict[str, Dict[str, Any]] = {
    "toxic_flow": {
        "name": "Toxic flow rejection",
        "description": (
            "16-taker population, toxic-heavy mix, pre-gate adverse-"
            "selection guard rejects ~45% of the flow before it reaches "
            "the risk gate."
        ),
        "expected_duration_s": 18,
        "default_ticks": 30_000,
        "config_schema": {
            "ticks": "int", "seed": "int",
            "taker_population": "int",
            "toxic_share": "float", "benign_share": "float",
            "trade_prob": "float",
            "toxic_rate_threshold": "float",
            "toxic_min_flow_events": "int",
        },
    },
    "kill_drill": {
        "name": "Volatility kill-switch",
        "description": (
            "Clean-baseline run interrupted by a 2% vol spike at tick "
            "9,000. Kill trips at intent 25,500; every subsequent "
            "intent must be rejected with reason=KILL_SWITCH."
        ),
        "expected_duration_s": 14,
        "default_ticks": 24_000,
        "config_schema": {
            "ticks": "int", "seed": "int",
            "spike_at_tick": "int",
            "spike_magnitude": "float",
            "inject_kill_at_intent": "int",
            "slo_budget_ns": "int",
        },
    },
    "latency": {
        "name": "Wire-to-wire latency attribution",
        "description": (
            "40k-tick clean-baseline replay; per-stage ingress/core/"
            "risk/egress latency with p50/p99/p999 and SLO violation "
            "counters."
        ),
        "expected_duration_s": 24,
        "default_ticks": 40_000,
        "config_schema": {
            "ticks": "int", "seed": "int",
            "toxic_share": "float", "benign_share": "float",
            "trade_prob": "float",
            "enable_toxic_guard": "bool",
            "slo_p99_ns": "int|null",
        },
    },
    "daily_evidence": {
        "name": "Daily evidence pack",
        "description": (
            "Three back-to-back sessions (morning / midday / eod), "
            "combined DORA bundle, all three audit chains verified."
        ),
        "expected_duration_s": 28,
        "default_ticks": 26_000,
        "config_schema": {
            "trading_date": "str",
            "sessions": "list[SessionSpec]",
        },
    },
}


# ---------------------------------------------------------------------
# Config parsing helpers
# ---------------------------------------------------------------------


def _dc_defaults(dc_cls) -> Dict[str, Any]:
    inst = dc_cls()
    out: Dict[str, Any] = {}
    for k, v in asdict(inst).items():
        if isinstance(v, Path):
            out[k] = str(v)
        elif isinstance(v, bytes):
            out[k] = v.hex()
        else:
            out[k] = v
    return out


def _apply_overrides(dc_inst, overrides: Optional[Dict[str, Any]]):
    """Best-effort apply a dict of overrides to a dataclass instance.
    Unknown keys are silently ignored -- the UI is a loose client."""
    if not overrides:
        return dc_inst
    for k, v in overrides.items():
        if hasattr(dc_inst, k):
            attr = getattr(dc_inst, k)
            # Preserve Path type.
            if isinstance(attr, Path) and v is not None:
                setattr(dc_inst, k, Path(v))
            else:
                setattr(dc_inst, k, v)
    return dc_inst


def _parse_cfg(kind: str, body: Optional[Dict[str, Any]]):
    body = body or {}
    if kind == "toxic_flow":
        cfg = ToxicFlowConfig()
    elif kind == "kill_drill":
        cfg = KillDrillConfig()
    elif kind == "latency":
        cfg = LatencyConfig()
    elif kind == "daily_evidence":
        cfg = DailyEvidenceConfig()
    else:
        raise HTTPException(status_code=404, detail=f"unknown drill: {kind}")
    return _apply_overrides(cfg, body)


# ---------------------------------------------------------------------
# Catalog + defaults
# ---------------------------------------------------------------------


@router.get("/drills")
async def list_drills():
    """Return the four-drill catalog with default configs."""
    out: Dict[str, Any] = {}
    for key, meta in DRILLS.items():
        if key == "toxic_flow":
            defaults = _dc_defaults(ToxicFlowConfig)
        elif key == "kill_drill":
            defaults = _dc_defaults(KillDrillConfig)
        elif key == "latency":
            defaults = _dc_defaults(LatencyConfig)
        else:
            defaults = _dc_defaults(DailyEvidenceConfig)
        out[key] = {**meta, "defaults": defaults}
    return out


@router.get("/config/defaults")
async def config_defaults():
    """Default RiskGateConfig for the demo's config editor."""
    return _dc_defaults(RiskGateConfig)


# ---------------------------------------------------------------------
# Synchronous drill runs (REST)
# ---------------------------------------------------------------------


@router.post("/drills/{kind}/run")
async def run_drill(kind: str, body: Optional[Dict[str, Any]] = Body(None)):
    """Run a drill to completion and return its Report as JSON.

    Blocks the HTTP request for the drill's duration (~15-30s).
    For live progress use the WebSocket endpoint instead.
    """
    cfg = _parse_cfg(kind, body)
    try:
        if kind == "toxic_flow":
            report = run_toxic_flow(cfg)
        elif kind == "kill_drill":
            report = run_kill_drill(cfg)
        elif kind == "latency":
            report = run_latency(cfg)
        elif kind == "daily_evidence":
            report = run_daily_evidence(cfg)
        else:
            raise HTTPException(status_code=404, detail=f"unknown drill: {kind}")
    except HTTPException:
        raise
    except Exception as e:                   # noqa: BLE001
        raise HTTPException(status_code=500,
                            detail=f"{type(e).__name__}: {e}") from e

    return JSONResponse({
        "drill": kind,
        "report": report_to_json(report),
    })


# ---------------------------------------------------------------------
# WebSocket streaming endpoint
# ---------------------------------------------------------------------


_BUILDERS = {
    "toxic_flow": build_toxic_flow_stream,
    "kill_drill": build_kill_drill_stream,
    "latency": build_latency_stream,
    "daily_evidence": build_daily_evidence_stream,
}


@router.websocket("/drills/{kind}/stream")
async def stream_drill(ws: WebSocket, kind: str):
    """Run a drill on a worker thread, stream progress events, and
    send the final Report when it completes.

    The client sends a single JSON message immediately after connecting
    with any config overrides (or ``{}`` to accept defaults). All
    subsequent messages from the server are typed events:

    - ``{"type":"start", "ticks_target":N, ...}``
    - ``{"type":"progress", "ticks_consumed":.., "latency_ns":{..}, ..}``
    - ``{"type":"result", "report":{...}}`` (terminal, happy path)
    - ``{"type":"error", "error":"..."}`` (terminal, sad path)
    """
    if kind not in _BUILDERS:
        await ws.close(code=1008, reason=f"unknown drill: {kind}")
        return

    await ws.accept()
    try:
        # The client must push its config first. We allow an empty
        # payload / missing message -> defaults.
        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=5.0)
            overrides = json.loads(raw) if raw else {}
        except asyncio.TimeoutError:
            overrides = {}

        cfg = _parse_cfg(kind, overrides)
        stream = _BUILDERS[kind](cfg)

        async for event in stream.events():
            try:
                await ws.send_json(event)
            except (WebSocketDisconnect, RuntimeError):
                # Client went away mid-run. Let the worker finish on
                # its own (it's a daemon thread) and exit quietly.
                return
    except WebSocketDisconnect:
        return
    except Exception as e:                    # noqa: BLE001
        try:
            await ws.send_json({
                "type": "error",
                "error": f"{type(e).__name__}: {e}",
            })
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


# ---------------------------------------------------------------------
# Audit-chain verifier + tamper demo
# ---------------------------------------------------------------------


@router.post("/audit/verify")
async def verify_audit(file: UploadFile):
    """Upload a ``.aud`` file, walk the hash chain, return the verdict.

    Response shape::

        {
          "ok": bool,
          "total_records": int,
          "verified_records": int,
          "breaks": [{"seq_no": int, "kind": str, "detail": str}, ...],
          "head_hash_lo_hex": "..."  // or null if chain empty
        }
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=".aud") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)
    try:
        records = list(read_records(tmp_path))
        result = verify_chain(records)
        payload = result.to_dict()
        payload["first_break_seq_no"] = (
            result.breaks[0].seq_no if result.breaks else None
        )
        return payload
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        tmp_path.unlink(missing_ok=True)


@router.post("/audit/tamper-demo")
async def tamper_demo(
    file: UploadFile,
    record_index: int = Query(
        ...,
        description=("0-based record index to tamper. Must be < the "
                     "chain's record count."),
        ge=0,
    ),
    byte_offset: int = Query(
        0,
        description="Byte offset inside the record to flip.",
        ge=0, lt=AUDIT_RECORD_SIZE,
    ),
):
    """Demonstrate tamper-detection: upload a clean ``.aud``, flip one
    byte at ``(record_index, byte_offset)``, re-run the verifier on
    the mutated copy, return the break. The client uses this to drive
    the "inject corruption and show the chain break" button on the
    audit-verifier panel.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=".aud") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)
    try:
        # Clean walk first so the UI can contrast clean vs tampered.
        clean_records = list(read_records(tmp_path))
        clean = verify_chain(clean_records).to_dict()

        if record_index >= len(clean_records):
            raise HTTPException(
                status_code=400,
                detail=(f"record_index {record_index} >= chain length "
                        f"{len(clean_records)}"),
            )

        # In-place byte flip inside the mmap-able file.
        target_offset = (
            AUDIT_FILE_HEADER_SIZE
            + (record_index * AUDIT_RECORD_SIZE)
            + byte_offset
        )
        with tmp_path.open("r+b") as f:
            f.seek(target_offset)
            b = f.read(1)
            if not b:
                raise HTTPException(
                    status_code=400,
                    detail="truncated record at tamper offset")
            f.seek(target_offset)
            f.write(bytes([b[0] ^ 0xFF]))

        # Re-walk the mutated file.
        mutated_records = list(read_records(tmp_path))
        mutated = verify_chain(mutated_records).to_dict()

        return {
            "clean": clean,
            "mutated": mutated,
            "tamper": {
                "record_index": record_index,
                "byte_offset": byte_offset,
                "file_offset": target_offset,
                "original_byte_hex": f"{b[0]:02x}",
                "mutated_byte_hex": f"{(b[0] ^ 0xFF):02x}",
            },
            "first_break_seq_no": (
                mutated["breaks"][0]["seq_no"]
                if mutated["breaks"] else None
            ),
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------
# Compliance crosswalk + live-counter key advertising
# ---------------------------------------------------------------------


@router.get("/compliance/crosswalk")
async def compliance_crosswalk():
    """Return the 9-entry regulation crosswalk.

    Consumed by ``/sentinel/regulations`` to render the static map of
    regulation -> primitive -> artefact rows. The payload is stable
    across runs -- it's the single source of truth that
    ``docs/COMPLIANCE.md`` is expected to mirror verbatim.
    """
    entries = crosswalk_as_dict()
    return {
        "entries": entries,
        "live_counter_keys": live_counter_keys(),
        "count": len(entries),
    }


@router.get("/compliance/live-counter-keys")
async def compliance_live_counter_keys():
    """Return the stable keys of crosswalk rows that emit a live counter.

    The UI uses this to decide which cells should bind to the WS
    progress event's ``event.compliance[KEY]`` tick stream.
    """
    return {"keys": live_counter_keys()}


@router.get("/compliance/snapshot-shape")
async def compliance_snapshot_shape():
    """Return an empty ``ComplianceSnapshot.as_dict()`` shape.

    Lets the UI render a zero-valued dashboard before any drill has
    run -- the WS progress events from ``/api/drills/{kind}/stream``
    will then overwrite the cells in place.
    """
    # Build an ephemeral stack (no CAT NDJSON output) purely to get
    # the shape; close it immediately. Counters are all at their zero
    # initial values.
    with ComplianceStack(cat_output_path=None) as stack:
        shape = stack.snapshot().as_dict()
    return shape


# ---------------------------------------------------------------------
# Artifact serving (for opening the generated HTML report inline)
# ---------------------------------------------------------------------


_SAFE_FILENAMES = {
    "toxic_flow.json", "toxic_flow.md", "toxic_flow.html",
    "kill_drill.json", "kill_drill.md", "kill_drill.html",
    "latency.json", "latency.md", "latency.html",
    "daily_evidence.json", "daily_evidence.md", "daily_evidence.html",
    "summary.md", "dora.json",
    "audit.aud", "traces.sst",
}


@router.get("/artifacts/{kind}/{filename}")
async def get_artifact(kind: str, filename: str,
                       output_root: Optional[str] = Query(
                           None,
                           description=(
                               "Override the output root if the drill "
                               "was run with a non-default --output-dir."
                           ))):
    """Serve a generated artifact file by drill kind + filename."""
    if filename not in _SAFE_FILENAMES:
        raise HTTPException(status_code=404,
                            detail=f"not a known artifact: {filename}")
    if kind not in DRILLS:
        raise HTTPException(status_code=404, detail=f"unknown drill: {kind}")
    root = Path(output_root) if output_root else Path("out/hl") / kind
    path = root / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"not found: {path}")
    media = {
        ".json": "application/json",
        ".md": "text/markdown",
        ".html": "text/html",
        ".aud": "application/octet-stream",
        ".sst": "application/octet-stream",
    }.get(path.suffix, "application/octet-stream")
    return FileResponse(path, media_type=media, filename=filename)


# ---------------------------------------------------------------------
# asyncio import deferred to avoid circular-looking imports.
# ---------------------------------------------------------------------

import asyncio  # noqa: E402  (placed here for the WS timeout helper)


__all__ = ["router", "DRILLS"]
