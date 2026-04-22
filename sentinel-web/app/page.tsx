import Link from "next/link";
import {
  Activity,
  Shield,
  Zap,
  FileCheck,
  ShieldCheck,
  Brain,
  Siren,
  Scale,
  ArrowRight,
  Github,
} from "lucide-react";

// Keyrock-focused landing page. Funnels straight into the /sentinel demo
// surface. Replaces the legacy SaaS-template Hero/Features/Stats/CTA stack
// (which still lives at /analyze, /demo, /pricing for anyone who needs it).

const PRIMARY_CTA = {
  href: "/sentinel",
  label: "Open the demo",
};

const DRILL_CARDS = [
  {
    href: "/sentinel/toxic_flow",
    icon: Shield,
    title: "Toxic-flow rejection",
    blurb:
      "Watch the risk gate quarantine adverse-selection bursts in real time, with a tamper-evident audit chain on every decision.",
    tag: "Use case 1",
  },
  {
    href: "/sentinel/kill_drill",
    icon: Zap,
    title: "Volatility kill-switch",
    blurb:
      "Replay a synthetic vol spike and confirm the kill-switch fires inside the documented wire-to-wire budget.",
    tag: "Use case 2",
  },
  {
    href: "/sentinel/latency",
    icon: Activity,
    title: "Latency attribution",
    blurb:
      "Per-stage nanosecond breakdown — parse, book, strategy, risk, egress — sourced straight from the FPGA trace.",
    tag: "Use case 3",
  },
  {
    href: "/sentinel/daily_evidence",
    icon: FileCheck,
    title: "Daily evidence pack",
    blurb:
      "One-click DORA / MiFID II evidence bundle: trace, audit chain, replay, signed manifest.",
    tag: "Use case 4",
  },
];

const PILLAR_CARDS = [
  {
    href: "/sentinel/regulations",
    icon: Scale,
    title: "Regulations crosswalk",
    blurb:
      "Nine-clause registry mapping MiFID II / CFTC Reg AT / FINRA 15c3-5 / SEC CAT / MAR / FINMA / MAS to the exact RTL or host artifact that implements it.",
    tag: "Compliance",
  },
  {
    href: "/sentinel/audit",
    icon: ShieldCheck,
    title: "Audit-chain verifier",
    blurb:
      "Upload an .aud file and watch the BLAKE2b hash chain re-validate; tamper a byte and watch it break with the exact failing record.",
    tag: "Integrity",
  },
  {
    href: "/sentinel/rca",
    icon: Brain,
    title: "Nightly RCA digest",
    blurb:
      "Local-LLM root-cause summary of the previous trading day — latency regressions, risk rejects, audit anomalies — no Claude API hard dependency.",
    tag: "AI ops",
  },
  {
    href: "/sentinel/triage",
    icon: Siren,
    title: "Streaming triage",
    blurb:
      "CUSUM + SPRT online detectors flag latency / reject-rate drift within tens of trades, with paged alerts and a precision/recall eval harness.",
    tag: "AI ops",
  },
];

export default function Home() {
  return (
    <div className="min-h-screen bg-[#0a0e14] text-[#d5e0ea]">
      {/* Hero */}
      <section className="relative overflow-hidden border-b border-[#1a232e]">
        <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/5 via-transparent to-sky-500/5" />
        <div className="relative mx-auto max-w-6xl px-6 py-24 md:py-32">
          <div className="flex items-center gap-3 mb-6">
            <div className="h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
            <span className="font-mono text-xs tracking-wider text-[#9ab3c8]">
              SENTINEL-HFT · v1.1.0-compliance-and-agents
            </span>
          </div>
          <h1 className="text-4xl md:text-6xl font-bold tracking-tight text-white max-w-4xl leading-[1.1]">
            FPGA-grade latency verification,{" "}
            <span className="text-emerald-400">tamper-evident audit</span>,{" "}
            <span className="text-sky-400">live compliance</span>, and{" "}
            <span className="text-amber-400">AI ops</span> — for HFT.
          </h1>
          <p className="mt-6 max-w-3xl text-lg text-[#9ab3c8] leading-relaxed">
            A working demo of the four Keyrock use cases on synthetic Hyperliquid
            and Deribit fixtures. Every drill produces a deterministic trace, a
            BLAKE2b-chained audit log, and an evidence bundle that maps to a
            specific regulatory clause.
          </p>
          <div className="mt-10 flex flex-wrap items-center gap-4">
            <Link
              href={PRIMARY_CTA.href}
              className="group inline-flex items-center gap-2 rounded-md bg-emerald-500 px-5 py-3 font-mono text-sm font-semibold text-[#0a0e14] transition hover:bg-emerald-400"
            >
              {PRIMARY_CTA.label}
              <ArrowRight className="h-4 w-4 transition group-hover:translate-x-0.5" />
            </Link>
            <Link
              href="/sentinel/regulations"
              className="inline-flex items-center gap-2 rounded-md border border-[#1f2a38] bg-[#0f151d] px-5 py-3 font-mono text-sm text-[#d5e0ea] transition hover:border-[#2a3848] hover:bg-[#131c27]"
            >
              <Scale className="h-4 w-4" />
              See the regulations crosswalk
            </Link>
            <a
              href="https://github.com/BorjaTR/Sentinel-HFT"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 rounded-md px-3 py-3 font-mono text-sm text-[#6b8196] transition hover:text-[#d5e0ea]"
            >
              <Github className="h-4 w-4" />
              GitHub
            </a>
          </div>
        </div>
      </section>

      {/* Drills */}
      <section className="border-b border-[#1a232e]">
        <div className="mx-auto max-w-6xl px-6 py-16">
          <div className="mb-2 font-mono text-[10px] uppercase tracking-wider text-emerald-400">
            Workstream 2 — interactive drills
          </div>
          <h2 className="text-2xl font-bold text-white">
            Four use cases, each backed by the real pipeline
          </h2>
          <p className="mt-2 max-w-2xl text-sm text-[#9ab3c8]">
            Click into any drill to fire it against the in-process FastAPI
            backend, watch the per-stage latency stream, and download the
            evidence bundle.
          </p>
          <div className="mt-8 grid grid-cols-1 gap-4 md:grid-cols-2">
            {DRILL_CARDS.map(({ href, icon: Icon, title, blurb, tag }) => (
              <Link
                key={href}
                href={href}
                className="group relative overflow-hidden rounded-lg border border-[#1a232e] bg-[#0f151d] p-6 transition hover:border-emerald-500/40 hover:bg-[#131c27]"
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="rounded-md border border-[#1a232e] bg-[#0a0e14] p-2">
                      <Icon className="h-4 w-4 text-emerald-400" />
                    </div>
                    <span className="font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
                      {tag}
                    </span>
                  </div>
                  <ArrowRight className="h-4 w-4 text-[#4d617a] transition group-hover:translate-x-0.5 group-hover:text-emerald-400" />
                </div>
                <h3 className="mt-4 text-lg font-semibold text-white">
                  {title}
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-[#9ab3c8]">
                  {blurb}
                </p>
              </Link>
            ))}
          </div>
        </div>
      </section>

      {/* Pillars */}
      <section className="border-b border-[#1a232e]">
        <div className="mx-auto max-w-6xl px-6 py-16">
          <div className="mb-2 font-mono text-[10px] uppercase tracking-wider text-sky-400">
            Workstreams 3 — 5
          </div>
          <h2 className="text-2xl font-bold text-white">
            Compliance, integrity, and AI ops
          </h2>
          <p className="mt-2 max-w-2xl text-sm text-[#9ab3c8]">
            The drills produce evidence; these surfaces turn the evidence into
            something a regulator, a CTO, or an on-call quant can act on.
          </p>
          <div className="mt-8 grid grid-cols-1 gap-4 md:grid-cols-2">
            {PILLAR_CARDS.map(({ href, icon: Icon, title, blurb, tag }) => (
              <Link
                key={href}
                href={href}
                className="group relative overflow-hidden rounded-lg border border-[#1a232e] bg-[#0f151d] p-6 transition hover:border-sky-500/40 hover:bg-[#131c27]"
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="rounded-md border border-[#1a232e] bg-[#0a0e14] p-2">
                      <Icon className="h-4 w-4 text-sky-400" />
                    </div>
                    <span className="font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
                      {tag}
                    </span>
                  </div>
                  <ArrowRight className="h-4 w-4 text-[#4d617a] transition group-hover:translate-x-0.5 group-hover:text-sky-400" />
                </div>
                <h3 className="mt-4 text-lg font-semibold text-white">
                  {title}
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-[#9ab3c8]">
                  {blurb}
                </p>
              </Link>
            ))}
          </div>
        </div>
      </section>

      {/* Spec strip */}
      <section className="border-b border-[#1a232e] bg-[#080b10]">
        <div className="mx-auto max-w-6xl px-6 py-12">
          <div className="grid grid-cols-2 gap-6 md:grid-cols-4">
            <SpecCell
              metric="322 MHz"
              label="CMAC clock"
              detail="100G Ethernet, U55C"
            />
            <SpecCell
              metric="100 MHz"
              label="Datapath"
              detail="parse → book → strategy → risk → egress"
            />
            <SpecCell
              metric="9 clauses"
              label="Compliance crosswalk"
              detail="MiFID II · CFTC · FINRA · SEC · MAR · FINMA · MAS"
            />
            <SpecCell
              metric="BLAKE2b"
              label="Audit chain"
              detail="tamper-evident, byte-level verifier"
            />
          </div>
        </div>
      </section>

      {/* Footer link to legacy */}
      <footer className="mx-auto max-w-6xl px-6 py-12 text-center">
        <p className="font-mono text-xs text-[#4d617a]">
          Sentinel-HFT v1.1.0-compliance-and-agents · Keyrock demo · synthetic
          fixtures only
        </p>
        <div className="mt-3 flex justify-center gap-6 font-mono text-xs text-[#6b8196]">
          <Link href="/sentinel" className="hover:text-emerald-400">
            Demo
          </Link>
          <Link href="/sentinel/regulations" className="hover:text-emerald-400">
            Regulations
          </Link>
          <Link href="/sentinel/rca" className="hover:text-emerald-400">
            RCA
          </Link>
          <Link href="/sentinel/triage" className="hover:text-emerald-400">
            Triage
          </Link>
          <a
            href="https://github.com/BorjaTR/Sentinel-HFT"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-emerald-400"
          >
            GitHub
          </a>
        </div>
      </footer>
    </div>
  );
}

function SpecCell({
  metric,
  label,
  detail,
}: {
  metric: string;
  label: string;
  detail: string;
}) {
  return (
    <div>
      <div className="font-mono text-2xl font-semibold text-white">{metric}</div>
      <div className="mt-1 font-mono text-[10px] uppercase tracking-wider text-[#9ab3c8]">
        {label}
      </div>
      <div className="mt-1 text-xs text-[#6b8196]">{detail}</div>
    </div>
  );
}
