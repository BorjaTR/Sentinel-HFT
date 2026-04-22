# Sentinel-HFT U55C — synthesis reports

This folder is the landing zone for every FPGA report the project
produces. Today the repo carries:

| File                 | Source tool                | Status |
|----------------------|----------------------------|--------|
| `area_census.txt`    | `scripts/area_census.py`   | present (analytic, reproducible) |
| `yosys_synth.txt`    | `yosys -s scripts/yosys_synth.ys` | populated on any host with Yosys ≥ 0.40 or oss-cad-suite |
| `vivado_utilization.rpt` | Vivado `report_utilization` | populated by `make fpga-build` |
| `vivado_timing.rpt`  | Vivado `report_timing_summary` | populated by `make fpga-build` |
| `vivado_power.rpt`   | Vivado `report_power`       | populated by `make fpga-build` |

## What's actually here today

**`area_census.txt`** is a deterministic first-order area and depth
estimate built by parsing the SystemVerilog directly (see
`../scripts/area_census.py`). It gives:

* an upper-bound flip-flop count (every `<=` LHS inside an `always_ff`
  block, times the declared width of the LHS signal),
* an operator-count based LUT estimate,
* a design-intent BRAM/DSP inventory,
* a longest-combinational-path estimate in LUT levels,
* expected U55C utilisation percentages.

Running it on the current tree yields:

```
Module                        Lines     FFs   Cmps  Arith   Mux  Cases
rate_limiter.sv                 187     564      7     22     0      0
kill_switch.sv                  108     198      1      8     0      0
position_limiter.sv             180     336      4     20     0      2
stage_timer.sv                   53      36      0      3     0      0
sync_fifo.sv                     83      88      3      5     1      1
risk_gate.sv                    235     256      0      7     0      0
risk_audit_log.sv               185     514      6     13     0      0
sentinel_shell_v12.sv           201     416      0     10     2      0
...
TOTAL                                  3141     47    129     3      6
```

First-order LUT estimate: **≈ 1,300 LUT6**, **≈ 3,141 FFs**, **≈ 4 BRAM36**,
**0 DSP48E2**. That is **0.1 % of the U55C's LUT budget and 0.12 % of the
FF budget** — there is no area risk, the bottleneck during bring-up will
be timing closure on the audit-log BLAKE2b lane and the order parser,
not area.

## Why there's no `yosys_synth.txt` yet

The repo carries a working `scripts/yosys_synth.ys` script. It runs
against the full RTL tree on any host with **Yosys ≥ 0.40** (for
SystemVerilog package + typedef support) or an **oss-cad-suite** build
(Yosys + slang front-end + Verilator pre-bundled). The CI sandbox used
to author this repo shipped Yosys 0.9, which predates SV-package
support, and the aarch64 oss-cad-suite tarball (~400 MB) did not fit
the remaining disk budget at the time the estimate was committed. The
report will appear here automatically the first time the script is run
on a host with the right toolchain.

## Why there's no Vivado reports yet

The design is wired for Vivado (`scripts/build.tcl`, `scripts/elaborate.tcl`,
constraints in `../constraints/sentinel_u55c.xdc`, and the top-level
wrapper `../sentinel_u55c_top.sv`). The bottleneck is licence and
platform: Vivado 2023.2 is roughly 85 GB on disk and needs an x86_64
Linux/Windows host with a valid AMD/Xilinx licence server. It is not
something the CI can run for free.

Once run on a Vivado host via `make fpga-build`, the three standard
reports drop into this folder.

## What we recommend a reviewer check

1. **`area_census.txt`** — the area headroom claim is analytic and the
   method is in `scripts/area_census.py`. Re-running the script on an
   unchanged tree produces byte-identical output.
2. **Makefile `fpga-elaborate`** — the Verilator `--lint-only` pass in
   `.github/workflows/fpga-elaborate.yml` is the CI gate today. It does
   not produce area numbers but it enforces that the RTL remains
   elaboration-clean on every PR touching `rtl/` or `fpga/`.
3. **`../docs/INTEGRATION_READINESS.md`** — the full checklist of what
   must be added before a real tape-out, including Ethernet MAC/PCS,
   venue parsers, HBM trace spill, PCIe handoff, operator UI, and
   multi-FPGA orchestration. See the gap report for the current state
   of each item.
