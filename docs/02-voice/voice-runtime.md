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
