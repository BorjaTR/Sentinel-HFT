# =============================================================================
# V-Parity — cocotb / Verilator runner for risk_gate_v2 ↔ golden parity.
#
# Targets:
#   make sim           — build + run the parity sim (writes RTL decisions JSON)
#   make compare       — run python comparator (golden JSON vs RTL JSON)
#   make all           — sim + compare
#   make clean         — remove build artifacts
#
# Tooling:
#   - Verilator >= 4.220
#   - cocotb >= 1.8 (`pip install cocotb`)
#   - Python 3.10+
#
# Inputs:
#   - PARITY_CORPUS    JSON corpus path (default: golden_seed42_n50000.json
#                      regenerated from MANIFEST.sha256)
#   - SIM              cocotb backend; default verilator
# =============================================================================

SHELL          := /bin/bash
TOPLEVEL_LANG  ?= verilog
TOPLEVEL       ?= risk_gate_v2_tb
SIM            ?= verilator
EXTRA_ARGS     += --trace --trace-structs

# RTL dependencies — order matters
VERILOG_SOURCES := \
	$(PWD)/../../rtl/risk_pkg.sv \
	$(PWD)/../../rtl/rate_limiter.sv \
	$(PWD)/../../rtl/position_limiter.sv \
	$(PWD)/../../rtl/kill_switch.sv \
	$(PWD)/../../rtl/risk_gate.sv \
	$(PWD)/../../rtl/fat_finger_band.sv \
	$(PWD)/../../rtl/symbol_allowlist.sv \
	$(PWD)/../../rtl/risk_gate_v2.sv \
	$(PWD)/risk_gate_v2_tb.sv

MODULE := drive_corpus

include $(shell cocotb-config --makefiles)/Makefile.sim

.PHONY: compare all
compare:
	python3 -m verification.v_parity.compare \
		--golden ../../verification/reports/v_floor/golden_seed42_n50000.json \
		--rtl    ../../verification/reports/v_parity/rtl_seed42_n50000.json \
		--out    ../../verification/reports/v_parity/parity_seed42.json

all: sim compare
