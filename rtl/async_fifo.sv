// async_fifo.sv - Dual-clock (asynchronous) FIFO with gray-coded pointers.
//
// Purpose
// -------
// Safe data hand-off between two unrelated clock domains. Used on the
// Sentinel CMAC <-> core boundary so the 322.265625 MHz CMAC user
// clock and the core clock can be genuinely asynchronous (Wave 2
// audit fix E-S1-02/03: removes the "CMAC clk == core clk" assumption
// baked into the WITH_CMAC=1 top-level path).
//
// Architecture
// ------------
//   write domain (clk_w)                 read domain (clk_r)
//   ----------------------               ----------------------
//   wr_addr_bin (ADDR_W bits)            rd_addr_bin (ADDR_W bits)
//     |                                    |
//     v                                    v
//   bin2gray                              bin2gray
//     |                                    |
//     v                                    v
//   wr_gray_r  --->  (ASYNC_REG x N) ---> wr_gray_rsync (compared vs rd_gray)
//   rd_gray_rsync <--- (ASYNC_REG x N) <--- rd_gray_r
//
//   full  = (wr_gray_next == {~rd_gray_rsync[ADDR_W:ADDR_W-1],
//                              rd_gray_rsync[ADDR_W-2:0]})
//   empty = (rd_gray_r == wr_gray_rsync)
//
// The classic Cummings SNUG2002 formulation: pointer width is
// (ADDR_W + 1), so the MSB lets the pointer wrap once before
// aliasing empty and full. Gray code guarantees at most one bit
// toggles per clock across the crossing, so a single metastable flop
// samples a transitional value only on that bit -- the rest of the
// pointer is by definition stable.
//
// Parameters
// ----------
//   WIDTH : data width
//   DEPTH : FIFO depth (must be a power of 2)
//
// Signals
// -------
//   wr_en   : write strobe in clk_w domain. Data is captured on the
//             same edge; wr_en must be gated externally by !full.
//   rd_en   : read strobe in clk_r domain; data presented on
//             rd_data is the entry at rd_addr BEFORE the increment
//             (classic "first-word-fall-through" requires a forward
//             register; this FIFO is the non-FWFT variant, so
//             rd_data is registered and available one cycle after
//             rd_en).
//
// Synthesis notes
// ---------------
//   * `(* ASYNC_REG = "TRUE" *)` on the synchronizer flops.
//   * Memory is inferred as distributed/block RAM by Vivado
//     depending on DEPTH.
//   * No registered output on the read side -- rd_data is the
//     combinational read of `mem[rd_addr_bin]`, which gives
//     "read latency 0" semantics. The non-FWFT discipline is
//     enforced by the external consumer sampling on rd_en &&
//     !empty.

`ifndef ASYNC_FIFO_SV
`define ASYNC_FIFO_SV

module async_fifo #(
    parameter int WIDTH  = 64,
    parameter int DEPTH  = 32,
    parameter int SYNC_STAGES = 2
) (
    // Write side
    input  logic             clk_w,
    input  logic             rst_n_w,
    input  logic             wr_en,
    input  logic [WIDTH-1:0] wr_data,
    output logic             full,

    // Read side
    input  logic             clk_r,
    input  logic             rst_n_r,
    input  logic             rd_en,
    output logic [WIDTH-1:0] rd_data,
    output logic             empty,

    // Optional occupancy sampling (write-domain view; approximate
    // because it uses synchronized read pointer).
    output logic [$clog2(DEPTH):0] wr_occupancy
);

    // Elaboration-time invariants.
    /* verilator lint_off UNUSED */
    localparam int DEPTH_POW2_OK = 1 / ((DEPTH >= 2) && ((DEPTH & (DEPTH - 1)) == 0) ? 1 : 0);
    localparam int SYNC_OK       = 1 / (SYNC_STAGES >= 2 ? 1 : 0);
    /* verilator lint_on UNUSED */

    localparam int ADDR_W = $clog2(DEPTH);

    // Pointers are ADDR_W+1 wide so the MSB disambiguates full vs empty.
    logic [ADDR_W:0] wr_ptr_bin_r, wr_ptr_bin_n;
    logic [ADDR_W:0] wr_ptr_gray_r, wr_ptr_gray_n;
    logic [ADDR_W:0] rd_ptr_bin_r, rd_ptr_bin_n;
    logic [ADDR_W:0] rd_ptr_gray_r, rd_ptr_gray_n;

    // Synchronized copies (read gray -> write domain, write gray -> read domain).
    (* ASYNC_REG = "TRUE" *) logic [ADDR_W:0] rd_gray_wclk [SYNC_STAGES-1:0];
    (* ASYNC_REG = "TRUE" *) logic [ADDR_W:0] wr_gray_rclk [SYNC_STAGES-1:0];

    // ---- bin->gray helper (combinational) ----
    function automatic logic [ADDR_W:0] bin2gray(input logic [ADDR_W:0] bin);
        bin2gray = bin ^ (bin >> 1);
    endfunction

    // ---- Write-side pointer ----
    assign wr_ptr_bin_n  = wr_ptr_bin_r + {{ADDR_W{1'b0}}, (wr_en && !full) ? 1'b1 : 1'b0};
    assign wr_ptr_gray_n = bin2gray(wr_ptr_bin_n);

    always_ff @(posedge clk_w or negedge rst_n_w) begin
        if (!rst_n_w) begin
            wr_ptr_bin_r  <= '0;
            wr_ptr_gray_r <= '0;
        end else begin
            wr_ptr_bin_r  <= wr_ptr_bin_n;
            wr_ptr_gray_r <= wr_ptr_gray_n;
        end
    end

    // ---- Read-side pointer ----
    assign rd_ptr_bin_n  = rd_ptr_bin_r + {{ADDR_W{1'b0}}, (rd_en && !empty) ? 1'b1 : 1'b0};
    assign rd_ptr_gray_n = bin2gray(rd_ptr_bin_n);

    always_ff @(posedge clk_r or negedge rst_n_r) begin
        if (!rst_n_r) begin
            rd_ptr_bin_r  <= '0;
            rd_ptr_gray_r <= '0;
        end else begin
            rd_ptr_bin_r  <= rd_ptr_bin_n;
            rd_ptr_gray_r <= rd_ptr_gray_n;
        end
    end

    // ---- CDC: read-gray into write clock ----
    always_ff @(posedge clk_w or negedge rst_n_w) begin
        if (!rst_n_w) begin
            for (int i = 0; i < SYNC_STAGES; i++)
                rd_gray_wclk[i] <= '0;
        end else begin
            rd_gray_wclk[0] <= rd_ptr_gray_r;
            for (int i = 1; i < SYNC_STAGES; i++)
                rd_gray_wclk[i] <= rd_gray_wclk[i-1];
        end
    end

    // ---- CDC: write-gray into read clock ----
    always_ff @(posedge clk_r or negedge rst_n_r) begin
        if (!rst_n_r) begin
            for (int i = 0; i < SYNC_STAGES; i++)
                wr_gray_rclk[i] <= '0;
        end else begin
            wr_gray_rclk[0] <= wr_ptr_gray_r;
            for (int i = 1; i < SYNC_STAGES; i++)
                wr_gray_rclk[i] <= wr_gray_rclk[i-1];
        end
    end

    // ---- Full: wr_gray_next == rd_gray_sync with top 2 bits inverted ----
    logic [ADDR_W:0] rd_gray_sync;
    logic [ADDR_W:0] wr_gray_sync;
    assign rd_gray_sync = rd_gray_wclk[SYNC_STAGES-1];
    assign wr_gray_sync = wr_gray_rclk[SYNC_STAGES-1];

    assign full  = (wr_ptr_gray_n ==
                    {~rd_gray_sync[ADDR_W:ADDR_W-1],
                     rd_gray_sync[ADDR_W-2:0]});
    assign empty = (rd_ptr_gray_n == wr_gray_sync);

    // ---- Occupancy (write-clock view, approximate) ----
    // Convert synchronized rd_gray back to binary and subtract from
    // wr_ptr_bin_r. Because rd_gray_sync is two flops old, this is a
    // conservative (over-count) estimate — never reports "less full"
    // than reality.
    logic [ADDR_W:0] rd_bin_wclk;
    always_comb begin
        rd_bin_wclk[ADDR_W] = rd_gray_sync[ADDR_W];
        for (int i = ADDR_W-1; i >= 0; i--)
            rd_bin_wclk[i] = rd_gray_sync[i] ^ rd_bin_wclk[i+1];
    end
    assign wr_occupancy = wr_ptr_bin_r - rd_bin_wclk;

    // ---- Memory ----
    // Simple inferred RAM. Single write port (clk_w), single read port
    // (combinational via clk_r's rd_addr). Vivado will typically map
    // DEPTH*WIDTH up to 1 kb into distributed RAM; bigger into BRAM.
    logic [WIDTH-1:0] mem [DEPTH];

    always_ff @(posedge clk_w) begin
        if (wr_en && !full)
            mem[wr_ptr_bin_r[ADDR_W-1:0]] <= wr_data;
    end

    assign rd_data = mem[rd_ptr_bin_r[ADDR_W-1:0]];

endmodule

`endif
