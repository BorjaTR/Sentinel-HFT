`ifndef SYMBOL_ALLOWLIST_SV
`define SYMBOL_ALLOWLIST_SV

`include "risk_pkg.sv"

// =============================================================================
// symbol_allowlist
// -----------------------------------------------------------------------------
// Fixed-size CAM-style allowlist of permitted symbol_id values.
// 64 slots; an order whose symbol is NOT in the table is rejected.
// A symbol of zero in a slot means the slot is empty/inactive.
//
// Spec: docs/fpga/ARCHITECTURE.md §3 (priority 7)
// Golden: sentinel_hft/golden/risk_gate.py — RejectReason.ALLOWLIST_BLOCK
// Reject code: RISK_ALLOWLIST_BLOCK (8'h08)
//
// Rules (mirroring the golden):
//   - If !cfg_enabled, never rejects.
//   - If allowlist is empty (all slots zero), never rejects (disabled).
//   - Heartbeats always pass.
//   - Otherwise: reject iff order.symbol_id is not present in any slot.
//
// Implementation notes:
//   - Slots are written from the host through the regmap (block 0x0500,
//     SLOT_SYMBOL_ID array @ offset 0x10, stride 4). We expose a write
//     interface for the host bridge to drive; the lookup is fully
//     parallel (one comparator per slot) so latency is ~1 LUT-stage.
//   - On U55C the allowlist fits trivially in distributed RAM; we use
//     a flop array here to keep the synthesis hint platform-agnostic.
// =============================================================================

module symbol_allowlist
  import risk_pkg::*;
#(
  parameter int NUM_SLOTS = 64
)(
  input  logic                  clk,
  input  logic                  rst_n,

  // Configuration
  input  logic                  cfg_enabled,

  // Slot write interface (driven from host bridge / regmap)
  input  logic                  slot_we,
  input  logic [$clog2(NUM_SLOTS)-1:0] slot_idx,
  input  logic [31:0]           slot_data,

  // Order interface — combinational decision
  input  logic                  order_valid,
  output logic                  order_ready,
  input  order_type_e           order_type,
  input  logic [31:0]           order_symbol_id,
  input  logic                  xfer_accept,

  // Decision
  output logic                  passed,
  output logic                  rejected,

  // Statistics
  output logic [63:0]           total_rejected
);

  // ---------------------------------------------------------------------------
  // Slot storage
  // ---------------------------------------------------------------------------
  logic [31:0] slots [NUM_SLOTS];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int i = 0; i < NUM_SLOTS; i++) begin
        slots[i] <= 32'd0;
      end
    end else if (slot_we) begin
      slots[slot_idx] <= slot_data;
    end
  end

  // ---------------------------------------------------------------------------
  // Lookup (combinational — wide OR-reduce)
  // ---------------------------------------------------------------------------
  logic any_match;
  logic any_active;            // are any non-zero slots populated?

  always_comb begin
    any_match  = 1'b0;
    any_active = 1'b0;
    for (int i = 0; i < NUM_SLOTS; i++) begin
      if (slots[i] != 32'd0) any_active = 1'b1;
      if (slots[i] != 32'd0 && slots[i] == order_symbol_id) any_match = 1'b1;
    end
  end

  logic bypass;
  always_comb begin
    bypass = (!cfg_enabled)
          || (!any_active)                       // empty allowlist → disabled
          || (order_type == ORDER_HEARTBEAT)
          || (!order_valid);

    rejected = (!bypass) && (!any_match);
    passed   = !rejected;
  end

  assign order_ready = 1'b1;

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
