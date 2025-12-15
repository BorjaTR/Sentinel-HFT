import { NextRequest, NextResponse } from "next/server";

export const runtime = "edge";

// Pre-computed explanations for demo mode
const EXPLANATIONS: Record<string, string> = {
  overview: `## Trace Analysis Summary

This trace file contains **1,247,832 records** captured from a production FPGA trading system over a 4.38-second window.

### Key Findings

1. **Performance is healthy** - P99 latency of 847ns is within typical bounds for well-tuned HFT systems.

2. **Core stage is the bottleneck** - Consumes 52% of total latency. The order matching and execution logic is the primary contributor.

3. **Two minor anomalies detected**:
   - Latency spike at t=2.341s (likely cache miss)
   - Brief backpressure at t=3.892s (downstream congestion)

### Recommendations

- Focus optimization on core stage
- Monitor cache hit rates for rare symbols
- Current FIFO depth is adequate

Would you like me to dive deeper into any specific aspect?`,

  bottleneck: `## Bottleneck Analysis: Core Stage

The **core stage consumes 52%** of total latency (approximately 443ns out of 850ns average).

### What's Happening

The core stage handles:
- Order book lookup and traversal
- Price matching logic
- Order type validation
- Fill generation

### Root Causes

1. **Order Book Traversal** (~200ns)
   - Binary search through price levels
   - Potential optimization: pre-computed indices for hot prices

2. **Matching Logic** (~150ns)
   - Order type dispatch and validation
   - Consider: specialized fast-paths for market orders

3. **State Updates** (~93ns)
   - Position tracking and fill accumulation
   - Consider: deferred batch updates

### Optimization Priority

This should be your primary optimization target. Reducing core latency by 30% would drop P99 from 847ns to ~700ns.`,

  anomaly: `## Anomaly Analysis

Two anomalies were detected in this trace:

### 1. Latency Spike at t=2.341s
- **Severity**: Medium
- **Duration**: Single transaction
- **Magnitude**: 285ns (3.2x baseline)
- **Likely Cause**: L1 cache miss on rarely-traded symbol

This is a **normal occurrence** in trading systems. The instant recovery and isolated nature suggest proper system behavior.

### 2. Backpressure at t=3.892s
- **Severity**: Low
- **Duration**: 47 cycles (470ns)
- **Cause**: Downstream consumer temporarily busy
- **Impact**: ~3,000 transactions buffered, no drops

Your system handled this correctly:
- FIFO absorbed the burst
- No message loss occurred
- Recovery was fast

### Assessment

Both anomalies are within acceptable operational bounds. No immediate action required, but consider:
- Adding cache miss monitoring
- Alerting if backpressure exceeds 100 cycles`,

  default: `I can help you understand this trace analysis. Here are some topics you can ask about:

- **Overview**: "Give me a summary of this trace"
- **Bottlenecks**: "What's causing the latency?"
- **Anomalies**: "Explain the detected anomalies"
- **Specific stages**: "Analyze the core/risk/ingress/egress stage"
- **Optimization**: "How can I reduce P99 latency?"

What would you like to know?`,
};

function findExplanation(query: string): string {
  const lowerQuery = query.toLowerCase();

  if (
    lowerQuery.includes("overview") ||
    lowerQuery.includes("summary") ||
    lowerQuery.includes("analyze")
  ) {
    return EXPLANATIONS.overview;
  }

  if (
    lowerQuery.includes("bottleneck") ||
    lowerQuery.includes("slow") ||
    lowerQuery.includes("core")
  ) {
    return EXPLANATIONS.bottleneck;
  }

  if (
    lowerQuery.includes("anomal") ||
    lowerQuery.includes("spike") ||
    lowerQuery.includes("backpressure")
  ) {
    return EXPLANATIONS.anomaly;
  }

  return EXPLANATIONS.default;
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { query, apiKey, analysisId } = body;

    if (!query) {
      return NextResponse.json(
        { success: false, error: "Query is required" },
        { status: 400 }
      );
    }

    // Check if pro user with API key
    if (apiKey) {
      // In production, this would call Claude API
      // For now, return demo response with a note
      return NextResponse.json({
        success: true,
        demo: false,
        message:
          "In production, this would use Claude to analyze your specific trace data.",
        explanation: findExplanation(query),
      });
    }

    // Demo mode - return pre-computed explanation
    // Simulate some latency for realism
    await new Promise((resolve) => setTimeout(resolve, 500));

    return NextResponse.json({
      success: true,
      demo: true,
      explanation: findExplanation(query),
    });
  } catch (error) {
    return NextResponse.json(
      { success: false, error: "Failed to process request" },
      { status: 400 }
    );
  }
}
