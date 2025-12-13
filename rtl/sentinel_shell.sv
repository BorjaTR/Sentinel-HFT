`ifndef SENTINEL_SHELL_SV
`define SENTINEL_SHELL_SV

// Sentinel Shell - Instrumentation wrapper for streaming RTL cores
//
// This module wraps any streaming core and emits cycle-accurate trace records
// for every transaction. The wrapper is non-invasive: it does NOT change
// the timing behavior of the wrapped core.
//
// Key guarantees:
// 1. Pass-through behavior: Shell does not alter core timing
// 2. Graceful overflow: Drops traces on FIFO full, never blocks pipeline
// 3. Deterministic: Same input + same ready/valid = identical traces
//
module sentinel_shell
  import trace_pkg::*;
#(
  parameter int DATA_WIDTH        = trace_pkg::DATA_WIDTH,
  parameter int TX_ID_WIDTH       = trace_pkg::TX_ID_WIDTH,
  parameter int CYCLE_WIDTH       = trace_pkg::CYCLE_WIDTH,
  parameter int OPCODE_WIDTH      = trace_pkg::OPCODE_WIDTH,
  parameter int META_WIDTH        = trace_pkg::META_WIDTH,
  parameter int INFLIGHT_DEPTH    = trace_pkg::INFLIGHT_DEPTH,
  parameter int TRACE_FIFO_DEPTH  = trace_pkg::TRACE_FIFO_DEPTH
)(
  input  logic clk,
  input  logic rst_n,

  // ===== Input Stream (from upstream) =====
  input  logic                    in_valid,
  output logic                    in_ready,
  input  logic [DATA_WIDTH-1:0]   in_data,
  input  logic [OPCODE_WIDTH-1:0] in_opcode,
  input  logic [META_WIDTH-1:0]   in_meta,

  // ===== Output Stream (to downstream) =====
  output logic                    out_valid,
  input  logic                    out_ready,
  output logic [DATA_WIDTH-1:0]   out_data,

  // ===== Core Interface =====
  // These signals connect to the wrapped core
  output logic                    core_in_valid,
  input  logic                    core_in_ready,
  output logic [DATA_WIDTH-1:0]   core_in_data,

  input  logic                    core_out_valid,
  output logic                    core_out_ready,
  input  logic [DATA_WIDTH-1:0]   core_out_data,
  input  logic                    core_error,

  // ===== Trace Output Stream =====
  output logic                    trace_valid,
  input  logic                    trace_ready,
  output trace_record_t           trace_data,

  // ===== Counters and Status =====
  output logic [CYCLE_WIDTH-1:0]  cycle_counter,
  output logic [63:0]             trace_drop_count,
  output logic [63:0]             in_backpressure_cycles,
  output logic [63:0]             out_backpressure_cycles,
  output logic [31:0]             inflight_underflow_count,
  output logic                    trace_overflow_seen
);

  // =========================================================================
  // PASS-THROUGH: Shell must NOT alter core timing
  // This is critical - the shell is transparent to the data path
  // =========================================================================
  assign core_in_valid  = in_valid;
  assign in_ready       = core_in_ready;
  assign core_in_data   = in_data;

  assign out_valid      = core_out_valid;
  assign core_out_ready = out_ready;
  assign out_data       = core_out_data;

  // =========================================================================
  // Cycle Counter - Free-running counter for timestamps
  // =========================================================================
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n)
      cycle_counter <= '0;
    else
      cycle_counter <= cycle_counter + 1'b1;
  end

  // =========================================================================
  // Handshake Detection
  // =========================================================================
  logic ingress_handshake;
  logic egress_handshake;

  assign ingress_handshake = in_valid && in_ready;
  assign egress_handshake  = out_valid && out_ready;

  // =========================================================================
  // Transaction ID Generator
  // Monotonically increasing ID assigned at ingress
  // =========================================================================
  logic [TX_ID_WIDTH-1:0] next_tx_id;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n)
      next_tx_id <= '0;
    else if (ingress_handshake)
      next_tx_id <= next_tx_id + 1'b1;
  end

  // =========================================================================
  // Inflight FIFO - Stores transaction metadata between ingress and egress
  // =========================================================================
  localparam int INFLIGHT_ADDR_WIDTH = $clog2(INFLIGHT_DEPTH);

  inflight_entry_t inflight_wr_data;
  inflight_entry_t inflight_rd_data;
  logic inflight_wr_en;
  logic inflight_rd_en;
  logic inflight_full;
  logic inflight_empty;
  logic [INFLIGHT_ADDR_WIDTH:0] inflight_count;

  // Pack inflight entry at ingress
  assign inflight_wr_data.tx_id     = next_tx_id;
  assign inflight_wr_data.t_ingress = cycle_counter;
  assign inflight_wr_data.opcode    = in_opcode;
  assign inflight_wr_data.meta      = in_meta;

  // Write to inflight FIFO on ingress handshake (if not full)
  assign inflight_wr_en = ingress_handshake && !inflight_full;

  // Read from inflight FIFO on egress handshake (if not empty)
  assign inflight_rd_en = egress_handshake && !inflight_empty;

  sync_fifo #(
    .WIDTH(INFLIGHT_ENTRY_WIDTH),
    .DEPTH(INFLIGHT_DEPTH)
  ) u_inflight_fifo (
    .clk     (clk),
    .rst_n   (rst_n),
    .wr_en   (inflight_wr_en),
    .wr_data (inflight_wr_data),
    .full    (inflight_full),
    .rd_en   (inflight_rd_en),
    .rd_data (inflight_rd_data),
    .empty   (inflight_empty),
    .count   (inflight_count)
  );

  // =========================================================================
  // Trace Record Generation
  // =========================================================================
  trace_record_t new_trace;
  logic trace_wr_en;
  logic trace_fifo_full;
  logic trace_fifo_empty;

  // Compose trace record at egress
  always_comb begin
    new_trace.tx_id     = inflight_rd_data.tx_id;
    new_trace.t_ingress = inflight_rd_data.t_ingress;
    new_trace.t_egress  = cycle_counter;
    new_trace.opcode    = inflight_rd_data.opcode;
    new_trace.meta      = inflight_rd_data.meta;
    new_trace.flags     = FLAG_NONE;

    // Set error flag if core reported error
    if (core_error)
      new_trace.flags = new_trace.flags | FLAG_CORE_ERROR;

    // Set underflow flag if egress without matching ingress
    if (inflight_empty && egress_handshake)
      new_trace.flags = new_trace.flags | FLAG_INFLIGHT_UNDER;
  end

  // Write trace on egress if inflight has data and trace FIFO has space
  assign trace_wr_en = egress_handshake && !inflight_empty && !trace_fifo_full;

  // =========================================================================
  // Trace FIFO - Buffers trace records for downstream consumption
  // =========================================================================
  localparam int TRACE_ADDR_WIDTH = $clog2(TRACE_FIFO_DEPTH);

  logic [TRACE_ADDR_WIDTH:0] trace_count;
  trace_record_t trace_rd_data;

  sync_fifo #(
    .WIDTH(TRACE_RECORD_WIDTH),
    .DEPTH(TRACE_FIFO_DEPTH)
  ) u_trace_fifo (
    .clk     (clk),
    .rst_n   (rst_n),
    .wr_en   (trace_wr_en),
    .wr_data (new_trace),
    .full    (trace_fifo_full),
    .rd_en   (trace_valid && trace_ready),
    .rd_data (trace_rd_data),
    .empty   (trace_fifo_empty),
    .count   (trace_count)
  );

  // Trace output interface
  assign trace_valid = !trace_fifo_empty;
  assign trace_data  = trace_rd_data;

  // =========================================================================
  // Counters - Track drops, backpressure, errors
  // =========================================================================

  // Trace drops: count when we would write a trace but FIFO is full
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      trace_drop_count    <= '0;
      trace_overflow_seen <= 1'b0;
    end else if (egress_handshake && !inflight_empty && trace_fifo_full) begin
      trace_drop_count    <= trace_drop_count + 1'b1;
      trace_overflow_seen <= 1'b1;
    end
  end

  // Input backpressure: count cycles where in_valid && !in_ready
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n)
      in_backpressure_cycles <= '0;
    else if (in_valid && !in_ready)
      in_backpressure_cycles <= in_backpressure_cycles + 1'b1;
  end

  // Output backpressure: count cycles where out_valid && !out_ready
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n)
      out_backpressure_cycles <= '0;
    else if (out_valid && !out_ready)
      out_backpressure_cycles <= out_backpressure_cycles + 1'b1;
  end

  // Inflight underflow: count egress handshakes when inflight FIFO is empty
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n)
      inflight_underflow_count <= '0;
    else if (egress_handshake && inflight_empty)
      inflight_underflow_count <= inflight_underflow_count + 1'b1;
  end

endmodule

`endif
