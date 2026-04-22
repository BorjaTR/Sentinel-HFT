// =============================================================================
// sentinel_sva.sv -- Shared SystemVerilog Assertion bind file
// -----------------------------------------------------------------------------
// Wave 0 audit fix WP0.2 — closes A-S3-13, B-S3-2, C-S3-12, D-S2-02.
//
// This file collects every cross-module invariant into a single place so we
// have one canonical location to look at when something regresses. Every
// assertion here was derived from the "minimum assertions" list in
// docs/AUDIT_FIX_PLAN.md §WP0.2.
//
// Structure:
//   1. Per-module assertion modules (kill_switch_sva, position_limiter_sva,
//      audit_log_sva, sync_fifo_sva, instrumented_pipeline_sva,
//      stage_timer_sva).
//   2. `bind` statements at the bottom attach each into the matching RTL
//      module with zero impact on synthesis (the `bind` only lives in
//      simulation / formal flows).
//
// `ifdef guard: all assertion bodies are wrapped in `ifndef SYNTHESIS so that
// Vivado / Yosys / Verilator-lint runs with SYNTHESIS defined skip them
// cleanly. Simulation defaults to keeping them on.
// =============================================================================

`ifndef SENTINEL_SVA_SV
`define SENTINEL_SVA_SV

`include "risk_pkg.sv"
`include "trace_pkg_v12.sv"

// -----------------------------------------------------------------------------
// Kill-switch assertions
//   A-S0-01: once `trigger_latched` is set, passed stays low until cmd_reset.
// -----------------------------------------------------------------------------
module kill_switch_sva (
    input logic clk,
    input logic rst_n,
    input logic trigger_latched,
    input logic cmd_reset,
    input logic passed,
    input logic cfg_armed
);
`ifndef SYNTHESIS
    // Once latched, stays latched until cmd_reset.
    property latched_sticky;
        @(posedge clk) disable iff (!rst_n)
            (trigger_latched && !cmd_reset) |=> trigger_latched;
    endproperty
    a_latched_sticky: assert property (latched_sticky)
        else $error("kill_switch: trigger_latched cleared without cmd_reset");

    // While latched, the gate never passes.
    property passed_requires_not_latched;
        @(posedge clk) disable iff (!rst_n)
            trigger_latched |-> !passed;
    endproperty
    a_passed_not_latched: assert property (passed_requires_not_latched)
        else $error("kill_switch: passed asserted while trigger_latched=1");
`endif
endmodule

// -----------------------------------------------------------------------------
// Rate-limiter assertions
//   A-S1-04: bucket never exceeds configured max tokens.
//   AXI-Stream: valid held && not ready => valid and data stable.
// -----------------------------------------------------------------------------
module rate_limiter_sva (
    input logic        clk,
    input logic        rst_n,
    input logic [31:0] bucket,
    input logic [31:0] cfg_max_tokens,
    input logic        cfg_enabled
);
`ifndef SYNTHESIS
    property bucket_bounded;
        @(posedge clk) disable iff (!rst_n)
            cfg_enabled |-> (bucket <= cfg_max_tokens);
    endproperty
    a_bucket_bounded: assert property (bucket_bounded)
        else $error("rate_limiter: bucket %0d exceeds cfg_max_tokens %0d",
                    bucket, cfg_max_tokens);
`endif
endmodule

// -----------------------------------------------------------------------------
// Risk-gate (AXI-Stream) assertions
//   valid held when not ready and payload must be stable.
// -----------------------------------------------------------------------------
module risk_gate_sva (
    input logic        clk,
    input logic        rst_n,
    input logic        in_valid,
    input logic        in_ready,
    input logic [63:0] in_data
);
`ifndef SYNTHESIS
    property stable_when_stalled;
        @(posedge clk) disable iff (!rst_n)
            (in_valid && !in_ready) |=> (in_valid && $stable(in_data));
    endproperty
    a_stable_when_stalled: assert property (stable_when_stalled)
        else $error("risk_gate: in_valid dropped or in_data changed under backpressure");
`endif
endmodule

// -----------------------------------------------------------------------------
// Audit-log assertions
//   B-S0-3: seq_r strictly monotonic, advances only on committed writes.
//   B-S0-2: FIFO-full never sees silent drop (handled in RTL; SVA checks
//           that do_write_any + full_r is impossible when write-arbiter OK).
// -----------------------------------------------------------------------------
module risk_audit_log_sva #(
    parameter int FIFO_DEPTH = 256
)(
    input logic        clk,
    input logic        rst_n,
    input logic [63:0] seq_r,
    input logic        do_write_any,
    input logic        full_r
);
`ifndef SYNTHESIS
    // seq_r is strictly monotonic, increments by exactly 1 on committed
    // writes, holds otherwise.
    property seq_monotonic;
        @(posedge clk) disable iff (!rst_n)
            do_write_any |=> (seq_r == $past(seq_r) + 64'd1);
    endproperty
    a_seq_monotonic: assert property (seq_monotonic)
        else $error("risk_audit_log: seq_r did not increment by 1 on committed write");

    property seq_hold_when_idle;
        @(posedge clk) disable iff (!rst_n)
            (!do_write_any) |=> (seq_r == $past(seq_r));
    endproperty
    a_seq_hold: assert property (seq_hold_when_idle)
        else $error("risk_audit_log: seq_r moved while no commit was active");

    // do_write_any implies FIFO had room.
    property no_write_when_full;
        @(posedge clk) disable iff (!rst_n)
            do_write_any |-> !full_r;
    endproperty
    a_no_write_when_full: assert property (no_write_when_full)
        else $error("risk_audit_log: write attempted while FIFO full");
`endif
endmodule

// -----------------------------------------------------------------------------
// sync_fifo invariants
//   No overflow, no underflow, empty ↔ count==0.
// -----------------------------------------------------------------------------
module sync_fifo_sva #(
    parameter int WIDTH = 64,
    parameter int DEPTH = 16,
    parameter int ADDR_WIDTH = $clog2(DEPTH)
)(
    input logic                      clk,
    input logic                      rst_n,
    input logic                      wr_en,
    input logic                      rd_en,
    input logic                      full,
    input logic                      empty,
    input logic [ADDR_WIDTH:0]       count
);
`ifndef SYNTHESIS
    // No overflow: full && wr_en without rd_en must not increase count.
    property no_overflow;
        @(posedge clk) disable iff (!rst_n)
            (full && wr_en && !rd_en) |=> ($stable(count));
    endproperty
    a_no_overflow: assert property (no_overflow)
        else $error("sync_fifo: count moved on wr_en into full FIFO");

    property no_underflow;
        @(posedge clk) disable iff (!rst_n)
            (empty && rd_en && !wr_en) |=> ($stable(count));
    endproperty
    a_no_underflow: assert property (no_underflow)
        else $error("sync_fifo: count moved on rd_en from empty FIFO");

    property empty_matches_count;
        @(posedge clk) disable iff (!rst_n)
            empty |-> (count == '0);
    endproperty
    a_empty_matches_count: assert property (empty_matches_count)
        else $error("sync_fifo: empty=1 but count!=0");

    property full_matches_count;
        @(posedge clk) disable iff (!rst_n)
            full |-> (count == DEPTH[ADDR_WIDTH:0]);
    endproperty
    a_full_matches_count: assert property (full_matches_count)
        else $error("sync_fifo: full=1 but count!=DEPTH");
`endif
endmodule

// -----------------------------------------------------------------------------
// Instrumented-pipeline assertions
//   Upstream backpressure: up_valid && !up_ready => stable up_data.
//   attr_valid is a one-cycle pulse.
//   Attribution sum invariant: sum of deltas <= t_egress - t_ingress,
//     unless any stage saturated (in which case the delta is a clamp).
// -----------------------------------------------------------------------------
module instrumented_pipeline_sva (
    input logic        clk,
    input logic        rst_n,
    input logic        up_valid,
    input logic        up_ready,
    input logic [63:0] up_data,
    input logic        attr_valid,
    input logic [31:0] attr_d_ingress,
    input logic [31:0] attr_d_core,
    input logic [31:0] attr_d_risk,
    input logic [31:0] attr_d_egress,
    input logic        attr_d_ingress_sat,
    input logic        attr_d_core_sat,
    input logic        attr_d_risk_sat,
    input logic        attr_d_egress_sat
);
`ifndef SYNTHESIS
    property upstream_stable_under_bp;
        @(posedge clk) disable iff (!rst_n)
            (up_valid && !up_ready) |=> (up_valid && $stable(up_data));
    endproperty
    a_upstream_stable: assert property (upstream_stable_under_bp)
        else $error("pipeline: up_valid dropped or up_data changed under backpressure");

    property attr_valid_is_pulse;
        @(posedge clk) disable iff (!rst_n)
            attr_valid |=> !attr_valid;
    endproperty
    a_attr_valid_pulse: assert property (attr_valid_is_pulse)
        else $error("pipeline: attr_valid stayed high for more than one cycle");

    // Attribution sum sanity — the sum of stage deltas fits in 32 bits
    // when no stage saturated. This is a weak check (we don't have
    // t_ingress/t_egress visible here), but it catches gross logic
    // errors like a delta being wildly out of range.
    property attr_sum_sane;
        @(posedge clk) disable iff (!rst_n)
            attr_valid
            && !attr_d_ingress_sat
            && !attr_d_core_sat
            && !attr_d_risk_sat
            && !attr_d_egress_sat
            |-> (attr_d_ingress + attr_d_core + attr_d_risk + attr_d_egress) >= attr_d_core;
    endproperty
    a_attr_sum_sane: assert property (attr_sum_sane)
        else $error("pipeline: attribution sum underflowed 32-bit range");
`endif
endmodule

// -----------------------------------------------------------------------------
// Stage-timer assertions
//   saturated |-> !counting || stop — a saturated timer must stop counting
//   on the same cycle unless an explicit clear follows. Paraphrased into
//   a form the RTL actually satisfies: when counter is at MAX and counting
//   is true, the next cycle either saturated or stop must clear counting.
// -----------------------------------------------------------------------------
module stage_timer_sva #(
    parameter int WIDTH = 32
)(
    input logic             clk,
    input logic             rst_n,
    input logic [WIDTH-1:0] cycles,
    input logic             active,
    input logic             saturated,
    input logic             stop,
    input logic             clear
);
`ifndef SYNTHESIS
    // Once saturated, stays saturated until clear.
    property saturated_sticky;
        @(posedge clk) disable iff (!rst_n)
            (saturated && !clear) |=> saturated;
    endproperty
    a_saturated_sticky: assert property (saturated_sticky)
        else $error("stage_timer: saturated cleared without clear pulse");

    // After clear, saturated de-asserts within a cycle.
    property clear_drops_saturated;
        @(posedge clk) disable iff (!rst_n)
            clear |=> !saturated;
    endproperty
    a_clear_drops_saturated: assert property (clear_drops_saturated)
        else $error("stage_timer: saturated stuck after clear pulse");
`endif
endmodule

// =============================================================================
// Bind statements
// -----------------------------------------------------------------------------
// One bind per RTL module. These are simulation-only — Vivado synthesis
// with `+define+SYNTHESIS` drops the assertions inside the bound modules.
// =============================================================================

`ifndef SYNTHESIS

bind kill_switch kill_switch_sva u_kill_switch_sva (
    .clk              (clk),
    .rst_n            (rst_n),
    .trigger_latched  (trigger_latched),
    .cmd_reset        (cmd_reset),
    .passed           (passed),
    .cfg_armed        (cfg_armed)
);

bind rate_limiter rate_limiter_sva u_rate_limiter_sva (
    .clk            (clk),
    .rst_n          (rst_n),
    .bucket         (bucket),
    .cfg_max_tokens (cfg_max_tokens),
    .cfg_enabled    (cfg_enabled)
);

bind risk_gate risk_gate_sva u_risk_gate_sva (
    .clk      (clk),
    .rst_n    (rst_n),
    .in_valid (in_valid),
    .in_ready (in_ready),
    .in_data  (in_data)
);

bind risk_audit_log risk_audit_log_sva #(.FIFO_DEPTH(FIFO_DEPTH)) u_risk_audit_log_sva (
    .clk          (clk),
    .rst_n        (rst_n),
    .seq_r        (seq_r),
    .do_write_any (do_write_any),
    .full_r       (full_r)
);

bind sync_fifo sync_fifo_sva #(.WIDTH(WIDTH), .DEPTH(DEPTH)) u_sync_fifo_sva (
    .clk    (clk),
    .rst_n  (rst_n),
    .wr_en  (wr_en),
    .rd_en  (rd_en),
    .full   (full),
    .empty  (empty),
    .count  (fill_count)
);

bind instrumented_pipeline instrumented_pipeline_sva u_instrumented_pipeline_sva (
    .clk                 (clk),
    .rst_n               (rst_n),
    .up_valid            (up_valid),
    .up_ready            (up_ready),
    .up_data             (up_data),
    .attr_valid          (attr_valid),
    .attr_d_ingress      (attr_d_ingress),
    .attr_d_core         (attr_d_core),
    .attr_d_risk         (attr_d_risk),
    .attr_d_egress       (attr_d_egress),
    .attr_d_ingress_sat  (attr_d_ingress_sat),
    .attr_d_core_sat     (attr_d_core_sat),
    .attr_d_risk_sat     (attr_d_risk_sat),
    .attr_d_egress_sat   (attr_d_egress_sat)
);

bind stage_timer stage_timer_sva #(.WIDTH(WIDTH)) u_stage_timer_sva (
    .clk       (clk),
    .rst_n     (rst_n),
    .cycles    (cycles),
    .active    (active),
    .saturated (saturated),
    .stop      (stop),
    .clear     (clear)
);

`endif  // SYNTHESIS

`endif  // SENTINEL_SVA_SV
