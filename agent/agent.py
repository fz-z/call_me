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
from qwen_tts import QwenTTS

load_dotenv(".env")
logger = logging.getLogger("agent")


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
                key: "***" if key.lower() in {"api_key", "apiKey".lower()} else redact(val)
                for key, val in value.items()
            }
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value

    return json.dumps(redact(config), ensure_ascii=False)


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


async def _monitor_farewell(should_end: asyncio.Event, session: AgentSession, logger):
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
                fallback_timer = asyncio.create_task(_fallback())
                return

    async def _fallback():
        await asyncio.sleep(5.0)
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
    await should_end.wait()


async def _monitor_silence(should_end: asyncio.Event, session: AgentSession, logger):
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
                prompt_task = asyncio.create_task(_prompt_and_wait())
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
    await should_end.wait()


server = AgentServer()


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session()
async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    t0 = time.time()
    connect_task = None

    # Read agent_config from dispatch metadata (fast path) or fall back to polling
    agent_config_str = ctx.job.metadata or None
    config = {}

    if agent_config_str:
        t1 = time.time()
        logger.info(f"[timing] got config from metadata at {t1 - t0:.2f}s, connecting in parallel")
        config = json.loads(agent_config_str)
        system_prompt = config.get("system_prompt", os.getenv("DEFAULT_SYSTEM_PROMPT", "你是一位贴心的语音智能助手。"))
        voice_id = config.get("voice_id")
        call_log_id = config.get("call_log_id")
        # Connect to room — can run concurrently with LLM/STT/TTS init below
        connect_task = asyncio.create_task(ctx.connect())
    else:
        # Fallback: connect first, then poll user attributes
        await ctx.connect()
        t1 = time.time()
        logger.info(f"[timing] ctx.connect (fallback): {t1 - t0:.2f}s")
        # Poll for up to 15s
        for _ in range(30):
            for p in ctx.room.remote_participants.values():
                attrs = p.attributes
                if attrs and "agent_config" in attrs:
                    agent_config_str = attrs["agent_config"]
                    break
            if agent_config_str:
                break
            await asyncio.sleep(0.5)
        t2 = time.time()
        logger.info(f"[timing] agent_config poll: {t2 - t1:.2f}s (total {t2 - t0:.2f}s)")
        if not agent_config_str:
            logger.warning("No agent_config in participant attributes, using defaults")
            system_prompt = os.getenv("DEFAULT_SYSTEM_PROMPT", "你是一位贴心的语音智能助手。")
            call_log_id = None
            voice_id = None
        else:
            config = json.loads(agent_config_str)
            system_prompt = config.get("system_prompt", os.getenv("DEFAULT_SYSTEM_PROMPT", "你是一位贴心的语音智能助手。"))
            voice_id = config.get("voice_id")
            call_log_id = config.get("call_log_id")

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
                api_url=os.getenv("QWEN_TTS_API_URL", "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"),
                api_key=tc["api_key"],
                model=tc["model"],
                voice_id=voice_id,
            )
            tts_configured = True
        else:
            logger.warning(f"Unknown tts_config provider: {tc_provider}, falling back to .env")

    if not tts_configured:
        tts = QwenTTS(
            api_url=os.getenv("QWEN_TTS_API_URL", "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"),
            api_key=os.getenv("DASHSCOPE_API_KEY", ""),
            model="qwen3-tts-flash-realtime",
            voice_id=voice_id,
        )
        tts_provider = "qwen"
    else:
        tts_provider = tc_provider

    # If using metadata path, await the connect task now (parallelized with LLM/STT/TTS init)
    if connect_task is not None:
        await connect_task
        connect_task = None
        t_connect = time.time()
        logger.info(f"[timing] ctx.connect (parallel): {t_connect - t0:.2f}s total")

    logger.info("pipeline config", extra={
        "room": ctx.room.name,
        "agent_config": _sanitize_agent_config_for_log(agent_config_str),
        "llm_provider": llm_provider,
        "tts_provider": tts_provider,
    })
    logger.info(f"TTS created: model={tts.model}, voice_id={voice_id}, is_realtime={tts._is_realtime_model()}")
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

    # Register call log callback BEFORE session.start, so it fires immediately
    # when the user disconnects (participant_disconnected) rather than waiting
    # for the room-level "disconnected" event which can be delayed.
    if call_log_id:
        _call_ended = False
        started_at = time.time()

        def _end_call_log():
            nonlocal _call_ended
            if _call_ended:
                return
            _call_ended = True
            duration = int(time.time() - started_at)
            api_base = os.getenv("API_BASE_URL", "http://api:8000")
            url = f"{api_base}/api/call/admin/call-logs/{call_log_id}/end"
            try:
                data = json.dumps({"status": "completed", "duration_seconds": duration}).encode()
                req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="PATCH")
                urllib.request.urlopen(req, timeout=5)
                logger.info(f"Call log {call_log_id} ended, duration={duration}s")
            except Exception as e:
                logger.warning(f"Failed to update call_log {call_log_id}: {e}")

        @ctx.room.on("participant_disconnected")
        def _on_participant_left(participant):
            # User participant left — mark call as ended
            _end_call_log()

        @ctx.room.on("disconnected")
        def _on_disconnected():
            # Safety net: room-level disconnect
            _end_call_log()

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
    _end_call_task = asyncio.create_task(_handle_end_call(_should_end, session, ctx.room, logger))
    _silence_task = asyncio.create_task(_monitor_silence(_should_end, session, logger))
    _farewell_task = asyncio.create_task(_monitor_farewell(_should_end, session, logger))

    # Agent speaks first: generate a short greeting via LLM
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


if __name__ == "__main__":
    cli.run_app(server)
