`ifndef RISK_GATE_V2_SV
`define RISK_GATE_V2_SV

`include "risk_pkg.sv"
`include "risk_gate.sv"
`include "fat_finger_band.sv"
`include "symbol_allowlist.sv"

// =============================================================================
// risk_gate_v2
// -----------------------------------------------------------------------------
// Phase-1 ship target: composes the existing risk_gate (rate / position /
// kill) with the two new Phase-1 modules (fat_finger_band, symbol_allowlist)
// to produce the full 7-rule decision set defined by the golden in
// sentinel_hft/golden/risk_gate.py.
//
// Why a composer instead of editing risk_gate.sv?
//   - risk_gate.sv is in active use by the existing testbench
//     (rtl/tb_risk_gate.sv) and by sentinel_shell_v12. Editing its port
//     list would force changes everywhere those modules instantiate it.
//   - A composer mirrors the established versioning pattern in this
//     codebase (see sentinel_shell_v12 vs sentinel_shell).
//   - The composer encodes the Phase-1 reject precedence (kill > rate >
//     pos-family > fat-finger > allowlist) explicitly in one place, which
//     is exactly the spec contract A-Spec / V-Parity verify.
//
// Inputs:
//   - All existing risk_gate ports (passed through verbatim).
//   - Fat-finger config + reference price.
//   - Allowlist config + slot-write interface (host bridge writes slots
//     through the regmap at block 0x0500).
//
// Decision composition:
//   v1 = inner risk_gate decision (kill / rate / pos)
//   v2 = fat_finger decision
//   v3 = allowlist decision
//   if v1.rejected:                  reject with v1.reject_reason
//   else if !v2.passed (rejected):   reject with RISK_FAT_FINGER (8'h07)
//   else if !v3.passed (rejected):   reject with RISK_ALLOWLIST_BLOCK (8'h08)
//   else:                            pass
//
// The skid buffer + AXI-Stream contract come from the inner risk_gate
// which already implements them (see Wave-1 audit fix A-S1-06). The new
// rules are evaluated combinationally on the same input order in
// parallel; the composer just OR-stacks their reject signals onto the
// already-skid-buffered output of risk_gate.
// =============================================================================

module risk_gate_v2
  import risk_pkg::*;
#(
  parameter int DATA_WIDTH = 64,
  parameter int ALLOWLIST_SLOTS = 64
)(
  input  logic                        clk,
  input  logic                        rst_n,

  // ===== Existing risk_gate config (rate / position / kill) =====
  input  logic [31:0]                 cfg_rate_max_tokens,
  input  logic [31:0]                 cfg_rate_refill_rate,
  input  logic [15:0]                 cfg_rate_refill_period,
  input  logic                        cfg_rate_enabled,

  input  logic [63:0]                 cfg_pos_max_long,
  input  logic [63:0]                 cfg_pos_max_short,
  input  logic [63:0]                 cfg_pos_max_notional,
  input  logic [63:0]                 cfg_pos_max_order_qty,
  input  logic                        cfg_pos_enabled,

  input  logic                        cfg_kill_armed,
  input  logic                        cfg_kill_auto_enabled,
  input  logic [63:0]                 cfg_kill_loss_threshold,
  input  logic                        cmd_kill_trigger,
  input  logic                        cmd_kill_reset,

  // ===== Phase-1 new modules =====
  // Fat-finger band
  input  logic                        cfg_ff_enabled,
  input  logic [15:0]                 cfg_ff_band_bps,
  input  logic [63:0]                 cfg_ff_ref_price,

  // Symbol allowlist
  input  logic                        cfg_allowlist_enabled,
  input  logic                        slot_we,
  input  logic [$clog2(ALLOWLIST_SLOTS)-1:0] slot_idx,
  input  logic [31:0]                 slot_data,

  // ===== Order Input Stream =====
  input  logic                        in_valid,
  output logic                        in_ready,
  input  logic [DATA_WIDTH-1:0]       in_data,
  input  order_t                      in_order,

  // ===== Order Output Stream =====
  output logic                        out_valid,
  input  logic                        out_ready,
  output logic [DATA_WIDTH-1:0]       out_data,
  output order_t                      out_order,
  output logic                        out_rejected,
  output risk_reject_e                out_reject_reason,

  // ===== Fill Notifications =====
  input  logic                        fill_valid,
  input  order_side_e                 fill_side,
  input  logic [63:0]                 fill_qty,
  input  logic [63:0]                 fill_notional,

  // ===== P&L Input =====
  input  logic signed [63:0]          current_pnl,
  input  logic                        pnl_is_loss,

  // ===== Status Outputs =====
  output risk_status_t                status,
  output logic                        kill_switch_active,

  // ===== Statistics =====
  output logic [63:0]                 stat_total_orders,
  output logic [63:0]                 stat_passed_orders,
  output logic [63:0]                 stat_rejected_rate,
  output logic [63:0]                 stat_rejected_position,
  output logic [63:0]                 stat_rejected_kill,
  output logic [63:0]                 stat_rejected_ff,
  output logic [63:0]                 stat_rejected_allowlist
);

  // ---------------------------------------------------------------------------
  // Inner risk_gate (existing)
  // ---------------------------------------------------------------------------
  logic        inner_out_valid;
  logic        inner_out_ready;
  logic [DATA_WIDTH-1:0] inner_out_data;
  order_t      inner_out_order;
  logic        inner_out_rejected;
  risk_reject_e inner_out_reject_reason;

  risk_gate #(
    .DATA_WIDTH(DATA_WIDTH)
  ) u_inner (
    .clk                      (clk),
    .rst_n                    (rst_n),
    .cfg_rate_max_tokens      (cfg_rate_max_tokens),
    .cfg_rate_refill_rate     (cfg_rate_refill_rate),
    .cfg_rate_refill_period   (cfg_rate_refill_period),
    .cfg_rate_enabled         (cfg_rate_enabled),
    .cfg_pos_max_long         (cfg_pos_max_long),
    .cfg_pos_max_short        (cfg_pos_max_short),
    .cfg_pos_max_notional     (cfg_pos_max_notional),
    .cfg_pos_max_order_qty    (cfg_pos_max_order_qty),
    .cfg_pos_enabled          (cfg_pos_enabled),
    .cfg_kill_armed           (cfg_kill_armed),
    .cfg_kill_auto_enabled    (cfg_kill_auto_enabled),
    .cfg_kill_loss_threshold  (cfg_kill_loss_threshold),
    .cmd_kill_trigger         (cmd_kill_trigger),
    .cmd_kill_reset           (cmd_kill_reset),
    .in_valid                 (in_valid),
    .in_ready                 (in_ready),
    .in_data                  (in_data),
    .in_order                 (in_order),
    .out_valid                (inner_out_valid),
    .out_ready                (inner_out_ready),
    .out_data                 (inner_out_data),
    .out_order                (inner_out_order),
    .out_rejected             (inner_out_rejected),
    .out_reject_reason        (inner_out_reject_reason),
    .fill_valid               (fill_valid),
    .fill_side                (fill_side),
    .fill_qty                 (fill_qty),
    .fill_notional            (fill_notional),
    .current_pnl              (current_pnl),
    .pnl_is_loss              (pnl_is_loss),
    .status                   (status),
    .kill_switch_active       (kill_switch_active),
    .stat_total_orders        (stat_total_orders),
    .stat_passed_orders       (stat_passed_orders),
    .stat_rejected_rate       (stat_rejected_rate),
    .stat_rejected_position   (stat_rejected_position),
    .stat_rejected_kill       (stat_rejected_kill)
  );

  // ---------------------------------------------------------------------------
  // Phase-1 new modules — combinational decisions on the *current input* order
  //
  // These modules do not back-pressure or buffer; they simply emit a
  // combinational rejected/passed pair driven by in_order. Their decisions
  // are joined to the inner gate's decision at the OUTPUT side via the
  // composer below.
  // ---------------------------------------------------------------------------
  logic ff_rejected, ff_passed;
  logic al_rejected, al_passed;

  // ff/al accept_xfer fires on the same handshake the inner gate uses.
  logic in_xfer_accept;
  assign in_xfer_accept = in_valid && in_ready;

  fat_finger_band u_ff (
    .clk            (clk),
    .rst_n          (rst_n),
    .cfg_enabled    (cfg_ff_enabled),
    .cfg_band_bps   (cfg_ff_band_bps),
    .cfg_ref_price  (cfg_ff_ref_price),
    .order_valid    (in_valid),
    .order_ready    (),
    .order_type     (in_order.order_type),
    .order_price    (in_order.price),
    .xfer_accept    (in_xfer_accept),
    .passed         (ff_passed),
    .rejected       (ff_rejected),
    .total_rejected (stat_rejected_ff)
  );

  symbol_allowlist #(
    .NUM_SLOTS(ALLOWLIST_SLOTS)
  ) u_al (
    .clk             (clk),
    .rst_n           (rst_n),
    .cfg_enabled     (cfg_allowlist_enabled),
    .slot_we         (slot_we),
    .slot_idx        (slot_idx),
    .slot_data       (slot_data),
    .order_valid     (in_valid),
    .order_ready     (),
    .order_type      (in_order.order_type),
    .order_symbol_id (in_order.symbol_id),
    .xfer_accept     (in_xfer_accept),
    .passed          (al_passed),
    .rejected        (al_rejected),
    .total_rejected  (stat_rejected_allowlist)
  );

  // ---------------------------------------------------------------------------
  // Skid-buffered new-module decisions (one cycle latency to align with
  // the inner gate's skid buffer)
  // ---------------------------------------------------------------------------
  logic ff_rejected_r, al_rejected_r;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      ff_rejected_r <= 1'b0;
      al_rejected_r <= 1'b0;
    end else if (in_xfer_accept) begin
      ff_rejected_r <= ff_rejected;
      al_rejected_r <= al_rejected;
    end
  end

  // ---------------------------------------------------------------------------
  // Composer — first-fail with full Phase-1 precedence
  //
  //   1. inner reject (kill > rate > pos-family) wins outright.
  //   2. else fat-finger.
  //   3. else allowlist.
  //   4. else pass.
  // ---------------------------------------------------------------------------
  always_comb begin
    if (inner_out_rejected) begin
      out_rejected      = 1'b1;
      out_reject_reason = inner_out_reject_reason;
    end else if (ff_rejected_r) begin
      out_rejected      = 1'b1;
      out_reject_reason = RISK_FAT_FINGER;
    end else if (al_rejected_r) begin
      out_rejected      = 1'b1;
      out_reject_reason = RISK_ALLOWLIST_BLOCK;
    end else begin
      out_rejected      = 1'b0;
      out_reject_reason = RISK_OK;
    end
  end

  assign out_valid       = inner_out_valid;
  assign inner_out_ready = out_ready;
  assign out_data        = inner_out_data;
  assign out_order       = inner_out_order;

endmodule

`endif
