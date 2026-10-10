"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import { Icon, type IconName } from "@/components/icons";
import { Button, Loading, cx } from "@/components/ui";
import type { Schemas } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useSession, type Permission } from "@/lib/session";

interface NavItem {
  href: string;
  label: string;
  icon: IconName;
  permission?: Permission;
  platformAdmin?: boolean;
  badge?: "handoffs";
}

const MENU: NavItem[] = [
  { href: "/", label: "Overview", icon: "grid" },
  { href: "/agent", label: "Agent", icon: "bot" },
  {
    href: "/test-call",
    label: "Test call",
    icon: "mic",
    permission: "calls.place",
  },
  { href: "/leads", label: "Leads", icon: "users" },
  { href: "/campaigns", label: "Campaigns", icon: "megaphone" },
  { href: "/calls", label: "Calls", icon: "list" },
  {
    href: "/activity",
    label: "Meetings & tasks",
    icon: "calendar",
    badge: "handoffs",
  },
  {
    href: "/usage",
    label: "Usage",
    icon: "chart",
    permission: "analytics.read",
  },
];

const GENERAL: NavItem[] = [
  { href: "/compliance", label: "Compliance", icon: "shield" },
  { href: "/team", label: "Team", icon: "team" },
  {
    href: "/audit",
    label: "Audit log",
    icon: "file",
    permission: "audit.read",
  },
  { href: "/settings", label: "Settings", icon: "settings" },
  {
    href: "/admin",
    label: "Platform admin",
    icon: "star",
    platformAdmin: true,
  },
];

function initials(name: string): string {
  const parts = name
    .replace(/@.*/, "")
    .split(/[\s._-]+/)
    .filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

/** Signed-in layout. UI permissions only tidy the menu; the API enforces every rule. */
export function AppShell({ children }: { children: ReactNode }) {
  const { status, me, can, logout } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const [search, setSearch] = useState("");
  const handoffs = useApi<Schemas["HandoffItem"][]>(
    status === "ready" ? "/handoffs" : null,
    {
      status: "open",
      limit: 50,
    },
  );

  useEffect(() => {
    if (status === "anonymous") router.replace("/login");
  }, [status, router]);
  useEffect(() => setMenuOpen(false), [pathname]);

  if (status !== "ready" || !me) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <Loading />
      </main>
    );
  }

  const visible = (item: NavItem) =>
    (!item.permission || can(item.permission)) &&
    (!item.platformAdmin || me.is_platform_admin);
  const active = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);
  const openHandoffs = handoffs.data?.length ?? 0;
  const displayName = me.full_name || me.email;

  const onSearch = (event: FormEvent) => {
    event.preventDefault();
    const q = search.trim();
    router.push(q ? `/leads?q=${encodeURIComponent(q)}` : "/leads");
  };

  const navGroup = (title: string, items: NavItem[]) => (
    <div>
      <div className="px-3 pb-2 text-[11px] font-medium tracking-wider text-muted uppercase">
        {title}
      </div>
      <nav className="space-y-0.5">
        {items.filter(visible).map((item) => {
          const on = active(item.href);
          const count = item.badge === "handoffs" ? openHandoffs : 0;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cx(
                "relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]",
                on
                  ? "font-medium text-foreground"
                  : "text-muted hover:translate-x-0.5 hover:text-foreground",
              )}
            >
              {on ? (
                <span className="absolute top-1/2 -left-3 h-6 w-1 -translate-y-1/2 rounded-r-full bg-accent" />
              ) : null}
              <Icon
                name={item.icon}
                className={on ? "text-accent" : undefined}
              />
              <span className="flex-1">{item.label}</span>
              {count > 0 ? (
                <span className="rounded-md bg-accent-strong px-1.5 py-0.5 text-[10px] font-semibold text-white tabular-nums">
                  {count}
                </span>
              ) : null}
            </Link>
          );
        })}
      </nav>
    </div>
  );

  const sidebarBody = (
    <>
      <div className="flex-1 space-y-6 overflow-y-auto px-3 py-2">
        {navGroup("Menu", MENU)}
        {navGroup("General", GENERAL)}
        <button
          type="button"
          onClick={() => void logout()}
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted transition hover:translate-x-0.5 hover:text-foreground"
        >
          <Icon name="logout" />
          Sign out
        </button>
      </div>
      {can("calls.place") ? (
        <div className="contour m-3 rounded-2xl p-4 text-ink-foreground">
          <span className="grid h-7 w-7 place-items-center rounded-full bg-white/10">
            <Icon name="mic" size={14} />
          </span>
          <div className="mt-3 text-base leading-tight font-semibold">
            Talk to your agent
          </div>
          <div className="mt-1 text-xs opacity-60">
            Hear how it sounds before it calls anyone.
          </div>
          <Link
            href="/test-call"
            className="mt-4 block rounded-lg bg-accent-strong py-2 text-center text-sm font-medium text-white transition hover:-translate-y-px hover:brightness-110"
          >
            Start a test call
          </Link>
        </div>
      ) : null}
    </>
  );

  return (
    <div className="min-h-screen bg-frame p-0 md:p-4">
      <div className="mx-auto flex min-h-screen max-w-[1600px] gap-3 bg-background md:min-h-[calc(100vh-2rem)] md:rounded-[22px] md:p-3">
        <aside className="hidden w-60 shrink-0 flex-col rounded-2xl bg-panel md:flex">
          <Link href="/" className="flex items-center gap-2.5 px-5 pt-5 pb-4">
            <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent-strong text-white">
              <Icon name="leaf" size={16} />
            </span>
            <span className="min-w-0">
              <span className="block text-base font-semibold tracking-tight">
                Aurevia
              </span>
              <span className="block truncate text-[11px] text-muted">
                {me.tenant.name}
              </span>
            </span>
          </Link>
          {sidebarBody}
        </aside>

        <div className="flex min-w-0 flex-1 flex-col gap-3">
          <header className="flex items-center gap-3 px-4 pt-3 md:rounded-2xl md:bg-panel md:px-4 md:py-2.5">
            <Button
              variant="secondary"
              className="md:hidden"
              onClick={() => setMenuOpen(!menuOpen)}
              aria-expanded={menuOpen}
            >
              Menu
            </Button>
            <form onSubmit={onSearch} className="relative max-w-sm flex-1">
              <Icon
                name="search"
                size={16}
                className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted"
              />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search leads"
                aria-label="Search leads"
                className="w-full rounded-xl border border-border bg-surface py-2 pr-3 pl-9 text-sm outline-none transition focus:border-accent focus:ring-4 focus:ring-accent/10"
              />
            </form>
            <div className="ml-auto flex items-center gap-2">
              <Link
                href="/activity"
                aria-label={`${openHandoffs} leads need a person`}
                className="relative grid h-9 w-9 place-items-center rounded-full border border-border bg-surface text-muted transition hover:-translate-y-px hover:text-foreground"
              >
                <Icon name="bell" size={16} />
                {openHandoffs > 0 ? (
                  <span className="absolute top-1.5 right-2 h-2 w-2 rounded-full bg-danger ring-2 ring-surface" />
                ) : null}
              </Link>
              <div className="flex items-center gap-2.5 pl-1">
                <span className="grid h-9 w-9 place-items-center rounded-full bg-accent-soft text-xs font-semibold text-accent">
                  {initials(displayName)}
                </span>
                <span className="hidden min-w-0 sm:block">
                  <span className="block max-w-40 truncate text-sm font-medium">
                    {displayName}
                  </span>
                  <span className="block max-w-40 truncate text-[11px] text-muted capitalize">
                    {me.full_name ? me.email : me.role}
                  </span>
                </span>
              </div>
            </div>
          </header>

          {menuOpen ? (
            <div className="mx-4 flex flex-col rounded-2xl border border-border bg-panel md:hidden">
              {sidebarBody}
            </div>
          ) : null}

          <main className="min-w-0 flex-1 px-4 pb-8 md:rounded-2xl md:bg-panel md:px-7 md:py-6">
            <div className="mx-auto max-w-7xl">{children}</div>
          </main>
        </div>
      </div>
    </div>
  );
}
