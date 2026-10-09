from __future__ import annotations

import ast
import asyncio
import io
import logging
from pathlib import Path
from typing import Any

import pytest
from livekit.agents import stt, tts

from aurevia_voice import redaction
from aurevia_voice.speech_providers import (
    SpeechConfigError,
    SpeechOptions,
    build_stt,
    build_tts,
    missing_keys,
)

# Obviously fake, test-only values.
FAKE_DEEPGRAM = "dg-test-key-0000000000"
FAKE_CARTESIA = "sk_car_test_0000000000"
ENV = {"DEEPGRAM_API_KEY": FAKE_DEEPGRAM, "CARTESIA_API_KEY": FAKE_CARTESIA}

OPTIONS = SpeechOptions(
    stt_provider="deepgram",
    tts_provider="cartesia",
    stt_model="nova-3",
    stt_language="multi",
    tts_model=None,
    tts_voice=None,
    tts_language="en",
)
SRC = Path(__file__).resolve().parents[1] / "src" / "aurevia_voice"


def test_missing_keys_are_named_not_valued() -> None:
    assert missing_keys("deepgram", "cartesia", {}) == ["DEEPGRAM_API_KEY", "CARTESIA_API_KEY"]
    assert missing_keys("deepgram", "cartesia", {"DEEPGRAM_API_KEY": "  "}) == [
        "DEEPGRAM_API_KEY",
        "CARTESIA_API_KEY",
    ]
    assert missing_keys("deepgram", "cartesia", ENV) == []


def test_builds_deepgram_and_cartesia_behind_livekit_interfaces() -> None:
    async def build() -> tuple[stt.STT[Any], tts.TTS[Any]]:
        return build_stt(OPTIONS, ENV), build_tts(OPTIONS, ENV)

    speech_to_text, text_to_speech = asyncio.run(build())
    assert isinstance(speech_to_text, stt.STT) and "deepgram" in speech_to_text.label.lower()
    assert isinstance(text_to_speech, tts.TTS) and "cartesia" in text_to_speech.label.lower()


def test_missing_key_error_names_the_variable() -> None:
    with pytest.raises(SpeechConfigError, match="DEEPGRAM_API_KEY is not set"):
        build_stt(OPTIONS, {"CARTESIA_API_KEY": FAKE_CARTESIA})
    with pytest.raises(SpeechConfigError) as exc:
        build_tts(OPTIONS, {"DEEPGRAM_API_KEY": FAKE_DEEPGRAM})
    assert "CARTESIA_API_KEY" in str(exc.value) and FAKE_DEEPGRAM not in str(exc.value)


def test_log_redaction_covers_messages_args_and_tracebacks() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("test.redaction")
    logger.addHandler(handler)
    previous = logging.getLogRecordFactory()
    try:
        redaction.install_log_redaction(ENV)
        logger.error("key in message %s", FAKE_DEEPGRAM)
        try:
            raise RuntimeError(f"vendor said: bad key {FAKE_CARTESIA}")
        except RuntimeError:
            logger.exception("vendor failure")
    finally:
        logging.setLogRecordFactory(previous)
        redaction._original_factory = None
        logger.removeHandler(handler)
    output = stream.getvalue()
    assert FAKE_DEEPGRAM not in output and FAKE_CARTESIA not in output
    assert output.count("[REDACTED]") == 2
    assert "vendor failure" in output and "RuntimeError" in output


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_only_speech_providers_imports_speech_vendors() -> None:
    offenders = {
        path.name: sorted(n for n in _imports(path) if n.startswith("livekit.plugins"))
        for path in SRC.glob("*.py")
        if path.name != "speech_providers.py"
    }
    assert {name: found for name, found in offenders.items() if found} == {}


def test_worker_never_imports_a_model_sdk() -> None:
    model_sdks = ("anthropic", "google.genai", "openai")
    found = {
        path.name: sorted(n for n in _imports(path) if n.startswith(model_sdks))
        for path in SRC.glob("*.py")
    }
    assert {name: names for name, names in found.items() if names} == {}
