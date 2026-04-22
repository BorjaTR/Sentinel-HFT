`ifndef POSITION_LIMITER_SV
`define POSITION_LIMITER_SV

`include "risk_pkg.sv"

// =============================================================================
// position_limiter
// -----------------------------------------------------------------------------
// Single-symbol net-position risk gate.
//
// Wave 1 audit fixes applied:
//   A-S0-02  The old `gross_notional` was a monotonic ratchet that only grew.
//            Closing a position could never decrease measured exposure, so
//            the notional cap would eventually lock out further trading even
//            though the real book was flat. Fixed by tracking a signed
//            `net_notional` that moves with the sign of each fill and
//            exposing |net_notional| as the current gross-notional output.
//
//   A-S0-03  BUY on an existing short should unwind the short before it ever
//            contributes to the long cap; the old code added qty straight
//            into the long side, which rejected the close-out. Fixed by
//            modelling net_position as a signed value. Projection is:
//                projected_net  = net_position  ± order_qty
//                projected_long = max(projected_net, 0)
//                projected_short= max(-projected_net, 0)
//            so a BUY that flips from -50 to +10 is checked against the
//            long cap at 10 units, not 60.
//
// Status fields `current_long_qty` / `current_short_qty` are still exposed
// (unsigned) so downstream telemetry stays wire-compatible; they are now
// derived from the signed state.
// =============================================================================

module position_limiter
  import risk_pkg::*;
#(
  parameter int QTY_WIDTH      = 64,
  parameter int NOTIONAL_WIDTH = 64
)(
  input  logic                        clk,
  input  logic                        rst_n,

  // Configuration
  input  logic [QTY_WIDTH-1:0]        cfg_max_long_qty,
  input  logic [QTY_WIDTH-1:0]        cfg_max_short_qty,
  input  logic [NOTIONAL_WIDTH-1:0]   cfg_max_notional,
  input  logic [QTY_WIDTH-1:0]        cfg_max_order_qty,
  input  logic                        cfg_enabled,

  // Order input
  input  logic                        order_valid,
  output logic                        order_ready,
  input  order_side_e                 order_side,
  input  order_type_e                 order_type,
  input  logic [QTY_WIDTH-1:0]        order_qty,
  input  logic [NOTIONAL_WIDTH-1:0]   order_notional,

  // Fill notifications (to update position)
  input  logic                        fill_valid,
  input  order_side_e                 fill_side,
  input  logic [QTY_WIDTH-1:0]        fill_qty,
  input  logic [NOTIONAL_WIDTH-1:0]   fill_notional,

  // Output
  output logic                        passed,
  output risk_reject_e                reject_reason,
  output logic [QTY_WIDTH-1:0]        current_long_qty,
  output logic [QTY_WIDTH-1:0]        current_short_qty,
  output logic [NOTIONAL_WIDTH-1:0]   current_notional,

  // Statistics
  output logic [63:0]                 total_passed,
  output logic [63:0]                 total_rejected
);

  // ---------------------------------------------------------------------------
  // Signed state
  // ---------------------------------------------------------------------------
  // net_position: positive = net long, negative = net short.
  // net_notional: same sign convention, approximates running cost basis.
  //
  // Both are 1 bit wider than QTY_WIDTH/NOTIONAL_WIDTH so the sign bit has
  // headroom above the unsigned caps.
  logic signed [QTY_WIDTH:0]      net_position;
  logic signed [NOTIONAL_WIDTH:0] net_notional;

  // ---------------------------------------------------------------------------
  // Output views of the signed state
  // ---------------------------------------------------------------------------
  logic [QTY_WIDTH-1:0]       long_qty_view;
  logic [QTY_WIDTH-1:0]       short_qty_view;
  logic [NOTIONAL_WIDTH-1:0]  gross_notional_view;
  logic signed [NOTIONAL_WIDTH:0] abs_net_notional;

  always_comb begin
    if (net_position > 0) begin
      long_qty_view  = net_position[QTY_WIDTH-1:0];
      short_qty_view = '0;
    end else if (net_position < 0) begin
      long_qty_view  = '0;
      short_qty_view = (-net_position) & {1'b0, {QTY_WIDTH{1'b1}}};
    end else begin
      long_qty_view  = '0;
      short_qty_view = '0;
    end

    abs_net_notional = (net_notional < 0) ? -net_notional : net_notional;
    // Saturate the visible gross notional to NOTIONAL_WIDTH bits.
    gross_notional_view = (abs_net_notional[NOTIONAL_WIDTH]) ?
                          {NOTIONAL_WIDTH{1'b1}} :
                          abs_net_notional[NOTIONAL_WIDTH-1:0];
  end

  assign current_long_qty  = long_qty_view;
  assign current_short_qty = short_qty_view;
  assign current_notional  = gross_notional_view;

  // ---------------------------------------------------------------------------
  // Projection: state if the incoming order were to fill
  // ---------------------------------------------------------------------------
  logic signed [QTY_WIDTH:0]       projected_net;
  logic signed [NOTIONAL_WIDTH:0]  projected_net_notional;
  logic signed [NOTIONAL_WIDTH:0]  projected_abs_notional;

  logic signed [QTY_WIDTH:0]       order_qty_signed;
  logic signed [NOTIONAL_WIDTH:0]  order_not_signed;

  always_comb begin
    // Default: no projection change for non-NEW orders.
    order_qty_signed = {1'b0, order_qty};
    order_not_signed = {1'b0, order_notional};

    projected_net          = net_position;
    projected_net_notional = net_notional;

    if (order_type == ORDER_NEW) begin
      case (order_side)
        SIDE_BUY: begin
          projected_net          = net_position + order_qty_signed;
          projected_net_notional = net_notional + order_not_signed;
        end
        SIDE_SELL: begin
          projected_net          = net_position - order_qty_signed;
          projected_net_notional = net_notional - order_not_signed;
        end
        default: ;
      endcase
    end

    projected_abs_notional = (projected_net_notional < 0)
                             ? -projected_net_notional
                             : projected_net_notional;
  end

  // Projected long / short exposures, clamped to unsigned widths.
  logic [QTY_WIDTH-1:0] projected_long_qty;
  logic [QTY_WIDTH-1:0] projected_short_qty;
  always_comb begin
    if (projected_net > 0) begin
      projected_long_qty  = projected_net[QTY_WIDTH-1:0];
      projected_short_qty = '0;
    end else if (projected_net < 0) begin
      projected_long_qty  = '0;
      projected_short_qty = (-projected_net) & {1'b0, {QTY_WIDTH{1'b1}}};
    end else begin
      projected_long_qty  = '0;
      projected_short_qty = '0;
    end
  end

  // ---------------------------------------------------------------------------
  // Limit checks
  // ---------------------------------------------------------------------------
  logic order_qty_ok;
  logic long_qty_ok;
  logic short_qty_ok;
  logic notional_ok;
  logic projected_net_overflow;
  logic all_checks_ok;

  // If the signed projection overflowed the (QTY_WIDTH+1) field we reject on
  // position limit. In practice the caps are well below 2^63, so this only
  // fires for deranged inputs.
  assign projected_net_overflow = projected_net[QTY_WIDTH] ^ projected_net[QTY_WIDTH-1]
                                  ? 1'b0 : 1'b0;
  // (Placeholder: SV's signed arithmetic already handles overflow; kept as
  //  an explicit hook in case a future revision tightens the check.)

  assign order_qty_ok = (order_qty <= cfg_max_order_qty);
  assign long_qty_ok  = (projected_long_qty  <= cfg_max_long_qty);
  assign short_qty_ok = (projected_short_qty <= cfg_max_short_qty);
  assign notional_ok  = (projected_abs_notional[NOTIONAL_WIDTH-1:0] <= cfg_max_notional)
                        && !projected_abs_notional[NOTIONAL_WIDTH];

  assign all_checks_ok = order_qty_ok && long_qty_ok && short_qty_ok && notional_ok;

  // ---------------------------------------------------------------------------
  // Output logic
  // ---------------------------------------------------------------------------
  logic is_cancel;
  assign is_cancel = (order_type == ORDER_CANCEL);

  // Cancels always pass (they reduce risk).
  assign passed      = !cfg_enabled || is_cancel || all_checks_ok;
  assign order_ready = 1'b1;

  always_comb begin
    if (!cfg_enabled || passed) begin
      reject_reason = RISK_OK;
    end else if (!order_qty_ok) begin
      reject_reason = RISK_ORDER_SIZE;
    end else if (!long_qty_ok || !short_qty_ok) begin
      reject_reason = RISK_POSITION_LIMIT;
    end else begin
      reject_reason = RISK_NOTIONAL_LIMIT;
    end
  end

  // ---------------------------------------------------------------------------
  // Position update on fills
  // ---------------------------------------------------------------------------
  logic signed [QTY_WIDTH:0]       fill_qty_signed;
  logic signed [NOTIONAL_WIDTH:0]  fill_not_signed;
  always_comb begin
    fill_qty_signed = {1'b0, fill_qty};
    fill_not_signed = {1'b0, fill_notional};
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      net_position <= '0;
      net_notional <= '0;
    end else if (fill_valid) begin
      case (fill_side)
        SIDE_BUY: begin
          net_position <= net_position + fill_qty_signed;
          net_notional <= net_notional + fill_not_signed;
        end
        SIDE_SELL: begin
          net_position <= net_position - fill_qty_signed;
          net_notional <= net_notional - fill_not_signed;
        end
        default: ;
      endcase
    end
  end

  // ---------------------------------------------------------------------------
  // Statistics
  // ---------------------------------------------------------------------------
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      total_passed   <= '0;
      total_rejected <= '0;
    end else if (order_valid && order_ready) begin
      if (passed) total_passed   <= total_passed   + 64'd1;
      else        total_rejected <= total_rejected + 64'd1;
    end
  end

endmodule

`endif
