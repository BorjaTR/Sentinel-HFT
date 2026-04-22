"""Workstream 5 -- triage agent integration tests.

End-to-end on a synthetic event stream: drives detectors, persists
alerts to the BLAKE2b-chained sidecar, fires the pager hook, and
verifies the chain cryptographically.
"""

from __future__ import annotations

import io
import json
import random
from pathlib import Path
from typing import List

from sentinel_hft.ai.triage_stream import (
    TriageAgent,
    enrich,
    iter_events_from_jsonl,
    iter_events_from_path,
    runbook_url,
    stdout_pager,
)
from sentinel_hft.ai.triage_detectors import (
    DetectorEnsemble,
    DetectorFiring,
    LatencyZScoreDetector,
    RejectRateCUSUMDetector,
    TriageEvent,
)
from sentinel_hft.audit.alert_log import (
    AlertRecord,
    read_alerts,
    verify_chain,
)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _baseline_latency(stage: str, n: int, seed: int = 0):
    rng = random.Random(seed)
    for i in range(n):
        yield TriageEvent(
            timestamp_ns=i,
            kind="latency",
            stage=stage,
            value=1000.0 + rng.gauss(0, 50),
        )


# ---------------------------------------------------------------------
# enrich() / runbook_url()
# ---------------------------------------------------------------------


def test_runbook_url_known_detector() -> None:
    assert runbook_url("latency_zscore").endswith("latency-spike.md")
    assert runbook_url("reject_rate_cusum").endswith("reject-rate-drift.md")
    assert runbook_url("fill_quality_sprt").endswith(
        "fill-quality-degradation.md"
    )


def test_runbook_url_unknown_falls_back() -> None:
    assert runbook_url("made_up").endswith("general-incident.md")


def test_enrich_template_is_deterministic_per_detector() -> None:
    f = DetectorFiring(
        detector="latency_zscore", stage="core", severity="warn",
        score=4.5, detail="x", window_samples=80, timestamp_ns=0,
    )
    a = enrich(f, backend="template")
    b = enrich(f, backend="template")
    assert a == b
    assert "core" in a
    assert "σ" in a


# ---------------------------------------------------------------------
# Agent end-to-end
# ---------------------------------------------------------------------


def test_agent_persists_a_latency_alert(tmp_path: Path) -> None:
    log = tmp_path / "alerts.alog"
    pager_seen: List[AlertRecord] = []
    ensemble = DetectorEnsemble(
        latency=LatencyZScoreDetector(
            z_threshold=4.0, min_samples=30, cooldown_samples=0,
        ),
    )
    with TriageAgent(
        alert_log_path=log,
        ensemble=ensemble,
        pager=pager_seen.append,
        backend="template",
    ) as agent:
        # Build a stable baseline.
        for ev in _baseline_latency("core", n=80):
            agent.observe(ev)
        # Inject a clean spike.
        spike = TriageEvent(
            timestamp_ns=10_000, kind="latency", stage="core", value=5000.0
        )
        alerts = agent.observe(spike)

    assert len(alerts) == 1
    assert alerts[0].detector == "latency_zscore"
    assert alerts[0].stage == "core"
    assert alerts[0].severity_name in ("warn", "alert")
    assert "runbook:" in alerts[0].detail
    assert "hint:" in alerts[0].detail
    assert pager_seen == alerts

    # Sidecar chain verifies cryptographically.
    res = verify_chain(log)
    assert res.chain_ok is True
    assert res.n_records == 1


def test_agent_handles_reject_drift(tmp_path: Path) -> None:
    log = tmp_path / "alerts.alog"
    ensemble = DetectorEnsemble(
        reject=RejectRateCUSUMDetector(
            baseline=0.02, slack=0.01, alert_threshold=5.0, window=500,
        ),
    )
    pager_seen: List[AlertRecord] = []
    with TriageAgent(
        alert_log_path=log,
        ensemble=ensemble,
        pager=pager_seen.append,
        backend="template",
    ) as agent:
        for i in range(300):
            agent.observe(TriageEvent(
                timestamp_ns=i,
                kind="reject",
                passed=(i % 2 == 0),     # 50% rejects -> drift
            ))
    assert len(pager_seen) >= 1
    assert pager_seen[0].detector == "reject_rate_cusum"
    res = verify_chain(log)
    assert res.chain_ok is True


def test_agent_records_stats(tmp_path: Path) -> None:
    log = tmp_path / "alerts.alog"
    ensemble = DetectorEnsemble(
        latency=LatencyZScoreDetector(
            z_threshold=4.0, min_samples=30, cooldown_samples=0,
        ),
    )
    with TriageAgent(
        alert_log_path=log, ensemble=ensemble, pager=lambda _r: None,
        backend="template",
    ) as agent:
        events = list(_baseline_latency("core", n=80))
        events.append(TriageEvent(
            timestamp_ns=999, kind="latency", stage="core", value=8000.0,
        ))
        agent.run(events)

    s = agent.stats.to_dict()
    assert s["events_in"] == len(events)
    assert s["firings"] >= 1
    assert "latency_zscore" in s["by_detector"]


def test_agent_pager_failure_does_not_propagate(tmp_path: Path) -> None:
    log = tmp_path / "alerts.alog"

    def boom(_r: AlertRecord) -> None:
        raise RuntimeError("pager exploded")

    ensemble = DetectorEnsemble(
        latency=LatencyZScoreDetector(
            z_threshold=4.0, min_samples=30, cooldown_samples=0,
        ),
    )
    with TriageAgent(
        alert_log_path=log, ensemble=ensemble, pager=boom,
        backend="template",
    ) as agent:
        for ev in _baseline_latency("core", n=80):
            agent.observe(ev)
        # Spike. Pager will raise, but the alert must still land.
        agent.observe(TriageEvent(
            timestamp_ns=10_000, kind="latency", stage="core", value=8000.0,
        ))
    res = verify_chain(log)
    assert res.chain_ok is True
    assert res.n_records >= 1


# ---------------------------------------------------------------------
# JSON-lines ingest
# ---------------------------------------------------------------------


def test_iter_events_from_jsonl_parses_three_kinds() -> None:
    blob = "\n".join([
        json.dumps({"kind": "latency", "stage": "core", "value": 1234,
                    "timestamp_ns": 1}),
        json.dumps({"kind": "reject", "passed": False, "timestamp_ns": 2}),
        json.dumps({"kind": "fill",   "passed": True,  "timestamp_ns": 3}),
        "",                                     # blank line
        "not json at all",                       # garbage line, skipped
        json.dumps({"kind": "unknown", "value": 0}),  # skipped
    ])
    events = list(iter_events_from_jsonl(io.StringIO(blob)))
    assert len(events) == 3
    assert events[0].kind == "latency"
    assert events[0].stage == "core"
    assert events[1].kind == "reject"
    assert events[1].passed is False
    assert events[2].kind == "fill"
    assert events[2].passed is True


def test_iter_events_from_path(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    p.write_text(
        json.dumps({"kind": "latency", "stage": "ingress",
                    "value": 700, "timestamp_ns": 1}) + "\n"
    )
    events = list(iter_events_from_path(p))
    assert len(events) == 1
    assert events[0].stage == "ingress"


# ---------------------------------------------------------------------
# Stdout pager smoke test
# ---------------------------------------------------------------------


def test_stdout_pager_smoke(capsys) -> None:
    rec = AlertRecord(
        seq_no=0, timestamp_ns=1, severity=2,
        detector="latency_zscore", stage="core",
        detail="x", score=4.5,
    )
    stdout_pager(rec)
    out = capsys.readouterr().out
    assert "ALERT" in out
    assert "latency_zscore" in out
    assert "core" in out
