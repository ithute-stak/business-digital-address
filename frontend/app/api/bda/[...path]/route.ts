import { NextRequest, NextResponse } from "next/server";

import {
  ACCESS_COOKIE,
  REFRESH_COOKIE,
  TokenSet,
  clearSessionCookies,
  getBdaServerConfig,
  refreshSession,
  setSessionCookies,
} from "../../../../lib/oidc";

export const dynamic = "force-dynamic";

const BODY_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const FORWARDED_REQUEST_HEADERS = ["accept", "content-type", "x-request-id"];
const FORWARDED_RESPONSE_HEADERS = ["content-type", "content-disposition", "etag", "last-modified"];

type RouteContext = { params: Promise<{ path: string[] }> };

function authenticationRequired(clear = false) {
  const response = NextResponse.json(
    { detail: "Ithute Auth session required", login_url: "/api/auth/login?return_to=/portal" },
    { status: 401 },
  );
  response.headers.set("cache-control", "no-store");
  if (clear) clearSessionCookies(response);
  return response;
}

function mutationAllowed(request: NextRequest): boolean {
  if (!BODY_METHODS.has(request.method)) return true;
  const config = getBdaServerConfig();
  const expectedOrigin = new URL(config.appUrl).origin;
  const origin = request.headers.get("origin");
  const fetchSite = request.headers.get("sec-fetch-site")?.toLowerCase();
  if (origin && origin !== expectedOrigin) return false;
  if (fetchSite === "cross-site") return false;
  return true;
}

async function callBackend(
  request: NextRequest,
  path: string[],
  body: Buffer | undefined,
  accessToken: string | null,
): Promise<Response> {
  const config = getBdaServerConfig();
  const encodedPath = path.map((segment) => encodeURIComponent(segment)).join("/");
  const target = new URL(`/${encodedPath}${request.nextUrl.search}`, `${config.apiInternalUrl}/`);
  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  if (accessToken) headers.set("authorization", `Bearer ${accessToken}`);

  return fetch(target, {
    method: request.method,
    headers,
    body: BODY_METHODS.has(request.method) ? body : undefined,
    cache: "no-store",
    redirect: "manual",
  });
}

async function copyResponse(upstream: Response): Promise<NextResponse> {
  const body = upstream.status === 204 ? null : Buffer.from(await upstream.arrayBuffer());
  const response = new NextResponse(body, { status: upstream.status });
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) response.headers.set(name, value);
  }
  response.headers.set("cache-control", "no-store");
  return response;
}

async function proxy(request: NextRequest, context: RouteContext) {
  const config = getBdaServerConfig();
  if (!mutationAllowed(request)) {
    return NextResponse.json({ detail: "Cross-origin mutation rejected" }, { status: 403 });
  }

  const { path } = await context.params;
  if (!path.length) return NextResponse.json({ detail: "API path required" }, { status: 404 });

  const body = BODY_METHODS.has(request.method)
    ? Buffer.from(await request.arrayBuffer())
    : undefined;
  let accessToken = request.cookies.get(ACCESS_COOKIE)?.value ?? null;
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value ?? null;
  let refreshed: TokenSet | null = null;
  let refreshFailed = false;

  if (!accessToken && refreshToken) {
    try {
      refreshed = await refreshSession(refreshToken);
      accessToken = refreshed.access_token;
    } catch {
      refreshFailed = true;
    }
  }

  if (!accessToken && !config.devAuthBypass) {
    return authenticationRequired(refreshFailed);
  }

  let upstream = await callBackend(request, path, body, accessToken);

  if (upstream.status === 401 && refreshToken && !refreshed) {
    try {
      refreshed = await refreshSession(refreshToken);
      accessToken = refreshed.access_token;
      upstream = await callBackend(request, path, body, accessToken);
    } catch {
      return authenticationRequired(true);
    }
  }

  if (upstream.status === 401 && !config.devAuthBypass) {
    return authenticationRequired(Boolean(refreshToken));
  }

  const response = await copyResponse(upstream);
  if (refreshed) setSessionCookies(response, refreshed);
  return response;
}

export async function GET(request: NextRequest, context: RouteContext) { return proxy(request, context); }
export async function POST(request: NextRequest, context: RouteContext) { return proxy(request, context); }
export async function PUT(request: NextRequest, context: RouteContext) { return proxy(request, context); }
export async function PATCH(request: NextRequest, context: RouteContext) { return proxy(request, context); }
export async function DELETE(request: NextRequest, context: RouteContext) { return proxy(request, context); }
