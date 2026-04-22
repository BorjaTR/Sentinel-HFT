# Sentinel-HFT -- Roadmap

*Status: 2026-04-21. Owner: Borja. This doc supersedes the earlier
`IMPLEMENTATION_PLAN.md` for everything that happens AFTER the
M10 integration-readiness milestone closed.*

The repo today is a credible deployment target for an Alveo U55C
co-located crypto trading appliance: deterministic tick-to-trade
RTL core, host-hashed audit trail (on-chip serialiser + off-chip
BLAKE2b chain; an in-fabric BLAKE2b core is a v1.1 Option-B
workstream), a real dual-clock 100 GbE CMAC shim with async-FIFO
CDC and reset synchronisers (Wave 2 closed E-S1-01/02/03), XDMA
trace DMA stubs, honest area + integration-readiness reports.
What's missing is the last-mile assurance work that turns it
from "elaborates cleanly" into "a regulator would sign off on
this" -- and the analytical layer that converts the trace /
audit stream into operational leverage.

This roadmap breaks that work into five workstreams, sized in
engineer-weeks. None of the five depend on each other; they can be
scheduled in parallel as capacity permits. The order below is the
*recommended* order by value-to-effort.

| # | Workstream | Effort | Gate |
|---|---|---|---|
| 1 | Core audit + known-bug fixes | 1 wk | **CLOSED 2026-04-21 — tag `v1.0.0-core-audit-closed`** |
| 2 | Interactive demo UI | 1 wk | UI drives all four drills end-to-end |
| 3 | Extra regulation modules | 2 wk | RTS 6 + 15c3-5 + MAR primitives in-tree |
| 4 | Phase 1 agent (offline RCA) | 4 wk | Nightly digest in production |
| 5 | Phase 2 agent (online triage) | 4 wk | Live alerts driving pager |
| 6 | Phase 3 agent (parameter suggestion, HITL) | 8 wk | Human-approved config changes logged in audit chain |
| 7 | Phase 4 research (in-fabric features) | 4 wk R&D | Feature stream lands on trace record |
| 8 | Phase 5 (closed-loop) | deferred | Requires DORA framework updates that do not exist yet |

---

## Workstream 1 -- Core audit **[CLOSED 2026-04-21]**

**Status.** Closed at tag `v1.0.0-core-audit-closed`. Release
artefacts archived under `docs/releases/v1.0.0/`:
`RELEASE_NOTES.md`, `RE_AUDIT_WAVE4.md`. Closing matrix: all 14 S0 +
19 S1 findings resolved across Waves 0--3 per
`docs/AUDIT_FIX_PLAN.md`, WP3.1 file-level dedup formally deferred to
a dedicated Wave 5 "tooling migration" window with the invariants
declared in `AUDIT_FIX_PLAN.md` §WP3.1, Wave 4 fresh-eyes re-audit
(`RE_AUDIT_WAVE4.md`) produced **zero new S0 findings**. Two
`AUDIT_FIX_PLAN.md` §10 checklist items (Vivado `WITH_CMAC=0` /
`WITH_CMAC=1` P&R + post-route timing) are deferred to the
hardware-bring-up workstream. Workstreams 2--7 are now unblocked.

**Why first (historical).** The whole DORA / MiCA pitch rests on the
core actually doing what the audit log claims. The RTL was authored
by an older model checkpoint 5 months ago, a lot of idioms and
tooling have moved, and nothing gets deployed before a modern audit
pass.

**Scope.** Every `.sv` file under `rtl/`, grouped by area:

* Group A -- risk controls: `risk_gate`, `rate_limiter`,
  `position_limiter`, `kill_switch`, `risk_pkg`
* Group B -- audit trail: `risk_audit_log`, `trace_pkg`,
  `trace_pkg_v12`
* Group C -- shell + pipeline: `sentinel_shell`,
  `sentinel_shell_v12`, `instrumented_pipeline`,
  `stub_latency_core`, `stage_timer`
* Group D -- infrastructure: `sync_fifo`, `fault_injector`,
  `fault_pkg`
* Group E -- ethernet layer: `eth_pkg`, `eth_mac_100g_shim`
  (self-review of the code I landed this session)

**Deliverable.** `docs/SENTINEL_CORE_AUDIT.md` with severity-ranked
findings (S0 blocker, S1 high, S2 medium, S3 nit), spec-vs-impl
drift list, recommended fix order, and test-coverage gaps. Findings
flagged S0/S1 turn into tickets on the main repo and get fixed
before any other workstream merges.

**Audit axes applied to every module:**

1. Spec correctness -- does the module do what its module-header
   comment claims, and does the claim survive a close read of the
   always_ff / always_comb blocks?
2. Determinism -- any reset-state ambiguity? any race conditions
   around ready/valid handshakes? any uninitialized registers?
3. Width correctness -- every assign, every comparison, every
   arithmetic op re-checked for truncation or sign-extension bugs.
4. Back-pressure -- does the module correctly stall upstream when
   downstream is not ready, and does it do so without dropping?
5. Test coverage -- what inputs / edge cases are *not* exercised
   by the existing testbench?
6. Modernisation -- are there idioms (unique case, priority case,
   ieee-1800-2017 interfaces, assertions) that would materially
   clarify the code without changing behaviour?

---

## Workstream 2 -- Interactive demo UI

**Why.** The current `sentinel-web/` is a static HTML snapshot
built by `sentinel_hft/cli/demo.py`. That's fine for "here's what
it looks like" but it's not a thing you can demo live on a
projector or hand to a risk officer to play with. The credible
story for Keyrock is "click through toxic flow / volatility spike /
wire-to-wire drill yourself and see the traces update."

**Scope.**

* A single-page interactive UI (either React + Tailwind single
  artifact, or a FastAPI + HTMX site served from
  `sentinel_hft/web/`).
* Left panel: scenario picker + scenario parameters (sliders for
  tick rate, spread, order size, toxic-flow mix, etc.).
* Right panel: live trace viewer with per-stage latency bars,
  risk-gate decision log, audit-chain verifier, and a PnL ticker.
* Top bar: risk-gate config knobs (rate_max_tokens,
  position_max_long, kill_threshold) exposed as live editors; any
  edit produces a config-write event that lands in the audit log.
* Bottom: the four drills as preset buttons that load canned
  scenarios.

**Backend contract.** The UI talks to a thin FastAPI wrapper around
the existing CLI entry points (`sentinel-hft deribit demo`,
`sentinel-hft hl demo`, etc.). No new simulation logic -- the UI
exercises the same code paths the tests and the CLI drive. This is
important: any divergence between "what the UI shows" and "what the
tests measure" would eat the trust this UI is meant to build.

**Deliverable.**
`sentinel_hft/web/app.py` (FastAPI server) + a single-page UI under
`sentinel_hft/web/static/`. Demo script updated with
"start the server, point your browser at localhost:8787" flow.

---

## Workstream 3 -- Extra regulation modules

**Why.** DORA + MiCA are the EU story. Keyrock also trades on
US derivatives venues, in Switzerland, and in Singapore. Each of
those has an additional regulation that maps onto a small, well-
scoped piece of RTL or host code.

| Regulation | Primitive | Location | Effort |
|---|---|---|---|
| MiFID II RTS 6 | Order-to-trade ratio counter | `rtl/risk_pkg.sv` + `rtl/risk_gate.sv` | 1 d |
| MiFID II RTS 6 | Max message rate per venue | `rtl/rate_limiter.sv` (already there) | -- |
| CFTC Reg AT | Self-trade prevention | new `rtl/self_trade_guard.sv` | 2 d |
| FINRA 15c3-5 | Fat-finger price check | new `rtl/price_sanity.sv` | 1 d |
| FINRA 15c3-5 | Credit / capital check | already covered by position_limiter | -- |
| SEC Rule 613 CAT | Order-event formatter | `sentinel_hft/host/cat_export.py` | 2 d |
| MAR | Spoofing / layering detector | `sentinel_hft/ai/market_abuse.py` | 3 d |
| Swiss FINMA | Operational resilience log export | host-side formatter | 1 d |
| MAS Singapore | Same shape as FINMA | host-side formatter | 1 d |

All of the RTL additions slot into the existing risk-gate fabric
(they extend the `risk_reject_e` enum and add one new
always_comb / always_ff stage each). Total additional LUT cost:
~300 -- still well under 1 % of the U55C budget.

**Deliverable.** New RTL modules + host formatters + `docs/COMPLIANCE.md`
crosswalk mapping each regulation clause to the specific RTL /
host module that satisfies it.

---

## Workstream 4 -- Phase 1 agent (offline RCA)

**Why.** Produces the first visible operational win from the
trace/audit streams. Nightly digest of latency anomalies,
reject-rate drift, fill-quality regressions.

**Scope.**

* Nightly cron job (or scheduled task) that:
  1. Pulls the day's trace + audit archives.
  2. Runs a feature pipeline: per-stage latency percentiles,
     reject-reason histograms, inter-arrival distributions,
     fill-ratio / slippage per venue, audit-chain integrity check.
  3. Hands the features to an LLM with a prompt template that
     produces a Markdown digest: anomalies, candidate root causes,
     recommended actions.
  4. Emails / Slacks the digest to a configured distribution.
* Model choice: local `claude-haiku-4-5` via API or a local
  llama-3.1-70B for air-gapped deployments. Output must be
  deterministic-ish (temp 0, logprobs captured for reproducibility).
* Archive: every digest + the trace features that produced it get
  stored so the agent's recommendations can be back-tested.

**Deliverable.** `sentinel_hft/ai/rca_nightly.py` + scheduled task
config + first two weeks of production digests archived.

---

## Workstream 5 -- Phase 2 agent (online triage)

**Why.** Compresses the attention funnel for the operator. Instead
of watching 200 k traces per second, the operator watches the 5--10
alerts per hour the agent surfaces.

**Scope.**

* A streaming consumer on the trace DMA ring (works off a PCIe
  descriptor ring in production, off a Unix pipe in simulation).
* Windowed statistical detectors: latency z-score per stage,
  reject-rate CUSUM, fill-quality SPRT. These are the three
  detectors we already use in the `live_bot/circuit_breaker.py`
  from the Volat project -- reuse them here.
* On detector firing, an LLM call enriches with context:
  "this looks like the 2026-02 QSFP RX-aligned drop; runbook
  entry at RUNBOOK-013."
* Human-in-the-loop: the agent *alerts*, it does not *act*. Every
  alert is logged in the audit chain (same BLAKE2b chain, new
  record type "alert") so the ops response timeline is
  regulator-reconstructable.

**Deliverable.**
`sentinel_hft/ai/triage_stream.py` + pager hooks + audit-log record
type extension + an evaluation harness that replays a week of real
traces and measures alert precision / recall against a
human-labelled ground truth.

---

## Workstream 6 -- Phase 3 agent (parameter suggestion, HITL)

**Why.** This is where the LLM starts paying back in strategy P&L,
not just ops time. The agent looks at multi-day behavior and
proposes specific config changes with evidence.

**Scope.**

* Every morning, the agent reads the previous day's digest (Phase 1
  output) and the current risk-gate config. It produces a set of
  proposed changes: "shift rate_max_tokens 100 -> 80 on Deribit BTC
  options, evidence: 43 rejects in the 14:00--15:00 UTC window
  correlated with IV spike above 80, proposed change would have
  reduced rejects by 31 with no adverse PnL."
* Each proposal is a structured object with: current value,
  proposed value, evidence summary, counterfactual backtest
  numbers, confidence band.
* A human (trader or risk officer) approves / rejects from the
  interactive UI (workstream 2). The approval event lands in the
  audit chain.
* After approval, the config write goes through the normal AXI-lite
  channel into the risk gate. The risk gate's audit record of the
  config write plus the human approval record form the
  regulator-facing chain of custody.

**Deliverable.**
`sentinel_hft/ai/param_suggest.py` + UI approval workflow + an
offline evaluation harness that measures the suggestions' alpha
over a historical holdout.

---

## Workstream 7 -- Phase 4 (in-fabric features, research)

**Why.** The host-side agent is only as good as the data stream it
consumes. Pushing a handful of lightweight statistical signals into
the FPGA gives the agent per-tick features instead of per-record
features.

**Scope.** Research prototype of three features in fabric:

1. Rolling 10 ms latency percentile per stage (P50 / P95 / P99).
2. Order-flow toxicity proxy -- short-window fill-side imbalance.
3. Per-venue microburst detector -- ticks-per-microsecond over a
   sliding window.

Each feature = 1--2 DSP slices + 1 BRAM + ~200 LUTs. Lands on the
trace record as new fields (requires a v1.3 trace format, backwards
compatible with v1.2).

**Deliverable.** RTL prototype, simulation numbers, and a go / no-go
decision on whether to move any of these into production. If yes,
they slot into a Workstream 8 deployment phase.

---

## Workstream 8 -- Phase 5 (closed-loop)

Deferred. Autonomous parameter tuning without a human in the loop
requires DORA / MiFID framework updates that regulators have
explicitly stated are not going to happen soon. We keep the design
space open but do not build.

---

## Cross-cutting: test-coverage gap list

Every workstream above ships with tests. The repo today has a
~90 % line-coverage Python test suite and a Verilator testbench
that covers the happy path of the risk gate. Below the waterline we
are thin on:

* Property-based testing of the risk gate against a Python oracle
  (planned as part of the audit's group A recommendations).
* Fuzzing the LBUS ingress path of the ethernet shim.
* Coverage-driven test generation for the instrumented pipeline
  (per-stage delta invariants).
* End-to-end replay from a recorded pcap through the shim, shell,
  and risk gate, compared against a Python-computed reference trace.

Each of these is a 1--2 day addition; they land with their owning
workstream rather than as a separate effort.

---

## Decision log

* **2026-04-21 -- Workstream 1 closed, tag `v1.0.0-core-audit-closed`.**
  All 14 S0 + 19 S1 findings from `docs/SENTINEL_CORE_AUDIT.md`
  closed across Waves 0--3; WP1.2 chose Option A (truthful
  serialiser + host-side BLAKE2b chain) over Option B (in-fabric
  BLAKE2b core) which is now a v1.1 workstream. WP3.1 file-level
  legacy dedup deferred to Wave 5 tooling-migration window. Wave 4
  independent re-audit (`docs/releases/v1.0.0/RE_AUDIT_WAVE4.md`)
  produced zero new S0 findings. Workstreams 2--7 unblocked.
* **2026-04-21 -- UI priority elevated.** The user added an
  interactive demo UI to the scope after seeing the 2-pager draft;
  this is worth 1 week of effort and moves in front of the
  regulation workstream because the UI is the delivery surface
  that makes the audit and the agent outputs legible.
* **2026-04-21 -- Closed-loop autonomy deferred indefinitely.**
  No serious European crypto trading firm will deploy autonomous
  parameter tuning against MiFID II / MiCA in the current
  framework. We keep the interface open but do not build.
* **2026-04-21 -- LLM stays on host.** An in-fabric LLM was
  discussed and rejected: physics (ns budget vs μs inference),
  determinism (regulator-opaque), and resource cost (no transformer
  fits in the U55C we care about). The compromise is in-fabric
  feature extraction + host-side LLM agent.
