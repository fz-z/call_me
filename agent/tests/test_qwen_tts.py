import asyncio
import os
import unittest
from unittest.mock import patch

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

from qwen_tts import (
    QwenTTS,
    _call_qwen_tts,
    _download_audio,
    _iter_flushed_text_segments,
    is_qwen_audio_tts_model,
    resolve_qwen_tts_api_url,
)


class QwenTTSTests(unittest.TestCase):
    def test_flush_sentinel_yields_current_text_before_input_ends(self):
        class Flush:
            pass

        async def items():
            for item in ("你", "好", Flush(), "再", "见"):
                yield item

        segments = asyncio.run(_collect(_iter_flushed_text_segments(items(), Flush)))

        self.assertEqual(segments, ["你好", "再见"])

    def test_qwen_audio_model_detection(self):
        self.assertTrue(is_qwen_audio_tts_model("qwen-audio-3.1-tts-flash"))
        self.assertTrue(is_qwen_audio_tts_model("qwen-audio-3.0-tts-flash"))
        self.assertFalse(is_qwen_audio_tts_model("qwen3-tts-flash-realtime"))
        self.assertFalse(is_qwen_audio_tts_model("cosyvoice-v3-flash"))

    def test_qwen_audio_build_body_uses_speech_synthesizer_contract(self):
        tts = QwenTTS(
            api_url="https://workspace.example/synthesize",
            api_key="secret",
            model="qwen-audio-3.1-tts-flash",
            voice_id="qwen-audio-3.1-tts-flash-ls-1234",
        )

        self.assertEqual(
            tts._build_body(text="你好"),
            {
                "model": "qwen-audio-3.1-tts-flash",
                "input": {
                    "text": "你好",
                    "voice": "qwen-audio-3.1-tts-flash-ls-1234",
                    "format": "wav",
                    "sample_rate": 24000,
                    "rate": 1.0,
                },
            },
        )

    def test_qwen_audio_build_body_includes_agent_speech_rate(self):
        tts = QwenTTS(
            api_url="https://workspace.example/synthesize",
            api_key="secret",
            model="qwen-audio-3.1-tts-flash",
            voice_id="voice",
            speech_rate=1.4,
        )

        self.assertEqual(tts._build_body(text="你好")["input"]["rate"], 1.4)

    def test_legacy_qwen_body_keeps_response_format(self):
        tts = QwenTTS(
            api_url="https://legacy.example/generation",
            api_key="secret",
            model="qwen3-tts-flash-realtime",
            voice="Cherry",
        )

        body = tts._build_body(text="你好")
        self.assertEqual(body["model"], "qwen3-tts-flash-realtime")
        self.assertIn("parameters", body)
        self.assertEqual(body["parameters"]["response_format"]["format"], "wav")

    def test_resolve_qwen_audio_endpoint_requires_workspace(self):
        with patch.dict(
            os.environ,
            {"QWEN_AUDIO_TTS_API_URL": "", "DASHSCOPE_WORKSPACE": ""},
        ):
            with self.assertRaisesRegex(RuntimeError, "DASHSCOPE_WORKSPACE"):
                resolve_qwen_tts_api_url("qwen-audio-3.1-tts-flash")

    def test_resolve_qwen_audio_endpoint_uses_workspace(self):
        with patch.dict(
            os.environ,
            {
                "QWEN_AUDIO_TTS_API_URL": "",
                "DASHSCOPE_WORKSPACE": "llm-example",
            },
        ):
            self.assertEqual(
                resolve_qwen_tts_api_url("qwen-audio-3.1-tts-flash"),
                "https://llm-example.cn-beijing.maas.aliyuncs.com/"
                "api/v1/services/audio/tts/SpeechSynthesizer",
            )

    def test_resolve_legacy_endpoint_keeps_qwen_tts_api_url(self):
        with patch.dict(
            os.environ,
            {"QWEN_TTS_API_URL": "https://legacy.example/generation"},
        ):
            self.assertEqual(
                resolve_qwen_tts_api_url("qwen3-tts-flash-realtime"),
                "https://legacy.example/generation",
            )


class QwenTTSHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        if hasattr(self, "tts"):
            await self.tts.aclose()

    async def test_qwen_audio_downloads_audio_url(self):
        seen = {}

        async def synthesize(request):
            seen["body"] = await request.json()
            return web.json_response(
                {"output": {"audio": {"url": str(request.url.with_path("/audio.wav"))}}}
            )

        async def audio(_request):
            return web.Response(body=b"RIFFagent", content_type="audio/wav")

        app = web.Application()
        app.router.add_post("/synthesize", synthesize)
        app.router.add_get("/audio.wav", audio)
        server = TestServer(app)
        await server.start_server()
        self.addAsyncCleanup(server.close)

        self.tts = QwenTTS(
            api_url=str(server.make_url("/synthesize")),
            api_key="secret",
            model="qwen-audio-3.1-tts-flash",
            voice_id="qwen-audio-3.1-tts-flash-ls-1234",
        )

        self.assertEqual(await _call_qwen_tts(tts=self.tts, text="你好"), b"RIFFagent")
        self.assertEqual(seen["body"], self.tts._build_body(text="你好"))

    async def test_qwen_audio_surfaces_provider_error_without_secret(self):
        async def synthesize(_request):
            return web.json_response(
                {
                    "request_id": "req-agent",
                    "code": "InvalidParameter",
                    "message": "bad voice for secret-key",
                },
                status=400,
            )

        app = web.Application()
        app.router.add_post("/synthesize", synthesize)
        server = TestServer(app)
        await server.start_server()
        self.addAsyncCleanup(server.close)

        self.tts = QwenTTS(
            api_url=str(server.make_url("/synthesize")),
            api_key="secret-key",
            model="qwen-audio-3.1-tts-flash",
            voice_id="bad-voice",
        )

        with self.assertRaisesRegex(
            RuntimeError, "InvalidParameter.*bad voice.*req-agent"
        ) as raised:
            await _call_qwen_tts(tts=self.tts, text="你好")
        self.assertNotIn("secret-key", str(raised.exception))

    async def test_download_reads_all_chunks(self):
        class Content:
            async def iter_chunked(self, _size):
                yield b"RIFF"
                yield b"agent"
                yield b"-audio"

        class Response:
            status = 200
            headers = {"Content-Type": "audio/wav"}
            content_length = None
            content = Content()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

        class Session:
            def get(self, _url, timeout=None):
                return Response()

        self.assertEqual(
            await _download_audio(session=Session(), url="https://audio.test/file"),
            b"RIFFagent-audio",
        )

    async def test_download_rejects_non_audio_content(self):
        session = aiohttp.ClientSession()
        self.addAsyncCleanup(session.close)

        async def not_audio(_request):
            return web.Response(text="provider error", content_type="text/plain")

        app = web.Application()
        app.router.add_get("/audio", not_audio)
        server = TestServer(app)
        await server.start_server()
        self.addAsyncCleanup(server.close)

        with self.assertRaisesRegex(RuntimeError, "non-audio"):
            await _download_audio(
                session=session, url=str(server.make_url("/audio"))
            )


async def _collect(segments):
    return [segment async for segment in segments]
