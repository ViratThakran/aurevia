"use client";

import { useState, type FormEvent } from "react";

import {
  Alert,
  Badge,
  Button,
  Card,
  Empty,
  Field,
  Input,
  Loading,
  PageHeader,
  Select,
  Stat,
  StatusBadge,
  Table,
  formatDate,
  label as readable,
} from "@/components/ui";
import { api, type Schemas } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";
import { KINDS, describeLabel, labelValue, type LabelKind } from "@/lib/labels";

type Label = Schemas["LabelOut"];

/** Learning review (WP-12.4): redacted expert-call transcripts and their labels. */
export default function LearningPage() {
  const sources = useApi<Schemas["SourceOut"][]>("/learning/sources");
  const accuracy = useApi<Schemas["LabelAccuracyOut"]>("/learning/labels/accuracy");
  const [selected, setSelected] = useState<string | null>(null);

  return (
    <>
      <PageHeader
        title="Learning"
        description="Expert-call transcripts, redacted before they were stored, and their labels. The model proposes labels; a person checks them."
      />
      {sources.error ? (
        <Alert>
          {sources.error}. If this says not found, learning is switched off on the server
          (AUREVIA_LEARNING_ENABLED).
        </Alert>
      ) : null}
      {accuracy.data ? (
        <div className="mb-6 grid gap-4 sm:grid-cols-3">
          <Stat label="Model labels" value={accuracy.data.model_labels} hint={`${accuracy.data.waiting} waiting for a check`} />
          <Stat
            label="Checked"
            value={accuracy.data.approved + accuracy.data.rejected}
            hint={`${accuracy.data.approved} right, ${accuracy.data.rejected} wrong`}
          />
          <Stat
            label="Label accuracy"
            value={accuracy.data.accuracy === null ? "—" : `${Math.round(accuracy.data.accuracy * 100)}%`}
            hint="Share of checked model labels a person approved"
          />
        </div>
      ) : null}
      <Card title="Sources">
        {sources.data ? (
          <Table
            head={["Title", "Type", "Language", "Outcome", "Lines", "Imported", ""]}
            rows={sources.data.map((s) => [
              s.title,
              readable(s.source_type),
              s.language,
              readable(s.outcome),
              s.line_count,
              formatDate(s.created_at),
              <Button key="o" variant="secondary" disabled={selected === s.id} onClick={() => setSelected(s.id)}>
                {selected === s.id ? "Showing below" : "Review"}
              </Button>,
            ])}
            empty="No sources imported yet."
          />
        ) : sources.error ? null : (
          <Loading />
        )}
      </Card>
      {selected ? <SourceReview key={selected} id={selected} onChanged={accuracy.reload} /> : null}
    </>
  );
}

function SourceReview({ id, onChanged }: { id: string; onChanged: () => Promise<void> }) {
  const source = useApi<Schemas["SourceDetailOut"]>(`/learning/sources/${id}`);
  const labels = useApi<Label[]>(`/learning/sources/${id}/labels`);
  const { run, pending, error } = useAction();

  const review = async (labelId: string, status: "approved" | "rejected") => {
    const done = await run(() =>
      api<Label>(`/learning/labels/${labelId}/review`, { method: "POST", body: { status } }),
    );
    if (done) {
      await labels.reload();
      await onChanged();
    }
  };

  const chip = (l: Label) => (
    <span key={l.id} className="inline-flex flex-wrap items-center gap-1.5">
      <Badge tone={l.review_status === "approved" ? "good" : l.review_status === "rejected" ? "bad" : "warn"}>
        {describeLabel(l.kind, l.value)}
      </Badge>
      <span className="text-xs text-muted">{l.proposed_by === "model" ? "model" : "person"}</span>
      {l.review_status === "proposed" ? (
        <>
          <Button variant="secondary" pending={pending} onClick={() => review(l.id, "approved")}>Right</Button>
          <Button variant="secondary" pending={pending} onClick={() => review(l.id, "rejected")}>Wrong</Button>
        </>
      ) : (
        <StatusBadge value={l.review_status} />
      )}
    </span>
  );

  if (!source.data || !labels.data) {
    return source.error || labels.error ? <Alert>{source.error ?? labels.error}</Alert> : <Loading />;
  }
  const byLine = new Map<number, Label[]>();
  for (const l of labels.data) {
    if (l.line_seq !== null) byLine.set(l.line_seq, [...(byLine.get(l.line_seq) ?? []), l]);
  }
  const callLabels = labels.data.filter((l) => l.line_seq === null);

  return (
    <div className="mt-6 space-y-6">
      <Alert>{error}</Alert>
      <Card title={`Transcript: ${source.data.title}`}>
        <ol className="space-y-3 text-sm">
          {source.data.lines.map((line) => (
            <li key={line.seq} className="space-y-1">
              <p>
                <span className="mr-2 text-xs text-muted">{line.seq}</span>
                <span className={line.speaker === "expert" ? "font-medium text-accent" : "font-medium"}>
                  {readable(line.speaker)}:
                </span>{" "}
                {line.text}
              </p>
              {byLine.get(line.seq)?.length ? (
                <div className="flex flex-wrap gap-3 pl-6">{byLine.get(line.seq)!.map(chip)}</div>
              ) : null}
            </li>
          ))}
        </ol>
      </Card>
      <Card title="Whole call">
        {callLabels.length ? <div className="flex flex-wrap gap-3">{callLabels.map(chip)}</div> : <Empty>No call labels yet.</Empty>}
      </Card>
      <AddLabel
        sourceId={id}
        lines={source.data.line_count}
        onAdded={async () => {
          await labels.reload();
        }}
      />
    </div>
  );
}

function AddLabel({ sourceId, lines, onAdded }: { sourceId: string; lines: number; onAdded: () => Promise<void> }) {
  const [kind, setKind] = useState<LabelKind>("stage");
  const [line, setLine] = useState("");
  const [choice, setChoice] = useState(KINDS.stage.choices[0]);
  const [note, setNote] = useState("");
  const { run, pending, error } = useAction();
  const spec = KINDS[kind];

  const pickKind = (next: LabelKind) => {
    setKind(next);
    setChoice(KINDS[next].choices[0] ?? "");
    if (KINDS[next].place === "call") setLine("");
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const done = await run(() =>
      api<Label>(`/learning/sources/${sourceId}/labels`, {
        method: "POST",
        body: {
          kind,
          line_seq: spec.place === "call" || line === "" ? null : Number(line),
          value: labelValue(kind, choice, note),
        },
      }),
    );
    if (done) {
      setNote("");
      await onAdded();
    }
  };

  return (
    <Card title="Add your own label">
      <form onSubmit={submit} className="grid gap-4 sm:grid-cols-4">
        <Field label="Kind">
          <Select value={kind} onChange={(e) => pickKind(e.target.value as LabelKind)}>
            {(Object.keys(KINDS) as LabelKind[]).map((k) => (
              <option key={k} value={k}>{KINDS[k].label}</option>
            ))}
          </Select>
        </Field>
        {spec.place !== "call" ? (
          <Field label="Line" hint={spec.place === "line" ? "Required" : "Optional"}>
            <Select value={line} onChange={(e) => setLine(e.target.value)}>
              <option value="">{spec.place === "line" ? "Choose a line" : "Whole call"}</option>
              {Array.from({ length: lines }, (_, i) => (
                <option key={i} value={i}>{i}</option>
              ))}
            </Select>
          </Field>
        ) : null}
        <Field label="Value">
          {spec.choices.length ? (
            <Select value={choice} onChange={(e) => setChoice(e.target.value)}>
              {spec.choices.map((c) => (
                <option key={c} value={c}>{readable(c)}</option>
              ))}
            </Select>
          ) : (
            <Input type="number" min={0} step="any" required value={choice} onChange={(e) => setChoice(e.target.value)} />
          )}
        </Field>
        {kind === "qualification" ? (
          <Field label="Note">
            <Input maxLength={200} value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
        ) : null}
        <div className="flex items-end gap-3 sm:col-span-4">
          <Button type="submit" pending={pending} disabled={spec.place === "line" && line === ""}>
            Add label
          </Button>
          <Alert>{error}</Alert>
        </div>
      </form>
    </Card>
  );
}
