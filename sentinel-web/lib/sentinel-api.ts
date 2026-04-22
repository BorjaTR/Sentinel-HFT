/**
 * Typed client for the Sentinel-HFT demo FastAPI router.
 *
 * Base URL comes from NEXT_PUBLIC_SENTINEL_API_URL (e.g. http://localhost:8000)
 * with a dev-safe fallback of http://127.0.0.1:8000.
 */

import type {
  AlertChainView,
  ComplianceCrosswalkResponse,
  ComplianceSnapshot,
  DigestDetail,
  DigestSummary,
  DrillCatalog,
  DrillKind,
  RiskGateConfig,
  RunDigestRequest,
  RunDigestResponse,
  TamperDemoResult,
  TriageEvalResponse,
  VerificationResult,
  WsEvent,
} from "./sentinel-types";

const API_BASE =
  process.env.NEXT_PUBLIC_SENTINEL_API_URL ?? "http://127.0.0.1:8000";

const WS_BASE =
  API_BASE.replace(/^http/, "ws");

// ---- REST ---------------------------------------------------------------

export async function getDrillCatalog(): Promise<DrillCatalog> {
  const r = await fetch(`${API_BASE}/api/drills`, { cache: "no-store" });
  if (!r.ok) throw new Error(`getDrillCatalog: ${r.status}`);
  return r.json();
}

export async function getConfigDefaults(): Promise<RiskGateConfig> {
  const r = await fetch(`${API_BASE}/api/config/defaults`, { cache: "no-store" });
  if (!r.ok) throw new Error(`getConfigDefaults: ${r.status}`);
  return r.json();
}

export async function runDrill<R = Record<string, unknown>>(
  kind: DrillKind,
  overrides: Record<string, unknown> = {},
): Promise<{ drill: DrillKind; report: R }> {
  const r = await fetch(`${API_BASE}/api/drills/${kind}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(overrides),
  });
  if (!r.ok) throw new Error(`runDrill(${kind}): ${r.status} ${await r.text()}`);
  return r.json();
}

export async function verifyAudit(file: File | Blob): Promise<VerificationResult> {
  const form = new FormData();
  form.append("file", file, (file as File).name ?? "audit.aud");
  const r = await fetch(`${API_BASE}/api/audit/verify`, { method: "POST", body: form });
  if (!r.ok) throw new Error(`verifyAudit: ${r.status} ${await r.text()}`);
  return r.json();
}

export async function tamperDemo(
  file: File | Blob,
  recordIndex: number,
  byteOffset = 80,
): Promise<TamperDemoResult> {
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
  return r.json();
}

// ---- Compliance (Workstream 3) ------------------------------------------

export async function getComplianceCrosswalk(): Promise<ComplianceCrosswalkResponse> {
  const r = await fetch(`${API_BASE}/api/compliance/crosswalk`, {
    cache: "no-store",
  });
  if (!r.ok) throw new Error(`getComplianceCrosswalk: ${r.status}`);
  return r.json();
}

export async function getLiveCounterKeys(): Promise<{ keys: string[] }> {
  const r = await fetch(`${API_BASE}/api/compliance/live-counter-keys`, {
    cache: "no-store",
  });
  if (!r.ok) throw new Error(`getLiveCounterKeys: ${r.status}`);
  return r.json();
}

export async function getComplianceSnapshotShape(): Promise<ComplianceSnapshot> {
  const r = await fetch(`${API_BASE}/api/compliance/snapshot-shape`, {
    cache: "no-store",
  });
  if (!r.ok) throw new Error(`getComplianceSnapshotShape: ${r.status}`);
  return r.json();
}

// ---- AI agents (Workstream 4 RCA + Workstream 5 triage) ----------------

export async function getRcaList(): Promise<DigestSummary[]> {
  const r = await fetch(`${API_BASE}/api/ai/rca/list`, { cache: "no-store" });
  if (!r.ok) throw new Error(`getRcaList: ${r.status}`);
  return r.json();
}

export async function getRcaDetail(isoDate: string): Promise<DigestDetail> {
  const r = await fetch(
    `${API_BASE}/api/ai/rca/${encodeURIComponent(isoDate)}`,
    { cache: "no-store" },
  );
  if (!r.ok) throw new Error(`getRcaDetail(${isoDate}): ${r.status}`);
  return r.json();
}

export async function runRcaDigest(
  body: RunDigestRequest = {},
): Promise<RunDigestResponse> {
  const r = await fetch(`${API_BASE}/api/ai/rca/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`runRcaDigest: ${r.status} ${await r.text()}`);
  return r.json();
}

export async function getTriageAlerts(
  opts: { limit?: number } = {},
): Promise<AlertChainView> {
  const qs = new URLSearchParams();
  if (opts.limit != null) qs.set("limit", String(opts.limit));
  const url = `${API_BASE}/api/ai/triage/alerts${
    qs.toString() ? `?${qs.toString()}` : ""
  }`;
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`getTriageAlerts: ${r.status}`);
  return r.json();
}

export async function runTriageEval(): Promise<TriageEvalResponse> {
  const r = await fetch(`${API_BASE}/api/ai/triage/eval`, {
    method: "POST",
  });
  if (!r.ok) throw new Error(`runTriageEval: ${r.status} ${await r.text()}`);
  return r.json();
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
 * Returns a handle with a ``.close()`` function.
 */
export function streamDrill(
  kind: DrillKind,
  overrides: Record<string, unknown>,
  handlers: DrillStreamHandlers,
): { close: () => void; socket: WebSocket } {
  const url = `${WS_BASE}/api/drills/${kind}/stream`;
  const socket = new WebSocket(url);

  socket.addEventListener("open", () => {
    socket.send(JSON.stringify(overrides));
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
  socket.addEventListener("close", (ev) => handlers.onClose?.(ev));
  socket.addEventListener("error", (ev) => handlers.onError?.(ev));

  return {
    close: () => {
      try {
        socket.close();
      } catch {
        /* noop */
      }
    },
    socket,
  };
}

export const SENTINEL_API_BASE = API_BASE;
