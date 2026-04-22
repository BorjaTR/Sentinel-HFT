# Sentinel-HFT — two-pager for Keyrock

*Borja Tarazona, April 2026*

## What it is

Sentinel-HFT is a tick-to-trade observability and risk-evidence
appliance for a co-located FPGA trading path. It does three things
that sit together. First, it wraps an existing FPGA trading core
with cycle-accurate instrumentation that emits a 64-byte trace
record per transaction, with per-stage latency attribution (ingress,
core, risk, egress) so you can point at *which* pipeline stage ate
your slack. Second, it enforces a deterministic hardware risk gate
(rate limiter, position tracker, kill switch) and writes every
decision through an on-chip audit serialiser — ordered, sequenced,
with an in-band overflow marker — while BLAKE2b chain construction
and verification happen off-chip on the host. A byte flip, a dropped
record, or a reordered insertion all surface as a chain break with
the exact sequence number. Third, it produces a DORA-shaped incident
bundle that a risk committee or the FSMA can diff against a
reference run without needing network access.

The tool is shaped around the specific venues Keyrock is exposed to:
Deribit LD4 options and perps (where the demo runs), Hyperliquid /
Lighter for on-chain perps, and Solana block builders in the
Jito-era. Same trace format across all three, so block-inclusion
latency from a Jito bundle and wire-to-wire latency from an LD4 perp
quote sit on the same histogram.

## Why now

Three things collided in Q1 2026 that make the timing sharp.
DORA has been in force since January 2025 and Belgium's FSMA MiCA
empowerment is still transitioning through mid-2026, which puts the
burden of producing audit evidence onto the firm's own stack rather
than onto a vendor. The crypto-native venue mix has shifted hard
toward on-chain perps, where incumbent observability tools (Corvil,
Exegy Nexus) have no primitives yet for block-inclusion attribution.
And the Exegy 2026 State of Trading Infrastructure survey put
market-data processing at the top of investment priorities for ~60%
of senior leaders — the observability budget is now a real line item,
not a nice-to-have.

## What's novel

The obvious piece is cycle-accurate attribution on an FPGA, which is
table stakes in equities but still differentiating in crypto. The
less obvious pieces are the two that make this a *Keyrock-fit* tool
rather than a generic one. The audit log chain is deterministic and
local — no cloud service, no external dependency — so the same run
on the same seed produces the same head hash, which is exactly what
you want when a regulator asks you to reproduce the evidence for a
post-incident report. The AI root-cause explainer runs locally too,
defaulting to a rule-based reasoner with an optional local LLM hook,
because HFT firms don't route trace content through an Anthropic or
OpenAI endpoint.

The DORA bundle is not a new format. It's the existing trace + audit
data packed into a schema (`dora-bundle/1`) that matches the evidence
structure DORA's Regulatory Technical Standards ask for: incident
timestamp, affected instruments, decisions taken, rollback point. The
novelty is that it falls out of the pipeline rather than being
assembled after the fact by a compliance engineer.

## How you'd use it

Three entry points, depending on the reader.

A strategy developer runs `sentinel-hft deribit demo` and diffs the
produced summary against a reference. If the p99 latency regressed or
the audit chain's head hash changed, CI fails the PR. The regression
test lives in `tests/test_e2e_demo.py` and is wired into the
`integration` GitHub Actions job.

An infrastructure engineer targets `make fpga-build` to produce an
Alveo U55C bitstream at 100 MHz, constrained to SLR0 so the tick-to-
trade critical path doesn't pay the cross-SLR hop. The XDC ships a
pblock floorplan that pins the risk gate into a single clock region
to keep intra-SLR latency variance out of the rate / position / kill
branches. A Verilator `--lint-only` elaboration pass runs on every
PR.

A risk officer runs `sentinel-hft audit verify` on an audit log and
gets back a bundle with the chain state, the first break (if any),
and the evidence table. The verifier tolerates truncation — if the
last K records are lost the first N-K still verify — which maps to
how DORA expects incidents to be reported (the "severed tail"
problem).

## What's not in scope

This is observability and risk evidence, not an alpha toolkit. There
is no strategy library, no backtester, no order-management
integration. The demo strategy is deliberately thin — a spread-based
market-maker that posts paired quotes on mid moves — because the
point is to exercise the trace and audit paths, not to make money in
simulation. On a real deployment the strategy is the firm's own; the
risk gate and audit log sit underneath it.

The tool does not sit in the live production hot path as a risk
gate. The RTL primitives are hot-path-capable (single-cycle
combinational decision, pass-through timing) but adopting them in
production requires a formal sign-off process that isn't in scope
here. The realistic deployment is staging and post-trade evidence
generation, which is also where DORA actually bites.

## Roadmap

Four work items are pending after this week. The Alveo U55C synth
flow needs a full timing closure pass on real silicon (today the
design elaborates cleanly and the XDC looks reasonable, but WNS is
not measured). The audit log's `prev_hash_lo` path is tied off at the
wrapper boundary — the real DMA-write loop lives in the XDMA shell
and hasn't been integrated. The on-chain attribution module covers
Hyperliquid and a Jito block-builder harness; Lighter and MegaETH are
follow-on. And the dashboard (Grafana / Prometheus) exists but has
not been re-skinned around the DORA evidence view.

## One pointer

Start at [`docs/DEMO_SCRIPT.md`](DEMO_SCRIPT.md) — it is a linear
script of copy-pasteable commands that produces every artifact in
this brief in about 60 seconds. The [architecture
overview](architecture.md) has the Mermaid diagram that shows how the
pieces fit. The [top-level README](../README.md) is the feature
reference. The [market-fit strategy
brief](keyrock-market-fit-brief.md) is the longer positioning
document this two-pager is summarising.
