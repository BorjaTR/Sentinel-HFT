`ifndef SYNC_FIFO_SV
`define SYNC_FIFO_SV

// Synchronous FIFO with read/write pointers
// No IP dependencies - pure RTL implementation
module sync_fifo #(
  parameter int WIDTH = 64,
  parameter int DEPTH = 16,
  parameter int ADDR_WIDTH = $clog2(DEPTH)
)(
  input  logic             clk,
  input  logic             rst_n,

  // Write interface
  input  logic             wr_en,
  input  logic [WIDTH-1:0] wr_data,
  output logic             full,

  // Read interface
  input  logic             rd_en,
  output logic [WIDTH-1:0] rd_data,
  output logic             empty,

  // Status
  output logic [ADDR_WIDTH:0] count
);

  // Storage array
  logic [WIDTH-1:0] mem [0:DEPTH-1];

  // Pointers
  logic [ADDR_WIDTH-1:0] wr_ptr;
  logic [ADDR_WIDTH-1:0] rd_ptr;

  // Fill count (one extra bit to distinguish full from empty)
  logic [ADDR_WIDTH:0] fill_count;

  // Status outputs
  assign count = fill_count;
  assign full  = (fill_count == DEPTH[ADDR_WIDTH:0]);
  assign empty = (fill_count == '0);

  // Read data is always available at read pointer
  assign rd_data = mem[rd_ptr];

  // Pointer wrap helper function
  function automatic logic [ADDR_WIDTH-1:0] next_ptr(logic [ADDR_WIDTH-1:0] ptr);
    return (ptr == ADDR_WIDTH'(DEPTH-1)) ? '0 : ptr + 1'b1;
  endfunction

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wr_ptr     <= '0;
      rd_ptr     <= '0;
      fill_count <= '0;
    end else begin
      // Handle read and write operations
      case ({wr_en && !full, rd_en && !empty})
        2'b10: begin  // Write only
          mem[wr_ptr] <= wr_data;
          wr_ptr      <= next_ptr(wr_ptr);
          fill_count  <= fill_count + 1'b1;
        end
        2'b01: begin  // Read only
          rd_ptr     <= next_ptr(rd_ptr);
          fill_count <= fill_count - 1'b1;
        end
        2'b11: begin  // Simultaneous read and write
          mem[wr_ptr] <= wr_data;
          wr_ptr      <= next_ptr(wr_ptr);
          rd_ptr      <= next_ptr(rd_ptr);
          // fill_count unchanged
        end
        default: begin
          // No operation - maintain state
        end
      endcase
    end
  end

endmodule

`endif
