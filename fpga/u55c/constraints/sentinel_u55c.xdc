#-----------------------------------------------------------------------------
# sentinel_u55c.xdc -- Sentinel-HFT constraints for AMD Alveo U55C
#
# Target device : xcu55c-fsvh2892-2L-e
# Speed grade   : -2L (low-voltage, HBM2-capable)
# User clock    : 100 MHz (10.0 ns period) derived from sysclk0 @ 300 MHz
#
# This is the minimal constraint set needed to close timing on the
# Sentinel RTL core (sentinel_shell_v12 + risk_gate + risk_audit_log).
# It deliberately does NOT pin QSFP / HBM / PCIe -- those are owned
# by the XDMA shell IP and its associated BD constraints.
#
# Sections:
#   1. Primary clocks
#   2. Generated / derived clocks
#   3. I/O standards and locations for status pins
#   4. Asynchronous / false-path resets
#   5. Pblock floorplan (risk gate -> SLR1 to avoid SLR crossings on
#      the tick-to-trade critical path)
#   6. Bitstream configuration
#   7. QSFP28 CMAC (100 GbE) -- only applied when WITH_CMAC=1
#
# All paths assume the top-level module is ``sentinel_u55c_top``.
#-----------------------------------------------------------------------------

#-----------------------------------------------------------------------------
# 1. Primary clocks
#-----------------------------------------------------------------------------
# sysclk0 is a differential 300 MHz reference sourced from the on-card
# oscillator. On the Alveo U55C this maps to bank 68 pins BK47/BL46.
# The input clock period is 3.333 ns; we treat the MMCM output
# (clk_100) as the datapath clock.
create_clock -period 3.333 -name sysclk0_p [get_ports sysclk0_p]

set_property PACKAGE_PIN BK47 [get_ports sysclk0_p]
set_property PACKAGE_PIN BL46 [get_ports sysclk0_n]
set_property IOSTANDARD LVDS  [get_ports {sysclk0_p sysclk0_n}]
set_property DIFF_TERM_ADV TERM_100 [get_ports sysclk0_p]

#-----------------------------------------------------------------------------
# 2. Generated clocks
#-----------------------------------------------------------------------------
# The MMCM inside sentinel_clock_gen divides 300 -> 100 MHz (divide-by-3).
# We expose the resulting clock net as ``clk_100`` at the wrapper boundary.
# If you swap sentinel_clock_gen for a full MMCME4_ADV instance, delete
# this create_generated_clock and let Vivado infer it from the IP.
create_generated_clock -name clk_100 \
  -source  [get_ports sysclk0_p] \
  -divide_by 3 \
  [get_pins u_clkgen/clk_100]

# Keep the Sentinel datapath on this clock domain.
set_clock_groups -asynchronous \
  -group [get_clocks clk_100] \
  -group [get_clocks sysclk0_p]

#-----------------------------------------------------------------------------
# 3. Status pins (heartbeat + LEDs)
#-----------------------------------------------------------------------------
# The U55C has no user-accessible LEDs on the faceplate, but the card
# exposes GPIO header pins on the J2 debug connector. For bring-up on a
# breakout board we drive them to those header pins. The pin names below
# are representative; swap them for your board if different.
set_property PACKAGE_PIN BC18 [get_ports {gpio_led[0]}]
set_property PACKAGE_PIN BD18 [get_ports {gpio_led[1]}]
set_property PACKAGE_PIN BE18 [get_ports {gpio_led[2]}]
set_property PACKAGE_PIN BF18 [get_ports {gpio_led[3]}]
set_property IOSTANDARD LVCMOS18 [get_ports {gpio_led[*]}]
set_property DRIVE 8              [get_ports {gpio_led[*]}]
set_property SLEW SLOW             [get_ports {gpio_led[*]}]

set_property PACKAGE_PIN BG18 [get_ports heartbeat]
set_property IOSTANDARD LVCMOS18 [get_ports heartbeat]

# Board-level reset push-button.
set_property PACKAGE_PIN BH18 [get_ports board_rstn]
set_property IOSTANDARD LVCMOS18 [get_ports board_rstn]

#-----------------------------------------------------------------------------
# 4. Asynchronous / false paths
#-----------------------------------------------------------------------------
# The risk-gate config ports (cfg_rate_*, cfg_pos_*, cfg_kill_*) are
# written from the host AXI-lite and held static for many cycles once
# initialised. Treating them as false paths frees up routing slack.
set_false_path -to [get_cells -hier -filter {NAME =~ *u_risk/cfg_rate_*_q}]
set_false_path -to [get_cells -hier -filter {NAME =~ *u_risk/cfg_pos_*_q}]
set_false_path -to [get_cells -hier -filter {NAME =~ *u_risk/cfg_kill_*_q}]

# The board-level reset synchroniser intentionally crosses from
# async to clk_100. Do not time the source side.
set_false_path -from [get_ports board_rstn]

#-----------------------------------------------------------------------------
# 5. Pblock floorplan
#-----------------------------------------------------------------------------
# U55C has three super-logic regions (SLR0, SLR1, SLR2). Cross-SLR
# hops add >= 1 ns of latency per hop via SLL Super Long Lines.
# Our tick-to-trade path is the whole point, so we keep it inside a
# single SLR. The CMAC / QSFP pads live in SLR0, so anchoring the
# datapath in SLR0 keeps ingress/egress cheap.
create_pblock pblock_sentinel
add_cells_to_pblock [get_pblocks pblock_sentinel] \
  [get_cells {u_shell u_risk u_audit u_clkgen}]
resize_pblock [get_pblocks pblock_sentinel] -add {SLR0}

# Risk gate alone (latency-critical sub-component) gets its own
# pblock inside the Sentinel pblock -- forces all of its flip-flops
# into the same clock region so we don't see intra-SLR latency
# variance between rate / position / kill branches.
create_pblock pblock_risk_gate
add_cells_to_pblock [get_pblocks pblock_risk_gate] [get_cells u_risk]
resize_pblock [get_pblocks pblock_risk_gate] -add {CLOCKREGION_X4Y0:CLOCKREGION_X4Y3}

#-----------------------------------------------------------------------------
# 6. Bitstream configuration
#-----------------------------------------------------------------------------
# Mirror the vendor reference flow -- run the configuration at the
# board's QSPI speed, enable CRC, and leave unused pins as pullups so
# they don't float during power-on.
set_property BITSTREAM.CONFIG.SPI_BUSWIDTH 4 [current_design]
set_property BITSTREAM.CONFIG.CONFIGRATE 85.0 [current_design]
set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]
set_property BITSTREAM.CONFIG.UNUSEDPIN PULLUP [current_design]

#-----------------------------------------------------------------------------
# 7. QSFP28 CMAC (100 GbE)
#-----------------------------------------------------------------------------
# Only applied when the top-level is elaborated with WITH_CMAC=1.
# The actual CMAC hard IP is instantiated outside this top (in the
# XDMA shell or a dedicated `cmac_usplus_0` block design); this file
# only constrains the shim's LBUS interface and the 322.265625 MHz
# user clock it runs on.
#
# U55C MGT / refclk pin assignments (from UG1352 "U55C Card User
# Guide", Table 2-4 and board schematic rev C):
#   QSFP0  : MGT quad 131, refclk MGTREFCLK0 on bank 131 (K10/K9),
#            161.1328125 MHz LVDS from Si5328 #0.
#   QSFP1  : MGT quad 134, refclk MGTREFCLK0 on bank 134 (V10/V9),
#            same frequency, separate synthesiser output.
# Both QSFP cages sit in SLR0 immediately above the PCIe bridge, so
# pblock_sentinel (SLR0) is already where the LBUS buffers will land.

# CMAC reference clock -- LVDS from the board's Si5328 output, drives
# the CMAC TX/RX PLLs at 161.1328125 MHz (= 6.206 ns period).
create_clock -period 6.206 -name qsfp0_refclk [get_ports qsfp0_refclk_p]
set_property PACKAGE_PIN K10 [get_ports qsfp0_refclk_p]
set_property PACKAGE_PIN K9  [get_ports qsfp0_refclk_n]

create_clock -period 6.206 -name qsfp1_refclk [get_ports qsfp1_refclk_p]
set_property PACKAGE_PIN V10 [get_ports qsfp1_refclk_p]
set_property PACKAGE_PIN V9  [get_ports qsfp1_refclk_n]

# CMAC user clock produced by the hard macro (322.265625 MHz =
# 3.103 ns period). Named so Vivado can derive it from the hard IP.
create_clock -period 3.103 -name cmac_usr_clk [get_ports cmac_usr_clk]

# The Sentinel datapath at 100 MHz and the CMAC user clock at 322 MHz
# are asynchronous. As of Wave 2 (E-S1-02, E-S1-03) the actual crossing
# is contained inside two `async_fifo` instances -- `u_rx_cdc_fifo`
# (cmac_usr_clk -> clk_100) and `u_tx_cdc_fifo` (clk_100 ->
# cmac_usr_clk) -- plus two `reset_sync` stages, one per domain. The
# two blanket `set_clock_groups -asynchronous` constraints below are
# correct for the FIFO interior (gray-coded pointers + 2-stage
# synchronisers) but let Vivado ignore all inter-clock paths globally,
# which is too aggressive: we want point-to-point max-delay on the
# gray pointer and synchroniser crossings so that transitional glitches
# don't propagate longer than one clock period of the destination
# domain. The recommended production tightening is:
#
#   set_max_delay -datapath_only -from [get_pins -hier *wr_ptr_gray_r*/C] \
#                                -to   [get_pins -hier *rd_gray_wclk_0_r*/D] 3.103
#   set_max_delay -datapath_only -from [get_pins -hier *rd_ptr_gray_r*/C] \
#                                -to   [get_pins -hier *wr_gray_rclk_0_r*/D] 3.103
#
# These are intentionally left commented in this stub because pin
# names depend on how the synthesis tool mangles the ASYNC_REG
# packed arrays; uncomment and adjust after `write_checkpoint
# -synth` inspection.
set_clock_groups -asynchronous \
  -group [get_clocks clk_100] \
  -group [get_clocks cmac_usr_clk]

# Reset synchronisers -- flops must not be part of a shift-register
# inference; Vivado's ASYNC_REG attribute on the HDL source handles
# this, but the false-path on the async assert input is declared
# belt-and-braces.
set_false_path -to [get_pins -hier -filter {NAME =~ *u_cmac_rst/sync_r_reg*/PRE}]

# Tell the placer the four high-speed serial lanes per cage map to
# the correct GT quad. These are GTY transceivers on the Alveo U55C;
# the pin list below is the nominal layout -- adjust to match your
# QSFP28 breakout board if you route to pins other than those the
# Alveo reference design uses.
# (Commented out because they take effect only in a build that
# actually includes the CMAC hard IP; uncomment alongside the IP
# instantiation in your XDMA shell project.)
# set_property PACKAGE_PIN F2 [get_ports qsfp0_rx_p[0]]
# set_property PACKAGE_PIN F1 [get_ports qsfp0_rx_n[0]]
# set_property PACKAGE_PIN G4 [get_ports qsfp0_tx_p[0]]
# set_property PACKAGE_PIN G3 [get_ports qsfp0_tx_n[0]]
# ... lanes 1..3 analogous ...

# Anchor the CMAC shim near the QSFP cage to keep LBUS routing local.
create_pblock pblock_qsfp0_shim
add_cells_to_pblock [get_pblocks pblock_qsfp0_shim] \
  [get_cells -quiet {g_cmac.u_qsfp0_shim}]
resize_pblock [get_pblocks pblock_qsfp0_shim] -add {CLOCKREGION_X0Y0:CLOCKREGION_X0Y3}
