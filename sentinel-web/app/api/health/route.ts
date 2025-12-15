import { NextRequest, NextResponse } from "next/server";

export const runtime = "edge";

export async function GET(request: NextRequest) {
  return NextResponse.json({
    status: "healthy",
    version: "2.2.0",
    timestamp: new Date().toISOString(),
    features: {
      aiAnalysis: true,
      liveDemo: true,
      fileUpload: false, // Requires Pro
      apiAccess: false, // Requires Pro
    },
    demo: true,
  });
}
