`ifndef RISK_GATE_SV
`define RISK_GATE_SV

`include "risk_pkg.sv"
`include "rate_limiter.sv"
`include "position_limiter.sv"
`include "kill_switch.sv"

module risk_gate
  import risk_pkg::*;
#(
  parameter int DATA_WIDTH = 64
)(
  input  logic                        clk,
  input  logic                        rst_n,

  // ===== Configuration =====
  // Rate limiter
  input  logic [31:0]                 cfg_rate_max_tokens,
  input  logic [31:0]                 cfg_rate_refill_rate,
  input  logic [15:0]                 cfg_rate_refill_period,
  input  logic                        cfg_rate_enabled,

  // Position limiter
  input  logic [63:0]                 cfg_pos_max_long,
  input  logic [63:0]                 cfg_pos_max_short,
  input  logic [63:0]                 cfg_pos_max_notional,
  input  logic [63:0]                 cfg_pos_max_order_qty,
  input  logic                        cfg_pos_enabled,

  // Kill switch
  input  logic                        cfg_kill_armed,
  input  logic                        cfg_kill_auto_enabled,
  input  logic [63:0]                 cfg_kill_loss_threshold,
  input  logic                        cmd_kill_trigger,
  input  logic                        cmd_kill_reset,

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

  // ===== P&L Input (for kill switch) =====
  input  logic [63:0]                 current_pnl,
  input  logic                        pnl_is_loss,

  // ===== Status Outputs =====
  output risk_status_t                status,
  output logic                        kill_switch_active,

  // ===== Statistics =====
  output logic [63:0]                 stat_total_orders,
  output logic [63:0]                 stat_passed_orders,
  output logic [63:0]                 stat_rejected_rate,
  output logic [63:0]                 stat_rejected_position,
  output logic [63:0]                 stat_rejected_kill
);

  // =========================================================================
  // Internal Signals
  // =========================================================================

  // Rate limiter
  logic rate_passed;
  logic rate_rejected;
  logic [31:0] rate_tokens;

  // Position limiter
  logic pos_passed;
  risk_reject_e pos_reject;
  logic [63:0] pos_long;
  logic [63:0] pos_short;
  logic [63:0] pos_notional;

  // Kill switch
  logic kill_passed;
  logic kill_active;
  logic kill_triggered;

  // Combined result
  logic all_passed;
  risk_reject_e first_reject;

  // =========================================================================
  // Rate Limiter Instance
  // =========================================================================

  rate_limiter u_rate_limiter (
    .clk               (clk),
    .rst_n             (rst_n),
    .cfg_max_tokens    (cfg_rate_max_tokens),
    .cfg_refill_rate   (cfg_rate_refill_rate),
    .cfg_refill_period (cfg_rate_refill_period),
    .cfg_enabled       (cfg_rate_enabled),
    .order_valid       (in_valid),
    .order_ready       (),  // Rate limiter doesn't backpressure
    .order_type        (in_order.order_type),
    .tokens_required   (8'd1),
    .passed            (rate_passed),
    .rejected          (rate_rejected),
    .tokens_remaining  (rate_tokens),
    .total_passed      (),
    .total_rejected    (stat_rejected_rate)
  );

  // =========================================================================
  // Position Limiter Instance
  // =========================================================================

  position_limiter u_position_limiter (
    .clk                (clk),
    .rst_n              (rst_n),
    .cfg_max_long_qty   (cfg_pos_max_long),
    .cfg_max_short_qty  (cfg_pos_max_short),
    .cfg_max_notional   (cfg_pos_max_notional),
    .cfg_max_order_qty  (cfg_pos_max_order_qty),
    .cfg_enabled        (cfg_pos_enabled),
    .order_valid        (in_valid && rate_passed),  // Only check if rate passed
    .order_ready        (),
    .order_side         (in_order.side),
    .order_type         (in_order.order_type),
    .order_qty          (in_order.quantity),
    .order_notional     (in_order.notional),
    .fill_valid         (fill_valid),
    .fill_side          (fill_side),
    .fill_qty           (fill_qty),
    .fill_notional      (fill_notional),
    .passed             (pos_passed),
    .reject_reason      (pos_reject),
    .current_long_qty   (pos_long),
    .current_short_qty  (pos_short),
    .current_notional   (pos_notional),
    .total_passed       (),
    .total_rejected     (stat_rejected_position)
  );

  // =========================================================================
  // Kill Switch Instance
  // =========================================================================

  kill_switch u_kill_switch (
    .clk                     (clk),
    .rst_n                   (rst_n),
    .cfg_armed               (cfg_kill_armed),
    .cmd_trigger             (cmd_kill_trigger),
    .cmd_reset               (cmd_kill_reset),
    .cfg_auto_trigger_enabled(cfg_kill_auto_enabled),
    .cfg_loss_threshold      (cfg_kill_loss_threshold),
    .current_pnl             (current_pnl),
    .pnl_is_loss             (pnl_is_loss),
    .order_valid             (in_valid),
    .order_ready             (),
    .passed                  (kill_passed),
    .killed                  (kill_active),
    .triggered               (kill_triggered),
    .orders_blocked          (stat_rejected_kill),
    .trigger_count           ()
  );

  assign kill_switch_active = kill_active;

  // =========================================================================
  // Combined Decision Logic
  // =========================================================================

  // Order passes only if ALL checks pass
  assign all_passed = rate_passed && pos_passed && kill_passed;

  // Determine first (highest priority) reject reason
  always_comb begin
    if (!kill_passed) begin
      first_reject = RISK_KILL_SWITCH;
    end else if (!rate_passed) begin
      first_reject = RISK_RATE_LIMITED;
    end else if (!pos_passed) begin
      first_reject = pos_reject;
    end else begin
      first_reject = RISK_OK;
    end
  end

  // =========================================================================
  // Output Logic
  // =========================================================================

  // Simple pass-through timing (combinational decision, registered output optional)
  assign in_ready = out_ready;  // Backpressure from downstream

  assign out_valid         = in_valid;
  assign out_data          = in_data;
  assign out_order         = in_order;
  assign out_rejected      = !all_passed;
  assign out_reject_reason = first_reject;

  // Status output
  assign status.passed           = all_passed;
  assign status.reject_reason    = first_reject;
  assign status.tokens_remaining = rate_tokens;
  assign status.current_position = pos_long - pos_short;  // Net position
  assign status.current_notional = pos_notional;

  // =========================================================================
  // Statistics
  // =========================================================================

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      stat_total_orders  <= '0;
      stat_passed_orders <= '0;
    end else if (in_valid && in_ready) begin
      stat_total_orders <= stat_total_orders + 1;
      if (all_passed) begin
        stat_passed_orders <= stat_passed_orders + 1;
      end
    end
  end

endmodule

`endif
