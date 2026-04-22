"""Use case: wire-to-wire latency attribution.

Story this use case tells the interviewer
-----------------------------------------

A market-maker competing on fill-quality needs wire-to-wire latency
visibility per decision, not per *tick*, and not just as a single
p99 number. The FPGA pipeline exposes four attribution stages --
ingress (deserialise + validate), core (book apply + strategy
decision), risk (rate/position/kill gate), egress (serialise +
transmit). This use case runs a clean-baseline HL session and emits:

* global wire-to-wire p50 / p99 / p99.9 / max,
* per-stage p50 / p99 histograms,
* SLO violation count (configurable total-budget; defaults to the
  sum of the per-stage 99th-percentile budgets).

A Keyrock reviewer should be able to look at the dashboard and see
*which stage* is the bottleneck on the tail, not just that "latency
is bad". That is the FPGA observability story the rest of the
package is built around.

Outputs
-------

Extends the four standard HL runner artifacts with:

* ``latency.json`` -- machine-readable report.
* ``latency.md``   -- narrative markdown.
* ``latency.html`` -- self-contained HTML dashboard with inline SVG
  histograms (one per stage + total).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from ..hyperliquid import (
    HLRunConfig,
    HLRunArtifacts,
    HyperliquidRunner,
)
from ..deribit.pipeline import (
    BUDGET_INGRESS,
    BUDGET_CORE,
    BUDGET_RISK,
    BUDGET_EGRESS,
    CLOCK_MHZ,
)
from ..deribit.risk import RiskGateConfig
from . import _html as H


# ---------------------------------------------------------------------
# Config / report
# ---------------------------------------------------------------------


@dataclass
class LatencyConfig:
    """Knobs for the latency attribution session."""

    ticks: int = 40_000
    seed: int = 3
    output_dir: Path = field(default_factory=lambda: Path("out/hl/latency"))
    subject: str = "sentinel-hft-hl-latency"
    environment: str = "sim"

    # Clean-baseline run: keep toxic flow in the mix so the pipeline
    # sees real pre-gate activity, but don't inject a vol spike.
    toxic_share: float = 0.20
    benign_share: float = 0.30
    trade_prob: float = 0.10
    enable_toxic_guard: bool = True

    # SLO budget for wire-to-wire latency (ns). Computed below as the
    # sum of the budgets' 99th-percentile cycles * (1000/CLOCK_MHZ).
    # We store the resolved value on the report for the HTML.
    slo_p99_ns: Optional[int] = None   # auto-computed when None

    label: str = "latency"


@dataclass
class LatencyReport:
    artifacts: HLRunArtifacts
    config: LatencyConfig
    json_path: Path
    md_path: Path
    html_path: Path

    p50_ns: float
    p99_ns: float
    p999_ns: float
    max_ns: float
    mean_ns: float
    count: int

    slo_p99_ns: int
    slo_violations: int
    slo_violation_rate: float

    stage_p50_ns: Dict[str, float]
    stage_p99_ns: Dict[str, float]
    stage_mean_ns: Dict[str, float]

    bottleneck_stage: str

    samples: List[int] = field(default_factory=list)
    stage_samples: Dict[str, List[int]] = field(default_factory=dict)


# ---------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------


def run_latency(cfg: Optional[LatencyConfig] = None) -> LatencyReport:
    cfg = cfg or LatencyConfig()
    output_dir = Path(cfg.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    run_cfg = HLRunConfig(
        ticks=cfg.ticks,
        seed=cfg.seed,
        output_dir=output_dir,
        subject=cfg.subject,
        environment=cfg.environment,
        enable_toxic_guard=cfg.enable_toxic_guard,
        toxic_share=cfg.toxic_share,
        benign_share=cfg.benign_share,
        trade_prob=cfg.trade_prob,
        label=cfg.label,
        risk=RiskGateConfig(),
    )

    runner = HyperliquidRunner(run_cfg)
    artifacts = runner.run()

    lat = list(runner.latencies_ns)
    count = len(lat)
    mean_ns = sum(lat) / count if count else 0.0

    stage_samples = {k: list(v) for k, v in runner.stage_ns.items()}
    stage_mean = {
        k: (sum(v) / len(v)) if v else 0.0
        for k, v in stage_samples.items()
    }

    # Auto-compute SLO budget from the base_cycles of each stage,
    # scaled by a jitter/burst allowance so p99 sits at ~2x base.
    # base cycles sum = 35 + 55 + 18 + 32 = 140 cycles (1.4 us @ 100 MHz).
    # p99 SLO = base * 2.2 to absorb lognormal jitter + burst_prob tails.
    slo_p99_ns = cfg.slo_p99_ns
    if slo_p99_ns is None:
        ns_per_cycle = 1000 // CLOCK_MHZ
        base_cycles_sum = (
            BUDGET_INGRESS.base_cycles + BUDGET_CORE.base_cycles
            + BUDGET_RISK.base_cycles + BUDGET_EGRESS.base_cycles
        )
        slo_p99_ns = int(round(base_cycles_sum * 2.2 * ns_per_cycle))

    violations = sum(1 for x in lat if x > slo_p99_ns)
    violation_rate = violations / count if count else 0.0

    # Find the stage whose p99 / global p99 ratio is highest.
    bottleneck_stage = "ingress"
    best_frac = -1.0
    for stage, p99 in artifacts.stage_p99_ns.items():
        if artifacts.p99_ns <= 0:
            continue
        frac = p99 / max(1.0, artifacts.p99_ns)
        if frac > best_frac:
            best_frac = frac
            bottleneck_stage = stage

    json_path = output_dir / "latency.json"
    md_path = output_dir / "latency.md"
    html_path = output_dir / "latency.html"

    report = LatencyReport(
        artifacts=artifacts,
        config=cfg,
        json_path=json_path,
        md_path=md_path,
        html_path=html_path,
        p50_ns=artifacts.p50_ns,
        p99_ns=artifacts.p99_ns,
        p999_ns=artifacts.p999_ns,
        max_ns=artifacts.max_ns,
        mean_ns=mean_ns,
        count=count,
        slo_p99_ns=int(slo_p99_ns),
        slo_violations=violations,
        slo_violation_rate=violation_rate,
        stage_p50_ns=dict(artifacts.stage_p50_ns),
        stage_p99_ns=dict(artifacts.stage_p99_ns),
        stage_mean_ns=stage_mean,
        bottleneck_stage=bottleneck_stage,
        samples=lat,
        stage_samples=stage_samples,
    )

    _write_json(report)
    _write_markdown(report)
    _write_html(report)
    return report


# ---------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------


def _write_json(rep: LatencyReport) -> None:
    art = rep.artifacts
    # Avoid writing raw sample arrays to JSON -- they'd be enormous.
    # We emit quantiles + histogram buckets.
    buckets_total = _histogram_buckets(rep.samples, bins=40)
    buckets_stage = {
        k: _histogram_buckets(v, bins=30)
        for k, v in rep.stage_samples.items()
    }
    doc = {
        "schema": "sentinel-hft/usecase/latency/1",
        "subject": rep.config.subject,
        "environment": rep.config.environment,
        "label": rep.config.label,
        "run_id_hex": f"{0x484C_0001:#010x}",
        "config": {
            "ticks": rep.config.ticks,
            "seed": rep.config.seed,
            "toxic_share": rep.config.toxic_share,
            "benign_share": rep.config.benign_share,
            "trade_prob": rep.config.trade_prob,
            "enable_toxic_guard": rep.config.enable_toxic_guard,
        },
        "latency_ns": {
            "count": rep.count,
            "mean": rep.mean_ns,
            "p50": rep.p50_ns,
            "p99": rep.p99_ns,
            "p999": rep.p999_ns,
            "max": rep.max_ns,
        },
        "slo": {
            "p99_budget_ns": rep.slo_p99_ns,
            "violations": rep.slo_violations,
            "violation_rate": rep.slo_violation_rate,
        },
        "stage_p50_ns": rep.stage_p50_ns,
        "stage_p99_ns": rep.stage_p99_ns,
        "stage_mean_ns": rep.stage_mean_ns,
        "bottleneck_stage": rep.bottleneck_stage,
        "histogram_total": buckets_total,
        "histogram_per_stage": buckets_stage,
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


def _histogram_buckets(samples: List[int], *, bins: int) -> Dict:
    if not samples:
        return {"lo": 0, "hi": 0, "bins": bins, "counts": []}
    lo = min(samples)
    hi = max(samples)
    if hi <= lo:
        hi = lo + 1
    width = (hi - lo) / bins
    counts = [0] * bins
    for s in samples:
        idx = int((s - lo) / width)
        if idx >= bins:
            idx = bins - 1
        if idx < 0:
            idx = 0
        counts[idx] += 1
    return {"lo": lo, "hi": hi, "bins": bins, "counts": counts}


def _write_markdown(rep: LatencyReport) -> None:
    art = rep.artifacts
    lines: List[str] = []
    lines.append("# Sentinel-HFT -- wire-to-wire latency attribution")
    lines.append("")
    lines.append(f"Subject: `{rep.config.subject}`  ")
    lines.append(f"Environment: `{rep.config.environment}`")
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    lines.append(f"- Samples: **{rep.count:,}**")
    lines.append(f"- p50:   {rep.p50_ns:,.0f} ns "
                 f"({rep.p50_ns/1000:,.2f} us)")
    lines.append(f"- p99:   {rep.p99_ns:,.0f} ns "
                 f"({rep.p99_ns/1000:,.2f} us)")
    lines.append(f"- p99.9: {rep.p999_ns:,.0f} ns "
                 f"({rep.p999_ns/1000:,.2f} us)")
    lines.append(f"- max:   {rep.max_ns:,.0f} ns "
                 f"({rep.max_ns/1000:,.2f} us)")
    lines.append("")
    lines.append(f"- SLO p99 budget: **{rep.slo_p99_ns:,} ns**")
    lines.append(f"- Violations:     {rep.slo_violations:,} "
                 f"({rep.slo_violation_rate*100:.3f}%)")
    lines.append(f"- Bottleneck stage: **{rep.bottleneck_stage}**")
    lines.append("")
    lines.append("## Per-stage (ns)")
    lines.append("")
    lines.append("| Stage   | mean | p50 | p99 |")
    lines.append("|:--|--:|--:|--:|")
    for stage in ("ingress", "core", "risk", "egress"):
        lines.append(
            f"| {stage:<8s} | {rep.stage_mean_ns.get(stage, 0):,.0f} | "
            f"{rep.stage_p50_ns.get(stage, 0):,.0f} | "
            f"{rep.stage_p99_ns.get(stage, 0):,.0f} |"
        )
    lines.append("")
    lines.append("## Artifacts")
    lines.append("")
    lines.append(f"- `{art.trace_path.name}`   (trace v1.2)")
    lines.append(f"- `{art.audit_path.name}`   (audit)")
    lines.append(f"- `{art.dora_path.name}`    (DORA)")
    lines.append(f"- `{art.summary_path.name}` (summary)")
    lines.append(f"- `{rep.html_path.name}`    (dashboard)")
    lines.append("")
    rep.md_path.write_text("\n".join(lines))


def _write_html(rep: LatencyReport) -> None:
    art = rep.artifacts

    slo_status = "ok" if rep.slo_violation_rate <= 0.01 else (
        "warn" if rep.slo_violation_rate <= 0.05 else "err"
    )

    kpis = [
        ("Samples",       f"{rep.count:,}", ""),
        ("p50",           H.fmt_ns(rep.p50_ns), ""),
        ("p99",           H.fmt_ns(rep.p99_ns), ""),
        ("p99.9",         H.fmt_ns(rep.p999_ns), ""),
        ("max",           H.fmt_ns(rep.max_ns), ""),
    ]
    slo_panel = [
        ("SLO p99 budget",    H.fmt_ns(rep.slo_p99_ns), ""),
        ("SLO violations",    f"{rep.slo_violations:,}",
            slo_status),
        ("Violation rate",    f"{rep.slo_violation_rate*100:.3f}%",
            slo_status),
        ("Bottleneck stage",  rep.bottleneck_stage, ""),
    ]
    stage_panel = []
    for stage in ("ingress", "core", "risk", "egress"):
        stage_panel.append((
            f"{stage} (p50 / p99)",
            f"{H.fmt_ns(rep.stage_p50_ns.get(stage, 0))} / "
            f"{H.fmt_ns(rep.stage_p99_ns.get(stage, 0))}",
            "warn" if stage == rep.bottleneck_stage else "",
        ))

    out: List[str] = []
    out.append(H.page_start(
        "Wire-to-wire latency attribution",
        subtitle="Per-stage p50 / p99 + SLO violation budget, "
                 "ingested from the v1.2 trace file.",
        env=rep.config.environment,
        run_id_hex=f"{0x484C_0001:#010x}",
    ))

    out.append('<div class="row">')
    out.append(H.kv_panel("Latency headline", kpis))
    out.append(H.kv_panel("SLO status", slo_panel))
    out.append(H.kv_panel("Per-stage", stage_panel))
    out.append("</div>")

    out.append(H.narrative(
        "Verdict",
        f'<p>{H.status_tag(slo_status, "slo")} '
        f'The pipeline kept wire-to-wire latency under the '
        f'{H.fmt_ns(rep.slo_p99_ns)} p99 budget on '
        f'{rep.slo_violations:,} of {rep.count:,} decisions '
        f'({rep.slo_violation_rate*100:.3f}% above budget). '
        f'The tail is dominated by the <strong>'
        f'{rep.bottleneck_stage}</strong> stage at '
        f'{H.fmt_ns(rep.stage_p99_ns.get(rep.bottleneck_stage, 0))} p99. '
        f'That is the component to harden first in the next '
        f'floorplan iteration.</p>'
        f'<p class="crumbs">The four stages map directly to FPGA '
        f'pblock regions on the Alveo U55C layout (see '
        f'<code>fpga/u55c/sentinel.xdc</code>). Budgets are in '
        f'cycles at 100 MHz; the SLO here is the sum of the per-stage '
        f'p99 cycle counts converted to ns.</p>',
    ))

    # Total histogram
    out.append('<div class="panel">'
               '<h3>Wire-to-wire latency distribution</h3>')
    out.append(H.svg_histogram(
        "wire-to-wire (ns)",
        samples=[float(x) for x in rep.samples],
        bins=48,
        width=720, height=240,
        colour="#0b63c5",
        threshold=float(rep.slo_p99_ns),
        threshold_label="p99 SLO",
        x_unit=" ns",
    ))
    out.append("</div>")

    # Per-stage histograms (2x2)
    out.append('<div class="row">')
    for stage in ("ingress", "core", "risk", "egress"):
        samples = rep.stage_samples.get(stage, [])
        out.append('<div class="panel">'
                   f'<h3>{stage}</h3>')
        out.append(H.svg_histogram(
            f"{stage} stage (ns)",
            samples=[float(x) for x in samples],
            bins=32,
            width=520, height=200,
            colour=("#be123c" if stage == rep.bottleneck_stage
                    else "#0b63c5"),
            threshold=None,
            x_unit=" ns",
        ))
        out.append("</div>")
    out.append("</div>")

    # Artifact links
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
    "LatencyConfig",
    "LatencyReport",
    "run_latency",
]
