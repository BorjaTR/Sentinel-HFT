"""Streaming windowed detectors for Workstream 5 online triage.

Three detector classes, each implementing the same minimal contract:

* ``observe(event) -> Optional[DetectorFiring]``

An event is a ``TriageEvent`` dataclass carrying latency / reject /
fill-quality measurements tagged to a stage. The detector owns its
own rolling window, so the caller can feed events from any stream
(PCIe descriptor ring in production, Unix pipe or queue in sim).

The three detectors mirror the ones used in the Volat project's
``live_bot/circuit_breaker.py``:

* ``LatencyZScoreDetector`` -- per-stage Welford mean/stdev; fires
  when a new sample exceeds ``z_threshold`` sigmas.
* ``RejectRateCUSUMDetector`` -- two-sided CUSUM over a windowed
  reject-count stream; fires on a drift up from baseline.
* ``FillQualitySPRTDetector`` -- Wald sequential ratio test on a
  binary "fill-at-expected-price" stream; fires when the
  log-likelihood ratio breaches ``accept_upper`` against baseline.

All three are pure-Python stdlib. No numpy. Meant to run inside a
single-threaded consumer loop; the caller serialises.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple
from collections import deque


# ---------------------------------------------------------------------
# Event + firing types
# ---------------------------------------------------------------------


@dataclass
class TriageEvent:
    """One record consumed by the triage stream.

    Canonical fields only -- the production ingest adapter is
    expected to translate native trace records into this shape.
    ``kind`` disambiguates which detector should look at the event.
    """

    timestamp_ns: int
    kind: str                 # "latency" | "reject" | "fill"
    stage: Optional[str] = None       # only meaningful for "latency"
    value: float = 0.0                # latency_ns / reject_count / slippage_bps
    passed: Optional[bool] = None     # only meaningful for "reject" & "fill"
    meta: Dict[str, object] = field(default_factory=dict)


@dataclass
class DetectorFiring:
    """Emitted by a detector on a threshold breach."""

    detector: str
    stage: Optional[str]
    severity: str                    # "warn" | "alert"
    score: float                     # z / CUSUM / log-likelihood ratio
    detail: str
    window_samples: int
    timestamp_ns: int

    def to_dict(self) -> Dict[str, object]:
        return {
            "detector": self.detector,
            "stage": self.stage,
            "severity": self.severity,
            "score": self.score,
            "detail": self.detail,
            "window_samples": self.window_samples,
            "timestamp_ns": self.timestamp_ns,
        }


# ---------------------------------------------------------------------
# Welford online mean + variance (one accumulator per stage)
# ---------------------------------------------------------------------


class _Welford:
    __slots__ = ("n", "mean", "m2")

    def __init__(self) -> None:
        self.n = 0
        self.mean = 0.0
        self.m2 = 0.0

    def update(self, x: float) -> None:
        self.n += 1
        delta = x - self.mean
        self.mean += delta / self.n
        delta2 = x - self.mean
        self.m2 += delta * delta2

    @property
    def variance(self) -> float:
        return (self.m2 / (self.n - 1)) if self.n > 1 else 0.0

    @property
    def stdev(self) -> float:
        return math.sqrt(self.variance)


# ---------------------------------------------------------------------
# Latency z-score detector (per stage)
# ---------------------------------------------------------------------


class LatencyZScoreDetector:
    """Per-stage online z-score over latency samples.

    Uses a warm-up of ``min_samples`` before firing. A firing carries
    the stage name, the observed value, and the z-score. Subsequent
    breaches within ``cooldown_samples`` on the same stage are
    suppressed (so a persistent drift produces one alert, not 2000)."""

    def __init__(
        self,
        *,
        z_threshold: float = 4.0,
        min_samples: int = 30,
        cooldown_samples: int = 50,
    ) -> None:
        self.z_threshold = z_threshold
        self.min_samples = min_samples
        self.cooldown_samples = cooldown_samples
        self._acc: Dict[str, _Welford] = {}
        self._last_fire_n: Dict[str, int] = {}

    def observe(self, event: TriageEvent) -> Optional[DetectorFiring]:
        if event.kind != "latency" or event.stage is None:
            return None
        w = self._acc.setdefault(event.stage, _Welford())
        n_before = w.n
        mean_before = w.mean
        stdev_before = w.stdev
        w.update(event.value)

        # Warm-up: keep collecting, never fire.
        if n_before < self.min_samples or stdev_before <= 0.0:
            return None
        z = (event.value - mean_before) / stdev_before
        if z < self.z_threshold:
            return None
        # Cooldown
        last = self._last_fire_n.get(event.stage, -10**9)
        if n_before - last < self.cooldown_samples:
            return None
        self._last_fire_n[event.stage] = n_before

        severity = "alert" if z >= self.z_threshold + 2.0 else "warn"
        return DetectorFiring(
            detector="latency_zscore",
            stage=event.stage,
            severity=severity,
            score=z,
            detail=(
                f"stage={event.stage} latency={event.value:.0f}ns "
                f"mean={mean_before:.0f}ns stdev={stdev_before:.0f}ns z={z:.2f}"
            ),
            window_samples=n_before,
            timestamp_ns=event.timestamp_ns,
        )


# ---------------------------------------------------------------------
# CUSUM on reject rate (count-stream)
# ---------------------------------------------------------------------


class RejectRateCUSUMDetector:
    """One-sided CUSUM for a drift up in reject rate.

    Accepts binary reject events (``event.passed is False`` means a
    reject was observed). Maintains a rolling fraction as baseline
    and a CUSUM that flags a sustained upward deviation.
    """

    def __init__(
        self,
        *,
        baseline: float = 0.02,
        slack: float = 0.01,
        alert_threshold: float = 5.0,
        window: int = 500,
    ) -> None:
        self.baseline = baseline
        self.slack = slack
        self.alert_threshold = alert_threshold
        self.window = window
        self._buf: Deque[int] = deque(maxlen=window)
        self._cusum = 0.0

    def observe(self, event: TriageEvent) -> Optional[DetectorFiring]:
        if event.kind != "reject" or event.passed is None:
            return None
        flag = 0 if event.passed else 1
        self._buf.append(flag)

        # CUSUM update. Under the reference baseline we subtract
        # (baseline + slack); any sustained excess feeds the positive
        # one-sided CUSUM.
        self._cusum = max(0.0, self._cusum + (flag - (self.baseline + self.slack)))

        if self._cusum < self.alert_threshold or len(self._buf) < 50:
            return None

        # Snapshot + reset the accumulator so we don't re-fire every
        # step on a persistent drift.
        score = self._cusum
        self._cusum = 0.0
        observed = sum(self._buf) / len(self._buf)
        severity = "alert" if observed > 3 * self.baseline else "warn"
        return DetectorFiring(
            detector="reject_rate_cusum",
            stage=None,
            severity=severity,
            score=score,
            detail=(
                f"reject_rate={observed:.2%} baseline={self.baseline:.2%} "
                f"cusum={score:.2f}"
            ),
            window_samples=len(self._buf),
            timestamp_ns=event.timestamp_ns,
        )


# ---------------------------------------------------------------------
# SPRT on fill-quality (binary good/bad per fill)
# ---------------------------------------------------------------------


class FillQualitySPRTDetector:
    """Wald Sequential Probability Ratio Test over fill-quality.

    Each fill event carries ``event.passed`` (``True`` = quality
    within target, ``False`` = slippage over ``slippage_bps_warn``).
    The detector tests:

        H0: fill-bad-rate <= baseline
        H1: fill-bad-rate >= baseline * k_ratio

    The log-likelihood ratio breaches ``accept_upper`` when H1 wins.
    On breach we fire and reset the accumulator.
    """

    def __init__(
        self,
        *,
        baseline: float = 0.05,
        k_ratio: float = 3.0,
        accept_upper: float = 4.0,   # ln(A), A ~ 50
        reject_lower: float = -4.0,  # ln(B), B ~ 1/50
    ) -> None:
        assert 0.0 < baseline < 1.0
        assert k_ratio > 1.0
        self.p0 = baseline
        self.p1 = min(0.99, baseline * k_ratio)
        self.accept_upper = accept_upper
        self.reject_lower = reject_lower
        # Precompute log-likelihood-ratio step coefficients.
        self._llr_bad = math.log(self.p1 / self.p0)
        self._llr_good = math.log((1 - self.p1) / (1 - self.p0))
        self._llr = 0.0
        self._seen = 0

    def observe(self, event: TriageEvent) -> Optional[DetectorFiring]:
        if event.kind != "fill" or event.passed is None:
            return None
        # bad-fill = passed is False
        step = self._llr_bad if (event.passed is False) else self._llr_good
        self._llr += step
        self._seen += 1

        if self._llr >= self.accept_upper and self._seen >= 20:
            score = self._llr
            detail = (
                f"SPRT accepts H1: bad-fill-rate >> {self.p0:.0%} "
                f"(llr={score:.2f}, samples={self._seen})"
            )
            self._reset()
            return DetectorFiring(
                detector="fill_quality_sprt",
                stage=None,
                severity="alert",
                score=score,
                detail=detail,
                window_samples=self._seen,
                timestamp_ns=event.timestamp_ns,
            )
        if self._llr <= self.reject_lower:
            # Quality is nominal -- silently drain state so we can
            # catch the next excursion fresh.
            self._reset()
        return None

    def _reset(self) -> None:
        self._llr = 0.0
        self._seen = 0


# ---------------------------------------------------------------------
# Detector ensemble
# ---------------------------------------------------------------------


class DetectorEnsemble:
    """Convenience wrapper running all three detectors on one stream."""

    def __init__(
        self,
        *,
        latency: Optional[LatencyZScoreDetector] = None,
        reject: Optional[RejectRateCUSUMDetector] = None,
        fill: Optional[FillQualitySPRTDetector] = None,
    ) -> None:
        self.latency = latency or LatencyZScoreDetector()
        self.reject = reject or RejectRateCUSUMDetector()
        self.fill = fill or FillQualitySPRTDetector()

    def observe(self, event: TriageEvent) -> List[DetectorFiring]:
        firings: List[DetectorFiring] = []
        for d in (self.latency, self.reject, self.fill):
            f = d.observe(event)
            if f is not None:
                firings.append(f)
        return firings


__all__ = [
    "TriageEvent",
    "DetectorFiring",
    "LatencyZScoreDetector",
    "RejectRateCUSUMDetector",
    "FillQualitySPRTDetector",
    "DetectorEnsemble",
]
