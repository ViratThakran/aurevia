"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { Button, Loading, cx } from "@/components/ui";
import { useSession, type Permission } from "@/lib/session";

interface NavItem {
  href: string;
  label: string;
  permission?: Permission;
  platformAdmin?: boolean;
}

const NAV: NavItem[] = [
  { href: "/", label: "Overview" },
  { href: "/agent", label: "Agent" },
  { href: "/test-call", label: "Test call", permission: "calls.place" },
  { href: "/leads", label: "Leads" },
  { href: "/campaigns", label: "Campaigns" },
  { href: "/calls", label: "Calls" },
  { href: "/activity", label: "Meetings & tasks" },
  { href: "/usage", label: "Usage", permission: "analytics.read" },
  { href: "/compliance", label: "Compliance" },
  { href: "/team", label: "Team" },
  { href: "/audit", label: "Audit log", permission: "audit.read" },
  { href: "/admin", label: "Platform admin", platformAdmin: true },
];

/** Signed-in layout. UI permissions only tidy the menu; the API enforces every rule. */
export function AppShell({ children }: { children: ReactNode }) {
  const { status, me, can, logout } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

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

  const items = NAV.filter(
    (item) =>
      (!item.permission || can(item.permission)) && (!item.platformAdmin || me.is_platform_admin),
  );
  const active = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

  const nav = (
    <nav className="space-y-0.5">
      {items.map((item) => (
        <Link
          key={item.href}
          href={item.href}
          className={cx(
            "block rounded-md px-3 py-2 text-sm",
            active(item.href)
              ? "bg-accent/10 font-medium text-accent"
              : "text-muted hover:bg-background hover:text-foreground",
          )}
        >
          {item.label}
        </Link>
      ))}
    </nav>
  );

  return (
    <div className="min-h-screen md:flex">
      <aside className="hidden w-60 shrink-0 border-r border-border bg-surface md:flex md:flex-col">
        <div className="px-5 py-5">
          <div className="text-base font-semibold tracking-tight">Aurevia</div>
          <div className="mt-0.5 truncate text-xs text-muted">{me.tenant.name}</div>
        </div>
        <div className="flex-1 overflow-y-auto px-3">{nav}</div>
        <div className="border-t border-border px-5 py-4">
          <div className="truncate text-sm">{me.full_name || me.email}</div>
          <div className="mb-2 text-xs text-muted capitalize">{me.role}</div>
          <Button variant="secondary" className="w-full" onClick={() => void logout()}>
            Sign out
          </Button>
        </div>
      </aside>

      <header className="flex items-center justify-between border-b border-border bg-surface px-4 py-3 md:hidden">
        <div>
          <div className="font-semibold">Aurevia</div>
          <div className="text-xs text-muted">{me.tenant.name}</div>
        </div>
        <Button variant="secondary" onClick={() => setMenuOpen(!menuOpen)} aria-expanded={menuOpen}>
          Menu
        </Button>
      </header>
      {menuOpen ? (
        <div className="border-b border-border bg-surface px-3 py-3 md:hidden">
          {nav}
          <Button variant="secondary" className="mt-3 w-full" onClick={() => void logout()}>
            Sign out
          </Button>
        </div>
      ) : null}

      <main className="min-w-0 flex-1 px-4 py-6 md:px-8 md:py-8">
        <div className="mx-auto max-w-6xl">{children}</div>
      </main>
    </div>
  );
}
