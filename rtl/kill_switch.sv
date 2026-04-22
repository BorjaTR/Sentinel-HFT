`ifndef KILL_SWITCH_SV
`define KILL_SWITCH_SV

`include "risk_pkg.sv"

// =============================================================================
// kill_switch
// -----------------------------------------------------------------------------
// Sticky kill switch for the risk gate.
//
// Wave 1 audit fixes:
//   A-S0-01  `passed` used to be `!cfg_armed || !kill_active`. That flipped
//            the polarity of "armed": once the switch was disarmed the
//            gate passed even if `trigger_latched` had fired earlier. The
//            correct semantics are "once tripped, reject until explicit
//            reset, regardless of whether the arm bit is still held".
//            Fixed: `passed = !trigger_latched`. Re-arming is done by
//            pulsing `cmd_reset`, which is still the only way to clear
//            the latched state.
//
//   A-S1-08  `current_pnl` was declared unsigned with a `pnl_is_loss`
//            companion sign bit. That required the host to do sign
//            management and was easy to get wrong. Replaced with a
//            `logic signed [63:0]` P&L input; the auto-trigger now fires
//            on `current_pnl <= -cfg_loss_threshold` (loss threshold is
//            an unsigned magnitude — the limit is "drop more than N").
//            The old `pnl_is_loss` port is kept as a no-op for backward
//            compatibility but is ignored by the trigger logic.
//
// `orders_blocked` now counts on true transfer acceptance (xfer_accept)
// driven by the parent risk_gate, consistent with the other sub-gates.
// =============================================================================

module kill_switch
  import risk_pkg::*;
(
  input  logic              clk,
  input  logic              rst_n,

  // Configuration / Control
  input  logic              cfg_armed,          // Kill switch is armed (edge-triggered semantics disabled)
  input  logic              cmd_trigger,        // Software trigger (pulse)
  input  logic              cmd_reset,          // Reset kill switch (pulse)

  // Optional: Auto-trigger on loss threshold
  input  logic              cfg_auto_trigger_enabled,
  input  logic [63:0]       cfg_loss_threshold, // unsigned magnitude
  input  logic signed [63:0] current_pnl,       // signed: positive = profit, negative = loss
  input  logic              pnl_is_loss,        // kept for wire-compat; ignored

  // Order input
  input  logic              order_valid,
  output logic              order_ready,
  input  logic              xfer_accept,        // true transfer into gate this cycle

  // Output
  output logic              passed,
  output logic              killed,             // currently in kill state
  output logic              triggered,          // sticky: has ever triggered since reset

  // Statistics
  output logic [63:0]       orders_blocked,
  output logic [31:0]       trigger_count
);

  // Silence synth lint on the deliberately-unused compatibility port.
  // verilator lint_off UNUSED
  wire _unused_pnl_is_loss = pnl_is_loss;
  // verilator lint_on UNUSED

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  logic kill_active;      // live gating state
  logic trigger_latched;  // sticky: fires once, clears only on cmd_reset

  assign killed    = kill_active;
  assign triggered = trigger_latched;

  // ---------------------------------------------------------------------------
  // Auto-trigger on loss threshold
  // ---------------------------------------------------------------------------
  // cfg_loss_threshold is an unsigned magnitude representing "max tolerable
  // loss". The switch auto-fires when realised loss exceeds this magnitude,
  // i.e. current_pnl <= -cfg_loss_threshold (treating current_pnl as signed).
  logic signed [64:0] neg_threshold;
  logic               auto_trigger;
  logic               any_trigger;

  assign neg_threshold = -($signed({1'b0, cfg_loss_threshold}));
  assign auto_trigger  = cfg_auto_trigger_enabled &&
                         ($signed({current_pnl[63], current_pnl}) <= neg_threshold);

  assign any_trigger = cmd_trigger || auto_trigger;

  // ---------------------------------------------------------------------------
  // State machine
  // ---------------------------------------------------------------------------
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      kill_active     <= 1'b0;
      trigger_latched <= 1'b0;
      trigger_count   <= '0;
    end else begin
      if (cmd_reset) begin
        kill_active     <= 1'b0;
        trigger_latched <= 1'b0;
      end
      else if (any_trigger && cfg_armed && !trigger_latched) begin
        kill_active     <= 1'b1;
        trigger_latched <= 1'b1;
        trigger_count   <= trigger_count + 32'd1;
      end
    end
  end

  // ---------------------------------------------------------------------------
  // Decision
  // ---------------------------------------------------------------------------
  // A-S0-01 fix: once triggered, reject until reset.
  assign passed      = !trigger_latched;
  assign order_ready = 1'b1;

  // ---------------------------------------------------------------------------
  // Statistics (gated on true transfer — A-S1-07-aligned)
  // ---------------------------------------------------------------------------
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      orders_blocked <= '0;
    end else if (xfer_accept && trigger_latched) begin
      orders_blocked <= orders_blocked + 64'd1;
    end
  end

endmodule

`endif
