import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import PortalClient from "./PortalClient";
import { ACCESS_COOKIE, REFRESH_COOKIE, getBdaServerConfig } from "../../lib/oidc";

export const metadata = {
  title: "Business Portal · Business Digital Address",
};

export const dynamic = "force-dynamic";

export default async function PortalPage() {
  const config = getBdaServerConfig();
  const cookieStore = await cookies();
  const hasSession = Boolean(cookieStore.get(ACCESS_COOKIE)?.value || cookieStore.get(REFRESH_COOKIE)?.value);
  if (!config.devAuthBypass && !hasSession) {
    redirect("/api/auth/login?return_to=/portal");
  }
  return <PortalClient />;
}
