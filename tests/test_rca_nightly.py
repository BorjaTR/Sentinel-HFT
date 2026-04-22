"""Workstream 4 -- nightly RCA digest tests.

Covers:

* ``rca_features.build_features_from_root`` against a canned drill
  artifact directory.
* Anomaly detection thresholds (stage latency, reject rate, toxic
  dominance, audit break, compliance signals).
* ``rca_nightly.generate_digest`` determinism in template backend.
* ``run_nightly`` full flow: archives Markdown + JSON sidecar.
* ``list_digests`` round-trip.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from sentinel_hft.ai.rca_features import (
    FEATURE_SCHEMA_VERSION,
    Anomaly,
    build_features,
    build_features_from_root,
    extract_drill_features,
)
from sentinel_hft.ai.rca_nightly import (
    DIGEST_SCHEMA_VERSION,
    generate_digest,
    list_digests,
    load_digest,
    run_nightly,
)


# ---------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------


def _toxic_flow_report(
    *,
    intents: int = 2866,
    rejected_toxic: int = 0,
    rejected: int = 0,
    core_p99: float = 2540.0,
    chain_ok: bool = True,
    compliance: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """A minimal toxic-flow report that mirrors the canonical schema."""
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
            "p50": 1410.0, "p99": 3751.0, "p999": 8010.0, "max": 8110.0
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
        "compliance": compliance or {},
    }


def _write_drill_dir(root: Path, drill: str, report: Dict[str, Any]) -> Path:
    drill_dir = root / drill
    drill_dir.mkdir(parents=True, exist_ok=True)
    (drill_dir / "audit.aud").write_bytes(b"")  # pairing sentinel
    jp = drill_dir / f"{drill}.json"
    jp.write_text(json.dumps(report))
    return jp


# ---------------------------------------------------------------------
# extract_drill_features
# ---------------------------------------------------------------------


def test_extract_drill_features_nominal(tmp_path: Path) -> None:
    jp = _write_drill_dir(tmp_path, "toxic_flow", _toxic_flow_report())
    feats = extract_drill_features(jp)
    assert feats.drill == "toxic_flow"
    assert feats.schema == "sentinel-hft/usecase/toxic-flow/1"
    assert feats.throughput["intents"] == 2866
    assert feats.audit["chain_ok"] is True
    assert feats.stage_latency_p99_ns["core"] == pytest.approx(2540.0)
    # Nominal day -> no rejects, empty histogram.
    assert feats.reject_histogram == {}


def test_reject_histogram_is_populated() -> None:
    report = _toxic_flow_report(
        intents=100,
        rejected=30,
        rejected_toxic=20,
    )
    # Non-toxic rejects surface through the other keys.
    report["throughput"]["rejected_rate"] = 5
    report["throughput"]["rejected_pos"] = 3
    report["throughput"]["rejected_kill"] = 2
    feats = build_features([]).drills  # empty but gives us the class
    # Instead of a helper, go via extract_drill_features
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        jp = _write_drill_dir(root, "toxic_flow", report)
        got = extract_drill_features(jp)
    assert got.reject_histogram == {
        "TOXIC_FLOW": 20,
        "RATE_LIMITED": 5,
        "POSITION_LIMIT": 3,
        "KILL_SWITCH": 2,
    }


# ---------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------


def test_no_anomalies_on_nominal(tmp_path: Path) -> None:
    _write_drill_dir(tmp_path, "toxic_flow", _toxic_flow_report())
    feats = build_features_from_root(tmp_path)
    assert feats.anomalies == []
    assert feats.aggregate["audit_chains_ok"] is True


def test_stage_latency_anomaly(tmp_path: Path) -> None:
    _write_drill_dir(
        tmp_path, "toxic_flow",
        _toxic_flow_report(core_p99=25_000.0),
    )
    feats = build_features_from_root(tmp_path)
    kinds = {a.kind for a in feats.anomalies}
    assert "stage_latency_p99" in kinds


def test_toxic_dominance_anomaly(tmp_path: Path) -> None:
    report = _toxic_flow_report(
        intents=100, rejected=30, rejected_toxic=20,
    )
    # Force another bucket so the mix has something to compare.
    report["throughput"]["rejected_rate"] = 10
    _write_drill_dir(tmp_path, "toxic_flow", report)
    feats = build_features_from_root(tmp_path)
    kinds = {a.kind for a in feats.anomalies}
    assert "toxic_dominant" in kinds
    assert "reject_rate_high" in kinds


def test_audit_chain_break_anomaly(tmp_path: Path) -> None:
    _write_drill_dir(
        tmp_path, "toxic_flow",
        _toxic_flow_report(chain_ok=False),
    )
    feats = build_features_from_root(tmp_path)
    kinds = {a.kind for a in feats.anomalies}
    assert "audit_chain_break" in kinds
    assert feats.aggregate["audit_chains_ok"] is False


def test_compliance_mar_alert_anomaly(tmp_path: Path) -> None:
    comp = {
        "mar_abuse": {
            "alerts": 3,
            "orders_seen": 20,
            "cancels_seen": 18,
            "fills_seen": 0,
            "last_alerts": [],
        }
    }
    _write_drill_dir(
        tmp_path, "toxic_flow",
        _toxic_flow_report(compliance=comp),
    )
    feats = build_features_from_root(tmp_path)
    kinds = {a.kind for a in feats.anomalies}
    assert "mar_spoofing_alerts" in kinds


def test_compliance_fat_finger_anomaly(tmp_path: Path) -> None:
    comp = {
        "finra_fat_finger": {
            "checked": 1000, "rejected": 4,
            "reject_rate": 0.004,
            "worst_deviation_bps": 275.0,
            "max_deviation_bps": 150.0,
            "symbols_tracked": 3,
        }
    }
    _write_drill_dir(
        tmp_path, "toxic_flow",
        _toxic_flow_report(compliance=comp),
    )
    feats = build_features_from_root(tmp_path)
    kinds = {a.kind for a in feats.anomalies}
    assert "fat_finger_excursion" in kinds


# ---------------------------------------------------------------------
# Digest determinism + archival
# ---------------------------------------------------------------------


def test_template_digest_is_deterministic(tmp_path: Path) -> None:
    _write_drill_dir(
        tmp_path, "toxic_flow",
        _toxic_flow_report(core_p99=25_000.0),
    )
    feats = build_features_from_root(
        tmp_path, window_start="2026-04-21", window_end="2026-04-21",
    )
    a = generate_digest(feats, backend="template")
    b = generate_digest(feats, backend="template")
    assert a.markdown == b.markdown
    assert a.prompt_sha256 == b.prompt_sha256
    assert a.backend == "template"
    assert a.model is None
    assert a.schema == DIGEST_SCHEMA_VERSION
    assert feats.schema == FEATURE_SCHEMA_VERSION


def test_run_nightly_archives_markdown_and_json(tmp_path: Path) -> None:
    artifacts = tmp_path / "out" / "hl"
    _write_drill_dir(artifacts, "toxic_flow", _toxic_flow_report())
    digest_dir = tmp_path / "digests"
    result = run_nightly(
        artifacts_root=artifacts,
        digest_dir=digest_dir,
        run_date="2026-04-21",
        backend="template",
    )
    assert (digest_dir / "2026-04-21.md").exists()
    assert (digest_dir / "2026-04-21.json").exists()
    assert result.date == "2026-04-21"

    listed = list_digests(digest_dir)
    assert len(listed) == 1
    assert listed[0]["date"] == "2026-04-21"
    loaded = load_digest(digest_dir, "2026-04-21")
    assert loaded is not None
    assert loaded["schema"] == DIGEST_SCHEMA_VERSION
    assert loaded["backend"] == "template"


def test_run_nightly_raises_when_no_artifacts(tmp_path: Path) -> None:
    digest_dir = tmp_path / "digests"
    with pytest.raises(RuntimeError):
        run_nightly(
            artifacts_root=tmp_path / "missing",
            digest_dir=digest_dir,
            run_date="2026-04-21",
            backend="template",
        )


def test_digest_markdown_mentions_every_anomaly_kind(tmp_path: Path) -> None:
    # Force a small-intent universe so reject_rate (rejected/intents)
    # crosses the 25% bar.
    report = _toxic_flow_report(
        intents=100,
        rejected=60,
        rejected_toxic=40,
        core_p99=25_000.0,
        chain_ok=False,
        compliance={
            "mar_abuse": {"alerts": 2, "last_alerts": []},
            "finra_fat_finger": {"worst_deviation_bps": 300},
            "mifid_otr": {"would_trip": True, "global_ratio": 420},
        },
    )
    report["throughput"]["rejected_rate"] = 20
    _write_drill_dir(tmp_path, "toxic_flow", report)
    feats = build_features_from_root(
        tmp_path, window_start="2026-04-21", window_end="2026-04-21",
    )
    d = generate_digest(feats, backend="template")
    for kind in (
        "stage_latency_p99",
        "reject_rate_high",
        "toxic_dominant",
        "audit_chain_break",
        "mifid_otr_would_trip",
        "fat_finger_excursion",
        "mar_spoofing_alerts",
    ):
        assert kind in d.markdown, f"digest missing anomaly kind {kind}"
