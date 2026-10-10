"use client";

import { AgentForm } from "@/components/agent-form";
import { Card, PageHeader } from "@/components/ui";
import { useSession } from "@/lib/session";

export default function AgentPage() {
  const { can } = useSession();
  return (
    <>
      <PageHeader
        title="Agent"
        description="Who your AI agent is, what it knows and how it sells. It never claims to be human."
      />
      <Card>
        <AgentForm readOnly={!can("agents.manage")} />
      </Card>
    </>
  );
}
