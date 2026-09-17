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
  return (
    <>
      <a
        href="/portal/correspondence"
        style={{
          position: "fixed",
          right: 24,
          bottom: 24,
          zIndex: 50,
          borderRadius: 999,
          padding: "12px 18px",
          background: "#ffffff",
          color: "#111827",
          border: "1px solid #d1d5db",
          boxShadow: "0 8px 24px rgba(0,0,0,.12)",
          fontWeight: 700,
          textDecoration: "none",
        }}
      >
        Open Correspondence Centre →
      </a>
      <PortalClient />
    </>
  );
}
