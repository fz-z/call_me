import asyncio
import json
import logging
import unittest
from unittest.mock import patch

from agent import (
    _cancel_and_wait,
    _idle_process_count,
    _monitor_farewell,
    _monitor_silence,
    _parse_worker_metadata,
    _register_pipeline_cleanup,
    _safe_failure_reason,
    entrypoint,
    run_realtime_call,
)
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
            self.handlers.setdefault(event, []).append(handler)
            return handler

        return register(callback) if callback is not None else register

    async def disconnect(self):
        self.disconnect_calls += 1

    def emit(self, event, *args):
        for handler in self.handlers.get(event, []):
            handler(*args)


class FakeContext:
    def __init__(self, metadata):
        self.job = type("Job", (), {"metadata": metadata})()
        self.room = FakeRoom()
        self.proc = type("Proc", (), {"userdata": {}})()
        self.connect_calls = 0
        self.log_context_fields = {}
        self.shutdown_callbacks = []

    async def connect(self):
        self.connect_calls += 1

    def add_shutdown_callback(self, callback):
        self.shutdown_callbacks.append(callback)


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
    def test_realtime_failure_reason_uses_only_allowed_diagnostic_codes(self):
        for code in ("provider_error", "connection_closed", "audio_publish_failure"):
            error = RealtimeRuntimeError("Bearer sk-private-key voice-private-id", code=code)
            self.assertEqual(_safe_failure_reason(error), code)

        untrusted = RealtimeRuntimeError("Bearer sk-private-key", code="sk-private-key")
        self.assertEqual(_safe_failure_reason(untrusted), "realtime_provider_error")

    def test_idle_process_count_defaults_to_one_and_rejects_invalid_values(self):
        with patch.dict("agent.os.environ", {}, clear=True):
            self.assertEqual(_idle_process_count(), 1)
        with patch.dict("agent.os.environ", {"AGENT_IDLE_PROCESSES": "0"}, clear=True):
            self.assertEqual(_idle_process_count(), 0)
        with patch.dict("agent.os.environ", {"AGENT_IDLE_PROCESSES": "-1"}, clear=True):
            self.assertEqual(_idle_process_count(), 1)
        with patch.dict("agent.os.environ", {"AGENT_IDLE_PROCESSES": "many"}, clear=True):
            self.assertEqual(_idle_process_count(), 1)

    async def test_pipeline_shutdown_callback_cancels_background_tasks_and_closes_session(self):
        ctx = FakeContext("")
        stopped = asyncio.Event()

        async def wait_forever():
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        class FakeSession:
            def __init__(self):
                self.close_calls = 0

            async def aclose(self):
                self.close_calls += 1

        background_task = asyncio.create_task(wait_forever())
        await asyncio.sleep(0)
        session = FakeSession()
        _register_pipeline_cleanup(ctx, session, [background_task])

        self.assertEqual(len(ctx.shutdown_callbacks), 1)
        await ctx.shutdown_callbacks[0]()
        await asyncio.wait_for(stopped.wait(), timeout=0.2)

        self.assertTrue(background_task.cancelled())
        self.assertEqual(session.close_calls, 1)

    async def test_pipeline_monitor_cancels_its_nested_silence_prompt_on_shutdown(self):
        should_end = asyncio.Event()
        owned_tasks = []
        prompt_started = asyncio.Event()
        prompt_cancelled = asyncio.Event()

        class FakeSession:
            def __init__(self):
                self.handlers = {}

            def on(self, event, handler):
                self.handlers[event] = handler

            def emit(self, event, payload):
                self.handlers[event](payload)

            def say(self, *args, **kwargs):
                class Handle:
                    async def wait_for_playout(self):
                        prompt_started.set()
                        try:
                            await asyncio.Event().wait()
                        finally:
                            prompt_cancelled.set()

                return Handle()

        session = FakeSession()
        monitor = asyncio.create_task(_monitor_silence(should_end, session, None, owned_tasks))
        owned_tasks.append(monitor)
        await asyncio.sleep(0)
        session.emit("user_state_changed", type("Event", (), {"new_state": "away"})())
        await asyncio.wait_for(prompt_started.wait(), timeout=0.2)

        await _cancel_and_wait(owned_tasks)
        await asyncio.wait_for(prompt_cancelled.wait(), timeout=0.2)

        self.assertTrue(monitor.done())
        self.assertFalse(any(not task.done() for task in owned_tasks))

    async def test_pipeline_monitor_cancels_its_nested_farewell_timer_on_shutdown(self):
        should_end = asyncio.Event()
        owned_tasks = []

        class FakeSession:
            def __init__(self):
                self.handlers = {}

            def on(self, event, handler):
                self.handlers[event] = handler

            def emit(self, event, payload):
                self.handlers[event](payload)

        session = FakeSession()
        monitor = asyncio.create_task(
            _monitor_farewell(should_end, session, logging.getLogger("test"), owned_tasks)
        )
        owned_tasks.append(monitor)
        await asyncio.sleep(0)
        session.emit(
            "user_input_transcribed",
            type("Event", (), {"transcript": "再见", "is_final": True})(),
        )
        await asyncio.sleep(0)

        self.assertEqual(len(owned_tasks), 2)
        await _cancel_and_wait(owned_tasks)

        self.assertTrue(monitor.done())
        self.assertFalse(any(not task.done() for task in owned_tasks))

    async def test_cancel_and_wait_consumes_a_completed_task_exception(self):
        async def fails_after_close():
            raise RealtimeRuntimeError("provider closed")

        task = asyncio.create_task(fails_after_close())
        await asyncio.sleep(0)

        await _cancel_and_wait([task])

        self.assertTrue(task.done())

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

    async def test_entrypoint_falls_back_to_participant_agent_config(self):
        ctx = FakeContext("")
        participant = type(
            "Participant",
            (),
            {
                "attributes": {
                    "agent_config": json.dumps(
                        {
                            "agent_id": "agent-1",
                            "call_log_id": "call-1",
                            "runtime_mode": "pipeline",
                        }
                    )
                }
            },
        )()
        ctx.room.remote_participants = {"caller": participant}
        pipeline_calls = []

        async def fake_pipeline(context, runtime, call_log_id):
            pipeline_calls.append((context, runtime, call_log_id))

        runtime = {"agent_id": "agent-1", "runtime_mode": "pipeline", "system_prompt": "hi"}
        with patch("agent._fetch_runtime_secrets", return_value=runtime), patch(
            "agent.run_pipeline_call", new=fake_pipeline
        ):
            await entrypoint(ctx)

        self.assertEqual(len(pipeline_calls), 1)
        self.assertEqual(pipeline_calls[0][2], "call-1")
        self.assertEqual(ctx.connect_calls, 1)
        self.assertEqual(ctx.room.disconnect_calls, 0)

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
                await self._event_handler(type("Event", (), {"type": "response.audio_transcript.delta", "data": {"response_id": "r1", "delta": "你"}})())
                await self._event_handler(type("Event", (), {"type": "response.audio_transcript.delta", "data": {"response_id": "r1", "delta": "好"}})())
                await self._event_handler(type("Event", (), {"type": "response.audio_transcript.done", "data": {"response_id": "r1", "transcript": "你好"}})())

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
        self.assertEqual(len(transcript), 1)
        self.assertEqual(transcript[0]["text"], "你好")
        self.assertTrue(bridges[0].closed)

    async def test_realtime_room_disconnect_stops_provider_and_releases_bridge(self):
        ctx = FakeContext("")
        bridges = []

        class BlockingAdapter:
            def __init__(self):
                self.started = asyncio.Event()
                self.cancelled = False
                self.closed = False

            async def send_audio(self, pcm):
                pass

            async def run(self, config, bridge):
                self.started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise

            async def close(self):
                self.closed = True

        adapter = BlockingAdapter()

        def make_bridge(*args, **kwargs):
            bridge = FakeBridge(*args, **kwargs)
            bridges.append(bridge)
            return bridge

        with patch("agent.LiveKitAudioBridge", side_effect=make_bridge), patch(
            "agent.create_realtime_provider", return_value=adapter
        ), patch("agent._write_call_log_end"):
            call = asyncio.create_task(run_realtime_call(ctx, realtime_runtime(), "call-1"))
            await asyncio.wait_for(adapter.started.wait(), timeout=0.2)
            ctx.room.emit("disconnected")
            transcript = await asyncio.wait_for(call, timeout=0.2)

        self.assertEqual(transcript, [])
        self.assertTrue(adapter.closed)
        self.assertTrue(adapter.cancelled)
        self.assertTrue(bridges[0].closed)

    async def test_realtime_disconnect_during_connect_does_not_start_provider(self):
        class DisconnectingContext(FakeContext):
            async def connect(self):
                await super().connect()
                self.room.emit("disconnected")

        ctx = DisconnectingContext("")

        class Adapter:
            def __init__(self):
                self.run_calls = 0
                self.closed = False

            async def send_audio(self, pcm):
                pass

            async def run(self, config, bridge):
                self.run_calls += 1

            async def close(self):
                self.closed = True

        adapter = Adapter()
        with patch("agent.LiveKitAudioBridge", side_effect=FakeBridge), patch(
            "agent.create_realtime_provider", return_value=adapter
        ), patch("agent._write_call_log_end"):
            transcript = await run_realtime_call(ctx, realtime_runtime(), "call-1")

        self.assertEqual(transcript, [])
        self.assertEqual(adapter.run_calls, 0)
        self.assertTrue(adapter.closed)


if __name__ == "__main__":
    unittest.main()
