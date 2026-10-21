import asyncio
import base64
import json
import unittest

from realtime.base import RealtimeRuntimeConfig, RealtimeRuntimeError
from realtime.factory import create_realtime_provider
from realtime.qwen import MAX_PENDING_OUTPUT_BYTES, QwenRealtimeAdapter


class FakeMessage:
    def __init__(self, message_type, data=None):
        self.type = message_type
        self.data = data


class FakeWebSocket:
    def __init__(self, messages=()):
        self.messages = asyncio.Queue()
        for message in messages:
            self.messages.put_nowait(message)
        self.sent = []
        self.close_calls = 0

    async def send_json(self, payload):
        self.sent.append(payload)

    async def receive(self):
        return await self.messages.get()

    async def close(self):
        self.close_calls += 1
        if self.close_calls == 1:
            self.messages.put_nowait(FakeMessage("CLOSE"))


class FailingInputWebSocket(FakeWebSocket):
    def __init__(self):
        super().__init__()
        self.send_calls = 0

    async def send_json(self, payload):
        self.send_calls += 1
        if self.send_calls > 3:
            raise ValueError("provider rejected sk-private-key")
        await super().send_json(payload)


class FakeSession:
    def __init__(self, websocket):
        self.websocket = websocket
        self.connect_calls = []
        self.close_calls = 0

    async def ws_connect(self, endpoint, **kwargs):
        self.connect_calls.append((endpoint, kwargs))
        return self.websocket

    async def close(self):
        self.close_calls += 1


class BlockingSession:
    def __init__(self):
        self.close_calls = 0
        self.connect_started = asyncio.Event()
        self.release_connect = asyncio.Event()

    async def ws_connect(self, endpoint, **kwargs):
        self.connect_started.set()
        await self.release_connect.wait()

    async def close(self):
        self.close_calls += 1


class FakeBridge:
    def __init__(self):
        self.published = []
        self.clear_calls = 0
        self.published_event = asyncio.Event()

    async def publish_pcm(self, pcm):
        self.published.append(pcm)
        self.published_event.set()

    async def clear_output(self):
        self.clear_calls += 1
        self.published.clear()
        return True


class BlockingOutputBridge(FakeBridge):
    def __init__(self):
        super().__init__()
        self.publish_started = asyncio.Event()
        self.release_publish = asyncio.Event()
        self.cleared = asyncio.Event()

    async def publish_pcm(self, pcm):
        self.publish_started.set()
        await self.release_publish.wait()
        await super().publish_pcm(pcm)

    async def clear_output(self):
        result = await super().clear_output()
        self.cleared.set()
        return result


def runtime_config(**overrides):
    values = {
        "provider": "qwen",
        "model": "qwen-audio-3.1-realtime-plus",
        "endpoint": "wss://dashscope.example/realtime",
        "api_key": "sk-private-key",
        "provider_voice_id": "voice-private-id",
        "system_prompt": "Answer clearly.",
    }
    values.update(overrides)
    return RealtimeRuntimeConfig(**values)


class QwenRealtimeAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_output_backlog_is_bounded(self):
        adapter = QwenRealtimeAdapter(runtime_config())
        adapter._bridge = BlockingOutputBridge()
        full = b"\x01\x00" * (MAX_PENDING_OUTPUT_BYTES // 2)
        await adapter._handle_message(json.dumps({
            "type": "response.audio.delta", "delta": base64.b64encode(full).decode("ascii"),
        }))

        with self.assertRaisesRegex(RealtimeRuntimeError, "backlog exceeded"):
            await adapter._handle_message(json.dumps({
                "type": "response.audio.delta", "delta": base64.b64encode(b"\x02\x00").decode("ascii"),
            }))
        await adapter.close()
        self.assertEqual(adapter._pending_output_bytes, 0)

    async def test_large_audio_delta_is_published_as_short_frames(self):
        bridge = FakeBridge()
        adapter = QwenRealtimeAdapter(runtime_config())
        adapter._bridge = bridge
        pcm = b"\x01\x00" * 4_000

        await adapter._handle_message(json.dumps({
            "type": "response.audio.delta",
            "delta": base64.b64encode(pcm).decode("ascii"),
        }))
        await adapter._output_queue.join()

        self.assertEqual(b"".join(bridge.published), pcm)
        self.assertTrue(all(len(frame) <= 960 for frame in bridge.published))
        await adapter.close()

    async def test_response_end_logs_safe_status_and_reason_only(self):
        adapter = QwenRealtimeAdapter(runtime_config())
        event = {
            "type": "response.done",
            "response": {
                "status": "cancelled",
                "status_details": {"reason": "turn_detected", "message": "sk-private-key voice-private-id"},
            },
        }

        with self.assertLogs("realtime.qwen", level="INFO") as captured:
            await adapter._handle_message(json.dumps(event))

        logs = "\n".join(captured.output)
        self.assertIn("status=cancelled", logs)
        self.assertIn("reason=turn_detected", logs)
        self.assertNotIn("sk-private-key", logs)
        self.assertNotIn("voice-private-id", logs)

    async def test_speech_start_after_response_done_clears_unplayed_tail(self):
        bridge = FakeBridge()
        adapter = QwenRealtimeAdapter(runtime_config())
        adapter._bridge = bridge
        audio = lambda value: {"type": "response.audio.delta", "delta": base64.b64encode(value).decode("ascii")}
        for event in [
            {"type": "response.created"}, audio(b"\x01\x00"),
            {"type": "response.done", "response": {"status": "completed"}},
            {"type": "input_audio_buffer.speech_started"},
            {"type": "response.created"}, audio(b"\x02\x00"),
        ]:
            await adapter._handle_message(json.dumps(event))
        await adapter._output_queue.join()

        self.assertEqual(bridge.clear_calls, 1)
        self.assertEqual(bridge.published, [b"\x02\x00"])
        await adapter.close()

    async def test_blocked_output_does_not_delay_speech_start_event(self):
        bridge = BlockingOutputBridge()
        adapter = QwenRealtimeAdapter(runtime_config())
        adapter._bridge = bridge
        websocket = FakeWebSocket([
            FakeMessage("TEXT", json.dumps({"type": "response.created"})),
            FakeMessage("TEXT", json.dumps({"type": "response.audio.delta", "delta": base64.b64encode(b"\x01\x00").decode("ascii")})),
        ])
        adapter._websocket = websocket
        consumer = asyncio.create_task(adapter._consume_messages())
        await asyncio.wait_for(bridge.publish_started.wait(), timeout=0.2)
        websocket.messages.put_nowait(FakeMessage("TEXT", json.dumps({"type": "input_audio_buffer.speech_started"})))
        websocket.messages.put_nowait(FakeMessage("CLOSE"))
        try:
            await asyncio.wait_for(bridge.cleared.wait(), timeout=0.2)
        finally:
            bridge.release_publish.set()
            with self.assertRaises(RealtimeRuntimeError):
                await consumer

        self.assertEqual(bridge.clear_calls, 1)

    async def test_speech_start_clears_greeting_and_discards_late_audio_until_done(self):
        bridge = FakeBridge()
        adapter = QwenRealtimeAdapter(runtime_config())
        adapter._bridge = bridge
        audio = lambda value: {"type": "response.audio.delta", "delta": base64.b64encode(value).decode("ascii")}
        events = [
            {"type": "response.created"},
            audio(b"\x01\x00"),
            {"type": "input_audio_buffer.speech_started"},
            audio(b"\x02\x00"),
            {"type": "response.done", "response": {"status": "cancelled", "status_details": {"reason": "turn_detected"}}},
            {"type": "response.created"},
            audio(b"\x03\x00"),
        ]
        for event in events:
            await adapter._handle_message(json.dumps(event))
        await adapter._output_queue.join()

        self.assertEqual(bridge.clear_calls, 1)
        self.assertEqual(bridge.published, [b"\x03\x00"])
        await adapter.close()

    async def test_speech_start_does_not_clear_when_interruptions_are_disabled(self):
        bridge = FakeBridge()
        adapter = QwenRealtimeAdapter(runtime_config(allow_interruptions=False))
        adapter._bridge = bridge
        await adapter._handle_message(json.dumps({"type": "response.created"}))
        await adapter._handle_message(json.dumps({"type": "input_audio_buffer.speech_started"}))
        await adapter._handle_message(json.dumps({"type": "response.audio.delta", "delta": base64.b64encode(b"\x01\x00").decode("ascii")}))
        await adapter._output_queue.join()

        self.assertEqual(bridge.clear_calls, 0)
        self.assertEqual(bridge.published, [b"\x01\x00"])
        await adapter.close()

    async def test_speech_start_without_active_response_keeps_next_response_audio(self):
        bridge = FakeBridge()
        adapter = QwenRealtimeAdapter(runtime_config())
        adapter._bridge = bridge
        await adapter._handle_message(json.dumps({"type": "input_audio_buffer.speech_started"}))
        await adapter._handle_message(json.dumps({"type": "response.created"}))
        await adapter._handle_message(json.dumps({"type": "response.audio.delta", "delta": base64.b64encode(b"\x01\x00").decode("ascii")}))
        await adapter._output_queue.join()

        self.assertEqual(bridge.clear_calls, 1)
        self.assertEqual(bridge.published, [b"\x01\x00"])
        await adapter.close()

    async def test_connects_with_authorization_and_initializes_voice_once(self):
        websocket = FakeWebSocket([FakeMessage("CLOSE")])
        session = FakeSession(websocket)
        adapter = QwenRealtimeAdapter(runtime_config(), session_factory=lambda: session)

        with self.assertRaisesRegex(RealtimeRuntimeError, "connection closed"):
            await adapter.run(runtime_config(), FakeBridge())

        endpoint, options = session.connect_calls[0]
        self.assertIn("model=qwen-audio-3.1-realtime-plus", endpoint)
        self.assertEqual(options["headers"]["Authorization"], "Bearer sk-private-key")
        self.assertEqual(len(websocket.sent), 3)
        update = websocket.sent[0]
        self.assertEqual(update["type"], "session.update")
        self.assertEqual(update["session"]["instructions"], "Answer clearly.")
        self.assertEqual(update["session"]["voice"], "voice-private-id")
        self.assertEqual(update["session"]["modalities"], ["audio", "text"])
        self.assertEqual(update["session"]["speech_rate"], 1.0)
        self.assertEqual(update["session"]["turn_detection"]["type"], "server_vad")

        greeting_item = websocket.sent[1]
        self.assertEqual(greeting_item["type"], "conversation.item.create")
        self.assertEqual(greeting_item["item"]["role"], "user")
        self.assertEqual(greeting_item["item"]["content"][0]["type"], "input_text")
        self.assertEqual(websocket.sent[2]["type"], "response.create")

    async def test_connection_model_query_is_authoritative_and_preserves_other_endpoint_options(self):
        websocket = FakeWebSocket([FakeMessage("CLOSE")])
        session = FakeSession(websocket)
        config = runtime_config(endpoint="wss://dashscope.example/realtime?model=old-model&region=cn")
        adapter = QwenRealtimeAdapter(config, session_factory=lambda: session)

        with self.assertRaises(RealtimeRuntimeError):
            await adapter.run(config, FakeBridge())

        self.assertIn("model=qwen-audio-3.1-realtime-plus", session.connect_calls[0][0])
        self.assertIn("region=cn", session.connect_calls[0][0])
        self.assertNotIn("old-model", session.connect_calls[0][0])

    async def test_sends_pcm_as_base64_input_audio_buffer_append(self):
        websocket = FakeWebSocket()
        session = FakeSession(websocket)
        adapter = QwenRealtimeAdapter(runtime_config(), session_factory=lambda: session)
        bridge = FakeBridge()

        run_task = asyncio.create_task(adapter.run(runtime_config(), bridge))
        await asyncio.sleep(0)
        await adapter._handle_message(json.dumps({"type": "response.created"}))
        await adapter.send_audio(b"\x01\x00\x02\x00")
        await adapter.close()
        with self.assertRaises(RealtimeRuntimeError):
            await run_task

        self.assertEqual(websocket.sent[3], {
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(b"\x01\x00\x02\x00").decode("ascii"),
        })

    async def test_input_send_failures_do_not_expose_provider_details(self):
        websocket = FailingInputWebSocket()
        adapter = QwenRealtimeAdapter(runtime_config(), session_factory=lambda: FakeSession(websocket))
        run_task = asyncio.create_task(adapter.run(runtime_config(), FakeBridge()))
        await asyncio.sleep(0)

        with self.assertRaisesRegex(RealtimeRuntimeError, "Failed to send audio") as raised:
            await adapter.send_audio(b"\x01\x00")

        self.assertNotIn("sk-private-key", str(raised.exception))
        await adapter.close()
        with self.assertRaises(RealtimeRuntimeError):
            await run_task

    async def test_publishes_audio_delta_and_emits_transcript_event(self):
        audio = b"\x03\x00\x04\x00"
        websocket = FakeWebSocket([
            FakeMessage("TEXT", json.dumps({"type": "response.audio.delta", "delta": base64.b64encode(audio).decode("ascii")})),
            FakeMessage("TEXT", json.dumps({"type": "conversation.item.input_audio_transcription.completed", "transcript": "hi"})),
            FakeMessage("TEXT", json.dumps({"type": "response.audio_transcript.delta", "delta": "hello"})),
        ])
        events = []
        adapter = QwenRealtimeAdapter(
            runtime_config(),
            session_factory=lambda: FakeSession(websocket),
            event_handler=events.append,
        )
        bridge = FakeBridge()

        run_task = asyncio.create_task(adapter.run(runtime_config(), bridge))
        await asyncio.wait_for(bridge.published_event.wait(), timeout=0.2)
        websocket.messages.put_nowait(FakeMessage("CLOSE"))
        with self.assertRaises(RealtimeRuntimeError):
            await run_task

        self.assertEqual(bridge.published, [audio])
        self.assertEqual(
            [(event.type, event.data.get("transcript") or event.data.get("delta")) for event in events],
            [
                ("conversation.item.input_audio_transcription.completed", "hi"),
                ("response.audio_transcript.delta", "hello"),
            ],
        )

    async def test_provider_errors_are_sanitized_and_close_is_idempotent(self):
        websocket = FakeWebSocket([
            FakeMessage("TEXT", json.dumps({"type": "error", "error": {"message": "bad sk-private-key voice-private-id"}})),
        ])
        session = FakeSession(websocket)
        adapter = QwenRealtimeAdapter(runtime_config(), session_factory=lambda: session)

        with self.assertRaisesRegex(RealtimeRuntimeError, "provider reported an error") as raised:
            await adapter.run(runtime_config(), FakeBridge())

        self.assertNotIn("sk-private-key", str(raised.exception))
        self.assertNotIn("voice-private-id", str(raised.exception))
        await adapter.close()
        await adapter.close()
        self.assertEqual(websocket.close_calls, 1)
        self.assertEqual(session.close_calls, 1)

    async def test_cancellation_closes_websocket_and_session(self):
        websocket = FakeWebSocket()
        session = FakeSession(websocket)
        adapter = QwenRealtimeAdapter(runtime_config(), session_factory=lambda: session)
        task = asyncio.create_task(adapter.run(runtime_config(), FakeBridge()))
        await asyncio.sleep(0)

        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        self.assertEqual(websocket.close_calls, 1)
        self.assertEqual(session.close_calls, 1)

    async def test_connection_timeout_is_bounded_and_sanitized(self):
        session = BlockingSession()
        adapter = QwenRealtimeAdapter(
            runtime_config(),
            session_factory=lambda: session,
            connect_timeout_seconds=0.001,
        )

        with self.assertRaisesRegex(RealtimeRuntimeError, "connection timed out"):
            await adapter.run(runtime_config(), FakeBridge())

        self.assertTrue(session.connect_started.is_set())
        self.assertEqual(session.close_calls, 1)

    def test_factory_registers_qwen_adapter(self):
        adapter = create_realtime_provider(runtime_config())

        self.assertIsInstance(adapter, QwenRealtimeAdapter)


if __name__ == "__main__":
    unittest.main()
