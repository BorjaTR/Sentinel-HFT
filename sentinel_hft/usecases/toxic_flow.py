"""Use case: toxic-flow adverse-selection scoring + pre-gate blocking.

Story this use case tells the interviewer
-----------------------------------------

A market-maker posts two-sided quotes on HL perps. Some takers pick
off stale quotes systematically -- they lift the ask just before the
mid prints higher, and hit the bid just before the mid prints lower.
That asymmetry shows up in post-trade price drift, which accrues
silently as negative PnL on the maker's book ("adverse selection" or
"toxic flow").

The demo replays a deterministic HL-shaped stream with a toxic-heavy
taker population (45% TOXIC, 20% BENIGN, 35% NEUTRAL by default), lets
:class:`~sentinel_hft.hyperliquid.scorer.ToxicFlowScorer` learn each
wallet's post-trade drift, and has
:class:`~sentinel_hft.hyperliquid.scorer.ToxicFlowGuard` block NEW
quote intents exposed to concentrated toxic flow. Every reject shows
up in the hash-chained audit log as
``RejectReason.TOXIC_FLOW`` (0x07), so the DORA evidence bundle
surfaces adverse-selection rejections as a first-class category
alongside rate / position / notional rejects.

Outputs
-------

The runner writes three files to ``output_dir`` in addition to the
four standard HL runner artifacts (traces / audit / DORA / summary):

* ``toxic_flow.json`` -- machine-readable report (for CI diffing).
* ``toxic_flow.md``   -- narrative markdown (for the repo).
* ``toxic_flow.html`` -- self-contained HTML dashboard with inline
  SVG charts (for an interviewer).

Run by :func:`run_toxic_flow` or via the ``sentinel-hft hl
toxic-flow`` CLI command.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..audit import FLAG_TOXIC_FLOW, RejectReason
from ..hyperliquid import (
    HL_DEFAULT_UNIVERSE,
    HLRunConfig,
    HLRunArtifacts,
    HyperliquidRunner,
    TakerProfile,
)
from ..deribit.risk import RiskGateConfig
from . import _html as H


# ---------------------------------------------------------------------
# Config / report
# ---------------------------------------------------------------------


@dataclass
class ToxicFlowConfig:
    """Knobs for the toxic-flow demo.

    Defaults build a toxic-heavy population so the guard has something
    interesting to reject in a 30-second replay. The risk gate's
    per-symbol notional limits are lifted slightly so we're not
    conflating adverse-selection rejects with notional caps.
    """

    ticks: int = 30_000
    seed: int = 7
    output_dir: Path = field(default_factory=lambda: Path("out/hl/toxic_flow"))
    subject: str = "sentinel-hft-hl-toxic-flow"
    environment: str = "sim"

    taker_population: int = 16
    toxic_share: float = 0.45
    benign_share: float = 0.20
    trade_prob: float = 0.14

    toxic_rate_threshold: float = 0.55
    toxic_min_flow_events: int = 3

    # How many top-drift takers / symbols to surface in the HTML.
    top_n_takers: int = 10

    label: str = "toxic-flow"


@dataclass
class ToxicFlowReport:
    """Machine-readable summary of a toxic-flow run."""

    artifacts: HLRunArtifacts
    config: ToxicFlowConfig
    json_path: Path
    md_path: Path
    html_path: Path

    # Headline stats surfaced on the dashboard cover.
    ticks: int
    intents: int
    toxic_rejects: int
    audit_chain_ok: bool
    taker_population: int
    classified_toxic: int
    classified_neutral: int
    classified_benign: int

    per_symbol_toxic_rejects: Dict[str, int] = field(default_factory=dict)
    per_symbol_passed: Dict[str, int] = field(default_factory=dict)
    top_takers: List[Dict] = field(default_factory=list)


# ---------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------


def run_toxic_flow(cfg: Optional[ToxicFlowConfig] = None) -> ToxicFlowReport:
    """Execute one toxic-flow session and emit JSON + MD + HTML."""
    cfg = cfg or ToxicFlowConfig()
    output_dir = Path(cfg.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    run_cfg = HLRunConfig(
        ticks=cfg.ticks,
        seed=cfg.seed,
        output_dir=output_dir,
        subject=cfg.subject,
        environment=cfg.environment,
        taker_population=cfg.taker_population,
        toxic_share=cfg.toxic_share,
        benign_share=cfg.benign_share,
        trade_prob=cfg.trade_prob,
        enable_toxic_guard=True,
        toxic_rate_threshold=cfg.toxic_rate_threshold,
        toxic_min_flow_events=cfg.toxic_min_flow_events,
        label=cfg.label,
        risk=RiskGateConfig(),
    )

    runner = HyperliquidRunner(run_cfg)
    artifacts = runner.run()

    # Enrich with per-symbol / per-taker stats pulled from live runner state.
    per_symbol_toxic, per_symbol_passed = _per_symbol_counters(runner)
    top_takers = _top_takers(runner, cfg.top_n_takers)

    json_path = output_dir / "toxic_flow.json"
    md_path = output_dir / "toxic_flow.md"
    html_path = output_dir / "toxic_flow.html"

    report = ToxicFlowReport(
        artifacts=artifacts,
        config=cfg,
        json_path=json_path,
        md_path=md_path,
        html_path=html_path,
        ticks=artifacts.ticks_consumed,
        intents=artifacts.intents_generated,
        toxic_rejects=artifacts.rejected_toxic,
        audit_chain_ok=artifacts.chain_ok,
        taker_population=artifacts.taker_population,
        classified_toxic=artifacts.takers_classified_toxic,
        classified_neutral=artifacts.takers_classified_neutral,
        classified_benign=artifacts.takers_classified_benign,
        per_symbol_toxic_rejects=per_symbol_toxic,
        per_symbol_passed=per_symbol_passed,
        top_takers=top_takers,
    )

    _write_json(report)
    _write_markdown(report)
    _write_html(report, runner)

    return report


# ---------------------------------------------------------------------
# Enrichment helpers
# ---------------------------------------------------------------------


def _per_symbol_counters(
    runner: HyperliquidRunner,
) -> Tuple[Dict[str, int], Dict[str, int]]:
    """Break out TOXIC_FLOW rejects vs passed decisions by symbol.

    Uses the audit records directly -- they are the source of truth
    the regulator reads, so we derive the dashboard numbers from them
    rather than from per-gate counters.
    """
    by_id = {ins.symbol_id: ins.symbol for ins in HL_DEFAULT_UNIVERSE}
    tox: Dict[str, int] = {name: 0 for name in by_id.values()}
    pas: Dict[str, int] = {name: 0 for name in by_id.values()}
    for rec in runner.audit_records:
        sym = by_id.get(rec.symbol_id, f"sym_{rec.symbol_id:#x}")
        if rec.reject_reason == int(RejectReason.TOXIC_FLOW):
            tox[sym] = tox.get(sym, 0) + 1
        elif rec.passed:
            pas[sym] = pas.get(sym, 0) + 1
    return tox, pas


def _top_takers(runner: HyperliquidRunner, n: int) -> List[Dict]:
    """Return the N takers with the highest absolute EWMA drift."""
    sorted_cards = sorted(
        runner.scorer.scorecards.values(),
        key=lambda s: (-abs(s.ewma_drift_ticks), -s.settled),
    )
    out: List[Dict] = []
    for sc in sorted_cards[:n]:
        out.append({
            "taker_id_hex": f"{sc.taker_id:#014x}",
            "profile": TakerProfile(sc.profile).name,
            "trades": sc.trades,
            "settled": sc.settled,
            "ewma_drift_ticks": round(sc.ewma_drift_ticks, 4),
            "mean_drift_ticks": round(sc.mean_drift_ticks, 4),
        })
    return out


# ---------------------------------------------------------------------
# Writers -- JSON
# ---------------------------------------------------------------------


def _write_json(rep: ToxicFlowReport) -> None:
    art = rep.artifacts
    doc = {
        "schema": "sentinel-hft/usecase/toxic-flow/1",
        "subject": rep.config.subject,
        "environment": rep.config.environment,
        "label": rep.config.label,
        "run_id_hex": f"{0x484C_0001:#010x}",
        "config": {
            "ticks": rep.config.ticks,
            "seed": rep.config.seed,
            "taker_population": rep.config.taker_population,
            "toxic_share": rep.config.toxic_share,
            "benign_share": rep.config.benign_share,
            "trade_prob": rep.config.trade_prob,
            "toxic_rate_threshold": rep.config.toxic_rate_threshold,
            "toxic_min_flow_events": rep.config.toxic_min_flow_events,
        },
        "throughput": {
            "ticks": art.ticks_consumed,
            "intents": art.intents_generated,
            "decisions": art.decisions_logged,
            "passed": art.passed,
            "rejected": art.rejected,
            "rejected_toxic": art.rejected_toxic,
        },
        "latency_ns": {
            "p50": art.p50_ns,
            "p99": art.p99_ns,
            "p999": art.p999_ns,
            "max": art.max_ns,
        },
        "stage_p99_ns": art.stage_p99_ns,
        "audit": {
            "head_hash_lo_hex": art.head_hash_lo_hex,
            "chain_ok": art.chain_ok,
        },
        "scorer": {
            "takers": art.taker_population,
            "toxic": art.takers_classified_toxic,
            "neutral": art.takers_classified_neutral,
            "benign": art.takers_classified_benign,
        },
        "per_symbol_toxic_rejects": rep.per_symbol_toxic_rejects,
        "per_symbol_passed": rep.per_symbol_passed,
        "top_takers": rep.top_takers,
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


# ---------------------------------------------------------------------
# Writers -- Markdown
# ---------------------------------------------------------------------


def _write_markdown(rep: ToxicFlowReport) -> None:
    art = rep.artifacts
    lines: List[str] = []
    lines.append("# Sentinel-HFT -- toxic-flow use case")
    lines.append("")
    lines.append(f"Subject: `{rep.config.subject}`  ")
    lines.append(f"Environment: `{rep.config.environment}`  ")
    lines.append(f"Label: `{rep.config.label}`")
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    pct = (art.rejected_toxic / max(1, art.intents_generated))
    lines.append(
        f"- Ticks consumed: **{art.ticks_consumed:,}**"
    )
    lines.append(
        f"- Quote intents generated: **{art.intents_generated:,}**"
    )
    lines.append(
        f"- Toxic-flow pre-gate rejects: **{art.rejected_toxic:,}** "
        f"({pct*100:.1f}% of intents)"
    )
    lines.append(
        f"- Audit chain verified: **{'PASS' if art.chain_ok else 'FAIL'}**"
    )
    lines.append("")
    lines.append("## Counterparty classification")
    lines.append("")
    lines.append(f"- Wallets observed:      {art.taker_population:,}")
    lines.append(f"- Classified TOXIC:      {art.takers_classified_toxic:,}")
    lines.append(f"- Classified NEUTRAL:    {art.takers_classified_neutral:,}")
    lines.append(f"- Classified BENIGN:     {art.takers_classified_benign:,}")
    lines.append("")
    lines.append("## Per-symbol breakdown")
    lines.append("")
    lines.append("| Symbol | Quotes passed | Toxic rejects |")
    lines.append("|:--|--:|--:|")
    for sym in sorted(rep.per_symbol_passed.keys()):
        lines.append(
            f"| `{sym}` | {rep.per_symbol_passed.get(sym, 0):,} | "
            f"{rep.per_symbol_toxic_rejects.get(sym, 0):,} |"
        )
    lines.append("")
    lines.append("## Top adverse-drift takers")
    lines.append("")
    lines.append("| # | Wallet hash | Profile | Trades | Settled | "
                 "EWMA drift (ticks) | Mean drift (ticks) |")
    lines.append("|--:|:--|:--|--:|--:|--:|--:|")
    for i, t in enumerate(rep.top_takers, start=1):
        lines.append(
            f"| {i} | `{t['taker_id_hex']}` | {t['profile']} | "
            f"{t['trades']:,} | {t['settled']:,} | "
            f"{t['ewma_drift_ticks']:+.3f} | {t['mean_drift_ticks']:+.3f} |"
        )
    lines.append("")
    lines.append("## Latency")
    lines.append("")
    lines.append(f"- p50:   {art.p50_ns:,.0f} ns")
    lines.append(f"- p99:   {art.p99_ns:,.0f} ns")
    lines.append(f"- p99.9: {art.p999_ns:,.0f} ns")
    lines.append(f"- max:   {art.max_ns:,.0f} ns")
    lines.append("")
    lines.append("## Artifacts")
    lines.append("")
    lines.append(f"- `{art.trace_path.name}`  (trace, v1.2)")
    lines.append(f"- `{art.audit_path.name}`  (audit chain)")
    lines.append(f"- `{art.dora_path.name}`   (DORA bundle)")
    lines.append(f"- `{art.summary_path.name}` (run summary)")
    lines.append(f"- `{rep.html_path.name}`   (dashboard)")
    lines.append("")
    rep.md_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------
# Writers -- HTML
# ---------------------------------------------------------------------


def _write_html(rep: ToxicFlowReport, runner: HyperliquidRunner) -> None:
    art = rep.artifacts

    # Profile / symbol breakdown for stacked bar.
    # For each symbol we count per-taker-profile TRADES from the audit log
    # isn't meaningful (audit contains decisions, not public trades).
    # Instead, break out: per-symbol (toxic rejects vs passed) for the
    # stacked bar.
    symbols = list(rep.per_symbol_passed.keys())
    stacks: List[List[float]] = []
    for sym in symbols:
        stacks.append([
            float(rep.per_symbol_passed.get(sym, 0)),
            float(rep.per_symbol_toxic_rejects.get(sym, 0)),
        ])

    # Classification donut-equivalent (stacked bar with three layers)
    class_labels = ["all takers"]
    class_stacks = [[
        float(art.takers_classified_toxic),
        float(art.takers_classified_neutral),
        float(art.takers_classified_benign),
    ]]

    # Per-symbol toxic-reject bars (horizontal).
    bar_cats = [s for s in symbols]
    bar_vals = [float(rep.per_symbol_toxic_rejects.get(s, 0)) for s in symbols]

    # Narrative: verdict.
    pct_toxic_intents = art.rejected_toxic / max(1, art.intents_generated)
    status = "ok"
    verdict_text = (
        f"The pre-gate blocked {art.rejected_toxic:,} of "
        f"{art.intents_generated:,} quote intents "
        f"({pct_toxic_intents*100:.1f}%). "
        f"{art.takers_classified_toxic} of {art.taker_population} "
        f"counterparties were learned as TOXIC from behavior alone -- "
        f"the fixture seeded "
        f"{int(round(rep.config.toxic_share * rep.config.taker_population))}."
    )
    if art.rejected_toxic == 0:
        status = "warn"
        verdict_text += (
            "  No rejects fired -- check that the toxic share is high "
            "enough and the session is long enough for the scorer to "
            "reach MIN_TRADES_FOR_CLASSIFY."
        )
    if not art.chain_ok:
        status = "err"
        verdict_text += "  Audit chain verification FAILED."

    # HTML body
    out: List[str] = []
    out.append(H.page_start(
        "Toxic-flow adverse-selection demo",
        subtitle="Post-trade drift scorecards feed a pre-gate that blocks "
                 "quotes exposed to toxic takers.",
        env=rep.config.environment,
        run_id_hex=f"{0x484C_0001:#010x}",
    ))

    # Headline KPI row.
    kpis = [
        ("Ticks consumed",       f"{art.ticks_consumed:,}", ""),
        ("Quote intents",        f"{art.intents_generated:,}", ""),
        ("Toxic-flow rejects",   f"{art.rejected_toxic:,}",
            "warn" if art.rejected_toxic > 0 else ""),
        ("Reject rate",          f"{pct_toxic_intents*100:.2f}%",
            "warn" if pct_toxic_intents > 0 else ""),
        ("Audit chain",          "PASS" if art.chain_ok else "FAIL",
            "ok" if art.chain_ok else "err"),
    ]
    scoreboard = [
        ("Wallets observed",     f"{art.taker_population:,}", ""),
        ("Classified TOXIC",     f"{art.takers_classified_toxic:,}", "err"),
        ("Classified NEUTRAL",   f"{art.takers_classified_neutral:,}", ""),
        ("Classified BENIGN",    f"{art.takers_classified_benign:,}", "ok"),
    ]
    lat = [
        ("p50",    H.fmt_ns(art.p50_ns), ""),
        ("p99",    H.fmt_ns(art.p99_ns), ""),
        ("p99.9",  H.fmt_ns(art.p999_ns), ""),
        ("max",    H.fmt_ns(art.max_ns), ""),
    ]

    out.append('<div class="row">')
    out.append(H.kv_panel("Run headline", kpis))
    out.append(H.kv_panel("Counterparty classification", scoreboard))
    out.append(H.kv_panel("Wire-to-wire latency", lat))
    out.append("</div>")

    # Verdict
    out.append(H.narrative(
        "Verdict",
        f'<p>{H.status_tag(status, "verdict")} {verdict_text}</p>'
        f'<p class="crumbs">The scorer is behavior-only: it learns each '
        f'wallet\'s post-trade drift from the public trade tape and never '
        f'reads the fixture\'s profile label. The pre-gate consults the '
        f'scorer before the risk gate and bypasses it (no rate-limit token '
        f'consumed) when it rejects, but still writes a '
        f'<code>RejectReason.TOXIC_FLOW</code> record to the hash-chained '
        f'audit log.</p>',
    ))

    # Charts: stacked by-symbol + reject bars.
    out.append('<div class="row">')
    out.append('<div class="panel">'
               '<h3>Per-symbol outcome (passed vs toxic reject)</h3>')
    out.append(H.svg_stacked_bar(
        "passed (blue) / toxic reject (red) per symbol",
        labels=symbols,
        stacks=stacks,
        stack_names=["passed", "toxic reject"],
        stack_colours=["#0b63c5", "#be123c"],
        width=520, height=260,
    ))
    out.append("</div>")

    out.append('<div class="panel">'
               '<h3>Taker classification mix</h3>')
    out.append(H.svg_stacked_bar(
        "TOXIC / NEUTRAL / BENIGN wallets",
        labels=class_labels,
        stacks=class_stacks,
        stack_names=["TOXIC", "NEUTRAL", "BENIGN"],
        stack_colours=["#be123c", "#5a6170", "#1c8a4b"],
        width=520, height=260,
    ))
    out.append("</div>")
    out.append("</div>")

    # Reject bar chart (horizontal)
    out.append('<div class="panel">'
               '<h3>Toxic-flow rejects per symbol</h3>')
    out.append(H.svg_bar_chart(
        "rejects",
        categories=bar_cats,
        values=bar_vals,
        width=640, height=200,
        colour="#be123c",
    ))
    out.append("</div>")

    # Top-N takers table
    table_rows: List[List[str]] = []
    for i, t in enumerate(rep.top_takers, start=1):
        tag = H.profile_tag(t["profile"])
        table_rows.append([
            str(i),
            t["taker_id_hex"],
            tag,
            f"{t['trades']:,}",
            f"{t['settled']:,}",
            f"{t['ewma_drift_ticks']:+.3f}",
            f"{t['mean_drift_ticks']:+.3f}",
        ])
    # table_panel escapes cell text -- for the profile tag (which is
    # already HTML) we use an inline approach: just render the table
    # manually.
    out.append('<div class="panel"><h3>Top adverse-drift counterparties</h3>')
    out.append('<table class="data">')
    out.append(
        "<tr><th>#</th><th>Wallet hash</th><th>Profile</th>"
        "<th>Trades</th><th>Settled</th>"
        "<th>EWMA drift (ticks)</th>"
        "<th>Mean drift (ticks)</th></tr>"
    )
    for r in table_rows:
        out.append(
            "<tr>"
            f"<td>{r[0]}</td>"
            f"<td>{r[1]}</td>"
            f"<td>{r[2]}</td>"
            f"<td>{r[3]}</td>"
            f"<td>{r[4]}</td>"
            f"<td>{r[5]}</td>"
            f"<td>{r[6]}</td>"
            "</tr>"
        )
    out.append("</table></div>")

    # Artifact links.
    out.append(H.narrative(
        "Artifacts",
        f'<ul style="margin:0;padding-left:18px;">'
        f'<li><a href="{art.trace_path.name}">{art.trace_path.name}</a> '
        f' -- v1.2 traces (per-stage latency)</li>'
        f'<li><a href="{art.audit_path.name}">{art.audit_path.name}</a> '
        f' -- BLAKE2b hash-chained risk-gate records</li>'
        f'<li><a href="{art.dora_path.name}">{art.dora_path.name}</a> '
        f' -- DORA evidence bundle</li>'
        f'<li><a href="{art.summary_path.name}">{art.summary_path.name}</a>'
        f' -- run summary</li>'
        f'<li><a href="{rep.json_path.name}">{rep.json_path.name}</a> '
        f' -- machine-readable report</li>'
        f'<li><a href="{rep.md_path.name}">{rep.md_path.name}</a> '
        f' -- narrative markdown</li>'
        f'</ul>',
    ))

    out.append(H.page_end())
    rep.html_path.write_text("\n".join(out))


__all__ = [
    "ToxicFlowConfig",
    "ToxicFlowReport",
    "run_toxic_flow",
]
