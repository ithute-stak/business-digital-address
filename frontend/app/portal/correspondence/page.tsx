import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { ACCESS_COOKIE, REFRESH_COOKIE, getBdaServerConfig } from "../../../lib/oidc";
import CorrespondenceClient from "./CorrespondenceClient";

export const metadata = {
  title: "Official Correspondence · Business Digital Address",
};

export const dynamic = "force-dynamic";

export default async function CorrespondencePage() {
  const config = getBdaServerConfig();
  const cookieStore = await cookies();
  const hasSession = Boolean(cookieStore.get(ACCESS_COOKIE)?.value || cookieStore.get(REFRESH_COOKIE)?.value);
  if (!config.devAuthBypass && !hasSession) {
    redirect("/api/auth/login?return_to=/portal/correspondence");
  }
  return <CorrespondenceClient />;
}
