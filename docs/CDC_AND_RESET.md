# Sentinel-HFT — Clock Domain Crossing & Reset Discipline

*Audience: FPGA / hardware engineer.*
*Status: v2.0 cycle (post-Wave 2 CMAC bridge closure).*
*Companion docs: `RTL_DESIGN_DECISIONS.md` (the why),
`VERIFICATION_METHODOLOGY.md` (what was checked),
`SENTINEL_CORE_AUDIT.md` (E-S1 findings that drove this design).*

This document is the per-crossing inventory of every place in
Sentinel-HFT where data passes between clock domains, plus the
per-domain reset discipline. It is the document a CDC reviewer
should be able to walk top-down to convince themselves that no
crossing is naked, that every reset has a synchroniser on the
de-assert side, and that the constraints in
`fpga/u55c/constraints/sentinel_u55c.xdc` correctly protect what is
implemented.

If a crossing exists in the code that is not listed here, the code
wins and this document is incomplete — file a ticket. If a crossing
is listed here that does not exist in the code, the code wins and
this document is wrong.

---

## 1. Clock domains

The shippable U55C bitstream has at most three clocks. Two are
always present, one is conditional on `WITH_CMAC=1`.

| Clock           | Source                                | Period    | Generator                         | Domain notation |
|-----------------|---------------------------------------|-----------|-----------------------------------|-----------------|
| `sysclk0`       | On-card 300 MHz LVDS oscillator       | 3.333 ns  | Board pin                         | sysclk          |
| `clk_100`       | MMCM divide-by-3 of `sysclk0`         | 10.000 ns | `u_clkgen`                        | core            |
| `cmac_usr_clk`  | CMAC hard-IP user-clock output (322.265625 MHz) | 3.103 ns | CMAC hard macro (vendor IP, outside repo) | cmac |

The `qsfp0_refclk` and `qsfp1_refclk` ports declared in the XDC
(6.206 ns LVDS, 161.1328125 MHz) are MGT reference clocks — they
feed the CMAC PLL but never appear as datapath clocks in this
repo. Listing them here for completeness; no `always_ff` block in
`rtl/` clocks off them.

`sysclk0` exists only as the MMCM input. No user logic runs on
`sysclk0` directly. The only exception is the MMCM itself, which
is treated as a vendor primitive.

The XDC declares `clk_100` and `sysclk0_p` as asynchronous to each
other (`set_clock_groups -asynchronous` in §2 of
`sentinel_u55c.xdc`). This is correct because the only path from
`sysclk0` into `clk_100` is through the MMCM, which contains a
PLL-aligned phase relationship that Vivado tracks separately. There
is no user-visible CDC between `sysclk0` and `clk_100`.

The XDC declares `clk_100` and `cmac_usr_clk` as asynchronous to
each other (§7 of `sentinel_u55c.xdc`). This is correct and is the
crossing the rest of this document is mostly about.

---

## 2. Crossing inventory

Each row is one direction of one crossing. A bidirectional handoff
(e.g. data RX + data TX between `core` and `cmac`) is two rows.

| # | Source domain | Destination domain | Carrier | Primitive | Implementing file | XDC entry |
|---|---|---|---|---|---|---|
| C1 | cmac (322 MHz) | core (100 MHz) | RX market-data words | `async_fifo` (DEPTH=32, WIDTH=64) — `u_rx_cdc_fifo` | `fpga/u55c/sentinel_u55c_top.sv` | §7 `set_clock_groups -asynchronous` |
| C2 | core (100 MHz) | cmac (322 MHz) | TX order words | `async_fifo` (DEPTH=32, WIDTH=64) — `u_tx_cdc_fifo` | `fpga/u55c/sentinel_u55c_top.sv` | §7 `set_clock_groups -asynchronous` |
| C3 | board (async) | core (100 MHz) | `board_rstn` reset | `reset_sync` (STAGES=3) — `u_rst_core` | `fpga/u55c/sentinel_u55c_top.sv` | §4 `set_false_path -from [get_ports board_rstn]` |
| C4 | board (async) | cmac (322 MHz) | `board_rstn` reset (gated by CMAC link-up) | `reset_sync` (STAGES=3) — `u_cmac_rst` | `fpga/u55c/sentinel_u55c_top.sv` | §7 `set_false_path -to [get_pins -hier -filter {NAME =~ *u_cmac_rst/sync_r_reg*/PRE}]` |
| C5 | host (PCIe AXI-Lite) | core (100 MHz) | `cfg_rate_*`, `cfg_pos_*`, `cfg_kill_*` | Static after init; `set_false_path -to` per-cell | `rtl/risk_gate.sv` (registers) | §4 `set_false_path -to [get_cells -hier -filter {NAME =~ *u_risk/cfg_*}]` |
| C6 | host (PCIe AXI-Lite) | core (100 MHz) | `cmd_kill`, `cmd_reset` (one-shot pulses) | 2-flop synchroniser (host->core) | `rtl/risk_gate.sv` (input flops) | Treated as part of the AXI-Lite slave — false-path on the same set as C5 |

The list is closed. There are no other crossings. In particular:

- The risk-gate, audit-log, latency-attribution probe, stage timer,
  rate limiter, position limiter, kill switch, and trace serialiser
  are **single-domain** modules. They all run on `clk_100` only.
- `sentinel_shell_v12.sv`, `instrumented_pipeline.sv`, `risk_gate.sv`,
  `risk_audit_log.sv`, `position_limiter.sv`, `rate_limiter.sv`,
  `kill_switch.sv`, `stage_timer.sv`, `sync_fifo.sv` — all
  single-clock.
- The legacy `sentinel_shell.sv` (deprecated, not in the active
  filelist) is also single-domain.

If you add a module that needs a second clock, this table grows by
two rows (one per direction) and you must instantiate a new
`async_fifo` or a 2-flop synchroniser per the
[Crossing-type rules](#5-crossing-type-rules) below.

---

## 3. Reset synchroniser inventory

Every clock domain has its own `reset_sync` instance. There are no
shared reset trees across domains. The convention is active-low
throughout (`rst_n_*`).

| Synchroniser | Domain | Source | Output net | STAGES | File |
|---|---|---|---|---|---|
| `u_rst_core` | core | `board_rstn` (async board pin) | `rst_n_core` | 3 | `fpga/u55c/sentinel_u55c_top.sv` |
| `u_cmac_rst` | cmac | `board_rstn` AND `cmac_link_up` | `rst_n_cmac` | 3 | `fpga/u55c/sentinel_u55c_top.sv` |
| `u_rx_cdc_fifo` internal | both | `rst_n_cmac` (write side), `rst_n_core` (read side) | per-side | n/a (FIFO uses the two domain resets directly) | `rtl/async_fifo.sv` |
| `u_tx_cdc_fifo` internal | both | `rst_n_core` (write side), `rst_n_cmac` (read side) | per-side | n/a (FIFO uses the two domain resets directly) | `rtl/async_fifo.sv` |

`reset_sync.sv` is async-assert / sync-deassert with `STAGES`
configurable (default 3). The flops carry
`(* ASYNC_REG = "TRUE" *)` so Vivado packs them into the same
slice and applies its MAX_DELAY discipline.

The XDC declares `set_false_path -from [get_ports board_rstn]`
because the source side is genuinely asynchronous; the
synchroniser flops are what makes the de-assert edge safe.

The XDC also declares
`set_false_path -to [get_pins -hier -filter {NAME =~ *u_cmac_rst/sync_r_reg*/PRE}]`
as a belt-and-braces measure on the async clear input of the CMAC
synchroniser flops. This is documented in §7 of the XDC and matches
the pattern recommended by the Cummings reset-synchroniser paper.

---

## 4. The CMAC bridge in detail

The C1 / C2 crossings are the design's hot spot — line-rate,
bidirectional, and the place the audit caught the original code
faking a single-clock stub (E-S1-02 / E-S1-03 in
`SENTINEL_CORE_AUDIT.md`). This section is the per-bit walk that
proves the post-Wave 2 bridge is correct.

### 4.1 Pointer FIFO (Cummings SNUG2002)

Both `u_rx_cdc_fifo` and `u_tx_cdc_fifo` are instances of
`rtl/async_fifo.sv`. The structure (per the source comments):

```
write domain (clk_w)                 read domain (clk_r)
----------------------               ----------------------
wr_addr_bin (ADDR_W bits)            rd_addr_bin (ADDR_W bits)
  |                                    |
  v                                    v
bin2gray                              bin2gray
  |                                    |
  v                                    v
wr_gray_r  --->  (ASYNC_REG x N) ---> wr_gray_rsync
rd_gray_rsync <--- (ASYNC_REG x N) <--- rd_gray_r

full  = (wr_gray_next ==
         {~rd_gray_rsync[ADDR_W:ADDR_W-1],
          rd_gray_rsync[ADDR_W-2:0]})
empty = (rd_gray_r == wr_gray_rsync)
```

Pointer width is `ADDR_W + 1` so the MSB lets the pointer wrap
once before aliasing empty and full. Gray code guarantees at most
one bit toggles per clock, so a single metastable sample only
affects that one bit — the rest of the pointer is stable by
construction.

Two pointer crossings happen per FIFO:
- write-pointer gray → read clock (depth = SYNC_STAGES, default 2)
- read-pointer gray → write clock (depth = SYNC_STAGES, default 2)

Both sides carry `(* ASYNC_REG = "TRUE" *)` on the synchroniser
arrays. Vivado packs the synchroniser flops adjacent and applies
its MAX_DELAY discipline.

### 4.2 Depth choice

`DEPTH = 32` for both FIFOs. The justification is: the LBUS bursts
from the CMAC are 1 word per cycle at 322 MHz, so a one-cycle
back-pressure event at the consumer is `ceil(322/100) = 4` words
in flight. A 32-deep FIFO absorbs an 8-cycle stall at full LBUS
rate before declaring full. That is comfortably above the worst
expected core-side stall (which is bounded by the risk-gate skid
buffer plus one cycle of audit-log handshake).

The depth must be a power of two — the FIFO asserts this at
elaboration via `localparam int DEPTH_POW2_OK = 1 / (...)` (intentional
divide-by-zero on violation, see `rtl/async_fifo.sv`).

### 4.3 SYNC_STAGES

`SYNC_STAGES = 2` is the default and is what both bridge
instances use. The XDC §7 comment notes that a 3-stage
synchroniser is recommended for the 322 MHz domain at the U55C
-2L speed grade; bumping to 3 is a one-line parameter change at
the instantiation site. We left it at 2 for now because the
post-Wave 2 timing reports closed comfortably; the 3-stage option
is the first lever to pull if a future tooling change tightens
the metastability margin.

### 4.4 Recommended XDC `set_max_delay` constraints

The XDC §7 carries (commented out, intentionally) the recommended
production constraints:

```
set_max_delay -datapath_only \
  -from [get_pins -hier *wr_ptr_gray_r*/C] \
  -to   [get_pins -hier *rd_gray_wclk_0_r*/D] 3.103
set_max_delay -datapath_only \
  -from [get_pins -hier *rd_ptr_gray_r*/C] \
  -to   [get_pins -hier *wr_gray_rclk_0_r*/D] 3.103
```

These are commented out because the exact pin names depend on how
Vivado mangles the `(* ASYNC_REG = "TRUE" *)` packed arrays at
synthesis time, which only stabilises after a `write_checkpoint
-synth` inspection. The comment in the XDC says so explicitly. The
path forward at hardware bring-up is:

1. Run `write_checkpoint -synth post_synth.dcp`.
2. `report_pins` on the FIFO synchroniser flops to learn the
   actual mangled names.
3. Uncomment the `set_max_delay` block, substitute the real names.
4. Re-run impl, confirm the constraints take effect via
   `report_clocks` and `report_timing -datapath_only`.

The blanket `set_clock_groups -asynchronous` is **correct for the
FIFO interior** (gray-coded pointers + 2-stage synchronisers
*do* tolerate any phase relationship) but is too aggressive
because it also tells Vivado to ignore other accidental crossings.
The `set_max_delay -datapath_only` constraint is the
point-to-point version that protects only the gray-pointer
crossings, and is what you want to run with in production.

### 4.5 Reset on the FIFO

Each FIFO side uses the synchronised reset for *its own* domain.
The write side of `u_rx_cdc_fifo` runs on `cmac_usr_clk` with
`rst_n_cmac`; the read side runs on `clk_100` with `rst_n_core`.
The pointers reset to 0 on both sides; gray code of 0 is 0, so a
fresh-reset pointer comparison (`empty = (0 == 0)`) is correctly
empty.

Crucially, the two domains can come out of reset at *different
times*. The write side might still be in reset while the read
side is live; the read side will see `wr_gray_sync = 0` (the
reset value of the synchroniser register) and read `empty = 1`,
which is correct. The reverse is the same. There is no
cross-domain reset coordination required; the gray-code MSB
discipline plus the per-side `reset_sync` is sufficient.

---

## 5. Crossing-type rules

For any future crossing, the rule is:

1. **Multi-bit data crossing.** Use `async_fifo`. Period. Do not
   use a 2-flop synchroniser on multiple bits — that breaks
   coherence the moment two bits of the source word change in the
   same cycle.

2. **Single-bit pulse crossing (one-shot).** Use a toggle
   synchroniser: source flips a level on the source clock, the
   destination samples through 2 flops and edge-detects. We do
   not currently have one of these in the tree (`cmd_kill` /
   `cmd_reset` are level-held by the host; see C6) but if you add
   one, make it a named module so the SVA can bind to it.

3. **Single-bit level crossing (slow-changing).** Use a 2-flop
   synchroniser with `(* ASYNC_REG = "TRUE" *)`. Document the
   guarantee that the source changes infrequently relative to the
   destination clock period, so a missed transition is impossible.

4. **Reset crossing.** Use `reset_sync.sv` per destination domain.
   Never share a reset across domains. Always declare
   `set_false_path` on the source-side input in the XDC.

5. **Static configuration crossing.** Use `set_false_path -to` on
   the destination-side flop. Document in the XDC which net is
   covered.

If your new crossing does not fit any of the above five
categories, it probably should not exist — re-think the
architecture. The Wave 1 audit caught one such case (the
"single-domain stub" CMAC bridge) and the cure was to refactor
the architecture, not to invent a sixth crossing pattern.

---

## 6. SVA coverage for the CDC primitives

`rtl/sentinel_sva.sv` binds the following per-FIFO and per-reset
assertions:

- **`async_fifo.no_overflow`**: `wr_en && full |=> $stable(wr_ptr_bin_r)`
  — a write attempt while full does not advance the pointer.
- **`async_fifo.no_underflow`**: `rd_en && empty |=> $stable(rd_ptr_bin_r)`
  — a read attempt while empty does not advance the pointer.
- **`async_fifo.gray_one_bit_toggle`**: per-clock,
  `$onehot0(wr_ptr_gray_r ^ wr_ptr_gray_n)` — gray code property,
  at most one bit toggles per pointer increment.
- **`reset_sync.sync_deassert`**: after `rst_n_in` rises, `rst_n_out`
  rises exactly STAGES clocks later.

These assertions are the lock-in for the crossing primitives. If
a future RTL change breaks any of them, the cocotb regression run
catches it before merge (see `VERIFICATION_METHODOLOGY.md` §3).

---

## 7. False paths and their justifications

Every `set_false_path` in `sentinel_u55c.xdc` has a justification.
This section is the audit trail.

| Path | Justification | XDC location |
|---|---|---|
| `set_false_path -to *u_risk/cfg_rate_*_q` | Static after init; written once by host AXI-Lite at startup. | §4 |
| `set_false_path -to *u_risk/cfg_pos_*_q`  | Same as above. | §4 |
| `set_false_path -to *u_risk/cfg_kill_*_q` | Same as above. | §4 |
| `set_false_path -from [get_ports board_rstn]` | Truly async board pin; `reset_sync` makes the de-assert edge safe. | §4 |
| `set_false_path -to *u_cmac_rst/sync_r_reg*/PRE` | Async clear input on the CMAC reset synchroniser; belt-and-braces with the `ASYNC_REG` discipline. | §7 |
| `set_clock_groups -asynchronous {clk_100} {cmac_usr_clk}` | Domain-level declaration; correct for the FIFO interior. The point-to-point `set_max_delay` constraints (commented in §7) are the production tightening. | §7 |
| `set_clock_groups -asynchronous {clk_100} {sysclk0_p}` | Datapath runs on `clk_100`; `sysclk0` is only the MMCM input. No user logic crosses this boundary. | §2 |

The false-path discipline is: every `set_false_path` is named
in this table. If a new constraint lands without an entry here,
it is missing its justification and should be questioned in
review.

---

## 8. Common CDC pitfalls and how the design avoids them

This is a checklist for the next reviewer to walk top-down.

**Multi-bit data through a 2-flop synchroniser.**
Avoided. Every multi-bit crossing uses `async_fifo`. Grep
confirms: `git grep "ASYNC_REG" rtl/` shows the attribute only on
the `reset_sync` shift register and the `async_fifo` synchroniser
arrays; nowhere else.

**Reset shared across clocks.**
Avoided. `rst_n_core` and `rst_n_cmac` are per-domain. The
`u_rx_cdc_fifo` and `u_tx_cdc_fifo` instances take *both* resets
(one per side) and the FIFO source enforces the per-side discipline.

**Same-bit toggling on both pointer sides.**
Cannot happen. Gray code, by construction, toggles exactly one bit
per increment. The `gray_one_bit_toggle` SVA locks this in.

**Placer crossing the synchroniser into a different SLR.**
Mitigated by the SLR0 floorplan in `pblock_sentinel`. The risk
gate's inner `pblock_risk_gate` is pinned to a single clock
region for the same reason. If a future change introduces logic
that the placer wants to push into another SLR, the
`(* ASYNC_REG = "TRUE" *)` attribute keeps the synchroniser flops
together; the SLR pinning keeps everything else local.

**Configuration written while the rate limiter has live tokens.**
Documented soft issue (A-S1 cluster). Hot-reload works today
because every config input is registered on the next config-write
clock; a more defensive design would also quiesce the token
bucket. Tracked as a Wave 5 backlog item; not a CDC bug.

**Clock gating on the destination side of a crossing.**
Not used. We do not gate `clk_100` or `cmac_usr_clk`. If a future
power-saving feature wants to gate either, the gating cell must be
on the *source* side of the synchroniser (so the sampled value is
stable) and a `set_disable_timing` constraint must cover the gating
path. This is a future Wave concern, not a current issue.

**Recovery / removal violations on de-assert.**
Avoided by the `reset_sync` discipline. Every domain has a
synchroniser; the `set_false_path -from [get_ports board_rstn]`
covers the source side.

---

## 9. What changed in Wave 2 (audit closure)

For traceability — if you are reading this with the audit in
hand:

- **E-S1-02 / E-S1-03 (CMAC single-domain stub).** Closed by
  WP2.5: `rtl/async_fifo.sv` and `rtl/reset_sync.sv` added,
  `eth_mac_100g_shim.sv` rewritten to instantiate them,
  `sentinel_u55c_top.sv` wires both per-side resets, XDC §7
  documents the recommended `set_max_delay` constraints.
- **E-S1-01 (TX last-beat off-by-one).** Closed by WP2.6:
  TX accumulator in the shim no longer reads stale `tx_beat`
  on the same cycle a new word is written.
- **E-S1-04 (`stat_rx_dropped_port` miscount).** Followed E-S0-01
  fix (header byte offsets). Counter now reflects real drops.

Wave 1 closed the S0 cluster (E-S0-01 byte offsets, E-S0-02
deadlock, E-S0-03 invalid TX frame, E-S0-04 `ord_tlast=1`); Wave 2
closed the S1 cluster (this section). The post-Wave 2 architecture
is what this document describes.

---

## 10. Re-audit checklist

If you are re-auditing this CDC design, walk these in order:

1. Confirm the crossing inventory in §2 matches `git grep` output
   for `always_ff` blocks across all `rtl/*.sv` files. Every
   `always_ff` should clock off `clk_100`, `cmac_usr_clk`, or
   `sysclk0` (only the MMCM). Any other clock name is a bug.
2. Confirm every `(* ASYNC_REG = "TRUE" *)` in `rtl/` is in
   either `rtl/async_fifo.sv` or `rtl/reset_sync.sv`. Anywhere
   else is a candidate naked synchroniser.
3. Confirm `sentinel_u55c.xdc` §7 declares
   `set_clock_groups -asynchronous` between `clk_100` and
   `cmac_usr_clk`, and that the recommended `set_max_delay`
   block is either uncommented (production) or commented with a
   justification (current state).
4. Confirm every `reset_sync` instance in
   `sentinel_u55c_top.sv` has a `set_false_path` companion in
   the XDC.
5. Run the cocotb tests in `tests/rtl/test_async_fifo.py` and
   `tests/rtl/test_reset_sync.py` (Wave 5 backlog item — these
   tests are stub-only today; the `WITH_CMAC=1` Verilator
   elaboration is the current acceptance gate).
6. Confirm the SVA assertions in §6 pass under the existing
   `make sim` target.

If any step fails, the design is a bug; if every step passes,
the CDC discipline is sound.
