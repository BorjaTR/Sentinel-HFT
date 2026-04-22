"""Tests for the on-chain latency attribution module.

Covers:
- OnchainRecord binary round-trip
- File header parsing and rejection of wrong magic
- Streaming analyzer correctness on hand-crafted records
- Fixture determinism under a fixed seed
- Quantile sanity: p50 lies within [min, max], p999 >= p99 >= p50
- Venue / action breakdowns
- Landed / rejected / timed-out accounting
- CLI generate + analyze round-trip
- AI explainer can consume an on-chain FactSet
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from sentinel_hft.onchain import (  # noqa: E402
    OnchainRecord,
    OnchainMetrics,
    OnchainStage,
    HyperliquidFixture,
    SolanaFixture,
    generate_fixture,
)
from sentinel_hft.onchain.record import (  # noqa: E402
    ONCHAIN_RECORD_SIZE,
    ONCHAIN_STRUCT,
    ONCHAIN_MAGIC,
    ONCHAIN_FILE_HEADER_STRUCT,
    ONCHAIN_FILE_HEADER_SIZE,
    OnchainVenue,
    OnchainAction,
    FLAG_LANDED,
    FLAG_REJECTED,
    FLAG_TIMEOUT,
    FLAG_REORG,
    symbol_hash,
)
from sentinel_hft.onchain.analyzer import write_records  # noqa: E402
from sentinel_hft.onchain.fixtures import (  # noqa: E402
    DydxV4Fixture,
    LighterFixture,
)


# ---------------------------------------------------------------------------
# Record format
# ---------------------------------------------------------------------------

class TestRecord:

    def test_struct_size_is_80(self):
        assert ONCHAIN_STRUCT.size == 80
        assert ONCHAIN_RECORD_SIZE == 80

    def test_encode_decode_round_trip(self):
        rec = OnchainRecord(
            version=1, venue=int(OnchainVenue.HYPERLIQUID),
            action=int(OnchainAction.QUOTE), flags=FLAG_LANDED,
            seq_no=42,
            client_ts_ns=1_000_000_000, signed_ts_ns=1_000_200_000,
            submitted_ts_ns=1_000_300_000, included_ts_ns=1_200_000_000,
            symbol_hash=symbol_hash("BTC-USD"),
            d_rpc_ns=120_000, d_quote_ns=25_000, d_sign_ns=60_000,
            d_submit_ns=8_000_000, d_inclusion_ns=200_000_000,
            notional_usd_e4=50_000_0000, slippage_bps=-2, reserved=0,
        )
        buf = rec.encode()
        assert len(buf) == ONCHAIN_RECORD_SIZE
        back = OnchainRecord.decode(buf)
        assert back == rec

    def test_decode_wrong_size_raises(self):
        with pytest.raises(ValueError):
            OnchainRecord.decode(b"\x00" * 64)

    def test_symbol_hash_is_deterministic(self):
        a = symbol_hash("BTC-USD")
        b = symbol_hash("BTC-USD")
        c = symbol_hash("ETH-USD")
        assert a == b
        assert a != c
        assert 0 <= a < 2**64

    def test_total_and_overhead_consistency(self):
        # By construction stage_sum < total (with jitter inserted).
        rec = OnchainRecord(
            version=1, venue=1, action=1, flags=FLAG_LANDED, seq_no=1,
            client_ts_ns=0, signed_ts_ns=1_000,
            submitted_ts_ns=2_000, included_ts_ns=1_000_000_000,
            symbol_hash=0,
            d_rpc_ns=100, d_quote_ns=200, d_sign_ns=300,
            d_submit_ns=400, d_inclusion_ns=500,
            notional_usd_e4=0, slippage_bps=0,
        )
        assert rec.total_ns == 1_000_000_000
        assert rec.stage_sum_ns == 1_500
        assert rec.overhead_ns == 1_000_000_000 - 1_500

    def test_flag_properties(self):
        rec = OnchainRecord(
            version=1, venue=1, action=1,
            flags=FLAG_LANDED | FLAG_REORG, seq_no=0,
            client_ts_ns=0, signed_ts_ns=0, submitted_ts_ns=0, included_ts_ns=0,
            symbol_hash=0, d_rpc_ns=0, d_quote_ns=0, d_sign_ns=0,
            d_submit_ns=0, d_inclusion_ns=0, notional_usd_e4=0, slippage_bps=0,
        )
        assert rec.landed is True
        assert rec.reorged is True
        assert rec.rejected is False
        assert rec.timed_out is False


# ---------------------------------------------------------------------------
# File header + I/O
# ---------------------------------------------------------------------------

class TestFileIO:

    def test_write_and_read_back(self, tmp_path: Path):
        recs = list(HyperliquidFixture(seed=7).generate(50))
        n = write_records(tmp_path / "t.onch", recs)
        assert n == ONCHAIN_FILE_HEADER_SIZE + 50 * ONCHAIN_RECORD_SIZE
        back = list(OnchainMetrics.iter_file(tmp_path / "t.onch"))
        assert len(back) == 50
        # Deterministic ordering preserved.
        for a, b in zip(recs, back):
            assert a == b

    def test_reject_wrong_magic(self, tmp_path: Path):
        bad = tmp_path / "bad.onch"
        # Write a random 16-byte header + one record.
        bad.write_bytes(b"BADMAGIC" + b"\x00" * 8 + b"\x00" * ONCHAIN_RECORD_SIZE)
        with pytest.raises(ValueError, match="Not an on-chain trace"):
            list(OnchainMetrics.iter_file(bad))

    def test_truncated_record_raises(self, tmp_path: Path):
        # Header + a partial record.
        header = ONCHAIN_FILE_HEADER_STRUCT.pack(ONCHAIN_MAGIC, 1, ONCHAIN_RECORD_SIZE)
        (tmp_path / "trunc.onch").write_bytes(header + b"\x00" * 40)
        with pytest.raises(ValueError, match="Truncated"):
            list(OnchainMetrics.iter_file(tmp_path / "trunc.onch"))


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class TestAnalyzer:

    def test_empty_snapshot(self):
        m = OnchainMetrics()
        snap = m.snapshot()
        assert snap.total_records == 0
        assert snap.landed_rate() == 0.0
        # All stage summaries are zero-valued but present.
        for name in ("rpc", "quote", "sign", "submit", "inclusion"):
            assert snap.stages[name].count == 0
            assert snap.stages[name].p99_ns == 0.0

    def test_add_many_from_fixture(self):
        m = OnchainMetrics()
        m.add_many(HyperliquidFixture(seed=0).generate(500))
        snap = m.snapshot()
        assert snap.total_records == 500
        # DDSketch has an alpha relative error bound (1% default); reported
        # p999 may sit very slightly above true max due to bucket midpoint
        # representation. Allow a 2% headroom when comparing against max.
        for name in ("rpc", "quote", "sign", "submit", "inclusion"):
            s = snap.stages[name]
            assert s.count == 500
            # Quantile monotonicity.
            assert s.p50_ns <= s.p99_ns <= s.p999_ns
            assert s.min_ns <= s.p50_ns
            assert s.p999_ns <= s.max_ns * 1.02, (
                f"{name}: p999 {s.p999_ns} exceeds max {s.max_ns} by > 2%"
            )

    def test_landed_rate_hyperliquid(self):
        m = OnchainMetrics()
        m.add_many(HyperliquidFixture(seed=123).generate(2000))
        snap = m.snapshot()
        # Hyperliquid profile has ~0.3% reject; landed rate should be > 95%.
        assert snap.landed_rate() > 0.95
        assert snap.total_rejected + snap.total_timed_out < snap.total_records * 0.05

    def test_venue_breakdown(self):
        m = OnchainMetrics()
        m.add_many(HyperliquidFixture(seed=1).generate(100))
        m.add_many(SolanaFixture(seed=2).generate(300))
        snap = m.snapshot()
        assert snap.per_venue.get("hyperliquid") == 100
        assert snap.per_venue.get("solana_jito") == 300

    def test_hyperliquid_p50_near_block_time(self):
        m = OnchainMetrics()
        m.add_many(HyperliquidFixture(seed=42).generate(3000))
        snap = m.snapshot()
        p50_ms = snap.total.p50_ns / 1e6
        # HL profile is 200ms block time; sum of other stages ~8ms.
        # p50 should fall in [180ms, 260ms] with realistic jitter.
        assert 180 <= p50_ms <= 260, (
            f"HL total p50 expected ~210ms, got {p50_ms:.1f}ms"
        )

    def test_solana_has_wider_tail_than_hyperliquid(self):
        """Solana profile has larger sigma; its p99/p50 ratio should
        exceed Hyperliquid's. Checks that sigma parameter actually
        affects observed tail shape."""
        m_hl = OnchainMetrics()
        m_hl.add_many(HyperliquidFixture(seed=5).generate(2000))
        hl_snap = m_hl.snapshot()

        m_sol = OnchainMetrics()
        m_sol.add_many(SolanaFixture(seed=5).generate(2000))
        sol_snap = m_sol.snapshot()

        hl_ratio = hl_snap.total.p99_ns / max(1, hl_snap.total.p50_ns)
        sol_ratio = sol_snap.total.p99_ns / max(1, sol_snap.total.p50_ns)
        assert sol_ratio > hl_ratio, (
            f"expected Solana tail > HL tail; got HL={hl_ratio:.2f}, "
            f"Sol={sol_ratio:.2f}"
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class TestFixtures:

    def test_fixture_is_deterministic(self):
        a = list(HyperliquidFixture(seed=99).generate(100))
        b = list(HyperliquidFixture(seed=99).generate(100))
        assert a == b

    def test_different_seed_different_output(self):
        a = list(HyperliquidFixture(seed=1).generate(100))
        b = list(HyperliquidFixture(seed=2).generate(100))
        # Not all records identical.
        assert any(x != y for x, y in zip(a, b))

    @pytest.mark.parametrize("venue,cls", [
        ("hyperliquid", HyperliquidFixture),
        ("solana", SolanaFixture),
        ("dydx_v4", DydxV4Fixture),
        ("lighter", LighterFixture),
    ])
    def test_generate_fixture_dispatches(self, venue, cls):
        recs = list(generate_fixture(venue=venue, n=20, seed=3))
        assert len(recs) == 20
        # Basic validity: all stages produce positive deltas.
        for r in recs:
            for stage in OnchainStage:
                assert r.stage_ns(stage) > 0

    def test_unknown_venue_raises(self):
        with pytest.raises(ValueError, match="unknown venue"):
            list(generate_fixture(venue="fake-dex", n=1))

    def test_fixture_produces_occasional_rejections(self):
        # With 5000 records and 0.3% reject rate, we expect > 0 rejections.
        recs = list(HyperliquidFixture(seed=42).generate(5000))
        n_rej = sum(1 for r in recs if r.rejected)
        n_land = sum(1 for r in recs if r.landed)
        assert n_rej > 0, "fixture should produce at least one rejection"
        assert n_land > n_rej * 50, "landed should dominate"


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

class TestCLI:

    def test_cli_generate_then_analyze(self, tmp_path: Path):
        """End-to-end CLI round-trip through subprocess; confirms that
        `sentinel-hft onchain generate` writes a valid file and
        `sentinel-hft onchain analyze` reads it and emits a JSON snapshot."""
        import subprocess

        env_root = Path(__file__).parent.parent
        trace = tmp_path / "t.onch"
        out_json = tmp_path / "t.json"

        # Generate
        r = subprocess.run(
            [sys.executable, "-m", "sentinel_hft.cli.main",
             "onchain", "generate",
             "--venue", "hyperliquid",
             "-n", "500",
             "--seed", "7",
             "-o", str(trace),
             "-q"],
            cwd=env_root, capture_output=True, text=True,
        )
        assert r.returncode == 0, f"generate failed: {r.stderr}"
        assert trace.exists()
        assert trace.stat().st_size == 16 + 500 * ONCHAIN_RECORD_SIZE

        # Analyze -> JSON
        r = subprocess.run(
            [sys.executable, "-m", "sentinel_hft.cli.main",
             "onchain", "analyze",
             "-i", str(trace),
             "-o", str(out_json),
             "--ai-backend", "deterministic",
             "-q"],
            cwd=env_root, capture_output=True, text=True,
        )
        assert r.returncode == 0, f"analyze failed: {r.stderr}"
        assert out_json.exists()
        data = json.loads(out_json.read_text())
        assert data["total_records"] == 500
        assert "stages" in data
        assert set(data["stages"].keys()) == {
            "rpc", "quote", "sign", "submit", "inclusion",
        }


# ---------------------------------------------------------------------------
# AI integration
# ---------------------------------------------------------------------------

class TestAIIntegration:

    def test_explainer_consumes_onchain_facts(self):
        """The explainer's FactSet interface should work seamlessly with
        on-chain facts — proves we didn't accidentally couple the
        explainer to FPGA-specific categories."""
        from ai.explainer import Explainer, ExplanationConfig
        from ai.fact_extractor import Fact, FactSet

        m = OnchainMetrics()
        m.add_many(HyperliquidFixture(seed=0).generate(500))
        snap = m.snapshot()

        fs = FactSet()
        for name in ("rpc", "quote", "sign", "submit", "inclusion"):
            s = snap.stages[name]
            fs.add(Fact(category="latency", key=f"{name}_p99",
                        value=int(s.p99_ns),
                        context=f"{name} p99 {s.p99_ns/1e3:.1f}us",
                        importance="medium"))
        fs.add(Fact(category="latency", key="total_p99",
                    value=int(snap.total.p99_ns),
                    context=f"total p99 {snap.total.p99_ns/1e6:.1f}ms",
                    importance="high"))

        explainer = Explainer(config=ExplanationConfig(backend="deterministic"))
        out = explainer.explain(fs)
        assert out.offline is True
        assert out.backend == "deterministic"
        # Rendered report should mention latency-ish content.
        md = out.to_markdown()
        assert "SUMMARY" in md.upper() or "Summary" in md
        assert "deterministic" in md
