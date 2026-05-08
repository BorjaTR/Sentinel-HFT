# Verification Report — d1a4c11de819

**Run at:** 2026-05-08T06:39:57.670896Z

| Axis | Status | Summary |
|------|--------|---------|
| `v_floor` | **PASS** | Golden corpus determinism verified across all canonical seeds. |
| `v_mutation` | **SKIP** | Mutation testing harness not yet built — Phase 1 sub-task pending. |
| `v_metamorphic` | **PASS** | All 4 metamorphic relations held across 10k pairs each. |
| `v_parity` | **SKIP** | Verilator and/or cocotb not available — see verification/v_parity/README.md. |
| `v_contract` | **PASS** | regmap.yaml: 8 blocks, 52 registers; no overlaps, no duplicate offsets. |
| `v_tamper` | **SKIP** | Audit-chain tamper-injection harness not yet built — Phase 1 sub-task pending. |

**3 PASS · 3 SKIP · 0 FAIL**


## Skipped (Phase-1 work-in-progress)
- `v_mutation` — Mutation testing harness not yet built — Phase 1 sub-task pending.
- `v_parity` — Verilator and/or cocotb not available — see verification/v_parity/README.md.
- `v_tamper` — Audit-chain tamper-injection harness not yet built — Phase 1 sub-task pending.
