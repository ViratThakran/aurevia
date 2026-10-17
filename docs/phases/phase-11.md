# Phase 11: Human feel

State: **not started.** Do not start before Gate 10 (plan rule 10). Content is from the plan
only.

## Goal

The call feels like two friends talking: the agent listens, reacts with short natural sounds,
pauses at the right moments, and its voice carries warmth. It still says it is an AI when asked
(rule 8).

## Gate 11 and how to measure it

| Check | Target (proposed, Virat confirms) | How it is measured |
|---|---|---|
| Would happily stay on the call | at least 70% of ten listeners | Blind listening test (WP-11.7) |
| Naturalness, warmth, listening, timing | average at least 4 of 5 each | Same test |

Listener recruitment, the scoring form and the test clips: **to confirm**.

## Work packages

| WP | What | Done when | Status | PR |
|---|---|---|---|---|
| 11.1 | Backchannel spike: play a short clip while the prospect speaks without taking the turn or triggering barge-in (guarded `session.say`, or a second mixed audio source). Write `docs/02-voice/backchannel-design.md`. **Design first, then stop for approval.** | The simulator shows a clip playing mid-prospect-speech with the prospect's turn intact. | Design in review; waiting for Virat's approval. Simulator proof waits on Cartesia credits. | this PR |
| 11.2 | Backchannel engine (`backchannel.py` in the voice worker): after a few seconds of prospect speech at a short pause; max rate (default about one per 8 s; off, low, medium per agent); never during numbers, emails, phone numbers, a question to the agent, or right after the agent spoke; pre-rendered clips per voice and language (English: hmm, okay, right, yeah; Hindi: haan, achha, theek hai, ji); stop if the prospect starts a new thought. | Unit tests cover every rule, simulator rate inside the configured range, overlap incidents counted and low. | Not started | none |
| 11.3 | Agent-side reactions: raise the prompt version, allow short varied reactions tied to mood; keep two short sentences, no echoing, one question at most. Update `evaluation/style.py` to reward variety. | 8 of 8 scenarios pass, word counts near 18 per reply. | Not started | none |
| 11.4 | Mood and emotion: bookkeeping pass records `prospect_mood` (warm, neutral, rushed, annoyed, skeptical, confused), mapped per turn to speed and emotion via the Cartesia adapter (`update_options`). Text-based first. | Personas produce different voice settings, setting stored in turn metrics, tests use a mocked provider. | Not started | none |
| 11.5 | Natural speech: rupee amounts, dates, phone numbers said naturally; pronunciation dictionary; per-turn Hinglish switching benchmarked on mixed-language audio before turning on. | **To confirm** (the plan gives no done-when). | Not started | none |
| 11.6 | Turn-taking polish: "sorry, go ahead" after interruption, "hold on", "can you repeat that", "I'm driving", long silences, clean goodbye. Reuse the silence tracker and interruption handling. | **To confirm** (no done-when in the plan). | Not started | none |
| 11.7 | Human-feel scorecard: blind A/B with and without each feature, plus backchannels per minute, pause before replying and talk ratio compared with the expert callers (Phase 12). | Gate 11 met and the scorecard saved in `docs/06-testing/`. | Not started | none |

## Decisions and open questions

- Virat confirms the Gate 11 pass marks.
- Virat chooses, with ten test listeners: the Hindi and Hinglish voice, and how often the agent
  says "hmm" and "okay".
- Backchannel method (guarded `say` vs second audio source): decided after WP-11.1's design,
  with Virat's approval.
- Voice-tone (audio) mood detection: only later if text-based mood shows a ceiling (Phase 18).

## Parts of the system it touches

- Voice worker: new `backchannel.py`, barge-in and turn handling, silence tracker, Cartesia
  adapter (`update_options`), pre-rendered clips, the simulator.
- Backend: prompt version, bookkeeping pass (`prospect_mood`), turn metrics,
  `evaluation/style.py`.
- Docs: `docs/02-voice/backchannel-design.md`, scorecard in `docs/06-testing/`.

## Risks and dependencies

- Depends on Gate 10 (speed) and on Phase 12's timing profile for defaults (WP-12.5) and
  expert comparison numbers (WP-11.7).
- Risk: backchannels and emotion sound fake or annoying. Fallback: conservative defaults,
  per-agent off switch, blind listening tests before any default changes.
- Rule 8 stays: naturalness from timing, warmth and listening, never from pretending to be
  human.

## Measured results

None yet.

## Done checklist

- [ ] WP-11.1 design approved by Virat
- [ ] WP-11.2 to 11.6 done-when met (11.5 and 11.6 done-when to confirm)
- [ ] WP-11.7 scorecard saved; Gate 11 met
- [ ] Definition of done for each WP; `CLAUDE.md` status and this file updated
