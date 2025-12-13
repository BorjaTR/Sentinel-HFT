`ifndef STUB_LATENCY_CORE_SV
`define STUB_LATENCY_CORE_SV

// Stub Latency Core - Configurable-latency test core for Sentinel Shell
//
// This module implements a simple streaming core with configurable latency.
// It's essential for testing the sentinel shell instrumentation.
//
// LATENCY parameter:
//   0 = combinational pass-through (same cycle)
//   N = N-cycle pipeline delay
//
// Supports backpressure: when out_ready is low, pipeline stalls.
//
module stub_latency_core #(
  parameter int DATA_WIDTH = 64,
  parameter int LATENCY    = 1    // 0 = combinational, N = N cycles
)(
  input  logic                  clk,
  input  logic                  rst_n,

  // Input stream
  input  logic                  in_valid,
  output logic                  in_ready,
  input  logic [DATA_WIDTH-1:0] in_data,

  // Output stream
  output logic                  out_valid,
  input  logic                  out_ready,
  output logic [DATA_WIDTH-1:0] out_data,

  // Error output (always 0 for this stub)
  output logic                  error
);

  // This stub core never produces errors
  assign error = 1'b0;

  generate
    if (LATENCY == 0) begin : g_combinational
      // ===================================================================
      // Combinational pass-through (zero latency)
      // Data flows through in the same cycle
      // ===================================================================
      assign out_valid = in_valid;
      assign in_ready  = out_ready;
      assign out_data  = in_data;

    end else begin : g_pipeline
      // ===================================================================
      // Pipeline with configurable depth
      // Implements a shift register with backpressure support
      // ===================================================================

      // Pipeline storage
      logic [DATA_WIDTH-1:0] data_pipe  [0:LATENCY-1];
      logic                  valid_pipe [0:LATENCY-1];

      // Pipeline can shift when output is ready or output stage is empty
      logic pipe_can_shift;
      assign pipe_can_shift = out_ready || !valid_pipe[LATENCY-1];

      // Accept input when pipeline can shift
      assign in_ready = pipe_can_shift;

      // Output from last pipeline stage
      assign out_valid = valid_pipe[LATENCY-1];
      assign out_data  = data_pipe[LATENCY-1];

      // Pipeline registers
      always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
          // Reset all pipeline stages
          for (int i = 0; i < LATENCY; i++) begin
            valid_pipe[i] <= 1'b0;
            data_pipe[i]  <= '0;
          end
        end else if (pipe_can_shift) begin
          // First stage: accept new input
          valid_pipe[0] <= in_valid && in_ready;
          data_pipe[0]  <= in_data;

          // Remaining stages: shift from previous
          for (int i = 1; i < LATENCY; i++) begin
            valid_pipe[i] <= valid_pipe[i-1];
            data_pipe[i]  <= data_pipe[i-1];
          end
        end
        // When !pipe_can_shift, pipeline is stalled - hold all values
      end
    end
  endgenerate

endmodule

`endif
