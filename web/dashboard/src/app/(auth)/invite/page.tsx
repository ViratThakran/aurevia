"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { AuthCard } from "@/components/auth-card";
import { Alert, Button, Field, Input } from "@/components/ui";
import { useAction } from "@/lib/hooks";
import { useSession } from "@/lib/session";

function AcceptInvitation() {
  const token = useSearchParams().get("token") ?? "";
  const { acceptInvitation } = useSession();
  const router = useRouter();
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const { pending, error, run } = useAction();

  return (
    <AuthCard
      title="Join your team"
      subtitle="New here? Choose a password. Already have an Aurevia account? Use its password."
    >
      {!token ? (
        <Alert>This invitation link is incomplete. Ask for a new one.</Alert>
      ) : (
        <form
          className="space-y-4"
          onSubmit={async (e) => {
            e.preventDefault();
            const done = await run(() =>
              acceptInvitation(token, password, fullName).then(() => true),
            );
            if (done) router.replace("/");
          }}
        >
          <Field label="Your name">
            <Input value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </Field>
          <Field label="Password" hint="New accounts: at least 12 characters.">
            <Input
              type="password"
              required
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          <Alert>{error}</Alert>
          <Button type="submit" className="w-full" pending={pending}>
            Join
          </Button>
        </form>
      )}
    </AuthCard>
  );
}

export default function InvitePage() {
  return (
    <Suspense>
      <AcceptInvitation />
    </Suspense>
  );
}
