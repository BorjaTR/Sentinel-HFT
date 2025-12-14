`timescale 1ns / 1ps

`include "risk_pkg.sv"
`include "risk_gate.sv"

module tb_risk_gate
  import risk_pkg::*;
#(
  parameter int DATA_WIDTH = 64
)(
  input  logic        clk,
  input  logic        rst_n,

  // Configuration inputs (directly exposed for C++ control)
  input  logic [31:0] cfg_rate_max_tokens,
  input  logic [31:0] cfg_rate_refill_rate,
  input  logic [15:0] cfg_rate_refill_period,
  input  logic        cfg_rate_enabled,

  input  logic [63:0] cfg_pos_max_long,
  input  logic [63:0] cfg_pos_max_short,
  input  logic [63:0] cfg_pos_max_notional,
  input  logic [63:0] cfg_pos_max_order_qty,
  input  logic        cfg_pos_enabled,

  input  logic        cfg_kill_armed,
  input  logic        cfg_kill_auto_enabled,
  input  logic [63:0] cfg_kill_loss_threshold,
  input  logic        cmd_kill_trigger,
  input  logic        cmd_kill_reset,

  // Order input (unpacked for C++ access)
  input  logic        in_valid,
  output logic        in_ready,
  input  logic [DATA_WIDTH-1:0] in_data,
  input  logic [63:0] in_order_id,
  input  logic [31:0] in_symbol_id,
  input  logic [1:0]  in_side,
  input  logic [3:0]  in_order_type,
  input  logic [63:0] in_quantity,
  input  logic [63:0] in_price,
  input  logic [63:0] in_notional,

  // Order output
  output logic        out_valid,
  input  logic        out_ready,
  output logic [DATA_WIDTH-1:0] out_data,
  output logic        out_rejected,
  output logic [7:0]  out_reject_reason,

  // Fill input
  input  logic        fill_valid,
  input  logic [1:0]  fill_side,
  input  logic [63:0] fill_qty,
  input  logic [63:0] fill_notional,

  // P&L input
  input  logic [63:0] current_pnl,
  input  logic        pnl_is_loss,

  // Status outputs
  output logic        status_passed,
  output logic [31:0] status_tokens,
  output logic [63:0] status_position,
  output logic [63:0] status_notional,
  output logic        kill_switch_active,

  // Statistics
  output logic [63:0] stat_total,
  output logic [63:0] stat_passed,
  output logic [63:0] stat_rejected_rate,
  output logic [63:0] stat_rejected_pos,
  output logic [63:0] stat_rejected_kill
);

  // Pack order struct
  order_t in_order_packed;
  assign in_order_packed.order_id   = in_order_id;
  assign in_order_packed.symbol_id  = in_symbol_id;
  assign in_order_packed.side       = order_side_e'(in_side);
  assign in_order_packed.order_type = order_type_e'(in_order_type);
  assign in_order_packed.quantity   = in_quantity;
  assign in_order_packed.price      = in_price;
  assign in_order_packed.notional   = in_notional;

  // Internal signals
  order_t out_order_packed;
  risk_status_t status;
  risk_reject_e reject_reason;

  // DUT
  risk_gate #(
    .DATA_WIDTH(DATA_WIDTH)
  ) u_risk_gate (
    .clk                    (clk),
    .rst_n                  (rst_n),

    .cfg_rate_max_tokens    (cfg_rate_max_tokens),
    .cfg_rate_refill_rate   (cfg_rate_refill_rate),
    .cfg_rate_refill_period (cfg_rate_refill_period),
    .cfg_rate_enabled       (cfg_rate_enabled),

    .cfg_pos_max_long       (cfg_pos_max_long),
    .cfg_pos_max_short      (cfg_pos_max_short),
    .cfg_pos_max_notional   (cfg_pos_max_notional),
    .cfg_pos_max_order_qty  (cfg_pos_max_order_qty),
    .cfg_pos_enabled        (cfg_pos_enabled),

    .cfg_kill_armed         (cfg_kill_armed),
    .cfg_kill_auto_enabled  (cfg_kill_auto_enabled),
    .cfg_kill_loss_threshold(cfg_kill_loss_threshold),
    .cmd_kill_trigger       (cmd_kill_trigger),
    .cmd_kill_reset         (cmd_kill_reset),

    .in_valid               (in_valid),
    .in_ready               (in_ready),
    .in_data                (in_data),
    .in_order               (in_order_packed),

    .out_valid              (out_valid),
    .out_ready              (out_ready),
    .out_data               (out_data),
    .out_order              (out_order_packed),
    .out_rejected           (out_rejected),
    .out_reject_reason      (reject_reason),

    .fill_valid             (fill_valid),
    .fill_side              (order_side_e'(fill_side)),
    .fill_qty               (fill_qty),
    .fill_notional          (fill_notional),

    .current_pnl            (current_pnl),
    .pnl_is_loss            (pnl_is_loss),

    .status                 (status),
    .kill_switch_active     (kill_switch_active),

    .stat_total_orders      (stat_total),
    .stat_passed_orders     (stat_passed),
    .stat_rejected_rate     (stat_rejected_rate),
    .stat_rejected_position (stat_rejected_pos),
    .stat_rejected_kill     (stat_rejected_kill)
  );

  // Unpack outputs
  assign out_reject_reason = reject_reason;
  assign status_passed     = status.passed;
  assign status_tokens     = status.tokens_remaining;
  assign status_position   = status.current_position;
  assign status_notional   = status.current_notional;

endmodule
