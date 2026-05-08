# Sentinel-HFT — Build Status

**Last updated:** 2026-05-08
**Overall phase:** Phase 1 (FPGA Floor) — IN PROGRESS

This file is the single canonical view of where the build is. Updated whenever
a phase or sub-task changes state. See [ROADMAP_TO_LAUNCH.md](../ROADMAP_TO_LAUNCH.md)
for the plan.

---

## Phase status

| #  | Phase                                       | Status          | Pre-reg | V-gate | A-gate |
|----|---------------------------------------------|-----------------|---------|--------|--------|
| 1  | FPGA Floor                                  | IN PROGRESS     | LOCKED  | —      | —      |
| 2  | Wire-Protocol Adapter (FIX 4.4)             | NOT STARTED     | —       | —      | —      |
| 3  | Failover & State Replication                | NOT STARTED     | —       | —      | —      |
| 4  | Policy & Config Plane                       | NOT STARTED     | —       | —      | —      |
| 5  | Audit Chain Persistence + Auditor Read      | NOT STARTED     | —       | —      | —      |
| 6  | Observability & Operational Glue            | NOT STARTED     | —       | —      | —      |
| 7  | Regulator Evidence Packs                    | NOT STARTED     | —       | —      | —      |
| 8  | Shadow-Mode Replay Harness                  | NOT STARTED     | —       | —      | —      |
| 9  | RCA + Triage Productionization              | NOT STARTED     | —       | —      | —      |
| 10 | Verification System (cross-cutting)         | SKELETON        | —       | —      | —      |
| 11 | Audit System (cross-cutting)                | SKELETON        | —       | —      | —      |
| 12 | Public-Surface Hardening (sentinel-web)     | NOT STARTED     | —       | —      | —      |
| 13 | Documentation, ADRs, Demo Reel              | NOT STARTED     | —       | —      | —      |
| 14 | End-to-End Launch Rehearsal                 | NOT STARTED     | —       | —      | —      |
| 15 | Launch (v1.0)                               | NOT STARTED     | —       | —      | —      |

Legend: **NOT STARTED** | **IN PROGRESS** | **GATES PASSING** | **CLOSED**

---

## Phase 1 — FPGA Floor (current)

**Pre-registration:** [`roadmap/pre_reg/phase_01.yml`](pre_reg/phase_01.yml) — LOCKED 2026-05-08.

### Sub-tasks

| Sub-task                                       | Status      |
|------------------------------------------------|-------------|
| Pre-registration (`phase_01.yml`)              | DONE        |
| RTL inventory vs spec                          | DONE        |
| Canonical `fpga/regmap.yaml`                   | DONE        |
| Behavioral golden model (`golden/risk_gate.py`)| DONE        |
| V-Floor random corpus + manifest determinism   | DONE        |
| V-Contract regmap schema check                 | DONE        |
| V-Meta metamorphic suite (4 relations × 10k)   | DONE        |
| V-Parity cocotb/Verilator harness (skips clean)| DONE        |
| V-gate runner                                  | DONE        |
| A-gate runner                                  | DONE        |
| Spec→RTL traceability matrix                   | DONE        |
| `docs/fpga/ARCHITECTURE.md`                    | DONE        |
| `rtl/fat_finger_band.sv` module                | DONE        |
| `rtl/symbol_allowlist.sv` module               | DONE        |
| `rtl/risk_gate_v2.sv` composer                 | DONE        |
| Mutation testing harness (V-Mut)               | TODO        |
| Tamper-injection harness (V-Tamper)            | TODO        |
| Vivado P&R + timing closure at 100 MHz         | TODO        |
| Bitstream reproducibility check                | TODO        |
| External review of `risk_audit_log.sv`         | TODO        |
| Phase 1 close report                           | TODO        |

### V-Gates

| Axis        | Status      | Last run     | Report |
|-------------|-------------|--------------|--------|
| V-Floor     | **PASS**    | 2026-05-08   | golden corpus determinism, 5 seeds × 50k orders |
| V-Mut       | SKIP (TODO) | —            | harness pending |
| V-Meta      | **PASS**    | 2026-05-08   | 4 relations × 10k pairs, 0 violations (40k checks) |
| V-Parity    | SKIP (env)  | —            | harness ready; needs Verilator + cocotb on host |
| V-Contract  | **PASS**    | 2026-05-08   | regmap.yaml: 8 blocks / 52 regs / no overlaps |
| V-Tamper    | SKIP (TODO) | —            | harness pending |

### A-Gates (Phase-1 active subset)

| Axis        | Status         | Last run     | Report |
|-------------|----------------|--------------|--------|
| A-Spec      | **PASS**       | 2026-05-08   | 7 files hashed |
| A-Forward   | SKIP (P8+)     | —            | inactive in P1 |
| A-Coverage  | **PASS**       | 2026-05-08   | 7/7 rules covered by tests |
| A-Drift     | SKIP (Phase 6) | —            | needs hardware run |
| A-Chain     | SKIP (Phase 5) | —            | needs persistent chain |
| A-Bias      | SKIP (Phase 8) | —            | needs replay corpus |

**Audit verdict 2026-05:** **PASS** (2 axes ran, both passed; 4 axes inactive at Phase 1).

---

## Cross-cutting systems

### Verification system (Phase 10)

- Skeleton planned. Concrete runner lands when V-Floor harness is built (Phase 1 sub-task).
- Reports: `verification/reports/`.

### Audit system (Phase 11)

- Skeleton planned. First A-Spec axis lands as part of Phase 1.
- Reports: `audit_system/reports/`.
- Pre-registration directory: `audit_system/pre_reg/` (one file per audit cycle).

---

## Known infrastructure already in place (pre-Phase-1)

Inherited from earlier work — needs auditing against Phase 1 pre-registration:

- `rtl/risk_gate.sv` + `rtl/position_limiter.sv` + `rtl/rate_limiter.sv` +
  `rtl/kill_switch.sv` + `rtl/risk_audit_log.sv` + `rtl/sentinel_sva.sv`.
- `fpga/u55c/` — top-level wrapper, XDC, Vivado + Yosys scripts.
- `sim/` — Verilator harness + `sim_main.cpp` + `sim_risk.cpp`.
- `tests/` — large pytest tree covering APIs, AI backends, compliance, etc.
- Phase 0a Yosys CI synth gate.

The job of Phase 1 is to bring this up to spec — not to rebuild it.
