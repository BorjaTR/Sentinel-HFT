"""Workstream 4 + 5 -- FastAPI router smoke tests.

Exercises every endpoint mounted by ``sentinel_hft.server.ai_api``:

    GET  /api/ai/rca/list
    POST /api/ai/rca/run
    GET  /api/ai/rca/{iso_date}
    GET  /api/ai/triage/alerts
    POST /api/ai/triage/eval

The tests use the ``digest_dir`` / ``log_path`` query overrides so
they never touch the process-wide env-defaulted paths and never
mutate state outside ``tmp_path``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from sentinel_hft.audit.alert_log import AlertChain, verify_chain
from sentinel_hft.server.app import app


# ---------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def _toxic_flow_report(
    *,
    intents: int = 2866,
    rejected_toxic: int = 0,
    rejected: int = 0,
    core_p99: float = 2540.0,
    chain_ok: bool = True,
) -> Dict[str, Any]:
    return {
        "schema": "sentinel-hft/usecase/toxic-flow/1",
        "subject": "sentinel-hft-hl-toxic-flow",
        "environment": "sim",
        "label": "toxic-flow",
        "run_id_hex": "0x484c0001",
        "config": {"ticks": 800},
        "throughput": {
            "ticks": 800,
            "intents": intents,
            "decisions": intents,
            "passed": intents - rejected,
            "rejected": rejected,
            "rejected_toxic": rejected_toxic,
        },
        "latency_ns": {
            "p50": 1410.0, "p99": 3751.0, "p999": 8010.0, "max": 8110.0,
        },
        "stage_p99_ns": {
            "ingress": 470.0,
            "core": core_p99,
            "risk": 230.0,
            "egress": 470.0,
        },
        "audit": {
            "head_hash_lo_hex": "3ff946f2d341833456e5a1a9aa525206",
            "chain_ok": chain_ok,
        },
        "compliance": {},
    }


def _seed_artifacts(root: Path) -> Path:
    """Write a single nominal toxic_flow drill under ``root/toxic_flow/``."""
    drill = root / "toxic_flow"
    drill.mkdir(parents=True, exist_ok=True)
    (drill / "audit.aud").write_bytes(b"")
    (drill / "toxic_flow.json").write_text(
        json.dumps(_toxic_flow_report())
    )
    return root


# ---------------------------------------------------------------------
# RCA: list / run / get
# ---------------------------------------------------------------------


def test_rca_list_empty_dir_returns_empty(client: TestClient,
                                          tmp_path: Path) -> None:
    digest_dir = tmp_path / "digests-empty"
    r = client.get(
        "/api/ai/rca/list",
        params={"digest_dir": str(digest_dir)},
    )
    assert r.status_code == 200
    assert r.json() == []


def test_rca_run_then_list_then_get(client: TestClient,
                                    tmp_path: Path) -> None:
    artifacts = tmp_path / "out" / "hl"
    digest_dir = tmp_path / "digests"
    _seed_artifacts(artifacts)

    # 1. Regenerate today's digest using the deterministic backend.
    r = client.post(
        "/api/ai/rca/run",
        json={
            "artifacts_root": str(artifacts),
            "digest_dir": str(digest_dir),
            "date": "2026-04-21",
            "backend": "template",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["date"] == "2026-04-21"
    assert body["backend"] == "template"
    assert body["markdown_path"].endswith("2026-04-21.md")
    assert body["json_path"].endswith("2026-04-21.json")
    assert body["anomaly_count"] >= 0
    assert (digest_dir / "2026-04-21.md").exists()
    assert (digest_dir / "2026-04-21.json").exists()

    # 2. List sees the new archive.
    r = client.get(
        "/api/ai/rca/list",
        params={"digest_dir": str(digest_dir)},
    )
    assert r.status_code == 200
    listed = r.json()
    assert len(listed) == 1
    row = listed[0]
    assert row["date"] == "2026-04-21"
    assert row["backend"] == "template"
    assert row["anomaly_count"] >= 0
    # ``schema`` is the wire-name (aliased from ``digest_schema``).
    assert "schema" in row

    # 3. Get returns the persisted JSON.
    r = client.get(
        "/api/ai/rca/2026-04-21",
        params={"digest_dir": str(digest_dir)},
    )
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["date"] == "2026-04-21"
    assert detail["backend"] == "template"
    assert detail["markdown"]
    assert detail["prompt_sha256"]
    assert isinstance(detail["features"], dict)
    assert detail["schema"].startswith("sentinel-hft/rca-digest")


def test_rca_get_unknown_date_404s(client: TestClient,
                                   tmp_path: Path) -> None:
    digest_dir = tmp_path / "digests-404"
    digest_dir.mkdir()
    r = client.get(
        "/api/ai/rca/1999-01-01",
        params={"digest_dir": str(digest_dir)},
    )
    assert r.status_code == 404


def test_rca_run_400_when_artifacts_missing(client: TestClient,
                                            tmp_path: Path) -> None:
    digest_dir = tmp_path / "digests-bad"
    r = client.post(
        "/api/ai/rca/run",
        json={
            "artifacts_root": str(tmp_path / "definitely-missing"),
            "digest_dir": str(digest_dir),
            "date": "2026-04-21",
            "backend": "template",
        },
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------
# Triage: alerts
# ---------------------------------------------------------------------


def test_triage_alerts_missing_log_returns_empty_chain(
    client: TestClient, tmp_path: Path
) -> None:
    log = tmp_path / "absent.alog"
    r = client.get(
        "/api/ai/triage/alerts",
        params={"log_path": str(log)},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["chain_ok"] is True
    assert body["n_records"] == 0
    assert body["alerts"] == []


def test_triage_alerts_round_trip(client: TestClient,
                                  tmp_path: Path) -> None:
    log = tmp_path / "alerts.alog"
    with AlertChain.open(log) as chain:
        chain.append(
            detector="latency_zscore", severity="warn",
            detail="spike", score=4.5, stage="core",
            timestamp_ns=10_000, window_n=80,
        )
        chain.append(
            detector="reject_rate_cusum", severity="alert",
            detail="drift", score=6.1, stage=None,
            timestamp_ns=20_000, window_n=500,
        )

    # Sanity: the chain we just wrote is verifiable on disk.
    assert verify_chain(log).chain_ok is True

    r = client.get(
        "/api/ai/triage/alerts",
        params={"log_path": str(log), "limit": 10},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["chain_ok"] is True
    assert body["n_records"] == 2
    assert len(body["alerts"]) == 2
    seen = {a["detector"] for a in body["alerts"]}
    assert seen == {"latency_zscore", "reject_rate_cusum"}
    # Hash low half is hex-encoded for transport.
    for a in body["alerts"]:
        assert isinstance(a["full_hash_lo"], str)
        assert len(a["full_hash_lo"]) == 32  # 16 bytes hex


def test_triage_alerts_limit_parameter(client: TestClient,
                                       tmp_path: Path) -> None:
    log = tmp_path / "alerts-many.alog"
    with AlertChain.open(log) as chain:
        for i in range(5):
            chain.append(
                detector="latency_zscore", severity="info",
                detail=f"n={i}", score=float(i), stage="core",
                timestamp_ns=1_000 * (i + 1), window_n=30,
            )

    r = client.get(
        "/api/ai/triage/alerts",
        params={"log_path": str(log), "limit": 2},
    )
    assert r.status_code == 200
    body = r.json()
    # Chain integrity still reports the full N=5; only the
    # response window is limited.
    assert body["n_records"] == 5
    assert len(body["alerts"]) == 2
    # Most-recent two -- detail strings are deterministic.
    assert body["alerts"][-1]["detail"].startswith("n=4")


# ---------------------------------------------------------------------
# Triage: eval harness
# ---------------------------------------------------------------------


def test_triage_eval_returns_quality_bar_payload(client: TestClient) -> None:
    r = client.post("/api/ai/triage/eval")
    assert r.status_code == 200
    report = r.json()
    # Schema sanity -- every CLI-table key is present.
    for k in (
        "events", "labelled_anomalies", "alerts_fired",
        "true_positives", "false_positives", "false_negatives",
        "precision", "recall", "f1",
        "anomaly_windows", "alerts",
    ):
        assert k in report, f"missing key: {k}"
    # Default scenario hits the contracted quality bar.
    assert report["events"] > 1000
    assert report["labelled_anomalies"] >= 3
    assert report["recall"] == 1.0
    assert report["precision"] >= 0.70
    assert report["f1"] >= 0.80
    # Window labels round-trip.
    fams = sorted({w["family"] for w in report["anomaly_windows"]})
    assert fams == ["fill", "latency", "reject"]
