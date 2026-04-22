# Sentinel-HFT — Compliance Crosswalk (Workstream 3)

**Status:** v1.1.0 — nine clauses crosswalked, six host-side modules
shipped, two existing RTL primitives reused, one synthesizable RTL
twin per implemented host module pending hardware bring-up.
**Owner:** Borja Tarazona
**Last updated:** 2026-04-22

This document is the regulator-facing reference for the compliance
layer. Its rows mirror `sentinel_hft.compliance.crosswalk.CROSSWALK`
verbatim — the demo API serves the same payload at
`/api/compliance/crosswalk` and the `/sentinel/regulations` UI
renders it. If a row here disagrees with the registry the registry
wins.

## What this layer is — and is not

* **Observational, not blocking.** Every primitive in
  `sentinel_hft/compliance/` records counters and (where applicable)
  raises a `would_reject_*` flag. None of them flip the
  `decision.passed` bit owned by the on-chip risk gate. The host
  stack is wired into the Hyperliquid runner via
  `runner._compliance` and rides alongside the existing decision
  stream.
* **Aligned with audited RTL.** Where the regulation is naturally a
  pre-trade gate (rate limiter, position / notional caps), the
  compliance row points at the existing audited RTL primitive —
  these were closed as part of `v1.0.0-core-audit-closed`. Where the
  regulation is a pattern alert, a counter, or a formatter, the host
  module is the source of truth and the RTL twin (when one ships) is
  a synthesizable reference at line rate.
* **One snapshot shape, stable across releases.** The
  `ComplianceSnapshot` dataclass exposes one dict per implemented
  primitive (`mifid_otr`, `cftc_self_trade`, `finra_fat_finger`,
  `sec_cat`, `mar_abuse`). Any key-name change must land in
  `sentinel-web/lib/sentinel-types.ts::ComplianceSnapshot` in the
  same commit.

## Crosswalk

| # | Key | Regulation | Jurisdiction | Clause | Layer | Status | Live counter |
|--:|---|---|---|---|---|---|:--:|
| 1 | `mifid_otr` | MiFID II RTS 6 | EU | Art. 2(2)(g) · Art. 15 order-to-trade ratio | Host | implemented | ✓ |
| 2 | `mifid_rate_limit` | MiFID II RTS 6 | EU | Art. 15 max message rate | RTL | reused | — |
| 3 | `cftc_self_trade` | CFTC Reg AT | US | 17 CFR § 1.80 / § 40.22 self-trade prevention | Host | implemented | ✓ |
| 4 | `finra_fat_finger` | FINRA 15c3-5 | US | SEA Rule 15c3-5(c)(1)(ii) erroneous-order check | Host | implemented | ✓ |
| 5 | `finra_credit` | FINRA 15c3-5 | US | SEA Rule 15c3-5(c)(1)(i) credit / capital check | RTL | reused | — |
| 6 | `sec_cat` | SEC Rule 613 (CAT) | US | 17 CFR § 242.613 order-event reporting | Host | implemented | ✓ |
| 7 | `mar_abuse` | MAR | EU | Art. 12 spoofing & layering | Host | implemented | — |
| 8 | `finma_resilience` | Swiss FINMA OpResilience | CH | FINMA Circ. 2023/1 §49–58 | Host | implemented | — |
| 9 | `mas_resilience` | MAS Notice TRM | SG | MAS Notice 644 §6.4 operational-risk reporting | Host | implemented | — |

The five rows with a check in **Live counter** drive the
`event.compliance[KEY]` cells the WS progress event ticks against
the dashboard. The other four are static (the rate limiter and
position limiter live in audited RTL and surface as the existing
`rejected_rate` / `rejected_pos` / `rejected_notional` audit-log
fields; FINMA / MAS are end-of-day envelopes; MAR alerts surface in
the `mar_abuse.last_alerts` block of the snapshot rather than as a
single tick).

## Per-module reference

### 1 — `mifid_otr` (MiFID II RTS 6, Art. 15)

* **Module:** `sentinel_hft/compliance/mifid_otr.py::OTRCounter`
* **RTL twin:** `rtl/otr_counter.sv` (synthesizable; not in the
  shipped 1.0.0 bitstream)
* **Primitive:** order-to-trade ratio per symbol. `observe(symbol_id,
  filled)` increments orders, optionally trades, and returns
  `True` when the per-symbol ratio exceeds `max_ratio_per_symbol`
  (default 100:1 to match Keyrock's live config).
* **Snapshot fields:** `total_orders`, `total_trades`,
  `global_ratio`, `worst_symbol_ratio`, `max_ratio_per_symbol`,
  `would_trip`.
* **Audit signal:** `otr_ratio`, `otr_orders`, `otr_trades`,
  `otr_rejects`.

### 2 — `mifid_rate_limit` (MiFID II RTS 6, Art. 15)

* **Module:** *reused* — `rtl/rate_limiter.sv` (audited and shipped
  in `v1.0.0-core-audit-closed`).
* **Primitive:** token-bucket per symbol / trader; reject reason
  surfaces in the audit log as `rejected_rate`.
* **No host mirror.** The counter is the existing `rejected_rate`
  audit-log field; the dashboard pulls it from the standard progress
  event, not from the compliance snapshot.

### 3 — `cftc_self_trade` (CFTC Reg AT, 17 CFR § 1.80 / § 40.22)

* **Module:** `sentinel_hft/compliance/self_trade_guard.py::SelfTradeGuard`
* **RTL twin:** `rtl/self_trade_guard.sv` (synthesizable; not in the
  shipped 1.0.0 bitstream)
* **Primitive:** maintains a per-`trader_id` register of resting
  orders. `check(trader_id, symbol_id, side, price, quantity)`
  returns `True` if the incoming intent would self-cross
  (buy ≥ resting sell or sell ≤ resting buy) on the same instrument.
* **Crossing rule (matches CFTC Reg AT commentary):**
  incoming BUY crosses resting SELL if `buy_px ≥ sell_px`; incoming
  SELL crosses resting BUY if `sell_px ≤ buy_px`.
* **Snapshot fields:** `checked`, `rejected`, `reject_rate`,
  `traders_tracked`, `resting_orders`.
* **Audit signal:** `self_trade_rejects`.

### 4 — `finra_fat_finger` (FINRA 15c3-5(c)(1)(ii))

* **Module:** `sentinel_hft/compliance/price_sanity.py::FatFingerGuard`
* **RTL twin:** `rtl/price_sanity.sv` (synthesizable; not in the
  shipped 1.0.0 bitstream)
* **Primitive:** rolling per-symbol last-trade price; `check(sym,
  price)` returns `True` if the order's price deviates from the last
  trade by more than `max_deviation_bps` (default 500 bps = 5%).
  Unknown symbols (no reference price yet) always pass.
* **Snapshot fields:** `checked`, `rejected`, `reject_rate`,
  `max_deviation_bps`, `worst_deviation_bps`, `symbols_tracked`.
* **Audit signal:** `fat_finger_rejects`.

### 5 — `finra_credit` (FINRA 15c3-5(c)(1)(i))

* **Module:** *reused* — `rtl/position_limiter.sv` (audited and
  shipped in `v1.0.0-core-audit-closed`).
* **Primitive:** per-account long / short / notional caps enforced
  at line rate.
* **Audit signal:** `rejected_pos + rejected_notional`. As above, no
  host mirror — the dashboard reads the standard audit-log fields.

### 6 — `sec_cat` (SEC Rule 613 — Consolidated Audit Trail, Phase 2e)

* **Module:** `sentinel_hft/compliance/cat_export.py::CATExporter`
* **Primitive:** transforms each order event (NEW / CANCEL /
  MODIFY / TRADE / REJECT) into the 23-field CAT Industry Member
  record (JSON flavour). Emits one record per event to an NDJSON
  feed (default `{output_dir}/cat_feed.ndjson`).
* **Event-type alphabet:** `MENO` (new order), `MECR` (cancel /
  route), `MEOM` (modify), `METR` (trade), `MEOR` (reject).
* **Snapshot fields:** `total_records`, `by_event_type`,
  `output_path`.
* **Out of scope:** the delivery to the central CAT processor (CSV
  bundling, encryption, SFTP / web upload). The exporter produces
  the file in the regulator-published shape; physical submission is
  an operations workstream.

### 7 — `mar_abuse` (MAR Art. 12)

* **Module:** `sentinel_hft/compliance/market_abuse.py::SpoofLayerDetector`
* **Primitive:** rolling per-`(trader_id, symbol_id, side)` window;
  raises one alert when ≥ `min_cancelled` (default 30) same-side
  NEWs are cancelled within `window_ns` (default 200 ms) without any
  fill on that side. Orders cancelled in under
  `min_time_on_book_ns` (default 5 ms) are filtered out as MM
  re-papering noise.
* **Snapshot fields:** `min_cancelled`, `window_ns`, `orders_seen`,
  `cancels_seen`, `fills_seen`, `alerts`, `last_alerts[]` (with
  `trader_id`, `symbol_id`, `side`, `n_orders`, `window_ns`,
  `first_order_ns`, `last_cancel_ns`).
* **Why host-only:** Art. 12 is a pattern over a rolling window,
  better suited to a software detector than to the line-rate gate.
  No RTL twin shipped or planned for v1.x.

### 8 — `finma_resilience` (Swiss FINMA Circ. 2023/1 §49–58)

* **Module:** `sentinel_hft/compliance/resilience_log.py::ResilienceLog`
* **Primitive:** end-of-day immutable JSON envelope. Records
  incidents (severity, component, RTO seconds, RPO records), binds
  to the audit-chain head hash, and writes a SHA-256 over the
  canonicalized envelope so the file is independently verifiable.
* **Configuration:** `jurisdiction='CH'` for FINMA.
* **Snapshot fields:** `jurisdiction`, `trading_date`, `incidents`,
  `worst_severity`, `audit_anchored`.
* **Envelope keys:** `trading_date`, `jurisdiction`, `subject`,
  `environment`, `generated_at`, `rto_target_seconds`,
  `rpo_target_records`, `incidents[]`, `incident_count`,
  `worst_severity`, `audit.{head_hash_lo_hex, record_count}`,
  `envelope_hash_sha256`.

### 9 — `mas_resilience` (MAS Notice TRM, MAS Notice 644 §6.4)

* **Module:** *same as FINMA* —
  `sentinel_hft/compliance/resilience_log.py::ResilienceLog`
* **Configuration:** `jurisdiction='SG'`.
* **Why same module:** the operational-resilience reporting shape is
  almost identical between FINMA Circ. 2023/1 §49–58 and MAS Notice
  TRM §6.4; the envelope keys cover both. The `jurisdiction` field
  in the envelope is the only thing that needs to flip.

## Aggregator and surfaces

### Host stack (`ComplianceStack`)

`sentinel_hft.compliance.stack.ComplianceStack` aggregates all five
live-counter primitives. It exposes:

* `on_trade(symbol_id, price, ts_ns)` — feed public-trade prints to
  the OTR denominator and the fat-finger reference price.
* `observe(intent=..., decision=..., ts_ns=..., trader_id=...)` —
  one call per intent. Returns
  `{would_reject_otr, would_reject_self_trade,
  would_reject_fat_finger, mar_alert}` so the runner can surface
  compliance warnings in the trace. Never modifies `decision.passed`.
* `snapshot()` → `ComplianceSnapshot` — the dict the UI binds to.
* `as_dict()` — JSON-safe shape (the wire format).

### REST surface (`/api/compliance/*`)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/compliance/crosswalk` | full crosswalk table for the UI; payload is `{entries[], live_counter_keys[], count}` |
| `GET` | `/api/compliance/live-counter-keys` | which entries have a live counter; payload is `{keys[]}` |
| `GET` | `/api/compliance/snapshot-shape` | empty `ComplianceSnapshot` so the UI can render zero-valued cells before any drill has run |

The progress-event WebSocket (`/api/drills/{kind}/stream`) carries
the live snapshot under `event.compliance` once a drill is wired
into the stack.

### UI surface (`/sentinel/regulations`)

The page renders the crosswalk in a single filterable table:
jurisdiction · regulation · clause · primitive · artifact · layer ·
status · live-counter cells. The live cells bind to the WS progress
event's `compliance.{key}` dict and tick in place during a drill.

## Cross-RTL anchoring

The two `reused` rows (rate limiter, position / notional limiter)
trace to RTL primitives that were closed against the six-axis rubric
in `docs/SENTINEL_CORE_AUDIT.md` (Group A — risk controls) as part
of `v1.0.0-core-audit-closed`. The four `implemented` host primitives
(OTR, self-trade, fat-finger, CAT exporter, MAR) ride alongside that
audited core; their RTL twins are synthesizable but explicitly
**not** in the shipped 1.0.0 bitstream — the host implementation is
truth for v1.1.0.

The `audit_head_hash_lo_hex` field on the resilience envelope ties
the end-of-day FINMA / MAS submission to the same BLAKE2b chain the
on-chain risk gate writes. A regulator who wants to verify the
envelope in isolation only needs the envelope file plus one head
hash.

## Tests

* `tests/test_compliance_crosswalk.py` — registry shape, key
  uniqueness, jurisdiction / layer / status enum coverage,
  doc-vs-registry parity check, dict-serialisation round-trip.
* `tests/test_compliance_stack.py` — `ComplianceStack` end-to-end:
  CAT NDJSON output well-formed, OTR ratio ticks, fat-finger flag
  fires above 500 bps and not below, self-trade flag fires on a
  cross and not on same-side, MAR detector fires on a layering
  burst, snapshot keys match `ComplianceSnapshot` exactly.
* `tests/test_compliance_api.py` — REST contract for
  `/api/compliance/{crosswalk, live-counter-keys, snapshot-shape}`
  including count parity with the registry.
* `tests/test_demo_api.py` — extended with a smoke check that
  `/api/compliance/crosswalk` and `/api/compliance/snapshot-shape`
  are reachable from the live FastAPI app and round-trip cleanly.

All four files are network-free and run in well under one second per
file.

## What this release does **not** ship

* **Submission pipelines.** CAT NDJSON delivery (CSV bundling,
  encryption, SFTP), FINMA / MAS envelope delivery, and any
  regulator-portal upload flow are explicitly out of scope; the
  formatter is the artefact, the submission is an ops workstream.
* **RTL bitstream for the four host-side twins.** Synthesizable
  reference RTL exists alongside each implementing host module but
  is not in the 1.0.0 audited core. Promotion to RTL requires a
  fresh audit cycle in the same shape as `docs/SENTINEL_CORE_AUDIT.md`.
* **Cross-jurisdiction reconciliation.** The MAS / FINMA envelopes
  use the same shape; they are not auto-reconciled into one report.
  Each is its own artefact.
* **Regulator-side parsing tools.** The CAT NDJSON shape mirrors the
  CAT IM Spec; we do not ship a verifier for it. The internal
  invariants (one record per event, monotonic timestamps, bound
  account / firm IDs) are checked by the test suite.

## References

* `sentinel_hft/compliance/crosswalk.py` — registry; source of truth.
* `sentinel_hft/compliance/stack.py` — aggregator + snapshot shape.
* `docs/AI_AGENTS.md` — the WS4 RCA digest consumes the
  `aggregate.compliance` block of the snapshot.
* `docs/ROADMAP.md` §Workstream 3 — original scope.
* `docs/SENTINEL_CORE_AUDIT.md` — six-axis rubric applied to the two
  reused RTL primitives in `v1.0.0-core-audit-closed`.
* `docs/releases/v1.1.0/RELEASE_NOTES.md` — this release's full
  shipping summary.
