/**
 * Voice-service failures on a browser call: what the voice worker publishes, the wording shown
 * to the person, and the call-screen state that follows. Kept free of React and LiveKit so it
 * can be tested on its own.
 *
 * The worker sends only a source, a category and (for a reply that could not be spoken) the
 * reply's words. Raw provider messages never reach the browser, so none can be shown here.
 */

export const STATUS_TOPIC = "aurevia.voice_status";
export const RETRY_METHOD = "aurevia.retry_speech";
/** The browser stops waiting for the agent's answer to a retry after this long. */
export const RETRY_TIMEOUT_MS = 10_000;

export type IssueSource = "voice" | "listening" | "model";
export type IssueCategory =
  | "credits_exhausted"
  | "rate_limited"
  | "timeout"
  | "provider_unavailable"
  | "unknown";

export interface VoiceIssue {
  id: string;
  source: IssueSource;
  category: IssueCategory;
  retryable: boolean;
  text: string | null;
}

export type StatusEvent =
  | ({ type: "voice_issue" } & VoiceIssue)
  | { type: "speech_recovered"; id: string };

const SOURCES: IssueSource[] = ["voice", "listening", "model"];
const CATEGORIES: IssueCategory[] = [
  "credits_exhausted",
  "rate_limited",
  "timeout",
  "provider_unavailable",
  "unknown",
];

/** Parse a status message from the worker; anything unexpected is ignored, never shown. */
export function parseStatusEvent(raw: string): StatusEvent | null {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof data !== "object" || data === null) return null;
  const d = data as Record<string, unknown>;
  if (typeof d.id !== "string" || d.id.length === 0 || d.id.length > 40)
    return null;
  if (d.type === "speech_recovered")
    return { type: "speech_recovered", id: d.id };
  if (d.type !== "voice_issue") return null;
  const source = SOURCES.find((s) => s === d.source);
  const category = CATEGORIES.find((c) => c === d.category);
  if (!source || !category) return null;
  const text =
    typeof d.text === "string" && d.text.trim()
      ? d.text.trim().slice(0, 4000)
      : null;
  return {
    type: "voice_issue",
    id: d.id,
    source,
    category,
    retryable: d.retryable === true && source === "voice" && text !== null,
    text,
  };
}

const AFTER_VOICE = "The AI generated a response, but it could not speak it.";

/** Plain-language wording for each failure. Credits is the exact wording agreed for Cartesia. */
export function issueMessage(
  issue: Pick<VoiceIssue, "source" | "category">,
): string {
  if (issue.source === "voice") {
    switch (issue.category) {
      case "credits_exhausted":
        return `The voice service is out of credits. ${AFTER_VOICE} Please check your Cartesia subscription.`;
      case "rate_limited":
        return `The voice service is getting too many requests right now. ${AFTER_VOICE} Wait a moment, then retry the audio.`;
      case "timeout":
        return `The voice service took too long to answer. ${AFTER_VOICE} You can retry the audio.`;
      case "provider_unavailable":
        return `The voice service is temporarily unavailable. ${AFTER_VOICE} You can retry the audio in a moment.`;
      default:
        return `The voice service had a problem. ${AFTER_VOICE} You can retry the audio.`;
    }
  }
  if (issue.source === "listening") {
    return issue.category === "credits_exhausted"
      ? "The speech-recognition service is out of credits, so the agent cannot hear you. Please check your Deepgram subscription."
      : "The speech-recognition service had a problem, so the agent may not have heard you. Please say it again.";
  }
  switch (issue.category) {
    case "rate_limited":
      return "The AI model is busy (rate limit reached). Wait a few seconds and say it again.";
    case "timeout":
      return "The AI model took too long to answer. Please say it again.";
    case "provider_unavailable":
      return "The AI model is temporarily unavailable. Please try again in a moment.";
    default:
      return "The AI model could not answer. Please say it again.";
  }
}

export const RETRYING_MESSAGE = "Replaying the audio…";
export const RETRY_FAILED_MESSAGE =
  "The audio could not be played again. The response is shown above; nothing else was repeated.";
export const RETRY_UNAVAILABLE_MESSAGE =
  "The agent could not be reached to replay the audio. The call may have ended.";

export interface Line {
  speaker: "you" | "agent";
  text: string;
  /** Agent lines only: heard by the caller, or generated but never spoken. */
  audio?: "played" | "not_spoken";
  /** Set while a not-spoken line can be retried. */
  failureId?: string;
}

export interface CallScreenState {
  lines: Line[];
  issue: VoiceIssue | null;
  /** The notice under the call controls; never raw provider text. */
  notice: string | null;
  retry: "idle" | "pending";
}

export const initialCallScreen: CallScreenState = {
  lines: [],
  issue: null,
  notice: null,
  retry: "idle",
};

export type CallScreenAction =
  | { type: "reset" }
  | { type: "transcript"; speaker: "you" | "agent"; text: string }
  | { type: "status"; event: StatusEvent }
  | { type: "retry_started" }
  | { type: "retry_result"; ok: boolean; reason?: string }
  | { type: "retry_unreachable" };

export function callScreenReducer(
  state: CallScreenState,
  action: CallScreenAction,
): CallScreenState {
  switch (action.type) {
    case "reset":
      return initialCallScreen;

    case "transcript": {
      if (action.speaker === "agent") {
        // The same words arriving through the normal transcript were spoken after all
        // (for example a successful retry): mark the line instead of showing it twice.
        const index = state.lines.findLastIndex(
          (l) =>
            l.speaker === "agent" &&
            l.audio === "not_spoken" &&
            l.text === action.text,
        );
        if (index >= 0) {
          const lines = state.lines.slice();
          lines[index] = {
            speaker: "agent",
            text: action.text,
            audio: "played",
          };
          return {
            ...state,
            lines,
            issue: clearedIf(state.issue, lines[index]),
            notice: null,
          };
        }
        return {
          ...state,
          lines: [
            ...state.lines,
            { speaker: "agent", text: action.text, audio: "played" },
          ],
        };
      }
      return {
        ...state,
        lines: [...state.lines, { speaker: "you", text: action.text }],
      };
    }

    case "status": {
      const event = action.event;
      if (event.type === "speech_recovered") {
        const lines = state.lines.map((l) =>
          l.failureId === event.id
            ? { speaker: l.speaker, text: l.text, audio: "played" as const }
            : l,
        );
        return {
          ...state,
          lines,
          issue: state.issue?.id === event.id ? null : state.issue,
          notice: null,
          retry: "idle",
        };
      }
      const { type: _type, ...issue } = event;
      void _type;
      let lines = state.lines;
      if (issue.text) {
        // A retry that failed again re-reports the same words: update that line, never add one.
        const index = lines.findLastIndex(
          (l) =>
            l.speaker === "agent" &&
            l.audio === "not_spoken" &&
            l.text === issue.text,
        );
        const line: Line = {
          speaker: "agent",
          text: issue.text,
          audio: "not_spoken",
          ...(issue.retryable ? { failureId: issue.id } : {}),
        };
        lines =
          index >= 0
            ? lines.map((l, i) => (i === index ? line : l))
            : [...lines, line];
      }
      return {
        ...state,
        lines,
        issue,
        notice: issueMessage(issue),
        retry: "idle",
      };
    }

    case "retry_started":
      return { ...state, retry: "pending", notice: RETRYING_MESSAGE };

    case "retry_result":
      // A failed retry has already published its own new status; keep that notice.
      return action.ok
        ? { ...state, retry: "idle" }
        : {
            ...state,
            retry: "idle",
            notice: state.issue
              ? issueMessage(state.issue)
              : RETRY_FAILED_MESSAGE,
          };

    case "retry_unreachable":
      return { ...state, retry: "idle", notice: RETRY_UNAVAILABLE_MESSAGE };
  }
}

function clearedIf(issue: VoiceIssue | null, line: Line): VoiceIssue | null {
  return issue && issue.text === line.text ? null : issue;
}

/** The failure a retry would replay, if it is still available. */
export function retryableFailureId(state: CallScreenState): string | null {
  return state.issue?.retryable && state.retry === "idle"
    ? state.issue.id
    : null;
}
