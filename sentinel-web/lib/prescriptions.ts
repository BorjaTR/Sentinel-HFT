import { AnalysisResult, DiagnosisReport, Prescription } from "@/types";

/**
 * Prescription Engine - Analyzes trace data and generates actionable prescriptions
 * for optimizing FPGA trading system performance.
 */

// Thresholds for generating prescriptions
const THRESHOLDS = {
  // Latency thresholds (ns)
  P99_EXCELLENT: 100,
  P99_GOOD: 200,
  P99_WARNING: 500,
  P99_CRITICAL: 1000,

  // P99/P50 ratio (tail latency indicator)
  TAIL_RATIO_EXCELLENT: 2.0,
  TAIL_RATIO_GOOD: 3.0,
  TAIL_RATIO_WARNING: 5.0,

  // Stage attribution thresholds
  STAGE_BOTTLENECK_PCT: 40,
  STAGE_WARNING_PCT: 30,

  // Throughput thresholds
  THROUGHPUT_EXCELLENT: 300000,
  THROUGHPUT_GOOD: 200000,
  THROUGHPUT_WARNING: 100000,

  // Anomaly severity counts
  HIGH_ANOMALY_CRITICAL: 3,
  MEDIUM_ANOMALY_WARNING: 5,
};

/**
 * Generate a diagnosis report with prescriptions from analysis results
 */
export function generateDiagnosisReport(result: AnalysisResult): DiagnosisReport {
  const prescriptions: Prescription[] = [];
  let idCounter = 1;

  // Analyze P99 latency
  const p99Prescriptions = analyzeP99Latency(result, idCounter);
  prescriptions.push(...p99Prescriptions);
  idCounter += p99Prescriptions.length;

  // Analyze tail latency (P99/P50 ratio)
  const tailPrescriptions = analyzeTailLatency(result, idCounter);
  prescriptions.push(...tailPrescriptions);
  idCounter += tailPrescriptions.length;

  // Analyze attribution/bottlenecks
  if (result.attribution) {
    const attrPrescriptions = analyzeAttribution(result, idCounter);
    prescriptions.push(...attrPrescriptions);
    idCounter += attrPrescriptions.length;
  }

  // Analyze anomalies
  const anomalyPrescriptions = analyzeAnomalies(result, idCounter);
  prescriptions.push(...anomalyPrescriptions);
  idCounter += anomalyPrescriptions.length;

  // Analyze throughput
  const throughputPrescriptions = analyzeThroughput(result, idCounter);
  prescriptions.push(...throughputPrescriptions);
  idCounter += throughputPrescriptions.length;

  // Analyze budget compliance
  const budgetPrescriptions = analyzeBudget(result, idCounter);
  prescriptions.push(...budgetPrescriptions);

  // Calculate health score and overall status
  const { healthScore, overallHealth } = calculateHealthScore(prescriptions, result);

  // Generate summary
  const summary = generateSummary(prescriptions, result, healthScore);

  // Count by severity
  const criticalCount = prescriptions.filter((p) => p.severity === "critical").length;
  const warningCount = prescriptions.filter((p) => p.severity === "warning").length;
  const optimizationCount = prescriptions.filter(
    (p) => p.category === "optimization" || p.severity === "info"
  ).length;

  return {
    id: `diagnosis-${Date.now()}`,
    timestamp: new Date(),
    overallHealth,
    healthScore,
    summary,
    prescriptions,
    metrics: {
      totalIssues: prescriptions.length,
      criticalCount,
      warningCount,
      optimizationCount,
    },
  };
}

function analyzeP99Latency(result: AnalysisResult, startId: number): Prescription[] {
  const prescriptions: Prescription[] = [];
  const p99 = result.metrics.p99;

  if (p99 > THRESHOLDS.P99_CRITICAL) {
    prescriptions.push({
      id: `rx-${startId}`,
      title: "Critical P99 Latency",
      severity: "critical",
      category: "bottleneck",
      diagnosis: `P99 latency of ${p99}ns exceeds critical threshold of ${THRESHOLDS.P99_CRITICAL}ns. This indicates severe performance issues affecting 1% of transactions.`,
      prescription:
        "1. Profile individual pipeline stages to identify the slowest paths\n2. Review cache hit rates - likely significant cache misses\n3. Check for memory allocation in the critical path\n4. Consider architectural review of the matching engine",
      impact: "Reducing P99 below 1µs is critical for competitive HFT systems",
      effort: "high",
      metrics: {
        current: p99,
        target: THRESHOLDS.P99_GOOD,
        unit: "ns",
      },
    });
  } else if (p99 > THRESHOLDS.P99_WARNING) {
    prescriptions.push({
      id: `rx-${startId}`,
      title: "Elevated P99 Latency",
      severity: "warning",
      category: "bottleneck",
      diagnosis: `P99 latency of ${p99}ns is above optimal range. While functional, this may impact competitiveness.`,
      prescription:
        "1. Implement fast-path for common order types\n2. Add L1 cache warming for hot symbols\n3. Pre-compute risk calculations where possible",
      impact: "Reducing P99 by 50% would significantly improve fill rates",
      effort: "medium",
      metrics: {
        current: p99,
        target: THRESHOLDS.P99_GOOD,
        unit: "ns",
      },
    });
  } else if (p99 <= THRESHOLDS.P99_EXCELLENT) {
    prescriptions.push({
      id: `rx-${startId}`,
      title: "Excellent P99 Latency",
      severity: "success",
      category: "health",
      diagnosis: `P99 latency of ${p99}ns is excellent - in the top tier for FPGA trading systems.`,
      prescription: "Maintain current optimizations. Focus on consistency and anomaly prevention.",
      impact: "Current performance is competitive",
      effort: "low",
    });
  }

  return prescriptions;
}

function analyzeTailLatency(result: AnalysisResult, startId: number): Prescription[] {
  const prescriptions: Prescription[] = [];
  const ratio = result.metrics.p99 / result.metrics.p50;

  if (ratio > THRESHOLDS.TAIL_RATIO_WARNING) {
    prescriptions.push({
      id: `rx-${startId}`,
      title: "High Tail Latency Variance",
      severity: "warning",
      category: "anomaly",
      diagnosis: `P99/P50 ratio of ${ratio.toFixed(1)}x indicates inconsistent performance. Typical transactions are fast (${result.metrics.p50}ns) but tail cases are significantly slower.`,
      prescription:
        "1. Profile P99 transactions specifically to identify slow paths\n2. Look for conditional branches that only trigger 1% of the time\n3. Check for memory contention or cache thrashing\n4. Review interrupt handling and system noise sources",
      impact: "Reducing variance improves predictability and risk management",
      effort: "medium",
      codeHint:
        "Add cycle counters around conditional paths to identify which branches cause tail latency",
    });
  } else if (ratio <= THRESHOLDS.TAIL_RATIO_EXCELLENT) {
    prescriptions.push({
      id: `rx-${startId}`,
      title: "Consistent Latency Distribution",
      severity: "success",
      category: "health",
      diagnosis: `P99/P50 ratio of ${ratio.toFixed(1)}x shows tight latency distribution. This is excellent for risk management.`,
      prescription: "Current consistency is good. Monitor for changes over time.",
      impact: "Predictable latency enables tighter risk parameters",
      effort: "low",
    });
  }

  return prescriptions;
}

function analyzeAttribution(result: AnalysisResult, startId: number): Prescription[] {
  const prescriptions: Prescription[] = [];
  const attr = result.attribution!;
  let id = startId;

  // Find bottleneck stage
  const stages = [
    { name: "ingress", pct: attr.ingress },
    { name: "core", pct: attr.core },
    { name: "risk", pct: attr.risk },
    { name: "egress", pct: attr.egress },
  ];

  const sorted = stages.sort((a, b) => b.pct - a.pct);
  const bottleneck = sorted[0];

  if (bottleneck.pct >= THRESHOLDS.STAGE_BOTTLENECK_PCT) {
    const rxMap: Record<string, { prescription: string; codeHint: string }> = {
      core: {
        prescription:
          "1. Pipeline the matching engine into 2-3 stages\n2. Add L1 cache for top 10 most-traded symbols\n3. Implement order type fast-paths for market/limit orders\n4. Consider parallel order book lookups",
        codeHint:
          "Measure cycles per sub-operation: order_lookup, match_logic, state_update separately",
      },
      risk: {
        prescription:
          "1. Pre-compute notional values at order entry\n2. Cache recent position lookups\n3. Parallelize independent risk checks\n4. Consider risk sharding by symbol group",
        codeHint:
          "Add bypass for repeat same-symbol orders within short window",
      },
      ingress: {
        prescription:
          "1. Review packet parsing for unnecessary validation\n2. Use fixed-width fields where possible\n3. Pre-allocate parsing buffers\n4. Consider DMA directly to processing stage",
        codeHint: "Profile per-field parsing time to find hotspots",
      },
      egress: {
        prescription:
          "1. Check output buffer sizing\n2. Review serialization logic for redundant operations\n3. Pre-format static message portions\n4. Verify downstream backpressure handling",
        codeHint: "Monitor TX FIFO fill levels for bottleneck patterns",
      },
    };

    const guidance = rxMap[bottleneck.name] || {
      prescription: "Profile this stage to identify optimization opportunities",
      codeHint: "Add per-operation cycle counters",
    };

    prescriptions.push({
      id: `rx-${id++}`,
      title: `${capitalize(bottleneck.name)} Stage Bottleneck`,
      severity: "warning",
      category: "bottleneck",
      affectedStage: bottleneck.name,
      diagnosis: `The ${bottleneck.name} stage consumes ${bottleneck.pct}% of total latency, making it the primary optimization target.`,
      prescription: guidance.prescription,
      impact: `Optimizing ${bottleneck.name} by 50% would reduce total latency by ~${Math.round(bottleneck.pct / 2)}%`,
      effort: "medium",
      codeHint: guidance.codeHint,
      metrics: {
        current: bottleneck.pct,
        target: 25,
        unit: "% of total",
      },
    });
  }

  // Check for well-balanced pipeline
  const maxPct = sorted[0].pct;
  const minPct = sorted[sorted.length - 1].pct;
  if (maxPct - minPct < 20 && maxPct < THRESHOLDS.STAGE_BOTTLENECK_PCT) {
    prescriptions.push({
      id: `rx-${id}`,
      title: "Well-Balanced Pipeline",
      severity: "success",
      category: "health",
      diagnosis: `Pipeline stages are well-balanced (${minPct}%-${maxPct}%). No single stage dominates latency.`,
      prescription:
        "Focus on system-wide optimizations rather than single-stage improvements.",
      impact: "Balanced pipelines are easier to optimize incrementally",
      effort: "low",
    });
  }

  return prescriptions;
}

function analyzeAnomalies(result: AnalysisResult, startId: number): Prescription[] {
  const prescriptions: Prescription[] = [];
  let id = startId;

  const highSeverity = result.anomalies.filter((a) => a.severity === "high");
  const mediumSeverity = result.anomalies.filter((a) => a.severity === "medium");

  if (highSeverity.length >= THRESHOLDS.HIGH_ANOMALY_CRITICAL) {
    prescriptions.push({
      id: `rx-${id++}`,
      title: "Multiple High-Severity Anomalies",
      severity: "critical",
      category: "anomaly",
      diagnosis: `${highSeverity.length} high-severity anomalies detected. This indicates systemic issues requiring immediate attention.`,
      prescription:
        "1. Review each anomaly event with cycle-level traces\n2. Check for common patterns (time of day, symbol, order type)\n3. Consider enabling defensive kill switch thresholds\n4. Escalate to hardware team if patterns suggest FPGA issues",
      impact: "High anomaly rates can cause significant P&L impact",
      effort: "high",
    });
  }

  // Specific anomaly type analysis
  const latencySpikes = result.anomalies.filter((a) => a.type === "latency_spike");
  if (latencySpikes.length > 0) {
    prescriptions.push({
      id: `rx-${id++}`,
      title: "Latency Spikes Detected",
      severity: latencySpikes.length >= 3 ? "warning" : "info",
      category: "anomaly",
      diagnosis: `${latencySpikes.length} latency spike(s) detected. ${latencySpikes[0]?.description || ""}`,
      prescription:
        "1. Add cache miss counters to identify memory access patterns\n2. Pre-warm caches for likely symbols\n3. Consider pinning hot data structures to L1 cache\n4. Profile for branch mispredictions",
      impact: "Eliminating spikes improves P99 predictability",
      effort: "medium",
      affectedStage: latencySpikes[0]?.affectedStage,
    });
  }

  const backpressureEvents = result.anomalies.filter((a) => a.type === "backpressure");
  if (backpressureEvents.length > 0) {
    prescriptions.push({
      id: `rx-${id++}`,
      title: "Backpressure Events",
      severity: backpressureEvents.length >= 3 ? "warning" : "info",
      category: "anomaly",
      diagnosis: `${backpressureEvents.length} backpressure event(s) from downstream systems. ${backpressureEvents[0]?.description || ""}`,
      prescription:
        "1. Monitor downstream consumer health\n2. Consider increasing FIFO depth if near capacity\n3. Add alerting for backpressure duration thresholds\n4. Review downstream system for optimization opportunities",
      impact: "Backpressure causes queuing delays affecting all transactions",
      effort: "low",
      affectedStage: backpressureEvents[0]?.affectedStage,
    });
  }

  if (result.anomalies.length === 0) {
    prescriptions.push({
      id: `rx-${id}`,
      title: "No Anomalies Detected",
      severity: "success",
      category: "health",
      diagnosis: "Trace analysis found no significant anomalies. System is operating normally.",
      prescription: "Continue monitoring. Consider setting up automated anomaly alerts.",
      impact: "Clean operation indicates stable system",
      effort: "low",
    });
  }

  return prescriptions;
}

function analyzeThroughput(result: AnalysisResult, startId: number): Prescription[] {
  const prescriptions: Prescription[] = [];
  const throughput = result.metrics.throughput;

  if (throughput < THRESHOLDS.THROUGHPUT_WARNING) {
    prescriptions.push({
      id: `rx-${startId}`,
      title: "Low Throughput",
      severity: "warning",
      category: "optimization",
      diagnosis: `Throughput of ${throughput.toLocaleString()}/sec is below optimal. This may limit market participation during high-volume periods.`,
      prescription:
        "1. Increase pipeline depth to have more transactions in flight\n2. Reduce per-transaction latency (see other prescriptions)\n3. Consider parallel processing for independent operations\n4. Review FIFO management for overhead",
      impact: "Higher throughput enables participation in more market opportunities",
      effort: "high",
      metrics: {
        current: throughput,
        target: THRESHOLDS.THROUGHPUT_GOOD,
        unit: "tx/sec",
      },
    });
  } else if (throughput >= THRESHOLDS.THROUGHPUT_EXCELLENT) {
    prescriptions.push({
      id: `rx-${startId}`,
      title: "Excellent Throughput",
      severity: "success",
      category: "health",
      diagnosis: `Throughput of ${throughput.toLocaleString()}/sec is excellent - top tier for FPGA systems.`,
      prescription: "Focus on latency consistency rather than raw throughput improvements.",
      impact: "Current throughput is competitive for most markets",
      effort: "low",
    });
  }

  return prescriptions;
}

function analyzeBudget(result: AnalysisResult, startId: number): Prescription[] {
  const prescriptions: Prescription[] = [];

  if (!result.budgetMet) {
    const overage = result.metrics.p99 - result.budget;
    const overagePct = ((overage / result.budget) * 100).toFixed(1);

    prescriptions.push({
      id: `rx-${startId}`,
      title: "Latency Budget Exceeded",
      severity: "critical",
      category: "configuration",
      diagnosis: `P99 latency (${result.metrics.p99}ns) exceeds budget (${result.budget}ns) by ${overage}ns (${overagePct}% over).`,
      prescription:
        "1. Review and address bottleneck prescriptions above\n2. Consider relaxing budget if current target is unrealistic\n3. Prioritize quick-win optimizations first\n4. Track budget compliance over time to identify regressions",
      impact: "Budget compliance is critical for risk management and system predictability",
      effort: "high",
      metrics: {
        current: result.metrics.p99,
        target: result.budget,
        unit: "ns",
      },
    });
  } else {
    const headroom = result.budget - result.metrics.p99;
    const headroomPct = ((headroom / result.budget) * 100).toFixed(1);

    if (headroom > result.budget * 0.2) {
      prescriptions.push({
        id: `rx-${startId}`,
        title: "Latency Budget Met with Headroom",
        severity: "success",
        category: "health",
        diagnosis: `P99 latency (${result.metrics.p99}ns) is ${headroom}ns (${headroomPct}%) under budget. Good safety margin.`,
        prescription: "Maintain current performance. Consider tightening budget for continuous improvement.",
        impact: "Headroom provides buffer against regressions",
        effort: "low",
      });
    }
  }

  return prescriptions;
}

function calculateHealthScore(
  prescriptions: Prescription[],
  result: AnalysisResult
): { healthScore: number; overallHealth: "healthy" | "warning" | "critical" } {
  let score = 100;

  // Deduct for prescriptions
  prescriptions.forEach((p) => {
    if (p.severity === "critical") score -= 25;
    else if (p.severity === "warning") score -= 10;
    else if (p.severity === "info" && p.category !== "health") score -= 2;
  });

  // Additional deductions
  if (!result.budgetMet) score -= 15;
  if (result.metrics.p99 > THRESHOLDS.P99_WARNING) score -= 10;

  // Bonus for good metrics
  if (result.metrics.p99 <= THRESHOLDS.P99_EXCELLENT) score += 5;
  if (result.anomalies.length === 0) score += 5;

  score = Math.max(0, Math.min(100, score));

  const overallHealth: "healthy" | "warning" | "critical" =
    score >= 80 ? "healthy" : score >= 50 ? "warning" : "critical";

  return { healthScore: score, overallHealth };
}

function generateSummary(
  prescriptions: Prescription[],
  result: AnalysisResult,
  healthScore: number
): string {
  const criticalCount = prescriptions.filter((p) => p.severity === "critical").length;
  const warningCount = prescriptions.filter((p) => p.severity === "warning").length;
  const successCount = prescriptions.filter((p) => p.severity === "success").length;

  if (criticalCount > 0) {
    return `System requires attention: ${criticalCount} critical issue(s) detected. P99 latency is ${result.metrics.p99}ns. Address critical prescriptions first.`;
  } else if (warningCount > 0) {
    return `System is operational with ${warningCount} optimization opportunity(ies). P99 latency is ${result.metrics.p99}ns (${result.budgetMet ? "within" : "over"} budget).`;
  } else if (successCount > 0) {
    return `System is healthy with ${successCount} positive indicator(s). P99 latency of ${result.metrics.p99}ns is excellent. Health score: ${healthScore}/100.`;
  }

  return `Analysis complete. P99 latency: ${result.metrics.p99}ns, Throughput: ${result.metrics.throughput.toLocaleString()}/sec.`;
}

function capitalize(str: string): string {
  return str.charAt(0).toUpperCase() + str.slice(1);
}

/**
 * Get demo diagnosis report for the sample trace
 */
export function getDemoDiagnosisReport(): DiagnosisReport {
  const demoResult: AnalysisResult = {
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

  return generateDiagnosisReport(demoResult);
}
