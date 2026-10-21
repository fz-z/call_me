"""LiveKit audio bridge with injectable primitives for deterministic unit tests."""

from __future__ import annotations

import asyncio
import inspect
import logging
import struct
from collections.abc import Awaitable, Callable
from typing import Any

from .base import RealtimeRuntimeError

logger = logging.getLogger("realtime.bridge")


INPUT_SAMPLE_RATE = 16_000
OUTPUT_SAMPLE_RATE = 24_000
PCM16_BYTES_PER_SAMPLE = 2


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _clamp_pcm16(value: float) -> int:
    return max(-32768, min(32767, int(round(value))))


def normalize_pcm16(data: bytes | bytearray | memoryview, sample_rate: int, num_channels: int) -> bytes:
    """Down/up-sample signed PCM16 to 16 kHz mono without provider dependencies."""
    if sample_rate <= 0 or num_channels <= 0:
        raise RealtimeRuntimeError("Invalid input audio format")

    raw = bytes(data)
    frame_width = PCM16_BYTES_PER_SAMPLE * num_channels
    if len(raw) % frame_width:
        raise RealtimeRuntimeError("Input audio is not aligned to PCM16 frames")
    frame_count = len(raw) // frame_width
    if frame_count == 0:
        return b""

    samples = struct.unpack(f"<{frame_count * num_channels}h", raw)
    mono = [
        _clamp_pcm16(sum(samples[index : index + num_channels]) / num_channels)
        for index in range(0, len(samples), num_channels)
    ]
    if sample_rate == INPUT_SAMPLE_RATE:
        return struct.pack(f"<{len(mono)}h", *mono)

    output_count = max(1, round(len(mono) * INPUT_SAMPLE_RATE / sample_rate))
    if len(mono) == 1:
        output = mono * output_count
    else:
        output = []
        for output_index in range(output_count):
            position = output_index * (len(mono) - 1) / max(1, output_count - 1)
            left_index = int(position)
            right_index = min(left_index + 1, len(mono) - 1)
            fraction = position - left_index
            output.append(_clamp_pcm16(mono[left_index] * (1 - fraction) + mono[right_index] * fraction))
    return struct.pack(f"<{len(output)}h", *output)


class LiveKitAudioBridge:
    """Moves normalized microphone PCM into a provider and provider PCM into LiveKit."""

    def __init__(
        self,
        room: Any,
        on_input: Callable[[bytes], Awaitable[None] | None],
        *,
        audio_stream_factory: Callable[[Any, int, int], Any] | None = None,
        audio_source_factory: Callable[[int, int], Any] | None = None,
        local_track_factory: Callable[[str, Any], Any] | None = None,
        audio_frame_factory: Callable[[bytes, int, int], Any] | None = None,
    ) -> None:
        self._room = room
        self._on_input = on_input
        self._audio_stream_factory = audio_stream_factory
        self._audio_source_factory = audio_source_factory
        self._local_track_factory = local_track_factory
        self._audio_frame_factory = audio_frame_factory
        self._input_task: asyncio.Task[None] | None = None
        self._stream: Any | None = None
        self._source: Any | None = None
        self._output_track: Any | None = None
        self._publication: Any | None = None
        self._closed = False
        self._output_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()

    def _livekit_rtc(self) -> Any:
        try:
            from livekit import rtc
        except ImportError as exc:
            raise RealtimeRuntimeError("LiveKit runtime is not installed") from exc
        return rtc

    def _create_stream(self, track: Any) -> Any:
        if self._audio_stream_factory is not None:
            return self._audio_stream_factory(track, INPUT_SAMPLE_RATE, 1)
        rtc = self._livekit_rtc()
        return rtc.AudioStream(track, sample_rate=INPUT_SAMPLE_RATE, num_channels=1)

    def _create_source(self) -> Any:
        if self._audio_source_factory is not None:
            return self._audio_source_factory(OUTPUT_SAMPLE_RATE, 1)
        return self._livekit_rtc().AudioSource(OUTPUT_SAMPLE_RATE, 1)

    def _create_track(self, source: Any) -> Any:
        if self._local_track_factory is not None:
            return self._local_track_factory("realtime-audio", source)
        return self._livekit_rtc().LocalAudioTrack.create_audio_track("realtime-audio", source)

    def _create_frame(self, data: bytes) -> Any:
        if self._audio_frame_factory is not None:
            return self._audio_frame_factory(data, OUTPUT_SAMPLE_RATE, 1)
        return self._livekit_rtc().AudioFrame(
            data,
            OUTPUT_SAMPLE_RATE,
            1,
            len(data) // PCM16_BYTES_PER_SAMPLE,
        )

    async def subscribe(self, track: Any) -> None:
        if self._closed:
            raise RealtimeRuntimeError("Audio bridge is closed")
        if self._input_task is not None:
            raise RealtimeRuntimeError("Audio bridge already has an input track")
        self._stream = self._create_stream(track)
        self._input_task = asyncio.create_task(self._consume_input(), name="realtime-audio-input")

    async def _consume_input(self) -> None:
        try:
            async for event in self._stream:
                frame = getattr(event, "frame", event)
                pcm = normalize_pcm16(frame.data, frame.sample_rate, frame.num_channels)
                if pcm:
                    await _maybe_await(self._on_input(pcm))
        except asyncio.CancelledError:
            raise
        except RealtimeRuntimeError:
            raise
        except Exception as exc:
            raise RealtimeRuntimeError("Failed to consume LiveKit input audio") from exc
        finally:
            stream, self._stream = self._stream, None
            await self._close_resource(stream)

    async def wait_for_input(self) -> None:
        if self._input_task is not None:
            await self._input_task

    async def publish_pcm(self, pcm: bytes | bytearray | memoryview) -> None:
        if self._closed:
            raise RealtimeRuntimeError("Audio bridge is closed")
        data = bytes(pcm)
        if len(data) % PCM16_BYTES_PER_SAMPLE:
            raise RealtimeRuntimeError("Output audio is not aligned to PCM16 samples")
        async with self._output_lock:
            if self._source is None:
                source = self._create_source()
                try:
                    track = self._create_track(source)
                    logger.info("Publishing realtime audio track")
                    publication = await asyncio.wait_for(
                        self._room.local_participant.publish_track(track),
                        timeout=10,
                    )
                except asyncio.TimeoutError as exc:
                    await self._close_resource(source)
                    logger.error("Timed out publishing realtime audio track")
                    raise RealtimeRuntimeError(
                        "Timed out publishing realtime audio track"
                    ) from exc
                except BaseException:
                    await self._close_resource(source)
                    raise
                self._source = source
                self._output_track = track
                self._publication = publication
                logger.info("Realtime audio track published")
            frame = self._create_frame(data)
            await _maybe_await(self._source.capture_frame(frame))

    async def clear_output(self) -> bool:
        """Discard queued provider audio without tearing down the published track."""
        async with self._output_lock:
            if self._source is None:
                return False
            clear_queue = getattr(self._source, "clear_queue", None)
            if not callable(clear_queue):
                logger.warning("Realtime audio source does not support queue clearing")
                return False
            try:
                await _maybe_await(clear_queue())
            except Exception:
                logger.warning("Failed to clear realtime audio output queue")
                return False
            return True

    async def _close_resource(self, resource: Any | None) -> None:
        if resource is None:
            return
        close = getattr(resource, "aclose", None) or getattr(resource, "close", None)
        if close is not None:
            await _maybe_await(close())

    async def close(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            stream, self._stream = self._stream, None
            await self._close_resource(stream)
            if self._input_task is not None and not self._input_task.done():
                self._input_task.cancel()
                try:
                    await self._input_task
                except asyncio.CancelledError:
                    pass
            async with self._output_lock:
                publication, self._publication = self._publication, None
                track, self._output_track = self._output_track, None
                track_sid = getattr(publication, "sid", None) or getattr(track, "sid", None)
                unpublish = getattr(self._room.local_participant, "unpublish_track", None)
                if unpublish is not None and track_sid is not None:
                    try:
                        await _maybe_await(unpublish(track_sid))
                    except Exception:
                        # Room teardown may already have removed the publication.
                        pass
                source, self._source = self._source, None
                await self._close_resource(source)
