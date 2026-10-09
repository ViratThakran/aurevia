"use client";

import { Alert, Card, Loading, PageHeader, Stat, Table, formatDate } from "@/components/ui";
import { useApi } from "@/lib/hooks";
import { type UsageReport, money } from "@/lib/types";

const RESOURCES: Record<string, string> = {
  llm_input_tokens: "AI model: input tokens",
  llm_output_tokens: "AI model: output tokens",
  stt_seconds: "Speech recognition: seconds",
  tts_characters: "Voice: characters spoken",
  telephony_seconds: "Phone: seconds connected",
};

function limit(used: number, max: number | null, unit = ""): string {
  const shown = Number.isInteger(used) ? used : used.toFixed(1);
  return max === null ? `${shown}${unit} (no limit)` : `${shown}${unit} of ${max}${unit}`;
}

export default function UsagePage() {
  const usage = useApi<UsageReport>("/usage");
  if (!usage.data) return usage.error ? <Alert>{usage.error}</Alert> : <Loading />;
  const u = usage.data;
  return (
    <>
      <PageHeader
        title="Usage"
        description={`Since ${formatDate(u.month_start, false)} · plan: ${u.plan.plan_name}. Limits are checked before every call.`}
      />
      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Calls this month" value={u.used.calls} hint={limit(u.used.calls, u.plan.monthly_call_limit)} />
        <Stat label="Minutes" value={u.used.minutes.toFixed(1)} hint={limit(u.used.minutes, u.plan.monthly_minute_limit, " min")} />
        <Stat label="Calls right now" value={u.used.concurrent_calls} hint={`at most ${u.plan.max_concurrent_calls} at once`} />
        <Stat
          label="Cost this month"
          value={money(u.cost)}
          hint={u.plan.monthly_cost_limit ? `limit ${u.plan.cost_currency} ${u.plan.monthly_cost_limit}` : "no spend limit"}
        />
      </div>
      {!u.fully_priced ? (
        <div className="mb-6">
          <Alert tone="warn">Some usage has no price set yet, so the cost shown is incomplete.</Alert>
        </div>
      ) : null}
      <Card title="By resource">
        <Table
          head={["Resource", "Quantity", "Cost", "Not priced"]}
          rows={u.resources.map((r) => [
            RESOURCES[r.resource] ?? r.resource,
            Number(r.quantity).toLocaleString(),
            money(r.cost),
            Number(r.unpriced_quantity) > 0 ? Number(r.unpriced_quantity).toLocaleString() : "—",
          ])}
        />
      </Card>
    </>
  );
}
