// reset_sync.sv - Async-assert, synchronous-deassert reset synchronizer.
//
// Purpose
// -------
// Moves a reset from an asynchronous source (e.g. global rst_n, or a
// reset generated in a foreign clock domain) into a target clock
// domain without introducing recovery/removal metastability on
// de-assertion.
//
// Semantics
// ---------
//   * Assertion (rst_n_in == 0) is propagated asynchronously to
//     rst_n_out.
//   * De-assertion (rst_n_in == 1) is held off until STAGES rising
//     edges of `clk` have passed with rst_n_in continuously high,
//     so downstream flip-flops see the de-assert edge synchronously
//     with `clk` and cannot enter recovery violation.
//
// Wave 2 audit fix (E-S1-02/03):
//   This module is the canonical reset-crossing primitive referenced
//   by the ethernet CDC hand-off. The convention throughout the
//   Sentinel RTL is active-low reset (`rst_n`), so the synchronizer
//   is built around that convention directly rather than inverting.
//
// Synthesis notes
// ---------------
//   * STAGES >= 2 is mandatory; 3 is recommended for 322 MHz CMAC
//     domain at -2L speed grade.
//   * `(* ASYNC_REG = "TRUE" *)` attributes are emitted so Vivado
//     places the flops into the same slice and applies MAX_DELAY
//     timing. Verilator and slang ignore the attribute strings.
//   * No combinational logic between the flops — they are a pure
//     shift register whose input is tied to 1'b1 and whose async
//     clear is rst_n_in.

`ifndef RESET_SYNC_SV
`define RESET_SYNC_SV

module reset_sync #(
    parameter int STAGES = 3
) (
    input  logic clk,
    input  logic rst_n_in,    // source-domain (or truly async) reset, active low
    output logic rst_n_out    // target-domain reset, active low
);

    // Elaboration-time guard: at least two stages are required.
    /* verilator lint_off UNUSED */
    localparam int STAGES_OK = 1 / (STAGES >= 2 ? 1 : 0);
    /* verilator lint_on UNUSED */

    (* ASYNC_REG = "TRUE" *) logic [STAGES-1:0] sync_r;

    always_ff @(posedge clk or negedge rst_n_in) begin
        if (!rst_n_in) begin
            sync_r <= '0;
        end else begin
            sync_r <= {sync_r[STAGES-2:0], 1'b1};
        end
    end

    assign rst_n_out = sync_r[STAGES-1];

endmodule

`endif
