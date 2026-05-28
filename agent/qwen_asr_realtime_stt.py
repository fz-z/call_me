from __future__ import annotations

import asyncio
import base64
import os
from dataclasses import dataclass
from typing import Any

from livekit.agents.stt.stt import (
    NOT_GIVEN,
    APIConnectOptions,
    DEFAULT_API_CONNECT_OPTIONS,
    NotGivenOr,
    RecognizeStream,
    SpeechData,
    SpeechEvent,
    SpeechEventType,
    STT,
    STTCapabilities,
)
from livekit.agents.utils import shortuuid
from livekit import rtc


@dataclass(frozen=True)
class _SegmentState:
    request_id: str
    started: bool


def _normalize_dashscope_language(lang: str) -> str:
    """
    DashScope ASR realtime 的 transcription_params.language 通常期望“语言名”，
    而不是 BCP-47 code（例如 zh-CN 会报错）。
    """
    # 观察到服务端对 "zh-CN" 与 "Chinese" 都会报不识别，
    # 更可能仅接受 ISO-639-1 语言码（例如 zh/en/ja/ko...）。
    l = (lang or "").strip()
    if not l:
        return "zh"

    lower = l.lower()
    # BCP-47 -> 取主语言 subtag
    if "-" in lower:
        lower = lower.split("-", 1)[0]
    if "_" in lower:
        lower = lower.split("_", 1)[0]

    # 语言名 -> ISO-639-1
    name_to_iso = {
        "chinese": "zh",
        "mandarin": "zh",
        "english": "en",
        "japanese": "ja",
        "korean": "ko",
        "french": "fr",
        "german": "de",
        "spanish": "es",
        "russian": "ru",
        "portuguese": "pt",
        "italian": "it",
    }
    if lower in name_to_iso:
        return name_to_iso[lower]

    # 已是短码则直接使用
    return lower


class QwenASRRealtimeSTT(STT):
    """
    通义 Qwen ASR Realtime（qwen3-asr-flash-realtime）适配为 LiveKit Agents STT。

    设计目标：
    - 保留 LiveKit 的 VAD/turn detector：这里主要输出 interim/final transcript
    - 使用 DashScope Python SDK 的 OmniRealtimeConversation（底层 WebSocket）
    """

    def __init__(
        self,
        *,
        model: str = "qwen3-asr-flash-realtime",
        api_key: str | None = None,
        ws_url: str | None = None,
        sample_rate: int = 16000,
        language: str = "zh",
    ) -> None:
        super().__init__(
            capabilities=STTCapabilities(streaming=True, interim_results=True)
        )
        self._model = model
        self._api_key = api_key or os.getenv("DASHSCOPE_API_KEY", "")
        self._ws_url = ws_url or os.getenv(
            "QWEN_ASR_REALTIME_WS_URL", "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
        )
        self._sample_rate = int(os.getenv("QWEN_ASR_SAMPLE_RATE", str(sample_rate)))
        self._language = language

        if not self._api_key:
            raise RuntimeError("缺少 DASHSCOPE_API_KEY（用于通义 ASR Realtime）")

    @classmethod
    def from_env(cls) -> QwenASRRealtimeSTT:
        model = os.getenv("QWEN_ASR_MODEL", "qwen3-asr-flash-realtime").strip()
        ws_url = os.getenv("QWEN_ASR_REALTIME_WS_URL", "").strip() or None
        sample_rate = int(os.getenv("QWEN_ASR_SAMPLE_RATE", "16000"))
        language = os.getenv("QWEN_ASR_LANGUAGE", "zh").strip()
        return cls(model=model, ws_url=ws_url, sample_rate=sample_rate, language=language)

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider(self) -> str:
        return "qwen"

    async def _recognize_impl(  # type: ignore[override]
        self,
        buffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions,
    ) -> SpeechEvent:
        raise NotImplementedError("QwenASRRealtimeSTT 仅支持 stream()（实时识别）")

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> RecognizeStream:
        lang = self._language if language is NOT_GIVEN else language
        return _QwenASRRecognizeStream(
            stt=self,
            conn_options=conn_options,
            sample_rate=self._sample_rate,
            language=str(lang),
        )

    async def aclose(self) -> None:
        # 每个 stream 自己管理会话
        return


class _QwenASRRecognizeStream(RecognizeStream):
    def __init__(
        self,
        *,
        stt: QwenASRRealtimeSTT,
        conn_options: APIConnectOptions,
        sample_rate: int,
        language: str,
    ) -> None:
        super().__init__(stt=stt, conn_options=conn_options, sample_rate=sample_rate)
        self._language = language
        self._segment = _SegmentState(request_id=shortuuid(), started=False)

    async def _run(self) -> None:
        assert isinstance(self._stt, QwenASRRealtimeSTT)
        stt: QwenASRRealtimeSTT = self._stt

        try:
            import dashscope
            # 说明：某些 dashscope 版本并不会在 qwen_omni/__init__.py 里导出 TranscriptionParams，
            # 因此这里从实现模块导入，避免 ImportError。
            from dashscope.audio.qwen_omni.omni_realtime import (  # type: ignore
                AudioFormat,
                MultiModality,
                OmniRealtimeCallback,
                OmniRealtimeConversation,
                TranscriptionParams,
            )
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "缺少 dashscope 依赖或版本过低。请先执行 `uv sync`。"
            ) from e

        loop = asyncio.get_running_loop()
        transcript_q: asyncio.Queue[SpeechEvent | None] = asyncio.Queue()
        err: dict[str, str] = {}
        stream = self

        def _emit(ev: SpeechEvent) -> None:
            loop.call_soon_threadsafe(transcript_q.put_nowait, ev)

        def _extract_text(resp: dict) -> str:
            # DashScope 事件里可能同时带 text / transcript / stash（stash 可能是 dict）
            for key in ("transcript", "text", "stash"):
                v = resp.get(key)
                if isinstance(v, str) and v.strip():
                    return v.strip()
                if isinstance(v, dict):
                    for k2 in ("transcript", "text", "stash"):
                        vv = v.get(k2)
                        if isinstance(vv, str) and vv.strip():
                            return vv.strip()
            return ""

        class _CB(OmniRealtimeCallback):
            def on_event(self, response: dict) -> None:  # type: ignore[override]
                try:
                    ev_type = response.get("type", "")
                    # interim
                    if ev_type == "conversation.item.input_audio_transcription.text":
                        text = _extract_text(response)
                        if not text:
                            return
                        _emit(
                            SpeechEvent(
                                type=SpeechEventType.INTERIM_TRANSCRIPT,
                                request_id=stream._segment.request_id,
                                alternatives=[
                                    SpeechData(language=stream._language, text=text)
                                ],
                            )
                        )
                    # final
                    elif ev_type == "conversation.item.input_audio_transcription.completed":
                        text = _extract_text(response)
                        if not text:
                            return
                        _emit(
                            SpeechEvent(
                                type=SpeechEventType.FINAL_TRANSCRIPT,
                                request_id=stream._segment.request_id,
                                alternatives=[
                                    SpeechData(language=stream._language, text=text)
                                ],
                            )
                        )
                    elif ev_type == "session.finished":
                        loop.call_soon_threadsafe(transcript_q.put_nowait, None)
                    elif ev_type == "error":
                        # 例如：language 参数非法等
                        try:
                            err["message"] = str(
                                response.get("error", {}).get("message") or response
                            )
                        except Exception:
                            err["message"] = str(response)
                        loop.call_soon_threadsafe(transcript_q.put_nowait, None)
                except Exception as e:
                    # 避免回调异常导致 websocket 直接断开
                    err["message"] = f"callback_exception: {e}"
                    loop.call_soon_threadsafe(transcript_q.put_nowait, None)

        dashscope.api_key = stt._api_key
        conversation = OmniRealtimeConversation(
            model=stt._model,
            url=stt._ws_url,
            callback=_CB(),
        )

        # connect 是同步风格，避免阻塞 event loop
        await asyncio.to_thread(conversation.connect)

        # 关键：关闭服务端 turn detection，保留 LiveKit 的 VAD/turn detector 负责分段。
        # 同时配置 ASR 的 language/sample_rate/input format。
        tp = TranscriptionParams(
            language=_normalize_dashscope_language(self._language),
            sample_rate=stt._sample_rate,
            input_audio_format="pcm",
        )
        await asyncio.to_thread(
            conversation.update_session,
            output_modalities=[MultiModality.TEXT],
            enable_turn_detection=True,
            turn_detection={
                "type": "server_vad",
                "threshold": 0.5,
                "silence_duration_ms": 400,
            },
            input_audio_format=AudioFormat.PCM_16000HZ_MONO_16BIT,
            enable_input_audio_transcription=True,
            transcription_params=tp,
        )

        # 发送音频 + 消费转写事件
        send_task = asyncio.create_task(
            _audio_sender(self, conversation), name="qwen_asr.audio_sender"
        )
        recv_task = asyncio.create_task(
            _event_forwarder(self, transcript_q), name="qwen_asr.event_forwarder"
        )

        try:
            await asyncio.gather(send_task, recv_task)
            if err.get("message"):
                raise RuntimeError(f"Qwen ASR realtime error: {err['message']}")
        finally:
            # 尽量收尾
            for t in (send_task, recv_task):
                if not t.done():
                    t.cancel()


async def _event_forwarder(
    stream: _QwenASRRecognizeStream, q: asyncio.Queue[SpeechEvent | None]
) -> None:
    """
    把 callback 收到的 SpeechEvent 转发到 LiveKit RecognizeStream 的 event channel。
    同时补齐 START_OF_SPEECH（在第一次 transcript 时触发）。
    """
    started = False
    while True:
        ev = await q.get()
        if ev is None:
            break
        if not started and ev.type in (
            SpeechEventType.INTERIM_TRANSCRIPT,
            SpeechEventType.FINAL_TRANSCRIPT,
        ):
            started = True
            stream._event_ch.send_nowait(
                SpeechEvent(
                    type=SpeechEventType.START_OF_SPEECH,
                    request_id=stream._segment.request_id,
                )
            )
        stream._event_ch.send_nowait(ev)


async def _audio_sender(stream: _QwenASRRecognizeStream, conversation: Any) -> None:
    """
    从 LiveKit 输入通道读取音频帧并发送给 DashScope。
    - FlushSentinel：表示本地 VAD 分段结束，尝试触发服务端 commit 以尽快拿到 final
    """
    while True:
        item = await stream._input_ch.recv()
        if item is None:
            # 结束输入：提交一次并结束会话
            m = getattr(conversation, "commit", None)
            if callable(m):
                await asyncio.to_thread(m)
            endm = getattr(conversation, "end_session_async", None)
            if callable(endm):
                await asyncio.to_thread(endm)
            # 通知 forwarder 退出（如果 callback 没发结束事件也能退出）
            try:
                stream._event_ch.send_nowait(
                    SpeechEvent(
                        type=SpeechEventType.END_OF_SPEECH,
                        request_id=stream._segment.request_id,
                    )
                )
            except Exception:
                pass
            break

        if isinstance(item, RecognizeStream._FlushSentinel):
            # 触发一次 commit，让服务端尽快产出 final
            m = getattr(conversation, "commit", None)
            if callable(m):
                await asyncio.to_thread(m)

            # segment boundary：切换 request_id
            stream._segment = _SegmentState(request_id=shortuuid(), started=False)
            continue

        assert isinstance(item, rtc.AudioFrame)
        # DashScope OmniRealtimeConversation.append_audio 需要 base64 字符串
        data = bytes(item.data)
        audio_b64 = base64.b64encode(data).decode("utf-8")
        m = getattr(conversation, "append_audio", None)
        if callable(m):
            try:
                await asyncio.to_thread(m, audio_b64)
            except Exception:
                # websocket 关闭或服务端 error 后，停止继续发送
                break

