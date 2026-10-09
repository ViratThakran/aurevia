"use client";

import Link from "next/link";

import {
  Alert,
  Card,
  Empty,
  LinkButton,
  Loading,
  PageHeader,
  Stat,
  StatusBadge,
  Table,
  formatDate,
} from "@/components/ui";
import type { Schemas } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import { type AnalyticsSummary, money, percent } from "@/lib/types";

export default function OverviewPage() {
  const { can, me } = useSession();
  const analytics = useApi<AnalyticsSummary>(can("analytics.read") ? "/analytics/summary" : null, {
    days: 30,
  });
  const calls = useApi<Schemas["CallListItem"][]>("/voice/calls", { limit: 5 });
  const meetings = useApi<Schemas["MeetingItem"][]>("/meetings", { limit: 5 });
  const handoffs = useApi<Schemas["HandoffItem"][]>("/handoffs", { status: "open", limit: 5 });

  const a = analytics.data;
  const noCallsYet = calls.data !== null && calls.data.length === 0;

  return (
    <>
      <PageHeader
        title="Overview"
        description={`Last 30 days at ${me?.tenant.name ?? ""}`}
        actions={
          can("calls.place") ? (
            <LinkButton href="/test-call" variant="primary">
              Test call
            </LinkButton>
          ) : null
        }
      />

      {noCallsYet ? (
        <div className="mb-6">
          <Alert tone="neutral">
            No calls yet.{" "}
            <Link className="font-medium text-accent" href="/onboarding">
              Finish setting up
            </Link>{" "}
            and talk to your agent in the browser.
          </Alert>
        </div>
      ) : null}

      {can("analytics.read") ? (
        analytics.loading ? (
          <Loading />
        ) : a ? (
          <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Calls" value={a.activity.calls} hint={`${a.activity.connected} connected`} />
            <Stat
              label="Meetings booked"
              value={a.sales.meetings_booked}
              hint={`${percent(a.sales.meetings_per_connected_call)} of connected calls`}
            />
            <Stat
              label="Typical reply time"
              value={
                a.ai_quality.latency_p50_ms
                  ? `${(a.ai_quality.latency_p50_ms / 1000).toFixed(1)} s`
                  : "—"
              }
              hint="Prospect stops talking → agent speaks"
            />
            <Stat
              label="Cost"
              value={money(a.economics.cost)}
              hint={a.economics.fully_priced ? "All usage priced" : "Some usage not priced yet"}
            />
          </div>
        ) : (
          <Alert>{analytics.error}</Alert>
        )
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Recent calls" actions={<LinkButton href="/calls">All calls</LinkButton>}>
          {calls.data ? (
            <Table
              head={["When", "Lead", "Channel", "Status"]}
              rows={calls.data.map((c) => [
                <Link key="w" className="text-accent" href={`/calls/${c.id}`}>
                  {formatDate(c.created_at)}
                </Link>,
                c.lead_name ?? "—",
                c.channel,
                <StatusBadge key="s" value={c.status} />,
              ])}
              empty="No calls yet."
            />
          ) : (
            <Loading />
          )}
        </Card>

        <Card
          title="Needs a person"
          actions={<LinkButton href="/activity">Meetings & tasks</LinkButton>}
        >
          {handoffs.data && handoffs.data.length > 0 ? (
            <ul className="divide-y divide-border text-sm">
              {handoffs.data.map((h) => (
                <li key={h.id} className="flex items-start justify-between gap-3 py-2">
                  <span>
                    <span className="font-medium">{h.lead_name ?? "Unknown caller"}</span>:{" "}
                    {h.reason}
                  </span>
                  <StatusBadge value={h.urgency} />
                </li>
              ))}
            </ul>
          ) : (
            <Empty>No open handoffs.</Empty>
          )}
          <h3 className="mt-4 mb-2 text-sm font-semibold">Upcoming meetings</h3>
          {meetings.data && meetings.data.length > 0 ? (
            <ul className="divide-y divide-border text-sm">
              {meetings.data.map((m) => (
                <li key={m.id} className="flex justify-between py-2">
                  <span>{m.lead_name}</span>
                  <span className="text-muted">{formatDate(m.starts_at)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>No meetings booked.</Empty>
          )}
        </Card>
      </div>
    </>
  );
}
