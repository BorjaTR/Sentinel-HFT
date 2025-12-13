# H1: Instrumentation Shell

This document describes the Phase H1 implementation of Sentinel-HFT: the instrumentation shell that wraps streaming RTL cores and emits cycle-accurate trace records.

## Overview

The Sentinel Shell is a non-invasive instrumentation wrapper for streaming RTL cores. It:

1. **Passes through all data** without modifying functional behavior
2. **Records cycle-accurate timestamps** for every transaction
3. **Emits trace records** that capture the full journey of each transaction
4. **Handles overflow gracefully** without blocking the data pipeline

## Architecture

```
Input Stream                                              Output Stream
    │                                                         ▲
    ▼                                                         │
┌─────────────────────────────────────────────────────────────────────────┐
│                         SENTINEL SHELL                                   │
│                                                                          │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐               │
│  │   Ingress   │     │   Wrapped   │     │   Egress    │               │
│  │  Timestamp  │────▶│    Core     │────▶│  Timestamp  │               │
│  │  Capture    │     │             │     │  Capture    │               │
│  └─────────────┘     └─────────────┘     └─────────────┘               │
│         │                                       │                        │
│         ▼                                       ▼                        │
│  ┌─────────────┐                         ┌─────────────┐               │
│  │  Inflight   │                         │   Trace     │               │
│  │    FIFO     │────────────────────────▶│   Record    │               │
│  └─────────────┘                         │  Generator  │               │
│                                          └─────────────┘               │
│                                                 │                        │
│                                                 ▼                        │
│                                          ┌─────────────┐               │
│                                          │   Trace     │──────▶ Trace   │
│                                          │    FIFO     │        Output  │
│                                          └─────────────┘               │
└─────────────────────────────────────────────────────────────────────────┘
```

## RTL Modules

### trace_pkg.sv

Package containing type definitions and constants:

- `trace_record_t` - 256-bit packed struct for trace records
- `inflight_entry_t` - Entry stored between ingress and egress
- `trace_flags_e` - Flag bit definitions for error conditions

### sync_fifo.sv

Generic synchronous FIFO with:

- Configurable width and depth
- Full/empty status
- Fill count output
- Simultaneous read/write support

### sentinel_shell.sv

The main instrumentation wrapper with ports:

| Category | Signals |
|----------|---------|
| Clock/Reset | `clk`, `rst_n` |
| Input Stream | `in_valid`, `in_ready`, `in_data`, `in_opcode`, `in_meta` |
| Output Stream | `out_valid`, `out_ready`, `out_data` |
| Core Interface | `core_in_*`, `core_out_*`, `core_error` |
| Trace Output | `trace_valid`, `trace_ready`, `trace_data` |
| Counters | `cycle_counter`, `trace_drop_count`, `*_backpressure_cycles`, etc. |

### stub_latency_core.sv

Configurable test core for verification:

- `LATENCY=0`: Combinational pass-through
- `LATENCY=N`: N-cycle pipeline with backpressure support

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `DATA_WIDTH` | 64 | Transaction data width |
| `TX_ID_WIDTH` | 64 | Transaction ID width |
| `CYCLE_WIDTH` | 64 | Cycle counter width |
| `OPCODE_WIDTH` | 16 | Opcode field width |
| `META_WIDTH` | 32 | Metadata field width |
| `INFLIGHT_DEPTH` | 16 | Max in-flight transactions |
| `TRACE_FIFO_DEPTH` | 64 | Trace buffer depth |

## Trace Record Format

Each trace record is 256 bits (32 bytes):

| Field | Bits | Description |
|-------|------|-------------|
| `tx_id` | 64 | Transaction ID (monotonic) |
| `t_ingress` | 64 | Cycle when transaction entered |
| `t_egress` | 64 | Cycle when transaction exited |
| `flags` | 16 | Status flags |
| `opcode` | 16 | Operation code |
| `meta` | 32 | User metadata |

### Flags

| Flag | Value | Meaning |
|------|-------|---------|
| `FLAG_NONE` | 0x0000 | No flags set |
| `FLAG_TRACE_DROPPED` | 0x0001 | Trace was dropped (unused) |
| `FLAG_CORE_ERROR` | 0x0002 | Core reported error |
| `FLAG_INFLIGHT_UNDER` | 0x0004 | Egress without matching ingress |

## Key Guarantees

### 1. Non-Invasive Pass-Through

The shell never modifies the timing of the wrapped core:

```systemverilog
assign core_in_valid  = in_valid;
assign in_ready       = core_in_ready;
assign core_in_data   = in_data;

assign out_valid      = core_out_valid;
assign core_out_ready = out_ready;
assign out_data       = core_out_data;
```

### 2. Graceful Overflow

When the trace FIFO is full:
- Traces are dropped (counted in `trace_drop_count`)
- The data pipeline continues unaffected
- `trace_overflow_seen` flag is set

### 3. Deterministic Replay

For the same input stream and ready/valid behavior:
- Trace output is bit-identical across runs
- SHA256 hash of trace files will match

## Host Tools

### trace_decode.py

Decodes binary trace files to JSONL:

```bash
python host/trace_decode.py trace.bin > traces.jsonl
```

Output format:
```json
{"tx_id": 0, "t_ingress": 1, "t_egress": 2, "latency_cycles": 1, "flags": 0, "opcode": 0, "meta": 0}
```

### metrics.py

Computes latency statistics from traces:

```bash
python host/metrics.py traces.jsonl
```

Output includes:
- count, min, max, mean
- p50, p95, p99, p99.9 percentiles
- Standard deviation
- Error/drop counts

## Building and Testing

### Build Simulation

```bash
make build                # Default LATENCY=1
make build-latency-7      # Build with LATENCY=7
```

### Run Tests

```bash
make test                 # All tests
make test-latency         # Latency verification
make test-determinism     # Determinism verification
make test-backpressure    # Backpressure counters
make test-overflow        # Overflow handling
make test-equivalence     # Functional equivalence
```

### Run Simulation Manually

```bash
./sim/obj_dir/Vtb_sentinel_shell --test latency --num-tx 100
./sim/obj_dir/Vtb_sentinel_shell --test overflow --num-tx 200
./sim/obj_dir/Vtb_sentinel_shell --help
```

## Acceptance Criteria

H1 is complete when:

- [x] All RTL compiles with `verilator --lint-only`
- [x] test_h1_stub_latency passes for LATENCY=1,2,7,19
- [x] test_h1_determinism produces identical trace hashes
- [x] test_h1_backpressure counters match expected values
- [x] test_h1_overflow completes all transactions (no deadlock)
- [x] test_h1_functional_equivalence shows identical sequences
- [x] trace_decode.py produces valid JSONL
- [x] metrics.py computes correct percentiles
- [x] This documentation exists

## Known Limitations

1. **LATENCY=0 Support**: Combinational cores (LATENCY=0) have timing edge cases due to same-cycle ingress/egress. Use LATENCY >= 1 for accurate measurements.

2. **Single Clock Domain**: All modules operate in a single clock domain.

3. **Fixed Struct Sizes**: Trace record size is fixed at 256 bits. Custom sizes require modifying `trace_pkg.sv`.

## Next Steps (H2)

Phase H2 will add:
- Python replay harness to drive simulations
- Runner orchestration for test campaigns
- Integration with recorded market data
