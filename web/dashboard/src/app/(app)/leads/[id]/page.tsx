"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";

import {
  Alert,
  Button,
  Card,
  Field,
  Input,
  Loading,
  PageHeader,
  Select,
  StatusBadge,
  Table,
  formatDate,
} from "@/components/ui";
import { api, type Schemas } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type Lead = Schemas["LeadResponse"];

function Details({ lead, onSaved, editable }: { lead: Lead; onSaved: () => void; editable: boolean }) {
  const [form, setForm] = useState({
    name: lead.name,
    phone: lead.phone ?? "",
    email: lead.email ?? "",
    company: lead.company ?? "",
  });
  const { pending, error, run } = useAction();
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [key]: e.target.value });
  return (
    <form
      className="space-y-3"
      onSubmit={async (e) => {
        e.preventDefault();
        const ok = await run(() =>
          api<Lead>(`/leads/${lead.id}`, {
            method: "PUT",
            body: {
              name: form.name,
              phone: form.phone || null,
              email: form.email || null,
              company: form.company || null,
            },
          }),
        );
        if (ok) onSaved();
      }}
    >
      <fieldset disabled={!editable} className="grid gap-3 sm:grid-cols-2">
        <Field label="Name"><Input required value={form.name} onChange={set("name")} /></Field>
        <Field label="Company"><Input value={form.company} onChange={set("company")} /></Field>
        <Field label="Phone"><Input value={form.phone} onChange={set("phone")} /></Field>
        <Field label="Email"><Input type="email" value={form.email} onChange={set("email")} /></Field>
      </fieldset>
      <Alert>{error}</Alert>
      {editable ? <Button type="submit" pending={pending}>Save</Button> : null}
    </form>
  );
}

function Consents({ leadId, editable }: { leadId: string; editable: boolean }) {
  const consents = useApi<Schemas["ConsentResponse"][]>(`/leads/${leadId}/consents`);
  const [form, setForm] = useState({ kind: "express", purpose: "promotional", source: "", evidence: "" });
  const { pending, error, run } = useAction();
  return (
    <div className="space-y-4">
      <Table
        head={["Kind", "Purpose", "Source", "Obtained", "Status", ""]}
        rows={(consents.data ?? []).map((c) => [
          c.kind,
          c.purpose,
          c.source,
          formatDate(c.obtained_at),
          <StatusBadge key="s" value={c.revoked_at ? "revoked" : "active"} />,
          editable && !c.revoked_at ? (
            <Button
              key="r"
              variant="ghost"
              onClick={async () => {
                if (await run(() => api(`/leads/${leadId}/consents/${c.id}/revoke`, { method: "POST" })))
                  void consents.reload();
              }}
            >
              Revoke
            </Button>
          ) : null,
        ])}
        empty="No consent recorded. Live phone calls need one."
      />
      {editable ? (
        <form
          className="grid gap-3 sm:grid-cols-4 sm:items-end"
          onSubmit={async (e) => {
            e.preventDefault();
            const ok = await run(() =>
              api(`/leads/${leadId}/consents`, {
                method: "POST",
                body: { ...form, evidence: form.evidence || null },
              }),
            );
            if (ok) {
              setForm({ ...form, source: "", evidence: "" });
              void consents.reload();
            }
          }}
        >
          <Field label="Kind">
            <Select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
              <option value="express">Express (they agreed to be called)</option>
              <option value="inquiry">Inquiry (they asked us)</option>
            </Select>
          </Field>
          <Field label="Purpose">
            <Select value={form.purpose} onChange={(e) => setForm({ ...form, purpose: e.target.value })}>
              <option value="promotional">Promotional (sales)</option>
              <option value="service">Service</option>
            </Select>
          </Field>
          <Field label="Source">
            <Input required placeholder="e.g. website form" value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} />
          </Field>
          <Button type="submit" pending={pending}>Record consent</Button>
          <div className="sm:col-span-4">
            <Field label="Evidence (optional)" hint="Where the proof is kept, e.g. form submission id.">
              <Input value={form.evidence} onChange={(e) => setForm({ ...form, evidence: e.target.value })} />
            </Field>
          </div>
        </form>
      ) : null}
      <Alert>{error ?? consents.error}</Alert>
    </div>
  );
}

function PhoneCall({ leadId }: { leadId: string }) {
  const campaigns = useApi<Schemas["CampaignResponse"][]>("/campaigns");
  const [purpose, setPurpose] = useState("promotional");
  const [campaignId, setCampaignId] = useState("");
  const [placed, setPlaced] = useState<string | null>(null);
  const { pending, error, run } = useAction();
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Purpose">
          <Select value={purpose} onChange={(e) => setPurpose(e.target.value)}>
            <option value="promotional">Promotional</option>
            <option value="service">Service</option>
          </Select>
        </Field>
        <Field label="Campaign">
          <Select value={campaignId} onChange={(e) => setCampaignId(e.target.value)}>
            <option value="">None</option>
            {(campaigns.data ?? []).filter((c) => c.status === "active").map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </Select>
        </Field>
        <Button
          pending={pending}
          onClick={async () => {
            setPlaced(null);
            const result = await run(() =>
              api<Schemas["OutboundCallResponse"]>("/calls/outbound", {
                method: "POST",
                body: { lead_id: leadId, purpose, campaign_id: campaignId || null },
              }),
            );
            if (result) setPlaced(result.call_id);
          }}
        >
          Call by phone
        </Button>
      </div>
      <p className="text-xs text-muted">
        The compliance gate checks every call first and records why it allowed or blocked it.
      </p>
      <Alert>{error}</Alert>
      {placed ? (
        <Alert tone="good">
          Dialing. <Link className="font-medium underline" href={`/calls/${placed}`}>Follow the call</Link>
        </Alert>
      ) : null}
    </div>
  );
}

function Privacy({ lead, onErased }: { lead: Lead; onErased: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const [via, setVia] = useState("");
  const { pending, error, run } = useAction();
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted">
        Everything held about this person, or erase it on their request. Erasure keeps only their
        number on your do-not-call list and the compliance records.
      </p>
      <div className="flex flex-wrap gap-2">
        <Button
          variant="secondary"
          pending={pending && !confirming}
          onClick={async () => {
            const data = await run(() => api<unknown>(`/leads/${lead.id}/export`));
            if (!data) return;
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
            const link = document.createElement("a");
            link.href = URL.createObjectURL(blob);
            link.download = `lead-${lead.id}.json`;
            link.click();
            URL.revokeObjectURL(link.href);
          }}
        >
          Export data
        </Button>
        {!lead.erased_at ? (
          <Button variant="danger" onClick={() => setConfirming(!confirming)}>
            Erase on request…
          </Button>
        ) : null}
      </div>
      {confirming ? (
        <div className="space-y-3 rounded-md border border-danger/40 p-3">
          <Field label="How did they ask?" hint="Kept with the erasure record, e.g. email to support on 9 Oct.">
            <Input value={via} onChange={(e) => setVia(e.target.value)} />
          </Field>
          <Button
            variant="danger"
            pending={pending}
            disabled={!via.trim()}
            onClick={async () => {
              const ok = await run(() =>
                api(`/leads/${lead.id}/erase`, { method: "POST", body: { received_via: via } }),
              );
              if (ok) {
                setConfirming(false);
                onErased();
              }
            }}
          >
            Erase permanently
          </Button>
        </div>
      ) : null}
      <Alert>{error}</Alert>
    </div>
  );
}

export default function LeadPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { can } = useSession();
  const lead = useApi<Lead>(`/leads/${id}`);
  const memories = useApi<Schemas["MemoryResponse"][]>(`/leads/${id}/memories`);
  const calls = useApi<Schemas["CallListItem"][]>("/voice/calls", { lead_id: id, limit: 20 });
  const { run, error } = useAction();
  const [key, setKey] = useState(0);
  useEffect(() => setKey((k) => k + 1), [lead.data?.erased_at]);

  if (!lead.data) return lead.error ? <Alert>{lead.error}</Alert> : <Loading />;
  const l = lead.data;
  const erased = Boolean(l.erased_at);
  const qualification = Object.entries(l.qualification ?? {});

  return (
    <>
      <PageHeader
        title={l.name}
        description={[l.company, l.phone].filter(Boolean).join(" · ") || undefined}
        actions={<><StatusBadge value={l.interest} /> {erased ? <StatusBadge value="erased" /> : null}</>}
      />
      {erased ? (
        <div className="mb-6"><Alert tone="neutral">This person&apos;s data was erased on {formatDate(l.erased_at)}.</Alert></div>
      ) : null}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Details">
          <Details key={key} lead={l} editable={can("leads.manage") && !erased} onSaved={() => void lead.reload()} />
        </Card>
        <Card title="What the agent learned">
          {qualification.length ? (
            <dl className="mb-4 grid grid-cols-2 gap-2 text-sm">
              {qualification.map(([k, v]) => (
                <div key={k}><dt className="text-muted">{k.replaceAll("_", " ")}</dt><dd>{String(v)}</dd></div>
              ))}
            </dl>
          ) : null}
          {l.interest_reason ? <p className="mb-3 text-sm">Interest: {l.interest_reason}</p> : null}
          <Table
            head={["Kind", "Fact", "Confidence", ""]}
            rows={(memories.data ?? []).map((m) => [
              m.kind,
              m.fact,
              `${Math.round(m.confidence * 100)}%`,
              can("leads.manage") ? (
                <Button key="d" variant="ghost" onClick={async () => {
                  if (await run(() => api(`/leads/${id}/memories/${m.id}`, { method: "DELETE" }).then(() => true)))
                    void memories.reload();
                }}>Delete</Button>
              ) : null,
            ])}
            empty="Nothing remembered yet. Facts are extracted after each call."
          />
          <Alert>{error}</Alert>
        </Card>
        {can("calls.place") && !erased ? (
          <Card title="Phone call"><PhoneCall leadId={id} /></Card>
        ) : null}
        <Card title="Consent"><Consents leadId={id} editable={can("leads.manage") && !erased} /></Card>
        <Card title="Calls" className="lg:col-span-2">
          <Table
            head={["When", "Channel", "Status", "Outcome", "Turns"]}
            rows={(calls.data ?? []).map((c) => [
              <Link key="w" className="text-accent" href={`/calls/${c.id}`}>{formatDate(c.created_at)}</Link>,
              c.direction ? `${c.channel} (${c.direction})` : c.channel,
              <StatusBadge key="s" value={c.status} />,
              c.end_reason ?? c.dial_status ?? "—",
              c.turn_count,
            ])}
            empty="No calls with this lead yet."
          />
        </Card>
        {can("leads.privacy") ? (
          <Card title="Personal data (DPDP)" className="lg:col-span-2">
            <Privacy lead={l} onErased={() => { void lead.reload(); void memories.reload(); }} />
          </Card>
        ) : null}
      </div>
    </>
  );
}
