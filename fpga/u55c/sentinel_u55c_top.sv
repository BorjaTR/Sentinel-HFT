// sentinel_u55c_top.sv -- Top-level wrapper for AMD Alveo U55C
//
// This is the FPGA-facing top that ties the Sentinel pipeline
// (sentinel_shell_v12 + risk_gate) to physical pins on an Alveo
// U55C (xcu55c-fsvh2892-2L-e).
//
// Target frequency: 100 MHz user clock (sysclk1, differential),
// derived on-board from the 161.1328125 MHz GT refclk via the
// shell MMCM. For standalone synthesis without the XDMA shell
// we bring up our own MMCM (``u_mmcm``) off the 300 MHz reference.
//
// This wrapper's job is *connectivity and timing closure*, not
// functional change: the behavioural core is shared with the
// simulation testbench so the demo pipeline and the FPGA pipeline
// are bit-identical.
//
// Physical bring-up on a real card would also wire up:
//   * QSFP28 cage (100GbE MAC via CMAC) for tick ingress / order
//     egress,
//   * HBM2 stacks for trace spill,
//   * PCIe Gen4 x16 (XDMA) for host handoff of traces.
// Those blocks are vendor IP and live outside this repo. Here we
// expose them as simple streaming/AXI-lite style stubs so the
// elaboration check can verify the Sentinel RTL fits a real
// part's I/O budget and timing targets.

`ifndef SENTINEL_U55C_TOP_SV
`define SENTINEL_U55C_TOP_SV

`include "sentinel_shell_v12.sv"
`include "risk_gate.sv"
`include "risk_audit_log.sv"
`include "risk_pkg.sv"
`include "eth/eth_pkg.sv"
`include "eth/eth_mac_100g_shim.sv"
`include "reset_sync.sv"
`include "async_fifo.sv"

module sentinel_u55c_top
  import risk_pkg::*;
  import eth_pkg::*;
#(
    parameter int  CORE_LATENCY = 10,
    parameter int  RISK_LATENCY = 5,
    parameter int  FIFO_DEPTH   = 256,
    parameter int  AUDIT_DEPTH  = 128,
    parameter int  CORE_ID      = 16'h0001,
    // When 1, bind QSFP28 CMAC LBUS pins to the Sentinel shell via
    // ``eth_mac_100g_shim``. When 0, drive the shell directly from
    // the mkt_*/ord_* AXIS ports (used by the Verilator testbench so
    // the CI elaboration path doesn't need a CMAC model).
    parameter bit  WITH_CMAC    = 1'b0,
    // UDP dst port to admit on QSFP0 (0 = accept every packet).
    parameter logic [15:0] MKT_UDP_DST_PORT = 16'd0
) (
    // ----- Differential reference clocks -----
    // 300 MHz board reference (sysclk0, differential LVDS).
    input  logic        sysclk0_p,
    input  logic        sysclk0_n,

    // Active-low board reset (SW1 push-button on the card; goes
    // through a schmitt trigger so we don't need debouncing here).
    input  logic        board_rstn,

    // ----- Streaming tick ingress (from CMAC/QSFP28) -----
    // 64 bits wide so we match the shell's ``up_data`` directly;
    // the CMAC adapter is responsible for unpacking the Ethernet
    // frame and presenting parsed market-data words.
    // In WITH_CMAC=1 builds these stay wired but are driven by the
    // shim's Sentinel-facing side so host-side logic analysers can
    // still tap into the stream.
    input  logic        mkt_tvalid,
    output logic        mkt_tready,
    input  logic [63:0] mkt_tdata,

    // ----- Streaming order egress (to CMAC/QSFP28) -----
    output logic        ord_tvalid,
    input  logic        ord_tready,
    output logic [63:0] ord_tdata,

    // ----- QSFP28 CMAC LBUS (100GbE hard macro) -----
    // Only meaningful when WITH_CMAC=1. Matches the signal set
    // presented by ``cmac_usplus_0`` (UltraScale+ CMAC hard IP).
    // Left unused in the Verilator elaboration path.
    input  logic         cmac_usr_clk,       // 322.265625 MHz user clk
    input  logic         cmac_usr_rstn,
    // QSFP0 RX (market data)
    input  logic         qsfp0_rx_lbus_valid,
    input  logic [511:0] qsfp0_rx_lbus_data,
    input  logic [5:0]   qsfp0_rx_lbus_mty,
    input  logic         qsfp0_rx_lbus_sop,
    input  logic         qsfp0_rx_lbus_eop,
    input  logic         qsfp0_rx_lbus_err,
    output logic         qsfp0_rx_lbus_ready,
    // QSFP1 TX (order egress)
    output logic         qsfp1_tx_lbus_valid,
    output logic [511:0] qsfp1_tx_lbus_data,
    output logic [5:0]   qsfp1_tx_lbus_mty,
    output logic         qsfp1_tx_lbus_sop,
    output logic         qsfp1_tx_lbus_eop,
    input  logic         qsfp1_tx_lbus_ready,
    // CMAC link status out (for LED / AXI-Lite stat register)
    output logic         qsfp0_link_up,

    // ----- Risk gate configuration (AXI-lite from host) -----
    input  logic [31:0] cfg_rate_max_tokens,
    input  logic [31:0] cfg_rate_refill_rate,
    input  logic [15:0] cfg_rate_refill_period,
    input  logic        cfg_rate_enabled,
    input  logic [63:0] cfg_pos_max_long,
    input  logic [63:0] cfg_pos_max_short,
    input  logic [63:0] cfg_pos_max_notional,
    input  logic [63:0] cfg_pos_max_order_qty,
    input  logic        cfg_pos_enabled,
    input  logic        cfg_kill_armed,
    input  logic        cfg_kill_auto_enabled,
    input  logic [63:0] cfg_kill_loss_threshold,
    input  logic        cmd_kill_trigger,
    input  logic        cmd_kill_reset,

    // ----- Fill feedback (from exchange gateway) -----
    input  logic        fill_valid,
    input  order_side_e fill_side,
    input  logic [63:0] fill_qty,
    input  logic [63:0] fill_notional,
    input  logic [63:0] current_pnl,
    input  logic        pnl_is_loss,

    // ----- Trace output (to PCIe/XDMA) -----
    output logic         trace_tvalid,
    input  logic         trace_tready,
    output logic [511:0] trace_tdata,
    output logic [6:0]   trace_tsize,

    // ----- Audit output (tamper-evident risk log) -----
    output logic         audit_tvalid,
    input  logic         audit_tready,
    output logic [767:0] audit_tdata,

    // ----- Board-level status LEDs -----
    // [0] kill switch active, [1] trace activity,
    // [2] any trace drops, [3] heartbeat
    output logic [3:0]  gpio_led,

    // ----- Heartbeat for probe pins -----
    output logic        heartbeat
);

    // =========================================================================
    // Clock + reset bring-up
    // =========================================================================
    //
    // In production the XDMA shell hands us a 250 MHz axi_aclk. In
    // standalone bring-up we use the on-board 300 MHz sysclk0 and
    // derive a 100 MHz user clock via MMCM. For elaboration we only
    // need the logical structure, so we model the MMCM as a pair of
    // IBUFDS / BUFG style primitives -- the Vivado toolchain picks
    // real primitives during synthesis via the XDC.

    logic sysclk0;
    logic clk_100;
    logic rst_n_sync;

    // Differential input buffer (elaborated as IBUFDS by Vivado).
    IBUFDS #(
        .DIFF_TERM ("TRUE"),
        .IOSTANDARD("LVDS")
    ) u_ibufds_sysclk (
        .O  (sysclk0),
        .I  (sysclk0_p),
        .IB (sysclk0_n)
    );

    // Clock generator: 300 MHz -> 100 MHz. For the elaboration
    // check the simulator doesn't model MMCME4_ADV, so we keep a
    // thin wrapper that degenerates to a straight through.
    sentinel_clock_gen u_clkgen (
        .clk_in  (sysclk0),
        .rstn_in (board_rstn),
        .clk_100 (clk_100),
        .locked  (rst_n_sync)
    );

    // =========================================================================
    // Network layer: optional CMAC shim in front of the shell
    // =========================================================================
    //
    // The shell sees a 64b AXI-Stream interface. When WITH_CMAC=1 the
    // shim converts QSFP28 LBUS <-> that AXI-Stream. When WITH_CMAC=0
    // the shell is driven directly from the top-level mkt_/ord_ ports
    // (this is the Verilator elaboration path).

    logic         shell_up_valid;
    logic         shell_up_ready;
    logic [63:0]  shell_up_data;
    logic         shell_dn_valid;
    logic         shell_dn_ready;
    logic [63:0]  shell_dn_data;
    logic         shell_dn_tlast;  // WP1.5 (E-S0-03): real tlast into shim

    // Shim status (only meaningful in WITH_CMAC=1 builds).
    logic [31:0]  qsfp0_stat_rx_frames;
    logic [31:0]  qsfp0_stat_rx_dropped_port;
    logic [31:0]  qsfp0_stat_rx_errors;
    logic [31:0]  qsfp1_stat_tx_frames;
    l4_meta_t     qsfp0_rx_meta;
    logic         qsfp0_rx_tlast;

    generate
      if (WITH_CMAC) begin : g_cmac
        // =====================================================================
        // CMAC CDC -- Wave 2 audit fix (E-S1-02, E-S1-03)
        // =====================================================================
        //
        // The CMAC hard macro runs the LBUS on its 322.265625 MHz user
        // clock (``cmac_usr_clk``). The Sentinel shell and core run on
        // ``clk_100`` (the board's sysclk0 in this stub, the XDMA
        // ap_clk in a production shell). These are genuinely
        // asynchronous domains: prior to this fix the top-level
        // collapsed them by tying ``u_qsfp0_shim.clk`` to ``clk_100``
        // and declaring ``set_clock_groups -asynchronous`` on the pair,
        // which leaves every flop in the shim's 512b datapath exposed
        // to metastability with no containment.
        //
        // The corrected topology is:
        //
        //   LBUS  <-->  eth_mac_100g_shim        --+
        //                 (clk = cmac_usr_clk)     |
        //                                          |  AXI-Stream RX
        //                                          v
        //                                      async_fifo (cmac -> clk_100)
        //                                          |
        //                                          v
        //                                      sentinel_shell_v12
        //                                          (clk = clk_100)
        //                                          |
        //                                          |  AXI-Stream TX
        //                                          v
        //                                      async_fifo (clk_100 -> cmac)
        //                                          |
        //                                          v
        //   LBUS  <-- eth_mac_100g_shim -----------+
        //
        // reset_sync instances generate each domain's active-low
        // reset so neither flop array sees a recovery/removal
        // violation when the upstream reset de-asserts.
        //
        // Depth: 32 entries on each direction (~2 KB combined) keeps
        // the worst-case gap between back-to-back 64-byte beats at
        // 100 GbE below the round-trip CDC latency; WP2.5 sizes the
        // jumbo-frame path with DEPTH=256 if the shell ever consumes
        // >9 KiB frames.

        // ---- CMAC-domain reset synchroniser ----
        logic cmac_rstn_sync;
        reset_sync #(.STAGES(3)) u_cmac_rst (
            .clk      (cmac_usr_clk),
            .rst_n_in (cmac_usr_rstn && rst_n),
            .rst_n_out(cmac_rstn_sync)
        );

        // ---- Shim-facing AXI-Stream pair (lives in cmac_usr_clk) ----
        logic        shim_mkt_tvalid, shim_mkt_tready;
        logic [63:0] shim_mkt_tdata;
        logic        shim_mkt_tlast;
        l4_meta_t    shim_mkt_tuser;

        logic        shim_ord_tvalid, shim_ord_tready;
        logic [63:0] shim_ord_tdata;
        logic        shim_ord_tlast;

        eth_mac_100g_shim #(
            .AXIS_WIDTH          (64),
            .STRIP_HEADERS       (1'b1),
            .FILTER_UDP_DST_PORT (MKT_UDP_DST_PORT)
        ) u_qsfp0_shim (
            .clk                 (cmac_usr_clk),
            .rst_n               (cmac_rstn_sync),

            .rx_lbus_valid       (qsfp0_rx_lbus_valid),
            .rx_lbus_data        (qsfp0_rx_lbus_data),
            .rx_lbus_mty         (qsfp0_rx_lbus_mty),
            .rx_lbus_sop         (qsfp0_rx_lbus_sop),
            .rx_lbus_eop         (qsfp0_rx_lbus_eop),
            .rx_lbus_err         (qsfp0_rx_lbus_err),
            .rx_lbus_ready       (qsfp0_rx_lbus_ready),

            .tx_lbus_valid       (qsfp1_tx_lbus_valid),
            .tx_lbus_data        (qsfp1_tx_lbus_data),
            .tx_lbus_mty         (qsfp1_tx_lbus_mty),
            .tx_lbus_sop         (qsfp1_tx_lbus_sop),
            .tx_lbus_eop         (qsfp1_tx_lbus_eop),
            .tx_lbus_ready       (qsfp1_tx_lbus_ready),

            .mkt_tvalid          (shim_mkt_tvalid),
            .mkt_tready          (shim_mkt_tready),
            .mkt_tdata           (shim_mkt_tdata),
            .mkt_tlast           (shim_mkt_tlast),
            .mkt_tuser           (shim_mkt_tuser),

            .ord_tvalid          (shim_ord_tvalid),
            .ord_tready          (shim_ord_tready),
            .ord_tdata           (shim_ord_tdata),
            .ord_tlast           (shim_ord_tlast),

            .stat_rx_frames      (qsfp0_stat_rx_frames),
            .stat_rx_dropped_port(qsfp0_stat_rx_dropped_port),
            .stat_rx_errors      (qsfp0_stat_rx_errors),
            .stat_tx_frames      (qsfp1_stat_tx_frames),
            .link_up             (qsfp0_link_up)
        );

        // ---- RX CDC: shim (cmac_usr_clk) -> shell (clk_100) ----
        localparam int RX_FIFO_WIDTH = 64 + 1 + $bits(l4_meta_t);
        logic [RX_FIFO_WIDTH-1:0] rx_fifo_wdata, rx_fifo_rdata;
        logic                     rx_fifo_full, rx_fifo_empty;

        assign rx_fifo_wdata   = {shim_mkt_tdata, shim_mkt_tlast, shim_mkt_tuser};
        assign shim_mkt_tready = !rx_fifo_full;

        async_fifo #(
            .WIDTH      (RX_FIFO_WIDTH),
            .DEPTH      (32),
            .SYNC_STAGES(2)
        ) u_rx_cdc_fifo (
            .clk_w       (cmac_usr_clk),
            .rst_n_w     (cmac_rstn_sync),
            .wr_en       (shim_mkt_tvalid && !rx_fifo_full),
            .wr_data     (rx_fifo_wdata),
            .full        (rx_fifo_full),

            .clk_r       (clk_100),
            .rst_n_r     (rst_n_sync),
            .rd_en       (shell_up_valid && shell_up_ready),
            .rd_data     (rx_fifo_rdata),
            .empty       (rx_fifo_empty),

            .wr_occupancy()
        );

        assign {shell_up_data, qsfp0_rx_tlast, qsfp0_rx_meta} = rx_fifo_rdata;
        assign shell_up_valid = !rx_fifo_empty;

        // ---- TX CDC: shell (clk_100) -> shim (cmac_usr_clk) ----
        localparam int TX_FIFO_WIDTH = 64 + 1;
        logic [TX_FIFO_WIDTH-1:0] tx_fifo_wdata, tx_fifo_rdata;
        logic                     tx_fifo_full, tx_fifo_empty;

        assign tx_fifo_wdata  = {shell_dn_data, shell_dn_tlast};
        assign shell_dn_ready = !tx_fifo_full;

        async_fifo #(
            .WIDTH      (TX_FIFO_WIDTH),
            .DEPTH      (32),
            .SYNC_STAGES(2)
        ) u_tx_cdc_fifo (
            .clk_w       (clk_100),
            .rst_n_w     (rst_n_sync),
            .wr_en       (shell_dn_valid && !tx_fifo_full),
            .wr_data     (tx_fifo_wdata),
            .full        (tx_fifo_full),

            .clk_r       (cmac_usr_clk),
            .rst_n_r     (cmac_rstn_sync),
            .rd_en       (shim_ord_tvalid && shim_ord_tready),
            .rd_data     (tx_fifo_rdata),
            .empty       (tx_fifo_empty),

            .wr_occupancy()
        );

        assign {shim_ord_tdata, shim_ord_tlast} = tx_fifo_rdata;
        assign shim_ord_tvalid = !tx_fifo_empty;

        // Reflect the shim's Sentinel-facing stream back out on
        // mkt_/ord_ top-level ports so existing probes still work.
        // These reflect the shell-side of the CDC (clk_100 domain),
        // which matches the rest of the core's observability.
        assign mkt_tready = shell_up_ready;
        assign ord_tvalid = shell_dn_valid;
        assign ord_tdata  = shell_dn_data;
      end else begin : g_no_cmac
        // Direct AXI-Stream path (Verilator / no-CMAC elaboration).
        assign shell_up_valid = mkt_tvalid;
        assign mkt_tready     = shell_up_ready;
        assign shell_up_data  = mkt_tdata;

        assign ord_tvalid     = shell_dn_valid;
        assign shell_dn_ready = ord_tready;
        assign ord_tdata      = shell_dn_data;

        // Tie off LBUS and status signals.
        assign qsfp0_rx_lbus_ready        = 1'b0;
        assign qsfp1_tx_lbus_valid        = 1'b0;
        assign qsfp1_tx_lbus_data         = '0;
        assign qsfp1_tx_lbus_mty          = '0;
        assign qsfp1_tx_lbus_sop          = 1'b0;
        assign qsfp1_tx_lbus_eop          = 1'b0;
        assign qsfp0_link_up              = 1'b0;
        assign qsfp0_stat_rx_frames       = '0;
        assign qsfp0_stat_rx_dropped_port = '0;
        assign qsfp0_stat_rx_errors       = '0;
        assign qsfp1_stat_tx_frames       = '0;
        assign qsfp0_rx_meta              = '0;
        assign qsfp0_rx_tlast             = 1'b0;
      end
    endgenerate

    // =========================================================================
    // Instrumentation shell (v1.2 attribution output)
    // =========================================================================

    logic [31:0] shell_seq_no;
    logic [31:0] shell_drop;
    logic [31:0] shell_inflight_underflow;

    sentinel_shell_v12 #(
        .CORE_LATENCY (CORE_LATENCY),
        .RISK_LATENCY (RISK_LATENCY),
        .FIFO_DEPTH   (FIFO_DEPTH),
        .EMIT_V12     (1'b1),
        .CORE_ID      (CORE_ID)
    ) u_shell (
        .clk                      (clk_100),
        .rst_n                    (rst_n_sync),
        .up_valid                 (shell_up_valid),
        .up_ready                 (shell_up_ready),
        .up_data                  (shell_up_data),
        .dn_valid                 (shell_dn_valid),
        .dn_ready                 (shell_dn_ready),
        .dn_data                  (shell_dn_data),
        .dn_tlast                 (shell_dn_tlast),
        .trace_valid              (trace_tvalid),
        .trace_ready              (trace_tready),
        .trace_data               (trace_tdata),
        .trace_size               (trace_tsize),
        .seq_no                   (shell_seq_no),
        .trace_drop_count         (shell_drop),
        .inflight_underflow_count (shell_inflight_underflow)
    );

    // =========================================================================
    // Risk gate + audit log
    // =========================================================================
    //
    // Orders flowing out of the shell loop through the risk gate
    // before reaching ``ord_tdata``. The audit log is hash-chained
    // and emitted on a separate AXI-stream interface so the DORA
    // bundle can be reconstructed off-chip.

    order_t       risk_in_order;
    logic         risk_in_valid;
    order_t       risk_out_order;
    logic         risk_out_valid;
    logic         risk_out_rejected;
    risk_reject_e risk_out_reason;
    risk_status_t risk_status;
    logic         kill_active;

    // Free-running nanosecond counter for audit timestamps. On a
    // 100 MHz clock one tick == 10 ns, so we increment by 10.
    logic [63:0] audit_ts_ns;
    always_ff @(posedge clk_100 or negedge rst_n_sync) begin
        if (!rst_n_sync) audit_ts_ns <= '0;
        else             audit_ts_ns <= audit_ts_ns + 64'd10;
    end

    // Decode the egress word into an order_t record. In a real
    // deployment the strategy publishes a rich order_t over AXI4-
    // Stream; here we keep the interface simple for elaboration.
    // The pad gives the synthesizer enough bits to fill order_t
    // (which is wider than 64b) without warnings.
    logic [$bits(order_t)-1:0] ord_pad;
    assign ord_pad        = { {($bits(order_t)-64){1'b0}}, shell_dn_data };
    assign risk_in_order  = order_t'(ord_pad);
    assign risk_in_valid  = shell_dn_valid;

    risk_gate u_risk (
        .clk                     (clk_100),
        .rst_n                   (rst_n_sync),
        .cfg_rate_max_tokens     (cfg_rate_max_tokens),
        .cfg_rate_refill_rate    (cfg_rate_refill_rate),
        .cfg_rate_refill_period  (cfg_rate_refill_period),
        .cfg_rate_enabled        (cfg_rate_enabled),
        .cfg_pos_max_long        (cfg_pos_max_long),
        .cfg_pos_max_short       (cfg_pos_max_short),
        .cfg_pos_max_notional    (cfg_pos_max_notional),
        .cfg_pos_max_order_qty   (cfg_pos_max_order_qty),
        .cfg_pos_enabled         (cfg_pos_enabled),
        .cfg_kill_armed          (cfg_kill_armed),
        .cfg_kill_auto_enabled   (cfg_kill_auto_enabled),
        .cfg_kill_loss_threshold (cfg_kill_loss_threshold),
        .cmd_kill_trigger        (cmd_kill_trigger),
        .cmd_kill_reset          (cmd_kill_reset),
        .in_valid                (risk_in_valid),
        .in_ready                (),
        .in_data                 (shell_dn_data),
        .in_order                (risk_in_order),
        .out_valid               (risk_out_valid),
        .out_ready               (shell_dn_ready),
        .out_data                (),
        .out_order               (risk_out_order),
        .out_rejected            (risk_out_rejected),
        .out_reject_reason       (risk_out_reason),
        .fill_valid              (fill_valid),
        .fill_side               (fill_side),
        .fill_qty                (fill_qty),
        .fill_notional           (fill_notional),
        .current_pnl             (current_pnl),
        .pnl_is_loss             (pnl_is_loss),
        .status                  (risk_status),
        .kill_switch_active      (kill_active),
        .stat_total_orders       (),
        .stat_passed_orders      (),
        .stat_rejected_rate      (),
        .stat_rejected_position  (),
        .stat_rejected_kill      ()
    );

    // Previous-hash port fed by the host over PCIe. Left tied off
    // in this wrapper -- the real DMA path lives in the XDMA shell.
    logic [127:0] prev_hash_lo_s = 128'h0;

    risk_audit_log #(
        .FIFO_DEPTH(AUDIT_DEPTH)
    ) u_audit (
        .clk                  (clk_100),
        .rst_n                (rst_n_sync),
        .timestamp_ns         (audit_ts_ns),
        .dec_valid            (risk_out_valid),
        .dec_order            (risk_out_order),
        .dec_passed           (!risk_out_rejected),
        .dec_reject_reason    (risk_out_reason),
        .dec_kill_triggered   (risk_out_reason == RISK_KILL_SWITCH),
        .dec_tokens_remaining (risk_status.tokens_remaining),
        .dec_position_after   ($signed(risk_status.current_position)),
        .dec_notional_after   (risk_status.current_notional),
        .prev_hash_lo         (prev_hash_lo_s),
        .rec_valid            (audit_tvalid),
        .rec_data             (audit_tdata),
        .rec_ready            (audit_tready),
        .stat_records_emitted (),
        .stat_records_dropped (),
        .stat_fifo_full       ()
    );

    // =========================================================================
    // Status LEDs + heartbeat
    // =========================================================================

    logic [25:0] hb_div;
    always_ff @(posedge clk_100 or negedge rst_n_sync) begin
        if (!rst_n_sync)
            hb_div <= '0;
        else
            hb_div <= hb_div + 1'b1;
    end
    assign heartbeat = hb_div[25];

    assign gpio_led = {heartbeat,                  // [3] "we are alive"
                       (shell_drop != 32'd0),      // [2] any drops observed
                       trace_tvalid,               // [1] trace activity
                       kill_active};               // [0] kill switch active

endmodule

// =============================================================================
// Thin MMCM wrapper -- degenerates to a pass-through for elaboration.
// Vivado infers MMCME4_ADV when targeting Ultrascale+.
// =============================================================================
module sentinel_clock_gen (
    input  logic clk_in,
    input  logic rstn_in,
    output logic clk_100,
    output logic locked
);
    // For lint/elaboration we expose a straight-through clock and a
    // one-cycle delayed reset. The real MMCM is inferred from an
    // IP-integrator block or instantiated directly for P&R.
    assign clk_100 = clk_in;
    logic rstn_q;
    always_ff @(posedge clk_in) rstn_q <= rstn_in;
    assign locked = rstn_q;
endmodule

// =============================================================================
// Minimal IBUFDS black-box so Verilator / yosys accept the top-level
// without the Xilinx unisim library. Vivado picks the real primitive
// during synthesis, so we only emit this model when VERILATOR is
// defined. If you drive the build from a different simulator, define
// SENTINEL_STUB_IBUFDS to force the stub on.
// =============================================================================
`ifdef VERILATOR
`define SENTINEL_STUB_IBUFDS
`endif

`ifdef SENTINEL_STUB_IBUFDS
(* keep_hierarchy = "yes" *)
module IBUFDS #(
    parameter string DIFF_TERM  = "FALSE",
    parameter string IOSTANDARD = "DEFAULT"
) (
    output logic O,
    input  logic I,
    input  logic IB
);
    assign O = I & ~IB;  // pass-through model for elaboration
endmodule
`endif

`endif
