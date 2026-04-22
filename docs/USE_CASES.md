# Hyperliquid use-case suite

Four end-to-end demonstrations built on top of the Hyperliquid
ingestion adapter (`sentinel_hft.hyperliquid`) and the shared
book → strategy → risk → audit pipeline. Each one answers a
different question a trading-venue reviewer or risk committee would
actually ask, and each one leaves behind a **JSON report**, a
**Markdown summary**, and a **self-contained HTML page** (inline SVG
charts, no external JS) suitable for offline review.

A single cover dashboard, produced by `sentinel-hft hl dashboard`,
stitches the four HTML pages into one click-through landing page.

## Why four?

The Deribit demo (`sentinel-hft deribit demo`) proves the
**tick-to-trade plumbing**. The four use cases below prove the
**operational guarantees** a firm would actually be asked about:

| # | Use case | Question it answers |
|---|---|---|
| 1 | Toxic-flow rejection | "Do we refuse to quote into adverse flow?" |
| 2 | Volatility kill-switch drill | "Does the kill switch latch within SLO when a vol spike hits?" |
| 3 | Wire-to-wire latency attribution | "Which stage owns the p99 — and is it within budget?" |
| 4 | Daily evidence pack | "Can we hand a regulator a single day's book of proof?" |

All four share the same fixture backbone and the same BLAKE2b-chained
audit log, so anything emitted is cross-verifiable with
`sentinel-hft audit verify`.

## Quick end-to-end

```bash
sentinel-hft hl demo -o /tmp/sentinel-hl
```

That sequentially runs the four use cases into per-use-case
sub-directories, then builds the dashboard. Skip flags are available
for fast iteration: `--skip-daily`, `--skip-latency`, etc.

Open `/tmp/sentinel-hl/dashboard.html` in any browser (no server
required) — the cover page links through to the four individual HTML
reports.

## 1. Toxic-flow rejection

```bash
sentinel-hft hl toxic-flow -n 30000 -o /tmp/sentinel-hl/toxic_flow
```

### What it proves

A toxic-heavy taker population (`--toxic-share 0.45` by default) is
fed through the pipeline. An online adverse-selection scorer
(`ToxicFlowScorer`) tracks EWMA post-trade drift for each taker; the
risk gate wraps `ToxicFlowGuard`, which rejects new quote intents on
the side being hit by counter-flow that has crossed the toxic
threshold.

Outcome: a non-zero count of `TOXIC_FLOW` rejects in the audit log,
concentrated on the symbol and taker IDs the scorer flagged.

### Key JSON keys (`toxic_flow.json`)

| Path | Meaning |
|---|---|
| `schema` | `sentinel-hft/usecase/toxic-flow/1` |
| `throughput.rejected_toxic` | Must be ≥ 1 for a toxic-heavy run |
| `per_symbol_toxic_rejects` | Where the guard was biting |
| `top_takers[].profile` | `BENIGN` / `NEUTRAL` / `TOXIC` classification |
| `audit.chain_ok` | Host BLAKE2b chain verifies over the on-chip audit serialiser stream |

### Key CLI knobs

| Flag | Default | Effect |
|---|---|---|
| `--ticks` | 30000 | Size of the fixture stream |
| `--toxic-share` | 0.45 | Fraction of takers flagged as TOXIC |
| `--trade-prob` | 0.14 | Per-tick probability of a trade event |
| `--seed` | 7 | Determinism anchor |

## 2. Volatility kill-switch drill

```bash
sentinel-hft hl kill-drill -n 24000 -o /tmp/sentinel-hl/kill_drill
```

### What it proves

A synthetic volatility spike is injected at tick `--spike-at-tick`
(default 9 000). A kill trigger is armed to fire at intent
`--inject-kill-at-intent` (default 25 500) — deliberately after the
spike in wire time. The drill measures **how long** it took between
the spike hitting the wire and the kill switch being latched, and
whether every post-trip intent (other than CANCELs, which legitimately
release exposure) was rejected with `KILL_SWITCH`.

Outcome: a positive spike-to-kill latency measured in nanoseconds, a
`post_trip_mismatch` of zero, and an SLO verdict against the
`--slo-budget-ns` budget.

### Key JSON keys (`kill_drill.json`)

| Path | Meaning |
|---|---|
| `schema` | `sentinel-hft/usecase/kill-drill/1` |
| `kill.triggered` | Must be `true` |
| `kill.latency_ns` | Spike-to-kill duration (ns). < 1e12, i.e. a duration not a wall-clock stamp. |
| `kill.within_slo` | Budget verdict |
| `kill.post_trip_mismatch` | Count of non-CANCEL intents that slipped past after trip. Must be 0. |
| `kill.decisions_before` / `decisions_after` | Audit-record split around the trip |

### Regression guard

`HyperliquidRunner.spike_tick_wire_ts_ns` captures the wire-clock
timestamp of the exact event that carried the spike. A previous bug
reported `latency_ns` as the absolute timestamp (≈1.7e18) — the
test suite now asserts `latency_ns < 1e12` to catch any regression.

## 3. Wire-to-wire latency attribution

```bash
sentinel-hft hl latency -n 40000 -o /tmp/sentinel-hl/latency
```

### What it proves

Every tick is timestamped at four stages on its way through the
pipeline: `ingress` (wire → book-update), `core` (book → strategy
decision), `risk` (strategy → gate verdict), `egress` (gate → trace
record). The use case collects the per-stage distributions, reports
p50/p99/p999/max, and identifies the **bottleneck stage** — the
single stage that owns the tail.

An SLO budget is auto-computed from observed mean + margin, or can be
pinned with `--slo-p99-ns`. The report lists violations and violation
rate against that budget.

### Key JSON keys (`latency.json`)

| Path | Meaning |
|---|---|
| `schema` | `sentinel-hft/usecase/latency/1` |
| `latency_ns.{p50,p99,p999,max}` | End-to-end quantiles (ns) |
| `stage_p99_ns.{ingress,core,risk,egress}` | Per-stage p99 |
| `bottleneck_stage` | Named stage that dominates the tail |
| `slo.p99_budget_ns`, `violations`, `violation_rate` | Budget verdict |
| `histogram_total`, `histogram_per_stage` | Bucketed distributions for the HTML |

## 4. Daily evidence pack

```bash
sentinel-hft hl daily-evidence --trading-date 2026-04-21 \
    -o /tmp/sentinel-hl/daily_evidence
```

### What it proves

A trading day is simulated as **three sessions** (morning, midday,
afternoon) with different load profiles and at least one vol-spike
session. Each session is a full HL run with its own audit chain; the
top-level report rolls up:

* per-session counters (records, passed, rejected, toxic, kill events),
* per-session audit chain verdicts (`chain_ok`),
* a cross-session DORA bundle combining every chain into a single
  evidence file a regulator could request under EU DORA Articles
  17–23 (ICT incident reporting).

Outcome: `all_chains_ok == true`, a single `daily_evidence.json`
summary, and a `daily_evidence.bundle.json` aggregated DORA file.

### Key JSON keys (`daily_evidence.json`)

| Path | Meaning |
|---|---|
| `trading_date` | ISO date |
| `sessions[]` | Per-session SessionReport (label, ticks, passed, rejected, toxic, kill_events, chain_ok) |
| `totals` | Day-level roll-up |
| `all_chains_ok` | Gate — every session chain verifies |
| `bundle` | Pointer to `daily_evidence.bundle.json` |

## Dashboard cover page

```bash
sentinel-hft hl dashboard /tmp/sentinel-hl -o /tmp/sentinel-hl/dashboard.html
```

Scans the output root for the four known sub-directories
(`toxic_flow/`, `kill_drill/`, `latency/`, `daily_evidence/`) and
emits a single `dashboard.html` that links through to whatever it
found. The cover page is deliberately a **static HTML file with
inline SVG** — no external JS, no web server, opens offline from a
USB stick.

## Test suite

Three test modules cover the HL surface:

* `tests/test_hyperliquid.py` — ingestion layer (instruments,
  fixture determinism, HLTK round-trip, toxic scorer, runner smoke).
* `tests/test_hl_usecases.py` — end-to-end per use case: artifacts
  exist, JSON schema is correct, HTML is self-contained (no external
  http refs), and the scenario-specific invariants hold (toxic
  rejects ≥ 1, kill triggered with positive duration, latency p99 > 0,
  daily-evidence chains all verify).
* `tests/test_hl_cli.py` — subprocess round-trip of every
  `sentinel-hft hl …` subcommand against a `tempfile.TemporaryDirectory`.

Run them all:

```bash
pytest tests/test_hyperliquid.py tests/test_hl_usecases.py tests/test_hl_cli.py -v
```

Typical runtime on a laptop: ≈ 7 s for all three modules combined.

## How this relates to the Deribit demo

The Deribit tick-to-trade demo
(`sentinel-hft deribit demo`, [docs/DEMO_SCRIPT.md](DEMO_SCRIPT.md))
is the **plumbing proof** — it shows the same pipeline can ingest a
realistic options book, price it, and emit attribution-grade traces.

The four HL use cases are the **operational proof** — they show the
same pipeline produces actionable evidence under four different
failure / review scenarios a real desk actually cares about.

Pick Deribit when asked "does it work end-to-end". Pick HL when asked
"does it do the right thing when something goes wrong".
