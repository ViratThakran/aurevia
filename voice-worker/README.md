# Aurevia voice worker

The real-time voice runtime (LiveKit Agents). It listens, detects turns, handles interruptions
and speaks; it never decides what to say. Every reply comes from the backend
(`/internal/v1/calls/{id}/turns`), which owns the prompt, the sales rules, the Model Gateway
and usage tracking.

```
browser mic ──WebRTC──▶ LiveKit ──▶ worker: VAD → Deepgram STT ─┐
                                                                 ▼
                                           backend: prompt + sales state → Claude (gateway)
                                                                 │  streamed text (NDJSON)
browser speaker ◀──WebRTC── LiveKit ◀── worker: Cartesia TTS ◀──┘
```

## How a call runs

1. A signed-in user calls `POST /api/v1/voice/sessions`. The backend creates the call and a
   LiveKit room, and dispatches this agent into the room with a per-call token as job
   metadata (server to server; the browser never sees it).
2. The worker calls `/start`, speaks the agent's greeting, then on every prospect turn streams
   the backend's reply into text-to-speech.
3. Barge-in: when the prospect talks over the agent, LiveKit stops playback and cancels the
   reply; closing the HTTP stream makes the backend stop generating and record the turn as
   interrupted.
4. On hang-up the worker reports speech-to-text seconds and text-to-speech characters and
   ends the call (`failed` if setup broke).

## Speech providers

`speech_providers.py` is the only module that imports speech-vendor plugins; the runtime uses
LiveKit's `stt.STT` / `tts.TTS` interfaces. Select vendors with `AUREVIA_STT_PROVIDER`
(`deepgram`) and `AUREVIA_TTS_PROVIDER` (`cartesia`). Keys (`DEEPGRAM_API_KEY`,
`CARTESIA_API_KEY`) exist only in this container, never in the API; the worker has no model key.
Log records are scrubbed of key values as they are created (`redaction.py`).

## Run

With Docker (from `backend/`): set the model key (`AUREVIA_GEMINI_API_KEY` with
`AUREVIA_AI_PROVIDER=gemini`), `DEEPGRAM_API_KEY` and `CARTESIA_API_KEY` in `backend/.env`, then

```bash
docker compose --profile voice up --build
```

and open http://localhost:3000 (or `VOICE_TEST_PORT`). The worker refuses to start without
its vendor keys.

Without Docker: `uv sync`, set `AUREVIA_BACKEND_URL`, `LIVEKIT_URL`, `LIVEKIT_API_KEY`,
`LIVEKIT_API_SECRET`, `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY`, then
`uv run python -m aurevia_voice.main dev`.

## Checks

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```
