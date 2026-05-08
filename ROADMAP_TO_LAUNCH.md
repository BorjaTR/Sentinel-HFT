# Sentinel-HFT — Roadmap to Launch (Portfolio Build)

**Author:** Borja Tarazona
**Status:** Draft v1 — locked 2026-05-08
**Goal:** Build the complete Sentinel-HFT system end-to-end as a portfolio piece.
Every claim demonstrable, every component verifiable, every artifact reproducible
from a clean checkout. Not chasing customers, not chasing revenue, not chasing
regulators — chasing **completeness and provability**.

---

## 0. North Star

A visitor to the GitHub repo can, with no special access:

1. Read the architecture in 15 minutes and understand what each layer does.
2. Run `make demo` and see a real bitstream, a real audit chain, real evidence
   packs, and a real RCA walkthrough — all on their own laptop or a single
   Vivado-equipped machine + U55C.
3. See a CI badge confirming that every claim in the docs is backed by a
   passing test (verification stack) and an independent audit run (audit system).
4. Understand exactly what would still be needed to put this in front of a real
   order book — and exactly what wouldn't.

If a CTO/CRO/CCO at an HFT firm clones the repo on a Saturday afternoon, they
should walk away thinking "this person could build the production version of
this in the right environment." That's the bar.

---

## 1. Operating Principles

These mirror the hard rules you already use for the trading agent — same
discipline, same pre-registration culture, same verify-before-ship pattern.

1. **Phase-gated.** Each phase has explicit ship criteria. Do not start the
   next phase until the current one passes both its V-gate (verification) and
   A-gate (audit).
2. **Pre-registered.** Every phase declares its ship/kill thresholds, test
   matrix, and acceptance bar in writing **before** work starts. Pre-reg files
   live in `roadmap/pre_reg/phase_NN.yml`.
3. **Reproducible.** Every artifact (bitstream, evidence pack, audit report)
   must rebuild byte-identical from a clean checkout in CI. No artisanal
   one-off builds.
4. **No stubs in user-facing paths.** Demo fallbacks are labeled explicitly
   (`MODE=demo`). Anything in the marketing copy on `/sentinel/*` must be
   backed by a passing test.
5. **Verification before publication.** The web surface only advertises a
   capability after the underlying code passes its V-gate.
6. **One-person review boundary.** Cryptographic code (audit chain, signed
   evidence packs) gets at least one external code review before being marked
   done. Everything else is self-reviewed but with a written rationale.
7. **No "almost done."** A phase is either passing all gates or it is in
   progress. There is no middle state in the roadmap.

---

## 2. Phase Map

15 phases. Sequential by default; cross-cutting phases (10, 11) run in
parallel from phase 4 onward.

| # | Phase | Est. duration | Depends on |
|---|---|---|---|
| 1 | FPGA Floor — bitstream, P&R, timing closure | 8–10 weeks | — |
| 2 | Wire-Protocol Adapter (FIX 4.4) | 4 weeks | 1 |
| 3 | Failover & State Replication | 3 weeks | 1, 2 |
| 4 | Policy & Config Plane | 4 weeks | 1 |
| 5 | Audit Chain Persistence + Auditor Read Access | 4 weeks | 1 |
| 6 | Observability & Operational Glue | 2 weeks | 1, 5 |
| 7 | Regulator Evidence Packs | 5 weeks | 5 |
| 8 | Shadow-Mode Replay Harness | 4 weeks | 1, 2, 5 |
| 9 | RCA + Triage Productionization | 4 weeks | 5, 6 |
| 10 | **Verification System** (cross-cutting) | runs from phase 4 onward | 1 |
| 11 | **Audit System** (cross-cutting) | runs from phase 5 onward | 1, 5 |
| 12 | Public-Surface Hardening (`sentinel-web`) | 3 weeks | all |
| 13 | Documentation, ADRs, Demo Reel | 4 weeks | all |
| 14 | End-to-End Launch Rehearsal | 2 weeks | all |
| 15 | **Launch** — public release v1.0 | 1 week | all |

Total bottom-up: ~14–16 months solo, with realistic slack. If you hit 12,
you crushed it; if you hit 18, you didn't. Either is fine for a portfolio
piece — the goal is the artifact, not the date.

---

## 3. Phase Detail

### Phase 1 — FPGA Floor

**Goal:** A working bitstream on U55C that enforces pre-trade risk gates with
deterministic, sub-microsecond decision latency.

**Scope.**
- RTL for the gate (notional cap, position cap, order rate, fat-finger,
  symbol allowlist, kill switch).
- Vivado place-and-route with timing closure at target frequency
  (lock target before starting; 250–322 MHz is realistic for U55C).
- Behavioral simulation matches gate-level simulation matches on-FPGA
  execution (three-way parity).
- Register map documented (one canonical YAML; codegen the C and Rust headers).
- Loadable bitstream + JTAG/PCIe driver glue.

**Deliverables.**
- `fpga/rtl/*.sv` — RTL.
- `fpga/sim/*` — testbenches (cocotb preferred; Verilator for speed).
- `fpga/build/timing_report.txt` — must show all paths met.
- `fpga/regmap.yaml` — single source of truth.
- `fpga/bitstreams/sentinel_v0.1.bit` — first locked bitstream.
- `docs/fpga/ARCHITECTURE.md` — block diagram + data flow.

**V-gate (Phase 1).**
- V1.0: 100% test coverage on gate decision logic (lines + branches).
- V1.1: 10⁶ random orders against RTL sim — zero divergence vs. golden model.
- V1.2: Mutation testing on RTL — every mutation caught by ≥1 test.
- V1.3: Cross-engine parity — RTL sim ≡ gate-level sim ≡ on-FPGA, ≥10⁵ orders.

**A-gate (Phase 1).**
- A1.0: Independent re-synthesis from a clean checkout produces a bitstream
  with identical SHA-256 (or documented reason for divergence — e.g., timestamp).
- A1.1: Timing report independently re-verified.
- A1.2: Spec→RTL traceability matrix complete (every spec clause maps to ≥1
  RTL block + ≥1 test).

**Risk.** P&R timing closure is the single biggest unknown. Budget 10 weeks,
not 6. If it slips, that's fine — it's the foundation.

---

### Phase 2 — Wire-Protocol Adapter (FIX 4.4)

**Goal:** A FIX session manager that proxies orders through the gate with
byte-exact pass-through on accept, and a structured reject on block.

**Scope.**
- FIX 4.4 session layer (logon, heartbeats, sequence numbers, resend).
- NewOrderSingle / OrderCancelRequest / OrderCancelReplaceRequest pass-through.
- Gate decision injected synchronously; rejects emit ExecutionReport with
  rule-specific text + audit-chain hash.
- pcap-replay test harness — feed a captured FIX session, assert byte-exact
  output stream.

**Deliverables.**
- `adapters/fix44/` — adapter binary.
- `tests/pcap/` — captured sessions + expected outputs.
- `docs/adapters/FIX44.md` — supported message types, edge cases, limitations.

**V-gate (Phase 2).**
- V2.0: pcap-replay test — 100 captured sessions, byte-exact match on accept;
  reject reason matches expected on block.
- V2.1: Fuzzing (libFuzzer/AFL) on inbound parse — no crashes in 10⁹ inputs.
- V2.2: Round-trip latency benchmark — p50, p99, p99.99 published.

**A-gate (Phase 2).**
- A2.0: All advertised FIX message types covered by tests.
- A2.1: Reject taxonomy documented and matches what's in `sentinel-web/regulations`.

---

### Phase 3 — Failover & State Replication

**Goal:** Active/standby topology with state replication and auto-failover
in < 10 ms with no order loss.

**Scope.**
- State machine spec for the replicated state (open positions, rate-limit
  counters, kill state).
- Replication via Raft (use `etcd-raft` or similar — don't roll your own).
- Heartbeat + leader-election protocol.
- Chaos harness — kill primary mid-flow, assert standby continues.

**Deliverables.**
- `replication/` — Raft glue.
- `tests/chaos/` — kill-during-flow harness.
- `docs/failover/RUNBOOK.md` — failover playbook.

**V-gate (Phase 3).**
- V3.0: 1000 random kill-points during a 1M-order replay — zero order loss
  in all runs.
- V3.1: Failover latency p99 < 10 ms.
- V3.2: Split-brain test — partition the cluster, verify exactly one leader.

**A-gate (Phase 3).**
- A3.0: Chaos test results published with seed + commit SHA — independently
  reproducible.

---

### Phase 4 — Policy & Config Plane

**Goal:** A first-class control plane that turns a firm's policy doc into
signed gate-parameter blobs, deployable with canary + rollback.

**Scope.**
- Policy DSL (YAML) with schema validation.
- Compiler from policy → gate register values.
- Signed config blobs (Ed25519 detached signature).
- Four-eyes approval flow (two signatures required for production blobs).
- Canary deployment (apply to N% of flow first; auto-rollback on threshold
  breach).
- Audit-logged change history.
- Policy editor UI in `sentinel-web`.

**Deliverables.**
- `policy/schema.yaml` — canonical schema.
- `policy/compiler/` — DSL → registers.
- `policy/signer/` — signing + verification.
- `sentinel-web/app/sentinel/policy/` — editor UI.
- `docs/policy/AUTHORING.md` — guide.

**V-gate (Phase 4).**
- V4.0: Round-trip test — policy YAML → compiler → registers → readback →
  YAML, byte-identical.
- V4.1: Signature verification on every config load — invalid signature
  rejects with no side effects.
- V4.2: Canary auto-rollback under simulated breach.

**A-gate (Phase 4).**
- A4.0: 100% of policy clauses have a corresponding gate test.
- A4.1: Audit log contains every config change with signer identity, blob
  hash, and timestamp.

---

### Phase 5 — Audit Chain Persistence + Auditor Read Access

**Goal:** The BLAKE2b chain lands in WORM-grade storage with an auditor-facing
read API supporting time-bounded slices.

**Scope.**
- Object storage with object lock (S3 or self-hosted MinIO with retention).
- Chain segments rolled hourly; each segment's hash chained to the previous.
- Auditor token system — time-bounded read tokens scoped to a date range.
- Chain-verification CLI (`sentinel-audit verify --from --to`).
- Tamper-injection harness — try to alter a record at rest, verify chain
  rejects.

**Deliverables.**
- `audit/storage/` — storage adapter + retention policy.
- `audit/cli/sentinel-audit` — verifier CLI.
- `audit/tokens/` — token issuer.
- `tests/tamper/` — tamper-injection harness.
- `docs/audit/CHAIN_FORMAT.md` — wire format spec.

**V-gate (Phase 5).**
- V5.0: Tamper-injection — 100 attempts (flip bit, swap block, truncate,
  insert, replay) — chain detects all 100.
- V5.1: Time-bounded slice — token scoped to [t0, t1] cannot read outside
  that window.
- V5.2: Cold-storage round-trip — write segment, retain for retention period
  (simulated), read back, verify.

**A-gate (Phase 5).**
- A5.0: Crypto code passes external review (this is the one place where
  external review is mandatory).
- A5.1: Storage retention configuration documented per regulator's required
  retention period.

---

### Phase 6 — Observability & Operational Glue

**Goal:** Gate metrics, reject reasons, latency histograms flow into a real
ops stack with alerting on policy breaches and latency drift.

**Scope.**
- Prometheus exporter (gate decisions, latency histograms, reject reasons,
  rate-limit counters, audit-chain segment status).
- Grafana dashboard (one canonical JSON, committed).
- Structured JSON logs.
- Alert rules (high reject rate, latency p99 drift, audit-chain segment
  failure).

**Deliverables.**
- `observability/prometheus/exporter.go` (or similar).
- `observability/grafana/sentinel.json`.
- `observability/alerts/rules.yaml`.

**V-gate (Phase 6).**
- V6.0: All exposed metrics have a unit test asserting their range and shape.
- V6.1: Alert rules fire correctly under simulated breach.

**A-gate (Phase 6).**
- A6.0: Dashboard renders end-to-end against a synthetic flow.

---

### Phase 7 — Regulator Evidence Packs

**Goal:** For every regulator the crosswalk supports, auto-generate signed
evidence packs (PDF + JSON) covering a date range.

**Scope (per regulator: SEC Reg SCI, MiFID II RTS 6, FCA SYSC 19F.6, ASIC
RG 241, MAS Notice SFA 04-N09, plus the others in the static crosswalk).**
- Pack template (one per regulator).
- Generator: pulls audit-chain slices, gate decisions, policy versions,
  drill results into a clause-indexed PDF + JSON manifest.
- Detached signature on each pack.
- Periodic schedule (daily / monthly / quarterly per regulator).
- Pack diff between consecutive periods.
- Pack verification CLI.

**Deliverables.**
- `evidence/templates/<regulator>.tex` (or HTML→PDF).
- `evidence/generator/`.
- `evidence/cli/sentinel-evidence`.
- `docs/evidence/PACK_FORMAT.md`.

**V-gate (Phase 7).**
- V7.0: Round-trip — generate pack, verify pack, every clause has a
  citation back to a chain entry.
- V7.1: Diff between consecutive periods is human-readable and machine-parseable.
- V7.2: Pack signatures verify against a known public key.

**A-gate (Phase 7).**
- A7.0: Each clause citation traces back to a real test or a real audit-chain
  entry — no synthesized claims.
- A7.1: Regulator-specific language reviewed against the public reg text.

---

### Phase 8 — Shadow-Mode Replay Harness

**Goal:** Replay synthetic and captured market data through the full stack
and produce trial reports.

**Scope.**
- Replay scheduler (run a scenario from time T to T+N at configurable
  speed multiples).
- Synthetic-flow generator (matches statistical profile of real HFT flow).
- Captured-flow ingester (pcap → replay → report).
- Comparison reports (gate decisions vs. expected, latency histograms,
  reject taxonomy).

**Deliverables.**
- `replay/` — harness.
- `replay/scenarios/` — synthetic scenarios.
- `replay/reports/` — output template.

**V-gate (Phase 8).**
- V8.0: Replay is deterministic — same input + seed → same output.
- V8.1: Replay at 10× speed produces identical decisions to 1× speed.

**A-gate (Phase 8).**
- A8.0: Reports are reproducible from the saved seed and bitstream SHA.

---

### Phase 9 — RCA + Triage Productionization

**Goal:** The incident-RCA and anomaly-triage agents currently surfaced on
`/sentinel/rca` and `/sentinel/triage` are actually wired to real logs,
metrics, and the audit chain — not demo stubs.

**Scope.**
- RCA agent ingests structured logs + metric series + chain entries for a
  declared incident window.
- Triage agent watches gate metrics in real time and raises a triage card
  when anomalies cross thresholds.
- End-to-end flow: incident → triage card → RCA writeup → postmortem
  template populated.

**Deliverables.**
- `agents/rca/` — production version.
- `agents/triage/` — production version.
- `tests/incidents/` — synthetic incident corpus.

**V-gate (Phase 9).**
- V9.0: 50 synthetic incidents → RCA outputs the right root cause for ≥45.
- V9.1: Triage agent detects all injected anomalies in the synthetic corpus.

**A-gate (Phase 9).**
- A9.0: RCA outputs cite chain entries and metrics that actually exist.
  No hallucinated evidence.

---

### Phase 10 — Verification System (cross-cutting)

**Goal:** Six-axis proof that the deployed system equals its specification.
Mirrors the L0-Floor + L6.1–L6.6 model from the trading agent's
`VERIFICATION_STACK.md`, adapted for HFT risk-gate semantics.

**Axes.**
- **V-Floor.** Gate decision matches behavioral spec on 100% of tested orders.
- **V-Mut.** Mutation testing — every mutation in RTL or adapters caught by
  the suite.
- **V-Meta.** Metamorphic — symmetric inputs (e.g., long/short) produce
  symmetric outputs.
- **V-Parity.** Cross-engine parity — RTL sim ≡ gate sim ≡ FPGA execution.
- **V-Contract.** Every interface (FIX, audit, policy, observability,
  evidence) has a contract test.
- **V-Tamper.** Audit-chain tamper-evidence formally proven via fuzz +
  property tests.

**Deliverables.**
- `verification/` — runner that executes all six axes on every CI run.
- `verification/REPORT_TEMPLATE.md` — auto-generated per-run report.
- A CI badge that goes red if any axis fails.

**Ship criterion.** All six axes green for 30 consecutive CI runs before
Phase 15.

---

### Phase 11 — Audit System (cross-cutting)

**Goal:** An independent monthly audit of the deployed system, run on a
schedule and committed to the repo. Mirrors the
`volat-agent/AUDIT_SYSTEM_DESIGN.md` pattern from the trading agent —
pre-registration, anti-bias, statistical rigor, ship/kill thresholds.

**Audit axes.**
- **A-Spec.** Does the shipped binary/bitstream match the locked spec?
  (Hash check + traceability matrix replay.)
- **A-Forward.** Replay last month's recorded flow; do gate decisions match
  expected per the policy in force at the time?
- **A-Coverage.** What percentage of policy clauses are exercised by the
  test suite this month?
- **A-Drift.** Have latency / reject-rate distributions moved beyond their
  pre-registered bands?
- **A-Chain.** Verify the audit chain end-to-end — segment hashes,
  signatures, retention compliance.
- **A-Bias.** Does the gate behave consistently across symbol / venue /
  time-of-day buckets, or is there an unwanted asymmetry?

**Audit cadence.** Monthly during build; quarterly post-launch.

**Pre-registration.** Each audit declares its tests + thresholds **before**
the data window it covers. Pre-reg files in `audit_system/pre_reg/`.

**Verdict.** PASS / WARN / FAIL per axis, with a single overall verdict.
WARN means "look at it"; FAIL is a hard stop on any new release.

**Deliverables.**
- `audit_system/runner/`.
- `audit_system/reports/audit_YYYY_MM.md` (one per month).
- `audit_system/AUDIT_SYSTEM_DESIGN.md` — protocol document.

**Ship criterion.** Three consecutive months of PASS verdicts before
Phase 15.

---

### Phase 12 — Public-Surface Hardening

**Goal:** Every page on `/sentinel/*` corresponds to a real, tested,
verified capability. Marketing copy ≡ implementation.

**Scope.**
- Audit each page against the verification report — anything advertised
  must have a green V-axis.
- Replace any remaining demo stubs with real wiring or remove them.
- Add a "verification status" badge on each page (links to the V-gate
  report for that capability).
- Replace screenshots with live data from the audit chain where possible.

**V-gate (Phase 12).**
- V12.0: For every claim on `/sentinel/*`, a corresponding test or audit
  entry exists. Automated check in CI.

---

### Phase 13 — Documentation, ADRs, Demo Reel

**Goal:** Portfolio-grade docs that let any engineer or reviewer reproduce
the system end-to-end.

**Scope.**
- README rewrite — one-page elevator pitch + quickstart + architecture
  diagram.
- 10–15 ADRs (Architecture Decision Records) covering the major choices
  (Raft vs. paxos, BLAKE2b vs. SHA-256, FIX 4.4 first, U55C target, etc.).
- Per-component runbooks.
- Recorded demo videos (drill execution, evidence-pack generation, RCA
  walkthrough, failover).
- Threat model document.

**Deliverables.**
- `README.md` (rewritten).
- `docs/adr/000N-*.md` (10–15 files).
- `docs/runbooks/` (per component).
- `docs/demos/` (linked to recorded videos hosted somewhere durable).
- `docs/THREAT_MODEL.md`.

---

### Phase 14 — End-to-End Launch Rehearsal

**Goal:** Simulate the full launch on a fresh machine. Catch every
"works on my laptop" surprise.

**Scope.**
- Fresh clone on a clean VM with documented prerequisites.
- Run `make demo` end-to-end.
- Run all V-gates and A-gates.
- Run a full audit cycle.
- Generate one sample evidence pack per regulator.
- Record the entire walkthrough.

**Ship criterion.** Two independent fresh-clone runs succeed end-to-end
with no manual intervention beyond installing prerequisites.

---

### Phase 15 — Launch (v1.0)

**Goal:** Public release.

**Scope.**
- Tag `v1.0.0`.
- Push everything to `origin/main`.
- Publish `sentinel-web` to its hosting target.
- Post the launch writeup (LinkedIn + blog).
- Open the repo for contributions.

**Ship criterion.** Phases 1–14 all closed with green gates.

---

## 4. Verification System Summary

The Verification System is **what proves the build matches the spec at any
given commit**. It runs in CI on every push to `main` and produces a
per-commit report.

| Axis | What it proves | Failure mode |
|---|---|---|
| V-Floor | Gate behavior ≡ spec | Any disagreement on tested order set |
| V-Mut | Tests catch RTL/adapter mutations | Surviving mutations |
| V-Meta | Symmetric inputs → symmetric outputs | Asymmetry under rotation |
| V-Parity | RTL sim ≡ gate sim ≡ FPGA | Cross-engine divergence |
| V-Contract | All interfaces tested at boundary | Contract test missing or red |
| V-Tamper | Chain detects tampering | Tampered chain not rejected |

Every release is gated on **all six axes green for 30 consecutive CI runs**.
A red axis blocks the release; warns are visible but non-blocking.

---

## 5. Audit System Summary

The Audit System is **what proves the deployed system has been behaving
correctly over time**. It runs on a schedule (monthly during build, quarterly
post-launch) and produces a per-period report.

| Axis | What it proves | Failure mode |
|---|---|---|
| A-Spec | Binary/bitstream ≡ locked spec | Hash mismatch w/o documented reason |
| A-Forward | Last period's flow → expected decisions | Decision divergence on replay |
| A-Coverage | Policy clauses exercised by tests | Clauses w/o tests |
| A-Drift | Latency/reject distributions in band | Out-of-band drift |
| A-Chain | Chain end-to-end integrity | Any chain integrity failure |
| A-Bias | Gate behaves consistently across cohorts | Statistically significant asymmetry |

Each audit run **pre-registers** its tests and thresholds before opening
the data window — same pattern you use for the trading agent.

---

## 6. Hard Rules (do not break)

1. **No phase ships without both V-gates and A-gates green.**
2. **No "TODO" in any user-facing path on `/sentinel/*`.**
3. **No claim in copy without a backing test.**
4. **No stub in any binary tagged for release.**
5. **Every artifact reproducible from clean checkout in CI.** Period.
6. **Cryptographic code gets external review.** No exceptions.
7. **Nothing escapes the verification stack.** If you need to skip a check
   to ship, you don't ship.
8. **Pre-register before you build.** Every phase, every audit, every
   change — write the success criteria first, then do the work.

---

## 7. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| FPGA P&R timing closure misses target | High | High | Budget 10 wks not 6; have lower-MHz fallback target |
| Vivado license access | Medium | High | AMD AUP free seats, university programs, or rent |
| Crypto bug in audit chain | Low | Catastrophic | External review mandatory; use stdlib primitives only |
| WORM storage complexity | Medium | Medium | MinIO with object lock as fallback to cloud S3 |
| Regulator clause misinterpretation | Medium | Medium | Cite official text only; never paraphrase |
| Scope creep | High | High | Phase gates are sacred; new ideas → Phase 16 backlog |
| Burnout (solo, 14 months) | High | High | Build in slack; let phases slip without panic |

---

## 8. Backlog (Phase 16+, not in v1.0)

- Second wire protocol (ITCH/OUCH).
- Multi-tenancy.
- Live exchange testnet integration.
- Hardware-backed signing (HSM integration).
- Formal verification (Coq/Lean) of the gate's correctness theorem.
- Web-based replay viewer with timeline scrubbing.

---

## 9. Tracking

- Phase status: `roadmap/STATUS.md` — one-line current state per phase.
- Pre-reg: `roadmap/pre_reg/phase_NN.yml`.
- V-gate reports: `verification/reports/`.
- A-gate reports: `audit_system/reports/`.
- Changelog: `CHANGELOG.md` (one entry per phase close).

---

## 10. What "Done" Looks Like

A reviewer cloning the repo at v1.0 should be able to:

1. Read `README.md` in 5 minutes and understand what this is.
2. Run `make demo` and see a real bitstream load, real orders flow through
   the gate, real audit-chain entries written, and a real evidence pack
   generated for at least one regulator.
3. See the latest `verification/reports/latest.md` showing all six axes green.
4. See the latest `audit_system/reports/audit_YYYY_MM.md` showing all six
   axes PASS.
5. Read the README's "what's not in this build" section and understand
   exactly what would be needed for a real production deployment.

That's the shippable artifact. That's launch.

---

## Changelog

- **2026-05-08** — Initial draft locked. 15 phases sequenced, two
  cross-cutting verification + audit systems specified. Mirrors the
  pre-registration / verification-stack discipline already in use for the
  trading agent.
