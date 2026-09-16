import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET() {
  const base = (process.env.BDA_API_INTERNAL_URL ?? "http://backend:8100").replace(/\/$/, "");
  try {
    const response = await fetch(`${base}/health/ready`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) {
      return NextResponse.json({ status: "not_ready", dependency: "backend" }, { status: 503 });
    }
    return NextResponse.json({ status: "ready", service: "business-digital-address-web" });
  } catch {
    return NextResponse.json({ status: "not_ready", dependency: "backend" }, { status: 503 });
  }
}
