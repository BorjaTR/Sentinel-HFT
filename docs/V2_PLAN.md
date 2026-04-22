# Sentinel-HFT v2.0 — implementation plan

*Agreed: 2026-04-22.*

This is the locked plan for the v2.0 cycle. Eight phases, sequenced so
the visible (UI) work lands first, the heavy backend lift (synthesis)
lands last in parallel with AWS provisioning. No "Keyrock" branding
anywhere in the UI — the product talks to two audiences (trading
desks, hardware engineers) without naming any specific firm.

## Audience contract

The product surface answers two readers:

1. **Trading desk / risk officer / compliance officer** — wants to see
   what fires, what's logged, what a regulator would receive, and how
   to reproduce it. Not interested in RTL.
2. **FPGA / hardware engineer** — wants to see the RTL contract, the
   CDC story, the timing budget, the verification methodology, the
   pblock floorplan, and the synthesis evidence.

Every page in the UI must say which audience it serves at the top.
The landing page picks the path.

## Phase 1 — UI rebuild for two audiences (3 days)

Done when:
- `/` is a two-card audience switch (Trading desks / Hardware engineers)
  with a head-hash banner + "Live • Replay • Fixture" provenance pill
  in the global header.
- `/sentinel` becomes the Trading-desk path: drill picker, evidence
  drawer, regulator-export button.
- `/sentinel/hardware` is the new Hardware path: interactive block
  diagram, RTL file index, CDC explainer, synthesis evidence panel,
  Wave 0-4 timeline.
- `/sentinel/about` is the plain-English explainer (what it is, what
  it does, why it's different).
- Legacy SaaS routes (`/demo`, `/pricing`, `/analyze`) dropped from
  nav. Files stay for now (deletion is a separate cleanup task).
- No "Keyrock" string anywhere in `sentinel-web/`.

## Phase 2 — Drill hardening (1.5 days)

Done when:
- `sentinel-hft hl chaos` exists and uses `rtl/fault_injector.sv`.
- Every drill accepts `--pcap PATH` for replay from real captures.
- WS progress events carry `source: "live" | "replay" | "fixture"`.
- UI badge wired to the `sentinel:source` CustomEvent and renders the
  three states distinctly.

## Phase 3 — Compliance UI (1 day)

Done when:
- Per-row evidence drawer on the crosswalk table — shows the exact
  RTL/Python code path and the artifact (audit row, trace bucket,
  config field) that satisfies that clause.
- "Today's evidence" header card with the five live counter values
  and the most recent audit head hash.
- "Regulator export" button produces a single PDF with crosswalk +
  head hash + audit chain state for the current run window.
- Compliance heartbeat cron emits a daily empty-but-signed bundle so
  there's always a "no incident today" record.

## Phase 4 — AI agent visibility (1 day)

Done when:
- `/sentinel/rca` shows the prompt that was sent (template OR Claude),
  the backend badge, and a side-by-side diff between deterministic and
  LLM narratives when both are available.
- `/sentinel/triage` shows live z-score / CUSUM / SPRT plots with
  threshold lines and the alert chain head hash.
- "Proposed config changes" panel renders the JSON patch the RCA agent
  would apply, with an explicit "review-only, never auto-applied" note.

## Phase 5 — Documentation surge (1.5 days)

Done when these all exist and render inline on `/sentinel/hardware`:
- `docs/RTL_DESIGN_DECISIONS.md` — why the choices were made.
- `docs/CDC_AND_RESET.md` — the CMAC bridge, async FIFOs, reset_sync.
- `docs/VERIFICATION_METHODOLOGY.md` — Waves 0-4, what was checked at
  each wave, what closed.
- `docs/INTEGRATION_PLAYBOOK.md` — how an FPGA engineer wires this
  into their stack, with file paths and TCL hooks.

## Phase 6 — Surprises in UI (1.5 days)

Done when:
- Cross-jurisdictional rollup card — one badge per regulator (EU/US/
  UK/CH/SG) and the clause coverage % for each.
- Data-residency diagram on `/sentinel/about` — every byte stays on
  the host, no third-party LLM hit unless explicitly opted in.
- "Runs offline from USB" download — a single zip with the demo binary
  + fixtures + audit verifier.
- Wave 0-4 timeline as a Sankey on `/sentinel/hardware`.
- SLR0 pblock floorplan SVG embedded with hover annotations.
- Architecture decision log — hover any block in the diagram, see the
  ADR for that block.

## Phase 7 — Alpha attribution (1 day)

Done when:
- `sentinel_hft/ai/rca_features.py` exposes three new features:
  fill-quality vs latency, reject-survival, kill-drill survival.
- `/sentinel/rca` shows a "Pipeline efficiency attribution" panel that
  decomposes p99 latency into the three features.
- The panel cites the exact trace records that drive each feature so
  the number isn't a black box.

## Phase 0 — Synthesis (1.5 days, in parallel with AWS provisioning)

Done in two halves:

**0a — Yosys CI (in repo, free, runs on every PR):**
- `.github/workflows/synth-yosys.yml` runs `yosys -p "synth_xilinx -family xcup -top sentinel_u55c_top"` on the full `rtl/` + `fpga/u55c/` tree.
- Output committed to `fpga/u55c/reports/yosys_synth.txt` with cell counts and longest path estimate.
- Lint-only mode if synthesis fails so the workflow surfaces the diagnostic without blocking.

**0b — Cloud Vivado (one-shot, when AWS + license ready):**
- `fpga/u55c/cloud-build/main.tf` provisions a `c6i.4xlarge` EC2 box.
- `fpga/u55c/cloud-build/build.tcl` runs the full synth → place → route → bitstream flow.
- `fpga/u55c/cloud-build/bootstrap.sh` installs Vivado from an
  AMD-authenticated download URL the user provides at build time.
- Reports captured into `fpga/u55c/reports/`: `timing_summary.rpt`,
  `utilization_placed.rpt`, `route_status.rpt`, `power_summary.rpt`.
- WNS / TNS / WHS values committed alongside as machine-readable JSON.

## Sequencing

```
Phase 1 (UI rebuild)        ← starts now, 3 days
   ├─ Phase 3 (Compliance UI)        ← depends on Phase 1, 1 day
   ├─ Phase 4 (AI agent visibility)  ← depends on Phase 1, 1 day
   ├─ Phase 6 (Surprises in UI)      ← depends on Phase 1, 1.5 days
   └─ Phase 7 (Alpha attribution)    ← depends on Phase 1 & 4, 1 day

Phase 2 (Drill hardening)   ← independent backend work, 1.5 days
Phase 5 (Documentation)     ← independent doc work, 1.5 days

Phase 0a (Yosys CI)         ← independent, 0.5 days
Phase 0b (Cloud Vivado)     ← LAST, blocked on user's AWS + AMD license
```

Total: ~10–13 engineer-days. Phases 1, 2, 5 can run in parallel today.
Phases 3, 4, 6, 7 need Phase 1 scaffolding. Phase 0b is the final
seal.
