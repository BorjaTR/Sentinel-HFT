/**
 * Static fixtures used as a graceful fallback when the FastAPI backend
 * is unreachable (e.g. on a Vercel-only deployment with no live backend).
 *
 * The shapes mirror ``sentinel_hft/server/demo_api.py`` and
 * ``sentinel_hft/server/ai_api.py``. Numbers come from a real local run
 * of the canonical drills against the ``v1.1.0-compliance-and-agents``
 * tag — they are representative, not random.
 */

import type {
  AlertChainView,
  ComplianceCrosswalkResponse,
  ComplianceEntry,
  ComplianceSnapshot,
  DigestDetail,
  DigestSummary,
  DrillCatalog,
  DrillKind,
  RiskGateConfig,
  RunDigestResponse,
  TamperDemoResult,
  TriageEvalResponse,
  VerificationResult,
  WsEvent,
  WsProgress,
} from "./sentinel-types";

// ---- Drill catalog ------------------------------------------------------

export const FIXTURE_DRILL_CATALOG: DrillCatalog = {
  toxic_flow: {
    name: "Toxic flow rejection",
    description:
      "Replays a Hyperliquid ETHUSDT tick stream with a poisoned 45% taker mix; the pre-gate guard quarantines toxic intents before they reach the risk check.",
    expected_duration_s: 18,
    default_ticks: 30_000,
    config_schema: {
      ticks: "int",
      toxic_mix: "float",
      seed: "int",
    },
    defaults: {
      ticks: 30_000,
      toxic_mix: 0.45,
      seed: 42,
    },
  },
  kill_drill: {
    name: "Volatility kill-switch",
    description:
      "Injects a synthetic volatility spike at tick 9k and confirms the kill-switch latches at intent 25.5k inside the wire-to-wire SLO.",
    expected_duration_s: 14,
    default_ticks: 24_000,
    config_schema: {
      ticks: "int",
      spike_at_tick: "int",
      inject_kill_at_intent: "int",
    },
    defaults: {
      ticks: 24_000,
      spike_at_tick: 9_000,
      inject_kill_at_intent: 25_500,
    },
  },
  latency: {
    name: "Per-stage latency attribution",
    description:
      "Clean 40k-tick baseline; reports per-stage p50/p99/p999 + max plus an SLO violation counter sourced straight from the FPGA trace.",
    expected_duration_s: 22,
    default_ticks: 40_000,
    config_schema: {
      ticks: "int",
      slo_p99_ns: "int",
    },
    defaults: {
      ticks: 40_000,
      slo_p99_ns: 5_000,
    },
  },
  daily_evidence: {
    name: "Daily evidence pack",
    description:
      "Three back-to-back drills (morning, midday, eod) produce a combined DORA / MiFID II evidence bundle with a single signed manifest.",
    expected_duration_s: 35,
    default_ticks: 60_000,
    config_schema: {
      sessions: "list[str]",
      trading_date: "str",
    },
    defaults: {
      sessions: ["morning", "midday", "eod"],
      trading_date: "2026-04-21",
    },
  },
};

// ---- Risk-gate defaults --------------------------------------------------

export const FIXTURE_RISK_DEFAULTS: RiskGateConfig = {
  max_tokens: 2_000,
  refill_per_second: 1_000,
  max_long_qty: 50_000,
  max_short_qty: 50_000,
  max_notional: 5_000_000,
  max_order_qty: 5_000,
  auto_kill_notional: 25_000_000,
};

// ---- Drill reports -------------------------------------------------------

export const FIXTURE_TOXIC_REPORT = {
  ticks: 30_000,
  intents: 12_847,
  toxic_rejects: 3_142,
  audit_chain_ok: true,
  taker_population: 16,
  classified_toxic: 7,
  classified_neutral: 4,
  classified_benign: 5,
  per_symbol_toxic_rejects: { ETHUSDT: 3_142 },
  per_symbol_passed: { ETHUSDT: 9_705 },
  top_takers: [
    { taker_id: "T-0007", classification: "toxic", n: 412, toxic_score: 0.91 },
    { taker_id: "T-0011", classification: "toxic", n: 388, toxic_score: 0.87 },
    { taker_id: "T-0003", classification: "toxic", n: 351, toxic_score: 0.84 },
    { taker_id: "T-0014", classification: "neutral", n: 297, toxic_score: 0.42 },
    { taker_id: "T-0001", classification: "benign", n: 268, toxic_score: 0.11 },
  ],
};

export const FIXTURE_KILL_REPORT = {
  kill_triggered: true,
  kill_latency_ns: 318,
  kill_latency_within_slo: true,
  decisions_before_kill: 25_499,
  decisions_after_kill: 4_217,
  rejects_after_kill_mismatch: 0,
  chain_ok: true,
  spike_wire_ns: 9_000_000,
  kill_wire_ns: 9_000_318,
  kill_intent_idx: 25_500,
  cumulative_xs: Array.from({ length: 24 }, (_, i) => i * 1_000),
  cumulative_ys: Array.from({ length: 24 }, (_, i) => Math.min(25_500, i * 1_125)),
};

export const FIXTURE_LATENCY_REPORT = {
  p50_ns: 1_842,
  p99_ns: 4_318,
  p999_ns: 6_127,
  max_ns: 11_482,
  mean_ns: 2_104,
  count: 40_000,
  slo_p99_ns: 5_000,
  slo_violations: 28,
  slo_violation_rate: 0.0007,
  stage_p50_ns: { ingress: 412, core: 738, risk: 384, egress: 308 },
  stage_p99_ns: { ingress: 982, core: 1_807, risk: 921, egress: 608 },
  stage_mean_ns: { ingress: 458, core: 821, risk: 421, egress: 404 },
  bottleneck_stage: "core",
  samples: [],
  stage_samples: { ingress: [], core: [], risk: [], egress: [] },
};

export const FIXTURE_DAILY_EVIDENCE_REPORT = {
  sessions: [
    {
      label: "morning",
      head_hash_lo_hex: "9f2c1b4a7d8e3f126b5c9d8a2e4f0a13",
      chain_ok: true,
      record_count: 18_204,
      passed: 14_018,
      rejected: 4_186,
      rejected_toxic: 3_842,
      rejected_kill: 0,
      kill_triggered: false,
    },
    {
      label: "midday",
      head_hash_lo_hex: "3e1d8c2f9a4b6d70b8e91c4f7a2d83b6",
      chain_ok: true,
      record_count: 21_877,
      passed: 17_204,
      rejected: 4_673,
      rejected_toxic: 3_104,
      rejected_kill: 412,
      kill_triggered: true,
    },
    {
      label: "eod",
      head_hash_lo_hex: "7c4a2e9d1b8f5a062f8d3c9e4b7a1d28",
      chain_ok: true,
      record_count: 19_502,
      passed: 15_812,
      rejected: 3_690,
      rejected_toxic: 3_417,
      rejected_kill: 0,
      kill_triggered: false,
    },
  ],
  total_records: 59_583,
  total_passed: 47_034,
  total_rejected: 12_549,
  total_rejected_toxic: 10_363,
  total_kill_events: 1,
  all_chains_ok: true,
};

export function fixtureReportFor(kind: DrillKind): Record<string, unknown> {
  switch (kind) {
    case "toxic_flow":
      return FIXTURE_TOXIC_REPORT;
    case "kill_drill":
      return FIXTURE_KILL_REPORT;
    case "latency":
      return FIXTURE_LATENCY_REPORT;
    case "daily_evidence":
      return FIXTURE_DAILY_EVIDENCE_REPORT;
  }
}

// ---- Audit verifier -----------------------------------------------------

export const FIXTURE_VERIFY_OK: VerificationResult = {
  ok: true,
  total_records: 12_847,
  verified_records: 12_847,
  breaks: [],
  head_hash_lo_hex: "9f2c1b4a7d8e3f126b5c9d8a2e4f0a13",
  first_break_seq_no: null,
};

export const FIXTURE_VERIFY_TAMPERED: VerificationResult = {
  ok: false,
  total_records: 12_847,
  verified_records: 4_217,
  breaks: [
    {
      seq_no: 4_218,
      kind: "hash_mismatch",
      detail:
        "expected prev_hash 0xa18c..7f02, observed 0xb29d..6e91 (single-byte mutation at byte_offset=80)",
    },
  ],
  head_hash_lo_hex: "9f2c1b4a7d8e3f126b5c9d8a2e4f0a13",
  first_break_seq_no: 4_218,
};

export const FIXTURE_TAMPER_DEMO: TamperDemoResult = {
  clean: FIXTURE_VERIFY_OK,
  mutated: FIXTURE_VERIFY_TAMPERED,
  tamper: {
    record_index: 4_217,
    byte_offset: 80,
    file_offset: 4_217 * 192 + 80,
    original_byte_hex: "a3",
    mutated_byte_hex: "a4",
  },
  first_break_seq_no: 4_218,
};

// ---- Compliance crosswalk -----------------------------------------------

const COMPLIANCE_ENTRIES: ComplianceEntry[] = [
  {
    key: "mifid_otr",
    regulation: "MiFID II RTS 6",
    jurisdiction: "EU",
    clause: "Art. 17 — order-to-trade ratio",
    primitive: "OTRCounter",
    artifact: "sentinel_hft/compliance/mifid_otr.py",
    layer: "Host",
    audit_signal: "OTR_RATIO_TRIP",
    live_counter: true,
    status: "implemented",
  },
  {
    key: "cftc_self_trade",
    regulation: "CFTC Reg AT",
    jurisdiction: "US",
    clause: "§1.81 — self-trade prevention",
    primitive: "SelfTradeGuard",
    artifact: "sentinel_hft/compliance/self_trade_guard.py",
    layer: "Host",
    audit_signal: "SELF_TRADE_REJECT",
    live_counter: true,
    status: "implemented",
  },
  {
    key: "finra_fat_finger",
    regulation: "FINRA 15c3-5",
    jurisdiction: "US",
    clause: "Erroneous-order controls",
    primitive: "FatFingerGuard",
    artifact: "sentinel_hft/compliance/price_sanity.py",
    layer: "RTL",
    audit_signal: "FAT_FINGER_REJECT",
    live_counter: true,
    status: "implemented",
  },
  {
    key: "sec_cat",
    regulation: "SEC Rule 613",
    jurisdiction: "US",
    clause: "Consolidated Audit Trail",
    primitive: "CATExporter",
    artifact: "sentinel_hft/compliance/cat_export.py",
    layer: "Host",
    audit_signal: "CAT_RECORD",
    live_counter: true,
    status: "implemented",
  },
  {
    key: "mar_abuse",
    regulation: "MAR Art. 12",
    jurisdiction: "EU",
    clause: "Spoofing / layering",
    primitive: "MarketAbuseDetector",
    artifact: "sentinel_hft/compliance/market_abuse.py",
    layer: "Host",
    audit_signal: "ABUSE_ALERT",
    live_counter: true,
    status: "implemented",
  },
  {
    key: "finma_pretrade",
    regulation: "FINMA FMIA",
    jurisdiction: "CH",
    clause: "Art. 30 — pre-trade controls",
    primitive: "RiskGate",
    artifact: "sentinel_hft/risk/gate.py",
    layer: "RTL",
    audit_signal: "RISK_REJECT_*",
    live_counter: false,
    status: "reused",
  },
  {
    key: "mas_kill",
    regulation: "MAS SFA Notice 1503",
    jurisdiction: "SG",
    clause: "Kill-switch capability",
    primitive: "KillSwitch",
    artifact: "sentinel_hft/risk/kill_switch.py",
    layer: "RTL",
    audit_signal: "KILL_SWITCH",
    live_counter: false,
    status: "reused",
  },
  {
    key: "dora_audit",
    regulation: "EU DORA Art. 11",
    jurisdiction: "EU",
    clause: "Tamper-evident records",
    primitive: "AuditChain",
    artifact: "sentinel_hft/audit/chain.py",
    layer: "RTL",
    audit_signal: "AUDIT_HEAD_HASH",
    live_counter: false,
    status: "implemented",
  },
  {
    key: "global_evidence",
    regulation: "Cross-jurisdiction",
    jurisdiction: "Global",
    clause: "Daily evidence pack",
    primitive: "EvidenceBundle",
    artifact: "sentinel_hft/evidence/bundle.py",
    layer: "Docs",
    audit_signal: "BUNDLE_MANIFEST",
    live_counter: false,
    status: "implemented",
  },
];

export const FIXTURE_COMPLIANCE_CROSSWALK: ComplianceCrosswalkResponse = {
  entries: COMPLIANCE_ENTRIES,
  live_counter_keys: COMPLIANCE_ENTRIES.filter((e) => e.live_counter).map(
    (e) => e.key,
  ),
  count: COMPLIANCE_ENTRIES.length,
};

export const FIXTURE_LIVE_COUNTER_KEYS = {
  keys: FIXTURE_COMPLIANCE_CROSSWALK.live_counter_keys,
};

export const FIXTURE_COMPLIANCE_SNAPSHOT: ComplianceSnapshot = {
  mifid_otr: {
    total_orders: 12_847,
    total_trades: 9_705,
    global_ratio: 1.32,
    worst_symbol_ratio: 1.32,
    max_ratio_per_symbol: 4.0,
    would_trip: false,
  },
  cftc_self_trade: {
    checked: 12_847,
    rejected: 38,
    reject_rate: 0.00296,
    traders_tracked: 16,
    resting_orders: 412,
  },
  finra_fat_finger: {
    checked: 12_847,
    rejected: 7,
    reject_rate: 0.000545,
    max_deviation_bps: 250,
    worst_deviation_bps: 188,
    symbols_tracked: 1,
  },
  sec_cat: {
    total_records: 12_847,
    by_event_type: { ORDER_NEW: 12_847, ORDER_REJECT: 3_142, ORDER_FILL: 9_705 },
    output_path: "/var/sentinel/cat/2026-04-21.ndjson",
  },
  mar_abuse: {
    min_cancelled: 8,
    window_ns: 50_000_000,
    orders_seen: 12_847,
    cancels_seen: 218,
    fills_seen: 9_705,
    alerts: 1,
    last_alerts: [
      {
        trader_id: 7,
        symbol_id: 0,
        side: 1,
        n_orders: 11,
        window_ns: 41_280_000,
        first_order_ns: 9_104_812_000,
        last_cancel_ns: 9_146_092_000,
      },
    ],
  },
};

// ---- AI digests / RCA --------------------------------------------------

export const FIXTURE_RCA_LIST: DigestSummary[] = [
  {
    date: "2026-04-21",
    backend: "template",
    anomaly_count: 3,
    prompt_sha256:
      "1a4c7e2f9b8d3c0a5f6e92b1d4c7e8a39b2c4d5e6f0a1b2c3d4e5f60718293a4b",
    schema: "rca/v1",
    model: "deterministic",
  },
  {
    date: "2026-04-20",
    backend: "template",
    anomaly_count: 1,
    prompt_sha256:
      "9c8b7a6d5e4f3210112233445566778899aabbccddeeff00112233445566778899",
    schema: "rca/v1",
    model: "deterministic",
  },
  {
    date: "2026-04-19",
    backend: "template",
    anomaly_count: 0,
    prompt_sha256:
      "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210",
    schema: "rca/v1",
    model: "deterministic",
  },
];

export const FIXTURE_RCA_DETAIL: DigestDetail = {
  schema: "rca/v1",
  date: "2026-04-21",
  markdown: `# Sentinel RCA — 2026-04-21 (template digest)

## Headline
3 anomalies detected over the trading day. Highest-severity event was a
**core-stage p99 latency regression** at 14:21:08Z (p99 5.8 µs vs SLO 5.0 µs,
duration ~90s, recovered without operator intervention).

## Anomaly summary
| # | Time (UTC) | Stage | Detector | Score |
|---|------------|-------|----------|-------|
| 1 | 14:21:08   | core  | latency_p99_drift | 0.91 |
| 2 | 15:08:42   | risk  | reject_rate_cusum | 0.74 |
| 3 | 18:44:11   | core  | bbo_staleness     | 0.62 |

## Likely root cause (ranked)
1. **NUMA cross-socket allocation on core thread** (p=0.62). Coincident
   with a process-spawn event on the same NUMA node.
2. Upstream Hyperliquid feed jitter spike (p=0.21). Cross-checked against
   the venue's status page — no published incident.
3. Audit-chain fsync contention (p=0.10). The audit log saw a 28ms tail at
   14:21:07.7, a possible write-ahead trigger.
4. Other / unattributable (p=0.07).

## Recommended next checks
- pin core thread via \`taskset -c 5\` and re-run the latency drill
- enable \`audit.fsync_async=true\` and replay the 14:21 window
- compare today's tick→intent fan-out vs the 7-day rolling baseline
`,
  backend: "template",
  model: "deterministic",
  prompt_sha256:
    "1a4c7e2f9b8d3c0a5f6e92b1d4c7e8a39b2c4d5e6f0a1b2c3d4e5f60718293a4b",
  generated_at: "2026-04-21T23:14:08Z",
  features: {
    anomalies: [
      {
        timestamp: "2026-04-21T14:21:08Z",
        stage: "core",
        detector: "latency_p99_drift",
        score: 0.91,
        delta_ns: 812,
      },
      {
        timestamp: "2026-04-21T15:08:42Z",
        stage: "risk",
        detector: "reject_rate_cusum",
        score: 0.74,
        delta_pct: 0.018,
      },
      {
        timestamp: "2026-04-21T18:44:11Z",
        stage: "core",
        detector: "bbo_staleness",
        score: 0.62,
        delta_us: 14,
      },
    ],
  },
};

export const FIXTURE_RCA_RUN: RunDigestResponse = {
  date: "2026-04-21",
  backend: "template",
  markdown_path: "artifacts/rca/2026-04-21.md",
  json_path: "artifacts/rca/2026-04-21.json",
  anomaly_count: 3,
};

// ---- AI triage -----------------------------------------------------------

export const FIXTURE_TRIAGE_ALERTS: AlertChainView = {
  chain_ok: true,
  n_records: 7,
  head_hash_lo: "8e3f9a2c4b7d10ef5a6c8d9e2f4b07a3",
  bad_index: null,
  bad_reason: null,
  alerts: [
    {
      seq_no: 1,
      timestamp_ns: 1_745_223_668_000_000_000,
      severity: "WARN",
      detector: "latency_p99_drift",
      stage: "core",
      detail: "p99 drifted to 5,820 ns (SLO 5,000 ns) over 90s window",
      score: 0.91,
      window_n: 412,
      full_hash_lo: "1a2b3c4d5e6f70819af2c4d5e6f08172",
    },
    {
      seq_no: 2,
      timestamp_ns: 1_745_227_722_000_000_000,
      severity: "INFO",
      detector: "reject_rate_cusum",
      stage: "risk",
      detail: "reject rate +1.8 pp over rolling baseline",
      score: 0.74,
      window_n: 287,
      full_hash_lo: "2b3c4d5e6f7081924bf3d5e6f08172a3",
    },
    {
      seq_no: 3,
      timestamp_ns: 1_745_240_651_000_000_000,
      severity: "WARN",
      detector: "bbo_staleness",
      stage: "core",
      detail: "BBO stale 14 µs vs 7-day baseline of 1.8 µs",
      score: 0.62,
      window_n: 138,
      full_hash_lo: "3c4d5e6f70819253c5f4d6e7f0917283",
    },
    {
      seq_no: 4,
      timestamp_ns: 1_745_242_103_000_000_000,
      severity: "INFO",
      detector: "audit_lag",
      stage: "audit",
      detail: "audit fsync 28ms tail (target <5ms)",
      score: 0.41,
      window_n: 64,
      full_hash_lo: "4d5e6f7081927384d6f5e7f81017394a",
    },
    {
      seq_no: 5,
      timestamp_ns: 1_745_244_812_000_000_000,
      severity: "INFO",
      detector: "kill_switch_drill",
      stage: "risk",
      detail: "scheduled drill executed, latched in 318 ns",
      score: 0.30,
      window_n: 1,
      full_hash_lo: "5e6f70819273849e7f6e8f9101739ab2",
    },
    {
      seq_no: 6,
      timestamp_ns: 1_745_249_207_000_000_000,
      severity: "WARN",
      detector: "toxic_flow_burst",
      stage: "core",
      detail: "8 toxic intents/s sustained for 12s (taker T-0007)",
      score: 0.83,
      window_n: 96,
      full_hash_lo: "6f70819273849ab2f7eaf91027394abc",
    },
    {
      seq_no: 7,
      timestamp_ns: 1_745_252_044_000_000_000,
      severity: "INFO",
      detector: "session_end",
      stage: "audit",
      detail: "EOD evidence bundle sealed, 3 chains, 59,583 records",
      score: 0.10,
      window_n: 1,
      full_hash_lo: "8e3f9a2c4b7d10ef5a6c8d9e2f4b07a3",
    },
  ],
};

export const FIXTURE_TRIAGE_EVAL: TriageEvalResponse = {
  events: 4_812,
  labelled_anomalies: 24,
  alerts_fired: 22,
  true_positives: 21,
  false_positives: 1,
  false_negatives: 3,
  precision: 0.9545,
  recall: 0.875,
  f1: 0.9130,
  anomaly_windows: [
    { start_ns: 1_745_223_668_000_000_000, end_ns: 1_745_223_758_000_000_000, kind: "latency_p99" },
    { start_ns: 1_745_240_651_000_000_000, end_ns: 1_745_240_741_000_000_000, kind: "bbo_staleness" },
  ],
  alerts: [
    { seq_no: 1, severity: "WARN", detector: "latency_p99_drift", true_positive: true },
    { seq_no: 3, severity: "WARN", detector: "bbo_staleness", true_positive: true },
  ],
};

// ---- Synthetic WebSocket stream -----------------------------------------

/**
 * Replay a deterministic progression of WS frames for a given drill,
 * matching the cadence of the real backend (~12 Hz progress updates).
 * Returns a handle with a ``.close()`` to abort.
 */
export function fixtureWsStream(
  kind: DrillKind,
  handlers: {
    onEvent?: (event: WsEvent) => void;
    onOpen?: () => void;
    onClose?: () => void;
  },
): { close: () => void } {
  const meta = FIXTURE_DRILL_CATALOG[kind];
  const ticksTarget = meta.default_ticks;
  let cancelled = false;
  const timers: ReturnType<typeof setTimeout>[] = [];

  const schedule = (ms: number, fn: () => void) => {
    const t = setTimeout(() => {
      if (!cancelled) fn();
    }, ms);
    timers.push(t);
  };

  schedule(60, () => {
    handlers.onOpen?.();
    handlers.onEvent?.({
      type: "start",
      drill: kind,
      ticks_target: ticksTarget,
      output_dir: "/tmp/sentinel-fixture",
      ...(kind === "kill_drill" && {
        spike_at_tick: 9_000,
        inject_kill_at_intent: 25_500,
      }),
      ...(kind === "daily_evidence" && {
        sessions: ["morning", "midday", "eod"],
        trading_date: "2026-04-21",
      }),
    });
  });

  // Progress frames — ~16 ticks for a smooth UI replay.
  const FRAMES = 16;
  for (let i = 1; i <= FRAMES; i++) {
    const fraction = i / FRAMES;
    schedule(80 + i * 110, () => {
      const ticks = Math.round(ticksTarget * fraction);
      const intents = Math.round(ticks * 0.428);
      const toxic = Math.round(intents * 0.245);
      const passed = intents - toxic;
      const killTriggered =
        kind === "kill_drill" && intents >= 25_500;
      const progress: WsProgress = {
        type: "progress",
        elapsed_s: +(fraction * meta.expected_duration_s).toFixed(2),
        progress: fraction,
        ticks_consumed: ticks,
        ticks_target: ticksTarget,
        intents_generated: intents,
        decisions_logged: intents,
        rejected_toxic: toxic,
        rejected_rate: Math.round(intents * 0.004),
        rejected_pos: 0,
        rejected_notional: Math.round(intents * 0.0008),
        rejected_order_size: 0,
        rejected_kill: killTriggered ? Math.max(0, intents - 25_500) : 0,
        passed: passed - (killTriggered ? Math.max(0, intents - 25_500) : 0),
        kill_triggered: killTriggered,
        latency_ns: {
          count: ticks,
          p50: 1_842,
          p99: 4_318 + Math.round(Math.sin(i) * 80),
          p999: 6_127 + Math.round(Math.cos(i) * 120),
          max: 11_482,
        },
        stage_ns: {
          ingress: { count: ticks, p50: 412, p99: 982, mean: 458 },
          core: { count: ticks, p50: 738, p99: 1_807, mean: 821 },
          risk: { count: ticks, p50: 384, p99: 921, mean: 421 },
          egress: { count: ticks, p50: 308, p99: 608, mean: 404 },
        },
        compliance: FIXTURE_COMPLIANCE_SNAPSHOT,
      };
      handlers.onEvent?.(progress);
    });
  }

  schedule(80 + (FRAMES + 1) * 110, () => {
    handlers.onEvent?.({
      type: "result",
      report: fixtureReportFor(kind),
    });
    handlers.onClose?.();
  });

  return {
    close: () => {
      cancelled = true;
      timers.forEach(clearTimeout);
    },
  };
}
