// stage_timer.sv - Cycle counter for a single pipeline stage
//
// Usage: Instantiate at each stage boundary. Assert 'active' while
// the stage is processing. Read 'cycles' when transaction completes.

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
    output logic             active      // Currently counting
);

    logic [WIDTH-1:0] counter;
    logic             counting;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            counter  <= '0;
            counting <= 1'b0;
        end else begin
            if (clear) begin
                counter  <= '0;
                counting <= 1'b0;
            end else if (start && !counting) begin
                counter  <= 32'd1;  // Start at 1 (this cycle counts)
                counting <= 1'b1;
            end else if (stop && counting) begin
                counting <= 1'b0;
                // counter holds final value
            end else if (counting) begin
                counter <= counter + 1'b1;
            end
        end
    end

    assign cycles = counter;
    assign active = counting;

endmodule

`endif
