import { describe, expect, it } from "vitest";

import {
  RETRYING_MESSAGE,
  RETRY_FAILED_MESSAGE,
  RETRY_UNAVAILABLE_MESSAGE,
  callScreenReducer,
  initialCallScreen,
  issueMessage,
  parseStatusEvent,
  retryableFailureId,
  type CallScreenAction,
  type CallScreenState,
} from "./voice-issues";

const run = (
  actions: CallScreenAction[],
  from: CallScreenState = initialCallScreen,
) => actions.reduce(callScreenReducer, from);

const issue = (over: Record<string, unknown> = {}) =>
  JSON.stringify({
    type: "voice_issue",
    id: "abc123",
    source: "voice",
    category: "credits_exhausted",
    retryable: true,
    text: "Forty staff, got it.",
    ...over,
  });

const failed = (raw = issue()): CallScreenAction => {
  const event = parseStatusEvent(raw);
  if (!event) throw new Error("test event did not parse");
  return { type: "status", event };
};

describe("messages", () => {
  it("uses the agreed wording for exhausted credits", () => {
    expect(
      issueMessage({ source: "voice", category: "credits_exhausted" }),
    ).toBe(
      "The voice service is out of credits. The AI generated a response, but it could not speak it. Please check your Cartesia subscription.",
    );
  });

  it.each([
    "rate_limited",
    "timeout",
    "provider_unavailable",
    "unknown",
  ] as const)("has a non-technical message for %s", (category) => {
    const text = issueMessage({ source: "voice", category });
    expect(text).toContain("could not speak it");
    expect(text).not.toMatch(
      /402|429|5\d\d|exception|traceback|api key|bearer/i,
    );
  });

  it("has a different message per category", () => {
    const categories = [
      "credits_exhausted",
      "rate_limited",
      "timeout",
      "provider_unavailable",
      "unknown",
    ] as const;
    const all = categories.map((category) =>
      issueMessage({ source: "voice", category }),
    );
    expect(new Set(all).size).toBe(all.length);
  });
});

describe("parsing worker messages", () => {
  it("accepts a well-formed failure", () => {
    expect(parseStatusEvent(issue())).toEqual({
      type: "voice_issue",
      id: "abc123",
      source: "voice",
      category: "credits_exhausted",
      retryable: true,
      text: "Forty staff, got it.",
    });
  });

  it("ignores anything unexpected instead of showing it", () => {
    expect(parseStatusEvent("not json")).toBeNull();
    expect(
      parseStatusEvent(JSON.stringify({ type: "voice_issue", id: "x" })),
    ).toBeNull();
    expect(
      parseStatusEvent(issue({ category: "402 Payment Required: sk-123" })),
    ).toBeNull();
    expect(parseStatusEvent(issue({ source: "billing" }))).toBeNull();
    expect(parseStatusEvent(issue({ id: "" }))).toBeNull();
  });

  it("never offers a retry without words to replay, or for non-voice failures", () => {
    expect(parseStatusEvent(issue({ text: null }))).toMatchObject({
      retryable: false,
    });
    expect(
      parseStatusEvent(issue({ source: "model", text: null })),
    ).toMatchObject({
      retryable: false,
    });
  });
});

describe("call screen", () => {
  const withConversation = run([
    { type: "transcript", speaker: "agent", text: "Hi, this is Aria." },
    { type: "transcript", speaker: "you", text: "We have forty staff." },
  ]);

  it("keeps the transcript and shows the generated reply as not spoken", () => {
    const state = run([failed()], withConversation);
    expect(state.lines).toEqual([
      { speaker: "agent", text: "Hi, this is Aria.", audio: "played" },
      { speaker: "you", text: "We have forty staff." },
      {
        speaker: "agent",
        text: "Forty staff, got it.",
        audio: "not_spoken",
        failureId: "abc123",
      },
    ]);
    expect(state.notice).toContain("out of credits");
    expect(state.retry).toBe("idle");
  });

  it("distinguishes spoken lines from generated-only lines", () => {
    const state = run([failed()], withConversation);
    expect(state.lines.filter((l) => l.audio === "played")).toHaveLength(1);
    expect(state.lines.filter((l) => l.audio === "not_spoken")).toHaveLength(1);
  });

  it("exits the loading state when the retry fails, and keeps everything on screen", () => {
    const before = run([failed()], withConversation);
    const pending = run([{ type: "retry_started" }], before);
    expect(pending.retry).toBe("pending");
    expect(pending.notice).toBe(RETRYING_MESSAGE); // visible feedback while waiting
    expect(retryableFailureId(pending)).toBeNull(); // no double click while waiting

    const after = run(
      [{ type: "retry_result", ok: false, reason: "failed" }],
      pending,
    );
    expect(after.retry).toBe("idle");
    expect(after.lines).toEqual(before.lines);
    expect(after.notice).toContain("out of credits");
  });

  it("exits the loading state when the agent cannot be reached", () => {
    const state = run(
      [failed(), { type: "retry_started" }, { type: "retry_unreachable" }],
      withConversation,
    );
    expect(state.retry).toBe("idle");
    expect(state.notice).toBe(RETRY_UNAVAILABLE_MESSAGE);
    expect(state.lines).toHaveLength(3);
  });

  it("does not show a false success: a failed retry is not marked as played", () => {
    const state = run(
      [
        failed(),
        { type: "retry_started" },
        { type: "retry_result", ok: false },
      ],
      withConversation,
    );
    expect(state.lines.at(-1)).toMatchObject({ audio: "not_spoken" });
    expect(state.notice).not.toBeNull();
    expect(RETRY_FAILED_MESSAGE).toContain("nothing else was repeated");
  });

  it("marks the line played once the audio is recovered", () => {
    const state = run(
      [
        failed(),
        { type: "retry_started" },
        { type: "status", event: { type: "speech_recovered", id: "abc123" } },
        { type: "retry_result", ok: true },
      ],
      withConversation,
    );
    expect(state.lines.at(-1)).toEqual({
      speaker: "agent",
      text: "Forty staff, got it.",
      audio: "played",
    });
    expect(state.issue).toBeNull();
    expect(state.notice).toBeNull();
    expect(state.retry).toBe("idle");
  });

  it("does not duplicate a line when the same words later arrive as spoken", () => {
    const state = run(
      [
        failed(),
        { type: "transcript", speaker: "agent", text: "Forty staff, got it." },
      ],
      withConversation,
    );
    expect(
      state.lines.filter((l) => l.text === "Forty staff, got it."),
    ).toHaveLength(1);
    expect(state.lines.at(-1)).toMatchObject({ audio: "played" });
  });

  it("does not add a second line when a retry fails again", () => {
    const again = failed(issue({ id: "def456" }));
    const state = run(
      [failed(), { type: "retry_started" }, again],
      withConversation,
    );
    expect(
      state.lines.filter((l) => l.text === "Forty staff, got it."),
    ).toHaveLength(1);
    expect(state.lines.at(-1)).toMatchObject({
      failureId: "def456",
      audio: "not_spoken",
    });
    expect(retryableFailureId(state)).toBe("def456");
  });

  it("explains listening and model failures without offering an audio retry", () => {
    const listening = run([
      failed(issue({ source: "listening", text: null, retryable: false })),
    ]);
    expect(listening.notice).toContain("speech-recognition");
    expect(retryableFailureId(listening)).toBeNull();
    const model = run([
      failed(
        issue({
          source: "model",
          category: "rate_limited",
          text: null,
          retryable: false,
        }),
      ),
    ]);
    expect(model.notice).toContain("AI model");
    expect(model.lines).toEqual([]);
  });

  it("starts clean for the next call", () => {
    expect(run([failed(), { type: "reset" }], withConversation)).toEqual(
      initialCallScreen,
    );
  });
});
