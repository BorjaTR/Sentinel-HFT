# Sentinel-HFT

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-2.2.0-green.svg)](https://github.com/BorjaTR/Sentinel-HFT)

**FPGA observability and risk-evidence appliance for crypto HFT.**

Sentinel-HFT is a tick-to-trade pipeline in RTL + Python that wraps a
co-located FPGA trading core with (a) cycle-accurate latency
attribution, (b) a host-hashed audit trail over every risk-gate
decision (on-chip serialiser + off-chip BLAKE2b chain; see
§"FPGA target" and the core-audit report for the full scope), and
(c) a local-only AI root-cause explainer. It is shaped for firms
running market-making on Deribit LD4, Hyperliquid, and Solana
block builders where nanosecond attribution pays and DORA requires
you to prove it later.

## Four heroes

1. **Deribit LD4 tick-to-trade demo** (`sentinel-hft deribit demo`) — a
   deterministic 20k-tick run across BTC/ETH perps and options that
   produces the four artifacts a regulator or an interviewer can diff
   against a reference: a v1.2 trace (64-byte records with per-stage
   attribution), a hash-chained audit log, a DORA bundle, and a
   markdown summary.
2. **Host-hashed risk audit trail** — the on-chip `risk_audit_log` is
   an ordered, monotonically-sequenced serialiser of every risk
   decision with an in-band `REC_OVERFLOW` marker on FIFO full; the
   host then BLAKE2b-chains the stream off-chip, so any insert,
   delete, or reorder breaks the chain (Wave 1 "Option A" from the
   core audit; a synthesisable in-fabric BLAKE2b core is a planned
   post-v1.0.0 item). The verifier produces a DORA-shaped bundle
   suitable for an incident report.
3. **Local-only AI RCA** — root-cause analysis that never ships trace
   content off-host. Ships as a rule-based explainer with optional
   local LLM hook; no Anthropic / OpenAI API key required.
4. **Hyperliquid use-case suite** (`sentinel-hft hl …`) — four
   end-to-end demonstrations on top of the shared pipeline, each
   answering a specific operational question and each emitting a
   self-contained HTML report (inline SVG, no external JS, opens
   offline):
   (a) toxic-flow rejection, (b) volatility kill-switch drill with
   spike-to-latch latency, (c) wire-to-wire latency attribution by
   pipeline stage, (d) a daily three-session DORA evidence bundle.
   A `sentinel-hft hl demo` one-liner runs all four plus stitches a
   cover dashboard. Full reference in
   [`docs/USE_CASES.md`](docs/USE_CASES.md).

## FPGA target

The RTL under [`rtl/`](rtl/) is wired through
[`fpga/u55c/sentinel_u55c_top.sv`](fpga/u55c/sentinel_u55c_top.sv) to
an **AMD Alveo U55C** (`xcu55c-fsvh2892-2L-e`) at 100 MHz, with XDC
constraints, Vivado batch scripts, and a CI elaboration check. See
[`fpga/u55c/README.md`](fpga/u55c/README.md) for the build flow.

What is wired in v2.2 (post-audit Waves 0-3):

- `sentinel_shell_v12` + `risk_gate` + `risk_audit_log` on the
  100 MHz datapath clock, pblocked into SLR0 to keep tick-to-trade
  inside one super-logic region.
- A real dual-clock CMAC bridge: the 322.265625 MHz LBUS domain
  from the CMAC hard IP is crossed into the 100 MHz datapath via
  two `async_fifo` instances (RX and TX) with gray-coded pointers
  plus `reset_sync` reset synchronisers in each domain
  (Wave 2 / E-S1-02/03, replaces the earlier "CMAC clk == core
  clk" stub).
- `eth_mac_100g_shim` byte-accurate header offsets on both RX and
  TX — the Wave 2 fix (E-S1-01) closes a 6-byte silent payload
  loss on the TX first-beat slice.
- `stub_latency_core` is a simulation-only placeholder; it is
  gated by a `STUB_ONLY` elaboration check (Wave 3 / WP3.3),
  kept out of both `fpga/u55c/scripts/build.tcl` and the
  Verilator lint target in `Makefile`, and raises a
  `stub_core_detected` tripwire if it ever reaches a bitstream.

What is still a known stub or deferred work (tracked in
[`docs/INTEGRATION_READINESS.md`](docs/INTEGRATION_READINESS.md)):
the production low-latency core behind `stub_latency_core`; a
real multi-in-flight pipeline behind
`latency_attribution_probe`; an in-fabric BLAKE2b core for the
audit chain (Option B); and final PCIe / XDMA / HBM2 bring-up
glue.

## 60-second demo

```bash
pip install -e ".[all]"
sentinel-hft deribit demo -o /tmp/sentinel-demo
sentinel-hft audit verify /tmp/sentinel-demo/audit.aud
cat /tmp/sentinel-demo/summary.md
```

A run produces:

| Artifact | What it is |
|---|---|
| `traces.sst` | v1.2 binary trace, 64B/record with per-stage attribution |
| `audit.aud` | Hash-chained audit log, one record per risk-gate decision |
| `dora.json` | DORA-aligned incident bundle (schema `dora-bundle/1`) |
| `summary.md` | Human-readable run summary with latency quantiles |

A full walkthrough lives in [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md)
and the Hyperliquid use-case suite (four operational drills +
dashboard) is documented in [`docs/USE_CASES.md`](docs/USE_CASES.md).
The market-fit framing is in
[`docs/keyrock-2pager.md`](docs/keyrock-2pager.md) and the
architecture overview (with diagram) is in
[`docs/architecture.md`](docs/architecture.md). The honest punch
list of what's in-tree vs. what an integrator still has to add
before this goes on a real Alveo U55C is in
[`docs/INTEGRATION_READINESS.md`](docs/INTEGRATION_READINESS.md).

---

## Who is this for

Crypto HFT firms running an FPGA tick-to-trade path that need to
prove to regulators, auditors, or a risk committee that every order
passed a deterministic check and that the latency distribution is
under control. Secondary: MEV searchers and L2 sequencer teams who
want the same attribution framework for on-chain paths. The features
below are the detailed reference for each of those audiences.

---

## Table of Contents

- [Features](#features)
- [Performance](#performance)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Core Features](#core-features)
  - [Trace Analysis](#1-trace-analysis)
  - [Latency Attribution](#2-latency-attribution-v12)
  - [Fault Injection](#3-fault-injection-testing)
  - [Risk Controls](#4-risk-controls)
  - [AI Explanations](#5-ai-powered-explanations)
- [Integration](#integration)
  - [CLI](#command-line-interface)
  - [Python API](#python-api)
  - [REST API](#rest-api)
  - [Prometheus & Grafana](#prometheus--grafana)
  - [GitHub Actions](#github-actions)
  - [Slack Alerts](#slack-alerts)
- [Configuration](#configuration)
- [Trace Formats](#trace-formats)
- [Architecture](#architecture)
- [Development](#development)
- [License](#license)

---

## Features

| Feature | Description |
|---------|-------------|
| **Cycle-accurate instrumentation** | Non-invasive RTL wrapper captures every transaction with nanosecond precision |
| **Latency attribution** | v1.2 format breaks down latency by pipeline stage (ingress/core/risk/egress) |
| **Streaming analysis** | Process millions of traces with O(1) memory using quantile estimation |
| **Fault injection** | 8 fault types with built-in scenarios for resilience testing |
| **Risk controls** | Hardware rate limiter, position limits, and kill switch |
| **AI explanations** | Natural language root cause analysis using Claude |
| **Real-time monitoring** | HTTP server with Prometheus metrics and Grafana dashboards |
| **CI/CD integration** | GitHub Actions, regression testing, and automated alerts |

---

## Performance

| Metric | Value | Notes |
|--------|-------|-------|
| **Throughput** | 284,000 traces/sec | Single-threaded Python analysis |
| **Memory** | O(1) constant | P² quantile estimation algorithm |
| **Quantile accuracy** | ±0.5% | At P99 with 10K+ samples |
| **Latency overhead** | <1 cycle | RTL instrumentation wrapper |
| **Startup time** | <100ms | CLI cold start |

**Benchmarks (10M traces, 100 MHz clock):**
```
Analysis time:     35.2s
Memory usage:      48 MB (constant)
P99 accuracy:      ±0.3% vs exact
Records dropped:   0
```

---

## Quick Start

```bash
# Install
pip install -e ".[all]"

# Run interactive demo
sentinel-hft demo

# Check installed features
sentinel-hft version -v

# Analyze trace file
sentinel-hft analyze traces.bin -o report.json

# Start monitoring server
docker-compose up -d sentinel-server prometheus grafana
# Open http://localhost:3000 (admin/sentinel)
```

---

## Installation

### From Source

```bash
git clone https://github.com/BorjaTR/Sentinel-HFT
cd Sentinel-HFT

# Core installation
pip install -e .

# With all optional features
pip install -e ".[all]"

# Or install specific extras
pip install -e ".[server]"      # FastAPI server
pip install -e ".[prometheus]"  # Prometheus metrics
pip install -e ".[ai]"          # Claude AI explanations
pip install -e ".[dev]"         # Development tools
```

### Docker

```bash
# Build image
docker build -t sentinel-hft .

# Run demo
docker run sentinel-hft demo

# Run full monitoring stack
docker-compose up -d
```

### Optional Dependencies

| Extra | Packages | Purpose |
|-------|----------|---------|
| `server` | fastapi, uvicorn | HTTP API server |
| `prometheus` | prometheus-client | Metrics export |
| `ai` | anthropic | AI-powered explanations |
| `slack` | requests | Slack notifications |
| `dev` | pytest, black, ruff | Development tools |
| `all` | Everything above | Full installation |

---

## Core Features

### 1. Trace Analysis

Analyze FPGA trace files with streaming quantile estimation for P50/P90/P99/P99.9 latency metrics.

```bash
# Basic analysis
sentinel-hft analyze traces.bin -o report.json

# With table output
sentinel-hft analyze traces.bin --format table

# Quiet mode for CI
sentinel-hft analyze traces.bin -q -o report.json
```

**Python API:**

```python
from sentinel_hft.formats.reader import TraceReader
from sentinel_hft.streaming.analyzer import StreamingMetrics, StreamingConfig

# Configure analysis
config = StreamingConfig(clock_hz=100_000_000)  # 100 MHz
metrics = StreamingMetrics(config)

# Process traces
for trace in TraceReader.read_path("traces.bin"):
    metrics.add(trace)

# Get results
snapshot = metrics.snapshot()
print(f"P99: {snapshot['latency']['p99_cycles']} cycles")
print(f"Drops: {snapshot['drops']['total_dropped']}")
```

---

### 2. Latency Attribution (v1.2)

The v1.2 trace format (64 bytes) includes per-stage timing breakdown:

| Stage | Description |
|-------|-------------|
| **ingress** | Time in ingress handling/parsing |
| **core** | Time in core business logic |
| **risk** | Time in risk gate checks |
| **egress** | Time in egress serialization |
| **overhead** | Queueing delays between stages |

```bash
# Demo with attribution
sentinel-hft demo
```

**Python API:**

```python
from sentinel_hft.adapters.sentinel_adapter_v12 import SentinelV12Adapter
from sentinel_hft.streaming.attribution import AttributionTracker

adapter = SentinelV12Adapter(clock_mhz=100.0)
tracker = AttributionTracker()

for trace, attribution in adapter.iterate_with_attribution("traces_v12.bin"):
    tracker.update(attribution)

    # Per-trace breakdown
    print(f"Total: {attribution.total_ns:.0f}ns")
    print(f"  Ingress: {attribution.ingress_ns:.0f}ns ({attribution.ingress_pct:.1%})")
    print(f"  Core:    {attribution.core_ns:.0f}ns ({attribution.core_pct:.1%})")
    print(f"  Risk:    {attribution.risk_ns:.0f}ns ({attribution.risk_pct:.1%})")
    print(f"  Egress:  {attribution.egress_ns:.0f}ns ({attribution.egress_pct:.1%})")
    print(f"  Bottleneck: {attribution.bottleneck}")

# Aggregate metrics
metrics = tracker.get_metrics()
print(f"\nOverall bottleneck: {metrics.bottleneck} ({metrics.bottleneck_pct:.1%})")
```

---

### 3. Fault Injection Testing

Test system resilience with 8 configurable fault types:

| Fault Type | Description |
|------------|-------------|
| `BACKPRESSURE` | Simulate downstream backpressure |
| `FIFO_OVERFLOW` | Force FIFO overflow conditions |
| `KILL_SWITCH` | Trigger emergency stop |
| `CORRUPT_DATA` | Inject data corruption |
| `CLOCK_STRETCH` | Add clock cycle delays |
| `BURST` | Generate traffic bursts |
| `REORDER` | Reorder transactions |
| `RESET` | Inject reset signals |

**Built-in Scenarios:**

```python
from sentinel_hft.testing import list_scenarios, get_scenario, FaultInjector

# List available scenarios
print(list_scenarios())
# ['backpressure_storm', 'fifo_overflow', 'kill_switch_trigger',
#  'cascading_failure', 'reorder_burst', 'reset_mid_stream']

# Run a scenario
scenario = get_scenario("backpressure_storm")
injector = FaultInjector()

for fault in scenario.faults:
    injector.inject(fault)
    # ... run test ...
    injector.clear(fault.fault_type)
```

**Custom Scenarios:**

```python
from sentinel_hft.testing import FaultConfig, FaultScenario, FaultType

custom = FaultScenario(
    name="stress_test",
    description="Combined stress test",
    faults=[
        FaultConfig(
            fault_type=FaultType.BACKPRESSURE,
            duration_cycles=1000,
            probability=0.3,
        ),
        FaultConfig(
            fault_type=FaultType.BURST,
            intensity=0.8,
            pattern="periodic",
        ),
    ]
)
```

---

### 4. Risk Controls

Hardware-enforced risk controls in RTL:

| Control | Description | Configuration |
|---------|-------------|---------------|
| **Rate Limiter** | Token bucket rate limiting | `max_tokens`, `refill_rate` |
| **Position Limiter** | Per-symbol position limits | `max_position`, `symbol_count` |
| **Kill Switch** | Emergency stop on breach | `auto_trigger`, `manual_reset` |

```systemverilog
// RTL instantiation
risk_gate #(
    .MAX_TOKENS(100),
    .REFILL_RATE(10),
    .MAX_POSITION(1000000)
) u_risk (
    .clk(clk),
    .rst_n(rst_n),
    .tx_valid(tx_valid),
    .tx_data(tx_data),
    .tx_ready(tx_ready),
    .kill_switch(kill_switch)
);
```

---

### 5. AI-Powered Explanations

Get natural language analysis of latency patterns using Claude:

```bash
export ANTHROPIC_API_KEY=your_key
sentinel-hft analyze traces.bin --explain
```

**Python API:**

```python
from sentinel_hft.ai.attribution_explainer import AttributionExplainer

explainer = AttributionExplainer()

# Explain attribution breakdown
explanation = explainer.explain_attribution(metrics)
print(explanation)

# Example output:
# "Core processing is the primary bottleneck at 65% of total latency.
#  The P99 core latency of 450ns suggests complex order matching logic.
#  Consider: 1) Pipelining the matching engine, 2) Caching frequent lookups..."
```

---

## Integration

### Command-Line Interface

```bash
# Analyze traces
sentinel-hft analyze <trace_file> [OPTIONS]
  -o, --output PATH      Output file
  -f, --format [json|table]
  -c, --config PATH      Config file
  --evidence             Include evidence bundle
  -q, --quiet            Suppress output

# Regression testing
sentinel-hft regression <current> <baseline> [OPTIONS]
  --max-p99-regression FLOAT  Max allowed P99 regression %
  --fail-on-drops            Fail if drops detected

# Live monitoring
sentinel-hft live [OPTIONS]
  --udp-port INT         UDP port for traces
  --prometheus-port INT  Prometheus metrics port
  -c, --config PATH      Config file

# Configuration
sentinel-hft config init              # Print default config
sentinel-hft config validate <path>   # Validate config file
sentinel-hft config dump [path]       # Dump current config

# Demo & Info
sentinel-hft demo [-o PATH]           # Run interactive demo
sentinel-hft version [-v]             # Show version info
```

---

### Python API

```python
# Full analysis pipeline
from sentinel_hft.config import load_config
from sentinel_hft.formats.reader import TraceReader
from sentinel_hft.streaming.analyzer import StreamingMetrics, StreamingConfig
from sentinel_hft.core.report import AnalysisReport

# Load configuration
config = load_config("sentinel.yaml")

# Setup streaming analysis
streaming_config = StreamingConfig(clock_hz=config.clock.frequency_hz)
metrics = StreamingMetrics(streaming_config)

# Process traces
trace_info = TraceReader.open("traces.bin")
for trace in TraceReader.read(trace_info):
    metrics.add(trace)

# Generate report
report = AnalysisReport(
    source_file="traces.bin",
    clock_frequency_mhz=config.clock.frequency_mhz,
)
snapshot = metrics.snapshot()
# ... populate report from snapshot ...
report.compute_status(
    p99_warning=config.thresholds.p99_warning,
    p99_error=config.thresholds.p99_error,
)

# Export
print(report.to_json())
print(report.to_markdown())
```

---

### REST API

Start the server:

```bash
# Direct
pip install sentinel-hft[server]
uvicorn sentinel_hft.server.app:app --host 0.0.0.0 --port 8000

# Docker
docker-compose up -d sentinel-server
```

**Endpoints:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/analyze` | Analyze uploaded trace file |
| GET | `/metrics` | Prometheus metrics |

**Examples:**

```bash
# Health check
curl http://localhost:8000/health

# Analyze trace file
curl -X POST http://localhost:8000/analyze \
  -F "file=@traces.bin" \
  -F "clock_mhz=100"

# Get Prometheus metrics
curl http://localhost:8000/metrics
```

---

### Prometheus & Grafana

Start the monitoring stack:

```bash
docker-compose up -d sentinel-server prometheus grafana
```

**Access:**

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | http://localhost:3000 | admin / sentinel |
| Prometheus | http://localhost:9090 | - |
| Sentinel API | http://localhost:8000 | - |

**Available Metrics:**

| Metric | Type | Description |
|--------|------|-------------|
| `sentinel_latency_p50_ns` | Gauge | P50 latency in nanoseconds |
| `sentinel_latency_p99_ns` | Gauge | P99 latency in nanoseconds |
| `sentinel_records_total` | Counter | Total records processed |
| `sentinel_sequence_gaps_total` | Counter | Sequence gaps detected |
| `sentinel_attribution_pct{stage}` | Gauge | Attribution percentage per stage |
| `sentinel_bottleneck_stage` | Gauge | Current bottleneck stage |

**Grafana Dashboard:**

The pre-configured dashboard includes:
- Latency percentiles over time (P50/P90/P99)
- Latency attribution pie chart
- Stage breakdown stacked timeseries
- Sequence gap alerts
- Bottleneck detection

---

### GitHub Actions

```yaml
name: Latency Regression

on:
  pull_request:
    branches: [main]

jobs:
  regression:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install Sentinel-HFT
        run: pip install -e .

      - name: Run analysis
        run: |
          sentinel-hft analyze tests/fixtures/traces.bin \
            -o current_metrics.json -q

      - name: Check regression
        run: |
          sentinel-hft regression \
            current_metrics.json \
            baseline_metrics.json \
            --max-p99-regression 10
```

---

### Slack Alerts

Configure in `sentinel.yaml`:

```yaml
slack:
  enabled: true
  webhook_url: ${SLACK_WEBHOOK_URL}
  channel: "#hft-alerts"

alerts:
  p99_threshold_ns: 1000000  # 1ms
  gap_threshold: 10
```

**Python API:**

```python
from sentinel_hft.exporters.slack import SlackExporter

slack = SlackExporter(
    webhook_url=os.environ["SLACK_WEBHOOK_URL"],
    channel="#hft-alerts"
)

# Send alert
slack.send_alert(
    title="P99 Latency Spike",
    message=f"P99 latency increased to {p99_ns}ns",
    severity="warning"
)

# Send report
slack.send_report(report)
```

---

## Configuration

Create `sentinel.yaml`:

```yaml
# Clock configuration
clock:
  frequency_mhz: 100.0  # FPGA clock frequency

# Analysis settings
analysis:
  percentiles: [50, 75, 90, 95, 99, 99.9]
  window_seconds: 60
  gap_threshold: 100

# Thresholds (in cycles)
thresholds:
  p99_warning: 100
  p99_error: 500
  p99_critical: 1000

# Prometheus export
prometheus:
  enabled: true
  port: 9090
  path: /metrics

# Slack notifications
slack:
  enabled: false
  webhook_url: ${SLACK_WEBHOOK_URL}
  channel: "#hft-alerts"

# AI explanations
ai:
  enabled: true
  model: claude-sonnet-4-20250514
  max_tokens: 1024
```

**Environment Variable Substitution:**

Use `${VAR_NAME}` syntax for secrets:

```yaml
slack:
  webhook_url: ${SLACK_WEBHOOK_URL}
ai:
  api_key: ${ANTHROPIC_API_KEY}
```

---

## Trace Formats

### v1.0 (Legacy) - 32 bytes

```
| Field     | Offset | Size | Description          |
|-----------|--------|------|----------------------|
| t_ingress | 0      | 8B   | Ingress timestamp    |
| t_egress  | 8      | 8B   | Egress timestamp     |
| data      | 16     | 8B   | Transaction data     |
| flags     | 24     | 2B   | Status flags         |
| tx_id     | 26     | 2B   | Transaction ID       |
| padding   | 28     | 4B   | Reserved             |
```

### v1.1 (Standard) - 48 bytes

```
| Field     | Offset | Size | Description          |
|-----------|--------|------|----------------------|
| version   | 0      | 1B   | Format version (1)   |
| type      | 1      | 1B   | Record type          |
| core_id   | 2      | 2B   | Source core ID       |
| seq_no    | 4      | 4B   | Sequence number      |
| t_ingress | 8      | 8B   | Ingress timestamp    |
| t_egress  | 16     | 8B   | Egress timestamp     |
| data      | 24     | 8B   | Transaction data     |
| flags     | 32     | 2B   | Status flags         |
| tx_id     | 34     | 2B   | Transaction ID       |
| reserved  | 36     | 12B  | Reserved             |
```

### v1.2 (Attribution) - 64 bytes

```
| Field     | Offset | Size | Description          |
|-----------|--------|------|----------------------|
| version   | 0      | 1B   | Format version (2)   |
| type      | 1      | 1B   | Record type          |
| core_id   | 2      | 2B   | Source core ID       |
| seq_no    | 4      | 4B   | Sequence number      |
| t_ingress | 8      | 8B   | Ingress timestamp    |
| t_egress  | 16     | 8B   | Egress timestamp     |
| t_host    | 24     | 8B   | Host timestamp       |
| tx_id     | 32     | 2B   | Transaction ID       |
| flags     | 34     | 2B   | Status flags         |
| reserved  | 36     | 12B  | Reserved             |
| d_ingress | 48     | 4B   | Ingress cycles       |
| d_core    | 52     | 4B   | Core cycles          |
| d_risk    | 56     | 4B   | Risk gate cycles     |
| d_egress  | 60     | 4B   | Egress cycles        |
```

### File Header - 32 bytes

All trace files start with a header:

```
| Field       | Offset | Size | Description        |
|-------------|--------|------|--------------------|
| magic       | 0      | 4B   | "SNTL" (0x4C544E53)|
| version     | 4      | 2B   | Header version     |
| record_size | 6      | 2B   | Record size (32/48/64) |
| flags       | 8      | 4B   | File flags         |
| clock_mhz   | 12     | 4B   | Clock frequency    |
| reserved    | 16     | 16B  | Reserved           |
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        FPGA Trading Core                         │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐     │
│  │  Ingress │──▶│   Core   │──▶│Risk Gate │──▶│  Egress  │     │
│  │  Parser  │   │  Logic   │   │          │   │Serializer│     │
│  └────┬─────┘   └────┬─────┘   └────┬─────┘   └────┬─────┘     │
│       │              │              │              │            │
│       └──────────────┴──────────────┴──────────────┘            │
│                              │                                   │
│                    ┌─────────▼─────────┐                        │
│                    │  Sentinel Shell   │                        │
│                    │  (Instrumentation)│                        │
│                    └─────────┬─────────┘                        │
└──────────────────────────────┼──────────────────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │   Trace Stream      │
                    │   (UDP / File)      │
                    └──────────┬──────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│                      Host Software                               │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐     │
│  │  Trace   │──▶│Streaming │──▶│  Report  │──▶│    AI    │     │
│  │  Decode  │   │ Metrics  │   │Generator │   │ Explainer│     │
│  └──────────┘   └──────────┘   └──────────┘   └──────────┘     │
│                      │                                          │
│         ┌────────────┴────────────┐                             │
│         ▼                         ▼                             │
│  ┌──────────────┐         ┌──────────────┐                     │
│  │  Prometheus  │         │    Slack     │                     │
│  │   Exporter   │         │   Alerts     │                     │
│  └──────────────┘         └──────────────┘                     │
└─────────────────────────────────────────────────────────────────┘
```

### Components

| Component | Location | Description |
|-----------|----------|-------------|
| Sentinel Shell | `rtl/sentinel_shell*.sv` | Non-invasive RTL instrumentation wrapper |
| Stage Timer | `rtl/stage_timer.sv` | Per-stage cycle counter |
| Risk Gate | `rtl/risk_gate.sv` | Rate limiter, position limits, kill switch |
| Fault Injector | `rtl/fault_injector.sv` | Configurable fault injection |
| Trace Decoder | `sentinel_hft/adapters/` | v1.0/v1.1/v1.2 format decoders |
| Streaming Metrics | `sentinel_hft/streaming/` | O(1) memory quantile estimation |
| Attribution Tracker | `sentinel_hft/streaming/attribution.py` | Stage-level latency tracking |
| Report Generator | `sentinel_hft/core/report.py` | JSON/YAML/Markdown reports |
| AI Explainer | `sentinel_hft/ai/` | Claude-powered analysis |
| HTTP Server | `sentinel_hft/server/` | FastAPI REST API |
| Exporters | `sentinel_hft/exporters/` | Prometheus, Slack |
| CLI | `sentinel_hft/cli/` | Command-line interface |

---

## Project Structure

```
Sentinel-HFT/
├── rtl/              # SystemVerilog RTL (instrumentation, risk, fault injection)
├── sentinel_hft/     # Python package (analysis, server, exporters, CLI)
├── monitoring/       # Prometheus + Grafana configuration
├── tests/            # Test suite (370+ tests)
├── docker-compose.yml
└── pyproject.toml
```

<details>
<summary><strong>Full directory structure</strong></summary>

```
rtl/
├── sentinel_shell.sv         # v1.1 instrumentation wrapper
├── sentinel_shell_v12.sv     # v1.2 with attribution
├── trace_pkg.sv / _v12.sv    # Trace format definitions
├── stage_timer.sv            # Cycle counter module
├── risk_gate.sv              # Rate limiter + position limits
├── fault_injector.sv         # Fault injection module
└── tb_*.sv                   # Testbenches

sentinel_hft/
├── adapters/                 # v1.0/v1.1/v1.2 decoders
├── streaming/                # Quantile estimation, attribution
├── core/                     # Report generation
├── formats/                  # File header, trace reader
├── ai/                       # Claude-powered explanations
├── testing/                  # Fault injection framework
├── server/                   # FastAPI REST API
├── exporters/                # Prometheus, Slack
└── cli/                      # Command-line interface

monitoring/
├── prometheus.yml            # Scrape config
├── prometheus_alerts.yml     # Alert rules
└── grafana/                  # Dashboards + provisioning
```

</details>

---

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Run specific test file
pytest tests/test_adapter_v12.py -v

# Code formatting
black sentinel_hft/ tests/
ruff check sentinel_hft/ tests/

# Build RTL simulation (requires Verilator)
make build

# Run RTL tests
make test-rtl

# Run demo
sentinel-hft demo
```

### Adding a New Fault Type

1. Add to `rtl/fault_pkg.sv`:
```systemverilog
typedef enum logic [3:0] {
    // ... existing types ...
    FAULT_NEW_TYPE = 4'h9
} fault_type_t;
```

2. Add to `sentinel_hft/testing/fault_injection.py`:
```python
class FaultType(str, Enum):
    # ... existing types ...
    NEW_TYPE = "new_type"
```

3. Update `rtl/fault_injector.sv` with injection logic.

### Adding a New Metric

1. Add to `sentinel_hft/streaming/analyzer.py`
2. Update `sentinel_hft/exporters/prometheus.py`
3. Add to Grafana dashboard in `monitoring/grafana/dashboards/`

---

## License

MIT

---

## Contributing

Contributions welcome! Please read the documentation first.

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing`
3. Make your changes
4. Run tests: `pytest tests/ -v`
5. Submit a pull request

---

## Support

- **Issues**: [GitHub Issues](https://github.com/BorjaTR/Sentinel-HFT/issues)
- **Documentation**: [Wiki](https://github.com/BorjaTR/Sentinel-HFT/wiki)
