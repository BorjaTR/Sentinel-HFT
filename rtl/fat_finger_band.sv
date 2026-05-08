`ifndef FAT_FINGER_BAND_SV
`define FAT_FINGER_BAND_SV

`include "risk_pkg.sv"

// =============================================================================
// fat_finger_band
// -----------------------------------------------------------------------------
// Combinational price-band check: rejects orders whose price falls outside
// ±band_bps (basis-points) of a configured reference price.
//
// Spec: docs/fpga/ARCHITECTURE.md §3 (priority 6)
// Golden: sentinel_hft/golden/risk_gate.py — RejectReason.FAT_FINGER branch
// Reject code: RISK_FAT_FINGER (8'h07)
//
// Rules (mirroring the golden):
//   - If !cfg_enabled, never rejects.
//   - If cfg_ref_price == 0, never rejects (disabled per-config).
//   - Heartbeats always pass.
//   - Otherwise: lo = ref - (ref * band_bps) / 10_000
//                hi = ref + (ref * band_bps) / 10_000
//                reject if order.price < lo OR order.price > hi
//
// Wave-1-style audit hygiene:
//   - The (ref * band_bps) intermediate multiplies a 64-bit price by a 16-bit
//     bps number. A 80-bit intermediate would be tidiest; we use a 96-bit
//     scratch to leave headroom and document the truncation.
//   - Division by 10_000 is a constant divide; synthesisers fold it. We use
//     the natural `/` operator and rely on Vivado/Yosys to lower it.
//
// Counter:
//   - total_rejected — increments on every actual reject (xfer_accept gated).
// =============================================================================

module fat_finger_band
  import risk_pkg::*;
(
  input  logic                  clk,
  input  logic                  rst_n,

  // Configuration
  input  logic                  cfg_enabled,
  input  logic [15:0]           cfg_band_bps,
  input  logic [63:0]           cfg_ref_price,

  // Order interface — combinational decision
  input  logic                  order_valid,
  output logic                  order_ready,
  input  order_type_e           order_type,
  input  logic [63:0]           order_price,
  input  logic                  xfer_accept,

  // Decision
  output logic                  passed,
  output logic                  rejected,

  // Statistics
  output logic [63:0]           total_rejected
);

  // ---------------------------------------------------------------------------
  // Decision
  // ---------------------------------------------------------------------------
  logic [95:0] band_abs;             // (ref * bps) in widened domain
  logic [63:0] band_q;               // band absolute, divided by 10_000
  logic [63:0] lo, hi;
  logic        outside_band;
  logic        bypass;

  always_comb begin
    band_abs    = {32'd0, cfg_ref_price} * 96'(cfg_band_bps);
    band_q      = band_abs[95:0] / 96'd10_000;
    lo          = (cfg_ref_price > band_q) ? (cfg_ref_price - band_q) : 64'd0;
    hi          = cfg_ref_price + band_q;
    outside_band = (order_price < lo) || (order_price > hi);

    // Bypass paths — never reject.
    bypass = (!cfg_enabled)
          || (cfg_ref_price == 64'd0)
          || (order_type == ORDER_HEARTBEAT)
          || (!order_valid);

    rejected = (!bypass) && outside_band;
    passed   = !rejected;
  end

  assign order_ready = 1'b1;   // never back-pressures upstream

  // ---------------------------------------------------------------------------
  // Counter
  // ---------------------------------------------------------------------------
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      total_rejected <= 64'd0;
    end else if (xfer_accept && rejected) begin
      total_rejected <= total_rejected + 64'd1;
    end
  end

endmodule

`endif
