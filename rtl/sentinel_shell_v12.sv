// sentinel_shell_v12.sv - Instrumentation shell with v1.2 attribution support
//
// This wraps the instrumented pipeline and emits trace records.
// Supports both v1.1 (48B) and v1.2 (64B) output formats.

`ifndef SENTINEL_SHELL_V12_SV
`define SENTINEL_SHELL_V12_SV

`include "trace_pkg_v12.sv"
`include "instrumented_pipeline.sv"
`include "sync_fifo.sv"

module sentinel_shell_v12 #(
    parameter int  CORE_LATENCY    = 10,
    parameter int  RISK_LATENCY    = 5,
    parameter int  FIFO_DEPTH      = 64,
    parameter bit  EMIT_V12        = 1,       // 1 = v1.2 (64B), 0 = v1.1 (48B)
    parameter int  CORE_ID         = 0
) (
    input  logic        clk,
    input  logic        rst_n,

    // Upstream interface
    input  logic        up_valid,
    output logic        up_ready,
    input  logic [63:0] up_data,

    // Downstream interface
    output logic        dn_valid,
    input  logic        dn_ready,
    output logic [63:0] dn_data,

    // Trace output interface
    output logic        trace_valid,
    input  logic        trace_ready,
    output logic [511:0] trace_data,  // Max size (v1.2 = 512 bits)
    output logic [6:0]  trace_size,   // Actual size in bytes (48 or 64)

    // Status
    output logic [31:0] seq_no,
    output logic [31:0] trace_drop_count
);

    import trace_pkg_v12::*;

    // =========================================================================
    // Internal Signals
    // =========================================================================

    // Timestamp counter
    logic [63:0] cycle_counter;

    // Transaction tracking
    logic [63:0] t_ingress_captured;
    logic [15:0] tx_id_counter;

    // Attribution from pipeline
    logic        attr_valid;
    logic [31:0] attr_d_ingress, attr_d_core, attr_d_risk, attr_d_egress;

    // Sequence number
    logic [31:0] seq_counter;

    // FIFO signals
    logic        fifo_push, fifo_pop;
    logic        fifo_full, fifo_empty;
    logic [511:0] fifo_din, fifo_dout;

    // Drop counter
    logic [31:0] drop_counter;

    // =========================================================================
    // Cycle Counter (Timestamp Source)
    // =========================================================================

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            cycle_counter <= '0;
        else
            cycle_counter <= cycle_counter + 1'b1;
    end

    // =========================================================================
    // Instrumented Pipeline
    // =========================================================================

    instrumented_pipeline #(
        .CORE_LATENCY(CORE_LATENCY),
        .RISK_LATENCY(RISK_LATENCY)
    ) u_pipeline (
        .clk(clk),
        .rst_n(rst_n),
        .up_valid(up_valid),
        .up_ready(up_ready),
        .up_data(up_data),
        .dn_valid(dn_valid),
        .dn_ready(dn_ready),
        .dn_data(dn_data),
        .attr_valid(attr_valid),
        .attr_d_ingress(attr_d_ingress),
        .attr_d_core(attr_d_core),
        .attr_d_risk(attr_d_risk),
        .attr_d_egress(attr_d_egress)
    );

    // =========================================================================
    // Ingress Timestamp Capture
    // =========================================================================

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            t_ingress_captured <= '0;
            tx_id_counter      <= '0;
        end else if (up_valid && up_ready) begin
            t_ingress_captured <= cycle_counter;
            tx_id_counter      <= tx_id_counter + 1'b1;
        end
    end

    // =========================================================================
    // Trace Record Generation
    // =========================================================================

    trace_record_v12_t trace_record;

    always_comb begin
        trace_record = '0;

        // v1.1 compatible header
        trace_record.version     = EMIT_V12 ? 8'h02 : 8'h01;
        trace_record.record_type = REC_TX_EVENT;
        trace_record.core_id     = CORE_ID[15:0];
        trace_record.seq_no      = seq_counter;
        trace_record.t_ingress   = t_ingress_captured;
        trace_record.t_egress    = cycle_counter;
        trace_record.t_host      = '0;  // Filled by host
        trace_record.tx_id       = tx_id_counter - 1'b1;  // ID of completing tx
        trace_record.flags.valid = 1'b1;

        // v1.2 attribution (zeros if EMIT_V12=0, but won't be transmitted)
        trace_record.d_ingress   = attr_d_ingress;
        trace_record.d_core      = attr_d_core;
        trace_record.d_risk      = attr_d_risk;
        trace_record.d_egress    = attr_d_egress;
    end

    // =========================================================================
    // Sequence Number Management
    // =========================================================================

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            seq_counter <= '0;
        else if (attr_valid && !fifo_full)
            seq_counter <= seq_counter + 1'b1;
    end

    // =========================================================================
    // Trace FIFO
    // =========================================================================

    assign fifo_push = attr_valid && !fifo_full;
    assign fifo_din  = trace_record;

    sync_fifo #(
        .WIDTH(512),
        .DEPTH(FIFO_DEPTH)
    ) u_trace_fifo (
        .clk(clk),
        .rst_n(rst_n),
        .wr_en(fifo_push),
        .wr_data(fifo_din),
        .full(fifo_full),
        .rd_en(fifo_pop),
        .rd_data(fifo_dout),
        .empty(fifo_empty),
        .count()
    );

    assign fifo_pop    = trace_valid && trace_ready;
    assign trace_valid = !fifo_empty;
    assign trace_data  = fifo_dout;
    assign trace_size  = EMIT_V12 ? 7'd64 : 7'd48;

    // =========================================================================
    // Drop Counter
    // =========================================================================

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            drop_counter <= '0;
        else if (attr_valid && fifo_full)
            drop_counter <= drop_counter + 1'b1;
    end

    assign seq_no           = seq_counter;
    assign trace_drop_count = drop_counter;

endmodule

`endif
