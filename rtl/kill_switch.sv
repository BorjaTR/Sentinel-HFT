`ifndef KILL_SWITCH_SV
`define KILL_SWITCH_SV

`include "risk_pkg.sv"

module kill_switch
  import risk_pkg::*;
(
  input  logic        clk,
  input  logic        rst_n,

  // Configuration / Control
  input  logic        cfg_armed,          // Kill switch is active
  input  logic        cmd_trigger,        // Software trigger (pulse)
  input  logic        cmd_reset,          // Reset kill switch (pulse)

  // Optional: Auto-trigger on loss threshold
  input  logic        cfg_auto_trigger_enabled,
  input  logic [63:0] cfg_loss_threshold,
  input  logic [63:0] current_pnl,        // Current P&L (signed, but use as unsigned for simplicity)
  input  logic        pnl_is_loss,        // Indicates current_pnl represents a loss

  // Order input
  input  logic        order_valid,
  output logic        order_ready,

  // Output
  output logic        passed,
  output logic        killed,             // Kill switch is currently active
  output logic        triggered,          // Sticky: kill switch has been triggered

  // Statistics
  output logic [63:0] orders_blocked,
  output logic [31:0] trigger_count
);

  // =========================================================================
  // Kill Switch State
  // =========================================================================

  logic kill_active;
  logic trigger_latched;  // Sticky trigger

  assign killed    = kill_active;
  assign triggered = trigger_latched;

  // =========================================================================
  // Trigger Detection
  // =========================================================================

  logic auto_trigger;
  logic any_trigger;

  // Auto-trigger on loss threshold breach
  assign auto_trigger = cfg_auto_trigger_enabled &&
                        pnl_is_loss &&
                        (current_pnl >= cfg_loss_threshold);

  // Any trigger source
  assign any_trigger = cmd_trigger || auto_trigger;

  // =========================================================================
  // State Machine
  // =========================================================================

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      kill_active     <= 1'b0;
      trigger_latched <= 1'b0;
      trigger_count   <= '0;
    end else begin
      // Reset command clears the kill switch
      if (cmd_reset) begin
        kill_active     <= 1'b0;
        trigger_latched <= 1'b0;
      end
      // Trigger command activates (if armed)
      else if (any_trigger && cfg_armed) begin
        kill_active     <= 1'b1;
        trigger_latched <= 1'b1;
        trigger_count   <= trigger_count + 1;
      end
    end
  end

  // =========================================================================
  // Output Logic
  // =========================================================================

  // Pass only if not armed or not killed
  assign passed = !cfg_armed || !kill_active;
  assign order_ready = 1'b1;

  // =========================================================================
  // Statistics
  // =========================================================================

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      orders_blocked <= '0;
    end else if (order_valid && kill_active) begin
      orders_blocked <= orders_blocked + 1;
    end
  end

endmodule

`endif
