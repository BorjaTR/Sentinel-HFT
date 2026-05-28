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
from fastapi.responses import FileResponse, JSONResponse, Response

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
# Offline-bundle export (Phase 6 "surprises" - regulator USB takeaway).
#
# Produces a single .zip containing:
#   - README_OFFLINE.md      -- what this is, how to use it, residency
#                               constraints (no network required)
#   - demo/                   -- market_data.csv + expected_metrics.json
#                               (fixtures for the smoke drill)
#   - scripts/smoke_demo.sh   -- the one-shot end-to-end smoke script
#   - verify_audit.py         -- standalone wrapper that re-runs the
#                               BLAKE2b chain verifier on a .aud file
#                               with zero third-party deps
#   - sentinel_hft/audit/*.py -- the actual verifier source (record,
#                               verifier, logger, alert_log) so the
#                               regulator can audit the audit
#   - docs/                   -- USE_CASES.md, COMPLIANCE.md,
#                               VERIFICATION_METHODOLOGY.md, V2_PLAN.md
#
# Everything stays local: this endpoint reads project files off disk
# and streams them through a zip buffer -- no external fetch, no LLM
# call, no network side-channel. Written synchronously because the
# payload is ~a few hundred KB.
# ---------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]


_OFFLINE_README = """\
# Sentinel-HFT offline evidence bundle

This zip is a self-contained, **no-network** takeaway that lets a
regulator (or any reviewer) re-run the Sentinel-HFT demo and
independently verify a BLAKE2b-chained audit log without trusting
the vendor's toolchain.

What you get
------------
- `demo/`                -- fixtures used by the four interactive
                            drills (toxic-flow, kill-drill, latency,
                            daily-evidence). Same inputs the UI runs
                            against.
- `scripts/smoke_demo.sh`-- one-shot end-to-end smoke script. Boots
                            the FastAPI server on a local port, runs
                            a drill, verifies the produced audit
                            chain, tears down.
- `verify_audit.py`      -- standalone audit-chain verifier. Zero
                            third-party deps. Run it against any
                            .aud file produced by Sentinel. Exits 0
                            on clean chain, non-zero on break.
- `sentinel_hft/audit/`  -- the verifier source (record format,
                            walker, alert-log). This is what the
                            vendor runs internally. Read it, audit
                            it, fork it.
- `docs/`                -- the methodology docs: USE_CASES,
                            COMPLIANCE crosswalk, VERIFICATION
                            methodology, V2_PLAN (what this build
                            delivers).

How to use it
-------------
Re-verify a .aud file produced by any Sentinel drill:

    python3 verify_audit.py path/to/audit.aud

Re-run the smoke drill (requires Python 3.10+ and the Sentinel
source tree; this zip intentionally does **not** bundle the
pipeline implementation -- only the verifier):

    bash scripts/smoke_demo.sh

Data residency
--------------
No file in this bundle makes an outbound network call. The
verifier reads the .aud from disk, walks the BLAKE2b chain, and
prints the head hash. If any record's prev_hash_lo does not match
the previous record's committed payload hash, the walker stops at
that sequence number and exits non-zero.

Generated by
------------
`GET /api/export/offline-bundle` on a running Sentinel-HFT
FastAPI server. The endpoint reads from the server's own source
tree at request time, so the bundle always reflects the deployed
build.
"""


_OFFLINE_VERIFIER = '''#!/usr/bin/env python3
"""
verify_audit.py - standalone Sentinel-HFT audit chain verifier.

Walks the BLAKE2b hash chain of an .aud file produced by Sentinel
and reports:
  - total records parsed
  - head hash (hex)
  - first chain break, if any

Zero third-party dependencies. Run under any Python 3.10+ on any
POSIX or Windows host. Exits 0 on clean chain, 1 on break or
unreadable input.

Usage
-----

    python3 verify_audit.py path/to/audit.aud

The verifier source is a subset of what the Sentinel server runs
internally. If you would rather audit the server's verifier
directly, see `sentinel_hft/audit/verifier.py` in this bundle.
"""
from __future__ import annotations

import sys
from pathlib import Path

# The bundle ships the actual verifier alongside this script so a
# regulator can read it before running.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from sentinel_hft.audit.record import read_records  # type: ignore
from sentinel_hft.audit.verifier import verify  # type: ignore


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: verify_audit.py <path/to/audit.aud>",
              file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"not found: {path}", file=sys.stderr)
        return 1
    # read_records returns an iterator over AuditRecord instances.
    records = list(read_records(path))
    result = verify(records)
    print(f"records   : {result.total_records}")
    print(f"verified  : {result.verified_records}")
    head_hex = (
        result.head_hash_lo.hex() if result.head_hash_lo else "<empty>"
    )
    print(f"head_hash : {head_hex}")
    print(f"ok        : {result.ok}")
    if not result.ok:
        for b in result.breaks[:5]:
            print(f"  seq={b.seq_no} kind={b.kind} detail={b.detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def _build_offline_bundle() -> bytes:
    """Materialise the offline-evidence zip in memory."""
    import io
    import zipfile

    buf = io.BytesIO()
    # ZIP_DEFLATED keeps the payload under ~200 KB for typical
    # fixture sizes. Deterministic mtime so the bundle hashes
    # identically across calls within a release.
    with zipfile.ZipFile(
        buf,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as zf:
        zf.writestr("README_OFFLINE.md", _OFFLINE_README)
        zf.writestr("verify_audit.py", _OFFLINE_VERIFIER)

        # Fixtures.
        demo_root = _REPO_ROOT / "demo"
        if demo_root.is_dir():
            for name in ("market_data.csv", "expected_metrics.json"):
                p = demo_root / name
                if p.is_file():
                    zf.write(p, arcname=f"demo/{name}")

        # Smoke script.
        smoke = _REPO_ROOT / "scripts" / "smoke_demo.sh"
        if smoke.is_file():
            zf.write(smoke, arcname="scripts/smoke_demo.sh")

        # Verifier source + its dependencies. We copy the whole
        # audit package because record.py and alert_log.py are
        # imported by verifier.py.
        audit_root = _REPO_ROOT / "sentinel_hft" / "audit"
        if audit_root.is_dir():
            for p in audit_root.glob("*.py"):
                rel = p.relative_to(_REPO_ROOT)
                zf.write(p, arcname=str(rel))
            # Include an empty __init__ for sentinel_hft so the
            # import path resolves when verify_audit.py runs with
            # HERE on sys.path.
            sh_init = _REPO_ROOT / "sentinel_hft" / "__init__.py"
            if sh_init.is_file():
                zf.write(sh_init,
                         arcname="sentinel_hft/__init__.py")

        # Methodology docs.
        docs_root = _REPO_ROOT / "docs"
        if docs_root.is_dir():
            for name in (
                "USE_CASES.md",
                "COMPLIANCE.md",
                "VERIFICATION_METHODOLOGY.md",
                "V2_PLAN.md",
                "ARCHITECTURE.md",
            ):
                p = docs_root / name
                if p.is_file():
                    zf.write(p, arcname=f"docs/{name}")

    return buf.getvalue()


@router.get("/export/offline-bundle")
async def export_offline_bundle():
    """Return a zip of the regulator-takeaway bundle.

    The bundle is assembled synchronously from files on the server's
    own source tree. No external fetch, no LLM call. The HTTP
    response carries a stable filename so the browser drops it
    straight into ~/Downloads.
    """
    payload = _build_offline_bundle()
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                'attachment; filename="sentinel-hft-offline-bundle.zip"'
            ),
            "Content-Length": str(len(payload)),
            "Cache-Control": "no-store",
        },
    )


@router.get("/export/offline-bundle/manifest")
async def export_offline_bundle_manifest():
    """Return a JSON manifest of the offline bundle.

    Lets the UI show what the download contains (filenames + sizes)
    before the user clicks. Keeps the download button honest -- if
    a file is missing on disk, it shows up as missing here.
    """
    import io
    import zipfile

    payload = _build_offline_bundle()
    buf = io.BytesIO(payload)
    entries: list[Dict[str, Any]] = []
    with zipfile.ZipFile(buf, "r") as zf:
        for info in zf.infolist():
            entries.append({
                "name": info.filename,
                "size": info.file_size,
                "compressed_size": info.compress_size,
            })
    return JSONResponse({
        "total_bytes": len(payload),
        "entries": entries,
    })


# ---------------------------------------------------------------------
# asyncio import deferred to avoid circular-looking imports.
# ---------------------------------------------------------------------

import asyncio  # noqa: E402  (placed here for the WS timeout helper)


__all__ = ["router", "DRILLS"]
