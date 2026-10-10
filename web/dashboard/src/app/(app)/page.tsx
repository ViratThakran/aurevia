"use client";

import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";

import { Icon } from "@/components/icons";
import {
  Alert,
  Empty,
  LinkButton,
  Loading,
  PageHeader,
  cx,
  formatDate,
} from "@/components/ui";
import type { Schemas } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import { type AnalyticsSummary, money, percent } from "@/lib/types";

const LATENCY_TARGET_MS = 1000;

function vars(index: number, extra?: CSSProperties): CSSProperties {
  return { "--i": index, ...extra } as CSSProperties;
}

function initials(name: string | null | undefined): string {
  const parts = (name ?? "?").split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "?") + (parts[1]?.[0] ?? "")).toUpperCase();
}

function Panel({
  index,
  title,
  action,
  className,
  children,
}: {
  index: number;
  title?: ReactNode;
  action?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section
      className={cx("surface-card lift rise-in flex flex-col p-5", className)}
      style={vars(index)}
    >
      {title ? (
        <header className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-[15px] font-semibold tracking-tight">{title}</h2>
          {action}
        </header>
      ) : null}
      {children}
    </section>
  );
}

function ArrowLink({
  href,
  label,
  hero,
}: {
  href: string;
  label: string;
  hero?: boolean;
}) {
  return (
    <Link
      href={href}
      aria-label={label}
      className={cx(
        "grid h-8 w-8 place-items-center rounded-full border transition duration-300 hover:rotate-45",
        hero
          ? "border-white/20 bg-white text-accent-strong"
          : "border-foreground/70 text-foreground",
      )}
    >
      <Icon name="arrow" size={14} />
    </Link>
  );
}

function StatCard({
  index,
  title,
  value,
  note,
  href,
  hero,
}: {
  index: number;
  title: string;
  value: ReactNode;
  note: ReactNode;
  href: string;
  hero?: boolean;
}) {
  return (
    <div
      className={cx("surface-card lift rise-in p-5", hero && "card-hero")}
      style={vars(index)}
    >
      <div className="flex items-start justify-between gap-2">
        <span
          className={cx(
            "text-[15px] font-medium",
            hero ? "text-white" : "text-foreground",
          )}
        >
          {title}
        </span>
        <ArrowLink href={href} label={title} hero={hero} />
      </div>
      <div className="mt-4 text-5xl font-semibold tracking-tight tabular-nums">
        {value}
      </div>
      <div
        className={cx("mt-3 text-xs", hero ? "text-white/75" : "text-muted")}
      >
        {note}
      </div>
    </div>
  );
}

/** Calls per day for the last 7 days, as rounded pill bars; empty days are hatched. */
function CallChart({ calls }: { calls: Schemas["CallListItem"][] }) {
  const days = Array.from({ length: 7 }, (_, i) => {
    const day = new Date();
    day.setHours(0, 0, 0, 0);
    day.setDate(day.getDate() - (6 - i));
    return day;
  });
  const counts = days.map(
    (day) =>
      calls.filter((c) => {
        const t = new Date(c.created_at);
        return t >= day && t.getTime() < day.getTime() + 86_400_000;
      }).length,
  );
  const max = Math.max(1, ...counts);
  const peak = counts.indexOf(Math.max(...counts));
  return (
    <div className="flex flex-1 items-end gap-2 sm:gap-3">
      {days.map((day, i) => {
        const n = counts[i];
        const today = i === 6;
        const height = n === 0 ? 42 : 30 + (n / max) * 70;
        return (
          <div key={i} className="flex flex-1 flex-col items-center gap-2">
            <div className="relative flex h-44 w-full items-end justify-center">
              {today && n > 0 ? (
                <span className="absolute -top-1 rounded-md border border-border bg-surface px-1.5 py-0.5 text-[10px] font-semibold shadow-sm">
                  {n}
                </span>
              ) : null}
              <div
                title={`${day.toLocaleDateString(undefined, { weekday: "long" })}: ${n} calls`}
                className={cx(
                  "grow-up w-full max-w-14 rounded-full",
                  n === 0
                    ? "hatch"
                    : today
                      ? "bg-accent-mid"
                      : i === peak
                        ? "bg-accent-strong"
                        : "bg-accent",
                )}
                style={vars(i, { height: `${height}%` })}
              />
            </div>
            <span className="text-[11px] text-muted">
              {day.toLocaleDateString(undefined, { weekday: "narrow" })}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** Half-donut: completed share first, then in progress, the rest hatched. */
function Gauge({
  completed,
  active,
  total,
}: {
  completed: number;
  active: number;
  total: number;
}) {
  const r = 80;
  const length = Math.PI * r;
  const done = total ? completed / total : 0;
  const live = total ? active / total : 0;
  const arc = `M ${100 - r} 100 A ${r} ${r} 0 0 1 ${100 + r} 100`;
  return (
    <div className="relative mx-auto w-full max-w-60">
      <svg viewBox="0 0 200 112" className="w-full" aria-hidden>
        <defs>
          <pattern
            id="gauge-hatch"
            width="6"
            height="6"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(45)"
          >
            <line
              x1="0"
              y1="0"
              x2="0"
              y2="6"
              stroke="var(--muted)"
              strokeOpacity="0.35"
              strokeWidth="2"
            />
          </pattern>
        </defs>
        <path d={arc} fill="none" stroke="url(#gauge-hatch)" strokeWidth="22" />
        <path
          d={arc}
          fill="none"
          stroke="var(--accent-strong)"
          strokeWidth="22"
          className="ring-progress"
          strokeDasharray={`${length * (done + live)} ${length}`}
        />
        <path
          d={arc}
          fill="none"
          stroke="var(--accent)"
          strokeWidth="22"
          className="ring-progress"
          strokeDasharray={`${length * done} ${length}`}
        />
      </svg>
      <div className="absolute inset-x-0 bottom-0 text-center">
        <div className="text-4xl font-semibold tracking-tight tabular-nums">
          {total ? `${Math.round(done * 100)}%` : "—"}
        </div>
        <div className="text-xs text-muted">Calls completed</div>
      </div>
    </div>
  );
}

const STATUS_PILL: Record<string, string> = {
  completed: "border-emerald-300 text-emerald-700 bg-emerald-50",
  in_progress: "border-amber-300 text-amber-700 bg-amber-50",
  created: "border-amber-300 text-amber-700 bg-amber-50",
  failed: "border-rose-300 text-rose-700 bg-rose-50",
  no_answer: "border-rose-300 text-rose-700 bg-rose-50",
  busy: "border-rose-300 text-rose-700 bg-rose-50",
};

export default function OverviewPage() {
  const { can, me } = useSession();
  const analytics = useApi<AnalyticsSummary>(
    can("analytics.read") ? "/analytics/summary" : null,
    {
      days: 30,
    },
  );
  const calls = useApi<Schemas["CallListItem"][]>("/voice/calls", {
    limit: 500,
  });
  const meetings = useApi<Schemas["MeetingItem"][]>("/meetings", { limit: 20 });
  const handoffs = useApi<Schemas["HandoffItem"][]>("/handoffs", {
    status: "open",
    limit: 20,
  });
  const leads = useApi<Schemas["LeadResponse"][]>("/leads");

  const a = analytics.data;
  const callList = calls.data ?? [];
  const openHandoffs = handoffs.data?.length ?? 0;
  const latency = a?.ai_quality.latency_p50_ms ?? null;
  const now = Date.now();
  const nextMeeting = (meetings.data ?? [])
    .filter((m) => new Date(m.ends_at).getTime() >= now)
    .sort((x, y) => x.starts_at.localeCompare(y.starts_at))[0];
  const newestLeads = [...(leads.data ?? [])]
    .sort((x, y) => y.created_at.localeCompare(x.created_at))
    .slice(0, 5);
  const count = (status: string) =>
    callList.filter((c) => c.status === status).length;
  const totalCalls = a?.activity.calls ?? callList.length;
  const time = (iso: string) =>
    new Date(iso).toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
    });

  return (
    <>
      <PageHeader
        title="Overview"
        description={`How your agent is selling at ${me?.tenant.name ?? "your company"}, last 30 days.`}
        actions={
          <>
            {can("calls.place") ? (
              <LinkButton href="/test-call" variant="primary">
                <Icon name="plus" size={15} /> Test call
              </LinkButton>
            ) : null}
            <LinkButton href="/leads">
              <Icon name="users" size={15} /> Import leads
            </LinkButton>
          </>
        }
      />

      {analytics.error ? (
        <div className="mb-4">
          <Alert>{analytics.error}</Alert>
        </div>
      ) : null}

      {calls.loading && !calls.data ? (
        <Loading />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard
            index={0}
            hero
            title="Total calls"
            value={totalCalls}
            href="/calls"
            note={
              a
                ? `${a.activity.completed} completed · ${a.activity.failed} failed`
                : "All calls"
            }
          />
          <StatCard
            index={1}
            title="Connected"
            value={a?.activity.connected ?? count("completed")}
            href="/calls"
            note={
              a
                ? `Answer rate ${percent(a.activity.phone_answer_rate)}`
                : "Prospect picked up"
            }
          />
          <StatCard
            index={2}
            title="Meetings booked"
            value={a?.sales.meetings_booked ?? meetings.data?.length ?? 0}
            href="/activity"
            note={
              a
                ? `${percent(a.sales.meetings_per_connected_call)} of connected calls`
                : "Booked by the agent"
            }
          />
          <StatCard
            index={3}
            title="Needs a person"
            value={openHandoffs}
            href="/activity"
            note={
              <span
                className={openHandoffs ? "font-medium text-accent" : undefined}
              >
                {openHandoffs ? "Waiting for your team" : "Nothing waiting"}
              </span>
            }
          />

          <Panel
            index={4}
            title="Call activity"
            className="sm:col-span-2"
            action={<span className="text-xs text-muted">Last 7 days</span>}
          >
            <CallChart calls={callList} />
          </Panel>

          <Panel index={5} title="Next meeting">
            {nextMeeting ? (
              <>
                <div className="text-2xl leading-tight font-semibold tracking-tight text-accent">
                  Meeting with {nextMeeting.lead_name}
                </div>
                <div className="mt-2 text-xs text-muted">
                  {formatDate(nextMeeting.starts_at, false)} ·{" "}
                  {time(nextMeeting.starts_at)} – {time(nextMeeting.ends_at)}
                </div>
              </>
            ) : (
              <>
                <div className="text-2xl leading-tight font-semibold tracking-tight text-accent">
                  No meetings booked yet
                </div>
                <div className="mt-2 text-xs text-muted">
                  Meetings your agent books appear here.
                </div>
              </>
            )}
            <Link
              href={nextMeeting ? "/activity" : "/test-call"}
              className="mt-auto flex items-center justify-center gap-2 rounded-full bg-accent-strong py-2.5 text-sm font-medium text-white transition hover:-translate-y-px hover:brightness-110"
            >
              <Icon name={nextMeeting ? "calendar" : "mic"} size={15} />
              {nextMeeting ? "Open meetings" : "Start a test call"}
            </Link>
          </Panel>

          <Panel
            index={6}
            title="Leads"
            action={
              <Link
                href="/leads"
                className="inline-flex items-center gap-1 rounded-full border border-foreground/70 px-2.5 py-1 text-xs font-medium transition hover:-translate-y-px"
              >
                <Icon name="plus" size={12} /> New
              </Link>
            }
          >
            {newestLeads.length ? (
              <ul className="space-y-3.5">
                {newestLeads.map((lead) => (
                  <li key={lead.id} className="flex items-center gap-3">
                    <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-accent-soft text-[11px] font-semibold text-accent">
                      {initials(lead.name)}
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium">
                        {lead.name}
                      </span>
                      <span className="block truncate text-[11px] text-muted">
                        {lead.company ? `${lead.company} · ` : ""}Added{" "}
                        {formatDate(lead.created_at, false)}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <Empty>No leads yet.</Empty>
            )}
          </Panel>

          <Panel
            index={7}
            title="Recent calls"
            className="sm:col-span-2"
            action={<LinkButton href="/calls">All calls</LinkButton>}
          >
            {callList.length ? (
              <ul className="space-y-3">
                {callList.slice(0, 5).map((c) => (
                  <li key={c.id}>
                    <Link
                      href={`/calls/${c.id}`}
                      className="flex items-center gap-3 rounded-xl px-1 py-0.5 transition hover:bg-accent-soft/60"
                    >
                      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-accent-soft text-xs font-semibold text-accent">
                        {initials(c.lead_name)}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">
                          {c.lead_name ?? "Unknown lead"}
                        </span>
                        <span className="block truncate text-[11px] text-muted">
                          {c.channel === "phone"
                            ? "Phone call"
                            : "Browser call"}{" "}
                          · {c.turn_count} turns · {formatDate(c.created_at)}
                        </span>
                      </span>
                      <span
                        className={cx(
                          "rounded-md border px-2 py-0.5 text-[11px] font-medium capitalize",
                          STATUS_PILL[c.status] ?? "border-border text-muted",
                        )}
                      >
                        {c.status.replaceAll("_", " ")}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <Empty>No calls yet.</Empty>
            )}
          </Panel>

          <Panel index={8} title="Call outcomes">
            <Gauge
              completed={count("completed")}
              active={count("in_progress")}
              total={callList.length}
            />
            <div className="mt-4 flex flex-wrap justify-center gap-x-4 gap-y-1 text-[11px] text-muted">
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-accent" />
                Completed
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-accent-strong" />
                In progress
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="hatch h-2 w-2 rounded-full" />
                Other
              </span>
            </div>
          </Panel>

          <section
            className="rise-in flex flex-col rounded-2xl bg-ink p-5 text-ink-foreground"
            style={vars(9)}
          >
            <div className="flex items-center justify-between">
              <h2 className="text-[15px] font-semibold">Reply time</h2>
              {a?.economics ? (
                <span className="text-[11px] opacity-60">
                  Cost {money(a.economics.cost)}
                </span>
              ) : null}
            </div>
            <div className="my-auto py-4 text-center">
              <div className="font-mono text-5xl font-semibold tracking-tight tabular-nums">
                {latency ? `${(latency / 1000).toFixed(1)}s` : "--.-s"}
              </div>
              <div className="mt-1 text-xs opacity-60">
                Typical · target {(LATENCY_TARGET_MS / 1000).toFixed(1)} s
                {a?.ai_quality.latency_p95_ms
                  ? ` · slowest ${(a.ai_quality.latency_p95_ms / 1000).toFixed(1)} s`
                  : ""}
              </div>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
