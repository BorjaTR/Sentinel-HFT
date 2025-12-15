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
    output logic [31:0] attr_d_egress
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

    // =========================================================================
    // Stage Timers
    // =========================================================================

    stage_timer #(.WIDTH(32)) u_timer_ingress (
        .clk(clk), .rst_n(rst_n),
        .start(timer_ingress_start),
        .stop(timer_ingress_stop),
        .clear(timers_clear),
        .cycles(cycles_ingress),
        .active()
    );

    stage_timer #(.WIDTH(32)) u_timer_core (
        .clk(clk), .rst_n(rst_n),
        .start(timer_core_start),
        .stop(timer_core_stop),
        .clear(timers_clear),
        .cycles(cycles_core),
        .active()
    );

    stage_timer #(.WIDTH(32)) u_timer_risk (
        .clk(clk), .rst_n(rst_n),
        .start(timer_risk_start),
        .stop(timer_risk_stop),
        .clear(timers_clear),
        .cycles(cycles_risk),
        .active()
    );

    stage_timer #(.WIDTH(32)) u_timer_egress (
        .clk(clk), .rst_n(rst_n),
        .start(timer_egress_start),
        .stop(timer_egress_stop),
        .clear(timers_clear),
        .cycles(cycles_egress),
        .active()
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

    assign timers_clear        = (state == ST_DONE);

    // =========================================================================
    // Interface Signals
    // =========================================================================

    assign up_ready = (state == ST_IDLE);
    assign dn_valid = (state == ST_EGRESS);
    assign dn_data  = captured_data;

    // Attribution output
    assign attr_valid     = (state == ST_DONE);
    assign attr_d_ingress = cycles_ingress;
    assign attr_d_core    = cycles_core;
    assign attr_d_risk    = cycles_risk;
    assign attr_d_egress  = cycles_egress;

endmodule

`endif
