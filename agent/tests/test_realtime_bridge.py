import asyncio
import inspect
import unittest

from realtime.bridge import LiveKitAudioBridge


class FakeFrame:
    def __init__(self, data, sample_rate, num_channels):
        self.data = data
        self.sample_rate = sample_rate
        self.num_channels = num_channels


class FakeStream:
    def __init__(self, frames):
        self._frames = list(frames)
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._frames:
            raise StopAsyncIteration
        return self._frames.pop(0)

    async def aclose(self):
        self.closed = True


class FakeSource:
    def __init__(self):
        self.frames = []
        self.closed = False
        self.clear_calls = 0

    async def capture_frame(self, frame):
        self.frames.append(frame)

    def clear_queue(self):
        self.clear_calls += 1
        self.frames.clear()

    def close(self):
        self.closed = True


class FakeParticipant:
    def __init__(self):
        self.published = []
        self.unpublished = []

    async def publish_track(self, track):
        self.published.append(track)
        return type("Publication", (), {"sid": "publication-1"})()

    async def unpublish_track(self, sid):
        self.unpublished.append(sid)


class FakeRoom:
    def __init__(self):
        self.local_participant = FakeParticipant()


class LiveKitAudioBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_input_frames_are_delivered_in_order_as_16k_mono_pcm16(self):
        # 8 kHz mono samples: 1, 2. The bridge should resample before delivery.
        input_frame = FakeFrame((1).to_bytes(2, "little", signed=True) + (2).to_bytes(2, "little", signed=True), 8000, 1)
        stream = FakeStream([input_frame])
        received = []

        async def on_input(pcm):
            received.append(pcm)

        bridge = LiveKitAudioBridge(
            room=FakeRoom(),
            on_input=on_input,
            audio_stream_factory=lambda track, sample_rate, num_channels: stream,
        )

        await bridge.subscribe(object())
        await bridge.wait_for_input()

        self.assertEqual(len(received), 1)
        self.assertEqual(len(received[0]), 8)  # resampled 8 kHz -> 16 kHz
        self.assertTrue(stream.closed)

    async def test_output_is_published_as_24k_mono_pcm16_in_order(self):
        source = FakeSource()
        room = FakeRoom()
        track = object()
        bridge = LiveKitAudioBridge(
            room=room,
            on_input=lambda pcm: None,
            audio_source_factory=lambda sample_rate, num_channels: source,
            local_track_factory=lambda name, output_source: track,
            audio_frame_factory=lambda data, sample_rate, num_channels: FakeFrame(data, sample_rate, num_channels),
        )

        await bridge.publish_pcm(b"\x01\x00\x02\x00")
        await bridge.publish_pcm(b"\x03\x00\x04\x00")

        self.assertEqual(room.local_participant.published, [track])
        self.assertEqual([frame.data for frame in source.frames], [b"\x01\x00\x02\x00", b"\x03\x00\x04\x00"])
        self.assertTrue(all(frame.sample_rate == 24000 for frame in source.frames))
        self.assertTrue(all(frame.num_channels == 1 for frame in source.frames))

    async def test_clear_output_removes_queued_frames_and_accepts_new_audio(self):
        source = FakeSource()
        bridge = LiveKitAudioBridge(
            room=FakeRoom(), on_input=lambda pcm: None,
            audio_source_factory=lambda sample_rate, num_channels: source,
            local_track_factory=lambda name, output_source: object(),
            audio_frame_factory=lambda data, sample_rate, num_channels: FakeFrame(data, sample_rate, num_channels),
        )

        await bridge.publish_pcm(b"\x01\x00")
        self.assertTrue(await bridge.clear_output())
        self.assertEqual(source.frames, [])
        self.assertEqual(source.clear_calls, 1)
        await bridge.publish_pcm(b"\x02\x00")
        self.assertEqual([frame.data for frame in source.frames], [b"\x02\x00"])

    async def test_clear_output_before_track_or_without_queue_support_is_safe(self):
        source = FakeSource()
        source.clear_queue = None
        bridge = LiveKitAudioBridge(
            room=FakeRoom(), on_input=lambda pcm: None,
            audio_source_factory=lambda sample_rate, num_channels: source,
            local_track_factory=lambda name, output_source: object(),
            audio_frame_factory=lambda data, sample_rate, num_channels: FakeFrame(data, sample_rate, num_channels),
        )

        self.assertFalse(await bridge.clear_output())
        await bridge.publish_pcm(b"\x01\x00")
        with self.assertLogs("realtime.bridge", level="WARNING"):
            self.assertFalse(await bridge.clear_output())
        await bridge.publish_pcm(b"\x02\x00")
        self.assertEqual([frame.data for frame in source.frames], [b"\x01\x00", b"\x02\x00"])

    async def test_close_is_idempotent_and_cleans_up_the_stream_and_source(self):
        stream = FakeStream([])
        source = FakeSource()
        bridge = LiveKitAudioBridge(
            room=FakeRoom(),
            on_input=lambda pcm: None,
            audio_stream_factory=lambda track, sample_rate, num_channels: stream,
            audio_source_factory=lambda sample_rate, num_channels: source,
            local_track_factory=lambda name, output_source: object(),
            audio_frame_factory=lambda data, sample_rate, num_channels: FakeFrame(data, sample_rate, num_channels),
        )

        await bridge.subscribe(object())
        await bridge.publish_pcm(b"\x00\x00")
        await bridge.close()
        await bridge.close()

        self.assertTrue(stream.closed)
        self.assertTrue(source.closed)
        self.assertEqual(bridge._room.local_participant.unpublished, ["publication-1"])


if __name__ == "__main__":
    unittest.main()
