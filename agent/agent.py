import asyncio
import json
import logging
import os
import time
import urllib.request

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    TurnHandlingOptions,
    cli,
    room_io,
)
from livekit.agents.llm import StopResponse, function_tool
from livekit.plugins import noise_cancellation, openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from qwen_asr_realtime_stt import QwenASRRealtimeSTT
from qwen_tts import QwenTTS, resolve_qwen_tts_api_url
from realtime.base import RealtimeEvent, RealtimeRuntimeConfig, RealtimeRuntimeError
from realtime.bridge import LiveKitAudioBridge
from realtime.factory import create_realtime_provider

load_dotenv(".env")
logger = logging.getLogger("agent")


def _fetch_runtime_secrets(agent_id: str) -> dict:
    api_base = os.getenv("API_BASE_URL", "http://api:8000").rstrip("/")
    secret = os.getenv("WORKER_INTERNAL_SECRET") or os.getenv("JWT_SECRET", "")
    if not secret:
        raise RuntimeError("WORKER_INTERNAL_SECRET is not configured")
    url = f"{api_base}/api/internal/worker/agent-runtime/{agent_id}"
    req = urllib.request.Request(url, headers={"X-Worker-Secret": secret})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _worker_headers() -> dict[str, str]:
    secret = os.getenv("WORKER_INTERNAL_SECRET") or os.getenv("JWT_SECRET", "")
    return {"X-Worker-Secret": secret, "Content-Type": "application/json"}


def _sanitize_agent_config_for_log(agent_config_str: str | None) -> str | None:
    if not agent_config_str:
        return agent_config_str

    try:
        config = json.loads(agent_config_str)
    except json.JSONDecodeError:
        return "<invalid agent_config>"

    def redact(value):
        if isinstance(value, dict):
            return {
                key: "***" if key.lower() in {
                    "api_key", "apikey", "voice_id", "voiceid", "provider_voice_id", "providervoiceid",
                } else redact(val)
                for key, val in value.items()
            }
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value

    return json.dumps(redact(config), ensure_ascii=False)


def _parse_worker_metadata(raw_metadata: str | None) -> dict[str, str]:
    """Return the small, non-secret dispatch contract embedded in a LK token.

    Provider credentials and voice bindings are intentionally fetched from the
    internal Worker endpoint after dispatch.  Do not add defaults here: a bad
    token must not accidentally select a public environment configuration.
    """
    if not raw_metadata:
        raise RuntimeError("Worker dispatch metadata is missing")
    try:
        parsed = json.loads(raw_metadata)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Worker dispatch metadata is invalid") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Worker dispatch metadata is invalid")
    metadata = {key: parsed.get(key) for key in ("agent_id", "call_log_id", "runtime_mode")}
    if any(not isinstance(value, str) or not value.strip() for value in metadata.values()):
        raise RuntimeError("Worker dispatch metadata is incomplete")
    if metadata["runtime_mode"] not in {"pipeline", "realtime"}:
        raise RuntimeError("Worker dispatch mode is unsupported")
    return metadata


def _safe_failure_reason(error: Exception) -> str:
    """Keep Worker callback diagnostics useful without serializing secrets."""
    if isinstance(error, RealtimeRuntimeError):
        return "realtime_provider_error"
    return "worker_runtime_error"


def _write_call_log_end(
    call_log_id: str,
    *,
    status: str,
    duration_seconds: int,
    transcript_turns: list[dict] | None = None,
    failure_stage: str | None = None,
    failure_reason: str | None = None,
) -> None:
    """Best-effort call log callback. Values are all diagnostics-safe."""
    api_base = os.getenv("API_BASE_URL", "http://api:8000")
    url = f"{api_base}/api/call/admin/call-logs/{call_log_id}/end"
    payload = {
        "status": status,
        "duration_seconds": duration_seconds,
        "transcript": json.dumps(transcript_turns or [], ensure_ascii=False),
        "failure_stage": failure_stage,
        "failure_reason": failure_reason,
    }
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers=_worker_headers(), method="PATCH")
        urllib.request.urlopen(req, timeout=5)
        logger.info("Call log %s ended, status=%s, turns=%s", call_log_id, status, len(transcript_turns or []))
    except Exception:
        # Do not interpolate an HTTP exception here: proxy messages sometimes
        # include request headers and would turn a logging failure into a leak.
        logger.warning("Failed to update call log %s", call_log_id)


def _register_call_log_completion(ctx: JobContext, call_log_id: str, transcript_turns: list[dict], started_at: float):
    """Register idempotent room-end callbacks shared by pipeline and realtime."""
    call_ended = False

    def end_call_log(
        *,
        status: str = "completed",
        failure_stage: str | None = None,
        failure_reason: str | None = None,
    ) -> None:
        nonlocal call_ended
        if call_ended:
            return
        call_ended = True
        _write_call_log_end(
            call_log_id,
            status=status,
            duration_seconds=int(time.time() - started_at),
            transcript_turns=transcript_turns,
            failure_stage=failure_stage,
            failure_reason=failure_reason,
        )

    @ctx.room.on("participant_disconnected")
    def _on_participant_left(participant):
        end_call_log()

    @ctx.room.on("disconnected")
    def _on_disconnected():
        end_call_log()

    return end_call_log


class CallMeAgent(Agent):
    def __init__(self, system_prompt: str) -> None:
        super().__init__(instructions=system_prompt)


def _make_end_call_tool(event: asyncio.Event):
    @function_tool()
    async def end_call() -> str:
        """当用户明确表达告别意图（如说"再见"、"拜拜"、"先这样"、"挂了"等）时调用此工具。调用后请简短友好告别，通话将自动挂断。"""
        event.set()
        raise StopResponse()
    return end_call


async def _handle_end_call(should_end: asyncio.Event, session: AgentSession, room, logger):
    """Background task: wait for end-call signal, wait for agent to finish speaking, then disconnect."""
    await should_end.wait()
    logger.info("End call signal received...")

    # Wait for agent to finish speaking (if currently speaking/thinking)
    if session.agent_state in ("speaking", "thinking"):
        logger.info(f"Agent is {session.agent_state}, waiting for speech to finish...")
        done_event = asyncio.Event()

        def _on_agent_state(ev):
            if ev.new_state not in ("speaking", "thinking"):
                done_event.set()

        session.on("agent_state_changed", _on_agent_state)
        try:
            await asyncio.wait_for(done_event.wait(), timeout=15.0)
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for agent to finish speaking")

    await asyncio.sleep(0.5)  # small buffer
    logger.info("Disconnecting room after end_call")
    await room.disconnect()


USER_FAREWELL_KEYWORDS = ["再见", "拜拜", "掰掰", "拜", "挂了", "先这样", "就这样", "下次再聊", "回头再聊", "bye", "goodbye",
    "大呆"]  # "大呆"/"掰掰" = common Deepgram variants of "拜拜"
AGENT_FAREWELL_KEYWORDS = ["再见", "拜拜", "bye", "goodbye", "下次再聊", "回头再聊"]


async def _monitor_farewell(
    should_end: asyncio.Event,
    session: AgentSession,
    logger,
    background_tasks: list[asyncio.Task],
):
    """Two-way farewell detection:
    1. User says goodbye (STT keyword) → wait for LLM to handle it, or force disconnect after 5s.
    2. Agent says goodbye (LLM response contains farewell) → disconnect after playout.
    """
    farewell_pending = False
    fallback_timer: asyncio.Task | None = None

    def _on_user_input(ev):
        nonlocal farewell_pending, fallback_timer
        if should_end.is_set() or farewell_pending:
            return
        text = ev.transcript.strip().lower()
        if ev.is_final:
            logger.info(f"User transcript (final): {text}")
        for kw in USER_FAREWELL_KEYWORDS:
            if kw in text:
                logger.info(f"User farewell '{kw}' detected, waiting for LLM to handle")
                farewell_pending = True
                fallback_timer = _track_background_task(background_tasks, asyncio.create_task(_fallback()))
                return

    async def _fallback():
        await asyncio.sleep(2.0)
        if farewell_pending and not should_end.is_set():
            logger.info("LLM did not handle farewell in time, forcing disconnect")
            should_end.set()

    def _on_conversation_item(ev):
        nonlocal farewell_pending, fallback_timer
        if should_end.is_set():
            return
        if hasattr(ev.item, "content") and hasattr(ev.item, "role"):
            if ev.item.role == "assistant" and ev.item.content:
                content = ev.item.content
                if isinstance(content, list):
                    text = " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
                else:
                    text = str(content)
                text = text.strip().lower()
                for kw in AGENT_FAREWELL_KEYWORDS:
                    if kw in text:
                        logger.info(f"Agent farewell '{kw}' in response, will disconnect after playout")
                        farewell_pending = True
                        if fallback_timer and not fallback_timer.done():
                            fallback_timer.cancel()
                        return

    def _on_agent_state(ev):
        nonlocal farewell_pending
        # After farewell is detected, wait for agent to finish speaking (not speaking/thinking)
        if farewell_pending and ev.new_state not in ("speaking", "thinking") and not should_end.is_set():
            logger.info("Agent finished speaking after farewell, ending call now")
            should_end.set()

    session.on("user_input_transcribed", _on_user_input)
    session.on("conversation_item_added", _on_conversation_item)
    session.on("agent_state_changed", _on_agent_state)
    try:
        await should_end.wait()
    finally:
        if fallback_timer is not None:
            await _cancel_and_wait([fallback_timer])


async def _monitor_silence(
    should_end: asyncio.Event,
    session: AgentSession,
    logger,
    background_tasks: list[asyncio.Task],
):
    """Monitor user silence: prompt once after away timeout, end call if still no response."""
    silence_prompted = False
    prompt_task: asyncio.Task | None = None

    def _on_user_state(ev):
        nonlocal silence_prompted, prompt_task

        if should_end.is_set():
            return

        if ev.new_state == "away":
            if not silence_prompted:
                silence_prompted = True
                prompt_task = _track_background_task(background_tasks, asyncio.create_task(_prompt_and_wait()))
        elif ev.new_state == "speaking":
            silence_prompted = False
            if prompt_task and not prompt_task.done():
                prompt_task.cancel()

    async def _prompt_and_wait():
        nonlocal silence_prompted
        try:
            handle = session.say("你还在吗？", allow_interruptions=True)
            await handle.wait_for_playout()
            for _ in range(20):  # 10 seconds, checking every 0.5s
                if should_end.is_set() or not silence_prompted:
                    return
                await asyncio.sleep(0.5)
            if not should_end.is_set():
                logger.info("No response after silence prompt, ending call")
                should_end.set()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"Silence prompt failed: {e}")

    session.on("user_state_changed", _on_user_state)
    try:
        await should_end.wait()
    finally:
        if prompt_task is not None:
            await _cancel_and_wait([prompt_task])


def _idle_process_count() -> int:
    """Return a safe, explicit idle-worker count for constrained servers.

    LiveKit's production default keeps ten prewarmed child processes.  Each
    process loads VAD during prewarm, which is expensive on this deployment.
    Keep one ready by default; deployments that prioritize memory over cold
    starts can set ``AGENT_IDLE_PROCESSES=0`` in their server-local .env.
    """
    raw = os.getenv("AGENT_IDLE_PROCESSES", "1")
    try:
        count = int(raw)
    except (TypeError, ValueError):
        logger.warning("Invalid AGENT_IDLE_PROCESSES value; using 1")
        return 1
    if count < 0:
        logger.warning("Negative AGENT_IDLE_PROCESSES value; using 1")
        return 1
    return count


async def _cancel_and_wait(tasks: list[asyncio.Task]) -> None:
    """Cancel Worker-owned detached tasks and consume their termination."""
    unique_tasks = list(dict.fromkeys(tasks))
    for task in unique_tasks:
        if not task.done():
            task.cancel()
    if unique_tasks:
        await asyncio.gather(*unique_tasks, return_exceptions=True)


def _track_background_task(tasks: list[asyncio.Task], task: asyncio.Task) -> asyncio.Task:
    """Keep only active detached tasks, while consuming late task failures."""
    tasks.append(task)

    def _remove_completed_task(completed: asyncio.Task) -> None:
        try:
            failed = completed.exception()
        except asyncio.CancelledError:
            pass
        else:
            if failed is not None:
                logger.warning("A pipeline background task stopped unexpectedly")
        try:
            tasks.remove(completed)
        except ValueError:
            pass

    task.add_done_callback(_remove_completed_task)
    return task


def _register_pipeline_cleanup(
    ctx: JobContext,
    session: AgentSession,
    background_tasks: list[asyncio.Task],
) -> None:
    """Tie detached pipeline tasks to the LiveKit job shutdown lifecycle."""
    cleanup_lock = asyncio.Lock()
    cleaned = False

    async def _cleanup() -> None:
        nonlocal cleaned
        async with cleanup_lock:
            if cleaned:
                return
            cleaned = True
            await _cancel_and_wait(background_tasks)
            await session.aclose()

    ctx.add_shutdown_callback(_cleanup)


server = AgentServer(num_idle_processes=_idle_process_count())


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


async def run_pipeline_call(ctx: JobContext, runtime: dict, call_log_id: str) -> None:
    """Run the existing STT → LLM → TTS session using Worker-private runtime."""
    ctx.log_context_fields = {"room": ctx.room.name}

    t0 = time.time()
    _bg_tasks: list[asyncio.Task] = []
    # Keep the old metadata fast path: overlap the one room connection with
    # provider initialization, but never create a second connection.
    connect_task = asyncio.create_task(ctx.connect())
    config = runtime
    system_prompt = config.get("system_prompt", os.getenv("DEFAULT_SYSTEM_PROMPT", "你是一位贴心的语音智能助手。"))
    voice_id = config.get("voice_id")

    # Global constraint: keep responses short for voice conversation
    system_prompt = system_prompt.strip() + " 请用口语简洁回答，控制在2-3句话以内。"
    system_prompt += " 你可以使用end_call工具：当用户表达告别意图（如说再见、拜拜等），请在友好简短告别后调用end_call挂断电话。"

    # LLM — use model_config from token if available, otherwise .env default
    default_llm_temp = float(os.getenv("DEFAULT_LLM_TEMPERATURE", "0.7"))
    llm_configured = False
    if config.get("model_config"):
        mc = config["model_config"]
        mc_provider = mc["provider"]
        if mc_provider == "deepseek":
            llm = openai.LLM.with_deepseek(
                model=mc["model"],
                api_key=mc["api_key"],
                temperature=mc.get("temperature", default_llm_temp),
            )
            llm_configured = True
        elif mc_provider == "qwen":
            llm = openai.LLM(
                model=mc["model"],
                api_key=mc["api_key"],
                base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
                temperature=mc.get("temperature", default_llm_temp),
            )
            llm_configured = True
        else:
            logger.warning(f"Unknown model_config provider: {mc_provider}, falling back to .env")

    if not llm_configured:
        llm = openai.LLM(
            model="qwen-plus",
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            temperature=default_llm_temp,
        )
        llm_provider = "qwen"
    else:
        llm_provider = mc_provider

    # STT
    stt_provider = os.getenv("STT_PROVIDER", "livekit").strip().lower()
    if stt_provider == "qwen":
        stt = QwenASRRealtimeSTT.from_env()
    else:
        stt_model = os.getenv("STT_MODEL", "deepgram/nova-2").strip()
        stt_language = os.getenv("STT_LANGUAGE", "zh-CN").strip()
        from livekit.agents import inference
        stt = inference.STT(model=stt_model, language=stt_language)

    # TTS — use tts_config from token if available, otherwise .env default
    tts_configured = False
    if config.get("tts_config"):
        tc = config["tts_config"]
        tc_provider = tc["provider"]
        if tc_provider == "qwen":
            tts = QwenTTS(
                api_url=resolve_qwen_tts_api_url(tc["model"]),
                api_key=tc["api_key"],
                model=tc["model"],
                voice_id=voice_id,
            )
            tts_configured = True
        else:
            logger.warning(f"Unknown tts_config provider: {tc_provider}, falling back to .env")

    if not tts_configured:
        tts = QwenTTS(
            api_url=resolve_qwen_tts_api_url("qwen3-tts-flash-realtime"),
            api_key=os.getenv("DASHSCOPE_API_KEY", ""),
            model="qwen3-tts-flash-realtime",
            voice_id=voice_id,
        )
        tts_provider = "qwen"
    else:
        tts_provider = tc_provider

    await connect_task
    t_connect = time.time()
    logger.info(f"[timing] ctx.connect (parallel): {t_connect - t0:.2f}s total")

    logger.info("pipeline config", extra={
        "room": ctx.room.name,
        "llm_provider": llm_provider,
        "tts_provider": tts_provider,
    })
    logger.info(f"TTS created: model={tts.model}, voice_id=***, is_realtime={tts._is_realtime_model()}")
    t_init = time.time()
    logger.info(f"[timing] LLM/STT/TTS init + connect: {t_init - t0:.2f}s total")

    # End-call coordination: shared event between LLM tool and silence timeout
    _should_end = asyncio.Event()
    end_call_tool = _make_end_call_tool(_should_end)

    session = AgentSession(
        stt=stt,
        llm=llm,
        tts=tts,
        tools=[end_call_tool],
        turn_handling=TurnHandlingOptions(
            turn_detector=MultilingualModel(),
            vad=ctx.proc.userdata["vad"],
            endpointing={"min_delay": 0.3, "max_delay": 2.0},
        ),
        user_away_timeout=30.0,
    )

    # Collect conversation transcript (user + assistant turns)
    transcript_turns: list[dict] = []

    def _on_transcript_item(ev):
        if not hasattr(ev.item, "role") or not hasattr(ev.item, "content"):
            return
        role = ev.item.role
        if role not in ("user", "assistant"):
            return
        content = ev.item.content
        if isinstance(content, list):
            text = " ".join(
                p.get("text", "") if isinstance(p, dict) else str(p) for p in content
            )
        else:
            text = str(content) if content else ""
        if text.strip():
            transcript_turns.append({
                "role": role,
                "text": text.strip(),
                "time": round(time.time() - t0, 1),
            })

    session.on("conversation_item_added", _on_transcript_item)

    # Register before session.start so a fast participant departure is still
    # captured. Realtime uses the same helper below.
    _register_call_log_completion(ctx, call_log_id, transcript_turns, time.time())

    await session.start(
        agent=CallMeAgent(system_prompt=system_prompt),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: noise_cancellation.BVCTelephony()
                if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                else noise_cancellation.BVC(),
            ),
        ),
    )
    t_session = time.time()
    logger.info(f"[timing] session.start: {t_session - t_init:.2f}s (total {t_session - t0:.2f}s)")

    # Start background tasks for end-call detection
    _end_call_task = _track_background_task(
        _bg_tasks, asyncio.create_task(_handle_end_call(_should_end, session, ctx.room, logger))
    )
    _silence_task = _track_background_task(
        _bg_tasks, asyncio.create_task(_monitor_silence(_should_end, session, logger, _bg_tasks))
    )
    _farewell_task = _track_background_task(
        _bg_tasks, asyncio.create_task(_monitor_farewell(_should_end, session, logger, _bg_tasks))
    )

    # Agent speaks first: generate greeting via LLM as background task
    # (non-blocking so entrypoint returns immediately, avoiding timeout)
    async def _speak_greeting():
        from livekit.agents.llm import ChatContext, ChatMessage
        try:
            greeting_prompt = os.getenv(
                "INITIAL_GREETING_PROMPT",
                "通话刚刚接通。请根据你的人设，用中文向对方简短打招呼"
                "（包含自我介绍），询问对方需要什么。20字以内，纯文本不要动作描写。"
            )
            greeting_ctx = ChatContext()
            greeting_ctx.add_message(role="system", content=system_prompt)
            greeting_ctx.add_message(role="user", content=greeting_prompt)
            t_llm_start = time.time()
            greeting_stream = llm.chat(chat_ctx=greeting_ctx)
            greeting_text = ""
            async for chunk in greeting_stream:
                if chunk.delta and chunk.delta.content:
                    greeting_text += chunk.delta.content
            greeting_text = greeting_text.strip()
            t_greet = time.time()
            logger.info(f"[timing] LLM greeting: {t_greet - t_llm_start:.2f}s (total {t_greet - t0:.2f}s)")
            if greeting_text:
                logger.info(f"Initial greeting: {greeting_text}")
                await session.say(greeting_text, allow_interruptions=False)
            else:
                await session.say("你好，请问有什么可以帮助你的？", allow_interruptions=False)
            t_speak = time.time()
            logger.info(f"[timing] TTS speak greeting: {t_speak - t_greet:.2f}s (total {t_speak - t0:.2f}s)")
        except Exception as e:
            logger.warning(f"Failed to generate initial greeting: {e}")
            await session.say("你好，请问有什么可以帮助你的？", allow_interruptions=False)

    _greeting_task = _track_background_task(_bg_tasks, asyncio.create_task(_speak_greeting()))
    _register_pipeline_cleanup(ctx, session, _bg_tasks)


def _is_audio_track(track) -> bool:
    kind = getattr(track, "kind", None)
    audio_kind = getattr(getattr(rtc, "TrackKind", None), "KIND_AUDIO", None)
    return kind == audio_kind or str(kind).lower() in {"audio", "trackkind.kind_audio"}


async def run_realtime_call(ctx: JobContext, runtime: dict, call_log_id: str) -> list[dict]:
    """Bridge one full-duplex provider session to LiveKit without pipeline fallback."""
    realtime = runtime.get("realtime_config")
    required = ("provider", "model", "endpoint", "api_key", "voice_id")
    if not isinstance(realtime, dict) or any(not realtime.get(field) for field in required):
        raise RealtimeRuntimeError("Realtime runtime configuration is incomplete")

    config = RealtimeRuntimeConfig(
        provider=realtime["provider"],
        model=realtime["model"],
        endpoint=realtime["endpoint"],
        api_key=realtime["api_key"],
        provider_voice_id=realtime["voice_id"],
        system_prompt=runtime.get("system_prompt") or "",
    )
    logger.info("Starting realtime call provider=%s model=%s", config.provider, config.model)
    started_at = time.time()
    transcript_turns: list[dict] = []
    adapter = create_realtime_provider(config)

    async def _on_realtime_event(event: RealtimeEvent) -> None:
        if "transcript" not in event.type:
            return
        data = event.data if isinstance(event.data, dict) else {}
        text = data.get("transcript") or data.get("delta")
        if not isinstance(text, str) or not text.strip():
            return
        role = "assistant" if event.type.startswith("response.") else "user"
        transcript_turns.append({
            "role": role,
            "text": text.strip(),
            "time": round(time.time() - started_at, 1),
        })

    # The initial provider adapter exposes an event callback at construction;
    # keep this narrow compatibility hook so future registered adapters can
    # offer a public setter without changing the Worker dispatch contract.
    set_event_handler = getattr(adapter, "set_event_handler", None)
    if callable(set_event_handler):
        result = set_event_handler(_on_realtime_event)
        if asyncio.iscoroutine(result):
            await result
    elif hasattr(adapter, "_event_handler"):
        setattr(adapter, "_event_handler", _on_realtime_event)

    bridge = LiveKitAudioBridge(ctx.room, adapter.send_audio)
    subscription_tasks: set[asyncio.Task] = set()
    adapter_task: asyncio.Task | None = None
    disconnect_task: asyncio.Task | None = None
    room_disconnected = asyncio.Event()

    @ctx.room.on("disconnected")
    def _on_room_disconnected():
        room_disconnected.set()

    try:
        _register_call_log_completion(ctx, call_log_id, transcript_turns, started_at)
        await ctx.connect()
        if room_disconnected.is_set():
            logger.info("LiveKit room disconnected during connection; skipping realtime provider")
            return transcript_turns

        async def _subscribe(track) -> None:
            if _is_audio_track(track):
                await bridge.subscribe(track)

        for participant in ctx.room.remote_participants.values():
            for publication in getattr(participant, "track_publications", {}).values():
                track = getattr(publication, "track", None)
                if track is not None:
                    await _subscribe(track)

        @ctx.room.on("track_subscribed")
        def _on_track_subscribed(track, publication, participant):
            if not _is_audio_track(track) or room_disconnected.is_set():
                return

            async def _subscribe_dynamic() -> None:
                try:
                    await _subscribe(track)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning("Failed to subscribe realtime audio track")

            task = asyncio.create_task(_subscribe_dynamic())
            subscription_tasks.add(task)
            task.add_done_callback(subscription_tasks.discard)

        adapter_task = asyncio.create_task(adapter.run(config, bridge))
        disconnect_task = asyncio.create_task(room_disconnected.wait())
        done, _ = await asyncio.wait(
            {adapter_task, disconnect_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if disconnect_task in done and not adapter_task.done():
            logger.info("LiveKit room disconnected; stopping realtime provider")
            try:
                await adapter.close()
            finally:
                await _cancel_and_wait([adapter_task])
        else:
            await adapter_task
        return transcript_turns
    finally:
        try:
            tasks_to_cancel = list(subscription_tasks)
            if disconnect_task is not None:
                tasks_to_cancel.append(disconnect_task)
            if adapter_task is not None:
                tasks_to_cancel.append(adapter_task)
            await _cancel_and_wait(tasks_to_cancel)
            await adapter.close()
        finally:
            await bridge.close()


@server.rtc_session()
async def entrypoint(ctx: JobContext):
    """Fetch secret runtime only in the Worker, then dispatch one explicit mode."""
    ctx.log_context_fields = {"room": ctx.room.name}
    metadata: dict[str, str] | None = None
    started_at = time.time()
    try:
        metadata = _parse_worker_metadata(ctx.job.metadata)
        runtime = await asyncio.to_thread(_fetch_runtime_secrets, metadata["agent_id"])
        if not isinstance(runtime, dict):
            raise RuntimeError("Worker runtime payload is invalid")
        if runtime.get("agent_id") != metadata["agent_id"] or runtime.get("runtime_mode") != metadata["runtime_mode"]:
            raise RuntimeError("Worker runtime does not match dispatch metadata")

        if metadata["runtime_mode"] == "pipeline":
            await run_pipeline_call(ctx, runtime, metadata["call_log_id"])
        elif metadata["runtime_mode"] == "realtime":
            await run_realtime_call(ctx, runtime, metadata["call_log_id"])
        else:  # _parse_worker_metadata deliberately makes this unreachable.
            raise RuntimeError("Worker dispatch mode is unsupported")
    except Exception as exc:
        if metadata is not None:
            stage = "realtime_runtime" if metadata["runtime_mode"] == "realtime" else "worker_runtime"
            _write_call_log_end(
                metadata["call_log_id"],
                status="failed",
                duration_seconds=int(time.time() - started_at),
                failure_stage=stage,
                failure_reason=_safe_failure_reason(exc),
            )
        # Never stringify the original exception: runtime and provider errors
        # can contain bearer credentials or a provider-bound voice identifier.
        logger.error("Worker runtime dispatch failed")
        try:
            await ctx.room.disconnect()
        except Exception:
            pass
        raise RuntimeError("Worker runtime dispatch failed") from None


if __name__ == "__main__":
    cli.run_app(server)
