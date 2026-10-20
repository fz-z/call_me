import unittest

from realtime.base import RealtimeRuntimeConfig, RealtimeRuntimeError
from realtime.factory import create_realtime_provider, register_realtime_provider


class RealtimeFactoryTests(unittest.TestCase):
    def test_runtime_config_redacts_provider_credentials(self):
        config = RealtimeRuntimeConfig(
            provider="qwen",
            model="qwen-audio-3.1-realtime-plus",
            endpoint="wss://example.test/realtime",
            api_key="sk-secret",
            provider_voice_id="voice-secret",
            system_prompt="Speak clearly.",
        )

        redacted = config.redacted()

        self.assertNotIn("sk-secret", str(redacted))
        self.assertNotIn("voice-secret", str(redacted))
        self.assertEqual(redacted["provider"], "qwen")
        self.assertEqual(redacted["model"], "qwen-audio-3.1-realtime-plus")

    def test_unknown_provider_fails_with_typed_error_without_fallback(self):
        config = RealtimeRuntimeConfig(
            provider="unsupported",
            model="model",
            endpoint="wss://example.test/realtime",
            api_key="secret",
            provider_voice_id="voice",
            system_prompt="prompt",
        )

        with self.assertRaisesRegex(RealtimeRuntimeError, "unsupported"):
            create_realtime_provider(config)

    def test_registered_provider_receives_the_requested_runtime_config(self):
        received = []

        def make_adapter(config):
            received.append(config)
            return object()

        register_realtime_provider("test-factory-provider", make_adapter)
        config = RealtimeRuntimeConfig(
            provider="test-factory-provider",
            model="test-model",
            endpoint="wss://example.test/realtime",
            api_key="secret",
            provider_voice_id="voice",
            system_prompt="prompt",
        )

        adapter = create_realtime_provider(config)

        self.assertIsInstance(adapter, object)
        self.assertEqual(received, [config])

    def test_provider_initialization_error_is_exposed_as_typed_runtime_error(self):
        def broken_adapter(config):
            raise ValueError("provider rejected configuration")

        register_realtime_provider("test-broken-provider", broken_adapter)
        config = RealtimeRuntimeConfig(
            provider="test-broken-provider",
            model="test-model",
            endpoint="wss://example.test/realtime",
            api_key="secret",
            provider_voice_id="voice",
            system_prompt="prompt",
        )

        with self.assertRaisesRegex(RealtimeRuntimeError, "test-broken-provider"):
            create_realtime_provider(config)


if __name__ == "__main__":
    unittest.main()
