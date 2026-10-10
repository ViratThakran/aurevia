"use client";

import { useState } from "react";

import { Icon, type IconName } from "@/components/icons";
import { PageHeader, cx } from "@/components/ui";
import { ACCENTS, useAccent } from "@/lib/accent";
import { useSession } from "@/lib/session";

type Tab = "profile" | "appearance";

const TABS: { key: Tab; label: string; icon: IconName }[] = [
  { key: "profile", label: "Profile", icon: "team" },
  { key: "appearance", label: "Appearance", icon: "grid" },
];

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border py-3 last:border-0">
      <span className="text-sm text-muted">{label}</span>
      <span className="text-sm font-medium">{value}</span>
    </div>
  );
}

export default function SettingsPage() {
  const { me } = useSession();
  const [tab, setTab] = useState<Tab>("appearance");
  const [accent, setAccent] = useAccent();

  return (
    <>
      <PageHeader
        title="Settings"
        description="Your profile and how Aurevia looks."
      />
      <div className="grid gap-4 md:grid-cols-[220px_1fr]">
        <nav className="surface-card rise-in h-fit p-2">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={cx(
                "flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm transition duration-300",
                tab === t.key
                  ? "bg-accent-soft font-medium text-accent"
                  : "text-muted hover:bg-background hover:text-foreground",
              )}
            >
              <Icon name={t.icon} size={16} />
              {t.label}
            </button>
          ))}
        </nav>

        <section
          className="surface-card rise-in p-6"
          style={{ "--i": 1 } as React.CSSProperties}
        >
          {tab === "appearance" ? (
            <>
              <h2 className="text-lg font-semibold tracking-tight">
                Appearance
              </h2>
              <p className="mt-1 text-sm text-muted">
                The accent re-tints the whole workspace and is remembered on
                this device.
              </p>
              <div className="mt-6 text-[11px] font-medium tracking-wider text-muted uppercase">
                Accent
              </div>
              <div
                className="mt-3 flex flex-wrap gap-2"
                role="radiogroup"
                aria-label="Accent"
              >
                {ACCENTS.map((a) => (
                  <button
                    key={a.key}
                    type="button"
                    role="radio"
                    aria-checked={accent === a.key}
                    onClick={() => setAccent(a.key)}
                    className={cx(
                      "inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-sm transition duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] hover:-translate-y-px",
                      accent === a.key
                        ? "border-accent bg-surface font-medium ring-4 ring-accent/10"
                        : "border-border bg-background text-muted hover:text-foreground",
                    )}
                  >
                    <span
                      className="h-5 w-5 rounded-md"
                      style={{ background: a.swatch }}
                    />
                    {a.label}
                  </button>
                ))}
              </div>
              <p className="mt-6 text-xs text-muted">
                Light or dark follows your device setting.
              </p>
            </>
          ) : (
            <>
              <h2 className="text-lg font-semibold tracking-tight">Profile</h2>
              <p className="mt-1 text-sm text-muted">
                Who you are signed in as.
              </p>
              <div className="mt-4">
                <Row label="Name" value={me?.full_name || "—"} />
                <Row label="Email" value={me?.email ?? "—"} />
                <Row label="Role" value={me?.role ?? "—"} />
                <Row label="Workspace" value={me?.tenant.name ?? "—"} />
              </div>
            </>
          )}
        </section>
      </div>
    </>
  );
}
