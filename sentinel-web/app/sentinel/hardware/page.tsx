import Link from "next/link";
import {
  Cpu,
  GitBranch,
  Clock,
  ShieldCheck,
  Zap,
  FileCode,
  Github,
  CheckCircle2,
  Circle,
  Layers,
  Hash,
  Activity,
} from "lucide-react";

// /sentinel/hardware — the Hardware-engineer path. RTL contract, CDC
// story, audit serialiser discipline, synthesis evidence, Wave 0-4
// verification methodology. Real file paths, real numbers from
// fpga/u55c/reports/area_census.txt, real GitHub links.
//
// This page is heavy by design — an FPGA engineer wants citations,
// not bullet points. Every claim has a file path or a number next
// to it.

export const metadata = {
  title: "Hardware — Sentinel-HFT",
};

const REPO = "https://github.com/BorjaTR/Sentinel-HFT/blob/main";

interface RtlBlock {
  id: string;
  name: string;
  domain: string;
  role: string;
  file: string;
  icon: typeof GitBranch;
  // Architecture decision record — the ``why`` behind the block choice.
  // Surfaced as a hover tooltip on the block diagram.
  adr: {
    id: string;
    title: string;
    choice: string;
    rationale: string;
  };
}

const RTL_BLOCKS: RtlBlock[] = [
  {
    id: "cmac_rx",
    name: "CMAC RX",
    domain: "322 MHz LBUS",
    role: "100GbE ingress, hard macro",
    file: "fpga/u55c/sentinel_u55c_top.sv",
    icon: GitBranch,
    adr: {
      id: "ADR-001",
      title: "Use Xilinx CMAC hard macro, not soft 100GbE",
      choice: "Hard CMAC + LBUS, not a soft 100GbE MAC.",
      rationale:
        "Soft MACs eat ~40% of an SLR for a feature the FPGA already has in silicon. Hard macro keeps the budget for risk + audit.",
    },
  },
  {
    id: "rxcdc",
    name: "async_fifo (RX)",
    domain: "322 → 100 MHz",
    role: "Gray-coded pointer crossing, reset_sync on each clock",
    file: "rtl/async_fifo.sv",
    icon: Clock,
    adr: {
      id: "ADR-002",
      title: "Async FIFO with Gray pointers for CMAC↔user CDC",
      choice: "Standard 2-FF + Gray-pointer async FIFO, one per direction.",
      rationale:
        "Earlier shim assumed a single clock and blew in sim (E-S1-02/03). Gray + reset_sync is the textbook pattern; no bespoke crossings in the repo.",
    },
  },
  {
    id: "parse",
    name: "Parser",
    domain: "100 MHz",
    role: "Wire format → TopOfBook structs",
    file: "rtl/instrumented_pipeline.sv",
    icon: FileCode,
    adr: {
      id: "ADR-003",
      title: "Inline parser, not a softcore",
      choice: "RTL state machine, no RISC-V front-end.",
      rationale:
        "A softcore parser adds pipeline depth and jitter we can't afford. Wire format is narrow; a fixed FSM meets the 10 ns period.",
    },
  },
  {
    id: "book",
    name: "Book state",
    domain: "100 MHz",
    role: "Order book updates, last-trade tracking",
    file: "rtl/instrumented_pipeline.sv",
    icon: Layers,
    adr: {
      id: "ADR-004",
      title: "BRAM-backed book, not URAM",
      choice: "BRAM36 for book state, reserve URAM for the trace ring.",
      rationale:
        "Book access is hot; BRAM latency + placement near the datapath is deterministic. URAM wins on size, not latency.",
    },
  },
  {
    id: "strat",
    name: "Strategy",
    domain: "100 MHz",
    role: "Spread market-maker (demo); real strategy is firm-supplied",
    file: "rtl/instrumented_pipeline.sv",
    icon: Cpu,
    adr: {
      id: "ADR-005",
      title: "Strategy is firm-supplied — demo is intentionally thin",
      choice: "Spread MM reference in-tree only so the trace + audit path lights up.",
      rationale:
        "Sentinel is observability + risk, not alpha. A bigger demo strategy would over-fit the RTL contract to one trading style.",
    },
  },
  {
    id: "risk",
    name: "risk_gate",
    domain: "100 MHz",
    role: "Token bucket + position cap + kill latch, single-cycle decision",
    file: "rtl/risk_gate.sv",
    icon: ShieldCheck,
    adr: {
      id: "ADR-006",
      title: "Single-cycle decision, registered output",
      choice: "All risk checks resolve in one combinational cone, result is registered.",
      rationale:
        "Multi-cycle risk is a liveness hazard during spikes. Single-cycle + registered keeps timing closed and the decision atomic.",
    },
  },
  {
    id: "audit",
    name: "risk_audit_log",
    domain: "100 MHz",
    role: "On-chip serialiser, host computes BLAKE2b chain off-chip",
    file: "rtl/risk_audit_log.sv",
    icon: Hash,
    adr: {
      id: "ADR-007",
      title: "Host-side BLAKE2b, on-chip serialiser only",
      choice: "RTL packs + sequences; host hashes + walks the chain.",
      rationale:
        "BLAKE2b in fabric is ~30k LUTs for no added trust — host has to recompute anyway. What the RTL enforces is the chaining discipline.",
    },
  },
  {
    id: "shell",
    name: "sentinel_shell_v12",
    domain: "100 MHz",
    role: "Trace FIFO, v1.2 64B records, per-stage timestamps",
    file: "rtl/sentinel_shell_v12.sv",
    icon: GitBranch,
    adr: {
      id: "ADR-008",
      title: "64-byte fixed record, per-stage cycle-accurate timestamps",
      choice: "Fixed-width record, DMA-friendly, one timestamp per stage.",
      rationale:
        "Variable-width records blow the DMA budget. 64B fits two cache lines, matches PCIe bursts, and leaves headroom for v1.3.",
    },
  },
  {
    id: "txcdc",
    name: "async_fifo (TX)",
    domain: "100 → 322 MHz",
    role: "Symmetric egress crossing back to LBUS",
    file: "rtl/async_fifo.sv",
    icon: Clock,
    adr: {
      id: "ADR-002",
      title: "Symmetric async FIFO on egress",
      choice: "Same Gray-pointer async FIFO, other direction.",
      rationale:
        "Same pattern both sides of the hot loop means one RTL body to prove, not two.",
    },
  },
  {
    id: "cmac_tx",
    name: "CMAC TX",
    domain: "322 MHz LBUS",
    role: "100GbE egress, hard macro",
    file: "fpga/u55c/sentinel_u55c_top.sv",
    icon: GitBranch,
    adr: {
      id: "ADR-001",
      title: "CMAC hard macro on egress too",
      choice: "Same hard macro on the TX side.",
      rationale:
        "Consistency + zero soft-MAC cost. The CMAC pair is symmetric.",
    },
  },
];

const CDC_RULES = [
  {
    label: "Two-flop synchronisers",
    body:
      "Every single-bit signal crossing a clock domain goes through a 2-FF synchroniser declared with ASYNC_REG=TRUE. See rtl/reset_sync.sv for the canonical instance.",
  },
  {
    label: "Gray-coded pointer crossings",
    body:
      "Multi-bit FIFO read/write pointers are Gray-encoded before crossing and synchronised at the destination — see rtl/async_fifo.sv. Standard CDC pattern; the codebase does not invent a new one.",
  },
  {
    label: "Reset synchronisers per clock",
    body:
      "Each clock domain gets its own reset_sync instance so the active-low release is deglitched and registered on the local clock before fanning out. Listed for both clocks in fpga/u55c/constraints/sentinel_u55c.xdc.",
  },
  {
    label: "XDC declares clocks asynchronous",
    body:
      "The two clocks are declared asynchronous with set_clock_groups -asynchronous and the FIFO pointer crossings carry set_max_delay -datapath_only entries. Vivado then knows not to try to time the crossing — the synchronisers do.",
  },
  {
    label: "Wave 2 closed E-S1-02/03",
    body:
      "Earlier shim implicitly assumed both clocks were the same. Closed in Wave 2 with the async_fifo + reset_sync rebuild. Documented in docs/SENTINEL_CORE_AUDIT.md.",
  },
];

const AREA_CENSUS = [
  { metric: "3,141", label: "FFs (upper bound)", detail: "all 15 RTL modules combined" },
  { metric: "1,298", label: "LUT6 (analytic)", detail: "first-order combinational estimate" },
  { metric: "4", label: "BRAM36", detail: "1 audit log + 1 trace FIFO + 2 metadata FIFOs" },
  { metric: "0", label: "DSP48E2", detail: "no multipliers in the risk path (deliberate)" },
  { metric: "0.10%", label: "LUT util", detail: "of the U55C 1.3M LUT budget" },
  { metric: "0.12%", label: "FF util", detail: "of the U55C 2.6M FF budget" },
  { metric: "≤ 6", label: "LUT6 longest path", detail: "ingress → risk gate AND → reject priority mux" },
  { metric: "100 MHz", label: "Datapath target", detail: "10 ns period · ≥ 2 ns slack target" },
];

const WAVES = [
  {
    name: "Wave 0",
    title: "Toolchain · SVA · cocotb harness",
    status: "closed",
    body:
      "Verilator lint-only on every PR, SystemVerilog assertions in rtl/sentinel_sva.sv, cocotb harness for risk_gate + latency attribution. Foundation for the next three waves.",
  },
  {
    name: "Wave 1",
    title: "Close 14 S0 findings",
    status: "closed",
    body:
      "Severity-0 issues from the first internal audit pass — overflow handling, kill-switch latch behaviour, audit log seq_no monotonicity, fault_injector hardening, stub-synthesis traps. All 14 closed in v1.0.0-core-audit-closed.",
  },
  {
    name: "Wave 2",
    title: "Close 19 S1 findings",
    status: "closed",
    body:
      "Severity-1 issues — CMAC CDC bridge (E-S1-02/03), Ethernet TX last-beat off-by-one (E-S1-01), audit-log edge cases (B-S1-1..4), pipeline rename + multi-in-flight (C-S1-03..05). All 19 closed.",
  },
  {
    name: "Wave 3",
    title: "Hygiene · dedup · doc alignment",
    status: "closed",
    body:
      "Removed the legacy sentinel_shell + trace_pkg duplicates (formally deferred), aligned all claims in docs with the actual RTL, added the stub_latency_core $fatal-under-SYNTHESIS guard.",
  },
  {
    name: "Wave 4",
    title: "Regression · re-audit · tag",
    status: "closed",
    body:
      "Full regression suite re-run, re-audit confirmed all 14 S0 + 19 S1 closed with zero new S0, tagged v1.0.0-core-audit-closed. Release notes pinned in docs.",
  },
  {
    name: "Wave 5",
    title: "Yosys CI + Vivado timing closure",
    status: "in_progress",
    body:
      "Phase 0 of the v2.0 cycle — Yosys synth_xilinx in CI on every PR for drift detection, plus a one-shot AWS EC2 Vivado ML Enterprise build for real WNS / TNS / utilisation numbers. See docs/V2_PLAN.md.",
  },
];

export default function HardwarePage() {
  return (
    <div className="max-w-5xl">
      <header className="mb-10">
        <div className="mb-2 flex items-center gap-2 font-mono text-xs uppercase tracking-widest text-sky-400">
          <Cpu className="h-3 w-3" />
          For hardware engineers
        </div>
        <h1 className="text-3xl font-semibold text-[#e4edf5]">
          The RTL contract
        </h1>
        <p className="mt-3 max-w-3xl text-sm leading-relaxed text-[#9ab3c8]">
          Every block in the diagram below links to the file that
          implements it. Every claim about CDC, area, or timing has a
          file path or a number next to it. If you find a hand-wave,
          file an issue — that's a bug.
        </p>
        <div className="mt-4 flex flex-wrap gap-2 font-mono text-xs">
          <Link
            href={`${REPO}/rtl`}
            className="inline-flex items-center gap-1.5 rounded-md border border-[#1a232e] bg-[#0f151d] px-3 py-1.5 text-sky-300 hover:border-sky-500/40"
          >
            <Github className="h-3 w-3" />
            rtl/
          </Link>
          <Link
            href={`${REPO}/fpga/u55c`}
            className="inline-flex items-center gap-1.5 rounded-md border border-[#1a232e] bg-[#0f151d] px-3 py-1.5 text-sky-300 hover:border-sky-500/40"
          >
            <Github className="h-3 w-3" />
            fpga/u55c/
          </Link>
          <Link
            href={`${REPO}/fpga/u55c/constraints/sentinel_u55c.xdc`}
            className="inline-flex items-center gap-1.5 rounded-md border border-[#1a232e] bg-[#0f151d] px-3 py-1.5 text-sky-300 hover:border-sky-500/40"
          >
            <Github className="h-3 w-3" />
            sentinel_u55c.xdc
          </Link>
          <Link
            href={`${REPO}/docs/SENTINEL_CORE_AUDIT.md`}
            className="inline-flex items-center gap-1.5 rounded-md border border-[#1a232e] bg-[#0f151d] px-3 py-1.5 text-sky-300 hover:border-sky-500/40"
          >
            <Github className="h-3 w-3" />
            SENTINEL_CORE_AUDIT.md
          </Link>
        </div>
      </header>

      {/* Block diagram (linear, ASCII-aesthetic for now; SVG floorplan
          arrives in Phase 6) */}
      <section className="mb-12">
        <div className="mb-2 font-mono text-[10px] uppercase tracking-wider text-sky-400">
          Pipeline
        </div>
        <h2 className="text-xl font-semibold text-white">
          Datapath — Ethernet ingress → risk → Ethernet egress
        </h2>
        <p className="mt-2 max-w-3xl text-sm text-[#9ab3c8]">
          Two clock domains: the CMAC hard macro at 322.265625 MHz LBUS,
          and the user datapath at 100 MHz. Two async FIFOs bridge
          them. Trace + audit are sidecar paths off the hot loop, not
          inline.
        </p>
        <div className="mt-6 overflow-x-auto">
          <div className="flex min-w-max items-stretch gap-2">
            {RTL_BLOCKS.map((block, i) => (
              <div key={`${block.id}-${i}`} className="flex items-stretch">
                <RtlBlockCard block={block} />
                {i < RTL_BLOCKS.length - 1 && (
                  <div className="flex items-center px-1 font-mono text-xs text-[#4d617a]">
                    →
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
        <p className="mt-3 font-mono text-[10px] text-[#4d617a]">
          Hover a block for its architecture decision record. Click to jump to the implementing file.
        </p>

        {/* SLR0 pblock floorplan */}
        <div className="mt-8">
          <div className="mb-2 flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-sky-400">
            <Layers className="h-3 w-3" />
            SLR0 floorplan
          </div>
          <h3 className="text-lg font-semibold text-white">
            pblock placement on U55C
          </h3>
          <p className="mt-1 max-w-3xl text-xs text-[#9ab3c8]">
            Constrained region derived from{" "}
            <code className="font-mono text-sky-300">
              fpga/u55c/constraints/sentinel_u55c.xdc
            </code>
            . CMAC hard macros anchor the north edge; the risk gate + audit
            serialiser cluster stays close to the CMAC TX so the egress path
            doesn&apos;t cross SLR boundaries. Hover a region for the ADR.
          </p>
          <div className="mt-4">
            <Slr0FloorplanSvg />
          </div>
        </div>
      </section>

      {/* CDC */}
      <section className="mb-12">
        <div className="mb-2 font-mono text-[10px] uppercase tracking-wider text-sky-400">
          CDC and reset
        </div>
        <h2 className="text-xl font-semibold text-white">
          Clock-domain crossings, by the book
        </h2>
        <p className="mt-2 max-w-3xl text-sm text-[#9ab3c8]">
          The hot loop has exactly two clock domains. Every signal
          that crosses follows the same five rules — there are no
          bespoke crossings.
        </p>
        <ul className="mt-5 space-y-3">
          {CDC_RULES.map(({ label, body }) => (
            <li
              key={label}
              className="rounded-md border border-[#1a232e] bg-[#0f151d] p-4"
            >
              <div className="flex items-center gap-2">
                <CheckCircle2 className="h-3.5 w-3.5 text-sky-400" />
                <div className="text-sm font-semibold text-white">{label}</div>
              </div>
              <p className="mt-1 text-sm text-[#9ab3c8]">{body}</p>
            </li>
          ))}
        </ul>
      </section>

      {/* Audit log discipline */}
      <section className="mb-12">
        <div className="mb-2 font-mono text-[10px] uppercase tracking-wider text-sky-400">
          Audit serialiser
        </div>
        <h2 className="text-xl font-semibold text-white">
          Why BLAKE2b is host-side
        </h2>
        <p className="mt-2 max-w-3xl text-sm text-[#9ab3c8]">
          The on-chip <code className="font-mono text-sky-300">risk_audit_log</code> is a
          pure serialiser. It advances <code className="font-mono text-sky-300">seq_no</code>{" "}
          on commit, packs the decision fields, and exposes a 128-bit{" "}
          <code className="font-mono text-sky-300">prev_hash_lo</code> input port driven by
          the host. The RTL does not compute any hash. That is
          deliberate:
        </p>
        <ul className="mt-3 space-y-2 text-sm leading-relaxed text-[#9ab3c8]">
          <li className="flex items-start gap-2">
            <Circle className="mt-1.5 h-1.5 w-1.5 shrink-0 fill-sky-400 text-sky-400" />
            BLAKE2b in fabric costs silicon (~30k LUTs for a full
            implementation) and adds zero trust — the host has to
            recompute the chain anyway to verify.
          </li>
          <li className="flex items-start gap-2">
            <Circle className="mt-1.5 h-1.5 w-1.5 shrink-0 fill-sky-400 text-sky-400" />
            What the RTL <em>does</em> enforce is the chaining{" "}
            <em>discipline</em>: <code className="font-mono text-sky-300">seq_no</code> only
            advances on committed writes, an overflow-tagged record is
            emitted when the sink stalls, and{" "}
            <code className="font-mono text-sky-300">prev_hash_lo</code> is captured at
            commit time, not at dispatch.
          </li>
          <li className="flex items-start gap-2">
            <Circle className="mt-1.5 h-1.5 w-1.5 shrink-0 fill-sky-400 text-sky-400" />
            The host-side verifier walks the chain and surfaces the
            first break with the failing sequence number. Truncation
            is tolerated — if the last K records are lost, the first
            N-K still verify, which matches how DORA expects incidents
            to be reported.
          </li>
        </ul>
      </section>

      {/* Synthesis evidence */}
      <section className="mb-12">
        <div className="mb-2 font-mono text-[10px] uppercase tracking-wider text-sky-400">
          Synthesis evidence
        </div>
        <h2 className="text-xl font-semibold text-white">
          First-order area + depth
        </h2>
        <p className="mt-2 max-w-3xl text-sm text-[#9ab3c8]">
          Numbers below are from{" "}
          <Link
            href={`${REPO}/fpga/u55c/reports/area_census.txt`}
            className="text-sky-300 hover:underline"
          >
            fpga/u55c/reports/area_census.txt
          </Link>{" "}
          — an analytic RTL scan, not a Vivado report. They give a
          ceiling for FF count and a first-order LUT estimate. Real
          post-synth numbers (WNS, TNS, utilisation) arrive when the
          Phase 0b cloud-Vivado pass runs on AWS EC2.
        </p>
        <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
          {AREA_CENSUS.map(({ metric, label, detail }) => (
            <div
              key={label}
              className="rounded-md border border-[#1a232e] bg-[#0f151d] p-4"
            >
              <div className="font-mono text-2xl font-semibold text-white">
                {metric}
              </div>
              <div className="mt-1 font-mono text-[10px] uppercase tracking-wider text-sky-300">
                {label}
              </div>
              <div className="mt-1 text-[11px] leading-snug text-[#6b8196]">
                {detail}
              </div>
            </div>
          ))}
        </div>
        <div className="mt-4 rounded-md border border-[#1a232e] bg-[#080b10] p-4 text-xs text-[#9ab3c8]">
          <span className="font-semibold text-amber-300">
            Caveat (preserved verbatim from area_census.txt):
          </span>{" "}
          This is NOT a post-synth report. Vivado numbers supersede
          it. FF count is an upper bound assuming full width
          propagation. LUT count is a first-order estimate from
          operator counts. Real numbers arrive once{" "}
          <code className="font-mono text-amber-300">make fpga-build</code>{" "}
          runs on a Vivado host.
        </div>
      </section>

      {/* Wave timeline */}
      <section className="mb-12">
        <div className="mb-2 font-mono text-[10px] uppercase tracking-wider text-sky-400">
          Verification methodology
        </div>
        <h2 className="text-xl font-semibold text-white">
          Wave 0 → Wave 5 — what was checked at each wave
        </h2>
        <p className="mt-2 max-w-3xl text-sm text-[#9ab3c8]">
          Verification is layered, not one big test pass. Each wave
          locks in a category of findings and tags a release. Wave
          5 is open and tracks the v2.0 cycle.
        </p>

        {/* Sankey: findings discovered → findings closed, wave by wave */}
        <div className="mt-6 rounded-md border border-[#1a232e] bg-[#080b10] p-4">
          <div className="mb-2 flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-sky-300">
            <Activity className="h-3 w-3" />
            Finding flow · discovered → closed
          </div>
          <WaveFindingsSankey />
          <p className="mt-2 font-mono text-[10px] text-[#4d617a]">
            Band heights are the number of findings handled per wave. S0 = severity-0 (critical),
            S1 = severity-1 (major), S2+ hygiene / dedup. Wave 5 is the open v2.0 cycle.
          </p>
        </div>

        <div className="mt-6 space-y-3">
          {WAVES.map(({ name, title, status, body }) => (
            <div
              key={name}
              className="flex gap-4 rounded-md border border-[#1a232e] bg-[#0f151d] p-4"
            >
              <div className="flex w-28 shrink-0 flex-col items-start gap-1">
                <div className="font-mono text-sm font-semibold text-sky-300">
                  {name}
                </div>
                <span
                  className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[9px] uppercase tracking-wider ${
                    status === "closed"
                      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                      : "border-amber-500/30 bg-amber-500/10 text-amber-300"
                  }`}
                >
                  {status === "closed" ? (
                    <CheckCircle2 className="h-2.5 w-2.5" />
                  ) : (
                    <Zap className="h-2.5 w-2.5" />
                  )}
                  {status === "closed" ? "Closed" : "In progress"}
                </span>
              </div>
              <div className="flex-1">
                <div className="text-sm font-semibold text-white">{title}</div>
                <p className="mt-1 text-sm text-[#9ab3c8]">{body}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Footnote — what ships next */}
      <section>
        <div className="rounded-lg border border-sky-500/20 bg-sky-950/20 p-5">
          <h3 className="text-sm font-semibold text-sky-200">
            Coming in this cycle
          </h3>
          <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-sky-100/80">
            <li>
              <code className="font-mono text-sky-200">docs/RTL_DESIGN_DECISIONS.md</code>,{" "}
              <code className="font-mono text-sky-200">docs/CDC_AND_RESET.md</code>,{" "}
              <code className="font-mono text-sky-200">docs/VERIFICATION_METHODOLOGY.md</code>,{" "}
              <code className="font-mono text-sky-200">docs/INTEGRATION_PLAYBOOK.md</code> rendered inline below this section (Phase 5).
            </li>
            <li>
              Yosys synth_xilinx report wired into CI on every PR
              (Phase 0a).
            </li>
            <li>
              One-shot AWS EC2 Vivado ML Enterprise build with WNS /
              TNS / utilisation numbers committed back to{" "}
              <code className="font-mono text-sky-200">fpga/u55c/reports/</code>{" "}
              (Phase 0b — runs after the AWS account + AMD eval license
              are in place).
            </li>
          </ul>
        </div>
      </section>
    </div>
  );
}

// ===========================================================================
// RtlBlockCard — a block in the datapath diagram with an ADR hover tooltip.
//
// Kept as a CSS-only hover (group-hover) so the whole page stays server-
// rendered. No client component boundary needed just to show a tooltip.

function RtlBlockCard({ block }: { block: RtlBlock }) {
  const { name, domain, role, file, icon: Icon, adr } = block;
  return (
    <div className="group relative">
      <Link
        href={`${REPO}/${file}`}
        className="block w-44 rounded-md border border-[#1a232e] bg-[#0f151d] p-3 transition hover:border-sky-500/40 hover:bg-[#131c27]"
      >
        <div className="flex items-center gap-2">
          <Icon className="h-3.5 w-3.5 text-sky-400" />
          <div className="font-mono text-xs font-semibold text-white">
            {name}
          </div>
        </div>
        <div className="mt-1 font-mono text-[9px] uppercase tracking-wider text-[#6b8196]">
          {domain}
        </div>
        <div className="mt-2 text-[11px] leading-snug text-[#9ab3c8]">
          {role}
        </div>
        <div className="mt-2 flex items-center justify-between gap-2">
          <span className="truncate font-mono text-[9px] text-[#4d617a] group-hover:text-sky-300">
            {file}
          </span>
          <span className="shrink-0 rounded border border-sky-500/30 bg-sky-500/5 px-1.5 py-0 font-mono text-[9px] text-sky-300">
            {adr.id}
          </span>
        </div>
      </Link>

      {/* Hover card — absolutely positioned so it floats above the row. */}
      <div
        role="tooltip"
        className="pointer-events-none absolute left-1/2 top-full z-20 mt-2 w-72 -translate-x-1/2 scale-95 rounded-md border border-sky-500/40 bg-[#080b10] p-3 opacity-0 shadow-xl shadow-black/40 transition duration-100 group-hover:scale-100 group-hover:opacity-100"
      >
        <div className="flex items-start justify-between gap-2">
          <div className="font-mono text-[10px] uppercase tracking-wider text-sky-300">
            {adr.id}
          </div>
          <div className="font-mono text-[9px] text-[#6b8196]">ADR</div>
        </div>
        <div className="mt-1 text-xs font-semibold text-white">{adr.title}</div>
        <div className="mt-2">
          <div className="font-mono text-[9px] uppercase tracking-wider text-[#6b8196]">
            Choice
          </div>
          <p className="mt-0.5 text-[11px] leading-snug text-[#e4edf5]">
            {adr.choice}
          </p>
        </div>
        <div className="mt-2">
          <div className="font-mono text-[9px] uppercase tracking-wider text-[#6b8196]">
            Why
          </div>
          <p className="mt-0.5 text-[11px] leading-snug text-[#9ab3c8]">
            {adr.rationale}
          </p>
        </div>
      </div>
    </div>
  );
}

// ===========================================================================
// WaveFindingsSankey — a compact SVG Sankey showing the finding flow across
// waves. We intentionally write the SVG by hand so the diagram renders
// server-side and has no chart-library dependency. Numbers match the Wave
// card bodies above.

const WAVE_FLOW: Array<{
  wave: string;
  title: string;
  s0: number;
  s1: number;
  hygiene: number;
  status: "closed" | "in_progress";
}> = [
  { wave: "Wave 0", title: "Toolchain · SVA · cocotb", s0: 0, s1: 0, hygiene: 6, status: "closed" },
  { wave: "Wave 1", title: "Close S0 findings", s0: 14, s1: 0, hygiene: 0, status: "closed" },
  { wave: "Wave 2", title: "Close S1 findings", s0: 0, s1: 19, hygiene: 0, status: "closed" },
  { wave: "Wave 3", title: "Hygiene · dedup", s0: 0, s1: 0, hygiene: 8, status: "closed" },
  { wave: "Wave 4", title: "Regression · re-audit", s0: 0, s1: 0, hygiene: 4, status: "closed" },
  { wave: "Wave 5", title: "Yosys + Vivado", s0: 0, s1: 0, hygiene: 2, status: "in_progress" },
];

function WaveFindingsSankey() {
  const W = 760;
  const H = 260;
  const PADL = 20;
  const PADR = 20;
  const PADT = 30;
  const PADB = 40;
  const innerW = W - PADL - PADR;
  const innerH = H - PADT - PADB;
  const n = WAVE_FLOW.length;

  // Column layout: one strip per wave, evenly spaced.
  const colW = innerW / n;
  const bandPad = 10;

  // Scale band heights by the wave's total findings. We reserve a
  // minimum non-zero height so closed-with-zero-findings waves still
  // show up as a thin slab (otherwise Wave 0 and similar disappear).
  const totals = WAVE_FLOW.map((w) => w.s0 + w.s1 + w.hygiene);
  const maxTotal = Math.max(...totals, 1);
  const maxBandH = innerH - 2 * bandPad;
  const minBandH = 12;

  const bandRects: Array<{
    x: number;
    y: number;
    w: number;
    h: number;
    s0H: number;
    s1H: number;
    hygieneH: number;
    status: string;
    wave: string;
    title: string;
    total: number;
  }> = [];

  WAVE_FLOW.forEach((w, i) => {
    const total = totals[i];
    const norm = total / maxTotal;
    const h = total === 0 ? minBandH : Math.max(minBandH, norm * maxBandH);
    const y = PADT + (innerH - h) / 2;
    const x = PADL + i * colW + bandPad / 2;
    const bw = colW - bandPad;
    const s0H = total > 0 ? (w.s0 / total) * h : 0;
    const s1H = total > 0 ? (w.s1 / total) * h : 0;
    const hygieneH = total > 0 ? (w.hygiene / total) * h : h;
    bandRects.push({
      x,
      y,
      w: bw,
      h,
      s0H,
      s1H,
      hygieneH,
      status: w.status,
      wave: w.wave,
      title: w.title,
      total,
    });
  });

  // Connector polygons between adjacent bands — thin gradient strips so
  // the eye carries through the waves.
  const connectors: Array<{ points: string; opacity: number }> = [];
  for (let i = 0; i < bandRects.length - 1; i++) {
    const a = bandRects[i];
    const b = bandRects[i + 1];
    const x1 = a.x + a.w;
    const x2 = b.x;
    const y1t = a.y;
    const y1b = a.y + a.h;
    const y2t = b.y;
    const y2b = b.y + b.h;
    connectors.push({
      points: `${x1},${y1t} ${x2},${y2t} ${x2},${y2b} ${x1},${y1b}`,
      opacity: 0.12,
    });
  }

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="h-auto w-full"
      role="img"
      aria-label="Wave findings Sankey"
    >
      <defs>
        <linearGradient id="wave-connector" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.35" />
          <stop offset="100%" stopColor="#8b5cf6" stopOpacity="0.2" />
        </linearGradient>
      </defs>

      {/* Connectors first so they sit behind the bands. */}
      {connectors.map((c, i) => (
        <polygon key={`c${i}`} points={c.points} fill="url(#wave-connector)" />
      ))}

      {/* Wave bands, stacked by severity. */}
      {bandRects.map((b, i) => {
        const running = b.status === "in_progress";
        return (
          <g key={b.wave}>
            {/* S0 slab (critical) */}
            {b.s0H > 0 && (
              <rect
                x={b.x}
                y={b.y}
                width={b.w}
                height={b.s0H}
                fill="#f43f5e"
                fillOpacity={0.75}
              >
                <title>
                  {b.wave}: {WAVE_FLOW[i].s0} S0 findings closed
                </title>
              </rect>
            )}
            {/* S1 slab (major) */}
            {b.s1H > 0 && (
              <rect
                x={b.x}
                y={b.y + b.s0H}
                width={b.w}
                height={b.s1H}
                fill="#f59e0b"
                fillOpacity={0.75}
              >
                <title>
                  {b.wave}: {WAVE_FLOW[i].s1} S1 findings closed
                </title>
              </rect>
            )}
            {/* Hygiene slab */}
            {b.hygieneH > 0 && (
              <rect
                x={b.x}
                y={b.y + b.s0H + b.s1H}
                width={b.w}
                height={b.hygieneH}
                fill={running ? "#8b5cf6" : "#10b981"}
                fillOpacity={running ? 0.5 : 0.6}
                stroke={running ? "#8b5cf6" : "none"}
                strokeDasharray={running ? "4 3" : undefined}
                strokeWidth={running ? 1 : 0}
              >
                <title>
                  {b.wave}: {WAVE_FLOW[i].hygiene} hygiene/dedup items
                  {running ? " (in progress)" : ""}
                </title>
              </rect>
            )}
            {/* Band border */}
            <rect
              x={b.x}
              y={b.y}
              width={b.w}
              height={b.h}
              fill="none"
              stroke="#1f2a38"
              strokeWidth={0.75}
            />
            {/* Top label: wave name + total */}
            <text
              x={b.x + b.w / 2}
              y={PADT - 14}
              textAnchor="middle"
              fontSize={10}
              fontFamily="ui-monospace, SFMono-Regular, monospace"
              fill="#e4edf5"
            >
              {b.wave}
            </text>
            <text
              x={b.x + b.w / 2}
              y={PADT - 2}
              textAnchor="middle"
              fontSize={9}
              fontFamily="ui-monospace, SFMono-Regular, monospace"
              fill={running ? "#c4b5fd" : "#6b8196"}
            >
              {running ? "in progress" : `n=${b.total}`}
            </text>
            {/* Bottom label: short title */}
            <text
              x={b.x + b.w / 2}
              y={H - PADB + 14}
              textAnchor="middle"
              fontSize={9}
              fontFamily="ui-monospace, SFMono-Regular, monospace"
              fill="#9ab3c8"
            >
              {b.title}
            </text>
          </g>
        );
      })}

      {/* Legend */}
      <g transform={`translate(${PADL}, ${H - 8})`}>
        <rect x={0} y={-8} width={10} height={8} fill="#f43f5e" fillOpacity={0.75} />
        <text
          x={14}
          y={-1}
          fontSize={9}
          fontFamily="ui-monospace, SFMono-Regular, monospace"
          fill="#f87171"
        >
          S0 critical
        </text>
        <rect x={90} y={-8} width={10} height={8} fill="#f59e0b" fillOpacity={0.75} />
        <text
          x={104}
          y={-1}
          fontSize={9}
          fontFamily="ui-monospace, SFMono-Regular, monospace"
          fill="#fbbf24"
        >
          S1 major
        </text>
        <rect x={180} y={-8} width={10} height={8} fill="#10b981" fillOpacity={0.6} />
        <text
          x={194}
          y={-1}
          fontSize={9}
          fontFamily="ui-monospace, SFMono-Regular, monospace"
          fill="#34d399"
        >
          hygiene / dedup
        </text>
        <rect
          x={310}
          y={-8}
          width={10}
          height={8}
          fill="#8b5cf6"
          fillOpacity={0.5}
          stroke="#8b5cf6"
          strokeDasharray="4 3"
          strokeWidth={1}
        />
        <text
          x={324}
          y={-1}
          fontSize={9}
          fontFamily="ui-monospace, SFMono-Regular, monospace"
          fill="#a78bfa"
        >
          open (wave 5)
        </text>
      </g>
    </svg>
  );
}

// ===========================================================================
// Slr0FloorplanSvg — illustrative U55C SLR0 floorplan. Pblock coordinates are
// illustrative, not SLICE-accurate; the point is to show the relative
// placement story (CMAC at the top, risk + audit next to CMAC TX, trace
// sidecar parked on the East edge). Each region has an ADR tooltip that
// reuses the same ADR IDs as the block diagram.

interface FloorplanRegion {
  id: string;
  label: string;
  adrId: string;
  x: number;
  y: number;
  w: number;
  h: number;
  fill: string;
  stroke: string;
  text: string;
  tooltip: string;
}

const SLR0_REGIONS: FloorplanRegion[] = [
  {
    id: "cmac_rx",
    label: "CMAC RX",
    adrId: "ADR-001",
    x: 30,
    y: 40,
    w: 140,
    h: 38,
    fill: "#0f172a",
    stroke: "#38bdf8",
    text: "#7dd3fc",
    tooltip: "ADR-001 · Hard CMAC at 322 MHz LBUS. Anchored north edge of SLR0.",
  },
  {
    id: "cmac_tx",
    label: "CMAC TX",
    adrId: "ADR-001",
    x: 180,
    y: 40,
    w: 140,
    h: 38,
    fill: "#0f172a",
    stroke: "#38bdf8",
    text: "#7dd3fc",
    tooltip: "ADR-001 · Symmetric hard CMAC TX. Same north edge for egress.",
  },
  {
    id: "async_fifo_rx",
    label: "async_fifo RX",
    adrId: "ADR-002",
    x: 30,
    y: 88,
    w: 140,
    h: 32,
    fill: "#1a1033",
    stroke: "#a78bfa",
    text: "#c4b5fd",
    tooltip: "ADR-002 · Gray-pointer + reset_sync. 322 → 100 MHz crossing.",
  },
  {
    id: "async_fifo_tx",
    label: "async_fifo TX",
    adrId: "ADR-002",
    x: 180,
    y: 88,
    w: 140,
    h: 32,
    fill: "#1a1033",
    stroke: "#a78bfa",
    text: "#c4b5fd",
    tooltip: "ADR-002 · Same async FIFO, 100 → 322 MHz return path.",
  },
  {
    id: "parse_book_strat",
    label: "parse · book · strat",
    adrId: "ADR-003",
    x: 30,
    y: 130,
    w: 290,
    h: 50,
    fill: "#082f1a",
    stroke: "#10b981",
    text: "#6ee7b7",
    tooltip: "ADR-003 / 004 / 005 · Parser + BRAM-backed book + demo strategy.",
  },
  {
    id: "risk_gate",
    label: "risk_gate",
    adrId: "ADR-006",
    x: 30,
    y: 190,
    w: 140,
    h: 50,
    fill: "#1a0d0d",
    stroke: "#f43f5e",
    text: "#fda4af",
    tooltip:
      "ADR-006 · Single-cycle token-bucket + position cap + kill latch. Placed adjacent to CMAC TX.",
  },
  {
    id: "audit_log",
    label: "risk_audit_log",
    adrId: "ADR-007",
    x: 180,
    y: 190,
    w: 140,
    h: 50,
    fill: "#241a08",
    stroke: "#f59e0b",
    text: "#fcd34d",
    tooltip:
      "ADR-007 · On-chip serialiser only. BRAM36 block ties to trace ring. Host walks BLAKE2b chain.",
  },
  {
    id: "shell",
    label: "sentinel_shell_v12 (trace)",
    adrId: "ADR-008",
    x: 340,
    y: 40,
    w: 110,
    h: 200,
    fill: "#0b1c2a",
    stroke: "#0ea5e9",
    text: "#7dd3fc",
    tooltip:
      "ADR-008 · Trace FIFO on East edge — off the hot loop. 64-byte records, per-stage timestamps, PCIe-friendly.",
  },
];

const SLR_OUTLINE = { x: 20, y: 25, w: 440, h: 230 };

function Slr0FloorplanSvg() {
  return (
    <div className="overflow-x-auto">
      <svg
        viewBox="0 0 480 280"
        className="h-auto w-full max-w-3xl"
        role="img"
        aria-label="SLR0 pblock floorplan"
      >
        {/* SLR0 die outline */}
        <rect
          x={SLR_OUTLINE.x}
          y={SLR_OUTLINE.y}
          width={SLR_OUTLINE.w}
          height={SLR_OUTLINE.h}
          fill="#0a0e14"
          stroke="#1f2a38"
          strokeWidth={1}
          strokeDasharray="4 3"
        />
        <text
          x={SLR_OUTLINE.x + 6}
          y={SLR_OUTLINE.y + 16}
          fontSize={10}
          fontFamily="ui-monospace, SFMono-Regular, monospace"
          fill="#6b8196"
        >
          SLR0 · xcu55c-fsvh2892
        </text>
        <text
          x={SLR_OUTLINE.x + SLR_OUTLINE.w - 6}
          y={SLR_OUTLINE.y + 16}
          fontSize={10}
          textAnchor="end"
          fontFamily="ui-monospace, SFMono-Regular, monospace"
          fill="#4d617a"
        >
          illustrative · not SLICE-accurate
        </text>

        {/* Clock domain annotation */}
        <line
          x1={SLR_OUTLINE.x + 5}
          y1={82}
          x2={SLR_OUTLINE.x + SLR_OUTLINE.w - 5}
          y2={82}
          stroke="#38bdf8"
          strokeOpacity={0.3}
          strokeDasharray="2 4"
        />
        <text
          x={SLR_OUTLINE.x + 8}
          y={80}
          fontSize={8}
          fontFamily="ui-monospace, SFMono-Regular, monospace"
          fill="#38bdf8"
          fillOpacity={0.8}
        >
          322 MHz LBUS
        </text>
        <line
          x1={SLR_OUTLINE.x + 5}
          y1={124}
          x2={SLR_OUTLINE.x + SLR_OUTLINE.w - 5}
          y2={124}
          stroke="#10b981"
          strokeOpacity={0.3}
          strokeDasharray="2 4"
        />
        <text
          x={SLR_OUTLINE.x + 8}
          y={122}
          fontSize={8}
          fontFamily="ui-monospace, SFMono-Regular, monospace"
          fill="#10b981"
          fillOpacity={0.85}
        >
          100 MHz user datapath
        </text>

        {/* Regions */}
        {SLR0_REGIONS.map((r) => (
          <g key={r.id} className="group">
            <rect
              x={r.x}
              y={r.y}
              width={r.w}
              height={r.h}
              fill={r.fill}
              stroke={r.stroke}
              strokeWidth={1.25}
              rx={3}
              ry={3}
              className="transition-[fill-opacity] duration-150 hover:[fill-opacity:0.8]"
            >
              <title>{r.tooltip}</title>
            </rect>
            <text
              x={r.x + r.w / 2}
              y={r.y + r.h / 2 + 3}
              textAnchor="middle"
              fontSize={10}
              fontFamily="ui-monospace, SFMono-Regular, monospace"
              fill={r.text}
              className="pointer-events-none"
            >
              {r.label}
            </text>
            <text
              x={r.x + r.w - 4}
              y={r.y + 10}
              textAnchor="end"
              fontSize={7}
              fontFamily="ui-monospace, SFMono-Regular, monospace"
              fill={r.text}
              fillOpacity={0.6}
              className="pointer-events-none"
            >
              {r.adrId}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}
