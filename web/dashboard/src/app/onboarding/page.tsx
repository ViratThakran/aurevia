"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AgentForm } from "@/components/agent-form";
import { TestCall } from "@/components/test-call";
import { Button, Card, Loading, cx } from "@/components/ui";
import { useSession } from "@/lib/session";

const STEPS = ["Your agent", "Test call", "Next steps"] as const;

/** Signup -> first call without help (the Phase 8 gate): set up the agent, then talk to it. */
export default function OnboardingPage() {
  const { status, me, can } = useSession();
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [called, setCalled] = useState(false);

  useEffect(() => {
    if (status === "anonymous") router.replace("/login");
  }, [status, router]);
  if (status !== "ready" || !me) return <Loading />;

  return (
    <main className="mx-auto max-w-3xl px-4 py-10">
      <div className="mb-8">
        <div className="text-sm font-semibold tracking-tight text-muted">Aurevia</div>
        <h1 className="mt-1 text-2xl font-semibold">Welcome, {me.tenant.name}</h1>
        <p className="mt-1 text-sm text-muted">Three short steps to hear your AI agent.</p>
      </div>

      <ol className="mb-6 flex gap-2 text-sm">
        {STEPS.map((name, i) => (
          <li
            key={name}
            className={cx(
              "flex-1 rounded-md border px-3 py-2",
              i === step ? "border-accent bg-accent/10 font-medium text-accent" : "border-border text-muted",
            )}
          >
            {i + 1}. {name}
          </li>
        ))}
      </ol>

      {step === 0 ? (
        <Card title="Tell your agent about your company">
          <AgentForm
            compact
            readOnly={!can("agents.manage")}
            submitLabel="Save and continue"
            onSaved={() => setStep(1)}
          />
          {!can("agents.manage") ? (
            <Button className="mt-4" onClick={() => setStep(1)}>
              Continue
            </Button>
          ) : null}
        </Card>
      ) : null}

      {step === 1 ? (
        <Card title="Talk to your agent">
          <p className="mb-4 text-sm text-muted">
            Play a prospect: ask what it offers, push back on price, ask if it is a bot. Calls
            happen in your browser; phone calls come later.
          </p>
          <TestCall onFinished={() => setCalled(true)} />
          <div className="mt-6 flex justify-between">
            <Button variant="ghost" onClick={() => setStep(0)}>
              Back
            </Button>
            <Button variant={called ? "primary" : "secondary"} onClick={() => setStep(2)}>
              {called ? "Continue" : "Skip for now"}
            </Button>
          </div>
        </Card>
      ) : null}

      {step === 2 ? (
        <Card title="You are set up">
          <ul className="list-disc space-y-2 pl-5 text-sm">
            <li>Refine the agent: personality, questions to ask, objection handling.</li>
            <li>Add leads by hand or import a CSV, then group them in a campaign.</li>
            <li>Invite your team and choose what each person may do.</li>
            <li>
              Phone calls: register your caller id and your own test phone under Compliance.
              Calls to real prospects open once your policy is reviewed by counsel.
            </li>
          </ul>
          <Button className="mt-6" onClick={() => router.replace("/")}>
            Go to the dashboard
          </Button>
        </Card>
      ) : null}
    </main>
  );
}
