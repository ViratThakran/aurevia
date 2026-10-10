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
