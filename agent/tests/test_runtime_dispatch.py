import asyncio
import json
import unittest
from unittest.mock import patch

from agent import _parse_worker_metadata, entrypoint, run_realtime_call
from realtime.base import RealtimeRuntimeError


class FakeRoom:
    def __init__(self):
        self.name = "room-test"
        self.remote_participants = {}
        self.handlers = {}
        self.disconnect_calls = 0
        self.local_participant = object()

    def on(self, event, callback=None):
        def register(handler):
            self.handlers[event] = handler
            return handler

        return register(callback) if callback is not None else register

    async def disconnect(self):
        self.disconnect_calls += 1


class FakeContext:
    def __init__(self, metadata):
        self.job = type("Job", (), {"metadata": metadata})()
        self.room = FakeRoom()
        self.proc = type("Proc", (), {"userdata": {}})()
        self.connect_calls = 0
        self.log_context_fields = {}

    async def connect(self):
        self.connect_calls += 1


def realtime_runtime():
    return {
        "agent_id": "agent-1",
        "runtime_mode": "realtime",
        "system_prompt": "help the caller",
        "realtime_config": {
            "provider": "qwen",
            "model": "qwen-audio-3.1-realtime-plus",
            "endpoint": "wss://example.test/realtime",
            "api_key": "sk-private-key",
            "voice_id": "voice-private-id",
        },
    }


class FakeBridge:
    def __init__(self, room, on_input):
        self.room = room
        self.on_input = on_input
        self.subscribed = []
        self.closed = False

    async def subscribe(self, track):
        self.subscribed.append(track)

    async def close(self):
        self.closed = True


class RuntimeDispatchTests(unittest.IsolatedAsyncioTestCase):
    def test_metadata_has_only_non_secret_dispatch_fields(self):
        metadata = json.dumps(
            {"agent_id": "agent-1", "call_log_id": "call-1", "runtime_mode": "realtime"}
        )

        parsed = _parse_worker_metadata(metadata)

        self.assertEqual(parsed["agent_id"], "agent-1")
        self.assertEqual(set(parsed), {"agent_id", "call_log_id", "runtime_mode"})

    def test_metadata_without_a_known_mode_is_rejected_without_defaulting_to_qwen(self):
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            _parse_worker_metadata(json.dumps({"agent_id": "agent-1", "call_log_id": "call-1"}))
        with self.assertRaisesRegex(RuntimeError, "unsupported"):
            _parse_worker_metadata(json.dumps({"agent_id": "agent-1", "call_log_id": "call-1", "runtime_mode": "qwen"}))

    async def test_entrypoint_fetches_private_runtime_and_dispatches_pipeline_once_connected(self):
        ctx = FakeContext(json.dumps({"agent_id": "agent-1", "call_log_id": "call-1", "runtime_mode": "pipeline"}))
        pipeline_calls = []

        async def fake_pipeline(context, runtime, call_log_id):
            pipeline_calls.append((context, runtime, call_log_id))

        runtime = {"agent_id": "agent-1", "runtime_mode": "pipeline", "system_prompt": "hi"}
        with patch("agent._fetch_runtime_secrets", return_value=runtime), patch(
            "agent.run_pipeline_call", new=fake_pipeline
        ):
            await entrypoint(ctx)

        self.assertEqual(len(pipeline_calls), 1)
        self.assertEqual(pipeline_calls[0][1], runtime)
        self.assertEqual(pipeline_calls[0][2], "call-1")
        self.assertEqual(ctx.connect_calls, 0, "pipeline setup owns the one metadata fast-path connection")

    async def test_entrypoint_dispatches_realtime_without_constructing_pipeline_defaults(self):
        ctx = FakeContext(json.dumps({"agent_id": "agent-1", "call_log_id": "call-1", "runtime_mode": "realtime"}))
        realtime_calls = []

        async def fake_realtime(context, runtime, call_log_id):
            realtime_calls.append((context, runtime, call_log_id))

        with patch("agent._fetch_runtime_secrets", return_value=realtime_runtime()), patch(
            "agent.run_realtime_call", new=fake_realtime
        ), patch("agent.run_pipeline_call") as pipeline:
            await entrypoint(ctx)

        self.assertEqual(len(realtime_calls), 1)
        pipeline.assert_not_called()

    async def test_entrypoint_marks_realtime_runtime_error_failed_without_secrets(self):
        ctx = FakeContext(json.dumps({"agent_id": "agent-1", "call_log_id": "call-1", "runtime_mode": "realtime"}))
        written_payloads = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def capture_request(request, timeout):
            written_payloads.append(json.loads(request.data.decode()))
            return Response()

        async def fail_realtime(*args, **kwargs):
            raise RealtimeRuntimeError("Bearer sk-private-key voice-private-id")

        with patch("agent._fetch_runtime_secrets", return_value=realtime_runtime()), patch(
            "agent.run_realtime_call", new=fail_realtime
        ), patch("agent.urllib.request.urlopen", side_effect=capture_request):
            with self.assertRaisesRegex(RuntimeError, "dispatch failed"):
                await entrypoint(ctx)

        self.assertEqual(written_payloads[0]["status"], "failed")
        self.assertEqual(written_payloads[0]["failure_stage"], "realtime_runtime")
        self.assertNotIn("sk-private-key", json.dumps(written_payloads))
        self.assertNotIn("voice-private-id", json.dumps(written_payloads))
        self.assertEqual(ctx.room.disconnect_calls, 1)

    async def test_realtime_call_accumulates_transcripts_and_subscribes_audio(self):
        ctx = FakeContext("")
        track = type("Track", (), {"kind": "audio"})()
        publication = type("Publication", (), {"track": track})()
        participant = type("Participant", (), {"track_publications": {"t": publication}})()
        ctx.room.remote_participants = {"p": participant}
        bridges = []

        class FakeAdapter:
            _event_handler = None

            async def send_audio(self, pcm):
                pass

            async def run(self, config, bridge):
                await self._event_handler(type("Event", (), {"type": "response.audio_transcript.done", "data": {"transcript": "你好"}})())

            async def close(self):
                pass

        def make_bridge(*args, **kwargs):
            bridge = FakeBridge(*args, **kwargs)
            bridges.append(bridge)
            return bridge

        with patch("agent.LiveKitAudioBridge", side_effect=make_bridge), patch(
            "agent.create_realtime_provider", return_value=FakeAdapter()
        ):
            transcript = await run_realtime_call(ctx, realtime_runtime(), "call-1")

        self.assertEqual(ctx.connect_calls, 1)
        self.assertEqual(bridges[0].subscribed, [track])
        self.assertEqual(transcript[0]["text"], "你好")
        self.assertTrue(bridges[0].closed)


if __name__ == "__main__":
    unittest.main()
