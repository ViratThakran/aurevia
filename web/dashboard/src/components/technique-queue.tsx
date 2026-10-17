"use client";

import { useState, type FormEvent } from "react";

import { Alert, Badge, Button, Card, Empty, Field, Input, Loading, Select, StatusBadge, label as readable } from "@/components/ui";
import { api, type Schemas } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";

type Technique = Schemas["TechniqueOut"];
type Status = "proposed" | "approved" | "rejected";

const STAGES = ["", "opening", "discovery", "qualification", "pitch", "objection", "next_step", "follow_up"];

interface Draft {
  stage: string;
  situation: string;
  says: string;
  tone: string;
  goal: string;
  conditions: string;
}

const EMPTY: Draft = { stage: "", situation: "", says: "", tone: "", goal: "", conditions: "" };

function body(d: Draft) {
  return { ...d, stage: d.stage || null };
}

/** Technique review queue (WP-12.6): policy check first, then a person approves, edits or rejects. */
export function TechniqueQueue() {
  const [status, setStatus] = useState<Status>("proposed");
  const techniques = useApi<Technique[]>("/learning/techniques", { status });
  const drafts = useApi<Schemas["VersionOut"][]>("/playbooks");
  const [adding, setAdding] = useState(false);
  const { run, pending, error } = useAction();
  const draftVersions = (drafts.data ?? []).filter((v) => v.status === "draft");

  const act = async (fn: () => Promise<unknown>) => {
    if ((await run(fn)) !== null) await techniques.reload();
  };

  return (
    <Card
      title="Technique review queue"
      actions={
        <>
          <Select className="w-auto" value={status} onChange={(e) => setStatus(e.target.value as Status)} aria-label="Show">
            <option value="proposed">Waiting for review</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
          </Select>
          <Button variant="secondary" onClick={() => setAdding(!adding)}>{adding ? "Close" : "Add a technique"}</Button>
        </>
      }
    >
      <Alert>{error}</Alert>
      {adding ? (
        <TechniqueForm
          initial={EMPTY}
          submitLabel="Add to the queue"
          pending={pending}
          onSubmit={(d) =>
            act(async () => {
              await api<Technique>("/learning/techniques", { method: "POST", body: body(d) });
              setAdding(false);
            })
          }
        />
      ) : null}
      {techniques.data ? (
        techniques.data.length ? (
          <ul className="divide-y divide-border">
            {techniques.data.map((t) => (
              <TechniqueRow key={t.id} t={t} pending={pending} drafts={draftVersions} act={act} />
            ))}
          </ul>
        ) : (
          <Empty>Nothing here.</Empty>
        )
      ) : techniques.error ? (
        <Alert>{techniques.error}</Alert>
      ) : (
        <Loading />
      )}
    </Card>
  );
}

function TechniqueRow({
  t,
  pending,
  drafts,
  act,
}: {
  t: Technique;
  pending: boolean;
  drafts: Schemas["VersionOut"][];
  act: (fn: () => Promise<unknown>) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [version, setVersion] = useState("");
  const review = (status: "approved" | "rejected") =>
    act(() => api(`/learning/techniques/${t.id}/review`, { method: "POST", body: { status } }));
  const seen = t.source_ids.length;

  return (
    <li className="space-y-2 py-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        {t.stage ? <Badge>{readable(t.stage)}</Badge> : <Badge>any stage</Badge>}
        <StatusBadge value={t.status} />
        <span className="text-xs text-muted">
          {t.proposed_by === "model" ? "from the model" : "added by a person"} · seen in {seen} source{seen === 1 ? "" : "s"} ({t.booked_count} booked, {t.unbooked_count} not booked)
        </span>
      </div>
      <p><span className="text-muted">When:</span> {t.situation}</p>
      <p><span className="text-muted">Says:</span> &ldquo;{t.says}&rdquo;</p>
      <p className="text-muted">Tone: {t.tone} · Goal: {t.goal}{t.conditions ? ` · Works when: ${t.conditions}` : ""}</p>
      {t.excerpt ? <p className="border-l-2 border-border pl-3 text-xs text-muted">{t.excerpt}</p> : null}
      {t.policy_reasons.length ? (
        <div className="flex flex-wrap gap-2">
          {t.policy_reasons.map((reason) => (
            <Badge key={reason} tone="bad">{reason}</Badge>
          ))}
        </div>
      ) : null}
      {t.playbook_entry_id ? (
        <p className="text-xs text-success">Copied into a draft playbook.</p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {t.status !== "approved" ? (
            <Button variant="secondary" pending={pending} disabled={t.policy_flags.length > 0} onClick={() => review("approved")}>
              Approve
            </Button>
          ) : null}
          <Button variant="secondary" pending={pending} onClick={() => setEditing(!editing)}>
            {editing ? "Cancel edit" : "Edit"}
          </Button>
          {t.status !== "rejected" ? (
            <Button variant="secondary" pending={pending} onClick={() => review("rejected")}>Reject</Button>
          ) : null}
          {t.status === "approved" && drafts.length ? (
            <>
              <Select value={version} onChange={(e) => setVersion(e.target.value)} aria-label="Draft playbook">
                <option value="">Choose a draft playbook</option>
                {drafts.map((v) => (
                  <option key={v.id} value={v.id}>Draft version {v.version}</option>
                ))}
              </Select>
              <Button
                variant="secondary"
                pending={pending}
                disabled={!version}
                onClick={() =>
                  act(() => api(`/learning/techniques/${t.id}/to-playbook`, { method: "POST", body: { version_id: version } }))
                }
              >
                Add to playbook
              </Button>
            </>
          ) : null}
        </div>
      )}
      {editing ? (
        <TechniqueForm
          initial={{ stage: t.stage ?? "", situation: t.situation, says: t.says, tone: t.tone, goal: t.goal, conditions: t.conditions }}
          submitLabel="Save and check again"
          pending={pending}
          onSubmit={(d) =>
            act(async () => {
              await api(`/learning/techniques/${t.id}`, { method: "PUT", body: body(d) });
              setEditing(false);
            })
          }
        />
      ) : null}
    </li>
  );
}

function TechniqueForm({
  initial,
  submitLabel,
  pending,
  onSubmit,
}: {
  initial: Draft;
  submitLabel: string;
  pending: boolean;
  onSubmit: (d: Draft) => Promise<void>;
}) {
  const [d, setD] = useState(initial);
  const set = (key: keyof Draft) => (e: { target: { value: string } }) => setD({ ...d, [key]: e.target.value });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    void onSubmit(d);
  };
  return (
    <form onSubmit={submit} className="my-4 grid gap-3 sm:grid-cols-2">
      <Field label="Stage">
        <Select value={d.stage} onChange={set("stage")}>
          {STAGES.map((s) => (
            <option key={s} value={s}>{s ? readable(s) : "Any stage"}</option>
          ))}
        </Select>
      </Field>
      <Field label="Tone">
        <Input required maxLength={100} value={d.tone} onChange={set("tone")} />
      </Field>
      <Field label="Situation">
        <Input required maxLength={300} value={d.situation} onChange={set("situation")} />
      </Field>
      <Field label="What the agent says">
        <Input required maxLength={500} value={d.says} onChange={set("says")} />
      </Field>
      <Field label="Goal">
        <Input required maxLength={200} value={d.goal} onChange={set("goal")} />
      </Field>
      <Field label="Works when (optional)">
        <Input maxLength={300} value={d.conditions} onChange={set("conditions")} />
      </Field>
      <div className="sm:col-span-2">
        <Button type="submit" pending={pending}>{submitLabel}</Button>
      </div>
    </form>
  );
}
