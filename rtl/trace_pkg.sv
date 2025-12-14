`ifndef TRACE_PKG_SV
`define TRACE_PKG_SV

package trace_pkg;

  // Configurable parameters (localparams in package, modules can override)
  localparam int DATA_WIDTH        = 64;
  localparam int TX_ID_WIDTH       = 64;
  localparam int CYCLE_WIDTH       = 64;
  localparam int INFLIGHT_DEPTH    = 16;
  localparam int TRACE_FIFO_DEPTH  = 64;
  localparam int OPCODE_WIDTH      = 16;
  localparam int META_WIDTH        = 32;

  // Flag bit definitions
  // Bits 0-7:  Core/trace flags
  // Bits 8-15: Risk control flags (from risk_pkg.sv)
  typedef enum logic [15:0] {
    FLAG_NONE           = 16'h0000,
    // Core flags (bits 0-7)
    FLAG_TRACE_DROPPED  = 16'h0001,
    FLAG_CORE_ERROR     = 16'h0002,
    FLAG_INFLIGHT_UNDER = 16'h0004,
    // Risk flags (bits 8-15)
    FLAG_RISK_RATE_LIMITED   = 16'h0100,
    FLAG_RISK_POSITION_LIMIT = 16'h0200,
    FLAG_RISK_NOTIONAL_LIMIT = 16'h0400,
    FLAG_RISK_KILL_SWITCH    = 16'h0800,
    FLAG_RISK_REJECTED       = 16'h1000,
    // Reserved
    FLAG_RESERVED       = 16'h8000
  } trace_flags_e;

  // Trace record structure (256 bits total with defaults)
  // Layout: tx_id[63:0] | t_ingress[63:0] | t_egress[63:0] | flags[15:0] | opcode[15:0] | meta[31:0]
  typedef struct packed {
    logic [TX_ID_WIDTH-1:0]    tx_id;      // 64 bits - transaction ID
    logic [CYCLE_WIDTH-1:0]    t_ingress;  // 64 bits - ingress cycle
    logic [CYCLE_WIDTH-1:0]    t_egress;   // 64 bits - egress cycle
    logic [15:0]               flags;      // 16 bits - status flags
    logic [OPCODE_WIDTH-1:0]   opcode;     // 16 bits - operation code
    logic [META_WIDTH-1:0]     meta;       // 32 bits - metadata
  } trace_record_t;

  // Inflight entry (stored between ingress and egress)
  typedef struct packed {
    logic [TX_ID_WIDTH-1:0]    tx_id;      // 64 bits
    logic [CYCLE_WIDTH-1:0]    t_ingress;  // 64 bits
    logic [OPCODE_WIDTH-1:0]   opcode;     // 16 bits
    logic [META_WIDTH-1:0]     meta;       // 32 bits
  } inflight_entry_t;

  // Computed widths
  localparam int TRACE_RECORD_WIDTH   = $bits(trace_record_t);   // 256 bits
  localparam int INFLIGHT_ENTRY_WIDTH = $bits(inflight_entry_t); // 176 bits

endpackage

`endif
