"use client";

import { use } from "react";

import {
  Alert,
  Card,
  Empty,
  Loading,
  PageHeader,
  Stat,
  StatusBadge,
  formatDate,
  formatDuration,
} from "@/components/ui";
import type { Schemas } from "@/lib/api";
import { useApi } from "@/lib/hooks";

function seconds(ms: number | null | undefined): string {
  return ms ? `${(ms / 1000).toFixed(2)} s` : "—";
}

export default function CallPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const call = useApi<Schemas["CallResponse"]>(`/voice/calls/${id}`);
  const transcript = useApi<Schemas["TranscriptResponse"]>(`/voice/calls/${id}/transcript`);

  if (!call.data) return call.error ? <Alert>{call.error}</Alert> : <Loading />;
  const c = call.data;
  const latency = c.latency;

  return (
    <>
      <PageHeader
        title="Call"
        description={`${c.channel} · ${formatDate(c.started_at ?? null)}`}
        actions={<StatusBadge value={c.status} />}
      />
      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Length" value={formatDuration(c.started_at, c.ended_at)} hint={c.end_reason?.replaceAll("_", " ")} />
        <Stat label="Turns" value={c.turn_count} hint={`Reached: ${c.sales_state.replaceAll("_", " ")}`} />
        <Stat
          label="Reply time (median)"
          value={seconds(latency.e2e_p50_ms)}
          hint={`95th percentile ${seconds(latency.e2e_p95_ms)} · target ${seconds(latency.target_p50_ms)}`}
        />
        <Stat
          label="Model usage"
          value={`${c.usage.llm_turns} replies`}
          hint={`${c.usage.llm_input_tokens + c.usage.llm_output_tokens} tokens · ${c.usage.llm_interrupted_turns} interrupted · ${Math.round(c.usage.stt_seconds)} s heard`}
        />
      </div>
      <Card title="Transcript">
        {transcript.data ? (
          transcript.data.lines.length ? (
            <div className="space-y-2 text-sm">
              {transcript.data.lines.map((line) => (
                <p key={line.seq}>
                  <span className={line.speaker === "agent" ? "font-medium text-accent" : "font-medium"}>
                    {line.speaker === "agent" ? "Agent" : "Prospect"}:
                  </span>{" "}
                  {line.text}
                </p>
              ))}
            </div>
          ) : (
            <Empty>No transcript: the call had no conversation, or it has expired (kept 90 days).</Empty>
          )
        ) : transcript.error ? (
          <Alert>{transcript.error}</Alert>
        ) : (
          <Loading />
        )}
      </Card>
    </>
  );
}
