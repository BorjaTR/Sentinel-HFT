"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Brain,
  Calendar,
  RefreshCw,
  Sparkles,
  AlertTriangle,
  CheckCircle2,
  FileText,
  Hash,
  Database,
  Cpu,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  getRcaDetail,
  getRcaList,
  runRcaDigest,
} from "@/lib/sentinel-api";
import type {
  DigestDetail,
  DigestSummary,
} from "@/lib/sentinel-types";

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function shortHash(h: string | null | undefined): string {
  if (!h) return "—";
  return h.length > 12 ? `${h.slice(0, 8)}…${h.slice(-4)}` : h;
}

function backendTone(backend: string): string {
  const b = (backend || "").toLowerCase();
  if (b === "anthropic") return "border-violet-500/40 text-violet-300 bg-violet-500/5";
  if (b === "template") return "border-emerald-500/40 text-emerald-300 bg-emerald-500/5";
  return "border-[#1f2a38] text-[#9ab3c8] bg-[#0f151d]";
}

export default function RcaDashboardPage() {
  const [list, setList] = useState<DigestSummary[]>([]);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [detail, setDetail] = useState<DigestDetail | null>(null);
  const [listing, setListing] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const [runDate, setRunDate] = useState<string>(todayIso());
  const [runBackend, setRunBackend] = useState<string>("template");
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<{
    date: string;
    backend: string;
    anomaly_count: number;
  } | null>(null);

  const [error, setError] = useState<string | null>(null);

  const refreshList = useCallback(async () => {
    setListing(true);
    setError(null);
    try {
      const rows = await getRcaList();
      setList(rows);
      // Auto-select newest if nothing selected (or selection vanished).
      if (rows.length > 0) {
        const stillThere =
          selectedDate && rows.some((r) => r.date === selectedDate);
        if (!stillThere) setSelectedDate(rows[0].date);
      } else {
        setSelectedDate(null);
        setDetail(null);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setListing(false);
    }
  }, [selectedDate]);

  useEffect(() => {
    refreshList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load detail when selection changes.
  useEffect(() => {
    if (!selectedDate) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setLoadingDetail(true);
    getRcaDetail(selectedDate)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoadingDetail(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedDate]);

  async function doRun() {
    setRunning(true);
    setError(null);
    setRunResult(null);
    try {
      const r = await runRcaDigest({ date: runDate, backend: runBackend });
      setRunResult({
        date: r.date,
        backend: r.backend,
        anomaly_count: r.anomaly_count,
      });
      await refreshList();
      setSelectedDate(r.date);
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  }

  const anomalies = useMemo(() => {
    const feats = (detail?.features ?? {}) as Record<string, unknown>;
    const raw = feats["anomalies"];
    if (!Array.isArray(raw)) return [] as Array<Record<string, unknown>>;
    return raw as Array<Record<string, unknown>>;
  }, [detail]);

  const aggregate = useMemo(() => {
    const feats = (detail?.features ?? {}) as Record<string, unknown>;
    const agg = feats["aggregate"];
    return (agg && typeof agg === "object" ? (agg as Record<string, unknown>) : null);
  }, [detail]);

  return (
    <div className="max-w-7xl">
      <header className="mb-6">
        <div className="font-mono text-xs uppercase tracking-widest text-[#4d617a]">
          tool · ai
        </div>
        <h1 className="mt-1 flex items-center gap-2 text-2xl font-semibold text-[#e4edf5]">
          <Brain className="h-6 w-6 text-emerald-400" />
          Nightly RCA digest
        </h1>
        <p className="mt-2 max-w-3xl text-xs text-[#9ab3c8]">
          Workstream 4 — every drill artifact under{" "}
          <span className="font-mono text-[#e4edf5]">out/hl/</span> is
          rolled up into a deterministic feature pack and rendered as a
          Markdown root-cause digest. The{" "}
          <span className="font-mono">template</span> backend produces the
          same bytes from the same inputs (no API key required); switch to{" "}
          <span className="font-mono">anthropic</span> when{" "}
          <span className="font-mono">ANTHROPIC_API_KEY</span> is set.
        </p>
      </header>

      {error && (
        <div className="mb-4 rounded border border-rose-900/60 bg-rose-950/40 p-3 font-mono text-xs text-rose-200">
          {error}
        </div>
      )}

      {/* Run row */}
      <Card className="mb-6 border-[#1a232e] bg-[#0f151d]">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
            <Sparkles className="h-3.5 w-3.5 text-emerald-400" />
            Generate digest on demand
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_1fr_auto]">
            <div>
              <Label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
                date (ISO)
              </Label>
              <Input
                type="date"
                value={runDate}
                onChange={(e) => setRunDate(e.target.value)}
                className="border-[#1f2a38] bg-[#0a0e14] font-mono text-xs text-[#e4edf5]"
                disabled={running}
              />
            </div>
            <div>
              <Label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
                backend
              </Label>
              <select
                value={runBackend}
                onChange={(e) => setRunBackend(e.target.value)}
                disabled={running}
                className="h-9 w-full rounded-md border border-[#1f2a38] bg-[#0a0e14] px-3 font-mono text-xs text-[#e4edf5] focus:outline-none focus:ring-1 focus:ring-emerald-400/40"
              >
                <option value="template">template (deterministic)</option>
                <option value="anthropic">anthropic (LLM)</option>
                <option value="auto">auto (anthropic → template fallback)</option>
              </select>
            </div>
            <div className="flex items-end gap-2">
              <Button
                onClick={doRun}
                disabled={running || !runDate}
                size="sm"
                className="bg-emerald-500 font-mono text-xs text-[#0a0e14] hover:bg-emerald-400 disabled:opacity-40"
              >
                <Sparkles className="mr-1 h-3 w-3" />
                {running ? "generating…" : "run digest"}
              </Button>
              <Button
                onClick={refreshList}
                disabled={listing}
                size="sm"
                variant="outline"
                className="border-[#1f2a38] bg-transparent font-mono text-xs text-[#9ab3c8] hover:bg-[#131c27] hover:text-[#e4edf5] disabled:opacity-40"
              >
                <RefreshCw className={`mr-1 h-3 w-3 ${listing ? "animate-spin" : ""}`} />
                refresh
              </Button>
            </div>
          </div>
          {runResult && (
            <div className="mt-3 rounded border border-emerald-500/30 bg-emerald-500/5 p-3 font-mono text-xs text-emerald-300">
              <CheckCircle2 className="mr-1 inline h-3.5 w-3.5" />
              wrote digest for{" "}
              <span className="text-emerald-200">{runResult.date}</span> via{" "}
              <span className="text-emerald-200">{runResult.backend}</span> ·{" "}
              <span className="text-emerald-200">{runResult.anomaly_count}</span>{" "}
              anomaly row(s)
            </div>
          )}
        </CardContent>
      </Card>

      {/* Two-column: list (left) + detail (right) */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
        {/* List */}
        <Card className="border-[#1a232e] bg-[#0f151d]">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
              <Calendar className="h-3.5 w-3.5 text-emerald-400" />
              Archived digests
              <span className="ml-auto text-[#4d617a]">{list.length}</span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            {list.length === 0 ? (
              <div className="rounded border border-[#1f2a38] bg-[#0a0e14] p-3 font-mono text-[11px] text-[#6b8196]">
                {listing ? "loading…" : "no digests yet — run one above."}
              </div>
            ) : (
              <ul className="flex flex-col gap-1">
                {list.map((row) => {
                  const isSel = row.date === selectedDate;
                  return (
                    <li key={row.date}>
                      <button
                        onClick={() => setSelectedDate(row.date)}
                        className={`w-full rounded-md border px-2 py-2 text-left font-mono text-[11px] transition ${
                          isSel
                            ? "border-emerald-500/40 bg-emerald-500/5 text-[#e4edf5]"
                            : "border-[#1f2a38] bg-[#0a0e14] text-[#9ab3c8] hover:border-[#2a3a4c] hover:text-[#e4edf5]"
                        }`}
                      >
                        <div className="flex items-baseline justify-between gap-2">
                          <span>{row.date}</span>
                          <span
                            className={`rounded border px-1.5 py-0 text-[9px] uppercase tracking-wider ${backendTone(
                              row.backend,
                            )}`}
                          >
                            {row.backend}
                          </span>
                        </div>
                        <div className="mt-0.5 flex items-center justify-between text-[10px] text-[#6b8196]">
                          <span>
                            <AlertTriangle className="mr-0.5 inline h-3 w-3 text-amber-400/80" />
                            {row.anomaly_count} anomalies
                          </span>
                          <span title={row.prompt_sha256 ?? ""}>
                            {shortHash(row.prompt_sha256)}
                          </span>
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </CardContent>
        </Card>

        {/* Detail */}
        <Card className="border-[#1a232e] bg-[#0f151d]">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
              <FileText className="h-3.5 w-3.5 text-emerald-400" />
              {selectedDate ? `digest · ${selectedDate}` : "no digest selected"}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {!selectedDate || loadingDetail ? (
              <div className="rounded border border-[#1f2a38] bg-[#0a0e14] p-4 font-mono text-[11px] text-[#6b8196]">
                {loadingDetail ? "loading…" : "select a date on the left."}
              </div>
            ) : detail ? (
              <div className="flex flex-col gap-4">
                {/* Meta strip */}
                <div className="grid grid-cols-2 gap-2 rounded-md border border-[#1f2a38] bg-[#0a0e14] p-3 font-mono text-[11px] md:grid-cols-4">
                  <Meta
                    icon={<Cpu className="h-3 w-3 text-emerald-400" />}
                    label="backend"
                    value={detail.backend}
                  />
                  <Meta
                    icon={<Sparkles className="h-3 w-3 text-emerald-400" />}
                    label="model"
                    value={detail.model ?? "—"}
                  />
                  <Meta
                    icon={<Hash className="h-3 w-3 text-emerald-400" />}
                    label="prompt_sha256"
                    value={shortHash(detail.prompt_sha256)}
                    title={detail.prompt_sha256}
                  />
                  <Meta
                    icon={<Database className="h-3 w-3 text-emerald-400" />}
                    label="schema"
                    value={detail.schema}
                  />
                </div>

                {/* Aggregate strip */}
                {aggregate && (
                  <div className="rounded-md border border-[#1f2a38] bg-[#0a0e14] p-3 font-mono text-[11px] text-[#9ab3c8]">
                    <div className="mb-1 text-[10px] uppercase tracking-wider text-[#6b8196]">
                      aggregate
                    </div>
                    <div className="grid grid-cols-1 gap-x-4 gap-y-1 md:grid-cols-3">
                      {Object.entries(aggregate).slice(0, 9).map(([k, v]) => (
                        <div key={k} className="flex items-baseline gap-2">
                          <span className="text-[#6b8196]">{k}</span>
                          <span className="truncate text-[#e4edf5]">
                            {typeof v === "object"
                              ? JSON.stringify(v)
                              : String(v)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Markdown body */}
                <div className="rounded-md border border-[#1f2a38] bg-[#0a0e14]">
                  <div className="border-b border-[#1f2a38] px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
                    digest.md
                  </div>
                  <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap p-4 font-mono text-[12px] leading-relaxed text-[#d5e0ea]">
{detail.markdown}
                  </pre>
                </div>

                {/* Anomalies table */}
                {anomalies.length > 0 && (
                  <div className="overflow-hidden rounded border border-amber-900/40">
                    <div className="bg-amber-950/40 px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider text-amber-300">
                      anomalies · {anomalies.length}
                    </div>
                    <table className="w-full font-mono text-[11px]">
                      <thead className="bg-amber-950/20 text-amber-200/80">
                        <tr>
                          <th className="px-3 py-1.5 text-left font-normal">drill</th>
                          <th className="px-3 py-1.5 text-left font-normal">kind</th>
                          <th className="px-3 py-1.5 text-left font-normal">severity</th>
                          <th className="px-3 py-1.5 text-left font-normal">detail</th>
                        </tr>
                      </thead>
                      <tbody>
                        {anomalies.map((a, i) => {
                          const drill = String(a["drill"] ?? "—");
                          const kind = String(a["kind"] ?? "—");
                          const severity = String(a["severity"] ?? "—");
                          const detailStr = String(a["detail"] ?? "");
                          const sevTone =
                            severity === "high" || severity === "critical"
                              ? "text-rose-300"
                              : severity === "warn" || severity === "medium"
                                ? "text-amber-300"
                                : "text-[#9ab3c8]";
                          return (
                            <tr
                              key={i}
                              className="border-t border-amber-900/30 hover:bg-amber-500/5"
                            >
                              <td className="px-3 py-1.5 text-[#e4edf5]">{drill}</td>
                              <td className="px-3 py-1.5 text-amber-100/90">{kind}</td>
                              <td className={`px-3 py-1.5 ${sevTone}`}>{severity}</td>
                              <td className="px-3 py-1.5 text-[#9ab3c8]">{detailStr}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* Footer meta */}
                <div className="font-mono text-[10px] text-[#4d617a]">
                  generated_at: {detail.generated_at || "—"}
                </div>
              </div>
            ) : (
              <div className="rounded border border-rose-900/60 bg-rose-950/20 p-3 font-mono text-[11px] text-rose-300">
                failed to load digest
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Meta({
  icon,
  label,
  value,
  title,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  title?: string | null;
}) {
  return (
    <div className="flex items-center gap-2" title={title ?? undefined}>
      {icon}
      <span className="text-[#6b8196]">{label}</span>
      <span className="ml-auto truncate text-[#e4edf5]">{value}</span>
    </div>
  );
}
