import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { createRemoteJWKSet, jwtVerify } from "jose";
import type { NextResponse } from "next/server";

export const ACCESS_COOKIE = "bda_access";
export const REFRESH_COOKIE = "bda_refresh";
export const PKCE_COOKIE = "bda_pkce";
export const STATE_COOKIE = "bda_state";
export const NONCE_COOKIE = "bda_nonce";
export const RETURN_COOKIE = "bda_return_to";

export type TokenSet = {
  access_token: string;
  refresh_token: string;
  id_token?: string;
  expires_in: number;
};

export type BdaServerConfig = {
  appUrl: string;
  apiInternalUrl: string;
  authUrl: string;
  clientId: string;
  runtimeEnvironment: string;
  devAuthBypass: boolean;
};

function normalizedBaseUrl(raw: string, name: string): string {
  let value: URL;
  try {
    value = new URL(raw);
  } catch {
    throw new Error(`${name} must be an absolute URL`);
  }
  if (!new Set(["http:", "https:"]).has(value.protocol)) {
    throw new Error(`${name} must use http or https`);
  }
  value.pathname = value.pathname.replace(/\/$/, "");
  value.search = "";
  value.hash = "";
  return value.toString().replace(/\/$/, "");
}

export function getBdaServerConfig(): BdaServerConfig {
  const appUrl = normalizedBaseUrl(process.env.BDA_APP_URL ?? "http://localhost:3000", "BDA_APP_URL");
  const apiInternalUrl = normalizedBaseUrl(
    process.env.BDA_API_INTERNAL_URL ?? "http://backend:8100",
    "BDA_API_INTERNAL_URL",
  );
  const authUrl = normalizedBaseUrl(
    process.env.BDA_ITHUTE_AUTH_URL ?? "https://auth.ithute.co.ls",
    "BDA_ITHUTE_AUTH_URL",
  );
  const clientId = (process.env.BDA_OIDC_CLIENT_ID ?? "business-digital-address").trim();
  const runtimeEnvironment = (process.env.BDA_RUNTIME_ENVIRONMENT ?? "development").trim().toLowerCase();
  const devAuthBypass = (process.env.BDA_DEV_AUTH_BYPASS ?? "false").trim().toLowerCase() === "true";

  if (!clientId) throw new Error("BDA_OIDC_CLIENT_ID is required");
  if (runtimeEnvironment === "production" && devAuthBypass) {
    throw new Error("BDA_DEV_AUTH_BYPASS cannot be enabled in production");
  }
  if (runtimeEnvironment === "production" && !appUrl.startsWith("https://")) {
    throw new Error("BDA_APP_URL must use https in production");
  }

  return { appUrl, apiInternalUrl, authUrl, clientId, runtimeEnvironment, devAuthBypass };
}

export function oidcRedirectUri(config = getBdaServerConfig()): string {
  return `${config.appUrl}/api/auth/callback`;
}

export function randomUrlSafe(bytes = 32): string {
  return randomBytes(bytes).toString("base64url");
}

export function pkceChallenge(verifier: string): string {
  return createHash("sha256").update(verifier, "ascii").digest("base64url");
}

export function safeReturnTo(value: string | null | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) return "/portal";
  try {
    const parsed = new URL(value, "https://business.invalid");
    if (parsed.origin !== "https://business.invalid") return "/portal";
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return "/portal";
  }
}

export function constantTimeEqual(left: string | undefined, right: string | undefined): boolean {
  if (!left || !right) return false;
  const a = Buffer.from(left, "utf8");
  const b = Buffer.from(right, "utf8");
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}

function cookieOptions(maxAge: number, config = getBdaServerConfig()) {
  return {
    httpOnly: true,
    secure: config.appUrl.startsWith("https://"),
    sameSite: "lax" as const,
    path: "/",
    maxAge,
  };
}

export function setTransientCookie(response: NextResponse, name: string, value: string, maxAge = 600): void {
  response.cookies.set(name, value, cookieOptions(maxAge));
}

export function clearTransientCookies(response: NextResponse): void {
  for (const name of [PKCE_COOKIE, STATE_COOKIE, NONCE_COOKIE, RETURN_COOKIE]) {
    response.cookies.set(name, "", cookieOptions(0));
  }
}

export function setSessionCookies(response: NextResponse, tokens: TokenSet): void {
  const accessMaxAge = Math.max(60, Number(tokens.expires_in || 600) - 15);
  response.cookies.set(ACCESS_COOKIE, tokens.access_token, cookieOptions(accessMaxAge));
  response.cookies.set(REFRESH_COOKIE, tokens.refresh_token, cookieOptions(30 * 24 * 60 * 60));
}

export function clearSessionCookies(response: NextResponse): void {
  response.cookies.set(ACCESS_COOKIE, "", cookieOptions(0));
  response.cookies.set(REFRESH_COOKIE, "", cookieOptions(0));
}

async function tokenRequest(params: URLSearchParams, config = getBdaServerConfig()): Promise<TokenSet> {
  const response = await fetch(`${config.authUrl}/oauth/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded", accept: "application/json" },
    body: params,
    cache: "no-store",
    redirect: "error",
  });
  if (!response.ok) throw new Error("Ithute Auth token exchange failed");
  const payload = (await response.json()) as Partial<TokenSet>;
  if (
    typeof payload.access_token !== "string" || !payload.access_token ||
    typeof payload.refresh_token !== "string" || !payload.refresh_token ||
    typeof payload.expires_in !== "number"
  ) {
    throw new Error("Ithute Auth returned an invalid token response");
  }
  return payload as TokenSet;
}

export async function exchangeAuthorizationCode(code: string, verifier: string): Promise<TokenSet> {
  const config = getBdaServerConfig();
  return tokenRequest(
    new URLSearchParams({
      grant_type: "authorization_code",
      client_id: config.clientId,
      code,
      redirect_uri: oidcRedirectUri(config),
      code_verifier: verifier,
    }),
    config,
  );
}

export async function refreshSession(refreshToken: string): Promise<TokenSet> {
  const config = getBdaServerConfig();
  return tokenRequest(
    new URLSearchParams({
      grant_type: "refresh_token",
      client_id: config.clientId,
      refresh_token: refreshToken,
    }),
    config,
  );
}

const jwksByUrl = new Map<string, ReturnType<typeof createRemoteJWKSet>>();

export async function verifyIdToken(idToken: string, expectedNonce: string): Promise<void> {
  const config = getBdaServerConfig();
  const jwksUrl = `${config.authUrl}/.well-known/jwks.json`;
  let jwks = jwksByUrl.get(jwksUrl);
  if (!jwks) {
    jwks = createRemoteJWKSet(new URL(jwksUrl));
    jwksByUrl.set(jwksUrl, jwks);
  }
  const { payload } = await jwtVerify(idToken, jwks, {
    algorithms: ["RS256"],
    issuer: config.authUrl,
    audience: config.clientId,
  });
  if (!constantTimeEqual(typeof payload.nonce === "string" ? payload.nonce : undefined, expectedNonce)) {
    throw new Error("Ithute Auth ID token nonce validation failed");
  }
}
