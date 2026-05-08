# Sentinel-HFT Audit System — Protocol

**Locked:** 2026-05-08
**Status:** v0 (Phase 1 partial — A-Spec + A-Coverage + A-Drift + A-Chain
+ A-Bias active; A-Forward inactive until Phase 8)

This document describes the independent audit system that proves
Sentinel-HFT has been behaving correctly over time. It is a sibling
to the verification system: verification proves the build matches the
spec, audit proves the deployment matches the build's behavior over a
period.

## 1. Cadence

- **During build (Phases 1–14):** monthly. Every calendar month gets
  one audit run.
- **Post-launch (Phase 15+):** quarterly, plus an ad-hoc audit on
  request from a regulator-equivalent reviewer.

## 2. Pre-registration

Before each audit window opens, an entry in
`audit_system/pre_reg/audit_<YYYY_MM>.yml` declares:

- `period`: the date range covered (UTC, inclusive).
- `commit`: the git SHA of the deployed build.
- `axes_active`: which of the six axes will be evaluated.
- `thresholds`: per-axis PASS / WARN / FAIL thresholds.
- `data_sources`: where the evidence comes from (audit chain, replay
  harness, metric exports).
- `kill_criteria`: any single failure that aborts the audit.

Pre-registration is **immutable** once locked. Amendments require an
explicit `amendments:` block at the bottom (matching the volat-agent
pattern).

## 3. Six axes

### A-Spec — Spec equals shipped artifact
- **Question:** does the deployed bitstream match the locked spec at
  the declared commit?
- **Method:** independent re-synthesis from a clean checkout. Compare
  SHA-256 of bitstream. Replay traceability matrix: every spec clause
  has ≥1 RTL block + ≥1 test, and the tests all pass at this commit.
- **PASS:** identical SHA OR documented-and-justified divergence
  (e.g., timestamp); 100% traceability.
- **WARN:** SHA divergence but tests still pass.
- **FAIL:** any spec clause without a test, OR test failure.

### A-Forward — Replay matches expected
- **Question:** if we replay last period's recorded flow against this
  build, do gate decisions match what the audit chain says happened?
- **Method:** Phase 8+ replay harness; compare decision streams.
- **Active from:** Phase 8.

### A-Coverage — Tests exercise every clause
- **Question:** what % of `pre_reg.rules_enforced` clauses are
  exercised by the test suite this period?
- **Method:** map each clause to the test files that exercise it,
  walk pytest collection, count.
- **PASS:** 100% of clauses exercised by ≥1 test.
- **FAIL:** any clause without a test.

### A-Drift — Distributions in band
- **Question:** have latency / reject-rate / accept-rate distributions
  moved beyond pre-registered bands?
- **Method:** compare period histograms against pre-reg bands.
  Bonferroni-corrected χ² per cohort.
- **PASS:** all distributions within band.
- **WARN:** any single distribution outside band but no statistical
  significance.
- **FAIL:** any distribution statistically out of band.

### A-Chain — End-to-end chain integrity
- **Question:** is the audit chain intact across the whole period?
- **Method:** walk every chain segment in the period; verify BLAKE2b
  hashes; check sequence-number gaps; check segment retention against
  the period's retention policy.
- **PASS:** every segment verifies; no sequence gaps.
- **FAIL:** any segment fails OR any sequence gap.

### A-Bias — Cohort consistency
- **Question:** does the gate behave consistently across symbol /
  side / time-of-day cohorts, or is there an undocumented asymmetry?
- **Method:** bucket the period's decisions by cohort. Compute
  reject-rate per cohort. Bonferroni-corrected χ² test.
- **PASS:** no statistically significant deviation per cohort under
  the period's policy.
- **FAIL:** any deviation > 3σ that the policy doesn't predict.

## 4. Verdict

Each axis emits PASS / WARN / FAIL. Overall verdict:

- **PASS** if all active axes are PASS.
- **WARN** if any active axis is WARN and none are FAIL.
- **FAIL** if any active axis is FAIL.

A FAIL is a hard stop: no new release ships until the audit passes.

## 5. Anti-bias guards

- Pre-registration locks **before** the data window. No threshold
  adjustments during evaluation.
- Reviewer of the audit cannot have authored the period's code.
- Random-corpus seeds for synthetic tests are committed in the
  pre-reg, not chosen during evaluation.

## 6. Promotion to launch

To unlock Phase 15 (launch), the audit system must produce **three
consecutive monthly PASS verdicts**.
