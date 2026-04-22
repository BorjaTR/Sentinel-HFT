"""End-to-end smoke test for the interactive-demo FastAPI router.

Exercises every endpoint in ``sentinel_hft.server.demo_api``:
    GET  /api/drills
    GET  /api/config/defaults
    POST /api/drills/toxic_flow/run
    POST /api/drills/latency/run
    POST /api/audit/verify
    POST /api/audit/tamper-demo
    GET  /api/artifacts/{kind}/{filename}
    GET  /api/compliance/crosswalk
    GET  /api/compliance/snapshot-shape
    WS   /api/drills/toxic_flow/stream

Ticks are kept small (800-2000) so the whole suite runs in ~5 s.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from sentinel_hft.server.app import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def tmp_out():
    root = Path(tempfile.mkdtemp(prefix="sentinel_demo_api_"))
    yield root
    # Leave artefacts for debug inspection on failure; OS tempdir GCs.


def test_drill_catalog(client):
    r = client.get("/api/drills")
    assert r.status_code == 200
    payload = r.json()
    assert set(payload.keys()) == {
        "toxic_flow", "kill_drill", "latency", "daily_evidence"}
    for v in payload.values():
        assert "defaults" in v
        assert "name" in v and "description" in v


def test_config_defaults(client):
    r = client.get("/api/config/defaults")
    assert r.status_code == 200
    cfg = r.json()
    # Fields every RiskGateConfig must carry.
    for k in ("max_tokens", "refill_per_second", "max_long_qty",
              "max_notional", "max_order_qty", "auto_kill_notional"):
        assert k in cfg


def test_run_toxic_flow(client, tmp_out):
    out = tmp_out / "toxic_flow"
    r = client.post("/api/drills/toxic_flow/run",
                    json={"ticks": 1500, "output_dir": str(out)})
    assert r.status_code == 200, r.text
    rep = r.json()["report"]
    assert rep["ticks"] == 1500
    assert rep["intents"] > 0
    assert rep["audit_chain_ok"] is True
    # Artefacts on disk.
    assert (out / "toxic_flow.json").exists()
    assert (out / "toxic_flow.html").exists()
    assert (out / "audit.aud").exists()


def test_run_latency(client, tmp_out):
    out = tmp_out / "latency"
    r = client.post("/api/drills/latency/run",
                    json={"ticks": 2000, "output_dir": str(out)})
    assert r.status_code == 200, r.text
    rep = r.json()["report"]
    assert rep["count"] > 0
    assert rep["p50_ns"] > 0
    assert rep["p99_ns"] >= rep["p50_ns"]
    assert rep["bottleneck_stage"] in rep["stage_p50_ns"]


def test_audit_verify_clean(client, tmp_out):
    aud = tmp_out / "toxic_flow" / "audit.aud"
    assert aud.exists(), "toxic_flow run must run first"
    with aud.open("rb") as f:
        r = client.post("/api/audit/verify",
                        files={"file": (aud.name, f, "application/octet-stream")})
    assert r.status_code == 200
    v = r.json()
    assert v["ok"] is True
    assert v["total_records"] == v["verified_records"]
    assert v["breaks"] == []


def test_audit_tamper_demo(client, tmp_out):
    aud = tmp_out / "toxic_flow" / "audit.aud"
    with aud.open("rb") as f:
        r = client.post(
            "/api/audit/tamper-demo",
            params={"record_index": 10, "byte_offset": 80},  # inside prev_hash_lo
            files={"file": (aud.name, f, "application/octet-stream")})
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["clean"]["ok"] is True
    assert t["mutated"]["ok"] is False
    assert t["first_break_seq_no"] is not None
    assert t["tamper"]["record_index"] == 10


def test_artifact_serving(client, tmp_out):
    r = client.get("/api/artifacts/toxic_flow/toxic_flow.json",
                   params={"output_root": str(tmp_out / "toxic_flow")})
    assert r.status_code == 200
    payload = r.json()
    assert "ticks" in payload or "config" in payload


def test_ws_stream(client, tmp_out):
    out = tmp_out / "toxic_flow_ws"
    with client.websocket_connect(
            "/api/drills/toxic_flow/stream") as ws:
        ws.send_text(json.dumps({"ticks": 800, "output_dir": str(out)}))
        saw_start = False
        saw_result = False
        while True:
            msg = ws.receive_json()
            if msg["type"] == "start":
                saw_start = True
                assert msg["ticks_target"] == 800
            elif msg["type"] == "progress":
                assert "latency_ns" in msg
                assert "stage_ns" in msg
            elif msg["type"] == "result":
                saw_result = True
                assert msg["report"]["ticks"] == 800
                break
            elif msg["type"] == "error":
                pytest.fail(f"stream error: {msg['error']}")
    assert saw_start and saw_result


def test_ws_stream_unknown_drill(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/api/drills/not_a_drill/stream") as ws:
            # Server should close the socket with policy-violation.
            ws.receive_json()


# ---------------------------------------------------------------------
# WS3 -- compliance crosswalk + snapshot smoke
# ---------------------------------------------------------------------


def test_compliance_crosswalk_endpoint(client):
    """Smoke: /api/compliance/crosswalk returns the registry payload."""
    r = client.get("/api/compliance/crosswalk")
    assert r.status_code == 200, r.text
    payload = r.json()
    assert set(payload.keys()) == {"entries", "live_counter_keys", "count"}
    # 9 clauses ship in v1.1.0; the count and entries length must agree.
    assert payload["count"] == len(payload["entries"]) >= 1
    # Every row has the documented field set.
    for row in payload["entries"]:
        assert {
            "key", "regulation", "jurisdiction", "clause", "primitive",
            "artifact", "layer", "audit_signal", "live_counter", "status",
        }.issubset(row.keys())


def test_compliance_snapshot_shape_endpoint(client):
    """Smoke: /api/compliance/snapshot-shape returns the empty
    ComplianceSnapshot the UI binds to before any drill runs."""
    r = client.get("/api/compliance/snapshot-shape")
    assert r.status_code == 200, r.text
    payload = r.json()
    # Five top-level dicts, one per implemented primitive.
    assert set(payload.keys()) == {
        "mifid_otr",
        "cftc_self_trade",
        "finra_fat_finger",
        "sec_cat",
        "mar_abuse",
    }
    for value in payload.values():
        assert isinstance(value, dict)
    # Counter blocks start at zero state.
    assert payload["mifid_otr"].get("total_orders", 0) == 0
    assert payload["mar_abuse"].get("alerts", 0) == 0
