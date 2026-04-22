# Sentinel-HFT `v1.1.0-compliance-and-agents` — Release Notes

**Tag:** `v1.1.0-compliance-and-agents`
**Date:** 2026-04-22
**Owner:** Borja Tarazona

This release closes **Workstreams 3, 4 and 5** from `docs/ROADMAP.md`
on top of the `v1.0.0-core-audit-closed` core. The audited RTL stays
unchanged — every primitive added in this release lives in the host
software and the demo UI. Three operator-visible surfaces ship: the
regulation × control crosswalk, the nightly RCA digest agent, and the
online triage agent.

## What shipped

### Workstream 3 — Compliance crosswalk and observational counters

A new `sentinel_hft/compliance/` package with seven host-side modules
plus a registry that maps each regulation clause to its primitive,
artifact, host module, and audit signal. All counters are
**observational** — they ride alongside the existing risk-gate
decisions and produce telemetry, they do not block trades.

| Regulation | Module | Primitive |
|---|---|---|
| MiFID II RTS 6 | `mifid_otr.OTRCounter` | order-to-trade ratio (per symbol + global, would-trip flag) |
| CFTC Reg AT | `self_trade_guard.SelfTradeGuard` | self-trade prevention check (per trader, resting-order map) |
| FINRA 15c3-5 | `price_sanity.FatFingerGuard` | fat-finger / erroneous-order price sanity (deviation bps) |
| SEC Rule 613 | `cat_export.CATExporter` | CAT NDJSON event-feed formatter |
| MAR Art. 12 | `market_abuse.MarketAbuseDetector` | spoofing / layering pattern detector |
| FINMA / MAS | `op_resilience.OpResilienceLog` | operational-resilience event log |

The complete crosswalk is in `docs/COMPLIANCE.md` and is exposed at
`/api/compliance/crosswalk` so the UI can render the table live.

### Workstream 4 — Phase 1 agent (offline RCA digest)

Nightly job that turns the day's drill artifacts (JSON reports + DORA
bundles + audit chains) into a Markdown root-cause digest. Pipeline:

```
out/hl/**  →  rca_features.build_features_from_root()
           →  rca_nightly.run_nightly()  →  out/digests/YYYY-MM-DD.{md,json}
```

* Feature pipeline (`sentinel_hft/ai/rca_features.py`) — deterministic
  detector pass (frozen thresholds: `P99_STAGE_NS_WARN = 10 µs`,
  `REJECT_RATE_WARN = 0.25`, kill-switch trigger, chain integrity)
  produces a typed feature dict with provenance (file paths +
  SHA-256 + size).
* Nightly digest (`sentinel_hft/ai/rca_nightly.py`) — terse anomaly-
  driven prompt template. Two backends: Anthropic Claude Haiku 4.5 at
  `temperature=0` when `ANTHROPIC_API_KEY` is set, deterministic
  template fallback otherwise. Auto mode picks the API path when
  available, never blocks ops on a network event. Every digest is
  archived with the full feature dict and the SHA-256 of the rendered
  prompt so the regulator can re-derive it.
* CLI: `sentinel-hft ai rca-nightly` and `sentinel-hft ai rca-list`.

### Workstream 5 — Phase 2 agent (online triage)

Streaming consumer that runs three windowed detectors and persists
every firing to a sidecar BLAKE2b-chained log. The agent is HITL: it
pages, it never re-arms or disarms the risk gate.

* Detectors (`sentinel_hft/ai/triage_detectors.py`) — pure stdlib,
  mirrors `live_bot/circuit_breaker.py` from the Volat project:
  `LatencyZScoreDetector` (Welford μ/σ), `RejectRateCUSUMDetector`
  (two-sided CUSUM), `FillQualitySPRTDetector` (Wald SPRT).
* Online agent (`sentinel_hft/ai/triage_stream.py`) — runbook lookup,
  optional LLM enrichment (best-effort; never blocks persistence),
  pluggable pager hook.
* Sidecar audit log (`sentinel_hft/audit/alert_log.py`) — separate
  `SALT` magic, BLAKE2b-256 with low-128-bit prev pointer, same
  discipline as the on-chain risk-audit log so a combined verifier
  walks both chains in one sweep. Tampered, deleted, or reordered
  alerts fail the chain check with the exact `bad_index`.
* Evaluation harness (`sentinel_hft/ai/triage_eval.py`) — scripted,
  fully-labelled scenario; deterministic seed; quality bar
  recall = 1.0 / precision ≥ 0.70 / F1 ≥ 0.80.
* CLI: `sentinel-hft ai triage-eval [-o REPORT.json]`.

### REST surface

New router mounted at `/api/ai/*` and `/api/compliance/*`:

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/api/compliance/crosswalk` | full crosswalk table for the UI |
| `GET`  | `/api/compliance/live-counter-keys` | which entries have a live counter |
| `GET`  | `/api/compliance/snapshot-shape` | empty `ComplianceSnapshot` for shape-only consumers |
| `GET`  | `/api/ai/rca/list` | archived digests, newest first |
| `GET`  | `/api/ai/rca/{iso_date}` | one digest detail |
| `POST` | `/api/ai/rca/run` | regenerate one digest on demand (default backend = template, no API key required) |
| `GET`  | `/api/ai/triage/alerts` | chain integrity + most-recent N decoded alerts |
| `POST` | `/api/ai/triage/eval` | run the scripted scenario, return precision / recall / F1 |

Stateless and read-mostly. The two mutating endpoints (`rca/run`,
`triage/eval`) do not close a control loop into the engine.

### UI surface

Three new pages in `sentinel-web/app/sentinel/`, all wired into the
left-rail layout and styled to match the existing trading-floor dark
shell:

* `/sentinel/regulations` — full crosswalk table, filterable by
  jurisdiction / status / layer.
* `/sentinel/rca` — two-column dashboard: archived digests on the
  left, selected digest detail on the right. `Run digest` form on the
  same page calls `POST /api/ai/rca/run` and auto-selects the new
  entry.
* `/sentinel/triage` — chain integrity card + eval action card on
  top, recent alerts table below, eval drill-down (anomaly windows +
  per-alert TP/FP) when an evaluation has been run.

The shared typed client is in `sentinel-web/lib/sentinel-api.ts` with
mirrored types in `sentinel-web/lib/sentinel-types.ts` — wire-name
fidelity preserved (e.g. the Pydantic `Field(alias="schema")` on
`DigestSummary` round-trips cleanly through
`response_model_by_alias=True`).

## Regression evidence (archived under `docs/releases/v1.1.0/`)

* **Python test suite:** `pytest tests/` → 474 (v1.0.0 baseline) +
  WS3 / WS4 / WS5 modules added with full coverage. WS4 alone:
  `test_ai_api.py` 8/8, `test_rca_nightly.py` 12/12 in 0.29 s. WS5:
  `test_triage_detectors.py`, `test_triage_stream.py`,
  `test_triage_eval.py`, `test_alert_log.py` — all green, all
  network-free by default.
* **Triage eval harness:** scripted scenario clears the quality bar
  on the default seed (recall 1.0, precision ≥ 0.70, F1 ≥ 0.80) in
  <1 s.
* **RCA reproducibility:** template backend produces bit-identical
  output for identical input. The same-day re-run on a frozen
  `out/hl` tree yields the same `prompt_sha256` and the same
  Markdown.
* **Frontend:** `npx tsc --noEmit` clean for the three new pages and
  the typed client extensions; zero new TS errors introduced (10
  pre-existing errors are unrelated to this release).

## Artefacts in this release

* `docs/AI_AGENTS.md` — operator-level reference for WS4 + WS5:
  pipelines, schemas, thresholds, CLI / REST / UI surfaces,
  scheduled-task config, cross-agent invariants.
* `docs/COMPLIANCE.md` — regulation × control crosswalk, per-module
  primitives, host-vs-RTL split, per-drill counter exposure.
* `docs/releases/v1.1.0/RELEASE_NOTES.md` — this document.
* `sentinel_hft/compliance/` — seven host-side compliance modules +
  registry.
* `sentinel_hft/ai/` — `rca_features.py`, `rca_nightly.py`,
  `triage_detectors.py`, `triage_stream.py`, `triage_eval.py`.
* `sentinel_hft/audit/alert_log.py` — sidecar BLAKE2b-chained alert
  log.
* `sentinel_hft/server/ai_api.py` + extended
  `sentinel_hft/server/demo_api.py` — REST routers for `/api/ai/*`
  and `/api/compliance/*`.
* `sentinel-web/app/sentinel/{regulations,rca,triage}/page.tsx` —
  three new dashboard pages.
* `sentinel-web/lib/sentinel-{api,types}.ts` — typed client
  extensions.

## Out of scope for this tag

* **Workstream 6 — Phase 3 agent (parameter suggestion, HITL).**
  Reads the previous day's RCA digest + current risk-gate config and
  proposes structured parameter changes. Catalogued in
  `docs/ROADMAP.md`; a v1.2 workstream.
* **Production CAT submission pipeline.** The CAT exporter produces
  the NDJSON event feed in the regulator-published shape; the
  delivery to the central CAT processor (CSV bundling, encryption,
  SFTP / web upload) is intentionally a separate operations
  workstream and stays out of the demo.
* **In-fabric BLAKE2b core (WP1.2 Option B).** Still a v1.1+
  workstream; the host-side chain is the truth source.
* **Hardware-sourced trace ingest for the triage agent.** Current
  ingest path is a Unix pipe / file-like; the PCIe DMA descriptor
  ring on real silicon is part of the hardware-bring-up workstream
  and stays out of this release.
* **Mutation testing on the new compliance modules.** Targeted in a
  follow-up; `risk_gate` mutation testing remains the only module
  with a >90% kill rate baseline.

## Tag reference

```bash
# Once the tree is clean and this release is merged to the default branch:
git tag -a v1.1.0-compliance-and-agents -m "WS3 compliance + WS4 RCA + WS5 triage; see docs/releases/v1.1.0/"
git push origin v1.1.0-compliance-and-agents
```

The tag marks the first shippable state of the regulator-facing
surfaces and the operator-attention agents on top of the audited
core.

## What unblocks

With Workstreams 3 / 4 / 5 closed, the natural next picks per
`docs/ROADMAP.md` are:

* **Workstream 6** — Phase 3 agent (parameter suggestion, HITL).
  Builds directly on the WS4 digest archive and the existing
  risk-gate config surface.
* **Hardware bring-up** — Vivado place-and-route on the U55C, post-
  route timing, real-silicon trace ingest. Unlocks the triage
  agent's PCIe DMA descriptor-ring path.
* **Workstream 7** — pre-trade attribution explainer (the LLM
  consumes risk-gate decisions in real time and produces a one-line
  reason string per reject). Foundation already present in
  `sentinel_hft/ai/attribution_explainer.py`.

## Acknowledgements

Compliance-module designs cross-checked against the published
regulatory texts cited inline in each module's docstring. WS4 / WS5
agent designs reuse the three-detector circuit-breaker pattern
established in the Volat project's `live_bot/circuit_breaker.py`
(post-Finding-6 patch). UI styling matches the trading-floor dark
shell established in `v1.0.0` for `/sentinel/{toxic_flow,kill_drill,
latency,daily_evidence,audit}`.
