export interface TraceRecord {
  seq_no: number;
  record_type: number;
  core_id: number;
  t_ingress: number;
  t_egress: number;
  tx_id: number;
  flags: number;
  latency_cycles: number;
  latency_ns: number;
  d_ingress?: number;
  d_core?: number;
  d_risk?: number;
  d_egress?: number;
}

export interface Attribution {
  total_ns: number;
  ingress_ns: number;
  core_ns: number;
  risk_ns: number;
  egress_ns: number;
  overhead_ns: number;
  bottleneck: string;
  bottleneck_pct: number;
}

export interface LatencyMetrics {
  p50: number;
  p90: number;
  p99: number;
  p999: number;
  min: number;
  max: number;
  mean: number;
}

export interface AnalysisResult {
  status: "healthy" | "warning" | "critical";
  latency: LatencyMetrics;
  throughput: {
    total: number;
    per_second: number;
  };
  drops: {
    count: number;
    rate: number;
  };
  attribution?: Attribution;
  anomalies: Anomaly[];
}

export interface Anomaly {
  type: string;
  severity: "low" | "medium" | "high";
  timestamp: number;
  description: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: Date;
  attachments?: Attachment[];
  analysis?: AnalysisResult;
}

export interface Attachment {
  type: "trace" | "config" | "report";
  name: string;
  size: number;
  data?: ArrayBuffer;
}

export interface AnalysisSettings {
  clock_mhz: number;
  format: "auto" | "v1.0" | "v1.1" | "v1.2";
  attribution: boolean;
  anomaly_threshold: number;
  percentiles: number[];
}

export interface TimelineSegment {
  start_time: number;
  end_time: number;
  type: "normal" | "spike" | "drop" | "backpressure" | "kill_switch";
  latency_p99: number;
  count: number;
  anomalies: Anomaly[];
}

export interface ChartDataPoint {
  time: number;
  value: number;
  label?: string;
}
