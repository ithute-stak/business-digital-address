"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import "./portal.css";

type OfficialAddress = {
  address: string;
  local_part: string;
  domain: string;
  mailbox_status: string;
  friendly_alias?: string | null;
};

type Business = {
  id: string;
  registration_number: string;
  tin: string;
  legal_name: string;
  trading_name?: string | null;
  status: string;
  official_address?: OfficialAddress | null;
  created_at: string;
};

type Member = {
  id: string;
  auth_user_sub?: string | null;
  role: string;
  status: string;
  invited_email?: string | null;
  invited_phone?: string | null;
  created_at: string;
};

type ExternalEmail = {
  id: string;
  email: string;
  status: string;
  forward_official_mail: boolean;
  verified_at?: string | null;
  created_at: string;
};

type Delivery = { channel: string; target: string; status: string; last_error?: string | null };

type Message = {
  id: string;
  external_message_id: string;
  agency_code: string;
  agency_name: string;
  subject: string;
  body_text: string;
  classification: string;
  status: string;
  received_at: string;
  deliveries: Delivery[];
};

type AuditEvent = {
  id: string;
  actor_type: string;
  actor_id: string;
  action: string;
  details: Record<string, unknown>;
  created_at: string;
};

type Snapshot = {
  business: Business;
  summary: {
    official_messages: number;
    authorised_members: number;
    verified_external_emails: number;
    pending_actions: number;
  };
  members: Member[];
  external_emails: ExternalEmail[];
  messages: Message[];
  audit: AuditEvent[];
};

type View = "dashboard" | "business" | "inbox" | "email" | "members" | "audit" | "settings";

const API = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8100").replace(/\/$/, "");

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = typeof window !== "undefined" ? window.localStorage.getItem("bda_access_token") : null;
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("content-type")) headers.set("content-type", "application/json");
  if (token) headers.set("authorization", `Bearer ${token}`);
  const response = await fetch(`${API}${path}`, { ...init, headers, cache: "no-store" });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail ?? `Request failed (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function niceStatus(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function shortDate(value: string) {
  return new Intl.DateTimeFormat("en-LS", { dateStyle: "medium" }).format(new Date(value));
}

function SidebarButton({ active, icon, label, onClick }: { active: boolean; icon: string; label: string; onClick: () => void }) {
  return (
    <button className={`portalNavItem ${active ? "active" : ""}`} onClick={onClick} type="button">
      <span>{icon}</span><b>{label}</b>
    </button>
  );
}

function StatusBadge({ value }: { value: string }) {
  const good = ["active", "verified", "delivered", "stored"].includes(value.toLowerCase());
  const bad = ["failed", "invite_failed", "provision_failed"].includes(value.toLowerCase());
  return <span className={`portalBadge ${good ? "good" : bad ? "bad" : "warn"}`}>{niceStatus(value)}</span>;
}

export default function PortalClient() {
  const [businesses, setBusinesses] = useState<Business[]>([]);
  const [activeId, setActiveId] = useState<string>("");
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [view, setView] = useState<View>("dashboard");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [selectedMessage, setSelectedMessage] = useState<Message | null>(null);
  const [verification, setVerification] = useState<{ emailId: string; email: string; code: string } | null>(null);

  const reloadSnapshot = async (businessId = activeId) => {
    if (!businessId) return;
    const data = await api<Snapshot>(`/api/v1/businesses/${businessId}/portal`);
    setSnapshot(data);
  };

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const items = await api<Business[]>("/api/v1/businesses");
      setBusinesses(items);
      const id = activeId && items.some((item) => item.id === activeId) ? activeId : items[0]?.id ?? "";
      setActiveId(id);
      if (id) setSnapshot(await api<Snapshot>(`/api/v1/businesses/${id}/portal`));
      else setSnapshot(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load the portal");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);

  useEffect(() => {
    if (!activeId || loading) return;
    setSelectedMessage(null);
    void reloadSnapshot(activeId).catch((err) => setError(err instanceof Error ? err.message : "Unable to load business"));
  }, [activeId]);

  const filteredMessages = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!snapshot) return [];
    if (!query) return snapshot.messages;
    return snapshot.messages.filter((message) =>
      [message.subject, message.agency_name, message.agency_code, message.external_message_id, message.classification]
        .join(" ").toLowerCase().includes(query),
    );
  }, [snapshot, search]);

  const run = async (work: () => Promise<void>, success?: string) => {
    setBusy(true); setError(""); setNotice("");
    try {
      await work();
      if (success) setNotice(success);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  const createBusiness = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await run(async () => {
      const created = await api<Business>("/api/v1/businesses", {
        method: "POST",
        body: JSON.stringify({
          registration_number: form.get("registration_number"),
          tin: form.get("tin"),
          legal_name: form.get("legal_name"),
          trading_name: form.get("trading_name") || null,
        }),
      });
      setActiveId(created.id);
      await load();
    }, "Business registered and official digital address reserved.");
  };

  const addEmail = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!snapshot) return;
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email") ?? "");
    await run(async () => {
      const result = await api<ExternalEmail & { verification_code?: string | null }>(
        `/api/v1/businesses/${snapshot.business.id}/external-emails`,
        { method: "POST", body: JSON.stringify({ email, forward_official_mail: true }) },
      );
      if (result.verification_code) setVerification({ emailId: result.id, email: result.email, code: result.verification_code });
      await reloadSnapshot();
      event.currentTarget.reset();
    }, "Custom email added. Verify it before forwarding is trusted.");
  };

  const verifyEmail = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!snapshot || !verification) return;
    const form = new FormData(event.currentTarget);
    await run(async () => {
      await api(`/api/v1/businesses/${snapshot.business.id}/external-emails/${verification.emailId}/verify`, {
        method: "POST", body: JSON.stringify({ code: form.get("code") }),
      });
      setVerification(null);
      await reloadSnapshot();
    }, "Custom business email verified.");
  };

  const inviteMember = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!snapshot) return;
    const form = new FormData(event.currentTarget);
    const channel = String(form.get("preferred_channel") ?? "email");
    await run(async () => {
      await api(`/api/v1/businesses/${snapshot.business.id}/members`, {
        method: "POST",
        body: JSON.stringify({
          display_name: form.get("display_name"),
          role: form.get("role"),
          preferred_channel: channel,
          email: channel === "email" ? form.get("target") : null,
          phone: channel === "phone" ? form.get("target") : null,
        }),
      });
      event.currentTarget.reset();
      await reloadSnapshot();
    }, "Member invitation recorded.");
  };

  if (loading) return <div className="portalLoading">Loading Business Digital Address…</div>;

  if (!businesses.length && !error) {
    return (
      <main className="onboardingPage">
        <section className="onboardingCard">
          <a href="/" className="portalBrand"><span>B</span><b>business.ls</b></a>
          <p className="eyebrow">Business onboarding</p>
          <h1>Create your first official business profile.</h1>
          <p className="portalMuted">The business record stays in this product. Ithute provides identity and mailbox infrastructure.</p>
          <form className="portalForm" onSubmit={createBusiness}>
            <label>Legal business name<input name="legal_name" required placeholder="Tjekatjeka Holdings (Pty) Ltd" /></label>
            <label>Trading name<input name="trading_name" placeholder="Tjekatjeka Holdings" /></label>
            <div className="formGrid">
              <label>Registration number<input name="registration_number" required placeholder="2026/ABC-001" /></label>
              <label>TIN<input name="tin" required placeholder="200012345" /></label>
            </div>
            <button className="portalPrimary" disabled={busy}>Create business profile</button>
          </form>
        </section>
      </main>
    );
  }

  if (error && !snapshot) {
    return (
      <main className="onboardingPage">
        <section className="onboardingCard">
          <a href="/" className="portalBrand"><span>B</span><b>business.ls</b></a>
          <h1>Portal access is not available yet.</h1>
          <p className="portalError">{error}</p>
          <p className="portalMuted">In development, start the API with authentication disabled. Production access will use the registered Ithute Auth OIDC redirect.</p>
          <button className="portalPrimary" onClick={() => void load()}>Retry</button>
        </section>
      </main>
    );
  }

  if (!snapshot) return null;
  const business = snapshot.business;

  return (
    <div className="portalShell">
      <aside className="portalSidebar">
        <a href="/" className="portalBrand light"><span>B</span><b>business.ls</b></a>
        <nav>
          <SidebarButton active={view === "dashboard"} icon="⌂" label="Dashboard" onClick={() => setView("dashboard")} />
          <SidebarButton active={view === "business"} icon="▥" label="My Business" onClick={() => setView("business")} />
          <SidebarButton active={view === "inbox"} icon="✉" label="Official Inbox" onClick={() => setView("inbox")} />
          <SidebarButton active={view === "email"} icon="↗" label="Email Settings" onClick={() => setView("email")} />
          <SidebarButton active={view === "members"} icon="♙" label="Members" onClick={() => setView("members")} />
          <SidebarButton active={view === "audit"} icon="⌁" label="Audit Log" onClick={() => setView("audit")} />
          <SidebarButton active={view === "settings"} icon="⚙" label="Settings" onClick={() => setView("settings")} />
        </nav>
        <div className="sidebarBusiness">
          <span className="avatar">{(business.trading_name || business.legal_name).slice(0, 2).toUpperCase()}</span>
          <div><b>{business.trading_name || business.legal_name}</b><small>Business portal</small></div>
        </div>
      </aside>

      <main className="portalMain">
        <header className="portalTopbar">
          <div className="mobileBrand">business.ls</div>
          <div className="topbarRight">
            <span className="securityDot">●</span><span>Ithute secured</span>
            <select value={activeId} onChange={(event) => setActiveId(event.target.value)} aria-label="Active business">
              {businesses.map((item) => <option value={item.id} key={item.id}>{item.trading_name || item.legal_name}</option>)}
            </select>
          </div>
        </header>

        <section className="portalContent">
          {(notice || error) && <div className={`portalNotice ${error ? "error" : "success"}`}>{error || notice}</div>}

          {view === "dashboard" && <>
            <div className="pageHeading"><div><p className="eyebrow">Business overview</p><h1>Welcome back, {business.trading_name || business.legal_name}</h1><p>Here is the current state of your official business digital address.</p></div></div>
            <article className="businessHeroCard">
              <div className="businessIcon">▥</div>
              <div className="businessSummary"><div className="businessTitle"><h2>{business.legal_name}</h2><StatusBadge value={business.status} /></div>
                <dl><dt>Registration Number</dt><dd>{business.registration_number}</dd><dt>TIN</dt><dd>{business.tin}</dd><dt>Official Address</dt><dd>{business.official_address?.address ?? "Pending"}</dd></dl>
              </div>
              <button className="portalSecondary" onClick={() => setView("business")}>View details</button>
            </article>
            <div className="metricGrid">
              <article><span>✉</span><strong>{snapshot.summary.official_messages}</strong><small>Official messages</small></article>
              <article><span>♙</span><strong>{snapshot.summary.authorised_members}</strong><small>Authorised members</small></article>
              <article><span>↗</span><strong>{snapshot.summary.verified_external_emails}</strong><small>Verified custom emails</small></article>
              <article><span>!</span><strong>{snapshot.summary.pending_actions}</strong><small>Pending actions</small></article>
            </div>
            <div className="portalPanel"><div className="panelHeading"><h2>Recent official communications</h2><button className="textButton" onClick={() => setView("inbox")}>Open inbox →</button></div>
              {snapshot.messages.slice(0, 4).map((message) => <div className="activityRow" key={message.id}><span className="agencyMark">{message.agency_code.slice(0, 1).toUpperCase()}</span><div><b>{message.subject}</b><small>{message.agency_name} · {shortDate(message.received_at)}</small></div><StatusBadge value={message.status} /></div>)}
              {!snapshot.messages.length && <div className="emptyState">No official communications have been received yet.</div>}
            </div>
          </>}

          {view === "business" && <>
            <div className="pageHeading"><div><p className="eyebrow">My Business</p><h1>Registered business details</h1><p>The identifiers used to route official communications.</p></div></div>
            <div className="twoColumn">
              <article className="portalPanel"><h2>Basic information</h2><dl className="detailList"><dt>Legal name</dt><dd>{business.legal_name}</dd><dt>Trading name</dt><dd>{business.trading_name || "—"}</dd><dt>Registration number</dt><dd>{business.registration_number}</dd><dt>TIN</dt><dd>{business.tin}</dd><dt>Status</dt><dd><StatusBadge value={business.status} /></dd><dt>Created</dt><dd>{shortDate(business.created_at)}</dd></dl></article>
              <article className="portalPanel"><h2>Official digital address</h2><div className="officialAddressBig">{business.official_address?.address ?? "Not assigned"}</div><p className="portalMuted">This address is stable and separate from the private TIN directory value.</p><div className="addressStatus"><span>Mailbox</span><StatusBadge value={business.official_address?.mailbox_status ?? "pending"} /></div>{business.official_address?.mailbox_status !== "active" && <button className="portalPrimary" disabled={busy} onClick={() => void run(async () => { await api(`/api/v1/businesses/${business.id}/official-address/provision`, { method: "POST" }); await reloadSnapshot(); }, "Mailbox provisioning completed.")}>Provision mailbox</button>}</article>
            </div>
          </>}

          {view === "inbox" && <>
            <div className="pageHeading inboxHeading"><div><p className="eyebrow">Official Inbox</p><h1>Government communications</h1><p>Messages retained for this registered business.</p></div><input className="searchBox" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search messages…" /></div>
            <div className="inboxLayout">
              <div className="portalPanel inboxTableWrap"><table className="portalTable"><thead><tr><th>From</th><th>Subject</th><th>Reference</th><th>Date</th><th>Status</th></tr></thead><tbody>{filteredMessages.map((message) => <tr key={message.id} onClick={() => setSelectedMessage(message)} className={selectedMessage?.id === message.id ? "selected" : ""}><td><b>{message.agency_code.toUpperCase()}</b></td><td>{message.subject}</td><td>{message.external_message_id}</td><td>{shortDate(message.received_at)}</td><td><StatusBadge value={message.status} /></td></tr>)}</tbody></table>{!filteredMessages.length && <div className="emptyState">No messages match this view.</div>}</div>
              {selectedMessage && <article className="portalPanel messageDetail"><div className="panelHeading"><div><p className="eyebrow">{selectedMessage.agency_name}</p><h2>{selectedMessage.subject}</h2></div><button className="textButton" onClick={() => setSelectedMessage(null)}>Close</button></div><p>{selectedMessage.body_text}</p><dl className="detailList compact"><dt>Reference</dt><dd>{selectedMessage.external_message_id}</dd><dt>Classification</dt><dd>{niceStatus(selectedMessage.classification)}</dd><dt>Received</dt><dd>{shortDate(selectedMessage.received_at)}</dd></dl><h3>Delivery record</h3>{selectedMessage.deliveries.map((delivery, index) => <div className="deliveryRow" key={`${delivery.channel}-${index}`}><div><b>{niceStatus(delivery.channel)}</b><small>{delivery.target}</small></div><StatusBadge value={delivery.status} /></div>)}</article>}
            </div>
          </>}

          {view === "email" && <>
            <div className="pageHeading"><div><p className="eyebrow">Email Settings</p><h1>Official address & forwarding</h1><p>Keep the official copy while optionally routing a copy to a verified company email.</p></div></div>
            <article className="portalPanel addressSettings"><span className="mailIcon">✉</span><div><small>Official Business Address</small><h2>{business.official_address?.address}</h2></div><StatusBadge value={business.official_address?.mailbox_status ?? "pending"} /></article>
            <article className="portalPanel"><div className="panelHeading"><div><h2>Custom email forwarding</h2><p className="portalMuted">Forwarding remains separate from the retained official inbox.</p></div></div>
              {snapshot.external_emails.map((item) => <div className="emailRow" key={item.id}><div><b>{item.email}</b><small><StatusBadge value={item.status} /> {item.forward_official_mail ? "Forwarding requested" : "Forwarding disabled"}</small></div><div className="rowActions"><button className="portalSecondary" disabled={busy} onClick={() => void run(async () => { await api(`/api/v1/businesses/${business.id}/external-emails/${item.id}`, { method: "PATCH", body: JSON.stringify({ forward_official_mail: !item.forward_official_mail }) }); await reloadSnapshot(); })}>{item.forward_official_mail ? "Disable" : "Enable"}</button><button className="dangerButton" disabled={busy} onClick={() => void run(async () => { await api(`/api/v1/businesses/${business.id}/external-emails/${item.id}`, { method: "DELETE" }); await reloadSnapshot(); }, "Custom email removed.")}>Remove</button></div></div>)}
              {!snapshot.external_emails.length && <div className="emptyState">No custom business email is attached yet.</div>}
              <form className="inlineForm" onSubmit={addEmail}><input type="email" name="email" required placeholder="info@yourcompany.co.ls" /><button className="portalPrimary" disabled={busy}>Add custom email</button></form>
              {verification && <form className="verificationBox" onSubmit={verifyEmail}><div><b>Verify {verification.email}</b><p>Development verification code: <code>{verification.code}</code></p></div><input name="code" required defaultValue={verification.code} /><button className="portalPrimary" disabled={busy}>Verify</button></form>}
            </article>
          </>}

          {view === "members" && <>
            <div className="pageHeading"><div><p className="eyebrow">Members</p><h1>Authorised business access</h1><p>Business roles live here; passwords and MFA remain in Ithute Auth.</p></div></div>
            <article className="portalPanel"><div className="memberGrid">{snapshot.members.map((member) => <div className="memberCard" key={member.id}><span className="avatar">{(member.invited_email || member.invited_phone || "ID").slice(0, 2).toUpperCase()}</span><div><b>{member.invited_email || member.invited_phone || "Ithute identity"}</b><small>{niceStatus(member.role)} · <StatusBadge value={member.status} /></small></div></div>)}</div></article>
            <article className="portalPanel"><h2>Invite a member</h2><form className="portalForm compactForm" onSubmit={inviteMember}><div className="formGrid"><label>Display name<input name="display_name" required /></label><label>Role<select name="role"><option value="member">Member</option><option value="admin">Admin</option><option value="owner">Owner</option></select></label></div><div className="formGrid"><label>Invitation channel<select name="preferred_channel"><option value="email">Email</option><option value="phone">Phone</option></select></label><label>Email or phone<input name="target" required /></label></div><button className="portalPrimary" disabled={busy}>Send invitation</button></form></article>
          </>}

          {view === "audit" && <>
            <div className="pageHeading"><div><p className="eyebrow">Audit Log</p><h1>Business activity history</h1><p>A chronological record of sensitive business actions.</p></div></div>
            <article className="portalPanel"><table className="portalTable auditTable"><thead><tr><th>Action</th><th>Actor</th><th>Details</th><th>Date</th></tr></thead><tbody>{snapshot.audit.map((event) => <tr key={event.id}><td><b>{niceStatus(event.action)}</b></td><td>{event.actor_type}: {event.actor_id}</td><td><code>{JSON.stringify(event.details)}</code></td><td>{shortDate(event.created_at)}</td></tr>)}</tbody></table></article>
          </>}

          {view === "settings" && <>
            <div className="pageHeading"><div><p className="eyebrow">Settings</p><h1>Platform status</h1><p>Configuration visible to this browser session.</p></div></div>
            <div className="twoColumn"><article className="portalPanel"><h2>Integration</h2><dl className="detailList"><dt>API</dt><dd>{API}</dd><dt>Human identity</dt><dd>Ithute Auth</dd><dt>Official domain</dt><dd>{business.official_address?.domain ?? "business.ls"}</dd><dt>Mailbox state</dt><dd><StatusBadge value={business.official_address?.mailbox_status ?? "pending"} /></dd></dl></article><article className="portalPanel"><h2>Production readiness</h2><p className="portalMuted">OIDC browser redirect registration, `business.ls` domain control and the Ithute service credential/domain grant must be completed before this portal is made public.</p></article></div>
          </>}
        </section>
      </main>
    </div>
  );
}
