"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Play,
  RotateCcw,
  ShieldCheck,
  FileText,
  CircuitBoard,
  AlertTriangle,
  Activity,
  X,
  Printer,
  Eye,
  Hash,
  ChevronRight,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  getComplianceCrosswalk,
  getComplianceSnapshotShape,
  getTriageAlerts,
  streamDrill,
} from "@/lib/sentinel-api";
import type {
  AlertChainView,
  ComplianceCrosswalkResponse,
  ComplianceEntry,
  ComplianceSnapshot,
  DrillKind,
  WsEvent,
  WsProgress,
} from "@/lib/sentinel-types";

const DRILL_CHOICES: Array<{ kind: DrillKind; label: string; note: string; ticks: number }> = [
  { kind: "toxic_flow", label: "toxic_flow", note: "16 takers · pre-gate guard", ticks: 1_500 },
  { kind: "kill_drill", label: "kill_drill", note: "vol spike + kill latch", ticks: 2_500 },
  { kind: "latency", label: "latency", note: "clean baseline · SLO run", ticks: 2_000 },
  { kind: "daily_evidence", label: "daily_evidence", note: "3 sessions · full DORA", ticks: 0 },
];

const LAYER_TONE: Record<string, string> = {
  RTL: "border-amber-500/30 bg-amber-500/5 text-amber-300",
  Host: "border-emerald-500/30 bg-emerald-500/5 text-emerald-300",
  Docs: "border-sky-500/30 bg-sky-500/5 text-sky-300",
};

const STATUS_TONE: Record<string, string> = {
  implemented: "text-emerald-400",
  reused: "text-sky-400",
  partial: "text-amber-400",
  stub: "text-rose-400",
};

const JURISDICTION_FLAG: Record<string, string> = {
  EU: "🇪🇺",
  US: "🇺🇸",
  CH: "🇨🇭",
  SG: "🇸🇬",
  Global: "🌐",
};

function fmtNum(x: number | undefined | null): string {
  if (x == null) return "–";
  return x.toLocaleString();
}

function fmtRatio(x: number | undefined | null): string {
  if (x == null || Number.isNaN(x)) return "–";
  return x.toFixed(2);
}

function shortHash(h: string | null | undefined): string {
  if (!h) return "–";
  const trimmed = h.replace(/^0x/, "");
  return trimmed.length <= 16 ? trimmed : `${trimmed.slice(0, 8)}…${trimmed.slice(-8)}`;
}

export default function RegulationsPage() {
  const [crosswalk, setCrosswalk] = useState<ComplianceCrosswalkResponse | null>(null);
  const [snapshot, setSnapshot] = useState<ComplianceSnapshot | null>(null);
  const [alertChain, setAlertChain] = useState<AlertChainView | null>(null);
  const [activeDrill, setActiveDrill] = useState<DrillKind | null>(null);
  const [progress, setProgress] = useState<WsProgress | null>(null);
  const [marAlertCount, setMarAlertCount] = useState<number>(0);
  const [lastTick, setLastTick] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [drawerEntry, setDrawerEntry] = useState<ComplianceEntry | null>(null);
  const streamRef = useRef<ReturnType<typeof streamDrill> | null>(null);

  useEffect(() => {
    Promise.all([
      getComplianceCrosswalk(),
      getComplianceSnapshotShape(),
      getTriageAlerts({ limit: 1 }),
    ])
      .then(([cw, shape, chain]) => {
        setCrosswalk(cw);
        setSnapshot(shape);
        setAlertChain(chain);
      })
      .catch((e) => setErr(String(e)));
    return () => {
      streamRef.current?.close();
    };
  }, []);

  const liveKeys = useMemo(
    () => new Set(crosswalk?.live_counter_keys ?? []),
    [crosswalk],
  );

  function resetRun() {
    setProgress(null);
    setMarAlertCount(0);
    setLastTick(null);
    setErr(null);
    // Reset the snapshot back to zero-shape so counters don't linger from
    // a previous drill.
    getComplianceSnapshotShape().then(setSnapshot).catch(() => {});
  }

  function startDrill(kind: DrillKind) {
    streamRef.current?.close();
    resetRun();
    setActiveDrill(kind);
    const preset = DRILL_CHOICES.find((d) => d.kind === kind);
    const overrides: Record<string, unknown> = {};
    if (preset && preset.ticks > 0 && kind !== "daily_evidence") {
      overrides.ticks = preset.ticks;
    }

    const handle = streamDrill(kind, overrides, {
      onEvent: (ev: WsEvent) => {
        if (ev.type === "progress") {
          setProgress(ev);
          setLastTick(ev.ticks_consumed);
          if (ev.compliance) {
            setSnapshot(ev.compliance);
            const a = ev.compliance.mar_abuse?.alerts;
            if (typeof a === "number") setMarAlertCount(a);
          }
        } else if (ev.type === "result") {
          setActiveDrill(null);
          // Refresh the audit chain tail so the Today's evidence card
          // reflects the just-finished drill's head hash.
          getTriageAlerts({ limit: 1 }).then(setAlertChain).catch(() => {});
        } else if (ev.type === "error") {
          setErr(ev.error);
          setActiveDrill(null);
        }
      },
      onClose: () => setActiveDrill(null),
      onError: () =>
        setErr("WebSocket error — is the FastAPI backend running on :8000?"),
    });
    streamRef.current = handle;
  }

  function stopDrill() {
    streamRef.current?.close();
    setActiveDrill(null);
  }

  // Group entries by jurisdiction for the crosswalk section.
  const grouped = useMemo(() => {
    if (!crosswalk) return [];
    const bag = new Map<string, ComplianceEntry[]>();
    for (const e of crosswalk.entries) {
      const k = e.jurisdiction;
      if (!bag.has(k)) bag.set(k, []);
      bag.get(k)!.push(e);
    }
    return Array.from(bag.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [crosswalk]);

  return (
    <div className="max-w-6xl pt-24 pb-10 print:pt-6 print:pb-6">
      {/* Header */}
      <header className="mb-8 print:mb-4">
        <div className="no-print">
          <Link
            href="/sentinel"
            className="mb-3 inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-widest text-[#4d617a] transition hover:text-emerald-400"
          >
            <ArrowLeft className="h-3 w-3" /> sentinel / overview
          </Link>
        </div>
        <div className="flex items-start justify-between gap-6">
          <div className="flex-1">
            <h1 className="font-mono text-xs uppercase tracking-widest text-[#4d617a]">
              Workstream 3 · Regulation crosswalk · Trading-desk / compliance view
            </h1>
            <h2 className="mt-2 text-3xl font-semibold text-[#e4edf5]">
              What each regulation does, and what&apos;s ticking up right now
            </h2>
            <p className="mt-3 max-w-3xl text-sm leading-relaxed text-[#9ab3c8]">
              Static map of 9 regulation clauses to the primitives Sentinel-HFT
              ships (top). Live observational counters from the host compliance
              stack (bottom) &mdash; pick a drill and watch the counters move.
              The stack never modifies a drill&apos;s outcome; it only observes.
            </p>
          </div>
          <RegulatorExportButton />
        </div>
      </header>

      {err && (
        <div className="mb-6 rounded-md border border-rose-900/60 bg-rose-950/40 px-4 py-3 font-mono text-xs text-rose-200 no-print">
          {err}
          <div className="mt-1 text-rose-400/80">
            start backend with:{" "}
            <span className="rounded bg-[#0a0e14] px-2 py-0.5">
              python3 -m sentinel_hft.server.app
            </span>
          </div>
        </div>
      )}

      {/* ================== Cross-jurisdictional rollup ================== */}
      <CrossJurisdictionRollup crosswalk={crosswalk} />

      {/* ================== Today's Evidence Header Card ================== */}
      <TodayEvidenceCard
        snapshot={snapshot}
        alertChain={alertChain}
        progress={progress}
      />

      {/* ================== Live Counters ================== */}
      <section className="mb-10 no-print">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#4d617a]">
              Live
            </div>
            <h3 className="mt-1 text-lg font-semibold text-[#e4edf5]">
              Observational counters
            </h3>
          </div>
          <div className="flex items-center gap-2">
            {activeDrill ? (
              <Button
                onClick={stopDrill}
                size="sm"
                variant="outline"
                className="border-rose-500/40 bg-transparent font-mono text-xs text-rose-300 hover:bg-rose-500/10"
              >
                stop {activeDrill}
              </Button>
            ) : (
              <Button
                onClick={resetRun}
                size="sm"
                variant="outline"
                className="border-[#1f2a38] bg-transparent font-mono text-xs text-[#9ab3c8] hover:bg-[#131c27] hover:text-[#e4edf5]"
              >
                <RotateCcw className="mr-1 h-3 w-3" /> reset
              </Button>
            )}
          </div>
        </div>

        {/* Drill chooser */}
        <div className="mb-4 flex flex-wrap gap-2">
          <span className="self-center font-mono text-[10px] uppercase tracking-wider text-[#4d617a]">
            drive counters with →
          </span>
          {DRILL_CHOICES.map((d) => {
            const isActive = activeDrill === d.kind;
            return (
              <button
                key={d.kind}
                type="button"
                disabled={!!activeDrill && !isActive}
                onClick={() => startDrill(d.kind)}
                className={`group inline-flex items-center gap-2 rounded border px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider transition disabled:cursor-not-allowed disabled:opacity-40 ${
                  isActive
                    ? "border-emerald-500/60 bg-emerald-500/10 text-emerald-300"
                    : "border-[#1f2a38] bg-[#0a0e14] text-[#9ab3c8] hover:border-[#2a3a4c] hover:text-[#e4edf5]"
                }`}
              >
                <Play className="h-2.5 w-2.5" />
                {d.label}
                <span className="normal-case text-[#4d617a] group-hover:text-[#6b8196]">
                  {d.note}
                </span>
              </button>
            );
          })}
        </div>

        {/* Progress strip */}
        {progress && (
          <div className="mb-4">
            <div className="h-1 overflow-hidden rounded-full bg-[#0a0e14]">
              <div
                className="h-full bg-gradient-to-r from-emerald-500 to-cyan-400 transition-all"
                style={{ width: `${Math.round(progress.progress * 100)}%` }}
              />
            </div>
            <div className="mt-1 flex items-center justify-between font-mono text-[10px] text-[#6b8196]">
              <span>
                tick {fmtNum(progress.ticks_consumed)} /{" "}
                {fmtNum(progress.ticks_target)}
              </span>
              <span>
                intents {fmtNum(progress.intents_generated)} · decisions{" "}
                {fmtNum(progress.decisions_logged)} · passed{" "}
                <span className="text-emerald-400">
                  {fmtNum(progress.passed)}
                </span>
              </span>
              <span>{progress.elapsed_s.toFixed(1)}s</span>
            </div>
          </div>
        )}

        {/* Counter tile grid */}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          <MifidOtrTile
            snap={snapshot?.mifid_otr}
            live={liveKeys.has("mifid_otr")}
          />
          <SelfTradeTile
            snap={snapshot?.cftc_self_trade}
            live={liveKeys.has("cftc_self_trade")}
          />
          <FatFingerTile
            snap={snapshot?.finra_fat_finger}
            live={liveKeys.has("finra_fat_finger")}
          />
          <CatTile
            snap={snapshot?.sec_cat}
            live={liveKeys.has("sec_cat")}
          />
        </div>

        {/* MAR alerts strip */}
        <div className="mt-4">
          <MarAlertsStrip
            snap={snapshot?.mar_abuse}
            alertCount={marAlertCount}
          />
        </div>
      </section>

      {/* ================== Static Crosswalk ================== */}
      <section>
        <div className="mb-3">
          <div className="font-mono text-[10px] uppercase tracking-widest text-[#4d617a]">
            Static
          </div>
          <h3 className="mt-1 text-lg font-semibold text-[#e4edf5]">
            Regulation → primitive → artefact
          </h3>
          <p className="mt-1 text-xs text-[#6b8196]">
            Ordered by jurisdiction. Source of truth:{" "}
            <span className="font-mono text-[#9ab3c8]">
              sentinel_hft/compliance/crosswalk.py
            </span>
            . Click any row for the exact code path and artefact that
            satisfies that clause.
          </p>
        </div>

        <div className="space-y-6">
          {grouped.map(([juris, entries]) => (
            <div key={juris}>
              <div className="mb-2 flex items-center gap-2 border-b border-[#1a232e] pb-1 font-mono text-[10px] uppercase tracking-widest text-[#6b8196]">
                <span className="text-base leading-none">
                  {JURISDICTION_FLAG[juris] ?? "🌐"}
                </span>
                {juris} · {entries.length} clause{entries.length === 1 ? "" : "s"}
              </div>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2 print:grid-cols-1">
                {entries.map((e) => (
                  <CrosswalkRow
                    key={e.key}
                    entry={e}
                    onOpenEvidence={() => setDrawerEntry(e)}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Legend */}
      <section className="mt-10 grid grid-cols-1 gap-3 md:grid-cols-3">
        <Legend
          icon={<CircuitBoard className="h-3 w-3 text-amber-300" />}
          label="RTL"
          text="Synthesizable reference implementation under rtl/. Deterministic at line rate."
        />
        <Legend
          icon={<ShieldCheck className="h-3 w-3 text-emerald-300" />}
          label="Host"
          text="Python observational module. Never flips a gate decision; counters only."
        />
        <Legend
          icon={<FileText className="h-3 w-3 text-sky-300" />}
          label="Docs"
          text="Envelope formatter (resilience log, CAT). Written once per session."
        />
      </section>

      {/* Evidence drawer */}
      {drawerEntry && (
        <EvidenceDrawer
          entry={drawerEntry}
          snapshot={snapshot}
          alertChain={alertChain}
          onClose={() => setDrawerEntry(null)}
        />
      )}

      {/* Print-only footer so the exported PDF carries the run window
          and the audit anchor inline, not just as a header card. */}
      <section className="mt-8 hidden border-t border-[#1a232e] pt-4 print:block">
        <div className="font-mono text-[10px] text-[#6b8196]">
          Exported {new Date().toISOString()} · head-hash{" "}
          {shortHash(alertChain?.head_hash_lo)} · chain{" "}
          {alertChain?.chain_ok === false ? "BROKEN" : "ok"} ·{" "}
          {alertChain?.n_records ?? 0} records · Sentinel-HFT regulator
          bundle.
        </div>
      </section>

      {/* Print styling: hide noise, tighten margins, keep rows intact. */}
      <style jsx global>{`
        @media print {
          html, body {
            background: white !important;
            color: black !important;
          }
          .no-print { display: none !important; }
          .print\\:block { display: block !important; }
          .print\\:grid-cols-1 { grid-template-columns: repeat(1, minmax(0, 1fr)) !important; }
          .print\\:pt-6 { padding-top: 1.5rem !important; }
          .print\\:pb-6 { padding-bottom: 1.5rem !important; }
          .print\\:mb-4 { margin-bottom: 1rem !important; }
          [class*="border-"] { border-color: #111 !important; }
          [class*="bg-[#0f151d]"], [class*="bg-[#0a0e14]"] {
            background: white !important;
          }
          [class*="text-[#e4edf5]"] { color: black !important; }
          [class*="text-[#9ab3c8]"] { color: #222 !important; }
          [class*="text-[#6b8196]"] { color: #444 !important; }
          [class*="text-[#4d617a]"] { color: #666 !important; }
          a { text-decoration: none !important; color: black !important; }
        }
      `}</style>
    </div>
  );
}

// =====================================================================
// Cross-jurisdictional rollup — one badge per regulator, clause coverage %
// =====================================================================

function CrossJurisdictionRollup({
  crosswalk,
}: {
  crosswalk: ComplianceCrosswalkResponse | null;
}) {
  // Collapse the crosswalk into a per-jurisdiction summary:
  //   - total clauses mapped
  //   - implemented + reused count (both are "shipped" states)
  //   - partial / stub count (the gap)
  //   - live counter coverage
  //
  // Coverage % is reported as ``(implemented + reused) / total`` because
  // those two statuses both mean "the primitive is in the build today".
  // ``partial`` and ``stub`` count as NOT-yet-covered.
  type Row = {
    jurisdiction: string;
    total: number;
    covered: number;
    partial: number;
    stub: number;
    live: number;
  };

  // Canonical display order. The V2 plan mentions UK; it isn't in the
  // current crosswalk but we keep the slot so the badge grid visibly
  // communicates "not yet mapped" instead of silently dropping it.
  const ORDER: Array<{ key: string; label: string }> = [
    { key: "EU", label: "EU · MiFID II / MAR" },
    { key: "US", label: "US · SEC / CFTC / FINRA" },
    { key: "UK", label: "UK · FCA" },
    { key: "CH", label: "CH · FINMA" },
    { key: "SG", label: "SG · MAS" },
    { key: "Global", label: "Global · DORA-shaped" },
  ];

  const rows: Row[] = ORDER.map(({ key }) => {
    const entries =
      crosswalk?.entries.filter((e) => e.jurisdiction === key) ?? [];
    const covered = entries.filter(
      (e) => e.status === "implemented" || e.status === "reused",
    ).length;
    const partial = entries.filter((e) => e.status === "partial").length;
    const stub = entries.filter((e) => e.status === "stub").length;
    const live = entries.filter((e) => e.live_counter).length;
    return {
      jurisdiction: key,
      total: entries.length,
      covered,
      partial,
      stub,
      live,
    };
  });

  const totalEntries = crosswalk?.entries.length ?? 0;
  const totalCovered =
    crosswalk?.entries.filter(
      (e) => e.status === "implemented" || e.status === "reused",
    ).length ?? 0;
  const totalLive = crosswalk?.live_counter_keys.length ?? 0;
  const globalPct =
    totalEntries > 0 ? Math.round((100 * totalCovered) / totalEntries) : 0;

  return (
    <section className="mb-8 no-print">
      <div className="mb-3 flex items-end justify-between">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-[#4d617a]">
            Cross-jurisdictional rollup
          </div>
          <h3 className="mt-1 text-lg font-semibold text-[#e4edf5]">
            Clause coverage by regulator
          </h3>
          <p className="mt-1 max-w-3xl text-xs text-[#6b8196]">
            One badge per regulator. Coverage % = (implemented + reused) /
            total clauses mapped. ``partial`` and ``stub`` count against
            coverage until they ship. Missing regulators show the slot
            with a zero count so the gap is visible, not hidden.
          </p>
        </div>
        <div className="text-right font-mono text-[10px] text-[#6b8196]">
          <div>
            global:{" "}
            <span className="text-[#e4edf5]">
              {totalCovered}/{totalEntries}
            </span>{" "}
            · {globalPct}%
          </div>
          <div>
            live counters:{" "}
            <span className="text-emerald-300">{totalLive}</span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {rows.map((row) => (
          <JurisdictionBadge key={row.jurisdiction} row={row} />
        ))}
      </div>
    </section>
  );
}

function JurisdictionBadge({
  row,
}: {
  row: {
    jurisdiction: string;
    total: number;
    covered: number;
    partial: number;
    stub: number;
    live: number;
  };
}) {
  const mapped = row.total > 0;
  const pct = mapped ? Math.round((100 * row.covered) / row.total) : 0;
  const hasGap = row.partial + row.stub > 0;
  const fullyCovered = mapped && row.covered === row.total && !hasGap;

  const border = !mapped
    ? "border-[#1f2a38]"
    : fullyCovered
      ? "border-emerald-500/40"
      : hasGap
        ? "border-amber-500/40"
        : "border-sky-500/30";
  const bg = !mapped
    ? "bg-[#0a0e14]"
    : fullyCovered
      ? "bg-emerald-500/5"
      : hasGap
        ? "bg-amber-500/5"
        : "bg-sky-500/5";
  const pctColor = !mapped
    ? "text-[#4d617a]"
    : fullyCovered
      ? "text-emerald-300"
      : hasGap
        ? "text-amber-300"
        : "text-sky-300";

  return (
    <div className={`rounded-md border px-3 py-3 ${border} ${bg}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-lg leading-none">
            {JURISDICTION_FLAG[row.jurisdiction] ?? "🌐"}
          </span>
          <span className="font-mono text-xs font-semibold text-[#e4edf5]">
            {row.jurisdiction}
          </span>
        </div>
        <span className={`font-mono text-lg font-semibold tabular-nums ${pctColor}`}>
          {mapped ? `${pct}%` : "—"}
        </span>
      </div>

      {/* progress bar */}
      <div className="mt-2 h-1 overflow-hidden rounded-full bg-[#0a0e14]">
        <div
          className={`h-full transition-all ${
            fullyCovered
              ? "bg-emerald-500"
              : hasGap
                ? "bg-amber-500"
                : "bg-sky-500"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>

      <div className="mt-2 font-mono text-[9px] uppercase tracking-wider text-[#6b8196]">
        {mapped ? (
          <>
            <span className="text-[#e4edf5]">{row.covered}</span>
            {" / "}
            <span>{row.total}</span> clauses
          </>
        ) : (
          <span className="text-[#4d617a]">not yet mapped</span>
        )}
      </div>
      <div className="mt-0.5 flex flex-wrap gap-1.5 font-mono text-[9px]">
        {row.live > 0 && (
          <span className="rounded border border-emerald-500/30 bg-emerald-500/5 px-1.5 py-0 text-emerald-300">
            {row.live} live
          </span>
        )}
        {row.partial > 0 && (
          <span className="rounded border border-amber-500/30 bg-amber-500/5 px-1.5 py-0 text-amber-300">
            {row.partial} partial
          </span>
        )}
        {row.stub > 0 && (
          <span className="rounded border border-rose-500/30 bg-rose-500/5 px-1.5 py-0 text-rose-300">
            {row.stub} stub
          </span>
        )}
      </div>
    </div>
  );
}

// =====================================================================
// Today's Evidence — the "what a regulator sees now" header card
// =====================================================================

function TodayEvidenceCard({
  snapshot,
  alertChain,
  progress,
}: {
  snapshot: ComplianceSnapshot | null;
  alertChain: AlertChainView | null;
  progress: WsProgress | null;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const mifid = snapshot?.mifid_otr;
  const selfTrade = snapshot?.cftc_self_trade;
  const fat = snapshot?.finra_fat_finger;
  const cat = snapshot?.sec_cat;
  const mar = snapshot?.mar_abuse;

  const orders = Number(mifid?.total_orders ?? 0);
  const selfRejects = Number(selfTrade?.rejected ?? 0);
  const fatRejects = Number(fat?.rejected ?? 0);
  const catEmitted = Number(cat?.total_records ?? 0);
  const marAlerts = Number(mar?.alerts ?? 0);

  const hasSignal =
    orders > 0 ||
    selfRejects > 0 ||
    fatRejects > 0 ||
    catEmitted > 0 ||
    marAlerts > 0;
  const chainOk = alertChain?.chain_ok ?? true;

  return (
    <Card className="mb-8 border-emerald-500/20 bg-gradient-to-br from-[#0f151d] to-[#0a1014] print:border-[#111] print:bg-white">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="font-mono text-[10px] uppercase tracking-widest text-emerald-300/80">
              Today&apos;s evidence · {today}
            </CardTitle>
            <div className="mt-1 text-sm text-[#9ab3c8]">
              Live compliance counters + the latest audit-chain head hash.
              This is what a regulator would see if they pulled the bundle
              right now.
            </div>
          </div>
          <div className="flex items-center gap-2 font-mono text-[9px] uppercase tracking-wider">
            {progress ? (
              <span className="inline-flex items-center gap-1 rounded border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-emerald-300">
                <span className="relative flex h-1.5 w-1.5">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
                  <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
                </span>
                drill running
              </span>
            ) : hasSignal ? (
              <span className="inline-flex items-center gap-1 rounded border border-sky-500/40 bg-sky-500/10 px-2 py-1 text-sky-300">
                drill complete
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded border border-[#1f2a38] bg-[#0a0e14] px-2 py-1 text-[#6b8196]">
                no events yet today
              </span>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <EvidenceStat
            label="MiFID OTR · orders"
            value={orders}
            sub={`ratio ${fmtRatio(Number(mifid?.global_ratio ?? 0))}`}
            warn={Boolean(mifid?.would_trip)}
          />
          <EvidenceStat
            label="CFTC self-trade · rejects"
            value={selfRejects}
            sub={`of ${fmtNum(Number(selfTrade?.checked ?? 0))} checked`}
            warn={selfRejects > 0}
          />
          <EvidenceStat
            label="FINRA fat-finger · rejects"
            value={fatRejects}
            sub={`worst ${fmtNum(Number(fat?.worst_deviation_bps ?? 0))} bps`}
            warn={fatRejects > 0}
          />
          <EvidenceStat
            label="SEC CAT · records"
            value={catEmitted}
            sub="Phase 2e feed"
          />
          <EvidenceStat
            label="MAR spoofing · alerts"
            value={marAlerts}
            sub={marAlerts > 0 ? "action required" : "clean"}
            warn={marAlerts > 0}
          />
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-md border border-[#1a232e] bg-[#0a0e14] px-3 py-2 font-mono text-[10px] text-[#9ab3c8] print:bg-white">
          <div className="flex items-center gap-2">
            <Hash className="h-3 w-3 text-emerald-400" />
            <span className="text-[#6b8196]">audit head hash ·</span>
            <span className="text-emerald-300">
              {shortHash(alertChain?.head_hash_lo)}
            </span>
            {alertChain?.head_hash_lo && (
              <span className="text-[#4d617a]">({alertChain.head_hash_lo.length * 4}-bit lo half)</span>
            )}
          </div>
          <div className="flex items-center gap-3">
            <span className="text-[#6b8196]">
              records{" "}
              <span className="text-[#e4edf5]">
                {fmtNum(alertChain?.n_records ?? 0)}
              </span>
            </span>
            <span className="text-[#6b8196]">·</span>
            <span
              className={
                chainOk
                  ? "text-emerald-400"
                  : "text-rose-400"
              }
            >
              chain {chainOk ? "ok" : "BROKEN"}
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function EvidenceStat({
  label,
  value,
  sub,
  warn,
}: {
  label: string;
  value: number;
  sub?: string;
  warn?: boolean;
}) {
  return (
    <div
      className={`rounded-md border px-3 py-2 ${
        warn
          ? "border-rose-500/40 bg-rose-500/5"
          : "border-[#1a232e] bg-[#0a0e14] print:bg-white"
      }`}
    >
      <div className="font-mono text-[9px] uppercase tracking-wider text-[#6b8196]">
        {label}
      </div>
      <div
        className={`mt-1 font-mono text-xl font-semibold tabular-nums ${
          warn ? "text-rose-300" : "text-[#e4edf5]"
        }`}
      >
        {fmtNum(value)}
      </div>
      {sub && (
        <div className="mt-0.5 font-mono text-[9px] text-[#4d617a]">{sub}</div>
      )}
    </div>
  );
}

// =====================================================================
// Regulator-export print button
// =====================================================================

function RegulatorExportButton() {
  return (
    <Button
      onClick={() => {
        if (typeof window !== "undefined") {
          window.print();
        }
      }}
      size="sm"
      variant="outline"
      className="no-print border-emerald-500/40 bg-emerald-500/5 font-mono text-xs text-emerald-300 hover:bg-emerald-500/10"
      title="Print the crosswalk + today's evidence + audit head hash as a single PDF. Use your browser's 'Save as PDF' destination."
    >
      <Printer className="mr-1.5 h-3 w-3" />
      Regulator export
    </Button>
  );
}

// =====================================================================
// Evidence drawer — click a crosswalk row to see the exact code path
// =====================================================================

type ArtifactSlice = { path: string; kind: "RTL" | "Host" | "Docs" | "Config" };

function splitArtifact(entry: ComplianceEntry): ArtifactSlice[] {
  // The artifact field may be a single path or a ``+`` joined list.
  // Classify each chunk by extension so the drawer can render a
  // file-icon and a sensible badge.
  const raw = entry.artifact
    .split("+")
    .map((s) => s.trim())
    .filter(Boolean);
  return raw.map((path) => {
    if (path.endsWith(".sv") || path.endsWith(".v")) {
      return { path, kind: "RTL" } as const;
    }
    if (path.endsWith(".py")) {
      return { path, kind: "Host" } as const;
    }
    if (path.endsWith(".md") || path.endsWith(".json") || path.endsWith(".yaml")) {
      return { path, kind: "Docs" } as const;
    }
    return { path, kind: "Config" } as const;
  });
}

function EvidenceDrawer({
  entry,
  snapshot,
  alertChain,
  onClose,
}: {
  entry: ComplianceEntry;
  snapshot: ComplianceSnapshot | null;
  alertChain: AlertChainView | null;
  onClose: () => void;
}) {
  const artefacts = splitArtifact(entry);
  const signals = entry.audit_signal
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  // Closable via Escape.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const liveValue = liveValueForEntry(entry.key, snapshot);

  return (
    <div
      className="fixed inset-0 z-50 flex items-stretch justify-end bg-black/60 backdrop-blur-sm no-print"
      onClick={onClose}
    >
      <aside
        className="h-full w-full max-w-xl overflow-y-auto border-l border-[#1a232e] bg-[#0f151d] p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#4d617a]">
              Evidence · {entry.jurisdiction}
            </div>
            <h3 className="mt-1 text-lg font-semibold text-[#e4edf5]">
              {entry.regulation}
            </h3>
            <div className="mt-0.5 font-mono text-[11px] text-[#6b8196]">
              {entry.clause}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-[#1f2a38] p-1.5 text-[#6b8196] transition hover:border-[#2a3a4c] hover:text-[#e4edf5]"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <p className="mb-5 text-sm leading-relaxed text-[#9ab3c8]">
          {entry.primitive}
        </p>

        <DrawerSection title="What satisfies this clause">
          <div className="space-y-2">
            {artefacts.map((a) => (
              <div
                key={a.path}
                className="flex items-start gap-2 rounded-md border border-[#1a232e] bg-[#0a0e14] px-3 py-2"
              >
                <span
                  className={`mt-0.5 inline-flex shrink-0 items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider ${
                    LAYER_TONE[a.kind] ?? LAYER_TONE.Host
                  }`}
                >
                  {a.kind}
                </span>
                <code className="break-all font-mono text-[11px] text-[#e4edf5]">
                  {a.path}
                </code>
              </div>
            ))}
            {artefacts.length === 0 && (
              <div className="rounded-md border border-[#1a232e] bg-[#0a0e14] px-3 py-2 font-mono text-[11px] text-[#6b8196]">
                (no concrete artefact recorded)
              </div>
            )}
          </div>
        </DrawerSection>

        <DrawerSection title="What the audit log records">
          <ul className="space-y-1">
            {signals.map((s) => (
              <li
                key={s}
                className="flex items-start gap-2 font-mono text-[11px] text-[#9ab3c8]"
              >
                <ChevronRight className="mt-0.5 h-3 w-3 shrink-0 text-[#4d617a]" />
                <code className="text-sky-300">{s}</code>
              </li>
            ))}
          </ul>
        </DrawerSection>

        {entry.live_counter && (
          <DrawerSection title="Today's value">
            <div className="rounded-md border border-[#1a232e] bg-[#0a0e14] p-3">
              {liveValue ? (
                <div className="space-y-1 font-mono text-[11px] text-[#9ab3c8]">
                  {Object.entries(liveValue).map(([k, v]) => (
                    <div key={k} className="flex items-center gap-3">
                      <span className="w-40 shrink-0 text-[#4d617a]">
                        {k}
                      </span>
                      <span className="text-[#e4edf5]">
                        {formatVal(v)}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="font-mono text-[11px] text-[#6b8196]">
                  no live counters published yet — run a drill to populate.
                </div>
              )}
            </div>
          </DrawerSection>
        )}

        <DrawerSection title="Audit chain anchor">
          <div className="rounded-md border border-[#1a232e] bg-[#0a0e14] p-3 font-mono text-[11px]">
            <div className="flex items-center gap-2">
              <span className="text-[#4d617a]">head hash</span>
              <span className="text-emerald-300">
                {shortHash(alertChain?.head_hash_lo)}
              </span>
            </div>
            <div className="mt-1 flex items-center gap-2">
              <span className="text-[#4d617a]">records</span>
              <span className="text-[#e4edf5]">
                {fmtNum(alertChain?.n_records ?? 0)}
              </span>
            </div>
            <div className="mt-1 flex items-center gap-2">
              <span className="text-[#4d617a]">chain</span>
              <span
                className={
                  (alertChain?.chain_ok ?? true)
                    ? "text-emerald-400"
                    : "text-rose-400"
                }
              >
                {(alertChain?.chain_ok ?? true) ? "ok" : "BROKEN"}
              </span>
            </div>
          </div>
        </DrawerSection>

        <DrawerSection title="Traceability">
          <div className="space-y-1 font-mono text-[11px] text-[#9ab3c8]">
            <Row label="crosswalk key" value={entry.key} mono />
            <Row label="layer" value={entry.layer} />
            <Row label="live counter" value={entry.live_counter ? "yes" : "no"} />
            <Row label="status">
              <span className={STATUS_TONE[entry.status] ?? "text-[#9ab3c8]"}>
                {entry.status}
              </span>
            </Row>
            <Row
              label="source-of-truth"
              value="sentinel_hft/compliance/crosswalk.py"
              mono
            />
          </div>
        </DrawerSection>
      </aside>
    </div>
  );
}

function DrawerSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-5">
      <div className="mb-2 flex items-center gap-2 font-mono text-[9px] uppercase tracking-widest text-[#4d617a]">
        <Eye className="h-2.5 w-2.5" /> {title}
      </div>
      {children}
    </div>
  );
}

function Row({
  label,
  value,
  mono,
  children,
}: {
  label: string;
  value?: string;
  mono?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-3">
      <span className="w-36 shrink-0 text-[#4d617a]">{label}</span>
      <span className={mono ? "break-all text-[#e4edf5]" : "text-[#e4edf5]"}>
        {children ?? value ?? "–"}
      </span>
    </div>
  );
}

function liveValueForEntry(
  key: string,
  snap: ComplianceSnapshot | null,
): Record<string, unknown> | null {
  if (!snap) return null;
  switch (key) {
    case "mifid_otr":
      return snap.mifid_otr ?? null;
    case "cftc_self_trade":
      return snap.cftc_self_trade ?? null;
    case "finra_fat_finger":
      return snap.finra_fat_finger ?? null;
    case "sec_cat":
      return snap.sec_cat ?? null;
    case "mar_abuse":
      return snap.mar_abuse ?? null;
    default:
      return null;
  }
}

function formatVal(v: unknown): string {
  if (v == null) return "–";
  if (typeof v === "number") return v.toLocaleString();
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "string") return v;
  if (Array.isArray(v)) return `[${v.length} items]`;
  return JSON.stringify(v);
}

// =====================================================================
// Live-counter tiles (unchanged from prior cut, kept in-file for locality)
// =====================================================================

function TileShell({
  title,
  subtitle,
  live,
  children,
}: {
  title: string;
  subtitle: string;
  live: boolean;
  children: React.ReactNode;
}) {
  return (
    <Card className="relative border-[#1a232e] bg-[#0f151d]">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between">
          <CardTitle className="font-mono text-[10px] uppercase tracking-widest text-[#6b8196]">
            {title}
          </CardTitle>
          {live && (
            <span className="flex items-center gap-1 font-mono text-[9px] uppercase tracking-wider text-emerald-400">
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
              </span>
              live
            </span>
          )}
        </div>
        <div className="mt-0.5 text-[10px] text-[#4d617a]">{subtitle}</div>
      </CardHeader>
      <CardContent className="pt-0">{children}</CardContent>
    </Card>
  );
}

function StatCell({
  label,
  value,
  tone,
}: {
  label: string;
  value: string | number;
  tone?: "emerald" | "rose" | "amber" | "sky";
}) {
  const cls =
    tone === "emerald"
      ? "text-emerald-400"
      : tone === "rose"
      ? "text-rose-400"
      : tone === "amber"
      ? "text-amber-400"
      : tone === "sky"
      ? "text-sky-400"
      : "text-[#e4edf5]";
  return (
    <div className="flex flex-col">
      <span className="font-mono text-[9px] uppercase tracking-wider text-[#4d617a]">
        {label}
      </span>
      <span className={`font-mono text-sm font-semibold tabular-nums ${cls}`}>
        {typeof value === "number" ? fmtNum(value) : value}
      </span>
    </div>
  );
}

function MifidOtrTile({
  snap,
  live,
}: {
  snap: ComplianceSnapshot["mifid_otr"] | undefined;
  live: boolean;
}) {
  const orders = Number(snap?.total_orders ?? 0);
  const trades = Number(snap?.total_trades ?? 0);
  const ratio = Number(
    snap?.global_ratio ?? (trades > 0 ? orders / trades : 0),
  );
  const worstRatio = Number(snap?.worst_symbol_ratio ?? 0);
  const wouldTrip = Boolean(snap?.would_trip);
  return (
    <TileShell
      title="MiFID II RTS 6"
      subtitle="order-to-trade ratio (EU)"
      live={live}
    >
      <div className="grid grid-cols-2 gap-2 gap-y-3">
        <StatCell label="orders" value={orders} />
        <StatCell label="trades" value={trades} />
        <StatCell label="global ratio" value={fmtRatio(ratio)} tone="sky" />
        <StatCell
          label="worst symbol"
          value={fmtRatio(worstRatio)}
          tone={wouldTrip ? "rose" : "sky"}
        />
      </div>
      <div className="mt-3 border-t border-[#1a232e] pt-2 font-mono text-[9px] uppercase tracking-wider">
        <span className="text-[#4d617a]">RTS 6 threshold · </span>
        <span className={wouldTrip ? "text-rose-400" : "text-emerald-400"}>
          {wouldTrip ? "WOULD TRIP" : "nominal"}
        </span>
      </div>
    </TileShell>
  );
}

function SelfTradeTile({
  snap,
  live,
}: {
  snap: ComplianceSnapshot["cftc_self_trade"] | undefined;
  live: boolean;
}) {
  const checked = Number(snap?.checked ?? 0);
  const rejected = Number(snap?.rejected ?? 0);
  const resting = Number(snap?.resting_orders ?? 0);
  const traders = Number(snap?.traders_tracked ?? 0);
  const rate = Number(snap?.reject_rate ?? (checked > 0 ? rejected / checked : 0));
  return (
    <TileShell
      title="CFTC Reg AT"
      subtitle="self-trade prevention (US)"
      live={live}
    >
      <div className="grid grid-cols-2 gap-2 gap-y-3">
        <StatCell label="checked" value={checked} />
        <StatCell
          label="would-reject"
          value={rejected}
          tone={rejected > 0 ? "rose" : undefined}
        />
        <StatCell label="resting" value={resting} tone="sky" />
        <StatCell
          label="traders"
          value={traders}
        />
      </div>
      <div className="mt-3 border-t border-[#1a232e] pt-2 font-mono text-[9px] uppercase tracking-wider text-[#4d617a]">
        reject rate · {(rate * 100).toFixed(2)}%
      </div>
    </TileShell>
  );
}

function FatFingerTile({
  snap,
  live,
}: {
  snap: ComplianceSnapshot["finra_fat_finger"] | undefined;
  live: boolean;
}) {
  const checked = Number(snap?.checked ?? 0);
  const rejected = Number(snap?.rejected ?? 0);
  const maxBps = Number(snap?.max_deviation_bps ?? 500);
  const worstBps = Number(snap?.worst_deviation_bps ?? 0);
  const rate = Number(snap?.reject_rate ?? (checked > 0 ? rejected / checked : 0));
  return (
    <TileShell
      title="FINRA 15c3-5"
      subtitle="fat-finger / erroneous order (US)"
      live={live}
    >
      <div className="grid grid-cols-2 gap-2 gap-y-3">
        <StatCell label="checked" value={checked} />
        <StatCell
          label="would-reject"
          value={rejected}
          tone={rejected > 0 ? "rose" : undefined}
        />
        <StatCell label="limit" value={`${maxBps} bps`} tone="sky" />
        <StatCell
          label="worst"
          value={`${worstBps.toFixed(0)} bps`}
          tone={worstBps > maxBps ? "rose" : undefined}
        />
      </div>
      <div className="mt-3 border-t border-[#1a232e] pt-2 font-mono text-[9px] uppercase tracking-wider text-[#4d617a]">
        reject rate · {(rate * 100).toFixed(2)}%
      </div>
    </TileShell>
  );
}

function CatTile({
  snap,
  live,
}: {
  snap: ComplianceSnapshot["sec_cat"] | undefined;
  live: boolean;
}) {
  const emitted = Number(snap?.total_records ?? 0);
  const byType = (snap?.by_event_type ?? {}) as Record<string, number>;
  const newOrd = Number(byType.MENO ?? 0);
  const cancels = Number(byType.MECR ?? 0);
  const rejects = Number(byType.MEOR ?? 0);
  return (
    <TileShell
      title="SEC Rule 613"
      subtitle="CAT Phase 2e feed (US)"
      live={live}
    >
      <div className="grid grid-cols-2 gap-2 gap-y-3">
        <StatCell label="emitted" value={emitted} tone="emerald" />
        <StatCell label="new (MENO)" value={newOrd} />
        <StatCell label="cancel (MECR)" value={cancels} />
        <StatCell
          label="reject (MEOR)"
          value={rejects}
          tone={rejects > 0 ? "rose" : undefined}
        />
      </div>
      {snap?.output_path && (
        <div className="mt-3 truncate border-t border-[#1a232e] pt-2 font-mono text-[9px] text-[#4d617a]">
          → {String(snap.output_path)}
        </div>
      )}
    </TileShell>
  );
}

function MarAlertsStrip({
  snap,
  alertCount,
}: {
  snap: ComplianceSnapshot["mar_abuse"] | undefined;
  alertCount: number;
}) {
  const min = (snap?.min_cancelled as number) ?? 30;
  const windowMs = ((snap?.window_ns as number) ?? 200_000_000) / 1_000_000;
  const orders = (snap?.orders_seen as number) ?? 0;
  const cancels = (snap?.cancels_seen as number) ?? 0;

  return (
    <Card
      className={`border-[#1a232e] bg-[#0f151d] ${
        alertCount > 0 ? "ring-1 ring-rose-500/40" : ""
      }`}
    >
      <CardContent className="py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <AlertTriangle
              className={`h-4 w-4 ${
                alertCount > 0 ? "text-rose-400" : "text-[#4d617a]"
              }`}
            />
            <div>
              <div className="font-mono text-[10px] uppercase tracking-widest text-[#6b8196]">
                MAR Art. 12 · spoofing / layering
              </div>
              <div className="mt-0.5 text-[10px] text-[#4d617a]">
                trigger: {min} same-side cancels inside {windowMs.toFixed(0)} ms
                window with no fills
              </div>
            </div>
          </div>
          <div className="flex items-center gap-6 font-mono">
            <div className="text-right">
              <div className="text-[9px] uppercase tracking-wider text-[#4d617a]">
                orders seen
              </div>
              <div className="text-sm tabular-nums text-[#e4edf5]">
                {fmtNum(orders)}
              </div>
            </div>
            <div className="text-right">
              <div className="text-[9px] uppercase tracking-wider text-[#4d617a]">
                cancels seen
              </div>
              <div className="text-sm tabular-nums text-[#e4edf5]">
                {fmtNum(cancels)}
              </div>
            </div>
            <div className="text-right">
              <div className="text-[9px] uppercase tracking-wider text-[#4d617a]">
                alerts
              </div>
              <div
                className={`text-lg font-semibold tabular-nums ${
                  alertCount > 0 ? "text-rose-400" : "text-[#e4edf5]"
                }`}
              >
                {alertCount}
              </div>
            </div>
          </div>
        </div>

        {snap?.last_alerts && snap.last_alerts.length > 0 && (
          <div className="mt-3 border-t border-[#1a232e] pt-2">
            <div className="mb-1 font-mono text-[9px] uppercase tracking-wider text-[#4d617a]">
              recent alerts ({snap.last_alerts.length})
            </div>
            <div className="space-y-1">
              {snap.last_alerts.slice(-5).map((a, i) => (
                <div
                  key={`${a.last_cancel_ns}-${i}`}
                  className="flex items-center gap-3 rounded bg-rose-950/20 px-2 py-1 font-mono text-[10px] text-rose-200"
                >
                  <span className="text-rose-400">trader#{a.trader_id}</span>
                  <span>HL-{a.symbol_id}</span>
                  <span>
                    {a.side === 1 ? "BUY" : a.side === 2 ? "SELL" : "?"}
                  </span>
                  <span className="ml-auto text-rose-300">
                    {a.n_orders} cancels / {(a.window_ns / 1_000_000).toFixed(0)}ms
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// =====================================================================
// Crosswalk row — now clickable to open the evidence drawer
// =====================================================================

function CrosswalkRow({
  entry,
  onOpenEvidence,
}: {
  entry: ComplianceEntry;
  onOpenEvidence: () => void;
}) {
  const layerCls =
    LAYER_TONE[entry.layer] ?? "border-[#1f2a38] bg-[#0a0e14] text-[#9ab3c8]";
  const statusCls = STATUS_TONE[entry.status] ?? "text-[#9ab3c8]";
  return (
    <button
      type="button"
      onClick={onOpenEvidence}
      className="group relative rounded-lg border border-[#1a232e] bg-[#0f151d] p-4 text-left transition hover:border-emerald-500/40 hover:bg-[#11181f] focus:outline-none focus:ring-1 focus:ring-emerald-500/60 print:cursor-default print:hover:border-[#1a232e] print:hover:bg-[#0f151d]"
    >
      <div className="mb-2 flex items-center gap-2">
        <span
          className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider ${layerCls}`}
        >
          {entry.layer}
        </span>
        <span className="font-mono text-[10px] uppercase tracking-wider text-[#4d617a]">
          {entry.key}
        </span>
        {entry.live_counter && (
          <span className="ml-auto flex items-center gap-1 font-mono text-[9px] uppercase tracking-wider text-emerald-400">
            <Activity className="h-2.5 w-2.5" /> live
          </span>
        )}
        <span className="text-[#4d617a] opacity-0 transition group-hover:opacity-100 no-print">
          <ChevronRight className="h-3 w-3" />
        </span>
      </div>
      <h4 className="text-sm font-semibold text-[#e4edf5]">{entry.regulation}</h4>
      <div className="mt-0.5 font-mono text-[10px] text-[#6b8196]">
        {entry.clause}
      </div>
      <p className="mt-2 text-xs leading-relaxed text-[#9ab3c8]">
        {entry.primitive}
      </p>
      <div className="mt-3 space-y-1 border-t border-[#1a232e] pt-2 font-mono text-[10px]">
        <div className="flex items-start gap-2">
          <span className="w-16 shrink-0 text-[#4d617a]">artifact</span>
          <span className="break-all text-[#9ab3c8]">{entry.artifact}</span>
        </div>
        <div className="flex items-start gap-2">
          <span className="w-16 shrink-0 text-[#4d617a]">signal</span>
          <span className="break-all text-[#9ab3c8]">{entry.audit_signal}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-16 shrink-0 text-[#4d617a]">status</span>
          <span className={statusCls}>{entry.status}</span>
        </div>
      </div>
    </button>
  );
}

function Legend({
  icon,
  label,
  text,
}: {
  icon: React.ReactNode;
  label: string;
  text: string;
}) {
  return (
    <div className="rounded-md border border-[#1a232e] bg-[#0f151d] p-3">
      <div className="mb-1 flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-[#9ab3c8]">
        {icon} {label}
      </div>
      <p className="text-[11px] leading-relaxed text-[#6b8196]">{text}</p>
    </div>
  );
}
