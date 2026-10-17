/** Label kinds and value shapes for the learning review screen (WP-12.4). Mirrors the API. */

export type LabelKind =
  | "stage"
  | "objection"
  | "outcome"
  | "qualification"
  | "next_step"
  | "talk_ratio"
  | "question_count";

interface KindSpec {
  label: string;
  /** Where the label sits: on a line, on the whole call, or either. */
  place: "line" | "call" | "either";
  /** The value field and its choices (empty: a number). */
  field: string;
  choices: string[];
}

export const KINDS: Record<LabelKind, KindSpec> = {
  stage: {
    label: "Stage starts here",
    place: "line",
    field: "stage",
    choices: ["opening", "discovery", "qualification", "pitch", "objection", "next_step", "follow_up"],
  },
  objection: {
    label: "Objection",
    place: "line",
    field: "category",
    choices: ["price", "timing", "authority", "need", "other"],
  },
  outcome: {
    label: "Outcome",
    place: "call",
    field: "result",
    choices: ["qualified", "disqualified", "educate", "realign"],
  },
  qualification: {
    label: "Qualification fact",
    place: "either",
    field: "fact",
    choices: ["budget", "authority", "need", "timeline"],
  },
  next_step: {
    label: "Next step",
    place: "call",
    field: "step",
    choices: ["meeting", "call_back", "stay_in_touch", "referral", "email", "none"],
  },
  talk_ratio: { label: "Expert talk share (0 to 1)", place: "call", field: "expert_share", choices: [] },
  question_count: { label: "Questions asked", place: "call", field: "count", choices: [] },
};

/** The value to send for a kind, from the form's choice (or number) and optional note. */
export function labelValue(kind: LabelKind, choice: string, note = ""): Record<string, unknown> {
  const spec = KINDS[kind];
  if (!spec.choices.length) return { [spec.field]: Number(choice) };
  const value: Record<string, unknown> = { [spec.field]: choice };
  if (kind === "qualification" && note.trim()) value.note = note.trim();
  return value;
}

/** A short readable text for a stored label, e.g. "Objection: price". */
export function describeLabel(kind: string, value: Record<string, unknown>): string {
  const spec = KINDS[kind as LabelKind];
  if (!spec) return kind;
  const main = String(value[spec.field] ?? "").replaceAll("_", " ");
  const note = typeof value.note === "string" && value.note ? ` (${value.note})` : "";
  return `${spec.label}: ${main}${note}`;
}
