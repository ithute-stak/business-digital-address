import { NextRequest, NextResponse } from "next/server";

import {
  NONCE_COOKIE,
  PKCE_COOKIE,
  RETURN_COOKIE,
  STATE_COOKIE,
  clearSessionCookies,
  clearTransientCookies,
  constantTimeEqual,
  exchangeAuthorizationCode,
  getBdaServerConfig,
  safeReturnTo,
  setSessionCookies,
  verifyIdToken,
} from "../../../../lib/oidc";

export const dynamic = "force-dynamic";

function failedRedirect(config: ReturnType<typeof getBdaServerConfig>, reason: string) {
  const url = new URL("/", config.appUrl);
  url.searchParams.set("auth_error", reason);
  const response = NextResponse.redirect(url);
  clearTransientCookies(response);
  clearSessionCookies(response);
  return response;
}

export async function GET(request: NextRequest) {
  const config = getBdaServerConfig();
  const code = request.nextUrl.searchParams.get("code");
  const state = request.nextUrl.searchParams.get("state");
  const expectedState = request.cookies.get(STATE_COOKIE)?.value;
  const verifier = request.cookies.get(PKCE_COOKIE)?.value;
  const nonce = request.cookies.get(NONCE_COOKIE)?.value;
  const returnTo = safeReturnTo(request.cookies.get(RETURN_COOKIE)?.value);

  if (!code || !verifier || !nonce || !constantTimeEqual(state ?? undefined, expectedState)) {
    return failedRedirect(config, "invalid_oauth_callback");
  }

  try {
    const tokens = await exchangeAuthorizationCode(code, verifier);
    if (!tokens.id_token) throw new Error("Ithute Auth did not return an ID token");
    await verifyIdToken(tokens.id_token, nonce);
    const response = NextResponse.redirect(new URL(returnTo, config.appUrl));
    setSessionCookies(response, tokens);
    clearTransientCookies(response);
    return response;
  } catch {
    return failedRedirect(config, "authentication_failed");
  }
}
