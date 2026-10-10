"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { AuthCard } from "@/components/auth-card";
import { Alert, Button, Field, Input } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import { useSession } from "@/lib/session";

interface TenantChoice {
  tenant_id: string;
  name: string;
}

export default function LoginPage() {
  const { login } = useSession();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [tenants, setTenants] = useState<TenantChoice[] | null>(null);
  const { pending, error, setError, run } = useAction();

  async function submit(tenantId?: string) {
    setError(null);
    try {
      await login(email, password, tenantId);
      router.replace("/");
    } catch (e) {
      if (e instanceof ApiError && e.code === "tenant_selection_required") {
        setTenants(e.details as TenantChoice[]);
        return;
      }
      await run(() => Promise.reject(e));
    }
  }

  return (
    <AuthCard
      title={tenants ? "Choose a workspace" : "Sign in"}
      subtitle={tenants ? "Your account belongs to several workspaces." : undefined}
      footer={
        <>
          New to Aurevia? <Link className="text-accent" href="/signup">Create an account</Link>
        </>
      }
    >
      {tenants ? (
        <div className="space-y-2">
          {tenants.map((t) => (
            <Button
              key={t.tenant_id}
              variant="secondary"
              className="w-full justify-start"
              pending={pending}
              onClick={() => void submit(t.tenant_id)}
            >
              {t.name}
            </Button>
          ))}
          <Alert>{error}</Alert>
        </div>
      ) : (
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <Field label="Email">
            <Input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </Field>
          <Field label="Password">
            <Input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          <Alert>{error}</Alert>
          <Button type="submit" className="w-full" pending={pending}>
            Sign in
          </Button>
        </form>
      )}
    </AuthCard>
  );
}
