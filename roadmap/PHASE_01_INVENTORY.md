# Phase 1 Inventory — what's there vs. what the pre-reg requires

**Date:** 2026-05-08
**Pre-registration ref:** [`pre_reg/phase_01.yml`](pre_reg/phase_01.yml)
**Purpose:** ground-truth audit of pre-existing RTL/sim/scripts against the
locked Phase-1 deliverables, before any new code is written.

---

## Method

For every deliverable in `pre_reg/phase_01.yml :: scope_in`, classify as:

- **EXISTS** — already in repo and matches the spec.
- **PARTIAL** — exists but needs work to match (gap noted).
- **MISSING** — not in repo; must be created.

The output of this audit drives the per-task list in `STATUS.md`.

---

## RTL modules

| Path                          | Status   | Gap / Notes |
|-------------------------------|----------|-------------|
| `rtl/risk_pkg.sv`             | EXISTS   | Has order_t, risk_status_t, reject reasons, rate/position/kill configs. Wave-1 audit fixes already applied (signed position, etc.). |
| `rtl/risk_gate.sv`            | EXISTS   | Skid-buffered, signed-position propagated, sub-modules wired through xfer_accept. |
| `rtl/position_limiter.sv`     | EXISTS   | Global net position (not per-symbol). See **gap G1** below. |
| `rtl/rate_limiter.sv`         | EXISTS   | Token-bucket with refill period. |
| `rtl/kill_switch.sv`          | EXISTS   | Sticky kill state, manual + auto loss-threshold trigger. |
| `rtl/risk_audit_log.sv`       | EXISTS   | BLAKE2b chain logic. **Needs external review** per pre-reg (E-1). |
| `rtl/sentinel_shell_v12.sv`   | EXISTS   | Wrapper around the gate. |
| `rtl/sentinel_sva.sv`         | EXISTS   | SVA assertions. Coverage TBD. |
| `rtl/fat_finger_band.sv`      | MISSING  | Required by `rules_enforced.fat_finger_price_band`. **Gap G2.** |
| `rtl/symbol_allowlist.sv`     | MISSING  | Required by `rules_enforced.symbol_allowlist`. **Gap G3.** |

## Configuration / control plane

| Path                            | Status   | Notes |
|---------------------------------|----------|-------|
| `fpga/regmap.yaml`              | MISSING  | Canonical register map — single source of truth for C / Rust / Python headers. **Gap G4.** |
| `fpga/u55c/sentinel_u55c_top.sv`| EXISTS   | 25 KB top-level wrapper. Needs review against the new modules added in G2/G3. |
| `fpga/u55c/constraints/sentinel_u55c.xdc` | EXISTS | XDC pinout + clock + pblock constraints. |

## Build flow

| Path                               | Status | Notes |
|------------------------------------|--------|-------|
| `fpga/u55c/scripts/build.tcl`      | EXISTS | Vivado non-project flow. |
| `fpga/u55c/scripts/elaborate.tcl`  | EXISTS | Vivado elaborate-only check. |
| `fpga/u55c/scripts/yosys_synth.ys` | EXISTS | Open-source Yosys synth. |
| `fpga/u55c/scripts/yosys_synth_u55c.ys` | EXISTS | U55C-specific Yosys flow. |
| `fpga/u55c/scripts/yosys_ltp_u55c.ys`   | EXISTS | Yosys longest topological path. |
| `fpga/u55c/scripts/area_census.py` | EXISTS | RTL-scan area estimator. |
| `fpga/u55c/reports/area_census.txt`| EXISTS | First-order area estimate. |
| `fpga/u55c/reports/yosys_synth.log`| EXISTS | Yosys synth log. |
| `fpga/u55c/reports/yosys_ltp.log`  | EXISTS | Yosys LTP log. |
| `fpga/u55c/reports/timing_report.txt` | MISSING | Vivado P&R timing report. **Gap G5** — must be checked in once timing closes. |
| `fpga/bitstreams/sentinel_v0.1.bit`   | MISSING | Locked Phase-1 deliverable. **Gap G6.** |

## Simulation / testbench

| Path                          | Status   | Notes |
|-------------------------------|----------|-------|
| `sim/Makefile`                | EXISTS   | Verilator flow, `--trace`, `--timing`. |
| `sim/sim_main.cpp`            | EXISTS   | C++ testbench driver (sentinel shell). |
| `sim/sim_risk.cpp`            | EXISTS   | C++ driver for risk-gate sim. |
| `sim/tb_sentinel_shell.sv`    | EXISTS   | SystemVerilog testbench. |
| `rtl/tb_risk_gate.sv`         | EXISTS   | Risk-gate testbench. |
| `rtl/tb_latency_attribution.sv`| EXISTS  | Latency-attribution testbench. |

## Verification artifacts (NEW for Phase 1 — all MISSING)

| Path                                          | Status   | Linked V-Gate |
|-----------------------------------------------|----------|---------------|
| `sentinel_hft/golden/risk_gate.py`            | MISSING  | V-Floor       |
| `verification/runner.py`                      | MISSING  | all V-axes    |
| `verification/v_floor/random_corpus.py`       | MISSING  | V-Floor       |
| `verification/v_mutation/inject.py`           | MISSING  | V-Mut         |
| `verification/v_metamorphic/relations.py`     | MISSING  | V-Meta        |
| `verification/v_parity/three_engine.py`       | MISSING  | V-Parity      |
| `verification/v_contract/regmap_contract.py`  | MISSING  | V-Contract    |
| `verification/v_tamper/tamper_inject.py`      | MISSING  | V-Tamper      |
| `verification/reports/`                       | MISSING  | (output dir)  |

## Audit artifacts (NEW for Phase 1 — all MISSING)

| Path                                       | Status   | Linked A-Gate |
|--------------------------------------------|----------|---------------|
| `audit_system/runner.py`                   | MISSING  | all A-axes    |
| `audit_system/a_spec/bitstream_hash.py`    | MISSING  | A-Spec        |
| `audit_system/a_spec/traceability_replay.py`| MISSING | A-Spec        |
| `audit_system/a_coverage/clause_to_test.py`| MISSING  | A-Coverage    |
| `audit_system/a_drift/latency_bands.py`    | MISSING  | A-Drift       |
| `audit_system/a_chain/end_to_end.py`       | MISSING  | A-Chain       |
| `audit_system/a_bias/cohort_chi2.py`       | MISSING  | A-Bias        |
| `audit_system/reports/`                    | MISSING  | (output dir)  |
| `audit_system/pre_reg/`                    | MISSING  | (per-cycle)   |
| `audit_system/AUDIT_SYSTEM_DESIGN.md`      | MISSING  | (protocol)    |

## Documentation (NEW for Phase 1)

| Path                          | Status   | Notes |
|-------------------------------|----------|-------|
| `docs/fpga/ARCHITECTURE.md`   | MISSING  | Block diagram + dataflow. |
| `docs/fpga/TRACEABILITY.md`   | MISSING  | Spec → RTL → test matrix. |

---

## Identified gaps

### G1 — Per-symbol position tracking
`position_limiter.sv` keeps a single global net position. The pre-reg
lists `position_cap_per_symbol`. Decision options:

- **A.** Keep global. Document as "single-book / aggregated firm-wide cap"
  in `ARCHITECTURE.md`. Per-symbol becomes Phase 16+ backlog.
- **B.** Add a per-symbol position table inside `position_limiter.sv`,
  bounded to N symbols (BRAM-sized). More work, more area, more test
  surface.

**Recommendation: A for v1.0.** The portfolio piece is more compelling
when shipped honestly than when scope-creeped. Amend the pre-reg to
say `position_cap_aggregated` instead of `_per_symbol`. Captured below.

### G2 — fat_finger_price_band module
Listed in `rules_enforced` but not present in RTL. Needs a small module
that takes `order.price` and a per-symbol reference price register, and
rejects if `|price − ref| / ref > band_pct`.

**Plan:** add `rtl/fat_finger_band.sv` + tests.

### G3 — symbol_allowlist module
Small CAM-style lookup of allowed `symbol_id` values. Reject if not in
the allowlist.

**Plan:** add `rtl/symbol_allowlist.sv` + tests.

### G4 — fpga/regmap.yaml
Canonical YAML defining every readable/writable register, its bit field
layout, default value, access type, and which RTL block owns it. Codegens
into C, Rust, Python headers. Not present today.

**Plan:** write `fpga/regmap.yaml`. Add a codegen script.

### G5 — Vivado P&R timing report
Phase 0a stopped at Yosys synth + LTP. Vivado P&R must complete with
all paths met at 100 MHz, and the report is checked in.

**Plan:** run `build.tcl`, capture report, commit.

### G6 — Locked bitstream
Same as G5 outcome. Output file must be committed under
`fpga/bitstreams/sentinel_v0.1.bit`.

### G7 — External review of `risk_audit_log.sv`
Pre-reg E-1: crypto code requires external review. Action: run an LLM
code-review pass first (logged), then schedule a human reviewer.

---

## Pre-registration amendment (proposed — to be applied if accepted)

```yaml
amendments:
  - date: "2026-05-08"
    reason: "G1 — keep position cap aggregated (global net) for v1.0; per-symbol slicing is Phase 16+ backlog."
    change: "rules_enforced.position_cap_per_symbol → rules_enforced.position_cap_aggregated"
```

---

## Net Phase 1 work plan (post-inventory)

Concrete sequence — each item is a session-sized chunk:

1. Apply pre-reg amendment for G1.
2. Write `fpga/regmap.yaml` (G4).
3. Write `sentinel_hft/golden/risk_gate.py` (golden model, source of truth for V-Floor).
4. Write `rtl/fat_finger_band.sv` + `rtl/symbol_allowlist.sv` (G2, G3).
5. Wire G2/G3 into `risk_gate.sv` and `sentinel_u55c_top.sv`.
6. Build `verification/runner.py` skeleton.
7. Wire V-Floor (Verilator vs golden, 10⁶ random corpus).
8. Wire V-Contract (regmap contract test).
9. Wire V-Meta (metamorphic relations on the golden + RTL).
10. Wire V-Mut (mutation injector for SystemVerilog).
11. Wire V-Tamper (chain tamper-inject test).
12. Wire V-Parity (RTL ≡ post-synth gate sim; FPGA leg skipped if no card).
13. Build `audit_system/runner.py` skeleton + A-Spec/A-Coverage/A-Drift/A-Chain/A-Bias for Phase 1.
14. Write `docs/fpga/ARCHITECTURE.md` and `docs/fpga/TRACEABILITY.md`.
15. Run Vivado build → check in timing report + bitstream (G5/G6).
16. External review of audit-log RTL (G7).
17. Phase-close report.

If Vivado is not available locally, items 12 and 15 fall back to "Yosys
synth complete + Verilator parity" and the phase-close documents that
constraint explicitly.
