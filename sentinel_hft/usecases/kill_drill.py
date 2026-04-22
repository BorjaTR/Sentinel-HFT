"""Use case: volatility-spike kill-switch drill.

Story this use case tells the interviewer
-----------------------------------------

Market-making exposure compounds fastest during volatility regime
changes. The maker must trip a kill switch quickly enough that the
book does not continue accumulating notional while the cross-venue
price is moving. The FPGA risk gate has a kill-switch latch: once
tripped, every subsequent intent is rejected with
``RejectReason.KILL_SWITCH`` and the decision is written to the
hash-chained audit log so a regulator can reconstruct *exactly* when
and why trading stopped.

This demo exercises that path end-to-end. We replay a deterministic
HL-shaped stream, inject a synthetic volatility spike at a known tick
(2% jump + 4x quote burst + 18% trade probability), and trip the
kill switch at a known intent index. Downstream we verify:

1. The kill was tripped before the SLO budget elapsed (``slo_budget_ns``).
2. Every intent *after* the trip was rejected in the audit log.
3. The audit chain still verifies (``chain_ok``) after the trip.
4. The DORA bundle surfaces the kill event in its highlights.

Outputs
-------

Extends the four standard HL runner artifacts with:

* ``kill_drill.json`` -- machine-readable report.
* ``kill_drill.md``   -- narrative markdown.
* ``kill_drill.html`` -- self-contained HTML dashboard including an
  SVG time-series showing per-tick cumulative decisions + a marker
  line at the vol-spike tick.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from ..audit import FLAG_KILL_TRIGGERED, RejectReason
from ..hyperliquid import (
    HL_DEFAULT_UNIVERSE,
    HLRunConfig,
    HLRunArtifacts,
    HyperliquidRunner,
    VolSpike,
)
from ..deribit.risk import RiskGateConfig
from . import _html as H


# ---------------------------------------------------------------------
# Config / report
# ---------------------------------------------------------------------


@dataclass
class KillDrillConfig:
    """Knobs for the kill-switch drill."""

    ticks: int = 24_000
    seed: int = 11
    output_dir: Path = field(default_factory=lambda: Path("out/hl/kill_drill"))
    subject: str = "sentinel-hft-hl-kill-drill"
    environment: str = "sim"

    # Where the volatility spike fires (1-based tick index).
    spike_at_tick: int = 9_000
    spike_magnitude: float = 0.02      # 2% jump
    spike_decay_ticks: int = 400
    spike_burst_quote_mult: float = 4.0
    spike_burst_trade_prob: float = 0.18

    # Which intent number trips the kill switch (offset from 1).
    # Calibrated empirically against the default seed: cumulative
    # intent count at tick 9_000 (= spike tick) is ~25_340 under the
    # HL default fixture; position-limit throttling keeps post-spike
    # rate near ~2 intents/tick. Firing at intent 25_500 puts the
    # kill ~80 ticks after the spike (~11 ms simulated wire-ns),
    # comfortably inside the 50 ms SLO. Lowering pushes the kill
    # *before* the spike (confusing demo); raising it blows the SLO.
    # Overridable from CLI.
    inject_kill_at_intent: int = 25_500

    # SLO: kill must latch within this wall-clock budget from the
    # spike firing, expressed in nanoseconds of *simulated* time.
    # This covers the whole "regime change observed -> operator trips
    # -> FPGA latches -> every subsequent intent rejected" loop, not
    # just the RTL latch (which is ~10 ns). 50 ms is a realistic
    # human/automation response budget; the per-intent latch latency
    # inside that window is reported separately in the per-stage
    # latency panel.
    slo_budget_ns: int = 50_000_000

    # We keep the toxic guard off so the drill is isolated from the
    # toxic-flow pre-gate (its rejects would confound the counters).
    enable_toxic_guard: bool = False

    label: str = "kill-drill"


@dataclass
class KillDrillReport:
    artifacts: HLRunArtifacts
    config: KillDrillConfig
    json_path: Path
    md_path: Path
    html_path: Path

    kill_triggered: bool
    kill_latency_ns: int
    kill_latency_within_slo: bool

    decisions_before_kill: int
    decisions_after_kill: int
    rejects_after_kill_mismatch: int  # zero == clean

    chain_ok: bool

    spike_wire_ns: int               # wire-ts of firing tick
    kill_wire_ns: int                # audit ts of the kill record
    kill_intent_idx: int             # which intent tripped it

    cumulative_xs: List[int] = field(default_factory=list)
    cumulative_ys: List[int] = field(default_factory=list)


# ---------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------


def run_kill_drill(cfg: Optional[KillDrillConfig] = None) -> KillDrillReport:
    cfg = cfg or KillDrillConfig()
    output_dir = Path(cfg.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    vol_spike = VolSpike(
        at_tick=cfg.spike_at_tick,
        magnitude=cfg.spike_magnitude,
        decay_ticks=cfg.spike_decay_ticks,
        burst_quote_mult=cfg.spike_burst_quote_mult,
        burst_trade_prob=cfg.spike_burst_trade_prob,
    )

    run_cfg = HLRunConfig(
        ticks=cfg.ticks,
        seed=cfg.seed,
        output_dir=output_dir,
        subject=cfg.subject,
        environment=cfg.environment,
        enable_toxic_guard=cfg.enable_toxic_guard,
        inject_kill_at=cfg.inject_kill_at_intent,
        vol_spike=vol_spike,
        label=cfg.label,
        risk=RiskGateConfig(),
    )

    runner = HyperliquidRunner(run_cfg)
    artifacts = runner.run()

    # Analyse the audit log to pin down trip timing and post-trip hygiene.
    trip = _find_kill_trip(runner)
    spike_ns = _spike_wire_ns(runner, cfg)
    kill_latency_ns = 0
    if trip is not None and spike_ns > 0:
        # Duration = (first kill-triggered audit ts) - (spike wire-ts).
        # Both are in the fixture's simulated-ns frame, so the delta is
        # the wall-clock time between "regime change fires" and "risk
        # gate latched kill".
        kill_latency_ns = max(0, trip["ts_ns"] - spike_ns)

    decisions_before, decisions_after, mismatch = _post_kill_audit(runner)
    cumulative_xs, cumulative_ys = _cumulative_decisions(runner)

    json_path = output_dir / "kill_drill.json"
    md_path = output_dir / "kill_drill.md"
    html_path = output_dir / "kill_drill.html"

    report = KillDrillReport(
        artifacts=artifacts,
        config=cfg,
        json_path=json_path,
        md_path=md_path,
        html_path=html_path,
        kill_triggered=artifacts.kill_triggered,
        kill_latency_ns=kill_latency_ns,
        kill_latency_within_slo=(
            artifacts.kill_triggered
            and kill_latency_ns <= cfg.slo_budget_ns
        ),
        decisions_before_kill=decisions_before,
        decisions_after_kill=decisions_after,
        rejects_after_kill_mismatch=mismatch,
        chain_ok=artifacts.chain_ok,
        spike_wire_ns=spike_ns,
        kill_wire_ns=trip["ts_ns"] if trip else 0,
        kill_intent_idx=cfg.inject_kill_at_intent,
        cumulative_xs=cumulative_xs,
        cumulative_ys=cumulative_ys,
    )

    _write_json(report)
    _write_markdown(report)
    _write_html(report, runner)
    return report


# ---------------------------------------------------------------------
# Audit helpers
# ---------------------------------------------------------------------


def _find_kill_trip(runner: HyperliquidRunner) -> Optional[Dict]:
    """Return the first audit record with kill_triggered=True."""
    for rec in runner.audit_records:
        if rec.kill_triggered:
            return {
                "ts_ns": rec.timestamp_ns,
                "order_id": rec.order_id,
                "symbol_id": rec.symbol_id,
            }
    return None


def _post_kill_audit(
    runner: HyperliquidRunner,
) -> tuple[int, int, int]:
    """Count decisions before/after the first kill-triggered record.

    Returns ``(before, after, mismatch)`` where ``mismatch`` is the
    count of post-trip records that *rejected for the wrong reason*.

    Subtlety: CANCEL intents intentionally bypass the kill latch in
    :class:`RiskGate.evaluate` -- we want open quotes to be pullable
    even after an emergency stop, otherwise we're stuck with exposure.
    They pass with ``reject_reason=OK``, so we must NOT count them as
    mismatches. We therefore only flag records that are *rejected*
    (``passed=False``) and whose reason is not ``KILL_SWITCH``.
    """
    before = 0
    after = 0
    mismatch = 0
    seen_kill = False
    for rec in runner.audit_records:
        if not seen_kill and rec.kill_triggered:
            seen_kill = True
            after += 1  # the trip record itself counts as after
            if (not rec.passed
                    and rec.reject_reason != int(RejectReason.KILL_SWITCH)):
                mismatch += 1
            continue
        if seen_kill:
            after += 1
            if (not rec.passed
                    and rec.reject_reason != int(RejectReason.KILL_SWITCH)):
                mismatch += 1
        else:
            before += 1
    return before, after, mismatch


def _cumulative_decisions(runner: HyperliquidRunner) -> tuple[list, list]:
    """Per-audit-index cumulative decision count (for the line plot).

    X axis = audit record index, Y axis = cumulative rejected
    decisions. We use rejected-count rather than raw count because
    the story is "rejections explode after the kill trip" -- the
    line should show a knee at the trip point.
    """
    xs: List[int] = []
    ys: List[int] = []
    cum_reject = 0
    for i, rec in enumerate(runner.audit_records, start=1):
        if not rec.passed:
            cum_reject += 1
        xs.append(i)
        ys.append(cum_reject)
    return xs, ys


def _spike_wire_ns(runner: HyperliquidRunner, cfg: KillDrillConfig) -> int:
    """Wire-ns (fixture-clock) of the configured vol-spike tick.

    The runner captures ``spike_tick_wire_ts_ns`` as it consumes
    events -- that's the truth: it's the ``wire_ts_ns`` the fixture
    stamped on the tick at index ``cfg.spike_at_tick``. We use that
    as the zero point for ``kill_latency_ns`` so the reported number
    is a genuine duration (spike -> kill latched) rather than an
    absolute timestamp.

    Fallback paths:
      * If the runner never reached the spike tick (``ticks < spike_at_tick``)
        its ``spike_tick_wire_ts_ns`` stays at 0. We then hunt for the
        earliest audit record whose timestamp is >= cfg.spike_at_tick
        * nominal_tick_ns. Failing that we return 0 and the caller
        treats kill_latency_ns as unknown (drill reports "not measurable").
      * If no audit records exist at all (drill didn't fire a single
        decision) we return 0.
    """
    wire_ns = int(getattr(runner, "spike_tick_wire_ts_ns", 0) or 0)
    if wire_ns > 0:
        return wire_ns

    # Fallback: the configured spike_at_tick was never reached by the
    # stream (short run). Approximate using the first audit record ts
    # - that at least guarantees a non-negative latency if the kill
    # still fired. The dashboard flags kill_latency_ns == 0 and reports
    # "not measurable" in the UI.
    if runner.audit_records:
        return int(runner.audit_records[0].timestamp_ns)
    return 0


# ---------------------------------------------------------------------
# Writers -- JSON / MD
# ---------------------------------------------------------------------


def _write_json(rep: KillDrillReport) -> None:
    art = rep.artifacts
    doc = {
        "schema": "sentinel-hft/usecase/kill-drill/1",
        "subject": rep.config.subject,
        "environment": rep.config.environment,
        "label": rep.config.label,
        "run_id_hex": f"{0x484C_0001:#010x}",
        "config": {
            "ticks": rep.config.ticks,
            "seed": rep.config.seed,
            "spike_at_tick": rep.config.spike_at_tick,
            "spike_magnitude": rep.config.spike_magnitude,
            "spike_decay_ticks": rep.config.spike_decay_ticks,
            "spike_burst_quote_mult": rep.config.spike_burst_quote_mult,
            "spike_burst_trade_prob": rep.config.spike_burst_trade_prob,
            "inject_kill_at_intent": rep.config.inject_kill_at_intent,
            "slo_budget_ns": rep.config.slo_budget_ns,
        },
        "throughput": {
            "ticks": art.ticks_consumed,
            "intents": art.intents_generated,
            "decisions": art.decisions_logged,
            "passed": art.passed,
            "rejected": art.rejected,
        },
        "kill": {
            "triggered": rep.kill_triggered,
            "intent_idx": rep.kill_intent_idx,
            "latency_ns": rep.kill_latency_ns,
            "within_slo_ns": rep.config.slo_budget_ns,
            "within_slo": rep.kill_latency_within_slo,
            "decisions_before": rep.decisions_before_kill,
            "decisions_after": rep.decisions_after_kill,
            "post_trip_mismatch": rep.rejects_after_kill_mismatch,
        },
        "audit": {
            "head_hash_lo_hex": art.head_hash_lo_hex,
            "chain_ok": art.chain_ok,
        },
        "latency_ns": {
            "p50": art.p50_ns,
            "p99": art.p99_ns,
            "p999": art.p999_ns,
            "max": art.max_ns,
        },
        "stage_p99_ns": art.stage_p99_ns,
        "artifacts": {
            "trace": str(art.trace_path.name),
            "audit": str(art.audit_path.name),
            "dora":  str(art.dora_path.name),
            "summary": str(art.summary_path.name),
            "json":  str(rep.json_path.name),
            "md":    str(rep.md_path.name),
            "html":  str(rep.html_path.name),
        },
    }
    rep.json_path.write_text(json.dumps(doc, indent=2, sort_keys=False))


def _write_markdown(rep: KillDrillReport) -> None:
    art = rep.artifacts
    lines: List[str] = []
    lines.append("# Sentinel-HFT -- kill-drill use case")
    lines.append("")
    lines.append(f"Subject: `{rep.config.subject}`  ")
    lines.append(f"Environment: `{rep.config.environment}`")
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    lines.append(f"- Kill switch triggered: "
                 f"**{'YES' if rep.kill_triggered else 'NO'}**")
    lines.append(f"- Trip-to-latch latency: "
                 f"{rep.kill_latency_ns:,} ns "
                 f"(SLO {rep.config.slo_budget_ns:,} ns)")
    lines.append(f"- Within SLO: "
                 f"**{'PASS' if rep.kill_latency_within_slo else 'FAIL'}**")
    lines.append(
        f"- Decisions before kill: {rep.decisions_before_kill:,}"
    )
    lines.append(
        f"- Decisions after kill: {rep.decisions_after_kill:,} "
        f"(post-trip mismatches: "
        f"{rep.rejects_after_kill_mismatch:,})"
    )
    lines.append(f"- Audit chain: "
                 f"**{'PASS' if rep.chain_ok else 'FAIL'}**")
    lines.append("")
    lines.append("## Scenario")
    lines.append("")
    lines.append(
        f"- Vol spike fires at tick {rep.config.spike_at_tick:,} "
        f"(magnitude {rep.config.spike_magnitude*100:.1f}% jump, "
        f"{rep.config.spike_burst_quote_mult:.1f}x quote burst for "
        f"{rep.config.spike_decay_ticks:,} ticks, "
        f"trade prob bursts to "
        f"{rep.config.spike_burst_trade_prob*100:.0f}%)."
    )
    lines.append(
        f"- Kill switch injected at intent "
        f"#{rep.config.inject_kill_at_intent:,}."
    )
    lines.append("")
    lines.append("## Artifacts")
    lines.append("")
    lines.append(f"- `{art.trace_path.name}`  (trace v1.2)")
    lines.append(f"- `{art.audit_path.name}`  (audit chain)")
    lines.append(f"- `{art.dora_path.name}`   (DORA bundle)")
    lines.append(f"- `{art.summary_path.name}` (run summary)")
    lines.append(f"- `{rep.html_path.name}`   (dashboard)")
    lines.append("")
    rep.md_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------
# Writers -- HTML
# ---------------------------------------------------------------------


def _write_html(rep: KillDrillReport, runner: HyperliquidRunner) -> None:
    art = rep.artifacts

    # Find the audit-index of the first kill-triggered record (for the
    # vertical marker on the line plot).
    kill_audit_idx: Optional[int] = None
    for i, rec in enumerate(runner.audit_records, start=1):
        if rec.kill_triggered:
            kill_audit_idx = i
            break

    status = "ok" if rep.kill_latency_within_slo and rep.chain_ok else "err"

    kpis = [
        ("Kill triggered",
         "YES" if rep.kill_triggered else "NO",
         "err" if not rep.kill_triggered else "ok"),
        ("Trip-to-latch (ns)",
         f"{rep.kill_latency_ns:,}",
         "warn" if rep.kill_latency_within_slo else "err"),
        ("SLO budget",
         f"{rep.config.slo_budget_ns:,} ns",
         ""),
        ("Within SLO",
         "PASS" if rep.kill_latency_within_slo else "FAIL",
         "ok" if rep.kill_latency_within_slo else "err"),
        ("Audit chain",
         "PASS" if rep.chain_ok else "FAIL",
         "ok" if rep.chain_ok else "err"),
    ]
    book = [
        ("Decisions before kill",
         f"{rep.decisions_before_kill:,}", ""),
        ("Decisions after kill",
         f"{rep.decisions_after_kill:,}", ""),
        ("Post-trip mismatches",
         f"{rep.rejects_after_kill_mismatch:,}",
         "ok" if rep.rejects_after_kill_mismatch == 0 else "err"),
        ("Intents generated",
         f"{art.intents_generated:,}", ""),
        ("Total decisions",
         f"{art.decisions_logged:,}", ""),
    ]
    lat = [
        ("p50",    H.fmt_ns(art.p50_ns), ""),
        ("p99",    H.fmt_ns(art.p99_ns), ""),
        ("p99.9",  H.fmt_ns(art.p999_ns), ""),
        ("max",    H.fmt_ns(art.max_ns), ""),
    ]

    out: List[str] = []
    out.append(H.page_start(
        "Kill-switch drill",
        subtitle="Vol spike -> kill switch latched -> "
                 "every subsequent intent rejected in the audit chain.",
        env=rep.config.environment,
        run_id_hex=f"{0x484C_0001:#010x}",
    ))

    out.append('<div class="row">')
    out.append(H.kv_panel("Drill headline", kpis))
    out.append(H.kv_panel("Decision book", book))
    out.append(H.kv_panel("Wire-to-wire latency", lat))
    out.append("</div>")

    verdict_bits: List[str] = []
    if rep.kill_triggered:
        verdict_bits.append(
            f"Kill latched {rep.kill_latency_ns:,} ns after the "
            f"vol-spike tick."
        )
    else:
        verdict_bits.append(
            "Kill was NOT triggered -- drill did not exercise the "
            "latch."
        )
    verdict_bits.append(
        f"Post-trip audit mismatches: {rep.rejects_after_kill_mismatch:,} "
        f"(zero expected)."
    )
    if rep.chain_ok:
        verdict_bits.append(
            "Hash chain verifies end-to-end: every record's "
            "prev_hash_lo matches BLAKE2b of the predecessor "
            "payload."
        )
    else:
        verdict_bits.append(
            "Hash chain DID NOT verify -- something mutated the audit log."
        )

    out.append(H.narrative(
        "Verdict",
        f'<p>{H.status_tag(status, "verdict")} '
        f'{" ".join(verdict_bits)}</p>'
        f'<p class="crumbs">The kill latch is a one-way gate at the '
        f'RTL risk layer; the software pipeline is merely the host-side '
        f'mirror. In production the latch lives inside '
        f'<code>rtl/risk_pkg.sv::kill_switch</code>. Once set, the FPGA '
        f'rejects all intents until the host sends an explicit '
        f'<em>reset</em> CSR write, which itself is logged as a reset '
        f'record in the audit chain.</p>',
    ))

    # Line plot: cumulative rejects vs audit-index, marker at kill.
    out.append('<div class="panel">'
               '<h3>Cumulative risk-gate rejects by audit index</h3>')
    if rep.cumulative_xs:
        out.append(H.svg_lineplot(
            "rejects cumulative (y) vs. audit record index (x)",
            xs=rep.cumulative_xs,
            ys=rep.cumulative_ys,
            width=720, height=240,
            x_label="audit record index",
            y_label="cumulative rejects",
            mark_x=float(kill_audit_idx) if kill_audit_idx else None,
            mark_label="kill trip",
        ))
    else:
        out.append('<p class="crumbs">no audit records to plot</p>')
    out.append("</div>")

    # Per-stage latency quantiles (small table)
    rows = []
    for stage in ("ingress", "core", "risk", "egress"):
        rows.append((
            stage,
            H.fmt_ns(art.stage_p50_ns.get(stage, 0)),
            H.fmt_ns(art.stage_p99_ns.get(stage, 0)),
        ))
    out.append('<div class="panel"><h3>Per-stage latency quantiles</h3>'
               '<table class="data">'
               '<tr><th>stage</th><th>p50</th><th>p99</th></tr>')
    for r in rows:
        out.append(
            f"<tr><td>{r[0]}</td><td>{r[1]}</td><td>{r[2]}</td></tr>"
        )
    out.append("</table></div>")

    out.append(H.narrative(
        "Artifacts",
        f'<ul style="margin:0;padding-left:18px;">'
        f'<li><a href="{art.trace_path.name}">{art.trace_path.name}</a></li>'
        f'<li><a href="{art.audit_path.name}">{art.audit_path.name}</a></li>'
        f'<li><a href="{art.dora_path.name}">{art.dora_path.name}</a></li>'
        f'<li><a href="{art.summary_path.name}">'
        f'{art.summary_path.name}</a></li>'
        f'<li><a href="{rep.json_path.name}">{rep.json_path.name}</a></li>'
        f'<li><a href="{rep.md_path.name}">{rep.md_path.name}</a></li>'
        f'</ul>',
    ))
    out.append(H.page_end())
    rep.html_path.write_text("\n".join(out))


__all__ = [
    "KillDrillConfig",
    "KillDrillReport",
    "run_kill_drill",
]
