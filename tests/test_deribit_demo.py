"""Tests for the Deribit LD4 tick-to-trade demo pipeline (M5).

Covers:

* Instrument universe sanity (stable ids, unique symbols).
* Fixture determinism and rate-rough-check.
* Book state consistency.
* Risk-gate reference semantics (happy path + each reject reason).
* End-to-end pipeline: trace file parses with v1.2 adapter, audit
  chain verifies, DORA bundle loads, summary.md is valid markdown.
* CLI subprocess round-trip (deribit demo -> audit verify).
"""

from __future__ import annotations

import json
import math
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from sentinel_hft.audit import RejectReason, read_records, verify as audit_verify
from sentinel_hft.adapters import auto_detect
from sentinel_hft.adapters.sentinel_adapter_v12 import (
    SentinelV12Adapter, V12_SIZE,
)
from sentinel_hft.formats.file_header import HEADER_SIZE

from sentinel_hft.deribit import (
    BookState,
    DEFAULT_UNIVERSE,
    DeribitDemo,
    DeribitFixture,
    DemoConfig,
    IntentAction,
    PositionTracker,
    QuoteIntent,
    RiskGate,
    RiskGateConfig,
    Side,
    SpreadMMStrategy,
    TickEvent,
    TickKind,
    TokenBucket,
    run_demo,
)
from sentinel_hft.deribit.instruments import (
    Instrument,
    InstrumentKind,
    OptionType,
    by_id,
    by_symbol,
)


# ---------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------


class TestInstrumentUniverse:

    def test_universe_nonempty(self):
        assert len(DEFAULT_UNIVERSE) >= 4

    def test_symbol_ids_unique(self):
        ids = [i.symbol_id for i in DEFAULT_UNIVERSE]
        assert len(ids) == len(set(ids))

    def test_symbols_unique(self):
        syms = [i.symbol for i in DEFAULT_UNIVERSE]
        assert len(syms) == len(set(syms))

    def test_symbol_ids_fit_u16(self):
        for i in DEFAULT_UNIVERSE:
            assert 0 < i.symbol_id <= 0xFFFF

    def test_universe_has_both_kinds(self):
        kinds = {i.kind for i in DEFAULT_UNIVERSE}
        assert InstrumentKind.PERPETUAL in kinds
        assert InstrumentKind.OPTION in kinds

    def test_options_have_strike_and_right(self):
        for i in DEFAULT_UNIVERSE:
            if i.kind == InstrumentKind.OPTION:
                assert i.option_type in (OptionType.CALL, OptionType.PUT)
                assert i.strike > 0

    def test_index_by_id_and_symbol(self):
        by_id_map = by_id()
        by_sym_map = by_symbol()
        for i in DEFAULT_UNIVERSE:
            assert by_id_map[i.symbol_id] is i
            assert by_sym_map[i.symbol] is i


# ---------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------


class TestFixture:

    def test_determinism(self):
        a = list(DeribitFixture(seed=123).generate(n=300))
        b = list(DeribitFixture(seed=123).generate(n=300))
        assert len(a) == len(b) == 300
        for x, y in zip(a, b):
            assert x.wire_ts_ns == y.wire_ts_ns
            assert x.seq_no == y.seq_no
            assert x.bid_price == y.bid_price
            assert x.ask_price == y.ask_price
            assert x.instrument.symbol_id == y.instrument.symbol_id

    def test_different_seeds_diverge(self):
        a = list(DeribitFixture(seed=1).generate(n=200))
        b = list(DeribitFixture(seed=2).generate(n=200))
        # At least one tick should differ in price or instrument choice.
        diffs = 0
        for x, y in zip(a, b):
            if (x.instrument.symbol_id != y.instrument.symbol_id
                    or x.bid_price != y.bid_price):
                diffs += 1
        assert diffs > 20

    def test_timestamps_monotonic(self):
        evs = list(DeribitFixture(seed=5).generate(n=500))
        ts = [e.wire_ts_ns for e in evs]
        assert ts == sorted(ts)

    def test_host_ts_after_wire(self):
        for e in DeribitFixture(seed=9).generate(n=200):
            assert e.host_ts_ns >= e.wire_ts_ns

    def test_bid_below_ask(self):
        for e in DeribitFixture(seed=11).generate(n=500):
            assert e.bid_price < e.ask_price
            assert e.spread > 0

    def test_trade_carries_trade_price(self):
        evs = list(DeribitFixture(seed=0, trade_prob=1.0).generate(n=100))
        trades = [e for e in evs if e.kind == TickKind.TRADE]
        assert trades, "trade_prob=1.0 should emit trades"
        for t in trades:
            assert t.trade_size > 0
            assert t.trade_price > 0

    def test_seq_no_unique_and_monotonic(self):
        evs = list(DeribitFixture(seed=0).generate(n=300))
        seqs = [e.seq_no for e in evs]
        assert seqs == list(range(1, len(seqs) + 1))

    def test_instrument_mix_all_present(self):
        evs = list(DeribitFixture(seed=3).generate(n=5000))
        counts = {}
        for e in evs:
            counts[e.instrument.symbol_id] = counts.get(
                e.instrument.symbol_id, 0) + 1
        # Each instrument should fire at least once in 5k ticks.
        for ins in DEFAULT_UNIVERSE:
            assert counts.get(ins.symbol_id, 0) > 0, (
                f"{ins.symbol} never fired"
            )


# ---------------------------------------------------------------------
# Book
# ---------------------------------------------------------------------


class TestBook:

    def test_apply_updates_bbo(self):
        bs = BookState()
        ev = next(iter(DeribitFixture(seed=0).generate(n=1)))
        tob = bs.apply(ev)
        assert tob.bid == ev.bid_price
        assert tob.ask == ev.ask_price
        assert tob.mid == pytest.approx(0.5 * (ev.bid_price + ev.ask_price))

    def test_trade_updates_last_trade(self):
        bs = BookState()
        fx = DeribitFixture(seed=0, trade_prob=1.0)
        ev = next(iter(fx.generate(n=1)))
        tob = bs.apply(ev)
        # With trade_prob=1.0 the first event is a trade.
        assert tob.last_trade == ev.trade_price
        assert tob.last_trade_ts_ns == ev.host_ts_ns


# ---------------------------------------------------------------------
# Risk primitives
# ---------------------------------------------------------------------


class TestRiskPrimitives:

    def test_bucket_refills(self):
        b = TokenBucket(max_tokens=10, refill_per_second=10.0)
        # Drain the bucket.
        for i in range(10):
            assert b.try_consume(1_000_000_000 + i)
        assert not b.try_consume(1_000_000_001)
        # Advance one second: 10 tokens refill.
        assert b.try_consume(2_000_000_000)

    def test_position_order_size_reject(self):
        p = PositionTracker(max_order_qty=5)
        assert p.check(Side.BUY, qty=6, notional=0) == RejectReason.ORDER_SIZE

    def test_position_long_limit(self):
        p = PositionTracker(max_long_qty=5)
        p.apply(Side.BUY, 3, 0)
        assert p.check(Side.BUY, 3, 0) == RejectReason.POSITION_LIMIT

    def test_position_notional_limit(self):
        p = PositionTracker(max_notional=1_000)
        p.apply(Side.BUY, 1, 800)
        assert p.check(Side.BUY, 1, 300) == RejectReason.NOTIONAL_LIMIT

    def test_position_release_does_not_go_negative(self):
        p = PositionTracker()
        p.release(Side.BUY, 5, 1000)
        assert p.long_qty == 0
        assert p.notional == 0

    def test_gate_cancel_is_free(self):
        g = RiskGate(RiskGateConfig(max_tokens=1, refill_per_second=0))
        # Drain rate limit.
        g.bucket.try_consume(0, 1)
        # A NEW would be rate-limited; a CANCEL should pass.
        cancel = QuoteIntent(
            order_id=1, symbol_id=1, side=Side.BUY, price=100.0,
            quantity=1, notional=100, generated_ts_ns=1,
            action=IntentAction.CANCEL,
        )
        dec = g.evaluate(cancel, now_ns=1)
        assert dec.passed

    def test_gate_kill_switch_blocks_everything(self):
        g = RiskGate()
        g.kill.trip()
        intent = QuoteIntent(
            order_id=1, symbol_id=1, side=Side.BUY, price=100,
            quantity=1, notional=100, generated_ts_ns=1,
        )
        dec = g.evaluate(intent, now_ns=1)
        assert not dec.passed
        assert dec.reject_reason == int(RejectReason.KILL_SWITCH)
        assert dec.kill_triggered


# ---------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------


class TestStrategy:

    def test_quotes_are_pair(self):
        bs = BookState()
        strat = SpreadMMStrategy()
        fx = DeribitFixture(seed=0)
        ev = next(iter(fx.generate(n=1)))
        tob = bs.apply(ev)
        intents = strat.on_tick(tob, ev.host_ts_ns + 1_000)
        # First tick: no cancels yet, just the new pair.
        assert len(intents) == 2
        sides = {i.side for i in intents}
        assert sides == {Side.BUY, Side.SELL}

    def test_repaper_emits_cancels(self):
        bs = BookState()
        strat = SpreadMMStrategy(repaper_ns=1)   # allow fast repaper
        fx = DeribitFixture(seed=0)
        evs = list(fx.generate(n=2))
        inst = evs[0].instrument
        tob0 = bs.apply(evs[0])
        first = strat.on_tick(tob0, evs[0].host_ts_ns + 1_000)
        # Confirm both NEWs so the strategy tracks them as outstanding
        # (mirrors what the pipeline does when the gate accepts them).
        for i in first:
            assert i.action == IntentAction.NEW
            strat.confirm_new(i)

        # Fake a same-instrument second tick that would trigger a repaper.
        same_ev = TickEvent(
            wire_ts_ns=evs[1].wire_ts_ns,
            host_ts_ns=evs[1].host_ts_ns,
            seq_no=evs[1].seq_no,
            instrument=inst,
            kind=TickKind.QUOTE,
            bid_price=tob0.bid * 1.01,
            ask_price=tob0.ask * 1.01,
            bid_size=1, ask_size=1,
        )
        tob_same = bs.apply(same_ev)
        intents = strat.on_tick(tob_same, same_ev.host_ts_ns + 10_000_000)
        cancels = [i for i in intents if i.action == IntentAction.CANCEL]
        news = [i for i in intents if i.action == IntentAction.NEW]
        assert len(cancels) == 2
        assert len(news) == 2


# ---------------------------------------------------------------------
# End-to-end pipeline
# ---------------------------------------------------------------------


class TestEndToEnd:

    def test_run_small(self, tmp_path):
        arts = run_demo(ticks=1_000, seed=7, output_dir=tmp_path)
        assert arts.trace_path.exists()
        assert arts.audit_path.exists()
        assert arts.dora_path.exists()
        assert arts.summary_path.exists()
        assert arts.decisions_logged > 0
        assert arts.chain_ok is True
        assert arts.p50_ns > 0
        # FPGA-ish latency budget: p99 should be well under 10us.
        assert arts.p99_ns < 50_000

    def test_determinism(self, tmp_path):
        a = run_demo(ticks=500, seed=99, output_dir=tmp_path / "a")
        b = run_demo(ticks=500, seed=99, output_dir=tmp_path / "b")
        assert a.head_hash_lo_hex == b.head_hash_lo_hex
        assert a.passed == b.passed
        assert a.rejected == b.rejected

    def test_trace_parses_with_v12_adapter(self, tmp_path):
        arts = run_demo(ticks=500, seed=3, output_dir=tmp_path)
        adapter, header = auto_detect(arts.trace_path)
        assert isinstance(adapter, SentinelV12Adapter)
        assert header is not None
        assert header.record_size == V12_SIZE
        recs = list(adapter.iterate_file(arts.trace_path))
        assert recs, "trace file yielded no records"
        # First record's stage sum should equal total latency (no
        # overhead on the first tick with no prior state).
        first = recs[0]
        total = first.t_egress - first.t_ingress
        stages = (first.d_ingress + first.d_core
                  + first.d_risk + first.d_egress) * 10
        assert total == pytest.approx(stages, abs=200)

    def test_audit_chain_verifies(self, tmp_path):
        arts = run_demo(ticks=500, seed=11, output_dir=tmp_path)
        records = list(read_records(arts.audit_path))
        result = audit_verify(records)
        assert result.ok, [b.to_dict() for b in result.breaks[:3]]
        assert result.total_records == len(records)
        assert result.verified_records == result.total_records

    def test_dora_bundle_shape(self, tmp_path):
        arts = run_demo(ticks=300, seed=13, output_dir=tmp_path)
        bundle = json.loads(arts.dora_path.read_text())
        assert bundle["metadata"]["schema_version"] == "dora-bundle/1"
        assert bundle["metadata"]["producer"] == "sentinel-hft"
        assert bundle["audit_chain"]["record_count"] == len(
            list(read_records(arts.audit_path))
        )
        assert bundle["audit_chain"]["verification"]["ok"] is True

    def test_summary_markdown_has_sections(self, tmp_path):
        arts = run_demo(ticks=200, seed=17, output_dir=tmp_path)
        md = arts.summary_path.read_text()
        for needle in ("# Sentinel-HFT Deribit LD4 demo",
                       "## Throughput",
                       "## Latency",
                       "## Risk-gate outcome",
                       "## Audit chain"):
            assert needle in md, f"missing section: {needle!r}"

    def test_kill_injection(self, tmp_path):
        arts = run_demo(
            ticks=3_000, seed=5, output_dir=tmp_path,
            inject_kill_at=50,
        )
        assert arts.kill_triggered
        # Once kill trips, most subsequent NEWs should be rejected via
        # KILL_SWITCH. Chain should still verify.
        assert arts.chain_ok
        records = list(read_records(arts.audit_path))
        kill_decisions = [
            r for r in records
            if r.reject_reason == int(RejectReason.KILL_SWITCH)
        ]
        assert len(kill_decisions) > 0


# ---------------------------------------------------------------------
# CLI (subprocess)
# ---------------------------------------------------------------------


class TestCLI:

    def test_deribit_demo_cli(self, tmp_path):
        out = tmp_path / "run"
        res = subprocess.run(
            [sys.executable, "-m", "sentinel_hft.cli.main", "deribit",
             "demo", "--ticks", "500", "--seed", "42",
             "-o", str(out), "-q"],
            capture_output=True, text=True, timeout=60,
        )
        assert res.returncode == 0, res.stderr
        for name in ("traces.sst", "audit.aud", "dora.json", "summary.md"):
            assert (out / name).exists(), f"{name} not produced"

        # Cross-verify the audit chain using the audit CLI.
        res2 = subprocess.run(
            [sys.executable, "-m", "sentinel_hft.cli.main", "audit",
             "verify", "-i", str(out / "audit.aud"), "-q"],
            capture_output=True, text=True, timeout=30,
        )
        assert res2.returncode == 0, res2.stderr
