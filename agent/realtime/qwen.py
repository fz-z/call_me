"""Qwen WebSocket adapter for full-duplex realtime audio sessions."""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .base import RealtimeEvent, RealtimeRuntimeConfig, RealtimeRuntimeError

logger = logging.getLogger("realtime.qwen")
MAX_PENDING_OUTPUT_BYTES = 24_000 * 2 * 60  # At most 60 seconds (2.88 MB) of PCM16 audio.
OUTPUT_CHUNK_BYTES = 24_000 * 2 // 50  # 20 ms; never give LiveKit one long uncancellable frame.


TranscriptHandler = Callable[[RealtimeEvent], Awaitable[None] | None]


def _session_instructions(system_prompt: str, greeting_text: str) -> str:
    greeting_text = greeting_text.strip()
    if not greeting_text:
        return system_prompt
    return (
        f"{system_prompt}\n\n"
        "当前是通话的第一轮。首个响应必须且只能逐字朗读以下固定开场白，"
        "不可添加、删减、改写或解释；朗读后等待用户输入。\n"
        f"固定开场白：{greeting_text}"
    )


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _default_session_factory() -> Any:
    # Keep this import lazy: contract tests inject a transport and should not
    # need the production WebSocket client installed.
    try:
        import aiohttp
    except ImportError as exc:
        raise RealtimeRuntimeError("aiohttp is required for Qwen realtime sessions") from exc
    return aiohttp.ClientSession()


def _endpoint_with_model(endpoint: str, model: str) -> str:
    """Use the configured endpoint while adding the required model query once."""
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"ws", "wss"} or not parsed.netloc:
        raise RealtimeRuntimeError("Invalid Qwen realtime endpoint")
    # The runtime configuration is the source of truth. Remove stale or
    # duplicated endpoint model values while retaining all unrelated options.
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "model"]
    query.append(("model", model))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


class QwenRealtimeAdapter:
    """Stream 16 kHz input PCM to Qwen and publish its 24 kHz PCM output."""

    def __init__(
        self,
        config: RealtimeRuntimeConfig,
        *,
        session_factory: Callable[[], Any] | None = None,
        event_handler: TranscriptHandler | None = None,
        connect_timeout_seconds: float = 10.0,
    ) -> None:
        if connect_timeout_seconds <= 0:
            raise ValueError("connect_timeout_seconds must be positive")
        self._config = config
        self._session_factory = session_factory or _default_session_factory
        self._event_handler = event_handler
        self._connect_timeout_seconds = connect_timeout_seconds
        self._session: Any | None = None
        self._websocket: Any | None = None
        self._bridge: Any | None = None
        self._started = False
        self._closed = False
        self._connection_ready = asyncio.Event()
        self._close_lock = asyncio.Lock()
        self._logged_audio = False
        self._response_active = False
        self._suppress_response_audio = False
        self._overflowed_response = False
        self._output_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._pending_output_bytes = 0
        self._output_task: asyncio.Task[None] | None = None
        self._output_error: RealtimeRuntimeError | None = None

    async def run(self, config: RealtimeRuntimeConfig, bridge: Any) -> None:
        if self._started:
            raise RealtimeRuntimeError("Qwen realtime adapter is already running")
        if config.provider.strip().lower() != "qwen":
            raise RealtimeRuntimeError("Qwen adapter requires qwen provider configuration")
        self._started = True
        self._bridge = bridge
        try:
            self._session = self._session_factory()
            self._websocket = await asyncio.wait_for(
                self._session.ws_connect(
                    _endpoint_with_model(config.endpoint, config.model),
                    headers={"Authorization": f"Bearer {config.api_key}"},
                ),
                timeout=self._connect_timeout_seconds,
            )
            self._connection_ready.set()
            await self._websocket.send_json(
                {
                    "type": "session.update",
                    "session": {
                        "instructions": _session_instructions(config.system_prompt, config.greeting_text),
                        "voice": config.provider_voice_id,
                        "modalities": ["audio", "text"],
                        "input_audio_format": "pcm",
                        "output_audio_format": "pcm",
                        "speech_rate": config.speech_rate,
                        "turn_detection": {"type": "server_vad"},
                    },
                }
            )
            # The provider refuses response.create without a user message, and
            # the call UI waits for the agent's first audio track. Seed one
            # synthetic user turn so the agent greets the caller immediately.
            await self._websocket.send_json(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "你好"}],
                    },
                }
            )
            await self._websocket.send_json({"type": "response.create"})
            await self._consume_messages()
        except asyncio.CancelledError:
            await self.close()
            raise
        except asyncio.TimeoutError as exc:
            raise RealtimeRuntimeError("Qwen realtime connection timed out") from exc
        except RealtimeRuntimeError as exc:
            logger.warning("Qwen realtime session failed category=%s", exc.code)
            raise
        except Exception as exc:
            raise RealtimeRuntimeError("Qwen realtime session failed") from exc
        finally:
            await self.close()

    async def send_audio(self, pcm: bytes | bytearray | memoryview) -> None:
        """Send 16 kHz mono PCM16 received from the LiveKit bridge."""
        if self._closed:
            raise RealtimeRuntimeError("Qwen realtime session is not connected")
        if self._websocket is None:
            # A caller track can be subscribed before the provider handshake
            # completes. Wait for the connection instead of dropping audio.
            try:
                await asyncio.wait_for(
                    self._connection_ready.wait(),
                    timeout=self._connect_timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                raise RealtimeRuntimeError(
                    "Qwen realtime session is not connected"
                ) from exc
        if self._closed or self._websocket is None:
            raise RealtimeRuntimeError("Qwen realtime session is not connected")
        data = bytes(pcm)
        if not data:
            return
        if not self._config.allow_interruptions and self._response_active:
            # The agent is speaking and this Agent is configured as
            # uninterruptible: drop the caller audio for this turn.
            return
        if len(data) % 2:
            raise RealtimeRuntimeError("Input audio is not aligned to PCM16 samples")
        try:
            await self._websocket.send_json(
                {
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(data).decode("ascii"),
                }
            )
        except RealtimeRuntimeError:
            raise
        except Exception as exc:
            raise RealtimeRuntimeError("Failed to send audio to Qwen realtime provider") from exc

    async def _consume_messages(self) -> None:
        while True:
            if self._output_error is not None:
                raise self._output_error
            message = await self._websocket.receive()
            if self._output_error is not None:
                raise self._output_error
            kind = getattr(message, "type", None)
            if self._is_text_message(kind):
                await self._handle_message(message.data)
                continue
            if self._is_close_message(kind):
                raise RealtimeRuntimeError("Qwen realtime connection closed", code="connection_closed")
            raise RealtimeRuntimeError("Qwen realtime connection failed")

    @staticmethod
    def _is_text_message(kind: Any) -> bool:
        return (isinstance(kind, str) and kind.upper() == "TEXT") or getattr(kind, "name", None) == "TEXT"

    @staticmethod
    def _is_close_message(kind: Any) -> bool:
        if isinstance(kind, str):
            return kind.upper() in {"CLOSE", "CLOSED", "CLOSING", "ERROR"}
        return getattr(kind, "name", None) in {"CLOSE", "CLOSED", "CLOSING", "ERROR"}

    def _queue_output(self, pcm: bytes) -> None:
        if self._pending_output_bytes + len(pcm) > MAX_PENDING_OUTPUT_BYTES:
            raise RealtimeRuntimeError("Qwen realtime audio output backlog exceeded")
        self._pending_output_bytes += len(pcm)
        for start in range(0, len(pcm), OUTPUT_CHUNK_BYTES):
            self._output_queue.put_nowait(pcm[start : start + OUTPUT_CHUNK_BYTES])
        if self._output_task is None or self._output_task.done():
            self._output_task = asyncio.create_task(self._drain_output())

    async def _drain_output(self) -> None:
        try:
            while True:
                pcm = await self._output_queue.get()
                try:
                    await self._bridge.publish_pcm(pcm)
                finally:
                    self._pending_output_bytes -= len(pcm)
                    self._output_queue.task_done()
        except asyncio.CancelledError:
            raise
        except Exception:
            self._output_error = RealtimeRuntimeError(
                "Failed to publish Qwen realtime audio", code="audio_publish_failure"
            )
            logger.warning("Qwen realtime event=audio_publish_failure")
            if self._websocket is not None:
                await _maybe_await(self._websocket.close())

    async def _stop_output(self) -> None:
        task, self._output_task = self._output_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        while not self._output_queue.empty():
            pcm = self._output_queue.get_nowait()
            self._pending_output_bytes -= len(pcm)
            self._output_queue.task_done()

    async def _handle_message(self, raw_data: Any) -> None:
        try:
            payload = json.loads(raw_data)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RealtimeRuntimeError("Invalid message from Qwen realtime provider") from exc
        event_type = payload.get("type")
        if not isinstance(event_type, str):
            raise RealtimeRuntimeError("Invalid message from Qwen realtime provider")
        if event_type == "error":
            raise RealtimeRuntimeError("Qwen realtime provider reported an error", code="provider_error")
        if event_type == "response.created":
            if self._overflowed_response:
                await self._stop_output()
                await self._bridge.clear_output()
                self._overflowed_response = False
                self._suppress_response_audio = False
            self._response_active = True
        elif event_type == "response.done":
            response = payload.get("response")
            status = response.get("status") if isinstance(response, dict) else None
            if status not in {"completed", "cancelled", "failed", "incomplete"}:
                status = "unknown"
            details = response.get("status_details") if isinstance(response, dict) else None
            reason = details.get("reason") if isinstance(details, dict) else None
            if reason not in {"turn_detected", "client_cancelled"}:
                reason = "other" if reason else "none"
            logger.info("Qwen realtime response ended status=%s reason=%s", status, reason)
            self._response_active = False
            self._suppress_response_audio = False
        elif event_type == "input_audio_buffer.speech_started":
            logger.info("Qwen realtime caller speech started response_active=%s", self._response_active)
            if self._config.allow_interruptions:
                self._suppress_response_audio = self._response_active
                await self._stop_output()
                cleared = await self._bridge.clear_output()
                self._overflowed_response = False
                logger.info("Qwen realtime interrupted output queue_cleared=%s", cleared)
        if event_type == "response.audio.delta":
            if not self._logged_audio:
                self._logged_audio = True
                logger.info("Qwen realtime audio delta received")
            encoded_audio = payload.get("delta")
            if not isinstance(encoded_audio, str):
                raise RealtimeRuntimeError("Invalid audio message from Qwen realtime provider")
            try:
                pcm = base64.b64decode(encoded_audio, validate=True)
            except (ValueError, TypeError) as exc:
                raise RealtimeRuntimeError("Invalid audio message from Qwen realtime provider") from exc
            if len(pcm) % 2:
                raise RealtimeRuntimeError("Invalid audio message from Qwen realtime provider")
            if not self._suppress_response_audio:
                try:
                    self._queue_output(pcm)
                except RealtimeRuntimeError:
                    self._suppress_response_audio = True
                    self._overflowed_response = True
                    logger.warning("Qwen realtime event=audio_backlog_overflow")
        if "transcript" in event_type:
            await self._emit_event(RealtimeEvent(type=event_type, data=payload))

    async def _emit_event(self, event: RealtimeEvent) -> None:
        if self._event_handler is not None:
            await _maybe_await(self._event_handler(event))

    async def close(self) -> None:
        """Close the socket and session exactly once, including cancellation teardown."""
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            self._response_active = False
            self._suppress_response_audio = False
            self._overflowed_response = False
            await self._stop_output()
            self._connection_ready.set()
            websocket, self._websocket = self._websocket, None
            session, self._session = self._session, None
            if websocket is not None:
                # Qwen-Audio Realtime documents direct WebSocket closure for
                # session teardown and does not define a `session.close` event.
                # Keep this best-effort cleanup silent so it never replaces the
                # original provider failure or cancellation.
                try:
                    await _maybe_await(websocket.close())
                except Exception:
                    pass
            if session is not None:
                try:
                    await _maybe_await(session.close())
                except Exception:
                    pass
