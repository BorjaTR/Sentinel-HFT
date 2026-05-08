# Verification Report — a94829c2271d

**Run at:** 2026-05-08T08:00:23.810032Z

| Axis | Status | Summary |
|------|--------|---------|
| `v_floor` | **PASS** | Golden corpus determinism verified across all canonical seeds. |
| `v_mutation` | **PASS** | Mutation survival rate ≤ 5% on the golden decision path. |
| `v_metamorphic` | **PASS** | All 4 metamorphic relations held across 10k pairs each. |
| `v_parity` | **SKIP** | Verilator and/or cocotb not available — see verification/v_parity/README.md. |
| `v_contract` | **PASS** | regmap.yaml: 8 blocks, 52 registers; no overlaps, no duplicate offsets. |
| `v_tamper` | **PASS** | 100/100 tamper attempts detected by golden chain verifier. |

**5 PASS · 1 SKIP · 0 FAIL**


## Skipped (Phase-1 work-in-progress)
- `v_parity` — Verilator and/or cocotb not available — see verification/v_parity/README.md.
