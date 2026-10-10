"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

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
  Textarea,
  formatDate,
} from "@/components/ui";
import { api, type Schemas } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type Lead = Schemas["LeadResponse"];

function AddLead({ onAdded }: { onAdded: () => void }) {
  const [form, setForm] = useState({ name: "", phone: "", email: "", company: "" });
  const { pending, error, run } = useAction();
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [key]: e.target.value });
  return (
    <form
      className="grid gap-3 sm:grid-cols-5 sm:items-end"
      onSubmit={async (e) => {
        e.preventDefault();
        const lead = await run(() =>
          api<Lead>("/leads", {
            method: "POST",
            body: {
              name: form.name,
              phone: form.phone || null,
              email: form.email || null,
              company: form.company || null,
            },
          }),
        );
        if (lead) {
          setForm({ name: "", phone: "", email: "", company: "" });
          onAdded();
        }
      }}
    >
      <Field label="Name">
        <Input required value={form.name} onChange={set("name")} />
      </Field>
      <Field label="Phone">
        <Input value={form.phone} onChange={set("phone")} placeholder="+91 98765 43210" />
      </Field>
      <Field label="Email">
        <Input type="email" value={form.email} onChange={set("email")} />
      </Field>
      <Field label="Company">
        <Input value={form.company} onChange={set("company")} />
      </Field>
      <Button type="submit" pending={pending}>
        Add lead
      </Button>
      <div className="sm:col-span-5">
        <Alert>{error}</Alert>
      </div>
    </form>
  );
}

function ImportLeads({ onImported }: { onImported: () => void }) {
  const campaigns = useApi<Schemas["CampaignResponse"][]>("/campaigns");
  const [csv, setCsv] = useState("");
  const [campaignId, setCampaignId] = useState("");
  const [result, setResult] = useState<Schemas["LeadImportResult"] | null>(null);
  const { pending, error, run } = useAction();

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted">
        Paste CSV or choose a file. Header row: <code>name,phone,email,company</code> (only
        name is required). Up to 5,000 rows.
      </p>
      <input
        type="file"
        accept=".csv,text/csv"
        className="text-sm"
        onChange={async (e) => {
          const file = e.target.files?.[0];
          if (file) setCsv(await file.text());
        }}
      />
      <Textarea rows={5} value={csv} onChange={(e) => setCsv(e.target.value)} placeholder="name,phone,email,company" />
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Also add to campaign (optional)">
          <Select value={campaignId} onChange={(e) => setCampaignId(e.target.value)}>
            <option value="">None</option>
            {(campaigns.data ?? [])
              .filter((c) => c.status !== "ended")
              .map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
          </Select>
        </Field>
        <Button
          pending={pending}
          disabled={!csv.trim()}
          onClick={async () => {
            const done = await run(() =>
              api<Schemas["LeadImportResult"]>("/leads/import", {
                method: "POST",
                body: { csv, campaign_id: campaignId || null },
              }),
            );
            if (done) {
              setResult(done);
              onImported();
            }
          }}
        >
          Import
        </Button>
      </div>
      <Alert>{error}</Alert>
      {result ? (
        <Alert tone={result.errors.length ? "warn" : "good"}>
          Created {result.created} leads
          {campaignId ? `, ${result.added_to_campaign} added to the campaign` : ""}.
          {result.errors.length ? (
            <ul className="mt-2 list-disc pl-5">
              {result.errors.slice(0, 20).map((err, i) => (
                <li key={i}>
                  Line {String(err.line)}: {String(err.field)}: {String(err.error)}
                </li>
              ))}
            </ul>
          ) : null}
        </Alert>
      ) : null}
    </div>
  );
}

export default function LeadsPageWithSearch() {
  // useSearchParams needs a Suspense boundary for static rendering.
  return (
    <Suspense>
      <LeadsPage />
    </Suspense>
  );
}

function LeadsPage() {
  const { can } = useSession();
  const [archived, setArchived] = useState(false);
  const query = useSearchParams().get("q") ?? "";
  const [search, setSearch] = useState(query);
  useEffect(() => setSearch(query), [query]); // the top bar search links here with ?q=
  const leads = useApi<Lead[]>("/leads", { include_archived: archived, limit: 500 });
  const [panel, setPanel] = useState<"add" | "import" | null>(null);

  const shown = (leads.data ?? []).filter((l) =>
    `${l.name} ${l.company ?? ""} ${l.phone ?? ""} ${l.email ?? ""}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );

  return (
    <>
      <PageHeader
        title="Leads"
        description="People your agent talks to. It remembers each one across calls."
        actions={
          can("leads.manage") ? (
            <>
              <Button variant={panel === "add" ? "primary" : "secondary"} onClick={() => setPanel(panel === "add" ? null : "add")}>
                Add lead
              </Button>
              <Button variant={panel === "import" ? "primary" : "secondary"} onClick={() => setPanel(panel === "import" ? null : "import")}>
                Import CSV
              </Button>
            </>
          ) : null
        }
      />
      {panel === "add" ? (
        <Card className="mb-6" title="New lead">
          <AddLead onAdded={() => void leads.reload()} />
        </Card>
      ) : null}
      {panel === "import" ? (
        <Card className="mb-6" title="Import leads">
          <ImportLeads onImported={() => void leads.reload()} />
        </Card>
      ) : null}
      <Card
        title={`${shown.length} leads`}
        actions={
          <>
            <Input placeholder="Search" value={search} onChange={(e) => setSearch(e.target.value)} className="w-48" />
            <label className="flex items-center gap-2 text-sm text-muted">
              <input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} />
              Archived
            </label>
          </>
        }
      >
        {leads.loading && !leads.data ? (
          <Loading />
        ) : (
          <>
            <Alert>{leads.error}</Alert>
            <Table
              head={["Name", "Company", "Phone", "Interest", "Status", "Added"]}
              rows={shown.map((l) => [
                <Link key="n" className="font-medium text-accent" href={`/leads/${l.id}`}>
                  {l.name}
                </Link>,
                l.company ?? "—",
                l.phone ?? "—",
                <StatusBadge key="i" value={l.interest} />,
                <StatusBadge key="s" value={l.erased_at ? "erased" : l.status} />,
                formatDate(l.created_at, false),
              ])}
              empty="No leads yet."
            />
          </>
        )}
      </Card>
    </>
  );
}
