"""Workstream 5 -- online triage agent.

Glues the streaming detectors (``triage_detectors.py``), an optional
LLM enrichment pass, the BLAKE2b-chained alert sidecar
(``audit/alert_log.py``), and a pluggable pager hook into a single
single-threaded consumer.

Wire model
----------

The production design pulls events from a PCIe DMA descriptor ring
written by the on-chip risk gate / stage timer. In simulation we
read newline-delimited JSON from any iterable / file-like / Unix
pipe -- the ingest function is just ``Iterable[TriageEvent]``.

The agent is HITL: it raises pages, it never re-arms or disarms the
risk gate. That is intentional and matches the Workstream 5 spec in
``docs/ROADMAP.md``.

LLM enrichment
--------------

When ``ANTHROPIC_API_KEY`` is set and the ``anthropic`` package is
installed, each firing is enriched with a one-paragraph plain-English
suggestion using ``claude-haiku-4-5`` (temp 0). When unavailable, a
deterministic template string is used. Enrichment is best-effort --
a network failure never blocks the alert from being persisted.

Runbook lookup
--------------

A small table maps ``(detector, severity)`` -> runbook URL fragment.
The fragment is appended to the alert detail before persistence so
the on-call sees one click away from the right page.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, List, Optional, TextIO

from sentinel_hft.audit.alert_log import (
    AlertChain,
    AlertRecord,
    SEVERITY_ALERT,
    SEVERITY_INFO,
    SEVERITY_WARN,
    severity_from_str,
)
from sentinel_hft.ai.triage_detectors import (
    DetectorEnsemble,
    DetectorFiring,
    TriageEvent,
)


# ---------------------------------------------------------------------
# Runbook table
# ---------------------------------------------------------------------


DEFAULT_RUNBOOK_BASE = "docs/runbooks"


RUNBOOK_PAGES: Dict[str, str] = {
    "latency_zscore": "latency-spike.md",
    "reject_rate_cusum": "reject-rate-drift.md",
    "fill_quality_sprt": "fill-quality-degradation.md",
}


def runbook_url(detector: str, base: str = DEFAULT_RUNBOOK_BASE) -> str:
    page = RUNBOOK_PAGES.get(detector, "general-incident.md")
    return f"{base}/{page}"


# ---------------------------------------------------------------------
# LLM enrichment (best-effort)
# ---------------------------------------------------------------------


_LLM_PROMPT = (
    "You are an SRE on-call assistant for a market-making engine.\n"
    "Given a single triage detector firing in JSON, write ONE short\n"
    "paragraph (max 60 words) suggesting the most likely cause and\n"
    "the first investigation step. Be concrete. Do not invent\n"
    "metrics or numbers that aren't in the input.\n\n"
    "Firing:\n{firing}\n"
)


def _enrich_template(firing: DetectorFiring) -> str:
    if firing.detector == "latency_zscore":
        return (
            f"Latency on stage `{firing.stage}` is {firing.score:.2f}σ above "
            f"baseline. Check for queue back-pressure, host page faults, "
            f"or a misbehaving downstream peer. Runbook step 1: pull the "
            f"last 60 seconds of stage timer histograms."
        )
    if firing.detector == "reject_rate_cusum":
        return (
            f"Reject rate has drifted up (cusum={firing.score:.2f}). "
            f"Check the reject-reason histogram in the latest DORA "
            f"bundle to see which limit is dominating, then verify "
            f"the upstream venue isn't fat-fingering quotes."
        )
    if firing.detector == "fill_quality_sprt":
        return (
            f"Fill quality has degraded (llr={firing.score:.2f}, "
            f"n={firing.window_samples}). Likely adverse selection or "
            f"stale book. Check the toxic-flow detector output and the "
            f"recent venue mid-mark drift."
        )
    return f"{firing.detector} fired (score={firing.score:.2f})."


def _enrich_anthropic(firing: DetectorFiring) -> Optional[str]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic  # type: ignore
    except ImportError:
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key)
        prompt = _LLM_PROMPT.format(firing=json.dumps(firing.to_dict()))
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=200,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
        out = "".join(
            getattr(b, "text", "") for b in msg.content
        ).strip()
        return out or None
    except Exception:                  # noqa: BLE001 -- best-effort
        return None


def enrich(firing: DetectorFiring, *, backend: str = "auto") -> str:
    """Return a one-paragraph operator hint for ``firing``.

    ``backend`` is ``"auto"`` (try anthropic, fall back to template),
    ``"anthropic"`` (anthropic only; falls back to template if the
    call fails), or ``"template"`` (deterministic, no network).
    """
    if backend in ("auto", "anthropic"):
        out = _enrich_anthropic(firing)
        if out is not None:
            return out
    return _enrich_template(firing)


# ---------------------------------------------------------------------
# Pager hooks
# ---------------------------------------------------------------------


# A pager hook is any callable that consumes an AlertRecord. It must
# not block for long -- in tests we use list.append; in production
# this would be a PagerDuty / Opsgenie / Slack webhook.
PagerHook = Callable[[AlertRecord], None]


def stdout_pager(rec: AlertRecord) -> None:
    """Default pager: pretty-print a one-liner to stdout."""
    sys.stdout.write(
        f"[{rec.severity_name.upper():5}] "
        f"detector={rec.detector} stage={rec.stage or '-'} "
        f"score={rec.score:.2f} | {rec.detail}\n"
    )
    sys.stdout.flush()


# ---------------------------------------------------------------------
# Triage agent
# ---------------------------------------------------------------------


@dataclass
class TriageStats:
    events_in: int = 0
    firings: int = 0
    by_detector: Dict[str, int] = field(default_factory=dict)
    by_severity: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "events_in": self.events_in,
            "firings": self.firings,
            "by_detector": dict(self.by_detector),
            "by_severity": dict(self.by_severity),
        }


class TriageAgent:
    """Single-threaded online triage consumer.

    Drives the detector ensemble, persists each firing to the BLAKE2b
    sidecar chain, optionally enriches with an LLM hint, and emits to
    the pager hook. The agent is purely observational -- it never
    closes loops back into the engine.
    """

    def __init__(
        self,
        *,
        alert_log_path: Path,
        ensemble: Optional[DetectorEnsemble] = None,
        pager: Optional[PagerHook] = None,
        backend: str = "auto",
        runbook_base: str = DEFAULT_RUNBOOK_BASE,
    ) -> None:
        self.ensemble = ensemble or DetectorEnsemble()
        self.pager = pager or stdout_pager
        self.backend = backend
        self.runbook_base = runbook_base
        self.stats = TriageStats()
        self._chain = AlertChain.open(Path(alert_log_path))

    # -- core ----------------------------------------------------------

    def observe(self, event: TriageEvent) -> List[AlertRecord]:
        """Process one event. Returns the alerts (if any) it raised."""
        self.stats.events_in += 1
        firings = self.ensemble.observe(event)
        out: List[AlertRecord] = []
        for f in firings:
            rec = self._handle_firing(f)
            out.append(rec)
        return out

    def run(self, events: Iterable[TriageEvent]) -> List[AlertRecord]:
        all_alerts: List[AlertRecord] = []
        for ev in events:
            all_alerts.extend(self.observe(ev))
        return all_alerts

    # -- internals -----------------------------------------------------

    def _handle_firing(self, firing: DetectorFiring) -> AlertRecord:
        hint = enrich(firing, backend=self.backend)
        runbook = runbook_url(firing.detector, base=self.runbook_base)
        detail = f"{firing.detail} | hint: {hint} | runbook: {runbook}"
        sev_code = severity_from_str(firing.severity)
        rec = self._chain.append(
            detector=firing.detector,
            severity=sev_code,
            detail=detail,
            score=firing.score,
            timestamp_ns=firing.timestamp_ns,
            stage=firing.stage,
            window_n=firing.window_samples,
        )
        self.stats.firings += 1
        self.stats.by_detector[firing.detector] = (
            self.stats.by_detector.get(firing.detector, 0) + 1
        )
        sev_name = firing.severity
        self.stats.by_severity[sev_name] = (
            self.stats.by_severity.get(sev_name, 0) + 1
        )
        try:
            self.pager(rec)
        except Exception:                # noqa: BLE001 -- never propagate
            pass
        return rec

    # -- shutdown ------------------------------------------------------

    def close(self) -> None:
        self._chain.close()

    def __enter__(self) -> "TriageAgent":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


# ---------------------------------------------------------------------
# Iterable adapters: JSON-lines pipe / file
# ---------------------------------------------------------------------


def iter_events_from_jsonl(stream: TextIO) -> Iterator[TriageEvent]:
    """Yield ``TriageEvent`` from a newline-delimited JSON stream.

    Each line is a JSON object with at minimum ``kind`` and either
    ``stage``/``value`` (for latency) or ``passed`` (for reject/fill).
    Missing ``timestamp_ns`` defaults to wall-clock time at parse.
    """
    for line in stream:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = obj.get("kind")
        if kind not in ("latency", "reject", "fill"):
            continue
        ts = int(obj.get("timestamp_ns", time.time_ns()))
        yield TriageEvent(
            timestamp_ns=ts,
            kind=kind,
            stage=obj.get("stage"),
            value=float(obj.get("value", 0.0)),
            passed=obj.get("passed"),
            meta=obj.get("meta", {}) or {},
        )


def iter_events_from_path(path: Path) -> Iterator[TriageEvent]:
    """Open a file (or named pipe) and yield triage events from it."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        yield from iter_events_from_jsonl(f)


__all__ = [
    "DEFAULT_RUNBOOK_BASE",
    "RUNBOOK_PAGES",
    "runbook_url",
    "enrich",
    "PagerHook",
    "stdout_pager",
    "TriageStats",
    "TriageAgent",
    "iter_events_from_jsonl",
    "iter_events_from_path",
]
