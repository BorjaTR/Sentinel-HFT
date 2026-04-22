"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, notFound } from "next/navigation";
import dynamic from "next/dynamic";
import Link from "next/link";
import { Play, RotateCcw, ExternalLink, ScrollText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import {
  artifactUrl,
  getDrillCatalog,
  streamDrill,
} from "@/lib/sentinel-api";
import {
  DrillStressPanel,
  type StressOverrides,
} from "@/components/sentinel/DrillStressPanel";
import type {
  ComplianceSnapshot,
  DrillCatalog,
  DrillKind,
  WsEvent,
  WsProgress,
} from "@/lib/sentinel-types";

const LatencyChart = dynamic(
  () => import("@/components/sentinel/LatencyChart"),
  { ssr: false, loading: () => <ChartSkeleton /> },
);

const StageChart = dynamic(
  () => import("@/components/sentinel/StageChart"),
  { ssr: false, loading: () => <ChartSkeleton /> },
);

const RejectSankey = dynamic(
  () => import("@/components/sentinel/RejectSankey"),
  { ssr: false, loading: () => <ChartSkeleton /> },
);

const VALID_DRILLS: DrillKind[] = [
  "toxic_flow",
  "kill_drill",
  "latency",
  "daily_evidence",
];

interface Preset {
  label: string;
  ticks?: number;
  note?: string;
}

const PRESETS: Record<DrillKind, Preset[]> = {
  toxic_flow: [
    { label: "smoke", ticks: 1_500, note: "90s quick check" },
    { label: "default", ticks: 30_000, note: "story baseline" },
    { label: "stress", ticks: 36_000, note: "+20% tick volume" },
  ],
  kill_drill: [
    { label: "smoke", ticks: 6_000, note: "early spike" },
    { label: "default", ticks: 24_000, note: "vol spike @ 9k" },
    { label: "late", ticks: 30_000, note: "extended window" },
  ],
  latency: [
    { label: "smoke", ticks: 5_000, note: "fast baseline" },
    { label: "default", ticks: 40_000, note: "SLO run" },
    { label: "stress", ticks: 48_000, note: "+20% load" },
  ],
  daily_evidence: [
    { label: "all sessions", note: "morning + midday + eod" },
  ],
};

// Plain-English "what am I looking at" strip rendered above every
// drill. Three columns: what the desk feeds in, what to watch while
// it runs, what the user walks away with. Deliberately free of
// jargon -- this is the only explanation a business reader needs.
interface IoStrip {
  input: string;
  watch: string;
  keep: string;
}

const IO_STRIP: Record<DrillKind, IoStrip> = {
  toxic_flow: {
    input:
      "30,000 orders from a simulated trading day. About half come from counterparties who would have picked you off.",
    watch:
      "The rejection counter climb in real time as the system refuses those orders \u2014 in microseconds, before the loss would land.",
    keep:
      "A signed report with loss avoided, who got refused, and which rule caught them. Ready to hand to risk or compliance.",
  },
  kill_drill: {
    input:
      "24,000 orders on a normal morning, then a volatility spike fires at 14:03:27 \u2014 the kind that precedes a flash crash.",
    watch:
      "The emergency stop latch at the exact moment the spike hits, and every order after that get refused automatically until a human clears it.",
    keep:
      "A sealed record of when the stop engaged, which orders it blocked, and how long until the desk was safe. Regulator-grade.",
  },
  latency: {
    input:
      "40,000 orders run clean with a stopwatch attached to every stage of the hardware \u2014 market data in, decision, risk check, order out.",
    watch:
      "A live chart showing typical time, worst-case time, and anything slower than the promised service level flagged red.",
    keep:
      "A per-stage timing table and the single worst trade of the day broken down stage-by-stage. The exact answer to \u201cwhere did the time go?\u201d",
  },
  daily_evidence: {
    input:
      "A full simulated trading day \u2014 morning open, midday, and close \u2014 the way the regulator would reconstruct it.",
    watch:
      "The packet assemble itself: every decision, every rejection, every timing measurement, all sealed so it can\u2019t be quietly edited later.",
    keep:
      "One downloadable zip the regulator can verify without trusting us. Pre-mapped to MiFID II, CFTC Reg AT, and FINMA clauses.",
  },
};

function ChartSkeleton() {
  return (
    <div className="flex h-48 animate-pulse items-center justify-center rounded border border-[#1a232e] bg-[#0a0e14] font-mono text-xs text-[#4d617a]">
      loading chart...
    </div>
  );
}

function fmtNs(x: number): string {
  if (!x) return "-";
  if (x < 1_000) return `${x.toFixed(0)} ns`;
  if (x < 1_000_000) return `${(x / 1_000).toFixed(2)} µs`;
  return `${(x / 1_000_000).toFixed(2)} ms`;
}

export default function DrillRunnerPage() {
  const { drill } = useParams<{ drill: string }>();
  if (!VALID_DRILLS.includes(drill as DrillKind)) notFound();
  const kind = drill as DrillKind;

  const [catalog, setCatalog] = useState<DrillCatalog | null>(null);
  const [ticks, setTicks] = useState<number | null>(null);
  const [running, setRunning] = useState(false);
  const [events, setEvents] = useState<WsEvent[]>([]);
  const [progress, setProgress] = useState<WsProgress | null>(null);
  const [finalReport, setFinalReport] = useState<Record<string, unknown> | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [p99History, setP99History] = useState<Array<[number, number]>>([]);
  const [stress, setStress] = useState<StressOverrides>({
    pcap: "",
    chaos: { reorder_pct: 0, drop_pct: 0, lag_us: 0 },
  });
  const streamRef = useRef<ReturnType<typeof streamDrill> | null>(null);

  useEffect(() => {
    getDrillCatalog()
      .then((c) => {
        setCatalog(c);
        const t = c[kind]?.default_ticks ?? 10_000;
        setTicks(t);
      })
      .catch((e) => setError(String(e)));
    return () => {
      streamRef.current?.close();
    };
  }, [kind]);

  const meta = catalog?.[kind];

  function reset() {
    setEvents([]);
    setProgress(null);
    setFinalReport(null);
    setError(null);
    setP99History([]);
  }

  function start() {
    reset();
    setRunning(true);
    const overrides: Record<string, unknown> = {};
    if (ticks != null && kind !== "daily_evidence") overrides.ticks = ticks;
    // Stress + replay overrides — pcap path triggers a deterministic
    // replay on the backend (and flips the ProvenancePill to REPLAY via
    // lib/sentinel-api.ts), chaos knobs degrade the input wire-side
    // before the parser timestamp so per-stage attribution still adds
    // up under reorder / drop / lag.
    if (stress.pcap.trim().length > 0) overrides.pcap = stress.pcap.trim();
    overrides.chaos = stress.chaos;

    const handle = streamDrill(kind, overrides, {
      onEvent: (ev) => {
        setEvents((prev) => [...prev, ev].slice(-200));
        if (ev.type === "progress") {
          setProgress(ev);
          setP99History((prev) => [
            ...prev,
            [ev.elapsed_s, ev.latency_ns.p99],
          ].slice(-120) as Array<[number, number]>);
        } else if (ev.type === "result") {
          setFinalReport(ev.report);
          setRunning(false);
        } else if (ev.type === "error") {
          setError(ev.error);
          setRunning(false);
        }
      },
      onClose: () => setRunning(false),
      onError: () => {
        setError("WebSocket error (is the backend up?)");
        setRunning(false);
      },
    });
    streamRef.current = handle;
  }

  // Derived metrics for display --------------------------------------------
  const progressPct = Math.round((progress?.progress ?? 0) * 100);
  const stageData = useMemo(() => {
    if (!progress) return null;
    return Object.entries(progress.stage_ns).map(([name, b]) => ({
      stage: name,
      p50: b.p50,
      p99: b.p99,
      mean: b.mean,
    }));
  }, [progress]);
  const rejectData = useMemo(() => {
    if (!progress) return null;
    return {
      passed: progress.passed,
      toxic: progress.rejected_toxic,
      rate: progress.rejected_rate,
      position: progress.rejected_pos,
      notional: progress.rejected_notional,
      order_size: progress.rejected_order_size,
      kill: progress.rejected_kill,
    };
  }, [progress]);

  return (
    <div className="max-w-6xl">
      <header className="mb-6 flex items-start justify-between">
        <div>
          <div className="font-mono text-xs uppercase tracking-widest text-[#4d617a]">
            drill · {kind}
          </div>
          <h1 className="mt-1 text-2xl font-semibold text-[#e4edf5]">
            {meta?.name ?? kind}
          </h1>
          {meta && (
            <p className="mt-2 max-w-2xl text-xs text-[#9ab3c8]">
              {meta.description}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button
            onClick={reset}
            variant="outline"
            size="sm"
            disabled={running}
            className="border-[#1f2a38] bg-transparent font-mono text-xs text-[#9ab3c8] hover:bg-[#131c27] hover:text-[#e4edf5]"
          >
            <RotateCcw className="mr-1 h-3 w-3" /> reset
          </Button>
          <Button
            onClick={start}
            disabled={running}
            size="sm"
            className="bg-emerald-500 font-mono text-xs text-[#0a0e14] hover:bg-emerald-400"
          >
            <Play className="mr-1 h-3 w-3" />
            {running ? "running..." : "run drill"}
          </Button>
        </div>
      </header>

      {/* Plain-English I/O strip -- the three-line "what am I
          looking at" answer for a business reader, before any
          controls or charts appear. */}
      <section className="mb-6 grid grid-cols-1 gap-3 md:grid-cols-3">
        <div className="rounded-md border border-[#1a232e] bg-[#0f151d] p-4">
          <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-emerald-400">
            What we feed in
          </div>
          <p className="text-xs leading-relaxed text-[#9ab3c8]">
            {IO_STRIP[kind].input}
          </p>
        </div>
        <div className="rounded-md border border-[#1a232e] bg-[#0f151d] p-4">
          <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-sky-400">
            What to watch
          </div>
          <p className="text-xs leading-relaxed text-[#9ab3c8]">
            {IO_STRIP[kind].watch}
          </p>
        </div>
        <div className="rounded-md border border-[#1a232e] bg-[#0f151d] p-4">
          <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-amber-400">
            What you keep
          </div>
          <p className="text-xs leading-relaxed text-[#9ab3c8]">
            {IO_STRIP[kind].keep}
          </p>
        </div>
      </section>

      {/* Preset chips */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="font-mono text-[10px] uppercase tracking-wider text-[#4d617a]">
          presets
        </span>
        {PRESETS[kind].map((p) => (
          <button
            key={p.label}
            type="button"
            disabled={running}
            onClick={() => {
              if (p.ticks != null) setTicks(p.ticks);
            }}
            className={`group inline-flex items-center gap-2 rounded border px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider transition ${
              ticks === p.ticks
                ? "border-emerald-500/40 bg-emerald-500/5 text-emerald-300"
                : "border-[#1f2a38] bg-[#0a0e14] text-[#9ab3c8] hover:border-[#2a3a4c] hover:text-[#e4edf5]"
            } disabled:cursor-not-allowed disabled:opacity-40`}
          >
            <span>{p.label}</span>
            {p.ticks != null && (
              <span className="text-[#4d617a] group-hover:text-[#6b8196]">
                · {(p.ticks / 1000).toFixed(0)}k
              </span>
            )}
            {p.note && (
              <span className="normal-case text-[#4d617a] group-hover:text-[#6b8196]">
                {p.note}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Config row */}
      {kind !== "daily_evidence" && ticks != null && (
        <Card className="mb-4 border-[#1a232e] bg-[#0f151d]">
          <CardContent className="py-4">
            <div className="flex items-center gap-6">
              <div className="flex-1">
                <Label className="mb-2 block font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
                  Ticks ({ticks.toLocaleString()})
                </Label>
                <Slider
                  value={[ticks]}
                  min={500}
                  max={(meta?.default_ticks ?? 10_000) * 1.2}
                  step={500}
                  onValueChange={([v]) => setTicks(v)}
                  disabled={running}
                />
              </div>
              <div className="font-mono text-[10px] text-[#6b8196]">
                <div>seed · default</div>
                <div>risk · default</div>
                <div>output · /tmp/sentinel/{kind}</div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Stress + replay panel — pcap path + chaos knobs. Provenance
          flip and chaos badging happen automatically; the panel just
          mirrors its state into ``stress`` for the next start(). */}
      <DrillStressPanel disabled={running} onChange={setStress} />

      {error && (
        <div className="mb-4 rounded border border-rose-900/60 bg-rose-950/40 p-3 font-mono text-xs text-rose-200">
          {error}
        </div>
      )}

      {/* Progress bar */}
      <div className="mb-4 h-1.5 overflow-hidden rounded-full bg-[#0a0e14]">
        <div
          className="h-full bg-gradient-to-r from-emerald-500 to-cyan-400 transition-all"
          style={{ width: `${progressPct}%` }}
        />
      </div>
      <div className="mb-6 flex items-center justify-between font-mono text-[10px] text-[#6b8196]">
        <span>
          {progress
            ? `${progress.ticks_consumed.toLocaleString()} / ${progress.ticks_target.toLocaleString()} ticks`
            : "idle"}
        </span>
        <span>{progress ? `${progress.elapsed_s.toFixed(1)}s` : ""}</span>
      </div>

      {/* KPI row */}
      <div className="mb-2 font-mono text-[10px] text-[#6b8196]">
        <span className="text-[#9ab3c8]">intents</span> orders the desk wanted to send &middot;{" "}
        <span className="text-[#9ab3c8]">decisions</span> orders the gate ruled on &middot;{" "}
        <span className="text-emerald-400">passed</span> allowed through &middot;{" "}
        <span className="text-rose-400">rejected</span> blocked by a rule &middot;{" "}
        <span className="text-[#9ab3c8]">p50 / p99 / p99.9</span> wire-to-wire
        latency in nanoseconds (middle / worst-one-in-a-hundred / worst-one-in-a-thousand) &middot;{" "}
        <span className="text-[#9ab3c8]">kill</span> the physical stop latch
      </div>
      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="intents" value={progress?.intents_generated ?? 0} />
        <Kpi label="decisions" value={progress?.decisions_logged ?? 0} />
        <Kpi label="passed" value={progress?.passed ?? 0} tone="emerald" />
        <Kpi
          label="rejected"
          value={
            (progress?.rejected_toxic ?? 0) +
            (progress?.rejected_rate ?? 0) +
            (progress?.rejected_pos ?? 0) +
            (progress?.rejected_notional ?? 0) +
            (progress?.rejected_order_size ?? 0) +
            (progress?.rejected_kill ?? 0)
          }
          tone="rose"
        />
        <Kpi label="p50" value={fmtNs(progress?.latency_ns.p50 ?? 0)} />
        <Kpi label="p99" value={fmtNs(progress?.latency_ns.p99 ?? 0)} />
        <Kpi label="p99.9" value={fmtNs(progress?.latency_ns.p999 ?? 0)} />
        <Kpi
          label="kill"
          value={progress?.kill_triggered ? "TRIGGERED" : "armed"}
          tone={progress?.kill_triggered ? "amber" : undefined}
        />
      </div>

      {/* Compliance strip -- observational would-block counters */}
      <ComplianceStrip compliance={progress?.compliance ?? null} />

      {/* Charts */}
      <div className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card className="border-[#1a232e] bg-[#0f151d]">
          <CardHeader className="pb-2">
            <CardTitle className="font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
              Wire-to-wire p99 (streaming)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <LatencyChart history={p99History} />
          </CardContent>
        </Card>
        <Card className="border-[#1a232e] bg-[#0f151d]">
          <CardHeader className="pb-2">
            <CardTitle className="font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
              Per-stage latency (p50 / p99)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <StageChart data={stageData} />
          </CardContent>
        </Card>
      </div>

      <Card className="mb-6 border-[#1a232e] bg-[#0f151d]">
        <CardHeader className="pb-2">
          <CardTitle className="font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
            Intent flow · pass vs reject breakdown
          </CardTitle>
        </CardHeader>
        <CardContent>
          <RejectSankey data={rejectData} />
        </CardContent>
      </Card>

      {/* Final report */}
      {finalReport && (
        <Card className="border-emerald-900/50 bg-[#0f151d]">
          <CardHeader className="pb-2">
            <CardTitle className="font-mono text-[10px] uppercase tracking-wider text-emerald-400">
              Drill complete · final report
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="mb-3 flex flex-wrap items-center gap-3 text-xs">
              <a
                href={artifactUrl(kind, `${kind}.html`)}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 rounded border border-[#1f2a38] bg-[#0a0e14] px-3 py-1.5 font-mono text-[10px] text-[#9ab3c8] hover:text-emerald-400"
              >
                <ExternalLink className="h-3 w-3" /> {kind}.html
              </a>
              <a
                href={artifactUrl(kind, `${kind}.json`)}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 rounded border border-[#1f2a38] bg-[#0a0e14] px-3 py-1.5 font-mono text-[10px] text-[#9ab3c8] hover:text-emerald-400"
              >
                <ExternalLink className="h-3 w-3" /> {kind}.json
              </a>
              <a
                href={artifactUrl(kind, "audit.aud")}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 rounded border border-[#1f2a38] bg-[#0a0e14] px-3 py-1.5 font-mono text-[10px] text-[#9ab3c8] hover:text-emerald-400"
              >
                <ExternalLink className="h-3 w-3" /> audit.aud
              </a>
            </div>
            <pre className="overflow-x-auto rounded bg-[#0a0e14] p-3 font-mono text-[10px] leading-relaxed text-[#9ab3c8]">
              {JSON.stringify(finalReport, null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function ComplianceStrip({
  compliance,
}: {
  compliance: ComplianceSnapshot | null | undefined;
}) {
  const otr = compliance?.mifid_otr;
  const selfTrade = compliance?.cftc_self_trade;
  const fatFinger = compliance?.finra_fat_finger;
  const cat = compliance?.sec_cat;
  const mar = compliance?.mar_abuse;

  const otrOrders = Number(otr?.total_orders ?? 0);
  const otrTrades = Number(otr?.total_trades ?? 0);
  const otrRatio = Number(
    otr?.global_ratio ??
      (otrTrades > 0 ? otrOrders / otrTrades : otrOrders > 0 ? Infinity : 0),
  );
  const otrWouldTrip = Boolean(otr?.would_trip);

  const stRejected = Number(selfTrade?.rejected ?? 0);
  const stChecked = Number(selfTrade?.checked ?? 0);
  const ffRejected = Number(fatFinger?.rejected ?? 0);
  const ffChecked = Number(fatFinger?.checked ?? 0);
  const catRecords = Number(cat?.total_records ?? 0);
  const catByType = (cat?.by_event_type ?? {}) as Record<string, number>;
  const marAlerts = Number(mar?.alerts ?? 0);

  const hasData =
    compliance != null &&
    (otrOrders > 0 || stChecked > 0 || ffChecked > 0 || catRecords > 0);

  return (
    <div className="mb-6 rounded-lg border border-[#1a232e] bg-[#0f151d] p-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
          <ScrollText className="h-3 w-3 text-emerald-400" />
          Compliance counters
        </div>
        <Link
          href="/sentinel/regulations"
          className="font-mono text-[10px] text-[#6b8196] hover:text-emerald-400"
        >
          see the full rulebook &rarr;
        </Link>
      </div>
      <p className="mb-3 text-[11px] leading-relaxed text-[#6b8196]">
        These counters watch the drill in parallel and tell you what each
        regulator would see. They never change the outcome — the hardware
        gate is what actually blocks orders.
      </p>

      {!hasData ? (
        <div className="py-3 text-center font-mono text-[10px] text-[#4d617a]">
          waiting for decisions &hellip; counters will populate once the drill emits intents
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <ComplianceCell
            label="mifid OTR"
            primary={Number.isFinite(otrRatio) ? otrRatio.toFixed(2) : "\u221e"}
            sub={`${otrOrders.toLocaleString()} ord / ${otrTrades.toLocaleString()} trd`}
            warn={otrWouldTrip}
            warnHint={otrWouldTrip ? "RTS 6 trip" : null}
          />
          <ComplianceCell
            label="self-trade"
            primary={stRejected.toLocaleString()}
            sub={`${stChecked.toLocaleString()} checked`}
            warn={stRejected > 0}
            warnHint={stRejected > 0 ? "CFTC Reg AT" : null}
          />
          <ComplianceCell
            label="fat-finger"
            primary={ffRejected.toLocaleString()}
            sub={`${ffChecked.toLocaleString()} checked`}
            warn={ffRejected > 0}
            warnHint={ffRejected > 0 ? "FINRA 15c3-5" : null}
          />
          <ComplianceCell
            label="CAT records"
            primary={catRecords.toLocaleString()}
            sub={`${Number(catByType.MENO ?? 0).toLocaleString()} N / ${Number(catByType.MECR ?? 0).toLocaleString()} C / ${Number(catByType.MEOR ?? 0).toLocaleString()} R`}
          />
          <ComplianceCell
            label="MAR alerts"
            primary={marAlerts.toLocaleString()}
            sub={`${Number(mar?.orders_seen ?? 0).toLocaleString()} o / ${Number(mar?.cancels_seen ?? 0).toLocaleString()} c`}
            warn={marAlerts > 0}
            warnHint={marAlerts > 0 ? "Art. 12 spoof" : null}
          />
        </div>
      )}
    </div>
  );
}

function ComplianceCell({
  label,
  primary,
  sub,
  warn,
  warnHint,
}: {
  label: string;
  primary: string;
  sub: string;
  warn?: boolean;
  warnHint?: string | null;
}) {
  return (
    <div
      className={`rounded border p-2.5 transition ${
        warn
          ? "border-rose-900/50 bg-rose-950/20"
          : "border-[#1a232e] bg-[#0a0e14]"
      }`}
    >
      <div className="flex items-center justify-between font-mono text-[9px] uppercase tracking-wider text-[#4d617a]">
        <span>{label}</span>
        {warn && warnHint && (
          <span className="text-[8px] text-rose-300">{warnHint}</span>
        )}
      </div>
      <div
        className={`mt-1 font-mono text-base font-semibold ${
          warn ? "text-rose-300" : "text-[#e4edf5]"
        }`}
      >
        {primary}
      </div>
      <div className="mt-0.5 font-mono text-[9px] text-[#6b8196]">{sub}</div>
    </div>
  );
}

function Kpi({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone?: "emerald" | "rose" | "amber";
}) {
  const toneCls =
    tone === "emerald"
      ? "text-emerald-400"
      : tone === "rose"
      ? "text-rose-400"
      : tone === "amber"
      ? "text-amber-400"
      : "text-[#e4edf5]";
  return (
    <div className="rounded border border-[#1a232e] bg-[#0f151d] p-3">
      <div className="font-mono text-[10px] uppercase tracking-wider text-[#4d617a]">
        {label}
      </div>
      <div className={`mt-1 font-mono text-lg font-semibold ${toneCls}`}>
        {typeof value === "number" ? value.toLocaleString() : value}
      </div>
    </div>
  );
}
