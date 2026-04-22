# Sentinel-HFT demo script

Copy-pasteable commands that exercise every hero module end-to-end.
Takes about 90 seconds on a laptop. Everything is local and
deterministic — no network access, no API keys, no licensed tools.

## 0. One-time setup

```bash
git clone https://github.com/BorjaTR/Sentinel-HFT
cd Sentinel-HFT
pip install -e ".[all]"
sentinel-hft version
```

The `version` command prints the installed feature matrix (server,
prometheus, ai, slack, dev). None of them are required for the demo.

## 1. Deribit LD4 tick-to-trade demo (hero 1)

```bash
sentinel-hft deribit demo -o /tmp/sentinel-demo --ticks 20000 --seed 1
```

Expected output:

```
Deribit demo
  output          /tmp/sentinel-demo
  ticks           20000
  intents         55880
  decisions       55880
  passed          35864  (64.2%)
  rejected        20016
  kill triggered  False
  chain OK        True
  head hash       f43e80aa1467fcd2c4ca7590ac8b999d

Latency (ns)
  p50             1344
  p99             3230
  p99.9           7062
  max             13784
```

Four artifacts land in `/tmp/sentinel-demo/`:

```
traces.sst   (~3.6 MB)   v1.2 binary trace, 20k tick-driven transactions
audit.aud    (~5.4 MB)   one 96B audit record per risk decision
dora.json    (~47 MB)    DORA-shaped evidence bundle (schema: dora-bundle/1)
summary.md   (~1 KB)     human-readable run summary
```

The run is deterministic: a second run with the same seed produces
the same `head_hash`. Regression tests pin against this.

## 2. Audit log verification (hero 2)

```bash
sentinel-hft audit verify /tmp/sentinel-demo/audit.aud
```

Expected output:

```
Audit chain
  records          55880
  chain OK         True
  head hash        f43e80aa1467fcd2c4ca7590ac8b999d
  first break      none
  truncation       0 records
```

To see the tamper-detection in action, corrupt a byte in the middle
of the file and re-verify:

```bash
# Flip one byte of record #100
python3 -c "
import os
f = '/tmp/sentinel-demo/audit.aud.bad'
os.system(f'cp /tmp/sentinel-demo/audit.aud {f}')
with open(f, 'r+b') as fh:
    fh.seek(32 + 100*96 + 10)   # 32B header + 100 records * 96B + into record
    b = fh.read(1)
    fh.seek(fh.tell() - 1)
    fh.write(bytes([b[0] ^ 0x01]))
print('corrupted byte at record 100, offset 10')
"

sentinel-hft audit verify /tmp/sentinel-demo/audit.aud.bad
```

The verifier reports the chain break at record 101 (the record
that expected the corrupted record's hash in its `prev_hash_lo`) and
flags every subsequent record as inconsistent.

## 3. Local AI RCA (hero 3)

```bash
sentinel-hft explain /tmp/sentinel-demo/traces.sst
```

By default this runs the rule-based explainer — no network calls,
no API keys. It produces a human-readable narrative covering which
pipeline stage dominated latency, whether the tail was driven by a
burst or a single outlier, and how the reject reasons were
distributed.

For the richer LLM-backed narrative, set `SENTINEL_AI_BACKEND=local`
and point `SENTINEL_AI_MODEL` at a locally-hosted Ollama or
llama.cpp endpoint. Individual trace records never leave the host
regardless of backend — the prompt only carries aggregate metrics.

## 4. Hyperliquid use-case suite (hero 4)

The Hyperliquid adapter ships with four end-to-end use cases on top
of the shared pipeline — each answers a specific operational
question and leaves a self-contained HTML report behind. Full
reference in [`docs/USE_CASES.md`](USE_CASES.md).

The one-liner that runs all four plus stitches a dashboard:

```bash
sentinel-hft hl demo -o /tmp/sentinel-hl
open /tmp/sentinel-hl/dashboard.html
```

Or run them individually:

```bash
# 4a. Toxic-flow rejection — guard bites on adverse counter-flow
sentinel-hft hl toxic-flow -n 30000 -o /tmp/sentinel-hl/toxic_flow

# 4b. Vol-spike kill-switch drill — latch latency vs SLO
sentinel-hft hl kill-drill -n 24000 -o /tmp/sentinel-hl/kill_drill

# 4c. Wire-to-wire latency attribution — which stage owns the p99
sentinel-hft hl latency -n 40000 -o /tmp/sentinel-hl/latency

# 4d. Daily evidence pack — three-session DORA bundle
sentinel-hft hl daily-evidence --trading-date 2026-04-21 \
    -o /tmp/sentinel-hl/daily_evidence

# 4e. Cover page
sentinel-hft hl dashboard /tmp/sentinel-hl \
    -o /tmp/sentinel-hl/dashboard.html
```

Each use case emits `{name}.json` (machine-checkable schema),
`{name}.md` (human summary), `{name}.html` (inline-SVG visualization,
no external JS), plus the standard four HL run artifacts
(`traces.sst`, `audit.aud`, `dora.json`, `summary.md`). Every audit
chain can be cross-verified with:

```bash
sentinel-hft audit verify /tmp/sentinel-hl/toxic_flow/audit.aud
```

### Expected shape (abridged)

```text
Toxic-flow rejection
  intents          10971
  passed           10964
  TOXIC_FLOW       7       (on SOL-USD-PERP)
  chain OK         True

Kill-switch drill
  kill triggered   True
  spike → latch    2.47 ms  (SLO 50 ms)    within budget
  post-trip mism.  0
  chain OK         True

Latency attribution
  p50 / p99        1.40 us / 3.41 us
  bottleneck       core stage (p99 1.44 us)
  SLO violations   1.2 %
```

### Why four?

Deribit proves the tick-to-trade plumbing. The HL four prove the
operational guarantees — that the system *refuses* toxic flow, that
the kill switch *latches* within SLO, that the p99 *attributes* to a
specific stage, and that a day's evidence can be handed over in one
bundle.

## 5. DORA bundle inspection

```bash
python3 -m json.tool /tmp/sentinel-demo/dora.json | head -40
```

You'll see the bundle envelope:

```json
{
  "schema": "dora-bundle/1",
  "subject": "SENTINEL-HFT-DEMO",
  "environment": "demo",
  "run_id": "0xDECAF0",
  "generated_at_ns": ...,
  "artifacts": {
    "trace": { "sha256": "...", "records": 20000, ... },
    "audit": { "sha256": "...", "records": 55880, "head_hash": "..." }
  },
  "summary": {
    "latency_p50_ns": 1344,
    "latency_p99_ns": 3230,
    ...
  },
  "decisions": [...]
}
```

A compliance engineer can hand this single JSON file to a regulator
without shipping the raw `traces.sst` — the `sha256` commitments
are enough to anchor the evidence chain.

## 6. FPGA elaboration check (hero 5)

```bash
make fpga-elaborate
```

Runs Verilator `--lint-only` against the Alveo U55C top-level
(`fpga/u55c/sentinel_u55c_top.sv`). This is the same check the CI
`fpga-elaborate` GitHub Actions job runs on every PR touching
`rtl/` or `fpga/`.

If you have Vivado installed:

```bash
make fpga-elaborate-vivado   # elaborate-only pass, no synth
make fpga-build              # full synth + impl + bitstream
```

See [`fpga/u55c/README.md`](../fpga/u55c/README.md) for the
clocking strategy, floorplan, and expected resource utilization.

## 7. End-to-end regression test

```bash
pytest tests/test_e2e_demo.py -v
```

Exercises the full demo path from CLI invocation through to audit
verification. The head hash is pinned to catch any non-deterministic
regressions.

## Troubleshooting

If the demo run hangs for more than 30 seconds, the most likely
cause is a slow random seed path through the Deribit fixture. Set
`--ticks 5000` to shrink the run. If the audit verifier reports a
chain break on a clean run, check that you're on `main` and
`pip install -e ".[all]"` succeeded — the BLAKE2b chaining logic
lives in `sentinel_hft.audit` and requires `hashlib.blake2b` which
ships with the standard library since Python 3.6.

## What each hero corresponds to in the repo

| Hero | Entry point | Implementation |
|---|---|---|
| Deribit demo | `sentinel-hft deribit demo` | `sentinel_hft/deribit/` |
| Audit log | `sentinel-hft audit verify` | `sentinel_hft/audit/`, `rtl/risk_audit_log.sv` |
| Local AI RCA | `sentinel-hft explain` | `sentinel_hft/ai/` |
| HL use-case suite | `sentinel-hft hl {toxic-flow,kill-drill,latency,daily-evidence,dashboard,demo}` | `sentinel_hft/hyperliquid/`, `sentinel_hft/usecases/` |
| FPGA target | `make fpga-build` | `fpga/u55c/`, `rtl/` |
