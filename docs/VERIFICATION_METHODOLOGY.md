# Sentinel-HFT — Verification Methodology

*Audience: FPGA / hardware engineer, verification lead, auditor.*
*Status: v2.0 cycle (post-Wave 4 closure, Wave 5 in progress).*
*Companion docs: `RTL_DESIGN_DECISIONS.md`, `CDC_AND_RESET.md`,
`SENTINEL_CORE_AUDIT.md`, `AUDIT_FIX_PLAN.md`,
`releases/v1.0.0/RE_AUDIT_WAVE4.md`.*

This document is the single narrative of *how* Sentinel-HFT gets
verified. It covers the five waves (0–4) that closed the v1.0
audit, the Wave 5 scope that lives in the v2.0 cycle, and the
per-module check matrix that the next reviewer can walk top-down.

The doctrine throughout: **every finding has a failing test before
it has a fix.** No S0 or S1 bug is considered closed until a
self-checking test exists that demonstrates the bug on unmodified
RTL (the `xfail`) and then confirms the fix on patched RTL (the
`xpass`). This is the discipline that prevents a future regression
from silently restoring the bug.

---

## 1. Verification principles

Before the wave structure, three principles that constrain every
wave.

**Test the contract, not the implementation.** Every self-checking
test asserts a property that comes from the spec (e.g. "a sticky
kill trigger clears only on `cmd_reset`") rather than from the
current line-of-code (e.g. "bit 91 of `kill_switch.sv` is high when
`trigger_latched` is high"). Implementation-level tests break
every refactor; contract-level tests survive.

**Self-checking over visual.** Every cocotb test ends in an `assert`
or a scoreboard comparison. Waveform diffs are useful debugging
aids, not acceptance criteria. A test that prints "looks right"
without asserting is not a test.

**Failing first.** Every finding added to `SENTINEL_CORE_AUDIT.md`
gets an `xfail`-marked cocotb test in the same commit. The fix
commit flips the marker to `xpass` and removes the `xfail`. A
finding without a demonstrating test is a claim, not a bug.

**SVA at the boundary.** Properties that hold for the lifetime of
the design (monotonicity of `seq_no`, AXI-Stream valid/ready
discipline, FIFO overflow) live in `rtl/sentinel_sva.sv` bound into
every module. These run during every simulation and catch
regressions the test suite might miss.

**Docs as contract.** Every public claim in `README.md`,
`docs/keyrock-2pager.md`, `docs/ARCHITECTURE.md` is reconciled to
the implementation during Wave 3. Prose that outruns code is an S0
bug in its own right (see Wave 3 WP3.4).

---

## 2. Wave structure

The v1.0 audit closure ran in five waves, each with an explicit
gate.

### Wave 0 — Toolchain, SVA, cocotb harness

**Scope.** Lay the verification infrastructure. No bug fixes.

**Closed.** D-S0-01 (`parameter` reserved-word rename); preparatory
work for every downstream S0.

**Deliverables.**
- Verilator pinned to ≥ 5.020 in CI (`.github/workflows/fpga-elaborate.yml`).
- `rtl/sentinel_sva.sv` bind file with at least one assertion per
  core module.
- `tests/rtl/` cocotb harness with one test file per module:
  `test_risk_gate.py`, `test_audit_log.py`, `test_sync_fifo.py`,
  `test_latency_attribution.py`, `test_eth_shim.py`.
- Every S0 / S1 finding has an `xfail` test demonstrating the bug
  on unmodified RTL.

**Gate.** All five test files run on CI, all xfails fail as
expected, `make fpga-elaborate` exits 0 on Verilator 5.x with
`-Wall -Werror`.

**Rationale.** A fix-first approach would have landed bug fixes on
a testbench infrastructure that could not tell correct from
broken. Wave 0 spent one engineer-week paying that cost up front
so every subsequent wave had a working scoreboard.

### Wave 1 — Close every S0

**Scope.** Every S0 finding from `SENTINEL_CORE_AUDIT.md` (14
total across five groups).

**Closed.** 14/14 S0 findings:

| ID | Subsystem | What broke |
|---|---|---|
| A-S0-01 | kill_switch | Disarm leaked orders past a latched kill |
| A-S0-02 | position_limiter | Monotonic notional ratchet |
| A-S0-03 | position_limiter | Wrong-side projection on offsetting orders |
| B-S0-01 | risk_audit_log | Hash chain host-supplied, not on-chip (resolved as Option A — serialiser + off-chip BLAKE2b, see RTL_DESIGN_DECISIONS §2) |
| B-S0-02 | risk_audit_log | Silent drop on FIFO-full → `REC_OVERFLOW` in-band marker |
| B-S0-03 | risk_audit_log | `seq_r` advanced on dropped decisions |
| C-S0-01 | latency_attribution_probe | `attr_valid` vs `t_ingress_captured` race |
| C-S0-02 | stage_timer | Silent 32-bit overflow → sticky `FLAG_STAGE_SAT` |
| D-S0-01 | fault_pkg | `parameter` reserved-word collision |
| D-S0-02 | fault_pkg | Packed-struct layout lock — `$bits` assertion added |
| E-S0-01 | eth_mac_100g_shim | Wholesale RX header byte-offset error |
| E-S0-02 | eth_mac_100g_shim | Dropped-frame deadlock |
| E-S0-03 | eth_mac_100g_shim | TX did not construct a valid Ethernet frame |
| E-S0-04 | sentinel_u55c_top | `ord_tlast` tied to `1'b1` at top |

**Deliverables per fix.**
- RTL patch.
- Corresponding cocotb `xfail` → `xpass` flip.
- New SVA assertion in `sentinel_sva.sv` locking the contract.
- `SENTINEL_CORE_AUDIT.md` finding annotated with commit hash.

**Gate.** All Wave 0 S0 `xfail` tests flip to `xpass`. No new SVA
assertion regresses.

### Wave 2 — Close every S1

**Scope.** Every S1 finding (19 total).

**Closed.** 19/19 S1 findings across risk controls, audit log,
shell/pipeline, infrastructure, and Ethernet layer. Detailed
finding-to-commit mapping in `AUDIT_FIX_PLAN.md`.

**Key structural work.**
- **WP2.4** — `instrumented_pipeline.sv` renamed to
  `latency_attribution_probe` (alias), plus
  `sentinel_pipeline.sv` scaffold for future multi-in-flight.
- **WP2.5** — CMAC CDC bridge: `rtl/async_fifo.sv` and
  `rtl/reset_sync.sv` added; `eth_mac_100g_shim.sv` rewritten to
  use them; XDC §7 documents `set_max_delay` recommendation.
- **WP2.6** — Ethernet TX last-beat off-by-one (E-S1-01) fixed.

**Gate.** All S1 xfails pass. Post-Wave 2 Verilator lint clean;
yosys synth runs to completion; CMAC bridge passes the two-clock
acceptance test (`WITH_CMAC=1` Verilator elaboration + SVA run).

### Wave 3 — Hygiene, dedup, doc alignment

**Scope.** Cleanups that were not bug fixes but would have
accumulated technical debt if deferred.

**Deliverables.**
- **WP3.1** — Legacy `sentinel_shell.sv` and `trace_pkg.sv` marked
  as deprecated; documented deletion path for a future Wave 5 /
  v2.x release.
- **WP3.3** — Stub synth guards: `stub_latency_core.sv` carries
  a `` `ifdef SYNTHESIS `` tripwire; LED tripwire on the board.
- **WP3.4** — Doc / claim alignment pass. Every "tamper-evident
  BLAKE2b hash chain" rewritten to "host-hashed audit trail
  (on-chip serialiser + off-chip BLAKE2b chain verifier)". Every
  "5-stage pipeline" claim rewritten or removed. CMAC claims
  made truthful post-WP2.5/2.6.

**Gate.** Zero references to the retired marketing claims
anywhere in `README.md`, `docs/`, `sentinel-web/` UI text.
Legacy modules carry explicit deprecation headers.

### Wave 4 — Regression + re-audit + release

**Scope.** Sign-off.

**Deliverables.**
- **WP4.2** — Drill replay on all four HL use cases + Deribit
  demo; every audit-log chain verified end-to-end by the host-side
  BLAKE2b verifier.
- **WP4.3** — Independent re-audit with the same six-axis rubric.
  Documented in `releases/v1.0.0/RE_AUDIT_WAVE4.md`. Outcome:
  zero new S0, zero new S1.
- **WP4.4** — `v1.0.0-core-audit-closed` release tagged with the
  release notes under `docs/releases/v1.0.0/`.

**Gate.** Re-audit produces zero new S0/S1. Full regression
green. Tag cut.

**Outcome.** v1.0.0 was the shippable-as-a-stub baseline. The
silicon was correct-as-documented; the marketing matched the
silicon. Everything that the audit flagged as not production-ready
was documented as such. This was the point the v2.0 cycle could
start from.

### Wave 5 — v2.0 cycle (in progress)

**Scope.** Net-new v2.0 features + any S2/S3 items that were
ticketed but deferred in v1.0.

**Current backlog.** Tracked in `docs/V2_PLAN.md` and the project
task list (phases 1–7 plus 0a/0b). Verification-relevant items:

- Multi-in-flight pipeline behind `latency_attribution_probe` (the
  v1.0 probe remains; the real pipeline is the v2.0 additive).
- Self-checking CDC tests (`tests/rtl/test_async_fifo.py`,
  `tests/rtl/test_reset_sync.py`) — current coverage is the
  `WITH_CMAC=1` Verilator elaboration plus SVA; the cocotb
  per-primitive tests are the next lock-in.
- Phase 0a (`yosys_synth_xilinx` CI) and Phase 0b (cloud Vivado)
  — adds synthesis evidence to the CI surface.
- Regulation module self-tests (CAT, MAR, FINRA 15c3-5, Reg AT,
  FINMA, MAS) — closed during Wave 5 workstream WS3.
- RCA feature pipeline tests (WS4) — closed.
- Streaming triage detectors (WS5) — closed.

**Gate (when v2.0 cuts).** Same six-axis re-audit rubric; zero
new S0/S1; `docs/RTL_DESIGN_DECISIONS.md` + `CDC_AND_RESET.md`
+ this doc + `INTEGRATION_PLAYBOOK.md` rendered on
`/sentinel/hardware` and reviewed by at least one engineer who
was not the author.

---

## 3. SVA inventory

`rtl/sentinel_sva.sv` binds assertions into every module. This is
the authoritative list — the SVA file is the source of truth, this
section is the index.

**Risk gate (`risk_gate.sv`).**
- `kill_sticky`: `triggered |-> ##[1:$] !passed until cmd_reset`
- `rate_bucket_bounded`: `bucket <= cfg_max_tokens`
- `axis_handshake_stability`: `valid && !ready |=> valid && $stable(payload)`
- `skid_no_loss`: skid buffer does not drop under back-pressure

**Audit log (`risk_audit_log.sv`).**
- `seq_monotonic`: `seq_r` increments only on `do_write`
- `full_no_write`: `full_r |-> !do_write`
- `rec_stability`: `rec_valid |-> $stable(rec_data) until rec_ready`
- `overflow_marker_present`: drop → in-band `REC_OVERFLOW`

**`sync_fifo.sv`.**
- `no_overflow`: `wr_en && full |=> $stable(count)`
- `no_underflow`: `rd_en && empty |=> $stable(count)`
- `push_pop_preserves_count`: concurrent push+pop with non-edge
  state leaves count stable
- `empty_iff_zero`: `empty |-> (count == 0)`

**`async_fifo.sv`.**
- `no_overflow`: `wr_en && full |=> $stable(wr_ptr_bin_r)`
- `no_underflow`: `rd_en && empty |=> $stable(rd_ptr_bin_r)`
- `gray_one_bit_toggle`: `$onehot0(wr_ptr_gray_r ^ wr_ptr_gray_n)`

**`reset_sync.sv`.**
- `sync_deassert`: after `rst_n_in` rises, `rst_n_out` rises exactly
  `STAGES` clocks later

**Latency attribution probe (`instrumented_pipeline.sv`).**
- `up_handshake_stability`: `up_valid && !up_ready |=> up_valid && $stable(up_data)`
- `attr_pulse`: `attr_valid` is a one-cycle pulse per transaction
- `stage_sum_bounded`: `d_ingress + d_core + d_risk + d_egress <= t_egress - t_ingress`

**Stage timer (`stage_timer.sv`).**
- `saturation_sticky`: `saturated |-> !counting || stop`

All of the above assertions pass on the current (Wave 4) RTL. A
future change that regresses any of them fails the SVA step of the
regression run before merge.

---

## 4. Per-module check matrix

This matrix is the top-down walk. Each row is one module; each
column is one verification axis. A tick means the axis is covered
by a named artefact (test, SVA, lint check, audit); a dash means
the axis is not applicable.

| Module | Lint | SVA | cocotb | Audit group | Acceptance |
|---|:---:|:---:|:---:|:---:|:---:|
| `risk_gate.sv` | ✓ | ✓ | ✓ | A | S0/S1 closed |
| `rate_limiter.sv` | ✓ | ✓ | ✓ | A | S0/S1 closed |
| `position_limiter.sv` | ✓ | ✓ | ✓ | A | S0/S1 closed |
| `kill_switch.sv` | ✓ | ✓ | ✓ | A | S0/S1 closed |
| `risk_pkg.sv` | ✓ | — | — | A | static only |
| `risk_audit_log.sv` | ✓ | ✓ | ✓ | B | S0/S1 closed |
| `trace_pkg_v12.sv` | ✓ | — | — | B | static only |
| `trace_pkg.sv` | ✓ | — | — | B | deprecated, scheduled delete |
| `sentinel_shell_v12.sv` | ✓ | ✓ | ✓ | C | S0/S1 closed |
| `sentinel_shell.sv` | ✓ | — | — | C | deprecated, scheduled delete |
| `instrumented_pipeline.sv` (alias `latency_attribution_probe`) | ✓ | ✓ | ✓ | C | S0/S1 closed, single-in-flight by design |
| `stage_timer.sv` | ✓ | ✓ | ✓ | C | S0/S1 closed |
| `stub_latency_core.sv` | ✓ | — | — | C | synthesis tripwire present |
| `sync_fifo.sv` | ✓ | ✓ | ✓ | D | S0/S1 closed |
| `fault_injector.sv` | ✓ | ✓ | ✓ | D | S0/S1 closed |
| `fault_pkg.sv` | ✓ | — | — | D | static only, `$bits` asserted |
| `eth_pkg.sv` | ✓ | — | — | E | static only |
| `eth_mac_100g_shim.sv` | ✓ | ✓ | Wave 5 | E | S0/S1 closed; per-primitive cocotb deferred |
| `async_fifo.sv` | ✓ | ✓ | Wave 5 | E | S0/S1 closed; per-primitive cocotb deferred |
| `reset_sync.sv` | ✓ | ✓ | Wave 5 | E | S0/S1 closed; per-primitive cocotb deferred |
| `sentinel_sva.sv` | ✓ | n/a (is the SVA) | — | all | binds into all modules |

The two Wave 5 items (per-primitive cocotb tests on the CDC
primitives) are the most significant verification gap still open.
The CMAC bridge is covered end-to-end by the `WITH_CMAC=1`
elaboration plus the SVA, but a targeted per-primitive test suite
is the right lock-in before the first production bitstream.

---

## 5. Toolchain

The verification toolchain is deliberately small.

**Verilator ≥ 5.020** — fast lint, elaboration, simulation with
SVA support. CI runs `verilator --lint-only` on every PR;
`make sim` does a full simulation with SVA active.

**Yosys ≥ 0.40** (Wave 5 Phase 0a) — open-source synthesis with
`synth_xilinx -family xcup`. Produces a cell count and rough
longest-path estimate. Not a substitute for Vivado timing
closure; it is a "does the design synthesise at all" signal that
runs in CI without a paid licence.

**Vivado 2023.2+** (Wave 5 Phase 0b, cloud-only) — the authority
on timing closure and bitstream generation. Runs one-shot on an
EC2 box provisioned by `fpga/u55c/cloud-build/main.tf` once AWS
is ready. WNS / TNS / WHS numbers committed as
`fpga/u55c/reports/timing_summary.rpt` plus a machine-readable
JSON sidecar.

**cocotb** — Python-driven RTL testbenches. Every bug finding has
a cocotb test; the harness lives at `tests/rtl/`.

**pytest** — wraps cocotb runs, provides `xfail` / `xpass`
discipline. Runs on every PR in the CI `rtl-tests` job.

**Host-side BLAKE2b verifier** — Python, uses the stdlib
`hashlib.blake2b`. Golden test vectors from RFC 7693 (BLAKE2
reference vectors) plus per-run chain verification against the
on-card trace DMA. This is the other half of the "host-hashed
audit trail" contract; see `RTL_DESIGN_DECISIONS.md` §2.

**What we deliberately do not use.**
- *UVM.* Too much infrastructure for a small RTL tree. cocotb +
  SVA covers the same contract with less boilerplate.
- *Formal property verification (Symbiyosys / JasperGold).* The
  SVA assertions are formal-ready (no `##` depth greater than
  `$` in most cases); a Wave 5 / v2.x item is to run Symbiyosys
  against `sentinel_sva.sv` for exhaustive proof, not just
  dynamic simulation. Tracked in the backlog.
- *Gate-level simulation.* Deferred to post-place-and-route in
  Vivado; no value from running it before a real bitstream.

---

## 6. CI surface

Every PR runs these jobs. A red job blocks merge.

| Job | Tool | Scope | Typical runtime |
|---|---|---|---|
| `fpga-elaborate` | Verilator `--lint-only -Wall -Werror` | All `rtl/` + `fpga/u55c/` with `WITH_CMAC=0` | ~ 10 s |
| `fpga-elaborate-cmac` | Verilator `--lint-only` | `WITH_CMAC=1` path | ~ 15 s |
| `rtl-tests` | cocotb + pytest | `tests/rtl/` | ~ 2 min |
| `host-tests` | pytest | `tests/` (Python side) | ~ 3 min |
| `sim-sva` | Verilator full sim with SVA | `sim/tb_sentinel_shell.sv` | ~ 30 s |
| `yosys-synth` (Phase 0a, pending) | Yosys `synth_xilinx` | Full tree | ~ 1 min |

The v2.0 cycle adds the `yosys-synth` job (Phase 0a — tracked as
task #98). The `vivado-build` job lives in a separate workflow
(Phase 0b) because it runs on an EC2 box, not the GitHub runner
pool.

---

## 7. Regression cadence

**Per PR.** Full CI surface (§6). Every PR must land green.

**Per merge to `main`.** Same as per PR, plus a tagged artefact
(Verilator sim log + cocotb junit XML + yosys report) uploaded to
`fpga/u55c/reports/` for the trailing-main history.

**Nightly.** Extended regression (soak):
- 1M-tick random-stimulus run through `tb_sentinel_shell`.
- Drill replay — all four HL use cases + Deribit demo, with the
  host-side BLAKE2b verifier walking every audit chain.
- Latency attribution p50/p95/p99 histogram, compared against
  the golden histogram from the last release. Deviation > 3σ
  flags a regression.

**Per release.** Everything above plus the independent re-audit
(Wave 4 pattern). Same six-axis rubric, a different pair of eyes
than the author. Zero new S0/S1 is the release gate.

---

## 8. Golden test vectors

The audit chain has external reference vectors that anchor the
host-side verifier to a standards-body truth.

**BLAKE2b RFC 7693 vectors.** The Python host verifier runs
against the full RFC 7693 reference set at CI time. Any drift
between the host `hashlib.blake2b` and the reference vectors is
a CI fail before the verifier is ever applied to a real audit
chain. This is what locks the host side to the published
standard.

**Synthetic audit chains.** `tests/test_audit_chain.py` generates
synthetic chains of 10, 100, 10_000 records; confirms the
verifier accepts untampered chains; confirms it rejects chains
with a single-byte mutation at a randomly chosen position. The
second is the *real* tamper-evidence test — the one the
regulator would ask about. This is a host-side test because the
claim is a host-side claim; see `RTL_DESIGN_DECISIONS.md` §2.

**Drill replay fixtures.** `wind_tunnel/replay_runner.py` replays
the four HL use cases plus the Deribit demo from stored pcaps.
The expected trace record set is golden-compared byte-exact.
Any deviation is a regression.

---

## 9. What Wave 4 proved, what it did not

The Wave 4 re-audit is documented in detail at
`docs/releases/v1.0.0/RE_AUDIT_WAVE4.md`. For this doc, the
summary is:

**Proved.**
- Every v1.0 S0 / S1 finding has a closing commit, a self-checking
  test, and an SVA or golden-vector lock-in.
- Prose / code alignment holds. No marketing claim in the current
  docs exceeds the implementation.
- The `WITH_CMAC=0` elaboration and the `WITH_CMAC=1` elaboration
  both pass Verilator with `-Wall -Werror`.
- The host-side BLAKE2b verifier passes RFC 7693 + synthetic
  chain vectors; rejects single-byte tampered chains.
- The drill replay for all five scenarios produces byte-exact
  golden traces.

**Did not prove.**
- Timing closure on real silicon. v1.0 is a pre-Vivado-run
  release by design; the cloud Vivado flow (Phase 0b) is the
  bring-up for that.
- Line-rate performance on a real CMAC. The `WITH_CMAC=1` path
  elaborates and passes SVA; it has not been run against a real
  hardware CMAC. Bring-up is a Wave 5 / Phase 0b item.
- Multi-in-flight throughput. The v1.0 probe is single-in-flight
  by design; the v2.0 cycle adds the real pipeline behind it.
- Anything about the specific venue protocols. Host-side parsers
  for Binance / OKX / Bybit are integration-readiness gaps
  listed in `INTEGRATION_READINESS.md`; not in verification
  scope.

The v1.0 release is the shippable-as-audited baseline. The v2.0
cycle closes the "did not prove" list and lands the net-new
features.

---

## 10. Re-audit checklist for v2.0

When Wave 5 cuts, this is the walk for the re-auditor.

1. **Toolchain.** Verilator ≥ 5.020 in CI, yosys ≥ 0.40 in CI,
   Vivado 2023.2+ cloud build produces timing reports. All three
   version-pinned in `Makefile` or workflow YAML.
2. **SVA.** `rtl/sentinel_sva.sv` binds into every module. The
   inventory in §3 matches the file.
3. **cocotb.** `tests/rtl/` has at least one test file per module
   with an `assert` at the scoreboard.
4. **Docs.** Every claim in `README.md`, `docs/keyrock-2pager.md`,
   `docs/ARCHITECTURE.md`, this doc, `RTL_DESIGN_DECISIONS.md`,
   `CDC_AND_RESET.md`, `INTEGRATION_PLAYBOOK.md` is reconciled
   to the code. Prose that outruns code is an S0.
5. **Findings.** `SENTINEL_CORE_AUDIT.md` lists every finding
   with a commit hash and a closing test. Any finding without
   both is open and must be closed before release.
6. **Regression.** Nightly soak has been green for 7 consecutive
   nights. Drill replay produces byte-exact golden traces.
7. **Independent eyes.** The re-auditor is not the author of the
   code under review. Zero new S0, zero new S1 is the release
   gate.

If every step passes, v2.0 is shippable. If any step fails, file
the finding and loop.
