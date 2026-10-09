"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { AuthCard } from "@/components/auth-card";
import { Alert, Button, Field, Input } from "@/components/ui";
import { useAction } from "@/lib/hooks";
import { useSession } from "@/lib/session";

export default function SignupPage() {
  const { signup } = useSession();
  const router = useRouter();
  const [form, setForm] = useState({ full_name: "", email: "", password: "", tenant_name: "" });
  const { pending, error, run } = useAction();
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [key]: e.target.value });

  return (
    <AuthCard
      title="Create your workspace"
      subtitle="Set up an AI agent and hear it on a test call in a few minutes."
      footer={
        <>
          Already have an account? <Link className="text-accent" href="/login">Sign in</Link>
        </>
      }
    >
      <form
        className="space-y-4"
        onSubmit={async (e) => {
          e.preventDefault();
          const done = await run(() =>
            signup({ ...form, full_name: form.full_name || null }).then(() => true),
          );
          if (done) router.replace("/onboarding");
        }}
      >
        <Field label="Company name">
          <Input required minLength={2} value={form.tenant_name} onChange={set("tenant_name")} />
        </Field>
        <Field label="Your name">
          <Input autoComplete="name" value={form.full_name} onChange={set("full_name")} />
        </Field>
        <Field label="Work email">
          <Input type="email" autoComplete="email" required value={form.email} onChange={set("email")} />
        </Field>
        <Field label="Password" hint="At least 12 characters.">
          <Input
            type="password"
            autoComplete="new-password"
            required
            minLength={12}
            value={form.password}
            onChange={set("password")}
          />
        </Field>
        <Alert>{error}</Alert>
        <Button type="submit" className="w-full" pending={pending}>
          Create workspace
        </Button>
      </form>
    </AuthCard>
  );
}
