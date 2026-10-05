# Voice Provider Abstraction

Keep STT, TTS, telephony and voice-transport providers behind interfaces.

```text
Aurevia Voice Interfaces
 +---------+-----------+----------+
 |         |           |
 STT       TTS      Telephony
 |         |           |
Adapters  Adapters    Adapters
```

Business logic must not import provider SDKs directly.

Record provider/session IDs, region/model/voice, latency, status, errors and usage metadata where available.

Phase 1 uses one implementation per capability. Do not build speculative adapters.

## Phase 2 decision (approved 2026-10-05)
LiveKit Agents' STT/TTS plugins (Deepgram, Cartesia) are used directly inside `voice-worker/`,
which acts as the voice provider boundary: swapping a speech vendor changes only that package.
The LLM is not a worker plugin: it is reached only through the backend's Model Gateway.
