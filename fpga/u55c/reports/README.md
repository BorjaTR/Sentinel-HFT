# Sentinel-HFT U55C — synthesis reports

This folder is the landing zone for every FPGA report the project
produces. Today the repo carries:

| File                 | Source tool                | Status |
|----------------------|----------------------------|--------|
| `area_census.txt`    | `scripts/area_census.py`   | present (analytic, reproducible) |
| `yosys_synth.txt`    | `yosys -s scripts/yosys_synth_u55c.ys` (V2 Phase 0a, full U55C top) | populated on any host with Yosys ≥ 0.40 or oss-cad-suite, **and by `.github/workflows/synth-yosys.yml` on every PR** as a build artifact |
| `yosys_synth.log`    | `yosys -l` sidecar         | uploaded alongside the report; contains the full Yosys stderr for debugging |
| `vivado_utilization.rpt` | Vivado `report_utilization` | populated by `make fpga-build` |
| `vivado_timing.rpt`  | Vivado `report_timing_summary` | populated by `make fpga-build` |
| `vivado_power.rpt`   | Vivado `report_power`       | populated by `make fpga-build` |

Three Yosys scripts live in `../scripts/`:

* `yosys_synth.ys` — targets `sentinel_shell_v12` (the instrumentation
  shell alone). Faster, useful for isolating shell-level regressions.
  Historical; pre-V2 entry point.
* `yosys_synth_u55c.ys` — targets `sentinel_u55c_top` (the full U55C
  wrapper, including CMAC CDC plumbing, risk gate, audit log, MMCM
  stub, LEDs, heartbeat). This is the V2.0 Phase 0a CI gate and the
  one the GitHub Actions workflow runs. Does synth + stat + check
  and produces `yosys_synth.txt` in ~5 s on an Apple-silicon host.
* `yosys_ltp_u55c.ys` — same front-end and same synth pass, but the
  only report it emits is `ltp -noff` (longest combinational path
  in LUT levels) into `yosys_ltp.txt`. Split out of the main script
  because on a fully-flattened synth_xilinx netlist `ltp` walks every
  automatically-inserted ALU feedback path and floods the log with
  tens of thousands of "Detected loop" warnings — fine locally or in
  a slower opt-in CI job, too heavy for the main 1-minute CI step.

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

## Where `yosys_synth.txt` comes from

The repo carries two Yosys scripts:

* `scripts/yosys_synth.ys` (shell-only, historical) and
* `scripts/yosys_synth_u55c.ys` (full U55C top, V2.0 Phase 0a).

Both run on any host with **Yosys ≥ 0.40** (for SystemVerilog package
+ typedef support) or an **oss-cad-suite** build (Yosys + slang
front-end + Verilator pre-bundled). The CI sandbox used to author
this repo originally shipped Yosys 0.9, which predates SV-package
support, so the first committed `yosys_synth.txt` comes from the
GitHub Actions workflow `.github/workflows/synth-yosys.yml` — it
downloads a recent oss-cad-suite release on `ubuntu-latest` and
uploads the resulting report as a build artifact. Re-running the
script locally on a host with the right toolchain produces
bit-identical output for an unchanged tree.

If the full `synth_xilinx -family xcup -flatten` pass fails (bad SV
feature, read error, etc.), the workflow falls back to a lint-only
`read_verilog -sv -defer ...; hierarchy -check -top sentinel_u55c_top`
pass and writes a clearly-marked "LINT-ONLY FALLBACK" banner into the
report, so a reviewer can tell a full-synth run from a lint-only run
at a glance.

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
