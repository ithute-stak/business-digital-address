import { NextResponse } from "next/server";

import { clearSessionCookies, clearTransientCookies, getBdaServerConfig } from "../../../../lib/oidc";

export const dynamic = "force-dynamic";

export async function GET() {
  const config = getBdaServerConfig();
  const response = NextResponse.redirect(new URL("/", config.appUrl));
  clearSessionCookies(response);
  clearTransientCookies(response);
  return response;
}

export async function POST() {
  const config = getBdaServerConfig();
  const response = NextResponse.json({ status: "signed_out" });
  clearSessionCookies(response);
  clearTransientCookies(response);
  response.headers.set("x-bda-home", config.appUrl);
  return response;
}
