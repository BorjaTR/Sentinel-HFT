"use client";

import { useEffect, useState } from "react";
import { Activity, FileText, Database } from "lucide-react";

// Provenance pill — listens to the global ``sentinel:source`` CustomEvent
// dispatched by lib/sentinel-api.ts on every backend round-trip and shows
// the user where the data on screen actually came from.
//
// Three states:
//   - "live"    : FastAPI backend reachable, data is from the running pipeline.
//   - "replay"  : FastAPI backend reachable, data is being replayed from a
//                 captured pcap (set when a drill is fired with ``--pcap``,
//                 wired in Phase 2).
//   - "fixture" : FastAPI unreachable, data is the deterministic in-memory
//                 fixture so the public Vercel deployment still demonstrates
//                 the full UX.
//
// The pill defaults to "fixture" until the first event arrives; that's the
// safe assumption because we don't know yet whether the backend is up.

type Source = "live" | "replay" | "fixture";

const STYLES: Record<Source, { dot: string; text: string; bg: string; border: string; label: string; icon: typeof Activity }> = {
  live: {
    dot: "bg-emerald-400 animate-pulse",
    text: "text-emerald-300",
    bg: "bg-emerald-500/10",
    border: "border-emerald-500/30",
    label: "LIVE",
    icon: Activity,
  },
  replay: {
    dot: "bg-sky-400",
    text: "text-sky-300",
    bg: "bg-sky-500/10",
    border: "border-sky-500/30",
    label: "REPLAY",
    icon: FileText,
  },
  fixture: {
    dot: "bg-amber-400",
    text: "text-amber-300",
    bg: "bg-amber-500/10",
    border: "border-amber-500/30",
    label: "FIXTURE",
    icon: Database,
  },
};

interface ProvenanceDetail {
  source: Source;
  reason?: string;
}

export function ProvenancePill({ compact = false }: { compact?: boolean }) {
  const [source, setSource] = useState<Source>("fixture");
  const [reason, setReason] = useState<string | undefined>(undefined);

  useEffect(() => {
    const handler = (ev: Event) => {
      const detail = (ev as CustomEvent<ProvenanceDetail>).detail;
      if (!detail || !detail.source) return;
      setSource(detail.source);
      setReason(detail.reason);
    };
    window.addEventListener("sentinel:source", handler as EventListener);
    return () =>
      window.removeEventListener("sentinel:source", handler as EventListener);
  }, []);

  const style = STYLES[source];
  const Icon = style.icon;

  return (
    <div
      className={`inline-flex items-center gap-2 rounded-full border px-2.5 py-1 ${style.bg} ${style.border}`}
      title={reason ?? `Data source: ${style.label.toLowerCase()}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} />
      <Icon className={`h-3 w-3 ${style.text}`} />
      {!compact && (
        <span
          className={`font-mono text-[10px] font-semibold tracking-wider ${style.text}`}
        >
          {style.label}
        </span>
      )}
    </div>
  );
}
