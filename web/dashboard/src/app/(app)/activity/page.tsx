"use client";

import Link from "next/link";
import { useState } from "react";

import {
  Alert,
  Button,
  Card,
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

export default function ActivityPage() {
  const { can } = useSession();
  const [pastMeetings, setPastMeetings] = useState(false);
  const [followupStatus, setFollowupStatus] = useState("scheduled");
  const [handoffStatus, setHandoffStatus] = useState("open");
  const meetings = useApi<Schemas["MeetingItem"][]>("/meetings", { include_past: pastMeetings });
  const followups = useApi<Schemas["FollowupItem"][]>("/followups", { status: followupStatus || null });
  const handoffs = useApi<Schemas["HandoffItem"][]>("/handoffs", { status: handoffStatus || null });
  const { run, error, pending } = useAction();
  const manage = can("leads.manage");

  const lead = (id: string | null | undefined, name: string | null | undefined) =>
    id ? <Link className="text-accent" href={`/leads/${id}`}>{name}</Link> : (name ?? "Unknown caller");

  return (
    <>
      <PageHeader title="Meetings & tasks" description="What the agent booked, promised and passed on to your team." />
      <Alert>{error}</Alert>
      <div className="mt-2 grid gap-6">
        <Card
          title="Requests for a person"
          actions={
            <Select className="w-32" value={handoffStatus} onChange={(e) => setHandoffStatus(e.target.value)}>
              <option value="open">Open</option>
              <option value="resolved">Resolved</option>
              <option value="">All</option>
            </Select>
          }
        >
          {handoffs.data ? (
            <Table
              head={["When", "Who", "Reason", "Urgency", "Status", ""]}
              rows={handoffs.data.map((h) => [
                formatDate(h.created_at),
                lead(h.lead_id, h.lead_name),
                h.reason,
                <StatusBadge key="u" value={h.urgency} />,
                <StatusBadge key="s" value={h.status} />,
                manage && h.status === "open" ? (
                  <Button key="r" variant="secondary" pending={pending} onClick={async () => {
                    if (await run(() => api(`/handoffs/${h.id}/resolve`, { method: "POST" }))) void handoffs.reload();
                  }}>Mark handled</Button>
                ) : null,
              ])}
              empty="Nothing waiting for a person."
            />
          ) : <Loading />}
        </Card>

        <Card
          title="Meetings"
          actions={
            <label className="flex items-center gap-2 text-sm text-muted">
              <input type="checkbox" checked={pastMeetings} onChange={(e) => setPastMeetings(e.target.checked)} /> Include past
            </label>
          }
        >
          {meetings.data ? (
            <Table
              head={["When", "With", "Status", "Booked on"]}
              rows={meetings.data.map((m) => [
                formatDate(m.starts_at),
                lead(m.lead_id, m.lead_name),
                <StatusBadge key="s" value={m.status} />,
                m.call_id ? <Link key="c" className="text-accent" href={`/calls/${m.call_id}`}>call</Link> : "—",
              ])}
              empty="No meetings."
            />
          ) : <Loading />}
        </Card>

        <Card
          title="Follow-ups"
          actions={
            <Select className="w-36" value={followupStatus} onChange={(e) => setFollowupStatus(e.target.value)}>
              <option value="scheduled">Scheduled</option>
              <option value="done">Done</option>
              <option value="cancelled">Cancelled</option>
              <option value="">All</option>
            </Select>
          }
        >
          {followups.data ? (
            <Table
              head={["Due", "Who", "How", "Note", "Status", ""]}
              rows={followups.data.map((f) => [
                formatDate(f.due_at),
                lead(f.lead_id, f.lead_name),
                f.channel,
                f.note,
                <StatusBadge key="s" value={f.status} />,
                manage && f.status === "scheduled" ? (
                  <div key="a" className="flex gap-1">
                    {(["done", "cancelled"] as const).map((status) => (
                      <Button key={status} variant="ghost" pending={pending} onClick={async () => {
                        if (await run(() => api(`/followups/${f.id}`, { method: "PATCH", body: { status } }))) void followups.reload();
                      }}>{status === "done" ? "Done" : "Cancel"}</Button>
                    ))}
                  </div>
                ) : null,
              ])}
              empty="No follow-ups."
            />
          ) : <Loading />}
        </Card>
      </div>
    </>
  );
}
