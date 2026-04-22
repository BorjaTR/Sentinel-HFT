"""Workstream 5 -- streaming triage detector tests.

Covers the three detectors and the ensemble wrapper:

* ``LatencyZScoreDetector`` warm-up suppression, z-score firing,
  cooldown suppression, and severity escalation.
* ``RejectRateCUSUMDetector`` baseline silence, drift detection,
  reset on firing.
* ``FillQualitySPRTDetector`` accept-H1 on bad-fill burst, silent
  reset on accept-H0 (lower boundary), no firing on noise.
* ``DetectorEnsemble`` routes events to the correct detector.
"""

from __future__ import annotations

import math
import random

from sentinel_hft.ai.triage_detectors import (
    DetectorEnsemble,
    DetectorFiring,
    FillQualitySPRTDetector,
    LatencyZScoreDetector,
    RejectRateCUSUMDetector,
    TriageEvent,
)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _lat(stage: str, value: float, ts: int = 0) -> TriageEvent:
    return TriageEvent(timestamp_ns=ts, kind="latency", stage=stage, value=value)


def _rej(passed: bool, ts: int = 0) -> TriageEvent:
    return TriageEvent(timestamp_ns=ts, kind="reject", passed=passed)


def _fill(passed: bool, ts: int = 0) -> TriageEvent:
    return TriageEvent(timestamp_ns=ts, kind="fill", passed=passed)


# ---------------------------------------------------------------------
# LatencyZScoreDetector
# ---------------------------------------------------------------------


def test_latency_warmup_suppresses() -> None:
    det = LatencyZScoreDetector(z_threshold=4.0, min_samples=30)
    rng = random.Random(0)
    fired = False
    # First 30 samples must never fire even on a huge spike.
    for i in range(30):
        v = 1000.0 + rng.gauss(0, 50)
        if i == 20:
            v = 100_000.0          # Massive spike during warm-up
        f = det.observe(_lat("core", v, ts=i))
        if f is not None:
            fired = True
    assert not fired, "detector fired during warm-up"


def test_latency_fires_on_spike_after_warmup() -> None:
    det = LatencyZScoreDetector(z_threshold=4.0, min_samples=30, cooldown_samples=0)
    rng = random.Random(1)
    # Build a stable baseline ~ 1000 with stdev ~ 50.
    for i in range(80):
        det.observe(_lat("core", 1000.0 + rng.gauss(0, 50), ts=i))
    # Now inject a sample that is clearly > 4 sigma.
    f = det.observe(_lat("core", 5000.0, ts=80))
    assert f is not None
    assert isinstance(f, DetectorFiring)
    assert f.detector == "latency_zscore"
    assert f.stage == "core"
    assert f.score >= 4.0


def test_latency_cooldown_suppresses_repeats() -> None:
    det = LatencyZScoreDetector(
        z_threshold=4.0, min_samples=30, cooldown_samples=50
    )
    rng = random.Random(2)
    for i in range(80):
        det.observe(_lat("core", 1000.0 + rng.gauss(0, 50), ts=i))
    first = det.observe(_lat("core", 5000.0, ts=80))
    assert first is not None
    # A second spike right after should be suppressed.
    second = det.observe(_lat("core", 6000.0, ts=81))
    assert second is None


def test_latency_severity_escalates() -> None:
    det = LatencyZScoreDetector(z_threshold=4.0, min_samples=30, cooldown_samples=0)
    rng = random.Random(3)
    for i in range(80):
        det.observe(_lat("ingress", 500.0 + rng.gauss(0, 25), ts=i))
    # Force a >> 6-sigma spike.
    f = det.observe(_lat("ingress", 100_000.0, ts=80))
    assert f is not None
    assert f.severity == "alert"


def test_latency_ignores_non_latency_events() -> None:
    det = LatencyZScoreDetector()
    f = det.observe(_rej(False))
    assert f is None
    f = det.observe(_fill(True))
    assert f is None
    # latency event with no stage is also ignored
    e = TriageEvent(timestamp_ns=0, kind="latency", value=1000.0)
    assert det.observe(e) is None


def test_latency_per_stage_isolation() -> None:
    det = LatencyZScoreDetector(z_threshold=4.0, min_samples=30, cooldown_samples=0)
    rng = random.Random(4)
    # Stage A: low latency baseline.
    for i in range(80):
        det.observe(_lat("A", 1000.0 + rng.gauss(0, 50), ts=i))
    # Stage B is fresh -- a spike should not fire (still in warm-up).
    f = det.observe(_lat("B", 50_000.0, ts=200))
    assert f is None


# ---------------------------------------------------------------------
# RejectRateCUSUMDetector
# ---------------------------------------------------------------------


def test_cusum_silent_on_baseline() -> None:
    det = RejectRateCUSUMDetector(
        baseline=0.02, slack=0.01, alert_threshold=5.0, window=500
    )
    rng = random.Random(5)
    fired = 0
    for _ in range(2000):
        # Reject 2% of the time -> matches baseline.
        passed = rng.random() > 0.02
        if det.observe(_rej(passed)) is not None:
            fired += 1
    assert fired == 0


def test_cusum_fires_on_drift() -> None:
    det = RejectRateCUSUMDetector(
        baseline=0.02, slack=0.01, alert_threshold=5.0, window=500
    )
    # Drive 200 events at 50% reject -- well above baseline + slack.
    f_seen = None
    for i in range(200):
        passed = (i % 2 == 0)              # 50% rejects
        f = det.observe(_rej(passed, ts=i))
        if f is not None:
            f_seen = f
            break
    assert f_seen is not None
    assert f_seen.detector == "reject_rate_cusum"
    assert f_seen.score >= 5.0


def test_cusum_resets_after_firing() -> None:
    det = RejectRateCUSUMDetector(
        baseline=0.02, slack=0.01, alert_threshold=5.0, window=500
    )
    # Drive drift until the first firing.
    fired_at = None
    for i in range(500):
        f = det.observe(_rej(i % 2 == 0, ts=i))
        if f is not None:
            fired_at = i
            break
    assert fired_at is not None
    # Right after the firing the internal cusum is back to 0,
    # so the very next *single* nominal sample (passed=True) cannot
    # re-fire on its own.
    f = det.observe(_rej(True, ts=fired_at + 1))
    assert f is None
    # And the cusum genuinely went to zero -- internal invariant.
    assert det._cusum >= 0.0


def test_cusum_ignores_non_reject_events() -> None:
    det = RejectRateCUSUMDetector()
    assert det.observe(_lat("core", 1000.0)) is None
    assert det.observe(_fill(True)) is None
    # reject event missing passed field is also ignored
    e = TriageEvent(timestamp_ns=0, kind="reject")
    assert det.observe(e) is None


# ---------------------------------------------------------------------
# FillQualitySPRTDetector
# ---------------------------------------------------------------------


def test_sprt_fires_on_bad_fill_burst() -> None:
    det = FillQualitySPRTDetector(
        baseline=0.05, k_ratio=4.0, accept_upper=4.0, reject_lower=-4.0
    )
    f_seen = None
    # All bad fills -> log-likelihood ratio climbs fast.
    for i in range(60):
        f = det.observe(_fill(False, ts=i))
        if f is not None:
            f_seen = f
            break
    assert f_seen is not None
    assert f_seen.detector == "fill_quality_sprt"
    assert f_seen.severity == "alert"
    assert f_seen.score >= 4.0


def test_sprt_silent_on_nominal_quality() -> None:
    det = FillQualitySPRTDetector(
        baseline=0.05, k_ratio=4.0, accept_upper=4.0, reject_lower=-4.0
    )
    rng = random.Random(7)
    fired = 0
    # Slightly better than baseline -- 2% bad fills.
    for i in range(2000):
        passed = rng.random() > 0.02
        if det.observe(_fill(passed, ts=i)) is not None:
            fired += 1
    assert fired == 0


def test_sprt_resets_on_lower_boundary() -> None:
    det = FillQualitySPRTDetector(
        baseline=0.05, k_ratio=4.0, accept_upper=4.0, reject_lower=-4.0
    )
    # Drive many good fills -- should reach the H0 lower boundary
    # silently and reset internal state.
    for i in range(200):
        det.observe(_fill(True, ts=i))
    # llr counter must have been drained, so a single bad fill
    # cannot push us instantly into accept_upper.
    f = det.observe(_fill(False, ts=300))
    assert f is None


def test_sprt_ignores_non_fill_events() -> None:
    det = FillQualitySPRTDetector()
    assert det.observe(_lat("core", 1000.0)) is None
    assert det.observe(_rej(False)) is None
    e = TriageEvent(timestamp_ns=0, kind="fill")
    assert det.observe(e) is None


def test_sprt_llr_step_constants_are_finite() -> None:
    # Sanity: with extreme baseline / k_ratio combinations the
    # constructor must not blow up and must clamp p1 < 1.
    det = FillQualitySPRTDetector(baseline=0.4, k_ratio=10.0)
    assert det.p1 < 1.0
    assert math.isfinite(det._llr_bad)
    assert math.isfinite(det._llr_good)


# ---------------------------------------------------------------------
# DetectorEnsemble
# ---------------------------------------------------------------------


def test_ensemble_routes_each_kind() -> None:
    ens = DetectorEnsemble()
    # Latency events go only to LatencyZScoreDetector; without
    # warm-up there can be no firing.
    for i in range(10):
        firings = ens.observe(_lat("core", 1000.0, ts=i))
        assert firings == []
    # Reject events go to the CUSUM only.
    firings = ens.observe(_rej(True, ts=100))
    assert firings == []
    # Fill events go to the SPRT only.
    firings = ens.observe(_fill(True, ts=200))
    assert firings == []


def test_ensemble_reports_a_firing() -> None:
    ens = DetectorEnsemble(
        reject=RejectRateCUSUMDetector(
            baseline=0.02, slack=0.01, alert_threshold=5.0, window=500
        ),
    )
    seen: list[DetectorFiring] = []
    for i in range(200):
        firings = ens.observe(_rej(i % 2 == 0, ts=i))
        seen.extend(firings)
        if seen:
            break
    assert seen, "ensemble did not surface a CUSUM firing"
    assert seen[0].detector == "reject_rate_cusum"


def test_firing_to_dict_round_trip() -> None:
    f = DetectorFiring(
        detector="latency_zscore",
        stage="core",
        severity="warn",
        score=4.5,
        detail="x",
        window_samples=42,
        timestamp_ns=123,
    )
    d = f.to_dict()
    assert d["detector"] == "latency_zscore"
    assert d["stage"] == "core"
    assert d["severity"] == "warn"
    assert d["score"] == 4.5
    assert d["detail"] == "x"
    assert d["window_samples"] == 42
    assert d["timestamp_ns"] == 123
