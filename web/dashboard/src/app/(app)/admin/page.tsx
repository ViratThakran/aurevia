"use client";

import { useState } from "react";

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
import { api } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { PlatformPlan, PlatformPrice, PlatformTenant } from "@/lib/types";

function PlanEditor({ tenant, onDone }: { tenant: PlatformTenant; onDone: () => void }) {
  const plan = useApi<PlatformPlan>(`/platform/tenants/${tenant.id}/plan`);
  const [form, setForm] = useState<Record<string, string> | null>(null);
  const { run, error, pending } = useAction();
  if (!plan.data) return <Loading />;
  const p = plan.data;
  const f = form ?? {
    plan_name: p.default ? "standard" : p.plan_name,
    monthly_call_limit: p.monthly_call_limit ? String(p.monthly_call_limit) : "",
    monthly_minute_limit: p.monthly_minute_limit ? String(p.monthly_minute_limit) : "",
    monthly_cost_limit: p.monthly_cost_limit ?? "",
    cost_currency: p.cost_currency ?? "",
    max_concurrent_calls: String(p.max_concurrent_calls),
  };
  const set = (key: string) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...f, [key]: e.target.value });
  const num = (v: string) => (v ? Number(v) : null);
  return (
    <form
      className="grid gap-3 rounded-md border border-border p-4 sm:grid-cols-3"
      onSubmit={async (e) => {
        e.preventDefault();
        const ok = await run(() =>
          api(`/platform/tenants/${tenant.id}/plan`, {
            method: "PUT",
            body: {
              plan_name: f.plan_name,
              monthly_call_limit: num(f.monthly_call_limit),
              monthly_minute_limit: num(f.monthly_minute_limit),
              monthly_cost_limit: f.monthly_cost_limit || null,
              cost_currency: f.cost_currency || null,
              max_concurrent_calls: Number(f.max_concurrent_calls),
            },
          }),
        );
        if (ok) onDone();
      }}
    >
      <div className="text-sm font-semibold sm:col-span-3">
        Plan for {tenant.name} {p.default ? <span className="font-normal text-muted">(currently the default plan)</span> : null}
      </div>
      <Field label="Plan name"><Input required value={f.plan_name} onChange={set("plan_name")} /></Field>
      <Field label="Calls / month"><Input type="number" min={1} value={f.monthly_call_limit} onChange={set("monthly_call_limit")} placeholder="unlimited" /></Field>
      <Field label="Minutes / month"><Input type="number" min={1} value={f.monthly_minute_limit} onChange={set("monthly_minute_limit")} placeholder="unlimited" /></Field>
      <Field label="Spend / month"><Input value={f.monthly_cost_limit} onChange={set("monthly_cost_limit")} placeholder="unlimited" /></Field>
      <Field label="Currency"><Input value={f.cost_currency} onChange={set("cost_currency")} placeholder="INR" maxLength={3} /></Field>
      <Field label="Calls at once"><Input type="number" min={1} max={100} required value={f.max_concurrent_calls} onChange={set("max_concurrent_calls")} /></Field>
      <div className="flex gap-2 sm:col-span-3">
        <Button type="submit" pending={pending}>Save plan</Button>
        <Button variant="ghost" onClick={onDone}>Close</Button>
      </div>
      <div className="sm:col-span-3"><Alert>{error}</Alert></div>
    </form>
  );
}

function Prices() {
  const prices = useApi<PlatformPrice[]>("/platform/prices");
  const [form, setForm] = useState({ provider: "", resource: "llm_input_tokens", model: "*", currency: "INR", amount: "", per_quantity: "1000000" });
  const { run, error, pending } = useAction();
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [key]: e.target.value });
  return (
    <Card title="Provider prices">
      <p className="mb-3 text-sm text-muted">
        Prices are never edited: adding a price for the same provider and resource starts a new version from now. Past usage keeps the price it had.
      </p>
      <form
        className="mb-4 grid gap-3 sm:grid-cols-7 sm:items-end"
        onSubmit={async (e) => {
          e.preventDefault();
          if (await run(() => api("/platform/prices", { method: "POST", body: { ...form, per_quantity: Number(form.per_quantity) } }))) {
            setForm({ ...form, amount: "" });
            void prices.reload();
          }
        }}
      >
        <Field label="Provider"><Input required value={form.provider} onChange={set("provider")} placeholder="gemini" /></Field>
        <Field label="Resource">
          <Select value={form.resource} onChange={set("resource")}>
            {["llm_input_tokens", "llm_output_tokens", "stt_seconds", "tts_characters", "telephony_seconds"].map((r) => <option key={r}>{r}</option>)}
          </Select>
        </Field>
        <Field label="Model"><Input value={form.model} onChange={set("model")} /></Field>
        <Field label="Currency"><Input required maxLength={3} value={form.currency} onChange={set("currency")} /></Field>
        <Field label="Amount"><Input required value={form.amount} onChange={set("amount")} /></Field>
        <Field label="Per units"><Input type="number" min={1} required value={form.per_quantity} onChange={set("per_quantity")} /></Field>
        <Button type="submit" pending={pending}>Add price</Button>
      </form>
      <Alert>{error}</Alert>
      <Table
        head={["Provider", "Resource", "Model", "Price", "From"]}
        rows={(prices.data ?? []).map((p) => [
          p.provider, p.resource, p.model, `${p.currency} ${p.amount} / ${p.per_quantity.toLocaleString()}`, formatDate(p.effective_from),
        ])}
        empty="No prices yet: costs show as not priced."
      />
    </Card>
  );
}

export default function AdminPage() {
  const { me } = useSession();
  const tenants = useApi<PlatformTenant[]>(me?.is_platform_admin ? "/platform/tenants" : null);
  const [planFor, setPlanFor] = useState<PlatformTenant | null>(null);
  const { run, error, pending } = useAction();

  if (!me?.is_platform_admin) return <Alert>Aurevia platform administrators only.</Alert>;
  return (
    <>
      <PageHeader title="Platform admin" description="All customers. Your changes appear in each customer's own audit log." />
      <div className="grid gap-6">
        <Card title="Tenants">
          <Alert>{error}</Alert>
          {tenants.data ? (
            <Table
              head={["Name", "Status", "Members", "Calls this month", "Last call", "Since", ""]}
              rows={tenants.data.map((t) => [
                t.name,
                <StatusBadge key="s" value={t.status} />,
                t.members,
                t.calls_this_month,
                formatDate(t.last_call_at),
                formatDate(t.created_at, false),
                <div key="a" className="flex gap-1">
                  <Button variant="ghost" onClick={() => setPlanFor(t)}>Plan</Button>
                  <Button
                    variant="ghost"
                    pending={pending}
                    onClick={async () => {
                      const action = t.status === "active" ? "suspend" : "resume";
                      if (action === "suspend" && !window.confirm(`Suspend ${t.name}? Everyone there is signed out and calls stop.`)) return;
                      if (await run(() => api(`/platform/tenants/${t.id}/${action}`, { method: "POST" }))) void tenants.reload();
                    }}
                  >
                    {t.status === "active" ? "Suspend" : "Resume"}
                  </Button>
                </div>,
              ])}
            />
          ) : <Loading />}
          {planFor ? <div className="mt-4"><PlanEditor key={planFor.id} tenant={planFor} onDone={() => setPlanFor(null)} /></div> : null}
        </Card>
        <Prices />
      </div>
    </>
  );
}
