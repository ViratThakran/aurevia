"use client";

import { useEffect, useState } from "react";

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
  cx,
  formatDate,
} from "@/components/ui";
import { api, type Schemas } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";
import { useSession } from "@/lib/session";

const TABS = ["Policy", "Decisions", "Do-not-call", "Numbers"] as const;
type Tab = (typeof TABS)[number];

function Policy() {
  const { can } = useSession();
  const settings = useApi<Schemas["ComplianceSettingsResponse"]>("/compliance/settings");
  const versions = useApi<Schemas["PolicyVersionResponse"][]>("/compliance/policy-versions");
  const [form, setForm] = useState({ version: "", window_start: "", window_end: "", per_day: "", per_week: "", no_dnd_override: false });
  const { pending, error, run } = useAction();

  useEffect(() => {
    const o = (settings.data?.overrides ?? {}) as Record<string, unknown>;
    setForm({
      version: settings.data?.policy_version_id ?? "",
      window_start: String(o.window_start ?? "").slice(0, 5),
      window_end: String(o.window_end ?? "").slice(0, 5),
      per_day: o.max_calls_per_number_per_day ? String(o.max_calls_per_number_per_day) : "",
      per_week: o.max_calls_per_number_per_week ? String(o.max_calls_per_number_per_week) : "",
      no_dnd_override: o.express_consent_overrides_dnd === false,
    });
  }, [settings.data]);

  if (!settings.data) return settings.error ? <Alert>{settings.error}</Alert> : <Loading />;
  const effective = settings.data.effective_policy as Record<string, unknown>;
  const editable = can("compliance.manage");

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="Rules in force">
        <div className="mb-3 flex items-center gap-2 text-sm">
          <span className="font-medium">{String(effective.version)}</span>
          <StatusBadge value={String(effective.status)} />
        </div>
        {effective.status !== "reviewed" ? (
          <Alert tone="warn">
            This policy version has not been reviewed by counsel, so calls to real prospects are
            blocked. Test calls to your own registered numbers work.
          </Alert>
        ) : null}
        <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
          <dt className="text-muted">Calling hours</dt>
          <dd>{String(effective.window_start).slice(0, 5)}–{String(effective.window_end).slice(0, 5)} ({String(effective.timezone)})</dd>
          <dt className="text-muted">Calls per number</dt>
          <dd>{String(effective.max_calls_per_number_per_day)}/day, {String(effective.max_calls_per_number_per_week)}/week</dd>
          <dt className="text-muted">Enquiry consent valid</dt>
          <dd>{String(effective.inquiry_consent_valid_days)} days</dd>
          <dt className="text-muted">Consent overrides DND</dt>
          <dd>{effective.express_consent_overrides_dnd ? "express consent only" : "never"}</dd>
          <dt className="text-muted">Unknown DND status</dt>
          <dd>{effective.block_when_dnd_unknown ? "blocks the call" : "allowed"}</dd>
          <dt className="text-muted">Live calls need a campaign</dt>
          <dd>{effective.require_campaign_for_live ? "yes" : "no"}</dd>
        </dl>
      </Card>
      <Card title="Your stricter settings">
        <form
          className="space-y-3"
          onSubmit={async (e) => {
            e.preventDefault();
            const time = (v: string) => (v ? `${v}:00` : null);
            const num = (v: string) => (v ? Number(v) : null);
            const saved = await run(() =>
              api<Schemas["ComplianceSettingsResponse"]>("/compliance/settings", {
                method: "PUT",
                body: {
                  policy_version_id: form.version || null,
                  overrides: {
                    window_start: time(form.window_start),
                    window_end: time(form.window_end),
                    max_calls_per_number_per_day: num(form.per_day),
                    max_calls_per_number_per_week: num(form.per_week),
                    express_consent_overrides_dnd: form.no_dnd_override ? false : null,
                  },
                },
              }),
            );
            if (saved) settings.setData(saved);
          }}
        >
          <fieldset disabled={!editable} className="space-y-3">
            <Field label="Policy version" hint="Default: the newest reviewed version, else the newest draft.">
              <Select value={form.version} onChange={(e) => setForm({ ...form, version: e.target.value })}>
                <option value="">Default</option>
                {(versions.data ?? []).filter((v) => v.status !== "retired").map((v) => (
                  <option key={v.id} value={v.id}>{v.version} ({v.status})</option>
                ))}
              </Select>
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Call from (not earlier than policy)"><Input type="time" value={form.window_start} onChange={(e) => setForm({ ...form, window_start: e.target.value })} /></Field>
              <Field label="Call until"><Input type="time" value={form.window_end} onChange={(e) => setForm({ ...form, window_end: e.target.value })} /></Field>
              <Field label="Max calls/number/day"><Input type="number" min={0} value={form.per_day} onChange={(e) => setForm({ ...form, per_day: e.target.value })} /></Field>
              <Field label="Max calls/number/week"><Input type="number" min={0} value={form.per_week} onChange={(e) => setForm({ ...form, per_week: e.target.value })} /></Field>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.no_dnd_override} onChange={(e) => setForm({ ...form, no_dnd_override: e.target.checked })} />
              Never call DND-registered numbers, even with consent
            </label>
          </fieldset>
          <p className="text-xs text-muted">Settings can only make the rules stricter. Looser values are refused.</p>
          <Alert>{error}</Alert>
          {editable ? <Button type="submit" pending={pending}>Save</Button> : null}
        </form>
      </Card>
    </div>
  );
}

function Decisions() {
  const decisions = useApi<Schemas["DecisionResponse"][]>("/compliance/decisions", { limit: 200 });
  const [open, setOpen] = useState<string | null>(null);
  if (!decisions.data) return decisions.error ? <Alert>{decisions.error}</Alert> : <Loading />;
  return (
    <Card title="Every call request, allowed or blocked">
      <Table
        head={["When", "Number", "Decision", "Reason", "Mode", "Policy", ""]}
        rows={decisions.data.flatMap((d) => {
          const row = [
            formatDate(d.created_at),
            d.to_number ?? "—",
            <StatusBadge key="d" value={d.decision} />,
            d.reason_code.replaceAll("_", " "),
            d.mode,
            d.policy_version,
            <Button key="o" variant="ghost" onClick={() => setOpen(open === d.id ? null : d.id)}>{open === d.id ? "Hide" : "Checks"}</Button>,
          ];
          if (open !== d.id) return [row];
          const checks = (d.checks as { name: string; passed: boolean; reason: string }[]).map((c) => (
            <span key={c.name} className={cx("mr-3 inline-block", c.passed ? "text-success" : "text-danger")}>
              {c.passed ? "✓" : "✗"} {c.name}: {c.reason.replaceAll("_", " ")}
            </span>
          ));
          return [row, [<div key="c" className="text-xs">{checks}</div>, "", "", "", "", "", ""]];
        })}
        empty="No call requests yet."
      />
    </Card>
  );
}

function DoNotCall() {
  const entries = useApi<Schemas["DoNotCallResponse"][]>("/do-not-call");
  const [phone, setPhone] = useState("");
  const [note, setNote] = useState("");
  const { pending, error, run } = useAction();
  return (
    <Card title="Numbers never to call">
      <form
        className="mb-4 flex flex-wrap items-end gap-3"
        onSubmit={async (e) => {
          e.preventDefault();
          if (await run(() => api("/do-not-call", { method: "POST", body: { phone, reason: "manual", note: note || null } }))) {
            setPhone("");
            setNote("");
            void entries.reload();
          }
        }}
      >
        <Field label="Phone"><Input required value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+91…" /></Field>
        <Field label="Note"><Input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
        <Button type="submit" pending={pending}>Add</Button>
      </form>
      <Alert>{error}</Alert>
      <Table
        head={["Phone", "Why", "Note", "Added"]}
        rows={(entries.data ?? []).map((d) => [d.phone, d.reason.replaceAll("_", " "), d.note ?? "—", formatDate(d.created_at)])}
        empty="The list is empty."
      />
    </Card>
  );
}

function Numbers() {
  const { can } = useSession();
  const numbers = useApi<Schemas["PhoneNumberResponse"][]>("/telephony/numbers");
  const tests = useApi<Schemas["TestNumberResponse"][]>("/telephony/test-numbers");
  const [number, setNumber] = useState({ e164: "", purpose: "promotional", dlt_registered: false, inbound_enabled: false });
  const [test, setTest] = useState({ e164: "", label: "" });
  const { pending, error, run } = useAction();
  const editable = can("numbers.manage");
  return (
    <div className="grid gap-6">
      <Alert>{error}</Alert>
      <Card title="Your phone numbers (caller ids)">
        <Table
          head={["Number", "Carrier", "Purpose", "DLT", "Inbound", "Active", ""]}
          rows={(numbers.data ?? []).map((n) => [
            n.e164, n.carrier, n.purpose, n.dlt_registered ? "yes" : "no", n.inbound_enabled ? "on" : "off",
            <StatusBadge key="a" value={n.active ? "active" : "paused"} />,
            editable ? (
              <Button key="t" variant="ghost" onClick={async () => {
                if (await run(() => api(`/telephony/numbers/${n.id}`, { method: "PATCH", body: { active: !n.active } }))) void numbers.reload();
              }}>{n.active ? "Deactivate" : "Activate"}</Button>
            ) : null,
          ])}
          empty="No numbers yet. Add the number your carrier (Exotel) gave you."
        />
        {editable ? (
          <form className="mt-4 flex flex-wrap items-end gap-3" onSubmit={async (e) => {
            e.preventDefault();
            if (await run(() => api("/telephony/numbers", { method: "POST", body: number }))) {
              setNumber({ ...number, e164: "" });
              void numbers.reload();
            }
          }}>
            <Field label="Number"><Input required value={number.e164} onChange={(e) => setNumber({ ...number, e164: e.target.value })} placeholder="+91140…" /></Field>
            <Field label="Purpose">
              <Select value={number.purpose} onChange={(e) => setNumber({ ...number, purpose: e.target.value })}>
                <option value="promotional">Promotional (140)</option>
                <option value="service">Service (160)</option>
              </Select>
            </Field>
            <label className="flex items-center gap-2 pb-2 text-sm"><input type="checkbox" checked={number.dlt_registered} onChange={(e) => setNumber({ ...number, dlt_registered: e.target.checked })} /> DLT registered</label>
            <label className="flex items-center gap-2 pb-2 text-sm"><input type="checkbox" checked={number.inbound_enabled} onChange={(e) => setNumber({ ...number, inbound_enabled: e.target.checked })} /> Answer inbound calls</label>
            <Button type="submit" pending={pending}>Add number</Button>
          </form>
        ) : null}
      </Card>
      <Card title="Your own test phones">
        <p className="mb-3 text-sm text-muted">In test mode these are the only numbers Aurevia will dial (at most 5).</p>
        <Table
          head={["Number", "Label", "Added", ""]}
          rows={(tests.data ?? []).map((t) => [
            t.e164, t.label, formatDate(t.created_at),
            editable ? (
              <Button key="r" variant="ghost" onClick={async () => {
                if (await run(() => api(`/telephony/test-numbers/${t.id}`, { method: "DELETE" }).then(() => true))) void tests.reload();
              }}>Remove</Button>
            ) : null,
          ])}
          empty="No test phones."
        />
        {editable ? (
          <form className="mt-4 flex flex-wrap items-end gap-3" onSubmit={async (e) => {
            e.preventDefault();
            if (await run(() => api("/telephony/test-numbers", { method: "POST", body: test }))) {
              setTest({ e164: "", label: "" });
              void tests.reload();
            }
          }}>
            <Field label="Number"><Input required value={test.e164} onChange={(e) => setTest({ ...test, e164: e.target.value })} placeholder="+91…" /></Field>
            <Field label="Label"><Input required value={test.label} onChange={(e) => setTest({ ...test, label: e.target.value })} placeholder="My phone" /></Field>
            <Button type="submit" pending={pending}>Add test phone</Button>
          </form>
        ) : null}
      </Card>
    </div>
  );
}

export default function CompliancePage() {
  const [tab, setTab] = useState<Tab>("Policy");
  return (
    <>
      <PageHeader title="Compliance" description="Every phone call passes these checks first. The gate's decisions are kept as evidence." />
      <div className="mb-6 flex flex-wrap gap-1 border-b border-border">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={cx("-mb-px border-b-2 px-3 py-2 text-sm", tab === t ? "border-accent font-medium text-accent" : "border-transparent text-muted hover:text-foreground")}
          >
            {t}
          </button>
        ))}
      </div>
      {tab === "Policy" ? <Policy /> : null}
      {tab === "Decisions" ? <Decisions /> : null}
      {tab === "Do-not-call" ? <DoNotCall /> : null}
      {tab === "Numbers" ? <Numbers /> : null}
    </>
  );
}
