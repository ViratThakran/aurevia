"use client";

import { TestCall } from "@/components/test-call";
import { Card, PageHeader } from "@/components/ui";
import type { Schemas } from "@/lib/api";
import { useApi } from "@/lib/hooks";

export default function TestCallPage() {
  const leads = useApi<Schemas["LeadResponse"][]>("/leads");
  return (
    <>
      <PageHeader
        title="Test call"
        description="Talk to your agent in the browser. Phone calls are placed from Leads and Campaigns."
      />
      <Card>
        <TestCall leads={(leads.data ?? []).map((l) => ({ id: l.id, name: l.name }))} />
      </Card>
    </>
  );
}
