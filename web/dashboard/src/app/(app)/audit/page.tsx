"use client";

import { useState } from "react";

import { Alert, Button, Card, Loading, PageHeader, Table, formatDate } from "@/components/ui";
import { api, type Schemas } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";

const PAGE = 100;

export default function AuditPage() {
  const [after, setAfter] = useState(0);
  const events = useApi<Schemas["AuditEventResponse"][]>("/audit/events", { after_seq: after, limit: PAGE });
  const [report, setReport] = useState<Schemas["AuditVerifyResponse"] | null>(null);
  const { run, pending, error } = useAction();

  return (
    <>
      <PageHeader
        title="Audit log"
        description="Every change in this workspace, in order. Each entry is chained to the one before, so edits or deletions show up."
        actions={
          <Button
            pending={pending}
            onClick={async () => setReport(await run(() => api<Schemas["AuditVerifyResponse"]>("/audit/verify")))}
          >
            Verify the log
          </Button>
        }
      />
      <Alert>{error}</Alert>
      {report ? (
        <div className="mb-6">
          <Alert tone={report.ok ? "good" : "bad"}>
            {report.ok
              ? `All ${report.events} entries check out. Current fingerprint: ${report.head_hash?.slice(0, 16)}…`
              : `The log was altered at entry ${report.first_broken_seq}.`}
          </Alert>
        </div>
      ) : null}
      <Card
        actions={
          <>
            <Button variant="secondary" disabled={after === 0} onClick={() => setAfter(Math.max(0, after - PAGE))}>Earlier</Button>
            <Button variant="secondary" disabled={(events.data?.length ?? 0) < PAGE} onClick={() => setAfter(after + PAGE)}>Later</Button>
          </>
        }
        title={`Entries ${after + 1}–${after + (events.data?.length ?? 0)}`}
      >
        {events.data ? (
          <Table
            head={["#", "When", "Action", "Target", "Details"]}
            rows={events.data.map((e) => [
              e.seq,
              formatDate(e.created_at),
              e.action,
              e.target_type ?? "—",
              <code key="d" className="text-xs break-all text-muted">{JSON.stringify(e.details)}</code>,
            ])}
            empty="No entries."
          />
        ) : events.error ? <Alert>{events.error}</Alert> : <Loading />}
      </Card>
    </>
  );
}
