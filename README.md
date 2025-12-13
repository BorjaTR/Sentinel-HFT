# Sentinel-HFT

Hardware execution observability for crypto trading infrastructure.

## What Is This?

Sentinel-HFT is a **deterministic replay and latency analysis tool** for FPGA-based trading systems. It wraps your RTL cores with instrumentation, captures cycle-accurate traces, and generates reports explaining latency behavior.

Think of it as **"Datadog for FPGA trading systems"** - but deterministic, hardware-aware, and designed for the specific needs of high-frequency crypto trading.

## Features

- **Non-invasive instrumentation** - Wrap any streaming RTL core without changing its behavior
- **Cycle-accurate traces** - Know exactly when each transaction entered and exited
- **Deterministic replay** - Same input produces identical output every time
- **Graceful overflow** - Never blocks the data pipeline, drops traces cleanly
- **Comprehensive metrics** - Latency distributions, percentiles, error counts

## Quick Start

### Prerequisites

- Verilator 5.0+ (`apt install verilator`)
- Python 3.10+
- NumPy (`pip install numpy`)

### Build and Test

```bash
# Clone the repository
git clone https://github.com/you/sentinel-hft
cd sentinel-hft

# Install Python dependencies
pip install -e ".[dev]"

# Build the simulation
make build

# Run all tests
make test

# Run a quick simulation
make run
```

### Decode Traces

```bash
# Run simulation and generate traces
./sim/obj_dir/Vtb_sentinel_shell --test latency --num-tx 100 --output traces.bin

# Decode to JSON Lines
python host/trace_decode.py traces.bin > traces.jsonl

# Compute metrics
python host/metrics.py traces.jsonl
```

## Project Status

- [x] **H1: Instrumentation Shell** - RTL wrapper + traces + tests
- [ ] H2: Replay Harness - Python replay + metrics pipeline
- [ ] H3: Risk Limiter - Real HFT primitive for credibility
- [ ] H4: AI Explainer - Natural language latency reports
- [ ] H5: Protocol Context - Integrate protocol health analysis
- [ ] H6: Packaging - CLI, Docker, documentation

## Architecture

```
Input → [Sentinel Shell + Core] → Output
              ↓
         Trace Stream → [Decode] → [Metrics] → [Report]
```

The Sentinel Shell wraps your RTL core and captures:
- Transaction IDs (monotonic)
- Ingress/egress timestamps (cycle-accurate)
- Operation codes and metadata
- Error flags

## Repository Structure

```
sentinel-hft/
├── rtl/                    # SystemVerilog RTL
│   ├── trace_pkg.sv        # Trace record types
│   ├── sync_fifo.sv        # Generic FIFO
│   ├── sentinel_shell.sv   # Instrumentation wrapper
│   └── stub_latency_core.sv # Test core
├── host/                   # Python tools
│   ├── trace_decode.py     # Binary → JSONL decoder
│   └── metrics.py          # Latency statistics
├── sim/                    # Simulation
│   ├── tb_sentinel_shell.sv # Testbench wrapper
│   ├── sim_main.cpp        # C++ test driver
│   └── Makefile            # Verilator build
├── tests/                  # Pytest test suite
│   ├── test_h1_stub_latency.py
│   ├── test_h1_determinism.py
│   ├── test_h1_backpressure.py
│   ├── test_h1_overflow.py
│   └── test_h1_functional_equivalence.py
├── docs/                   # Documentation
│   └── H1_instrumentation_shell.md
├── pyproject.toml          # Python package config
├── Makefile                # Top-level build
└── README.md
```

## Key Commands

```bash
# Build with specific latency
make build-latency-7

# Run specific test suite
make test-latency
make test-determinism
make test-overflow

# Lint code
make lint

# Clean build artifacts
make clean
```

## Trace Record Format

Each trace record is 32 bytes:

| Field | Size | Description |
|-------|------|-------------|
| tx_id | 8B | Transaction ID |
| t_ingress | 8B | Ingress cycle |
| t_egress | 8B | Egress cycle |
| flags | 2B | Status flags |
| opcode | 2B | Operation code |
| meta | 4B | User metadata |

## Who Is This For?

- **Crypto HFT firms** - Debug and optimize FPGA execution paths
- **MEV searchers** - Understand latency in transaction ordering
- **L2 sequencers** - Analyze sequencer performance
- **FPGA engineers** - Verify RTL timing behavior

## Documentation

- [H1: Instrumentation Shell](docs/H1_instrumentation_shell.md) - Detailed H1 specification

## License

MIT

## Contributing

Contributions welcome! Please read the documentation first, then open issues or PRs.
