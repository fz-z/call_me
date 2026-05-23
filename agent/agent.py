import asyncio
import json
import logging
import os

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


server = AgentServer()


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session()
async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    # Connect first, then wait for user participant to join with agent_config
    await ctx.connect()

    agent_config_str = None
    # Poll for up to 15s waiting for a participant with agent_config
    for _ in range(30):
        for p in ctx.room.remote_participants.values():
            attrs = p.attributes
            if attrs and "agent_config" in attrs:
                agent_config_str = attrs["agent_config"]
                break
        if agent_config_str:
            break
        await asyncio.sleep(0.5)

    config = {}
    if not agent_config_str:
        logger.warning("No agent_config in participant attributes, using defaults")
        system_prompt = os.getenv("DEFAULT_SYSTEM_PROMPT", "你是一位贴心的语音智能助手。")
        voice_id = None
    else:
        config = json.loads(agent_config_str)
        system_prompt = config.get("system_prompt", os.getenv("DEFAULT_SYSTEM_PROMPT", "你是一位贴心的语音智能助手。"))
        voice_id = config.get("voice_id")

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

    logger.info("pipeline config", extra={
        "room": ctx.room.name,
        "agent_config": _sanitize_agent_config_for_log(agent_config_str),
        "llm_provider": llm_provider,
        "tts_provider": tts_provider,
    })
    logger.info(f"TTS created: model={tts.model}, voice_id={voice_id}, is_realtime={tts._is_realtime_model()}")

    session = AgentSession(
        stt=stt,
        llm=llm,
        tts=tts,
        turn_handling=TurnHandlingOptions(
            turn_detector=MultilingualModel(),
            vad=ctx.proc.userdata["vad"],
        ),
    )

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
        greeting_stream = llm.chat(chat_ctx=greeting_ctx)
        greeting_text = ""
        async for chunk in greeting_stream:
            if chunk.delta and chunk.delta.content:
                greeting_text += chunk.delta.content
        greeting_text = greeting_text.strip()
        if greeting_text:
            logger.info(f"Initial greeting: {greeting_text}")
            await session.say(greeting_text, allow_interruptions=False)
        else:
            await session.say("你好，请问有什么可以帮助你的？", allow_interruptions=False)
    except Exception as e:
        logger.warning(f"Failed to generate initial greeting: {e}")
        await session.say("你好，请问有什么可以帮助你的？", allow_interruptions=False)


if __name__ == "__main__":
    cli.run_app(server)
