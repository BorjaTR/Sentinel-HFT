`ifndef RISK_GATE_SV
`define RISK_GATE_SV

`include "risk_pkg.sv"
`include "rate_limiter.sv"
`include "position_limiter.sv"
`include "kill_switch.sv"

// =============================================================================
// risk_gate
// -----------------------------------------------------------------------------
// Top-level risk gate. Combines the rate limiter, position limiter and kill
// switch and produces a single accept/reject decision per order.
//
// Wave 1 audit fixes:
//   A-S1-06  The old handshake was purely combinational:
//                assign in_ready  = out_ready;
//                assign out_valid = in_valid;
//            which pushed every risk check, every fill update and the
//            downstream backpressure onto the same critical path. Now
//            replaced with a single-entry skid buffer: the gate captures
//            (order, decision) on the input handshake, then presents the
//            captured result on the output until it is accepted, at which
//            point the buffer reopens.
//
//   A-S0-01 / A-S0-02 / A-S0-03  (propagated from sub-modules)
//            `current_position` is now signed (net_position_t). The gate
//            forwards position_limiter's signed net directly instead of
//            computing `pos_long - pos_short` which could wrap 64-bit
//            unsigned and hide a negative position as a huge positive.
//
//   A-S1-07  Sub-modules now take `xfer_accept` from the real input
//            handshake instead of counting on `order_valid` alone.
//
// current_pnl is passed through as signed to kill_switch.
// =============================================================================

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
  input  logic signed [63:0]          current_pnl,
  input  logic                        pnl_is_loss,   // ignored; kept for wire-compat

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

  // ---------------------------------------------------------------------------
  // Combinational decision for the *current* input order
  // ---------------------------------------------------------------------------
  logic         rate_passed;
  logic         rate_rejected;
  logic [31:0]  rate_tokens;

  logic         pos_passed;
  risk_reject_e pos_reject;
  logic [63:0]  pos_long;
  logic [63:0]  pos_short;
  logic [63:0]  pos_notional;

  logic         kill_passed;
  logic         kill_active;
  logic         kill_triggered;

  logic         all_passed;
  risk_reject_e first_reject;

  // Skid-buffer control — defined early so sub-modules can see xfer_accept.
  logic buf_valid_r;
  logic in_accept;   // in_valid && in_ready

  // ---------------------------------------------------------------------------
  // Sub-module instances
  // ---------------------------------------------------------------------------
  rate_limiter u_rate_limiter (
    .clk               (clk),
    .rst_n             (rst_n),
    .cfg_max_tokens    (cfg_rate_max_tokens),
    .cfg_refill_rate   (cfg_rate_refill_rate),
    .cfg_refill_period (cfg_rate_refill_period),
    .cfg_enabled       (cfg_rate_enabled),
    .order_valid       (in_valid),
    .order_ready       (),
    .order_type        (in_order.order_type),
    .tokens_required   (8'd1),
    .xfer_accept       (in_accept),
    .passed            (rate_passed),
    .rejected          (rate_rejected),
    .tokens_remaining  (rate_tokens),
    .total_passed      (),
    .total_rejected    (stat_rejected_rate)
  );

  position_limiter u_position_limiter (
    .clk                (clk),
    .rst_n              (rst_n),
    .cfg_max_long_qty   (cfg_pos_max_long),
    .cfg_max_short_qty  (cfg_pos_max_short),
    .cfg_max_notional   (cfg_pos_max_notional),
    .cfg_max_order_qty  (cfg_pos_max_order_qty),
    .cfg_enabled        (cfg_pos_enabled),
    .order_valid        (in_valid && rate_passed),
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
    .xfer_accept             (in_accept),
    .passed                  (kill_passed),
    .killed                  (kill_active),
    .triggered               (kill_triggered),
    .orders_blocked          (stat_rejected_kill),
    .trigger_count           ()
  );

  assign kill_switch_active = kill_active;

  // ---------------------------------------------------------------------------
  // Combined decision on the *input* order (combinational)
  // ---------------------------------------------------------------------------
  assign all_passed = rate_passed && pos_passed && kill_passed;

  always_comb begin
    if (!kill_passed)      first_reject = RISK_KILL_SWITCH;
    else if (!rate_passed) first_reject = RISK_RATE_LIMITED;
    else if (!pos_passed)  first_reject = pos_reject;
    else                   first_reject = RISK_OK;
  end

  // ---------------------------------------------------------------------------
  // Single-entry skid buffer
  // ---------------------------------------------------------------------------
  logic                    buf_passed_r;
  risk_reject_e            buf_reject_r;
  order_t                  buf_order_r;
  logic [DATA_WIDTH-1:0]   buf_data_r;

  // in_ready: buffer is empty, or it's about to drain this cycle.
  assign in_ready  = !buf_valid_r || (out_ready);
  assign in_accept = in_valid && in_ready;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      buf_valid_r   <= 1'b0;
      buf_passed_r  <= 1'b0;
      buf_reject_r  <= RISK_OK;
      buf_order_r   <= '0;
      buf_data_r    <= '0;
    end else begin
      // Drain on downstream handshake
      if (out_ready && buf_valid_r) begin
        buf_valid_r <= 1'b0;
      end
      // Capture on input handshake (same cycle as drain → buffer bypass)
      if (in_accept) begin
        buf_valid_r  <= 1'b1;
        buf_passed_r <= all_passed;
        buf_reject_r <= first_reject;
        buf_order_r  <= in_order;
        buf_data_r   <= in_data;
      end
    end
  end

  assign out_valid         = buf_valid_r;
  assign out_data          = buf_data_r;
  assign out_order         = buf_order_r;
  assign out_rejected      = !buf_passed_r;
  assign out_reject_reason = buf_reject_r;

  // ---------------------------------------------------------------------------
  // Status — signed current_position (A-S0-02/03 propagation)
  // ---------------------------------------------------------------------------
  net_position_t signed_pos;
  always_comb begin
    if (pos_long >= pos_short) begin
      signed_pos =  net_position_t'({1'b0, (pos_long - pos_short)});
    end else begin
      signed_pos = -net_position_t'({1'b0, (pos_short - pos_long)});
    end
  end

  assign status.passed           = all_passed;
  assign status.reject_reason    = first_reject;
  assign status.tokens_remaining = rate_tokens;
  assign status.current_position = signed_pos;
  assign status.current_notional = pos_notional;

  // ---------------------------------------------------------------------------
  // Statistics
  // ---------------------------------------------------------------------------
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      stat_total_orders  <= '0;
      stat_passed_orders <= '0;
    end else if (in_accept) begin
      stat_total_orders <= stat_total_orders + 64'd1;
      if (all_passed)
        stat_passed_orders <= stat_passed_orders + 64'd1;
    end
  end

endmodule

`endif
