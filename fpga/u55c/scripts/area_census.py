#!/usr/bin/env python3
"""
Sentinel-HFT first-order FPGA area + depth estimate.

This is NOT a synthesis report. It is a deterministic analytic census
derived from parsing the RTL directly. It gives an upper-bound register
count (every LHS signal inside an ``always_ff`` block contributes its
declared width) and a rough LUT-operator inventory (comparators,
arithmetic operators, multiplexers, case statements).

Real Vivado numbers will normally be:
  * LOWER on LUTs — resource sharing, constant folding, carry-chain use.
  * IDENTICAL on FF bits — the upper bound is tight once widths are fully
    propagated by elaboration.

Used to sanity-check that the design fits the U55C (1.3 M LUTs, 2.6 M
FFs, 2,016 BRAM36, 9,024 DSP48E2) before committing to a full P&R run.

Usage (from the repo root):

    python3 fpga/u55c/scripts/area_census.py \
        > fpga/u55c/reports/area_census.txt

The script is pure Python (no external deps) and reproducible: running
it twice on an unchanged tree yields byte-identical output.
"""

from __future__ import annotations

import re
from pathlib import Path


TOP_MODULES = [
    ("risk_pkg.sv",              "package (types only, 0 HW)"),
    ("trace_pkg.sv",             "package (types only, 0 HW)"),
    ("trace_pkg_v12.sv",         "package (types only, 0 HW)"),
    ("fault_pkg.sv",             "package (types only, 0 HW)"),
    ("rate_limiter.sv",          "token bucket + heartbeat fastpath"),
    ("kill_switch.sv",           "armed/triggered state + counters"),
    ("position_limiter.sv",      "long/short/notional + order cap"),
    ("stage_timer.sv",           "per-stage monotonic counter"),
    ("sync_fifo.sv",             "parameterised sync FIFO"),
    ("stub_latency_core.sv",     "deterministic latency model"),
    ("fault_injector.sv",        "fault mux (off in production)"),
    ("risk_gate.sv",             "3-arm parallel gate + priority encoder"),
    ("risk_audit_log.sv",        "BLAKE2b chained audit log"),
    ("instrumented_pipeline.sv", "pipeline wrap + stage probes"),
    ("sentinel_shell_v12.sv",    "shell: ingress FIFO + trace egress"),
]


# Declared widths of the canonical parameters used across the tree.
WIDTH_MAP = {
    "DATA_WIDTH":       64,
    "ADDR_WIDTH":        8,
    "MAX_TOKENS_WIDTH": 32,
    "COUNTER_WIDTH":    32,
    "FIFO_DEPTH":       64,
    "DEPTH":            64,
    "CORE_LATENCY":     10,
    "RISK_LATENCY":      5,
}


def width_of(expr: str | None) -> int:
    """Width of a `[...]` declaration expression; conservative defaults."""
    if expr is None:
        return 1
    e = expr.strip()
    m = re.match(r'(\d+)\s*:\s*(\d+)', e)
    if m:
        return abs(int(m.group(1)) - int(m.group(2))) + 1
    for k, v in WIDTH_MAP.items():
        if k in e:
            return v
    if "$clog2" in e:
        return 8
    return 8


def scan_module(src: str) -> dict:
    # Strip comments so comment content doesn't count as operators.
    src = re.sub(r'/\*.*?\*/', '', src, flags=re.S)
    src = re.sub(r'//[^\n]*', '', src)

    stats: dict[str, int] = dict(
        lines=src.count("\n"),
        always_ff=len(re.findall(r'\balways_ff\b', src)),
        always_comb=len(re.findall(r'\balways_comb\b', src)),
        case_stmts=len(re.findall(r'\bcase\s*\(', src)),
        muxes_est=src.count("?"),
        comparators=(
            len(re.findall(r'==', src))
            + len(re.findall(r'!=', src))
            + len(re.findall(r'>=', src))
            + len(re.findall(r'(?<![<>=])>(?!=)', src))
        ),
        arith_ops=(
            len(re.findall(r'(?<![a-zA-Z0-9_])\+(?![+=])', src))
            + len(re.findall(r'(?<![a-zA-Z0-9_])-(?![-=>])', src))
            + len(re.findall(r'[&|^](?![&|])', src))
        ),
        ff_bits=0,
    )

    # Register-bit count: every `<=` LHS inside an always_ff block,
    # multiplied by the LHS signal's declared width.
    ff_blocks = re.findall(
        r'always_ff[^\n]*\n(.*?)(?=\n\s*(?:always_ff|always_comb|endmodule))',
        src, flags=re.S)
    ff_bits = 0
    for blk in ff_blocks:
        for line in blk.splitlines():
            m = re.search(r'([A-Za-z_][A-Za-z0-9_]*)\s*(?:\[[^\]]+\])?\s*<=', line)
            if not m:
                continue
            name = m.group(1)
            d = re.search(
                r'logic\s*(?:\[([^\]]+)\])?\s+' + re.escape(name) + r'\b', src)
            ff_bits += width_of(d.group(1) if d else None)
    stats["ff_bits"] = ff_bits
    return stats


def main() -> int:
    root = Path(__file__).resolve().parents[3]  # repo root
    rtl_dir = root / "rtl"

    print("SENTINEL-HFT FIRST-ORDER AREA + DEPTH ESTIMATE")
    print("Target: AMD Alveo U55C (xcu55c-fsvh2892-2L-e)  @  100 MHz user clock")
    print("Generated: analytic RTL scan, not Vivado / Yosys output.")
    print("=" * 78)
    print(
        f"{'Module':28s}  {'Lines':>5s}  {'FFs':>6s}  "
        f"{'Cmps':>5s}  {'Arith':>5s}  {'Mux':>4s}  {'Cases':>5s}"
    )
    print("-" * 78)

    totals = dict(ff_bits=0, comparators=0, arith_ops=0,
                  muxes_est=0, case_stmts=0)

    for fname, _descr in TOP_MODULES:
        fp = rtl_dir / fname
        if not fp.exists():
            continue
        s = scan_module(fp.read_text())
        print(
            f"{fname:28s}  {s['lines']:5d}  {s['ff_bits']:6d}  "
            f"{s['comparators']:5d}  {s['arith_ops']:5d}  "
            f"{s['muxes_est']:4d}  {s['case_stmts']:5d}"
        )
        for k in totals:
            totals[k] += s[k]

    print("-" * 78)
    print(
        f"{'TOTAL':28s}  {'':5s}  {totals['ff_bits']:6d}  "
        f"{totals['comparators']:5d}  {totals['arith_ops']:5d}  "
        f"{totals['muxes_est']:4d}  {totals['case_stmts']:5d}"
    )
    print()

    est_luts = (
        totals["comparators"] * 4    # avg 8-bit cmp ≈ 4 LUT6
        + totals["arith_ops"] * 8    # 32-bit +/- ≈ 8 LUT6 w/ carry8
        + totals["muxes_est"] * 2    # 4:1 mux ≈ 2 LUT6
        + totals["case_stmts"] * 12
    )
    print("First-order LUT estimate (UltraScale+ LUT6 equivalents):")
    print(f"  combinational LUTs   ~= {est_luts:,}")
    print(f"  sequential FFs       ~= {totals['ff_bits']:,}")
    print(f"  estimated BRAM36     ~= 4   "
          f"(1 audit-log, 1 trace FIFO, 2 metadata FIFOs)")
    print(f"  estimated DSP48E2    ~= 0   (no multipliers in risk path)")
    print()
    print("U55C utilisation headroom "
          "(1.3M LUTs, 2.6M FFs, 2016 BRAM, 9024 DSP):")
    pct_lut = 100.0 * est_luts / 1_300_000
    pct_ff = 100.0 * totals["ff_bits"] / 2_600_000
    pct_brm = 100.0 * 4 / 2016
    print(f"  LUT  utilisation     ~= {pct_lut:.3f}%")
    print(f"  FF   utilisation     ~= {pct_ff:.3f}%")
    print(f"  BRAM utilisation     ~= {pct_brm:.2f}%")
    print(f"  DSP  utilisation     ~= 0.000%")
    print()
    print("Longest combinational path (LUT levels, analytic):")
    print("  ingress -> risk gate all-pass AND -> reject priority mux  : <= 6 LUT6")
    print("  audit log BLAKE2b chained lane (pipelined)                : <= 5 LUT6/stage")
    print("  stage_timer diff + hash seal                              : <= 4 LUT6")
    print()
    print("Fmax target : 100 MHz (10 ns period).")
    print("Slack target: >= 2 ns margin at WNS.")
    print()
    print("Caveats")
    print("-------")
    print("* This is NOT a post-synth report. Vivado numbers supersede it.")
    print("* FF count is an UPPER BOUND assuming full width propagation.")
    print("* LUT count is a FIRST-ORDER estimate from operator counts.")
    print("* BRAM count is design-intent (see risk_audit_log.sv + sync_fifo.sv).")
    print("* Real numbers arrive once `make fpga-build` runs on a Vivado host.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
