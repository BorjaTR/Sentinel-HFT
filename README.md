# Sentinel-HFT

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Hardware execution observability for crypto trading infrastructure.**

Sentinel-HFT wraps your FPGA trading cores with instrumentation, captures cycle-accurate traces, enforces risk controls, and generates AI-powered latency analysis reports.

## Features

- **Cycle-accurate instrumentation** - Non-invasive RTL wrapper captures every transaction
- **Latency analysis** - P50/P95/P99/P99.9 distributions with anomaly detection
- **Risk controls** - Rate limiter, position limits, kill switch in hardware
- **AI explanations** - Natural language root cause analysis using Claude
- **Protocol context** - Integrate DeFi protocol health data for unified risk assessment

## Quick Start

```bash
# Install
pip install -e .

# Run demo
sentinel-hft demo

# Analyze your data
sentinel-hft replay market_data.csv -o report.json

# With AI explanation
export ANTHROPIC_API_KEY=your_key
sentinel-hft analyze traces.bin --explain --protocol arbitrum
```

## Installation

### From Source

```bash
git clone https://github.com/BorjaTR/Sentinel-HFT
cd Sentinel-HFT
pip install -e ".[dev]"

# Build simulations (requires Verilator)
make build
```

### Docker

```bash
docker build -t sentinel-hft .
docker run sentinel-hft demo
```

## Usage

### Replay Market Data

```bash
sentinel-hft replay market_data.csv \
    --output report.json \
    --latency 2
```

### Analyze Traces

```bash
sentinel-hft analyze traces.bin \
    --explain \
    --protocol arbitrum \
    --format markdown
```

### Validate Traces

```bash
sentinel-hft validate traces.bin --strict
```

## Architecture

```
Input -> [Sentinel Shell + Risk Gate + Core] -> Output
                      |
                 Trace Stream
                      |
         [Decode] -> [Metrics] -> [AI Explainer] -> Report
```

### Components

| Component | Description |
|-----------|-------------|
| Sentinel Shell | Non-invasive RTL instrumentation wrapper |
| Risk Gate | Rate limiter, position limits, kill switch |
| Wind Tunnel | Replay harness and metrics pipeline |
| AI Explainer | Pattern detection and LLM-powered explanations |
| Protocol Context | DeFi protocol health integration |

## Project Status

- [x] **H1: Instrumentation Shell** - RTL wrapper + traces + tests
- [x] **H2: Replay Harness** - Python replay + metrics pipeline
- [x] **H3: Risk Controls** - Rate limiter, position limits, kill switch
- [x] **H4: AI Explainer** - Natural language latency reports
- [x] **H5: Protocol Context** - Integrate protocol health analysis
- [x] **H6: Packaging** - CLI, Docker, documentation

## Example Output

```markdown
# Sentinel-HFT Analysis Report

## Executive Summary

Trading system healthy on Arbitrum (A-tier, 48mo runway).
P99 latency: 3 cycles (30ns). One rate limit burst detected.

## Key Findings

- Median latency stable at 2 cycles (20ns)
- Rate limit burst at cycle 45,000 (12 rejections)
- No position limit breaches
- Kill switch not triggered

## Recommendations

- Increase max_tokens from 10 to 25 for burst absorption
- Current risk limits are appropriate
```

## Project Structure

```
Sentinel-HFT/
├── rtl/                 # SystemVerilog RTL
│   ├── sentinel_shell.sv    # Instrumentation wrapper
│   ├── risk_gate.sv         # Risk control module
│   ├── rate_limiter.sv      # Token bucket rate limiter
│   ├── position_tracker.sv  # Position limit tracking
│   └── kill_switch.sv       # Emergency stop
├── host/                # Python host utilities
│   ├── metrics.py           # Metrics computation
│   ├── report.py            # Report generation
│   └── trace_decode.py      # Trace decoding
├── ai/                  # AI analysis
│   ├── pattern_detector.py  # Latency pattern detection
│   ├── explainer.py         # LLM explanation generator
│   └── report_generator.py  # AI-enhanced reports
├── protocol/            # Protocol integration
│   ├── context.py           # Protocol context provider
│   ├── health.py            # Health integration
│   └── risk_correlation.py  # Risk correlation
├── wind_tunnel/         # Replay infrastructure
│   ├── replay.py            # Replay runner
│   └── pipeline.py          # Trace pipeline
├── cli/                 # Command-line interface
│   └── main.py              # CLI entry point
├── sim/                 # Verilator simulation
│   └── Makefile             # Build configuration
├── tests/               # Test suite
└── demo/                # Demo data
```

## Documentation

- [Installation Guide](docs/INSTALL.md)
- [CLI Reference](docs/USAGE.md)
- [Architecture](docs/ARCHITECTURE.md)

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
make test

# Lint
make lint

# Build simulation
make build
```

## Key Commands

```bash
# Build RTL simulation
make build

# Run all tests
make test

# Run Python tests only
make test-python

# Run RTL tests only
make test-rtl

# Run demo
make demo

# Clean build artifacts
make clean
```

## Trace Record Format

Each trace record is 22 bytes:

| Field | Size | Description |
|-------|------|-------------|
| tx_id | 4B | Transaction ID |
| t_ingress | 8B | Ingress cycle |
| t_egress | 8B | Egress cycle |
| flags | 2B | Status flags |

## Who Is This For?

- **Crypto HFT firms** - Debug and optimize FPGA execution paths
- **MEV searchers** - Understand latency in transaction ordering
- **L2 sequencers** - Analyze sequencer performance
- **FPGA engineers** - Verify RTL timing behavior

## License

MIT

## Contributing

Contributions welcome! Please read the documentation first, then open issues or PRs.

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests: `make test`
5. Submit a pull request
