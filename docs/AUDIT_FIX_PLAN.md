# Sentinel-HFT — Audit Fix Plan

**Companion to** `docs/SENTINEL_CORE_AUDIT.md`.
**Purpose:** Concrete, sequenced, acceptance-gated plan to close every S0 and S1 finding before Sentinel-HFT is considered "shippable".
**Scope:** 14 S0 + 19 S1 findings across 5 RTL module groups, plus prerequisite verification infrastructure.
**Target:** One calendar month of focused work for a 2-engineer team (~8 engineer-weeks). One engineer can do it in ~2 months; three is the sweet spot if we parallelise across groups.

---

## 1. Definition of "Shippable"

The core is shippable when every one of these statements is simultaneously true:

1. Every S0 finding in `SENTINEL_CORE_AUDIT.md` is **closed** (fixed in RTL, covered by a self-checking test, and re-audited).
2. Every S1 finding is **closed or explicitly deferred** with a dated ticket and a risk-acceptance sign-off.
3. A shared `sentinel_sva.sv` bind file asserts monotonicity / handshake / FIFO invariants on every module in `rtl/`.
4. A cocotb-based regression suite covers every scenario listed in the per-group "Coverage gaps" sections of the audit. CI runs it on every PR.
5. The toolchain is upgraded to Verilator ≥5.x (current 4.038 accepts code that newer tools reject — see D-S0-01).
6. The README / 2-pager / architecture doc **match the code**. No claim of "tamper-evident BLAKE2b hash chain", "5-stage pipeline", or "100 GbE CMAC shim" until the implementation supports it (or the claim is re-scoped to what actually works).
7. An independent re-audit (fresh pair of eyes, same 6-axis rubric) produces zero new S0 findings.

S2/S3 findings can ship open as long as they are ticketed. S0 and S1 cannot.

---

## 2. Strategy: Waves, Not Weeks

Landing fixes sequentially by severity fails because S0 fixes depend on verification infrastructure that doesn't exist yet. The right ordering is **capability-first, bug-fix-second**:

- **Wave 0** (1 engineer-week): build the regression harness, SVA library, and modern toolchain. No bug fixes land.
- **Wave 1** (2-3 engineer-weeks): close every S0 in parallel, gated on Wave 0 deliverables.
- **Wave 2** (2 engineer-weeks): close every S1.
- **Wave 3** (1 engineer-week): hygiene, dedup, doc alignment.
- **Wave 4** (1 engineer-week): sign-off — full regression green, independent re-audit, tag release.

Each wave has a gate. No wave starts until the previous wave's gate passes.

---

## 3. Wave 0 — Prerequisites

Without these, Wave 1 fixes land on a testbench infrastructure that can't tell correct from broken.

### WP0.1 — Toolchain upgrade to Verilator ≥5.x
**Effort:** 1 engineer-day
**Finding closed:** D-S0-01 (reserved-word `parameter` → `fault_param`), partial on B-S1 group (strict lint catches struct mis-packings)
**Work:**
- Rename `fault_pkg::parameter` to `fault_pkg::fault_param` across `rtl/fault_pkg.sv:29`, `rtl/fault_injector.sv:122,127,128`.
- Bump CI `verilator` pin to ≥5.020 in `.github/workflows/fpga-elaborate.yml`.
- Fix `rtl/trace_pkg_v12.sv:75` `initial begin` in package (pre-existing Verilator 4.038 limitation — newer versions accept, but verify).
- Fix `rtl/fault_pkg.sv:29` reserved-word collision (same PR as above rename).
- Add `-Wall -Werror --lint-only` to Makefile `fpga-elaborate` target.
**Gate:** `make fpga-elaborate` exits 0 on Verilator 5.x with `-Wall -Werror`.

### WP0.2 — Shared SVA bind file (`rtl/sentinel_sva.sv`)
**Effort:** 3 engineer-days
**Finding closed:** A-S3-13, B-S3-2, C-S3-12, D-S2-02 (all "no SVA" findings)
**Work:** Single `rtl/sentinel_sva.sv` file with `bind` statements into every core module. Minimum assertions:
- **Risk gate:** `triggered |-> ##[1:$] !passed until cmd_reset`; `bucket <= cfg_max_tokens`; AXI-Stream `valid && !ready |=> valid && $stable(payload)`.
- **Audit log:** `seq_r` strictly monotonic (increment only on `do_write`); `full_r |-> !do_write`; `rec_valid |-> $stable(rec_data) until rec_ready`.
- **sync_fifo:** `no_overflow` (wr_en && full |=> $stable(count)); `no_underflow`; `push_pop_preserves_count`; `empty |-> (count == 0)`.
- **Pipeline:** `up_valid && !up_ready |=> up_valid && $stable(up_data)`; `attr_valid` is a one-cycle pulse; `d_ingress + d_core + d_risk + d_egress <= t_egress - t_ingress`.
- **Stage timer:** `saturated |-> !counting || stop`.
**Gate:** All SVA pass on the current (unmodified) RTL in sim — establishes a baseline. Any fix that regresses an SVA must address it in-PR.

### WP0.3 — cocotb regression harness (`tests/rtl/`)
**Effort:** 4 engineer-days
**Finding closed:** foundation for every subsequent fix
**Work:**
- Replace `rtl/tb_risk_gate.sv` (port-wrapper, no stimulus) with `tests/rtl/test_risk_gate.py` driving stimulus and scoreboards.
- Replace `rtl/tb_latency_attribution.sv` (hard-ties `dn_ready=1`, `trace_ready=1`) with `tests/rtl/test_latency_attribution.py` that sweeps back-pressure patterns.
- Create new `tests/rtl/test_sync_fifo.py`, `tests/rtl/test_audit_log.py`, `tests/rtl/test_eth_shim.py` (the last three have zero coverage today).
- Wire into CI alongside the existing lint pass.
**Gate:** Every test file exists and runs green against unmodified RTL for the "trivial" scenarios; failing scenarios are marked `pytest.mark.xfail` with a finding ID so Wave 1 can flip them to `xpass`.

**Wave 0 gate (must all be true before Wave 1 starts):**
- Verilator 5.x pin in CI ✓
- `sentinel_sva.sv` binds into every module with at least one assertion ✓
- cocotb harness runs five per-module test files on CI ✓
- Every S0 / S1 finding has an `xfail`-marked cocotb test that demonstrates the bug ✓

---

## 4. Wave 1 — Close every S0

These run in parallel once Wave 0 lands. Each WP is independent of the others except where noted.

### WP1.1 — Risk-gate safety (Group A)
**Effort:** 1 engineer-week
**Findings closed:** A-S0-01, A-S0-02, A-S0-03
**Work:**
- **A-S0-01** (`rtl/kill_switch.sv:91`): drive `passed` from `!trigger_latched` instead of `!kill_active`. Require `cmd_reset` while `cfg_armed=1` to clear the latch — add an `assert property` that `trigger_latched && !cmd_reset |=> trigger_latched`.
- **A-S0-02** (`rtl/position_limiter.sv:127-159`): replace `long_qty`/`short_qty` unsigned pair with a single `logic signed [QTY_WIDTH:0] net_position`. Compute `gross_notional = $abs(net_position) * mark_price` combinationally. Delete the monotonic-add path.
- **A-S0-03** (`rtl/position_limiter.sv:68-80`): project against signed `net_position + signed_order_delta`. BUY-while-short now correctly projects `|net + order| < max_long`.
- Update `risk_pkg.sv` with the new `net_position_t` signed type; update all consumers.
**Acceptance:**
- Every Wave 0 `xfail` test on kill-switch / position-limiter flips to `xpass`.
- New cocotb scenarios pass: partial-then-offsetting fill returns `gross_notional → 0`; BUY-while-short at risk-reducing delta is accepted; kill trip → `cmd_reset` clears on next cycle.
- `sentinel_sva.sv` assertions on kill-switch pass.

### WP1.2 — Audit-log integrity (Group B)
**Effort:** 1 engineer-week
**Findings closed:** B-S0-1, B-S0-2, B-S0-3
**Decision point (B-S0-1):** two options, pick one before starting.

**Option A — "Truthful serializer".** Rename `rtl/risk_audit_log.sv` → `rtl/risk_audit_serializer.sv`. Strike every "tamper-evident" claim from README, 2-pager, architecture doc, ROADMAP. Host is declared a trusted component. Effort: 1 engineer-day + doc updates.

**Option B — "Real BLAKE2b core".** Instantiate a synthesisable BLAKE2b-256 core in the fabric; chain purely in-fabric; host receives `prev_hash` as read-only. Effort: 2 engineer-weeks (pipelined BLAKE2b is the bulk).

**Recommendation: start with Option A** (ship as truthful serializer), schedule Option B for a post-ship workstream. The compliance ceiling with Option A is "host-trusted audit trail", which is still useful for DORA provided the host is in the same trust boundary as the FPGA.

**Other work (independent of A/B choice):**
- **B-S0-2** (`rtl/risk_audit_log.sv:156`): on FIFO-full, emit an in-band `REC_OVERFLOW` record with the drop count. `trace_pkg_v12.sv:22` already defines the record type. Keep the hash chain continuous across the drop. Add `dec_ready` output for optional back-pressure to the risk gate (gated by a new `cfg_audit_backpressure` bit).
- **B-S0-3** (`rtl/risk_audit_log.sv:98-101`): gate `seq_r <= seq_r + 1` on `do_write`. The verifier now sees contiguous seq numbers separated only by explicit `REC_OVERFLOW` records.

**Acceptance:**
- cocotb `test_audit_log.py::test_mutate_and_detect` passes (mutating any byte of a record triggers host-side verifier failure).
- `test_audit_log.py::test_fifo_full_emits_overflow` passes.
- `sentinel_sva.sv` monotonic-seq assertion passes.
- If Option A: README / 2-pager / architecture / ROADMAP scrubbed of "tamper-evident" claim on the risk-audit log. `grep -ri "tamper-evident" docs/ README.md` returns zero.

### WP1.3 — Ethernet header byte-offset rewrite (E-S0-01)
**Effort:** 2 engineer-days
**Finding closed:** E-S0-01 (plus eliminates the root cause of E-S1-04 miscount)
**Work:**
- Replace the raw bit-slicing at `rtl/eth/eth_mac_100g_shim.sv:165-175` with packed-struct unpacking via `eth_pkg::eth_hdr_t` / `ipv4_hdr_t` / `udp_hdr_t`.
- Add a `byte_reverse_512()` helper (or `unpack_from_lbus()` function in `eth_pkg`) that maps LBUS convention (byte 0 at bits `[511:504]`) into SV-native struct ordering.
- Drive the UDP-port filter / IPv4-proto check through struct members, not integer bit ranges.
**Acceptance:**
- cocotb `test_eth_shim.py::test_rx_single_beat_frame` passes with a hand-crafted IEEE-conformant UDP frame.
- `test_rx_all_field_offsets` asserts ethertype, proto, src_ip, dst_ip, src_port, dst_port, udp_length each land in the correct struct member given a reference frame from Scapy.

### WP1.4 — Ethernet drop-deadlock (E-S0-02)
**Effort:** 1 engineer-day
**Finding closed:** E-S0-02
**Work:**
- Add an `ST_DRAIN` state in the RX FSM: when `rx_frame_drop=1`, advance `rx_word_idx` and release `rx_beat_valid` regardless of `mkt_tvalid`.
- Guarantee: `rx_frame_drop` is cleared at beat-tlast in both drain and non-drain paths.
**Acceptance:**
- `test_eth_shim.py::test_rx_filter_reject_no_deadlock` passes: inject 100 mixed frames with ~50% filter-rejection rate, verify the pipeline drains every beat within 1× MTU cycles.

### WP1.5 — Ethernet TX framing (E-S0-03, E-S0-04)
**Effort:** 3 engineer-days
**Findings closed:** E-S0-03, E-S0-04
**Work:**
- Add a TX header-prepend FSM in `eth_mac_100g_shim.sv` with parameters `LOCAL_MAC`, `PEER_MAC`, `LOCAL_IP`, `PEER_IP`, `ORDER_UDP_DPORT`.
- Synthesise Eth+IP+UDP preamble; compute IPv4 header checksum (one's complement over the 20-byte header); back-fill IPv4 `total_length = 20+8+payload_bytes` and UDP `length = 8+payload_bytes` from a payload byte counter.
- Change `sentinel_u55c_top.sv:246` from `.ord_tlast(1'b1)` to the shell's actual `tlast` signal (add a new port to `sentinel_shell_v12.sv` if needed).
**Acceptance:**
- `test_eth_shim.py::test_tx_roundtrip_scapy` passes: drive `ord_tvalid`/`ord_tdata` with 1, 8, 9, 64 words; decode LBUS output with Scapy; assert bit-equality of frame layout, IPv4 checksum, UDP length.

### WP1.6 — Shell attribution race (C-S0-01)
**Effort:** 2 engineer-days
**Finding closed:** C-S0-01
**Work:**
- Port the inflight FIFO from `rtl/sentinel_shell.sv:115-148` forward into `rtl/sentinel_shell_v12.sv`. Key it on `tx_id_counter` at ingress; pop at `attr_valid`.
- Depth = pipeline depth parameter (default 1, so no behavioural change today; ready for WP2.4 when pipeline depth grows).
**Acceptance:**
- `test_latency_attribution.py::test_inflight_depth_2` passes (requires WP2.4 to land before this test is meaningful, but the FIFO exists).
- `sentinel_sva.sv`: `attr_valid |-> (t_ingress_captured == inflight_fifo.rd_data.t_ingress)`.

### WP1.7 — Stage timer saturation (C-S0-02)
**Effort:** 1 engineer-day
**Finding closed:** C-S0-02
**Work:**
- Add sticky `saturated` output to `rtl/stage_timer.sv` (set when `counter == '1 && counting && !stop`; cleared by `clear`).
- Wire four sticky bits (`d_ingress_sat`, `d_core_sat`, `d_risk_sat`, `d_egress_sat`) into `trace_record.flags` in `sentinel_shell_v12.sv`. Add bits to `trace_pkg_v12::trace_flags_t`.
**Acceptance:**
- `test_latency_attribution.py::test_stage_saturation` passes: hold `dn_ready=0` for 2^32 + 100 cycles, verify the emitted trace has `d_egress_sat=1`.

### WP1.8 — Fault injector FSM (Group D, S0s/S1s)
**Effort:** 3 engineer-days
**Findings closed:** D-S0-02, D-S1-01, D-S1-02, D-S1-03
**Work:**
- **D-S0-02:** `initial assert ($bits(fault_config_t) == 100);` in `rtl/fault_pkg.sv`.
- **D-S1-01:** move decrement + deactivation outside the `if (config_valid[i])` guard at `rtl/fault_injector.sv:67-89`. On `!config_valid[i]` force `fault_active[i] <= 0, remaining[i] <= 0`.
- **D-S1-02:** deactivate when `remaining == 1` on the same cycle (not after reaching 0). Single-shot (`duration=0`) fires for exactly 1 cycle.
- **D-S1-03:** implement `FAULT_CLOCK_STRETCH` and `FAULT_BURST`, OR `$fatal(1, "unimplemented fault");` under `` `ifndef SYNTHESIS ``.
**Acceptance:**
- `test_fault_injector.py::test_no_fault_identity` passes (config_valid=0 → output stream byte-identical to input).
- `test_fault_injector.py::test_exact_duration` passes for durations 0, 1, 5, 100.
- `test_fault_injector.py::test_config_deassert_mid_scenario` passes (deasserting `config_valid` mid-run clears the fault on the next cycle).

**Wave 1 gate (must all be true before Wave 2 starts):**
- All 14 S0 findings closed per acceptance criteria.
- Full cocotb suite green on CI.
- `sentinel_sva.sv` assertions all pass.
- Either BLAKE2b core lands (Option B) OR docs scrubbed of tamper-evident claims (Option A).

---

## 5. Wave 2 — Close every S1

### WP2.1 — Risk-gate AXI-Stream skid buffer (A-S1-06)
**Effort:** 2 engineer-days
**Finding closed:** A-S1-06
**Work:** Add a 1-entry register slice at the output of `rtl/risk_gate.sv`. Register the decision (`all_passed`, `first_reject`); `out_valid` gated on `decision_valid` pipe stage. Break the combinational `in_ready=out_ready` coupling.
**Acceptance:** timing closes at 250 MHz on the U55C target (run `make fpga-build`, check `out/timing_post_route.rpt` WNS > 0); cocotb AXI-Stream scoreboard passes on back-to-back orders with intermittent `out_ready=0`.

### WP2.2 — Rate-limiter arithmetic (A-S1-04, A-S1-05, A-S1-07, A-S1-08)
**Effort:** 2 engineer-days
**Findings closed:** A-S1-04, A-S1-05, A-S1-07, A-S1-08
**Work:**
- **A-S1-04** (`rtl/rate_limiter.sv:128-134`): widen refill sum to 33 bits before compare; saturating-add clamp.
- **A-S1-05** (`rtl/rate_limiter.sv:42`): clamp `cfg_refill_period` to `>=1` (AXI-Lite write rejected if 0, or internally ORed with 1).
- **A-S1-07** (`rtl/rate_limiter.sv:176` vs `rtl/risk_gate.sv:225`): gate rate-limiter counters on `in_valid && in_ready`, not raw `in_valid`.
- **A-S1-08** (`rtl/kill_switch.sv:55-57`): make `current_pnl` a signed type end-to-end; drop the `pnl_is_loss` companion bit.
**Acceptance:** cocotb tests for each scenario pass; rate-limiter and top-level stats agree on order count across a 10,000-order run with random back-pressure.

### WP2.3 — Audit-log edge cases (B-S1-1, B-S1-2, B-S1-3, B-S1-4)
**Effort:** 2 engineer-days
**Findings closed:** B-S1-1, B-S1-2, B-S1-3, B-S1-4
**Work:**
- **B-S1-1:** rewrite `full_r` comparison with explicit MSB-toggle pattern (supports non-pow2 depth).
- **B-S1-2:** `rec_nxt[239:224] = 16'(dec_reject_reason);` with a compile-time `initial assert ($bits(risk_reject_e) <= 16);`.
- **B-S1-3:** either reorder `trace_pkg::trace_record_t` members to match wire-format offset order, OR document MSB-first packing and add a `pack_le()` / `unpack_le()` helper. Pick one; document it.
- **B-S1-4:** deprecate `trace_pkg.sv`. Merge `FLAG_CORE_ERROR` / `FLAG_INFLIGHT_UNDER` into `trace_pkg_v12::trace_flags_t` reserved bits. Grep for every `import trace_pkg::*`, migrate to `trace_pkg_v12`. Mark `trace_pkg.sv` deprecated; delete in next release.
**Acceptance:** host-side Scapy/Python verifier round-trips every record correctly; no file imports `trace_pkg` except `trace_pkg.sv` itself (transitional deprecation guard).

### WP2.4 — Pipeline rename + multi-in-flight (C-S1-03, C-S1-04, C-S1-05)
**Effort:** 3 engineer-days
**Findings closed:** C-S1-03, C-S1-04, C-S1-05
**Work:**
- **C-S1-03:** rename `rtl/instrumented_pipeline.sv` → `rtl/latency_attribution_probe.sv`. Update every instantiation. Add a new `rtl/sentinel_pipeline.sv` that is a real multi-in-flight pipeline (skid-buffered per-stage valid/ready; parallel timestamp FIFO sized from a `PIPELINE_DEPTH` parameter).
- **C-S1-04:** include `!rst_n` in `timers_clear`; drive `timers_clear` on `ST_IDLE` entry as well as `ST_DONE`.
- **C-S1-05:** capture `tx_id_at_ingress` into the inflight FIFO; emit that on `attr_valid`, not `tx_id_counter - 1`.
**Acceptance:** `test_sentinel_pipeline.py::test_back_to_back_stream` passes at line rate (no stall); `test_reset_mid_tx` passes (first post-reset tx attribution is clean); `test_tx_id_monotonicity` passes across resets.

### WP2.5 — Ethernet CDC + async FIFO (E-S1-02, E-S1-03)
**Effort:** 2 engineer-weeks (biggest single work item)
**Findings closed:** E-S1-02, E-S1-03
**Work:**
- Build a 512→64 gearbox in the 322 MHz CMAC domain with a packet-boundary FSM.
- Insert an async FIFO (min 2 KiB, 9 KiB for jumbos) between the gearbox output and core-clock consumers.
- Symmetric 64→512 packer on the TX side with its own async FIFO.
- Instantiate `async_reset_synchronizer` per domain.
- Drop the `set_clock_groups -asynchronous` override on the specific net until the FIFO exists; add `set_max_delay -datapath_only` on FIFO pointer crossings once it does.
**Acceptance:**
- `make fpga-elaborate` green.
- `test_eth_shim.py::test_cdc_100k_frames` passes: drive LBUS on a 322 MHz clock and core on 100 MHz, assert no data loss across 100,000 randomised frames.
- `out/timing_post_route.rpt` WNS > 0 at both clock domains.

### WP2.6 — Ethernet TX last-beat off-by-one (E-S1-01)
**Effort:** 1 engineer-day
**Finding closed:** E-S1-01
**Work:** Use a combinational `tx_beat_next` wire that includes the current `ord_tdata` in the slot being written, OR add a 1-cycle register-delay on the emitted beat. Pick the lower-latency option.
**Acceptance:** `test_eth_shim.py::test_tx_single_word_order` passes (single-word order `ord_tvalid && ord_tlast` in one cycle; verify the 64 bits appear in `tx_lbus_data[511:448]` on the emitted beat).

**Wave 2 gate (must all be true before Wave 3 starts):**
- All 19 S1 findings closed or formally deferred.
- Full cocotb suite green.
- Timing closes at target Fmax in post-route.
- Ethernet `WITH_CMAC=1` elaborates cleanly in Vivado (not just Verilator).

---

## 6. Wave 3 — Hygiene

Each item independent; can parallelise across the team.

### WP3.1 — Version deduplication
**Effort:** 3 engineer-days
**Findings closed:** B-S1-4 follow-through, C version hygiene
**Work (original):**
- Delete `rtl/trace_pkg.sv` after WP2.3 deprecation cycle.
- Delete `rtl/sentinel_shell.sv` once every consumer points to `sentinel_shell_v12`.
- Delete `rtl/trace_pkg_v12.sv` → `rtl/trace_pkg.sv` rename if we want to normalise the name post-dedup.
**Acceptance (original):** `rg -l "trace_pkg\b|sentinel_shell\b"` returns only the canonical current-version files.

**Status (2026-04-21): FORMALLY DEFERRED to a dedicated Wave 5 "tooling migration" window.**

The file-level deletes cannot be done in isolation. An `rg` sweep of the tree
surfaces the following active, non-trivial consumers that still pin the old
names:

| Consumer | Path | Why it blocks |
|---|---|---|
| Verilator testbench | `sim/tb_sentinel_shell.sv` | Imports `trace_pkg::*` and instantiates `sentinel_shell` directly — the C++ harness in `sim/sim_main.cpp` is generated against this exact hierarchy. |
| Simulator build | `sim/Makefile` | Compiles the non-v12 file list. |
| Pytest fixtures | `tests/conftest.py` | Builds and imports against `sentinel_shell` signal names. |
| Wind-tunnel replay | `wind_tunnel/replay_runner.py` | Drives the Verilator binary whose top is `tb_sentinel_shell`. |
| Vivado TCL | `fpga/u55c/scripts/build.tcl`, `fpga/u55c/scripts/elaborate.tcl` | Adds both `sentinel_shell.sv` and `sentinel_shell_v12.sv` to the read list. |
| Host decoders | `host/trace_decode.py`, `host/metrics.py` | Parse records whose layout is declared in `trace_pkg.sv` (the non-v12 package). |

Migrating every consumer is roughly 3 engineer-days by itself (Verilator rebuild
harness + TCL regen + pytest fixture rewrite + host-side decoder flag
plumbing), and until WP3.2 (interface abstraction) also lands the v12 path
does not offer a strict superset of the fields some of these consumers read.

Rather than carry a half-migrated tree into Wave 4 sign-off, the dedup is
deferred with these acceptance invariants still respected at Wave 3 close:

1. The elaboration green-light on the canonical top-level
   (`fpga/u55c/sentinel_u55c_top.sv`, 0 errors / 19 warnings in slang) is
   unchanged by the coexistence of both trees.
2. No production path (i.e. anything that ends up in the U55C bitstream)
   pulls in either `sentinel_shell.sv` or `trace_pkg.sv`. That is a
   `fpga/u55c/scripts/build.tcl` property and is re-verified each wave.
3. The v12 files remain the single source of truth for every field used by
   `sentinel_u55c_top.sv`, `risk_gate`, `risk_audit_log`, `eth_mac_100g_shim`,
   and the WP2.5 CDC path — and the old files are imported only by sim and
   host-tooling consumers listed above.

**Wave 5 migration plan (not part of this audit cycle):**
- Introduce `sim/tb_sentinel_shell_v12.sv` alongside the existing TB.
- Regenerate `sim/sim_main.cpp` against the new TB.
- Update `sim/Makefile`, `tests/conftest.py`, `wind_tunnel/replay_runner.py`.
- Update `host/trace_decode.py` and `host/metrics.py` to parse the v12 record
  layout.
- Only after all consumers are green, delete `rtl/sentinel_shell.sv` and
  `rtl/trace_pkg.sv`; optionally rename `rtl/trace_pkg_v12.sv` →
  `rtl/trace_pkg.sv` and `rtl/sentinel_shell_v12.sv` →
  `rtl/sentinel_shell.sv` to keep public names stable.

**Acceptance (revised):** Wave 3 accepts the coexistence; Wave 5 closes the
dedup. Bitstream builds contain exactly one copy of the shell/trace package.

### WP3.2 — Interface abstraction
**Effort:** 1 engineer-week
**Findings closed:** A-S3-12, C-S3-09
**Work:**
- Replace the 30+ individual `cfg_*` ports on `risk_gate` with a single `risk_cfg_t` packed-struct port; keep AXI-Lite mapping unchanged at the host boundary.
- Introduce `sv_axis_if.sv` interface with `valid/ready/data/user/keep/last` modports; migrate `sentinel_shell_v12` and the new `sentinel_pipeline` to use it.
**Acceptance:** port count drops by at least 25 per module; lint green.

### WP3.3 — Stub and synth guards
**Effort:** 1 engineer-day
**Findings closed:** C-S3-10, C-S3-11
**Work:**
- Wrap `rtl/stub_latency_core.sv` body in `` `ifndef SYNTHESIS ``; add `` `ifdef SYNTHESIS `initial $fatal(1, "stub must not synth"); `endif ``.
- Add a `parameter bit STUB_ONLY = 1` with `initial assert` check.
- Add a "stub core detected" LED bit in `sentinel_u55c_top.sv` flagged in-bitstream if the stub ever reaches tape-out.
**Acceptance:** attempting to synth with `stub_latency_core` in the strategy slot fails at elaboration.

### WP3.4 — Doc / claim alignment
**Effort:** 2 engineer-days
**Findings closed:** cross-cutting pattern #5 from the audit
**Work:**
- Rewrite README "Tamper-evident audit log" section to match whichever path WP1.2 took.
- Rewrite architecture diagram captions: "5-stage pipeline" → "1-in-flight attribution probe" OR remove if WP2.4 landed a real pipeline.
- Rewrite 2-pager "100 GbE CMAC shim" claim to match reality (truthful stub + Wave-4-milestone timeline, or "real" if WP2.5 closed).
- Audit ROADMAP.md against the current state; flip completed workstreams.
**Acceptance:** every technical claim in the external-facing docs has a corresponding green test or RTL implementation. Spot-check by a non-author.

**Wave 3 gate (must all be true before Wave 4 starts):**
- Zero dead code in `rtl/`.
- Zero "old vs new" version pairs in-tree.
- Every doc claim backed by RTL or a test.

---

## 7. Wave 4 — Sign-off

### WP4.1 — Full regression + coverage
**Effort:** 2 engineer-days
**Work:**
- Run the full cocotb suite; minimum 80% line coverage on every module in `rtl/`, 100% on risk-gate + audit-log.
- Run `make fpga-build` end-to-end against the U55C target. Archive `post_route.dcp`, `timing_post_route.rpt`, `utilization_post_route.rpt`, `drc.rpt`, `power.rpt` under `out/releases/v1.0.0/`.
- Mutation test the risk-gate: flip every comparison operator (`<` → `<=`, `>` → `>=`, etc.) one at a time; verify at least one test fails per mutation. Target: >90% mutation kill rate. (Direct analog to the Volat project's `mutation_test_validators.py` pattern.)
**Acceptance:** coverage report + mutation kill rate meet targets; all artefacts archived.

### WP4.2 — Portfolio-level permutation analog
**Effort:** 1 engineer-day
**Work:** End-to-end drill test: replay all four use cases (toxic flow, kill-switch, wire-to-wire, evidence pack) against the post-Wave-3 RTL. Confirm trace records + audit records match the pre-fix demos byte-for-byte on the non-buggy paths and correctly diverge on the buggy ones.
**Acceptance:** drill output artefacts pass the same host-side verifiers that the demos ship with.

### WP4.3 — Independent re-audit
**Effort:** 2 engineer-days (auditor)
**Work:** Fresh pair of eyes. Same 6-axis rubric. Same Group A-E decomposition. Subagent or external reviewer — not the author of any of the fixes.
**Acceptance:** zero new S0 findings. Any new S1 findings get ticketed and formally deferred or fixed before tag.

### WP4.4 — Tag + release
**Effort:** 1 engineer-day
**Work:**
- Tag `v1.0.0-core-audit-closed`.
- Archive the audit report, fix plan, and re-audit report under `docs/releases/v1.0.0/`.
- Update `ROADMAP.md`: Workstream 1 → closed. Unblock Workstreams 2-7.
**Acceptance:** tag pushed; release notes written; `docs/ROADMAP.md` updated.

---

## 8. Schedule

Assuming a 2-engineer team working in parallel. Single-engineer timelines are ~2× wider.

```
 Week 1:  [Wave 0: toolchain + SVA + cocotb harness]
                                                   ▲ Gate 0
 Week 2:  [WP1.1 risk] [WP1.3-1.5 eth S0s]
 Week 3:  [WP1.2 audit] [WP1.6-1.8 shell / fault]
                                                   ▲ Gate 1
 Week 4:  [WP2.1-2.3 risk/audit S1s] [WP2.5 eth CDC (starts, spills into W5)]
 Week 5:  [WP2.4 pipeline] [WP2.5 eth CDC (completes)] [WP2.6 tx]
                                                   ▲ Gate 2
 Week 6:  [WP3.1-3.4 hygiene]
                                                   ▲ Gate 3
 Week 7:  [WP4.1 regression] [WP4.2 drills] [WP4.3 re-audit]
 Week 8:  [WP4.4 tag + release]
                                                   ▲ SHIP
```

Critical path: Wave 0 → WP1.2 (audit log, biggest decision) → WP2.5 (ethernet CDC, biggest work item) → Wave 4.

---

## 9. Risks and Deferred Items

**Risks:**
- **WP1.2 Option B (real BLAKE2b core)** is a 2-week slippage if selected; recommend Option A for the first ship, Option B as a post-ship workstream. Decide before Wave 1 starts.
- **WP2.5 ethernet CDC** is the biggest single work item and has no unit-test substitute for a real Vivado WITH_CMAC=1 run. Budget extra for Vivado licensing / hardware access.
- **WP4.3 independent re-audit** might surface new findings. Budget 1 buffer week after Wave 4 in case a new S0 surfaces.

**Deferred (not closing before ship, but ticketed):**
- S2 / S3 findings (15 + 15). Post-ship cleanup backlog.
- A-S2-09 ORDER_MODIFY semantics (needs product decision, not just RTL work).
- A-S2-10 kill-switch cancel policy (needs risk-committee decision).
- E-S3-03 VLAN / ARP support (needs deployment-target decision).
- Mutation testing beyond risk-gate (extends to other modules post-ship).

**Explicitly not doing:**
- Rewriting any subsystem from scratch. The audit findings are all addressable within the existing architecture.
- Multi-card / multi-FPGA orchestration (out of scope for core audit, belongs to Workstream 7+ per ROADMAP).

---

## 10. Acceptance Summary — Sign-off Checklist

Before tagging `v1.0.0-core-audit-closed`:

- [ ] All 14 S0 findings closed with acceptance criteria met
- [ ] All 19 S1 findings closed or formally deferred with sign-off
- [ ] `sentinel_sva.sv` binds into every module; all assertions pass
- [ ] cocotb suite green on CI; ≥80% line coverage (100% on risk + audit)
- [ ] Verilator 5.x pinned; `-Wall -Werror` clean
- [ ] Vivado `WITH_CMAC=0` and `WITH_CMAC=1` both synth + place + route
- [ ] Timing closes at target Fmax; WNS > 0 post-route
- [ ] External docs (README, 2-pager, architecture, ROADMAP) match the code
- [ ] Independent re-audit produces zero new S0 findings
- [ ] Release artefacts archived under `docs/releases/v1.0.0/`

Ship when every box is ticked, not before.
