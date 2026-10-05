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
