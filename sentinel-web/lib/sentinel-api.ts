/**
 * Typed client for the Sentinel-HFT demo FastAPI router.
 *
 * Base URL comes from NEXT_PUBLIC_SENTINEL_API_URL (e.g. http://localhost:8000)
 * with a dev-safe fallback of http://127.0.0.1:8000.
 *
 * If the backend is unreachable (network error, CORS, 5xx, etc.) every
 * call falls back to a deterministic static fixture in
 * ``./sentinel-fixtures``. This keeps the public Vercel deployment
 * fully usable without a live FastAPI backend — the buttons still do
 * something meaningful, and the UI surfaces a small "fixture mode"
 * badge via the ``sentinel:source`` window event so pages can show
 * provenance to the user.
 */

import type {
  AlertChainView,
  AttributionView,
  ComplianceCrosswalkResponse,
  ComplianceSnapshot,
  DigestDetail,
  DigestSummary,
  DrillCatalog,
  DrillKind,
  ProposedPatchView,
  RcaCompareView,
  RcaPromptView,
  RiskGateConfig,
  RunDigestRequest,
  RunDigestResponse,
  TamperDemoResult,
  TriageEvalResponse,
  VerificationResult,
  WsEvent,
} from "./sentinel-types";

import {
  FIXTURE_COMPLIANCE_CROSSWALK,
  FIXTURE_COMPLIANCE_SNAPSHOT,
  FIXTURE_DRILL_CATALOG,
  FIXTURE_LIVE_COUNTER_KEYS,
  FIXTURE_RCA_ATTRIBUTION,
  FIXTURE_RCA_COMPARE,
  FIXTURE_RCA_DETAIL,
  FIXTURE_RCA_LIST,
  FIXTURE_RCA_PROMPT,
  FIXTURE_RCA_PROPOSED_PATCH,
  FIXTURE_RCA_RUN,
  FIXTURE_RISK_DEFAULTS,
  FIXTURE_TAMPER_DEMO,
  FIXTURE_TRIAGE_ALERTS,
  FIXTURE_TRIAGE_EVAL,
  FIXTURE_VERIFY_OK,
  fixtureReportFor,
  fixtureWsStream,
} from "./sentinel-fixtures";

const API_BASE =
  process.env.NEXT_PUBLIC_SENTINEL_API_URL ?? "http://127.0.0.1:8000";

const WS_BASE =
  API_BASE.replace(/^http/, "ws");

/** Fired whenever a request resolves so pages can surface "live" vs
 *  "replay" vs "fixture" provenance.
 *
 *  - "live"    — backend reachable, data is the running pipeline.
 *  - "replay"  — backend reachable, data is being replayed from a
 *                captured pcap (overrides.pcap was set on the request).
 *  - "fixture" — backend unreachable, deterministic in-memory fixture
 *                serves the UI so the public Vercel deployment still
 *                demonstrates the full UX.
 */
type Source = "live" | "replay" | "fixture";

function announceSource(source: Source, reason?: string): void {
  if (typeof window === "undefined") return;
  try {
    window.dispatchEvent(
      new CustomEvent("sentinel:source", { detail: { source, reason } }),
    );
  } catch {
    /* noop — old browsers without CustomEvent */
  }
}

/** True iff the overrides contain a non-empty pcap reference, in which
 *  case a successful backend round-trip is `replay` rather than `live`.
 *  Centralised so every entry point honours the same contract. */
function isReplayOverrides(overrides: Record<string, unknown> | undefined): boolean {
  if (!overrides) return false;
  const v = overrides.pcap;
  return typeof v === "string" && v.trim().length > 0;
}

/** Run ``fn``; if it throws (network / CORS / 5xx / abort) return the
 *  fixture instead and announce ``fixture`` provenance. The reason is
 *  included so consumers can debug. */
async function withFallback<T>(
  fn: () => Promise<T>,
  fallback: T,
  label: string,
  liveAs: Source = "live",
): Promise<T> {
  try {
    const result = await fn();
    announceSource(liveAs, label);
    return result;
  } catch (err) {
    announceSource("fixture", `${label}: ${(err as Error).message ?? err}`);
    return fallback;
  }
}

// ---- REST ---------------------------------------------------------------

export async function getDrillCatalog(): Promise<DrillCatalog> {
  return withFallback(
    async () => {
      const r = await fetch(`${API_BASE}/api/drills`, { cache: "no-store" });
      if (!r.ok) throw new Error(`getDrillCatalog: ${r.status}`);
      return r.json() as Promise<DrillCatalog>;
    },
    FIXTURE_DRILL_CATALOG,
    "getDrillCatalog",
  );
}

export async function getConfigDefaults(): Promise<RiskGateConfig> {
  return withFallback(
    async () => {
      const r = await fetch(`${API_BASE}/api/config/defaults`, { cache: "no-store" });
      if (!r.ok) throw new Error(`getConfigDefaults: ${r.status}`);
      return r.json() as Promise<RiskGateConfig>;
    },
    FIXTURE_RISK_DEFAULTS,
    "getConfigDefaults",
  );
}

export async function runDrill<R = Record<string, unknown>>(
  kind: DrillKind,
  overrides: Record<string, unknown> = {},
): Promise<{ drill: DrillKind; report: R }> {
  // pcap presence flips the announced provenance from "live" to "replay"
  // so the ProvenancePill flips its badge without the page caring.
  const liveAs: Source = isReplayOverrides(overrides) ? "replay" : "live";
  return withFallback(
    async () => {
      const r = await fetch(`${API_BASE}/api/drills/${kind}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(overrides),
      });
      if (!r.ok) throw new Error(`runDrill(${kind}): ${r.status} ${await r.text()}`);
      return r.json() as Promise<{ drill: DrillKind; report: R }>;
    },
    { drill: kind, report: fixtureReportFor(kind) as R },
    `runDrill(${kind})`,
    liveAs,
  );
}

export async function verifyAudit(file: File | Blob): Promise<VerificationResult> {
  return withFallback(
    async () => {
      const form = new FormData();
      form.append("file", file, (file as File).name ?? "audit.aud");
      const r = await fetch(`${API_BASE}/api/audit/verify`, { method: "POST", body: form });
      if (!r.ok) throw new Error(`verifyAudit: ${r.status} ${await r.text()}`);
      return r.json() as Promise<VerificationResult>;
    },
    {
      ...FIXTURE_VERIFY_OK,
      total_records: file.size > 0 ? Math.max(1, Math.floor(file.size / 192)) : FIXTURE_VERIFY_OK.total_records,
      verified_records: file.size > 0 ? Math.max(1, Math.floor(file.size / 192)) : FIXTURE_VERIFY_OK.verified_records,
    },
    "verifyAudit",
  );
}

export async function tamperDemo(
  file: File | Blob,
  recordIndex: number,
  byteOffset = 80,
): Promise<TamperDemoResult> {
  return withFallback(
    async () => {
      const form = new FormData();
      form.append("file", file, (file as File).name ?? "audit.aud");
      const qs = new URLSearchParams({
        record_index: String(recordIndex),
        byte_offset: String(byteOffset),
      });
      const r = await fetch(`${API_BASE}/api/audit/tamper-demo?${qs.toString()}`, {
        method: "POST",
        body: form,
      });
      if (!r.ok) throw new Error(`tamperDemo: ${r.status} ${await r.text()}`);
      return r.json() as Promise<TamperDemoResult>;
    },
    {
      ...FIXTURE_TAMPER_DEMO,
      tamper: {
        ...FIXTURE_TAMPER_DEMO.tamper,
        record_index: recordIndex,
        byte_offset: byteOffset,
        file_offset: recordIndex * 192 + byteOffset,
      },
      first_break_seq_no: recordIndex + 1,
    },
    "tamperDemo",
  );
}

// ---- Compliance (Workstream 3) ------------------------------------------

export async function getComplianceCrosswalk(): Promise<ComplianceCrosswalkResponse> {
  return withFallback(
    async () => {
      const r = await fetch(`${API_BASE}/api/compliance/crosswalk`, {
        cache: "no-store",
      });
      if (!r.ok) throw new Error(`getComplianceCrosswalk: ${r.status}`);
      return r.json() as Promise<ComplianceCrosswalkResponse>;
    },
    FIXTURE_COMPLIANCE_CROSSWALK,
    "getComplianceCrosswalk",
  );
}

export async function getLiveCounterKeys(): Promise<{ keys: string[] }> {
  return withFallback(
    async () => {
      const r = await fetch(`${API_BASE}/api/compliance/live-counter-keys`, {
        cache: "no-store",
      });
      if (!r.ok) throw new Error(`getLiveCounterKeys: ${r.status}`);
      return r.json() as Promise<{ keys: string[] }>;
    },
    FIXTURE_LIVE_COUNTER_KEYS,
    "getLiveCounterKeys",
  );
}

export async function getComplianceSnapshotShape(): Promise<ComplianceSnapshot> {
  return withFallback(
    async () => {
      const r = await fetch(`${API_BASE}/api/compliance/snapshot-shape`, {
        cache: "no-store",
      });
      if (!r.ok) throw new Error(`getComplianceSnapshotShape: ${r.status}`);
      return r.json() as Promise<ComplianceSnapshot>;
    },
    FIXTURE_COMPLIANCE_SNAPSHOT,
    "getComplianceSnapshotShape",
  );
}

// ---- AI agents (Workstream 4 RCA + Workstream 5 triage) ----------------

export async function getRcaList(): Promise<DigestSummary[]> {
  return withFallback(
    async () => {
      const r = await fetch(`${API_BASE}/api/ai/rca/list`, { cache: "no-store" });
      if (!r.ok) throw new Error(`getRcaList: ${r.status}`);
      return r.json() as Promise<DigestSummary[]>;
    },
    FIXTURE_RCA_LIST,
    "getRcaList",
  );
}

export async function getRcaDetail(isoDate: string): Promise<DigestDetail> {
  return withFallback(
    async () => {
      const r = await fetch(
        `${API_BASE}/api/ai/rca/${encodeURIComponent(isoDate)}`,
        { cache: "no-store" },
      );
      if (!r.ok) throw new Error(`getRcaDetail(${isoDate}): ${r.status}`);
      return r.json() as Promise<DigestDetail>;
    },
    { ...FIXTURE_RCA_DETAIL, date: isoDate },
    `getRcaDetail(${isoDate})`,
  );
}

export async function runRcaDigest(
  body: RunDigestRequest = {},
): Promise<RunDigestResponse> {
  return withFallback(
    async () => {
      const r = await fetch(`${API_BASE}/api/ai/rca/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error(`runRcaDigest: ${r.status} ${await r.text()}`);
      return r.json() as Promise<RunDigestResponse>;
    },
    { ...FIXTURE_RCA_RUN, date: body.date ?? FIXTURE_RCA_RUN.date },
    "runRcaDigest",
  );
}

export async function getRcaPrompt(isoDate: string): Promise<RcaPromptView> {
  return withFallback(
    async () => {
      const r = await fetch(
        `${API_BASE}/api/ai/rca/${encodeURIComponent(isoDate)}/prompt`,
        { cache: "no-store" },
      );
      if (!r.ok) throw new Error(`getRcaPrompt(${isoDate}): ${r.status}`);
      return r.json() as Promise<RcaPromptView>;
    },
    { ...FIXTURE_RCA_PROMPT, date: isoDate },
    `getRcaPrompt(${isoDate})`,
  );
}

export async function getProposedPatch(
  isoDate: string,
): Promise<ProposedPatchView> {
  return withFallback(
    async () => {
      const r = await fetch(
        `${API_BASE}/api/ai/rca/${encodeURIComponent(isoDate)}/proposed-patch`,
        { cache: "no-store" },
      );
      if (!r.ok) throw new Error(`getProposedPatch(${isoDate}): ${r.status}`);
      return r.json() as Promise<ProposedPatchView>;
    },
    { ...FIXTURE_RCA_PROPOSED_PATCH, date: isoDate },
    `getProposedPatch(${isoDate})`,
  );
}

export async function getRcaCompare(isoDate: string): Promise<RcaCompareView> {
  return withFallback(
    async () => {
      const r = await fetch(
        `${API_BASE}/api/ai/rca/${encodeURIComponent(isoDate)}/compare`,
        { cache: "no-store" },
      );
      if (!r.ok) throw new Error(`getRcaCompare(${isoDate}): ${r.status}`);
      return r.json() as Promise<RcaCompareView>;
    },
    { ...FIXTURE_RCA_COMPARE, date: isoDate },
    `getRcaCompare(${isoDate})`,
  );
}

/**
 * Phase 7 alpha attribution. Explains *why* the day's trading
 * outcome landed where it did, citing the exact drill fields and
 * audit seq_no ranges so a compliance engineer can chase the claim
 * back to raw artifacts without trusting the LLM.
 *
 * Lenses: fill-quality-vs-latency, reject-survival, and (only for
 * kill-drill runs) kill-survival blast radius.
 */
export async function getRcaAttribution(
  isoDate: string,
): Promise<AttributionView> {
  return withFallback(
    async () => {
      const r = await fetch(
        `${API_BASE}/api/ai/rca/${encodeURIComponent(isoDate)}/attribution`,
        { cache: "no-store" },
      );
      if (!r.ok) throw new Error(`getRcaAttribution(${isoDate}): ${r.status}`);
      return r.json() as Promise<AttributionView>;
    },
    { ...FIXTURE_RCA_ATTRIBUTION, date: isoDate },
    `getRcaAttribution(${isoDate})`,
  );
}

export async function getTriageAlerts(
  opts: { limit?: number } = {},
): Promise<AlertChainView> {
  return withFallback(
    async () => {
      const qs = new URLSearchParams();
      if (opts.limit != null) qs.set("limit", String(opts.limit));
      const url = `${API_BASE}/api/ai/triage/alerts${
        qs.toString() ? `?${qs.toString()}` : ""
      }`;
      const r = await fetch(url, { cache: "no-store" });
      if (!r.ok) throw new Error(`getTriageAlerts: ${r.status}`);
      return r.json() as Promise<AlertChainView>;
    },
    {
      ...FIXTURE_TRIAGE_ALERTS,
      alerts: opts.limit
        ? FIXTURE_TRIAGE_ALERTS.alerts.slice(0, opts.limit)
        : FIXTURE_TRIAGE_ALERTS.alerts,
    },
    "getTriageAlerts",
  );
}

export async function runTriageEval(): Promise<TriageEvalResponse> {
  return withFallback(
    async () => {
      const r = await fetch(`${API_BASE}/api/ai/triage/eval`, {
        method: "POST",
      });
      if (!r.ok) throw new Error(`runTriageEval: ${r.status} ${await r.text()}`);
      return r.json() as Promise<TriageEvalResponse>;
    },
    FIXTURE_TRIAGE_EVAL,
    "runTriageEval",
  );
}

export function artifactUrl(
  kind: DrillKind,
  filename: string,
  outputRoot?: string,
): string {
  const qs = outputRoot
    ? `?output_root=${encodeURIComponent(outputRoot)}`
    : "";
  return `${API_BASE}/api/artifacts/${kind}/${encodeURIComponent(filename)}${qs}`;
}

// ---- WebSocket ----------------------------------------------------------

export interface DrillStreamHandlers {
  onEvent?: (event: WsEvent) => void;
  onOpen?: () => void;
  onClose?: (ev: CloseEvent) => void;
  onError?: (ev: Event) => void;
}

/**
 * Open a WebSocket to /api/drills/{kind}/stream, push the config
 * overrides as the first message, and forward every typed event to
 * ``handlers.onEvent``.
 *
 * If the WebSocket fails to open (or errors before the start frame),
 * fall back to a deterministic in-memory replay of frames so the UI
 * still animates and shows a complete drill outcome.
 *
 * Returns a handle with a ``.close()`` function.
 */
export function streamDrill(
  kind: DrillKind,
  overrides: Record<string, unknown>,
  handlers: DrillStreamHandlers,
): { close: () => void; socket: WebSocket | null } {
  // Browsers without a running ws server resolve quickly to "error".
  // We race the socket against a 1.5s timeout: if the socket hasn't
  // opened by then OR an error fires first, kick over to fixtures.
  let fallbackHandle: { close: () => void } | null = null;
  let socket: WebSocket | null = null;
  let switchedToFixture = false;
  let opened = false;

  const startFixtureFallback = (reason: string) => {
    if (switchedToFixture) return;
    switchedToFixture = true;
    announceSource("fixture", `streamDrill(${kind}): ${reason}`);
    fallbackHandle = fixtureWsStream(kind, {
      onOpen: handlers.onOpen,
      onEvent: handlers.onEvent,
      onClose: () =>
        handlers.onClose?.({ code: 1000, reason: "fixture", wasClean: true } as unknown as CloseEvent),
    });
  };

  try {
    const url = `${WS_BASE}/api/drills/${kind}/stream`;
    socket = new WebSocket(url);

    const openTimer = setTimeout(() => {
      if (!opened) {
        try {
          socket?.close();
        } catch {
          /* noop */
        }
        startFixtureFallback("ws open timeout (1.5s)");
      }
    }, 1500);

    socket.addEventListener("open", () => {
      opened = true;
      clearTimeout(openTimer);
      // If the start frame carries a pcap path the backend replays a
      // captured run instead of generating fresh ticks — surface that
      // distinction up to the ProvenancePill so the operator can see at
      // a glance whether the chart they're watching is live ingest or
      // bit-for-bit replay of an earlier capture.
      const liveAs: Source = isReplayOverrides(overrides) ? "replay" : "live";
      announceSource(liveAs, `streamDrill(${kind})`);
      try {
        socket?.send(JSON.stringify(overrides));
      } catch {
        /* noop */
      }
      handlers.onOpen?.();
    });
    socket.addEventListener("message", (ev) => {
      try {
        const parsed = JSON.parse(ev.data as string) as WsEvent;
        handlers.onEvent?.(parsed);
      } catch {
        // Ignore malformed frames; the server never sends them.
      }
    });
    socket.addEventListener("close", (ev) => {
      clearTimeout(openTimer);
      if (!opened && !switchedToFixture) {
        startFixtureFallback(`ws closed before open (code ${ev.code})`);
      } else {
        handlers.onClose?.(ev);
      }
    });
    socket.addEventListener("error", (ev) => {
      clearTimeout(openTimer);
      if (!opened && !switchedToFixture) {
        startFixtureFallback("ws error before open");
      } else {
        handlers.onError?.(ev);
      }
    });
  } catch (err) {
    startFixtureFallback(`ws constructor threw: ${(err as Error).message ?? err}`);
  }

  return {
    close: () => {
      try {
        socket?.close();
      } catch {
        /* noop */
      }
      fallbackHandle?.close();
    },
    socket,
  };
}

export const SENTINEL_API_BASE = API_BASE;

/** True iff the env var has been set explicitly to a non-default URL.
 *  Useful for pages that want to show "fixture-only" banners. */
export const SENTINEL_API_CONFIGURED =
  Boolean(process.env.NEXT_PUBLIC_SENTINEL_API_URL) &&
  process.env.NEXT_PUBLIC_SENTINEL_API_URL !== "http://127.0.0.1:8000";
