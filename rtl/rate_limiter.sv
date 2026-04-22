`ifndef RATE_LIMITER_SV
`define RATE_LIMITER_SV

`include "risk_pkg.sv"

// =============================================================================
// rate_limiter
// -----------------------------------------------------------------------------
// Token-bucket rate limiter for order flow.
//
// Wave 1 audit fixes:
//   A-S1-04  Widened bucket-refill arithmetic to (MAX_TOKENS_WIDTH+1) bits
//            so `bucket + cfg_refill_rate` cannot wrap inside a 32-bit
//            operand before being compared against cfg_max_tokens.
//
//   A-S1-05  A refill_period of 0 used to silently *disable* the limiter
//            because refill_counter==0 every cycle → the bucket refilled
//            every cycle and `has_tokens` was effectively always true.
//            The guard `cfg_refill_period > 0` is now required for refill,
//            and `passed` is forced to 0 (reject) when period==0 and the
//            limiter is enabled. This fails safe instead of failing open.
//
//   A-S1-07  Bucket consumption and stats counters are now gated on an
//            explicit `xfer_accept` input driven by the parent with
//            "the downstream actually took this order this cycle". The
//            old path decremented on `order_valid` alone, which rang up
//            phantom stats every cycle an upstream queue presented an
//            order that was then held by backpressure.
//
// `order_ready` is still driven to 1 — the rate limiter never backpressures
// upstream; it rejects by flipping `passed`=0 and the parent gate consumes
// that as a risk reject.
// =============================================================================

module rate_limiter
  import risk_pkg::*;
#(
  parameter int MAX_TOKENS_WIDTH = 32,
  parameter int COUNTER_WIDTH    = 32
)(
  input  logic                          clk,
  input  logic                          rst_n,

  // Configuration (directly exposed)
  input  logic [MAX_TOKENS_WIDTH-1:0]   cfg_max_tokens,
  input  logic [MAX_TOKENS_WIDTH-1:0]   cfg_refill_rate,
  input  logic [15:0]                   cfg_refill_period,
  input  logic                          cfg_enabled,

  // Order input (valid/ready interface)
  input  logic                          order_valid,
  output logic                          order_ready,
  input  order_type_e                   order_type,
  input  logic [7:0]                    tokens_required,  // Usually 1

  // True transfer happened this cycle: driven by parent risk_gate as
  // (in_valid && in_ready). Consumption of tokens happens only here.
  input  logic                          xfer_accept,

  // Output
  output logic                          passed,
  output logic                          rejected,
  output logic [MAX_TOKENS_WIDTH-1:0]   tokens_remaining,

  // Statistics
  output logic [63:0]                   total_passed,
  output logic [63:0]                   total_rejected
);

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  logic [MAX_TOKENS_WIDTH-1:0] bucket;
  logic [15:0]                 refill_counter;

  // ---------------------------------------------------------------------------
  // Misconfiguration detection
  // ---------------------------------------------------------------------------
  // A zero refill period with the limiter enabled is treated as a
  // mis-configuration; we fail safe by forcing passed=0 and leaving the
  // bucket alone. Downstream sees RISK_RATE_LIMITED rejects until the host
  // repairs the config.
  logic cfg_period_ok;
  assign cfg_period_ok = (cfg_refill_period != 16'd0);

  // ---------------------------------------------------------------------------
  // Refill counter
  // ---------------------------------------------------------------------------
  logic cfg_enabled_d;
  logic enable_edge;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) cfg_enabled_d <= 1'b0;
    else        cfg_enabled_d <= cfg_enabled;
  end
  assign enable_edge = cfg_enabled && !cfg_enabled_d;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      refill_counter <= 16'd1;
    end else if (enable_edge) begin
      refill_counter <= cfg_period_ok ? cfg_refill_period : 16'd1;
    end else if (!cfg_enabled || !cfg_period_ok) begin
      refill_counter <= 16'd1;
    end else if (refill_counter == 16'd0) begin
      refill_counter <= cfg_refill_period;
    end else begin
      refill_counter <= refill_counter - 16'd1;
    end
  end

  logic do_refill;
  assign do_refill = cfg_enabled
                   && cfg_period_ok
                   && (refill_counter == 16'd0)
                   && (cfg_refill_rate > 0);

  // ---------------------------------------------------------------------------
  // Token bookkeeping — with wide arithmetic to avoid 32-bit overflow
  // ---------------------------------------------------------------------------
  logic [MAX_TOKENS_WIDTH-1:0] tokens_required_ext;
  logic                        has_tokens;
  logic [MAX_TOKENS_WIDTH-1:0] tokens_after_consume;

  // Use a (W+1)-bit sum so refill_rate + bucket cannot wrap at 2^W.
  logic [MAX_TOKENS_WIDTH:0]   bucket_plus_refill;
  logic                        refill_caps_out;

  assign tokens_required_ext  = {{(MAX_TOKENS_WIDTH-8){1'b0}}, tokens_required};
  assign has_tokens           = (bucket >= tokens_required_ext);
  assign tokens_after_consume = bucket - tokens_required_ext;

  assign bucket_plus_refill = {1'b0, bucket} + {1'b0, cfg_refill_rate};
  assign refill_caps_out    = (bucket_plus_refill > {1'b0, cfg_max_tokens});

  // ---------------------------------------------------------------------------
  // Consumption is gated on true transfer acceptance (A-S1-07)
  // ---------------------------------------------------------------------------
  logic consume_token;
  assign consume_token = xfer_accept && passed && cfg_enabled && cfg_period_ok;

  logic cfg_enabled_prev;
  logic enable_rising;
  assign enable_rising = cfg_enabled && !cfg_enabled_prev;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      bucket           <= '0;
      cfg_enabled_prev <= 1'b0;
    end else begin
      cfg_enabled_prev <= cfg_enabled;

      if (enable_rising) begin
        bucket <= cfg_max_tokens;
      end else if (cfg_enabled && cfg_period_ok) begin
        // Priority: consume + refill same cycle
        if (consume_token && do_refill) begin
          if (refill_caps_out) begin
            bucket <= cfg_max_tokens - tokens_required_ext;
          end else begin
            bucket <= bucket_plus_refill[MAX_TOKENS_WIDTH-1:0] - tokens_required_ext;
          end
        end else if (consume_token) begin
          bucket <= tokens_after_consume;
        end else if (do_refill) begin
          if (refill_caps_out) begin
            bucket <= cfg_max_tokens;
          end else begin
            bucket <= bucket_plus_refill[MAX_TOKENS_WIDTH-1:0];
          end
        end
      end
      // If disabled or period==0, bucket is preserved.
    end
  end

  // ---------------------------------------------------------------------------
  // Decision
  // ---------------------------------------------------------------------------
  logic is_heartbeat;
  assign is_heartbeat = (order_type == ORDER_HEARTBEAT);

  // Pass if disabled, or heartbeat (no cost), or we have tokens. But if the
  // limiter is enabled with period=0 we fail safe.
  assign passed = !cfg_enabled       ? 1'b1
                : !cfg_period_ok     ? 1'b0
                : is_heartbeat       ? 1'b1
                :                      has_tokens;

  assign rejected         = order_valid && !passed;
  assign order_ready      = 1'b1;                 // Never backpressure upstream
  assign tokens_remaining = bucket;

  // ---------------------------------------------------------------------------
  // Statistics — gated on real transfer (A-S1-07)
  // ---------------------------------------------------------------------------
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      total_passed   <= '0;
      total_rejected <= '0;
    end else if (xfer_accept) begin
      if (passed) total_passed   <= total_passed   + 64'd1;
      else        total_rejected <= total_rejected + 64'd1;
    end
  end

endmodule

`endif
