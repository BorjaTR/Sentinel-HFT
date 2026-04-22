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

    // Flags bitfield — 16 bits total. Layout from MSB to LSB so that
    // older parsers reading the same 16-bit word as a raw bitmask see
    // the v1.1-era bits (valid/fifo_full/backpressure/risk_rejected) in
    // the same positions; the new sat bits occupy what used to be the
    // MSB of the reserved span.
    //
    // Wave 1 audit fix (C-S0-02):
    //   - Added d_{ingress,core,risk,egress}_sat sticky bits. Each is
    //     driven by the corresponding stage_timer saturated output and
    //     captured into the trace record for the transaction that owns
    //     the saturating interval. Downstream tooling treats any sat
    //     bit as "this stage stalled for >= 2^WIDTH cycles, the delta
    //     field is a clamp, not a measurement".
    // Wave 2 audit fix (B-S1-4):
    //   The legacy trace_pkg.sv `trace_flags_e` enum carried two
    //   event-level flags that have no equivalent in v1.1:
    //       FLAG_CORE_ERROR      (core raised an error mid-tx)
    //       FLAG_INFLIGHT_UNDER  (egress saw attr_valid with empty
    //                             inflight FIFO — shell underflow)
    //   These are migrated to v1.2 by carving two bits out of the
    //   MSB-side `reserved` span. Old v1.1 parsers that treat bits
    //   [15:8] as opaque "reserved, don't interpret" continue to work
    //   unchanged; v1.2-aware parsers read the new bits by name.
    //
    //   Position choice: the core_error / inflight_under bits sit
    //   immediately above the four sat bits (bits 9:8), so the
    //   stage-delta bits are still contiguous at [7:4] and the v1.1
    //   low nibble at [3:0] is untouched.
    typedef struct packed {
        logic [5:0]  reserved;         // 6 reserved bits, zero (was 8)
        logic        d_core_error;     // B-S1-4: core raised error mid-tx
        logic        d_inflight_under; // B-S1-4: attr_valid with empty inflight FIFO
        logic        d_ingress_sat;    // Stage timer for ingress saturated (C-S0-02)
        logic        d_core_sat;       // Stage timer for core saturated
        logic        d_risk_sat;       // Stage timer for risk saturated
        logic        d_egress_sat;     // Stage timer for egress saturated
        logic        risk_rejected;    // Transaction was rejected by risk gate
        logic        backpressure;     // Backpressure was active
        logic        fifo_full;        // Trace FIFO was full
        logic        valid;            // Record contains valid data
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

    // Compile-time size verification.
    // Wave 0 WP0.1 fix: `initial begin` at package scope is rejected
    // by Verilator >= 5.x and slang (IEEE 1800-2017 §3.3 does not
    // permit procedural blocks in packages). The invariant is now a
    // `localparam` that forces an elaboration-time error if the sizes
    // ever drift. The `/* verilator lint_off UNUSED */` guards exist
    // because the parameter may otherwise be reported as unused.
    /* verilator lint_off UNUSED */
    localparam int V11_RECORD_BITS = $bits(trace_record_v11_t);
    localparam int V12_RECORD_BITS = $bits(trace_record_v12_t);
    // These will fail to elaborate (division-by-zero) if the struct
    // widths ever drift from 384 and 512 bits respectively.
    localparam int V11_SIZE_OK = 1 / (V11_RECORD_BITS == 384 ? 1 : 0);
    localparam int V12_SIZE_OK = 1 / (V12_RECORD_BITS == 512 ? 1 : 0);
    /* verilator lint_on UNUSED */

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
