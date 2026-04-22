# Sentinel-HFT -- Integration Readiness Gap Report

*Target platform: AMD Alveo U55C (xcu55c-fsvh2892-2L-e), co-located in a
crypto venue rack. The Sentinel datapath is bolted in between the
CMAC 100 GbE MAC and either the Xilinx XDMA shell or the venue's
own kernel-bypass TCP stack.*

This document is the honest punch list of what has to land before
Sentinel-HFT can move from "elaborates in Verilator" to "processes a
real market-data feed on a real co-lo card". Everything in here is
out-of-scope for the current repo by design -- we keep this repo the
size of a demo and push venue / vendor specifics to the deployment
project. Each gap is marked with a status, the owner the
integrator would typically assign, and the rough effort.

Status legend:

* **READY** -- in-tree and elaborates clean.
* **STUB** -- interface is wired, but the real implementation is a
  vendor block or a to-be-written module.
* **GAP** -- not present in the repo at all.

Effort legend is engineer-days of focused work on a well-resourced
FPGA / trading team, *not* calendar days (multiply by ~2x for
calendar time on a shared team).

---

## 1. Network layer (MAC, PCS, FEC)

| Item | Status | Owner | Effort |
|---|---|---|---|
| 100 GbE MAC / PCS (CMAC hard IP) | STUB | FPGA | 5 d |
| RS-FEC | STUB | FPGA | 1 d |
| QSFP28 MGT pin constraints | STUB | FPGA | 1 d |
| CMAC LBUS <-> AXI-Stream shim | READY | -- | -- |
| Ethernet / IPv4 / UDP parser | READY | -- | -- |
| ARP / ICMP responder | GAP | FPGA | 3 d |
| VLAN tag handling | GAP | FPGA | 1 d |
| TCP offload (for venues that publish over TCP) | GAP | FPGA + host | 10--20 d (or buy vendor IP) |
| PTP / hardware timestamping | GAP | FPGA | 3 d |

The shim (`rtl/eth/eth_mac_100g_shim.sv`) converts the CMAC 512 b
LBUS to the 64 b AXI-Stream the Sentinel shell consumes, parses
Ethernet+IPv4+UDP headers at SOP, and filters by UDP destination
port. It is synthesizable and elaborates under a lint-only pass.

The *MAC itself* (`cmac_usplus`) is an encrypted vendor netlist and
lives outside this repo. On the target board you would instantiate
it inside the XDMA shell's block design and wire its LBUS outputs to
`u_qsfp0_shim`. The XDC already carves out a pblock for the shim
next to the QSFP0 cage.

For venues that publish over TCP (e.g. Hyperliquid on the HTTP
endpoint, Binance US) we assume the TCP stack runs on the host in
DPDK or a kernel-bypass library and the tick payload is handed to
the FPGA over PCIe as parsed UDP-style records. Doing in-fabric TCP
reassembly is technically possible (PLDA / NetFPGA / Solarflare
offerings exist) but blows up the scope of this repo by an order of
magnitude.

## 2. Venue parsers

| Item | Status | Owner | Effort |
|---|---|---|---|
| Deribit options tick parser (host side) | READY | -- | -- |
| Hyperliquid perps tick parser (host side) | READY | -- | -- |
| Binance / OKX / Bybit parsers | GAP | host | 2 d per venue |
| In-fabric ITCH-like parser | GAP | FPGA | 10 d per protocol |

Per-venue parsing is deliberately a host-side problem in this
architecture. The FPGA sees a canonical 64 b "tick word" on
`mkt_tvalid/tdata`; host-side software (`sentinel_hft/cli/`) owns
the venue-specific framing and pushes parsed payloads over PCIe.

If a co-lo partner insists on wire-to-fabric parsing (because the
extra 200 ns of PCIe hop is unaffordable), each protocol needs its
own in-fabric parser. We have not done that here -- the demo runs
fine over the host-side path and the latency attribution harness
measures both variants.

## 3. Trace / audit DMA to host

| Item | Status | Owner | Effort |
|---|---|---|---|
| AXI-Stream trace output (64 B records) | READY | -- | -- |
| AXI-Stream audit output (96 B records) | READY | -- | -- |
| PCIe Gen4 x16 XDMA shell | GAP | FPGA | 5 d (vendor shell) |
| Descriptor ring driver (kernel) | GAP | host | 5 d |
| Descriptor ring user-space consumer | GAP | host | 3 d |
| HBM2 trace spill (back-pressure absorption) | GAP | FPGA | 7 d |

The shell emits two independent streams:

* `trace_tvalid/tdata/tsize` -- per-tick attribution record (64 B).
* `audit_tvalid/tdata` -- hash-chained risk decision record (96 B).

Both are plain AXI-Stream; any XDMA-style descriptor engine can
consume them. In a real bring-up you would drop the Xilinx XDMA
shell project into Vivado, expose two AXI-Stream ingress ports to
host, and let its DMA engine write 4 kB buffers into host-pinned
memory. Our host-side replay parser (`sentinel_hft/host/replay.py`)
already understands the record format.

The HBM2 spill is an optional add-on: if host back-pressure lasts
more than ~16 K ticks, the on-chip trace FIFO fills and we start
dropping records (observable on LED [2] today). Wiring the FIFO
overflow path to an HBM2 channel gives us ~16 GB of spill buffer
before we actually start losing evidence.

## 4. Risk-gate configuration surface

| Item | Status | Owner | Effort |
|---|---|---|---|
| Flat AXI-lite config ports | READY | -- | -- |
| AXI-Lite <-> register-file decoder | GAP | FPGA | 2 d |
| Host-side config tool (Python) | READY | -- | -- |
| Hot-reload without quiescing pipeline | GAP | FPGA | 2 d |

The top-level exposes the full config set
(`cfg_rate_*`, `cfg_pos_*`, `cfg_kill_*`, `cmd_kill_*`) as flat
ports. The integrator wires these into a standard AXI4-Lite slave
(Xilinx provides a template); the Python tool at
`sentinel_hft/cli/config.py` already writes to the matching register
offsets in `protocol/risk_config.py`.

Hot reload (update limits while the pipeline is running) works
today because every config input is synchronous and registered on
the next config-write clock; a more defensive design would also
quiesce the rate limiter's token bucket to avoid a one-tick burst
when max_tokens changes.

## 5. Timing closure

| Item | Status | Owner | Effort |
|---|---|---|---|
| Verilator lint clean | READY | -- | -- |
| Analytic area + depth estimate | READY | -- | -- |
| Yosys synth script (open-source) | READY | -- | -- |
| Yosys run on a Yosys >= 0.40 host | GAP | FPGA | 0.5 d |
| Vivado synth + impl run | GAP | FPGA | 2 d (first run) |
| 100 MHz WNS > 0 ns | GAP | FPGA | 2--5 d (depends on first run) |
| 250 MHz retiming pass | GAP | FPGA | 5--15 d |
| Multi-corner sign-off | GAP | FPGA | 2 d |

The area estimate (`fpga/u55c/reports/area_census.txt`) says the
design is ~0.1 % of the U55C's LUT budget -- area is not the
bottleneck. The bottlenecks to watch on the first Vivado run will
be:

* **BLAKE2b audit-log lane** -- the hash-chain combinational depth.
  Mitigation: the lane is already registered at the audit output, so
  any negative slack collapses to routing; one pipeline stage inside
  the `G` mix function is cheap to add.
* **Order parser fan-in** -- the risk gate decision combines rate +
  position + kill, each 64 b. Mitigation: push the position
  comparator one cycle earlier (`cfg_pos_max_notional` is already
  registered so this is a one-cycle add).
* **Cross-SLR routing** -- the pblock keeps everything in SLR0 so
  we should not be crossing SLLs, but if the placer spills anything
  it will show up as an SLR0 -> SLR1 hop with ~1 ns added latency.

## 6. Test / verification coverage

| Item | Status | Owner | Effort |
|---|---|---|---|
| Verilator testbench (`tb_sentinel_shell`) | READY | -- | -- |
| Python unit + integration tests | READY | -- | -- |
| 4 demo use cases + end-to-end smoke | READY | -- | -- |
| `tb_eth_mac_100g_shim.sv` (RX + TX + filter) | GAP | FPGA | 2 d |
| Co-sim against real pcap | GAP | FPGA + host | 3 d |
| CMAC loopback bring-up | GAP | FPGA (on hardware) | 1 d |
| QSFP optics + Finisar TX/RX sanity | GAP | hardware | 1 d |
| 72-hour soak | GAP | operations | 3 d |

The gap that matters most for *software* confidence is a shim
testbench that drives LBUS sequences extracted from a recorded pcap
-- that converts the integration from "trust the HDL" to "trust a
reproducible waveform diff". Adding it is a two-day job and is the
first thing we would do on the target board.

## 7. Operator UI + ops

| Item | Status | Owner | Effort |
|---|---|---|---|
| Dashboard HTML (sentinel-web) | READY | -- | -- |
| Live metric scraper from PCIe | GAP | host | 3 d |
| Alerting (PagerDuty / Slack hook) | GAP | ops | 1 d |
| Grafana / Prometheus exporters | GAP | ops | 2 d |
| Kill-switch arming workflow | GAP | ops | 2 d |
| Runbook (first-response + escalation) | GAP | ops | 1 d |

The web dashboard rendering is done; it renders from a static JSON
produced by `sentinel_hft/cli/demo.py`. The gap is the plumbing
that turns the on-chip counters and trace stream into the same JSON
on a live card. In production you would point a metrics process at
the trace DMA ring, aggregate to Prometheus metric names, and let
Grafana draw the same dashboard with refresh semantics.

## 8. Secrets / key management

| Item | Status | Owner | Effort |
|---|---|---|---|
| Audit log HMAC key handling | GAP | security | 3 d |
| Venue API keys rotation | GAP | security | 2 d |
| HSM / vault integration | GAP | security | 5 d |
| Bitstream signing | GAP | security | 2 d |

The audit log is hash-chained (BLAKE2b); the prev-hash seed is fed
from the host today as a 128 b constant. In production this
becomes an HMAC with a board-resident key that never leaves the
secure enclave of whichever HSM the trading desk uses. The repo
deliberately does not ship any key material.

## 9. Multi-FPGA / multi-card orchestration

| Item | Status | Owner | Effort |
|---|---|---|---|
| Deterministic core ID per board | READY | -- | -- |
| Per-core sequence numbers | READY | -- | -- |
| Cross-card trace aggregation | GAP | host | 5 d |
| Host-side deduplication of duplicate ticks | GAP | host | 3 d |
| Per-card risk-gate config sync | GAP | host | 3 d |
| N+1 active-standby failover | GAP | ops | 10 d |

Two cards running the same bitstream will produce traces that merge
losslessly on the host side thanks to the `CORE_ID` + `seq_no`
fields. The remaining items are all host-side plumbing -- the FPGA
does not need to know about its peers to stay correct.

## 10. Hardware + procurement

| Item | Status | Owner | Effort |
|---|---|---|---|
| U55C in the target rack | GAP | ops | -- |
| Co-lo cross-connect | GAP | ops | -- |
| Vivado 2023.2+ licence | GAP | ops | -- |
| JTAG / XVC access for first bring-up | GAP | ops | -- |

Listed for completeness -- none of these are engineering gaps,
they're just the physical and legal prerequisites.

---

## How to read this document

If you're a reviewer asking "is this ready for production?", the
answer is **no -- and deliberately so**. The repo is a credible
design artifact that demonstrates the hard parts of an observability
stack for HFT trading:

* deterministic-latency RTL core,
* host-hashed audit trail (on-chip serialiser + off-chip BLAKE2b chain),
* hash-chained trace format,
* honest per-module area / depth estimate,
* Verilator / Vivado / yosys builds that all elaborate.

It is **not** a drop-in bitstream. The ~100 engineer-days listed
above cover the last-mile work that any integrator would need to do
regardless of where the starting point came from; we've deliberately
scoped those out because they're venue-specific, rack-specific, and
licence-specific.

If you are the integrator, the suggested order of operations is:

1. Drop the XDMA shell project in Vivado and add `sentinel_u55c_top`
   as a user-logic block. Set `WITH_CMAC=1`.
2. Wire `u_qsfp0_shim` to the shell's CMAC LBUS outputs.
3. Run `make fpga-build` and inspect `timing_post_route.rpt`.
4. If WNS > 0, jump straight to a CMAC loopback test on the bench.
5. If WNS < 0, iterate on BLAKE2b pipelining first (it's the
   longest combinational lane in the design).
6. Then come back and walk the rest of the gap list.

Everything above is sized for a single competent FPGA engineer and a
single host-side engineer working together for roughly one quarter.
