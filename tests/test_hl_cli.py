"""Subprocess round-trip tests for the `sentinel-hft hl ...` CLI.

These tests shell out to the real CLI (``python -m sentinel_hft.cli.main``)
so they exercise argument parsing, typer wiring, runner construction
and artifact emission end-to-end. Each command is driven with tiny
``--ticks`` so the whole module runs in a few seconds.

Coverage:

* ``hl --help``, ``hl toxic-flow --help``, ``hl kill-drill --help``,
  ``hl latency --help`` all exit 0 and advertise their subcommands /
  options.
* ``hl toxic-flow -n 1500 -o tmp`` produces the three use-case
  artifacts + the four HL run artifacts, and the JSON reports the
  expected schema.
* ``hl kill-drill`` with a tiny tick budget but spike-before-kill
  ordering trips the kill switch and reports a positive duration.
* ``hl latency --no-toxic-guard -n 2000 -o tmp`` produces a valid
  latency report with a positive p99.
* ``hl dashboard <root>`` stitches whatever use-cases are present
  into ``dashboard.html`` and links them by name.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


# Repo root; CLI is invoked as a module so we don't depend on an
# installed entry-point.
REPO_ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
CLI_ENTRY = [PY, "-m", "sentinel_hft.cli.main"]


def _run(*args: str, cwd: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run the sentinel-hft CLI as a subprocess and return the result.

    Captures both stdout/stderr; never raises on non-zero exit -- the
    caller asserts on ``.returncode`` so test failures carry the
    command's own output.
    """
    proc = subprocess.run(
        CLI_ENTRY + list(args),
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc


def _assert_nonempty_file(p: Path) -> None:
    assert p.exists(), f"missing artifact: {p}"
    assert p.stat().st_size > 0, f"empty artifact: {p}"


# ---------------------------------------------------------------------
# Help surfaces
# ---------------------------------------------------------------------


class TestHelpSurfaces:

    def test_hl_help_lists_subcommands(self):
        r = _run("hl", "--help")
        assert r.returncode == 0, r.stderr
        out = r.stdout
        for sub in (
            "toxic-flow", "kill-drill", "latency",
            "daily-evidence", "dashboard", "demo",
        ):
            assert sub in out, f"hl --help missing subcommand: {sub}"

    @pytest.mark.parametrize("sub", [
        "toxic-flow", "kill-drill", "latency",
        "daily-evidence", "dashboard", "demo",
    ])
    def test_subcommand_help_exits_zero(self, sub: str):
        r = _run("hl", sub, "--help")
        assert r.returncode == 0, (r.stderr or r.stdout)
        # Typer prints "Usage:" on help; keep the assertion loose so a
        # Typer version bump doesn't break us.
        assert "Usage" in r.stdout or "usage" in r.stdout


# ---------------------------------------------------------------------
# Toxic-flow CLI round-trip
# ---------------------------------------------------------------------


class TestToxicFlowCLI:

    def test_toxic_flow_emits_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            r = _run(
                "hl", "toxic-flow",
                "-n", "1500",
                "-o", str(out),
                "--toxic-share", "0.5",
                "--benign-share", "0.15",
                "--trade-prob", "0.18",
                "-q",
            )
            assert r.returncode == 0, r.stderr or r.stdout

            # Use-case reports.
            for name in ("toxic_flow.json", "toxic_flow.md", "toxic_flow.html"):
                _assert_nonempty_file(out / name)

            # Underlying HL run artifacts.
            for name in ("traces.sst", "audit.aud",
                          "dora.json", "summary.md"):
                _assert_nonempty_file(out / name)

            doc = json.loads((out / "toxic_flow.json").read_text())
            assert doc["schema"] == "sentinel-hft/usecase/toxic-flow/1"
            # Toxic-heavy mix must produce at least one reject.
            assert doc["throughput"]["rejected_toxic"] >= 1


# ---------------------------------------------------------------------
# Kill-drill CLI round-trip
# ---------------------------------------------------------------------


class TestKillDrillCLI:

    def test_kill_drill_trips_and_measures_latency(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            r = _run(
                "hl", "kill-drill",
                "-n", "8000",
                "--spike-at-tick", "2000",
                "--inject-kill-at-intent", "8000",
                "--slo-budget-ns", "500000000",
                "-o", str(out),
                "-q",
            )
            assert r.returncode == 0, r.stderr or r.stdout

            for name in ("kill_drill.json", "kill_drill.md",
                          "kill_drill.html"):
                _assert_nonempty_file(out / name)

            doc = json.loads((out / "kill_drill.json").read_text())
            kill = doc["kill"]
            assert kill["triggered"] is True
            assert int(kill["latency_ns"]) > 0, (
                "kill latency zero -- spike/kill ordering regression."
            )
            # Duration, not wall-clock stamp.
            assert int(kill["latency_ns"]) < 10 ** 12
            assert kill["post_trip_mismatch"] == 0


# ---------------------------------------------------------------------
# Latency CLI round-trip
# ---------------------------------------------------------------------


class TestLatencyCLI:

    def test_latency_reports_positive_p99_and_bottleneck(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            r = _run(
                "hl", "latency",
                "-n", "2000",
                "--no-toxic-guard",
                "-o", str(out),
                "-q",
            )
            assert r.returncode == 0, r.stderr or r.stdout

            for name in ("latency.json", "latency.md", "latency.html"):
                _assert_nonempty_file(out / name)

            doc = json.loads((out / "latency.json").read_text())
            assert doc["schema"] == "sentinel-hft/usecase/latency/1"
            lat = doc["latency_ns"]
            assert float(lat["p99"]) > 0
            assert lat["p50"] <= lat["p99"] <= lat["p999"] <= lat["max"]
            assert doc["bottleneck_stage"] in (
                "ingress", "core", "risk", "egress",
            )


# ---------------------------------------------------------------------
# Dashboard CLI round-trip (depends on 2 prior use-cases)
# ---------------------------------------------------------------------


class TestDashboardCLI:

    def test_dashboard_stitches_existing_use_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            # Seed the root with two small use-cases so there is
            # something to aggregate.
            r1 = _run(
                "hl", "toxic-flow",
                "-n", "1200",
                "-o", str(root / "toxic_flow"),
                "--toxic-share", "0.5",
                "--benign-share", "0.15",
                "--trade-prob", "0.18",
                "-q",
            )
            assert r1.returncode == 0, r1.stderr or r1.stdout
            r2 = _run(
                "hl", "latency",
                "-n", "1500",
                "--no-toxic-guard",
                "-o", str(root / "latency"),
                "-q",
            )
            assert r2.returncode == 0, r2.stderr or r2.stdout

            dash_path = root / "dashboard.html"
            r3 = _run(
                "hl", "dashboard",
                str(root),
                "-o", str(dash_path),
                "-q",
            )
            assert r3.returncode == 0, r3.stderr or r3.stdout

            _assert_nonempty_file(dash_path)
            html = dash_path.read_text(encoding="utf-8")
            for needle in ("toxic_flow", "latency"):
                assert needle in html, (
                    f"dashboard missing use-case link: {needle}"
                )
