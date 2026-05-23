import json
import unittest

from agent import _sanitize_agent_config_for_log


class AgentLoggingTests(unittest.TestCase):
    def test_sanitizes_api_keys_in_agent_config_log(self):
        raw = json.dumps(
            {
                "agent_id": "agent-1",
                "model_config": {"provider": "qwen", "api_key": "sk-model"},
                "tts_config": {"provider": "qwen", "api_key": "sk-tts"},
            }
        )

        sanitized = _sanitize_agent_config_for_log(raw)

        self.assertNotIn("sk-model", sanitized)
        self.assertNotIn("sk-tts", sanitized)
        self.assertIn('"api_key": "***"', sanitized)


if __name__ == "__main__":
    unittest.main()
