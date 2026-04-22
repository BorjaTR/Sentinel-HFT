"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Shield, Zap, Activity, FileCheck, ArrowRight, ScrollText } from "lucide-react";
import { getDrillCatalog } from "@/lib/sentinel-api";
import type { DrillCatalog, DrillKind } from "@/lib/sentinel-types";

const DRILL_META: Record<DrillKind, {
  icon: typeof Shield;
  accent: string;
  story: string;
}> = {
  toxic_flow: {
    icon: Shield,
    accent: "from-rose-500/20 to-rose-500/5",
    story: "16 takers · 45% toxic mix · pre-gate guard rejects before risk check",
  },
  kill_drill: {
    icon: Zap,
    accent: "from-amber-500/20 to-amber-500/5",
    story: "Vol spike tick 9k · kill latches at intent 25.5k · every subsequent intent = KILL_SWITCH",
  },
  latency: {
    icon: Activity,
    accent: "from-emerald-500/20 to-emerald-500/5",
    story: "Clean 40k-tick baseline · per-stage p50/p99/p999 · SLO violation counter",
  },
  daily_evidence: {
    icon: FileCheck,
    accent: "from-sky-500/20 to-sky-500/5",
    story: "morning / midday / eod · three chains · combined DORA bundle",
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
          Tick-to-trade observability, risk controls, and tamper-evident audit
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-relaxed text-[#9ab3c8]">
          Four end-to-end drills replay a Hyperliquid tick stream through the
          real book &rarr; strategy &rarr; risk-gate &rarr; audit-log pipeline.
          Each drill emits a JSON + Markdown + HTML report plus a
          verifiable <span className="font-mono text-[#e4edf5]">.aud</span> chain.
          Pick a drill to run it live against your local backend.
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
                    {meta?.name ?? "\u00A0"}
                  </h3>
                  <p className="mt-2 text-xs text-[#9ab3c8]">{story}</p>
                  {meta && (
                    <div className="mt-4 flex items-center gap-4 font-mono text-[10px] text-[#6b8196]">
                      <span>~{meta.expected_duration_s}s run</span>
                      <span>default {meta.default_ticks.toLocaleString()} ticks</span>
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
            verifier
          </div>
          <h3 className="text-lg font-semibold text-[#e4edf5]">
            Audit-chain verifier
          </h3>
          <p className="mt-2 text-xs text-[#9ab3c8]">
            Upload any <span className="font-mono">.aud</span> file, walk the
            BLAKE2b-chained sequence, flip a byte on demand to prove
            tamper detection. The host verifier is the ground truth the
            RTL claims match.
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
            Regulations dashboard
          </h3>
          <p className="mt-2 text-xs text-[#9ab3c8]">
            MiFID II RTS 6, CFTC Reg AT, FINRA 15c3-5, SEC Rule 613, MAR Art.
            12, FINMA &amp; MAS. Static clause{"\u2192"}primitive crosswalk on top,
            live would-block + alert counters that tick during drill runs
            underneath.
          </p>
        </Link>
        <div className="rounded-lg border border-[#1a232e] bg-[#0f151d] p-5">
          <div className="mb-2 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
            Release · 2026-04-21
          </div>
          <h3 className="text-base font-semibold text-[#e4edf5]">
            Core audit closed
          </h3>
          <p className="mt-2 text-xs text-[#9ab3c8]">
            14 S0 + 19 S1 findings resolved across four waves. Fresh-eyes
            re-audit passed with zero new S0. Tag{" "}
            <span className="font-mono text-[#e4edf5]">v1.0.0-core-audit-closed</span>.
          </p>
        </div>
      </section>
    </div>
  );
}
