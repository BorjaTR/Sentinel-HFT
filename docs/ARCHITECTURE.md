# Architecture

## Overview

Sentinel-HFT is a hardware execution observability platform for crypto trading infrastructure. It consists of RTL instrumentation, a replay harness, and an AI-powered analysis pipeline.

```
                    ┌─────────────────────────────────────────┐
                    │           Sentinel-HFT                   │
                    ├─────────────────────────────────────────┤
 Market Data ──────►│ Sentinel Shell ──► Risk Gate ──► Core   │──────► Output
                    │       │                  │               │
                    │       ▼                  ▼               │
                    │   Trace FIFO      Risk Metrics           │
                    └───────┼─────────────────┼───────────────┘
                            │                 │
                            ▼                 ▼
                    ┌───────────────┐  ┌──────────────┐
                    │ Trace Decode  │  │ Risk Report  │
                    └───────┬───────┘  └──────────────┘
                            │
                            ▼
                    ┌───────────────┐
                    │ Metrics Engine│
                    └───────┬───────┘
                            │
                            ▼
                    ┌───────────────┐
                    │ AI Explainer  │◄──── Protocol Context
                    └───────┬───────┘
                            │
                            ▼
                        Report
```

## Components

### 1. RTL Layer (rtl/)

**Sentinel Shell** (`sentinel_shell.sv`)
- Wraps any streaming RTL core
- Non-invasive - doesn't modify core behavior
- Captures ingress/egress timestamps
- Generates trace records

**Risk Gate** (`risk_gate.sv`)
- Token bucket rate limiter
- Position tracking with limits
- Kill switch for emergency stop
- Aggregated risk metrics

**Sub-modules:**
- `rate_limiter.sv` - Token bucket implementation
- `position_tracker.sv` - Net position tracking
- `kill_switch.sv` - Latched emergency stop
- `sync_fifo.sv` - Synchronous FIFO for traces

### 2. Host Layer (host/)

**Trace Decode** (`trace_decode.py`)
- Parses binary trace records
- Validates record integrity
- Yields structured trace objects

**Metrics Engine** (`metrics.py`)
- Computes latency statistics (min, max, mean, percentiles)
- Detects anomalies using z-score
- Identifies patterns in trace data

**Report Generator** (`report.py`)
- Generates JSON and Markdown reports
- Formats metrics for human consumption

### 3. AI Layer (ai/)

**Pattern Detector** (`pattern_detector.py`)
- Identifies latency spikes (z-score based)
- Detects bimodal distributions
- Finds rate limit bursts
- Recognizes kill switch events

**Fact Extractor** (`fact_extractor.py`)
- Converts metrics to structured facts
- Extracts protocol-relevant information
- Builds context for LLM

**Explainer** (`explainer.py`)
- Interfaces with Anthropic Claude API
- Generates natural language explanations
- Provides root cause analysis

**Report Generator** (`report_generator.py`)
- Orchestrates pattern detection + explanation
- Produces AI-enhanced reports
- Supports protocol context integration

### 4. Protocol Layer (protocol/)

**Context Provider** (`context.py`)
- Loads protocol health data
- Supports static configs and Sentinel integration
- Caches protocol context

**Health Integrator** (`health.py`)
- Combines HFT metrics with protocol health
- Computes unified risk assessment
- Generates trading recommendations

**Risk Correlator** (`risk_correlation.py`)
- Links HFT patterns with governance events
- Identifies temporal/causal correlations
- Adds protocol context to findings

### 5. Wind Tunnel (wind_tunnel/)

**Replay Runner** (`replay.py`)
- Manages Verilator simulation lifecycle
- Feeds stimulus to simulation
- Collects trace output

**Pipeline** (`pipeline.py`)
- Coordinates decode → metrics → report flow
- Validates trace integrity
- Handles streaming analysis

### 6. CLI Layer (cli/)

**Main** (`main.py`)
- Entry point for all commands
- Argument parsing and validation
- Colored output and progress indicators

## Data Flow

### Replay Flow

```
1. Load CSV/binary input
2. Convert to stimulus format
3. Start Verilator simulation
4. Feed transactions
5. Collect trace output
6. Decode binary traces
7. Compute metrics
8. Generate report
```

### Analysis Flow

```
1. Load binary trace file
2. Decode to trace objects
3. Compute latency metrics
4. [Optional] Detect patterns
5. [Optional] Generate AI explanation
6. [Optional] Add protocol context
7. Output report (JSON/Markdown/Console)
```

## Risk Control Architecture

```
                Input Valid
                    │
                    ▼
            ┌───────────────┐
            │  Rate Check   │◄─── Token Bucket
            └───────┬───────┘
                    │ Pass
                    ▼
            ┌───────────────┐
            │Position Check │◄─── Position Tracker
            └───────┬───────┘
                    │ Pass
                    ▼
            ┌───────────────┐
            │  Kill Check   │◄─── Kill Switch Latch
            └───────┬───────┘
                    │ Pass
                    ▼
                Core Input
```

Each gate can reject transactions:
- **Rate Limiter**: Rejects if tokens exhausted
- **Position Tracker**: Rejects if limit exceeded
- **Kill Switch**: Rejects all if triggered

## Protocol Integration

```
┌──────────────────────────────────────┐
│        Protocol Context              │
├──────────────────────────────────────┤
│ • Treasury health (score, tier)      │
│ • Financial runway (months)          │
│ • Governance activity                │
│ • Risk flags                         │
└───────────────┬──────────────────────┘
                │
                ▼
┌───────────────────────────────────────┐
│         Health Integrator             │
├───────────────────────────────────────┤
│ HFT Health    │  Protocol Health      │
│ • Latency     │  • Tier (A-F)         │
│ • Anomalies   │  • Runway             │
│ • Risk events │  • Governance risk    │
└───────────────┴───────────────────────┘
                │
                ▼
        Combined Risk Assessment
        + Trading Recommendation
```

## File Formats

### Trace Record (22 bytes)

```
┌────────┬────────────┬────────────┬────────┐
│ tx_id  │ t_ingress  │  t_egress  │ flags  │
│ 4B     │ 8B         │  8B        │ 2B     │
└────────┴────────────┴────────────┴────────┘
```

### Stimulus Record (24 bytes)

```
┌──────────────┬────────┬────────┬────────┐
│ timestamp_ns │  data  │ opcode │  meta  │
│ 8B           │  8B    │  4B    │  4B    │
└──────────────┴────────┴────────┴────────┘
```

## Configuration

### Protocol Configs (protocol/configs/)

```json
{
  "health": {
    "protocol_id": "arbitrum",
    "health": { "overall_score": 85, "tier": "A" },
    "financial": { "treasury_usd": 2500000000, "runway_months": 48 },
    "governance": { "active_proposals": 2, "participation_rate": 0.12 },
    "risk": { "flags": [], "level": "low" }
  }
}
```

## Testing Strategy

| Layer | Test Type | Framework |
|-------|-----------|-----------|
| RTL | C++ unit tests | Verilator |
| Host | Python unit tests | pytest |
| AI | Mock API tests | pytest |
| Integration | End-to-end | pytest + Verilator |

## Performance Considerations

- **Trace FIFO**: 256 entries, never blocks data path
- **Metrics computation**: O(n) for n traces
- **Pattern detection**: O(n log n) for sorting
- **AI API calls**: Rate limited, ~1-2 seconds
