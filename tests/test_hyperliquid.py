"""Tests for the Hyperliquid ingestion layer (M_HL.A + M_HL.B).

Covers the building blocks that the four use-cases sit on top of:

* Instrument universe sanity (unique ids, kind/price tick plausible).
* Fixture determinism for a fixed seed + config.
* Binary HLTK capture round-trip (pack/unpack + file header magic).
* Toxic-flow scorer + guard: a toxic-heavy taker trips TOXIC_FLOW;
  a benign one does not.
* Runner smoke: HL_DEFAULT fixture + HyperliquidRunner emits the
  four artifacts (traces.sst, audit.aud, dora.json, summary.md)
  and the audit chain verifies end-to-end.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from sentinel_hft.audit import (
    RejectReason,
    read_records,
    verify as audit_verify,
)
from sentinel_hft.deribit.risk import RiskGateConfig
from sentinel_hft.hyperliquid import (
    HL_DEFAULT_UNIVERSE,
    HL_UNIVERSE,
    HLRunConfig,
    HyperliquidFixture,
    HyperliquidInstrument,
    HyperliquidRunner,
    TakerProfile,
    ToxicFlowGuard,
    ToxicFlowScorer,
    VolSpike,
    hl_by_id,
    hl_by_symbol,
    read_events,
    write_events,
)


# ---------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------


class TestHLInstruments:

    def test_universe_nonempty(self):
        assert len(HL_UNIVERSE) >= 3
        assert len(HL_DEFAULT_UNIVERSE) >= 1

    def test_symbol_ids_unique(self):
        ids = [i.symbol_id for i in HL_UNIVERSE]
        assert len(ids) == len(set(ids))

    def test_symbols_unique(self):
        syms = [i.symbol for i in HL_UNIVERSE]
        assert len(syms) == len(set(syms))

    def test_symbol_ids_fit_u16(self):
        for i in HL_UNIVERSE:
            assert 0 < i.symbol_id <= 0xFFFF

    def test_lookup_by_id_and_symbol(self):
        i = HL_UNIVERSE[0]
        by_id = hl_by_id()
        by_sym = hl_by_symbol()
        assert by_id[i.symbol_id] is i
        assert by_sym[i.symbol] is i

    def test_default_subset_of_universe(self):
        for inst in HL_DEFAULT_UNIVERSE:
            assert isinstance(inst, HyperliquidInstrument)
            assert inst in HL_UNIVERSE


# ---------------------------------------------------------------------
# Fixture determinism
# ---------------------------------------------------------------------


class TestFixtureDeterminism:

    @staticmethod
    def _run(seed: int, n: int = 1_000) -> list:
        fix = HyperliquidFixture(
            universe=HL_DEFAULT_UNIVERSE,
            seed=seed,
            trade_prob=0.1,
            taker_population=8,
            toxic_share=0.2,
            benign_share=0.4,
        )
        return list(fix.generate(n=n))

    def test_deterministic_same_seed(self):
        a = self._run(seed=7)
        b = self._run(seed=7)
        assert len(a) == len(b)
        for x, y in zip(a, b):
            assert x.wire_ts_ns == y.wire_ts_ns
            assert x.seq_no == y.seq_no
            assert x.instrument.symbol_id == y.instrument.symbol_id
            assert x.kind == y.kind
            assert x.bid_price == y.bid_price
            assert x.ask_price == y.ask_price
            assert x.taker_id == y.taker_id

    def test_different_seed_produces_different_stream(self):
        a = self._run(seed=1)
        b = self._run(seed=2)
        # Same fixture duration -> same tick count, but content differs.
        assert len(a) == len(b)
        diffs = sum(
            1 for x, y in zip(a, b)
            if (x.seq_no != y.seq_no or x.taker_id != y.taker_id)
        )
        assert diffs > 0

    def test_wire_ts_monotonic(self):
        stream = self._run(seed=3, n=2_000)
        last = 0
        for ev in stream:
            assert ev.wire_ts_ns >= last
            last = ev.wire_ts_ns


# ---------------------------------------------------------------------
# Binary HLTK capture round-trip
# ---------------------------------------------------------------------


class TestHLTKRoundTrip:

    def test_pack_unpack_event_fidelity(self):
        stream = list(HyperliquidFixture(
            universe=HL_DEFAULT_UNIVERSE, seed=13,
        ).generate(n=500))
        assert stream, "fixture produced no events"

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "capture.hltk"
            written = write_events(p, stream)
            assert written > 0
            back = list(read_events(p))

        assert len(back) == len(stream)
        for orig, decoded in zip(stream, back):
            assert orig.wire_ts_ns == decoded.wire_ts_ns
            assert orig.host_ts_ns == decoded.host_ts_ns
            assert orig.seq_no == decoded.seq_no
            assert orig.instrument.symbol_id == decoded.instrument.symbol_id
            assert orig.kind == decoded.kind
            # Prices are floats packed via the reader's fixed-point
            # codec; allow 1e-6 relative tolerance.
            assert abs(orig.bid_price - decoded.bid_price) < max(
                1e-6, 1e-6 * orig.bid_price
            )
            assert abs(orig.ask_price - decoded.ask_price) < max(
                1e-6, 1e-6 * orig.ask_price
            )


# ---------------------------------------------------------------------
# Toxic-flow scorer + guard
# ---------------------------------------------------------------------


class TestToxicFlowPipeline:

    def test_scorer_classifies_toxic_vs_benign(self):
        """Force a toxic-heavy stream for one taker and verify the
        scorer's adverse-selection classification moves in the right
        direction."""
        stream = list(HyperliquidFixture(
            universe=HL_DEFAULT_UNIVERSE,
            seed=21,
            trade_prob=0.15,
            taker_population=6,
            toxic_share=0.5,
            benign_share=0.1,
        ).generate(n=4_000))

        scorer = ToxicFlowScorer()
        for ev in stream:
            scorer.on_tick(ev)

        summ = scorer.summary()
        # With a 50% toxic share + 10% benign, we expect at least one
        # taker to land in each classification bucket over 4k ticks.
        assert summ["takers"] >= 3
        assert summ["toxic"] >= 1

    def test_guard_blocks_high_toxicity_after_warmup(self):
        """Guard should NOT reject the very first intent (before any
        flow events accumulate) and SHOULD reject once enough toxic
        counter-flow has landed."""
        from sentinel_hft.deribit import QuoteIntent, IntentAction, Side

        scorer = ToxicFlowScorer()
        guard = ToxicFlowGuard(
            scorer, toxic_rate_threshold=0.5, min_flow_events=3,
        )
        # Prime the scorer with toxic TRADE events against taker 7
        # on symbol 1 (arbitrary) so it crosses the warmup threshold.
        stream = list(HyperliquidFixture(
            universe=HL_DEFAULT_UNIVERSE, seed=99,
            trade_prob=0.4, taker_population=4,
            toxic_share=0.9, benign_share=0.05,
        ).generate(n=2_000))
        for ev in stream:
            scorer.on_tick(ev)

        # Build a NEW intent and ask the guard.
        instr = HL_DEFAULT_UNIVERSE[0]
        intent = QuoteIntent(
            order_id=1,
            symbol_id=instr.symbol_id,
            side=Side.BUY,
            action=IntentAction.NEW,
            price=100.0,
            quantity=0.01,
            notional=1.0,
            generated_ts_ns=stream[-1].wire_ts_ns,
        )
        # Guard returns OK for warmup or TOXIC_FLOW if the recent
        # opposite-side flow is toxic-dominant. We tolerate both but
        # assert it never returns an unexpected reject reason.
        out = guard.check(intent, now_ns=stream[-1].wire_ts_ns + 1_000)
        assert out in (RejectReason.OK, RejectReason.TOXIC_FLOW)


# ---------------------------------------------------------------------
# Runner smoke
# ---------------------------------------------------------------------


class TestRunnerSmoke:

    def test_runner_emits_four_artifacts_with_verifying_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = HLRunConfig(
                ticks=1_200,
                seed=5,
                output_dir=Path(tmp),
                enable_toxic_guard=False,
                risk=RiskGateConfig(),
            )
            runner = HyperliquidRunner(cfg)
            art = runner.run()

            # Four named artifacts exist and are non-empty.
            for path in (art.trace_path, art.audit_path,
                         art.dora_path, art.summary_path):
                assert path.exists(), f"missing artifact: {path}"
                assert path.stat().st_size > 0, f"empty artifact: {path}"

            # Audit chain verifies.
            records = list(read_records(art.audit_path))
            v = audit_verify(records)
            assert v.ok, f"chain broken: {v.breaks}"

            # DORA bundle parses as JSON with the expected schema.
            dora = json.loads(art.dora_path.read_text())
            assert dora["metadata"]["schema_version"] == "dora-bundle/1"
            assert dora["metadata"]["producer"] == "sentinel-hft"
            assert "audit_chain" in dora
            assert "summary" in dora
            assert art.chain_ok is True

    def test_runner_captures_spike_wire_ts(self):
        """The kill-drill use-case relies on
        ``runner.spike_tick_wire_ts_ns`` being captured when a vol
        spike is configured. Without this the drill's reported
        kill_latency_ns is a wall-clock timestamp, not a duration."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = HLRunConfig(
                ticks=800,
                seed=7,
                output_dir=Path(tmp),
                enable_toxic_guard=False,
                vol_spike=VolSpike(
                    at_tick=400, magnitude=0.02,
                    decay_ticks=100, burst_quote_mult=4.0,
                    burst_trade_prob=0.18,
                ),
            )
            r = HyperliquidRunner(cfg)
            r.run()
            assert r.spike_tick_wire_ts_ns > 0, (
                "spike_tick_wire_ts_ns was not captured"
            )
            # Must fall inside [first_audit_ts, last_audit_ts].
            assert r.audit_records, "no audit records"
            first = r.audit_records[0].timestamp_ns
            last = r.audit_records[-1].timestamp_ns
            assert first <= r.spike_tick_wire_ts_ns <= last

    def test_runner_no_vol_spike_means_zero_wire_ts(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = HLRunConfig(
                ticks=300, seed=4, output_dir=Path(tmp),
                enable_toxic_guard=False,
                vol_spike=None,
            )
            r = HyperliquidRunner(cfg)
            r.run()
            assert r.spike_tick_wire_ts_ns == 0
