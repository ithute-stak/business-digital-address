import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const read = (file) => fs.readFileSync(path.join(root, file), "utf8");

const oidc = read("lib/oidc.ts");
const login = read("app/api/auth/login/route.ts");
const callback = read("app/api/auth/callback/route.ts");
const proxy = read("app/api/bda/[...path]/route.ts");
const portal = read("app/portal/page.tsx");

const checks = [
  [oidc.includes('httpOnly: true'), "session cookies must be HttpOnly"],
  [oidc.includes('sameSite: "lax"'), "session cookies must use SameSite=Lax"],
  [oidc.includes('runtimeEnvironment === "production" && devAuthBypass'), "production must reject the development auth bypass"],
  [oidc.includes('jwtVerify(idToken'), "OIDC ID tokens must be signature verified"],
  [oidc.includes('issuer: config.authUrl') && oidc.includes('audience: config.clientId'), "ID token issuer and audience must be checked"],
  [oidc.includes("expectedNonce") && oidc.includes("constantTimeEqual"), "OIDC nonce must be checked"],
  [login.includes('code_challenge_method", "S256"') && login.includes("pkceChallenge(verifier)"), "login must use PKCE S256"],
  [callback.includes("constantTimeEqual") && callback.includes("STATE_COOKIE"), "OAuth state must be checked"],
  [callback.includes("exchangeAuthorizationCode") && callback.includes("verifyIdToken"), "callback must exchange code and verify ID token"],
  [proxy.includes("refreshSession") && proxy.includes("setSessionCookies"), "BFF must rotate sessions with Ithute refresh tokens"],
  [proxy.includes('headers.set("authorization", `Bearer ${accessToken}`)'), "only the server-side BFF should attach the backend bearer token"],
  [portal.includes("redirect(\"/api/auth/login?return_to=/portal\")"), "portal must send unauthenticated production users through Ithute Auth"],
];

const failed = checks.filter(([ok]) => !ok);
if (failed.length) {
  for (const [, message] of failed) console.error(`FAIL: ${message}`);
  process.exit(1);
}
console.log(`OIDC/BFF security contract passed (${checks.length} checks).`);
