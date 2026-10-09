"""Simulated prospect: a scripted caller for voice-quality regression runs.

It signs in to the backend as a local test user, starts a real browser-style voice session,
joins the LiveKit room and speaks scripted lines (synthesized with the configured TTS) as the
prospect. The real pipeline answers: STT -> backend -> model -> TTS. The worker records each
turn's latency; at the end this script prints the call's latency summary and exits non-zero
when the Phase 3 target is missed.

Run inside the voice-worker container (local development only):

    python -m aurevia_voice.simulate --email demo@example.com --password '...'

Scenarios are in ``SCENARIOS``. ``--barge-in`` makes the prospect talk over the agent's
second reply to exercise interruption handling.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.request
from dataclasses import dataclass
from typing import Any

import aiohttp
from livekit import rtc

from aurevia_voice.speech_providers import SpeechOptions, build_tts

SAMPLE_RATE = 24000
TRANSCRIPTION_TOPIC = "lk.transcription"

SCENARIOS: dict[str, list[str]] = {
    "skeptical": [
        "Hello? Who is this?",
        "Wait, are you a real person or a bot?",
        "Okay. We already have insurance through another broker.",
        "What would you do differently?",
        "Fine, you can have someone email me. Bye.",
    ],
    "busy": [
        "Yeah, hi, I'm in the middle of something.",
        "Can you just tell me in one sentence what this is?",
        "Call me back next week then.",
    ],
    "booking": [
        "Hi, yes, I was expecting a call about group health cover.",
        "We have about forty staff and our renewal is in two months.",
        "Sure, a meeting with your specialist sounds good. What times do you have?",
        "The first time you mentioned works for me.",
        "Great, thanks. Bye.",
    ],
}


@dataclass
class AgentTurns:
    """Signals when the agent starts and finishes speaking, from its live transcription."""

    started: asyncio.Event
    finished: asyncio.Event
    replies: int = 0


def _api(base: str, method: str, path: str, body: Any = None, token: str | None = None) -> Any:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(  # noqa: S310 - fixed local backend URL
        base + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        raw = response.read()
    return json.loads(raw) if raw else None


async def _speak(source: rtc.AudioSource, tts: Any, text: str) -> None:
    async for chunk in tts.synthesize(text):
        await source.capture_frame(chunk.frame)
    await source.wait_for_playout()


async def run(args: argparse.Namespace) -> int:
    base = args.backend_url.rstrip("/")
    access = _api(
        base, "POST", "/api/v1/auth/login", {"email": args.email, "password": args.password}
    )["access_token"]
    session = _api(base, "POST", "/api/v1/voice/sessions", {"lead_id": args.lead_id}, token=access)
    call_id = session["call_id"]
    print(f"call {call_id} | scenario {args.scenario} | barge-in {args.barge_in}")

    turns = AgentTurns(started=asyncio.Event(), finished=asyncio.Event())
    room = rtc.Room()
    pending: set[asyncio.Future[None]] = set()

    def on_text_stream(reader: rtc.TextStreamReader, participant: str) -> None:
        if participant.startswith("user-"):
            return  # the prospect's own transcription

        async def consume() -> None:
            turns.started.set()
            await reader.read_all()
            attributes = reader.info.attributes or {}
            if attributes.get("lk.transcription_final") in ("true", None):
                turns.replies += 1
                turns.finished.set()

        future = asyncio.ensure_future(consume())
        pending.add(future)
        future.add_done_callback(pending.discard)

    room.register_text_stream_handler(TRANSCRIPTION_TOPIC, on_text_stream)
    await room.connect(args.livekit_url, session["token"])

    source = rtc.AudioSource(SAMPLE_RATE, 1)
    track = rtc.LocalAudioTrack.create_audio_track("prospect-mic", source)
    await room.local_participant.publish_track(
        track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    )

    async with aiohttp.ClientSession() as http:
        options = SpeechOptions(
            stt_provider="deepgram",
            tts_provider="cartesia",
            stt_model="nova-3",
            stt_language="multi",
            tts_model=None,
            tts_voice=args.voice,
            tts_language="en",
        )
        tts = build_tts(options, http_session=http)

        await asyncio.wait_for(turns.finished.wait(), timeout=30)  # the greeting
        for index, line in enumerate(SCENARIOS[args.scenario]):
            await asyncio.sleep(0.6)  # a natural pause before answering
            turns.started.clear()
            turns.finished.clear()
            print(f"  prospect: {line}")
            await _speak(source, tts, line)
            if args.barge_in and index == 1:
                await asyncio.wait_for(turns.started.wait(), timeout=20)
                await asyncio.sleep(1.0)  # let the agent get a few words out, then cut in
                turns.finished.clear()
                print("  prospect (interrupting): Sorry, hold on, let me stop you there.")
                await _speak(source, tts, "Sorry, hold on, let me stop you there.")
            await asyncio.wait_for(turns.finished.wait(), timeout=30)

    await asyncio.sleep(1.0)
    await room.disconnect()
    await asyncio.sleep(args.settle_seconds)  # the worker reports metrics as the call ends

    call = _api(base, "GET", f"/api/v1/voice/calls/{call_id}", token=access)
    latency = call["latency"]
    print(json.dumps({"status": call["status"], "latency": latency}, indent=2))
    if args.barge_in and latency["interrupted_turns"] < 1:
        print("FAIL: the interruption was not registered")
        return 1
    if latency["meets_target"] is not True:
        print("FAIL: latency target missed (or not measured)")
        return 1
    print("PASS")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backend-url", default=os.environ.get("AUREVIA_BACKEND_URL", ""))
    parser.add_argument("--livekit-url", default=os.environ.get("LIVEKIT_URL", ""))
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="skeptical")
    parser.add_argument("--barge-in", action="store_true")
    parser.add_argument("--lead-id", default=None, help="lead to call (memory is kept per lead)")
    parser.add_argument("--voice", default=None, help="TTS voice id for the prospect")
    parser.add_argument("--settle-seconds", type=float, default=6.0)
    args = parser.parse_args()
    started = time.monotonic()
    code = asyncio.run(run(args))
    print(f"finished in {time.monotonic() - started:.0f}s")
    sys.exit(code)


if __name__ == "__main__":
    main()
