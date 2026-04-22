# Sentinel-HFT — Core RTL Audit

**Audit date:** 2026-04-21
**Scope:** All SystemVerilog under `rtl/` (5 module groups, 20 files)
**Motivation:** Original RTL was authored ~5 months ago by an older Opus checkpoint. This audit is the modern re-review directive from the ROADMAP (Workstream 1) before any new feature work, regulation module, or agent phase merges on top.
**Method:** Five parallel single-group reads against a fixed six-axis rubric (spec correctness, determinism, width, back-pressure, coverage, modernisation). Severity ladder S0 → S3 defined per group. Findings consolidated here with a triage verdict.

---

## 1. Headline

**The core is not yet shippable.** Out of 20 files audited we found **14 S0 (safety-critical) findings** and **15 S1 (likely-to-fire) findings**, concentrated in three subsystems:

1. **Risk gate (Group A)** — the one subsystem that MUST be bullet-proof has three S0 bugs that will fire in normal operation (kill-switch disarm leak, monotonic notional ratchet, wrong-side projection on offsetting orders). Plus a combinational AXI-Stream handshake that will miss timing at any realistic HFT clock.
2. **Audit log (Group B)** — the "tamper-evident BLAKE2b hash chain" is neither tamper-evident nor BLAKE2b: the module accepts the previous hash as a host input, so any attacker with DMA access can forge the chain. Additionally, FIFO-full silently drops decisions while the sequence counter still advances — a drop is indistinguishable from a tamper from the verifier's point of view. Contradicts every DORA-alignment claim in the repo.
3. **Ethernet shim (Group E)** — freshly written this session; self-review caught **four S0 findings**: wholesale RX header byte-offset error (every field off by ~10 bytes), deadlock on every dropped frame, TX that does not construct a valid Ethernet frame, and `ord_tlast` tied to `1'b1` at the top producing 8-byte "frames". Lint-passes because it is structurally a single-domain stub; the `WITH_CMAC=1` path is a named empty box.

Pipeline (Group C) and infrastructure (Group D) are in better shape — both are "ship with fixes" rather than "rewrite" — but each has S0 silent-failure modes (single-tx throughput masquerading as a pipeline; packed-struct reserved-word collision that breaks modern Verilator).

**Net verdict: the core passes lint, simulates, and demos. It is not production-shaped. The sections below itemise what has to change to close the gap, file-and-line-grained.**

---

## 2. Severity Summary

| Group | Subsystem | S0 | S1 | S2 | S3 | Verdict |
|---|---|---:|---:|---:|---:|---|
| A | Risk controls (`risk_gate`, `rate_limiter`, `position_limiter`, `kill_switch`, `risk_pkg`) | 3 | 5 | 3 | 2 | Ship with fixes; re-architect position tracking |
| B | Audit log + trace (`risk_audit_log`, `trace_pkg`, `trace_pkg_v12`) | 3 | 4 | 2 | 3 | Not trustworthy as tamper-evident; see §5 |
| C | Shell + pipeline (`sentinel_shell{,_v12}`, `instrumented_pipeline`, `stage_timer`, `stub_latency_core`) | 2 | 3 | 3 | 4 | Safe as attribution probe; unsafe as throughput skeleton |
| D | Infrastructure (`sync_fifo`, `fault_injector`, `fault_pkg`) | 2 | 3 | 3 | 3 | `sync_fifo` reliable; `fault_injector` needs rework |
| E | Ethernet layer (`eth_pkg`, `eth_mac_100g_shim`) | 4 | 4 | 4 | 3 | Not ready for `WITH_CMAC=1`; stub only |
| **Total** | | **14** | **19** | **15** | **15** | |

S-ladder definitions: **S0** silent data corruption / safety failure / compliance break; **S1** bug likely to fire under realistic conditions; **S2** correctness gap only under edge case; **S3** style / modernisation.

---

## 3. Group A — Risk Controls

Full findings in `agent-Group-A.md` (this report; the subagent's output is preserved verbatim below). Key S0s:

**A-S0-01 — Kill switch leaks orders when disarmed** (`rtl/kill_switch.sv:91`)
`assign passed = !cfg_armed || !kill_active;` derives `passed` from `kill_active` gated by `cfg_armed`. But the sticky register is `trigger_latched`, not `kill_active`. A host AXI-Lite write clearing `cfg_armed` without `cmd_reset` lets orders through even though the trigger is still latched. Contradicts the "sticky until explicit reset" spec. **Fix:** drive `passed` from `!trigger_latched`, require `cmd_reset` while `cfg_armed=1`.

**A-S0-02 — Monotonic notional ratchet** (`rtl/position_limiter.sv:127-159`)
`gross_notional <= gross_notional + fill_notional` runs on every fill, regardless of whether the fill reduces exposure. In normal two-sided trading `gross_notional` grows monotonically until `notional_ok` fails permanently. **Fix:** track a single signed `net_position`; compute `gross_notional` as `|net_position| * mark_price`.

**A-S0-03 — Wrong-side projection on offsetting orders** (`rtl/position_limiter.sv:68-80`)
A BUY order while short is projected as `long_qty + order_qty`, triggering a position-limit breach when it is actually flattening exposure. Legitimate risk-reducing orders are rejected. **Fix:** project against signed net position.

**A-S1-06 — Combinational AXI-Stream handshake** (`rtl/risk_gate.sv:202-208`)
`in_ready = out_ready`, `out_valid = in_valid`, decisions pure combinational. Creates a combinational loop from downstream `out_ready` back to upstream `in_ready` through three decision modules — will not close timing at HFT clock rates and violates AXI-Stream compliance. **Fix:** add a skid buffer; register the decision with a 1-cycle latency.

**Remaining S1/S2/S3** (selected):
- A-S1-04 Rate-limiter 32-bit refill arithmetic can overflow on same-cycle consume+refill (`rtl/rate_limiter.sv:128-134`)
- A-S1-05 Zero-refill-period silently disables rate limiting (`rtl/rate_limiter.sv:42`)
- A-S1-07 Rate-limiter stats desync with top-level stats under stall (`rtl/rate_limiter.sv:176` vs `rtl/risk_gate.sv:225`)
- A-S1-08 `current_pnl` unsigned with companion `pnl_is_loss` bit invites a two's-complement integration bug (`rtl/kill_switch.sv:55-57`)
- A-S2-10 Heartbeats bypass rate limiter but cancels are blocked by kill switch — should kill-switch allow cancels for flattening? Policy TBD.
- A-S3-12 30+ individual `cfg_*` ports instead of a single struct-typed port; `include` instead of `import`.
- A-S3-13 Zero SVA coverage on the one subsystem that most needs it.

**Coverage gaps:** `tb_risk_gate.sv` is a port-expansion wrapper with no stimulus and no checks. Twelve specific scenarios unexercised (simultaneous triggers, partial/offsetting fills, kill+reset → first post-reset order, boundary WR at `<=`, 32-bit token saturation, signed-PnL INT64_MIN, 10+ cycle `out_ready` stall, etc.).

**Net:** ship with fixes. Three S0 bugs to land before any live deployment; A-S1-06 handshake refactor before tape-out; position representation migration to signed net-position before adding features.

---

## 4. Group B — Audit Log + Trace

**B-S0-1 — Hash chain is host-supplied, not computed on-chip** (`rtl/risk_audit_log.sv:79, 138`)
`prev_hash_lo` arrives as a 128-bit input from the host DMA/Zynq PS path and is blindly embedded into the record. There is no synthesisable BLAKE2b core in the module; the docstring at lines 38-44 admits this but the integration-readiness doc and 2-pager market it as tamper-evident. A compromised host forges records trivially. Collision resistance is also halved — only the low 128 bits of BLAKE2b-512 are carried. **Why it matters:** a DORA conformance review that takes the marketing at face value will fail. **Fix (two paths):** (a) instantiate a real synthesisable BLAKE2b core (~8-16 cycles/block, pipelined, fits HFT budget); or (b) rename the module to `risk_audit_serializer`, strike every "tamper-evident" claim from README / architecture / 2-pager, and treat the host as a trusted component.

**B-S0-2 — Silent drop on FIFO-full** (`rtl/risk_audit_log.sv:156, 170-172`)
`do_write = dec_valid && !full_r`. On full, `dec_valid` decisions are dropped and `stat_records_dropped` increments, but there is no back-pressure to the risk gate, no HBM2 spill (despite what `INTEGRATION_READINESS.md` claims), and no in-band overflow marker. The verifier cannot tell a drop from a tamper. **Fix:** back-pressure via a `dec_ready` output, OR emit an in-band `REC_OVERFLOW` marker (type already exists in `trace_pkg_v12.sv:22`) with drop count and a hash-chain continuation.

**B-S0-3 — Sequence counter advances on dropped decisions** (`rtl/risk_audit_log.sv:98-101`)
`seq_r` increments on any `dec_valid`, including drops. Compounds B-S0-2: a drop leaves a gap in seq numbers but the record that did land carries a post-increment value, so the verifier cannot mechanically distinguish "record dropped at seq N" from "reset glitch skipped seq N". **Fix:** gate `seq_r` increment on `do_write` only, OR maintain separate `attempted_seq` / `committed_seq`.

**S1/S2 (selected):**
- B-S1-1 `full_r` comparison width-broken for non-power-of-2 `FIFO_DEPTH` (`rtl/risk_audit_log.sv:148,151`).
- B-S1-2 `reject_reason` field reserves 16 bits but pads with only 8 zeros — silently truncates if enum widens (`rtl/risk_audit_log.sv:129`).
- B-S1-3 `trace_pkg.sv` struct MSB-first packing vs host little-endian expectation: tx_id lands at bits `[255:192]`, not offset 0 as host parsers assume (`rtl/trace_pkg.sv:35-43`).
- B-S1-4 `trace_pkg` vs `trace_pkg_v12` flag encodings disagree; no version field in v1.0 record to disambiguate. Host parsers will drift.

**Coverage gaps:** no unit test that mutates a record byte and confirms host verifier detects it (the core premise of the subsystem is unverified). No FIFO-drop gap-detection test. No cross-version parser test. No PCIe endianness test. No X-propagation check on `prev_hash_lo`.

**Version hygiene:** deprecate `trace_pkg.sv`. Merge useful `FLAG_CORE_ERROR` / `FLAG_INFLIGHT_UNDER` bits into `trace_pkg_v12::trace_flags_t` reserved bits, grep for every `import trace_pkg::*`, migrate, delete after one release.

**Net:** **not trustworthy as a tamper-evident layer today.** The serializer is well-structured; the cryptographic claim is marketing. Priority: (1) fix B-S0-3 (trivial); (2) fix B-S0-2 with in-band overflow marker + seq gap; (3) make the go/no-go call on B-S0-1 — real BLAKE2b core or rename the module. Trace-package cleanup is independent, schedulable anytime before a host-side parser is frozen.

---

## 5. Group C — Shell + Pipeline

**C-S0-01 — `attr_valid` vs `t_ingress_captured` race** (`rtl/sentinel_shell_v12.sv:110-145`, `rtl/instrumented_pipeline.sv:210-214`)
`t_ingress_captured` updates on every `up_valid && up_ready`; the trace emits `t_ingress_captured` at `ST_DONE`. This is only correct because the pipeline is 1-deep (see C-S1-03) — the moment anyone raises pipeline depth without an inflight FIFO, every tx's ingress timestamp silently overwrites the previous one. The legacy `sentinel_shell.sv:115-148` *has* an inflight FIFO; v12 regressed. **Fix:** port the FIFO forward.

**C-S0-02 — Stage timer silent overflow** (`rtl/stage_timer.sv:25-46`)
32-bit counter, no overflow detect, no sticky flag, no `FLAG_STAGE_SAT` in the v1.2 record. At 250 MHz, 2^32 cycles = 17.2 s — well within a realistic PCIe backpressure stall. After wrap, `d_egress` looks healthy. **Fix:** add sticky `saturated` output, OR the four sticky bits into `trace_record.flags`.

**C-S1-03 — Single-in-flight, not a pipeline** (`rtl/instrumented_pipeline.sv:209`)
`assign up_ready = (state == ST_IDLE);` caps throughput at ~(clk / (CORE_LATENCY + RISK_LATENCY + 2)) — roughly 15 MHz order rate at default params, regardless of clock. The module is an attribution *probe*, not a pipeline. **Fix:** rename the module (`latency_attribution_probe`), OR refactor to true skid-buffered per-stage valid/ready + inflight FIFO for timestamps.

**C-S1-04 — Timer cleanup on reset-mid-tick** — `timers_clear` only fires in `ST_DONE`; a reset during `ST_CORE`/`ST_EGRESS` leaves the risk timer active across the next tx's ingress. First post-reset tx produces garbage attribution. **Fix:** include `!rst_n` in `timers_clear`.

**C-S3-11 — `stub_latency_core` has no synthesis guard** (`rtl/stub_latency_core.sv:1-97`)
Name says "stub", docstring says "essential for testing", but there is no `` `ifndef SYNTHESIS `` wrapper, no `$fatal`, no filelist exclusion. A build-system typo ships it as the strategy core. **Fix:** `` `ifdef SYNTHESIS `initial $fatal(1, "stub_latency_core.sv must not be synthesized"); `endif ``

**Coverage gaps:** `tb_latency_attribution.sv:84` hard-wires `dn_ready=1` and `trace_ready=1` — no back-pressure coverage at all. Nine specific scenarios untested (egress stall, trace-sink stall > FIFO_DEPTH, reset mid-tx, stage-timer saturation, zero-latency stub, v1.1 record format, back-to-back up_valid, tx_id wrap across reset, feature-parity between the two shells).

**Version hygiene:** neither shell is fit to delete. v12 regressed on inflight FIFO + underflow telemetry; legacy has those but is on the 256b trace format. Port inflight-FIFO + underflow bits forward into v12, then deprecate legacy.

**Net:** safe as an instrumentation skeleton; **unsafe as a throughput skeleton.** C-S1-03 and C-S0-02 must close before this is the integration foundation for a real multi-stage shell.

---

## 6. Group D — Infrastructure

**D-S0-01 — Reserved-word `parameter` in packed struct** (`rtl/fault_pkg.sv:29`)
`logic [31:0] parameter;` is rejected by Verilator ≥5.x and VCS `-lint strict`. Three downstream references: `rtl/fault_injector.sv:122, 127, 128`. Blocks any toolchain upgrade. **Fix:** rename to `fault_param`.

**D-S0-02 — Packed layout lock** (`rtl/fault_pkg.sv:25-39`)
`fault_config_t` is packed but there is no `$bits` sanity assertion. Any future field addition silently re-lays out the struct. **Fix:** `initial assert ($bits(fault_config_t) == 100);` in `fault_pkg`.

**D-S1-01 — `fault_injector` stuck-active FSM** (`rtl/fault_injector.sv:67-89`)
Decrement + deactivation are gated on `config_valid[i]` alongside the trigger. A TB that deasserts `config_valid` mid-injection latches `fault_active` forever; the fault leaks into the next scenario silently. **Fix:** move decrement/deactivation outside the `config_valid` gate; force `fault_active <= 0` on `!config_valid`.

**D-S1-02 — Duration off-by-one** (`rtl/fault_injector.sv:83-87`)
Decrement-then-test means a `duration_cycles=N` request fires for `N+1` cycles; `duration=0` (single-shot) fires for 2 cycles. Every `tb_*.sv` scenario is measuring a slightly-longer fault than configured. **Fix:** deactivate when `remaining==1` on the same cycle.

**D-S1-03 — Declared-but-unimplemented fault types** (`rtl/fault_pkg.sv:18-19`)
`FAULT_CLOCK_STRETCH` and `FAULT_BURST` in the enum; `default` branch in the injector does nothing. TBs configuring these see `status.active=1` and `injection_count++` but nothing is injected. Silent no-op. **Fix:** implement both, or `$fatal(1, "unimplemented fault");` under simulation.

**D-S2-02 — sync_fifo has no SVA** (`rtl/sync_fifo.sv`)
Zero `assert property` on a module instantiated in trace FIFO, audit FIFO, order egress FIFO. A regression here compounds N-fold. Four cheap SVAs close this: `no_overflow`, `no_underflow`, `push_pop_preserves_count`, `empty_implies_zero_count`.

**Coverage gaps:** `sync_fifo` has no standalone testbench at all (fill-to-DEPTH, concurrent push+pop at full/empty boundaries, reset mid-fill, DATA_WIDTH=1 / 512, DEPTH=2 / 1024). `fault_injector` has no "no-fault identity" check (config_valid=0 → stream byte-identical to input).

**Net:** sync_fifo is **structurally sound** — full/empty conservative, fill-counter arithmetic correct, concurrent push+pop at full-minus-one safe, reset synchronous. Keep as-is, harden with SVA. `fault_injector` + `fault_pkg` **need surgery**: reserved-word rename, FSM rewrite, fault-type completeness. The adversarial-scenario suite currently measures something other than what it claims until the FSM bug is fixed.

---

## 7. Group E — Ethernet Layer (self-review of M9)

**E-S0-01 — Wholesale RX header byte-offset error** (`rtl/eth/eth_mac_100g_shim.sv:165-175`)
LBUS convention: byte 0 at bits `[511:504]`, byte N at `[511-8N : 504-8N]`. IEEE offsets:
- ethertype bytes 12-13 → `[415:400]` — code reads `[399:384]` (bytes 14-15)
- IPv4 protocol byte 23 → `[327:320]` — code reads `[303:296]` (byte 26)
- IPv4 src_ip bytes 26-29 → `[287:256]` — code reads `[271:240]`
- IPv4 dst_ip bytes 30-33 → `[255:224]` — code reads `[239:208]`
- UDP src_port bytes 34-35 → `[223:208]` — code reads `[143:128]`
- UDP dst_port bytes 36-37 → `[207:192]` — code reads `[127:112]`
- UDP length bytes 38-39 → `[191:176]` — code reads `[111:96]`

Every field is offset by ~10 bytes. No live frame passes the filter; UDP port match is essentially random. **Fix:** parse via `eth_hdr_t`/`ipv4_hdr_t`/`udp_hdr_t` with a byte-reverse helper so the compiler enforces offsets rather than copy-pasted integers.

**E-S0-02 — Dropped-frame deadlock** (`rtl/eth/eth_mac_100g_shim.sv:180-205, 235`)
On filter reject, `rx_frame_drop` latches at SOP and `mkt_tvalid` is held low. But the beat is only released on `mkt_tvalid && mkt_tready`, so it stays stuck, `rx_lbus_ready=0` forever, pipeline stalls until reset. **Fix:** add a consume-and-discard state that advances `rx_word_idx` regardless of `mkt_tvalid` when `rx_frame_drop=1`.

**E-S0-03 — TX does not build a valid Ethernet frame** (`rtl/eth/eth_mac_100g_shim.sv:272-311`)
No MACs, no EtherType, no IPv4 header, no checksum, no UDP length. `ord_tdata` is raw-copied into a 512b beat and tagged SOP/EOP. No real NIC will accept the output. **Fix:** TX header-prepend FSM with parameterised `LOCAL_MAC`/`PEER_MAC`/`LOCAL_IP`/`PEER_IP`/`ORDER_UDP_DPORT`, IPv4 header checksum, back-filled total_length/udp_length from counted payload.

**E-S0-04 — `ord_tlast` tied to `1'b1`** (`fpga/u55c/sentinel_u55c_top.sv:246`)
Top wires `ord_tlast=1'b1`, so the TX packer fires EOP every 8-byte word — "frames" below the 64-byte Ethernet minimum. **Fix:** shell must emit framed AXIS (multi-word orders terminated by tlast); add a minimum-payload accumulator in the shim until it does.

**S1 (selected):**
- E-S1-01 TX last-beat word missing — `tx_lbus_data` reads old `tx_beat` register on the same cycle a new word is being written (`rtl/eth/eth_mac_100g_shim.sv:292-307`).
- E-S1-02 LBUS RX has no line-rate backpressure — CMAC LBUS is free-running, the shim's `rx_lbus_ready` is ignored by the hard IP. Under `mkt_tready=0` the shim stalls and CMAC overruns. **Requires an async FIFO minimum 2 KiB (9 KiB for jumbos) before `WITH_CMAC=1` is usable.**
- E-S1-03 CDC entirely absent. Shim header comments `clk` as 322 MHz; top wires it to `clk_100`. XDC declares the two clocks asynchronous, which will mask real timing violations across what is structurally a synchronous stub.
- E-S1-04 `stat_rx_dropped_port` miscounts because the header reads are wrong (E-S0-01).

**Coverage gaps:** 13 specific scenarios needed minimum (see subagent report) — the shim has zero testbench today.

**CDC honesty:** the current code is a **placeholder**, not production-shaped. Production gap: 512→64 gearbox in 322 MHz domain + packet-boundary FSM; async FIFO (2 KiB min, 9 KiB for jumbos) to core clock; symmetric 64→512 packer on TX; async-reset synchronisers per domain.

**XDC cross-check:** refclk periods (6.206 ns / 3.103 ns) and async-clock-group declaration are correct. `qsfp0_refclk_p/n` and `cmac_usr_clk` ports are declared in `sentinel_u55c_top.sv` — ✓. Missing: `set_max_delay -datapath_only` on future async-FIFO pointer crossings; guard the XDC §7 with `if {[llength [get_ports -quiet qsfp0_refclk_p]]}` so `WITH_CMAC=0` builds don't fail on missing-port lookups.

**Net:** not ready for a `WITH_CMAC=1` Vivado run. As a `WITH_CMAC=0` lint-pass stub the generate-else branch ties everything off cleanly and the shell sees `mkt_*`/`ord_*` directly — **useful for CI only**. Before trusting it: fix byte offsets (S0-01), wire async FIFO + gearbox (S1-02/03), construct TX packet (S0-03), add 13-case testbench, re-audit.

---

## 8. Cross-cutting Patterns

Same problems keep recurring across the five groups:

1. **Zero SVA.** Not a single `assert property` anywhere in `rtl/`. Every audit flagged this. Risk gate invariants, audit log monotonicity, sync_fifo overflow, pipeline AXIS handshake, header checksums — all are textbook formal candidates. One shared `sentinel_sva.sv` bind file would cover 80% of this.

2. **Testbench theatre.** `tb_risk_gate.sv` is a port wrapper. `tb_latency_attribution.sv` hard-ties `dn_ready=1`/`trace_ready=1`. The ethernet shim has no TB at all. `fault_injector` is the test harness and has its own bug that silently pollutes downstream scenarios. None of the TBs exercise back-pressure, reset-mid-tx, or boundary conditions. **We are currently proving things that do not require proving.**

3. **Two copies of each interface.** `trace_pkg` vs `trace_pkg_v12`; `sentinel_shell` vs `sentinel_shell_v12`. In both cases the "old" version has features (inflight FIFO, richer flags) that the "new" version dropped, and both compile and are imported by different parts of the tree. Every migration-in-progress is a drift hazard.

4. **Reserved-word and toolchain-brittleness.** `fault_pkg::parameter`, packed-struct-through-port in `fault_injector`, `trace_pkg_v12.sv:75 initial begin` in package — the RTL compiles on Verilator 4.038 and breaks on ≥5.x. Modernising the toolchain is a prerequisite for every other improvement here.

5. **Claims > implementation, quietly.** "Tamper-evident BLAKE2b hash chain" → the module copies a host-supplied hash. "5-stage pipeline" → 1-in-flight FSM. "100 GbE CMAC shim" → single-domain stub with wrong byte offsets. The behaviour matches the integration-readiness doc's stub list, but the README / 2-pager / architecture doc lean on the marketing version. Tighten the prose to match the code before anyone external reads it.

   **Status (2026-04-21, Wave 3 WP3.4 — RECONCILED):** doc-vs-code reconciled as follows:
   - "Tamper-evident BLAKE2b hash chain" → rewritten across `README.md`, `docs/keyrock-2pager.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/INTEGRATION_READINESS.md`, `docs/USE_CASES.md` as **"host-hashed audit trail (on-chip serialiser + off-chip BLAKE2b chain verifier)"**. Option A per `AUDIT_FIX_PLAN.md` §WP1.2 — the RTL is a pure serialiser (monotonic `seq_no`, 128-bit `prev_hash_lo` driven by host DMA, `REC_OVERFLOW` in-band marker); the BLAKE2b chain is built and walked on the host. Ambiguous "tamper" prose stripped from non-plan docs. "Tamper-detection" retained in `docs/DEMO_SCRIPT.md` §2 where it accurately describes what the host verifier does.
   - "100 GbE CMAC shim" → now truthful. Wave 2 WP2.5 (E-S1-02/03) added a real dual-clock LBUS↔datapath CMAC bridge (`async_fifo` ×2 with gray-coded pointers, `reset_sync` on each side, `set_max_delay -datapath_only` documented in the XDC); WP2.6 (E-S1-01) fixed the 6-byte TX first-beat payload loss. README "FPGA target" section, `docs/ROADMAP.md`, and `docs/ARCHITECTURE.md` Mermaid now reflect the post-WP2.5/2.6 state.
   - "5-stage pipeline" → not yet a true multi-in-flight pipeline. WP2.4 (C-S1-03/04/05) renamed `instrumented_pipeline.sv` → `latency_attribution_probe.sv` (one-in-flight attribution probe, which is what the RTL actually is) and added the `sentinel_pipeline.sv` scaffold. README explicitly lists "real multi-in-flight pipeline behind `latency_attribution_probe`" as a known deferred item; `docs/ARCHITECTURE.md` no longer claims a 5-stage pipeline.

---

## 9. Triage — What Lands First

Ordered by blast-radius × effort:

| # | Finding | Group | Effort | Rationale |
|---|---|---|---|---|
| 1 | B-S0-1 / B-S0-2 / B-S0-3 — audit log hash + drop semantics | B | 1 week | Single biggest gap between claim and code. Either implement real BLAKE2b or drop the "tamper-evident" claim everywhere. |
| 2 | A-S0-01 / A-S0-02 / A-S0-03 — risk controls | A | 1 week | Three S0s that fire in normal operation. Kill-switch disarm leak is the most dangerous. |
| 3 | D-S0-01 — `parameter` reserved-word rename | D | 1 day | Blocks every other toolchain upgrade. Three call sites. |
| 4 | E-S0-01 — header byte-offset rewrite (eth_hdr_t unpacking) | E | 2 days | Prerequisite for anything downstream to see a real frame. |
| 5 | C-S1-03 — rename `instrumented_pipeline` → `latency_attribution_probe` | C | 1 day | Truth-in-labelling; removes the "we have a pipeline" claim until we do. |
| 6 | Shared `sentinel_sva.sv` bind file | all | 1 week | Covers monotonicity / handshake / FIFO invariants for every module. Catches future regressions. |
| 7 | Self-checking TBs (cocotb) for risk_gate + audit_log + sync_fifo | A/B/D | 2 weeks | Gate every subsequent fix on a real regression suite. |
| 8 | E-S1-02 / E-S1-03 — async FIFO + gearbox | E | 2 weeks | Required before `WITH_CMAC=1` is honest. |
| 9 | Legacy-shell / v1.0-trace deprecation | B/C | 3 days | Delete drift hazard. |
| 10 | A-S1-06 — AXI-Stream handshake skid buffer | A | 2 days | Required before timing closure at real HFT clock. |

Total: ~5 engineer-weeks to close every S0 and S1 finding flagged here. That's the number that goes into the next planning cycle — not "the core is done."

---

## 10. Appendix — Raw subagent reports

Each group's audit was produced by an independent subagent against the same rubric. The verbatim markdown is preserved in-line above (§3-§7); the agent IDs are kept for traceability:

- Group A: `acc405a8b75422f9b`
- Group B: `aca3afce04fbc3ca6`
- Group C: `a2d2233020b038c27`
- Group D: `a8d197083f0f46b9c`
- Group E: `a2c30dcd17e51aa63`

This document is the consolidated output. For any line-and-file reference, `rg` the relevant identifier in `rtl/` — every finding carries a path and line number.

---

**Next actions per ROADMAP Workstream 1:**
1. Accept this audit. Open a ticket per S0 finding.
2. Land the triage top-5 (audit-log cluster, risk cluster, `parameter` rename, ethernet header fix, instrumented-pipeline rename) before Workstream 2 (demo UI).
3. Move Workstream 3 (extra regulation modules) to AFTER the audit-log cluster — a regulation module on top of a non-tamper-evident log is worth nothing.
4. Workstreams 4-6 (LLM agent phases) are unblocked by this audit but should not merge until the self-checking TB infrastructure from triage #7 exists — otherwise the agent has nothing trustworthy to learn from.
