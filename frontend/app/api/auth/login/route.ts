import { NextRequest, NextResponse } from "next/server";

import {
  NONCE_COOKIE,
  PKCE_COOKIE,
  RETURN_COOKIE,
  STATE_COOKIE,
  getBdaServerConfig,
  oidcRedirectUri,
  pkceChallenge,
  randomUrlSafe,
  safeReturnTo,
  setTransientCookie,
} from "../../../../lib/oidc";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const config = getBdaServerConfig();
  const verifier = randomUrlSafe(32);
  const state = randomUrlSafe(32);
  const nonce = randomUrlSafe(32);
  const returnTo = safeReturnTo(request.nextUrl.searchParams.get("return_to"));

  const authorize = new URL(`${config.authUrl}/oauth/authorize`);
  authorize.searchParams.set("response_type", "code");
  authorize.searchParams.set("client_id", config.clientId);
  authorize.searchParams.set("redirect_uri", oidcRedirectUri(config));
  authorize.searchParams.set("code_challenge", pkceChallenge(verifier));
  authorize.searchParams.set("code_challenge_method", "S256");
  authorize.searchParams.set("state", state);
  authorize.searchParams.set("nonce", nonce);
  authorize.searchParams.set("scope", "openid profile email phone");

  const response = NextResponse.redirect(authorize);
  setTransientCookie(response, PKCE_COOKIE, verifier);
  setTransientCookie(response, STATE_COOKIE, state);
  setTransientCookie(response, NONCE_COOKIE, nonce);
  setTransientCookie(response, RETURN_COOKIE, returnTo);
  return response;
}
