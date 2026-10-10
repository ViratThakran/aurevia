"use client";

import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";

import {
  Alert,
  Card,
  Empty,
  FloatingPill,
  LinkButton,
  Loading,
  PageHeader,
  ProgressRing,
  StatusBadge,
  Table,
  Ticker,
  cx,
  formatDate,
} from "@/components/ui";
import type { Schemas } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import { type AnalyticsSummary, money, percent } from "@/lib/types";

const LATENCY_TARGET_MS = 1000;

/** A bento tile without a header: used for the metric cards. */
function Tile({
  index,
  className,
  children,
}: {
  index: number;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cx("surface-card lift rise-in p-5", className)}
      style={{ "--i": index } as CSSProperties}
    >
      {children}
    </div>
  );
}

function TileLabel({ children }: { children: ReactNode }) {
  return <div className="text-xs font-medium tracking-wide text-muted uppercase">{children}</div>;
}

function RingTile({
  index,
  label,
  value,
  caption,
}: {
  index: number;
  label: string;
  value: number | null | undefined;
  caption: ReactNode;
}) {
  return (
    <Tile index={index} className="flex items-center gap-4">
      <ProgressRing value={value}>
        <span className="text-lg font-semibold tabular-nums">{percent(value)}</span>
      </ProgressRing>
      <div className="min-w-0">
        <TileLabel>{label}</TileLabel>
        <div className="mt-1 text-sm text-muted">{caption}</div>
      </div>
    </Tile>
  );
}

/** Share of calls per status, as one segmented bar. */
function StatusBar({ byStatus, total }: { byStatus: Record<string, number>; total: number }) {
  const entries = Object.entries(byStatus).filter(([, n]) => n > 0);
  if (total === 0 || entries.length === 0) return null;
  const shade: Record<string, string> = {
    completed: "bg-accent",
    in_progress: "bg-accent/60",
    no_answer: "bg-warning/70",
    busy: "bg-warning",
    failed: "bg-danger/80",
  };
  return (
    <div className="mt-5">
      <div className="flex h-2 overflow-hidden rounded-full bg-accent-soft">
        {entries.map(([status, n]) => (
          <div
            key={status}
            title={`${status.replaceAll("_", " ")}: ${n}`}
            className={cx("h-full", shade[status] ?? "bg-muted/40")}
            style={{ width: `${(n / total) * 100}%` }}
          />
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        {entries.map(([status, n]) => (
          <span key={status} className="inline-flex items-center gap-1.5">
            <span className={cx("h-2 w-2 rounded-full", shade[status] ?? "bg-muted/40")} />
            {status.replaceAll("_", " ")} {n}
          </span>
        ))}
      </div>
    </div>
  );
}

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
  const openHandoffs = handoffs.data?.length ?? 0;
  const latency = a?.ai_quality.latency_p50_ms ?? null;

  // The dark ticker cycles through what happened most recently.
  const tickerItems: ReactNode[] = [
    ...(calls.data ?? []).map((c) => (
      <span key={`c${c.id}`}>
        <span className="opacity-60">{formatDate(c.created_at)} · </span>
        Call with {c.lead_name ?? "a lead"}: {c.status.replaceAll("_", " ")}
      </span>
    )),
    ...(meetings.data ?? []).map((m) => (
      <span key={`m${m.id}`}>
        <span className="opacity-60">Meeting · </span>
        {m.lead_name} on {formatDate(m.starts_at)}
      </span>
    )),
    ...(handoffs.data ?? []).map((h) => (
      <span key={`h${h.id}`}>
        <span className="opacity-60">Needs a person · </span>
        {h.lead_name ?? "Unknown caller"}: {h.reason}
      </span>
    )),
  ];

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

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {can("analytics.read") ? (
          analytics.loading ? (
            <div className="sm:col-span-2 lg:col-span-4">
              <Loading />
            </div>
          ) : a ? (
            <>
              <Tile index={0} className="sm:col-span-2">
                <TileLabel>Calls</TileLabel>
                <div className="mt-2 flex items-baseline gap-3">
                  <span className="text-5xl font-semibold tracking-tight tabular-nums">
                    {a.activity.calls}
                  </span>
                  <span className="rounded-full bg-accent-soft px-2.5 py-0.5 text-xs font-medium text-accent">
                    {a.activity.connected} connected
                  </span>
                </div>
                <StatusBar byStatus={a.activity.by_status} total={a.activity.calls} />
              </Tile>

              <RingTile
                index={1}
                label="Meetings booked"
                value={a.sales.meetings_per_connected_call}
                caption={
                  <>
                    <span className="font-semibold text-foreground">{a.sales.meetings_booked}</span>{" "}
                    booked, of connected calls
                  </>
                }
              />
              <RingTile
                index={2}
                label="Phone answer rate"
                value={a.activity.phone_answer_rate}
                caption={`${a.sales.interested} interested · ${a.sales.handoffs} handoffs`}
              />

              <div
                className="surface-card lift rise-in bg-ink p-5 text-ink-foreground sm:col-span-2"
                style={{ "--i": 3, borderColor: "transparent", background: "var(--ink)" } as CSSProperties}
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium tracking-wide uppercase opacity-60">
                    Live activity
                  </span>
                  <span className="inline-flex items-center gap-1.5 text-xs opacity-60">
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#4ade80]" />
                    latest
                  </span>
                </div>
                <div className="mt-4 text-sm">
                  {tickerItems.length > 0 ? (
                    <Ticker items={tickerItems} />
                  ) : (
                    <span className="opacity-60">Nothing yet: make a test call.</span>
                  )}
                </div>
              </div>

              <Tile index={4} className="flex items-center gap-4">
                <ProgressRing value={latency ? Math.min(1, LATENCY_TARGET_MS / latency) : null}>
                  <span className="text-base font-semibold tabular-nums">
                    {latency ? `${(latency / 1000).toFixed(1)}s` : "—"}
                  </span>
                </ProgressRing>
                <div className="min-w-0">
                  <TileLabel>Reply time</TileLabel>
                  <div className="mt-1 text-sm text-muted">
                    Typical; target {(LATENCY_TARGET_MS / 1000).toFixed(1)} s
                  </div>
                </div>
              </Tile>

              <Tile index={5}>
                <TileLabel>Cost</TileLabel>
                <div className="mt-2 text-2xl font-semibold tracking-tight tabular-nums">
                  {money(a.economics.cost)}
                </div>
                <div className="mt-1 text-xs text-muted">
                  {a.economics.cost_per_meeting
                    ? `${money(a.economics.cost_per_meeting)} per meeting`
                    : a.economics.fully_priced
                      ? "All usage priced"
                      : "Some usage not priced yet"}
                </div>
              </Tile>
            </>
          ) : (
            <div className="sm:col-span-2 lg:col-span-4">
              <Alert>{analytics.error}</Alert>
            </div>
          )
        ) : null}

        <Card
          index={6}
          className="sm:col-span-2"
          title="Recent calls"
          actions={<LinkButton href="/calls">All calls</LinkButton>}
        >
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

        <Card index={7} title="Needs a person" actions={<LinkButton href="/activity">Tasks</LinkButton>}>
          {handoffs.data && handoffs.data.length > 0 ? (
            <ul className="space-y-2 text-sm">
              {handoffs.data.map((h) => (
                <li key={h.id} className="rounded-xl border border-border px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate font-medium">{h.lead_name ?? "Unknown caller"}</span>
                    <StatusBadge value={h.urgency} />
                  </div>
                  <div className="mt-0.5 line-clamp-2 text-xs text-muted">{h.reason}</div>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>No open handoffs.</Empty>
          )}
        </Card>

        <Card index={8} title="Upcoming meetings">
          {meetings.data && meetings.data.length > 0 ? (
            <ul className="space-y-2 text-sm">
              {meetings.data.map((m) => (
                <li
                  key={m.id}
                  className="flex items-center justify-between gap-2 rounded-xl bg-accent-soft px-3 py-2"
                >
                  <span className="truncate font-medium">{m.lead_name}</span>
                  <span className="shrink-0 text-xs text-muted">{formatDate(m.starts_at)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>No meetings booked.</Empty>
          )}
        </Card>
      </div>

      {openHandoffs > 0 ? (
        <FloatingPill href="/activity">
          {openHandoffs} {openHandoffs === 1 ? "lead needs" : "leads need"} a person
        </FloatingPill>
      ) : null}
    </>
  );
}
