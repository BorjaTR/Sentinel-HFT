# Makefile for Sentinel-HFT RTL Simulation
#
# Builds Verilator simulation models for testing.
#
# Targets:
#   all       - Build simulation executable (Sentinel Shell)
#   risk      - Build risk gate test executable
#   run       - Run simulation with default settings
#   clean     - Remove build artifacts
#   lint      - Run Verilator lint-only

SHELL := /bin/bash

# Project paths
RTL_DIR   := ../rtl
SIM_DIR   := .
BUILD_DIR := ./obj_dir

# Verilator settings
VERILATOR := verilator
VFLAGS    := --cc --exe --build
VFLAGS    += --timing
VFLAGS    += -CFLAGS "-std=c++17 -O3"
VFLAGS    += -LDFLAGS "-pthread"
VFLAGS    += -Wno-VARHIDDEN -Wno-TIMESCALEMOD
VFLAGS    += --trace
VFLAGS    += -I$(RTL_DIR)

# Top module
TOP := tb_sentinel_shell

# RTL sources (order matters for dependencies)
RTL_SRCS := \
	$(RTL_DIR)/trace_pkg.sv \
	$(RTL_DIR)/sync_fifo.sv \
	$(RTL_DIR)/sentinel_shell.sv \
	$(RTL_DIR)/stub_latency_core.sv \
	$(SIM_DIR)/tb_sentinel_shell.sv

# C++ testbench driver
CPP_SRCS := $(SIM_DIR)/sim_main.cpp

# Output executable
SIM_EXE := $(BUILD_DIR)/V$(TOP)

# Default latency for parameterized builds
CORE_LATENCY ?= 1

#-------------------------------------------------------------------------------
# Targets
#-------------------------------------------------------------------------------

.PHONY: all run clean lint build_latency_% run_latency_%

all: $(SIM_EXE)

$(SIM_EXE): $(RTL_SRCS) $(CPP_SRCS)
	$(VERILATOR) $(VFLAGS) \
		-GCORE_LATENCY=$(CORE_LATENCY) \
		--top-module $(TOP) \
		$(RTL_SRCS) \
		$(CPP_SRCS) \
		-o V$(TOP)

# Build with specific latency parameter
build_latency_%:
	$(MAKE) CORE_LATENCY=$* all

# Run simulation
run: $(SIM_EXE)
	$(SIM_EXE)

# Run with specific latency
run_latency_%: build_latency_%
	$(BUILD_DIR)/V$(TOP)

# Lint only (no build)
lint:
	$(VERILATOR) --lint-only --timing \
		-Wno-VARHIDDEN -Wno-TIMESCALEMOD \
		-I$(RTL_DIR) \
		$(RTL_SRCS)

# Clean build artifacts
clean:
	rm -rf $(BUILD_DIR)
	rm -f *.vcd *.fst
	rm -f trace_output.bin
	rm -rf __pycache__

#-------------------------------------------------------------------------------
# Risk Gate (H3)
#-------------------------------------------------------------------------------

# Risk gate RTL sources
RISK_RTL_SRCS := \
	$(RTL_DIR)/risk_pkg.sv \
	$(RTL_DIR)/rate_limiter.sv \
	$(RTL_DIR)/position_limiter.sv \
	$(RTL_DIR)/kill_switch.sv \
	$(RTL_DIR)/risk_gate.sv \
	$(RTL_DIR)/tb_risk_gate.sv

# Risk gate C++ driver
RISK_CPP_SRCS := $(SIM_DIR)/sim_risk.cpp

# Risk gate executable
RISK_TOP := tb_risk_gate
RISK_EXE := $(BUILD_DIR)/V$(RISK_TOP)

.PHONY: risk run_risk lint_risk

risk: $(RISK_EXE)

$(RISK_EXE): $(RISK_RTL_SRCS) $(RISK_CPP_SRCS)
	$(VERILATOR) $(VFLAGS) \
		--top-module $(RISK_TOP) \
		$(RISK_RTL_SRCS) \
		$(RISK_CPP_SRCS) \
		-o V$(RISK_TOP)

run_risk: $(RISK_EXE)
	$(RISK_EXE)

lint_risk:
	$(VERILATOR) --lint-only --timing \
		-Wno-VARHIDDEN -Wno-TIMESCALEMOD \
		-I$(RTL_DIR) \
		$(RISK_RTL_SRCS)

#-------------------------------------------------------------------------------
# Help
#-------------------------------------------------------------------------------

# Help
help:
	@echo "Sentinel-HFT Simulation Makefile"
	@echo ""
	@echo "Targets:"
	@echo "  all              Build simulation (default CORE_LATENCY=1)"
	@echo "  build_latency_N  Build with CORE_LATENCY=N"
	@echo "  run              Run simulation"
	@echo "  run_latency_N    Build and run with CORE_LATENCY=N"
	@echo "  risk             Build risk gate simulation"
	@echo "  run_risk         Run risk gate tests"
	@echo "  lint             Run Verilator lint checks"
	@echo "  lint_risk        Lint risk gate RTL"
	@echo "  clean            Remove build artifacts"
	@echo ""
	@echo "Examples:"
	@echo "  make build_latency_0    # Build with combinational core"
	@echo "  make build_latency_7    # Build with 7-cycle latency core"
	@echo "  make run_latency_19     # Build and run with 19-cycle latency"
	@echo "  make run_risk           # Build and run risk gate tests"
