"use client";

import { useEffect, useMemo, useState } from "react";
import "../portal.css";

type Business = {
  id: string;
  legal_name: string;
  trading_name?: string | null;
  registration_number: string;
  tin: string;
  official_address?: { address: string; mailbox_status: string } | null;
};

type Delivery = {
  id: string;
  channel: string;
  target: string;
  status: string;
  provider_reference?: string | null;
  last_error?: string | null;
  delivered_at?: string | null;
  created_at: string;
};

type Attachment = {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256_hex: string;
  created_at: string;
};

type Acknowledgement = {
  id: string;
  member_id: string;
  actor_sub: string;
  acknowledged_at: string;
};

type InboxMessage = {
  id: string;
  external_message_id: string;
  agency_code: string;
  agency_name: string;
  subject: string;
  body_text: string;
  classification: string;
  status: string;
  received_at: string;
  state: { is_read: boolean; starred: boolean; archived: boolean; read_at?: string | null };
  attachments: Attachment[];
  acknowledgements: Acknowledgement[];
  deliveries: Delivery[];
};

type InboxPage = {
  items: InboxMessage[];
  total: number;
  unread: number;
  starred: number;
  limit: number;
  offset: number;
};

type Snapshot = {
  business: Business;
  members: Array<{ id: string; role: string; status: string; invited_email?: string | null; invited_phone?: string | null }>;
};

type Receipt = {
  receipt_id: string;
  message_id: string;
  external_message_id: string;
  agency_code: string;
  agency_name: string;
  subject: string;
  classification: string;
  received_at: string;
  business: {
    legal_name: string;
    trading_name?: string | null;
    registration_number: string;
    tin: string;
    official_address?: string | null;
  };
  deliveries: Delivery[];
  acknowledgements: Acknowledgement[];
  attachment_count: number;
  generated_at: string;
};

type AdminOps = {
  businesses: number;
  active_official_addresses: number;
  pending_mailboxes: number;
  official_messages: number;
  messages_last_24h: number;
  verified_forwarding_addresses: number;
  forwarding_failures: number;
  active_agencies: number;
  acknowledgements: number;
  attachments: number;
  recent_failures: Array<Record<string, unknown>>;
  recent_audit: Array<Record<string, unknown>>;
};

const API = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8100").replace(/\/$/, "");

function token() {
  return typeof window === "undefined" ? null : window.localStorage.getItem("bda_access_token");
}

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const accessToken = token();
  if (accessToken) headers.set("authorization", `Bearer ${accessToken}`);
  if (init.body && !headers.has("content-type")) headers.set("content-type", "application/json");
  const response = await fetch(`${API}${path}`, { ...init, headers, cache: "no-store" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function label(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function dateTime(value?: string | null) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-LS", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function bytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function Badge({ value }: { value: string }) {
  const normalized = value.toLowerCase();
  const good = ["active", "delivered", "stored", "verified", "sent"].includes(normalized);
  const bad = ["failed", "provision_failed", "invite_failed"].includes(normalized);
  return <span className={`portalBadge ${good ? "good" : bad ? "bad" : "warn"}`}>{label(value)}</span>;
}

export default function CorrespondenceClient() {
  const [businesses, setBusinesses] = useState<Business[]>([]);
  const [businessId, setBusinessId] = useState("");
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [inbox, setInbox] = useState<InboxPage | null>(null);
  const [selected, setSelected] = useState<InboxMessage | null>(null);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [admin, setAdmin] = useState<AdminOps | null>(null);
  const [query, setQuery] = useState("");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [starredOnly, setStarredOnly] = useState(false);
  const [archived, setArchived] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const activeBusiness = useMemo(
    () => businesses.find((item) => item.id === businessId) ?? null,
    [businesses, businessId],
  );

  const loadInbox = async (id = businessId) => {
    if (!id) return;
    const params = new URLSearchParams();
    if (query.trim()) params.set("q", query.trim());
    if (unreadOnly) params.set("unread_only", "true");
    if (starredOnly) params.set("starred_only", "true");
    if (archived) params.set("archived", "true");
    params.set("limit", "100");
    const data = await api<InboxPage>(`/api/v1/businesses/${id}/inbox?${params.toString()}`);
    setInbox(data);
    if (selected) setSelected(data.items.find((item) => item.id === selected.id) ?? null);
  };

  const loadBusiness = async (id: string) => {
    if (!id) return;
    const [portal] = await Promise.all([
      api<Snapshot>(`/api/v1/businesses/${id}/portal`),
      loadInbox(id),
    ]);
    setSnapshot(portal);
  };

  useEffect(() => {
    void (async () => {
      try {
        const items = await api<Business[]>("/api/v1/businesses");
        setBusinesses(items);
        const id = items[0]?.id ?? "";
        setBusinessId(id);
        if (id) await loadBusiness(id);
        try {
          setAdmin(await api<AdminOps>("/api/v1/admin/operations"));
        } catch {
          setAdmin(null);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unable to load correspondence centre");
      }
    })();
  }, []);

  useEffect(() => {
    if (!businessId) return;
    const timer = window.setTimeout(() => {
      void loadInbox().catch((err) => setError(err instanceof Error ? err.message : "Unable to load inbox"));
    }, 180);
    return () => window.clearTimeout(timer);
  }, [query, unreadOnly, starredOnly, archived, businessId]);

  const run = async (work: () => Promise<void>, success?: string) => {
    setBusy(true); setError(""); setNotice("");
    try {
      await work();
      if (success) setNotice(success);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  };

  const updateState = (message: InboxMessage, patch: Record<string, boolean>) => run(async () => {
    await api(`/api/v1/businesses/${businessId}/messages/${message.id}/state`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    });
    await loadInbox();
  });

  const openMessage = (message: InboxMessage) => {
    setSelected(message);
    setReceipt(null);
    if (!message.state.is_read) void updateState(message, { is_read: true });
  };

  const acknowledge = (message: InboxMessage) => run(async () => {
    await api(`/api/v1/businesses/${businessId}/messages/${message.id}/acknowledgements`, { method: "POST" });
    await loadInbox();
  }, "Receipt acknowledged and audit history updated.");

  const showReceipt = (message: InboxMessage) => run(async () => {
    setReceipt(await api<Receipt>(`/api/v1/businesses/${businessId}/messages/${message.id}/receipt`));
  });

  const retryDelivery = (message: InboxMessage, delivery: Delivery) => run(async () => {
    await api(`/api/v1/businesses/${businessId}/messages/${message.id}/deliveries/${delivery.id}/retry`, { method: "POST" });
    await loadInbox();
  }, "Forwarding retry requested.");

  const downloadAttachment = async (message: InboxMessage, attachment: Attachment) => {
    setError("");
    try {
      const headers = new Headers();
      const accessToken = token();
      if (accessToken) headers.set("authorization", `Bearer ${accessToken}`);
      const response = await fetch(
        `${API}/api/v1/businesses/${businessId}/messages/${message.id}/attachments/${attachment.id}`,
        { headers, cache: "no-store" },
      );
      if (!response.ok) throw new Error(`Attachment download failed (${response.status})`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = attachment.filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Attachment download failed");
    }
  };

  const changeRole = (memberId: string, role: string) => run(async () => {
    await api(`/api/v1/businesses/${businessId}/members/${memberId}/role`, {
      method: "PATCH",
      body: JSON.stringify({ role }),
    });
    await loadBusiness(businessId);
  }, "Member role updated.");

  return (
    <main className="portalContent" style={{ maxWidth: 1500, margin: "0 auto" }}>
      <div className="pageHeading">
        <div>
          <p className="eyebrow">Pre-production correspondence suite</p>
          <h1>Official Correspondence Centre</h1>
          <p>Read, acknowledge, archive, prove and monitor official business communication.</p>
        </div>
        <div className="rowActions">
          <a className="portalSecondary" href="/portal">← Business portal</a>
          <select value={businessId} onChange={(event) => { setBusinessId(event.target.value); setSelected(null); setReceipt(null); void loadBusiness(event.target.value); }}>
            {businesses.map((business) => <option key={business.id} value={business.id}>{business.trading_name || business.legal_name}</option>)}
          </select>
        </div>
      </div>

      {(notice || error) && <div className={`portalNotice ${error ? "error" : "success"}`}>{error || notice}</div>}

      {activeBusiness && <article className="businessHeroCard">
        <div className="businessIcon">✉</div>
        <div className="businessSummary">
          <div className="businessTitle"><h2>{activeBusiness.legal_name}</h2><Badge value={activeBusiness.official_address?.mailbox_status ?? "pending"} /></div>
          <dl><dt>Registration</dt><dd>{activeBusiness.registration_number}</dd><dt>TIN</dt><dd>{activeBusiness.tin}</dd><dt>Official address</dt><dd>{activeBusiness.official_address?.address ?? "Pending"}</dd></dl>
        </div>
      </article>}

      <div className="metricGrid">
        <article><span>✉</span><strong>{inbox?.total ?? 0}</strong><small>Messages in view</small></article>
        <article><span>●</span><strong>{inbox?.unread ?? 0}</strong><small>Unread</small></article>
        <article><span>★</span><strong>{inbox?.starred ?? 0}</strong><small>Starred</small></article>
        <article><span>!</span><strong>{admin?.forwarding_failures ?? 0}</strong><small>Forwarding failures</small></article>
      </div>

      <article className="portalPanel">
        <div className="panelHeading">
          <div><h2>Official inbox</h2><p className="portalMuted">Original BDA records remain canonical even when copies are forwarded externally.</p></div>
          <div className="rowActions">
            <label><input type="checkbox" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} /> Unread</label>
            <label><input type="checkbox" checked={starredOnly} onChange={(e) => setStarredOnly(e.target.checked)} /> Starred</label>
            <label><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> Archive</label>
          </div>
        </div>
        <input className="searchBox" style={{ width: "100%", marginBottom: 16 }} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search subject, body, reference or agency…" />
        <div className="inboxLayout">
          <div className="inboxTableWrap">
            <table className="portalTable">
              <thead><tr><th></th><th>Agency</th><th>Subject</th><th>Reference</th><th>Received</th><th>Attachments</th></tr></thead>
              <tbody>{inbox?.items.map((message) => <tr key={message.id} className={selected?.id === message.id ? "selected" : ""} onClick={() => openMessage(message)}>
                <td>{message.state.starred ? "★" : message.state.is_read ? "" : "●"}</td>
                <td><b>{message.agency_code.toUpperCase()}</b></td>
                <td>{message.subject}</td>
                <td>{message.external_message_id}</td>
                <td>{dateTime(message.received_at)}</td>
                <td>{message.attachments.length || "—"}</td>
              </tr>)}</tbody>
            </table>
            {!inbox?.items.length && <div className="emptyState">No official messages match this view.</div>}
          </div>

          {selected && <article className="messageDetail">
            <div className="panelHeading"><div><p className="eyebrow">{selected.agency_name}</p><h2>{selected.subject}</h2></div><button className="textButton" onClick={() => setSelected(null)}>Close</button></div>
            <p>{selected.body_text}</p>
            <dl className="detailList compact"><dt>Reference</dt><dd>{selected.external_message_id}</dd><dt>Classification</dt><dd>{label(selected.classification)}</dd><dt>Received</dt><dd>{dateTime(selected.received_at)}</dd></dl>
            <div className="rowActions" style={{ flexWrap: "wrap", marginBottom: 16 }}>
              <button className="portalSecondary" disabled={busy} onClick={() => void updateState(selected, { starred: !selected.state.starred })}>{selected.state.starred ? "Unstar" : "★ Star"}</button>
              <button className="portalSecondary" disabled={busy} onClick={() => void updateState(selected, { archived: !selected.state.archived })}>{selected.state.archived ? "Restore" : "Archive"}</button>
              <button className="portalPrimary" disabled={busy || selected.acknowledgements.length > 0} onClick={() => void acknowledge(selected)}>{selected.acknowledgements.length ? "Acknowledged" : "Acknowledge receipt"}</button>
              <button className="portalSecondary" disabled={busy} onClick={() => void showReceipt(selected)}>Official receipt</button>
            </div>

            {selected.attachments.length > 0 && <><h3>Attachments</h3>{selected.attachments.map((attachment) => <div className="deliveryRow" key={attachment.id}><div><b>{attachment.filename}</b><small>{attachment.content_type} · {bytes(attachment.size_bytes)} · SHA-256 {attachment.sha256_hex.slice(0, 12)}…</small></div><button className="portalSecondary" onClick={() => void downloadAttachment(selected, attachment)}>Download</button></div>)}</>}

            <h3>Delivery record</h3>
            {selected.deliveries.map((delivery) => <div className="deliveryRow" key={delivery.id}><div><b>{label(delivery.channel)}</b><small>{delivery.target}{delivery.last_error ? ` · ${delivery.last_error}` : ""}</small></div><div className="rowActions"><Badge value={delivery.status} />{delivery.channel === "external_forward" && ["failed", "pending_provider"].includes(delivery.status) && <button className="portalSecondary" disabled={busy} onClick={() => void retryDelivery(selected, delivery)}>Retry</button>}</div></div>)}

            {selected.acknowledgements.length > 0 && <><h3>Acknowledgements</h3>{selected.acknowledgements.map((ack) => <div className="deliveryRow" key={ack.id}><div><b>Receipt acknowledged</b><small>{ack.actor_sub} · {dateTime(ack.acknowledged_at)}</small></div><Badge value="delivered" /></div>)}</>}
          </article>}
        </div>
      </article>

      {receipt && <article className="portalPanel">
        <div className="panelHeading"><div><p className="eyebrow">Proof of communication</p><h2>{receipt.receipt_id}</h2></div><button className="portalSecondary" onClick={() => window.print()}>Print receipt</button></div>
        <div className="twoColumn"><dl className="detailList"><dt>Business</dt><dd>{receipt.business.legal_name}</dd><dt>Registration</dt><dd>{receipt.business.registration_number}</dd><dt>TIN</dt><dd>{receipt.business.tin}</dd><dt>BDA address</dt><dd>{receipt.business.official_address ?? "—"}</dd></dl><dl className="detailList"><dt>Agency</dt><dd>{receipt.agency_name}</dd><dt>Reference</dt><dd>{receipt.external_message_id}</dd><dt>Received</dt><dd>{dateTime(receipt.received_at)}</dd><dt>Generated</dt><dd>{dateTime(receipt.generated_at)}</dd></dl></div>
      </article>}

      {snapshot && <article className="portalPanel">
        <div className="panelHeading"><div><h2>Authorised users</h2><p className="portalMuted">Owners can assign operational roles. Ithute Auth continues to own passwords and MFA.</p></div></div>
        {snapshot.members.map((member) => <div className="emailRow" key={member.id}><div><b>{member.invited_email || member.invited_phone || "Ithute identity"}</b><small><Badge value={member.status} /></small></div><select value={member.role} disabled={busy} onChange={(event) => void changeRole(member.id, event.target.value)}><option value="owner">Owner</option><option value="admin">Admin</option><option value="viewer">Viewer</option><option value="member">Member</option></select></div>)}
      </article>}

      {admin && <article className="portalPanel">
        <div className="panelHeading"><div><p className="eyebrow">Platform administrator</p><h2>Operations dashboard</h2></div></div>
        <div className="metricGrid">
          <article><strong>{admin.businesses}</strong><small>Businesses</small></article>
          <article><strong>{admin.active_official_addresses}</strong><small>Active addresses</small></article>
          <article><strong>{admin.pending_mailboxes}</strong><small>Pending mailboxes</small></article>
          <article><strong>{admin.messages_last_24h}</strong><small>Messages / 24h</small></article>
          <article><strong>{admin.verified_forwarding_addresses}</strong><small>Verified forwards</small></article>
          <article><strong>{admin.forwarding_failures}</strong><small>Forward failures</small></article>
          <article><strong>{admin.acknowledgements}</strong><small>Acknowledgements</small></article>
          <article><strong>{admin.attachments}</strong><small>Attachments</small></article>
        </div>
      </article>}
    </main>
  );
}
