# Sentinel-HFT FPGA — Architecture

**Phase:** 1 (FPGA Floor)
**Last updated:** 2026-05-08

This document describes the FPGA datapath at a level a software engineer
or auditor can follow. RTL details (specific module ports, packed-struct
layouts, etc.) live with the modules themselves.

---

## 1. One-paragraph summary

The Sentinel risk gate is an FPGA-resident pre-trade circuit. Orders
arrive on an AXI-Stream interface, pass through five parallel rule
checks (rate, position-family, fat-finger, allowlist, kill-state), and
emerge on the output stream either accepted (with the original payload
intact) or rejected (with a one-byte reject code). Every decision is
chained into a BLAKE2b-keyed audit log on the way out, so the host
can prove after the fact that no order bypassed the gate.

---

## 2. Block diagram (logical)

```
                    ┌──────────────────────────────────────────────┐
                    │                                              │
   FIX/OUCH         │                                              │     downstream
   adapter ───►──── │  AXI-Stream                                  │ ───►── exchange
   (host /          │     in                                       │       out
    Phase 2)        │                                              │
                    │     ┌───────────────────────────────┐        │
                    │     │ risk_gate.sv                  │        │
                    │     │  ┌─────────┐  ┌─────────┐     │        │
                    │     │  │ kill    │  │ rate    │     │        │
                    │     │  │ switch  │  │ limiter │     │        │
                    │     │  └────┬────┘  └────┬────┘     │        │
                    │     │       │            │           │        │
                    │     │  ┌────▼─────────────▼────┐     │        │
                    │     │  │ position_limiter      │     │        │
                    │     │  │ (notional+long+short) │     │        │
                    │     │  └────────────┬──────────┘     │        │
                    │     │               │                 │        │
                    │     │  ┌────────────▼──────────┐     │        │
                    │     │  │ fat_finger_band       │     │        │
                    │     │  └────────────┬──────────┘     │        │
                    │     │               │                 │        │
                    │     │  ┌────────────▼──────────┐     │        │
                    │     │  │ symbol_allowlist      │     │        │
                    │     │  └────────────┬──────────┘     │        │
                    │     │               │                 │        │
                    │     │      first-fail compositor      │        │
                    │     │               │                 │        │
                    │     │           skid buffer           │        │
                    │     │               │                 │        │
                    │     └───────────────┼─────────────────┘        │
                    │                     │                          │
                    │                     ▼                          │
                    │             risk_audit_log                     │
                    │            (BLAKE2b chain)                     │
                    │                     │                          │
                    └─────────────────────┼──────────────────────────┘
                                          │
                                          ▼
                                  AXI-Stream out
                                  + audit chain head register
```

The five rule modules are evaluated combinationally on the same input
order; a "first-fail compositor" picks the highest-precedence reject
reason (kill > rate > position-family > fat-finger > allowlist). The
result is captured by a single-entry skid buffer (one decision per
clock at full throughput) and emitted to downstream and to the audit
chain.

Per Phase-1 pre-reg amendment AM-01, the position limiter accumulates
one **aggregated** book (long, short, notional) — not per-symbol. Per-
symbol slicing is Phase 16+ backlog.

---

## 3. Reject precedence

When more than one rule rejects an order, the gate returns a SINGLE
reject reason chosen by the compositor in this order:

| Priority | Reason                        | Source               |
|----------|-------------------------------|----------------------|
| 1 (high) | `RISK_KILL_SWITCH` (0x05)     | `kill_switch.sv`     |
| 2        | `RISK_RATE_LIMITED` (0x01)    | `rate_limiter.sv`    |
| 3        | `RISK_ORDER_SIZE` (0x04)      | `position_limiter.sv`|
| 4        | `RISK_NOTIONAL_LIMIT` (0x03)  | `position_limiter.sv`|
| 5        | `RISK_POSITION_LIMIT` (0x02)  | `position_limiter.sv`|
| 6        | `RISK_FAT_FINGER` (0x07)      | `fat_finger_band.sv` |
| 7 (low)  | `RISK_ALLOWLIST_BLOCK` (0x08) | `symbol_allowlist.sv`|

The order matches the Python golden model in `sentinel_hft/golden/risk_gate.py`
exactly. This is verified by V-Floor on every CI run.

---

## 4. Datapath timing

- **Target Fmax (Phase 1):** 100 MHz (conservative — see U55C README).
- **Decision latency:** combinational through the rule modules, captured
  on the next clock by the skid buffer. End-to-end = 1 cycle = 10 ns at
  100 MHz.
- **Throughput:** one decision per clock. At 100 MHz that is 10⁸
  decisions/sec — the AXI-Stream upstream is the bottleneck, not the
  gate.
- **Pre-reg latency band:** p99 ≤ 1000 ns; p99.99 ≤ 1500 ns. Headroom is
  large; the band exists for *future* Vivado retiming runs that may not
  hit the 100 MHz target on a particular toolchain version.

---

## 5. State machines

### 5.1 Kill switch (`kill_switch.sv`)

```
         arm bit
           │
           ▼
        ┌──────┐  cmd_trigger / pnl<threshold   ┌──────────┐
        │ IDLE │─────────────────────────────►──│ TRIPPED  │
        └──────┘                                └─────┬────┘
           ▲                cmd_reset                 │
           └──────────────────────────────────────────┘
```

Sticky once tripped. The only way out is a host-issued `cmd_reset`.
This is intentional — kill-switch state is a regulatory primitive.

### 5.2 Token bucket (`rate_limiter.sv`)

Standard token bucket. Tokens refill `cfg_refill_rate` units every
`cfg_refill_period` cycles, capped at `cfg_max_tokens`. Each non-
heartbeat order consumes one token.

### 5.3 Position book (`position_limiter.sv`)

Accumulates aggregated long/short/notional from `fill_*` notifications
(NOT from incoming orders — the order may not actually fill). Wave-1
audit fix A-S0-02/03: signed unwind on opposite-side fills (a BUY on
a short book reduces the short before contributing to the long).

### 5.4 Audit chain (`risk_audit_log.sv`)

```
   decision_t
       │
       ▼
   ┌─────────────────────────────┐
   │ BLAKE2b-keyed hash of       │
   │   (head_hash, decision_t)   │ ──► new head_hash + monotonic seq
   └─────────────────────────────┘
       ▲
       │
   key (write-only; not readable from host)
```

Key never leaves the FPGA register file once written. Seq number
monotonically increases. Full chain spec: `docs/audit/CHAIN_FORMAT.md`
(Phase 5).

---

## 6. AXI-Stream contract

### Inbound (`order_in_*`)

| Signal             | Width | Direction | Notes |
|--------------------|-------|-----------|-------|
| `tvalid`           | 1     | in        | order is presented |
| `tready`           | 1     | out       | gate accepts on rising edge |
| `tdata` (`order_t`)| ~256  | in        | packed `order_t` from `risk_pkg.sv` |
| `tlast`            | 1     | in        | unused for orders; reserved for batches |

### Outbound (`order_out_*`)

| Signal             | Width | Direction | Notes |
|--------------------|-------|-----------|-------|
| `tvalid`           | 1     | out       | decision presented |
| `tready`           | 1     | in        | downstream backpressure |
| `tdata` (`order_t`)| ~256  | out       | the original payload (echo) |
| `out_rejected`     | 1     | out       | 1 if this order is rejected |
| `out_reject_reason`| 8     | out       | `risk_reject_e` per `risk_pkg.sv` |

The skid buffer ensures one-cycle decoupling — `tready` going low
downstream does not stall combinational rule evaluation upstream.

---

## 7. Register-map binding

The single source of truth for all host-visible registers is
`fpga/regmap.yaml`. The FPGA's PCIe BAR0 maps that file 1:1. Eight
logical blocks at byte offsets `0x0000, 0x0100, 0x0200, 0x0300,
0x0400, 0x0500, 0x0700, 0x0800` (audit_chain shifted to 0x0700 to make
room for the 0x0200-byte allowlist; documented in regmap.yaml).

V-Contract (the verification system's regmap-checker) parses the YAML
on every CI run and asserts:

- No two blocks overlap.
- Every register has a unique `(block.base + offset)`.
- All `wo` registers read as zero, all `ro` registers reject writes,
  all `w1c` registers self-clear after one cycle.

If any rule fails, V-Contract returns FAIL and the build doesn't ship.

---

## 8. What's NOT in this build (Phase 1 scope)

Per `roadmap/pre_reg/phase_01.yml`:

- No FIX/OUCH adapter — orders arrive in the gate's native AXI-Stream
  format (Phase 2 introduces FIX 4.4).
- No active/standby failover — single FPGA, single book (Phase 3).
- No policy/config plane — registers are written directly by the host
  (Phase 4).
- No persistent audit storage — chain head lives on the FPGA only;
  off-chip persistence lands in Phase 5.
- No per-symbol position slicing — see AM-01.
- No second wire protocol (ITCH/OUCH) — Phase 16+ backlog.

Each of these has a corresponding open phase in `roadmap/STATUS.md`.

---

## 9. Source-of-truth ownership

| Artifact                              | Owner                       |
|---------------------------------------|-----------------------------|
| Reject codes / order_t / config types | `rtl/risk_pkg.sv`           |
| Behavioural decision spec             | `sentinel_hft/golden/risk_gate.py` |
| Register map                          | `fpga/regmap.yaml`          |
| Reject precedence                     | This file (§3)              |
| AXI-Stream contract                   | This file (§6)              |
| Spec→RTL→test traceability            | `docs/fpga/TRACEABILITY.md` |

Any disagreement between two of these is, by definition, a bug.
V-Contract + V-Floor + V-Meta exist precisely to detect such disagreements.
