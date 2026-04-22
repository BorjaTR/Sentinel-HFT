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
  Eye,
  EyeOff,
  Shield,
  GitCompare,
  FileDiff,
  FileCode,
  Activity,
  ShieldCheck,
  ShieldAlert,
  XCircle,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  getProposedPatch,
  getRcaAttribution,
  getRcaCompare,
  getRcaDetail,
  getRcaList,
  getRcaPrompt,
  runRcaDigest,
} from "@/lib/sentinel-api";
import type {
  AttributionRecordView,
  AttributionView,
  ConfigPatchOp,
  DigestDetail,
  DigestSummary,
  ProposedPatchView,
  RcaCompareView,
  RcaPromptView,
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

/** Simple line-by-line diff. Tags each line as `same` / `add` (only in
 *  live) / `del` (only in deterministic). We don't do a full Myers
 *  diff — anchor-and-walk is enough for the Markdown side-by-side
 *  because headers and bullet points line up in the typical case.
 */
type DiffLine = { tag: "same" | "add" | "del"; text: string };

function lineDiff(aTxt: string, bTxt: string): DiffLine[] {
  const a = aTxt.split("\n");
  const b = bTxt.split("\n");
  const aSet = new Set(a);
  const bSet = new Set(b);
  const out: DiffLine[] = [];
  // Walk two pointers, emitting same / del / add.
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) {
      out.push({ tag: "same", text: a[i] });
      i++;
      j++;
      continue;
    }
    // Line a[i] is not at b[j]: if it exists somewhere in b, emit
    // b[j] as `add` (prose only in live). Otherwise emit a[i] as `del`
    // (prose only in deterministic).
    if (j < b.length && !aSet.has(b[j])) {
      out.push({ tag: "add", text: b[j] });
      j++;
      continue;
    }
    if (i < a.length && !bSet.has(a[i])) {
      out.push({ tag: "del", text: a[i] });
      i++;
      continue;
    }
    // Both lines exist on the other side but out of order — advance both.
    if (i < a.length) {
      out.push({ tag: "del", text: a[i] });
      i++;
    }
    if (j < b.length) {
      out.push({ tag: "add", text: b[j] });
      j++;
    }
  }
  return out;
}

function valuePreview(v: unknown): string {
  if (v === null || v === undefined) return "null";
  if (typeof v === "string") return `"${v}"`;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

export default function RcaDashboardPage() {
  const [list, setList] = useState<DigestSummary[]>([]);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [detail, setDetail] = useState<DigestDetail | null>(null);
  const [prompt, setPrompt] = useState<RcaPromptView | null>(null);
  const [compare, setCompare] = useState<RcaCompareView | null>(null);
  const [patch, setPatch] = useState<ProposedPatchView | null>(null);
  const [attribution, setAttribution] = useState<AttributionView | null>(null);
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

  const [promptOpen, setPromptOpen] = useState(false);
  const [diffOpen, setDiffOpen] = useState(true);

  const [error, setError] = useState<string | null>(null);

  const refreshList = useCallback(async () => {
    setListing(true);
    setError(null);
    try {
      const rows = await getRcaList();
      setList(rows);
      if (rows.length > 0) {
        const stillThere =
          selectedDate && rows.some((r) => r.date === selectedDate);
        if (!stillThere) setSelectedDate(rows[0].date);
      } else {
        setSelectedDate(null);
        setDetail(null);
        setPrompt(null);
        setCompare(null);
        setPatch(null);
        setAttribution(null);
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

  // Load detail + prompt + compare + patch + attribution when selection changes.
  useEffect(() => {
    if (!selectedDate) {
      setDetail(null);
      setPrompt(null);
      setCompare(null);
      setPatch(null);
      setAttribution(null);
      return;
    }
    let cancelled = false;
    setLoadingDetail(true);
    Promise.all([
      getRcaDetail(selectedDate),
      getRcaPrompt(selectedDate),
      getRcaCompare(selectedDate),
      getProposedPatch(selectedDate),
      getRcaAttribution(selectedDate),
    ])
      .then(([d, p, c, pt, att]) => {
        if (cancelled) return;
        setDetail(d);
        setPrompt(p);
        setCompare(c);
        setPatch(pt);
        setAttribution(att);
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

  const diffLines = useMemo(() => {
    if (!compare) return [] as DiffLine[];
    if (compare.identical) return [];
    // First arg is "from" (deterministic); lines only in the second
    // arg ("live") are marked as `add` — LLM prose added on top of
    // the template baseline.
    return lineDiff(compare.deterministic_markdown, compare.live_markdown);
  }, [compare]);

  return (
    <div className="max-w-7xl">
      <header className="mb-6">
        <div className="font-mono text-xs uppercase tracking-widest text-[#4d617a]">
          workstream 4 · ai agent visibility · trading-desk / compliance view
        </div>
        <h1 className="mt-1 flex items-center gap-2 text-2xl font-semibold text-[#e4edf5]">
          <Brain className="h-6 w-6 text-emerald-400" />
          Nightly RCA digest
        </h1>
        <p className="mt-2 max-w-3xl text-xs text-[#9ab3c8]">
          Every drill artifact under{" "}
          <span className="font-mono text-[#e4edf5]">out/hl/</span> is rolled
          up into a deterministic feature pack. The page shows{" "}
          <span className="font-mono">(a)</span> the archived digest,{" "}
          <span className="font-mono">(b)</span> the exact prompt bytes and
          sha256 that were sent,{" "}
          <span className="font-mono">(c)</span> a byte-level diff between the
          deterministic template and whatever the LLM actually produced, and{" "}
          <span className="font-mono">(d)</span> the review-only JSON patch
          the agent would propose. No patch is ever auto-applied.
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

                {/* Prompt viewer */}
                <PromptViewer
                  view={prompt}
                  open={promptOpen}
                  onToggle={() => setPromptOpen((v) => !v)}
                />

                {/* Deterministic vs LLM diff */}
                <CompareDiff
                  view={compare}
                  lines={diffLines}
                  open={diffOpen}
                  onToggle={() => setDiffOpen((v) => !v)}
                />

                {/* Proposed config changes */}
                <ProposedPatchPanel view={patch} />

                {/* Phase 7 alpha attribution — pipeline efficiency as
                 *  cited claims. */}
                <AttributionPanel view={attribution} />

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

/** Exact prompt viewer. Collapsed by default; shows sha256 match badge
 *  against the prompt_sha256 that was stored with the digest so drift
 *  (schema change, tampering) is visible at a glance. */
function PromptViewer({
  view,
  open,
  onToggle,
}: {
  view: RcaPromptView | null;
  open: boolean;
  onToggle: () => void;
}) {
  if (!view) {
    return (
      <div className="rounded-md border border-[#1f2a38] bg-[#0a0e14] p-3 font-mono text-[11px] text-[#6b8196]">
        loading prompt…
      </div>
    );
  }
  const hashMatches = view.prompt_sha256_matches_stored;
  return (
    <div className="rounded-md border border-[#1f2a38] bg-[#0a0e14]">
      <div className="flex items-center gap-2 border-b border-[#1f2a38] px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
        <FileCode className="h-3.5 w-3.5 text-emerald-400" />
        <span>prompt sent to {view.backend}</span>
        <span
          className={`ml-2 rounded border px-1.5 py-0 text-[9px] tracking-wider ${
            hashMatches
              ? "border-emerald-500/40 bg-emerald-500/5 text-emerald-300"
              : "border-rose-500/40 bg-rose-500/5 text-rose-300"
          }`}
          title={view.prompt_sha256}
        >
          sha256 {hashMatches ? "match" : "MISMATCH"} · {shortHash(view.prompt_sha256)}
        </span>
        <button
          onClick={onToggle}
          className="ml-auto flex items-center gap-1 rounded border border-[#1f2a38] bg-transparent px-2 py-0.5 text-[10px] text-[#9ab3c8] hover:bg-[#131c27] hover:text-[#e4edf5]"
        >
          {open ? (
            <>
              <EyeOff className="h-3 w-3" /> hide
            </>
          ) : (
            <>
              <Eye className="h-3 w-3" /> show
            </>
          )}
        </button>
      </div>
      {open && (
        <div className="p-3">
          <div className="mb-2 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
            template
          </div>
          <pre className="max-h-60 overflow-auto whitespace-pre-wrap rounded border border-[#1f2a38] bg-black/40 p-3 font-mono text-[11px] leading-relaxed text-[#d5e0ea]">
{view.prompt_template}
          </pre>
          <div className="mb-2 mt-4 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
            interpolated prompt (exact bytes)
          </div>
          <pre className="max-h-[40vh] overflow-auto whitespace-pre-wrap rounded border border-[#1f2a38] bg-black/40 p-3 font-mono text-[11px] leading-relaxed text-[#d5e0ea]">
{view.prompt}
          </pre>
        </div>
      )}
    </div>
  );
}

/** Side-by-side deterministic vs live Markdown diff. When identical,
 *  shows a single confirmation row. When backend=template this is
 *  always identical; when backend=anthropic it's where the LLM's
 *  contribution becomes visible. */
function CompareDiff({
  view,
  lines,
  open,
  onToggle,
}: {
  view: RcaCompareView | null;
  lines: DiffLine[];
  open: boolean;
  onToggle: () => void;
}) {
  if (!view) {
    return (
      <div className="rounded-md border border-[#1f2a38] bg-[#0a0e14] p-3 font-mono text-[11px] text-[#6b8196]">
        loading diff…
      </div>
    );
  }
  const added = lines.filter((l) => l.tag === "add").length;
  const removed = lines.filter((l) => l.tag === "del").length;
  return (
    <div className="rounded-md border border-[#1f2a38] bg-[#0a0e14]">
      <div className="flex flex-wrap items-center gap-2 border-b border-[#1f2a38] px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
        <GitCompare className="h-3.5 w-3.5 text-emerald-400" />
        <span>deterministic vs {view.backend}</span>
        {view.identical ? (
          <span className="ml-2 rounded border border-emerald-500/40 bg-emerald-500/5 px-1.5 py-0 text-[9px] tracking-wider text-emerald-300">
            identical bytes
          </span>
        ) : (
          <>
            <span className="ml-2 rounded border border-emerald-500/40 bg-emerald-500/5 px-1.5 py-0 text-[9px] tracking-wider text-emerald-300">
              +{added}
            </span>
            <span className="ml-1 rounded border border-rose-500/40 bg-rose-500/5 px-1.5 py-0 text-[9px] tracking-wider text-rose-300">
              −{removed}
            </span>
          </>
        )}
        <button
          onClick={onToggle}
          className="ml-auto flex items-center gap-1 rounded border border-[#1f2a38] bg-transparent px-2 py-0.5 text-[10px] text-[#9ab3c8] hover:bg-[#131c27] hover:text-[#e4edf5]"
        >
          {open ? (
            <>
              <EyeOff className="h-3 w-3" /> hide
            </>
          ) : (
            <>
              <FileDiff className="h-3 w-3" /> show
            </>
          )}
        </button>
      </div>
      {open && (
        <div className="grid grid-cols-1 gap-3 p-3 lg:grid-cols-2">
          <div>
            <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
              deterministic (template)
            </div>
            <pre className="h-[40vh] overflow-auto whitespace-pre-wrap rounded border border-[#1f2a38] bg-black/40 p-3 font-mono text-[11px] leading-relaxed text-[#d5e0ea]">
{view.deterministic_markdown}
            </pre>
          </div>
          <div>
            <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
              live ({view.backend})
            </div>
            <pre className="h-[40vh] overflow-auto whitespace-pre-wrap rounded border border-[#1f2a38] bg-black/40 p-3 font-mono text-[11px] leading-relaxed text-[#d5e0ea]">
{view.live_markdown}
            </pre>
          </div>
          {!view.identical && (
            <div className="lg:col-span-2">
              <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
                line-by-line diff · green = only in live · red = only in deterministic
              </div>
              <pre className="max-h-[30vh] overflow-auto whitespace-pre-wrap rounded border border-[#1f2a38] bg-black/40 p-3 font-mono text-[11px] leading-relaxed">
                {lines.map((l, i) => (
                  <div
                    key={i}
                    className={
                      l.tag === "add"
                        ? "bg-emerald-500/10 text-emerald-200"
                        : l.tag === "del"
                          ? "bg-rose-500/10 text-rose-200"
                          : "text-[#9ab3c8]"
                    }
                  >
                    {l.tag === "add" ? "+ " : l.tag === "del" ? "− " : "  "}
                    {l.text || "\u00a0"}
                  </div>
                ))}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Review-only JSON patch panel. Always renders a yellow "review-only,
 *  never auto-applied" badge and never wires a submit/apply button. */
function ProposedPatchPanel({ view }: { view: ProposedPatchView | null }) {
  if (!view) {
    return (
      <div className="rounded-md border border-[#1f2a38] bg-[#0a0e14] p-3 font-mono text-[11px] text-[#6b8196]">
        loading proposed patch…
      </div>
    );
  }
  return (
    <div className="rounded-md border border-amber-500/30 bg-amber-500/5">
      <div className="flex flex-wrap items-center gap-2 border-b border-amber-500/20 px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider text-amber-200/90">
        <Shield className="h-3.5 w-3.5 text-amber-300" />
        <span>proposed config changes · {view.patch.length} op(s)</span>
        <span
          className="ml-2 rounded border border-amber-400/50 bg-amber-400/10 px-1.5 py-0 text-[9px] tracking-wider text-amber-200"
          title="Proposed by the RCA agent. Never auto-applied. Requires operator sign-off."
        >
          review-only · never auto-applied
        </span>
        <span
          className="ml-auto font-mono text-[10px] text-amber-200/70"
          title={view.patch_hash_sha256}
        >
          hash {shortHash(view.patch_hash_sha256)}
        </span>
      </div>
      <div className="p-3">
        <div className="mb-3 font-mono text-[11px] text-amber-100/80">{view.summary}</div>
        {view.patch.length === 0 ? (
          <div className="rounded border border-[#1f2a38] bg-black/40 p-3 font-mono text-[11px] text-[#9ab3c8]">
            <CheckCircle2 className="mr-1 inline h-3.5 w-3.5 text-emerald-400" />
            No anomalies for this day — no configuration change proposed.
          </div>
        ) : (
          <>
            <div className="overflow-x-auto rounded border border-[#1f2a38]">
              <table className="w-full font-mono text-[11px]">
                <thead className="bg-black/40 text-[#6b8196]">
                  <tr>
                    <th className="px-3 py-1.5 text-left font-normal">op</th>
                    <th className="px-3 py-1.5 text-left font-normal">path</th>
                    <th className="px-3 py-1.5 text-left font-normal">value</th>
                    <th className="px-3 py-1.5 text-left font-normal">anomaly</th>
                  </tr>
                </thead>
                <tbody>
                  {view.patch.map((op, i) => (
                    <PatchRow key={i} op={op} />
                  ))}
                </tbody>
              </table>
            </div>
            <details className="mt-3 font-mono text-[11px] text-[#9ab3c8]">
              <summary className="cursor-pointer select-none text-[10px] uppercase tracking-wider text-[#6b8196] hover:text-[#e4edf5]">
                raw RFC-6902 patch (JSON)
              </summary>
              <pre className="mt-2 overflow-auto rounded border border-[#1f2a38] bg-black/40 p-3 text-[11px] leading-relaxed text-[#d5e0ea]">
{JSON.stringify(
  {
    schema: view.schema,
    date: view.date,
    review_only: view.review_only,
    patch: view.patch,
    patch_hash_sha256: view.patch_hash_sha256,
  },
  null,
  2,
)}
              </pre>
            </details>
          </>
        )}
      </div>
    </div>
  );
}

function PatchRow({ op }: { op: ConfigPatchOp }) {
  return (
    <tr className="border-t border-[#1f2a38] align-top hover:bg-[#131c27]">
      <td className="px-3 py-1.5 text-amber-200">
        <span className="rounded border border-amber-500/40 bg-amber-500/5 px-1.5 py-0 text-[9px] uppercase tracking-wider">
          {op.op}
        </span>
      </td>
      <td className="px-3 py-1.5 text-[#e4edf5]">{op.path}</td>
      <td className="px-3 py-1.5 text-emerald-200">{valuePreview(op.value)}</td>
      <td className="px-3 py-1.5 text-[#9ab3c8]">
        <div className="text-amber-300/80">{op.anomaly_kind}</div>
        <div className="mt-0.5 text-[10px] leading-relaxed text-[#9ab3c8]">
          {op.rationale}
        </div>
      </td>
    </tr>
  );
}

// ---- Phase 7 alpha attribution panel ------------------------------------
//
// Each AttributionRecord is a cited claim about *why* the trading day
// landed where it did. The UI contract is literal: every record gets a
// traffic-light (pass/fail/neutral), the exact headline from the
// deterministic pipeline, a collapsible "detail" paragraph, and the
// ``cited_records`` list verbatim in monospace so a compliance engineer
// can walk each claim back to the raw artifact (``<filename>::<field>=<value>``)
// without trusting the LLM. Nothing here is editorialised — the panel
// only lays out what ``_build_attribution`` produced.

/** Map an attribution ``kind`` to a human label and lens icon.
 *  Kept in sync with ``sentinel_hft/ai/rca_features.py::_build_attribution``.
 */
function attributionKindMeta(kind: string): {
  label: string;
  icon: React.ReactNode;
} {
  switch (kind) {
    case "fill_quality_vs_latency":
      return {
        label: "Fill quality vs latency",
        icon: <Activity className="h-3.5 w-3.5 text-sky-400" />,
      };
    case "reject_survival":
      return {
        label: "Reject survival",
        icon: <ShieldAlert className="h-3.5 w-3.5 text-amber-400" />,
      };
    case "kill_drill_survival":
      return {
        label: "Kill-switch blast radius",
        icon: <ShieldCheck className="h-3.5 w-3.5 text-rose-300" />,
      };
    default:
      return {
        label: kind,
        icon: <Activity className="h-3.5 w-3.5 text-[#9ab3c8]" />,
      };
  }
}

function formatAttributionValue(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  // All three attribution metrics today are ratios in [0, 1]; render
  // them as percentages so the ratio-vs-baseline comparison is literal.
  return `${(v * 100).toFixed(1)}%`;
}

function AttributionPanel({ view }: { view: AttributionView | null }) {
  if (!view) {
    return (
      <div className="rounded-md border border-[#1f2a38] bg-[#0a0e14] p-3 font-mono text-[11px] text-[#6b8196]">
        loading attribution…
      </div>
    );
  }
  const records = view.records ?? [];
  const hasAny = records.length > 0;
  return (
    <div className="rounded-md border border-sky-500/30 bg-sky-500/5">
      <div className="flex flex-wrap items-center gap-2 border-b border-sky-500/20 px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider text-sky-200/90">
        <Activity className="h-3.5 w-3.5 text-sky-300" />
        <span>pipeline efficiency attribution · {records.length} lens(es)</span>
        {hasAny && (
          <>
            <span
              className="ml-2 rounded border border-emerald-500/40 bg-emerald-500/5 px-1.5 py-0 text-[9px] tracking-wider text-emerald-300"
              title="Passing attribution lenses on this digest"
            >
              <CheckCircle2 className="mr-0.5 inline h-3 w-3" />
              {view.pass_count} pass
            </span>
            <span
              className="ml-1 rounded border border-rose-500/40 bg-rose-500/5 px-1.5 py-0 text-[9px] tracking-wider text-rose-300"
              title="Failing attribution lenses on this digest"
            >
              <XCircle className="mr-0.5 inline h-3 w-3" />
              {view.fail_count} fail
            </span>
          </>
        )}
        <span
          className="ml-auto rounded border border-sky-400/40 bg-sky-400/10 px-1.5 py-0 text-[9px] tracking-wider text-sky-200"
          title="Observational — the attribution pipeline never reshapes decisions, only cites the trace records that back each claim."
        >
          observation-only · every number cited
        </span>
      </div>
      <div className="p-3">
        {!hasAny ? (
          <div className="rounded border border-[#1f2a38] bg-black/40 p-3 font-mono text-[11px] text-[#9ab3c8]">
            <CheckCircle2 className="mr-1 inline h-3.5 w-3.5 text-emerald-400" />
            No drill features stored for this digest — attribution lenses
            have nothing to cite.
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3">
            {records.map((r, i) => (
              <AttributionCard key={i} rec={r} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function AttributionCard({ rec }: { rec: AttributionRecordView }) {
  const [open, setOpen] = useState(false);
  const meta = attributionKindMeta(rec.kind);
  const passes = rec.passes;
  const tone =
    passes === true
      ? {
          border: "border-emerald-500/40",
          bg: "bg-emerald-500/5",
          dotBg: "bg-emerald-500",
          pill:
            "border-emerald-500/40 bg-emerald-500/10 text-emerald-200",
          label: "pass",
        }
      : passes === false
        ? {
            border: "border-rose-500/40",
            bg: "bg-rose-500/5",
            dotBg: "bg-rose-500",
            pill: "border-rose-500/40 bg-rose-500/10 text-rose-200",
            label: "fail",
          }
        : {
            border: "border-[#1f2a38]",
            bg: "bg-[#0a0e14]",
            dotBg: "bg-[#4d617a]",
            pill: "border-[#1f2a38] bg-[#0f151d] text-[#9ab3c8]",
            label: "n/a",
          };
  return (
    <div className={`overflow-hidden rounded-md border ${tone.border} ${tone.bg}`}>
      <div className="flex flex-wrap items-center gap-2 border-b border-[#1f2a38]/60 px-3 py-1.5 font-mono text-[11px]">
        <span
          aria-hidden="true"
          className={`inline-block h-2.5 w-2.5 rounded-full ${tone.dotBg}`}
          title={`attribution verdict: ${tone.label}`}
        />
        {meta.icon}
        <span className="font-semibold text-[#e4edf5]">{meta.label}</span>
        <span className="text-[#6b8196]">·</span>
        <span className="text-[#9ab3c8]">{rec.drill}</span>
        <span className="text-[#6b8196]">·</span>
        <span className="text-[#9ab3c8]">{rec.metric}</span>
        <span className="ml-auto flex items-center gap-2">
          {(rec.value !== null && rec.value !== undefined) && (
            <span
              className="rounded border border-[#1f2a38] bg-black/40 px-1.5 py-0 text-[10px] text-[#e4edf5]"
              title={`value=${rec.value}${
                rec.baseline !== null && rec.baseline !== undefined
                  ? ` baseline=${rec.baseline}`
                  : ""
              }`}
            >
              {formatAttributionValue(rec.value)}
              {rec.baseline !== null && rec.baseline !== undefined ? (
                <span className="ml-1 text-[#6b8196]">
                  / {formatAttributionValue(rec.baseline)}
                </span>
              ) : null}
            </span>
          )}
          <span
            className={`rounded border px-1.5 py-0 text-[9px] uppercase tracking-wider ${tone.pill}`}
          >
            {tone.label}
          </span>
          <button
            onClick={() => setOpen((v) => !v)}
            className="flex items-center gap-1 rounded border border-[#1f2a38] bg-transparent px-2 py-0.5 text-[10px] text-[#9ab3c8] hover:bg-[#131c27] hover:text-[#e4edf5]"
          >
            {open ? (
              <>
                <ChevronDown className="h-3 w-3" /> hide
              </>
            ) : (
              <>
                <ChevronRight className="h-3 w-3" /> detail
              </>
            )}
          </button>
        </span>
      </div>
      <div className="px-3 py-2 font-mono text-[11px] text-[#e4edf5]">
        {rec.headline || "—"}
      </div>
      {open && (
        <div className="border-t border-[#1f2a38]/60 p-3">
          {rec.detail && (
            <>
              <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
                detail
              </div>
              <pre className="mb-3 whitespace-pre-wrap rounded border border-[#1f2a38] bg-black/40 p-3 font-mono text-[11px] leading-relaxed text-[#d5e0ea]">
{rec.detail}
              </pre>
            </>
          )}
          <div className="mb-1 flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
            <FileCode className="h-3 w-3 text-sky-400" />
            <span>cited records · {rec.cited_records.length}</span>
            <span className="text-[#4d617a]">— every claim traces back to a raw artifact</span>
          </div>
          {rec.cited_records.length === 0 ? (
            <div className="rounded border border-[#1f2a38] bg-black/40 p-3 font-mono text-[11px] text-[#6b8196]">
              (no citations — this lens skipped)
            </div>
          ) : (
            <ul className="flex flex-col gap-1">
              {rec.cited_records.map((c, i) => (
                <li
                  key={i}
                  className="rounded border border-[#1f2a38] bg-black/40 px-2 py-1 font-mono text-[11px] leading-relaxed text-[#d5e0ea]"
                >
                  {c}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
