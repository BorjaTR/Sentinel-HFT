"""End-to-end Deribit LD4 demo pipeline.

Consumes a tick stream, runs it through book -> strategy -> risk ->
audit, and emits four artifacts:

1. ``traces.sst``  -- v1.2 trace file with per-stage attribution.
2. ``audit.aud``   -- tamper-evident risk-gate audit log.
3. ``dora.json``   -- DORA-aligned evidence bundle.
4. ``summary.md``  -- human-readable run summary.

Per-stage latencies are reported in FPGA cycles so they match what the
synthesised pipeline would produce at 100 MHz. The Python implementation
isn't fast enough to measure ns-scale timing, so we draw per-stage
costs from a small cycle-budget model (see :class:`_LatencyBudget`)
calibrated to an Alveo U55C target. The *shape* of the latency
distribution -- p50, tail, risk-gate rejection proportion -- is the
artifact we want to demonstrate, not Python's native wall clock.
"""

from __future__ import annotations

import json
import math
import random
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

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
from ..formats.file_header import FileHeader, HEADER_SIZE, MAGIC
from ..adapters.sentinel_adapter_v12 import V12_STRUCT, V12_SIZE

from .book import BookState, TopOfBook
from .fixture import DeribitFixture, TickEvent, TickKind
from .instruments import DEFAULT_UNIVERSE, Instrument, InstrumentKind
from .risk import RiskGate, RiskGateConfig
from .strategy import QuoteIntent, Side, SpreadMMStrategy


# ---------------------------------------------------------------------
# Latency budget
# ---------------------------------------------------------------------


CLOCK_MHZ = 100  # Alveo U55C in this design runs risk-gate at 100 MHz


@dataclass
class _LatencyBudget:
    """Cycle-budget model for one pipeline stage.

    Base is the expected cycle count under ideal conditions; jitter
    is a per-event lognormal (sigma) adding tail. A small burst_prob
    injects a large multi-cycle stall (cache miss on the host shim,
    or backpressure from the MAC tx FIFO).
    """

    base_cycles: int
    sigma: float = 0.15
    burst_prob: float = 0.01
    burst_factor: float = 4.0

    def sample(self, rng: random.Random) -> int:
        mu = math.log(max(1, self.base_cycles))
        val = max(1, int(rng.lognormvariate(mu, self.sigma)))
        if rng.random() < self.burst_prob:
            val = int(val * (1.0 + rng.expovariate(1.0 / self.burst_factor)))
        return val


# Calibrated against published Alveo U55C reference numbers for a
# parse/match/risk pipeline clocked at 100 MHz.
BUDGET_INGRESS = _LatencyBudget(base_cycles=35, sigma=0.12, burst_prob=0.005)
BUDGET_CORE = _LatencyBudget(base_cycles=55, sigma=0.18, burst_prob=0.02,
                             burst_factor=3.0)
BUDGET_RISK = _LatencyBudget(base_cycles=18, sigma=0.10, burst_prob=0.005)
BUDGET_EGRESS = _LatencyBudget(base_cycles=32, sigma=0.15, burst_prob=0.01)


# ---------------------------------------------------------------------
# Public config / artifact records
# ---------------------------------------------------------------------


@dataclass
class DemoConfig:
    """Operator-supplied knobs for a demo run."""

    ticks: int = 20_000
    seed: int = 1
    risk: RiskGateConfig = field(default_factory=RiskGateConfig)
    output_dir: Optional[Path] = None
    subject: str = "sentinel-hft-demo"
    environment: str = "sim"
    run_id: int = 0x00DECAF0
    inject_kill_at: Optional[int] = None
    inject_rate_burst: bool = True

    # Fraction of cancels that model a fill instead of a clean cancel.
    # A "filled" cancel does not release exposure, so over time the
    # book accumulates directional risk and eventually trips the
    # position / notional limits -- a realistic market-making failure
    # mode that the demo must exercise.
    fill_prob: float = 0.04


@dataclass
class DemoArtifacts:
    """Paths + head-line stats for a completed demo run."""

    trace_path: Path
    audit_path: Path
    dora_path: Path
    summary_path: Path

    ticks_consumed: int
    intents_generated: int
    decisions_logged: int
    passed: int
    rejected: int
    kill_triggered: bool
    head_hash_lo_hex: str
    chain_ok: bool
    p50_ns: float
    p99_ns: float
    p999_ns: float
    max_ns: float


# ---------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------


class DeribitDemo:
    """End-to-end runner. One instance == one run."""

    def __init__(self, cfg: Optional[DemoConfig] = None):
        self.cfg = cfg or DemoConfig()
        self._rng = random.Random(self.cfg.seed ^ 0xDEAD_BEEF)

        self._book = BookState()
        self._strategy = SpreadMMStrategy()
        self._gate = RiskGate(self.cfg.risk)
        self._audit = AuditLogger()

        self._trace_records: List[bytes] = []
        self._latencies_ns: List[int] = []

        # The risk gate is a single serial datapath; decision timestamps
        # must be monotonically non-decreasing even when per-stage
        # cycle bursts reorder the arithmetic. We clamp here.
        self._last_decision_ns: int = 0

        self.ticks_consumed = 0
        self.intents_generated = 0
        self.decisions_logged = 0

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> DemoArtifacts:
        output_dir = self.cfg.output_dir or Path.cwd() / "out" / "deribit"
        output_dir.mkdir(parents=True, exist_ok=True)

        fixture = DeribitFixture(
            universe=DEFAULT_UNIVERSE,
            seed=self.cfg.seed,
        )

        for ev in fixture.generate(n=self.cfg.ticks):
            self._consume_tick(ev)
            self.ticks_consumed += 1

        # Write the four artifacts.
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

        # Verify chain before writing summary so we can embed the result.
        verification = audit_verify(self._audit.records)

        stats = self._compute_stats()
        self._write_summary(summary_path, stats, verification)

        return DemoArtifacts(
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
                + self._gate.rejected_kill
            ),
            kill_triggered=self._gate.kill.triggered,
            head_hash_lo_hex=self._audit.head_hash_lo.hex(),
            chain_ok=verification.ok,
            p50_ns=stats["p50_ns"],
            p99_ns=stats["p99_ns"],
            p999_ns=stats["p999_ns"],
            max_ns=stats["max_ns"],
        )

    # ------------------------------------------------------------------
    # Per-tick inner loop
    # ------------------------------------------------------------------

    def _consume_tick(self, ev: TickEvent) -> None:
        # --- Ingress (FPGA MAC -> parser) ----------------------------
        d_ingress = BUDGET_INGRESS.sample(self._rng)
        t_ingress = ev.wire_ts_ns

        # --- Core (book update + strategy decision) ------------------
        d_core = BUDGET_CORE.sample(self._rng)
        book = self._book.apply(ev)
        # Strategy time advance: from t_ingress + d_ingress cycles.
        core_ts = t_ingress + self._cycles_to_ns(d_ingress + d_core)
        intents = self._strategy.on_tick(book, core_ts)
        if not intents:
            # Still emit a trace record for the tick -- the pipeline
            # was exercised even though no order was generated.
            d_risk = 0
            d_egress = BUDGET_EGRESS.sample(self._rng) // 2
            self._append_trace_record(
                ev=ev, seq_no=ev.seq_no,
                t_ingress=t_ingress,
                t_egress=core_ts + self._cycles_to_ns(d_egress),
                d_ingress=d_ingress, d_core=d_core,
                d_risk=d_risk, d_egress=d_egress,
                tx_id=0, flags=0x8000,  # "no order" flag
            )
            return

        # Optional kill injection tied to order counter, not tick idx.
        from .strategy import IntentAction as _IntentAction  # local import

        for idx, intent in enumerate(intents):
            self.intents_generated += 1
            if (self.cfg.inject_kill_at is not None
                    and self.intents_generated == self.cfg.inject_kill_at):
                self._gate.kill.trip()

            # Model fills: with small probability, a cancel actually
            # races a fill and does not release exposure. We simply
            # skip this cancel from being emitted to the gate -- the
            # exposure it would have released stays on the book,
            # which is exactly what a race with a fill looks like.
            if (intent.action == _IntentAction.CANCEL
                    and self._rng.random() < self.cfg.fill_prob):
                # We still count it as generated / logged so the trace
                # has a record, but we tag the intent as a fill-race
                # by forcing rejection through a synthetic zero-tokens
                # path: set action to NEW and let the rate limiter or
                # position gate catch it if it would exceed limits.
                # To keep semantics honest: leave the CANCEL intent as
                # such but skip the release step downstream. We model
                # that by decrementing the intent quantity/notional to
                # zero BEFORE release, then emit the cancel. The net
                # effect is: the cancel passes the gate but releases
                # nothing, so the filled side stays on the book.
                intent.quantity = 0.0
                intent.notional = 0.0

            # --- Risk ---------------------------------------------------
            d_risk = BUDGET_RISK.sample(self._rng)
            if self.cfg.inject_rate_burst and self.ticks_consumed > 0 \
                    and self.ticks_consumed % 2500 == 0 and idx == 0:
                # Occasional burst to exercise rate-limit rejections.
                for _ in range(6):
                    self._gate.bucket.try_consume(core_ts, 80)

            raw_now_ns = core_ts + self._cycles_to_ns(d_risk)
            # Clamp to monotonic: the risk gate is a single serial
            # datapath so its decision timestamps cannot go backwards.
            now_ns = max(raw_now_ns, self._last_decision_ns + 1)
            self._last_decision_ns = now_ns

            decision = self._gate.evaluate(intent, now_ns)
            self._audit.log(decision)
            self.decisions_logged += 1

            # Keep the strategy in sync with the gate: only orders the
            # gate accepted go on the strategy's "outstanding" list.
            if (decision.passed
                    and intent.action == _IntentAction.NEW
                    and intent.quantity > 0):
                self._strategy.confirm_new(intent)

            # --- Egress -------------------------------------------------
            d_egress = BUDGET_EGRESS.sample(self._rng)
            if not decision.passed:
                d_egress = d_egress // 3  # short-circuit on reject

            t_egress = now_ns + self._cycles_to_ns(d_egress)
            total_ns = t_egress - t_ingress
            self._latencies_ns.append(total_ns)

            flags = 0
            if decision.passed:
                flags |= 0x0001
            if decision.kill_triggered:
                flags |= 0x0002
            if decision.reject_reason != int(RejectReason.OK):
                flags |= 0x0010

            # Stash 16-bit tx_id we can correlate with order_id in logs.
            tx_id = intent.order_id & 0xFFFF

            self._append_trace_record(
                ev=ev, seq_no=ev.seq_no,
                t_ingress=t_ingress,
                t_egress=t_egress,
                d_ingress=d_ingress, d_core=d_core,
                d_risk=d_risk, d_egress=d_egress,
                tx_id=tx_id, flags=flags,
            )

    # ------------------------------------------------------------------

    @staticmethod
    def _cycles_to_ns(cycles: int) -> int:
        # 100 MHz -> 10 ns per cycle.
        return int(cycles * (1000 // CLOCK_MHZ))

    # ------------------------------------------------------------------
    # Artifact writers
    # ------------------------------------------------------------------

    def _append_trace_record(
        self, *, ev: TickEvent, seq_no: int,
        t_ingress: int, t_egress: int,
        d_ingress: int, d_core: int, d_risk: int, d_egress: int,
        tx_id: int, flags: int,
    ) -> None:
        """Pack a v1.2 trace record for this tick."""
        record = V12_STRUCT.pack(
            2,                  # version (v1.2)
            ev.instrument.kind, # record_type (use instrument kind)
            ev.instrument.symbol_id,  # core_id hijacked as symbol id
            seq_no & 0xFFFFFFFF,
            t_ingress,
            t_egress,
            ev.host_ts_ns,      # t_host
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

        def q(p: float) -> float:
            if n == 0:
                return 0.0
            idx = min(n - 1, max(0, int(round(p * (n - 1)))))
            return float(lats[idx])

        return {
            "count": n,
            "p50_ns": q(0.50),
            "p90_ns": q(0.90),
            "p99_ns": q(0.99),
            "p999_ns": q(0.999),
            "max_ns": float(max(lats)) if lats else 0.0,
            "min_ns": float(min(lats)) if lats else 0.0,
            "mean_ns": sum(lats) / n if n else 0.0,
        }

    def _write_summary(self, path: Path, stats: dict, verification) -> None:
        g = self._gate
        total_dec = max(1, g.total)
        md = []
        md.append("# Sentinel-HFT Deribit LD4 demo")
        md.append("")
        md.append(f"Run ID: `{self.cfg.run_id:#010x}`  ")
        md.append(f"Subject: `{self.cfg.subject}`  ")
        md.append(f"Environment: `{self.cfg.environment}`")
        md.append("")
        md.append("## Throughput")
        md.append("")
        md.append(f"- Ticks consumed: **{self.ticks_consumed:,}**")
        md.append(f"- Quote intents generated: **{self.intents_generated:,}**")
        md.append(f"- Risk decisions logged: **{self.decisions_logged:,}**")
        md.append("")
        md.append("## Latency (wire-to-wire)")
        md.append("")
        md.append(
            f"- p50:  {stats['p50_ns']:,.0f} ns "
            f"({stats['p50_ns']/1000:,.2f} us)"
        )
        md.append(
            f"- p99:  {stats['p99_ns']:,.0f} ns "
            f"({stats['p99_ns']/1000:,.2f} us)"
        )
        md.append(
            f"- p99.9: {stats['p999_ns']:,.0f} ns "
            f"({stats['p999_ns']/1000:,.2f} us)"
        )
        md.append(
            f"- max:  {stats['max_ns']:,.0f} ns "
            f"({stats['max_ns']/1000:,.2f} us)"
        )
        md.append("")
        md.append("## Risk-gate outcome")
        md.append("")
        md.append(f"- Passed: **{g.passed:,}** "
                  f"({g.passed/total_dec:.2%})")
        md.append(f"- Rejected (rate-limit): {g.rejected_rate:,}")
        md.append(f"- Rejected (position):   {g.rejected_pos:,}")
        md.append(f"- Rejected (notional):   {g.rejected_notional:,}")
        md.append(f"- Rejected (order-size): {g.rejected_order_size:,}")
        md.append(f"- Rejected (kill):       {g.rejected_kill:,}")
        md.append("")
        md.append(f"- Final long: {g.positions.long_qty:,.2f}  "
                  f"short: {g.positions.short_qty:,.2f}  "
                  f"notional: {g.positions.notional:,.0f}")
        md.append(f"- Kill switch triggered: "
                  f"{'**YES**' if g.kill.triggered else 'no'}")
        md.append("")
        md.append("## Audit chain")
        md.append("")
        md.append(f"- Records: {len(self._audit.records):,}")
        md.append(f"- Head hash (lo 128): `{self._audit.head_hash_lo.hex()}`")
        md.append(f"- Verification: "
                  f"{'PASS' if verification.ok else 'FAIL'} "
                  f"({verification.verified_records} / "
                  f"{verification.total_records})")
        if verification.breaks:
            md.append(f"- Breaks: {len(verification.breaks)}")
            for b in verification.breaks[:5]:
                md.append(f"    - seq {b.seq_no}: {b.kind.value} -- "
                          f"{b.detail}")
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


def run_demo(
    *, ticks: int = 20_000, seed: int = 1,
    output_dir: Optional[Path] = None,
    subject: str = "sentinel-hft-demo",
    environment: str = "sim",
    inject_kill_at: Optional[int] = None,
    risk: Optional[RiskGateConfig] = None,
) -> DemoArtifacts:
    """Run a demo with sensible defaults and return the artifact record."""
    cfg = DemoConfig(
        ticks=ticks, seed=seed, output_dir=output_dir,
        subject=subject, environment=environment,
        inject_kill_at=inject_kill_at,
        risk=risk or RiskGateConfig(),
    )
    demo = DeribitDemo(cfg)
    return demo.run()


__all__ = [
    "CLOCK_MHZ",
    "DemoConfig",
    "DemoArtifacts",
    "DeribitDemo",
    "run_demo",
]
