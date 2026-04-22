"""End-to-end Hyperliquid tick-to-trade runner.

This is the HL counterpart of
:class:`sentinel_hft.deribit.pipeline.DeribitDemo`: it consumes a
stream of :class:`HLTickEvent` objects and drives the full
book -> strategy -> *toxic-flow pre-gate* -> risk gate -> audit
pipeline.

Two design choices worth calling out:

1. **Pluggable tick source.** The use-case runners need to replay a
   fixture (for CI determinism), replay a captured binary file (for
   "this demo ran on real HL data yesterday" provenance), and in the
   future stream a live WebSocket. They all produce the same
   :class:`HLTickEvent`, so the runner accepts an ``Iterable`` and
   doesn't care where the events came from.

2. **Toxic-flow pre-gate.** :class:`ToxicFlowScorer` ingests every
   tick regardless of whether the strategy decides to quote, because
   its scorecards are built from *public trades* on the tape.
   Quote intents the strategy emits are first handed to a
   :class:`ToxicFlowGuard`; a reject here short-circuits the risk
   gate (no rate-limit token is consumed) and is logged in the audit
   chain with ``RejectReason.TOXIC_FLOW``. That keeps the audit
   stream the single source of truth: a regulator reading the chain
   can separate adverse-selection rejections from rate / position /
   kill rejections without needing a side-channel.

The latency budget is imported from the Deribit pipeline so the two
demos publish comparable numbers. The FPGA target (Alveo U55C at
100 MHz) is unchanged by the venue switch; only the adapter layer
differs.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator, List, Optional, Tuple

from ..adapters.sentinel_adapter_v12 import V12_STRUCT, V12_SIZE
from ..audit import (
    AuditLogger,
    AuditRecord,
    RejectReason,
    RiskDecision,
    build_bundle,
    dump_bundle,
    read_records,
    verify as audit_verify,
    write_records as write_audit_records,
)
from ..formats.file_header import FileHeader

from ..deribit.book import BookState, TopOfBook
from ..deribit.fixture import TickKind
from ..deribit.pipeline import (
    BUDGET_CORE,
    BUDGET_EGRESS,
    BUDGET_INGRESS,
    BUDGET_RISK,
    CLOCK_MHZ,
)
from ..deribit.risk import RiskGate, RiskGateConfig
from ..deribit.strategy import IntentAction, QuoteIntent, Side, SpreadMMStrategy

from ..compliance import ComplianceStack

from .fixture import HLTickEvent, HyperliquidFixture, TakerProfile, VolSpike
from .instruments import HL_DEFAULT_UNIVERSE, HyperliquidInstrument
from .scorer import ToxicFlowGuard, ToxicFlowScorer


# ---------------------------------------------------------------------
# Configuration / artifact records
# ---------------------------------------------------------------------


@dataclass
class HLRunConfig:
    """Operator-supplied knobs for one HL run.

    Defaults are tuned for a ~30 second synthetic session over three
    HL perps. A use-case runner overrides the fields it cares about:
    :mod:`sentinel_hft.usecases.kill_drill` sets ``vol_spike``,
    :mod:`sentinel_hft.usecases.toxic_flow` bumps ``toxic_share``,
    :mod:`sentinel_hft.usecases.latency` uses the defaults.
    """

    ticks: int = 20_000
    seed: int = 1
    risk: RiskGateConfig = field(default_factory=RiskGateConfig)
    output_dir: Optional[Path] = None
    subject: str = "sentinel-hft-hl-demo"
    environment: str = "sim"
    # run_id convention: 0x484C____ where 0x484C is ASCII "HL".
    run_id: int = 0x484C_0001

    # Fixture knobs (ignored when a pre-built event iterator is passed).
    taker_population: int = 12
    toxic_share: float = 0.25
    benign_share: float = 0.35
    trade_prob: float = 0.09
    vol_spike: Optional[VolSpike] = None

    # Toxic-flow guard knobs.
    enable_toxic_guard: bool = True
    toxic_rate_threshold: float = 0.55
    toxic_min_flow_events: int = 3
    toxic_horizon_ns: int = 5_000_000
    toxic_flow_window_ns: int = 500_000_000

    # Kill-drill knob: if set, fire the kill switch at this intent idx.
    inject_kill_at: Optional[int] = None

    # Compliance observer (Workstream 3). Attached to the runner so the
    # /sentinel/regulations UI can poll live counters. Purely
    # observational - never flips the risk decision.
    enable_compliance: bool = True
    compliance_cat_path: Optional[Path] = None

    # Optional per-run label carried through the summary / DORA bundle
    # metadata so a multi-session evidence pack can attribute each
    # input session.
    label: str = ""


@dataclass
class HLRunArtifacts:
    """Paths + head-line stats for a completed HL run.

    Extends the Deribit equivalent with toxic-flow counters and per-
    cohort taker classification counts so the UI dashboard can render
    the adverse-selection story without re-parsing the audit log.
    """

    trace_path: Path
    audit_path: Path
    dora_path: Path
    summary_path: Path

    ticks_consumed: int
    intents_generated: int
    decisions_logged: int
    passed: int
    rejected: int
    rejected_toxic: int
    kill_triggered: bool
    head_hash_lo_hex: str
    chain_ok: bool

    p50_ns: float
    p99_ns: float
    p999_ns: float
    max_ns: float

    taker_population: int
    takers_classified_toxic: int
    takers_classified_neutral: int
    takers_classified_benign: int

    label: str = ""

    # Per-stage latency quantiles (ns) for the HTML dashboard.
    stage_p50_ns: dict = field(default_factory=dict)
    stage_p99_ns: dict = field(default_factory=dict)

    # Optional hooks that use-cases can populate (kill-drill attaches
    # the tick index at which the vol spike fired; toxic_flow attaches
    # the highest-drift taker; latency attaches the bottleneck stage).
    notes: dict = field(default_factory=dict)


# ---------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------


class HyperliquidRunner:
    """End-to-end HL runner. One instance == one run.

    Use :meth:`run` for the common case (auto-build a fixture and
    emit all four artifacts). For use-cases that need finer control
    over the tick stream (e.g. replay a captured file) pass a
    pre-built iterator to :meth:`run_stream`.
    """

    def __init__(self, cfg: Optional[HLRunConfig] = None):
        self.cfg = cfg or HLRunConfig()
        self._rng = random.Random(self.cfg.seed ^ 0xBEEF_4C01)

        self._book = BookState()
        self._strategy = SpreadMMStrategy()
        self._gate = RiskGate(self.cfg.risk)
        self._audit = AuditLogger()

        self._scorer = ToxicFlowScorer(
            horizon_ns=self.cfg.toxic_horizon_ns,
            flow_window_ns=self.cfg.toxic_flow_window_ns,
        )
        self._guard: Optional[ToxicFlowGuard] = None
        if self.cfg.enable_toxic_guard:
            self._guard = ToxicFlowGuard(
                self._scorer,
                toxic_rate_threshold=self.cfg.toxic_rate_threshold,
                min_flow_events=self.cfg.toxic_min_flow_events,
            )

        self._trace_records: List[bytes] = []
        self._latencies_ns: List[int] = []
        self._stage_ns: dict = {
            "ingress": [], "core": [], "risk": [], "egress": [],
        }
        self._last_decision_ns: int = 0

        # Compliance layer (optional, observational).
        self._compliance: Optional[ComplianceStack] = None
        if self.cfg.enable_compliance:
            cat_path = (
                str(self.cfg.compliance_cat_path)
                if self.cfg.compliance_cat_path is not None
                else None
            )
            self._compliance = ComplianceStack(cat_output_path=cat_path)

        self.ticks_consumed = 0
        self.intents_generated = 0
        self.decisions_logged = 0
        self.rejected_toxic = 0

        # Wire-ts (ns) of the tick at which the configured vol spike
        # fires. Captured during ``run_stream`` so use-cases that need
        # to compute "kill-trip latency from spike" (e.g. kill-drill)
        # don't have to re-derive the fixture's timing. Stays at 0 when
        # no vol spike is configured.
        self.spike_tick_wire_ts_ns: int = 0

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def run(self) -> HLRunArtifacts:
        """Build a fixture from the config and run it."""
        fixture = HyperliquidFixture(
            universe=HL_DEFAULT_UNIVERSE,
            seed=self.cfg.seed,
            trade_prob=self.cfg.trade_prob,
            taker_population=self.cfg.taker_population,
            toxic_share=self.cfg.toxic_share,
            benign_share=self.cfg.benign_share,
            vol_spike=self.cfg.vol_spike,
        )
        stream = fixture.generate(n=self.cfg.ticks)
        return self.run_stream(stream)

    def run_stream(self, events: Iterable[HLTickEvent]) -> HLRunArtifacts:
        """Consume an arbitrary event stream and emit the artifact set."""
        output_dir = self.cfg.output_dir or Path.cwd() / "out" / "hl"
        output_dir.mkdir(parents=True, exist_ok=True)

        spike_tick = None
        if self.cfg.vol_spike is not None:
            spike_tick = int(self.cfg.vol_spike.at_tick)

        for ev in events:
            # Capture the spike tick's wire-ts BEFORE consuming it so
            # use-cases can reason about "kill latched N ns after the
            # regime change fired". We use tick index 1..N (ticks_consumed
            # is incremented after consume).
            if (spike_tick is not None
                    and self.ticks_consumed + 1 == spike_tick):
                self.spike_tick_wire_ts_ns = int(ev.wire_ts_ns)
            self._consume_tick(ev)
            self.ticks_consumed += 1

        # Write the four artifacts (same shape as Deribit demo).
        trace_path = output_dir / "traces.sst"
        audit_path = output_dir / "audit.aud"
        dora_path = output_dir / "dora.json"
        summary_path = output_dir / "summary.md"

        self._write_trace_file(trace_path)
        write_audit_records(audit_path, self._audit.records)

        dump_bundle(
            self._audit.records, dora_path,
            subject=self.cfg.subject,
            environment=self.cfg.environment,
        )

        # Flush the CAT NDJSON feed before we expose the snapshot
        # to the caller so the record count on disk matches the counter.
        if self._compliance is not None:
            self._compliance.close()

        verification = audit_verify(self._audit.records)
        stats = self._compute_stats()
        self._write_summary(summary_path, stats, verification)

        summ = self._scorer.summary()
        return HLRunArtifacts(
            trace_path=trace_path,
            audit_path=audit_path,
            dora_path=dora_path,
            summary_path=summary_path,
            ticks_consumed=self.ticks_consumed,
            intents_generated=self.intents_generated,
            decisions_logged=self.decisions_logged,
            passed=self._gate.passed,
            rejected=(
                self._gate.rejected_rate + self._gate.rejected_pos
                + self._gate.rejected_notional + self._gate.rejected_order_size
                + self._gate.rejected_kill + self.rejected_toxic
            ),
            rejected_toxic=self.rejected_toxic,
            kill_triggered=self._gate.kill.triggered,
            head_hash_lo_hex=self._audit.head_hash_lo.hex(),
            chain_ok=verification.ok,
            p50_ns=stats["p50_ns"],
            p99_ns=stats["p99_ns"],
            p999_ns=stats["p999_ns"],
            max_ns=stats["max_ns"],
            taker_population=summ["takers"],
            takers_classified_toxic=summ["toxic"],
            takers_classified_neutral=summ["neutral"],
            takers_classified_benign=summ["benign"],
            label=self.cfg.label,
            stage_p50_ns=stats["stage_p50_ns"],
            stage_p99_ns=stats["stage_p99_ns"],
        )

    # ------------------------------------------------------------------
    # Accessors (for use-cases / dashboards)
    # ------------------------------------------------------------------

    @property
    def audit_records(self) -> List[AuditRecord]:
        return self._audit.records

    @property
    def scorer(self) -> ToxicFlowScorer:
        return self._scorer

    @property
    def guard(self) -> Optional[ToxicFlowGuard]:
        return self._guard

    @property
    def gate(self) -> RiskGate:
        return self._gate

    @property
    def latencies_ns(self) -> List[int]:
        return self._latencies_ns

    @property
    def stage_ns(self) -> dict:
        return self._stage_ns

    @property
    def compliance(self) -> Optional[ComplianceStack]:
        return self._compliance

    # ------------------------------------------------------------------
    # Per-tick inner loop (mirrors DeribitDemo._consume_tick)
    # ------------------------------------------------------------------

    def _consume_tick(self, ev: HLTickEvent) -> None:
        # The scorer ingests every tick regardless of whether the
        # strategy decides to quote -- its scorecards are built from
        # public trades, which exist on QUOTE and TRADE alike (the BBO
        # is required to settle post-trade drift).
        self._scorer.on_tick(ev)

        # Compliance layer feeds on public trade prints so the
        # fat-finger reference price + OTR denominator track the tape.
        if (self._compliance is not None
                and ev.kind == TickKind.TRADE
                and ev.trade_price > 0):
            self._compliance.on_trade(
                ev.instrument.symbol_id,
                float(ev.trade_price),
                int(ev.wire_ts_ns),
            )

        d_ingress = BUDGET_INGRESS.sample(self._rng)
        t_ingress = ev.wire_ts_ns

        # Core (book update + strategy decision).
        d_core = BUDGET_CORE.sample(self._rng)
        deribit_ev = ev.as_deribit_event()
        book = self._book.apply(deribit_ev)
        core_ts = t_ingress + self._cycles_to_ns(d_ingress + d_core)
        intents = self._strategy.on_tick(book, core_ts)

        if not intents:
            # Still emit a trace for the tick so the histogram is
            # complete; flag "no order" in bit 15.
            d_egress = BUDGET_EGRESS.sample(self._rng) // 2
            self._append_trace_record(
                ev=ev, seq_no=ev.seq_no,
                t_ingress=t_ingress,
                t_egress=core_ts + self._cycles_to_ns(d_egress),
                d_ingress=d_ingress, d_core=d_core,
                d_risk=0, d_egress=d_egress,
                tx_id=0, flags=0x8000,
            )
            return

        for idx, intent in enumerate(intents):
            self.intents_generated += 1
            if (self.cfg.inject_kill_at is not None
                    and self.intents_generated == self.cfg.inject_kill_at):
                self._gate.kill.trip()

            # --- Toxic-flow pre-gate ------------------------------------
            d_risk = BUDGET_RISK.sample(self._rng)
            raw_now_ns = core_ts + self._cycles_to_ns(d_risk)
            now_ns = max(raw_now_ns, self._last_decision_ns + 1)
            self._last_decision_ns = now_ns

            toxic_reject = RejectReason.OK
            if (self._guard is not None
                    and intent.action == IntentAction.NEW):
                toxic_reject = self._guard.check(intent, now_ns)

            if toxic_reject == RejectReason.TOXIC_FLOW:
                # Bypass the main risk gate -- the pre-gate has the
                # final word and we log the decision in the audit
                # chain directly so the chain remains the single
                # source of truth.
                self.rejected_toxic += 1
                decision = self._build_toxic_decision(intent, now_ns)
                self._audit.log(decision)
                self.decisions_logged += 1
                if self._compliance is not None:
                    self._compliance.observe(
                        intent=intent, decision=decision, ts_ns=now_ns,
                    )
                d_egress = BUDGET_EGRESS.sample(self._rng) // 3
                t_egress = now_ns + self._cycles_to_ns(d_egress)
                self._record_latency(
                    t_ingress, t_egress,
                    d_ingress, d_core, d_risk, d_egress,
                )
                self._append_trace_record(
                    ev=ev, seq_no=ev.seq_no,
                    t_ingress=t_ingress, t_egress=t_egress,
                    d_ingress=d_ingress, d_core=d_core,
                    d_risk=d_risk, d_egress=d_egress,
                    tx_id=intent.order_id & 0xFFFF,
                    flags=0x0010 | 0x0040,   # reject bit + toxic bit
                )
                continue

            # --- Standard risk gate -------------------------------------
            decision = self._gate.evaluate(intent, now_ns)
            self._audit.log(decision)
            self.decisions_logged += 1

            if (decision.passed
                    and intent.action == IntentAction.NEW
                    and intent.quantity > 0):
                self._strategy.confirm_new(intent)

            if self._compliance is not None:
                self._compliance.observe(
                    intent=intent, decision=decision, ts_ns=now_ns,
                )

            d_egress = BUDGET_EGRESS.sample(self._rng)
            if not decision.passed:
                d_egress = d_egress // 3

            t_egress = now_ns + self._cycles_to_ns(d_egress)
            self._record_latency(
                t_ingress, t_egress, d_ingress, d_core, d_risk, d_egress,
            )

            flags = 0
            if decision.passed:
                flags |= 0x0001
            if decision.kill_triggered:
                flags |= 0x0002
            if decision.reject_reason != int(RejectReason.OK):
                flags |= 0x0010

            tx_id = intent.order_id & 0xFFFF
            self._append_trace_record(
                ev=ev, seq_no=ev.seq_no,
                t_ingress=t_ingress, t_egress=t_egress,
                d_ingress=d_ingress, d_core=d_core,
                d_risk=d_risk, d_egress=d_egress,
                tx_id=tx_id, flags=flags,
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_toxic_decision(
        self, intent: QuoteIntent, now_ns: int,
    ) -> RiskDecision:
        """Build an audit RiskDecision for a toxic-flow pre-gate reject.

        Mirrors :meth:`RiskGate._build` but bypasses counter mutation
        so the main gate's tallies stay accurate.
        """
        price_fp = int(round(intent.price * 1e8))
        notional_fp = int(round(intent.notional * 1e8))
        quantity_fp = int(round(intent.quantity * 1e6))
        long_qty_fp = int(round(self._gate.positions.long_qty * 1e6))
        short_qty_fp = int(round(self._gate.positions.short_qty * 1e6))
        net_fp = long_qty_fp - short_qty_fp
        notional_after_fp = int(round(self._gate.positions.notional * 1e8))
        return RiskDecision(
            timestamp_ns=now_ns,
            order_id=intent.order_id,
            symbol_id=intent.symbol_id,
            quantity=quantity_fp,
            price=price_fp,
            notional=notional_fp,
            passed=False,
            reject_reason=int(RejectReason.TOXIC_FLOW),
            kill_triggered=False,
            tokens_remaining=self._gate.bucket.remaining(),
            position_after=net_fp,
            notional_after=notional_after_fp,
        )

    def _record_latency(
        self, t_ingress: int, t_egress: int,
        d_ingress: int, d_core: int, d_risk: int, d_egress: int,
    ) -> None:
        total_ns = t_egress - t_ingress
        self._latencies_ns.append(total_ns)
        ns_per_cycle = 1000 // CLOCK_MHZ
        self._stage_ns["ingress"].append(d_ingress * ns_per_cycle)
        self._stage_ns["core"].append(d_core * ns_per_cycle)
        self._stage_ns["risk"].append(d_risk * ns_per_cycle)
        self._stage_ns["egress"].append(d_egress * ns_per_cycle)

    @staticmethod
    def _cycles_to_ns(cycles: int) -> int:
        return int(cycles * (1000 // CLOCK_MHZ))

    # ------------------------------------------------------------------
    # Artifact writers
    # ------------------------------------------------------------------

    def _append_trace_record(
        self, *, ev: HLTickEvent, seq_no: int,
        t_ingress: int, t_egress: int,
        d_ingress: int, d_core: int, d_risk: int, d_egress: int,
        tx_id: int, flags: int,
    ) -> None:
        record = V12_STRUCT.pack(
            2,
            ev.instrument.kind,
            ev.instrument.symbol_id,
            seq_no & 0xFFFFFFFF,
            t_ingress,
            t_egress,
            ev.host_ts_ns,
            tx_id,
            flags,
            d_ingress, d_core, d_risk, d_egress,
        )
        self._trace_records.append(record)

    def _write_trace_file(self, path: Path) -> None:
        header = FileHeader(
            version=2,
            record_size=V12_SIZE,
            clock_mhz=CLOCK_MHZ,
            run_id=self.cfg.run_id,
            record_count=len(self._trace_records),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            f.write(header.encode())
            for r in self._trace_records:
                f.write(r)

    # ------------------------------------------------------------------
    # Stats / summary
    # ------------------------------------------------------------------

    def _compute_stats(self) -> dict:
        lats = sorted(self._latencies_ns) or [0]
        n = len(lats)

        def q(data, p: float) -> float:
            if not data:
                return 0.0
            idx = min(len(data) - 1, max(0, int(round(p * (len(data) - 1)))))
            return float(data[idx])

        stage_p50: dict = {}
        stage_p99: dict = {}
        for name, vals in self._stage_ns.items():
            s = sorted(vals)
            stage_p50[name] = q(s, 0.50)
            stage_p99[name] = q(s, 0.99)

        return {
            "count": n,
            "p50_ns": q(lats, 0.50),
            "p90_ns": q(lats, 0.90),
            "p99_ns": q(lats, 0.99),
            "p999_ns": q(lats, 0.999),
            "max_ns": float(max(lats)) if lats else 0.0,
            "min_ns": float(min(lats)) if lats else 0.0,
            "mean_ns": sum(lats) / n if n else 0.0,
            "stage_p50_ns": stage_p50,
            "stage_p99_ns": stage_p99,
        }

    def _write_summary(self, path: Path, stats: dict, verification) -> None:
        g = self._gate
        total_dec = max(1, g.total + self.rejected_toxic)
        summ = self._scorer.summary()
        md = []
        md.append("# Sentinel-HFT Hyperliquid demo")
        md.append("")
        md.append(f"Run ID: `{self.cfg.run_id:#010x}`  ")
        md.append(f"Subject: `{self.cfg.subject}`  ")
        md.append(f"Environment: `{self.cfg.environment}`")
        if self.cfg.label:
            md.append(f"Label: `{self.cfg.label}`")
        md.append("")
        md.append("## Throughput")
        md.append("")
        md.append(f"- Ticks consumed: **{self.ticks_consumed:,}**")
        md.append(f"- Quote intents generated: **{self.intents_generated:,}**")
        md.append(f"- Risk decisions logged: **{self.decisions_logged:,}**")
        md.append("")
        md.append("## Latency (wire-to-wire)")
        md.append("")
        md.append(f"- p50:   {stats['p50_ns']:,.0f} ns "
                  f"({stats['p50_ns']/1000:,.2f} us)")
        md.append(f"- p99:   {stats['p99_ns']:,.0f} ns "
                  f"({stats['p99_ns']/1000:,.2f} us)")
        md.append(f"- p99.9: {stats['p999_ns']:,.0f} ns "
                  f"({stats['p999_ns']/1000:,.2f} us)")
        md.append(f"- max:   {stats['max_ns']:,.0f} ns "
                  f"({stats['max_ns']/1000:,.2f} us)")
        md.append("")
        md.append("### Per-stage p99 (ns)")
        md.append("")
        for name, val in stats["stage_p99_ns"].items():
            md.append(f"- {name:<8s} {val:,.0f} ns")
        md.append("")
        md.append("## Risk-gate outcome")
        md.append("")
        md.append(f"- Passed:                 **{g.passed:,}** "
                  f"({g.passed/total_dec:.2%})")
        md.append(f"- Rejected (toxic flow):  {self.rejected_toxic:,}")
        md.append(f"- Rejected (rate-limit):  {g.rejected_rate:,}")
        md.append(f"- Rejected (position):    {g.rejected_pos:,}")
        md.append(f"- Rejected (notional):    {g.rejected_notional:,}")
        md.append(f"- Rejected (order-size):  {g.rejected_order_size:,}")
        md.append(f"- Rejected (kill):        {g.rejected_kill:,}")
        md.append("")
        md.append(f"- Final long:    {g.positions.long_qty:,.2f}")
        md.append(f"- Final short:   {g.positions.short_qty:,.2f}")
        md.append(f"- Final notional: {g.positions.notional:,.0f}")
        md.append(f"- Kill switch:   "
                  f"{'**YES**' if g.kill.triggered else 'no'}")
        md.append("")
        md.append("## Adverse-selection scorecard")
        md.append("")
        md.append(f"- Counterparties observed: {summ['takers']:,}")
        md.append(f"- Learned TOXIC:   {summ['toxic']:,}")
        md.append(f"- Learned NEUTRAL: {summ['neutral']:,}")
        md.append(f"- Learned BENIGN:  {summ['benign']:,}")
        md.append(f"- Open outcomes:   {summ['open_outcomes']:,}")
        md.append(f"- Flow events:     {summ['flow_events']:,}")
        md.append("")
        md.append("## Audit chain")
        md.append("")
        md.append(f"- Records: {len(self._audit.records):,}")
        md.append(f"- Head hash (lo 128): `{self._audit.head_hash_lo.hex()}`")
        md.append(f"- Verification: "
                  f"{'PASS' if verification.ok else 'FAIL'} "
                  f"({verification.verified_records} / "
                  f"{verification.total_records})")
        md.append("")
        md.append("## Artifacts")
        md.append("")
        md.append("- `traces.sst`  -- v1.2 trace with per-stage attribution")
        md.append("- `audit.aud`   -- hash-chained risk-gate log")
        md.append("- `dora.json`   -- DORA-aligned evidence bundle")
        md.append("- `summary.md`  -- this file")
        md.append("")
        path.write_text("\n".join(md))


# ---------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------


def run_hl(
    *, ticks: int = 20_000, seed: int = 1,
    output_dir: Optional[Path] = None,
    subject: str = "sentinel-hft-hl-demo",
    environment: str = "sim",
    toxic_share: float = 0.25,
    benign_share: float = 0.35,
    vol_spike: Optional[VolSpike] = None,
    inject_kill_at: Optional[int] = None,
    enable_toxic_guard: bool = True,
    risk: Optional[RiskGateConfig] = None,
    label: str = "",
) -> HLRunArtifacts:
    """Run a default HL session and return the artifact record."""
    cfg = HLRunConfig(
        ticks=ticks, seed=seed, output_dir=output_dir,
        subject=subject, environment=environment,
        toxic_share=toxic_share, benign_share=benign_share,
        vol_spike=vol_spike, inject_kill_at=inject_kill_at,
        enable_toxic_guard=enable_toxic_guard,
        risk=risk or RiskGateConfig(),
        label=label,
    )
    return HyperliquidRunner(cfg).run()


__all__ = [
    "HLRunConfig",
    "HLRunArtifacts",
    "HyperliquidRunner",
    "run_hl",
]
