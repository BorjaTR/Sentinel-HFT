`timescale 1ns / 1ps

// Testbench Wrapper for Sentinel Shell with Stub Latency Core
//
// This module wraps the sentinel_shell and stub_latency_core together
// and exposes all necessary signals as ports for Verilator C++ testbench.
//
module tb_sentinel_shell
  import trace_pkg::*;
#(
  parameter int DATA_WIDTH       = 64,
  parameter int CORE_LATENCY     = 1,
  parameter int INFLIGHT_DEPTH   = 16,
  parameter int TRACE_FIFO_DEPTH = 64
)(
  // Clock and Reset (directly driven by testbench)
  input  logic clk,
  input  logic rst_n,

  // Input Stream Control
  input  logic                        in_valid,
  output logic                        in_ready,
  input  logic [DATA_WIDTH-1:0]       in_data,
  input  logic [OPCODE_WIDTH-1:0]     in_opcode,
  input  logic [META_WIDTH-1:0]       in_meta,

  // Output Stream Control
  output logic                        out_valid,
  input  logic                        out_ready,
  output logic [DATA_WIDTH-1:0]       out_data,

  // Trace Output Control
  output logic                        trace_valid,
  input  logic                        trace_ready,

  // Trace Record Fields (unpacked for easy C++ access)
  output logic [TX_ID_WIDTH-1:0]      trace_tx_id,
  output logic [CYCLE_WIDTH-1:0]      trace_t_ingress,
  output logic [CYCLE_WIDTH-1:0]      trace_t_egress,
  output logic [15:0]                 trace_flags,
  output logic [OPCODE_WIDTH-1:0]     trace_opcode,
  output logic [META_WIDTH-1:0]       trace_meta,

  // Status Counters
  output logic [CYCLE_WIDTH-1:0]      cycle_counter,
  output logic [63:0]                 trace_drop_count,
  output logic [63:0]                 in_backpressure_cycles,
  output logic [63:0]                 out_backpressure_cycles,
  output logic [31:0]                 inflight_underflow_count,
  output logic                        trace_overflow_seen
);

  // =========================================================================
  // Core Interface (internal wires between shell and core)
  // =========================================================================
  logic                        core_in_valid;
  logic                        core_in_ready;
  logic [DATA_WIDTH-1:0]       core_in_data;
  logic                        core_out_valid;
  logic                        core_out_ready;
  logic [DATA_WIDTH-1:0]       core_out_data;
  logic                        core_error;

  // Trace data (packed struct from shell)
  trace_record_t               trace_data;

  // =========================================================================
  // DUT: Sentinel Shell
  // =========================================================================
  sentinel_shell #(
    .DATA_WIDTH       (DATA_WIDTH),
    .INFLIGHT_DEPTH   (INFLIGHT_DEPTH),
    .TRACE_FIFO_DEPTH (TRACE_FIFO_DEPTH)
  ) u_shell (
    .clk                      (clk),
    .rst_n                    (rst_n),
    // Input stream
    .in_valid                 (in_valid),
    .in_ready                 (in_ready),
    .in_data                  (in_data),
    .in_opcode                (in_opcode),
    .in_meta                  (in_meta),
    // Output stream
    .out_valid                (out_valid),
    .out_ready                (out_ready),
    .out_data                 (out_data),
    // Core interface
    .core_in_valid            (core_in_valid),
    .core_in_ready            (core_in_ready),
    .core_in_data             (core_in_data),
    .core_out_valid           (core_out_valid),
    .core_out_ready           (core_out_ready),
    .core_out_data            (core_out_data),
    .core_error               (core_error),
    // Trace output
    .trace_valid              (trace_valid),
    .trace_ready              (trace_ready),
    .trace_data               (trace_data),
    // Counters
    .cycle_counter            (cycle_counter),
    .trace_drop_count         (trace_drop_count),
    .in_backpressure_cycles   (in_backpressure_cycles),
    .out_backpressure_cycles  (out_backpressure_cycles),
    .inflight_underflow_count (inflight_underflow_count),
    .trace_overflow_seen      (trace_overflow_seen)
  );

  // =========================================================================
  // DUT: Stub Latency Core
  // =========================================================================
  stub_latency_core #(
    .DATA_WIDTH (DATA_WIDTH),
    .LATENCY    (CORE_LATENCY)
  ) u_core (
    .clk       (clk),
    .rst_n     (rst_n),
    .in_valid  (core_in_valid),
    .in_ready  (core_in_ready),
    .in_data   (core_in_data),
    .out_valid (core_out_valid),
    .out_ready (core_out_ready),
    .out_data  (core_out_data),
    .error     (core_error)
  );

  // =========================================================================
  // Unpack trace record for C++ access
  // =========================================================================
  assign trace_tx_id     = trace_data.tx_id;
  assign trace_t_ingress = trace_data.t_ingress;
  assign trace_t_egress  = trace_data.t_egress;
  assign trace_flags     = trace_data.flags;
  assign trace_opcode    = trace_data.opcode;
  assign trace_meta      = trace_data.meta;

endmodule
