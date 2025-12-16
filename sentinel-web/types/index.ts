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
  ingress: number;
  core: number;
  risk: number;
  egress: number;
}

export interface LatencyMetrics {
  p50: number;
  p90: number;
  p99: number;
  p99_9: number;
  min: number;
  max: number;
  mean: number;
  stdDev: number;
  throughput: number;
}

export interface Anomaly {
  type: string;
  severity: "low" | "medium" | "high";
  timestamp: number;
  description: string;
  affectedStage?: string;
}

export interface AnalysisResult {
  id: string;
  timestamp: Date;
  traceFile: string;
  totalRecords: number;
  budget: number;
  budgetMet: boolean;
  metrics: LatencyMetrics;
  attribution?: Attribution;
  anomalies: Anomaly[];
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
  size?: number;
  data?: {
    totalRecords?: number;
    p99Latency?: number;
    throughput?: number;
    anomalyCount?: number;
  };
}

export interface AnalysisSettings {
  budget: number;
  percentile: "p50" | "p90" | "p99" | "p99.9";
  showAttribution: boolean;
  detectAnomalies: boolean;
  anomalyThreshold: number;
  apiKey?: string;
}

export interface TimelineSegment {
  id: string;
  stage: string;
  startTime: number;
  duration: number;
  anomaly?: boolean;
}

export interface ChartDataPoint {
  time: number;
  p50?: number;
  p90?: number;
  p99?: number;
  max?: number;
  value?: number;
  label?: string;
}

// Performance Doctor / Prescription Engine types
export type PrescriptionSeverity = "critical" | "warning" | "info" | "success";
export type PrescriptionCategory = "bottleneck" | "anomaly" | "optimization" | "configuration" | "health";

export interface Prescription {
  id: string;
  title: string;
  severity: PrescriptionSeverity;
  category: PrescriptionCategory;
  diagnosis: string;
  prescription: string;
  impact: string;
  effort: "low" | "medium" | "high";
  affectedStage?: string;
  metrics?: {
    current: number;
    target: number;
    unit: string;
  };
  codeHint?: string;
}

export interface DiagnosisReport {
  id: string;
  timestamp: Date;
  overallHealth: "healthy" | "warning" | "critical";
  healthScore: number; // 0-100
  summary: string;
  prescriptions: Prescription[];
  metrics: {
    totalIssues: number;
    criticalCount: number;
    warningCount: number;
    optimizationCount: number;
  };
}
