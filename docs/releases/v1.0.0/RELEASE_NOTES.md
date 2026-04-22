# Sentinel-HFT `v1.0.0-core-audit-closed` — Release Notes

**Tag:** `v1.0.0-core-audit-closed`
**Date:** 2026-04-21
**Owner:** Borja Tarazona

This release closes **Workstream 1 (Core audit + known-bug fixes)**
from `docs/ROADMAP.md`. The core RTL has been audited end-to-end
against the six-axis rubric in `docs/SENTINEL_CORE_AUDIT.md`, all
14 S0 + 19 S1 findings have been closed across four sequenced
waves of work, a fresh-eyes independent re-audit has been passed
with zero new S0 findings, and the release artefacts are archived
under `docs/releases/v1.0.0/`.

## What shipped

- **14 S0 findings closed** — risk-gate safety (kill-switch disarm
  leak, monotonic notional ratchet, wrong-side offsetting
  projection), audit-log integrity (host-hashed chain claim aligned
  to RTL, in-band overflow marker, seq gated on committed writes),
  ethernet RX/TX correctness (header byte-offsets, drop-drain FSM,
  valid Eth/IP/UDP frame construction, real `ord_tlast`), shell
  attribution race, stage-timer saturation, reserved-word
  `parameter` rename, fault-injector FSM completeness.
- **19 S1 findings closed** — AXI-Stream skid buffer on risk_gate,
  rate-limiter arithmetic, audit-log edge cases, pipeline rename +
  multi-in-flight scaffolding, 100 GbE CMAC CDC + async FIFOs, TX
  last-beat off-by-one.
- **Zero new S0 findings** in the Wave 4 fresh-eyes re-audit
  (`RE_AUDIT_WAVE4.md`).
- **WP1.2 decision:** Option A (truthful serialiser + host-side
  BLAKE2b chain). Option B (in-fabric BLAKE2b core) is catalogued
  in `docs/ROADMAP.md` as a v1.1 workstream.
- **WP3.1 decision:** file-level dedup of `rtl/sentinel_shell.sv`
  and `rtl/trace_pkg.sv` formally deferred to a dedicated Wave 5
  tooling-migration window, with the acceptance invariants in
  `docs/AUDIT_FIX_PLAN.md` §WP3.1. No production path pulls either
  legacy file into the U55C bitstream.

## Regression evidence (archived under `docs/releases/v1.0.0/`)

- **Elaboration:** 17 FPGA_RTL files through `pyslang` single
  preprocessor unit with `SENTINEL_STUB_IBUFDS=1` → **0 errors,
  19 warnings** (baseline; no regressions across the 33 closing
  work packages).
- **Python test suite:** `pytest tests/` → **474 passed, 60
  skipped** (all skips are Vivado-gated). Includes
  `test_e2e_demo.py` 11/11, `test_audit_log.py::test_mutate_and_detect`,
  `test_audit_log.py::test_fifo_full_emits_overflow`,
  `test_risk_gate.py` 12/12 scenarios, `test_sync_fifo.py` full
  boundary sweep, `test_fault_injector.py` full FSM coverage.
- **Drill replay (WP4.2)** on the post-Wave-3 RTL across all four
  Hyperliquid use cases:

  | Drill | Ticks | Intents | Records | Latency p99 / p99.9 (ns) | Chain |
  |---|---:|---:|---:|---|---|
  | Toxic flow | 30,000 | 72,444 | 72,444 | 3,101 / 6,140 | PASS |
  | Kill-switch | 24,000 | 52,984 | 52,984 | 3,100 / 6,490 | PASS |
  | Wire-to-wire | 40,000 | 95,311 | 95,311 | 3,081 / 6,761 | PASS |
  | Daily evidence | — | — | 73,107 (3 sessions) | — | 3/3 PASS |

  Per-stage p99 on the latency drill: ingress 470 ns, core 1,630 ns,
  risk 230 ns, egress 460 ns — bottleneck = core, as expected.

- **Tamper-detection end-to-end proof (B-S0-1 Option-A loop):**
  `sentinel-hft deribit demo` produced 55,880-record audit chain,
  head hash `f43e80aa1467fcd2c4ca7590ac8b999d`. Flipped one byte
  at record #100. Host verifier re-run reported chain break at
  record #101 with the exact hash mismatch (computed
  `f450a68b4e698fa6c1df328d8eec1a00`, expected
  `26a2af58901387f0b546a7aa6d8fc604`) and the exact sequence
  number. Functional closure of the S0 acceptance criterion
  exercised on a real workload.

## Artefacts in this release

- `docs/releases/v1.0.0/RE_AUDIT_WAVE4.md` — fresh-eyes independent
  re-audit. Per-finding closing matrix for 14 S0 + 19 S1, regression
  evidence pack, sign-off checklist cross-reference.
- `docs/releases/v1.0.0/RELEASE_NOTES.md` — this document.
- Referenced throughout: `docs/SENTINEL_CORE_AUDIT.md` (original
  audit), `docs/AUDIT_FIX_PLAN.md` (sequenced closing plan).

## Out of scope for this tag

- **Vivado `WITH_CMAC=0` and `WITH_CMAC=1` place-and-route + post-route
  timing on real silicon.** Deferred to the hardware-bring-up
  workstream (catalogued in `docs/ROADMAP.md`). No unit-test
  substitute exists; needs a licensed Vivado run.
- **In-fabric BLAKE2b core (WP1.2 Option B).** v1.1 workstream.
- **Wave 5 file-level dedup of `rtl/sentinel_shell.sv` and
  `rtl/trace_pkg.sv`.** Tooling migration window; does not alter
  bitstream content.
- **S2 / S3 findings** (15 + 15) — post-ship cleanup backlog.
- **Product / risk-committee decisions** — A-S2-09 (ORDER_MODIFY),
  A-S2-10 (kill-switch cancel policy), E-S3-03 (VLAN / ARP) stay
  open pending product-side decisions.
- **Mutation testing beyond risk_gate** — WP4.1 met the >90% kill
  rate on risk_gate; post-ship extension to other modules.

## Tag reference

```bash
# Once the tree is clean and this release is merged to the default branch:
git tag -a v1.0.0-core-audit-closed -m "Core audit closed; 14 S0 + 19 S1 resolved; see docs/releases/v1.0.0/"
git push origin v1.0.0-core-audit-closed
```

The tag marks the first shippable state of the Sentinel-HFT core per
the "Definition of shippable" in `docs/AUDIT_FIX_PLAN.md` §1.

## What unblocks

With Workstream 1 closed, Workstreams 2–7 in `docs/ROADMAP.md` are
unblocked and can be scheduled in parallel as capacity permits.
Workstream 2 (Interactive demo UI) is the recommended next pick
per the 2026-04-21 priority elevation in the roadmap's decision log.

## Acknowledgements

Audit findings consolidated from five parallel single-group RTL
reads (Groups A–E) logged in `docs/SENTINEL_CORE_AUDIT.md` §10.
Closing work executed across Waves 0–4 per `docs/AUDIT_FIX_PLAN.md`.
Independent re-audit performed by a fresh-eyes pass against the
same six-axis rubric.
