"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Hash, ShieldCheck, ChevronRight } from "lucide-react";
import { ProvenancePill } from "./ProvenancePill";
import { getTriageAlerts } from "@/lib/sentinel-api";

// HeadHashBanner — sticky banner that surfaces the most recent BLAKE2b
// chain head hash so any operator landing on any page can immediately
// see which run they're looking at and whether the chain is intact.
//
// "Head hash" is the BLAKE2b commitment over the last committed
// record; a regulator-acceptable single-string proof that the run
// hasn't been retroactively altered. We currently pull it from the
// triage alert chain because /api/ai/triage/alerts is the cheapest
// always-on endpoint that returns a chain head + chain_ok. A
// dedicated /api/audit/head endpoint backed by the risk audit chain
// is a follow-up — when added, swap the import below and nothing
// else needs to change.
//
// If no backend is reachable, the fixture sidecar chain is used and
// the provenance pill flips to "fixture" automatically.

export function HeadHashBanner() {
  const [headHash, setHeadHash] = useState<string | null>(null);
  const [chainOk, setChainOk] = useState<boolean>(true);
  const [nRecords, setNRecords] = useState<number>(0);

  useEffect(() => {
    let cancelled = false;
    getTriageAlerts({ limit: 1 })
      .then((view) => {
        if (cancelled || !view) return;
        setHeadHash(view.head_hash_lo ?? null);
        setChainOk(view.chain_ok ?? true);
        setNRecords(view.n_records ?? 0);
      })
      .catch(() => {
        /* withFallback already emits a fixture provenance event */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const shortHash = headHash
    ? `${headHash.slice(0, 8)}…${headHash.slice(-8)}`
    : "no chain yet";

  return (
    <div className="flex items-center gap-3 rounded-md border border-[#1a232e] bg-[#0f151d] px-3 py-1.5 font-mono text-xs">
      <ShieldCheck
        className={`h-3.5 w-3.5 ${
          chainOk ? "text-emerald-400" : "text-rose-400"
        }`}
      />
      <span className="text-[#6b8196]">Head hash</span>
      <Link
        href="/sentinel/audit"
        className="group flex items-center gap-1 text-[#d5e0ea] hover:text-emerald-400"
      >
        <Hash className="h-3 w-3 text-[#4d617a] group-hover:text-emerald-400" />
        <span className="text-[11px]">{shortHash}</span>
        <ChevronRight className="h-3 w-3 opacity-0 transition group-hover:opacity-100" />
      </Link>
      {nRecords > 0 && (
        <span className="text-[#4d617a]">· {nRecords.toLocaleString()} rec</span>
      )}
      <span className="text-[#1f2a38]">·</span>
      <ProvenancePill />
    </div>
  );
}
