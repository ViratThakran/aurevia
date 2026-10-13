"""Join a real browser-style call and report what the voice worker publishes on failures.

A manual end-to-end check for the Test Call error handling (local development only):

    python -m aurevia_voice.check_status --email you@example.com --password '...'

It signs in, starts a browser session, joins the room without a microphone and waits for the
agent's greeting. If the voice service fails (for example Cartesia out of credits) the worker
publishes a ``voice_issue`` message on ``aurevia.voice_status``: this prints its category and
whether it carries the reply's words, then asks the worker to replay the audio (RPC) and prints
the answer. The script never prints tokens, and the reply text is shown as a length only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.request
from typing import Any

from livekit import rtc

TOPIC = "aurevia.voice_status"
RETRY_METHOD = "aurevia.retry_speech"


def _api(
    base: str, method: str, path: str, body: dict[str, Any] | None = None, token: str | None = None
) -> dict[str, Any]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(  # noqa: S310 - local dev URL
        base + path, data=data, headers=headers, method=method
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - local dev URL
        parsed: dict[str, Any] = json.loads(response.read() or b"{}")
        return parsed


async def run(args: argparse.Namespace) -> int:
    base = args.backend_url.rstrip("/")
    credentials = {"email": args.email, "password": args.password}
    login = _api(base, "POST", "/api/v1/auth/login", credentials)
    token = login["access_token"]
    session = _api(base, "POST", "/api/v1/voice/sessions", {"lead_id": None}, token=token)
    print(f"call {session['call_id'][:8]} started")

    events: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
    room = rtc.Room()
    pending: set[asyncio.Future[None]] = set()

    def on_stream(reader: rtc.TextStreamReader, participant: str) -> None:
        async def consume() -> None:
            raw = await reader.read_all()
            await events.put((participant, json.loads(raw)))

        future = asyncio.ensure_future(consume())
        pending.add(future)
        future.add_done_callback(pending.discard)

    room.register_text_stream_handler(TOPIC, on_stream)
    await room.connect(args.livekit_url, session["token"])
    print("joined; waiting for the greeting (up to 30 s)")
    try:
        agent, event = await asyncio.wait_for(events.get(), timeout=30)
    except TimeoutError:
        print("no voice_issue event: the voice service is working (or the agent did not speak)")
        await room.disconnect()
        return 0

    text = event.get("text")
    print(
        "voice_issue received:",
        {k: (f"<{len(text)} chars>" if k == "text" and text else v) for k, v in event.items()},
    )
    if event.get("retryable"):
        try:
            answer = await room.local_participant.perform_rpc(
                destination_identity=agent,
                method=RETRY_METHOD,
                payload=json.dumps({"id": event["id"]}),
                response_timeout=15,
            )
            print("retry answer:", answer)
        except Exception as exc:  # the same path the dashboard shows as "could not be reached"
            print("retry failed:", type(exc).__name__)
        try:
            _, again = await asyncio.wait_for(events.get(), timeout=10)
            print("after retry:", again.get("type"), again.get("category"))
        except TimeoutError:
            print("after retry: no further event")
    await room.disconnect()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-url", default=os.environ.get("AUREVIA_BACKEND_URL", ""))
    parser.add_argument("--livekit-url", default=os.environ.get("LIVEKIT_URL", ""))
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    sys.exit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
