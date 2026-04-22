"""End-to-end regression test for the Sentinel-HFT Deribit demo.

This is the one test that exercises the full hero path from CLI
invocation through to audit verification. It pins the head hash of
the tamper-evident audit chain to catch any non-deterministic
regression or silent change in the strategy / risk / pipeline
semantics.

If this test fails after a refactor you have three options:

1. Convince yourself the change was intentional (e.g. bumped a
   default, reordered a field in the strategy state). If so, update
   the pinned ``HEAD_HASH_SEED_1_5K`` and ``HEAD_HASH_SEED_42_5K``
   constants to match the new canonical values and note the change
   in the PR description.
2. Convince yourself it's a genuine non-determinism bug (e.g. a set
   somewhere got iterated in hash order, or a timestamp source got
   re-wired to the wall clock). Fix the bug.
3. If you can't tell, bisect against ``main``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from sentinel_hft.audit import read_records, verify as audit_verify
from sentinel_hft.deribit import run_demo


# ---------------------------------------------------------------------
# Canonical pinned head hashes
# ---------------------------------------------------------------------
#
# Computed from the canonical demo run on the reference build. These
# are the full BLAKE2b-256 low-128-bit values emitted by the audit
# chain. Any change here must be deliberate.

HEAD_HASH_SEED_1_5K = "03486379076bf490d53b62ae0bb235c0"
HEAD_HASH_SEED_42_5K = "52c727cf183fce37e85b296a04742132"


# ---------------------------------------------------------------------
# Programmatic entry-point path
# ---------------------------------------------------------------------


class TestEndToEndDemo:
    """Exercise the run_demo() programmatic entry point."""

    def test_reference_run_seed_1(self, tmp_path: Path) -> None:
        """Canonical 5k-tick run at seed=1 must produce the pinned head hash."""
        artifacts = run_demo(
            ticks=5000, seed=1, output_dir=tmp_path,
        )

        assert artifacts.head_hash_lo_hex == HEAD_HASH_SEED_1_5K, (
            "Head hash drifted from canonical value. If intentional, "
            "update HEAD_HASH_SEED_1_5K in this test; otherwise "
            "investigate for non-determinism."
        )
        assert artifacts.chain_ok is True
        assert artifacts.ticks_consumed == 5000
        assert artifacts.intents_generated > 0
        assert artifacts.decisions_logged == artifacts.intents_generated
        assert artifacts.passed + artifacts.rejected == artifacts.decisions_logged
        assert artifacts.kill_triggered is False

    def test_reference_run_seed_42(self, tmp_path: Path) -> None:
        """Different seed must produce different but pinned head hash."""
        artifacts = run_demo(
            ticks=5000, seed=42, output_dir=tmp_path,
        )

        assert artifacts.head_hash_lo_hex == HEAD_HASH_SEED_42_5K
        assert artifacts.chain_ok is True

    def test_determinism(self, tmp_path: Path) -> None:
        """Two runs with the same seed must produce byte-identical artifacts."""
        run_a = run_demo(ticks=2000, seed=7, output_dir=tmp_path / "a")
        run_b = run_demo(ticks=2000, seed=7, output_dir=tmp_path / "b")

        # Hashes + counts must match.
        assert run_a.head_hash_lo_hex == run_b.head_hash_lo_hex
        assert run_a.intents_generated == run_b.intents_generated
        assert run_a.passed == run_b.passed
        assert run_a.rejected == run_b.rejected
        assert run_a.p50_ns == run_b.p50_ns
        assert run_a.p99_ns == run_b.p99_ns

        # Audit files should be byte-identical. Trace files may differ
        # in wall-clock timestamps embedded by the adapter, so we skip
        # those -- but audit.aud is purely derived from the run, so it
        # *must* match.
        a_audit = (tmp_path / "a" / "audit.aud").read_bytes()
        b_audit = (tmp_path / "b" / "audit.aud").read_bytes()
        assert a_audit == b_audit, (
            "audit.aud is non-deterministic -- something in the "
            "risk-gate path depends on wall-clock time or memory addresses."
        )

    def test_artifacts_exist_and_nonempty(self, tmp_path: Path) -> None:
        """All four artifacts must be produced and non-empty."""
        run_demo(ticks=1000, seed=3, output_dir=tmp_path)

        for name in ("traces.sst", "audit.aud", "dora.json", "summary.md"):
            p = tmp_path / name
            assert p.exists(), f"{name} not produced"
            assert p.stat().st_size > 0, f"{name} is empty"

    def test_dora_bundle_schema(self, tmp_path: Path) -> None:
        """DORA bundle must have the expected top-level shape."""
        run_demo(ticks=1000, seed=3, output_dir=tmp_path)

        bundle = json.loads((tmp_path / "dora.json").read_text())
        # Our DORA bundle splits evidence into four sections. Version
        # and subject identifiers live under ``metadata``.
        for required in ("metadata", "audit_chain", "summary", "records"):
            assert required in bundle, f"missing top-level section: {required}"
        assert "schema" in bundle["metadata"] or "bundle_version" in bundle["metadata"] \
            or "subject" in bundle["metadata"]
        # Audit chain must carry the head hash commitment.
        assert "head_hash_lo" in bundle["audit_chain"] \
            or "head_hash" in bundle["audit_chain"] \
            or any("hash" in k for k in bundle["audit_chain"].keys())

    def test_summary_mentions_head_hash(self, tmp_path: Path) -> None:
        """Summary markdown should include the head hash for humans to diff."""
        artifacts = run_demo(ticks=1000, seed=3, output_dir=tmp_path)
        summary = (tmp_path / "summary.md").read_text()
        assert artifacts.head_hash_lo_hex in summary
        assert "## Latency" in summary or "Latency" in summary

    def test_audit_chain_round_trip(self, tmp_path: Path) -> None:
        """Write an audit file, read it back, and verify the chain."""
        artifacts = run_demo(ticks=2000, seed=11, output_dir=tmp_path)

        records = list(read_records(artifacts.audit_path))
        assert len(records) == artifacts.decisions_logged

        result = audit_verify(records)
        assert result.ok is True
        assert not result.breaks
        assert result.total_records == artifacts.decisions_logged

    def test_audit_chain_breaks_on_tamper(self, tmp_path: Path) -> None:
        """Flipping a single byte in the audit file must break the chain."""
        artifacts = run_demo(ticks=1000, seed=13, output_dir=tmp_path)
        audit_path = artifacts.audit_path

        # Clean run first.
        records = list(read_records(audit_path))
        assert audit_verify(records).ok is True

        # Corrupt one byte in the payload region of record #5 (skip
        # the 32-byte file header, skip 5 * 96-byte records, then
        # flip a byte mid-record).
        tampered = audit_path.read_bytes()
        offset = 32 + 5 * 96 + 12
        tampered = (
            tampered[:offset]
            + bytes([tampered[offset] ^ 0x01])
            + tampered[offset + 1:]
        )
        audit_path.write_bytes(tampered)

        records = list(read_records(audit_path))
        result = audit_verify(records)
        assert result.ok is False, "tamper detection failed"
        assert result.breaks, "expected at least one recorded chain break"


# ---------------------------------------------------------------------
# CLI entry-point path
# ---------------------------------------------------------------------


def _cli_available() -> bool:
    """The sentinel-hft CLI needs to be installed to run the CLI tests."""
    return shutil.which("sentinel-hft") is not None


@pytest.mark.skipif(not _cli_available(), reason="sentinel-hft CLI not installed")
class TestCLIPath:
    """Exercise the user-facing CLI that docs/DEMO_SCRIPT.md advertises."""

    def test_deribit_demo_cli(self, tmp_path: Path) -> None:
        """`sentinel-hft deribit demo` must produce all four artifacts."""
        result = subprocess.run(
            [
                "sentinel-hft", "deribit", "demo",
                "--ticks", "1000",
                "--seed", "1",
                "-o", str(tmp_path),
                "--quiet",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"CLI failed:\n  stdout: {result.stdout}\n  stderr: {result.stderr}"
        )
        for name in ("traces.sst", "audit.aud", "dora.json", "summary.md"):
            assert (tmp_path / name).exists(), f"{name} not produced by CLI"

    def test_audit_verify_cli_round_trip(self, tmp_path: Path) -> None:
        """`sentinel-hft audit verify` must pass on a fresh demo run."""
        # 1. Produce a run.
        run = subprocess.run(
            [
                "sentinel-hft", "deribit", "demo",
                "--ticks", "1000",
                "--seed", "1",
                "-o", str(tmp_path),
                "--quiet",
            ],
            capture_output=True, text=True, timeout=60,
        )
        assert run.returncode == 0

        # 2. Verify the audit chain.
        verify = subprocess.run(
            [
                "sentinel-hft", "audit", "verify",
                str(tmp_path / "audit.aud"),
            ],
            capture_output=True, text=True, timeout=30,
        )
        assert verify.returncode == 0, (
            f"audit verify failed:\n  stdout: {verify.stdout}\n"
            f"  stderr: {verify.stderr}"
        )
        # CLI should report the chain as OK.
        output = verify.stdout + verify.stderr
        assert "OK" in output or "ok" in output or "PASS" in output.lower()


# ---------------------------------------------------------------------
# CI signal -- keep the dashboard honest
# ---------------------------------------------------------------------


def test_latency_budget_is_fpga_realistic(tmp_path: Path) -> None:
    """Sanity-check that the demo's latency distribution matches a 100 MHz FPGA.

    p50 should be in the 1-2us band (100-200 cycles at 100 MHz).
    p99 should be under 10us (1000 cycles). If either drifts out of
    these bands by a factor of 2+, something in the budget model
    changed and the demo no longer represents an Alveo U55C target.
    """
    artifacts = run_demo(ticks=3000, seed=1, output_dir=tmp_path)

    assert 500 <= artifacts.p50_ns <= 3000, (
        f"p50 {artifacts.p50_ns} ns is outside the 0.5-3us FPGA band"
    )
    assert 1500 <= artifacts.p99_ns <= 20000, (
        f"p99 {artifacts.p99_ns} ns is outside the 1.5-20us FPGA band"
    )
    assert artifacts.p999_ns >= artifacts.p99_ns, "p999 must be >= p99"
    assert artifacts.max_ns >= artifacts.p999_ns, "max must be >= p999"
