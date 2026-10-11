# Voice Runtime

## Pipeline
```text
Microphone/RTP -> VAD -> Turn Detection -> Streaming STT
 -> Conversation Engine -> Model Gateway -> Streaming TTS -> Audio
```

## Responsibilities
Audio lifecycle, VAD, turn detection, partial STT, streaming model output, streaming TTS, interruption, cancellation, silence, reconnect and cleanup.

## Interruption
1. Detect new speech.
2. Stop/cancel TTS playback.
3. Cancel or invalidate obsolete model generation.
4. Preserve the new utterance.
5. Continue from the new turn.

## Streaming
Do not wait for complete transcript/model/TTS output when safe streaming is available.

## Session lifecycle
CREATED -> CONNECTING -> ACTIVE -> INTERRUPTED/RECOVERING -> COMPLETED/FAILED

Recovery must not duplicate external side effects.

## Voice-service failures on a browser call

The voice worker (`voice-worker/src/aurevia_voice/voice_status.py`) reports provider failures
to the Test Call page, so a failure is never silent.

| Source | Provider | What the person sees |
|---|---|---|
| `voice` (text to speech) | Cartesia | the reply as text, marked "Response generated, audio not played", a notice and **Retry audio** |
| `listening` (speech to text) | Deepgram | a notice to say it again (no retry) |
| `model` (the AI model, via the backend) | Gemini | a notice to say it again (no retry) |

**Categories** (from the error type and HTTP status only; raw provider text is never read or
sent): `credits_exhausted` (402), `rate_limited` (429), `timeout` (408, 504, timeouts),
`provider_unavailable` (5xx, connection errors), `unknown`.

**Messages.** The dashboard owns the wording (`web/dashboard/src/lib/voice-issues.ts`).
Credits: "The voice service is out of credits. The AI generated a response, but it could not
speak it. Please check your Cartesia subscription."

**Channel.** The worker sends one JSON text message on the LiveKit topic
`aurevia.voice_status` (`voice_issue` / `speech_recovered`: source, category, retryable, id,
and for voice failures the reply's words). It stays inside that call's room. A browser that
joins after a failure (the greeting can fail before it arrives) is sent the recent unresolved
failures.

**Retry.** The browser calls the worker's RPC `aurevia.retry_speech` with only the failure id.
The worker speaks the words it stored with `session.say(..., add_to_chat_ctx=False)`:

- no model call and no backend turn, so **no tool can run again**: a booking, handoff or
  do-not-call recorded for that turn is not repeated
- one attempt per failure; only the latest 5 failures are kept
- the browser cannot supply text, only an id; it stops waiting after 10 s

**Call keeps going.** On a **browser** call a failed reply does not end the call
(`max_unrecoverable_errors` is 20 instead of 3), so audio can be retried after fixing the
provider. **Phone calls keep the default of 3**: a prospect on the line is not left in silence
while the provider is down.

**Logging.** One line per failure: `call_id`, `provider`, `source`, `category`, `http_status`.
No reply text, headers or keys.

**Phone calls.** No browser is attached, so there is no notice; the failure is logged and the
session ends after 3 consecutive failures.

### Verified (2026-10-11)

Against the **real Cartesia service**, which returned HTTP 402 (credits exhausted) throughout:
- the worker classified the failure as `credits_exhausted`, status 402, and kept the call up
- greeting failing **before** the browser joined the room (browser held out for 12 s): the
  notice, the greeting text and the retry button still appeared when it joined
- failure after the browser had joined: same result
- **Retry audio** with the worker reachable: settled in about 1 s, the credits notice stayed
  (Cartesia still 402), the transcript lines stayed, and nothing was shown as played
- worker unreachable (container paused): "Replaying the audio…" with a spinner for about 7 s,
  then "The agent could not be reached…", the button usable again, transcript kept
- backend counters for the call before and after a retry: tool executions, model calls,
  meetings, handoffs and turn requests all **unchanged** (0 → 0): a retry makes no backend call

With **mocked** providers (unit tests, no network): 402, 429, timeout, 5xx, connection error,
error text carrying a status, generic "no audio" (unknown), cause chains; the log and
published message contain no provider text or secrets; one retry per failure; a failing retry
is reported, not called a success; arbitrary text cannot be injected into a retry; recent
failures replayed to a late browser and not once handled; interruptions are not failures;
the TTS node keeps the whole reply; the dashboard state machine (loading clears, transcript
kept, no duplicate lines, false success impossible).

### Limitations

- **Successful audio recovery is only tested with mocks.** Cartesia credits are exhausted, so
  a retry that really speaks, and the "audio played" transition, were not seen against the
  real service. Do not treat it as proven until credits are restored and the Test Call is
  repeated.
- **Retry replays the latest failure only.** An earlier unspoken line (for example the
  greeting, when a later reply also failed) stays marked "audio not played".
- **The retry cannot be verified against a real sales action in this setup.** A real
  booking/handoff/do-not-call turn needs spoken input, and speech synthesis for a test
  prospect is down. What is verified: a retry has no path to the backend or the model (only
  the stored words are spoken), and the counters above did not move.
- The unspoken reply is not marked in the saved call transcript on the backend; only the
  browser distinguishes "generated" from "played".
- `python -m aurevia_voice.check_status` once aborted on a LiveKit client library panic at
  exit (not reproduced in 4 further runs; the worker was unaffected).
- "Retry audio" is offered on browser calls only.

**Check it manually** (local development): `python -m aurevia_voice.check_status --email …
--password …` inside the voice-worker container joins a call, prints the published failure
(reply text as a length only), asks for a retry and prints the answer.
