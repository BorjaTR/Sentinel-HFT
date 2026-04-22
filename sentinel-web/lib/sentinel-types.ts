/**
 * TypeScript types mirroring the Sentinel-HFT demo FastAPI contract.
 * Server source of truth: sentinel_hft/server/demo_api.py.
 */

export type DrillKind = "toxic_flow" | "kill_drill" | "latency" | "daily_evidence";

export interface DrillMeta {
  name: string;
  description: string;
  expected_duration_s: number;
  default_ticks: number;
  config_schema: Record<string, string>;
  defaults: Record<string, unknown>;
}

export type DrillCatalog = Record<DrillKind, DrillMeta>;

export interface RiskGateConfig {
  max_tokens: number;
  refill_per_second: number;
  max_long_qty: number;
  max_short_qty: number;
  max_notional: number;
  max_order_qty: number;
  auto_kill_notional: number;
}

// ---- WebSocket event shapes ---------------------------------------------

export interface WsStart {
  type: "start";
  drill: DrillKind;
  ticks_target: number;
  output_dir?: string;
  // kill_drill-only:
  spike_at_tick?: number;
  inject_kill_at_intent?: number;
  // daily_evidence-only:
  sessions?: string[];
  trading_date?: string;
}

export interface LatencyBucket {
  count: number;
  p50: number;
  p99: number;
  p999: number;
  max: number;
}

export interface StageBucket {
  count: number;
  p50: number;
  p99: number;
  mean: number;
}

export interface WsProgress {
  type: "progress";
  elapsed_s: number;
  progress: number;
  ticks_consumed: number;
  ticks_target: number;
  intents_generated: number;
  decisions_logged: number;
  rejected_toxic: number;
  rejected_rate: number;
  rejected_pos: number;
  rejected_notional: number;
  rejected_order_size: number;
  rejected_kill: number;
  passed: number;
  kill_triggered: boolean;
  latency_ns: LatencyBucket;
  stage_ns: Record<"ingress" | "core" | "risk" | "egress", StageBucket>;
  /** Observational compliance counters (optional — null on legacy backends). */
  compliance?: ComplianceSnapshot | null;
}

export interface WsHeartbeat {
  type: "heartbeat";
  elapsed_s: number;
}

export interface WsResult {
  type: "result";
  report: Record<string, unknown>;
}

export interface WsError {
  type: "error";
  error: string;
}

export type WsEvent = WsStart | WsProgress | WsHeartbeat | WsResult | WsError;

// ---- Report shapes (partial -- UI only needs a subset) ------------------

export interface ToxicFlowReport {
  ticks: number;
  intents: number;
  toxic_rejects: number;
  audit_chain_ok: boolean;
  taker_population: number;
  classified_toxic: number;
  classified_neutral: number;
  classified_benign: number;
  per_symbol_toxic_rejects: Record<string, number>;
  per_symbol_passed: Record<string, number>;
  top_takers: Array<Record<string, unknown>>;
}

export interface KillDrillReport {
  kill_triggered: boolean;
  kill_latency_ns: number;
  kill_latency_within_slo: boolean;
  decisions_before_kill: number;
  decisions_after_kill: number;
  rejects_after_kill_mismatch: number;
  chain_ok: boolean;
  spike_wire_ns: number;
  kill_wire_ns: number;
  kill_intent_idx: number;
  cumulative_xs: number[];
  cumulative_ys: number[];
}

export interface LatencyReport {
  p50_ns: number;
  p99_ns: number;
  p999_ns: number;
  max_ns: number;
  mean_ns: number;
  count: number;
  slo_p99_ns: number;
  slo_violations: number;
  slo_violation_rate: number;
  stage_p50_ns: Record<string, number>;
  stage_p99_ns: Record<string, number>;
  stage_mean_ns: Record<string, number>;
  bottleneck_stage: string;
  samples: number[];
  stage_samples: Record<string, number[]>;
}

export interface DailyEvidenceReport {
  sessions: Array<{
    label: string;
    head_hash_lo_hex: string;
    chain_ok: boolean;
    record_count: number;
    passed: number;
    rejected: number;
    rejected_toxic: number;
    rejected_kill: number;
    kill_triggered: boolean;
  }>;
  total_records: number;
  total_passed: number;
  total_rejected: number;
  total_rejected_toxic: number;
  total_kill_events: number;
  all_chains_ok: boolean;
}

// ---- Audit verifier ------------------------------------------------------

export interface ChainBreak {
  seq_no: number;
  kind: string;
  detail: string;
}

export interface VerificationResult {
  ok: boolean;
  total_records: number;
  verified_records: number;
  breaks: ChainBreak[];
  head_hash_lo_hex: string | null;
  first_break_seq_no: number | null;
}

// ---- Compliance (Workstream 3) ------------------------------------------

export type ComplianceLayer = "RTL" | "Host" | "Docs";
export type ComplianceStatus = "implemented" | "partial" | "reused" | "stub";
export type ComplianceJurisdiction = "EU" | "US" | "CH" | "SG" | "Global";

export interface ComplianceEntry {
  key: string;
  regulation: string;
  jurisdiction: ComplianceJurisdiction;
  clause: string;
  primitive: string;
  artifact: string;
  layer: ComplianceLayer;
  audit_signal: string;
  live_counter: boolean;
  status: ComplianceStatus;
}

export interface ComplianceCrosswalkResponse {
  entries: ComplianceEntry[];
  live_counter_keys: string[];
  count: number;
}

/** Shape returned by ComplianceStack.snapshot().as_dict().
 *
 *  Canonical field names mirror the Python ``snapshot()`` methods in
 *  ``sentinel_hft/compliance/*.py``. All fields are optional because
 *  the empty snapshot from a fresh ComplianceStack only fills a subset.
 */
export interface ComplianceSnapshot {
  /** MiFID II RTS 6 order-to-trade ratio counter.
   *  Source: ``sentinel_hft.compliance.mifid_otr.OTRCounter.snapshot``. */
  mifid_otr: {
    total_orders?: number;
    total_trades?: number;
    global_ratio?: number;
    worst_symbol_ratio?: number;
    max_ratio_per_symbol?: number;
    would_trip?: boolean;
    [key: string]: unknown;
  };
  /** CFTC Reg AT self-trade prevention counter.
   *  Source: ``sentinel_hft.compliance.self_trade_guard.SelfTradeGuard.snapshot``. */
  cftc_self_trade: {
    checked?: number;
    rejected?: number;
    reject_rate?: number;
    traders_tracked?: number;
    resting_orders?: number;
    [key: string]: unknown;
  };
  /** FINRA 15c3-5 fat-finger (erroneous-order) counter.
   *  Source: ``sentinel_hft.compliance.price_sanity.FatFingerGuard.snapshot``. */
  finra_fat_finger: {
    checked?: number;
    rejected?: number;
    reject_rate?: number;
    max_deviation_bps?: number;
    worst_deviation_bps?: number;
    symbols_tracked?: number;
    [key: string]: unknown;
  };
  /** SEC Rule 613 CAT NDJSON feed.
   *  Source: ``sentinel_hft.compliance.cat_export.CATExporter.snapshot``. */
  sec_cat: {
    total_records?: number;
    by_event_type?: Record<string, number>;
    output_path?: string | null;
    [key: string]: unknown;
  };
  /** MAR Art. 12 spoofing / layering alerts.
   *  Source: ``sentinel_hft.compliance.market_abuse.MarketAbuseDetector.snapshot``. */
  mar_abuse: {
    min_cancelled?: number;
    window_ns?: number;
    orders_seen?: number;
    cancels_seen?: number;
    fills_seen?: number;
    alerts?: number;
    last_alerts?: Array<{
      trader_id: number;
      symbol_id: number;
      side: number;
      n_orders: number;
      window_ns: number;
      first_order_ns: number;
      last_cancel_ns: number;
    }>;
    [key: string]: unknown;
  };
}

export interface TamperDemoResult {
  clean: VerificationResult;
  mutated: VerificationResult;
  tamper: {
    record_index: number;
    byte_offset: number;
    file_offset: number;
    original_byte_hex: string;
    mutated_byte_hex: string;
  };
  first_break_seq_no: number | null;
}

// ---- AI agents (Workstream 4 RCA + Workstream 5 triage) -----------------
//
// Server source of truth: ``sentinel_hft/server/ai_api.py``. The router is
// mounted under ``/api/ai/*``.

/** One row in /api/ai/rca/list -- newest first. */
export interface DigestSummary {
  date: string;
  backend: string;
  anomaly_count: number;
  prompt_sha256?: string | null;
  /** Wire-name preserved (Pydantic alias of ``digest_schema``). */
  schema?: string | null;
  model?: string | null;
}

/** Full digest payload from /api/ai/rca/{iso_date}. */
export interface DigestDetail {
  /** Wire-name preserved (Pydantic alias of ``digest_schema``). */
  schema: string;
  date: string;
  markdown: string;
  backend: string;
  model?: string | null;
  prompt_sha256: string;
  generated_at: string;
  features: Record<string, unknown>;
}

/** Body of POST /api/ai/rca/run. All fields optional -- defaults apply. */
export interface RunDigestRequest {
  artifacts_root?: string;
  digest_dir?: string;
  date?: string;
  /** "auto" | "anthropic" | "template". Default "template" (deterministic). */
  backend?: string;
  model?: string;
}

export interface RunDigestResponse {
  date: string;
  backend: string;
  markdown_path: string;
  json_path: string;
  anomaly_count: number;
}

/** One sidecar alert row (BLAKE2b chain). */
export interface AlertSummary {
  seq_no: number;
  timestamp_ns: number;
  severity: string;
  detector: string;
  stage: string | null;
  detail: string;
  score: number;
  window_n: number;
  /** 16-byte hash low half, hex-encoded (32 chars). */
  full_hash_lo: string;
}

/** Response of GET /api/ai/triage/alerts. */
export interface AlertChainView {
  chain_ok: boolean;
  n_records: number;
  head_hash_lo: string;
  bad_index?: number | null;
  bad_reason?: string | null;
  alerts: AlertSummary[];
}

/** Response of POST /api/ai/triage/eval (scripted-scenario harness). */
export interface TriageEvalResponse {
  events: number;
  labelled_anomalies: number;
  alerts_fired: number;
  true_positives: number;
  false_positives: number;
  false_negatives: number;
  precision: number;
  recall: number;
  f1: number;
  anomaly_windows: Array<Record<string, unknown>>;
  alerts: Array<Record<string, unknown>>;
}
