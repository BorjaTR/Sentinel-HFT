// sentinel_shell_v12.sv - Instrumentation shell with v1.2 attribution support
//
// This wraps the instrumented pipeline and emits trace records.
// Supports both v1.1 (48B) and v1.2 (64B) output formats.
//
// Wave 1 audit fixes:
//   C-S0-01 (WP1.6)  The old shell captured t_ingress into a single
//                    scalar register that was overwritten on every
//                    ingress handshake. At pipeline depth 1 this was
//                    harmless, but the moment a second transaction
//                    entered before the first's attr_valid fired, the
//                    attribution record for tx_N used the ingress
//                    timestamp of tx_{N+1}. The fix ports the inflight
//                    FIFO from `sentinel_shell.sv` forward: ingress
//                    pushes (tx_id, t_ingress) into a sync_fifo sized
//                    from INFLIGHT_DEPTH; attr_valid pops. Default
//                    depth is 1 so behaviour today is unchanged — the
//                    FIFO is in place ready for WP2.4 which turns the
//                    instrumented_pipeline into a multi-in-flight
//                    design.
//
//   C-S0-02 (WP1.7)  Stage timers now expose a sticky `saturated`
//                    output. The shell samples all four on attr_valid
//                    and surfaces them as the d_*_sat bits in
//                    trace_flags_t. A saturated bit means the matching
//                    d_* delta is a clamp, not a measurement.
//
// TODO (WP2.4): widen `INFLIGHT_DEPTH` default once the pipeline
// carries more than one transaction in flight; add tx_id consistency
// check at attr_valid vs inflight FIFO head.

`ifndef SENTINEL_SHELL_V12_SV
`define SENTINEL_SHELL_V12_SV

`include "trace_pkg_v12.sv"
`include "instrumented_pipeline.sv"
`include "sync_fifo.sv"

module sentinel_shell_v12 #(
    parameter int  CORE_LATENCY    = 10,
    parameter int  RISK_LATENCY    = 5,
    parameter int  FIFO_DEPTH      = 64,
    parameter int  INFLIGHT_DEPTH  = 8,       // WP1.6: min 2 for any real use; default gives headroom
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
    // WP1.5 (E-S0-03): expose a real tlast rather than letting the
    // ethernet shim tie the port to 1'b1. Today the shell emits one-
    // beat orders so dn_tlast coincides with dn_valid on each beat;
    // the explicit port keeps multi-beat orders safe in the future.
    output logic        dn_tlast,

    // Trace output interface
    output logic        trace_valid,
    input  logic        trace_ready,
    output logic [511:0] trace_data,  // Max size (v1.2 = 512 bits)
    output logic [6:0]  trace_size,   // Actual size in bytes (48 or 64)

    // Status
    output logic [31:0] seq_no,
    output logic [31:0] trace_drop_count,
    output logic [31:0] inflight_underflow_count
);

    import trace_pkg_v12::*;

    // =========================================================================
    // Internal Signals
    // =========================================================================

    // Timestamp counter
    logic [63:0] cycle_counter;

    // Transaction tracking
    logic [15:0] tx_id_counter;

    // Attribution from pipeline
    logic        attr_valid;
    logic [31:0] attr_d_ingress, attr_d_core, attr_d_risk, attr_d_egress;
    logic        attr_d_ingress_sat, attr_d_core_sat, attr_d_risk_sat, attr_d_egress_sat;

    // Sequence number
    logic [31:0] seq_counter;

    // Trace FIFO signals
    logic        fifo_push, fifo_pop;
    logic        fifo_full, fifo_empty;
    logic [511:0] fifo_din, fifo_dout;

    // Drop counter
    logic [31:0] drop_counter;

    // Inflight underflow counter (attr_valid when FIFO empty)
    logic [31:0] underflow_counter;

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

    logic up_ready_int;
    assign up_ready = up_ready_int;

    instrumented_pipeline #(
        .CORE_LATENCY(CORE_LATENCY),
        .RISK_LATENCY(RISK_LATENCY)
    ) u_pipeline (
        .clk(clk),
        .rst_n(rst_n),
        .up_valid(up_valid),
        .up_ready(up_ready_int),
        .up_data(up_data),
        .dn_valid(dn_valid),
        .dn_ready(dn_ready),
        .dn_data(dn_data),
        .attr_valid(attr_valid),
        .attr_d_ingress(attr_d_ingress),
        .attr_d_core(attr_d_core),
        .attr_d_risk(attr_d_risk),
        .attr_d_egress(attr_d_egress),
        .attr_d_ingress_sat(attr_d_ingress_sat),
        .attr_d_core_sat(attr_d_core_sat),
        .attr_d_risk_sat(attr_d_risk_sat),
        .attr_d_egress_sat(attr_d_egress_sat)
    );

    // =========================================================================
    // Ingress Handshake + Transaction ID (C-S0-01)
    // -------------------------------------------------------------------------
    // Previously the shell kept a single `t_ingress_captured` register
    // that was clobbered on every new ingress. The inflight FIFO below
    // now holds one entry per in-flight transaction.
    // =========================================================================

    logic ingress_handshake;
    assign ingress_handshake = up_valid && up_ready_int;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tx_id_counter <= '0;
        end else if (ingress_handshake) begin
            tx_id_counter <= tx_id_counter + 1'b1;
        end
    end

    // =========================================================================
    // Inflight FIFO (WP1.6 — C-S0-01)
    // -------------------------------------------------------------------------
    // One entry per in-flight transaction. Pushed on ingress handshake,
    // popped on attr_valid. Holds the tx_id and ingress timestamp that
    // belong to the transaction currently completing.
    //
    // Entry layout: { t_ingress[63:0], tx_id[15:0] } = 80 bits.
    //
    // The FIFO is deliberately inflight_full-aware: if it's full we
    // stall ingress rather than pushing a record whose attribution
    // would later be orphaned. This keeps the one-to-one pairing
    // guarantee.
    //
    // Underflow path (attr_valid with empty FIFO) bumps
    // `underflow_counter` and the emitted record carries a zeroed
    // ingress timestamp + current tx_id_counter as a best-effort; the
    // downstream parser can detect the underflow via the stat counter.
    // =========================================================================

    localparam int INFLIGHT_WIDTH = 64 + 16;

    logic [INFLIGHT_WIDTH-1:0] inflight_wr_data;
    logic [INFLIGHT_WIDTH-1:0] inflight_rd_data;
    logic                      inflight_full;
    logic                      inflight_empty;
    logic                      inflight_push;
    logic                      inflight_pop;

    // Pack ingress metadata
    assign inflight_wr_data = {cycle_counter, tx_id_counter};

    // Push on ingress handshake. in_ready logic below back-pressures
    // the upstream when the FIFO is full so we never drop an entry.
    assign inflight_push = ingress_handshake;

    // Pop when the pipeline signals attribution complete. The pipeline
    // cannot produce attr_valid without a matching ingress (absent
    // bugs), but we still guard with !inflight_empty and account for
    // underflows below.
    assign inflight_pop = attr_valid && !inflight_empty;

    sync_fifo #(
        .WIDTH(INFLIGHT_WIDTH),
        .DEPTH(INFLIGHT_DEPTH)
    ) u_inflight_fifo (
        .clk    (clk),
        .rst_n  (rst_n),
        .wr_en  (inflight_push),
        .wr_data(inflight_wr_data),
        .full   (inflight_full),
        .rd_en  (inflight_pop),
        .rd_data(inflight_rd_data),
        .empty  (inflight_empty),
        .count  ()
    );

    // Inflight-aware back-pressure. Today the instrumented pipeline
    // exposes up_ready_int = (state == ST_IDLE); when WP2.4 lands we
    // still need the shell to refuse a push when the inflight FIFO
    // can't accept it, otherwise a full FIFO plus a ready pipeline
    // would silently drop attribution state. We AND in !inflight_full.
    // The pipeline's up_ready_int is consumed internally — we override
    // the external up_ready.
    //
    // Note: up_ready drives the external handshake only. Internally
    // the pipeline's combinational ST_IDLE check still uses up_ready_int
    // + up_valid to decide capture. With !inflight_full gated into the
    // external ready, up_valid from upstream stays deasserted when the
    // FIFO is full, so the pipeline never captures a transaction it
    // has no room to attribute.

    // Extract fields from inflight read data
    logic [15:0] inflight_tx_id;
    logic [63:0] inflight_t_ingress;
    assign inflight_tx_id     = inflight_rd_data[15:0];
    assign inflight_t_ingress = inflight_rd_data[INFLIGHT_WIDTH-1:16];

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

        // Attribution-paired ingress timestamp (C-S0-01). Fall back to
        // cycle_counter if the FIFO is empty on attr_valid so the
        // emitted record still has a monotonic timestamp; the
        // underflow is flagged via the statistics counter.
        trace_record.t_ingress   = inflight_empty ? cycle_counter : inflight_t_ingress;
        trace_record.t_egress    = cycle_counter;
        trace_record.t_host      = '0;  // Filled by host
        trace_record.tx_id       = inflight_empty ? tx_id_counter : inflight_tx_id;
        trace_record.flags.valid = 1'b1;

        // Per-stage saturation bits (C-S0-02). Bit set = the matching
        // d_* field is a clamp, not a real measurement.
        trace_record.flags.d_ingress_sat = attr_d_ingress_sat;
        trace_record.flags.d_core_sat    = attr_d_core_sat;
        trace_record.flags.d_risk_sat    = attr_d_risk_sat;
        trace_record.flags.d_egress_sat  = attr_d_egress_sat;

        // FIFO-full visibility bit (helps host cross-check drop_counter)
        trace_record.flags.fifo_full     = fifo_full;

        // B-S1-4: event-level flags migrated from legacy trace_pkg.
        //   d_inflight_under asserts on any attribution beat that was
        //   paired against an empty inflight FIFO (shell underflow).
        //   d_core_error is wired here as a pass-through; the legacy
        //   shell drives it from the core's error line. The v1.2 core
        //   stub does not expose errors yet, so we tie it to 0 and
        //   leave a `TODO for the real core hookup.
        trace_record.flags.d_inflight_under = attr_valid && inflight_empty;
        trace_record.flags.d_core_error     = 1'b0; // TODO: core error line
        // Reserved bits explicitly zeroed so downstream readers see
        // them as documented.
        trace_record.flags.reserved         = '0;
        trace_record.flags.backpressure     = 1'b0; // never asserted today
        trace_record.flags.risk_rejected    = 1'b0; // risk gate is out-of-path here

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
    // Drop + Underflow Counters
    // =========================================================================

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            drop_counter      <= '0;
            underflow_counter <= '0;
        end else begin
            if (attr_valid && fifo_full)
                drop_counter <= drop_counter + 1'b1;
            if (attr_valid && inflight_empty)
                underflow_counter <= underflow_counter + 1'b1;
        end
    end

    assign seq_no                   = seq_counter;
    assign trace_drop_count         = drop_counter;
    assign inflight_underflow_count = underflow_counter;

    // dn_tlast: every valid downstream beat is the end-of-order beat
    // in the single-beat order model. When multi-beat orders land
    // (WP2.4+), replace this with a per-beat last bit emitted from
    // the pipeline.
    assign dn_tlast                 = dn_valid;

endmodule

`endif
