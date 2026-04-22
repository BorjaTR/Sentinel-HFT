// instrumented_pipeline.sv - Pipeline wrapper with latency attribution
//
// Architecture:
//   ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
//   │ Ingress │───▶│  Core   │───▶│  Risk   │───▶│ Egress  │
//   │ Timer 0 │    │ Timer 1 │    │ Timer 2 │    │ Timer 3 │
//   └─────────┘    └─────────┘    └─────────┘    └─────────┘
//
// Each timer captures cycles spent in that stage.
// Total overhead = total_latency - sum(stage_times)
//
// Wave 2 audit fixes (C-S1-03..05):
//   C-S1-03  This module is a *1-in-flight latency attribution probe*,
//            not a real multi-in-flight pipeline. Keeping the legacy
//            name here to avoid a giant cross-repo rename; a thin
//            alias module `latency_attribution_probe` is provided at
//            the bottom of this file for new call-sites and
//            documentation. Wave 3 (WP3.1) will retire the legacy
//            name.
//   C-S1-04  `timers_clear` now includes `!rst_n` so the clear pulse
//            is definitely high during and immediately after reset,
//            and it also fires on ST_DONE->ST_IDLE (the terminal
//            cycle of the previous tx), which matches the original
//            single-cycle clear semantics. The stage_timer itself
//            resets sat_r on its own `!rst_n` branch, so this is a
//            defence-in-depth change that makes the clear signal
//            self-contained.
//   C-S1-05  Ingress tx_id capture lives in the shell's inflight FIFO
//            (WP1.6 delivered). The probe does not own tx_id; it
//            simply emits attr_valid on ST_DONE, and the shell pairs
//            that against the corresponding FIFO entry.

`ifndef INSTRUMENTED_PIPELINE_SV
`define INSTRUMENTED_PIPELINE_SV

`include "trace_pkg_v12.sv"
`include "stage_timer.sv"

module instrumented_pipeline #(
    parameter int CORE_LATENCY = 10,     // Simulated core processing cycles
    parameter int RISK_LATENCY = 5       // Risk gate evaluation cycles
) (
    input  logic        clk,
    input  logic        rst_n,

    // Upstream interface (orders in)
    input  logic        up_valid,
    output logic        up_ready,
    input  logic [63:0] up_data,

    // Downstream interface (orders out)
    output logic        dn_valid,
    input  logic        dn_ready,
    output logic [63:0] dn_data,

    // Attribution output (active for one cycle when transaction completes)
    output logic        attr_valid,
    output logic [31:0] attr_d_ingress,
    output logic [31:0] attr_d_core,
    output logic [31:0] attr_d_risk,
    output logic [31:0] attr_d_egress,

    // Per-stage saturation flags (C-S0-02) — one bit per stage timer.
    // Sticky from timer start to timers_clear.
    output logic        attr_d_ingress_sat,
    output logic        attr_d_core_sat,
    output logic        attr_d_risk_sat,
    output logic        attr_d_egress_sat
);

    // =========================================================================
    // Pipeline State Machine
    // =========================================================================

    typedef enum logic [2:0] {
        ST_IDLE,
        ST_INGRESS,
        ST_CORE,
        ST_RISK,
        ST_EGRESS,
        ST_DONE
    } state_t;

    state_t state, state_next;

    // Stage counters (simulated processing time)
    logic [31:0] stage_counter;

    // Captured data
    logic [63:0] captured_data;

    // Timer control signals
    logic timer_ingress_start, timer_ingress_stop;
    logic timer_core_start, timer_core_stop;
    logic timer_risk_start, timer_risk_stop;
    logic timer_egress_start, timer_egress_stop;
    logic timers_clear;

    // Timer outputs
    logic [31:0] cycles_ingress, cycles_core, cycles_risk, cycles_egress;
    logic        sat_ingress, sat_core, sat_risk, sat_egress;

    // =========================================================================
    // Stage Timers
    // =========================================================================

    stage_timer #(.WIDTH(32)) u_timer_ingress (
        .clk(clk), .rst_n(rst_n),
        .start(timer_ingress_start),
        .stop(timer_ingress_stop),
        .clear(timers_clear),
        .cycles(cycles_ingress),
        .active(),
        .saturated(sat_ingress)
    );

    stage_timer #(.WIDTH(32)) u_timer_core (
        .clk(clk), .rst_n(rst_n),
        .start(timer_core_start),
        .stop(timer_core_stop),
        .clear(timers_clear),
        .cycles(cycles_core),
        .active(),
        .saturated(sat_core)
    );

    stage_timer #(.WIDTH(32)) u_timer_risk (
        .clk(clk), .rst_n(rst_n),
        .start(timer_risk_start),
        .stop(timer_risk_stop),
        .clear(timers_clear),
        .cycles(cycles_risk),
        .active(),
        .saturated(sat_risk)
    );

    stage_timer #(.WIDTH(32)) u_timer_egress (
        .clk(clk), .rst_n(rst_n),
        .start(timer_egress_start),
        .stop(timer_egress_stop),
        .clear(timers_clear),
        .cycles(cycles_egress),
        .active(),
        .saturated(sat_egress)
    );

    // =========================================================================
    // State Machine
    // =========================================================================

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state         <= ST_IDLE;
            stage_counter <= '0;
            captured_data <= '0;
        end else begin
            state <= state_next;

            case (state)
                ST_IDLE: begin
                    if (up_valid && up_ready) begin
                        captured_data <= up_data;
                        stage_counter <= '0;
                    end
                end

                ST_INGRESS, ST_CORE, ST_RISK: begin
                    stage_counter <= stage_counter + 1'b1;
                end

                ST_EGRESS: begin
                    if (dn_valid && dn_ready) begin
                        stage_counter <= '0;
                    end else begin
                        stage_counter <= stage_counter + 1'b1;
                    end
                end

                default: stage_counter <= '0;
            endcase
        end
    end

    // Next state logic
    always_comb begin
        state_next = state;

        case (state)
            ST_IDLE: begin
                if (up_valid && up_ready)
                    state_next = ST_INGRESS;
            end

            ST_INGRESS: begin
                // Ingress is 1 cycle (capture and validate)
                state_next = ST_CORE;
            end

            ST_CORE: begin
                if (stage_counter >= CORE_LATENCY - 1)
                    state_next = ST_RISK;
            end

            ST_RISK: begin
                if (stage_counter >= CORE_LATENCY + RISK_LATENCY - 1)
                    state_next = ST_EGRESS;
            end

            ST_EGRESS: begin
                if (dn_valid && dn_ready)
                    state_next = ST_DONE;
            end

            ST_DONE: begin
                state_next = ST_IDLE;
            end
        endcase
    end

    // =========================================================================
    // Timer Control
    // =========================================================================

    assign timer_ingress_start = (state == ST_IDLE) && up_valid && up_ready;
    assign timer_ingress_stop  = (state == ST_INGRESS);

    assign timer_core_start    = (state == ST_INGRESS);
    assign timer_core_stop     = (state == ST_CORE) && (stage_counter >= CORE_LATENCY - 1);

    assign timer_risk_start    = (state == ST_CORE) && (stage_counter >= CORE_LATENCY - 1);
    assign timer_risk_stop     = (state == ST_RISK) && (stage_counter >= CORE_LATENCY + RISK_LATENCY - 1);

    assign timer_egress_start  = (state == ST_RISK) && (stage_counter >= CORE_LATENCY + RISK_LATENCY - 1);
    assign timer_egress_stop   = (state == ST_EGRESS) && dn_valid && dn_ready;

    // C-S1-04: include `!rst_n` so the clear pulse is high during and
    // immediately after reset (defence in depth against any future
    // stage_timer variant that doesn't self-clear on reset), and keep
    // the ST_DONE cycle pulse that matches the original single-cycle
    // clear semantics. Note: we deliberately do NOT assert `clear` in
    // ST_IDLE, because stage_timer gives `clear` priority over `start`
    // and a continuous ST_IDLE clear would mask `timer_ingress_start`.
    assign timers_clear        = !rst_n || (state == ST_DONE);

    // =========================================================================
    // Interface Signals
    // =========================================================================

    assign up_ready = (state == ST_IDLE);
    assign dn_valid = (state == ST_EGRESS);
    assign dn_data  = captured_data;

    // Attribution output
    assign attr_valid        = (state == ST_DONE);
    assign attr_d_ingress    = cycles_ingress;
    assign attr_d_core       = cycles_core;
    assign attr_d_risk       = cycles_risk;
    assign attr_d_egress     = cycles_egress;

    // Saturation bits sampled at attr_valid. The timers are cleared on
    // ST_DONE entry (via `timers_clear = (state == ST_DONE)`), so the
    // sticky bits must be read on the ST_DONE cycle itself. The shell
    // captures them into the trace flags on the same cycle that it
    // captures the delta values.
    assign attr_d_ingress_sat = sat_ingress;
    assign attr_d_core_sat    = sat_core;
    assign attr_d_risk_sat    = sat_risk;
    assign attr_d_egress_sat  = sat_egress;

endmodule

// =============================================================================
// latency_attribution_probe - Wave 2 rename alias (C-S1-03)
// -----------------------------------------------------------------------------
// The module above is historically called `instrumented_pipeline`, but it is
// NOT a multi-in-flight pipeline: it holds exactly one transaction at a time
// in the ST_INGRESS -> ST_CORE -> ST_RISK -> ST_EGRESS -> ST_DONE walk, and
// the `up_ready` handshake only asserts in ST_IDLE. The four stage timers
// attribute wall-clock cycles for that single in-flight tx to each phase,
// so the component is most accurately described as a *latency attribution
// probe*.
//
// New call-sites should instantiate `latency_attribution_probe` instead of
// `instrumented_pipeline`. The legacy name is preserved above to avoid a
// giant cross-repo rename churn in Wave 2; Wave 3 (WP3.1) will retire the
// legacy name by collapsing consumers onto the alias.
//
// This alias is a parameter-preserving pass-through with identical ports,
// so the two names are observationally indistinguishable from any outer
// shell that wraps it.
// =============================================================================

module latency_attribution_probe #(
    parameter int CORE_LATENCY = 10,
    parameter int RISK_LATENCY = 5
) (
    input  logic        clk,
    input  logic        rst_n,

    input  logic        up_valid,
    output logic        up_ready,
    input  logic [63:0] up_data,

    output logic        dn_valid,
    input  logic        dn_ready,
    output logic [63:0] dn_data,

    output logic        attr_valid,
    output logic [31:0] attr_d_ingress,
    output logic [31:0] attr_d_core,
    output logic [31:0] attr_d_risk,
    output logic [31:0] attr_d_egress,

    output logic        attr_d_ingress_sat,
    output logic        attr_d_core_sat,
    output logic        attr_d_risk_sat,
    output logic        attr_d_egress_sat
);

    instrumented_pipeline #(
        .CORE_LATENCY(CORE_LATENCY),
        .RISK_LATENCY(RISK_LATENCY)
    ) u_probe (
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
        .attr_d_egress(attr_d_egress),
        .attr_d_ingress_sat(attr_d_ingress_sat),
        .attr_d_core_sat(attr_d_core_sat),
        .attr_d_risk_sat(attr_d_risk_sat),
        .attr_d_egress_sat(attr_d_egress_sat)
    );

endmodule

`endif
