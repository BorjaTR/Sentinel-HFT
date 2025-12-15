import { NextRequest, NextResponse } from "next/server";

export const runtime = "edge";

// Demo analysis result (same as frontend for consistency)
const DEMO_RESULT = {
  id: "demo-analysis-001",
  timestamp: new Date().toISOString(),
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

export async function GET(request: NextRequest) {
  // Return demo analysis result
  return NextResponse.json({
    success: true,
    demo: true,
    result: DEMO_RESULT,
  });
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { budget = 850, apiKey } = body;

    // Check if this is a pro user with API key
    if (apiKey) {
      // In production, validate API key and process actual trace file
      // For now, return enhanced demo result
      return NextResponse.json({
        success: true,
        demo: false,
        message: "API key validation would happen here",
        result: {
          ...DEMO_RESULT,
          budget,
          budgetMet: 847 <= budget,
        },
      });
    }

    // Demo mode - return pre-computed result
    return NextResponse.json({
      success: true,
      demo: true,
      result: {
        ...DEMO_RESULT,
        budget,
        budgetMet: 847 <= budget,
      },
    });
  } catch (error) {
    return NextResponse.json(
      {
        success: false,
        error: "Failed to process request",
      },
      { status: 400 }
    );
  }
}
