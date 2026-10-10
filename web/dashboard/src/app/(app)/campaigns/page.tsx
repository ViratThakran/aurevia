"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
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
import { api, type Schemas } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type Campaign = Schemas["CampaignResponse"];

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function NewCampaign() {
  const router = useRouter();
  const [form, setForm] = useState({ name: "", purpose: "promotional", starts_on: today(), ends_on: "" });
  const { pending, error, run } = useAction();
  return (
    <form
      className="grid gap-3 sm:grid-cols-5 sm:items-end"
      onSubmit={async (e) => {
        e.preventDefault();
        const campaign = await run(() =>
          api<Campaign>("/campaigns", {
            method: "POST",
            body: { ...form, ends_on: form.ends_on || null },
          }),
        );
        if (campaign) router.push(`/campaigns/${campaign.id}`);
      }}
    >
      <Field label="Name">
        <Input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
      </Field>
      <Field label="Purpose">
        <Select value={form.purpose} onChange={(e) => setForm({ ...form, purpose: e.target.value })}>
          <option value="promotional">Promotional (sales)</option>
          <option value="service">Service</option>
        </Select>
      </Field>
      <Field label="Starts">
        <Input type="date" required value={form.starts_on} onChange={(e) => setForm({ ...form, starts_on: e.target.value })} />
      </Field>
      <Field label="Ends (optional)">
        <Input type="date" value={form.ends_on} onChange={(e) => setForm({ ...form, ends_on: e.target.value })} />
      </Field>
      <Button type="submit" pending={pending}>Create</Button>
      <div className="sm:col-span-5"><Alert>{error}</Alert></div>
    </form>
  );
}

export default function CampaignsPage() {
  const { can } = useSession();
  const campaigns = useApi<Campaign[]>("/campaigns");
  const [adding, setAdding] = useState(false);
  return (
    <>
      <PageHeader
        title="Campaigns"
        description="Groups of leads to call, with their own dates, hours and limits."
        actions={can("campaigns.manage") ? <Button onClick={() => setAdding(!adding)}>New campaign</Button> : null}
      />
      {adding ? <Card className="mb-6" title="New campaign"><NewCampaign /></Card> : null}
      <Card>
        {campaigns.data ? (
          <Table
            head={["Name", "Purpose", "Status", "Dates", "Auto-dial", "Created"]}
            rows={campaigns.data.map((c) => [
              <Link key="n" className="font-medium text-accent" href={`/campaigns/${c.id}`}>{c.name}</Link>,
              c.purpose,
              <StatusBadge key="s" value={c.status} />,
              `${formatDate(c.starts_on, false)} – ${c.ends_on ? formatDate(c.ends_on, false) : "open"}`,
              c.auto_dial ? "on" : "off",
              formatDate(c.created_at, false),
            ])}
            empty="No campaigns yet."
          />
        ) : campaigns.error ? <Alert>{campaigns.error}</Alert> : <Loading />}
      </Card>
    </>
  );
}
