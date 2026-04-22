import Link from "next/link";
import {
  ArrowRight,
  Github,
  Briefcase,
  Cpu,
  ShieldCheck,
  ScrollText,
} from "lucide-react";
import { HeadHashBanner } from "@/components/sentinel/HeadHashBanner";

// Two-audience landing. Trading desks (compliance + risk + ops) head
// left; hardware engineers head right. The third surface is the plain-
// English explainer that pre-answers "what is this thing".
//
// Deliberately no firm or vendor branding — the product talks to
// roles, not to a single named buyer.

const PRIMARY = {
  href: "/sentinel/about",
  label: "What is this?",
  icon: ScrollText,
};

const AUDIENCES = [
  {
    href: "/sentinel",
    icon: Briefcase,
    title: "For trading desks",
    audience: "Risk officers · compliance · ops · quants",
    blurb:
      "Four scenarios every trading desk has lived through. Watch the system refuse orders from counterparties who would have picked you off; freeze the desk when the market tears itself apart; attach a stopwatch to every stage of every order; assemble the end-of-day packet a regulator would ask for. Each one takes under a minute and hands you back a report.",
    cta: "Open the drills",
    accent: "emerald",
  },
  {
    href: "/sentinel/hardware",
    icon: Cpu,
    title: "For hardware engineers",
    audience: "FPGA · RTL · CDC · timing · synthesis",
    blurb:
      "RTL contract, CDC story, reset discipline, audit log serialiser, pblock floorplan, Wave 0–4 verification methodology, and the synthesis evidence (Yosys + Vivado reports). Every block in the diagram links to the file that implements it.",
    cta: "Open the hardware view",
    accent: "sky",
  },
] as const;

const DIFFERENTIATORS = [
  {
    title: "Measured on the chip, not guessed after",
    body: "Every order carries its own stopwatch through the hardware — one reading per stage, written directly from the FPGA. Nothing is reconstructed after the fact, so the numbers can't drift or be massaged.",
  },
  {
    title: "A log nobody can quietly edit",
    body: "Every decision is stamped with a cryptographic seal that depends on the decision before it. Change one byte anywhere in the log and the seal breaks, pointing at the exact record that was touched. The math is public and independently re-checkable — the same kind used by Bitcoin.",
  },
  {
    title: "Runs on your own machines",
    body: "Every piece of the product — the scenarios, the plain-English incident explainer, the alert triage, the log verifier — runs on your own hardware. No trading data leaves the building. A local AI explainer is available if you want richer narratives, off by default.",
  },
  {
    title: "Pre-mapped to the rules regulators cite",
    body: "Nine specific clauses from seven regulators — EU, US, Swiss, Singapore — each mapped to the exact circuit or module that satisfies it. When a regulator asks \"show me the control for MiFID II RTS 6\", you point at one cell and open the file.",
  },
];

export default function Home() {
  return (
    <div className="min-h-screen bg-[#0a0e14] text-[#d5e0ea]">
      {/* Persistent banner — head hash + provenance pill. Always-on so
          you can see at a glance what run you're looking at. */}
      <div className="border-b border-[#1a232e] bg-[#080b10]">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-2">
          <div className="flex items-center gap-3">
            <div className="h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
            <span className="font-mono text-xs tracking-wider text-[#9ab3c8]">
              SENTINEL-HFT · v2.0
            </span>
          </div>
          <HeadHashBanner />
        </div>
      </div>

      {/* Hero */}
      <section className="relative overflow-hidden border-b border-[#1a232e]">
        <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/5 via-transparent to-sky-500/5" />
        <div className="relative mx-auto max-w-6xl px-6 py-20 md:py-28">
          <h1 className="max-w-4xl text-4xl font-bold leading-[1.1] tracking-tight text-white md:text-6xl">
            A trading desk's{" "}
            <span className="text-emerald-400">black box</span>
            {" "}—{" "}
            <span className="text-sky-400">in custom silicon</span>.
          </h1>
          <p className="mt-6 max-w-3xl text-lg leading-relaxed text-[#9ab3c8]">
            Every order, every decision, every safety check — measured
            in nanoseconds, logged in a form no one can quietly edit
            later, and pre-mapped to the rules your regulators cite.
            Two doors in: trading desks see four bad days and how the
            system catches each one. Hardware engineers see the circuits,
            the timing budgets, and the synthesis reports.
          </p>

          <div className="mt-10 flex flex-wrap items-center gap-3">
            <Link
              href={PRIMARY.href}
              className="group inline-flex items-center gap-2 rounded-md bg-emerald-500 px-5 py-3 font-mono text-sm font-semibold text-[#0a0e14] transition hover:bg-emerald-400"
            >
              <PRIMARY.icon className="h-4 w-4" />
              {PRIMARY.label}
              <ArrowRight className="h-4 w-4 transition group-hover:translate-x-0.5" />
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

      {/* Two-card audience switch */}
      <section className="border-b border-[#1a232e]">
        <div className="mx-auto max-w-6xl px-6 py-16">
          <div className="mb-2 font-mono text-[10px] uppercase tracking-wider text-[#9ab3c8]">
            Pick your path
          </div>
          <h2 className="text-2xl font-bold text-white">
            Two audiences. Same pipeline.
          </h2>
          <p className="mt-2 max-w-2xl text-sm text-[#9ab3c8]">
            The product is one piece — but the questions it answers
            split cleanly. We don't try to put both on one page.
          </p>

          <div className="mt-8 grid grid-cols-1 gap-4 md:grid-cols-2">
            {AUDIENCES.map(({ href, icon: Icon, title, audience, blurb, cta, accent }) => {
              const accentBorder =
                accent === "emerald"
                  ? "hover:border-emerald-500/40"
                  : "hover:border-sky-500/40";
              const accentText =
                accent === "emerald" ? "text-emerald-400" : "text-sky-400";
              const accentArrow =
                accent === "emerald"
                  ? "group-hover:text-emerald-400"
                  : "group-hover:text-sky-400";
              return (
                <Link
                  key={href}
                  href={href}
                  className={`group relative flex flex-col overflow-hidden rounded-lg border border-[#1a232e] bg-[#0f151d] p-7 transition ${accentBorder} hover:bg-[#131c27]`}
                >
                  <div className="flex items-start justify-between">
                    <div className="rounded-md border border-[#1a232e] bg-[#0a0e14] p-2.5">
                      <Icon className={`h-5 w-5 ${accentText}`} />
                    </div>
                    <ArrowRight
                      className={`h-5 w-5 text-[#4d617a] transition group-hover:translate-x-0.5 ${accentArrow}`}
                    />
                  </div>
                  <h3 className="mt-5 text-xl font-semibold text-white">
                    {title}
                  </h3>
                  <div className="mt-1 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
                    {audience}
                  </div>
                  <p className="mt-4 flex-1 text-sm leading-relaxed text-[#9ab3c8]">
                    {blurb}
                  </p>
                  <div
                    className={`mt-6 inline-flex items-center gap-2 font-mono text-xs ${accentText}`}
                  >
                    {cta}
                    <ArrowRight className="h-3 w-3" />
                  </div>
                </Link>
              );
            })}
          </div>
        </div>
      </section>

      {/* Differentiators */}
      <section className="border-b border-[#1a232e] bg-[#080b10]">
        <div className="mx-auto max-w-6xl px-6 py-16">
          <div className="mb-2 font-mono text-[10px] uppercase tracking-wider text-emerald-400">
            What makes it different
          </div>
          <h2 className="text-2xl font-bold text-white">
            Four claims you can verify yourself
          </h2>
          <div className="mt-8 grid grid-cols-1 gap-4 md:grid-cols-2">
            {DIFFERENTIATORS.map(({ title, body }) => (
              <div
                key={title}
                className="rounded-lg border border-[#1a232e] bg-[#0f151d] p-5"
              >
                <div className="flex items-center gap-2">
                  <ShieldCheck className="h-4 w-4 text-emerald-400" />
                  <h3 className="text-sm font-semibold text-white">{title}</h3>
                </div>
                <p className="mt-2 text-sm leading-relaxed text-[#9ab3c8]">
                  {body}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Spec strip */}
      <section className="border-b border-[#1a232e]">
        <div className="mx-auto max-w-6xl px-6 py-12">
          <div className="grid grid-cols-2 gap-6 md:grid-cols-4">
            <SpecCell
              metric="322 MHz"
              label="CMAC clock"
              detail="100G Ethernet, U55C"
            />
            <SpecCell
              metric="100 MHz"
              label="Order path"
              detail="market data in → decision → risk check → order out"
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

      <footer className="mx-auto max-w-6xl px-6 py-12 text-center">
        <p className="font-mono text-xs text-[#4d617a]">
          Sentinel-HFT v2.0 · synthetic fixtures only · no proprietary
          venue or firm data
        </p>
        <div className="mt-3 flex justify-center gap-6 font-mono text-xs text-[#6b8196]">
          <Link href="/sentinel/about" className="hover:text-emerald-400">
            About
          </Link>
          <Link href="/sentinel" className="hover:text-emerald-400">
            Trading desks
          </Link>
          <Link href="/sentinel/hardware" className="hover:text-emerald-400">
            Hardware
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
      <div className="font-mono text-2xl font-semibold text-white">
        {metric}
      </div>
      <div className="mt-1 font-mono text-[10px] uppercase tracking-wider text-[#9ab3c8]">
        {label}
      </div>
      <div className="mt-1 text-xs text-[#6b8196]">{detail}</div>
    </div>
  );
}
