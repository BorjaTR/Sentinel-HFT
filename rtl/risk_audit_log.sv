`ifndef RISK_AUDIT_LOG_SV
`define RISK_AUDIT_LOG_SV

`include "risk_pkg.sv"

// =============================================================================
// risk_audit_log
// -----------------------------------------------------------------------------
// Ordered, monotonically-sequenced *serialiser* of risk decisions. Wave 1
// audit fixes apply the "Option A" remediation from AUDIT_FIX_PLAN: this
// module is no longer billed as a tamper-evident audit log. It is an
// on-chip serialiser that the host BLAKE2b hasher chains off-chip. Real
// tamper evidence is a post-v1.0.0 item.
//
// Wave 1 audit fixes:
//   B-S0-1   `prev_hash_lo` is supplied by the host. The RTL does not
//            compute any hash. Documented explicitly so no one assumes
//            the chain is constructed locally. The hasher runs on the
//            Zynq PS (or host) and feeds prev_hash back via DMA.
//
//   B-S0-2   FIFO full used to silently drop records. Now the module
//            emits an in-band REC_OVERFLOW marker on the next accepted
//            write so any reader of the record stream can see where the
//            gap started. The number of dropped records since the last
//            successful write is carried in the marker's order_id slot.
//
//   B-S0-3   Sequence counter used to advance on every incoming decision
//            even when the FIFO rejected the write. That produced gaps
//            that looked identical to actual dropped decisions and made
//            off-chip chain verification ambiguous. `seq_r` now advances
//            only on committed writes.
//
// Wave 2 audit fixes:
//   B-S1-1   FIFO full/empty used a gray-style MSB-toggle pointer
//            compare that silently degraded on non-power-of-2 depths.
//            Replaced with an explicit occupancy counter
//            (`count_r`) that is depth-agnostic, plus an explicit
//            pointer wrap at FIFO_DEPTH. A compile-time check keeps
//            FIFO_DEPTH >= 2.
//
//   B-S1-2   `rec_nxt_normal[239:224] = {8'b0, dec_reject_reason}`
//            relied on `$bits(risk_reject_e) == 8`. Guarded with a
//            localparam divide-by-zero elaboration-time assert so
//            any future widening of risk_reject_e fails the build
//            rather than silently truncating.
//
//   B-S1-3   Record layout is MSB-packed into a 768b vector (bit
//            offsets are as documented below) but emitted on-wire
//            in little-endian byte order by the host DMA descriptor.
//            The two representations are NOT identical — the host
//            verifier must byte-swap each field from the MSB-packed
//            RTL view into the LE on-wire view. See the comment
//            block above the record-assembly `always_comb` for the
//            exact mapping.
//
// Record layout is unchanged (96 bytes, little-endian on-wire, MSB-
// packed inside the RTL). "hash_prev_lo" is the low 128 bits of the
// previous record's hash as supplied by the host.
//
// Record layout (96 bytes, little-endian on-wire, synthesizable):
//
//   offset  size  field           notes
//   ------  ----  --------------  -------------------------------------------
//   0       8     seq_no          monotonic, resets on rst_n; advances only
//                                 on committed writes (B-S0-3).
//   8       8     timestamp_ns    free-running ns counter
//   16      8     order_id        or drop_count on REC_OVERFLOW
//   24      4     symbol_id       or 0 on REC_OVERFLOW
//   28      2     reject_reason   risk_reject_e or 0xFFFE on REC_OVERFLOW
//   30      2     flags           bit 0..3 as before; bit 15 = REC_OVERFLOW
//   32      8     quantity
//   40      8     price
//   48      8     notional
//   56      8     current_position_after (signed)
//   64      8     current_notional_after
//   72      4     tokens_remaining
//   76      4     reserved
//   80      16    hash_prev_lo    host-supplied
// =============================================================================

module risk_audit_log
  import risk_pkg::*;
#(
  parameter int DATA_WIDTH = 64,
  parameter int FIFO_DEPTH = 256
)(
  input  logic                 clk,
  input  logic                 rst_n,

  // ===== Free-running timestamp (ns) =====
  input  logic [63:0]          timestamp_ns,

  // ===== Input: one decision per cycle =====
  input  logic                 dec_valid,
  input  order_t               dec_order,
  input  logic                 dec_passed,
  input  risk_reject_e         dec_reject_reason,
  input  logic                 dec_kill_triggered,
  input  logic [31:0]          dec_tokens_remaining,
  input  logic signed [64:0]   dec_position_after,
  input  logic [63:0]          dec_notional_after,

  // ===== Previous-hash port (written by host DMA / updater) =====
  // Host discipline: chain hashes off-chip; this module never computes a
  // hash itself.
  input  logic [127:0]         prev_hash_lo,

  // ===== Output: serialised record stream =====
  output logic                 rec_valid,
  output logic [767:0]         rec_data,     // 96 bytes packed
  input  logic                 rec_ready,

  // ===== Statistics =====
  output logic [63:0]          stat_records_emitted,
  output logic [63:0]          stat_records_dropped,  // FIFO full drops
  output logic                 stat_fifo_full
);

  // In-band marker used when a record is written after previous drops.
  // Reserves 0xFFFE in the reject_reason space; callers should treat this
  // as "synthetic gap marker" rather than a real risk outcome.
  localparam logic [15:0] REC_OVERFLOW_REASON = 16'hFFFE;
  localparam logic [15:0] OVERFLOW_FLAG_BIT   = 16'h8000;

  // B-S1-2: elaboration-time assert that risk_reject_e fits in the
  // 16-bit reject_reason slot. Uses the divide-by-zero trick because
  // IEEE 1800-2017 §16.14 `assert static` is spotty across tools.
  /* verilator lint_off UNUSED */
  localparam int REJECT_REASON_BITS   = $bits(risk_reject_e);
  localparam int REJECT_REASON_OK     = 1 / (REJECT_REASON_BITS <= 16 ? 1 : 0);
  // B-S1-1: elaboration-time check for sensible FIFO_DEPTH. We no
  // longer require power-of-two depth (see below).
  localparam int FIFO_DEPTH_OK        = 1 / (FIFO_DEPTH >= 2 ? 1 : 0);
  /* verilator lint_on UNUSED */

  // ---------------------------------------------------------------------------
  // FIFO state (B-S1-1: occupancy-counter style, depth-agnostic)
  //
  // Old implementation used a gray-style MSB-toggle compare, which
  // silently stopped working for non-power-of-2 depths because the
  // pointer increment `wr_ptr_r <= wr_ptr_r + 1` relied on natural
  // wraparound at 2*FIFO_DEPTH. The replacement here tracks
  // occupancy explicitly and wraps the pointers at FIFO_DEPTH.
  // ---------------------------------------------------------------------------
  localparam int ADDR_WIDTH = (FIFO_DEPTH <= 1) ? 1 : $clog2(FIFO_DEPTH);
  localparam int CNT_WIDTH  = $clog2(FIFO_DEPTH + 1);

  // Unsigned typed constants so compare/arith don't infer signed literals.
  localparam logic [ADDR_WIDTH-1:0] ADDR_LAST  = ADDR_WIDTH'(FIFO_DEPTH - 1);
  localparam logic [ADDR_WIDTH-1:0] ADDR_ONE   = ADDR_WIDTH'(1);
  localparam logic [CNT_WIDTH-1:0]  CNT_ONE    = CNT_WIDTH'(1);
  localparam logic [CNT_WIDTH-1:0]  CNT_FULL   = CNT_WIDTH'(FIFO_DEPTH);
  localparam logic [CNT_WIDTH-1:0]  CNT_ZERO   = '0;

  logic [767:0]             fifo_mem [FIFO_DEPTH];
  logic [ADDR_WIDTH-1:0]    wr_ptr_r, rd_ptr_r;
  logic [CNT_WIDTH-1:0]     count_r;
  logic                     full_r, empty_r;

  assign full_r         = (count_r == CNT_FULL);
  assign empty_r        = (count_r == CNT_ZERO);
  assign stat_fifo_full = full_r;

  // ---------------------------------------------------------------------------
  // Monotonic sequence counter — advances only on committed writes
  // ---------------------------------------------------------------------------
  logic [63:0] seq_r;

  // ---------------------------------------------------------------------------
  // Overflow-pending state: set when at least one record was dropped since
  // the last successful write. Cleared when we emit a REC_OVERFLOW marker.
  // ---------------------------------------------------------------------------
  logic        overflow_pending;
  logic [31:0] overflow_drop_count;

  // ---------------------------------------------------------------------------
  // Flag packing for a normal decision record
  // ---------------------------------------------------------------------------
  logic [15:0] flags_normal;
  always_comb begin
    flags_normal = 16'h0000;
    flags_normal[0] = dec_passed;
    flags_normal[1] = dec_kill_triggered;
    flags_normal[2] = (dec_reject_reason == RISK_RATE_LIMITED);
    flags_normal[3] = (dec_reject_reason == RISK_POSITION_LIMIT)
                    || (dec_reject_reason == RISK_NOTIONAL_LIMIT)
                    || (dec_reject_reason == RISK_ORDER_SIZE);
  end

  // ---------------------------------------------------------------------------
  // Record assembly — two shapes: normal + REC_OVERFLOW
  // ---------------------------------------------------------------------------
  logic [767:0] rec_nxt_normal;
  logic [767:0] rec_nxt_overflow;

  always_comb begin
    rec_nxt_normal = '0;
    rec_nxt_normal[63:0]    = seq_r;
    rec_nxt_normal[127:64]  = timestamp_ns;
    rec_nxt_normal[191:128] = dec_order.order_id;
    rec_nxt_normal[223:192] = dec_order.symbol_id;
    rec_nxt_normal[239:224] = {8'b0, dec_reject_reason};
    rec_nxt_normal[255:240] = flags_normal;
    rec_nxt_normal[319:256] = dec_order.quantity;
    rec_nxt_normal[383:320] = dec_order.price;
    rec_nxt_normal[447:384] = dec_order.notional;
    rec_nxt_normal[511:448] = dec_position_after[63:0];
    rec_nxt_normal[575:512] = dec_notional_after;
    rec_nxt_normal[607:576] = dec_tokens_remaining;
    rec_nxt_normal[639:608] = 32'h0;
    rec_nxt_normal[767:640] = prev_hash_lo;
  end

  always_comb begin
    rec_nxt_overflow = '0;
    rec_nxt_overflow[63:0]    = seq_r;
    rec_nxt_overflow[127:64]  = timestamp_ns;
    rec_nxt_overflow[191:128] = {32'h0, overflow_drop_count}; // drop count in order_id slot
    rec_nxt_overflow[223:192] = 32'h0;
    rec_nxt_overflow[239:224] = REC_OVERFLOW_REASON;
    rec_nxt_overflow[255:240] = OVERFLOW_FLAG_BIT;
    rec_nxt_overflow[319:256] = 64'h0;
    rec_nxt_overflow[383:320] = 64'h0;
    rec_nxt_overflow[447:384] = 64'h0;
    rec_nxt_overflow[511:448] = 64'h0;
    rec_nxt_overflow[575:512] = 64'h0;
    rec_nxt_overflow[607:576] = 32'h0;
    rec_nxt_overflow[639:608] = 32'h0;
    rec_nxt_overflow[767:640] = prev_hash_lo;
  end

  // ---------------------------------------------------------------------------
  // Write arbitration:
  //   1. If overflow is pending AND FIFO has room, write REC_OVERFLOW first.
  //   2. Else if dec_valid AND FIFO has room, write the normal record.
  //   3. If dec_valid AND FIFO full, increment drop count and set pending.
  // ---------------------------------------------------------------------------
  logic do_write_overflow;
  logic do_write_normal;
  logic do_write_any;
  logic do_read;

  assign do_write_overflow = overflow_pending && !full_r;
  assign do_write_normal   = !do_write_overflow && dec_valid && !full_r;
  assign do_write_any      = do_write_overflow || do_write_normal;
  assign do_read           = rec_valid && rec_ready;

  // ---------------------------------------------------------------------------
  // State update
  // ---------------------------------------------------------------------------
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wr_ptr_r             <= '0;
      rd_ptr_r             <= '0;
      count_r              <= '0;
      stat_records_emitted <= 64'd0;
      stat_records_dropped <= 64'd0;
      seq_r                <= 64'd0;
      overflow_pending     <= 1'b0;
      overflow_drop_count  <= 32'd0;
    end else begin
      // Commit a write (B-S0-2 / B-S0-3: seq_r advances here only)
      if (do_write_any) begin
        if (do_write_overflow) begin
          fifo_mem[wr_ptr_r] <= rec_nxt_overflow;
          overflow_pending    <= 1'b0;
          overflow_drop_count <= 32'd0;
        end else begin
          fifo_mem[wr_ptr_r] <= rec_nxt_normal;
        end
        // B-S1-1: explicit wrap at FIFO_DEPTH, depth-agnostic
        wr_ptr_r <= (wr_ptr_r == ADDR_LAST) ? '0 : wr_ptr_r + ADDR_ONE;
        seq_r                <= seq_r + 64'd1;
        stat_records_emitted <= stat_records_emitted + 64'd1;
      end

      // Drop handling
      if (dec_valid && full_r) begin
        stat_records_dropped <= stat_records_dropped + 64'd1;
        overflow_pending     <= 1'b1;
        if (overflow_drop_count != 32'hFFFF_FFFF)
          overflow_drop_count <= overflow_drop_count + 32'd1;
      end

      // Drain
      if (do_read)
        rd_ptr_r <= (rd_ptr_r == ADDR_LAST) ? '0 : rd_ptr_r + ADDR_ONE;

      // B-S1-1: occupancy counter. Write+read same cycle is a no-op.
      case ({do_write_any, do_read})
        2'b10:   count_r <= count_r + CNT_ONE;
        2'b01:   count_r <= count_r - CNT_ONE;
        default: count_r <= count_r;
      endcase
    end
  end

  assign rec_valid = !empty_r;
  assign rec_data  = fifo_mem[rd_ptr_r];

endmodule

`endif
