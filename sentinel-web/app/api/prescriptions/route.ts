import { NextRequest, NextResponse } from "next/server";
import { AnalysisResult, DiagnosisReport, Prescription } from "@/types";

export const runtime = "edge";

// Thresholds for generating prescriptions
const THRESHOLDS = {
  P99_EXCELLENT: 100,
  P99_GOOD: 200,
  P99_WARNING: 500,
  P99_CRITICAL: 1000,
  TAIL_RATIO_EXCELLENT: 2.0,
  TAIL_RATIO_WARNING: 5.0,
  STAGE_BOTTLENECK_PCT: 40,
  THROUGHPUT_EXCELLENT: 300000,
  THROUGHPUT_GOOD: 200000,
  THROUGHPUT_WARNING: 100000,
};

// Demo analysis result
const DEMO_RESULT: AnalysisResult = {
  id: "demo-analysis-001",
  timestamp: new Date(),
  traceFile: "demo-traces.bin",
  totalRecords: 1247832,
  budget: 850,
  budgetMet: true,
  metrics: {
    p50: 423,
    p90: 712,
    p99: 847,
    p99_9: 923,
    max: 1247,
    min: 89,
    mean: 456,
    stdDev: 124,
    throughput: 284535,
  },
  attribution: {
    ingress: 9,
    core: 52,
    risk: 31,
    egress: 8,
  },
  anomalies: [
    {
      type: "latency_spike",
      severity: "medium",
      timestamp: 2.341,
      description:
        "Single transaction spike to 285ns (3.2x baseline). Likely caused by L1 cache miss on rarely-traded symbol.",
      affectedStage: "core",
    },
    {
      type: "backpressure",
      severity: "low",
      timestamp: 3.892,
      description:
        "Brief 47-cycle backpressure event. Downstream consumer temporarily busy. No drops occurred.",
      affectedStage: "egress",
    },
  ],
};

function generatePrescriptions(result: AnalysisResult): Prescription[] {
  const prescriptions: Prescription[] = [];
  let idCounter = 1;

  // P99 Latency analysis
  const p99 = result.metrics.p99;
  if (p99 > THRESHOLDS.P99_WARNING) {
    prescriptions.push({
      id: `rx-${idCounter++}`,
      title: p99 > THRESHOLDS.P99_CRITICAL ? "Critical P99 Latency" : "Elevated P99 Latency",
      severity: p99 > THRESHOLDS.P99_CRITICAL ? "critical" : "warning",
      category: "bottleneck",
      diagnosis: `P99 latency of ${p99}ns is above optimal range.`,
      prescription: "Profile pipeline stages and optimize the slowest paths.",
      impact: "Reducing P99 improves competitiveness",
      effort: "high",
      metrics: { current: p99, target: THRESHOLDS.P99_GOOD, unit: "ns" },
    });
  } else if (p99 <= THRESHOLDS.P99_EXCELLENT) {
    prescriptions.push({
      id: `rx-${idCounter++}`,
      title: "Excellent P99 Latency",
      severity: "success",
      category: "health",
      diagnosis: `P99 latency of ${p99}ns is excellent.`,
      prescription: "Maintain current optimizations.",
      impact: "Current performance is competitive",
      effort: "low",
    });
  }

  // Tail latency analysis
  const ratio = result.metrics.p99 / result.metrics.p50;
  if (ratio > THRESHOLDS.TAIL_RATIO_WARNING) {
    prescriptions.push({
      id: `rx-${idCounter++}`,
      title: "High Tail Latency Variance",
      severity: "warning",
      category: "anomaly",
      diagnosis: `P99/P50 ratio of ${ratio.toFixed(1)}x indicates inconsistent performance.`,
      prescription: "Profile P99 transactions to identify slow paths.",
      impact: "Reducing variance improves predictability",
      effort: "medium",
    });
  }

  // Attribution analysis
  if (result.attribution) {
    const stages = [
      { name: "ingress", pct: result.attribution.ingress },
      { name: "core", pct: result.attribution.core },
      { name: "risk", pct: result.attribution.risk },
      { name: "egress", pct: result.attribution.egress },
    ];
    const bottleneck = stages.sort((a, b) => b.pct - a.pct)[0];

    if (bottleneck.pct >= THRESHOLDS.STAGE_BOTTLENECK_PCT) {
      prescriptions.push({
        id: `rx-${idCounter++}`,
        title: `${bottleneck.name.charAt(0).toUpperCase() + bottleneck.name.slice(1)} Stage Bottleneck`,
        severity: "warning",
        category: "bottleneck",
        affectedStage: bottleneck.name,
        diagnosis: `The ${bottleneck.name} stage consumes ${bottleneck.pct}% of total latency.`,
        prescription: `Optimize the ${bottleneck.name} stage to reduce overall latency.`,
        impact: `Optimizing by 50% would reduce total latency by ~${Math.round(bottleneck.pct / 2)}%`,
        effort: "medium",
        metrics: { current: bottleneck.pct, target: 25, unit: "%" },
      });
    }
  }

  // Anomaly analysis
  if (result.anomalies.length > 0) {
    const highSeverity = result.anomalies.filter((a) => a.severity === "high");
    if (highSeverity.length >= 3) {
      prescriptions.push({
        id: `rx-${idCounter++}`,
        title: "Multiple High-Severity Anomalies",
        severity: "critical",
        category: "anomaly",
        diagnosis: `${highSeverity.length} high-severity anomalies detected.`,
        prescription: "Review each anomaly event. Consider defensive kill switches.",
        impact: "High anomaly rates can cause significant P&L impact",
        effort: "high",
      });
    }

    const latencySpikes = result.anomalies.filter((a) => a.type === "latency_spike");
    if (latencySpikes.length > 0) {
      prescriptions.push({
        id: `rx-${idCounter++}`,
        title: "Latency Spikes Detected",
        severity: latencySpikes.length >= 3 ? "warning" : "info",
        category: "anomaly",
        diagnosis: `${latencySpikes.length} latency spike(s) detected.`,
        prescription: "Add cache miss counters. Pre-warm caches for likely symbols.",
        impact: "Eliminating spikes improves P99 predictability",
        effort: "medium",
        affectedStage: latencySpikes[0]?.affectedStage,
      });
    }

    const backpressure = result.anomalies.filter((a) => a.type === "backpressure");
    if (backpressure.length > 0) {
      prescriptions.push({
        id: `rx-${idCounter++}`,
        title: "Backpressure Events",
        severity: backpressure.length >= 3 ? "warning" : "info",
        category: "anomaly",
        diagnosis: `${backpressure.length} backpressure event(s) from downstream.`,
        prescription: "Monitor downstream health. Consider increasing FIFO depth.",
        impact: "Backpressure causes queuing delays",
        effort: "low",
        affectedStage: backpressure[0]?.affectedStage,
      });
    }
  } else {
    prescriptions.push({
      id: `rx-${idCounter++}`,
      title: "No Anomalies Detected",
      severity: "success",
      category: "health",
      diagnosis: "No significant anomalies found. System operating normally.",
      prescription: "Continue monitoring. Set up automated anomaly alerts.",
      impact: "Clean operation indicates stable system",
      effort: "low",
    });
  }

  // Budget compliance
  if (!result.budgetMet) {
    prescriptions.push({
      id: `rx-${idCounter++}`,
      title: "Latency Budget Exceeded",
      severity: "critical",
      category: "configuration",
      diagnosis: `P99 latency (${result.metrics.p99}ns) exceeds budget (${result.budget}ns).`,
      prescription: "Address bottleneck prescriptions. Consider relaxing budget if unrealistic.",
      impact: "Budget compliance is critical for risk management",
      effort: "high",
      metrics: { current: result.metrics.p99, target: result.budget, unit: "ns" },
    });
  }

  // Throughput
  if (result.metrics.throughput < THRESHOLDS.THROUGHPUT_WARNING) {
    prescriptions.push({
      id: `rx-${idCounter++}`,
      title: "Low Throughput",
      severity: "warning",
      category: "optimization",
      diagnosis: `Throughput of ${result.metrics.throughput.toLocaleString()}/sec is below optimal.`,
      prescription: "Increase pipeline depth. Reduce per-transaction latency.",
      impact: "Higher throughput enables more market opportunities",
      effort: "high",
      metrics: { current: result.metrics.throughput, target: THRESHOLDS.THROUGHPUT_GOOD, unit: "tx/sec" },
    });
  } else if (result.metrics.throughput >= THRESHOLDS.THROUGHPUT_EXCELLENT) {
    prescriptions.push({
      id: `rx-${idCounter++}`,
      title: "Excellent Throughput",
      severity: "success",
      category: "health",
      diagnosis: `Throughput of ${result.metrics.throughput.toLocaleString()}/sec is excellent.`,
      prescription: "Focus on latency consistency rather than throughput.",
      impact: "Current throughput is competitive",
      effort: "low",
    });
  }

  return prescriptions;
}

function calculateHealthScore(prescriptions: Prescription[], result: AnalysisResult): number {
  let score = 100;

  prescriptions.forEach((p) => {
    if (p.severity === "critical") score -= 25;
    else if (p.severity === "warning") score -= 10;
    else if (p.severity === "info" && p.category !== "health") score -= 2;
  });

  if (!result.budgetMet) score -= 15;
  if (result.metrics.p99 > THRESHOLDS.P99_WARNING) score -= 10;
  if (result.metrics.p99 <= THRESHOLDS.P99_EXCELLENT) score += 5;
  if (result.anomalies.length === 0) score += 5;

  return Math.max(0, Math.min(100, score));
}

export async function GET() {
  const prescriptions = generatePrescriptions(DEMO_RESULT);
  const healthScore = calculateHealthScore(prescriptions, DEMO_RESULT);

  const report: DiagnosisReport = {
    id: `diagnosis-${Date.now()}`,
    timestamp: new Date(),
    overallHealth: healthScore >= 80 ? "healthy" : healthScore >= 50 ? "warning" : "critical",
    healthScore,
    summary: `Demo analysis complete. P99: ${DEMO_RESULT.metrics.p99}ns, Health: ${healthScore}/100`,
    prescriptions,
    metrics: {
      totalIssues: prescriptions.length,
      criticalCount: prescriptions.filter((p) => p.severity === "critical").length,
      warningCount: prescriptions.filter((p) => p.severity === "warning").length,
      optimizationCount: prescriptions.filter((p) => p.category === "optimization").length,
    },
  };

  return NextResponse.json({ success: true, demo: true, report });
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const result: AnalysisResult = body.analysisResult || DEMO_RESULT;

    const prescriptions = generatePrescriptions(result);
    const healthScore = calculateHealthScore(prescriptions, result);

    const report: DiagnosisReport = {
      id: `diagnosis-${Date.now()}`,
      timestamp: new Date(),
      overallHealth: healthScore >= 80 ? "healthy" : healthScore >= 50 ? "warning" : "critical",
      healthScore,
      summary: `Analysis complete. P99: ${result.metrics.p99}ns, Health: ${healthScore}/100`,
      prescriptions,
      metrics: {
        totalIssues: prescriptions.length,
        criticalCount: prescriptions.filter((p) => p.severity === "critical").length,
        warningCount: prescriptions.filter((p) => p.severity === "warning").length,
        optimizationCount: prescriptions.filter((p) => p.category === "optimization").length,
      },
    };

    return NextResponse.json({ success: true, demo: false, report });
  } catch {
    return NextResponse.json({ success: false, error: "Failed to generate prescriptions" }, { status: 400 });
  }
}
