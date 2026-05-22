from __future__ import annotations

import asyncio
import base64
import json
import os
from typing import Any

import aiohttp
from livekit.agents.tts import (
    TTS,
    AudioEmitter,
    ChunkedStream,
    SynthesizeStream,
    TTSCapabilities,
)
from livekit.agents.types import APIConnectOptions, DEFAULT_API_CONNECT_OPTIONS
from livekit.agents.utils import shortuuid


class QwenTTS(TTS):
    """
    通义（Qwen-TTS）在线语音合成适配器。

    说明：
    - 默认使用 DashScope 的 Qwen-TTS HTTP 接口（multimodal-generation）。
    - 当前实现为“整段文本一次请求”，拿到音频后再按 chunk 推送给 LiveKit，
      以兼容 LiveKit 的流式播放机制。
    - 响应解析尽量做成“容错”，以适配不同版本/区域返回结构的细微差异。
    """

    def __init__(
        self,
        *,
        api_url: str,
        api_key: str,
        model: str = "qwen3-tts-flash",
        voice: str = "Cherry",
        voice_id: str | None = None,
        # 常见：wav / mp3 / pcm
        audio_format: str = "wav",
        sample_rate: int = 24000,
        num_channels: int = 1,
        request_timeout_s: float | None = None,
        extra_headers: dict[str, str] | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            capabilities=TTSCapabilities(streaming=True),
            sample_rate=sample_rate,
            num_channels=num_channels,
        )
        self._api_url = api_url
        self._api_key = api_key
        self._model = model
        self._voice = voice
        self._voice_id = voice_id
        self._audio_format = audio_format
        self._request_timeout_s = request_timeout_s
        self._extra_headers = extra_headers or {}
        self._extra_body = extra_body or {}

        self._session: aiohttp.ClientSession | None = None
        self._session_lock = asyncio.Lock()

    @classmethod
    def from_env(cls) -> QwenTTS:
        api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("缺少环境变量 DASHSCOPE_API_KEY（通义 DashScope API Key）")

        # Qwen-TTS HTTP API（中国站默认）
        api_url = os.environ.get("QWEN_TTS_API_URL", "").strip() or (
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/"
            "multimodal-generation/generation"
        )

        model = os.environ.get("QWEN_TTS_MODEL", "qwen-tts").strip()
        # 复刻音色（voice_id）优先：如果设置了 QWEN_TTS_VOICE_ID，则会覆盖 QWEN_TTS_VOICE
        voice_id = os.environ.get("QWEN_TTS_VOICE_ID", "").strip() or None
        voice = os.environ.get("QWEN_TTS_VOICE", "Cherry").strip()
        audio_format = os.environ.get("QWEN_TTS_FORMAT", "wav").strip()

        sample_rate = int(os.environ.get("QWEN_TTS_SAMPLE_RATE", "24000"))
        num_channels = int(os.environ.get("QWEN_TTS_NUM_CHANNELS", "1"))

        request_timeout_s_env = os.environ.get("QWEN_TTS_REQUEST_TIMEOUT_S", "").strip()
        request_timeout_s = float(request_timeout_s_env) if request_timeout_s_env else None

        extra_headers: dict[str, str] = {}
        extra_headers_json = os.environ.get("QWEN_TTS_EXTRA_HEADERS_JSON", "").strip()
        if extra_headers_json:
            extra_headers = json.loads(extra_headers_json)

        extra_body: dict[str, Any] = {}
        extra_body_json = os.environ.get("QWEN_TTS_EXTRA_BODY_JSON", "").strip()
        if extra_body_json:
            extra_body = json.loads(extra_body_json)

        return cls(
            api_url=api_url,
            api_key=api_key,
            model=model,
            voice=voice,
            voice_id=voice_id,
            audio_format=audio_format,
            sample_rate=sample_rate,
            num_channels=num_channels,
            request_timeout_s=request_timeout_s,
            extra_headers=extra_headers,
            extra_body=extra_body,
        )

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider(self) -> str:
        return "qwen-tts"

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> ChunkedStream:
        return self._synthesize_with_stream(text=text, conn_options=conn_options)

    def stream(
        self, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> SynthesizeStream:
        return _QwenSynthesizeStream(tts=self, conn_options=conn_options)

    async def aclose(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _get_session(self) -> aiohttp.ClientSession:
        async with self._session_lock:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession()
            return self._session

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            **self._extra_headers,
        }

    def _build_body(self, *, text: str) -> dict[str, Any]:
        # 按官方文档：/services/aigc/multimodal-generation/generation
        # 不同文档版本可能略有差异，所以这里把关键字段放在最常见的位置，同时支持 extra_body 覆盖。
        body: dict[str, Any] = {
            "model": self._model,
            "input": {
                "text": text,
                # voice 可以是内置音色名（如 Cherry），也可以是 enrollment 返回的 voice_id（复刻音色）
                "voice": self._voice_id or self._voice,
            },
            "parameters": {
                # DashScope 近期把 response_format 校验为 object（需包含 type）。
                # 这里按“音频输出”给出一个兼容结构；如你的账号/地域需要其它字段，
                # 可通过 QWEN_TTS_EXTRA_BODY_JSON 覆盖。
                "response_format": {
                    "type": "audio",
                    "format": self._audio_format,
                },
            },
        }
        # 允许调用方扩展/覆盖（例如 language、speaking_rate、pitch、style 等）
        return _deep_merge(body, self._extra_body)

    def _is_realtime_model(self) -> bool:
        # 经验规则：VC/VD realtime 模型通常要求走 WebSocket Realtime 协议，
        # 用 HTTP multimodal-generation 调用会出现 500 / grpc stream cancelled 等错误。
        return "realtime" in (self._model or "").lower()


class _QwenSynthesizeStream(SynthesizeStream):
    async def _run(self, output_emitter: AudioEmitter) -> None:
        assert isinstance(self._tts, QwenTTS)
        tts: QwenTTS = self._tts

        request_id = shortuuid()
        # realtime 通常只返回 PCM（base64 chunk），因此强制以 PCM 方式初始化
        mime_type = "audio/pcm" if tts._is_realtime_model() else _format_to_mime(tts._audio_format)
        output_emitter.initialize(
            request_id=request_id,
            sample_rate=tts.sample_rate,
            num_channels=tts.num_channels,
            mime_type=mime_type,
            stream=True,
            frame_size_ms=100,
        )
        output_emitter.start_segment(segment_id=shortuuid())

        buf = ""
        async for item in self._input_ch:
            if isinstance(item, self._FlushSentinel):
                continue
            if not item:
                continue
            self._mark_started()
            buf += item

        text = buf.strip()
        if not text:
            return

        if tts._is_realtime_model():
            async for chunk in _call_qwen_tts_realtime_stream(tts=tts, text=text):
                if chunk:
                    output_emitter.push(chunk)
            output_emitter.flush()
        else:
            audio = await _call_qwen_tts(tts=tts, text=text)
            for chunk in _iter_chunks(audio, 16 * 1024):
                output_emitter.push(chunk)
            output_emitter.flush()


async def _call_qwen_tts(*, tts: QwenTTS, text: str) -> bytes:
    session = await tts._get_session()
    headers = tts._build_headers()
    body = tts._build_body(text=text)

    timeout_total = tts._request_timeout_s or None
    timeout = aiohttp.ClientTimeout(total=timeout_total) if timeout_total else None

    async with session.post(tts._api_url, json=body, headers=headers, timeout=timeout) as r:
        raw = await r.read()
        if r.status >= 400:
            # 尽量把返回内容带出来，方便排查
            snippet = raw[:1000].decode("utf-8", errors="replace")
            raise RuntimeError(f"Qwen-TTS HTTP {r.status}: {snippet}")

        # 有些实现会直接返回音频（少见），优先按 content-type 判断
        ctype = (r.headers.get("Content-Type") or "").lower()
        if ctype.startswith("audio/"):
            return raw

        # 否则按 JSON 解析，尝试在多个可能字段里提取 base64 音频
        try:
            obj = json.loads(raw.decode("utf-8"))
        except Exception:
            snippet = raw[:200].decode("utf-8", errors="replace")
            raise RuntimeError(f"Qwen-TTS 返回非 JSON 且非音频: {snippet}")

        audio_b64 = _extract_audio_b64(obj)
        if not audio_b64:
            audio_url = _extract_audio_url(obj)
            if audio_url:
                return await _download_audio(session=session, url=audio_url)

            # 进一步把 output 的结构带出来，方便排查字段差异
            output = obj.get("output") if isinstance(obj, dict) else None
            output_keys = list(output.keys()) if isinstance(output, dict) else None
            raise RuntimeError(
                "Qwen-TTS 响应中未找到音频字段或 URL。"
                f" top_keys={list(obj.keys()) if isinstance(obj, dict) else type(obj)}"
                f" output_keys={output_keys}"
            )
        try:
            return base64.b64decode(audio_b64)
        except Exception as e:
            raise RuntimeError("Qwen-TTS 音频 base64 解码失败") from e


async def _call_qwen_tts_realtime_stream(*, tts: QwenTTS, text: str):
    """
    Qwen TTS Realtime（DashScope SDK）：
    - 用于 qwen3-tts-*-realtime-* 系列模型（包含 VC 声音复刻）。
    - SDK 会处理底层 websocket 协议，我们只接收 `response.audio.delta` 并输出 PCM bytes。
    """
    try:
        import dashscope
        from dashscope.audio.qwen_tts_realtime import (
            AudioFormat,
            QwenTtsRealtime,
            QwenTtsRealtimeCallback,
        )
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "缺少 dashscope 依赖。请先执行 `uv sync`（或 `uv add dashscope`）安装依赖。"
        ) from e

    ws_url = os.environ.get("QWEN_TTS_REALTIME_WS_URL", "").strip() or (
        "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
    )
    # DashScope SDK 会自己拼接 `?model=...`，因此这里确保 url 不带 query 参数
    ws_url = ws_url.split("?", 1)[0]
    workspace_id = os.environ.get("DASHSCOPE_WORKSPACE", "").strip() or None
    voice = tts._voice_id or tts._voice

    dashscope.api_key = tts._api_key

    loop = asyncio.get_running_loop()
    q: asyncio.Queue[bytes | None] = asyncio.Queue()
    got_audio = False

    class _CB(QwenTtsRealtimeCallback):
        def on_event(self, message: Any) -> None:  # type: ignore[override]
            nonlocal got_audio
            # dashscope SDK 有的回调会传 dict（已解析），有的会传 str
            if isinstance(message, dict):
                response = message
            elif isinstance(message, str):
                try:
                    response = json.loads(message)
                except Exception:
                    # 无法解析的事件直接忽略，避免回调异常导致 websocket 断开
                    return
            else:
                return

            ev_type = response.get("type", "")
            if ev_type == "response.audio.delta":
                delta = response.get("delta")
                if isinstance(delta, str) and delta:
                    try:
                        audio = base64.b64decode(delta)
                    except Exception:
                        return
                    got_audio = True
                    loop.call_soon_threadsafe(q.put_nowait, audio)
            elif ev_type in (
                # 常见结束事件（不同版本可能不同）
                "response.audio.done",
                "response.done",
                "session.finished",
            ):
                loop.call_soon_threadsafe(q.put_nowait, None)
            elif ev_type in ("error", "session.error", "response.error"):
                loop.call_soon_threadsafe(q.put_nowait, None)

        def on_close(self, close_status_code, close_msg) -> None:  # type: ignore[override]
            # websocket 异常关闭时，确保退出等待，避免 LiveKit 侧卡住
            loop.call_soon_threadsafe(q.put_nowait, None)

    cb = _CB()
    client = QwenTtsRealtime(
        model=tts._model,
        callback=cb,
        url=ws_url,
        workspace=workspace_id,
    )

    # SDK 为同步风格（内部线程处理 websocket + 回调），放到线程池避免阻塞 event loop
    try:
        await asyncio.to_thread(client.connect)
        await asyncio.to_thread(
            client.update_session,
            voice=voice,
            response_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
            mode="server_commit",
        )
        await asyncio.to_thread(client.append_text, text)
        # 官方示例：finish 会触发合成并在完成后结束会话
        await asyncio.to_thread(client.finish)
    except Exception:
        # 连接/发送失败，确保唤醒消费者并退出
        loop.call_soon_threadsafe(q.put_nowait, None)
        raise
    # 等待音频帧（由 callback 推入队列）。不要在这里过早 close，
    # 否则会在 response.audio.delta 到来前断链，导致 “no audio frames were pushed”.
    while True:
        item = await q.get()
        if item is None:
            break
        yield item

    # 正常结束后再收尾（best-effort）
    try:
        await asyncio.to_thread(client.close)
    except Exception:
        pass


def _extract_audio_b64(obj: Any) -> str | None:
    """
    兼容多种可能的返回结构：
    - {"output": {"audio": "..."}} 或 {"output": {"audio": {"data": "..."}}}
    - {"output": {"choices": [{"message": {"content": [{"audio": "..."}, ...]}}]}}
    - {"audio": "..."} / {"data": "..."} 之类的扁平结构
    """

    if isinstance(obj, dict):
        for k in ("audio", "audio_base64", "data"):
            v = obj.get(k)
            if isinstance(v, str) and v:
                return v
            if isinstance(v, dict):
                for kk in ("data", "audio", "audio_base64"):
                    vv = v.get(kk)
                    if isinstance(vv, str) and vv:
                        return vv

        output = obj.get("output")
        if output is not None:
            found = _extract_audio_b64(output)
            if found:
                return found

        # choices/message/content 结构
        choices = obj.get("choices") or (obj.get("output", {}) if isinstance(obj.get("output"), dict) else {}).get(
            "choices"
        )
        if isinstance(choices, list):
            for c in choices:
                if not isinstance(c, dict):
                    continue
                msg = c.get("message") if isinstance(c.get("message"), dict) else None
                content = msg.get("content") if msg else None
                found = _extract_audio_b64(content)
                if found:
                    return found

        # content list
        content = obj.get("content")
        found = _extract_audio_b64(content)
        if found:
            return found

    if isinstance(obj, list):
        for item in obj:
            found = _extract_audio_b64(item)
            if found:
                return found

    return None


def _extract_audio_url(obj: Any) -> str | None:
    """
    非流式场景常见：返回一个可下载音频的 url（一般 24h 有效）。
    这里递归搜索常见字段名。
    """
    if isinstance(obj, dict):
        for k in ("audio_url", "audioUrl", "url", "download_url", "downloadUrl"):
            v = obj.get(k)
            if isinstance(v, str) and v.startswith(("http://", "https://")):
                return v
        # 一些返回可能是 {"audio": {"url": "..."}}
        for k in ("audio", "output", "result", "data"):
            if k in obj:
                found = _extract_audio_url(obj[k])
                if found:
                    return found

        # choices/message/content 结构
        choices = obj.get("choices")
        if isinstance(choices, list):
            found = _extract_audio_url(choices)
            if found:
                return found

    if isinstance(obj, list):
        for item in obj:
            found = _extract_audio_url(item)
            if found:
                return found

    return None


async def _download_audio(*, session: aiohttp.ClientSession, url: str) -> bytes:
    async with session.get(url) as r:
        data = await r.read()
        if r.status >= 400:
            snippet = data[:500].decode("utf-8", errors="replace")
            raise RuntimeError(f"下载 Qwen-TTS 音频失败 HTTP {r.status}: {snippet}")
        return data


def _iter_chunks(b: bytes, size: int):
    for i in range(0, len(b), size):
        yield b[i : i + size]


def _format_to_mime(fmt: str) -> str:
    fmt = (fmt or "").lower()
    if fmt in ("wav", "wave"):
        return "audio/wav"
    if fmt in ("mp3", "mpeg"):
        return "audio/mpeg"
    if fmt in ("pcm", "raw"):
        return "audio/pcm"
    return "application/octet-stream"


def _deep_merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    if not b:
        return a
    out: dict[str, Any] = dict(a)
    for k, v in b.items():
        if (
            k in out
            and isinstance(out[k], dict)
            and isinstance(v, dict)
        ):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out

