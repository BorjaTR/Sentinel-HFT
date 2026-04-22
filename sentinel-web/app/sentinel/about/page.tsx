import Link from "next/link";
import {
  ArrowRight,
  Briefcase,
  Cpu,
  ShieldCheck,
  Database,
  Zap,
  Network,
  Brain,
  Scale,
  CheckCircle2,
  Info,
  HardDrive,
  Package,
} from "lucide-react";
import { OfflineBundleDownload } from "./offline-bundle-download";

// /sentinel/about — the plain-English explainer that answers "what is
// this thing?" before the user has to figure it out from the drills or
// the RTL. No firm names, no pitch language, no marketing.

export const metadata = {
  title: "About — Sentinel-HFT",
};

const PIECES = [
  {
    icon: Network,
    title: "1. Wrap an existing FPGA trading core",
    body:
      "Sentinel sits as an instrumentation shell around your tick-to-trade pipeline. It does not change behaviour — it captures cycle-accurate timestamps at every stage (parse, book, strategy, risk, egress) and emits a 64-byte trace record per transaction.",
  },
  {
    icon: ShieldCheck,
    title: "2. Enforce a deterministic risk gate",
    body:
      "A token-bucket rate limiter, a position tracker, and a kill switch sit between the strategy and the egress path. Single-cycle decision, registered output. Every decision is sequenced and emitted to an on-chip audit serialiser.",
  },
  {
    icon: Database,
    title: "3. Chain every decision tamper-evidently",
    body:
      "The audit serialiser advances a monotonic seq_no on commit and captures a host-supplied prev_hash_lo into each record. The host then re-derives BLAKE2b over the committed payload, walks the chain, and surfaces any break with the exact failing sequence number.",
  },
  {
    icon: Scale,
    title: "4. Produce regulator-shaped evidence",
    body:
      "Every drill assembles a DORA-shaped bundle (schema dora-bundle/1) covering the run window, decisions taken, audit chain state, and latency distribution — the structure DORA's RTS asks for, dropped onto disk by the pipeline rather than reconstructed by a compliance engineer after the fact.",
  },
  {
    icon: Brain,
    title: "5. Explain the run, locally",
    body:
      "A nightly RCA agent reads the trace + audit bundle and writes a plain-English digest of what happened. Default backend is rule-based (no network call). An optional local Llama or Claude hook is available for richer narratives — off by default, and the prompt only ever carries aggregate metrics, never raw records.",
  },
  {
    icon: Zap,
    title: "6. Catch drift in tens of trades, not days",
    body:
      "Three streaming detectors run online: a Welford z-score on per-stage latency, a CUSUM on reject-rate drift, and a Wald SPRT on fill-rate degradation. Each alert is itself BLAKE2b-chained so the alert log is as auditable as the decision log.",
  },
];

const NOT_IN_SCOPE = [
  "Strategy library or alpha toolkit. The demo strategy is intentionally thin (a spread market-maker) — it exercises the trace and audit paths, nothing more.",
  "Live production hot-path risk gate. The RTL primitives are hot-path-capable (single-cycle decision, pass-through timing) but adopting them in production requires a sign-off process that is out of scope here. The realistic deployment is staging and post-trade evidence generation.",
  "Order-management or execution venue integration. Sentinel sits behind whatever the firm's OMS already does.",
  "Market-data normalisation. We assume the parser already understands the venue's wire format. ITCH, FIX, OUCH, custom — that's existing IP.",
];

const RESIDENCY = [
  "Trace records (.sst), audit log (.aud), DORA bundles (dora.json), summaries (summary.md), RCA digests, triage alert chains — every byte stays on the host that runs the pipeline.",
  "No third-party LLM endpoint is called by default. The deterministic RCA backend writes the digest entirely locally.",
  "If the optional Claude/Llama hook is enabled, the prompt carries only aggregate metrics (p99 latency, reject counts, kill state, head hash) — never trace records, never order details, never per-instrument fills. That's a deliberate design constraint, not a marketing claim.",
  "The 'runs offline from USB' build (Phase 6) drops the demo binary, fixtures, and audit verifier into a single zip with no network dependency. A regulator can take it home.",
];

export default function AboutPage() {
  return (
    <div className="max-w-4xl">
      <header className="mb-10">
        <h1 className="font-mono text-xs uppercase tracking-widest text-[#4d617a]">
          About
        </h1>
        <h2 className="mt-2 text-3xl font-semibold text-[#e4edf5]">
          What Sentinel-HFT actually is
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-relaxed text-[#9ab3c8]">
          Sentinel-HFT is a tick-to-trade observability and risk-evidence
          appliance for a co-located FPGA trading path. It does six
          things, all together. Read the six in order and the rest of
          the product will make sense.
        </p>
      </header>

      {/* Six-piece explainer */}
      <section className="space-y-3">
        {PIECES.map(({ icon: Icon, title, body }) => (
          <div
            key={title}
            className="flex gap-4 rounded-lg border border-[#1a232e] bg-[#0f151d] p-5"
          >
            <div className="shrink-0 rounded-md border border-[#1a232e] bg-[#0a0e14] p-2">
              <Icon className="h-4 w-4 text-emerald-400" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-white">{title}</h3>
              <p className="mt-1 text-sm leading-relaxed text-[#9ab3c8]">
                {body}
              </p>
            </div>
          </div>
        ))}
      </section>

      {/* Data residency */}
      <section className="mt-12">
        <div className="mb-2 flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-sky-400">
          <HardDrive className="h-3 w-3" />
          Data residency
        </div>
        <h3 className="text-xl font-semibold text-white">
          Where the bytes live
        </h3>
        <p className="mt-2 max-w-3xl text-sm text-[#9ab3c8]">
          A regulator-grade observability tool is only useful if its
          own data path is auditable. Here is exactly where every byte
          ends up:
        </p>

        <DataResidencyDiagram />

        <ul className="mt-6 space-y-3">
          {RESIDENCY.map((line) => (
            <li
              key={line}
              className="flex items-start gap-3 rounded-md border border-[#1a232e] bg-[#0f151d] p-4 text-sm text-[#9ab3c8]"
            >
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-sky-400" />
              <span>{line}</span>
            </li>
          ))}
        </ul>
      </section>

      {/* Offline evidence bundle */}
      <section className="mt-12">
        <div className="mb-2 flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-emerald-400">
          <Package className="h-3 w-3" />
          Offline evidence bundle
        </div>
        <h3 className="text-xl font-semibold text-white">
          The zip the regulator takes home
        </h3>
        <p className="mt-2 max-w-3xl text-sm text-[#9ab3c8]">
          The Phase 6 deliverable is a single{" "}
          <code className="rounded bg-[#0a0e14] px-1 py-0.5 font-mono text-xs text-sky-300">
            sentinel-hft-offline-bundle.zip
          </code>{" "}
          — fixtures, smoke script, audit verifier source, methodology
          docs. Zero third-party deps. A regulator can take it home,
          drop it on a laptop, and re-run the audit-chain walk against
          any{" "}
          <code className="rounded bg-[#0a0e14] px-1 py-0.5 font-mono text-xs text-sky-300">
            .aud
          </code>{" "}
          file produced by this build. The zip is assembled on-demand
          from the server&apos;s own source tree, so it always
          reflects the deployed build.
        </p>
        <OfflineBundleDownload />
      </section>

      {/* What it isn't */}
      <section className="mt-12">
        <div className="mb-2 flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-amber-400">
          <Info className="h-3 w-3" />
          Not in scope
        </div>
        <h3 className="text-xl font-semibold text-white">
          Things Sentinel deliberately does not do
        </h3>
        <p className="mt-2 max-w-3xl text-sm text-[#9ab3c8]">
          Naming the boundaries up front is part of being audit-grade.
          Sentinel is observability and risk evidence, not a trading
          system.
        </p>
        <ul className="mt-4 space-y-3">
          {NOT_IN_SCOPE.map((line) => (
            <li
              key={line}
              className="rounded-md border border-amber-900/40 bg-amber-950/20 p-4 text-sm text-amber-100/80"
            >
              {line}
            </li>
          ))}
        </ul>
      </section>

      {/* Audience CTAs */}
      <section className="mt-14 rounded-lg border border-[#1a232e] bg-[#080b10] p-6">
        <h3 className="text-lg font-semibold text-white">Where to next</h3>
        <p className="mt-1 text-sm text-[#9ab3c8]">
          Pick the path that matches the question you actually want to
          answer.
        </p>
        <div className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-2">
          <Link
            href="/sentinel"
            className="group flex items-center justify-between rounded-md border border-[#1a232e] bg-[#0f151d] p-4 transition hover:border-emerald-500/40 hover:bg-[#131c27]"
          >
            <div className="flex items-center gap-3">
              <Briefcase className="h-5 w-5 text-emerald-400" />
              <div>
                <div className="text-sm font-semibold text-white">
                  For trading desks
                </div>
                <div className="text-xs text-[#6b8196]">
                  Drills, evidence bundles, regulatory crosswalk
                </div>
              </div>
            </div>
            <ArrowRight className="h-4 w-4 text-[#4d617a] transition group-hover:translate-x-0.5 group-hover:text-emerald-400" />
          </Link>
          <Link
            href="/sentinel/hardware"
            className="group flex items-center justify-between rounded-md border border-[#1a232e] bg-[#0f151d] p-4 transition hover:border-sky-500/40 hover:bg-[#131c27]"
          >
            <div className="flex items-center gap-3">
              <Cpu className="h-5 w-5 text-sky-400" />
              <div>
                <div className="text-sm font-semibold text-white">
                  For hardware engineers
                </div>
                <div className="text-xs text-[#6b8196]">
                  RTL, CDC, timing, synthesis evidence
                </div>
              </div>
            </div>
            <ArrowRight className="h-4 w-4 text-[#4d617a] transition group-hover:translate-x-0.5 group-hover:text-sky-400" />
          </Link>
        </div>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------
// Data-residency SVG diagram.
//
// Visualises what "runs local" actually means. One big dashed box is
// the host (firm co-lo cage). Inside it sit the six artifact types
// the pipeline writes. One solid arrow leaves the host boundary into
// the "regulator" node -- that's the offline bundle zip, physically
// handed off (sneaker-net). One dashed arrow labelled "aggregate
// metrics only · off by default" leaves toward the optional LLM
// hook. Any byte not on a solid "inside the host" edge is opt-in.
// ---------------------------------------------------------------------

type Artifact = {
  label: string;
  path: string;
  note: string;
  y: number;
};

const ARTIFACTS: Artifact[] = [
  { label: ".sst trace records", path: "out/<drill>/trace.sst", note: "64-byte cycle-accurate transactions", y: 78 },
  { label: ".aud audit chain", path: "out/<drill>/audit.aud", note: "BLAKE2b-chained decisions", y: 118 },
  { label: "dora.json bundle", path: "out/<drill>/dora.json", note: "RTS-shaped evidence", y: 158 },
  { label: "summary.md runbook", path: "out/<drill>/summary.md", note: "plain-English run report", y: 198 },
  { label: "rca/<date>.md digest", path: "out/digests/", note: "nightly root-cause narrative", y: 238 },
  { label: "triage/alerts.alog", path: "out/triage/", note: "BLAKE2b-chained detector alerts", y: 278 },
];

function DataResidencyDiagram() {
  const W = 820;
  const H = 360;
  const hostX = 24;
  const hostY = 44;
  const hostW = 540;
  const hostH = 296;
  const pipelineX = 56;
  const pipelineY = 158;
  const pipelineW = 150;
  const pipelineH = 60;
  const artifactX = 236;
  const artifactW = 300;

  return (
    <div className="mt-6 rounded-lg border border-[#1a232e] bg-[#080b10] p-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="font-mono text-[10px] uppercase tracking-wider text-sky-300">
          Host boundary · every artifact stays local
        </div>
        <div className="flex items-center gap-3 font-mono text-[9px] uppercase tracking-wider text-[#6b8196]">
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full bg-emerald-400" />
            inside host
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full bg-amber-400" />
            physical hand-off
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full bg-violet-400" />
            opt-in edge
          </span>
        </div>
      </div>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          <marker
            id="res-arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#4b6b86" />
          </marker>
          <marker
            id="res-arrow-opt"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#8b5cf6" />
          </marker>
          <marker
            id="res-arrow-bundle"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#f59e0b" />
          </marker>
        </defs>

        {/* Host boundary */}
        <rect
          x={hostX}
          y={hostY}
          width={hostW}
          height={hostH}
          rx={10}
          fill="#0a0e14"
          stroke="#1f3550"
          strokeDasharray="6 4"
          strokeWidth={1.5}
        />
        <text
          x={hostX + 14}
          y={hostY + 22}
          fontFamily="ui-monospace, monospace"
          fontSize={11}
          fill="#93c5fd"
        >
          HOST · firm co-lo cage · same rack as the FPGA card
        </text>

        {/* Pipeline node */}
        <rect
          x={pipelineX}
          y={pipelineY}
          width={pipelineW}
          height={pipelineH}
          rx={6}
          fill="#0f151d"
          stroke="#34d399"
          strokeWidth={1.5}
        />
        <text
          x={pipelineX + pipelineW / 2}
          y={pipelineY + 22}
          textAnchor="middle"
          fontFamily="ui-monospace, monospace"
          fontSize={11}
          fill="#e4edf5"
          fontWeight={600}
        >
          Sentinel pipeline
        </text>
        <text
          x={pipelineX + pipelineW / 2}
          y={pipelineY + 38}
          textAnchor="middle"
          fontFamily="ui-monospace, monospace"
          fontSize={9}
          fill="#6b8196"
        >
          trace · audit · dora
        </text>
        <text
          x={pipelineX + pipelineW / 2}
          y={pipelineY + 50}
          textAnchor="middle"
          fontFamily="ui-monospace, monospace"
          fontSize={9}
          fill="#6b8196"
        >
          rca · triage
        </text>

        {/* Artifacts */}
        {ARTIFACTS.map((a) => {
          const x = artifactX;
          const y = a.y;
          return (
            <g key={a.label}>
              <rect
                x={x}
                y={y}
                width={artifactW}
                height={32}
                rx={4}
                fill="#0f151d"
                stroke="#1a232e"
              />
              <text
                x={x + 10}
                y={y + 14}
                fontFamily="ui-monospace, monospace"
                fontSize={10}
                fill="#e4edf5"
              >
                {a.label}
              </text>
              <text
                x={x + 10}
                y={y + 26}
                fontFamily="ui-monospace, monospace"
                fontSize={9}
                fill="#6b8196"
              >
                {a.note}
              </text>
              <line
                x1={pipelineX + pipelineW}
                y1={pipelineY + pipelineH / 2}
                x2={x - 2}
                y2={y + 16}
                stroke="#34d399"
                strokeOpacity={0.35}
                strokeWidth={1}
                markerEnd="url(#res-arrow)"
              />
            </g>
          );
        })}

        {/* Regulator node (outside host, right side) */}
        <rect
          x={600}
          y={130}
          width={196}
          height={64}
          rx={6}
          fill="#0f151d"
          stroke="#f59e0b"
          strokeWidth={1.5}
        />
        <text
          x={698}
          y={152}
          textAnchor="middle"
          fontFamily="ui-monospace, monospace"
          fontSize={11}
          fill="#fcd34d"
          fontWeight={600}
        >
          Regulator / DORA auditor
        </text>
        <text
          x={698}
          y={170}
          textAnchor="middle"
          fontFamily="ui-monospace, monospace"
          fontSize={9}
          fill="#9ab3c8"
        >
          offline bundle zip
        </text>
        <text
          x={698}
          y={184}
          textAnchor="middle"
          fontFamily="ui-monospace, monospace"
          fontSize={9}
          fill="#6b8196"
        >
          physical / sneaker-net
        </text>
        <line
          x1={hostX + hostW + 2}
          y1={162}
          x2={598}
          y2={162}
          stroke="#f59e0b"
          strokeWidth={1.5}
          markerEnd="url(#res-arrow-bundle)"
        />
        <text
          x={580}
          y={156}
          textAnchor="end"
          fontFamily="ui-monospace, monospace"
          fontSize={9}
          fill="#fbbf24"
        >
          zip
        </text>

        {/* Optional LLM (outside host, lower right) */}
        <rect
          x={600}
          y={250}
          width={196}
          height={64}
          rx={6}
          fill="#0f151d"
          stroke="#8b5cf6"
          strokeDasharray="3 3"
          strokeWidth={1.5}
        />
        <text
          x={698}
          y={272}
          textAnchor="middle"
          fontFamily="ui-monospace, monospace"
          fontSize={11}
          fill="#c4b5fd"
          fontWeight={600}
        >
          Optional LLM hook
        </text>
        <text
          x={698}
          y={290}
          textAnchor="middle"
          fontFamily="ui-monospace, monospace"
          fontSize={9}
          fill="#9ab3c8"
        >
          aggregate metrics only
        </text>
        <text
          x={698}
          y={304}
          textAnchor="middle"
          fontFamily="ui-monospace, monospace"
          fontSize={9}
          fill="#6b8196"
        >
          off by default · never raw records
        </text>
        <line
          x1={hostX + hostW + 2}
          y1={282}
          x2={598}
          y2={282}
          stroke="#8b5cf6"
          strokeDasharray="3 3"
          strokeWidth={1.5}
          markerEnd="url(#res-arrow-opt)"
        />
        <text
          x={580}
          y={276}
          textAnchor="end"
          fontFamily="ui-monospace, monospace"
          fontSize={9}
          fill="#c4b5fd"
        >
          opt-in
        </text>
      </svg>

      <p className="mt-3 font-mono text-[10px] leading-relaxed text-[#6b8196]">
        Solid emerald arrows never leave the host. The amber edge is
        the offline zip, delivered physically. The dashed violet
        edge is the only path that can touch a third-party endpoint
        and it carries only aggregate metrics, gated by operator
        consent per run.
      </p>
    </div>
  );
}
