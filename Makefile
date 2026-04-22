# Sentinel-HFT Top-Level Makefile
#
# Usage:
#   make build       - Build RTL simulation
#   make test        - Run all tests
#   make lint        - Lint RTL and Python code
#   make clean       - Remove build artifacts
#   make help        - Show this help

SHELL := /bin/bash

# Directories
SIM_DIR   := sim
TESTS_DIR := tests
HOST_DIR  := host

# Default target
.PHONY: all
all: build

#-------------------------------------------------------------------------------
# Build Targets
#-------------------------------------------------------------------------------

.PHONY: build
build:
	@echo "=== Building RTL simulation ==="
	$(MAKE) -C $(SIM_DIR) all

.PHONY: build-latency-%
build-latency-%:
	@echo "=== Building with CORE_LATENCY=$* ==="
	$(MAKE) -C $(SIM_DIR) CORE_LATENCY=$* all

#-------------------------------------------------------------------------------
# Test Targets
#-------------------------------------------------------------------------------

.PHONY: test
test: test-python test-rtl
	@echo "=== All tests completed ==="

.PHONY: test-python
test-python:
	@echo "=== Running Python tests ==="
	python3 -m pytest $(TESTS_DIR) -v --ignore=$(TESTS_DIR)/test_h3_risk_controls.py

.PHONY: test-rtl
test-rtl: build
	@echo "=== Running RTL tests ==="
	cd $(SIM_DIR) && python3 -m pytest ../$(TESTS_DIR)/test_h1_*.py -v

.PHONY: test-quick
test-quick: build
	@echo "=== Running quick tests ==="
	cd $(SIM_DIR) && python3 -m pytest ../$(TESTS_DIR) -v -x --ignore=../$(TESTS_DIR)/test_h1_determinism.py --ignore=../$(TESTS_DIR)/test_h3_risk_controls.py

.PHONY: test-latency
test-latency: build
	@echo "=== Running latency tests ==="
	cd $(SIM_DIR) && python3 -m pytest ../$(TESTS_DIR)/test_h1_stub_latency.py -v

.PHONY: test-determinism
test-determinism: build
	@echo "=== Running determinism tests ==="
	cd $(SIM_DIR) && python3 -m pytest ../$(TESTS_DIR)/test_h1_determinism.py -v

.PHONY: test-backpressure
test-backpressure: build
	@echo "=== Running backpressure tests ==="
	cd $(SIM_DIR) && python3 -m pytest ../$(TESTS_DIR)/test_h1_backpressure.py -v

.PHONY: test-overflow
test-overflow: build
	@echo "=== Running overflow tests ==="
	cd $(SIM_DIR) && python3 -m pytest ../$(TESTS_DIR)/test_h1_overflow.py -v

.PHONY: test-equivalence
test-equivalence: build
	@echo "=== Running equivalence tests ==="
	cd $(SIM_DIR) && python3 -m pytest ../$(TESTS_DIR)/test_h1_functional_equivalence.py -v

.PHONY: test-coverage
test-coverage: build
	@echo "=== Running tests with coverage ==="
	cd $(SIM_DIR) && python3 -m pytest ../$(TESTS_DIR) -v --cov=../$(HOST_DIR) --cov-report=term-missing

#-------------------------------------------------------------------------------
# Simulation Targets
#-------------------------------------------------------------------------------

.PHONY: run
run: build
	@echo "=== Running simulation ==="
	$(SIM_DIR)/obj_dir/Vtb_sentinel_shell --test latency --num-tx 100

.PHONY: run-trace
run-trace: build
	@echo "=== Running simulation with VCD trace ==="
	$(SIM_DIR)/obj_dir/Vtb_sentinel_shell --test latency --num-tx 100 --trace

.PHONY: demo
demo:
	@echo "=== Running demo ==="
	sentinel-hft demo --output-dir demo_output
	@echo "Demo output in demo_output/"

#-------------------------------------------------------------------------------
# Lint Targets
#-------------------------------------------------------------------------------

.PHONY: lint
lint: lint-rtl lint-python

.PHONY: lint-rtl
lint-rtl:
	@echo "=== Linting RTL ==="
	$(MAKE) -C $(SIM_DIR) lint

.PHONY: lint-python
lint-python:
	@echo "=== Linting Python ==="
	-python3 -m ruff check $(HOST_DIR) $(TESTS_DIR) 2>/dev/null || echo "ruff not installed, skipping"
	-python3 -m black --check $(HOST_DIR) $(TESTS_DIR) 2>/dev/null || echo "black not installed, skipping"

.PHONY: format
format:
	@echo "=== Formatting Python code ==="
	-python3 -m black $(HOST_DIR) $(TESTS_DIR) 2>/dev/null || echo "black not installed, skipping"
	-python3 -m ruff check --fix $(HOST_DIR) $(TESTS_DIR) 2>/dev/null || echo "ruff not installed, skipping"

#-------------------------------------------------------------------------------
# FPGA Targets (Alveo U55C)
#-------------------------------------------------------------------------------

FPGA_DIR    := fpga/u55c
FPGA_TOP    := sentinel_u55c_top
# WP3.1 (2026-04-21): legacy `rtl/trace_pkg.sv` and `rtl/sentinel_shell.sv`
# are deliberately NOT in this list; v12 is the single production
# source. WP3.3: `rtl/stub_latency_core.sv` is deliberately absent --
# its STUB_ONLY elaboration check would fire under Verilator lint.
# Keep this list in sync with fpga/u55c/scripts/build.tcl and
# fpga/u55c/scripts/elaborate.tcl.
FPGA_RTL    := \
	rtl/trace_pkg_v12.sv \
	rtl/risk_pkg.sv \
	rtl/fault_pkg.sv \
	rtl/eth/eth_pkg.sv \
	rtl/sync_fifo.sv \
	rtl/reset_sync.sv \
	rtl/async_fifo.sv \
	rtl/stage_timer.sv \
	rtl/rate_limiter.sv \
	rtl/position_limiter.sv \
	rtl/kill_switch.sv \
	rtl/risk_audit_log.sv \
	rtl/risk_gate.sv \
	rtl/instrumented_pipeline.sv \
	rtl/sentinel_shell_v12.sv \
	rtl/eth/eth_mac_100g_shim.sv \
	$(FPGA_DIR)/sentinel_u55c_top.sv

# Elaboration-only check via Verilator --lint-only. Catches most
# structural bugs (port mismatches, width typos, missing includes)
# without needing a Vivado install. Used by CI.
.PHONY: fpga-elaborate
fpga-elaborate:
	@echo "=== Elaborating $(FPGA_TOP) with Verilator --lint-only ==="
	verilator --lint-only -sv \
	  -Wno-UNUSEDSIGNAL -Wno-UNUSEDPARAM -Wno-UNDRIVEN \
	  -Wno-WIDTHEXPAND -Wno-WIDTHTRUNC -Wno-WIDTH \
	  -Wno-PINMISSING -Wno-DECLFILENAME -Wno-CASEINCOMPLETE \
	  -Irtl -Irtl/eth -I$(FPGA_DIR) \
	  --top-module $(FPGA_TOP) \
	  $(FPGA_RTL)

# Full Vivado synth + impl flow. Requires `vivado` on PATH.
.PHONY: fpga-build
fpga-build:
	@echo "=== Running Vivado synth + impl for $(FPGA_TOP) ==="
	@command -v vivado >/dev/null 2>&1 || { \
	    echo "ERROR: vivado not on PATH. Install Xilinx Vivado 2023.2+ first."; \
	    exit 1; }
	vivado -mode batch -source $(FPGA_DIR)/scripts/build.tcl

# Elaboration-only via Vivado (more thorough than Verilator, but
# still much faster than a full synth).
.PHONY: fpga-elaborate-vivado
fpga-elaborate-vivado:
	@echo "=== Running Vivado elaboration for $(FPGA_TOP) ==="
	@command -v vivado >/dev/null 2>&1 || { \
	    echo "ERROR: vivado not on PATH. Install Xilinx Vivado 2023.2+ first."; \
	    exit 1; }
	vivado -mode batch -source $(FPGA_DIR)/scripts/elaborate.tcl

# Open-source synthesis via Yosys. Produces an independent LUT/FF
# estimate without a Vivado install. Requires Yosys >= 0.40 (the
# older 0.9 in Ubuntu 22.04 LTS cannot parse SystemVerilog package
# typedefs). Recommended: yowasp/oss-cad-suite.
.PHONY: fpga-synth-yosys
fpga-synth-yosys:
	@echo "=== Running Yosys synth_xilinx for $(FPGA_TOP) ==="
	@command -v yosys >/dev/null 2>&1 || { \
	    echo "ERROR: yosys not on PATH. Install Yosys >= 0.40."; \
	    exit 1; }
	yosys -s $(FPGA_DIR)/scripts/yosys_synth.ys \
	  -l $(FPGA_DIR)/reports/yosys_synth.txt

# First-order area + depth estimate from static RTL parsing. Runs
# without any FPGA toolchain installed; deterministic and
# reproducible. Used as a cheap pre-synth sanity check.
.PHONY: fpga-area-census
fpga-area-census:
	@echo "=== First-order area + depth census for $(FPGA_TOP) ==="
	python3 $(FPGA_DIR)/scripts/area_census.py \
	  > $(FPGA_DIR)/reports/area_census.txt
	@tail -20 $(FPGA_DIR)/reports/area_census.txt

.PHONY: fpga-clean
fpga-clean:
	@echo "=== Cleaning FPGA build artifacts ==="
	rm -rf $(FPGA_DIR)/out
	rm -rf .Xil vivado*.jou vivado*.log

#-------------------------------------------------------------------------------
# Clean Targets
#-------------------------------------------------------------------------------

.PHONY: clean
clean:
	@echo "=== Cleaning build artifacts ==="
	$(MAKE) -C $(SIM_DIR) clean
	rm -rf __pycache__ .pytest_cache .coverage
	rm -rf $(HOST_DIR)/__pycache__ $(TESTS_DIR)/__pycache__
	find . -name "*.pyc" -delete
	find . -name "*.pyo" -delete
	find . -name ".ruff_cache" -type d -exec rm -rf {} + 2>/dev/null || true

.PHONY: clean-all
clean-all: clean
	rm -rf *.egg-info build dist

#-------------------------------------------------------------------------------
# Development Targets
#-------------------------------------------------------------------------------

.PHONY: install
install:
	@echo "=== Installing package in development mode ==="
	pip install -e ".[dev]"

.PHONY: install-deps
install-deps:
	@echo "=== Installing dependencies ==="
	pip install numpy pytest

#-------------------------------------------------------------------------------
# Documentation Targets
#-------------------------------------------------------------------------------

.PHONY: docs
docs:
	@echo "=== Documentation ==="
	@echo "See docs/ directory for documentation"

#-------------------------------------------------------------------------------
# Help
#-------------------------------------------------------------------------------

.PHONY: help
help:
	@echo "Sentinel-HFT Makefile"
	@echo ""
	@echo "Build targets:"
	@echo "  build            Build RTL simulation (default)"
	@echo "  build-latency-N  Build with CORE_LATENCY=N"
	@echo ""
	@echo "Test targets:"
	@echo "  test             Run all tests"
	@echo "  test-quick       Run tests quickly (skip slow ones)"
	@echo "  test-latency     Run latency tests only"
	@echo "  test-determinism Run determinism tests only"
	@echo "  test-backpressure Run backpressure tests only"
	@echo "  test-overflow    Run overflow tests only"
	@echo "  test-equivalence Run equivalence tests only"
	@echo "  test-coverage    Run tests with coverage report"
	@echo ""
	@echo "Simulation targets:"
	@echo "  run              Run simulation"
	@echo "  run-trace        Run simulation with VCD output"
	@echo ""
	@echo "Lint targets:"
	@echo "  lint             Lint RTL and Python code"
	@echo "  lint-rtl         Lint RTL only"
	@echo "  lint-python      Lint Python only"
	@echo "  format           Format Python code"
	@echo ""
	@echo "FPGA targets (Alveo U55C):"
	@echo "  fpga-elaborate         Verilator --lint-only on $(FPGA_TOP) (CI-friendly)"
	@echo "  fpga-elaborate-vivado  Vivado elaborate-only flow"
	@echo "  fpga-build             Full Vivado synth + impl + bitstream"
	@echo "  fpga-synth-yosys       Open-source synth via Yosys >= 0.40"
	@echo "  fpga-area-census       First-order area + depth estimate (no toolchain)"
	@echo "  fpga-clean             Remove fpga/u55c/out + Vivado scratch"
	@echo ""
	@echo "Other targets:"
	@echo "  install          Install package in dev mode"
	@echo "  install-deps     Install dependencies"
	@echo "  clean            Remove build artifacts"
	@echo "  clean-all        Remove all generated files"
	@echo "  help             Show this help"
