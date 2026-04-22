"""Workstream 5 -- triage evaluation harness.

Replays a scripted, fully-labelled event stream through the
``TriageAgent`` and scores precision / recall / F1 against the
ground-truth anomaly windows.

Why this exists
---------------

The detectors (``triage_detectors.py``) and the agent
(``triage_stream.py``) are calibrated by hand. To know whether the
defaults are reasonable -- not too jumpy, not too sleepy -- we need
a regression harness that drives a known-mix scenario and counts
hits and misses. This is intentionally pure-Python, no fixtures,
deterministic seed, runs in <1s.

A "true positive" is an alert raised inside (or within
``hit_window_ns`` after) an injected anomaly window for the same
detector family. A "false positive" is an alert outside any
anomaly window. A "false negative" is an injected anomaly window
that never produced an alert from the matching detector.

The report dict returned matches the schema the CLI table expects.
"""

from __future__ import annotations

import math
import random
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sentinel_hft.ai.triage_detectors import (
    DetectorEnsemble,
    FillQualitySPRTDetector,
    LatencyZScoreDetector,
    RejectRateCUSUMDetector,
    TriageEvent,
)
from sentinel_hft.ai.triage_stream import TriageAgent
from sentinel_hft.audit.alert_log import AlertRecord


# Detector -> anomaly family used for matching.
_DET_FAMILY = {
    "latency_zscore": "latency",
    "reject_rate_cusum": "reject",
    "fill_quality_sprt": "fill",
}


@dataclass
class AnomalyWindow:
    """One labelled ground-truth anomaly window."""

    family: str                       # "latency" | "reject" | "fill"
    stage: Optional[str]
    start_ns: int
    end_ns: int


@dataclass
class ScriptedScenario:
    events: List[TriageEvent] = field(default_factory=list)
    anomalies: List[AnomalyWindow] = field(default_factory=list)


# ---------------------------------------------------------------------
# Scenario builder
# ---------------------------------------------------------------------


def build_default_scenario(
    *,
    seed: int = 0,
    n_baseline: int = 200,
    spike_count: int = 3,
    reject_drift_n: int = 200,
    bad_fill_burst_n: int = 50,
) -> ScriptedScenario:
    """Generate a multi-segment scripted stream.

    Layout (timestamps in ns, event index 1ns apart):

        [0 .. n_baseline)             baseline latency on "core"
        [n_baseline .. +spike_count)  one big latency spike per step
        ...                           more baseline
        ... reject baseline (passed=True)
        ... reject drift (50% rejects)
        ... fill baseline (passed=True)
        ... fill burst (passed=False)
    """
    rng = random.Random(seed)
    sc = ScriptedScenario()
    t = 0

    # 1. Latency baseline on "core".
    for _ in range(n_baseline):
        sc.events.append(TriageEvent(
            timestamp_ns=t, kind="latency", stage="core",
            value=1000.0 + rng.gauss(0, 50),
        ))
        t += 1

    # 2. Latency spike anomaly windows.
    for s in range(spike_count):
        spike_start = t
        for _ in range(5):
            sc.events.append(TriageEvent(
                timestamp_ns=t, kind="latency", stage="core",
                value=10_000.0 + rng.gauss(0, 100),
            ))
            t += 1
        # cool-down baseline so detectors can settle between spikes
        for _ in range(120):
            sc.events.append(TriageEvent(
                timestamp_ns=t, kind="latency", stage="core",
                value=1000.0 + rng.gauss(0, 50),
            ))
            t += 1
        sc.anomalies.append(AnomalyWindow(
            family="latency", stage="core",
            start_ns=spike_start, end_ns=t,
        ))

    # 3. Reject baseline (~2% rejects).
    for _ in range(300):
        sc.events.append(TriageEvent(
            timestamp_ns=t, kind="reject",
            passed=(rng.random() > 0.02),
        ))
        t += 1

    # 4. Reject drift -- ~50% rejects.
    drift_start = t
    for _ in range(reject_drift_n):
        sc.events.append(TriageEvent(
            timestamp_ns=t, kind="reject",
            passed=(rng.random() > 0.5),
        ))
        t += 1
    sc.anomalies.append(AnomalyWindow(
        family="reject", stage=None,
        start_ns=drift_start, end_ns=t,
    ))

    # 5. Fill baseline (~5% bad fills).
    for _ in range(300):
        sc.events.append(TriageEvent(
            timestamp_ns=t, kind="fill",
            passed=(rng.random() > 0.05),
        ))
        t += 1

    # 6. Fill burst -- 100% bad fills, well above SPRT alternative.
    burst_start = t
    for _ in range(bad_fill_burst_n):
        sc.events.append(TriageEvent(
            timestamp_ns=t, kind="fill", passed=False,
        ))
        t += 1
    sc.anomalies.append(AnomalyWindow(
        family="fill", stage=None,
        start_ns=burst_start, end_ns=t,
    ))

    return sc


# ---------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------


def _alert_matches(
    rec: AlertRecord, win: AnomalyWindow, hit_window_ns: int
) -> bool:
    fam = _DET_FAMILY.get(rec.detector)
    if fam != win.family:
        return False
    if win.stage is not None and rec.stage != win.stage:
        return False
    return win.start_ns <= rec.timestamp_ns <= (win.end_ns + hit_window_ns)


def score(
    alerts: List[AlertRecord],
    scenario: ScriptedScenario,
    *,
    hit_window_ns: int = 200,
) -> Dict[str, object]:
    """Score the alert list against the scripted scenario."""
    matched_windows = [False] * len(scenario.anomalies)
    matched_alerts = [False] * len(alerts)

    # Greedy-but-symmetric matching: walk alerts, attribute each to
    # the first overlapping anomaly window of the same family.
    for ai, rec in enumerate(alerts):
        for wi, win in enumerate(scenario.anomalies):
            if _alert_matches(rec, win, hit_window_ns):
                matched_alerts[ai] = True
                matched_windows[wi] = True
                # Don't break -- one alert can ratify multiple
                # windows, but we still want to count it once,
                # which matched_alerts handles.
    # Precision is "what fraction of alerts were attributable to a
    # labelled window?" -- per alert. Recall is "what fraction of
    # labelled windows fired at least one alert?" -- per window.
    # That separation is required because a single anomaly window
    # can legitimately produce many alerts (cooldown is finite,
    # episodes are long), and counting those repeats as FPs would
    # be perverse.
    alert_tp = sum(matched_alerts)
    fp = sum(1 for m in matched_alerts if not m)
    window_tp = sum(matched_windows)
    fn = sum(1 for m in matched_windows if not m)
    tp = alert_tp                              # per-alert TPs

    precision = alert_tp / len(alerts) if alerts else 0.0
    recall = window_tp / len(scenario.anomalies) if scenario.anomalies else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) else 0.0
    )

    return {
        "events": len(scenario.events),
        "labelled_anomalies": len(scenario.anomalies),
        "alerts_fired": len(alerts),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "anomaly_windows": [
            {
                "family": w.family,
                "stage": w.stage,
                "start_ns": w.start_ns,
                "end_ns": w.end_ns,
                "matched": bool(matched_windows[i]),
            }
            for i, w in enumerate(scenario.anomalies)
        ],
        "alerts": [
            {
                "detector": a.detector,
                "stage": a.stage,
                "severity": a.severity_name,
                "score": a.score,
                "timestamp_ns": a.timestamp_ns,
                "matched": bool(matched_alerts[i]),
            }
            for i, a in enumerate(alerts)
        ],
    }


# ---------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------


def run_evaluation(
    *,
    scenario: Optional[ScriptedScenario] = None,
    ensemble: Optional[DetectorEnsemble] = None,
    alert_log_path: Optional[Path] = None,
    backend: str = "template",
) -> Dict[str, object]:
    """End-to-end evaluation.

    Builds a scripted scenario (or uses the one passed in), runs it
    through a TriageAgent backed by the given (or default-tuned)
    detector ensemble, and returns a report dict matching the CLI
    table schema.
    """
    sc = scenario or build_default_scenario()
    ens = ensemble or DetectorEnsemble(
        latency=LatencyZScoreDetector(
            z_threshold=4.0, min_samples=30, cooldown_samples=20,
        ),
        reject=RejectRateCUSUMDetector(
            baseline=0.02, slack=0.01, alert_threshold=5.0, window=500,
        ),
        fill=FillQualitySPRTDetector(
            baseline=0.05, k_ratio=4.0,
            accept_upper=4.0, reject_lower=-4.0,
        ),
    )

    # Use a temp sidecar log unless caller supplied a destination.
    cleanup_dir: Optional[tempfile.TemporaryDirectory] = None
    if alert_log_path is None:
        cleanup_dir = tempfile.TemporaryDirectory(prefix="triage-eval-")
        alert_log_path = Path(cleanup_dir.name) / "alerts.alog"

    alerts: List[AlertRecord] = []
    try:
        with TriageAgent(
            alert_log_path=alert_log_path,
            ensemble=ens,
            pager=alerts.append,
            backend=backend,
        ) as agent:
            agent.run(sc.events)
    finally:
        if cleanup_dir is not None:
            cleanup_dir.cleanup()

    return score(alerts, sc)


__all__ = [
    "AnomalyWindow",
    "ScriptedScenario",
    "build_default_scenario",
    "score",
    "run_evaluation",
]
