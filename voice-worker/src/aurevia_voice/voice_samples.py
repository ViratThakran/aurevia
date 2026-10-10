"""Render the approved test sentences with candidate voices, for people to listen and compare.

    python -m aurevia_voice.voice_samples OUT_DIR [--voice ID ...]

Writes one WAV per voice and sentence. Choosing a voice is a listening decision: this only
produces the samples (see docs/02-voice/voice-quality-audit.md for the sentences and scoring).
"""

from __future__ import annotations

import argparse
import asyncio
import re
import wave
from pathlib import Path

import aiohttp

from aurevia_voice.speech_providers import SpeechOptions, build_tts

# Approved test sentences: (key, language code for the TTS, text).
SENTENCES: tuple[tuple[str, str, str], ...] = (
    (
        "1-intro-en",
        "en",
        "Hi, this is Aria, an AI assistant calling from Sunrise Insurance Brokers. We help "
        "businesses in Pune compare group health plans. Is now a good time?",
    ),
    (
        "2-dates-en",
        "en",
        "Would Monday, the twelfth of October, at ten thirty in the morning work? It's a "
        "twenty-minute call with our specialist.",
    ),
    (
        "3-hindi",
        "hi",
        "नमस्ते, मैं आरिया हूँ, सनराइज़ इंश्योरेंस ब्रोकर्स की ओर से एक एआई असिस्टेंट। "
        "क्या अभी बात करने का सही समय है?",
    ),
    (
        "4-hinglish",
        "hi",
        "Aapki team mein kitne log hain? Agar renewal do mahine mein hai, toh abhi plans "
        "compare karna sahi rahega.",
    ),
)

# Candidates: the plugin default the agents use today, and Indian voices from Cartesia's
# catalogue (listed via its voices API, 2026-10-10).
CANDIDATES: dict[str, str] = {
    "katie-current-default": "f786b574-daa5-4673-aa0c-cbe3e8534c02",
    "siya-hi-female": "4459a9a5-69d6-4680-b970-e13dc51845b6",
    "meera-hi-female": "a81fccdc-5595-4dfc-ae76-4de6a515b8a2",
    "dev-hi-male": "910fb75e-1d20-4840-ac63-ac6b26a71bdc",
}


async def render(out: Path, voices: dict[str, str]) -> None:
    async with aiohttp.ClientSession() as http:
        for name, voice_id in voices.items():
            for key, language, text in SENTENCES:
                options = SpeechOptions(
                    stt_provider="deepgram",
                    tts_provider="cartesia",
                    stt_model="nova-3",
                    stt_language="multi",
                    tts_model=None,
                    tts_voice=voice_id,
                    tts_language=language,
                )
                tts = build_tts(options, http_session=http)
                frames = [chunk.frame async for chunk in tts.synthesize(text)]
                path = out / f"{name}__{key}.wav"
                with wave.open(str(path), "wb") as wav:
                    wav.setnchannels(frames[0].num_channels)
                    wav.setsampwidth(2)
                    wav.setframerate(frames[0].sample_rate)
                    wav.writeframes(b"".join(bytes(f.data) for f in frames))
                print(f"wrote {path.name}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="aurevia_voice.voice_samples")
    parser.add_argument("out")
    parser.add_argument("--voice", action="append", help="extra voice id (name=id)")
    args = parser.parse_args()
    voices = dict(CANDIDATES)
    for item in args.voice or []:
        name, _, voice_id = item.partition("=")
        voices[re.sub(r"[^a-z0-9-]", "-", name.lower())] = voice_id
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    asyncio.run(render(out, voices))


if __name__ == "__main__":
    main()
