"use client";

import Link from "next/link";
import type {
  ButtonHTMLAttributes,
  CSSProperties,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";

export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "danger" | "ghost";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-accent-strong text-white shadow-sm hover:-translate-y-px hover:brightness-110",
  secondary:
    "border border-border bg-surface hover:-translate-y-px hover:border-accent/40",
  danger: "bg-danger text-white hover:opacity-90",
  ghost: "text-muted hover:bg-background hover:text-foreground",
};

export function Button({
  variant = "primary",
  pending,
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  pending?: boolean;
}) {
  return (
    <button
      type="button"
      {...props}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-full px-4 py-2 text-sm font-medium transition duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0",
        VARIANTS[variant],
        className,
      )}
      disabled={pending || props.disabled}
    >
      {pending ? <Spinner /> : null}
      {children}
    </button>
  );
}

export function LinkButton({
  href,
  children,
  variant = "secondary",
}: {
  href: string;
  children: ReactNode;
  variant?: Variant;
}) {
  return (
    <Link
      href={href}
      className={cx(
        "inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium transition duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]",
        VARIANTS[variant],
      )}
    >
      {children}
    </Link>
  );
}

const FIELD =
  "w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none transition focus:border-accent focus:ring-4 focus:ring-accent/10";

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(FIELD, props.className)} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea rows={4} {...props} className={cx(FIELD, props.className)} />
  );
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx(FIELD, props.className)} />;
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block space-y-1">
      <span className="text-sm font-medium">{label}</span>
      {children}
      {hint ? <span className="block text-xs text-muted">{hint}</span> : null}
    </label>
  );
}

export function Card({
  title,
  actions,
  children,
  className,
  index = 0,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  /** Position among siblings: staggers the slide-in. */
  index?: number;
}) {
  return (
    <section
      className={cx("surface-card lift rise-in", className)}
      style={{ "--i": index } as CSSProperties}
    >
      {title || actions ? (
        <header className="flex flex-wrap items-center justify-between gap-3 px-5 pt-4 pb-3">
          <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
          <div className="flex flex-wrap gap-2">{actions}</div>
        </header>
      ) : null}
      <div className={title || actions ? "px-5 pb-5" : "p-5"}>{children}</div>
    </section>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="rise-in mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description ? (
          <p className="mt-1 text-sm text-muted">{description}</p>
        ) : null}
      </div>
      <div className="flex flex-wrap gap-2">{actions}</div>
    </div>
  );
}

const TONES = {
  neutral: "bg-background text-muted border-border",
  good: "bg-accent-soft text-success border-success/20",
  bad: "bg-danger/10 text-danger border-danger/30",
  warn: "bg-warning/10 text-warning border-warning/30",
  accent: "bg-accent-soft text-accent border-accent/20",
} as const;

export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: keyof typeof TONES;
  children: ReactNode;
}) {
  return (
    <span
      className={cx(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        TONES[tone],
      )}
    >
      {children}
    </span>
  );
}

const STATUS_TONES: Record<string, keyof typeof TONES> = {
  completed: "good",
  answered: "good",
  active: "good",
  done: "good",
  booked: "good",
  ok: "good",
  allow: "good",
  reviewed: "good",
  resolved: "good",
  scheduled: "accent",
  failed: "bad",
  busy: "bad",
  block: "bad",
  suspended: "bad",
  no_answer: "warn",
  skipped: "warn",
  paused: "warn",
  open: "warn",
  in_progress: "accent",
  calling: "accent",
  queued: "neutral",
  created: "neutral",
  draft: "neutral",
  cancelled: "neutral",
  ended: "neutral",
  retired: "neutral",
};

export function StatusBadge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-muted">—</span>;
  return (
    <Badge tone={STATUS_TONES[value] ?? "neutral"}>
      {value.replaceAll("_", " ")}
    </Badge>
  );
}

export function Alert({
  tone = "bad",
  children,
}: {
  tone?: "bad" | "good" | "warn" | "neutral";
  children: ReactNode;
}) {
  if (!children) return null;
  return (
    <div
      role="alert"
      className={cx("rise-in rounded-xl border px-4 py-3 text-sm", TONES[tone])}
    >
      {children}
    </div>
  );
}

export function Spinner() {
  return (
    <span
      aria-hidden
      className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"
    />
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-6 text-sm text-muted">
      <Spinner /> {label}…
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-muted">{children}</p>;
}

export function Stat({
  label,
  value,
  hint,
  index = 0,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  index?: number;
}) {
  return (
    <div
      className="surface-card lift rise-in p-5"
      style={{ "--i": index } as CSSProperties}
    >
      <div className="text-xs font-medium tracking-wide text-muted uppercase">
        {label}
      </div>
      <div className="mt-2 text-3xl font-semibold tracking-tight tabular-nums">
        {value}
      </div>
      {hint ? <div className="mt-1 text-xs text-muted">{hint}</div> : null}
    </div>
  );
}

export function Table({
  head,
  rows,
  empty,
}: {
  head: ReactNode[];
  rows: ReactNode[][];
  empty?: ReactNode;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-border text-[11px] tracking-wide text-muted uppercase">
          <tr>
            {head.map((h, i) => (
              <th key={i} className="px-3 py-2 font-medium whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((cells, r) => (
            <tr key={r} className="transition-colors hover:bg-accent-soft/60">
              {cells.map((cell, c) => (
                <td key={c} className="px-3 py-2 align-top">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && empty ? <Empty>{empty}</Empty> : null}
    </div>
  );
}

export function formatDate(
  value: string | null | undefined,
  withTime = true,
): string {
  if (!value) return "—";
  const date = new Date(value);
  return withTime
    ? date.toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : date.toLocaleDateString(undefined, { dateStyle: "medium" });
}

export function formatDuration(
  start: string | null | undefined,
  end: string | null | undefined,
): string {
  if (!start || !end) return "—";
  const seconds = Math.max(
    0,
    Math.round((new Date(end).getTime() - new Date(start).getTime()) / 1000),
  );
  return seconds < 60
    ? `${seconds}s`
    : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export function label(value: string): string {
  return value.replaceAll("_", " ").replaceAll(".", " · ");
}
