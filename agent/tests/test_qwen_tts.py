import asyncio
import unittest

from qwen_tts import _iter_flushed_text_segments


class QwenTTSTests(unittest.TestCase):
    def test_flush_sentinel_yields_current_text_before_input_ends(self):
        class Flush:
            pass

        async def items():
            for item in ("你", "好", Flush(), "再", "见"):
                yield item

        segments = asyncio.run(_collect(_iter_flushed_text_segments(items(), Flush)))

        self.assertEqual(segments, ["你好", "再见"])


async def _collect(segments):
    return [segment async for segment in segments]
