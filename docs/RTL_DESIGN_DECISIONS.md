# Sentinel-HFT — RTL Design Decisions

*Audience: FPGA / hardware engineer.*
*Status: v2.0 cycle (post-Wave 4 audit closure).*
*Companion docs: `CDC_AND_RESET.md`, `VERIFICATION_METHODOLOGY.md`,
`INTEGRATION_PLAYBOOK.md`, `SENTINEL_CORE_AUDIT.md`,
`AUDIT_FIX_PLAN.md`.*

This document records every non-obvious choice in the RTL, the
trade-off behind it, the alternative we rejected, and the file (and,
where useful, the line) that implements the choice. The intent is
that a fresh reviewer can understand *why* the code is the way it is
without re-deriving the audit history. If a claim here disagrees with
the code, the code wins and this document is wrong — file a ticket.

The convention throughout is: **the silicon does as little as
possible, the host does as much as possible**. Anything that can be
moved off the FPGA without compromising determinism (parsing,
hashing, framing, formatting) lives on the host. This is what makes
the design auditable, portable, and small enough to reason about.

---

## 1. Active-low reset, async-assert / sync-deassert

**Decision.** Every `rst_n` in the tree is active-low, asserted
asynchronously, deasserted synchronously through `reset_sync.sv`
(STAGES ≥ 2, default 3 in the CMAC domain).

**Why.** Synchronous-only reset costs a clock-tree + a guaranteed
high-fanout net during normal operation; pure-async reset risks
recovery / removal violations on de-assertion when the source clock
is foreign. Async-assert / sync-deassert is the standard discipline
for a multi-clock design and is what Vivado expects when
`ASYNC_REG = "TRUE"` is on the synchroniser flops.

**Rejected.** "Just use the global PCIe reset everywhere" — fine on a
single-clock board, breaks the moment we cross from `clk_100` to
`cmac_usr_clk`. Per-clock `reset_sync` instances cost three flops and
remove the entire class of recovery-violation bugs.

**Implementing files.** `rtl/reset_sync.sv` (the primitive),
`fpga/u55c/sentinel_u55c_top.sv` (`u_rst_core`, `u_cmac_rst` per
domain), `fpga/u55c/constraints/sentinel_u55c.xdc` §4
(`set_false_path -from [get_ports board_rstn]` plus the
synchroniser-pin false-path on line 187).

**Cross-reference.** `CDC_AND_RESET.md` §3 has the per-domain
synchroniser inventory; it is generated from this convention.

---

## 2. Host-hashed audit trail, on-chip serialiser only

**Decision.** `risk_audit_log.sv` is a serialiser. It assigns a
monotonic `seq_no`, captures the decision payload, and emits a 96 B
record. The BLAKE2b chain is computed on the host. The 128-bit
`prev_hash_lo` field of each record is filled by the host before the
descriptor is committed; the silicon copies it verbatim.

**Why.** Wave 1 audit (B-S0-1 in `SENTINEL_CORE_AUDIT.md`) caught the
original module marketing itself as "tamper-evident BLAKE2b hash
chain" while the chain was actually a host-supplied input. The two
honest paths were (a) build a synthesisable BLAKE2b core (8–16
cycles per block, easily fits the budget at 100 MHz, but adds ~3.5 k
LUTs and a module nobody on the team wants to maintain), or (b) make
the silicon a serialiser and put the BLAKE2b verifier off-chip
where it can be tested with reference test vectors and rotated
without a new bitstream. We chose (b) explicitly per AUDIT_FIX_PLAN
§WP1.2 Option A.

The trade is: the *host* becomes the trusted compute. The *silicon*
guarantees only what silicon can guarantee — monotonic sequence,
no-loss back-pressure, in-band overflow markers (`REC_OVERFLOW` from
`trace_pkg_v12.sv`) so a dropped record is discoverable rather than
silent. This matches the DORA/MiFID II requirement (auditable chain
with a clear trust boundary), without making the bitstream part of
the cryptographic root of trust.

**Rejected.**
- *On-chip BLAKE2b.* Worth the LUTs only if the host can be malicious
  *and* the bitstream is the trust anchor. In our deployment model
  the operator owns both the host and the bitstream, so moving the
  hash on-chip protects against nothing the operator wasn't already
  trusted with.
- *On-chip HMAC with a fused key.* Same conclusion plus a key-rotation
  problem (every rotation is a new bitstream).

**Implementing files.** `rtl/risk_audit_log.sv` (serialiser, in-band
overflow marker, gated `seq_r` increment); `rtl/trace_pkg_v12.sv`
(`REC_OVERFLOW`, version field, packed record); `sentinel_hft/host/`
(BLAKE2b verifier — host-side). The host verifier is what actually
detects tamper; the silicon merely guarantees the verifier sees a
gap-free sequence or an explicit overflow marker.

**Cross-reference.** `COMPLIANCE.md` walks the verifier path;
`SENTINEL_CORE_AUDIT.md` §4 documents the original finding;
`AUDIT_FIX_PLAN.md` §WP1.2 records the Option A decision.

---

## 3. `seq_no` increments on commit, not on decision

**Decision.** `seq_r` advances only when a record is actually written
to the FIFO (`do_write`), not on every `dec_valid` from the risk
gate.

**Why.** Wave 1 audit (B-S0-3) caught the opposite: the legacy
implementation incremented on every `dec_valid` including drops, so
a verifier could not distinguish "record dropped at seq N" from
"reset glitch skipped seq N". Gating on `do_write` makes the
sequence number a true statement about what landed off-chip; any
gap is *guaranteed* to be either a drop or a reset, both of which
are observable in-band (drop = `REC_OVERFLOW` marker; reset =
sequence restart with a known seed).

**Rejected.** Maintaining separate `attempted_seq` / `committed_seq`
counters. More expressive, but doubles the state and forces the
verifier to reconcile two streams. The drop case is rare enough that
a single counter plus an explicit overflow marker is the simpler
path.

**Implementing files.** `rtl/risk_audit_log.sv` (gated increment).

---

## 4. Signed `net_position`, not unsigned long/short pair

**Decision.** `position_limiter.sv` tracks a single
`logic signed [QTY_WIDTH:0] net_position`. Gross notional is computed
combinationally as `|net_position| * mark_price`.

**Why.** Wave 1 audit (A-S0-02 / A-S0-03) found two related bugs in
the original `long_qty`/`short_qty` unsigned-pair representation:
(a) `gross_notional` ratcheted monotonically because every fill
incremented one side without netting against the other, so the
position-limit gate failed permanently after enough two-sided
trading; (b) a BUY while short was projected as
`long_qty + order_qty` and rejected as a position-limit breach
even though the order was reducing exposure. A signed scalar
representation is the textbook fix and removes both bugs by
construction.

**Rejected.** "Track gross long, gross short, and net separately."
Strictly more state for a property (gross = |net|) we can compute
combinationally. The signed representation is also what the host
config tool already speaks (`cfg_pos_max_notional` is symmetric).

**Implementing files.** `rtl/position_limiter.sv`, `rtl/risk_pkg.sv`
(`net_position_t`).

---

## 5. Sticky kill, explicit reset only

**Decision.** `kill_switch.sv` drives `passed` from
`!trigger_latched`. The latch is cleared only when `cmd_reset` is
asserted while `cfg_armed=1`. Disarming via `cfg_armed=0` does
**not** clear the latch.

**Why.** Wave 1 audit (A-S0-01) caught the original `!cfg_armed
|| !kill_active` formulation: a host AXI-Lite write that cleared
`cfg_armed` (e.g. an operator "let me investigate" gesture) silently
let orders through even though the trigger was still latched. The
spec was always "sticky until explicit reset"; the code didn't
match. The fix makes the latch the authoritative state and forces
operator intent to clear it.

**Rejected.** "Allow disarm to clear the latch if the trader confirms
twice." Adds a UI workflow for what should be a single, auditable
gesture. The current behaviour matches the audit-log expectation
that every kill event has a paired reset event.

**Implementing files.** `rtl/kill_switch.sv`, `sentinel_sva.sv`
(SVA: `triggered |-> ##[1:$] !passed until cmd_reset`).

---

## 6. AXI-Stream skid buffer on the risk-gate boundary

**Decision.** The risk-gate output is registered through a one-stage
skid buffer; `out_valid` is a flop, `in_ready = !skid_full`. The
gate has 1-cycle latency.

**Why.** Wave 2 audit (A-S1-06) called out a combinational
handshake (`in_ready = out_ready`, `out_valid = in_valid`, decisions
pure combinational) that closed a loop from downstream `out_ready`
back to upstream `in_ready` through three decision modules. That
loop will never close timing at any realistic HFT clock and is not
AXI-Stream compliant — a downstream stall would propagate
combinationally into the upstream tick parser. Adding the skid
buffer costs one cycle of latency, breaks the loop, and makes the
boundary a clean valid/ready handshake the rest of the system can
rely on.

**Rejected.** "Add a forward register only" (no skid). Fine for the
ready→valid direction but loses one cycle of throughput per stall
because the upstream has to wait for the register to drain. Skid
buffer is the standard one-cycle-latency, full-throughput primitive.

**Implementing files.** `rtl/risk_gate.sv` (skid output),
`rtl/sentinel_sva.sv` (`valid && !ready |=> valid && $stable(payload)`).

---

## 7. One in flight, by design — `latency_attribution_probe`

**Decision.** `instrumented_pipeline.sv` is a single-in-flight
attribution probe (`up_ready = (state == ST_IDLE)`). It is *not* a
multi-stage throughput pipeline. The Wave 3 hygiene pass added a
`latency_attribution_probe` alias module pointing at the same RTL
and renamed the path in the architecture doc.

**Why.** The probe exists to attribute end-to-end latency into
`d_ingress` / `d_core` / `d_risk` / `d_egress` with timestamps
captured on a single transaction at a time. A genuine multi-in-flight
pipeline would need an inflight FIFO keyed on `tx_id` so each
transaction's ingress timestamp is preserved through to the egress
timestamp; without that FIFO every new tick overwrites the previous
ingress timestamp and the attribution becomes garbage (Wave 1 audit
C-S0-01). Either we build the FIFO (and it becomes a real pipeline)
or we accept single-in-flight semantics and label the module
honestly. We picked the second path because the attribution numbers
are what we ship to the operator; throughput in the probe doesn't
matter.

The actual order-rate cap on the probe is roughly
`clk / (CORE_LATENCY + RISK_LATENCY + 2)` — about 15 MHz at default
parameters and 100 MHz `clk_100`. That is more than adequate for the
"capture the worst tick" use case the probe serves.

**Rejected.** Building the inflight FIFO right now. It's a Wave 5
backlog item (see `ROADMAP.md`); the right time to land it is when
the shell genuinely needs multi-in-flight throughput, not before.

**Implementing files.** `rtl/instrumented_pipeline.sv` (the FSM and
the alias), `rtl/sentinel_shell_v12.sv` (one-shot wiring),
`docs/ARCHITECTURE.md` (no longer claims multi-stage pipeline).

---

## 8. Stage timer with sticky saturation flag

**Decision.** `stage_timer.sv` carries a sticky `saturated` output and
ORs into the trace record's `flags.stage_sat` bit. The 32-bit counter
saturates rather than wraps.

**Why.** Wave 1 audit (C-S0-02) noted that the original 32-bit
counter wrapped silently. At 100 MHz wraps every 43 s, at 250 MHz
every 17 s — both well within a realistic PCIe back-pressure stall.
After wrap, `d_egress` looked healthy, which is the worst kind of
silent failure mode for an attribution probe whose entire purpose is
to surface long stalls. Sticky saturation plus a flag bit keeps the
counter cheap and makes the failure mode loud.

**Rejected.** Widening the counter to 64 bits. Fixes the symptom
(wrap takes longer) without fixing the failure mode (silent wrap on
genuine pathological stalls). The flag bit is the observable
signal the operator actually wants.

**Implementing files.** `rtl/stage_timer.sv`,
`rtl/trace_pkg_v12.sv` (`FLAG_STAGE_SAT` in `trace_flags_t`).

---

## 9. Parameterised SLR0 floorplan, no SLL crossings on critical path

**Decision.** Every cell on the tick-to-trade critical path
(`u_shell`, `u_risk`, `u_audit`, `u_clkgen`) is constrained into
`pblock_sentinel` which is `SLR0` only. The risk gate gets its own
inner `pblock_risk_gate` pinned to a single clock region
(`CLOCKREGION_X4Y0:CLOCKREGION_X4Y3`) so all risk-decision flops
share a clock region.

**Why.** The U55C has three super-logic regions and SLL crossings
add ≥ 1 ns of latency per hop. The QSFP cages and the PCIe block
are physically in SLR0, so anchoring the datapath there minimises
ingress and egress hops. Pinning the risk gate to a single clock
region prevents intra-SLR latency variance between the rate /
position / kill branches — a variance that would show up as jitter
in the per-stage attribution and confuse the operator.

**Rejected.** "Let Vivado place freely and trust the timing report."
On a near-empty design (~0.1 % LUT utilisation per
`fpga/u55c/reports/area_census.txt`) the placer has too much freedom
and can spill across SLRs even when there is no congestion reason
to. Explicit floorplanning at this scale costs nothing and makes
the timing reports stable run-to-run.

**Implementing files.** `fpga/u55c/constraints/sentinel_u55c.xdc` §5,
`fpga/u55c/sentinel_u55c_top.sv` (matching cell names).

---

## 10. CMAC LBUS bridge is a real CDC, not a single-domain stub

**Decision.** The QSFP path goes through two `async_fifo` instances
(`u_rx_cdc_fifo` from `cmac_usr_clk` to `clk_100`, `u_tx_cdc_fifo`
the other way), each guarded by a `reset_sync` per domain. The XDC
declares the two clocks asynchronous globally and documents the
recommended `set_max_delay -datapath_only` constraints on the gray
pointer crossings (commented in `sentinel_u55c.xdc` §7 because the
pin names depend on synthesis-time mangling).

**Why.** Wave 1 audit (E-S1-02 / E-S1-03) caught the original CMAC
shim as a single-domain stub: header comments said `clk` was
322 MHz, top wired it to `clk_100`, the XDC declared the clocks
async to make Vivado ignore the violation. That is the textbook way
to ship a silently broken CDC. The fix is a real bridge — gray-coded
pointer FIFO (Cummings SNUG2002 formulation), depth ≥ 32 to absorb
LBUS bursts, two-flop synchronisers with `ASYNC_REG = "TRUE"`,
per-domain `reset_sync`. Wave 2 (WP2.5) shipped this; Wave 2 (WP2.6,
E-S1-01) fixed a six-byte first-beat payload loss that was an
artefact of the same broken bridge.

**Rejected.**
- *Synchronous bridge with a clock-MUX.* Defeats the entire reason
  for a real CMAC link (line-rate ingress on the user's choice of
  optics) and wedges the design at one clock ratio.
- *Single deep BRAM-backed FIFO with a global reset.* Misses the
  per-domain reset synchronisation and risks `recovery/removal`
  violations on link bring-up.

**Implementing files.** `rtl/async_fifo.sv`, `rtl/reset_sync.sv`,
`rtl/eth/eth_mac_100g_shim.sv`,
`fpga/u55c/sentinel_u55c_top.sv` (instantiation),
`fpga/u55c/constraints/sentinel_u55c.xdc` §7.

**Cross-reference.** `CDC_AND_RESET.md` is the per-crossing
inventory; the design rationale is here.

---

## 11. `WITH_CMAC` is a generate-gate, not a runtime switch

**Decision.** `sentinel_u55c_top.sv` exposes `WITH_CMAC` as a
parameter. When 0, the QSFP-facing ports are tied off and the
shell sees `mkt_*` / `ord_*` driven directly from the testbench.
When 1, `eth_mac_100g_shim` is generate-instantiated and the QSFP
LBUS pins become live. The XDC §7 constraints are conditional on
the generate branch via `[get_ports -quiet ...]` lookups.

**Why.** Verilator CI has no CMAC model, and dragging in the
encrypted vendor netlist for every elaboration would slow CI by
minutes per PR. A `WITH_CMAC=0` build elaborates the entire shell
without the QSFP path, which is exactly what unit tests need. A
`WITH_CMAC=1` build wires in the real shim and is what the bring-up
flow uses. Using `generate` rather than a runtime switch means the
unused branch is genuinely absent from the netlist; no orphan logic,
no spurious timing reports.

**Rejected.** "Two top-level files, one per build mode." Doubles the
maintenance surface for a difference that's structurally a single
generate.

**Implementing files.**
`fpga/u55c/sentinel_u55c_top.sv` (the generate),
`fpga/u55c/constraints/sentinel_u55c.xdc` §7 (the conditional
constraints), `Makefile` (`WITH_CMAC=0` for elaboration target).

---

## 12. `stub_latency_core` exists, with a tripwire

**Decision.** `stub_latency_core.sv` is a behavioural model used by
the testbench. It carries a synthesis-time `$fatal` tripwire so a
build-system typo that wired it into the bitstream halts elaboration
loudly.

**Why.** Wave 1 audit (C-S3-11) flagged the original module as a
silent shipping risk: name said "stub", docstring said "essential
for testing", but no synthesis guard prevented the integrator from
typoing it into the strategy core. The cost of the tripwire is one
`` `ifdef SYNTHESIS `` block; the cost of *not* having it is a
shipped bitstream where the strategy core is replaced by a fixed-
latency dummy.

**Rejected.** "Just don't put the stub in the filelist." Filelists
get rebuilt, regenerated, and copy-pasted; relying on filelist
hygiene for a safety property is an organisational solution to a
technical problem.

**Implementing files.** `rtl/stub_latency_core.sv` (the tripwire),
`Makefile` (filelist exclusion as defence in depth).

---

## 13. Two trace packages exist, by design — for now

**Decision.** `trace_pkg_v12.sv` is the active record format
(96 bytes, version field, `REC_OVERFLOW`, `FLAG_STAGE_SAT`,
`FLAG_CORE_ERROR`). `trace_pkg.sv` is the legacy v1.0 format,
preserved during the v1.0→v1.2 migration and scheduled for deletion
in a Wave 5 hygiene cycle.

**Why.** Both are imported by different parts of the tree (host
parsers, legacy testbench fragments). Deleting `trace_pkg.sv`
before every `import trace_pkg::*` site is migrated would break
elaboration on the migration branch and force a flag-day cutover.
Keeping the deprecated package compiles the migration as a series
of small PRs, each verifiable independently. The cost is a known
drift hazard the audit calls out (B-S1-4) — mitigated by the
version field in v1.2 records, which lets a host parser reject a
mismatched mix.

**Rejected.** Single `trace_pkg.sv` with conditional defines for the
legacy format. Conditional packages are a worse drift hazard than
two clearly-versioned ones.

**Implementing files.** `rtl/trace_pkg_v12.sv` (current),
`rtl/trace_pkg.sv` (deprecated, scheduled for v2.x deletion).

---

## 14. SVA in a separate `bind` file, not inline

**Decision.** All `assert property` lives in `rtl/sentinel_sva.sv`
which `bind`s into every core module. RTL files contain no inline
assertions.

**Why.** SVA inline in the RTL pollutes the synthesis-clean source
and forces every reader of the module to also reason about its
properties — a category mistake. A separate `bind` file means the
RTL stays focused on the implementation, the SVA file stays focused
on the contract, and a tool that doesn't understand SVA (an
open-source linter, an unfamiliar synthesiser) can ignore the
contract file entirely. This is the standard formal-verification
discipline.

**Rejected.** Inline assertions guarded by `` `ifndef SYNTHESIS ``.
Works, but every reader has to mentally separate spec from
implementation in the same file.

**Implementing files.** `rtl/sentinel_sva.sv` (binds),
all `rtl/*.sv` (no inline assertions).

**Cross-reference.** `VERIFICATION_METHODOLOGY.md` §3 lists the SVAs
per module.

---

## 15. Clock generation: project-local MMCM, no XPM

**Decision.** `sentinel_clock_gen` is a thin local wrapper around
the Vivado MMCM primitive (`MMCME4_ADV` on the U55C) producing
`clk_100` from `sysclk0_p/n`. The XDC declares it via
`create_generated_clock -divide_by 3` rather than letting Vivado
infer it from XPM IP.

**Why.** XPM clocking IP comes with its own IP-management
boilerplate (`.xci` files, IP cache, regeneration steps). For a
single MMCM whose only job is divide-by-3, a hand-written wrapper
plus an explicit `create_generated_clock` is shorter, more
auditable, and survives Vivado version bumps without `.xci`
regeneration drama.

**Rejected.** Full XPM. Worth it the moment we need dynamic phase
shift, jitter shaping, or multi-output clocking. Until then, the
hand-rolled wrapper is the simpler thing.

**Implementing files.** `fpga/u55c/sentinel_u55c_top.sv` (instance
`u_clkgen`), `fpga/u55c/constraints/sentinel_u55c.xdc` §2.

---

## 16. Config ports are flat, not packed AXI-Lite

**Decision.** `sentinel_u55c_top` exposes the full risk-gate config
set (`cfg_rate_*`, `cfg_pos_*`, `cfg_kill_*`, `cmd_kill_*`) as
flat input ports. The integrator wires them into a standard
AXI4-Lite slave (Xilinx provides a template). The host-side config
tool already writes to the matching register offsets.

**Why.** Embedding an AXI-Lite slave in `sentinel_u55c_top` would
make the top-level depend on a vendor template and force every
integrator who already has their own register file to either rip it
out or fight it. Flat ports mean the integrator owns the bus and
the bitstream owns the policy. The host-side `risk_config.py` is
the contract that pins the offsets, and the audit log records
every config write so policy changes are traceable.

The XDC marks these ports as `set_false_path -to ...` because they
are written once at startup and held static; treating them as
timed paths wastes routing slack.

**Rejected.** Embedded AXI-Lite slave. Useful when we ship a
reference shell to a customer who has no register file of their own.
We are not yet that product.

**Implementing files.** `fpga/u55c/sentinel_u55c_top.sv` (port
list), `fpga/u55c/constraints/sentinel_u55c.xdc` §4 (false paths),
`sentinel_hft/cli/config.py` (host-side writer),
`sentinel_hft/protocol/risk_config.py` (offset map).

---

## 17. Per-tick `core_id` + `seq_no` for cross-card replay

**Decision.** Every trace and audit record carries `CORE_ID`
(parameterised at the top, default `16'h0001`) and a strictly
monotonic `seq_no` per core. Two cards running the same bitstream
produce streams that merge losslessly on the host by
`(core_id, seq_no)`.

**Why.** Multi-card deployments are a host-side dedup problem;
making the silicon emit a deterministic key turns it into a
trivial host-side problem rather than a distributed-systems
problem. The cost is two fields per record and zero state in the
silicon (the ID is a parameter, the sequence is per-record). The
benefit is that N+1 redundancy and cross-card aggregation become
host plumbing, not RTL.

**Rejected.** A global cross-card sequence (would require inter-card
synchronisation), or no key at all (forces the host to dedup by
content hash, which is fragile).

**Implementing files.** `fpga/u55c/sentinel_u55c_top.sv` (`CORE_ID`
parameter), `rtl/risk_audit_log.sv` (sequence), `rtl/trace_pkg_v12.sv`
(record layout).

---

## 18. No on-chip TCP, no on-chip ITCH parsing

**Decision.** The shell admits a canonical 64-bit "tick word" on
`mkt_tvalid/tdata`. Per-venue framing (TCP, websocket, ITCH-style
protocols) is host-side. The Ethernet shim parses Ethernet + IPv4 +
UDP only.

**Why.** In-fabric TCP reassembly and per-protocol parsing exist as
vendor IP (PLDA, NetFPGA-style) but blow up the repo size by an
order of magnitude and pin us to a single venue. Host-side framing
in DPDK / kernel-bypass (~200 ns added latency over a pure on-chip
parser) is the standard architecture for venues that publish over
TCP, and it lets us add a new venue by writing a Python parser
rather than a new SystemVerilog module.

**Rejected.** Wire-to-fabric ITCH parsing. Worth it the moment a
co-lo partner insists on the extra 200 ns; not worth it before.

**Implementing files.** `rtl/eth/eth_mac_100g_shim.sv` (Ethernet
+ IPv4 + UDP only), `sentinel_hft/cli/` (host-side venue parsers).

---

## 19. `fault_injector` is in the silicon, not the testbench

**Decision.** `rtl/fault_injector.sv` lives in the synthesisable
tree and can be enabled in a bitstream. The host CLI
(`sentinel-hft hl chaos`, see Phase 2 plumbing in `lib/sentinel-api.ts`)
arms it through the AXI-Lite config surface.

**Why.** Drill replay (kill-switch drill, latency stretch, reject
storm) needs a deterministic, hardware-accurate stimulus path that
matches what production code sees. A testbench-only injector
proves nothing about how the silicon behaves under those faults; an
in-bitstream injector means the drill is run on the same path as
real traffic. The cost is a few hundred LUTs and one config write
per drill.

**Rejected.** Force-mode SVA in the testbench only. Useful for
property checks but not for "what happens to the audit chain when
we inject a one-cycle hold every 1000 ticks for 60 s on the live
card".

**Implementing files.** `rtl/fault_injector.sv`, `rtl/fault_pkg.sv`
(parameter rename `parameter` → `fault_param` per Wave 0 toolchain
upgrade), host CLI in `sentinel_hft/cli/`.

---

## 20. Open-source-first toolchain (Verilator + Yosys), Vivado last

**Decision.** Every PR runs Verilator `--lint-only` and (Phase 0a)
`yosys -p "synth_xilinx"` in CI. Vivado is used only for the cloud
build (Phase 0b) and the on-card bring-up.

**Why.** Vivado licences are expensive, slow, and not available in
the GitHub-hosted CI runners we want to use. Verilator catches the
vast majority of lint and elaboration errors in seconds; Yosys
catches a useful subset of synthesis errors (and gives a free
cell-count estimate) without the licence wait. Vivado is the
authority on timing closure and bitstream generation, but it is the
*last* tool, not the first. This ordering means a PR that fails
Vivado has already passed Verilator and Yosys, so the failure is
real.

**Rejected.** "Vivado in CI." Worth it only if we have a paid build
farm. We do not.

**Implementing files.** `Makefile` (`fpga-elaborate` target),
`.github/workflows/fpga-elaborate.yml`,
`fpga/u55c/scripts/yosys_synth.ys`,
`fpga/u55c/cloud-build/` (the Phase 0b cloud Vivado scaffold).

---

## 21. Active-low `ord_tlast` is the shell's contract, not the shim's

**Decision.** Multi-word orders are framed by the shell: each order
is one or more 64-bit beats terminated by `ord_tlast=1`. The shim's
TX packer accumulates beats until it sees `ord_tlast` and then
emits a single Ethernet frame.

**Why.** Wave 1 audit (E-S0-04) caught the top-level wiring
`ord_tlast=1'b1` as a constant, which made every 8-byte word an
"Ethernet frame" — well below the 64-byte minimum. The fix was to
move the framing responsibility upstream to the shell (which knows
the order semantics) and have the shim trust it. The shim still
zero-pads to 64 bytes if the accumulated payload is smaller.

**Rejected.** "Have the shim guess where order boundaries are."
Couples two modules that should not be coupled and adds a fragile
stateful behaviour to a module whose job is wire-side framing.

**Implementing files.** `rtl/sentinel_shell_v12.sv` (sets `ord_tlast`
correctly per order), `rtl/eth/eth_mac_100g_shim.sv` (TX accumulator
with min-payload pad).

---

## 22. SLR-aware audit log placement near PCIe

**Decision.** The audit log FIFO and the PCIe-egress side of the
trace stream sit in `pblock_sentinel` (SLR0). The PCIe block is
also in SLR0. This minimises the SLL crossings on the egress path
and keeps the audit-log FIFO drain latency deterministic.

**Why.** Every SLL hop on the egress path is jitter that the host
verifier sees as drain-rate noise; pinning everything to SLR0
removes the source of variance. The audit log is small enough
(`AUDIT_DEPTH = 128`, 96 B records → ~12 KiB) that it lives
comfortably in distributed RAM and does not need a BRAM column,
which means the placer has no reason to spill it across SLRs.

**Rejected.** Letting the placer choose. On a near-empty design
the placer may spill purely to balance utilisation, which produces
noisier per-build timing reports.

**Implementing files.**
`fpga/u55c/constraints/sentinel_u55c.xdc` §5,
`rtl/risk_audit_log.sv`.

---

## 23. Heartbeat is a counter, not a free-running oscillator

**Decision.** The board-faceplate heartbeat LED is driven from a
divide-down counter on `clk_100`, not from a separate oscillator.

**Why.** A counter blink proves the user clock is alive. A
separate oscillator blink proves only that the oscillator is alive
(which the board test would already have caught). The counter
costs a handful of LUTs and gives the operator a real liveness
signal at the bezel.

**Rejected.** Oscillator-driven blink. Cheaper visually, useless as
a liveness signal.

**Implementing files.** `fpga/u55c/sentinel_u55c_top.sv`
(`heartbeat` net),
`fpga/u55c/constraints/sentinel_u55c.xdc` §3 (pin assignment).

---

## 24. Documentation is part of the contract

**Decision.** Every claim in `README.md`, `docs/keyrock-2pager.md`,
`docs/ARCHITECTURE.md` is reconciled to the code. Wave 3 (WP3.4)
ran a documented pass (recorded in `SENTINEL_CORE_AUDIT.md` §8)
that rewrote "tamper-evident BLAKE2b hash chain" to "host-hashed
audit trail (on-chip serialiser + off-chip BLAKE2b chain
verifier)", removed the "5-stage pipeline" claim, and made the
"100 GbE CMAC shim" claim truthful by pointing at the post-Wave 2
real CDC bridge.

**Why.** The audit's worst category of finding was "marketing claim
exceeds implementation" — three separate places where the prose
described a property the silicon did not have. A regulator review
that takes the marketing at face value fails the audit. The
discipline is: docs are part of the contract, every change to the
RTL that affects an external claim has to update the doc in the
same PR, and the audit treats prose / code drift as an S0 bug.

**Rejected.** "Docs are aspirational, code is authoritative." The
people who read the docs (regulators, integrators, the operator's
risk committee) do not read the code. Aspirational docs become
silent misrepresentation.

**Implementing files.** All `docs/*.md`,
`README.md`, this document.

---

## Cross-cutting principles

**Be small.** The shippable bitstream uses ~0.1 % of the U55C's LUT
budget. Most decisions above prefer the smaller, more auditable path
even when a bigger one is "more general".

**Be honest.** Where the silicon is a stub, the docstring says
"stub". Where the implementation is a probe, the module name says
"probe". Where a claim is host-side, the prose says "host-side".
The audit found a class of bugs that were purely a labelling
mismatch; the cure is to label everything precisely and let the
reader decide what they need.

**Be portable.** No vendor IP in `rtl/`. The CMAC hard macro lives
outside this repo and is integrated through the LBUS-to-AXIS shim.
The XDMA shell is the integrator's choice. The bitstream is small
enough to run in a soft-core test harness and a hard-IP integration
without behavioural change.

**Be auditable.** Every decision above has a finding ID, a fix PR,
and an SVA or cocotb test that locks it in. The next reviewer
walks `SENTINEL_CORE_AUDIT.md` → this document → the code, in that
order.
