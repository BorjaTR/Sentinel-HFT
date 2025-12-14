`ifndef RATE_LIMITER_SV
`define RATE_LIMITER_SV

`include "risk_pkg.sv"

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

  // Output
  output logic                          passed,
  output logic                          rejected,
  output logic [MAX_TOKENS_WIDTH-1:0]   tokens_remaining,

  // Statistics
  output logic [63:0]                   total_passed,
  output logic [63:0]                   total_rejected
);

  // =========================================================================
  // Token Bucket State
  // =========================================================================

  logic [MAX_TOKENS_WIDTH-1:0] bucket;
  logic [15:0]                 refill_counter;

  // =========================================================================
  // Refill Logic
  // =========================================================================

  logic do_refill;
  logic [15:0] refill_counter_next;

  // Track enable edge for counter initialization (separate from bucket)
  logic cfg_enabled_d;
  logic enable_edge;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      cfg_enabled_d <= 1'b0;
    end else begin
      cfg_enabled_d <= cfg_enabled;
    end
  end

  assign enable_edge = cfg_enabled && !cfg_enabled_d;

  // Countdown timer for refill
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      refill_counter <= 16'd1;  // Start small, will reinit on enable
    end else if (enable_edge) begin
      // Reinitialize counter when first enabled with current config
      refill_counter <= cfg_refill_period;
    end else if (!cfg_enabled) begin
      // Keep counter ready when disabled
      refill_counter <= 16'd1;
    end else begin
      if (refill_counter == 0) begin
        refill_counter <= cfg_refill_period;
      end else begin
        refill_counter <= refill_counter - 16'd1;
      end
    end
  end

  // Refill when counter wraps (but not on first cycle after enable)
  assign do_refill = cfg_enabled && (refill_counter == 0) && (cfg_refill_rate > 0);

  // =========================================================================
  // Token Bucket Update
  // =========================================================================

  logic consume_token;
  logic [MAX_TOKENS_WIDTH-1:0] tokens_after_consume;
  logic has_tokens;

  // Extend tokens_required to match width
  logic [MAX_TOKENS_WIDTH-1:0] tokens_required_ext;
  assign tokens_required_ext = {{(MAX_TOKENS_WIDTH-8){1'b0}}, tokens_required};

  // Check if we have enough tokens
  assign has_tokens = (bucket >= tokens_required_ext);

  // Calculate post-consumption amount
  assign tokens_after_consume = bucket - tokens_required_ext;

  // Consume when order is valid, we're ready, and order passes
  assign consume_token = order_valid && order_ready && passed && cfg_enabled;

  // Track enable edge for bucket initialization
  logic cfg_enabled_prev;
  logic enable_rising;

  assign enable_rising = cfg_enabled && !cfg_enabled_prev;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      // Start empty on reset (will be filled on enable)
      bucket <= '0;
      cfg_enabled_prev <= 1'b0;
    end else begin
      // Track previous enable state
      cfg_enabled_prev <= cfg_enabled;

      if (enable_rising) begin
        // Fill bucket to max when first enabled
        bucket <= cfg_max_tokens;
      end else if (cfg_enabled) begin
        // Priority: consume > refill
        if (consume_token && do_refill) begin
          // Both consume and refill on same cycle
          if (bucket + cfg_refill_rate > cfg_max_tokens) begin
            bucket <= cfg_max_tokens - tokens_required_ext;
          end else begin
            bucket <= bucket + cfg_refill_rate - tokens_required_ext;
          end
        end else if (consume_token) begin
          bucket <= tokens_after_consume;
        end else if (do_refill) begin
          // Add tokens up to max
          if (bucket + cfg_refill_rate > cfg_max_tokens) begin
            bucket <= cfg_max_tokens;
          end else begin
            bucket <= bucket + cfg_refill_rate;
          end
        end
        // else bucket stays the same
      end
      // When disabled, bucket is preserved (doesn't matter, will reset on enable)
    end
  end

  // =========================================================================
  // Output Logic
  // =========================================================================

  // Heartbeats always pass, other orders need tokens
  logic is_heartbeat;
  assign is_heartbeat = (order_type == ORDER_HEARTBEAT);

  // Pass if disabled, or heartbeat, or have tokens
  assign passed = !cfg_enabled || is_heartbeat || has_tokens;
  assign rejected = order_valid && !passed;

  // Always ready (rate limiter doesn't stall, it rejects)
  assign order_ready = 1'b1;

  assign tokens_remaining = bucket;

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
