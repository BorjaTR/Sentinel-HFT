"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Shield, Zap, Activity, FileCheck, ArrowRight, ScrollText } from "lucide-react";
import { getDrillCatalog } from "@/lib/sentinel-api";
import type { DrillCatalog, DrillKind } from "@/lib/sentinel-types";

const DRILL_META: Record<DrillKind, {
  icon: typeof Shield;
  accent: string;
  title: string;
  story: string;
}> = {
  toxic_flow: {
    icon: Shield,
    accent: "from-rose-500/20 to-rose-500/5",
    title: "The sharp counterparty",
    story:
      "A fund quietly starts picking off your best market-makers. Can you say \u201cno\u201d before the loss lands? 30,000 orders, nearly half from informed counterparties \u2014 watch the system refuse them in microseconds.",
  },
  kill_drill: {
    icon: Zap,
    accent: "from-amber-500/20 to-amber-500/5",
    title: "The flash crash",
    story:
      "The market tears itself apart at 14:03:27. Does your desk keep trading, or does it stop? 24,000 orders run clean, then a volatility spike fires \u2014 watch the emergency stop latch and every subsequent order get blocked automatically.",
  },
  latency: {
    icon: Activity,
    accent: "from-emerald-500/20 to-emerald-500/5",
    title: "The slow leg",
    story:
      "You promise clients sub-microsecond decisions. On the worst trade of the day, where did the time actually go? 40,000 orders stopwatched at every stage \u2014 typical time, worst case, and anything slower than the SLA flagged red.",
  },
  daily_evidence: {
    icon: FileCheck,
    accent: "from-sky-500/20 to-sky-500/5",
    title: "The Friday afternoon regulator call",
    story:
      "The regulator phones at 16:00 and wants proof, today, that nothing was mistraded. A full simulated trading day \u2014 morning, midday, close \u2014 assembles the exact packet MiFID II, CFTC Reg AT and FINMA ask for, sealed so they can verify it without trusting us.",
  },
};

export default function SentinelOverviewPage() {
  const [catalog, setCatalog] = useState<DrillCatalog | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getDrillCatalog().then(setCatalog).catch((e) => setErr(String(e)));
  }, []);

  return (
    <div className="max-w-6xl">
      <header className="mb-8">
        <h1 className="font-mono text-xs uppercase tracking-widest text-[#4d617a]">
          Sentinel-HFT · Interactive demo
        </h1>
        <h2 className="mt-2 text-3xl font-semibold text-[#e4edf5]">
          Four scenarios. Each one a bad day for a trading desk.
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-relaxed text-[#9ab3c8]">
          Every trading firm fears the same four things: getting quietly
          picked off by smarter counterparties, losing millions in the
          first ten seconds of a market crash, being slower than the
          competition without knowing it, and missing the regulator's
          paperwork deadline. This demo reproduces each of those four
          days &mdash; live, on the same hardware the desk runs &mdash;
          and shows how the system catches it, stops it, and documents
          it. Pick a scenario. Each one takes under a minute.
        </p>
      </header>

      {err && (
        <div className="mb-6 rounded-md border border-rose-900/60 bg-rose-950/40 px-4 py-3 font-mono text-xs text-rose-200">
          backend unreachable at {process.env.NEXT_PUBLIC_SENTINEL_API_URL ?? "http://127.0.0.1:8000"}
          <div className="mt-1 text-rose-400/80">{err}</div>
          <div className="mt-1 text-rose-300/80">
            start it with:{" "}
            <span className="rounded bg-[#0a0e14] px-2 py-0.5">
              python3 -m sentinel_hft.server.app
            </span>
          </div>
        </div>
      )}

      <section className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {(Object.keys(DRILL_META) as DrillKind[]).map((kind) => {
          const meta = catalog?.[kind];
          const { icon: Icon, accent, story } = DRILL_META[kind];
          return (
            <Link
              key={kind}
              href={`/sentinel/${kind}`}
              className="group relative overflow-hidden rounded-lg border border-[#1a232e] bg-[#0f151d] p-5 transition hover:border-[#2a3a4c] hover:bg-[#131c27]"
            >
              <div
                className={`pointer-events-none absolute inset-0 bg-gradient-to-br ${accent} opacity-0 transition group-hover:opacity-100`}
              />
              <div className="relative flex items-start justify-between">
                <div>
                  <div className="mb-2 inline-flex items-center gap-2 rounded border border-[#1f2a38] bg-[#0a0e14] px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
                    <Icon className="h-3 w-3 text-emerald-400" />
                    {kind}
                  </div>
                  <h3 className="text-lg font-semibold text-[#e4edf5]">
                    {DRILL_META[kind].title}
                  </h3>
                  {meta?.name && (
                    <div className="mt-0.5 font-mono text-[10px] uppercase tracking-wider text-[#4d617a]">
                      {meta.name}
                    </div>
                  )}
                  <p className="mt-2 text-xs text-[#9ab3c8]">{story}</p>
                  {meta && (
                    <div className="mt-4 flex items-center gap-4 font-mono text-[10px] text-[#6b8196]">
                      <span>~{meta.expected_duration_s}s to run</span>
                      <span>{meta.default_ticks.toLocaleString()} orders replayed</span>
                    </div>
                  )}
                </div>
                <ArrowRight className="h-5 w-5 text-[#4d617a] transition group-hover:translate-x-0.5 group-hover:text-emerald-400" />
              </div>
            </Link>
          );
        })}
      </section>

      <section className="mt-10 grid grid-cols-1 gap-4 md:grid-cols-3">
        <Link
          href="/sentinel/audit"
          className="group rounded-lg border border-[#1a232e] bg-[#0f151d] p-5 transition hover:border-[#2a3a4c]"
        >
          <div className="mb-2 inline-flex items-center gap-2 rounded border border-[#1f2a38] bg-[#0a0e14] px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
            <FileCheck className="h-3 w-3 text-emerald-400" />
            tamper test
          </div>
          <h3 className="text-lg font-semibold text-[#e4edf5]">
            Don&rsquo;t trust the log. Try to break it.
          </h3>
          <p className="mt-2 text-xs text-[#9ab3c8]">
            Load one of today&rsquo;s sealed records, change any single
            byte, and watch the seal break &mdash; the checker points at
            the exact record that was touched. The math is public, the
            same kind used by Bitcoin, and you don&rsquo;t have to trust
            us to run it.
          </p>
        </Link>
        <Link
          href="/sentinel/regulations"
          className="group rounded-lg border border-[#1a232e] bg-[#0f151d] p-5 transition hover:border-[#2a3a4c]"
        >
          <div className="mb-2 inline-flex items-center gap-2 rounded border border-[#1f2a38] bg-[#0a0e14] px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
            <ScrollText className="h-3 w-3 text-emerald-400" />
            compliance
          </div>
          <h3 className="text-lg font-semibold text-[#e4edf5]">
            Every rule, every circuit, in one table
          </h3>
          <p className="mt-2 text-xs text-[#9ab3c8]">
            Nine clauses across seven regulators &mdash; MiFID II, CFTC,
            FINRA, SEC, MAR, FINMA, MAS &mdash; each sitting on the
            exact control that satisfies it. When a regulator asks
            &ldquo;show me the control for RTS 6&rdquo;, you point at
            one row. Live counters tick underneath as the drills run.
          </p>
        </Link>
        <div className="rounded-lg border border-[#1a232e] bg-[#0f151d] p-5">
          <div className="mb-2 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
            Release · 2026-04-21
          </div>
          <h3 className="text-base font-semibold text-[#e4edf5]">
            33 issues found &mdash; 33 fixed
          </h3>
          <p className="mt-2 text-xs text-[#9ab3c8]">
            We audited our own design in four passes and brought in a
            fresh reviewer to check the result. Every critical and
            high-severity finding is closed. Nothing left open above
            medium. Frozen as{" "}
            <span className="font-mono text-[#e4edf5]">v1.0.0-core-audit-closed</span>.
          </p>
        </div>
      </section>
    </div>
  );
}
