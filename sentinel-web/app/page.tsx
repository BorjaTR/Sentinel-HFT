import Link from "next/link";
import {
  ArrowRight,
  Github,
  Cpu,
  ShieldCheck,
  Play,
  Scale,
  Brain,
} from "lucide-react";

// Two-audience landing. Trading desks (compliance + risk + ops) head
// left; hardware engineers head right. The third surface is the plain-
// English explainer that pre-answers "what is this thing".
//
// Deliberately no firm or vendor branding — the product talks to
// roles, not to a single named buyer.

const PRIMARY = {
  href: "/sentinel",
  label: "See a live drill",
  icon: Play,
};

const FEATURES = [
  {
    href: "/sentinel",
    icon: Play,
    title: "Live drills",
    audience: "Risk · compliance · ops",
    blurb:
      "Four scenarios every trading desk has lived through — toxic flow, market tearing itself apart, latency hunt, end-of-day packet. Each runs in under a minute and hands you back a report.",
    cta: "Run a drill",
    accent: "emerald",
  },
  {
    href: "/sentinel/regulations",
    icon: Scale,
    title: "Regulatory crosswalk",
    audience: "Compliance · legal · audit",
    blurb:
      "Every rule a regulator cites, mapped to the exact control that satisfies it. MiFID II, CFTC, FINRA, SEC, MAR, FINMA, MAS — 9 clauses across 4 jurisdictions, printable.",
    cta: "Open the rulebook",
    accent: "emerald",
  },
  {
    href: "/sentinel/audit",
    icon: ShieldCheck,
    title: "Audit verifier",
    audience: "Regulator · internal audit",
    blurb:
      "Every decision is sealed into a cryptographic chain. Change one byte anywhere and the seal points at the exact record that was touched. The regulator runs the verifier on their own laptop.",
    cta: "Verify a chain",
    accent: "emerald",
  },
  {
    href: "/sentinel/rca",
    icon: Brain,
    title: "Incident AI",
    audience: "Trading desk · compliance",
    blurb:
      "Nightly, a local AI writes the plain-English incident report. Live, three detectors rank alerts so the on-call sees the important one first. Runs on your hardware — no data leaves the building.",
    cta: "Read a nightly digest",
    accent: "emerald",
  },
  {
    href: "/sentinel/hardware",
    icon: Cpu,
    title: "Hardware design",
    audience: "FPGA · RTL · synthesis",
    blurb:
      "RTL contract, CDC story, reset discipline, audit log serialiser, pblock floorplan, Wave 0–4 verification methodology, Yosys + Vivado reports. Every block in the diagram links to the file.",
    cta: "Open the hardware view",
    accent: "sky",
  },
] as const;

const DIFFERENTIATORS = [
  {
    title: "Checks run in hardware, not in software",
    body: "Most trading firms run their safety checks inside the same software that runs the trading system. One bad release on a Friday afternoon and the checks are gone with it. Here they live in a separate hardware circuit — the trading software can't switch them off, bypass them, or accidentally reach around them.",
  },
  {
    title: "The audit log proves itself",
    body: "Every decision — approved or blocked — is sealed with a cryptographic seal that depends on the decision before it. Change one byte anywhere in the log and the seal breaks, pointing at the exact record that was touched. The math is public, the same kind Bitcoin uses, and the regulator runs the verifier on their own laptop. No vendor trust required.",
  },
  {
    title: "A local AI writes the incident report",
    body: "The moment an order gets blocked or a kill switch fires, a local AI produces a plain-English write-up — which desk, which rule, which orders, why, and what the regulator will want to see. It runs entirely on your own hardware. No trading data, no order book, no client information ever leaves the building.",
  },
  {
    title: "The stop button is a physical circuit",
    body: "Most kill switches are a button in a piece of software that depends on that same software still working. Here the stop is a latched hardware state — a person, or an automatic rule, trips the circuit and the door closes. The trading software cannot unlatch it. Only an operator with the right permission can reopen.",
  },
];

export default function Home() {
  return (
    <div className="min-h-screen bg-[#0a0e14] text-[#d5e0ea]">
      {/* Root landing intentionally has no head-hash banner -- that
          surface belongs inside the /sentinel/* shell (see
          app/sentinel/layout.tsx) where it's operationally
          meaningful.  Here it would just collide with the global
          top nav and confuse a business reader. */}

      {/* Hero */}
      <section className="relative overflow-hidden border-b border-[#1a232e]">
        <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/5 via-transparent to-sky-500/5" />
        <div className="relative mx-auto max-w-6xl px-6 py-20 md:py-28">
          <h1 className="max-w-4xl text-4xl font-bold leading-[1.1] tracking-tight text-white md:text-5xl lg:text-6xl">
            Sentinel is the{" "}
            <span className="text-emerald-400">safety layer</span>
            {" "}between your trading desk and the{" "}
            <span className="text-sky-400">market</span>.
          </h1>
          <p className="mt-6 max-w-3xl text-lg leading-relaxed text-[#9ab3c8]">
            Every desk already has one. What's different about this one:
          </p>
          <ul className="mt-5 max-w-3xl space-y-3 text-base leading-relaxed text-[#9ab3c8]">
            <li className="flex gap-3">
              <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" />
              <span>
                <span className="font-semibold text-white">Checks run in hardware</span>, not inside the trading software — a bad release can't switch them off.
              </span>
            </li>
            <li className="flex gap-3">
              <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" />
              <span>
                <span className="font-semibold text-white">The audit log proves itself.</span> The regulator verifies it on their own laptop, in minutes.
              </span>
            </li>
            <li className="flex gap-3">
              <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" />
              <span>
                <span className="font-semibold text-white">A local AI writes the incident report in plain English.</span> On your hardware. No data leaves the building.
              </span>
            </li>
            <li className="flex gap-3">
              <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" />
              <span>
                <span className="font-semibold text-white">The stop button is a physical circuit.</span> It works when the software doesn't.
              </span>
            </li>
          </ul>

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

      {/* Feature grid -- every surface is one click from the landing. */}
      <section className="border-b border-[#1a232e]">
        <div className="mx-auto max-w-6xl px-6 py-16">
          <div className="mb-2 font-mono text-[10px] uppercase tracking-wider text-[#9ab3c8]">
            What&apos;s inside
          </div>
          <h2 className="text-2xl font-bold text-white">
            Five surfaces. Every one clickable from here.
          </h2>
          <p className="mt-2 max-w-2xl text-sm text-[#9ab3c8]">
            The product is one pipeline, but it shows up to different people
            in different forms. Pick the one that answers your question.
          </p>

          <div className="mt-8 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map(({ href, icon: Icon, title, audience, blurb, cta, accent }) => {
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
                  className={`group relative flex flex-col overflow-hidden rounded-lg border border-[#1a232e] bg-[#0f151d] p-6 transition ${accentBorder} hover:bg-[#131c27]`}
                >
                  <div className="flex items-start justify-between">
                    <div className="rounded-md border border-[#1a232e] bg-[#0a0e14] p-2.5">
                      <Icon className={`h-5 w-5 ${accentText}`} />
                    </div>
                    <ArrowRight
                      className={`h-5 w-5 text-[#4d617a] transition group-hover:translate-x-0.5 ${accentArrow}`}
                    />
                  </div>
                  <h3 className="mt-5 text-lg font-semibold text-white">
                    {title}
                  </h3>
                  <div className="mt-1 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
                    {audience}
                  </div>
                  <p className="mt-3 flex-1 text-sm leading-relaxed text-[#9ab3c8]">
                    {blurb}
                  </p>
                  <div
                    className={`mt-5 inline-flex items-center gap-2 font-mono text-xs ${accentText}`}
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
              metric="< 1 μs"
              label="Per order, in hardware"
              detail="checked before it leaves the building"
            />
            <SpecCell
              metric="2 min"
              label="Audit verification"
              detail="the regulator runs it on their own laptop"
            />
            <SpecCell
              metric="9 clauses"
              label="7 regulators, 4 jurisdictions"
              detail="MiFID II · CFTC · FINRA · SEC · MAR · FINMA · MAS"
            />
            <SpecCell
              metric="0 bytes"
              label="Leave the building"
              detail="incident AI runs on your own hardware"
            />
          </div>
        </div>
      </section>

      <footer className="mx-auto max-w-6xl px-6 py-12 text-center">
        <p className="font-mono text-xs text-[#4d617a]">
          Sentinel-HFT v2.0 · synthetic fixtures only · no proprietary
          venue or firm data
        </p>
        <div className="mt-3 flex flex-wrap justify-center gap-x-5 gap-y-2 font-mono text-xs text-[#6b8196]">
          <Link href="/sentinel/about" className="hover:text-emerald-400">
            About
          </Link>
          <Link href="/sentinel" className="hover:text-emerald-400">
            Drills
          </Link>
          <Link href="/sentinel/regulations" className="hover:text-emerald-400">
            Regulations
          </Link>
          <Link href="/sentinel/audit" className="hover:text-emerald-400">
            Audit
          </Link>
          <Link href="/sentinel/rca" className="hover:text-emerald-400">
            Incident AI
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
