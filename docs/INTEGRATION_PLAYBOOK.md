# Integration playbook — wiring Sentinel-HFT into a real U55C build

Status: v2.0 — Wave 5 (2026-04-22)
Scope: how an FPGA engineer takes this repo from "it elaborates"
to "it's running on a card on a desk" with file paths, TCL hooks,
and a bring-up order.

This document is the **operational companion** to the three
design-reference docs:

* `docs/RTL_DESIGN_DECISIONS.md` — why the RTL is shaped the way it
  is (24 numbered decisions with finding-to-fix traceability).
* `docs/CDC_AND_RESET.md` — the per-crossing inventory and the
  timing constraints that go with each one.
* `docs/VERIFICATION_METHODOLOGY.md` — how we check that the RTL
  matches its contract and how to re-run the checks.

It is **not** a duplicate of `docs/INTEGRATION_READINESS.md`. That
doc enumerates the ~100 engineer-days of last-mile work that any
production integrator still has to do (venue protocols, DMA
ring, multi-card aggregation, key management, etc.). **This doc
is about the parts that already exist**: how you stitch them into
a real Vivado build, boot the card, and confirm end-to-end
behaviour before you start closing the remaining gaps.

If you are reading this before Wave 5 ships, the short version is:
the repo elaborates in Verilator, elaborates in Vivado 2023.2 on a
cloud image, and synthesises under Yosys. What it does not yet
have is a bench-validated bitstream, because no one on this
project has card access. The playbook is therefore written as an
instruction set for the first engineer who does.

---

## 1. Prerequisites

### Host machine

| Tool | Minimum version | Notes |
|---|---|---|
| Vivado | 2023.2 | Needed for U55C CMAC, HBM, XDMA IP. 2024.1 also tested. |
| Verilator | 5.020 | Faster than Vivado for RTL iteration; covers all lint gates. |
| Yosys | 0.40 | Independent area estimate via `synth_xilinx`. Older Yosys (0.9 in Ubuntu 22.04) cannot parse our package typedefs. |
| Python | 3.10 | cocotb, pytest, BLAKE2b host verifier. |
| cocotb | 1.8 | RTL tests live under `tests/rtl/`. |

### Card-side dependencies

* AMD Alveo U55C (part `xcu55c-fsvh2892-2L-e`).
* An XDMA reference design project for the U55C — Vivado ships
  one under `<vivado_install>/data/xilinx_board_store/xilinx.com/au55c/`
  or you can pull the Avery/AMD U55C example design for your
  corporate licence. **We do not redistribute the shell.**
* A CMAC (`cmac_usplus`) IP licence if you want the 100GbE path.
  The no-CMAC elaboration path (`WITH_CMAC=0`) does not need it.
* QSFP28 optics and fibre if you plan to run real L2 traffic.

### Licensing

The four main deliverables of this repo — the RTL, the host
tools, the verifier, and the testbench — are all Apache-2.0. The
Vivado toolchain, the CMAC hard IP, the XDMA reference shell, and
AMD's IBUFDS/MMCM primitives are **not** covered by this licence
and require a Xilinx support agreement.

---

## 2. Source file inventory

Keep this list in sync with `Makefile` (variable `FPGA_RTL`) and
`fpga/u55c/scripts/build.tcl`. The three files drift silently
otherwise; the check-in rule is "touch all three or none of
them".

```
rtl/trace_pkg_v12.sv          # Active trace package (v12 format)
rtl/risk_pkg.sv               # order_t, risk_reject_e, risk_status_t
rtl/fault_pkg.sv              # Fault injection codepoints
rtl/eth/eth_pkg.sv            # l4_meta_t + LBUS helper types
rtl/sync_fifo.sv              # Same-clock FIFO
rtl/reset_sync.sv             # Async-assert / sync-deassert primitive
rtl/async_fifo.sv             # Dual-clock FIFO (Cummings SNUG2002)
rtl/stage_timer.sv            # Per-stage latency counter w/ saturation
rtl/rate_limiter.sv           # Token bucket
rtl/position_limiter.sv       # Signed net_position tracker
rtl/kill_switch.sv            # Sticky kill w/ explicit reset
rtl/risk_audit_log.sv         # On-chip serialiser (Option A: no hashing)
rtl/risk_gate.sv              # Rate + position + kill composition
rtl/instrumented_pipeline.sv  # Core pipeline w/ probe (aliased latency_attribution_probe)
rtl/sentinel_shell_v12.sv     # Instrumentation shell
rtl/eth/eth_mac_100g_shim.sv  # CMAC LBUS <-> AXI-Stream
fpga/u55c/sentinel_u55c_top.sv# Top
```

**Deliberately absent from the build list** (but present in
the tree):

* `rtl/trace_pkg.sv` — deprecated legacy pre-v12 format. Kept for
  historical reference, not compiled. See Decision 13 in
  `RTL_DESIGN_DECISIONS.md`.
* `rtl/sentinel_shell.sv` — deprecated shell. Replaced by
  `sentinel_shell_v12.sv`.
* `rtl/stub_latency_core.sv` — synthesis tripwire, intentionally
  fails `STUB_ONLY` elaboration. See Decision 12.

If you find one of those in a build file, it's a bug.

---

## 3. Top-level ports you have to wire

The full signature lives in `fpga/u55c/sentinel_u55c_top.sv`
(lines 39 – 147). The integrator-facing groups are:

* **Board-level** — `sysclk0_p/n` (300 MHz differential),
  `board_rstn` (active low), `gpio_led[3:0]`, `heartbeat`.
* **CMAC LBUS** — `cmac_usr_clk` (322.265625 MHz), `cmac_usr_rstn`,
  QSFP0 RX (`qsfp0_rx_lbus_*`), QSFP1 TX (`qsfp1_tx_lbus_*`),
  `qsfp0_link_up`. Only meaningful when `WITH_CMAC=1`.
* **Tick ingress / order egress** (AXI-Stream, 64b) — `mkt_*`,
  `ord_*`. In `WITH_CMAC=1` builds these reflect the shell-side
  of the RX/TX CDC and are useful as observability taps.
* **Risk-gate config** — flat `cfg_rate_*`, `cfg_pos_*`,
  `cfg_kill_*`, `cmd_kill_*`. Nineteen ports total; drive from
  AXI-Lite register file in the shell (Decision 16).
* **Fill feedback** — `fill_valid`, `fill_side`, `fill_qty`,
  `fill_notional`, `current_pnl`, `pnl_is_loss`. Drive from the
  exchange gateway return path.
* **Trace output** — `trace_tvalid/tready/tdata/tsize`
  (512b, 7-bit size). Feeds PCIe/XDMA.
* **Audit output** — `audit_tvalid/tready/tdata` (768b).
  Separate DMA channel so the DORA bundle is reconstructable
  off-chip independently of the trace ring (Decision 2).

All of these are plain SystemVerilog `logic` — no opaque
interfaces, no packed AXI-Lite. Decision 16 covers why.

---

## 4. Dropping the core into an XDMA shell

Target topology (the one the repo is designed for):

```
             QSFP28                          PCIe Gen4 x16
                |                                 |
                v                                 v
      cmac_usplus_0  (CMAC)              xdma_0  (XDMA shell)
         | LBUS                             | AXI-MM  AXI-Lite
         v                                  v        v
      sentinel_u55c_top (WITH_CMAC=1) <-- AXI-Lite cfg
         ^                                  ^
         |                                  |
       trace_tvalid ---------------------->  MM2S/S2MM ring
       audit_tvalid ---------------------->  separate ring
```

Steps:

1. Open the U55C XDMA reference project in Vivado. Confirm it
   builds and boots on your card before adding anything.
2. Add `sentinel_u55c_top` as a user-logic block in the block
   diagram.
3. Set the block parameters:
   * `WITH_CMAC = 1`
   * `CORE_ID = 16'h0001` (bump per card for multi-card builds —
     see Decision 17)
   * `FIFO_DEPTH = 256` is a safe default; bump to 512 for jumbo
     frames.
   * `AUDIT_DEPTH = 128` gives headroom at 1 Mord/s.
4. Wire the CMAC LBUS. The shim lives at `u_qsfp0_shim` inside
   the `g_cmac` generate block (see top lines 210 – 311). Its
   LBUS ports are named exactly like `cmac_usplus_0`'s (`rx_lbus_*`
   / `tx_lbus_*`) so it drops on.
5. Tie `cmac_usr_clk` to the CMAC's TX user clock output
   (`gt_txusrclk2` in Xilinx nomenclature) and `cmac_usr_rstn`
   to `~cmac_usplus_0/usr_rx_reset`.
6. Wire `trace_tvalid/ready/data/size` to an S2MM AXI-Stream
   channel and `audit_tvalid/ready/data` to a separate one.
   Two channels, not one.
7. Hook `cfg_*` to an AXI-Lite register file in the shell. A
   forty-slot 32-bit register file is enough — see the port
   widths in `sentinel_u55c_top.sv:106-119`.
8. Wire `gpio_led[3:0]` to the four user LEDs, `heartbeat` to a
   probe pin for a 'scope.
9. Validate connections. Run `make fpga-elaborate-vivado` at
   the repo root:

   ```
   make fpga-elaborate-vivado
   ```

   This runs `fpga/u55c/scripts/elaborate.tcl` and is the
   fastest way to confirm that the port list and `WITH_CMAC=1`
   path still matches what your shell is driving.

---

## 5. TCL hooks and build scripts

The Vivado-facing scripts live under `fpga/u55c/scripts/`. They
are intentionally thin; the heavy lifting (source list,
constraints list, part number) is declared in
`build.tcl` so an integrator can point to a single file rather
than hunting through subfolders.

Entry points exposed by the Makefile:

```
make fpga-elaborate         # Verilator --lint-only. No Vivado needed.
make fpga-elaborate-vivado  # vivado -mode batch -source .../elaborate.tcl
make fpga-build             # vivado -mode batch -source .../build.tcl
make fpga-synth-yosys       # yosys -s .../yosys_synth.ys (independent area check)
make fpga-area-census       # static RTL parsing, no toolchain required
make fpga-clean             # scrub fpga/u55c/out and Vivado scratch
```

Five hooks an integrator typically adds on top of the canonical
`build.tcl`:

1. **Extra source files** — your shell wrapper, your AXI-Lite
   decoder, your XDMA BD. Append to the `read_verilog -sv`
   block, keeping `sentinel_u55c_top.sv` last so its `include`s
   resolve.
2. **Additional XDC** — pin constraints for your card variant,
   your QSFP cage numbering. Layer on top of
   `fpga/u55c/constraints/sentinel_u55c.xdc`; do not modify the
   repo's XDC in place.
3. **Strategy** — for the first build, use
   `Flow_PerfOptimized_high`. Drop to `Flow_RuntimeOptimized`
   only once you've closed timing.
4. **Report generation** — add `report_clocks`,
   `report_cdc`, `report_methodology` calls after `opt_design`
   and `route_design`. The CDC report is the one that catches
   regressions on the constraints laid out in
   `CDC_AND_RESET.md`.
5. **Bitstream output path** — point `write_bitstream` at a
   workspace directory under `fpga/u55c/out/` that `make
   fpga-clean` will scrub.

The open-source flows (`make fpga-elaborate`,
`make fpga-synth-yosys`, `make fpga-area-census`) do not need
any of the above. They exist specifically so CI can assert
structural correctness without a Vivado licence.

---

## 6. First-build bring-up order

**Read this section before you type `make fpga-build` for the
first time.** The ordering matters — several of the steps below
will not complete until earlier steps are green, and debugging
out of order wastes a calendar day per misstep.

### 6.1 Elaboration (zero hardware, ~5 minutes)

```
make fpga-elaborate            # Verilator --lint-only
make fpga-elaborate-vivado     # Vivado elaborate-only
```

Both should finish clean. If Verilator finds a structural bug
that Vivado missed, that's a signoff-quality lint improvement
— please flag it as an audit finding.

### 6.2 Area census (zero hardware, ~10 seconds)

```
make fpga-area-census
```

Reads the RTL statically and reports per-module LUT / FF / BRAM
estimates. The committed reference numbers live in
`fpga/u55c/reports/area_census.txt`. An integrator-side census
that disagrees by more than ~10% is a signal that your shell
wrapper has introduced logic inside the Sentinel hierarchy; it
should not.

### 6.3 Yosys independent synthesis (zero hardware, ~2 minutes)

```
make fpga-synth-yosys
```

Writes `fpga/u55c/reports/yosys_synth.txt`. Use this as a
pre-Vivado sanity check — if Yosys and Vivado disagree by more
than a factor of two on cell counts for a module, something is
being inferred differently and needs investigating.

### 6.4 Full Vivado synth + impl (no card, ~60 minutes)

```
make fpga-build
```

Inspect the post-route timing report
(`fpga/u55c/out/timing_post_route.rpt`). The decision point:

* **WNS > 0** — proceed to §6.5.
* **WNS < 0 but small (0 – 100 ps)** — re-run with a different
  placement seed before touching RTL. Decision 9's SLR0
  floorplan is the first suspect; try relaxing the
  `pblock_sentinel` rectangle slightly.
* **WNS < 0 and substantial (> 100 ps)** — iterate on BLAKE2b
  pipelining first. The BLAKE2b compression function in the
  host-side verifier is already pipelined; if timing fails on a
  shell-side BLAKE2b lane, it is because an integrator has
  collapsed the stages. **Do not** touch the audit log module
  to close timing; it is Option A by design and has no hashing
  on-chip (see Decision 2).

### 6.5 CMAC loopback test (card required, ~1 hour)

Load the bitstream. With the QSFP cage looped back (either with
a QSFP loopback plug or a short patch cable QSFP0 → QSFP1),
push synthetic Ethernet frames from the host and confirm they
come back. `qsfp0_link_up` should be high, `qsfp0_stat_rx_frames`
should match the host-side counter, and the heartbeat LED
(`gpio_led[3]`) should blink at ~1.5 Hz.

### 6.6 QSFP optics on live fibre (card required, ~1 hour)

Same as §6.5 but with real optics and a venue replay feed. Confirm
`qsfp0_stat_rx_dropped_port` stays at zero on matching UDP dst
ports and grows on non-matching ports (that's the filter
working). `MKT_UDP_DST_PORT` is exposed as a top-level parameter
for this.

### 6.7 End-to-end trace capture (card required, ~2 hours)

Arm the host-side DMA consumer, push a known synthetic tick
stream, pull the resulting trace file off-card, and run the
BLAKE2b verifier:

```
python3 host/tools/verify_audit.py --chain audit.bin --seed 0
```

A green run means the risk gate is accepting the expected
orders, the audit serialiser is emitting the expected
records, and the off-chip BLAKE2b chain reconstructs cleanly.
This is the end-to-end acceptance test for §6.

### 6.8 72-hour soak (card required, 3 days)

Run a production-weight tick replay for 72 hours. Monitor:

* `trace_tvalid` activity (LED [1]) — should be near-continuous.
* `trace_drop_count` via DMA-level status — must stay at 0.
* `inflight_underflow_count` — must stay at 0.
* CMAC `link_up` — must stay high.
* Card temperature and QSFP power.

A clean 72-hour soak with zero drops, zero underflows, and
the BLAKE2b chain verifying on every capture window is the
Wave 5 acceptance bar.

---

## 7. Host-side plumbing

The on-card work is only half the integration. The host side
consists of four processes, three of which already exist in this
repo:

1. **Trace DMA consumer** — pulls trace beats off the S2MM
   ring, deframes them per `trace_pkg_v12.sv`, writes out a
   binary log. Reference implementation: `host/trace_consumer.py`.
2. **Audit DMA consumer** — same but for the 768-bit audit
   records on the other channel. Reference implementation:
   `host/audit_consumer.py`.
3. **BLAKE2b verifier** — walks the audit log, chains records
   via BLAKE2b, verifies against the anchoring seed. Reference
   implementation: `host/tools/verify_audit.py`. Anchored to
   the RFC 7693 reference vectors — see
   `VERIFICATION_METHODOLOGY.md` §7.
4. **AXI-Lite config tool** — pokes `cfg_rate_*`, `cfg_pos_*`,
   `cfg_kill_*`. Currently a skeleton at `host/tools/config.py`;
   integrators will want to wire it to whatever risk-management
   UI they already run on the desk. The Sentinel UI at
   `sentinel-web/` speaks to these via the ops API the
   integrator builds on top of the config tool — it does not
   touch the card directly.

The four host processes run independently; the only shared
state is the DMA ring metadata exposed by the XDMA shell.
Failure of any one process is diagnosable in isolation — the
BLAKE2b verifier, in particular, runs fully off-line and
doesn't need the card to reproduce a historical audit trail.

---

## 8. Multi-card considerations

If you are building a fabric with more than one U55C:

* Bump `CORE_ID` per card. The trace and audit records both
  carry a 16-bit `core_id` tag so cross-card replay is
  unambiguous (Decision 17).
* Wire each card's `heartbeat` to a distinct test point on the
  backplane. A card that stops heartbeating is a card whose
  clock has stopped.
* The host-side BLAKE2b verifier works per-card — chains are
  not merged across cards by design. Merging is a higher-level
  decision about your DORA bundle format and lives outside the
  Sentinel contract.
* Shared-memory cross-card aggregation (e.g., global position
  across ten cards) is deliberately out of scope; it is one of
  the ten sections in `INTEGRATION_READINESS.md`.

---

## 9. Common first-day surprises

Things that have caught integrators in dry-runs and are worth
calling out up front:

1. **The repo does not ship the XDMA shell or the CMAC IP.** We
   cannot — they are Xilinx-licensed. If `make fpga-build`
   complains about missing `xdma_0.xci` or `cmac_usplus_0.xci`,
   that is your cue to generate them against your licence and
   add them to the project.
2. **`WITH_CMAC=0` is the CI default, not the integration
   default.** The Verilator elaboration path drives the core
   directly from `mkt_*`/`ord_*`. Real cards always run
   `WITH_CMAC=1`. Do not leave it at 0 by accident.
3. **The audit log does not hash.** Option A by design (Decision 2).
   The silicon only enforces monotonic sequencing and
   boundary framing; the BLAKE2b chain is constructed on the
   host. An integrator who expects on-chip hashing is expecting
   the wrong contract.
4. **`set_max_delay -datapath_only` on the CMAC CDC is
   commented out in `sentinel_u55c.xdc`.** The `async_fifo`
   primitives are structurally sufficient (see
   `CDC_AND_RESET.md` §4.4) and the extra constraint is
   redundant on a well-constrained build. Uncomment it only if
   your static timing analysis flags recovery/removal on the
   gray pointers — it should not.
5. **`latency_attribution_probe` is an alias, not a separate
   file.** `rtl/instrumented_pipeline.sv` carries both names
   (Decision 7). Grep hits for either map to the same module.
6. **`seq_no` increments on commit, not on decision.** An
   integrator who logs `seq_no` at the risk-gate input will see
   repeated numbers on rejected orders. This is deliberate
   (Decision 3, B-S0-3); log at the audit output instead.
7. **The trace channel and the audit channel are separate
   rings.** One S2MM is insufficient. See §4 step 6.

---

## 10. Where to go from here

After a clean §6.8 72-hour soak:

* Revisit `INTEGRATION_READINESS.md` for the ten sections of
  venue-specific, rack-specific, licence-specific work that
  remain. The playbook gets you to a card that is structurally
  correct and passes the on-chip contract; that doc enumerates
  the last-mile work to make it a production trading
  appliance.
* Revisit `VERIFICATION_METHODOLOGY.md` §11 (re-audit checklist)
  before cutting the Wave 5 tag. Every audit finding has a
  traceable fix; every fix has a matching test; every test
  runs in CI.
* Fold per-card bring-up notes back into this playbook as
  Section 11 ("Lessons from the first build on real silicon")
  when you have them. The repo maintainers will accept PRs
  against this file from the first integrator to cut a
  bitstream on real hardware — that's explicitly the feedback
  loop we want to close.

---

## Change log

| Date | Wave | Change |
|---|---|---|
| 2026-04-22 | 5 | Initial version. Written alongside `RTL_DESIGN_DECISIONS.md`, `CDC_AND_RESET.md`, `VERIFICATION_METHODOLOGY.md`. |
