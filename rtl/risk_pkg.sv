`ifndef RISK_PKG_SV
`define RISK_PKG_SV

package risk_pkg;

  // =========================================================================
  // Order Types
  // =========================================================================

  // Order side
  typedef enum logic [1:0] {
    SIDE_BUY  = 2'b01,
    SIDE_SELL = 2'b10
  } order_side_e;

  // Order type (for rate limiting categories)
  typedef enum logic [3:0] {
    ORDER_NEW       = 4'h1,
    ORDER_CANCEL    = 4'h2,
    ORDER_MODIFY    = 4'h3,
    ORDER_HEARTBEAT = 4'hF   // Doesn't count against limits
  } order_type_e;

  // =========================================================================
  // Risk Control Configuration
  // =========================================================================

  // Rate limiter config
  typedef struct packed {
    logic [31:0] max_tokens;        // Bucket capacity
    logic [31:0] refill_rate;       // Tokens per refill period
    logic [15:0] refill_period;     // Cycles between refills
    logic        enabled;
  } rate_limit_config_t;

  // Position limiter config
  typedef struct packed {
    logic [63:0] max_long_qty;      // Max long position (units)
    logic [63:0] max_short_qty;     // Max short position (units)
    logic [63:0] max_notional;      // Max notional value
    logic [63:0] max_order_qty;     // Max single order size
    logic        enabled;
  } position_limit_config_t;

  // Kill switch config
  typedef struct packed {
    logic        armed;             // Kill switch is armed
    logic        triggered;         // Kill switch has fired (sticky)
    logic [31:0] loss_threshold;    // P&L loss that triggers (optional)
    logic        manual_kill;       // Software-triggered kill
  } kill_switch_config_t;

  // =========================================================================
  // Risk Status / Reject Reasons
  // =========================================================================

  typedef enum logic [7:0] {
    RISK_OK              = 8'h00,
    RISK_RATE_LIMITED    = 8'h01,
    RISK_POSITION_LIMIT  = 8'h02,
    RISK_NOTIONAL_LIMIT  = 8'h03,
    RISK_ORDER_SIZE      = 8'h04,
    RISK_KILL_SWITCH     = 8'h05,
    RISK_INVALID_ORDER   = 8'h06,
    RISK_DISABLED        = 8'hFF
  } risk_reject_e;

  // Combined risk status
  typedef struct packed {
    logic           passed;         // Order passed all checks
    risk_reject_e   reject_reason;  // Why it was rejected (if !passed)
    logic [31:0]    tokens_remaining;
    logic [63:0]    current_position;
    logic [63:0]    current_notional;
  } risk_status_t;

  // =========================================================================
  // Order Structure (input to risk gate)
  // =========================================================================

  typedef struct packed {
    logic [63:0]    order_id;
    logic [31:0]    symbol_id;
    order_side_e    side;
    order_type_e    order_type;
    logic [63:0]    quantity;       // Order quantity
    logic [63:0]    price;          // Price (fixed point, e.g., 8 decimals)
    logic [63:0]    notional;       // Pre-computed: qty * price (or compute in RTL)
  } order_t;

  localparam int ORDER_WIDTH = $bits(order_t);

  // =========================================================================
  // Trace Flag Extensions (add to trace_pkg.sv)
  // =========================================================================

  // New flags for risk events (bits 8-15 reserved for risk)
  localparam logic [15:0] FLAG_RISK_RATE_LIMITED   = 16'h0100;
  localparam logic [15:0] FLAG_RISK_POSITION_LIMIT = 16'h0200;
  localparam logic [15:0] FLAG_RISK_NOTIONAL_LIMIT = 16'h0400;
  localparam logic [15:0] FLAG_RISK_KILL_SWITCH    = 16'h0800;
  localparam logic [15:0] FLAG_RISK_REJECTED       = 16'h1000;

endpackage

`endif
