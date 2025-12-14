`ifndef POSITION_LIMITER_SV
`define POSITION_LIMITER_SV

`include "risk_pkg.sv"

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

  // =========================================================================
  // Position State
  // =========================================================================

  logic [QTY_WIDTH-1:0]      long_qty;
  logic [QTY_WIDTH-1:0]      short_qty;
  logic [NOTIONAL_WIDTH-1:0] gross_notional;

  assign current_long_qty  = long_qty;
  assign current_short_qty = short_qty;
  assign current_notional  = gross_notional;

  // =========================================================================
  // Projected Position (if order were filled)
  // =========================================================================

  logic [QTY_WIDTH-1:0]      projected_long;
  logic [QTY_WIDTH-1:0]      projected_short;
  logic [NOTIONAL_WIDTH-1:0] projected_notional;

  always_comb begin
    projected_long     = long_qty;
    projected_short    = short_qty;
    projected_notional = gross_notional + order_notional;

    if (order_type == ORDER_NEW) begin
      case (order_side)
        SIDE_BUY:  projected_long  = long_qty + order_qty;
        SIDE_SELL: projected_short = short_qty + order_qty;
        default: ;
      endcase
    end
  end

  // =========================================================================
  // Limit Checks
  // =========================================================================

  logic order_qty_ok;
  logic long_qty_ok;
  logic short_qty_ok;
  logic notional_ok;
  logic all_checks_ok;

  assign order_qty_ok = (order_qty <= cfg_max_order_qty);
  assign long_qty_ok  = (projected_long <= cfg_max_long_qty);
  assign short_qty_ok = (projected_short <= cfg_max_short_qty);
  assign notional_ok  = (projected_notional <= cfg_max_notional);

  assign all_checks_ok = order_qty_ok && long_qty_ok && short_qty_ok && notional_ok;

  // =========================================================================
  // Output Logic
  // =========================================================================

  // Cancels always pass position check (they reduce risk)
  logic is_cancel;
  assign is_cancel = (order_type == ORDER_CANCEL);

  assign passed = !cfg_enabled || is_cancel || all_checks_ok;
  assign order_ready = 1'b1;

  // Determine reject reason (priority order)
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

  // =========================================================================
  // Position Update (on fills)
  // =========================================================================

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      long_qty       <= '0;
      short_qty      <= '0;
      gross_notional <= '0;
    end else if (fill_valid) begin
      // Update position based on fill
      case (fill_side)
        SIDE_BUY: begin
          // Buy fill: increase long or decrease short
          if (short_qty >= fill_qty) begin
            short_qty <= short_qty - fill_qty;
          end else begin
            long_qty <= long_qty + fill_qty - short_qty;
            short_qty <= '0;
          end
        end
        SIDE_SELL: begin
          // Sell fill: increase short or decrease long
          if (long_qty >= fill_qty) begin
            long_qty <= long_qty - fill_qty;
          end else begin
            short_qty <= short_qty + fill_qty - long_qty;
            long_qty <= '0;
          end
        end
        default: ;
      endcase

      // Track gross notional (simplified: always adds)
      gross_notional <= gross_notional + fill_notional;
    end
  end

  // =========================================================================
  // Statistics
  // =========================================================================

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      total_passed   <= '0;
      total_rejected <= '0;
    end else if (order_valid && order_ready) begin
      if (passed) begin
        total_passed <= total_passed + 1;
      end else begin
        total_rejected <= total_rejected + 1;
      end
    end
  end

endmodule

`endif
