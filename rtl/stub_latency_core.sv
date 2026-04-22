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
// Wave 3 audit fix (WP3.3 / C-S3-10, C-S3-11):
//   This file is a simulation stub and MUST NOT appear in any
//   synthesis or place-and-route run. Three guards enforce that:
//
//     1. A `SYNTHESIS`-gated `$fatal` inside the module body so
//        Vivado / yosys / DC will abort elaboration if the stub
//        ends up in the synthesis source list.
//     2. A `STUB_ONLY` parameter with a compile-time assertion so
//        the top-level can tie STUB_ONLY=0 when instantiating the
//        production core and watch elaboration fail if the wrong
//        module is accidentally wired in.
//     3. A `stub_core_detected` LED-style flag surfaced as an
//        output so if the stub does sneak into a bitstream an LED
//        lights up at boot -- last line of defence.
//
module stub_latency_core #(
  parameter int DATA_WIDTH = 64,
  parameter int LATENCY    = 1,   // 0 = combinational, N = N cycles
  parameter bit STUB_ONLY  = 1'b1 // WP3.3: set to 0 at instantiation to fail
                                  // compile if the stub ever sneaks into a
                                  // production path.
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
  output logic                  error,

  // WP3.3 last-line-of-defence flag: if this module is ever
  // instantiated in a bitstream, route this up to a visible LED
  // at the top level. A non-zero value here on real silicon
  // means the production strategy slot was replaced by the stub.
  output logic                  stub_core_detected
);

  // This stub core never produces errors
  assign error = 1'b0;

  // WP3.3 bitstream tripwire. Always asserted while this module
  // lives in the hierarchy; top level is expected to OR-combine
  // this with similar flags from any other stub and drive an LED.
  assign stub_core_detected = 1'b1;

  // WP3.3 guard 1: synthesis must not accept this module.
  // Elaboration fails with a clear message when built under a
  // synthesis flow that sets the SYNTHESIS define (Vivado, DC,
  // yosys all set one of the names below; we check the common
  // ones plus a Sentinel-specific override).
  `ifdef SYNTHESIS
    `define SENTINEL_STUB_IN_SYNTH 1
  `endif
  `ifdef XILINX_SYNTHESIS
    `define SENTINEL_STUB_IN_SYNTH 1
  `endif
  `ifdef YOSYS
    `define SENTINEL_STUB_IN_SYNTH 1
  `endif
  `ifdef SENTINEL_STRICT_NO_STUB
    `define SENTINEL_STUB_IN_SYNTH 1
  `endif

  `ifdef SENTINEL_STUB_IN_SYNTH
    initial begin
      $fatal(1, "stub_latency_core in synthesis source list -- refusing to build a bitstream that shorts out the production latency core");
    end
  `endif

  // WP3.3 guard 2: STUB_ONLY parameter. Production instantiators
  // must override to 0, which triggers the elaboration-time $error
  // below and stops the build. Simulation-only instantiators leave
  // the default value and the check silently passes.
  //
  // $error inside a generate scope is IEEE 1800-2017 §20.11 (an
  // "elaboration system task") -- Vivado, DC, yosys, verilator, and
  // slang all treat this as a hard elaboration failure, which is
  // exactly what we want: a production build that accidentally ties
  // the production core slot to the stub must fail to elaborate
  // before it can ever reach synthesis.
  generate
    if (STUB_ONLY != 1'b1) begin : g_stub_only_check
      $error("stub_latency_core: STUB_ONLY parameter must be 1'b1 (this module is a simulation stub, not a production core).");
    end
  endgenerate

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
