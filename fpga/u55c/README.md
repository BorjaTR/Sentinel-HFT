# Sentinel-HFT on AMD Alveo U55C

This directory holds the FPGA-deployable target for Sentinel-HFT: an
Alveo U55C-shaped top level, the XDC constraints to close timing on
the Sentinel datapath at 100 MHz, and the Vivado batch scripts to
synthesize + implement + generate a bitstream from the command line.

The behavioural core lives in [`../../rtl/`](../../rtl/); this
directory is the thin connectivity + constraints layer that turns
"works in Verilator" into "fits in a xcu55c".

## Why U55C

The U55C is AMD's HBM2-equipped datacentre PCIe card. It's the
realistic target for a co-located market-making appliance:

- **Part number**: `xcu55c-fsvh2892-2L-e`
- **Fabric**: Virtex Ultrascale+ (XCVU47P-FSVH2892), 3 SLRs
- **DSPs**: 9024 (more than enough for the risk gate's notional math)
- **BRAM**: 2016 blocks (plenty for trace FIFOs)
- **HBM2**: 16 GB in two stacks (trace spill if PCIe back-pressures)
- **Network**: 2× QSFP28, 100 GbE per cage
- **Host**: PCIe Gen4 x16 via XDMA shell
- **Target Fmax for Sentinel core**: 100 MHz (conservative), headroom
  to ~250 MHz once timing-driven retiming is enabled

## What's in here

```
fpga/u55c/
├── README.md                    ← this file
├── sentinel_u55c_top.sv         ← top-level wrapper
├── constraints/
│   └── sentinel_u55c.xdc        ← timing + I/O + pblock constraints
├── reports/
│   ├── README.md                ← what each report is, and which tool emits it
│   └── area_census.txt          ← first-order area + depth estimate (checked in)
└── scripts/
    ├── build.tcl                ← full non-project Vivado flow
    ├── elaborate.tcl            ← Vivado elaboration-only check
    ├── yosys_synth.ys           ← open-source Yosys synth script
    └── area_census.py           ← RTL-scan area estimator (no toolchain)
```

## Build flow (local)

### Option A -- full synth + implementation + bitstream

Requires Vivado 2023.2 or newer on `$PATH`.

```bash
make fpga-build
```

That just shells out to:

```bash
vivado -mode batch -source fpga/u55c/scripts/build.tcl
```

Outputs land in `fpga/u55c/out/`:

| File | What it is |
|---|---|
| `post_synth.dcp` | Checkpoint after synthesis. Useful for re-running impl. |
| `post_route.dcp` | Checkpoint after full routing. |
| `sentinel_u55c.bit` | Bitstream, suitable for JTAG or XVC programming. |
| `timing_post_route.rpt` | Worst-case slack across clk_100. |
| `utilization_post_route.rpt` | LUT / FF / BRAM / DSP usage. |
| `drc.rpt`, `power.rpt` | DRC and estimated static+dynamic power. |

### Option B -- elaboration-only (fast, no bitstream)

With Vivado:

```bash
make fpga-elaborate-vivado
```

Or, the CI-friendly path that only needs Verilator:

```bash
make fpga-elaborate
```

The Verilator path is what runs on every PR via the GitHub Actions
workflow [`fpga-elaborate.yml`](../../.github/workflows/fpga-elaborate.yml).
It will not catch every Vivado-specific issue (e.g. unrouteable
IOSTANDARDs), but it catches 95% of the "someone broke the top-level"
class of bugs at zero licensing cost.

### Option C -- open-source synthesis via Yosys

Produces an independent LUT/FF estimate without a Vivado install.
Requires Yosys ≥ 0.40 (older versions can't parse SV-package
typedefs). The script is at [`scripts/yosys_synth.ys`](scripts/yosys_synth.ys)
and is wired into:

```bash
make fpga-synth-yosys
```

Yosys' `synth_xilinx -family xcup` pass only covers mapping; it does
NOT run Vivado's UltraScale+ place-and-route, so use this as a
cross-check against Vivado's area numbers — not as a bitstream
source.

### Option D -- first-order area + depth estimate (no toolchain)

For every host (no Vivado, no Yosys, no Verilator):

```bash
make fpga-area-census
```

Runs [`scripts/area_census.py`](scripts/area_census.py), a pure-Python
RTL parser that counts register bits, comparators, arithmetic
operators, muxes, and case statements per module, then prints a
first-order LUT and FF estimate plus U55C utilisation percentages.
The checked-in output is at [`reports/area_census.txt`](reports/area_census.txt).
Today the design is ≈ 3,141 FFs and ≈ 1,300 LUT6, i.e. **≈ 0.1 %
of the U55C budget** — the bring-up bottleneck is timing, not area.

## Clocking

The Sentinel datapath runs on `clk_100`, derived from the card's
differential `sysclk0` reference (300 MHz LVDS). The
`sentinel_clock_gen` module is a light wrapper around an MMCME4_ADV;
for elaboration it degenerates to a pass-through so Verilator can
chew on the whole design without a unisim library.

| Clock | Source | Frequency | Constraint |
|---|---|---|---|
| `sysclk0_p/n` | On-card oscillator | 300 MHz | `create_clock -period 3.333` |
| `clk_100` | MMCM divide-by-3 | 100 MHz | `create_generated_clock` |

For a production build you'd replace the clocking block with the
XDMA shell's `ap_clk` (typically 250 MHz) and run the Sentinel core
at either that rate or a divided-down 125 MHz user clock.

## Floorplan

`sentinel_u55c.xdc` creates two nested pblocks:

1. `pblock_sentinel` -- the whole Sentinel core, constrained to **SLR0**
   (the SLR adjacent to the QSFP28 cage) to keep the tick-to-trade
   path out of the cross-SLR super long lines.
2. `pblock_risk_gate` -- the risk gate alone, constrained to a single
   clock region inside SLR0, so that rate / position / kill decisions
   don't pay any intra-SLR routing latency skew.

Both pblocks are soft (not physically exclusive), so if Vivado's
placer wants to spill non-critical FFs outside of them it still can.
They exist to give the placer a strong hint, not to wall off the
logic.

## Physical I/O (production bring-up)

The wrapper exposes AXI-stream-like ports for tick ingress, order
egress, trace DMA, and audit DMA. On a real card those stubs get
connected to vendor IP:

| Wrapper port | Production source / sink | Vendor IP |
|---|---|---|
| `mkt_tvalid / mkt_tdata` | QSFP28 cage 0, RX path | CMAC (100GbE) |
| `ord_tvalid / ord_tdata` | QSFP28 cage 1, TX path | CMAC (100GbE) |
| `trace_tvalid / trace_tdata` | PCIe Gen4 x16 to host | XDMA (descriptor ring) |
| `audit_tvalid / audit_tdata` | PCIe Gen4 x16 to host | XDMA (secondary ring) |
| `cfg_*` / `cmd_kill_*` | PCIe BAR0 | AXI-Lite slave |
| `fill_*` | Exchange gateway feedback | CMAC RX or HBM tunnel |
| HBM2 spill (optional) | Trace overflow | HBM2 AXI-MM slave |

The vendor IP is not checked into the repo. On the target machine
you'd drop the XDMA shell project, add `sentinel_u55c_top` as a
user-logic block, and connect up the AXI interfaces.

For the full punch list of what's in-tree vs. what the integrator
still has to add (MAC, PCS, TCP offload, PTP, DMA ring driver, HSM,
multi-card orchestration, etc.), see
[`../../docs/INTEGRATION_READINESS.md`](../../docs/INTEGRATION_READINESS.md).

### Enabling the CMAC shim (`WITH_CMAC=1`)

The top-level exposes a `WITH_CMAC` parameter (default `0` so the
Verilator CI stays simple). Set it to `1` to route market data
through `rtl/eth/eth_mac_100g_shim.sv`:

```tcl
synth_design -top sentinel_u55c_top -generic WITH_CMAC=1 ...
```

With `WITH_CMAC=1`, the following top-level ports become active and
must be wired to the CMAC hard IP inside your XDMA / block-design
shell:

| Port | Direction | Description |
|---|---|---|
| `cmac_usr_clk` | in | 322.265625 MHz CMAC user clock |
| `qsfp0_rx_lbus_*` | in | CMAC QSFP0 receive LBUS (512 b, 6 b mty, SOP/EOP/err) |
| `qsfp1_tx_lbus_*` | out | CMAC QSFP1 transmit LBUS |
| `qsfp0_link_up` | out | MAC alignment OK (mirror of CMAC `stat_rx_aligned`) |

The XDC has a reserved section (§7) that creates the CMAC reference
clocks and a pblock next to the QSFP0 cage; uncomment the MGT pin
assignments after you instantiate the real `cmac_usplus_0` block.

## Expected resource usage

Rough budget for the Sentinel core only (no CMAC / XDMA):

| Resource | Estimate | U55C total | Utilization |
|---|---|---|---|
| LUTs | ~12 k | 1 303 680 | <1% |
| FFs | ~18 k | 2 607 360 | <1% |
| BRAM (36Kb) | ~8 | 2 016 | <1% |
| DSP48E2 | ~16 | 9 024 | <1% |

Numbers will be confirmed against a real run; see
`out/utilization_post_route.rpt` after the first implementation.

## Timing targets

- `clk_100` worst negative slack (WNS): **> 0 ns** at 100 MHz
- Audit-log critical path (hash-chain prev-hash fan-in): registered
  at the audit log output so the datapath is 1 cycle of combinational
  logic + routing.
- Risk-gate critical path: combinational decision across rate + position
  + kill, registered at the gate output. Designed to close at 250 MHz
  on -2L silicon; we run at 100 MHz to buy slack for the CMAC adapter
  logic that gets bolted on later.

If WNS goes negative, the first knob to turn is `phys_opt_design`
inside `build.tcl` -- it's already enabled but more aggressive
directives (`Explore`, `AggressiveExplore`) help at the cost of
runtime.

## CI behaviour

- On every PR that touches `rtl/**` or `fpga/**`, GitHub Actions runs
  `make fpga-elaborate` -- a Verilator lint pass on the full U55C top.
- Full Vivado synth + impl runs **are not wired into CI** because the
  Vivado image is enormous and the license rules are unfriendly to
  cloud CI. Run it locally before tagging a release, archive the
  `.dcp` and reports for the audit trail.

## Where the pieces fit

```
 market data (QSFP28)                                order egress (QSFP28)
         |                                                    ^
         v                                                    |
   mkt_tvalid/tdata                                    ord_tvalid/tdata
         |                                                    |
         +----> sentinel_shell_v12 --> risk_gate --> (downstream)
                      |                     |
                      v                     v
                trace FIFO --> trace_tdata  audit FIFO --> audit_tdata
                      |                            |
                      v                            v
                  PCIe XDMA host ring       PCIe XDMA host ring
                      |                            |
                      v                            v
                  host trace parser         host audit verifier
                      |                            |
                      v                            v
                  .sst on disk               .aud + DORA bundle
```
