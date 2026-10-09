"use client";

import Link from "next/link";

import {
  Alert,
  Card,
  Loading,
  PageHeader,
  StatusBadge,
  Table,
  formatDate,
  formatDuration,
} from "@/components/ui";
import type { Schemas } from "@/lib/api";
import { useApi } from "@/lib/hooks";

export default function CallsPage() {
  const calls = useApi<Schemas["CallListItem"][]>("/voice/calls", { limit: 200 });
  return (
    <>
      <PageHeader title="Calls" description="Browser test calls and phone calls, newest first." />
      <Card>
        {calls.data ? (
          <Table
            head={["When", "Lead", "Channel", "Status", "Phone", "Length", "Stage reached"]}
            rows={calls.data.map((c) => [
              <Link key="w" className="text-accent" href={`/calls/${c.id}`}>{formatDate(c.created_at)}</Link>,
              c.lead_id ? <Link key="l" href={`/leads/${c.lead_id}`}>{c.lead_name}</Link> : "—",
              c.direction ? `${c.channel} · ${c.direction}` : c.channel,
              <StatusBadge key="s" value={c.status} />,
              c.dial_status ? <StatusBadge key="d" value={c.dial_status} /> : "—",
              formatDuration(c.started_at, c.ended_at),
              c.sales_state.replaceAll("_", " "),
            ])}
            empty="No calls yet."
          />
        ) : calls.error ? (
          <Alert>{calls.error}</Alert>
        ) : (
          <Loading />
        )}
      </Card>
    </>
  );
}
