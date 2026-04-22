"""Workstream 5 -- evaluation harness tests."""

from __future__ import annotations

from pathlib import Path
from typing import List

from sentinel_hft.ai.triage_eval import (
    AnomalyWindow,
    ScriptedScenario,
    build_default_scenario,
    run_evaluation,
    score,
)
from sentinel_hft.ai.triage_detectors import TriageEvent
from sentinel_hft.audit.alert_log import AlertRecord, verify_chain


# ---------------------------------------------------------------------
# Scenario shape
# ---------------------------------------------------------------------


def test_default_scenario_has_three_anomaly_families() -> None:
    sc = build_default_scenario()
    fams = sorted({a.family for a in sc.anomalies})
    assert fams == ["fill", "latency", "reject"]
    assert len(sc.events) > 1000
    assert len(sc.anomalies) >= 3
    # Latency windows must specify the stage they are tagged on.
    lat = [a for a in sc.anomalies if a.family == "latency"]
    assert all(a.stage == "core" for a in lat)


def test_default_scenario_is_seed_deterministic() -> None:
    a = build_default_scenario(seed=7)
    b = build_default_scenario(seed=7)
    assert len(a.events) == len(b.events)
    for x, y in zip(a.events, b.events):
        assert x.kind == y.kind
        assert x.value == y.value
        assert x.passed == y.passed


# ---------------------------------------------------------------------
# Score function unit tests
# ---------------------------------------------------------------------


def _alert(detector: str, ts: int, stage=None) -> AlertRecord:
    return AlertRecord(
        seq_no=0, timestamp_ns=ts, severity=1,
        detector=detector, stage=stage, detail="x", score=0.0,
    )


def test_score_clean_match() -> None:
    sc = ScriptedScenario(
        events=[],
        anomalies=[
            AnomalyWindow(family="latency", stage="core",
                          start_ns=100, end_ns=200),
        ],
    )
    alerts = [_alert("latency_zscore", ts=150, stage="core")]
    r = score(alerts, sc)
    assert r["true_positives"] == 1
    assert r["false_positives"] == 0
    assert r["false_negatives"] == 0
    assert r["precision"] == 1.0
    assert r["recall"] == 1.0
    assert r["f1"] == 1.0


def test_score_false_positive_outside_window() -> None:
    sc = ScriptedScenario(
        events=[],
        anomalies=[
            AnomalyWindow(family="latency", stage="core",
                          start_ns=100, end_ns=200),
        ],
    )
    alerts = [
        _alert("latency_zscore", ts=150, stage="core"),    # match
        _alert("latency_zscore", ts=10_000, stage="core"), # FP
    ]
    r = score(alerts, sc)
    assert r["true_positives"] == 1
    assert r["false_positives"] == 1
    assert r["false_negatives"] == 0
    assert r["precision"] == 0.5
    assert r["recall"] == 1.0


def test_score_false_negative_unmatched_window() -> None:
    sc = ScriptedScenario(
        events=[],
        anomalies=[
            AnomalyWindow(family="reject", stage=None,
                          start_ns=100, end_ns=200),
        ],
    )
    r = score([], sc)
    assert r["true_positives"] == 0
    assert r["false_positives"] == 0
    assert r["false_negatives"] == 1
    assert r["precision"] == 0.0
    assert r["recall"] == 0.0


def test_score_wrong_family_does_not_match() -> None:
    sc = ScriptedScenario(
        events=[],
        anomalies=[
            AnomalyWindow(family="reject", stage=None,
                          start_ns=100, end_ns=200),
        ],
    )
    alerts = [_alert("latency_zscore", ts=150, stage="core")]
    r = score(alerts, sc)
    assert r["true_positives"] == 0
    assert r["false_positives"] == 1
    assert r["false_negatives"] == 1


def test_score_wrong_stage_does_not_match() -> None:
    sc = ScriptedScenario(
        events=[],
        anomalies=[
            AnomalyWindow(family="latency", stage="core",
                          start_ns=100, end_ns=200),
        ],
    )
    alerts = [_alert("latency_zscore", ts=150, stage="risk")]
    r = score(alerts, sc)
    assert r["true_positives"] == 0
    assert r["false_positives"] == 1
    assert r["false_negatives"] == 1


def test_score_hit_window_grace() -> None:
    sc = ScriptedScenario(
        events=[],
        anomalies=[
            AnomalyWindow(family="fill", stage=None,
                          start_ns=100, end_ns=200),
        ],
    )
    # Alert lands 150 ns after window end. With default 200 ns grace
    # this still counts.
    alerts = [_alert("fill_quality_sprt", ts=350)]
    r = score(alerts, sc, hit_window_ns=200)
    assert r["true_positives"] == 1
    # And without the grace it doesn't.
    r2 = score(alerts, sc, hit_window_ns=0)
    assert r2["true_positives"] == 0


# ---------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------


def test_run_evaluation_default_scenario_meets_quality_bar() -> None:
    r = run_evaluation()
    # Sanity counts.
    assert r["events"] > 1000
    assert r["labelled_anomalies"] >= 3
    assert r["alerts_fired"] >= r["labelled_anomalies"]
    # Quality bar -- the default detector tunings must catch every
    # planted anomaly window and keep precision high. Numbers must
    # not regress silently.
    assert r["recall"] == 1.0
    assert r["precision"] >= 0.70
    assert r["f1"] >= 0.80


def test_run_evaluation_persists_alert_chain(tmp_path: Path) -> None:
    log = tmp_path / "alerts.alog"
    r = run_evaluation(alert_log_path=log)
    assert log.exists()
    res = verify_chain(log)
    assert res.chain_ok is True
    assert res.n_records == r["alerts_fired"]


def test_run_evaluation_is_deterministic() -> None:
    r1 = run_evaluation()
    r2 = run_evaluation()
    for k in ("events", "labelled_anomalies", "alerts_fired",
              "true_positives", "false_positives", "false_negatives",
              "precision", "recall", "f1"):
        assert r1[k] == r2[k], f"non-deterministic key: {k}"
