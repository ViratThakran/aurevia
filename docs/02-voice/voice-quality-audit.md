# Voice quality audit and baseline (2026-10-10)

Scope: `voice-worker/src/aurevia_voice/`, `backend/src/aurevia/conversation/`, `evaluation/`, `sales/`. Installed SDKs (checked in `voice-worker/.venv`): livekit-agents 1.8.4, livekit-plugins-deepgram / cartesia / silero 1.8.4. No turn-detector plugin is installed.

## 1. What the pipeline does today

```text
mic → Silero VAD → Deepgram nova-3 (language "multi", interim results, endpointing_ms=25)
    → LiveKit turn handling (fixed endpointing 0.5–1.5 s, preemptive LLM on, interruption ≥ 0.5 s)
    → BackendLLM → /internal/v1/calls/{id}/turns → Model Gateway (Gemini 3.5 Flash, fallback Flash-Lite)
       ↳ tool rounds (≤ 3) through ToolExecutor
    → Cartesia sonic-3 TTS (language and voice fixed at call start)
```

## 2. Supported settings: checked, not assumed

| Setting | Supported in the installed SDK | Used today |
|---|---|---|
| Endpointing `fixed` / `dynamic` (`alpha`) | yes (`EndpointingOptions`) | fixed, 0.5 / 1.5 s |
| Turn detection `stt` / `vad` / `realtime_llm` / detector model | yes; the detector model needs the turn-detector plugin (not installed) | default (auto) |
| Preemptive LLM; **preemptive TTS** | yes (`preemptive_tts`, default **off**) | LLM on, TTS off |
| Interruption `adaptive` / `vad`, `min_words`, false-interruption resume, backchannel boundary | yes | min_duration 0.5 s, other defaults |
| Cartesia `language`, `voice`, `speed`, `emotion`, `pronunciation_dict_id`; `update_options()` mid-call | yes. The plugin's `TTSLanguages` type lists 7 languages and defers to Cartesia's docs; the Cartesia voices API lists **100+ `hi` voices** | language = agent language prefix (`en`); voice = **none set** |
| Deepgram `keyterms` (nova-3), `smart_format`, `numerals`, `filler_words` | yes | not used |

## 3. Baseline: measured, real numbers

**Recorded calls** (dev database, 14 calls, 88 agent turns; browser and simulator):

| Metric | p50 | p95 |
|---|---|---|
| End of prospect speech → first agent audio (`e2e`) | **2 827 ms** | **6 474 ms** |
| Model time to first token | 1 668 ms | |
| TTS time to first byte | 170 ms | |
| End-of-turn wait | 579 ms | 3 001 ms (calls before the 1.5 s cap) |
| STT transcription delay | 486 ms | |
| Agent turns interrupted | 5.7 % | |

Agent replies across those calls averaged **21.7 words** (p90 38). Openers repeat: "thanks for", "I understand", "that makes".

**Sales scenarios** (`python -m aurevia.evaluation.run`, real Gemini, 19 replies), before → after:

| Metric | Before (`voice-2026-10-10.1`) | After (`.2` + slot fix) |
|---|---|---|
| Scenarios passed | 8/8 | 8/8 (booking also passed 3 of 3 extra runs) |
| Words per reply | **30.2** | **17.9** |
| Replies over 30 words (≈ 12 s of speech) | **36.8 %** | **0 %** |
| Replies opening with a stock acknowledgement | 42.1 % | 15.8 % |
| Filler phrases per reply | 0.16 | 0 |
| Questions per reply; replies with 2+ questions | 0.58; 0 % | 0.58; 0 % |
| Slot lookups per booking (each costs a model round) | 2–5 | 2–3 |
| First word over the text path, p50 / p95 | 2 158 / 4 919 ms | 2 115 / 3 806 ms |

**Simulated voice call** after the change (`simulate --scenario skeptical`, 4 measured turns):
- end of speech → first audio p50 **2 582 ms**, p95 2 759 ms
- model time to first token p50 1 996 ms; TTS 182 ms; end-of-turn wait 578 ms
- **prospect word error rate 0.0**

That word error rate comes from synthetic TTS speech over WebRTC: clean audio, not phone audio. **No real phone audio and no human caller were tested.** Latency still misses the 1.0 / 1.8 s target.

## 4. Causes found

1. **Wrong voice for the market, and a fixed language.**
   - No agent has a voice set and the worker has no default (`AUREVIA_TTS_VOICE` unset), so every call has used the plugin default "Katie", an American English voice, for an Indian English agent.
   - The prompt tells the agent to "reply in the language the prospect uses", but TTS language is fixed at call start (`en`). Hindi replies would be read with English phonemes.
2. **Latency is mostly the model.**
   - Model time to first token is ~60–75 % of `e2e`.
   - Every tool round adds a full model round trip.
   - A **bug** multiplied the rounds: the model asks for slots from a past date (it guessed **2025**). The tool silently returned "no free times", and the model retried, sometimes until the tool rounds ran out (one booking failed this way in evaluation).
3. **Long, formulaic replies** (30 words, 42 % stock openers in evaluation). Spoken, that is 10–15 s monologues that start with the same phrases.
4. Smaller items:
   - endpointing is fixed rather than adaptive (not benchmarked yet)
   - preemptive TTS is off
   - Deepgram has no `keyterms` for company and agent names
   - Hindi STT relies on `multi`

## 5. What changed in this milestone (smallest change, highest impact we can verify)

| Change | Why | Acceptance test |
|---|---|---|
| Spoken-style rules in the prompt (`PROMPT_VERSION voice-2026-10-10.2`): ≤ 2 short sentences, ≤ 1 question, no stock openers / echoes / filler, backchannel / correction / interruption / busy handling | Cause 3 | Evaluation style metrics improve, with no scenario regression: 30.2 → 17.9 words, long replies 37 % → 0 %, 8/8 pass. Honesty, tool and state rules unchanged (`tests/test_conversation.py`) |
| `get_available_slots`: a past `from_date` searches from today and says so (`today`, `note`) | Cause 2 (bug) | `tests/integration/test_sales_tools.py::test_a_past_start_date_searches_from_today` |
| Baseline metrics: evaluation style metrics (`evaluation/style.py`), first-word p50/p95 in the evaluation report, **prospect WER** in the simulator (`aurevia_voice/wer.py`) | Task 1 | `tests/test_evaluation_style.py`, `voice-worker/tests/test_wer.py` |
| Voice samples for listening (`python -m aurevia_voice.voice_samples OUT`) | Cause 1 needs a human decision | 16 WAVs rendered: 4 voices × 4 approved sentences |

Not changed, on purpose:
- the default voice (a listening decision)
- endpointing and other turn-handling defaults (not benchmarked yet)
- the TTS language switching (see §6)
- compliance, sales state, tools and AI disclosure

Cost implications:
- Prompt change: about +200 input tokens per model call (the new section replaces a shorter one), and ~40 % fewer output tokens per reply. Fewer TTS characters (−40 %) and slightly shorter calls.
- One evaluation run is ~25 model calls.
- The voice samples cost ~1 500 TTS characters.

## 6. Proposals that need a decision or a benchmark

- **Voice:** listen to `voice-samples/` and score each voice 1–5 for clarity, warmth and Indian English naturalness, plus Hindi and Hinglish pronunciation. Then set the chosen id per agent (the dashboard **Agent → Voice id**) or as the worker default `AUREVIA_TTS_VOICE`.
  - Candidates: Siya, Meera (female), Dev (male); the current default is Katie.
  - The approved sentences are in `voice_samples.py`.
- **Language:** the safest provider-supported option is a **per-agent language setting** applied at call start:
  - `hi-IN` agent → Cartesia `language="hi"` with a Hindi voice, and a prompt default of Hindi.
  - Switching mid-call with `update_options(language=…)` is supported by the plugin, but it needs per-turn language detection and a benchmark of mixed-language audio. Proposed for later, not done here.
- **Endpointing:** A/B `fixed 0.5/1.5` against `dynamic` (alpha 0.9) and against the turn-detector model, using the simulator's busy and skeptical scenarios plus 10 human calls each. Compare end-of-turn wait, false interruptions and `interrupted_turns`.
- **Preemptive TTS:** benchmark `preemptive_tts=True` (saves TTS time to first byte, ~180 ms, when the prediction holds).
- **Deepgram `keyterms`:** the agent and company names, for accuracy on names.
- **Model latency:** remains the dominant gap (decision 2026-10-09: a faster model or key).

## 7. Next milestone (proposed)

1. Pick the voice from the samples, and add the per-agent language setting (`hi-IN` → Hindi TTS).
2. Endpointing and preemptive-TTS benchmark with the simulator: 5 runs per setting, then change defaults only on evidence.
3. Five human browser calls (en-IN and Hinglish) scored with the call-review rubric in the pilot runbook.
4. Then start the sales-learning system ([../07-learning/sales-learning-design.md](../07-learning/sales-learning-design.md)), stage 1.

## 8. Voice decision (2026-10-10)

The user chose **Meera** (female, default for new agents) and **Dev** (male) from the samples,
in chat on 2026-10-10. Both come from Cartesia's Indian catalogue. They are the two selectable
voices: an agent may use either, picked on the dashboard (**Agent → Voice**; `GET /api/v1/voices`).
**Status: chosen, not yet accepted.** Acceptance needs the microphone test in
[../06-testing/voice-manual-acceptance.md](../06-testing/voice-manual-acceptance.md), which has
not been run.
`AUREVIA_TTS_VOICE` defaults to Meera for agents with no voice set. Siya and the old default
(Katie) are no longer used.

## 9. Speak first, then record; Hindi voice switch (2026-10-10)

**Cause found** (per-turn timing log, `Turn first word`: `prepare_ms`, `first_word_ms`, `rounds`):
- backend preparation is 13–50 ms
- one model call takes about 0.8–1.0 s to its first word (Flash-Lite, real prompt and tools)
- most turns made **2–3 model calls before the first word**: the model called a bookkeeping
  tool (`set_stage`, `qualify_lead`, `log_objection` …) with no text, and spoke only in the next call
- telling the model to speak first in the prompt did not change this, and broke a booking scenario (reverted)

**Change (approved 2026-10-10):**
- **Speech pass:** only tools the reply may depend on are offered: slots, booking,
  cancellation, follow-up, do-not-call and handoff (`DEFERRED_TOOLS` in `conversation/engine.py`
  lists the ones held back).
- **Bookkeeping pass:** after the reply streams, a second model call may use only the five
  bookkeeping tools (stage, qualification, interest, objection, note), through the same
  validated `ToolExecutor`. It sees the reply as spoken and its text is ignored. It runs off the
  prospect's clock and cannot book or change anything the prospect was told. *(Corrected
  2026-10-10, section 10: "not interested" moved back into the spoken turn, a failed pass is
  retried once, and the next turn waits for it.)*
- `PROMPT_VERSION voice-2026-10-10.3` (now `.4`): the agent is told that bookkeeping is recorded after it speaks.
- **Hindi voice switch** (`voice-worker/src/aurevia_voice/language.py`): before each reply is
  synthesized, its first words are checked (Devanagari, or Hinglish words in Latin script). The
  Cartesia language is set to `hi` or `en` before the TTS stream is created. A reply too short
  to tell ("Okay.") keeps the current language.

**Measured** (evaluation, real Gemini, free-tier key with rate limits and an exhausted Flash quota):

| Turn type | Before | After |
|---|---|---|
| No tool needed (most turns) | 2 calls, first word ~2.0–2.5 s | 1 call, **0.9–1.3 s** when the model is not throttled |
| Not interested | 2 calls, ~1.9 s | 1 call, 1.2–1.3 s *(superseded: it is in the spoken turn again, see section 10)* |
| Slot lookup and booking | 2–3 calls, 2.6–3.6 s | 2–3 calls, unchanged (it needs the lookup) |
| Handoff and do-not-call | 2 calls | 2 calls, unchanged on purpose (the agent talks about the result) |

- **Cost:** one extra small model call per turn, about 2.2k input tokens and few output tokens.
- **Free-tier limits:** this doubles requests per minute on a free-tier key. Rate limits then
  stall turns (20–40 s retries) and drop bookkeeping passes. **A paid key is needed for real calls.**

## 10. Validation of the voice changes (2026-10-10)

### Bugs found and fixed

| # | Bug | Fix | Test |
|---|---|---|---|
| 1 | "Not interested" was recorded only by the bookkeeping pass. If that pass failed (for example on a rate limit), the lead stayed callable | `mark_not_interested` is back in the spoken turn. Deferred now: stage, qualify, interested, objection, note | `test_speech_first_then_bookkeeping_after_the_reply` |
| 2 | A failed bookkeeping pass was only logged as a warning | One retry for rate limit, timeout or outage. A pass still lost is logged as an **error** ("Bookkeeping pass lost") | `test_bookkeeping_retries_once_after_a_transient_failure`, `test_bookkeeping_failure_never_breaks_the_spoken_reply` |
| 3 | Turn N+1 could start while turn N's bookkeeping was still writing: a stale stage in the prompt, and two concurrent writers | A turn waits (≤ 2 s) for its call's pending pass | `test_next_turn_waits_for_the_previous_bookkeeping` (fails without the wait; checked) |
| 4 | The bookkeeping pass was sent text from earlier tool rounds twice | It gets only the last round's words; earlier rounds are already in the history | covered by the tests above |
| 5 | Hinglish dates and times ("Somvaar ko 10 baje") were detected as English and read with English pronunciation | Added particles, days and times; removed the English-colliding "par" and "din" | `test_hinglish_dates_times_and_numbers` |
| 6 | The API accepted any voice id; the docs said only Meera and Dev | `AgentUpdate.voice` must be an approved voice (or empty, meaning Meera) | `test_approved_voices_and_the_default` |
| 7 | The docs said the voice was "approved" | Corrected: **chosen by the user, not yet accepted**. Acceptance is the manual test | n/a |

Still true:
- Tools stay validated, tenant-scoped and audited in both passes (same `ToolExecutor`; `test_bookkeeping_tools_are_validated_scoped_and_audited`).
- Booking, slots, handoff, do-not-call and "not interested" run before the turn ends (`test_required_actions_happen_in_the_spoken_turn`).
- A bookkeeping failure never changes the spoken reply.

### Measurements (`backend/scripts/voice_benchmark.py`; raw reports in `benchmarks/`)

**Conditions:** real Gemini, **free-tier key**, text path only (backend and model: request sent →
first text delta). **No STT, TTS or audio.**
- Flash: daily quota (20 requests) used up all day, so every turn fell back to Flash-Lite.
- Flash-Lite answered a trivial prompt in 0.8 s in the morning and 4.5–11 s in the evening.
- Flash-Lite's daily quota (500 requests) ran out during the comparison.

**Run A**: new code, the configured settings (Flash, falling back to Flash-Lite; 2.5 s
first-token timeout), 1 run of 6 scenarios.
**Run B-old**: the code before the speak-first change (`1fb897d`), Flash-Lite only, 2 runs.
**Run B-new** (same settings as B-old): **blocked**. Flash-Lite's daily quota ran out after
4 turns; 2 turns measured 1 544 and 1 028 ms.

| Scenario | A new: p50 / p95 ms | B old: p50 / p95 ms | A new: model requests per turn | B old: model requests per turn | A new: cost / scenario | B old: cost / scenario |
|---|---|---|---|---|---|---|
| Ordinary (3 turns) | 2 101 / 2 109 | 2 089 / 3 740 | 2.33 | 2.33 | $0.0039 | $0.0053 |
| Objection (2) | 951 / 1 014 | 2 337 / 4 104 | 2.0 | 2.0 | $0.0023 | $0.0030 |
| Slot lookup (1) | 2 183 | 1 956 / 2 737 | 3.0 | 2.0 | $0.0018 | $0.0016 |
| Booking (3) | 3 196 / 3 866 | 2 349 / 4 323 | 4.33 | 3.0 | $0.0067 | $0.0067 |
| Handoff (1) | 3 170 | 2 054 / 2 282 | 4.0 | 2.0 | $0.0017 | $0.0015 |
| Do-not-call (1) | 1 991 | 2 008 / 2 068 | 3.0 | 2.0 | $0.0016 | $0.0014 |
| **All turns** | **2 101 / 3 866** (11 turns) | **2 282 / 4 104** (22 turns) | **3.09** | **2.36** | **$0.0179** for the 6 | **$0.0196** for the 6 |

- **Cost:** at Gemini 3.5 Flash-Lite paid-tier rates, $0.30 per 1M input tokens and $2.50 per 1M
  output tokens (ai.google.dev pricing, read 2026-10-10). The platform price table is empty, so
  the platform itself reports usage as "not priced".
- **Model requests per turn** include the bookkeeping pass and, in run A, three requests the
  provider refused (Flash quota).
- **Rate limits:** run A had 3 refused requests and 1 harness retry (a 20 s wait). Run B-old had
  1 refused request and 1 retry. No turn failed in A or B-old.

**What this does and doesn't show:**
- The samples are small, and the provider's speed changed several-fold during the day.
- The latency difference between A and B-old is **within noise**, so it is not evidence either way.
- Speak-first saves the extra model call only on turns where the old flow made a bookkeeping-only
  call before speaking. On the same day, under faster provider conditions (section 9), turns
  without a needed tool went from about 2.0–2.5 s to 0.9–1.3 s.
- **Cost:** speak-first adds about one bookkeeping request per turn (+0.7 requests per turn here).
  Cost per scenario stayed about the same ($0.018 against $0.020), because each call carries
  fewer tool definitions. On a free-tier key, the extra requests use up the daily quota sooner,
  which is what stopped run B-new.
- **No other latency options were turned on** (preemptive TTS, dynamic endpointing): there is no
  measured evidence for them yet.

**Not measured (blocked):**
- **End of speech → first audio** with synthetic speech (`aurevia_voice.simulate`, now with a
  `hinglish` scenario): blocked, because the model quota ran out. The last measurement (before
  speak-first) was p50 2 582 ms / p95 2 759 ms.
- **Human microphone test:** needs a person; see
  [../06-testing/voice-manual-acceptance.md](../06-testing/voice-manual-acceptance.md).
- **Phone audio:** needs hosting and Exotel.
- **The Hindi switch with real audio:** the TTS side was checked with Cartesia (a Hinglish reply
  switched to `hi` and produced audio). A full call is blocked for the same reasons as above.

**To repeat** (inside the API container, ideally with a paid key):
`python scripts/voice_benchmark.py --runs 3 --out /tmp/new.json --label new`. For the old
version, put its `src` first on `PYTHONPATH`.
