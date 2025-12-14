# Installation Guide

## Prerequisites

### Python

Python 3.10 or later required.

```bash
python3 --version  # Should be 3.10+
```

### Verilator (for RTL simulation)

```bash
# Ubuntu/Debian
sudo apt install verilator

# macOS
brew install verilator

# Verify
verilator --version  # Should be 5.0+
```

## Installation Methods

### 1. From Source (Recommended)

```bash
git clone https://github.com/BorjaTR/Sentinel-HFT
cd Sentinel-HFT

# Install in development mode
pip install -e ".[dev]"

# Build RTL simulations
make build
```

### 2. Docker

```bash
# Build image
docker build -t sentinel-hft .

# Run demo
docker run sentinel-hft demo

# Run with volume mounts
docker run -v $(pwd)/data:/data -v $(pwd)/output:/output \
    sentinel-hft replay /data/market_data.csv -o /output/report.json
```

## Verification

```bash
# Check installation
sentinel-hft --version

# Run demo
sentinel-hft demo
```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `ANTHROPIC_API_KEY` | API key for AI explanations | For `--explain` |
| `SENTINEL_HFT_SIM_DIR` | Path to simulation binaries | Auto-detected |
| `NO_COLOR` | Disable colored output | Optional |
| `SENTINEL_DEBUG` | Enable debug output | Optional |

## Optional Dependencies

### AI Features

```bash
pip install sentinel-hft[ai]
# or
pip install anthropic
```

Required for:
- `--explain` flag
- AI-powered analysis reports

### Development

```bash
pip install sentinel-hft[dev]
```

Includes:
- pytest
- black
- ruff

## Troubleshooting

### "verilator: command not found"

Install Verilator or use Docker image.

### "ANTHROPIC_API_KEY required"

Set API key or omit `--explain` flag:

```bash
export ANTHROPIC_API_KEY=your_key
# or run without AI
sentinel-hft analyze traces.bin
```

### Import errors

```bash
pip install --upgrade -e ".[dev]"
```

### Simulation not found

```bash
make -C sim clean
make -C sim all
```
