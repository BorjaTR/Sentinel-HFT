# Sentinel-HFT FPGA — Spec → RTL → Test Traceability

**Phase:** 1 (FPGA Floor)
**Last updated:** 2026-05-08
**Pre-reg ref:** [`roadmap/pre_reg/phase_01.yml`](../../roadmap/pre_reg/phase_01.yml)

This file is the canonical traceability matrix. Every clause in the
Phase-1 specification (the locked `rules_enforced` list) maps to:

- The **golden** function or branch that defines its semantics.
- The **RTL** module(s) that implement it.
- The **test(s)** that exercise it.
- The **verification axis** that watches it.

A-Spec replays this matrix on every audit run. If any cell becomes
empty, A-Spec is FAIL.

---

## Coverage matrix

| Clause (pre-reg)                   | Golden ref                        | RTL                       | Tests                                                | V-axes that watch it     |
|-----------------------------------|-----------------------------------|---------------------------|------------------------------------------------------|--------------------------|
| `notional_cap_per_order`          | `RejectReason.ORDER_SIZE` branch  | `position_limiter.sv` (`cfg_max_order_qty`) | `tests/test_golden_risk_gate.py::test_per_order_size_rejects_oversized` + V-Floor corpus | V-Floor, V-Meta (M3), A-Coverage |
| `notional_cap_aggregated_rolling` | `RejectReason.NOTIONAL_LIMIT`     | `position_limiter.sv` (`cfg_max_notional`) | `tests/test_golden_risk_gate.py::test_notional_cap_rejects_when_aggregate_exceeds` | V-Floor, A-Coverage |
| `position_cap_aggregated`         | `RejectReason.POSITION_LIMIT`     | `position_limiter.sv` (`cfg_max_long`/`cfg_max_short`) | `tests/test_golden_risk_gate.py::test_position_long_cap` + V-Floor corpus | V-Floor, V-Meta (M2, M3), A-Coverage |
| `order_rate_cap`                  | `RejectReason.RATE_LIMITED`       | `rate_limiter.sv`         | `tests/test_golden_risk_gate.py::test_rate_limiter_rejects_when_empty` + V-Floor corpus | V-Floor, A-Coverage |
| `fat_finger_price_band`           | `RejectReason.FAT_FINGER` branch  | `fat_finger_band.sv` (composed via `risk_gate_v2.sv`)  | `tests/test_golden_risk_gate.py::test_fat_finger_blocks_outside_band` + `::test_fat_finger_passes_within_band` + V-Floor corpus | V-Floor, A-Coverage |
| `symbol_allowlist`                | `RejectReason.ALLOWLIST_BLOCK`    | `symbol_allowlist.sv` (composed via `risk_gate_v2.sv`) | `tests/test_golden_risk_gate.py::test_allowlist_rejects_unknown_symbol` + `::test_allowlist_passes_known_symbol` + V-Floor corpus | V-Floor, A-Coverage |
| `kill_switch_state`               | `RejectReason.KILL_SWITCH`        | `kill_switch.sv`          | `tests/test_golden_risk_gate.py::test_kill_switch_takes_precedence` + `::test_auto_kill_fires_below_loss_threshold` + `::test_heartbeat_always_passes_even_on_tripped_kill` | V-Floor (deterministic), A-Coverage |

**TODO markers** above (G2, G3) reference the gap analysis in
`roadmap/PHASE_01_INVENTORY.md`. The golden model and tests are in
place; the RTL modules are the next Phase-1 deliverable. V-Parity will
fail closed on those clauses until the RTL exists.

---

## Reject precedence (cross-validation)

The reject precedence in the gate is a separate clause that A-Coverage
must keep watching, because every reject reason above depends on
ordering.

| Spec clause                  | Golden ref                                  | RTL                                  | Test |
|-----------------------------|---------------------------------------------|--------------------------------------|------|
| Reject precedence ordering  | `GoldenRiskGate.decide` if/elif chain       | `risk_gate.sv` first-fail compositor | `test_kill_switch_takes_precedence` + `test_heartbeat_always_passes_even_on_tripped_kill` |

V-Floor's RTL leg (Phase-1 sub-task) will exercise the precedence on
every random-corpus order; any disagreement between golden and RTL
ordering is an immediate FAIL.

---

## Status / Statistics registers

The regmap exposes per-rule reject counters. A-Drift (Phase 6+) compares
the period's measured rates to the pre-reg bands.

| Register (regmap.yaml)              | Block                | Source counter |
|-------------------------------------|----------------------|----------------|
| `decision_stats.STAT_TOTAL`         | `decision_stats`     | `risk_gate.sv` `stat_total_orders` |
| `decision_stats.STAT_PASSED`        | `decision_stats`     | `risk_gate.sv` `stat_passed_orders` |
| `decision_stats.STAT_REJECTED_RATE` | `decision_stats`     | `rate_limiter.sv` `total_rejected` |
| `decision_stats.STAT_REJECTED_POS`  | `decision_stats`     | `position_limiter.sv` `total_rejected` |
| `decision_stats.STAT_REJECTED_KILL` | `decision_stats`     | `kill_switch.sv` `orders_blocked` |
| `decision_stats.STAT_REJECTED_FF`   | `decision_stats`     | `fat_finger_band.sv` `total_rejected` (via risk_gate_v2) |
| `decision_stats.STAT_REJECTED_ALLOWLIST` | `decision_stats` | `symbol_allowlist.sv` `total_rejected` (via risk_gate_v2) |
| `decision_stats.STAT_LATENCY_NS_LAST` | `decision_stats`   | gate-level timestamp delta |

---

## How A-Coverage walks this file

1. Parse `roadmap/pre_reg/phase_01.yml` → list of `rules_enforced`.
2. Walk this file's "Coverage matrix" — for each clause, assert at
   least one test exists in `tests/` whose source text contains a
   substring from the clause-to-substring map in `audit_system/runner.py`
   (`rule_to_substrings`).
3. PASS iff all clauses match; FAIL if any clause has no matching test.

Today A-Coverage runs by substring-matching the test corpus. A future
strengthening (Phase 4+) will make A-Coverage run pytest with a
selection marker per clause, so the mapping is enforced by collected
test IDs rather than by string match.
