# V-Parity — RTL ≡ Golden

This directory implements the V-Parity axis from the Phase-1 pre-reg:
the RTL `risk_gate_v2` must produce byte-exact `(passed, reason)` for
every order in the V-Floor canonical corpus.

## Prerequisites

- **Verilator ≥ 4.220**, on `$PATH`. Install on Ubuntu/Debian:
  `sudo apt-get install verilator` or build from source.
- **cocotb ≥ 1.8**: `pip install cocotb`
- **Python ≥ 3.10**

The verification runner detects whether these are available and emits
SKIP if not. CI on a developer laptop with Verilator + cocotb will run
V-Parity green.

## Layout

```
verification/v_parity/
├── README.md              ← this file
├── Makefile               ← cocotb/Verilator entrypoint
├── risk_gate_v2_tb.sv     ← thin testbench wrapper (flat-port form)
├── drive_corpus.py        ← cocotb test: corpus → DUT → JSON
├── compare.py             ← golden JSON ↔ RTL JSON comparator
└── ...
```

## Running locally

```bash
# 1. Regenerate the canonical V-Floor seed if not already on disk
python -m verification.v_floor.regenerate_and_verify

# 2. Build + run the parity sim (writes RTL decisions JSON)
cd verification/v_parity
PARITY_CORPUS=../../verification/reports/v_floor/golden_seed42_n50000.json \
make sim

# 3. Compare
make compare
# or directly:
python -m verification.v_parity.compare \
    --golden ../../verification/reports/v_floor/golden_seed42_n50000.json \
    --rtl    ../../verification/reports/v_parity/rtl_seed42_n50000.json \
    --out    ../../verification/reports/v_parity/parity_seed42.json
```

Expected output on success:

```
V-Parity OK: 50000 orders, 0 diffs.
```

## What's exposed (and what isn't)

The testbench wrapper `risk_gate_v2_tb.sv` flattens the packed `order_t`
struct into primitive ports (so cocotb can address them by name) and
exposes only the decision outputs `out_rejected` and `out_reject_reason`.

Tokens-remaining, current-position, and current-notional are deliberately
**not** compared — they are derived state already covered by V-Floor and
V-Meta on the golden side. V-Parity's contract is the gate's externally-
visible decision; that's what the bitstream ships and what the audit
chain logs.

## Integration with the runner

`verification/runner.py :: _axis_v_parity` invokes the Makefile here
when both `verilator` and the `cocotb` package are present. Otherwise
it returns SKIP with a documented reason — that keeps CI green on
machines without an FPGA toolchain installed.
