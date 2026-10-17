# Backchannel design (WP-11.1), for approval

**Status: proposal. Nothing is built.**
- **Design first, then stop:** the plan asks for this design to be approved before the engine
  (WP-11.2) is built.
- **The simulator proof waits on providers:** WP-11.1's done-when ("the simulator shows a clip
  playing mid-prospect-speech with the prospect's turn intact") needs Deepgram and Cartesia, so
  it waits until Virat says Cartesia is topped up.

## What a backchannel is here

A short sound from the agent while the prospect is still talking: "hmm", "okay", "right",
"yeah"; Hindi "haan", "achha", "theek hai", "ji". It tells the prospect the agent is listening.
It is **not a turn**:
- it must not take the floor;
- it must not trigger barge-in (the prospect "interrupting" the agent);
- it must not enter the transcript or the model's context.

The agent still says it is an AI when asked (rule 8). Backchannels are timing, not pretending.

## Options considered (LiveKit Agents 1.8.4, as installed)

| Option | How | Problem |
|---|---|---|
| A. `session.say("hmm")` with guards | The agent speaks a pre-rendered clip as normal agent speech. | It is a real agent turn. While it plays, the prospect's ongoing speech counts as an interruption of the agent, so the session's barge-in logic stops the clip and treats the prospect as interrupting. The clip also goes into the chat context unless excluded. It fights the turn machine. |
| **B. A second audio track (recommended)** | LiveKit's `BackgroundAudioPlayer` (`livekit.agents.voice.background_audio`) publishes its own track (`background_audio`) and mixes clips into it. `play()` takes generated audio frames and returns a handle; `stop()` fades out. | The session does not know the clip played, which is what we want (no turn, no barge-in, no transcript). Echo risk; see below. |

**Recommendation: option B.** The session's turn logic is untouched. A clip is a sound effect
on a separate track, like LiveKit's own "thinking" sounds, which use this same player.

## When the engine would speak (WP-11.2 rules, from the plan)

The engine listens to events the worker already receives:
- `user_state_changed` (speaking, listening, away);
- interim transcripts;
- `agent_state_changed`.

It plays a clip only if **all** of these hold:
1. **The prospect has talked for a few seconds in this turn.** Default 3 s of speech since the
   turn started.
2. **There is a short pause inside the turn.** The prospect went quiet, and the latest
   transcript does not end a sentence or a question.
   - The clip starts about 250 ms into the pause. That is earlier than the endpointing wait
     (0.5 s by default), so a clip never lands after the agent has started its reply.
3. **The rate allows it.** At most one per 8 s by default, set per agent: off, low (one per
   12 s), medium (one per 8 s).
4. **It is not a sensitive moment.** Never while the prospect is giving:
   - digits (phone numbers, amounts, dates);
   - an email address or "at the rate";
   - a question to the agent (the latest transcript ends in "?" or starts a question).
5. **The agent did not just speak.** Not within 2 s of the agent finishing.
6. **The agent is not speaking now** (agent state is listening).

**It stops at once** (fade out of about 80 ms) if the prospect starts a new thought over it:
speech resumes within 150 ms of the clip starting.

**Clips are pre-rendered**, per voice and language, once per voice. They are stored as short
audio files and reused, so each use costs nothing. Rendering them needs Cartesia, so it waits
for credits. Tests use generated silent or tone frames.

## Risks and how the design handles them

| Risk | Handling |
|---|---|
| **Echo:** on a phone line without echo cancellation, the prospect's microphone picks up the clip, and speech-to-text hears "hmm" as the prospect. That could look like barge-in. | Browsers cancel echo. For phone calls, WP-11.2 ignores interim words matching backchannel tokens for 1 s after a clip. **Phone calls start with backchannels off** until WP-14.4 measures real phone audio. |
| The clip lands as the prospect finishes, just before the agent replies. | Clips only fire on a mid-sentence pause and finish before the endpointing wait ends (rule 2). The rate limit keeps it rare. |
| It sounds fake or annoying (plan risk). | **Off by default**, per-agent setting, conservative rate. Defaults change only after Virat's listening test (WP-11.7). |
| The model or transcript treats the clip as speech. | Option B never touches the chat context or the transcript. Clip counts go into turn metrics only. |

## Switch

A worker setting `AUREVIA_BACKCHANNELS` (`off` by default; `low` or `medium`), plus a
per-agent setting later. Off means the player is never started.

## Tests (WP-11.2, all with fakes)

- **Unit tests, one per rule:**
  - minimum speech time;
  - pause inside a turn;
  - rate limit per level;
  - digits, email and question guards;
  - the 2 s gap after the agent spoke;
  - stop when the prospect resumes;
  - echo-token ignore window.
- **A driver test:** a scripted stream of fake events and a fake player confirms that clips
  are only requested when the rules allow, and that `stop()` follows resumed speech.
- **Not proven by these tests:** how it sounds, and real timing on a real call. Those need the
  simulator with real speech (waiting on Cartesia) and Virat's listening test.

## Decision needed from Virat

Approve option B and the rules above, or say what to change. WP-11.2 starts only after that.
