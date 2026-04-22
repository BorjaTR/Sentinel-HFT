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
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  getComplianceCrosswalk,
  getComplianceSnapshotShape,
  streamDrill,
} from "@/lib/sentinel-api";
import type {
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

export default function RegulationsPage() {
  const [crosswalk, setCrosswalk] = useState<ComplianceCrosswalkResponse | null>(null);
  const [snapshot, setSnapshot] = useState<ComplianceSnapshot | null>(null);
  const [activeDrill, setActiveDrill] = useState<DrillKind | null>(null);
  const [progress, setProgress] = useState<WsProgress | null>(null);
  const [marAlertCount, setMarAlertCount] = useState<number>(0);
  const [lastTick, setLastTick] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const streamRef = useRef<ReturnType<typeof streamDrill> | null>(null);

  useEffect(() => {
    Promise.all([getComplianceCrosswalk(), getComplianceSnapshotShape()])
      .then(([cw, shape]) => {
        setCrosswalk(cw);
        setSnapshot(shape);
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
    <div className="max-w-6xl pt-24 pb-10">
      {/* Header */}
      <header className="mb-8">
        <Link
          href="/sentinel"
          className="mb-3 inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-widest text-[#4d617a] transition hover:text-emerald-400"
        >
          <ArrowLeft className="h-3 w-3" /> sentinel / overview
        </Link>
        <h1 className="font-mono text-xs uppercase tracking-widest text-[#4d617a]">
          Workstream 3 · Regulation crosswalk
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
      </header>

      {err && (
        <div className="mb-6 rounded-md border border-rose-900/60 bg-rose-950/40 px-4 py-3 font-mono text-xs text-rose-200">
          {err}
          <div className="mt-1 text-rose-400/80">
            start backend with:{" "}
            <span className="rounded bg-[#0a0e14] px-2 py-0.5">
              python3 -m sentinel_hft.server.app
            </span>
          </div>
        </div>
      )}

      {/* ================== Live Counters ================== */}
      <section className="mb-10">
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
            .
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
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {entries.map((e) => (
                  <CrosswalkRow key={e.key} entry={e} />
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
    </div>
  );
}

// =====================================================================
// Live-counter tiles
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
// Crosswalk row
// =====================================================================

function CrosswalkRow({ entry }: { entry: ComplianceEntry }) {
  const layerCls =
    LAYER_TONE[entry.layer] ?? "border-[#1f2a38] bg-[#0a0e14] text-[#9ab3c8]";
  const statusCls = STATUS_TONE[entry.status] ?? "text-[#9ab3c8]";
  return (
    <div className="relative rounded-lg border border-[#1a232e] bg-[#0f151d] p-4">
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
    </div>
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
