"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, type ReactNode } from "react";

import { useSession } from "@/lib/session";

/** Centered card for the signed-out pages; sends signed-in users to the app. */
export function AuthCard({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const { status } = useSession();
  const router = useRouter();
  // Only for someone who arrives already signed in; after signing in here, the page itself
  // decides where to go (e.g. onboarding after sign-up).
  const firstStatus = useRef<string | null>(null);
  useEffect(() => {
    if (status === "loading") return;
    firstStatus.current ??= status;
    if (firstStatus.current === "ready") router.replace("/");
  }, [status, router]);

  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm">
        <Link href="/" className="mb-8 block text-center text-lg font-semibold tracking-tight">
          Aurevia
        </Link>
        <div className="rounded-lg border border-border bg-surface p-6 shadow-sm">
          <h1 className="text-lg font-semibold">{title}</h1>
          {subtitle ? <p className="mt-1 text-sm text-muted">{subtitle}</p> : null}
          <div className="mt-6">{children}</div>
        </div>
        {footer ? <div className="mt-4 text-center text-sm text-muted">{footer}</div> : null}
      </div>
    </main>
  );
}
