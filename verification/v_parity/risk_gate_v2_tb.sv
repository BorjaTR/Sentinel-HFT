`ifndef RISK_GATE_V2_TB_SV
`define RISK_GATE_V2_TB_SV

`include "risk_pkg.sv"

// =============================================================================
// risk_gate_v2_tb
// -----------------------------------------------------------------------------
// Cocotb-driven testbench wrapper around risk_gate_v2. The cocotb Python
// driver (drive_corpus.py) writes the configuration registers, then for
// each order in the corpus drives in_valid/in_data/in_order and samples
// out_valid/out_rejected/out_reject_reason.
//
// The wrapper exposes "flat" port names so cocotb can find them by string
// — packed structs (order_t, risk_status_t) are unpacked to their primitive
// fields here. Field widths and bit positions match the packed layout in
// rtl/risk_pkg.sv.
// =============================================================================

module risk_gate_v2_tb
  import risk_pkg::*;
(
  input  logic        clk,
  input  logic        rst_n,

  // Rate limiter
  input  logic [31:0] cfg_rate_max_tokens,
  input  logic [31:0] cfg_rate_refill_rate,
  input  logic [15:0] cfg_rate_refill_period,
  input  logic        cfg_rate_enabled,

  // Position limiter
  input  logic [63:0] cfg_pos_max_long,
  input  logic [63:0] cfg_pos_max_short,
  input  logic [63:0] cfg_pos_max_notional,
  input  logic [63:0] cfg_pos_max_order_qty,
  input  logic        cfg_pos_enabled,

  // Kill switch
  input  logic        cfg_kill_armed,
  input  logic        cfg_kill_auto_enabled,
  input  logic [63:0] cfg_kill_loss_threshold,
  input  logic        cmd_kill_trigger,
  input  logic        cmd_kill_reset,

  // Fat finger
  input  logic        cfg_ff_enabled,
  input  logic [15:0] cfg_ff_band_bps,
  input  logic [63:0] cfg_ff_ref_price,

  // Allowlist
  input  logic        cfg_allowlist_enabled,
  input  logic        slot_we,
  input  logic [5:0]  slot_idx,
  input  logic [31:0] slot_data,

  // Order in (flat-port form of order_t)
  input  logic        in_valid,
  output logic        in_ready,
  input  logic [63:0] in_order_id,
  input  logic [31:0] in_order_symbol,
  input  logic [1:0]  in_order_side,
  input  logic [3:0]  in_order_type,
  input  logic [63:0] in_order_qty,
  input  logic [63:0] in_order_price,
  input  logic [63:0] in_order_notional,

  // P&L (signed) + fills
  input  logic signed [63:0] current_pnl,
  input  logic        fill_valid,
  input  logic [1:0]  fill_side,
  input  logic [63:0] fill_qty,
  input  logic [63:0] fill_notional,

  // Decision out
  output logic        out_valid,
  input  logic        out_ready,
  output logic        out_rejected,
  output logic [7:0]  out_reject_reason,

  // Stats
  output logic [63:0] stat_total_orders,
  output logic [63:0] stat_passed_orders,
  output logic [63:0] stat_rejected_rate,
  output logic [63:0] stat_rejected_position,
  output logic [63:0] stat_rejected_kill,
  output logic [63:0] stat_rejected_ff,
  output logic [63:0] stat_rejected_allowlist
);

  // Pack flat ports into the order_t struct expected by risk_gate_v2.
  order_t       in_order_pk;
  always_comb begin
    in_order_pk.order_id   = in_order_id;
    in_order_pk.symbol_id  = in_order_symbol;
    in_order_pk.side       = order_side_e'(in_order_side);
    in_order_pk.order_type = order_type_e'(in_order_type);
    in_order_pk.quantity   = in_order_qty;
    in_order_pk.price      = in_order_price;
    in_order_pk.notional   = in_order_notional;
  end

  order_t       out_order_pk;
  risk_status_t status_pk;
  risk_reject_e reject_pk;
  logic         kill_active_unused;

  risk_gate_v2 #(
    .DATA_WIDTH(64),
    .ALLOWLIST_SLOTS(64)
  ) u_dut (
    .clk                        (clk),
    .rst_n                      (rst_n),
    .cfg_rate_max_tokens        (cfg_rate_max_tokens),
    .cfg_rate_refill_rate       (cfg_rate_refill_rate),
    .cfg_rate_refill_period     (cfg_rate_refill_period),
    .cfg_rate_enabled           (cfg_rate_enabled),
    .cfg_pos_max_long           (cfg_pos_max_long),
    .cfg_pos_max_short          (cfg_pos_max_short),
    .cfg_pos_max_notional       (cfg_pos_max_notional),
    .cfg_pos_max_order_qty      (cfg_pos_max_order_qty),
    .cfg_pos_enabled            (cfg_pos_enabled),
    .cfg_kill_armed             (cfg_kill_armed),
    .cfg_kill_auto_enabled      (cfg_kill_auto_enabled),
    .cfg_kill_loss_threshold    (cfg_kill_loss_threshold),
    .cmd_kill_trigger           (cmd_kill_trigger),
    .cmd_kill_reset             (cmd_kill_reset),
    .cfg_ff_enabled             (cfg_ff_enabled),
    .cfg_ff_band_bps            (cfg_ff_band_bps),
    .cfg_ff_ref_price           (cfg_ff_ref_price),
    .cfg_allowlist_enabled      (cfg_allowlist_enabled),
    .slot_we                    (slot_we),
    .slot_idx                   (slot_idx),
    .slot_data                  (slot_data),
    .in_valid                   (in_valid),
    .in_ready                   (in_ready),
    .in_data                    (64'd0),
    .in_order                   (in_order_pk),
    .out_valid                  (out_valid),
    .out_ready                  (out_ready),
    .out_data                   (),
    .out_order                  (out_order_pk),
    .out_rejected               (out_rejected),
    .out_reject_reason          (reject_pk),
    .fill_valid                 (fill_valid),
    .fill_side                  (order_side_e'(fill_side)),
    .fill_qty                   (fill_qty),
    .fill_notional              (fill_notional),
    .current_pnl                (current_pnl),
    .pnl_is_loss                (1'b0),
    .status                     (status_pk),
    .kill_switch_active         (kill_active_unused),
    .stat_total_orders          (stat_total_orders),
    .stat_passed_orders         (stat_passed_orders),
    .stat_rejected_rate         (stat_rejected_rate),
    .stat_rejected_position     (stat_rejected_position),
    .stat_rejected_kill         (stat_rejected_kill),
    .stat_rejected_ff           (stat_rejected_ff),
    .stat_rejected_allowlist    (stat_rejected_allowlist)
  );

  assign out_reject_reason = reject_pk;

endmodule

`endif
