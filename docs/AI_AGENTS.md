# Sentinel-HFT — AI Agents (Workstreams 4 & 5)

**Status:** v1.1.0 — both phases shipped, REST + UI surfaces wired.
**Owner:** Borja Tarazona
**Last updated:** 2026-04-22

This document is the operator-level reference for the two AI agents in
Sentinel-HFT:

* **Workstream 4 — Phase 1 agent (offline RCA).** A deterministic
  nightly job that turns the day's trace + audit + compliance
  artifacts into a Markdown root-cause digest, archives it, and
  exposes it through a REST + UI surface.
* **Workstream 5 — Phase 2 agent (online triage).** A streaming
  consumer that runs three windowed detectors (latency z-score,
  reject CUSUM, fill-quality SPRT), enriches each firing with an LLM
  one-paragraph suggestion, and persists every alert to a sidecar
  BLAKE2b-chained log.

Both agents share three invariants:

1. **Human-in-the-loop.** Neither agent re-arms or disarms the risk
   gate, neither closes a control loop into the hardware. The RCA
   agent writes Markdown; the triage agent writes alerts. Operators
   read both.
2. **Deterministic by default.** Every prompt is hashed (SHA-256) and
   archived next to the output. The default backend is the
   templated, network-free path so `pytest` and CI runs are
   reproducible.
3. **Tamper-evident.** Triage alerts are persisted in a sidecar file
   with the same BLAKE2b chain discipline as the on-chain risk-audit
   log. The RCA digests are archived with the SHA-256 of their input
   prompt so the regulator can re-derive the digest from the JSON
   sidecar.

---

## Workstream 4 — Nightly RCA digest

### Pipeline

```
out/hl/**                              (drill artifacts: JSON + audit + DORA)
   │
   ▼
sentinel_hft.ai.rca_features.build_features_from_root()
   │   • per-drill throughput, reject histogram, p50/p99/mean stage latency
   │   • audit-chain integrity (record count, head hash, chain_ok)
   │   • compliance rollups (OTR, self-trade, fat-finger, CAT, MAR)
   │   • detector pass: anomaly list (kind / drill / stage / value / baseline / z)
   │   • provenance block (file paths + sha256 + size)
   ▼
sentinel_hft.ai.rca_nightly.run_nightly()
   │   • prompt template (NIGHTLY_PROMPT) + feature dict
   │   • prompt_sha256 = hash of the rendered prompt
   │   • backend dispatch:
   │       - "anthropic"  → Claude Haiku 4.5, temp 0
   │       - "template"   → deterministic, network-free
   │       - "auto"       → anthropic if ANTHROPIC_API_KEY set, else template
   ▼
out/digests/YYYY-MM-DD.md       ← human-readable Markdown
out/digests/YYYY-MM-DD.json     ← machine-readable sidecar (features + prompt hash + backend + model)
```

### Schemas

**Feature schema** — `sentinel-hft/rca-features/1`. Top level keys:
`window`, `drills`, `aggregate`, `anomalies`, `provenance`. See the
docstring of `sentinel_hft/ai/rca_features.py` for the per-drill block
shape.

**Digest schema** — `sentinel-hft/rca-digest/1`. JSON sidecar fields:
`schema`, `date`, `markdown`, `backend`, `model`, `prompt_sha256`,
`generated_at`, `features`.

### Anomaly thresholds (frozen)

The detector pass in `rca_features.py` is intentionally
non-LLM-driven: thresholds are explicit constants so a digest is
auditable bit-for-bit.

| Constant | Value | Meaning |
|---|---:|---|
| `P99_STAGE_NS_WARN` | 10,000 ns | Per-stage p99 above this raises a `latency_spike` anomaly (10 µs is a soft bar for the software-simulation pipeline; tighten to ~1 µs once traces are hardware-sourced) |
| `REJECT_RATE_WARN` | 0.25 | Drill-level reject rate above this raises a `reject_spike` |
| `KILL_TRIGGER_WARN` | true | Any kill-switch firing raises a `kill_triggered` |
| `CHAIN_INTEGRITY` | required | A non-OK audit chain raises a `chain_break` |

The LLM only **explains** candidate root causes for items already on
the anomaly list; it does not invent new anomalies, nor set
thresholds.

### Backend selection

The default in production is `--backend auto`:

* **Anthropic API** — `claude-haiku-4-5`, temperature 0. Used when
  `ANTHROPIC_API_KEY` is set and the `anthropic` package imports
  cleanly. Falls through silently to template on transient API errors
  so the nightly job never blocks ops on a network event.
* **Template** — pure-Python rendering of the same anomaly list into
  the same `## Headline` / `## Anomalies` / `## Candidate root causes`
  / `## Recommended actions` / `## Chain integrity` section layout.
  This is the path used by `pytest` and any air-gapped deployment.

### CLI

```bash
# Run today's digest (default backend = auto)
sentinel-hft ai rca-nightly \
    --artifacts out/hl \
    --digest-dir out/digests

# Force the deterministic path (no API key required)
sentinel-hft ai rca-nightly --backend template

# Re-run a historical date
sentinel-hft ai rca-nightly --date 2026-04-22

# List archived digests, newest first
sentinel-hft ai rca-list --digest-dir out/digests
```

### REST surface (`/api/ai/rca/*`)

Mounted by `sentinel_hft.server.app`. Stateless, read-mostly.

| Method | Path | Body / Query | Returns |
|---|---|---|---|
| `GET`  | `/api/ai/rca/list` | `?digest_dir=…` (override) | `DigestSummary[]` newest first |
| `GET`  | `/api/ai/rca/{iso_date}` | `?digest_dir=…` | `DigestDetail` (404 if missing) |
| `POST` | `/api/ai/rca/run` | `RunDigestRequest` (artifacts_root, digest_dir, date, backend, model — all optional) | `RunDigestResponse` (date, backend, markdown_path, json_path, anomaly_count) |

**Pydantic note.** `DigestSummary.schema` would shadow
`pydantic.BaseModel.schema`, so the wire-name is preserved via
`Field(alias="schema")` + `response_model_by_alias=True`. The
TypeScript client mirrors this in `sentinel-web/lib/sentinel-types.ts`.

### UI surface (`/sentinel/rca`)

Two-column dashboard:

* Left rail — list of archived digests (most recent first), with the
  date, backend tag, and anomaly count per row.
* Right pane — selected digest. Shows backend, model, prompt SHA-256
  (short), schema; an aggregate strip with the first nine top-level
  feature keys; the Markdown body; and the anomaly table coloured by
  severity.

The `Run digest` form on the same page calls `POST /api/ai/rca/run`
with date + backend, then re-fetches the list and auto-selects the
new entry. Useful for both the demo flow and for catching up after a
missed nightly.

### Scheduled-task config

```yaml
# Production cron (UTC)
schedule: "30 4 * * *"
command: |
  sentinel-hft ai rca-nightly \
      --artifacts /var/sentinel/out/hl \
      --digest-dir /var/sentinel/out/digests \
      --backend auto \
      --no-print
env:
  ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
```

The `--no-print` flag suppresses Markdown to stdout — the cron's job
is to write the archive, not flood the operator's mail. Operators
read the archive through the dashboard.

---

## Workstream 5 — Online triage

### Pipeline

```
trace events (PCIe DMA ring in prod / Unix pipe in sim)
   │   each event = TriageEvent { timestamp_ns, kind, stage, value, passed, meta }
   ▼
sentinel_hft.ai.triage_detectors.DetectorEnsemble.observe(event)
   │   ┌──────────────────────────────┐
   │   │ LatencyZScoreDetector        │  per-stage Welford μ/σ; fires at z ≥ z_threshold
   │   │ RejectRateCUSUMDetector      │  two-sided CUSUM on reject stream; fires on drift up
   │   │ FillQualitySPRTDetector      │  Wald SPRT on fill-at-expected-price; fires on log-LR breach
   │   └──────────────────────────────┘
   ▼
sentinel_hft.ai.triage_stream.TriageAgent
   │   • runbook lookup: (detector, severity) → docs/runbooks/{page}.md
   │   • optional LLM enrichment (Claude Haiku 4.5, temp 0, best-effort)
   │   • pager hook (pluggable Callable)
   ▼
sentinel_hft.audit.alert_log.AlertChain.append()
   │   • BLAKE2b-256, low-128-bit prev pointer (same discipline as on-chain risk audit)
   │   • sidecar file: out/triage/alerts.alog
   ▼
verify_chain() / read_alerts() — used by REST + UI
```

### Detectors (mirror `live_bot/circuit_breaker.py` from the Volat project)

| Detector | Stat | Fires on |
|---|---|---|
| `LatencyZScoreDetector` | per-stage Welford mean / stdev | sample exceeds `z_threshold` σ |
| `RejectRateCUSUMDetector` | two-sided CUSUM on reject count | drift up from baseline |
| `FillQualitySPRTDetector` | Wald sequential ratio test on fill@expected | log-LR ≥ `accept_upper` |

All three are pure stdlib (no numpy). Each owns its own rolling
window. Calibration knobs live alongside each class.

### Sidecar alert log

Format spec in the docstring of `sentinel_hft/audit/alert_log.py`.

* **Magic** — `b"SALT"` (Sentinel ALerT)
* **Version** — 1
* **Per-record fields** — framing, seq_no, timestamp_ns, severity
  (info / warn / alert), detector, stage, detail, score (Q32 fixed
  point), window_n, flags, prev_hash_lo (16 bytes), variable-length
  detector / stage / detail bytes, full_hash_lo (16 bytes).
* **Hash chain** — for record `i`: `h_i = BLAKE2b-256(payload)` with
  payload excluding `prev_hash_lo` and `full_hash_lo`. Then
  `record_{i+1}.prev_hash_lo == low128(h_i)` and
  `record_i.full_hash_lo == low128(h_i)`.

A tampered, deleted, or reordered alert fails one of those checks and
`verify_chain()` returns `chain_ok=False` with the exact `bad_index`
and `bad_reason`.

The sidecar is intentionally **separate** from the on-chain risk-audit
log: triage alerts originate in software, are observational, and have
a different schema. Extending the 96-byte RTL record would force a
hardware respin — a sidecar with the same hash discipline gives the
combined verifier a clean two-pass.

### LLM enrichment

When `ANTHROPIC_API_KEY` is set and the `anthropic` package imports
cleanly, each firing gets a one-paragraph plain-English suggestion
appended to the alert detail. When unavailable, a deterministic
template string is used. **Network failure never blocks the alert
from being persisted** — the alert lands in the chain regardless;
only the enrichment text degrades to the template fallback.

### Runbook lookup

`triage_stream.RUNBOOK_PAGES` maps `(detector)` → page fragment.
Operators see one click away from the right runbook entry.

| Detector | Runbook page |
|---|---|
| `latency_zscore` | `docs/runbooks/latency-spike.md` |
| `reject_rate_cusum` | `docs/runbooks/reject-rate-drift.md` |
| `fill_quality_sprt` | `docs/runbooks/fill-quality-degradation.md` |
| (other) | `docs/runbooks/general-incident.md` |

### Evaluation harness

`sentinel_hft.ai.triage_eval.run_evaluation()` replays a scripted,
fully-labelled event stream through `TriageAgent` and scores
precision / recall / F1 against the ground-truth anomaly windows.

* **True positive** — alert raised inside (or within `hit_window_ns`
  after) an injected anomaly window for the same detector family.
* **False positive** — alert outside any anomaly window.
* **False negative** — anomaly window that never produced an alert
  from the matching detector.

Quality bar (current default scenario):

| Metric | Target |
|---|---|
| Recall | 1.0 (every injected anomaly caught) |
| Precision | ≥ 0.70 |
| F1 | ≥ 0.80 |

Pure-Python, deterministic seed, runs in <1 s.

### CLI

```bash
# Run the scripted scenario, print precision/recall/F1
sentinel-hft ai triage-eval

# Persist the full report (events + per-alert detail) to disk
sentinel-hft ai triage-eval -o out/triage/eval_report.json
```

### REST surface (`/api/ai/triage/*`)

| Method | Path | Body / Query | Returns |
|---|---|---|---|
| `GET`  | `/api/ai/triage/alerts` | `?log_path=…&limit=N` (limit 1..10000, default 100) | `AlertChainView` (chain_ok, n_records, head_hash_lo, bad_index/reason, alerts[]) |
| `POST` | `/api/ai/triage/eval` | (none) | `TriageEvalResponse` (events, labelled_anomalies, alerts_fired, TP/FP/FN, precision, recall, F1, anomaly_windows[], alerts[]) |

The `GET /api/ai/triage/alerts` endpoint runs the chain verifier on
every call and returns both the pass/fail verdict and the most-recent
N decoded records. If the file does not exist yet (no alerts have
ever fired), the response is a clean empty chain — not a 404.

### UI surface (`/sentinel/triage`)

Top row:

* **Chain integrity** card — head hash, record count, bad-index (if
  any), table-limit input, refresh button.
* **Eval action** card — run button + 9-stat grid for events,
  labelled anomalies, alerts fired, TP / FP / FN, precision, recall,
  F1.

Below: the most-recent alerts table (most-recent first) with seq,
ISO timestamp (from ns), severity badge, detector, stage, score,
window_n, detail, hash low-128 (8 chars + tooltip).

When an evaluation has been run, an extra drill-down section appears
with the anomaly-windows table (family / stage / matched) and the
eval-alerts table (detector / severity / score / matched=TP/FP).

---

## Cross-agent invariants

### Determinism

Both agents use temperature 0 on the LLM call when one happens, and
both default to a non-LLM path that produces bit-identical output for
identical input. The RCA prompt is hashed (SHA-256) and stored next to
the output. The triage scripted scenario is seeded.

### Replayability

* Every digest's JSON sidecar carries the full feature dict that
  produced it. Re-running `run_nightly` on the same artifact tree
  yields the same Markdown (modulo the LLM backend's own
  determinism).
* Every alert in the sidecar log is independently verifiable: the
  combined `verify_chain` walks the file and re-derives every hash.
* The eval harness is deterministic — the same scripted scenario runs
  the same way on every machine.

### Audit posture

| Surface | Tamper-evident? | Reproducible? | Air-gap-safe? |
|---|---|---|---|
| RCA digest archive | input hash + sidecar features | yes (template backend) | yes (template backend) |
| Triage alert log | BLAKE2b chain | yes (scripted eval) | yes (template enrichment) |

### What the agents intentionally do **not** do

* They never re-arm or disarm the risk gate.
* They never modify a config file or push a parameter change.
* They never write to the on-chain risk-audit log.
* They never block trades on detection — the risk gate already does
  that, deterministically, in hardware.

The agents compress the operator's attention funnel and produce
audit-grade evidence of "what looked off and when". Acting on the
evidence is a human decision.

---

## Code map

```
sentinel_hft/ai/
├── rca_features.py        # WS4 — feature pipeline (deterministic detector pass)
├── rca_nightly.py         # WS4 — prompt + backends + archive writer
├── triage_detectors.py    # WS5 — Welford / CUSUM / SPRT
├── triage_stream.py       # WS5 — TriageAgent + runbook lookup + LLM enrichment
├── triage_eval.py         # WS5 — scripted scenario + precision/recall scorer
└── attribution_explainer.py  # shared LLM helper (used by both)

sentinel_hft/audit/
└── alert_log.py           # WS5 — sidecar BLAKE2b-chained log

sentinel_hft/server/
└── ai_api.py              # FastAPI router mounted at /api/ai/*

sentinel-web/
├── lib/sentinel-api.ts    # typed client: getRcaList / getRcaDetail / runRcaDigest /
│                          #               getTriageAlerts / runTriageEval
├── lib/sentinel-types.ts  # DigestSummary / DigestDetail / AlertChainView / TriageEvalResponse
└── app/sentinel/
    ├── rca/page.tsx       # WS4 dashboard
    └── triage/page.tsx    # WS5 dashboard
```

## Tests

* `tests/test_ai_api.py` — FastAPI router tests for `/api/ai/*` (8/8).
* `tests/test_rca_nightly.py` — end-to-end pipeline + backend selection
  + idempotence tests (12/12).
* `tests/test_triage_detectors.py` — per-detector calibration.
* `tests/test_triage_stream.py` — TriageAgent loop + runbook lookup +
  alert-log persistence.
* `tests/test_triage_eval.py` — quality bar (recall=1.0,
  precision≥0.70, F1≥0.80) on the default scripted scenario.
* `tests/test_alert_log.py` — sidecar format + chain verifier +
  tamper-and-detect.

All tests are network-free by default (template backend, no API
calls) and run in well under one second per file.

## References

* `docs/ROADMAP.md` §Workstream 4 / Workstream 5 — original spec.
* `docs/SENTINEL_CORE_AUDIT.md` — six-axis rubric used to audit the
  core RTL; the audit-chain primitives the alert sidecar mirrors are
  closed under finding `B-S0-1`.
* `docs/COMPLIANCE.md` — regulation × control crosswalk consumed by
  the `aggregate` block of the RCA feature dict.
* `live_bot/circuit_breaker.py` (Volat project) — original
  three-detector design that the WS5 detectors mirror.
