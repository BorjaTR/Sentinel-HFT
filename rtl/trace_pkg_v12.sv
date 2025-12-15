// trace_pkg_v12.sv - Extended trace record with latency attribution
//
// Format evolution:
//   v1.0: 32 bytes (basic)
//   v1.1: 48 bytes (extended timestamps)
//   v1.2: 64 bytes (v1.1 + attribution deltas)
//
// Key design decisions:
//   - v1.2 EXTENDS v1.1, does not replace
//   - First 48 bytes are identical to v1.1
//   - Attribution uses deltas (4x u32 = 16 bytes) not absolute timestamps
//   - Overhead = total - sum(deltas), captures queueing implicitly

`ifndef TRACE_PKG_V12_SV
`define TRACE_PKG_V12_SV

package trace_pkg_v12;

    // Record types (unchanged from v1.1)
    typedef enum logic [7:0] {
        REC_TX_EVENT    = 8'h01,  // Normal transaction
        REC_OVERFLOW    = 8'h02,  // FIFO overflow marker
        REC_RESET       = 8'h03,  // Reset/epoch boundary
        REC_HEARTBEAT   = 8'h04   // Keepalive
    } record_type_t;

    // Flags bitfield (unchanged from v1.1)
    typedef struct packed {
        logic [11:0] reserved;
        logic        risk_rejected;   // Transaction was rejected by risk gate
        logic        backpressure;    // Backpressure was active
        logic        fifo_full;       // Trace FIFO was full
        logic        valid;           // Record contains valid data
    } trace_flags_t;

    // v1.1 record (48 bytes) - for reference
    typedef struct packed {
        logic [7:0]   version;      // 0x01
        record_type_t record_type;
        logic [15:0]  core_id;
        logic [31:0]  seq_no;
        logic [63:0]  t_ingress;
        logic [63:0]  t_egress;
        logic [63:0]  t_host;
        logic [15:0]  tx_id;
        trace_flags_t flags;
        logic [95:0]  reserved;     // 12 bytes reserved
    } trace_record_v11_t;

    // v1.2 record (64 bytes) - extends v1.1 with attribution
    typedef struct packed {
        // === v1.1 HEADER (48 bytes) - BINARY COMPATIBLE ===
        logic [7:0]   version;      // 0x02 for v1.2
        record_type_t record_type;
        logic [15:0]  core_id;
        logic [31:0]  seq_no;
        logic [63:0]  t_ingress;    // Absolute: when transaction entered shell
        logic [63:0]  t_egress;     // Absolute: when transaction exited shell
        logic [63:0]  t_host;       // Host-side timestamp (filled by collector)
        logic [15:0]  tx_id;
        trace_flags_t flags;
        logic [95:0]  reserved;     // 12 bytes reserved for v1.1 compatibility

        // === v1.2 ATTRIBUTION EXTENSION (16 bytes) ===
        logic [31:0]  d_ingress;    // Cycles spent in ingress handling
        logic [31:0]  d_core;       // Cycles spent in core processing
        logic [31:0]  d_risk;       // Cycles spent in risk gate
        logic [31:0]  d_egress;     // Cycles spent in egress serialization
        // Note: overhead = (t_egress - t_ingress) - (d_ingress + d_core + d_risk + d_egress)
        //       This implicitly captures queueing delays between stages
    } trace_record_v12_t;

    // Compile-time size verification
    // synthesis translate_off
    initial begin
        assert($bits(trace_record_v11_t) == 384)
            else $error("v1.1 record must be 48 bytes (384 bits)");
        assert($bits(trace_record_v12_t) == 512)
            else $error("v1.2 record must be 64 bytes (512 bits)");
    end
    // synthesis translate_on

    // Helper function: compute total latency from deltas
    function automatic logic [31:0] sum_deltas(trace_record_v12_t rec);
        return rec.d_ingress + rec.d_core + rec.d_risk + rec.d_egress;
    endfunction

    // Helper function: check if record has valid attribution
    function automatic logic has_attribution(trace_record_v12_t rec);
        return rec.version == 8'h02;
    endfunction

endpackage

`endif
