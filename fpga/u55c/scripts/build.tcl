#-----------------------------------------------------------------------------
# build.tcl -- Non-project Vivado flow for Sentinel-HFT on Alveo U55C.
#
# Usage (from the repo root):
#
#   vivado -mode batch -source fpga/u55c/scripts/build.tcl
#
# Optional overrides via -tclargs:
#
#   vivado -mode batch -source fpga/u55c/scripts/build.tcl \
#          -tclargs -run synth                        # synthesis only
#
#   vivado -mode batch -source fpga/u55c/scripts/build.tcl \
#          -tclargs -run impl -jobs 8 -part xcu55c-fsvh2892-2L-e
#
# What it does:
#   1. Creates an in-memory design (no .xpr written).
#   2. Reads all SystemVerilog from rtl/ + fpga/u55c/.
#   3. Reads sentinel_u55c.xdc for timing + I/O.
#   4. Runs synth_design / opt_design / place_design / route_design.
#   5. Writes bitstream + reports into fpga/u55c/out/.
#
# Why non-project: it's faster to re-run, has no GUI state to drift,
# and mirrors what hardware teams run in batch on their build farm.
#-----------------------------------------------------------------------------

# ---------- Configuration ----------------------------------------------------
set part    "xcu55c-fsvh2892-2L-e"
set top     "sentinel_u55c_top"
set jobs    8
set run     "all"                        ;# all | synth | impl

# Paths are relative to the repo root; we cd there so everything else
# stays short.
set repo_root [file normalize [file join [file dirname [info script]] ../../..]]
cd $repo_root
puts "==> Sentinel-HFT U55C build from $repo_root"

# ---------- Arg parsing ------------------------------------------------------
for {set i 0} {$i < [llength $argv]} {incr i} {
    set arg [lindex $argv $i]
    switch -- $arg {
        -part { incr i; set part [lindex $argv $i] }
        -top  { incr i; set top  [lindex $argv $i] }
        -jobs { incr i; set jobs [lindex $argv $i] }
        -run  { incr i; set run  [lindex $argv $i] }
        default { puts "ignoring unknown arg: $arg" }
    }
}

set out_dir [file join $repo_root "fpga/u55c/out"]
file mkdir $out_dir

# ---------- RTL sources ------------------------------------------------------
# Packages first so `import risk_pkg::*` resolves when the module files
# are elaborated in-order.
#
# WP3.1 (2026-04-21): the legacy `rtl/trace_pkg.sv` and `rtl/sentinel_shell.sv`
# are deliberately NOT in this list. The production top level
# (`sentinel_u55c_top.sv`) imports `trace_pkg_v12` and instantiates
# `sentinel_shell_v12` only. Leaving the legacy files out of the synth
# read list enforces the Wave 3 invariant that the bitstream contains
# exactly one copy of the shell and trace package, even while sim and
# host-tooling consumers still import the older names (see
# docs/AUDIT_FIX_PLAN.md §WP3.1 for the Wave 5 migration plan).
#
# IMPORTANT: do not add `rtl/trace_pkg.sv` or `rtl/sentinel_shell.sv` to
# this list without first removing every consumer under `sim/`, `tests/`,
# `wind_tunnel/`, and `host/` -- otherwise a change here is silently
# elaborated into the production bitstream alongside v12 and Vivado
# picks the wrong one.
set pkg_sources [list \
    rtl/trace_pkg_v12.sv \
    rtl/risk_pkg.sv \
    rtl/fault_pkg.sv \
]

set rtl_sources [list \
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
]

# NOTE: rtl/stub_latency_core.sv is a simulation-only module with a
# `SYNTHESIS`-gated $fatal and an elaboration-time STUB_ONLY assertion
# (WP3.3). It is intentionally absent from the bitstream source list.
# Adding it here will cause elaboration to fail -- that is the
# designed behaviour.

# ---------- Design bring-up --------------------------------------------------
puts "==> Creating in-memory design for $part"
set_part $part

foreach f $pkg_sources {
    read_verilog -sv [file join $repo_root $f]
}
foreach f $rtl_sources {
    read_verilog -sv [file join $repo_root $f]
}
read_xdc [file join $repo_root "fpga/u55c/constraints/sentinel_u55c.xdc"]

# ---------- Synthesis --------------------------------------------------------
if {$run eq "synth" || $run eq "all"} {
    puts "==> Running synth_design"
    synth_design -top $top -part $part -flatten_hierarchy rebuilt
    write_checkpoint -force [file join $out_dir "post_synth.dcp"]
    report_utilization -file [file join $out_dir "utilization_post_synth.rpt"]
    report_timing_summary -file [file join $out_dir "timing_post_synth.rpt"]
}

# ---------- Implementation ---------------------------------------------------
if {$run eq "impl" || $run eq "all"} {
    if {$run eq "impl"} {
        # Picks up a previous post_synth checkpoint if we're resuming.
        open_checkpoint [file join $out_dir "post_synth.dcp"]
    }
    puts "==> opt_design / place_design / route_design ($jobs jobs)"
    opt_design
    place_design
    phys_opt_design
    route_design
    write_checkpoint -force [file join $out_dir "post_route.dcp"]
    report_utilization      -file [file join $out_dir "utilization_post_route.rpt"]
    report_timing_summary   -file [file join $out_dir "timing_post_route.rpt"]
    report_clock_utilization -file [file join $out_dir "clock_utilization.rpt"]
    report_drc              -file [file join $out_dir "drc.rpt"]
    report_power            -file [file join $out_dir "power.rpt"]

    # Bitstream (optional -- skip via -run synth for fast PnR-only runs).
    puts "==> Writing bitstream"
    write_bitstream -force [file join $out_dir "sentinel_u55c.bit"]
}

puts "==> Build artifacts in: $out_dir"
puts "==> Done."
