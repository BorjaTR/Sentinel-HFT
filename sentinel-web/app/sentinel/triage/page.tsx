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
  LineChart,
  TrendingUp,
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

// ---------------------------------------------------------------------------
// Detector contract
//
// These thresholds mirror ``sentinel_hft/ai/triage.py`` defaults. The UI is
// observational — if the server config changes at runtime we won't know here,
// but the numbers below are the values used by the deterministic eval harness
// (``run_evaluation()``) so the rendered plots match the shipped quality bar.
// ---------------------------------------------------------------------------

interface DetectorSpec {
  key: string;
  label: string;
  family: "latency" | "reject_rate" | "fill_quality";
  threshold: number;
  threshold_label: string;
  description: string;
}

const DETECTORS: DetectorSpec[] = [
  {
    key: "latency_zscore",
    label: "latency z-score",
    family: "latency",
    threshold: 4.0,
    threshold_label: "z_threshold",
    description:
      "Rolling z-score on stage latency p99. Fires when the latest window deviates by ≥ z_threshold standard deviations from the rolling baseline.",
  },
  {
    key: "reject_rate_cusum",
    label: "reject-rate CUSUM",
    family: "reject_rate",
    threshold: 5.0,
    threshold_label: "alert_threshold",
    description:
      "One-sided CUSUM on risk-reject rate. Fires when the cumulative deviation above the reference level crosses alert_threshold.",
  },
  {
    key: "fill_quality_sprt",
    label: "fill-quality SPRT",
    family: "fill_quality",
    threshold: 4.0,
    threshold_label: "accept_upper",
    description:
      "Sequential probability ratio test on fill-quality clusters. Fires when the log-likelihood ratio exceeds accept_upper in favour of the anomaly hypothesis.",
  },
];

// ---------------------------------------------------------------------------
// Helpers

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

// ---------------------------------------------------------------------------
// Page component

export default function TriageDashboardPage() {
  const [view, setView] = useState<AlertChainView | null>(null);
  const [limit, setLimit] = useState<number>(200);
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

  // Group alerts by detector key for the per-detector plots.
  //
  // We keep chain-order (seq_no ascending) so the sparkline reads left→right
  // as a time series. This matches how the underlying .alog is appended.
  const alertsByDetector: Record<string, AlertSummary[]> = useMemo(() => {
    const out: Record<string, AlertSummary[]> = {};
    if (!view) return out;
    const chronological = [...view.alerts].sort((a, b) => a.seq_no - b.seq_no);
    for (const a of chronological) {
      const key = (a.detector || "").toLowerCase();
      if (!out[key]) out[key] = [];
      out[key].push(a);
    }
    return out;
  }, [view]);

  return (
    <div className="max-w-7xl">
      <header className="mb-6">
        <div className="font-mono text-[10px] uppercase tracking-widest text-[#4d617a]">
          Live alert triage &middot; trading desk &middot; compliance
        </div>
        <h1 className="mt-1 flex items-center gap-2 text-2xl font-semibold text-[#e4edf5]">
          <Siren className="h-6 w-6 text-rose-400" />
          Live alert triage
        </h1>
        <p className="mt-2 max-w-3xl text-sm leading-relaxed text-[#9ab3c8]">
          Three live detectors watch the desk in real time: one spots a sudden
          latency spike, one spots a surge in order rejections, one spots
          fill quality turning bad. Every alert they raise is appended to a
          tamper-evident log and ranked here by severity so the on-call
          operator sees the important one first. The page also runs a
          canned test battery on demand to prove the detectors still clear
          the agreed quality bar (catch every real problem, with at most a
          few false alarms per hundred).
        </p>
      </header>

      {error && (
        <div className="mb-4 rounded border border-rose-900/60 bg-rose-950/40 p-3 font-mono text-xs text-rose-200">
          {error}
        </div>
      )}

      {/* --------------------------------------------------------------- */}
      {/* Head-hash banner — promoted above the fold so compliance and    */}
      {/* engineering reviewers can copy-verify the chain tip at a glance.*/}
      {/* --------------------------------------------------------------- */}
      <ChainHeadBanner view={view} loading={loading} />

      {/* Top row: chain integrity summary + eval action */}
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
                icon={<AlertCircle className="h-3 w-3 text-amber-400" />}
                label="bad_index"
                value={view?.bad_index != null ? String(view.bad_index) : "—"}
              />
              <KV
                icon={<Hash className="h-3 w-3 text-[#6b8196]" />}
                label="table_limit"
                value={String(limit)}
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

      {/* --------------------------------------------------------------- */}
      {/* Per-detector score plots.                                       */}
      {/*                                                                 */}
      {/* One card per detector spec. Each plot renders the full sequence */}
      {/* of chain scores for that detector family, with a horizontal     */}
      {/* threshold line at the contracted value. Points above the        */}
      {/* threshold are coloured by severity.                             */}
      {/* --------------------------------------------------------------- */}
      <Card className="mb-6 border-[#1a232e] bg-[#0f151d]">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
            <LineChart className="h-3.5 w-3.5 text-violet-400" />
            Detector score traces · threshold lines from triage.py
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            {DETECTORS.map((spec) => (
              <DetectorPlotCard
                key={spec.key}
                spec={spec}
                alerts={alertsByDetector[spec.key] ?? []}
              />
            ))}
          </div>
        </CardContent>
      </Card>

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

// ---------------------------------------------------------------------------
// Chain head banner

function ChainHeadBanner({
  view,
  loading,
}: {
  view: AlertChainView | null;
  loading: boolean;
}) {
  const ok = view?.chain_ok === true;
  const broken = view !== null && view.chain_ok === false;

  let tone = "border-[#1a232e] bg-[#0a0e14]";
  let iconColor = "text-[#6b8196]";
  let statusLabel = "loading…";
  let statusText = "text-[#6b8196]";

  if (ok) {
    tone = "border-emerald-900/50 bg-emerald-950/10";
    iconColor = "text-emerald-400";
    statusLabel = "chain verified";
    statusText = "text-emerald-300";
  } else if (broken) {
    tone = "border-rose-900/60 bg-rose-950/15";
    iconColor = "text-rose-400";
    statusLabel = "chain broken";
    statusText = "text-rose-300";
  }

  const fullHash = view?.head_hash_lo ?? "";
  const display = fullHash ? `0x${fullHash}` : view ? "(empty chain)" : "—";

  return (
    <div
      className={`mb-4 rounded border px-4 py-3 ${tone}`}
      data-testid="triage-head-hash-banner"
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Hash className={`h-4 w-4 flex-none ${iconColor}`} />
        <div className="min-w-0 flex-1">
          <div className="font-mono text-[10px] uppercase tracking-widest text-[#6b8196]">
            alert-chain head · BLAKE2b-128 low half
          </div>
          <div
            className="mt-0.5 break-all font-mono text-xs text-[#e4edf5]"
            title={display}
          >
            {display}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1 whitespace-nowrap">
          <span
            className={`font-mono text-[10px] uppercase tracking-wider ${statusText}`}
          >
            {loading ? "reading…" : statusLabel}
          </span>
          <span className="font-mono text-[10px] text-[#6b8196]">
            {view ? `${view.n_records.toLocaleString()} records` : "—"}
          </span>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Per-detector plot
//
// Renders a small SVG line+scatter of all chain scores for one detector
// family against its contracted threshold. We intentionally avoid a chart
// library here — an embedded SVG keeps the bundle small and gives us exact
// control over the threshold line, which is the whole point of the widget.

function DetectorPlotCard({
  spec,
  alerts,
}: {
  spec: DetectorSpec;
  alerts: AlertSummary[];
}) {
  const scores = alerts
    .map((a) => a.score)
    .filter((s) => Number.isFinite(s));

  const hasData = scores.length > 0;
  const maxScore = hasData ? Math.max(...scores, spec.threshold) : spec.threshold;
  const minScore = hasData ? Math.min(...scores, 0) : 0;

  // Reserve a little headroom above the largest point so the threshold line
  // doesn't clip at the top of the chart on dense alert windows.
  const yTop = Math.max(spec.threshold, maxScore) * 1.15;
  const yBot = Math.min(0, minScore);
  const yRange = Math.max(1e-9, yTop - yBot);

  const W = 320;
  const H = 140;
  const PADL = 30;
  const PADR = 8;
  const PADT = 8;
  const PADB = 22;
  const innerW = W - PADL - PADR;
  const innerH = H - PADT - PADB;

  const n = alerts.length;
  const xFor = (i: number) => {
    if (n <= 1) return PADL + innerW / 2;
    return PADL + (i / (n - 1)) * innerW;
  };
  const yFor = (s: number) => {
    const norm = (s - yBot) / yRange;
    return PADT + (1 - norm) * innerH;
  };

  const thresholdY = yFor(spec.threshold);
  const zeroY = yFor(0);

  const linePath =
    n > 0
      ? alerts
          .map((a, i) => {
            const x = xFor(i);
            const y = yFor(a.score);
            return `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
          })
          .join(" ")
      : "";

  const overThresholdCount = alerts.filter(
    (a) => a.score >= spec.threshold,
  ).length;
  const latest = alerts.length > 0 ? alerts[alerts.length - 1] : null;
  const latestOver = latest != null && latest.score >= spec.threshold;

  return (
    <div
      className={`rounded border p-3 ${
        latestOver
          ? "border-rose-500/40 bg-rose-500/5"
          : overThresholdCount > 0
            ? "border-amber-500/30 bg-amber-500/5"
            : "border-[#1f2a38] bg-[#0a0e14]"
      }`}
    >
      <div className="mb-2 flex items-center justify-between">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
            {spec.family}
          </div>
          <div className="mt-0.5 flex items-center gap-1 font-mono text-xs text-[#e4edf5]">
            <TrendingUp className="h-3 w-3 text-violet-400" />
            {spec.label}
          </div>
        </div>
        <div className="text-right">
          <div className="font-mono text-[9px] uppercase tracking-wider text-[#6b8196]">
            {spec.threshold_label}
          </div>
          <div className="font-mono text-xs text-amber-300">
            ≥ {spec.threshold.toFixed(2)}
          </div>
        </div>
      </div>

      {hasData ? (
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="h-[140px] w-full"
          role="img"
          aria-label={`${spec.label} score trace`}
        >
          {/* y-axis */}
          <line
            x1={PADL}
            y1={PADT}
            x2={PADL}
            y2={H - PADB}
            stroke="#1f2a38"
            strokeWidth={1}
          />
          {/* x-axis (at zero or bottom) */}
          <line
            x1={PADL}
            y1={Math.min(H - PADB, Math.max(PADT, zeroY))}
            x2={W - PADR}
            y2={Math.min(H - PADB, Math.max(PADT, zeroY))}
            stroke="#1f2a38"
            strokeWidth={1}
          />

          {/* threshold line */}
          <line
            x1={PADL}
            y1={thresholdY}
            x2={W - PADR}
            y2={thresholdY}
            stroke="#f59e0b"
            strokeWidth={1}
            strokeDasharray="4 3"
          />
          <text
            x={W - PADR}
            y={Math.max(PADT + 9, thresholdY - 3)}
            textAnchor="end"
            fontSize={9}
            fontFamily="ui-monospace, SFMono-Regular, monospace"
            fill="#f59e0b"
          >
            {spec.threshold_label} = {spec.threshold.toFixed(2)}
          </text>

          {/* y-axis ticks */}
          <text
            x={PADL - 4}
            y={PADT + 8}
            textAnchor="end"
            fontSize={9}
            fontFamily="ui-monospace, SFMono-Regular, monospace"
            fill="#6b8196"
          >
            {yTop.toFixed(1)}
          </text>
          <text
            x={PADL - 4}
            y={H - PADB + 2}
            textAnchor="end"
            fontSize={9}
            fontFamily="ui-monospace, SFMono-Regular, monospace"
            fill="#6b8196"
          >
            {yBot.toFixed(1)}
          </text>

          {/* score line */}
          {n > 1 && (
            <path
              d={linePath}
              fill="none"
              stroke="#8b5cf6"
              strokeWidth={1.25}
            />
          )}

          {/* score points, coloured by threshold crossing */}
          {alerts.map((a, i) => {
            const over = a.score >= spec.threshold;
            const sev = (a.severity || "").toLowerCase();
            const critical =
              sev === "critical" || sev === "alert" || sev === "high";
            const fill = over
              ? critical
                ? "#f43f5e"
                : "#f59e0b"
              : "#8b5cf6";
            return (
              <circle
                key={a.seq_no}
                cx={xFor(i)}
                cy={yFor(a.score)}
                r={over ? 2.8 : 2}
                fill={fill}
                stroke={over ? "#0a0e14" : "none"}
                strokeWidth={0.5}
              >
                <title>
                  seq #{a.seq_no} · score {a.score.toFixed(2)} · {a.severity}
                  {"\n"}
                  {a.detail}
                </title>
              </circle>
            );
          })}

          {/* x-axis label */}
          <text
            x={PADL + innerW / 2}
            y={H - 5}
            textAnchor="middle"
            fontSize={9}
            fontFamily="ui-monospace, SFMono-Regular, monospace"
            fill="#6b8196"
          >
            seq_no (chain order) · n={n}
          </text>
        </svg>
      ) : (
        <div className="flex h-[140px] items-center justify-center rounded border border-dashed border-[#1f2a38] font-mono text-[10px] text-[#4d617a]">
          no alerts for this detector in the chain
        </div>
      )}

      <div className="mt-2 grid grid-cols-3 gap-2 font-mono text-[10px]">
        <div className="rounded border border-[#1f2a38] bg-[#0a0e14] p-1.5">
          <div className="text-[9px] uppercase tracking-wider text-[#6b8196]">
            alerts
          </div>
          <div className="text-[#e4edf5]">{n}</div>
        </div>
        <div
          className={`rounded border p-1.5 ${
            overThresholdCount > 0
              ? "border-amber-500/40 bg-amber-500/5 text-amber-300"
              : "border-[#1f2a38] bg-[#0a0e14] text-[#e4edf5]"
          }`}
        >
          <div className="text-[9px] uppercase tracking-wider text-[#6b8196]">
            over thresh
          </div>
          <div>{overThresholdCount}</div>
        </div>
        <div
          className={`rounded border p-1.5 ${
            latestOver
              ? "border-rose-500/40 bg-rose-500/5 text-rose-300"
              : "border-[#1f2a38] bg-[#0a0e14] text-[#e4edf5]"
          }`}
        >
          <div className="text-[9px] uppercase tracking-wider text-[#6b8196]">
            latest score
          </div>
          <div>
            {latest ? latest.score.toFixed(2) : "—"}
          </div>
        </div>
      </div>

      <p className="mt-2 text-[10px] leading-snug text-[#6b8196]">
        {spec.description}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------

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
