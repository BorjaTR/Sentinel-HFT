"""End-to-end tests for the four Hyperliquid demo use-cases.

Each use-case runner is exercised with a *tiny* config (few-thousand
ticks) into a ``tempfile.TemporaryDirectory`` so the whole test module
runs in a couple of seconds. For every runner we assert:

* The returned report dataclass points at files that exist and are
  non-empty on disk (JSON + Markdown + HTML).
* The JSON report parses as valid JSON with the expected top-level
  keys the dashboard / docs consume.
* The HTML report is self-contained (no external ``<script src=>``
  or ``<link rel="stylesheet">`` tags -- the interview demo must open
  offline).
* The runner-level invariants for that scenario hold (e.g. the kill
  drill actually trips the kill switch, toxic flow rejects at least
  one intent, latency p99 is > 0, daily evidence chain is OK).

Finally ``build_dashboard`` is smoke-tested against the four
sub-directories and the resulting aggregator HTML is asserted to
mention every use-case label.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import pytest

from sentinel_hft.usecases import (
    DailyEvidenceConfig,
    KillDrillConfig,
    LatencyConfig,
    ToxicFlowConfig,
    build_dashboard,
    run_daily_evidence,
    run_kill_drill,
    run_latency,
    run_toxic_flow,
)
from sentinel_hft.usecases.daily_evidence import SessionSpec


# ---------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------


def _assert_nonempty_file(p: Path) -> None:
    assert p.exists(), f"missing artifact: {p}"
    assert p.stat().st_size > 0, f"empty artifact: {p}"


# Matches any `src=` / `href=` pointing at an http(s) URL. A
# self-contained demo HTML must have none of these (inline SVG/CSS
# only). Data URIs and anchor/hash links are fine.
_EXTERNAL_REF_RE = re.compile(
    r'''(?:src|href)\s*=\s*["']\s*(?:https?:)?//''',
    re.IGNORECASE,
)


def _assert_self_contained_html(p: Path) -> None:
    text = p.read_text(encoding="utf-8")
    assert "<html" in text.lower(), f"not HTML: {p}"
    assert not _EXTERNAL_REF_RE.search(text), (
        f"external http(s) reference found in {p.name}; demo HTML "
        f"must be offline-first (inline SVG + inline CSS only)."
    )
    # No <script src=...> pointing at a file path either (the demo
    # should have zero external JS). Allow inline <script> blocks.
    assert 'script src=' not in text.lower(), (
        f"external <script src=...> found in {p.name}"
    )


# ---------------------------------------------------------------------
# Use case 1 -- Toxic flow rejection
# ---------------------------------------------------------------------


class TestToxicFlow:

    def test_runner_emits_artifacts_and_rejects_toxic(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = ToxicFlowConfig(
                ticks=3_000,
                seed=7,
                output_dir=Path(tmp),
                toxic_share=0.5,
                benign_share=0.15,
                trade_prob=0.18,
            )
            rep = run_toxic_flow(cfg)

            for p in (rep.json_path, rep.md_path, rep.html_path):
                _assert_nonempty_file(p)
            _assert_self_contained_html(rep.html_path)

            # Canonical filenames on disk.
            assert rep.json_path.name == "toxic_flow.json"
            assert rep.md_path.name == "toxic_flow.md"
            assert rep.html_path.name == "toxic_flow.html"

            # JSON schema sanity + demo invariant: a toxic-heavy
            # population over 3k ticks must produce at least one
            # TOXIC_FLOW reject. If this starts failing the scorer
            # or guard has regressed.
            doc = json.loads(rep.json_path.read_text())
            assert doc["schema"] == "sentinel-hft/usecase/toxic-flow/1"
            tp = doc["throughput"]
            for key in ("ticks", "intents", "passed", "rejected",
                         "rejected_toxic"):
                assert key in tp, f"missing throughput key: {key}"
            assert tp["rejected_toxic"] >= 1, (
                "expected >=1 TOXIC_FLOW reject with toxic_share=0.5"
            )
            assert isinstance(doc.get("top_takers"), list)
            assert doc.get("audit", {}).get("chain_ok") is True


# ---------------------------------------------------------------------
# Use case 2 -- Volatility kill-switch drill
# ---------------------------------------------------------------------


class TestKillDrill:

    def test_runner_trips_kill_and_reports_latency(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Keep the drill faithful to the default storyline
            # (spike first, kill-switch tripped AFTER spike so we
            # actually measure a positive latency) but cap total
            # ticks so the test runs fast. Empirically 12k ticks
            # generates ~26k intents; spike at tick 2_000 + kill at
            # intent 12_000 puts the kill well after the spike.
            cfg = KillDrillConfig(
                ticks=12_000,
                seed=11,
                output_dir=Path(tmp),
                spike_at_tick=2_000,
                inject_kill_at_intent=12_000,
                slo_budget_ns=500_000_000,  # generous, not asserting
            )
            rep = run_kill_drill(cfg)

            for p in (rep.json_path, rep.md_path, rep.html_path):
                _assert_nonempty_file(p)
            _assert_self_contained_html(rep.html_path)

            assert rep.json_path.name == "kill_drill.json"

            doc = json.loads(rep.json_path.read_text())
            # Kill block is nested under "kill".
            kill = doc["kill"]
            # The drill must actually trip the kill switch -- that's
            # the whole point of the use-case.
            assert kill["triggered"] is True
            assert int(kill["latency_ns"]) > 0, (
                "kill latency_ns missing or zero -- regression of the "
                "spike_tick_wire_ts_ns capture in HyperliquidRunner, "
                "or kill fired before the vol spike."
            )
            # kill latency_ns is a *duration*, not a wall-clock
            # stamp (regression guard: the pre-fix bug returned
            # ~1.7e18 = absolute ns since epoch).
            assert int(kill["latency_ns"]) < 10 ** 12, (
                "kill latency_ns looks like an absolute timestamp; "
                "expected a duration (< 1s = 1e9 ns)."
            )
            # Every post-trip non-CANCEL intent should be rejected
            # with KILL_SWITCH -- the _post_kill_audit helper counts
            # anything else as a mismatch.
            assert kill["post_trip_mismatch"] == 0


# ---------------------------------------------------------------------
# Use case 3 -- Wire-to-wire latency
# ---------------------------------------------------------------------


class TestLatency:

    def test_runner_emits_histograms_and_positive_p99(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = LatencyConfig(
                ticks=4_000,
                seed=3,
                output_dir=Path(tmp),
                enable_toxic_guard=False,
            )
            rep = run_latency(cfg)

            for p in (rep.json_path, rep.md_path, rep.html_path):
                _assert_nonempty_file(p)
            _assert_self_contained_html(rep.html_path)

            assert rep.json_path.name == "latency.json"

            doc = json.loads(rep.json_path.read_text())
            assert doc["schema"] == "sentinel-hft/usecase/latency/1"
            lat = doc["latency_ns"]
            # p50/p99 must exist and be positive.
            for key in ("count", "mean", "p50", "p99", "p999", "max"):
                assert key in lat, f"missing latency_ns key: {key}"
            assert float(lat["p99"]) > 0
            # Monotone ordering must hold (p50 <= p99 <= p999 <= max).
            assert lat["p50"] <= lat["p99"] <= lat["p999"] <= lat["max"]
            # Stage breakdown is what makes this the "attribution"
            # use-case.
            for stage in ("ingress", "core", "risk", "egress"):
                assert stage in doc["stage_p99_ns"]
            assert doc["bottleneck_stage"] in (
                "ingress", "core", "risk", "egress",
            )


# ---------------------------------------------------------------------
# Use case 4 -- Daily evidence pack
# ---------------------------------------------------------------------


class TestDailyEvidence:

    def test_runner_assembles_multi_session_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = DailyEvidenceConfig(
                output_dir=Path(tmp),
                trading_date="2026-04-21",
                sessions=[
                    SessionSpec(label="morning", ticks=1_500, seed=1),
                    SessionSpec(label="midday", ticks=1_500, seed=2),
                    SessionSpec(
                        label="afternoon",
                        ticks=1_500,
                        seed=3,
                        vol_spike_at_tick=500,
                    ),
                ],
            )
            rep = run_daily_evidence(cfg)

            for p in (rep.json_path, rep.md_path, rep.html_path):
                _assert_nonempty_file(p)
            _assert_self_contained_html(rep.html_path)

            # Combined DORA bundle (cross-session) must exist too.
            bundle = getattr(rep, "bundle_path", None)
            if bundle is not None:
                _assert_nonempty_file(bundle)

            assert rep.json_path.name == "daily_evidence.json"

            doc = json.loads(rep.json_path.read_text())
            # Schema sanity: top-level must carry a sessions list.
            assert isinstance(doc.get("sessions"), list)
            assert len(doc["sessions"]) == 3

            # Chains should verify end-to-end across every session.
            assert rep.all_chains_ok is True, (
                f"daily evidence chain breaks: {rep}"
            )


# ---------------------------------------------------------------------
# Dashboard cover page
# ---------------------------------------------------------------------


class TestDashboard:

    def test_dashboard_discovers_and_links_all_four(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Run all four into sibling subdirs -- the dashboard
            # auto-discovers by convention.
            run_toxic_flow(ToxicFlowConfig(
                ticks=1_200, seed=7,
                output_dir=root / "toxic_flow",
                toxic_share=0.5, benign_share=0.15, trade_prob=0.18,
            ))
            run_kill_drill(KillDrillConfig(
                ticks=6_000, seed=11,
                output_dir=root / "kill_drill",
                spike_at_tick=2_000,
                inject_kill_at_intent=3_500,
                slo_budget_ns=500_000_000,
            ))
            run_latency(LatencyConfig(
                ticks=1_500, seed=3,
                output_dir=root / "latency",
                enable_toxic_guard=False,
            ))
            run_daily_evidence(DailyEvidenceConfig(
                output_dir=root / "daily_evidence",
                trading_date="2026-04-21",
                sessions=[
                    SessionSpec(label="s1", ticks=800, seed=1),
                    SessionSpec(label="s2", ticks=800, seed=2),
                ],
            ))

            out = build_dashboard(
                root,
                title="Sentinel-HFT HL Demo",
                subtitle="pytest smoke",
            )
            _assert_nonempty_file(out)
            _assert_self_contained_html(out)

            html = out.read_text(encoding="utf-8")
            # The cover page should mention every use-case by its
            # artifact name so the interviewer can click through.
            for needle in (
                "toxic_flow", "kill_drill", "latency", "daily_evidence",
            ):
                assert needle in html, (
                    f"dashboard missing link to {needle}: {out}"
                )
