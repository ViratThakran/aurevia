"""Voice worker entrypoint.

Run: ``python -m aurevia_voice.main start`` (or ``dev`` for auto-reload).

The backend creates a LiveKit room per call and dispatches this agent into it with the call's
id and per-call token as job metadata. The worker then: starts the call with the backend,
speaks the agent's greeting, and lets LiveKit run listening, turn detection and interruption
while every reply comes from the backend. On the way out it reports STT/TTS usage and ends
the call.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sys
from collections.abc import AsyncIterable, AsyncIterator, Callable, Mapping
from typing import Any

from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    ModelSettings,
    TurnHandlingOptions,
    cli,
)
from livekit.agents.metrics.usage import STTModelUsage, TTSModelUsage
from livekit.agents.stt import STTError
from livekit.agents.tts import TTSError
from livekit.agents.voice.agent_session import SessionConnectOptions

from aurevia_voice.backend_client import BackendClient, BackendError
from aurevia_voice.config import WorkerSettings
from aurevia_voice.language import Language, LanguageSwitch
from aurevia_voice.llm_bridge import BackendLLM
from aurevia_voice.phone import wait_for_answer
from aurevia_voice.redaction import install_log_redaction
from aurevia_voice.silence import SilenceTracker
from aurevia_voice.speech_providers import (
    SpeechOptions,
    build_stt,
    build_tts,
    load_vad,
    missing_keys,
)
from aurevia_voice.spoken import natural_chunks
from aurevia_voice.transcript import TranscriptCollector
from aurevia_voice.turn_metrics import TurnMetricsCollector
from aurevia_voice.voice_status import (
    RETRY_METHOD,
    Source,
    VoiceStatusReporter,
)
from aurevia_voice.voice_status import TOPIC as STATUS_TOPIC

logger = logging.getLogger("aurevia.voice")

settings = WorkerSettings()  # type: ignore[call-arg]  # backend_url comes from the environment


def prewarm(proc: JobProcess) -> None:
    # Loading the voice activity model once per process keeps call start fast.
    install_log_redaction()  # job processes log too
    proc.userdata["vad"] = load_vad()


server = AgentServer(setup_fnc=prewarm)


async def _finish(
    session: AgentSession[Any],
    backend: BackendClient,
    collector: TurnMetricsCollector,
    transcript: TranscriptCollector,
    reason: str,
) -> None:
    try:
        if collector.turns:
            await backend.report_turn_metrics(collector.turns)
        if transcript.lines:
            await backend.save_transcript(transcript.lines)
        for usage in session.usage.model_usage:
            if isinstance(usage, STTModelUsage):
                await backend.report_usage(
                    kind="stt",
                    provider=usage.provider,
                    model=usage.model,
                    audio_seconds=usage.audio_duration,
                )
            elif isinstance(usage, TTSModelUsage):
                await backend.report_usage(
                    kind="tts",
                    provider=usage.provider,
                    model=usage.model,
                    characters=usage.characters_count,
                )
        await backend.end(_reason_code(reason))
    except BackendError:
        logger.exception("Could not close the call with the backend")
    finally:
        await backend.aclose()


def turn_handling(config: WorkerSettings) -> TurnHandlingOptions:
    return {
        "endpointing": {
            "mode": config.endpointing_mode,
            "min_delay": config.endpointing_min_delay,
            "max_delay": config.endpointing_max_delay,
        },
        "preemptive_generation": {
            "enabled": config.preemptive_generation,
            "preemptive_tts": config.preemptive_tts,
        },
        "interruption": {"min_duration": config.interruption_min_duration},
    }


# Consecutive unrecoverable provider errors a browser call survives, so the caller can fix the
# provider and retry the audio. Phone calls keep the SDK default (3): a prospect on the line
# must not be left in silence while the provider is down.
BROWSER_MAX_UNRECOVERABLE_ERRORS = 20


def connect_options(is_phone: bool) -> SessionConnectOptions:
    if is_phone:
        return SessionConnectOptions()
    return SessionConnectOptions(max_unrecoverable_errors=BROWSER_MAX_UNRECOVERABLE_ERRORS)


class SpeakingAgent(Agent):
    """Replies come from the backend; before each one is spoken, the TTS language is matched
    to the reply's words (English or Hindi/Hinglish)."""

    def __init__(
        self,
        language: LanguageSwitch,
        on_failure: Callable[[BaseException, str], None] | None = None,
        pronunciations: Mapping[str, str] | None = None,
        natural_speech: bool = False,
    ) -> None:
        # The instructions are a placeholder: the backend builds the real prompt every turn.
        super().__init__(instructions="Replies are generated by the Aurevia backend.")
        self._language = language
        self._on_failure = on_failure
        # WP-11.5 (off by default): shape only what the voice hears; the transcript keeps
        # the original words (``said`` below records them before shaping).
        self._natural_speech = natural_speech
        self._pronunciations = dict(pronunciations or {})

    async def tts_node(
        self, text: AsyncIterable[str], model_settings: ModelSettings
    ) -> AsyncIterator[rtc.AudioFrame]:
        primed = await self._language.ready(text)
        said: list[str] = []

        async def recorded() -> AsyncIterator[str]:
            async for chunk in primed:
                said.append(chunk)
                yield chunk

        voiced: AsyncIterable[str] = recorded()
        if self._natural_speech:
            voiced = natural_chunks(voiced, self._pronunciations)
        try:
            async for frame in Agent.default.tts_node(self, voiced, model_settings):
                yield frame
        except asyncio.CancelledError:
            raise  # the prospect interrupted: not a failure
        except Exception as exc:
            if self._on_failure is None:
                raise
            # The words were generated but could not be spoken. Keep the rest of the reply
            # (it is still streaming in), tell the caller, and let the call carry on.
            with contextlib.suppress(Exception):
                async with asyncio.timeout(20):
                    async for chunk in primed:
                        said.append(chunk)
            self._on_failure(exc, "".join(said))


def _reason_code(reason: str) -> str:
    code = "".join(c if c.isalnum() else "_" for c in reason.lower()).strip("_")
    return code[:100] or "unknown"


@server.rtc_session(agent_name=settings.agent_name)
async def entrypoint(ctx: JobContext) -> None:
    metadata = json.loads(ctx.job.metadata or "{}")
    backend = BackendClient(
        base_url=settings.backend_url,
        call_id=metadata["call_id"],
        call_token=metadata["call_token"],
    )
    is_phone = metadata.get("channel") == "phone"
    if is_phone:
        # Join first and stay silent until the phone is picked up: nobody hears a greeting
        # spoken to a ringing line, and an unanswered call never counts as started.
        await ctx.connect()
        if not await wait_for_answer(ctx.room, settings.answer_timeout_seconds):
            logger.info("Phone not answered", extra={"call_id": metadata["call_id"]})
            try:
                await backend.end("not_answered", failed=True)
            finally:
                await backend.aclose()
            ctx.shutdown(reason="not_answered")
            return
    opening = await backend.start()
    logger.info("Call started", extra={"call_id": metadata["call_id"]})

    try:
        speech = SpeechOptions(
            stt_provider=settings.stt_provider,
            tts_provider=settings.tts_provider,
            stt_model=settings.stt_model,
            stt_language=settings.stt_language,
            tts_model=settings.tts_model,
            tts_voice=opening.voice or settings.tts_voice,
            tts_language=opening.language.split("-")[0],
            stt_keyterms=tuple(settings.stt_keyterms),
        )
        tts = build_tts(speech)

        def set_language(language: Language) -> None:
            tts.update_options(language=language)  # type: ignore[attr-defined]
            logger.info(
                "TTS language switched",
                extra={"call_id": metadata["call_id"], "language": language},
            )

        async def publish(payload: dict[str, Any], destination: str | None) -> None:
            await ctx.room.local_participant.send_text(
                json.dumps(payload),
                topic=STATUS_TOPIC,
                destination_identities=[destination] if destination else None,
            )

        async def say_again(words: str) -> None:
            # Speaks the stored words only: no model call, so no tool can run again.
            await session.say(words, add_to_chat_ctx=False).wait_for_playout()

        reporter = VoiceStatusReporter(
            call_id=metadata["call_id"],
            provider=str(getattr(tts, "provider", "voice")),
            publish=publish,
            say=say_again,
        )

        def on_voice_failure(exc: BaseException, words: str) -> None:
            reporter.report(exc, source="voice", text=words)

        speaking = SpeakingAgent(
            LanguageSwitch(speech.tts_language, set_language),
            on_failure=on_voice_failure,
            pronunciations=settings.pronunciations,
            natural_speech=settings.natural_speech,
        )
        session: AgentSession[Any] = AgentSession(
            stt=build_stt(speech),
            tts=tts,
            vad=ctx.proc.userdata["vad"],
            llm=BackendLLM(backend),
            turn_handling=turn_handling(settings),
            user_away_timeout=settings.silence_timeout_seconds,
            conn_options=connect_options(is_phone),
        )

        def on_error(event: Any) -> None:
            err = event.error
            if getattr(err, "recoverable", True) or isinstance(err, TTSError):
                return  # retried by the SDK, or reported with its words by the speaking agent
            source: Source = "listening" if isinstance(err, STTError) else "model"
            reporter.report(getattr(err, "error", None), source=source)

        session.on("error", on_error)
        if not is_phone:
            await ctx.connect()

        async def on_retry(data: rtc.RpcInvocationData) -> str:
            return await reporter.handle_rpc(data.payload)

        ctx.room.local_participant.register_rpc_method(RETRY_METHOD, on_retry)

        # A failure can happen before the caller's browser has joined: tell it when it does.
        def on_participant(participant: rtc.RemoteParticipant) -> None:
            # Only the caller's browser: not the phone line, not other agents.
            if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD:
                reporter.replay_to(participant.identity)

        ctx.room.on("participant_connected", on_participant)
        await session.start(agent=speaking, room=ctx.room)
    except Exception:
        # The call was started with the backend; never leave it looking in progress.
        logger.exception("Voice session setup failed", extra={"call_id": metadata["call_id"]})
        try:
            await backend.end("worker_error", failed=True)
        finally:
            await backend.aclose()
        raise

    silence = SilenceTracker(reprompts_before_hang_up=settings.silence_reprompts)

    async def end_after_goodbye() -> None:
        handle = session.say(settings.silence_goodbye_text, allow_interruptions=False)
        await handle.wait_for_playout()
        ctx.shutdown(reason="prospect_silent")

    def on_user_state(event: Any) -> None:
        action = silence.on_user_state(event.new_state)
        if action == "reprompt":
            session.say(settings.silence_reprompt_text)
        elif action == "hang_up":
            tasks.add(task := asyncio.create_task(end_after_goodbye()))
            task.add_done_callback(tasks.discard)

    tasks: set[asyncio.Task[None]] = set()
    session.on("user_state_changed", on_user_state)

    collector = TurnMetricsCollector()
    transcript = TranscriptCollector()

    def on_item(event: Any) -> None:
        collector.add(event.item)
        transcript.add(event.item)

    session.on("conversation_item_added", on_item)

    async def on_shutdown(reason: str) -> None:
        await _finish(session, backend, collector, transcript, reason)

    ctx.add_shutdown_callback(on_shutdown)
    session.on("close", lambda event: ctx.shutdown(reason=str(event.reason)))
    session.say(opening.greeting)


def main() -> None:
    install_log_redaction()
    serving = len(sys.argv) > 1 and sys.argv[1] in ("start", "dev", "connect")
    missing = missing_keys(settings.stt_provider, settings.tts_provider)
    if serving and missing:
        # A worker that cannot speak or listen must not accept calls.
        sys.exit(f"Refusing to start: set {', '.join(missing)}")
    cli.run_app(server)


if __name__ == "__main__":
    main()
