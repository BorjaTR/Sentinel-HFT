"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Siren,
  RefreshCw,
  ShieldCheck,
  ShieldAlert,
  Activity,
  Target,
  Hash,
  Zap,
  AlertCircle,
  CheckCircle2,
  XCircle,
  Play,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  getTriageAlerts,
  runTriageEval,
} from "@/lib/sentinel-api";
import type {
  AlertChainView,
  AlertSummary,
  TriageEvalResponse,
} from "@/lib/sentinel-types";

function severityTone(sev: string): string {
  const s = (sev || "").toLowerCase();
  if (s === "critical" || s === "alert" || s === "high") return "text-rose-300";
  if (s === "warn" || s === "warning" || s === "medium") return "text-amber-300";
  if (s === "info") return "text-sky-300";
  return "text-[#9ab3c8]";
}

function severityBadge(sev: string): string {
  const s = (sev || "").toLowerCase();
  if (s === "critical" || s === "alert" || s === "high")
    return "border-rose-500/40 bg-rose-500/5 text-rose-300";
  if (s === "warn" || s === "warning" || s === "medium")
    return "border-amber-500/40 bg-amber-500/5 text-amber-300";
  if (s === "info") return "border-sky-500/40 bg-sky-500/5 text-sky-300";
  return "border-[#1f2a38] bg-[#0a0e14] text-[#9ab3c8]";
}

function fmtTs(ns: number): string {
  // Records are ns since epoch; convert to ms.
  if (!ns || !Number.isFinite(ns)) return "—";
  const ms = Math.floor(ns / 1_000_000);
  try {
    return new Date(ms).toISOString().replace("T", " ").replace("Z", "Z");
  } catch {
    return String(ns);
  }
}

function pct(x: number): string {
  if (!Number.isFinite(x)) return "—";
  return `${(x * 100).toFixed(1)}%`;
}

export default function TriageDashboardPage() {
  const [view, setView] = useState<AlertChainView | null>(null);
  const [limit, setLimit] = useState<number>(100);
  const [loading, setLoading] = useState(false);

  const [evalReport, setEvalReport] = useState<TriageEvalResponse | null>(null);
  const [evaluating, setEvaluating] = useState(false);

  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(
    async (n: number = limit) => {
      setLoading(true);
      setError(null);
      try {
        const v = await getTriageAlerts({ limit: n });
        setView(v);
      } catch (e) {
        setError(String(e));
      } finally {
        setLoading(false);
      }
    },
    [limit],
  );

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function doEval() {
    setEvaluating(true);
    setError(null);
    setEvalReport(null);
    try {
      const r = await runTriageEval();
      setEvalReport(r);
    } catch (e) {
      setError(String(e));
    } finally {
      setEvaluating(false);
    }
  }

  // Most-recent first in the table.
  const orderedAlerts: AlertSummary[] = useMemo(() => {
    if (!view) return [];
    return [...view.alerts].reverse();
  }, [view]);

  return (
    <div className="max-w-7xl">
      <header className="mb-6">
        <div className="font-mono text-xs uppercase tracking-widest text-[#4d617a]">
          tool · ai
        </div>
        <h1 className="mt-1 flex items-center gap-2 text-2xl font-semibold text-[#e4edf5]">
          <Siren className="h-6 w-6 text-rose-400" />
          Online triage agent
        </h1>
        <p className="mt-2 max-w-3xl text-xs text-[#9ab3c8]">
          Workstream 5 — streaming detectors (latency z-score, reject-rate
          CUSUM, SPRT) write to a BLAKE2b-chained sidecar log
          (<span className="font-mono text-[#e4edf5]">out/triage/alerts.alog</span>).
          This page reads the chain head and recent records, and runs the
          deterministic scripted evaluation harness on demand to confirm the
          quality bar (recall = 1.0, precision ≥ 0.70, F1 ≥ 0.80).
        </p>
      </header>

      {error && (
        <div className="mb-4 rounded border border-rose-900/60 bg-rose-950/40 p-3 font-mono text-xs text-rose-200">
          {error}
        </div>
      )}

      {/* Top row: chain integrity + eval action */}
      <div className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card
          className={
            view
              ? view.chain_ok
                ? "border-emerald-900/50 bg-emerald-950/10"
                : "border-rose-900/60 bg-rose-950/10"
              : "border-[#1a232e] bg-[#0f151d]"
          }
        >
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider">
              {view?.chain_ok ? (
                <>
                  <ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />
                  <span className="text-emerald-400">Chain OK</span>
                </>
              ) : view ? (
                <>
                  <ShieldAlert className="h-3.5 w-3.5 text-rose-400" />
                  <span className="text-rose-400">Chain broken</span>
                </>
              ) : (
                <>
                  <Activity className="h-3.5 w-3.5 text-[#6b8196]" />
                  <span className="text-[#6b8196]">loading…</span>
                </>
              )}
              <span className="ml-auto text-[#6b8196]">
                {view?.n_records.toLocaleString() ?? "—"} records
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-1 gap-2 font-mono text-[11px] md:grid-cols-2">
              <KV
                icon={<Hash className="h-3 w-3 text-emerald-400" />}
                label="head_hash_lo"
                value={
                  view?.head_hash_lo
                    ? `0x${view.head_hash_lo}`
                    : view
                      ? "(empty)"
                      : "—"
                }
              />
              <KV
                icon={<AlertCircle className="h-3 w-3 text-amber-400" />}
                label="bad_index"
                value={view?.bad_index != null ? String(view.bad_index) : "—"}
              />
              {view?.bad_reason && (
                <div className="col-span-full text-rose-300">
                  reason: {view.bad_reason}
                </div>
              )}
            </dl>
            <div className="mt-3 flex items-end gap-3">
              <div className="w-32">
                <Label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
                  table limit
                </Label>
                <Input
                  type="number"
                  min={1}
                  max={10000}
                  value={limit}
                  onChange={(e) =>
                    setLimit(
                      Math.max(1, Math.min(10000, Number(e.target.value) || 1)),
                    )
                  }
                  className="border-[#1f2a38] bg-[#0a0e14] font-mono text-xs text-[#e4edf5]"
                  disabled={loading}
                />
              </div>
              <Button
                onClick={() => refresh(limit)}
                disabled={loading}
                size="sm"
                className="bg-emerald-500 font-mono text-xs text-[#0a0e14] hover:bg-emerald-400 disabled:opacity-40"
              >
                <RefreshCw className={`mr-1 h-3 w-3 ${loading ? "animate-spin" : ""}`} />
                {loading ? "reading…" : "refresh"}
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card className="border-[#1a232e] bg-[#0f151d]">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
              <Target className="h-3.5 w-3.5 text-emerald-400" />
              Quality-bar evaluation
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="mb-3 text-xs text-[#9ab3c8]">
              Replays the scripted scenario through{" "}
              <span className="font-mono text-[#e4edf5]">run_evaluation()</span>:
              labelled anomaly windows for latency, reject-rate, and
              fill-cluster families. Asserts the contracted quality bar.
            </p>
            <Button
              onClick={doEval}
              disabled={evaluating}
              size="sm"
              className="bg-emerald-500 font-mono text-xs text-[#0a0e14] hover:bg-emerald-400 disabled:opacity-40"
            >
              <Play className="mr-1 h-3 w-3" />
              {evaluating ? "running…" : "run eval harness"}
            </Button>

            {evalReport && (
              <div className="mt-4 grid grid-cols-3 gap-2 font-mono text-[11px]">
                <Stat
                  label="precision"
                  value={pct(evalReport.precision)}
                  ok={evalReport.precision >= 0.7}
                />
                <Stat
                  label="recall"
                  value={pct(evalReport.recall)}
                  ok={evalReport.recall >= 1.0}
                />
                <Stat
                  label="F1"
                  value={pct(evalReport.f1)}
                  ok={evalReport.f1 >= 0.8}
                />
                <Stat
                  label="events"
                  value={evalReport.events.toLocaleString()}
                />
                <Stat
                  label="alerts_fired"
                  value={evalReport.alerts_fired.toLocaleString()}
                />
                <Stat
                  label="anomalies"
                  value={evalReport.labelled_anomalies.toLocaleString()}
                />
                <Stat
                  label="TP"
                  value={evalReport.true_positives.toLocaleString()}
                  ok={evalReport.true_positives > 0}
                />
                <Stat
                  label="FP"
                  value={evalReport.false_positives.toLocaleString()}
                  ok={evalReport.false_positives === 0}
                />
                <Stat
                  label="FN"
                  value={evalReport.false_negatives.toLocaleString()}
                  ok={evalReport.false_negatives === 0}
                />
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Alert table */}
      <Card className="mb-6 border-[#1a232e] bg-[#0f151d]">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
            <Zap className="h-3.5 w-3.5 text-emerald-400" />
            Sidecar alert log · most recent {orderedAlerts.length}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {orderedAlerts.length === 0 ? (
            <div className="rounded border border-[#1f2a38] bg-[#0a0e14] p-4 font-mono text-[11px] text-[#6b8196]">
              {loading
                ? "reading sidecar log…"
                : "no alerts in the chain. Run a drill or the eval harness to emit some."}
            </div>
          ) : (
            <div className="overflow-x-auto rounded border border-[#1f2a38]">
              <table className="w-full font-mono text-[11px]">
                <thead className="bg-[#0a0e14] text-[#6b8196]">
                  <tr>
                    <th className="px-3 py-1.5 text-left font-normal">seq</th>
                    <th className="px-3 py-1.5 text-left font-normal">timestamp</th>
                    <th className="px-3 py-1.5 text-left font-normal">severity</th>
                    <th className="px-3 py-1.5 text-left font-normal">detector</th>
                    <th className="px-3 py-1.5 text-left font-normal">stage</th>
                    <th className="px-3 py-1.5 text-right font-normal">score</th>
                    <th className="px-3 py-1.5 text-right font-normal">window_n</th>
                    <th className="px-3 py-1.5 text-left font-normal">detail</th>
                    <th className="px-3 py-1.5 text-left font-normal">hash_lo</th>
                  </tr>
                </thead>
                <tbody>
                  {orderedAlerts.map((a) => (
                    <tr
                      key={a.seq_no}
                      className="border-t border-[#1a232e] hover:bg-[#131c27]"
                    >
                      <td className="px-3 py-1.5 text-[#9ab3c8]">{a.seq_no}</td>
                      <td className="px-3 py-1.5 text-[#9ab3c8]">{fmtTs(a.timestamp_ns)}</td>
                      <td className="px-3 py-1.5">
                        <span
                          className={`rounded border px-1.5 py-0 text-[9px] uppercase tracking-wider ${severityBadge(a.severity)}`}
                        >
                          {a.severity}
                        </span>
                      </td>
                      <td className="px-3 py-1.5 text-[#e4edf5]">{a.detector}</td>
                      <td className="px-3 py-1.5 text-[#9ab3c8]">{a.stage ?? "—"}</td>
                      <td className={`px-3 py-1.5 text-right ${severityTone(a.severity)}`}>
                        {Number.isFinite(a.score) ? a.score.toFixed(2) : "—"}
                      </td>
                      <td className="px-3 py-1.5 text-right text-[#9ab3c8]">{a.window_n}</td>
                      <td className="px-3 py-1.5 text-[#9ab3c8]">{a.detail}</td>
                      <td className="px-3 py-1.5 text-[#4d617a]" title={a.full_hash_lo}>
                        {a.full_hash_lo.slice(0, 8)}…
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Eval drill-down: anomaly windows + alerts */}
      {evalReport && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card className="border-[#1a232e] bg-[#0f151d]">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
                <Target className="h-3.5 w-3.5 text-emerald-400" />
                anomaly windows · {evalReport.anomaly_windows.length}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto rounded border border-[#1f2a38]">
                <table className="w-full font-mono text-[11px]">
                  <thead className="bg-[#0a0e14] text-[#6b8196]">
                    <tr>
                      <th className="px-3 py-1.5 text-left font-normal">family</th>
                      <th className="px-3 py-1.5 text-left font-normal">stage</th>
                      <th className="px-3 py-1.5 text-left font-normal">matched</th>
                    </tr>
                  </thead>
                  <tbody>
                    {evalReport.anomaly_windows.map((w, i) => {
                      const matched = Boolean(w["matched"]);
                      return (
                        <tr
                          key={i}
                          className="border-t border-[#1a232e] hover:bg-[#131c27]"
                        >
                          <td className="px-3 py-1.5 text-[#e4edf5]">
                            {String(w["family"] ?? "—")}
                          </td>
                          <td className="px-3 py-1.5 text-[#9ab3c8]">
                            {w["stage"] != null ? String(w["stage"]) : "—"}
                          </td>
                          <td className="px-3 py-1.5">
                            {matched ? (
                              <span className="text-emerald-400">
                                <CheckCircle2 className="mr-1 inline h-3 w-3" />
                                matched
                              </span>
                            ) : (
                              <span className="text-rose-400">
                                <XCircle className="mr-1 inline h-3 w-3" />
                                missed
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          <Card className="border-[#1a232e] bg-[#0f151d]">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
                <Zap className="h-3.5 w-3.5 text-emerald-400" />
                eval alerts · {evalReport.alerts.length}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto rounded border border-[#1f2a38]">
                <table className="w-full font-mono text-[11px]">
                  <thead className="bg-[#0a0e14] text-[#6b8196]">
                    <tr>
                      <th className="px-3 py-1.5 text-left font-normal">detector</th>
                      <th className="px-3 py-1.5 text-left font-normal">severity</th>
                      <th className="px-3 py-1.5 text-right font-normal">score</th>
                      <th className="px-3 py-1.5 text-left font-normal">matched</th>
                    </tr>
                  </thead>
                  <tbody>
                    {evalReport.alerts.map((a, i) => {
                      const matched = Boolean(a["matched"]);
                      const sev = String(a["severity"] ?? "—");
                      const sc = Number(a["score"]);
                      return (
                        <tr
                          key={i}
                          className="border-t border-[#1a232e] hover:bg-[#131c27]"
                        >
                          <td className="px-3 py-1.5 text-[#e4edf5]">
                            {String(a["detector"] ?? "—")}
                          </td>
                          <td className="px-3 py-1.5">
                            <span
                              className={`rounded border px-1.5 py-0 text-[9px] uppercase tracking-wider ${severityBadge(sev)}`}
                            >
                              {sev}
                            </span>
                          </td>
                          <td className={`px-3 py-1.5 text-right ${severityTone(sev)}`}>
                            {Number.isFinite(sc) ? sc.toFixed(2) : "—"}
                          </td>
                          <td className="px-3 py-1.5">
                            {matched ? (
                              <span className="text-emerald-400">
                                <CheckCircle2 className="mr-1 inline h-3 w-3" />
                                TP
                              </span>
                            ) : (
                              <span className="text-rose-400">
                                <XCircle className="mr-1 inline h-3 w-3" />
                                FP
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

function KV({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center gap-2">
      {icon}
      <span className="text-[#6b8196]">{label}</span>
      <span className="ml-auto truncate text-[#e4edf5]">{value}</span>
    </div>
  );
}

function Stat({
  label,
  value,
  ok,
}: {
  label: string;
  value: string;
  ok?: boolean;
}) {
  const tone =
    ok === true
      ? "border-emerald-500/40 bg-emerald-500/5 text-emerald-300"
      : ok === false
        ? "border-rose-500/40 bg-rose-500/5 text-rose-300"
        : "border-[#1f2a38] bg-[#0a0e14] text-[#e4edf5]";
  return (
    <div className={`rounded border p-2 ${tone}`}>
      <div className="text-[9px] uppercase tracking-wider text-[#6b8196]">
        {label}
      </div>
      <div className="mt-0.5 font-mono text-sm">{value}</div>
    </div>
  );
}
