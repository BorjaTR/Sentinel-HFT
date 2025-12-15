import { NextRequest, NextResponse } from "next/server";

export const runtime = "edge";

// Demo trace data for the live visualization
function generateDemoTraces(count: number = 100) {
  const traces = [];
  const stages = ["ingress", "core", "risk", "egress"];
  const baseLatencies = {
    ingress: 77,
    core: 443,
    risk: 264,
    egress: 68,
  };

  for (let i = 0; i < count; i++) {
    const timestamp = i * 3.5; // ~3.5ns between traces at 284K/sec
    const hasAnomaly = Math.random() < 0.02;

    for (const stage of stages) {
      const base = baseLatencies[stage as keyof typeof baseLatencies];
      const variance = base * 0.2;
      const multiplier = hasAnomaly && stage === "core" ? 3 : 1;
      const latency = Math.round(
        (base + (Math.random() - 0.5) * variance * 2) * multiplier
      );

      traces.push({
        id: `trace-${i}-${stage}`,
        timestamp,
        stage,
        latency,
        anomaly: hasAnomaly && stage === "core",
      });
    }
  }

  return traces;
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const count = parseInt(searchParams.get("count") || "100", 10);
  const offset = parseInt(searchParams.get("offset") || "0", 10);

  // Generate demo traces
  const traces = generateDemoTraces(Math.min(count, 1000));

  return NextResponse.json({
    success: true,
    demo: true,
    traces: traces.slice(offset, offset + count),
    total: 1247832,
    hasMore: offset + count < 1247832,
  });
}

export async function POST(request: NextRequest) {
  // Handle file upload (Pro feature)
  try {
    const formData = await request.formData();
    const file = formData.get("file");
    const apiKey = formData.get("apiKey");

    if (!apiKey) {
      return NextResponse.json(
        {
          success: false,
          error: "File upload requires Pro subscription",
          upgradeUrl: "/pricing",
        },
        { status: 403 }
      );
    }

    if (!file) {
      return NextResponse.json(
        { success: false, error: "No file provided" },
        { status: 400 }
      );
    }

    // In production, this would:
    // 1. Validate the API key
    // 2. Parse the binary trace file
    // 3. Run the analysis
    // 4. Return results

    return NextResponse.json({
      success: true,
      message: "File upload processing would happen here",
      demo: false,
    });
  } catch (error) {
    return NextResponse.json(
      { success: false, error: "Failed to process upload" },
      { status: 500 }
    );
  }
}
