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
  Stat,
  StatusBadge,
  Table,
  formatDate,
} from "@/components/ui";
import { api, type Schemas } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import { type AnalyticsSummary, money, percent } from "@/lib/types";

type Campaign = Schemas["CampaignResponse"];

const TRANSITIONS: Record<string, { to: string; label: string; variant?: "danger" | "secondary" }[]> = {
  draft: [{ to: "active", label: "Start" }, { to: "ended", label: "End", variant: "danger" }],
  active: [{ to: "paused", label: "Pause", variant: "secondary" }, { to: "ended", label: "End", variant: "danger" }],
  paused: [{ to: "active", label: "Resume" }, { to: "ended", label: "End", variant: "danger" }],
  ended: [],
};

function Settings({ campaign, onSaved, editable }: { campaign: Campaign; onSaved: (c: Campaign) => void; editable: boolean }) {
  const initial = () => ({
    name: campaign.name,
    starts_on: campaign.starts_on,
    ends_on: campaign.ends_on ?? "",
    window_start: campaign.window_start?.slice(0, 5) ?? "",
    window_end: campaign.window_end?.slice(0, 5) ?? "",
    max_attempts_per_lead: String(campaign.max_attempts_per_lead),
    daily_call_cap: campaign.daily_call_cap ? String(campaign.daily_call_cap) : "",
    retry_delay_minutes: String(campaign.retry_delay_minutes),
    max_concurrent_calls: String(campaign.max_concurrent_calls),
  });
  const [form, setForm] = useState(initial);
  useEffect(() => setForm(initial()), [campaign]); // eslint-disable-line react-hooks/exhaustive-deps
  const { pending, error, run } = useAction();
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [key]: e.target.value });
  const time = (v: string) => (v ? `${v}:00` : null);
  return (
    <form
      className="space-y-4"
      onSubmit={async (e) => {
        e.preventDefault();
        const saved = await run(() =>
          api<Campaign>(`/campaigns/${campaign.id}`, {
            method: "PATCH",
            body: {
              name: form.name,
              starts_on: form.starts_on,
              ends_on: form.ends_on || null,
              window_start: time(form.window_start),
              window_end: time(form.window_end),
              max_attempts_per_lead: Number(form.max_attempts_per_lead),
              daily_call_cap: form.daily_call_cap ? Number(form.daily_call_cap) : null,
              retry_delay_minutes: Number(form.retry_delay_minutes),
              max_concurrent_calls: Number(form.max_concurrent_calls),
            },
          }),
        );
        if (saved) onSaved(saved);
      }}
    >
      <fieldset disabled={!editable || campaign.status === "ended"} className="grid gap-3 sm:grid-cols-3">
        <Field label="Name"><Input required value={form.name} onChange={set("name")} /></Field>
        <Field label="Starts"><Input type="date" required value={form.starts_on} onChange={set("starts_on")} /></Field>
        <Field label="Ends"><Input type="date" value={form.ends_on} onChange={set("ends_on")} /></Field>
        <Field label="Calling from" hint="Narrows the policy's hours; leave empty to use them.">
          <Input type="time" value={form.window_start} onChange={set("window_start")} />
        </Field>
        <Field label="Calling until"><Input type="time" value={form.window_end} onChange={set("window_end")} /></Field>
        <Field label="Attempts per lead"><Input type="number" min={1} max={10} value={form.max_attempts_per_lead} onChange={set("max_attempts_per_lead")} /></Field>
        <Field label="Daily call cap"><Input type="number" min={1} value={form.daily_call_cap} onChange={set("daily_call_cap")} placeholder="none" /></Field>
        <Field label="Retry after (minutes)"><Input type="number" min={5} max={10080} value={form.retry_delay_minutes} onChange={set("retry_delay_minutes")} /></Field>
        <Field label="Calls at once (auto-dial)"><Input type="number" min={1} max={5} value={form.max_concurrent_calls} onChange={set("max_concurrent_calls")} /></Field>
      </fieldset>
      <Alert>{error}</Alert>
      {editable && campaign.status !== "ended" ? <Button type="submit" pending={pending}>Save settings</Button> : null}
    </form>
  );
}

function AddLeads({ campaignId, onAdded }: { campaignId: string; onAdded: () => void }) {
  const leads = useApi<Schemas["LeadResponse"][]>("/leads", { limit: 500 });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const { pending, error, run } = useAction();
  const [added, setAdded] = useState<number | null>(null);
  if (!leads.data) return <Loading />;
  return (
    <div className="space-y-3">
      <div className="max-h-64 overflow-y-auto rounded-md border border-border">
        {leads.data.map((l) => (
          <label key={l.id} className="flex items-center gap-3 border-b border-border px-3 py-2 text-sm last:border-0">
            <input
              type="checkbox"
              checked={selected.has(l.id)}
              onChange={(e) => {
                const next = new Set(selected);
                if (e.target.checked) next.add(l.id);
                else next.delete(l.id);
                setSelected(next);
              }}
            />
            <span className="font-medium">{l.name}</span>
            <span className="text-muted">{l.phone ?? "no phone"}</span>
          </label>
        ))}
      </div>
      <div className="flex items-center gap-3">
        <Button
          pending={pending}
          disabled={selected.size === 0}
          onClick={async () => {
            const result = await run(() =>
              api<Schemas["CampaignLeadsAdded"]>(`/campaigns/${campaignId}/leads`, {
                method: "POST",
                body: { lead_ids: [...selected] },
              }),
            );
            if (result) {
              setAdded(result.added);
              setSelected(new Set());
              onAdded();
            }
          }}
        >
          Add {selected.size || ""} to queue
        </Button>
        {added !== null ? <span className="text-sm text-muted">{added} added (leads already queued are skipped).</span> : null}
      </div>
      <Alert>{error}</Alert>
    </div>
  );
}

export default function CampaignPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { can } = useSession();
  const campaign = useApi<Campaign>(`/campaigns/${id}`);
  const [statusFilter, setStatusFilter] = useState("");
  const queue = useApi<Schemas["CampaignLeadResponse"][]>(`/campaigns/${id}/leads`, { status: statusFilter || null });
  const stats = useApi<AnalyticsSummary>(can("analytics.read") ? "/analytics/summary" : null, { days: 90, campaign_id: id });
  const [adding, setAdding] = useState(false);
  const [lastResult, setLastResult] = useState<Schemas["CallNextResponse"] | null>(null);
  const action = useAction();

  if (!campaign.data) return campaign.error ? <Alert>{campaign.error}</Alert> : <Loading />;
  const c = campaign.data;
  const manage = can("campaigns.manage");

  return (
    <>
      <PageHeader
        title={c.name}
        description={`${c.purpose} · ${formatDate(c.starts_on, false)} – ${c.ends_on ? formatDate(c.ends_on, false) : "open"}`}
        actions={
          <>
            <StatusBadge value={c.status} />
            {manage
              ? TRANSITIONS[c.status]?.map((t) => (
                  <Button
                    key={t.to}
                    variant={t.variant ?? "primary"}
                    pending={action.pending}
                    onClick={async () => {
                      if (t.to === "ended" && !window.confirm("End this campaign? It cannot be restarted.")) return;
                      const saved = await action.run(() =>
                        api<Campaign>(`/campaigns/${id}/status`, { method: "POST", body: { status: t.to } }),
                      );
                      if (saved) campaign.setData(saved);
                    }}
                  >
                    {t.label}
                  </Button>
                ))
              : null}
          </>
        }
      />
      <Alert>{action.error}</Alert>

      {stats.data ? (
        <div className="my-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Calls" value={stats.data.activity.calls} hint={`${percent(stats.data.activity.phone_answer_rate)} answered`} />
          <Stat label="Meetings" value={stats.data.sales.meetings_booked} />
          <Stat label="Interested" value={stats.data.sales.interested} hint={`${stats.data.sales.not_interested} not interested`} />
          <Stat label="Cost" value={money(stats.data.economics.cost)} hint={`per meeting ${money(stats.data.economics.cost_per_meeting)}`} />
        </div>
      ) : null}

      <div className="mt-6 grid gap-6">
        <Card
          title="Calling queue"
          actions={
            <>
              <Select className="w-36" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                <option value="">All</option>
                {["queued", "calling", "done", "failed", "skipped"].map((s) => <option key={s} value={s}>{s}</option>)}
              </Select>
              {manage && c.status !== "ended" ? (
                <Button variant="secondary" onClick={() => setAdding(!adding)}>Add leads</Button>
              ) : null}
              {can("calls.place") && c.status === "active" ? (
                <Button
                  pending={action.pending}
                  onClick={async () => {
                    const result = await action.run(() =>
                      api<Schemas["CallNextResponse"]>(`/campaigns/${id}/call-next`, { method: "POST" }),
                    );
                    if (result) {
                      setLastResult(result);
                      void queue.reload();
                    }
                  }}
                >
                  Call next
                </Button>
              ) : null}
            </>
          }
        >
          {adding ? <div className="mb-4"><AddLeads campaignId={id} onAdded={() => void queue.reload()} /></div> : null}
          {lastResult ? (
            <div className="mb-4">
              <Alert tone={lastResult.status === "placed" ? "good" : lastResult.status === "empty" ? "neutral" : "warn"}>
                {lastResult.status === "placed" && (
                  <>Dialing. <Link className="underline" href={`/calls/${lastResult.call_id}`}>Follow the call</Link></>
                )}
                {lastResult.status === "empty" && "Nobody is due for a call right now."}
                {lastResult.status === "blocked" && `The gate refused: ${lastResult.reasons.join(", ").replaceAll("_", " ")}.`}
              </Alert>
            </div>
          ) : null}
          {queue.data ? (
            <Table
              head={["Lead", "Status", "Attempts", "Next attempt", "Last result"]}
              rows={queue.data.map((e) => [
                <Link key="l" className="text-accent" href={`/leads/${e.lead_id}`}>{e.lead_name}</Link>,
                <StatusBadge key="s" value={e.status} />,
                e.attempts,
                e.status === "queued" ? formatDate(e.next_attempt_at) : "—",
                e.last_call_id ? (
                  <Link key="r" className="text-accent" href={`/calls/${e.last_call_id}`}>{(e.last_result ?? "").replaceAll("_", " ")}</Link>
                ) : (
                  (e.last_result ?? "—").replaceAll("_", " ")
                ),
              ])}
              empty="No leads in this campaign yet."
            />
          ) : <Loading />}
        </Card>

        <Card title="Automatic dialing">
          <p className="mb-3 text-sm text-muted">
            When on, Aurevia calls due leads on its own during calling hours, up to {c.max_concurrent_calls} at a time.
            Every call still passes the compliance gate and your plan limits, and it also needs the
            dialer to be enabled on the server.
          </p>
          <div className="flex items-center gap-3">
            <StatusBadge value={c.auto_dial ? "active" : "paused"} />
            {manage && c.status !== "ended" ? (
              <Button
                variant={c.auto_dial ? "secondary" : "primary"}
                pending={action.pending}
                onClick={async () => {
                  const saved = await action.run(() =>
                    api<Campaign>(`/campaigns/${id}`, { method: "PATCH", body: { auto_dial: !c.auto_dial } }),
                  );
                  if (saved) campaign.setData(saved);
                }}
              >
                {c.auto_dial ? "Turn off" : "Turn on"}
              </Button>
            ) : null}
          </div>
        </Card>

        <Card title="Settings">
          <Settings campaign={c} editable={manage} onSaved={(saved) => campaign.setData(saved)} />
        </Card>
      </div>
    </>
  );
}
