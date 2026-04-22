// eth_pkg.sv -- Ethernet / TCP / UDP framing types for the CMAC adapter.
//
// Everything below matches the IEEE 802.3 frame layout for the
// Ethernet + IPv4 + UDP path we actually use for market data and
// orders. Fields are declared in *big-endian* wire-order so the
// frame parser can index them by byte offset without swapping.
//
// Scope: enough to route tick payloads into the Sentinel shell and
// serialise order payloads back out. No ARP, DHCP, VLAN tag, or
// fragmented-IP handling -- those live in the host-side stack or in
// the venue-specific parser.

`ifndef ETH_PKG_SV
`define ETH_PKG_SV

package eth_pkg;

  // Layer-2: Ethernet II frame header. 14 bytes.
  typedef struct packed {
    logic [47:0] dst_mac;
    logic [47:0] src_mac;
    logic [15:0] ethertype;
  } eth_hdr_t;

  localparam logic [15:0] ETHERTYPE_IPV4 = 16'h0800;
  localparam logic [15:0] ETHERTYPE_ARP  = 16'h0806;
  localparam logic [15:0] ETHERTYPE_VLAN = 16'h8100;

  // Layer-3: minimal IPv4 header, no options. 20 bytes.
  typedef struct packed {
    logic [3:0]  version;      // = 4
    logic [3:0]  ihl;           // header length in 32b words, = 5 (no opt)
    logic [7:0]  dscp_ecn;
    logic [15:0] total_length;
    logic [15:0] identification;
    logic [2:0]  flags;
    logic [12:0] frag_offset;
    logic [7:0]  ttl;
    logic [7:0]  protocol;
    logic [15:0] header_checksum;
    logic [31:0] src_ip;
    logic [31:0] dst_ip;
  } ipv4_hdr_t;

  localparam logic [7:0] IP_PROTO_TCP = 8'd6;
  localparam logic [7:0] IP_PROTO_UDP = 8'd17;

  // Layer-4: UDP header. 8 bytes.
  typedef struct packed {
    logic [15:0] src_port;
    logic [15:0] dst_port;
    logic [15:0] length;
    logic [15:0] checksum;
  } udp_hdr_t;

  // Headers combined, for quick indexing (Ethernet + IPv4 + UDP):
  // 14 + 20 + 8 = 42 bytes.
  localparam int ETH_IPV4_UDP_HDR_BYTES = 42;

  // Decoded metadata carried alongside a market-data or order
  // payload on the stream that enters / leaves the Sentinel shell.
  typedef struct packed {
    logic [31:0] src_ip;
    logic [31:0] dst_ip;
    logic [15:0] src_port;
    logic [15:0] dst_port;
    logic [15:0] payload_len;  // bytes of L4 payload
    logic [7:0]  protocol;
  } l4_meta_t;

endpackage : eth_pkg

`endif
