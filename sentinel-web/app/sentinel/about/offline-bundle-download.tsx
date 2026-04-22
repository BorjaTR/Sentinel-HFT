"use client";

/**
 * Offline-bundle download button + manifest preview.
 *
 * Hits GET /api/export/offline-bundle/manifest first so the user sees
 * exactly what's in the zip before they click download. Then a real
 * anchor link drives GET /api/export/offline-bundle which responds
 * with a Content-Disposition: attachment and triggers the browser's
 * native save dialog.
 *
 * Notes:
 * - No third-party JS. The manifest is fetched with plain fetch().
 * - The download path is relative so it works behind any reverse
 *   proxy that mounts /api on the same origin as the Next.js UI.
 * - If the manifest fetch fails (server down), the component still
 *   renders the download button -- the user can always try the
 *   underlying endpoint; the manifest is a courtesy preview.
 */

import { useEffect, useMemo, useState } from "react";
import { Download, Package, FileText, Loader2, AlertTriangle } from "lucide-react";

interface ManifestEntry {
  name: string;
  size: number;
  compressed_size: number;
}

interface Manifest {
  total_bytes: number;
  entries: ManifestEntry[];
}

const API_BASE =
  process.env.NEXT_PUBLIC_SENTINEL_API_BASE ?? "http://localhost:8000";

function humanBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

function groupEntries(entries: ManifestEntry[]): Record<string, ManifestEntry[]> {
  const groups: Record<string, ManifestEntry[]> = {};
  for (const e of entries) {
    const slash = e.name.indexOf("/");
    const key = slash === -1 ? "(root)" : e.name.slice(0, slash);
    if (!groups[key]) groups[key] = [];
    groups[key].push(e);
  }
  return groups;
}

export function OfflineBundleDownload() {
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    (async () => {
      try {
        setLoading(true);
        const resp = await fetch(
          `${API_BASE}/api/export/offline-bundle/manifest`,
          { signal: ctrl.signal, cache: "no-store" },
        );
        if (!resp.ok) {
          throw new Error(`manifest HTTP ${resp.status}`);
        }
        const j = (await resp.json()) as Manifest;
        setManifest(j);
        setError(null);
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        setError((err as Error).message);
      } finally {
        setLoading(false);
      }
    })();
    return () => ctrl.abort();
  }, []);

  const groups = useMemo(
    () => (manifest ? groupEntries(manifest.entries) : {}),
    [manifest],
  );

  return (
    <div className="mt-5 rounded-lg border border-[#1a232e] bg-[#0f151d] p-5">
      <div className="flex flex-wrap items-center gap-4">
        <a
          href={`${API_BASE}/api/export/offline-bundle`}
          download="sentinel-hft-offline-bundle.zip"
          className="inline-flex items-center gap-2 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 text-sm font-semibold text-emerald-300 transition hover:border-emerald-400 hover:bg-emerald-500/20"
        >
          <Download className="h-4 w-4" />
          Download sentinel-hft-offline-bundle.zip
          {manifest ? (
            <span className="ml-1 font-mono text-xs font-normal text-emerald-200/80">
              ({humanBytes(manifest.total_bytes)})
            </span>
          ) : null}
        </a>
        <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-[#6b8196]">
          <Package className="h-3 w-3" />
          assembled on demand from the server source tree
        </div>
      </div>

      {loading ? (
        <div className="mt-5 flex items-center gap-2 text-xs text-[#6b8196]">
          <Loader2 className="h-3 w-3 animate-spin" />
          reading bundle manifest…
        </div>
      ) : error ? (
        <div className="mt-5 flex items-start gap-2 rounded-md border border-amber-900/40 bg-amber-950/20 p-3 text-xs text-amber-200/80">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
          <span>
            Could not fetch bundle manifest from{" "}
            <code className="font-mono">{API_BASE}</code>: {error}.
            The download link still works — the manifest is just a
            courtesy preview.
          </span>
        </div>
      ) : manifest ? (
        <div className="mt-5">
          <div className="mb-2 flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-sky-300">
            <FileText className="h-3 w-3" />
            Contents · {manifest.entries.length} files ·{" "}
            {humanBytes(manifest.total_bytes)} zipped
          </div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {Object.entries(groups).map(([group, entries]) => (
              <div
                key={group}
                className="rounded-md border border-[#1a232e] bg-[#080b10] p-3"
              >
                <div className="mb-2 font-mono text-[11px] font-semibold text-white">
                  {group === "(root)" ? "top-level" : `${group}/`}
                </div>
                <ul className="space-y-1">
                  {entries.map((e) => (
                    <li
                      key={e.name}
                      className="flex items-center justify-between font-mono text-[10px] text-[#9ab3c8]"
                    >
                      <span className="truncate">
                        {e.name.slice(
                          group === "(root)" ? 0 : group.length + 1,
                        )}
                      </span>
                      <span className="ml-3 shrink-0 text-[#4d617a]">
                        {humanBytes(e.size)}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
