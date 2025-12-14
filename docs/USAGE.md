# CLI Reference

## Global Options

```
sentinel-hft [--version] [--no-color] <command> [options]
```

| Option | Description |
|--------|-------------|
| `--version`, `-V` | Show version and exit |
| `--no-color` | Disable colored output |

## Commands

### sentinel-hft replay

Replay market data through RTL simulation.

```bash
sentinel-hft replay <input> [options]
```

**Arguments:**
- `input` - Input data file (CSV or binary)

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `-o, --output FILE` | `replay_output/` | Output report file or directory |
| `-l, --latency N` | 1 | Core latency in cycles |
| `--clock-ns NS` | 10.0 | Clock period in nanoseconds |
| `-z, --zscore Z` | 3.0 | Z-score threshold for anomaly detection |
| `--sim-dir DIR` | `sim/` | Simulation directory |
| `--rebuild` | false | Force rebuild of simulation |
| `-q, --quiet` | false | Suppress console output |
| `--no-json` | false | Skip JSON report generation |
| `--no-markdown` | false | Skip Markdown report generation |

**Examples:**
```bash
sentinel-hft replay data.csv -o report.json
sentinel-hft replay data.csv --latency 3 --clock-ns 5.0
sentinel-hft replay data.csv -o output/ --quiet
```

### sentinel-hft analyze

Analyze existing trace file.

```bash
sentinel-hft analyze <traces> [options]
```

**Arguments:**
- `traces` - Binary trace file

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `-o, --output FILE` | stdout | Output report file |
| `-f, --format FMT` | console | Output format: json, markdown, console |
| `--clock-ns NS` | 10.0 | Clock period in nanoseconds |
| `-z, --zscore Z` | 3.0 | Z-score threshold |
| `--explain` | false | Generate AI explanation |
| `-p, --protocol NAME` | none | Protocol for context |
| `--sentinel-path PATH` | none | Path to Sentinel for live data |

**Examples:**
```bash
sentinel-hft analyze traces.bin --format markdown
sentinel-hft analyze traces.bin --explain -o report.md
sentinel-hft analyze traces.bin --explain --protocol arbitrum
```

### sentinel-hft validate

Check trace file integrity.

```bash
sentinel-hft validate <traces> [--clock-ns NS] [--strict]
```

**Arguments:**
- `traces` - Trace file to validate

**Options:**
- `--clock-ns NS` - Clock period in nanoseconds (default: 10.0)
- `--strict` - Exit with code 2 on warnings

**Examples:**
```bash
sentinel-hft validate traces.bin
sentinel-hft validate traces.bin --strict
```

### sentinel-hft convert

Convert between formats.

```bash
sentinel-hft convert <input> [-o output]
```

**Arguments:**
- `input` - Input file (CSV)

**Options:**
- `-o, --output FILE` - Output file (default: input with .bin extension)

**Examples:**
```bash
sentinel-hft convert data.csv
sentinel-hft convert data.csv -o stimulus.bin
```

### sentinel-hft info

Show file information.

```bash
sentinel-hft info <file>
```

**Arguments:**
- `file` - File to inspect (CSV, binary, or trace file)

**Examples:**
```bash
sentinel-hft info market_data.csv
sentinel-hft info traces.bin
```

### sentinel-hft demo

Run demo with sample data.

```bash
sentinel-hft demo [--output-dir DIR]
```

**Options:**
- `--output-dir DIR` - Output directory (default: demo_output)

**Examples:**
```bash
sentinel-hft demo
sentinel-hft demo --output-dir my_demo/
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error |
| 2 | Warning (with `--strict`) |
| 130 | Interrupted (Ctrl+C) |

## Input Formats

### CSV Format

```csv
timestamp_ns,data,opcode,meta
0,0x0000000100000001,1,1001
10000,0x0000000100000002,1,1002
```

| Column | Description |
|--------|-------------|
| timestamp_ns | Timestamp in nanoseconds |
| data | 64-bit data payload (hex) |
| opcode | Operation code (1=new, 2=cancel, 3=modify) |
| meta | User metadata |

### Binary Trace Format

22 bytes per record:
- tx_id: 4 bytes (uint32)
- t_ingress: 8 bytes (uint64)
- t_egress: 8 bytes (uint64)
- flags: 2 bytes (uint16)

## Output Formats

### JSON Report

```json
{
  "metadata": {
    "trace_count": 1000,
    "trace_file": "traces.bin"
  },
  "latency": {
    "p50_cycles": 2,
    "p99_cycles": 5
  }
}
```

### Markdown Report

```markdown
# Analysis Report

## Latency Distribution

| Percentile | Cycles | Time (ns) |
|------------|--------|-----------|
| P50 | 2 | 20 |
| P99 | 5 | 50 |
```
