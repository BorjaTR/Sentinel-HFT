# Sentinel-HFT v2.3 — Multi-Session Implementation Plan

**Owner:** Borja Tarazona
**Start:** 21 April 2026
**Target:** Deployable FPGA reference + Keyrock-ready demo
**Sessions:** ~5 sessions over ~1 week

---

## Goal

Turn Sentinel-HFT from "interesting open-source repo" into a **deployable reference implementation + sharp Keyrock interview demo** that credibly says:

> Here is a production-grade, DORA-compatible FPGA observability and risk stack
> for crypto market makers. It runs on Alveo hardware, it attributes latency across
> on-chain and CEX paths, it emits host-hashed (BLAKE2b) audit evidence with
> chain-break detection at the verifier, and the AI RCA doesn't leak your traces
> to a third-party API.

Non-goals: tier-1 HFT production hot-path adoption, a SaaS business, a Corvil replacement.

---

## Baseline (confirmed 21 April 2026)

- **Tests:** 330 passing, 60 skipped (RTL-sim, require Verilator). Was 3 failing — `demo` CLI + test-drift. Fixed in this session.
- **RTL:** 2,434 lines SystemVerilog. v1.2 attribution shell, risk gate (rate + position + kill switch), fault injector, stage timer, sync FIFO. Clean packages.
- **Python:** 40+ modules. Streaming analyzer with P², streaming attribution, v1.1/v1.2 readers, CLI, FastAPI server, Prometheus/Slack exporters, wind-tunnel fault-injection replay, protocol correlation (Optimism/Arbitrum).
- **AI:** 1,332 lines. Anthropic-only (hard dependency on `ANTHROPIC_API_KEY`). Pattern detection + fact extraction + prompt templates are solid.
- **Web:** Next.js app (not blocked on, but will refresh styling in M7 if time).
- **Monitoring:** Prometheus + Grafana provisioning in place.
- **Docs:** Reasonable USAGE / INSTALL / ARCHITECTURE. Market-fit brief already written.

**Verdict:** the skeleton is solid. The plan is to *extend*, not rewrite.

---

## Milestones

| # | Module | Status | Session |
|---|--------|--------|---------|
| M1 | Baseline + plan | Done | 1 |
| M2 | Local-only AI RCA (pluggable backends) | Pending | 1 |
| M3 | Hyperliquid / on-chain latency attribution | Pending | 2 |
| M4 | Host-hashed risk audit trail (DORA; on-chip serialiser + off-chip BLAKE2b) | Pending | 2–3 |
| M5 | Deribit LD4 end-to-end demo pipeline | Pending | 3 |
| M6 | FPGA-deployable target (Alveo synthesis) | Pending | 4 |
| M7 | Demo artifacts + README + CI | Pending | 5 |

Each milestone has an explicit acceptance test below.

---

## M2 — Local-only AI RCA (the biggest adoption objection)

**Why:** No prop desk will route cycle-accurate trading traces through Anthropic's public API. That single concern kills Option A (DORA audit evidence) as shipped.

**Deliverable:**

- Refactor `ai/explainer.py` into a pluggable backend interface:
  - `AnthropicBackend` (existing behaviour, optional)
  - `OllamaBackend` (local HTTP to `localhost:11434`, default models `llama3.1:8b` / `qwen2.5:7b`)
  - `DeterministicBackend` (no LLM — template-driven RCA from `FactSet` + `PatternDetectionResult`; always works offline)
- `SENTINEL_AI_BACKEND` env var + CLI flag (`--ai-backend {auto,anthropic,ollama,none}`) with `auto` preferring Ollama → Deterministic → Anthropic (deliberately reversed from current default).
- Grounded prompts: inject real numeric facts into the prompt, not free-form narrative (prevents hallucinated latency numbers).
- Tests (mock all backends, no network).

**Acceptance:**

- `SENTINEL_AI_BACKEND=none sentinel-hft explain traces.bin` works with zero external deps and zero network.
- Existing `tests/test_h4_ai_explainer.py` continues passing.
- New tests cover Ollama error paths + deterministic output structure.

---

## M3 — On-chain / Hyperliquid latency attribution

**Why:** It's the "why now" hook for April 2026. Hyperliquid + Lighter + Solana/Jito are the growth venues; no observability tool covers them. This is the demo that makes a Keyrock engineer open the repo.

**Deliverable:**

- New trace record type: `v1.3` (or a sibling schema) with on-chain-specific stages:
  - `d_rpc`: RPC fetch latency (book state)
  - `d_quote`: strategy quoting latency (host-side)
  - `d_sign`: transaction signing
  - `d_submit`: submission to relayer / JitoBAM
  - `d_inclusion`: time to block inclusion (post-submit)
  - optional `d_settle`: settlement confirmation
- `sentinel_hft/onchain/` module:
  - `hyperliquid_ingest.py`: reads Hyperliquid API / WS traces + public block data
  - `solana_ingest.py`: Jito relayer timestamp extraction
  - `attribution.py`: per-stage streaming quantiles (reusing `streaming/quantiles.py`)
- Synthetic fixture generator (`sentinel_hft/onchain/fixtures.py`) for CI.
- CLI: `sentinel-hft onchain analyze <path>`
- Tests.

**Acceptance:**

- Demo command `sentinel-hft demo --onchain` generates fixture traces, runs attribution, prints per-stage P50/P99/P99.9 table.
- Attribution correctness: synthetic traces with known injected delays recover the injected values within expected quantile error.

---

## M4 — Host-hashed risk audit trail (DORA)

**Why:** This is the regulatorily-defensible wedge. DORA Article 18 mandates hard incident reporting evidence; today no FPGA tool emits it.

**Division of responsibility** (Option A, per `AUDIT_FIX_PLAN.md` §WP1.2): the RTL is a pure *serialiser* that enforces ordering, the host is the trusted *hasher* that computes BLAKE2b and walks the chain. Putting a BLAKE2b core on-chip adds silicon with no trust gain, because the host would have to recompute it anyway to verify.

**Deliverable:**

- RTL module: `rtl/risk_audit_log.sv`:
  - Emits one record per risk decision (order_hash, decision, reject_reason, timestamp, seq_no).
  - Monotonic `seq_no` — advances only on committed writes.
  - 128-bit `prev_hash_lo` input port driven by the host over DMA; captured into the record at commit time.
  - `REC_OVERFLOW` in-band marker when the sink stalls, so a drop is distinguishable from a tamper.
- Host verifier: `sentinel_hft/audit/verifier.py` — reads exported log, computes BLAKE2b per record, walks `prev_hash_lo` to detect tamper / insertion / deletion, emits DORA-shaped JSON.
- Testbench: `rtl/tb_risk_audit_log.sv`.
- CLI: `sentinel-hft audit verify <path>`, `sentinel-hft audit export --dora <path>`.

**Acceptance:**

- Any injected byte flip in an exported record is detected by the host verifier at the exact sequence number.
- Verifier runs in <2s on 1M records.
- DORA JSON export conforms to a pinned schema (`sentinel_hft/audit/schemas/dora_v1.json`).

---

## M5 — Deribit LD4 end-to-end demo pipeline

**Why:** Closest to what Keyrock actually runs. The "one thing I built that you don't have" demo.

**Deliverable:**

- `demo/deribit/` fixture generator: synthesised BTC/ETH options market data in Deribit's native-ish wire shape
- Host-side pipeline: fixture → Verilator sim (v1.2 shell) → traces → streaming analyzer → Grafana
- Preset Grafana dashboard: `monitoring/grafana/dashboards/sentinel-deribit.json` with per-stage attribution, risk-gate rejections, P99.9 tail.
- Runbook: `docs/DEMO_DERIBIT.md` — reproduce in ≤5 minutes on a laptop.
- Fallback path if Verilator is unavailable: Python simulator (`sentinel_hft/sim/python_shell.py`) with matching trace output so the demo works anywhere.

**Acceptance:**

- `make demo-deribit` runs end-to-end and opens the dashboard.
- Dashboard shows non-trivial attribution and at least one injected tail spike.

---

## M6 — FPGA-deployable target (Alveo)

**Why:** Makes "deployable" a real claim, not marketing.

**Deliverable:**

- `rtl/synth/` directory:
  - `top_alveo_u55c.sv` (or U50) wrapper with PCIe/DMA stubs
  - `constraints/alveo_u55c.xdc` — timing, clock, I/O
  - `constraints/false_paths.xdc` for instrumentation
- `synth/Makefile` or `synth/build.tcl` for Vivado batch flow
- Dockerfile for reproducible Vivado build (Vivado itself not shipped, but paths/versions pinned)
- `.github/workflows/synth-check.yml`: lint + elaboration check (no full synthesis in free CI; document how to run timing closure locally)
- Utilisation/timing report template that CI fails on regression

**Acceptance:**

- `make synth-elaborate` succeeds headlessly (no license-gated steps).
- Resource budget documented: ≤5% LUTs + ≤2% BRAM for the observability + risk layer on Alveo U55C.
- Known-good timing report committed as baseline.

---

## M7 — Demo artifacts + CI

**Deliverable:**

- Rewrite top-level `README.md` to lead with **"DORA-compatible observability + audit evidence for crypto HFT FPGAs"** — not the current generic framing.
- `docs/keyrock-2pager.md` — outreach-ready 2-pager referencing specific built features.
- Architecture diagram (Mermaid, committed in markdown).
- Demo script (`docs/DEMO_SCRIPT.md`) — 10-minute live walkthrough.
- Harden `.github/workflows/*`: run the full pytest suite, lint, elaboration check, on PR.
- End-to-end regression: `tests/test_e2e_demo.py` covering Deribit + Hyperliquid fixture paths.
- Update `docs/keyrock-market-fit-brief.md` with a "what was built" appendix.

**Acceptance:**

- A first-time visitor can clone and run `make demo` successfully in under 10 minutes.
- README top section passes the "would an FPGA Lead read past the first paragraph?" test.

---

## Risks + how we blunt them

| Risk | Impact | Mitigation |
|------|--------|------------|
| Verilator unavailable in sandbox | Can't exercise RTL | Python simulator fallback in M5; mark RTL sim as optional in CI |
| Ollama not on the demo machine | M2 backend unreachable | Deterministic backend is always-on default |
| Vivado license-gated | Can't prove synthesis closes timing | Ship elaboration-only flow + documented manual closure, not marketing "production-ready synthesis" |
| Hyperliquid API shape changes | M3 fixtures rot | Freeze fixture format in-repo; document how to refresh from live API |
| Scope creep (web UI, protocol correlation extensions) | Miss milestones | Strict "not this week" list: no new web UI features, no new L2 protocol adapters, no new quantile algorithms |

---

## Cross-cutting standards

- **No new dependencies** in `[all]` extras without an offline fallback.
- **All new RTL must build cleanly under Verilator** (used in CI) and **elaborate cleanly under Vivado** (checked in M6).
- **No Python in the FPGA critical path**, ever. Python is for analysis, orchestration, demo, and CI.
- **Every new CLI command has a `--dry-run`** option for use in CI without side effects.
- **Every new module has a test** before it's merged into main.
- **No network calls in default code paths**. AI explanations, DORA exports, and on-chain ingest must work offline from cached fixtures.

---

## "Not this week" list

Things explicitly deferred — so we stay honest about scope.

- Multi-core RTL coherency
- Full Solana transaction tracing end-to-end (only fixture-level attribution)
- Live Hyperliquid replay (only offline fixture ingest)
- HdrHistogram replacement of P² (note the trade-off in README instead)
- Web UI redesign
- MiCA reporting formats beyond DORA JSON
- Alveo U55C bitstream actually flashed to hardware (only validated synthesis)

---

## Demo narrative (the thing this whole plan serves)

The elevator version I'll run end-to-end at the end of M7:

> Sentinel-HFT wraps your FPGA trading cores with always-on, non-invasive,
> cycle-accurate instrumentation. It breaks latency down per stage — including
> on-chain paths for Hyperliquid, Lighter, and Solana MEV. Every risk-gate
> decision emits a hash-chained audit record that DORA supervision can verify
> byte-for-byte. The AI root-cause analysis runs on a local model by default —
> your traces never leave your infrastructure. And the whole thing targets
> Alveo U55C with a reference bitstream, so you can try it on your bench
> before trusting it in production.

If a Keyrock engineer says "show me the Hyperliquid part," the demo is 90 seconds. If they say "show me the DORA part," it's another 60. If they say "how much does this cost in LUTs," there's a committed timing report.
