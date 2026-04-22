// stage_timer.sv - Cycle counter for a single pipeline stage
//
// Usage: Instantiate at each stage boundary. Assert 'active' while
// the stage is processing. Read 'cycles' when transaction completes.
//
// Wave 1 audit fixes (C-S0-02):
//   - Added a sticky `saturated` output. It asserts on the cycle the
//     counter would wrap (counter == '1 && counting && !stop && !clear)
//     and stays asserted until `clear` is applied. Previously the
//     counter silently wrapped and handed the shell a legitimate-looking
//     small delta on a stage that had actually stalled for 2^WIDTH
//     cycles. The shell now surfaces this bit via trace_flags_t.
//     See AUDIT_FIX_PLAN.md WP1.7.

`ifndef STAGE_TIMER_SV
`define STAGE_TIMER_SV

module stage_timer #(
    parameter int WIDTH = 32  // Counter width
) (
    input  logic             clk,
    input  logic             rst_n,

    // Control
    input  logic             start,      // Pulse: begin counting
    input  logic             stop,       // Pulse: stop counting
    input  logic             clear,      // Pulse: reset counter

    // Output
    output logic [WIDTH-1:0] cycles,     // Elapsed cycles
    output logic             active,     // Currently counting
    output logic             saturated   // Sticky: counter wrapped before stop (C-S0-02)
);

    logic [WIDTH-1:0] counter;
    logic             counting;
    logic             sat_r;

    // Detect wrap on the cycle that would take us past '1. The condition
    // is combinational off the registered state so it fires before the
    // next posedge overwrites `counter` with 0.
    localparam logic [WIDTH-1:0] MAX_VAL = {WIDTH{1'b1}};
    logic wrap_event;
    assign wrap_event = counting && !stop && (counter == MAX_VAL);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            counter  <= '0;
            counting <= 1'b0;
            sat_r    <= 1'b0;
        end else begin
            if (clear) begin
                counter  <= '0;
                counting <= 1'b0;
                sat_r    <= 1'b0;
            end else if (start && !counting) begin
                counter  <= {{(WIDTH-1){1'b0}}, 1'b1};  // Start at 1 (this cycle counts)
                counting <= 1'b1;
                // sat_r intentionally preserved across start/stop edges
                // until a full `clear` — a mid-burst retime should not
                // erase evidence of a previous saturation event.
            end else if (stop && counting) begin
                counting <= 1'b0;
                // counter holds final value
            end else if (counting) begin
                if (wrap_event) begin
                    // Clamp: hold at max, mark sticky saturated. Never
                    // roll over — a tiny delta on a multi-minute stall
                    // is worse than a clamped max.
                    counter <= MAX_VAL;
                    sat_r   <= 1'b1;
                end else begin
                    counter <= counter + 1'b1;
                end
            end
        end
    end

    assign cycles    = counter;
    assign active    = counting;
    assign saturated = sat_r;

endmodule

`endif
