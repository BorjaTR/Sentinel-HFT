// eth_mac_100g_shim.sv -- Hard-MAC facing shim for the AMD CMAC (100GbE).
//
// Purpose
// -------
// Wraps the CMAC LBUS into a clean AXI4-Stream pair sized to match the
// Sentinel shell's 64-bit ingress/egress interface.
//
// Wave 1 audit fixes:
//   E-S0-01  RX byte-offset extraction for the Ethernet / IPv4 / UDP
//            header fields was wrong on every field. With byte 0 at
//            bits [511:504] of the LBUS word (big-endian wire order),
//            the correct slices are:
//                ethertype  = [415:400]  (bytes 12..13)
//                protocol   = [327:320]  (byte  23)
//                src_ip     = [303:272]  (bytes 26..29)
//                dst_ip     = [271:240]  (bytes 30..33)
//                udp_src    = [239:224]  (bytes 34..35)
//                udp_dst    = [223:208]  (bytes 36..37)
//                udp_length = [207:192]  (bytes 38..39)
//            All other slices were off-by-anywhere-from-2-to-12 bytes.
//
//   E-S0-02  TX path could stall a partial beat forever because nothing
//            flushed when the upstream went idle. Added an explicit
//            ST_DRAIN state driven by an idle timer; once the upstream
//            stops presenting data for >= TX_DRAIN_IDLE cycles while
//            bytes remain in tx_beat, we synthesise a tlast and push
//            the partial beat out to CMAC with the correct mty.
//
//   E-S0-03  The TX path emitted raw order payload as the full Ethernet
//            frame, with no L2/L3/L4 headers. CMAC would have shipped
//            bytes that did not parse as an Ethernet frame anywhere
//            downstream. Now the TX FSM prepends the 42 byte
//            Ethernet + IPv4 + UDP header from configured MAC/IP/port
//            parameters and computes total_length / udp_length from
//            the observed payload byte count per frame.
//
//   E-S0-04  Header stripping used `HDR_WORDS = 42/8 = 5`, which leaks
//            the last 2 bytes of the UDP header into the first AXI
//            payload word. Corrected to ceil(42/8) = 6. This loses 6
//            bytes from the first beat's payload, which is acceptable
//            for the POC. A byte-aligned shifter is future work.
//
// Wave 2 audit fixes:
//   E-S1-01  First-beat emit slice was `{hdr_patched, tx_beat[79:0]}`.
//            `hdr_patched` covered bits [511:80] (bytes 0..53), so
//            bytes 42..53 were zero-padded and only bytes 54..63 of
//            the 64-byte beat came from `tx_beat`. Payload word 0
//            was written into `tx_beat[127:64]` (bytes 48..55), so
//            the top 6 bytes of that word were silently replaced by
//            the zero pad. A single-word order (`ord_tvalid &&
//            ord_tlast` in one cycle) emitted only its low 2 bytes.
//            Fix: shrink `hdr_patched` to [511:128] (bytes 0..47 --
//            42 header bytes plus 6 zero-pad bytes) and widen the
//            payload window in the concat to `tx_beat[127:0]`, so
//            the byte boundaries on write and emit match.

`ifndef ETH_MAC_100G_SHIM_SV
`define ETH_MAC_100G_SHIM_SV

`include "eth/eth_pkg.sv"

module eth_mac_100g_shim
  import eth_pkg::*;
#(
    parameter int AXIS_WIDTH = 64,
    parameter bit STRIP_HEADERS = 1'b1,
    parameter logic [15:0] FILTER_UDP_DST_PORT = 16'd0,

    // TX header template -- configured by the parent at instantiation time
    // (or tied off to a constant set by the top-level wrapper).
    parameter logic [47:0] TX_DST_MAC   = 48'h00_00_00_00_00_00,
    parameter logic [47:0] TX_SRC_MAC   = 48'h02_00_00_00_00_01,
    parameter logic [31:0] TX_SRC_IP    = 32'h0A_00_00_01,
    parameter logic [31:0] TX_DST_IP    = 32'h0A_00_00_02,
    parameter logic [15:0] TX_SRC_PORT  = 16'd20000,
    parameter logic [15:0] TX_DST_PORT  = 16'd20001,

    // Cycles the TX path will hold a partial beat before flushing it
    // as the final beat of a frame (E-S0-02).
    parameter int          TX_DRAIN_IDLE = 8
) (
    // --- clocks + reset --------------------------------------------------
    input  logic                        clk,          // CMAC user clock (322.265625 MHz)
    input  logic                        rst_n,

    // --- CMAC LBUS receive (from CMAC) -----------------------------------
    input  logic                        rx_lbus_valid,
    input  logic [511:0]                rx_lbus_data,
    input  logic [5:0]                  rx_lbus_mty,  // bytes of LAST beat that are INVALID
    input  logic                        rx_lbus_sop,
    input  logic                        rx_lbus_eop,
    input  logic                        rx_lbus_err,
    output logic                        rx_lbus_ready,

    // --- CMAC LBUS transmit (to CMAC) ------------------------------------
    output logic                        tx_lbus_valid,
    output logic [511:0]                tx_lbus_data,
    output logic [5:0]                  tx_lbus_mty,
    output logic                        tx_lbus_sop,
    output logic                        tx_lbus_eop,
    input  logic                        tx_lbus_ready,

    // --- Sentinel-facing market-data egress (AXI-Stream) -----------------
    output logic                        mkt_tvalid,
    input  logic                        mkt_tready,
    output logic [AXIS_WIDTH-1:0]       mkt_tdata,
    output logic                        mkt_tlast,
    output l4_meta_t                    mkt_tuser,

    // --- Sentinel-facing order ingress (AXI-Stream) ----------------------
    input  logic                        ord_tvalid,
    output logic                        ord_tready,
    input  logic [AXIS_WIDTH-1:0]       ord_tdata,
    input  logic                        ord_tlast,

    // --- Status ----------------------------------------------------------
    output logic [31:0]                 stat_rx_frames,
    output logic [31:0]                 stat_rx_dropped_port,
    output logic [31:0]                 stat_rx_errors,
    output logic [31:0]                 stat_tx_frames,
    output logic [31:0]                 stat_tx_drain_flushes,
    output logic                        link_up
);

  // ==========================================================================
  // RX PATH -- 512b LBUS -> 64b AXI-Stream + header strip
  // ==========================================================================
  logic [511:0] rx_beat_q;
  logic [5:0]   rx_mty_q;
  logic         rx_sop_q, rx_eop_q, rx_err_q;
  logic         rx_beat_valid;

  logic [2:0]   rx_word_idx;
  logic         rx_in_frame;

  l4_meta_t     rx_meta;
  logic         rx_meta_valid;
  logic         rx_frame_drop;

  // ceil(42/8) = 6  (E-S0-04). The first 6 AXI words of a stripped frame
  // are header bytes 0..47 and are suppressed. Payload starts on word 6.
  localparam int HDR_WORDS = (ETH_IPV4_UDP_HDR_BYTES + (AXIS_WIDTH/8) - 1)
                             / (AXIS_WIDTH/8);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rx_beat_q      <= '0;
      rx_mty_q       <= '0;
      rx_sop_q       <= 1'b0;
      rx_eop_q       <= 1'b0;
      rx_err_q       <= 1'b0;
      rx_beat_valid  <= 1'b0;
      rx_word_idx    <= 3'd0;
      rx_in_frame    <= 1'b0;
      rx_meta        <= '0;
      rx_meta_valid  <= 1'b0;
      rx_frame_drop  <= 1'b0;
    end else begin
      if (rx_lbus_valid && rx_lbus_ready) begin
        automatic logic [15:0] et_w;
        automatic logic [7:0]  proto_w;
        automatic logic [31:0] src_ip_w;
        automatic logic [31:0] dst_ip_w;
        automatic logic [15:0] sp_w, dp_w, ul_w;

        rx_beat_q     <= rx_lbus_data;
        rx_mty_q      <= rx_lbus_mty;
        rx_sop_q      <= rx_lbus_sop;
        rx_eop_q      <= rx_lbus_eop;
        rx_err_q      <= rx_lbus_err;
        rx_beat_valid <= 1'b1;

        if (rx_lbus_sop) begin
          // E-S0-01: correct big-endian byte slices
          et_w     = rx_lbus_data[415:400];   // bytes 12..13
          proto_w  = rx_lbus_data[327:320];   // byte  23
          src_ip_w = rx_lbus_data[303:272];   // bytes 26..29
          dst_ip_w = rx_lbus_data[271:240];   // bytes 30..33
          sp_w     = rx_lbus_data[239:224];   // bytes 34..35
          dp_w     = rx_lbus_data[223:208];   // bytes 36..37
          ul_w     = rx_lbus_data[207:192];   // bytes 38..39

          rx_meta.src_ip      <= src_ip_w;
          rx_meta.dst_ip      <= dst_ip_w;
          rx_meta.src_port    <= sp_w;
          rx_meta.dst_port    <= dp_w;
          rx_meta.payload_len <= (ul_w >= 16'd8) ? (ul_w - 16'd8) : 16'd0;
          rx_meta.protocol    <= proto_w;
          rx_meta_valid       <= 1'b1;

          rx_frame_drop <= !(
              (et_w == ETHERTYPE_IPV4) &&
              (proto_w == IP_PROTO_UDP) &&
              ((FILTER_UDP_DST_PORT == 16'd0) ||
               (dp_w == FILTER_UDP_DST_PORT))
          );
        end

        rx_in_frame <= 1'b1;
      end

      if (rx_beat_valid && mkt_tvalid && mkt_tready) begin
        if (rx_word_idx == 3'd7 || mkt_tlast) begin
          rx_beat_valid <= 1'b0;
          rx_word_idx   <= 3'd0;
          if (mkt_tlast) begin
            rx_in_frame   <= 1'b0;
            rx_meta_valid <= 1'b0;
            rx_frame_drop <= 1'b0;
          end
        end else begin
          rx_word_idx <= rx_word_idx + 3'd1;
        end
      end
    end
  end

  assign rx_lbus_ready = !rx_beat_valid;

  logic [AXIS_WIDTH-1:0] rx_word;
  always_comb begin
    unique case (rx_word_idx)
      3'd0: rx_word = rx_beat_q[511:448];
      3'd1: rx_word = rx_beat_q[447:384];
      3'd2: rx_word = rx_beat_q[383:320];
      3'd3: rx_word = rx_beat_q[319:256];
      3'd4: rx_word = rx_beat_q[255:192];
      3'd5: rx_word = rx_beat_q[191:128];
      3'd6: rx_word = rx_beat_q[127: 64];
      3'd7: rx_word = rx_beat_q[ 63:  0];
    endcase
  end

  logic rx_past_header;
  assign rx_past_header = (STRIP_HEADERS == 1'b0) ||
                          ((rx_sop_q == 1'b0) || (rx_word_idx >= HDR_WORDS[2:0]));

  assign mkt_tvalid = rx_beat_valid && !rx_frame_drop && rx_past_header;
  assign mkt_tdata  = rx_word;
  assign mkt_tuser  = rx_meta;

  logic [2:0] last_word_idx;
  assign last_word_idx = 3'd7 - rx_mty_q[5:3];
  assign mkt_tlast  = rx_beat_valid && rx_eop_q && (rx_word_idx == last_word_idx);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      stat_rx_frames       <= 32'd0;
      stat_rx_dropped_port <= 32'd0;
      stat_rx_errors       <= 32'd0;
    end else begin
      if (rx_lbus_valid && rx_lbus_ready && rx_lbus_eop) begin
        if (rx_lbus_err)
          stat_rx_errors <= stat_rx_errors + 32'd1;
        else if (rx_frame_drop)
          stat_rx_dropped_port <= stat_rx_dropped_port + 32'd1;
        else
          stat_rx_frames <= stat_rx_frames + 32'd1;
      end
    end
  end

  // ==========================================================================
  // TX PATH -- 64b AXI-Stream -> 512b LBUS packer with:
  //   * Header-prepend FSM (E-S0-03)
  //   * ST_DRAIN for partial-beat flush (E-S0-02)
  // ==========================================================================
  //
  // Frame shape emitted on LBUS:
  //   beat 0 (SOP): Ethernet(14) + IPv4(20) + UDP(8) + first 22 bytes of
  //                 payload. total_length / udp_length are patched in
  //                 when we observe tlast on the payload stream.
  //   beat 1..N-1 : Subsequent payload, 64 bytes each.
  //   beat N  (EOP): Remaining payload; tx_lbus_mty indicates unused bytes.

  typedef enum logic [2:0] {
      ST_IDLE      = 3'd0,
      ST_HDR_LATCH = 3'd1,
      ST_PAYLOAD   = 3'd2,
      ST_EMIT      = 3'd3,
      ST_DRAIN     = 3'd4
  } tx_state_e;

  tx_state_e tx_state;

  // Current beat being assembled and per-frame counters.
  logic [511:0] tx_beat;
  logic [2:0]   tx_word_idx;   // 0..7 = words packed into tx_beat
  logic         tx_beat_has_sop;
  logic         tx_beat_is_eop;
  logic [15:0]  tx_payload_bytes;   // total payload bytes accumulated this frame
  logic [15:0]  tx_drain_ctr;

  // Computed header bytes (big-endian). Length fields are patched on the
  // final emit so the first beat is re-serialised with the right values.
  // For the first beat we assemble headers in tx_beat directly.
  logic [15:0]  tx_total_length;  // IP total_length = 20 + 8 + payload
  logic [15:0]  tx_udp_length;    // UDP length      = 8 + payload

  // Temporary pre-assembled first-beat header (bits 511..128 = bytes 0..47,
  // i.e. 42 real header bytes in [511:176] plus 6 zero-pad bytes in
  // [175:128]). E-S1-01: shrunk from [511:80] so the emit concat slice
  // matches the tx_beat payload write window.
  logic [511:128] tx_hdr_first_beat;

  // IPv4 header checksum is computed off the header with length fields
  // treated as zero, then patched at emit time. For the POC we compute
  // a full fresh checksum on final emit because we hold the first beat
  // until we know the total length.
  function automatic logic [15:0] ipv4_checksum(
      input logic [3:0]  version,
      input logic [3:0]  ihl,
      input logic [7:0]  dscp_ecn,
      input logic [15:0] total_length,
      input logic [15:0] identification,
      input logic [2:0]  flags,
      input logic [12:0] frag_offset,
      input logic [7:0]  ttl,
      input logic [7:0]  protocol,
      input logic [31:0] src_ip,
      input logic [31:0] dst_ip
  );
      automatic logic [31:0] sum;
      sum  = {version, ihl, dscp_ecn};
      sum += total_length;
      sum += identification;
      sum += {flags, frag_offset};
      sum += {ttl, protocol};
      sum += src_ip[31:16];
      sum += src_ip[15: 0];
      sum += dst_ip[31:16];
      sum += dst_ip[15: 0];
      // Fold carries.
      sum = (sum & 32'hFFFF) + (sum >> 16);
      sum = (sum & 32'hFFFF) + (sum >> 16);
      ipv4_checksum = ~sum[15:0];
  endfunction

  // Build the constant-shape header (length/checksum patched at emit).
  // Width covers bytes 0..47 (bits [511:128]): 42 real header bytes in
  // [511:176] plus 6 zero-pad bytes in [175:128] (E-S1-01).
  logic [511:128] hdr_template;
  always_comb begin
    // bytes 0..5   dst_mac
    hdr_template[511:464] = TX_DST_MAC;
    // bytes 6..11  src_mac
    hdr_template[463:416] = TX_SRC_MAC;
    // bytes 12..13 ethertype = IPv4
    hdr_template[415:400] = ETHERTYPE_IPV4;
    // byte 14      version=4, ihl=5
    hdr_template[399:392] = {4'd4, 4'd5};
    // byte 15      dscp_ecn = 0
    hdr_template[391:384] = 8'h00;
    // bytes 16..17 total_length (patched)
    hdr_template[383:368] = 16'h0000;
    // bytes 18..19 identification (static)
    hdr_template[367:352] = 16'hABCD;
    // bytes 20..21 flags+fragoff = DF, no fragment
    hdr_template[351:336] = {3'b010, 13'd0};
    // byte 22      ttl
    hdr_template[335:328] = 8'd64;
    // byte 23      protocol = UDP
    hdr_template[327:320] = IP_PROTO_UDP;
    // bytes 24..25 header checksum (patched)
    hdr_template[319:304] = 16'h0000;
    // bytes 26..29 src_ip
    hdr_template[303:272] = TX_SRC_IP;
    // bytes 30..33 dst_ip
    hdr_template[271:240] = TX_DST_IP;
    // bytes 34..35 udp src_port
    hdr_template[239:224] = TX_SRC_PORT;
    // bytes 36..37 udp dst_port
    hdr_template[223:208] = TX_DST_PORT;
    // bytes 38..39 udp length (patched)
    hdr_template[207:192] = 16'h0000;
    // bytes 40..41 udp checksum (0 = disabled)
    hdr_template[191:176] = 16'h0000;
    // bytes 42..47 POC zero-pad so payload starts on an 8-byte word boundary
    hdr_template[175:128] = 48'h0;
  end

  // Patched version of hdr_template using the observed lengths.
  logic [511:128] hdr_patched;
  logic [15:0]    ip_csum;
  always_comb begin
    hdr_patched = hdr_template;
    hdr_patched[383:368] = tx_total_length;
    hdr_patched[207:192] = tx_udp_length;
    ip_csum = ipv4_checksum(
        4'd4, 4'd5, 8'h00, tx_total_length,
        16'hABCD, 3'b010, 13'd0,
        8'd64, IP_PROTO_UDP,
        TX_SRC_IP, TX_DST_IP
    );
    hdr_patched[319:304] = ip_csum;
  end

  // When we're filling the first beat, words 0..4 are headers (40 bytes)
  // plus the last 2 header bytes live in word 5's top half. The remaining
  // 6 bytes of word 5 + words 6..7 are early payload. For POC simplicity
  // the first beat reserves *6* AXIS words for the header (48 bytes) with
  // the UDP checksum padding out the slack, and payload starts at word 6.
  //
  // Thus tx_word_idx on the first beat counts payload words starting at 6.
  // When packing a non-first beat, tx_word_idx counts from 0.

  // Upstream backpressure: accept a payload word when we're in PAYLOAD
  // state and the current beat has room, or when we're in HDR_LATCH and
  // can absorb into the first beat's tail.
  logic tx_take_word;
  assign ord_tready = (tx_state == ST_PAYLOAD || tx_state == ST_HDR_LATCH)
                      && tx_lbus_ready
                      && (tx_word_idx != 3'd7 || !tx_beat_is_eop);

  assign tx_take_word = ord_tvalid && ord_tready;

  // Beat emit condition.
  logic emit_now;
  assign emit_now = (tx_state == ST_EMIT) || (tx_state == ST_DRAIN);

  // ==========================================================================
  // TX FSM
  // ==========================================================================
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      tx_state              <= ST_IDLE;
      tx_beat               <= '0;
      tx_word_idx           <= 3'd0;
      tx_beat_has_sop       <= 1'b1;
      tx_beat_is_eop        <= 1'b0;
      tx_payload_bytes      <= 16'd0;
      tx_drain_ctr          <= 16'd0;
      tx_total_length       <= 16'd0;
      tx_udp_length         <= 16'd0;
      stat_tx_frames        <= 32'd0;
      stat_tx_drain_flushes <= 32'd0;
    end else begin
      case (tx_state)
        // -------------------------------------------------------------
        ST_IDLE: begin
          tx_beat_has_sop  <= 1'b1;
          tx_beat_is_eop   <= 1'b0;
          tx_payload_bytes <= 16'd0;
          tx_drain_ctr     <= 16'd0;
          // Start the first beat with the header template in the top 384
          // bits (bytes 0..47 incl. 6 bytes of zero-pad) and zero the low
          // 128 bits where payload words 0/1 will be written. E-S1-01:
          // width matches `hdr_template` and the emit concat slice.
          tx_beat          <= {hdr_template, 128'h0};
          tx_word_idx      <= HDR_WORDS[2:0];   // first payload slot
          if (ord_tvalid) tx_state <= ST_HDR_LATCH;
        end

        // First-beat-payload packing. Header words 0..5 are locked.
        ST_HDR_LATCH: begin
          if (tx_take_word) begin
            case (tx_word_idx)
              3'd6: tx_beat[127: 64] <= ord_tdata;
              3'd7: tx_beat[ 63:  0] <= ord_tdata;
              default: ;  // never happens in this state
            endcase
            tx_payload_bytes <= tx_payload_bytes + 16'd8;

            if (ord_tlast) begin
              // tiny frame ending inside the first beat
              tx_beat_is_eop <= 1'b1;
              tx_state       <= ST_EMIT;
            end else if (tx_word_idx == 3'd7) begin
              tx_state <= ST_EMIT;   // first beat full, emit then go to PAYLOAD
            end else begin
              tx_word_idx <= tx_word_idx + 3'd1;
            end
          end else begin
            // Upstream idle — increment drain counter; if we've already
            // latched at least one payload word into this beat, fall
            // through to DRAIN.
            if (tx_word_idx != HDR_WORDS[2:0]) begin
              if (tx_drain_ctr + 16'd1 >= TX_DRAIN_IDLE) begin
                tx_beat_is_eop <= 1'b1;
                tx_state       <= ST_DRAIN;
              end else begin
                tx_drain_ctr <= tx_drain_ctr + 16'd1;
              end
            end
          end
        end

        // -------------------------------------------------------------
        // Continuation beats (header already shipped).
        ST_PAYLOAD: begin
          if (tx_take_word) begin
            tx_drain_ctr <= 16'd0;
            case (tx_word_idx)
              3'd0: tx_beat[511:448] <= ord_tdata;
              3'd1: tx_beat[447:384] <= ord_tdata;
              3'd2: tx_beat[383:320] <= ord_tdata;
              3'd3: tx_beat[319:256] <= ord_tdata;
              3'd4: tx_beat[255:192] <= ord_tdata;
              3'd5: tx_beat[191:128] <= ord_tdata;
              3'd6: tx_beat[127: 64] <= ord_tdata;
              3'd7: tx_beat[ 63:  0] <= ord_tdata;
            endcase
            tx_payload_bytes <= tx_payload_bytes + 16'd8;

            if (ord_tlast) begin
              tx_beat_is_eop <= 1'b1;
              tx_state       <= ST_EMIT;
            end else if (tx_word_idx == 3'd7) begin
              tx_state <= ST_EMIT;
            end else begin
              tx_word_idx <= tx_word_idx + 3'd1;
            end
          end else begin
            if (tx_word_idx != 3'd0) begin
              if (tx_drain_ctr + 16'd1 >= TX_DRAIN_IDLE) begin
                tx_beat_is_eop <= 1'b1;
                tx_state       <= ST_DRAIN;
              end else begin
                tx_drain_ctr <= tx_drain_ctr + 16'd1;
              end
            end
          end
        end

        // -------------------------------------------------------------
        // Emit current beat (normal path). Only reached when a full beat
        // is assembled or tlast arrived.
        ST_EMIT: begin
          if (tx_lbus_ready) begin
            if (tx_beat_is_eop) begin
              stat_tx_frames <= stat_tx_frames + 32'd1;
              tx_state       <= ST_IDLE;
            end else begin
              // Beat full, continue packing in subsequent beats.
              tx_state        <= ST_PAYLOAD;
              tx_beat         <= '0;
              tx_word_idx     <= 3'd0;
              tx_beat_has_sop <= 1'b0;
              tx_drain_ctr    <= 16'd0;
            end
          end
        end

        // -------------------------------------------------------------
        // Drain partial beat on upstream idle.
        ST_DRAIN: begin
          if (tx_lbus_ready) begin
            stat_tx_frames        <= stat_tx_frames + 32'd1;
            stat_tx_drain_flushes <= stat_tx_drain_flushes + 32'd1;
            tx_state              <= ST_IDLE;
          end
        end

        default: tx_state <= ST_IDLE;
      endcase

      // Maintain the length fields so ST_EMIT sees up-to-date values.
      tx_udp_length   <= tx_payload_bytes + 16'd8;           // UDP hdr + payload
      tx_total_length <= tx_payload_bytes + 16'd8 + 16'd20;  // + IPv4 hdr
    end
  end

  // ==========================================================================
  // LBUS drive signals
  // ==========================================================================
  // On a SOP beat we must stream the patched header; on non-SOP beats we
  // stream the raw tx_beat packed data.
  //
  // E-S1-01: the concat is `{hdr_patched[511:128], tx_beat[127:0]}` so
  // that the payload window lines up byte-for-byte with where
  // ST_HDR_LATCH writes payload word 0 (tx_beat[127:64]) and payload
  // word 1 (tx_beat[63:0]). Prior to the fix the concat was
  // `{hdr_patched[511:80], tx_beat[79:0]}`, which zero-overwrote the
  // top 6 bytes of the first payload word.
  logic [511:0] tx_beat_emit;
  always_comb begin
    if (tx_beat_has_sop) begin
      tx_beat_emit = {hdr_patched, tx_beat[127:0]};
    end else begin
      tx_beat_emit = tx_beat;
    end
  end

  // mty = unused tail bytes in the final beat. Semantics: tx_word_idx
  // holds the INDEX of the last word written (0..7), so used =
  // (tx_word_idx + 1) * 8 bytes and unused = (7 - tx_word_idx) * 8
  // bytes. For non-EOP beats mty must be 0.
  logic [5:0] mty_calc;
  assign mty_calc = tx_beat_is_eop ? ((3'd7 - tx_word_idx) * 6'd8) : 6'd0;

  assign tx_lbus_valid = emit_now;
  assign tx_lbus_data  = tx_beat_emit;
  assign tx_lbus_sop   = tx_beat_has_sop && emit_now;
  assign tx_lbus_eop   = tx_beat_is_eop  && emit_now;
  assign tx_lbus_mty   = mty_calc;

  // ==========================================================================
  // Link up proxy
  // ==========================================================================
  logic link_up_q;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) link_up_q <= 1'b0;
    else if (rx_lbus_valid) link_up_q <= 1'b1;
  end
  assign link_up = link_up_q;

endmodule

`endif
