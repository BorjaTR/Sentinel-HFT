# Sentinel-HFT Integration Guide

How to add Sentinel to your existing FPGA development workflow in 5 minutes.

---

## Table of Contents

1. [What This Does](#what-this-does)
2. [Quick Start](#quick-start)
3. [Integration Patterns](#integration-patterns)
4. [Configuration](#configuration)
5. [Trace Format Compatibility](#trace-format-compatibility)
6. [Interpreting Results](#interpreting-results)
7. [Common Workflows](#common-workflows)
8. [Troubleshooting](#troubleshooting)

---

## What This Does

Sentinel checks your simulation traces for latency regressions. It:

- Calculates P50/P99/P999 latency
- Compares against baseline
- Fails CI if regression detected
- Identifies which pipeline stage caused it
- Generates RTL fix templates

---

## Quick Start

### 1. Install

```bash
pip install sentinel-hft
```

### 2. Create Baseline

Run once with known-good traces:

```bash
sentinel-hft analyze path/to/golden_traces.bin -o baseline.json
```

Commit `baseline.json` to your repo.

### 3. Add to Makefile

```makefile
# Your existing simulation target
sim:
    verilator --binary -j 0 $(TOP) $(SRCS)
    ./obj_dir/V$(TOP) +trace

# Add latency check
latency-check: sim
    sentinel-hft regression build/traces.bin baseline.json

# Or as part of your test target
test: sim lint latency-check
```

### 4. Run

```bash
make test
# Exit 0 = pass
# Exit 1 = latency regression detected
```

---

## Integration Patterns

### Pattern 1: Simple CI Gate

Block PRs that regress latency.

```yaml
# .github/workflows/ci.yml
- name: Run simulation
  run: make sim

- name: Check latency
  run: sentinel-hft regression build/traces.bin baseline.json
```

**What happens:**
- PR that regresses P99 by >10% → CI fails
- PR that maintains or improves latency → CI passes

### Pattern 2: Nightly Regression Tracking

Track latency over time, alert on trends.

```bash
#!/bin/bash
# nightly_check.sh

# Run simulation
make sim

# Record today's metrics
sentinel-hft benchmark record build/traces.bin --tag "nightly-$(date +%Y%m%d)"

# Compare to baseline
sentinel-hft regression build/traces.bin baseline.json --max-p99-regression 5

# If degraded, get diagnosis
if [ $? -ne 0 ]; then
    sentinel-hft prescribe build/traces.bin > diagnosis.txt
    # Send to Slack/email
fi
```

### Pattern 3: Pre-Commit Hook

Check before committing changes to critical paths.

```bash
#!/bin/bash
# .git/hooks/pre-commit

# Only check if RTL files changed
if git diff --cached --name-only | grep -q '\.sv$'; then
    make sim-quick
    sentinel-hft regression build/traces.bin baseline.json
fi
```

### Pattern 4: Release Gate

Require explicit latency sign-off before release.

```makefile
release: test timing-closure latency-signoff
    ./package_release.sh

latency-signoff:
    @echo "Running full latency validation..."
    sentinel-hft regression build/traces.bin baseline.json --max-p99-regression 0
    sentinel-hft prescribe build/traces.bin --min-confidence 0.9
    @echo "Latency validation PASSED"
```

---

## Configuration

### Option 1: Command Line Arguments

```bash
# Allow up to 15% P99 regression
sentinel-hft regression current.bin baseline.json --max-p99-regression 15

# Fail if any drops detected
sentinel-hft regression current.bin baseline.json --fail-on-drops

# Output to file
sentinel-hft regression current.bin baseline.json -o regression_report.json
```

### Option 2: Config File

**sentinel.yaml:**

```yaml
# Clock configuration
clock:
  frequency_mhz: 100

# Baseline metrics (or path to baseline.json)
baseline:
  p99_ns: 100
  p999_ns: 150

# Thresholds
thresholds:
  p99_warning: 120
  p99_error: 150
  p99_critical: 200
  max_p99_regression_pct: 10
  max_p999_regression_pct: 15
  fail_on_drops: true

# Alert patterns (fail if detected with high confidence)
alert_patterns:
  - FIFO_BACKPRESSURE
  - CLOCK_DOMAIN_CROSSING
```

```bash
sentinel-hft regression traces.bin --config sentinel.yaml
```

### Option 3: Environment Variables

```bash
export SENTINEL_BASELINE=baseline.json
export SENTINEL_MAX_P99_REGRESSION=10
export SENTINEL_FAIL_ON_DROPS=1
export SENTINEL_LICENSE_KEY=sl_live_pro_xxxxx  # For Pro features

sentinel-hft regression traces.bin
```

---

## Trace Format Compatibility

Sentinel reads trace files in these formats:

| Format | Extension | Notes |
|--------|-----------|-------|
| Sentinel native | `.bin` | Fastest, recommended |
| VCD | `.vcd` | From Verilator/Icarus |
| FST | `.fst` | From GTKWave |
| CSV | `.csv` | Simple timestamp format |
| JSON Lines | `.jsonl` | Streaming JSON |

### Sentinel Native Format

Binary format with header:

```
MAGIC: 4 bytes ('SNTL')
VERSION: 2 bytes
RECORD_SIZE: 2 bytes
RECORD_COUNT: 4 bytes
CLOCK_MHZ: 4 bytes
... records ...
```

Each record (64 bytes for v1.2):
- seq_id, timestamps (ingress, core, risk, egress)
- flags, metadata

### Verilator Integration

```cpp
// In your testbench
#include "verilated_vcd_c.h"

// ... simulation code ...

// Sentinel can read the VCD directly
// Or export timestamps to CSV:
fprintf(trace_file, "%lu,%lu,%lu,%lu\n",
        t_ingress, t_core, t_risk, t_egress);
```

### CSV Format

Simple 4-column format:

```csv
t_ingress,t_core,t_risk,t_egress
1000,1025,1056,1074
1100,1128,1159,1177
```

### Custom Format Converter

```python
# convert_traces.py
import struct
from pathlib import Path

def convert_my_format(input_path: str, output_path: str):
    """Convert your trace format to Sentinel format."""

    MAGIC = b'SNTL'
    VERSION = 0x0102
    RECORD_SIZE = 64

    records = []
    # ... parse your format into records ...

    with open(output_path, 'wb') as out:
        # Write header
        out.write(MAGIC)
        out.write(struct.pack('<H', VERSION))
        out.write(struct.pack('<H', RECORD_SIZE))
        out.write(struct.pack('<I', len(records)))
        out.write(struct.pack('<I', 100))  # clock_mhz
        out.write(b'\x00' * 48)  # padding to 64 bytes

        # Write records
        for rec in records:
            out.write(rec)
```

---

## Interpreting Results

### Regression Output

```
REGRESSION REPORT

  P50     85ns ->    88ns  (+3.5%)    OK
  P99     89ns ->   142ns  (+59.6%)   REGRESS
  P99.9   95ns ->   185ns  (+94.7%)   REGRESS

FAILED: P99 regression 59.6% exceeds 10.0% threshold
```

**What this means:**
- P50 (median) barely changed — most transactions are fine
- P99 (99th percentile) jumped 60% — tail latency degraded significantly
- Something is causing occasional slow transactions

### Pattern Detection Output

```
Pattern: FIFO_BACKPRESSURE (87% confidence)
Stage: risk

Evidence:
  + Risk stage contributes 65% of total latency
  + High variance in risk timing
  + Burst patterns in ingress
```

**What this means:**
- The risk check stage has a FIFO that's filling up under load
- Upstream is producing faster than downstream can consume
- Solution: Increase buffer depth or add flow control

### Exit Codes

| Code | Meaning | CI Action |
|------|---------|-----------|
| 0 | Pass | Continue |
| 1 | Regression/Fail | Block deploy |
| 2 | Critical | Immediate attention |

---

## Common Workflows

### "We already have latency assertions in our testbench"

Great. Sentinel complements that by:
1. Tracking P99/P999 (not just max)
2. Comparing to historical baseline automatically
3. Identifying which stage caused the regression

```makefile
test: sim
    ./run_testbench.sh          # Your existing assertions
    sentinel-hft regression ...  # Historical comparison
```

### "We use Synopsys VCS, not Verilator"

Sentinel doesn't care about your simulator. It reads trace files.

```makefile
sim:
    vcs -sverilog $(SRCS) -o simv
    ./simv +trace=traces.vcd

latency-check: sim
    sentinel-hft regression traces.vcd baseline.json
```

### "Our traces are huge (100GB+)"

Sentinel uses streaming analysis — constant memory regardless of trace size.

```bash
# Works fine with large traces
sentinel-hft analyze huge_trace.bin  # Streams, doesn't load into memory
```

### "We need compliance reports"

```bash
# Generate detailed report
sentinel-hft analyze traces.bin -o report.json

# With Pro license: PDF export
sentinel-hft report traces.bin --format pdf --output compliance_report.pdf
```

### "Multiple test scenarios"

```bash
#!/bin/bash
# Run all scenarios, fail if any regresses

for scenario in normal burst stress corner; do
    echo "Testing: $scenario"
    sentinel-hft regression traces_${scenario}.bin baseline_${scenario}.json || exit 1
done

echo "All scenarios passed"
```

---

## Troubleshooting

### "Exit code 1 but no obvious regression"

Check the threshold. Default is 10% P99 regression.

```bash
# See exact numbers
sentinel-hft regression current.bin baseline.json --verbose

# Adjust threshold if needed
sentinel-hft regression current.bin baseline.json --max-p99-regression 15
```

### "Pattern detection shows low confidence"

Need more trace data. Minimum ~10,000 transactions for reliable detection.

```bash
# Check trace count
sentinel-hft analyze traces.bin -f table
```

### "Trace format not recognized"

```bash
# Check format
file traces.bin
hexdump -C traces.bin | head

# Expected for Sentinel format:
# 00000000  53 4e 54 4c 02 01 40 00  ...  |SNTL..@...|
```

### "typer and rich are required"

```bash
pip install typer rich click pyyaml
```

### "Import errors"

```bash
# Install with all dependencies
pip install sentinel-hft[all]

# Or install from source
pip install -e ".[dev]"
```

---

## Quick Reference

| Goal | Command |
|------|---------|
| Create baseline | `sentinel-hft analyze golden.bin -o baseline.json` |
| Check regression | `sentinel-hft regression current.bin baseline.json` |
| Diagnose issue | `sentinel-hft prescribe current.bin` |
| Generate fix | `sentinel-hft prescribe current.bin --export ./fix` |
| Verify fix | `sentinel-hft verify ./fix` |
| Track over time | `sentinel-hft benchmark record current.bin` |
| View history | `sentinel-hft benchmark history` |
| Full demo | `sentinel-hft demo-e2e` |

---

## Minimal Integration

One line in your Makefile:

```makefile
test: sim
    sentinel-hft regression build/traces.bin baseline.json
```

That's it. CI fails on regression.

---

## Getting Help

- Documentation: See `TESTING_GUIDE.md` for detailed testing instructions
- Demo: Run `sentinel-hft demo-e2e` for interactive walkthrough
- Issues: https://github.com/anthropics/claude-code/issues
