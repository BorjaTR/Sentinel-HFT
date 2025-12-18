# Sentinel-HFT Testing Guide

Complete step-by-step guide to test all Sentinel-HFT features.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start - End-to-End Demo](#quick-start---end-to-end-demo)
3. [Individual Feature Testing](#individual-feature-testing)
   - [Basic Trace Analysis](#1-basic-trace-analysis)
   - [Regression Testing](#2-regression-testing)
   - [Pattern Detection & Prescriptions](#3-pattern-detection--prescriptions)
   - [Fix Verification](#4-fix-verification)
   - [Trace Bisect](#5-trace-bisect)
   - [Benchmark History](#6-benchmark-history)
4. [Web Dashboard Testing](#web-dashboard-testing)
5. [License System Testing](#license-system-testing)
6. [Interpreting Results](#interpreting-results)

---

## Prerequisites

### Install Dependencies

```bash
cd /home/user/Sentinel-HFT

# Install Python dependencies
pip install typer rich click pyyaml

# For web dashboard (optional)
cd sentinel-web && npm install && cd ..
```

### Verify Installation

```bash
python -m sentinel_hft.cli.main version -v
```

**Expected output:**
```
Sentinel-HFT v2.2.0

Feature                Status
Trace Analysis         + Streaming quantile estimation
Report Schema          + JSON/YAML/Markdown export
Regression Testing     + CI/CD integration
Latency Attribution    + v1.2 format (64-byte records)
Stage Breakdown        + ingress/core/risk/egress/overhead
Fault Injection        + 8 fault types
...
```

---

## Quick Start - End-to-End Demo

The fastest way to see all features in action is the end-to-end demo.

### Interactive Demo (Recommended for First Time)

```bash
python -m sentinel_hft.cli.main demo-e2e
```

This runs a 6-step interactive demo showing the FOMC backpressure scenario:

| Step | Description | What You'll See |
|------|-------------|-----------------|
| 1 | Analyze baseline | P99 = 89ns at normal load |
| 2 | Analyze incident | P99 = 142ns during spike |
| 3 | Bisect traces | Finds exact regression point |
| 4 | Detect pattern | FIFO_BACKPRESSURE (87% confidence) |
| 5 | Generate fix | Elastic buffer RTL template |
| 6 | Verify fix | Testbench passes, P99 projected to 94ns |

**Press Enter between steps** to proceed through the demo.

### Non-Interactive Demo

```bash
python -m sentinel_hft.cli.main demo-e2e --non-interactive
```

Runs through all steps automatically without pauses.

### Demo with Custom Output Directory

```bash
python -m sentinel_hft.cli.main demo-e2e -o ./my_demo_output
```

**Interpreting Demo Results:**
- **Baseline P99 (89ns)**: Normal operating latency under 2M msg/sec
- **Incident P99 (142ns)**: 60% degradation during 8x traffic spike
- **Pattern Confidence (87%)**: High confidence indicates strong evidence
- **Fix Improvement (-34%)**: Expected P99 reduction from 142ns to 94ns

---

## Individual Feature Testing

### 1. Basic Trace Analysis

Generate demo data first:

```bash
python -m sentinel_hft.cli.main demo-setup -o ./test_data
```

This creates:
- `./test_data/traces/baseline.bin` - Normal operation traces
- `./test_data/traces/incident.bin` - Incident traces with latency spike

#### Analyze Baseline

```bash
python -m sentinel_hft.cli.main analyze ./test_data/traces/baseline.bin
```

**Expected Output:**
```
Sentinel-HFT v2.2.0
Analyzing: ./test_data/traces/baseline.bin
Clock: 100 MHz
Format: v1

{
  "source_file": "./test_data/traces/baseline.bin",
  "latency": {
    "p50_cycles": 85,
    "p99_cycles": 89,
    "p999_cycles": 95,
    "mean_cycles": 84.2
  },
  "status": "OK"
}

Summary
Metric        Value
Records       50,000
P50           85 cycles
P99           89 cycles
P99.9         95 cycles
Mean          84.20 cycles
```

**Interpreting:**
- **P99 = 89 cycles**: 99th percentile latency (good baseline)
- **P999 vs P99 ratio**: ~1.07 indicates stable tail latency
- **Status OK**: Within acceptable thresholds

#### Analyze Incident

```bash
python -m sentinel_hft.cli.main analyze ./test_data/traces/incident.bin
```

**Expected Output:**
```
{
  "latency": {
    "p99_cycles": 142,
    "p999_cycles": 185
  },
  "status": "WARNING"
}
```

**Interpreting:**
- **P99 = 142 cycles**: 60% higher than baseline
- **P999/P99 ratio**: ~1.30 indicates tail instability
- **Status WARNING**: Exceeds warning threshold

#### Output Formats

```bash
# JSON output (default)
python -m sentinel_hft.cli.main analyze ./test_data/traces/baseline.bin -f json

# Table output
python -m sentinel_hft.cli.main analyze ./test_data/traces/baseline.bin -f table

# Save to file
python -m sentinel_hft.cli.main analyze ./test_data/traces/baseline.bin -o report.json
```

---

### 2. Regression Testing

Compare current metrics against baseline to detect regressions.

#### Create Baseline and Current Reports

```bash
# Analyze baseline and save report
python -m sentinel_hft.cli.main analyze ./test_data/traces/baseline.bin -o baseline_report.json -q

# Analyze incident and save report
python -m sentinel_hft.cli.main analyze ./test_data/traces/incident.bin -o current_report.json -q
```

#### Run Regression Check

```bash
python -m sentinel_hft.cli.main regression current_report.json baseline_report.json
```

**Expected Output:**
```
REGRESSION REPORT

  P50     85ns ->    88ns  (+3.5%)    OK
  P99     89ns ->   142ns  (+59.6%)   REGRESS
  P99.9   95ns ->   185ns  (+94.7%)   REGRESS
  Drops      0    ->      0           OK

--- FAILED ---
  x P99 regression 59.6% exceeds 10.0% threshold
```

**Interpreting:**
- **Exit code 1**: Regression detected (use `echo $?` to check)
- **P99 +59.6%**: Significantly exceeds 10% default threshold
- **P99.9 +94.7%**: Tail latency even worse

#### Custom Thresholds

```bash
# Allow up to 20% P99 regression
python -m sentinel_hft.cli.main regression current_report.json baseline_report.json --max-p99-regression 20

# Fail if any drops detected
python -m sentinel_hft.cli.main regression current_report.json baseline_report.json --fail-on-drops
```

#### CI/CD Integration

```bash
# In CI pipeline
python -m sentinel_hft.cli.main regression current.json baseline.json || exit 1
```

Exit codes:
- **0**: No regression (PASSED)
- **1**: Regression detected (FAILED)

---

### 3. Pattern Detection & Prescriptions

Analyze traces to detect performance patterns and generate fixes.

```bash
python -m sentinel_hft.cli.main prescribe ./test_data/traces/incident.bin
```

**Expected Output:**
```
Analyzing: ./test_data/traces/incident.bin
Loaded 50,000 traces

Pattern Analysis
==================================================

#1 FIFO_BACKPRESSURE
   Confidence: 87% (high)
   Stage: risk

   Evidence:
     + Risk stage contributes 65% of total latency
     + High variance in risk timing (std/mean > 0.3)
     + Burst patterns detected in ingress timing

#2 ARBITER_CONTENTION
   Confidence: 42% (medium)
   Stage: core

   Evidence:
     + Core stage shows bimodal distribution
```

**Interpreting Patterns:**

| Pattern | Description | Root Cause |
|---------|-------------|------------|
| FIFO_BACKPRESSURE | FIFO buffer filling up | Downstream slower than upstream |
| ARBITER_CONTENTION | Multiple requesters competing | Shared resource bottleneck |
| MEMORY_BANDWIDTH | DDR/HBM saturation | High memory traffic |

**Confidence Levels:**
- **>70%**: High confidence - strong evidence, recommend action
- **40-70%**: Medium - investigate further
- **<40%**: Low - possible but not definitive

#### Generate Fix Pack

```bash
python -m sentinel_hft.cli.main prescribe ./test_data/traces/incident.bin --export ./fix_output
```

This generates:
```
./fix_output/
  elastic_buffer.sv          # RTL fix template
  elastic_buffer_tb.sv       # Testbench
  integration_guide.md       # Integration instructions
  fixpack_summary.json       # Fix metadata
```

**Expected Output:**
```
CANDIDATE FIX PACK

Pattern: FIFO_BACKPRESSURE
Expected Improvement: ~34%

Human review required before deployment.

Output: ./fix_output
```

---

### 4. Fix Verification

Verify a generated fix pack with testbench simulation.

```bash
python -m sentinel_hft.cli.main verify ./fix_output
```

**Expected Output:**
```
Verifying fix pack: ./fix_output

Running testbench...
  + Basic integrity: PASSED
  + Backpressure handling: PASSED
  + Burst traffic: PASSED
  + Credit flow: PASSED
  + Stress test (10,000 vectors): PASSED

+------------------------------------------+
| VERIFICATION PASSED                      |
|                                          |
| Testbench: 5/5 tests PASSED              |
|                                          |
| Latency Projection:                      |
|   Before fix: P99 = 142ns                |
|   After fix:  P99 = 94ns (projected)     |
|   Improvement: -34%                      |
|                                          |
| Budget compliance: OK - Within 100ns     |
+------------------------------------------+
```

#### Verify with Original Trace

```bash
python -m sentinel_hft.cli.main verify ./fix_output --trace ./test_data/traces/incident.bin
```

Uses actual trace metrics for more accurate projection.

---

### 5. Trace Bisect

Find exactly when a regression was introduced using binary search.

First, create multiple trace files (simulating timeline):

```bash
python -m sentinel_hft.cli.main demo-setup -o ./bisect_data
```

Then run bisect:

```bash
python -m sentinel_hft.cli.bisect ./bisect_data/timeline/
```

**Expected Output:**
```
Found 5 trace files

Baseline P99: 89ns (t1_normal.bin)

  Step 1: Testing t3_spike_start.bin... regression
  Step 2: Testing t2_normal.bin... ok

Found in 2 steps

Regression Identified
=======================================================

  Last good:  t2_normal.bin
  First bad:  t3_spike_start.bin

Impact:
  P99: 89ns -> 142ns (+59.6%)

Stage Attribution:
  +---------------------------------------------------------+
  | Stage      Before    After     Delta    Share           |
  +---------------------------------------------------------+
  | Ingress        12ns     14ns   +16.7%                   |
  | Core           25ns     28ns   +12.0%                   |
  | Risk           31ns     78ns  +151.6%  ###### <- SOURCE |
  | Egress         18ns     22ns   +22.2%                   |
  +---------------------------------------------------------+

Pattern Match:
  FIFO_BACKPRESSURE (87% confidence)

Suggested Action:
  Run 'sentinel-hft prescribe t3_spike_start.bin' for fix options
```

**Interpreting:**
- **Last good / First bad**: Exact transition point
- **Stage Attribution**: Shows which stage caused regression
- **Share column**: Percentage of total latency increase
- **<- SOURCE**: Identifies primary contributor

---

### 6. Benchmark History

Track latency over time and detect trends.

#### Record Benchmarks

```bash
# Record baseline as named benchmark
python -m sentinel_hft.cli.benchmark record ./test_data/traces/baseline.bin --name v1.0-baseline

# Record current performance
python -m sentinel_hft.cli.benchmark record ./test_data/traces/incident.bin --tag incident --tag fomc
```

#### View History

```bash
python -m sentinel_hft.cli.benchmark history
```

**Expected Output:**
```
Benchmark History (last 90 days)
=======================================================

  Current P99: 142ns
  90-day average: 115ns
  Best: 89ns
  Worst: 142ns

  Stability Score: 45/100
  Trend: degrading
  P99 increased 59% from baseline

  142 |
      |      ##
      |    ####
      |  ######
   89 +----------
       12/01   12/18

Recent snapshots:
  2024-12-18  unknown  142ns  incident, fomc
  2024-12-18  unknown   89ns  baseline, v1.0-baseline
```

**Interpreting:**
- **Stability Score**: 0-100 (higher is better)
  - >70: Stable
  - 50-70: Moderate variance
  - <50: Unstable/degrading
- **Trend**: improving/stable/degrading

#### Compare to Baseline

```bash
python -m sentinel_hft.cli.benchmark compare v1.0-baseline ./test_data/traces/incident.bin
```

---

## Web Dashboard Testing

### Start the Dashboard

```bash
cd sentinel-web
npm run dev
```

Open: http://localhost:3000

### Dashboard Features to Test

1. **Landing Page** (http://localhost:3000)
   - View feature overview
   - See live terminal demo animation

2. **Demo Page** (http://localhost:3000/demo)
   - **MetricsPanel**: Real-time latency visualization
   - **TraceTimeline**: Individual trace breakdown
   - **FaultInjector**: Inject test faults
   - **LiveFeed**: Streaming trace events

3. **API Endpoints**
   ```bash
   # Health check
   curl http://localhost:3000/api/health

   # Analyze traces (POST)
   curl -X POST http://localhost:3000/api/analyze \
     -H "Content-Type: application/json" \
     -d '{"traces": [...]}'
   ```

---

## License System Testing

### Free Tier (Default)

```bash
# No license key needed
unset SENTINEL_LICENSE_KEY
python -m sentinel_hft.cli.main analyze ./test_data/traces/baseline.bin
```

Free tier includes:
- Full trace analysis
- Regression testing with CI exit codes
- Pattern detection (preview only)
- Up to 3 prescriptions shown

### Pro Tier Testing

```bash
# Use test key (always works in development)
export SENTINEL_LICENSE_KEY="sl_test_pro_abc123def456"
python -m sentinel_hft.cli.main prescribe ./test_data/traces/incident.bin --export ./fix
```

Pro features unlocked:
- Full prescription details
- Fix download
- Testbench generation
- Slack alerts
- API access

### Team Tier Testing

```bash
export SENTINEL_LICENSE_KEY="sl_test_team_xyz789uvw012"
python -m sentinel_hft.cli.main prescribe ./test_data/traces/incident.bin
```

Team features:
- Compliance PDF export
- Custom patterns
- 5 seats

---

## Interpreting Results

### Latency Metrics Reference

| Metric | Description | Good Value | Warning | Critical |
|--------|-------------|------------|---------|----------|
| P50 | Median latency | <100ns | >150ns | >200ns |
| P99 | 99th percentile | <150ns | >200ns | >300ns |
| P99.9 | 99.9th percentile | <200ns | >300ns | >500ns |
| P99.9/P99 ratio | Tail stability | <1.5 | >2.0 | >3.0 |

### Pattern Detection Thresholds

| Pattern | Key Indicators |
|---------|----------------|
| FIFO_BACKPRESSURE | Stage >50% of total, high variance |
| ARBITER_CONTENTION | Bimodal distribution, core stage |
| MEMORY_BANDWIDTH | Consistent high latency across stages |

### CI Exit Codes

| Code | Meaning | Action |
|------|---------|--------|
| 0 | Pass | Continue deployment |
| 1 | Fail/Regression | Block deployment, investigate |
| 2 | Critical | Immediate attention required |

---

## Complete Test Script

Run all tests in sequence:

```bash
#!/bin/bash
set -e

echo "=== Sentinel-HFT Complete Test Suite ==="

# Setup
python -m sentinel_hft.cli.main demo-setup -o ./test_output

# 1. Basic Analysis
echo -e "\n[1/6] Testing basic analysis..."
python -m sentinel_hft.cli.main analyze ./test_output/traces/baseline.bin -o baseline.json -q

# 2. Regression Testing
echo -e "\n[2/6] Testing regression detection..."
python -m sentinel_hft.cli.main analyze ./test_output/traces/incident.bin -o incident.json -q
python -m sentinel_hft.cli.main regression incident.json baseline.json || true

# 3. Pattern Detection
echo -e "\n[3/6] Testing pattern detection..."
python -m sentinel_hft.cli.main prescribe ./test_output/traces/incident.bin

# 4. Fix Generation
echo -e "\n[4/6] Testing fix generation..."
python -m sentinel_hft.cli.main prescribe ./test_output/traces/incident.bin --export ./fix_test

# 5. Fix Verification
echo -e "\n[5/6] Testing fix verification..."
python -m sentinel_hft.cli.main verify ./fix_test

# 6. End-to-End Demo
echo -e "\n[6/6] Running end-to-end demo..."
python -m sentinel_hft.cli.main demo-e2e --non-interactive

echo -e "\n=== All tests completed ==="
```

Save as `run_tests.sh` and execute:

```bash
chmod +x run_tests.sh
./run_tests.sh
```

---

## Troubleshooting

### "typer and rich are required"
```bash
pip install typer rich
```

### "No traces found"
Ensure you've run `demo-setup` first to generate test data.

### Pattern confidence is low
- Increase trace count (more data = better detection)
- Check trace format compatibility

### Dashboard not starting
```bash
cd sentinel-web
npm install
npm run dev
```

---

## Next Steps

1. **Integrate with CI/CD**: Use `regression` command in pipelines
2. **Set up alerting**: Configure Slack webhooks (Pro feature)
3. **Create custom baselines**: Record benchmarks at known-good states
4. **Explore protocol analysis**: FIX/ITCH message correlation
