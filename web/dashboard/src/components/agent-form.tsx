"use client";

import { useEffect, useState } from "react";

import { Alert, Button, Field, Input, Loading, Textarea } from "@/components/ui";
import { api, type Schemas } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";

type Agent = Schemas["AgentResponse"];
type AgentUpdate = Schemas["AgentUpdate"];

function toForm(agent: Agent): AgentUpdate & { questions: string } {
  return {
    name: agent.name,
    company_name: agent.company_name,
    company_description: agent.company_description,
    objective: agent.objective,
    greeting: agent.greeting,
    language: agent.language,
    voice: agent.voice ?? null,
    personality: agent.personality ?? "",
    qualification_questions: agent.qualification_questions ?? [],
    objection_guidance: agent.objection_guidance ?? "",
    escalation_guidance: agent.escalation_guidance ?? "",
    questions: (agent.qualification_questions ?? []).join("\n"),
  };
}

/** The tenant's agent. `compact` shows only what onboarding needs. */
export function AgentForm({
  compact = false,
  readOnly = false,
  onSaved,
  submitLabel = "Save",
}: {
  compact?: boolean;
  readOnly?: boolean;
  onSaved?: (agent: Agent) => void;
  submitLabel?: string;
}) {
  const { data, error: loadError, loading } = useApi<Agent>("/agents/default");
  const [form, setForm] = useState<ReturnType<typeof toForm> | null>(null);
  const [saved, setSaved] = useState(false);
  const { pending, error, run } = useAction();

  useEffect(() => {
    if (data) setForm(toForm(data));
  }, [data]);

  if (loading || !form) return loadError ? <Alert>{loadError}</Alert> : <Loading />;

  const set =
    (key: keyof typeof form) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      setSaved(false);
      setForm({ ...form, [key]: e.target.value });
    };

  async function save() {
    if (!form) return;
    const { questions, ...body } = form;
    const agent = await run(() =>
      api<Agent>("/agents/default", {
        method: "PUT",
        body: {
          ...body,
          voice: body.voice || null,
          qualification_questions: questions
            .split("\n")
            .map((q) => q.trim())
            .filter(Boolean),
        },
      }),
    );
    if (agent) {
      setSaved(true);
      setForm(toForm(agent));
      onSaved?.(agent);
    }
  }

  return (
    <form
      className="space-y-5"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <fieldset disabled={readOnly} className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Company name">
            <Input required value={form.company_name} onChange={set("company_name")} />
          </Field>
          <Field label="Agent name" hint="What the agent calls itself.">
            <Input required value={form.name} onChange={set("name")} />
          </Field>
        </div>
        <Field
          label="About your company"
          hint="Products, prices, who you serve. The agent only says what is written here."
        >
          <Textarea
            required
            rows={6}
            value={form.company_description}
            onChange={set("company_description")}
          />
        </Field>
        <Field label="Goal of each call" hint="E.g. book a 20-minute meeting with a specialist.">
          <Textarea required rows={2} value={form.objective} onChange={set("objective")} />
        </Field>
        <Field
          label="Opening line"
          hint="Must say that it is an AI, the agent's name and your company's name (required for phone calls)."
        >
          <Textarea required rows={2} value={form.greeting} onChange={set("greeting")} />
        </Field>

        {compact ? null : (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Language" hint="E.g. en-IN, hi-IN.">
                <Input required value={form.language} onChange={set("language")} />
              </Field>
              <Field label="Voice id (optional)" hint="Leave empty for the default voice.">
                <Input value={form.voice ?? ""} onChange={set("voice")} />
              </Field>
            </div>
            <Field label="Personality" hint="Short, e.g. warm, concise, never pushy.">
              <Input value={form.personality ?? ""} onChange={set("personality")} />
            </Field>
            <Field label="What to find out" hint="One question per line, up to 10.">
              <Textarea rows={4} value={form.questions} onChange={set("questions")} />
            </Field>
            <Field label="Handling objections">
              <Textarea rows={4} value={form.objection_guidance ?? ""} onChange={set("objection_guidance")} />
            </Field>
            <Field label="When to bring in a colleague">
              <Textarea rows={3} value={form.escalation_guidance ?? ""} onChange={set("escalation_guidance")} />
            </Field>
          </>
        )}
      </fieldset>
      <Alert>{error}</Alert>
      {saved ? <Alert tone="good">Saved.</Alert> : null}
      {readOnly ? (
        <p className="text-sm text-muted">You can view the agent; changing it needs the agents permission.</p>
      ) : (
        <Button type="submit" pending={pending}>
          {submitLabel}
        </Button>
      )}
    </form>
  );
}
