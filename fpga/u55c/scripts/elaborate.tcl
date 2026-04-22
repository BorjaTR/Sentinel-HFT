#-----------------------------------------------------------------------------
# elaborate.tcl -- Elaboration-only flow (no place/route).
#
# Runs Vivado synth_design with -rtl and -mode elaborate. Catches:
#   * Missing files / typos in module names
#   * Width mismatches between packed structs and AXI-stream ports
#   * Undriven top-level inputs / dangling outputs
#   * Unresolved `import risk_pkg::*` etc.
#
# Fast enough to run on a laptop (~30-60s) and we wire it into the
# GitHub Actions job as an optional manual check when Vivado is
# available. The hosted CI uses Verilator --lint-only instead (see
# .github/workflows/fpga-elaborate.yml) because Vivado isn't free.
#
# Usage:  vivado -mode batch -source fpga/u55c/scripts/elaborate.tcl
#-----------------------------------------------------------------------------

set part "xcu55c-fsvh2892-2L-e"
set top  "sentinel_u55c_top"

set repo_root [file normalize [file join [file dirname [info script]] ../../..]]
cd $repo_root

set_part $part

# Packages first.
#
# WP3.1 (2026-04-21): only v12 packages are fed to the Vivado elaborate
# flow. The legacy `rtl/trace_pkg.sv` is still consumed by the Verilator
# testbench and the host decoders; see docs/AUDIT_FIX_PLAN.md §WP3.1.
foreach f [list \
    rtl/trace_pkg_v12.sv \
    rtl/risk_pkg.sv \
    rtl/fault_pkg.sv \
] {
    read_verilog -sv [file join $repo_root $f]
}

# Modules.
#
# WP3.1 (2026-04-21): `rtl/sentinel_shell.sv` is explicitly NOT in the
# read list -- production uses `sentinel_shell_v12`.
# WP3.3 (2026-04-21): `rtl/stub_latency_core.sv` is explicitly NOT in
# the read list -- its STUB_ONLY elaboration assertion would fire the
# moment Vivado saw it alongside the production path.
foreach f [list \
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
    fpga/u55c/sentinel_u55c_top.sv \
] {
    read_verilog -sv [file join $repo_root $f]
}

synth_design -top $top -part $part -rtl -mode out_of_context
puts "==> Elaboration passed for $top on $part"
