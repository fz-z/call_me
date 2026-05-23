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

    if not agent_config_str:
        logger.warning("No agent_config in participant attributes, using defaults")
        system_prompt = "你是一位贴心的语音智能助手。"
        voice_id = None
    else:
        config = json.loads(agent_config_str)
        system_prompt = config.get("system_prompt", "你是一位贴心的语音智能助手。")
        voice_id = config.get("voice_id")

    # LLM — use model_config from token if available, otherwise .env default
    if config and config.get("model_config"):
        mc = config["model_config"]
        mc_provider = mc["provider"]
        if mc_provider == "deepseek":
            llm = openai.LLM.with_deepseek(
                model=mc["model"],
                api_key=mc["api_key"],
                temperature=mc.get("temperature", 0.7),
            )
        elif mc_provider == "qwen":
            llm = openai.LLM(
                model=mc["model"],
                api_key=mc["api_key"],
                base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
                temperature=mc.get("temperature", 0.7),
            )
        else:
            logger.warning(f"Unknown model_config provider: {mc_provider}, falling back to .env")
            # fall through to .env defaults below
            config = None  # trigger fallback
        if config:  # model_config was successfully applied
            llm_provider = mc_provider
    else:
        config = None  # trigger fallback

    if not config or not config.get("model_config"):
        # Fallback to .env defaults
        llm_provider = os.getenv("LLM_PROVIDER", "qwen").strip().lower()
        if llm_provider == "qwen":
            qwen_base_url = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
            llm = openai.LLM(
                model=os.getenv("QWEN_MODEL", "qwen3-max"),
                api_key=os.getenv("DASHSCOPE_API_KEY"),
                base_url=qwen_base_url,
                temperature=0.7,
            )
        elif llm_provider == "deepseek":
            llm = openai.LLM.with_deepseek(model="deepseek-chat", temperature=0.7)
        else:
            raise ValueError(f"Unsupported LLM_PROVIDER: {llm_provider}")

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
    if config and config.get("tts_config"):
        tc = config["tts_config"]
        tc_provider = tc["provider"]
        if tc_provider == "qwen":
            tts = QwenTTS(
                api_url=os.getenv("QWEN_TTS_API_URL", "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"),
                api_key=tc["api_key"],
                model=tc["model"],
                voice_id=voice_id,
            )
            tts_provider = "qwen"
        else:
            logger.warning(f"Unknown tts_config provider: {tc_provider}, falling back to .env")
            config = None
    else:
        config = None

    if not config or not config.get("tts_config"):
        # Fallback to .env defaults
        tts_provider = os.getenv("TTS_PROVIDER", "livekit").strip().lower()
        if tts_provider == "qwen":
            tts_model = os.getenv("QWEN_TTS_MODEL", "qwen3-tts-vc-realtime-2026-01-15")
            tts = QwenTTS(
                api_url=os.getenv("QWEN_TTS_API_URL", "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"),
                api_key=os.getenv("DASHSCOPE_API_KEY", ""),
                model=tts_model,
                voice_id=voice_id,
            )
        else:
            from livekit.agents import inference
            tts = inference.TTS(
                model=os.getenv("TTS_MODEL", "cartesia/sonic-3"),
                voice=os.getenv("TTS_VOICE", "694f17b5-0c44-42bd-9d88-f18e9a5e40a1"),
            )

    logger.info("pipeline config", extra={
        "room": ctx.room.name,
        "agent_config": agent_config_str,
        "llm_provider": llm_provider,
        "tts_provider": tts_provider,
    })

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


if __name__ == "__main__":
    cli.run_app(server)
