import unittest

from realtime.transcript import RealtimeTranscriptCollector


class RealtimeTranscriptCollectorTests(unittest.TestCase):
    def setUp(self):
        self.collector = RealtimeTranscriptCollector()

    def test_deltas_and_done_are_one_agent_turn(self):
        self.collector.add("response.audio_transcript.delta", {"response_id": "r1", "delta": "你"}, 0.2)
        self.collector.add("response.audio_transcript.delta", {"response_id": "r1", "delta": "好"}, 0.3)
        self.collector.add("response.audio_transcript.done", {"response_id": "r1", "transcript": "你好"}, 0.4)
        self.assertEqual(self.collector.turns, [{"role": "assistant", "text": "你好", "time": 0.2, "granularity": "turn"}])

    def test_distinct_responses_remain_distinct(self):
        self.collector.add("response.audio_transcript.delta", {"response_id": "r1", "delta": "你好"}, 0.2)
        self.collector.add("response.audio_transcript.delta", {"response_id": "r2", "delta": "再见"}, 2.0)
        self.assertEqual([turn["text"] for turn in self.collector.turns], ["你好", "再见"])

    def test_interrupted_response_keeps_partial_text(self):
        self.collector.add("response.audio_transcript.delta", {"response_id": "r1", "delta": "说到一"}, 0.2)
        self.collector.add("response.audio_transcript.delta", {"response_id": "r1", "delta": "半"}, 0.3)
        self.assertEqual(self.collector.turns[0]["text"], "说到一半")

    def test_done_replaces_partial_text_and_repeated_done_does_not_duplicate(self):
        self.collector.add("response.audio_transcript.delta", {"response_id": "r1", "delta": "hello"}, 0.2)
        self.collector.add("response.audio_transcript.done", {"response_id": "r1", "transcript": "hello world"}, 0.4)
        self.collector.add("response.audio_transcript.done", {"response_id": "r1", "transcript": "hello world"}, 0.5)
        self.assertEqual(self.collector.turns, [{"role": "assistant", "text": "hello world", "time": 0.2, "granularity": "turn"}])

    def test_user_completion_is_one_turn_and_unrelated_events_are_ignored(self):
        self.collector.add("conversation.item.input_audio_transcription.delta", {"item_id": "u1", "text": "你"}, 0.1)
        self.collector.add("conversation.item.input_audio_transcription.completed", {"item_id": "u1", "transcript": "你好"}, 0.5)
        self.collector.add("conversation.item.input_audio_transcription.completed", {"item_id": "u1", "transcript": "你好"}, 0.6)
        self.collector.add("response.audio.delta", {"delta": "audio"}, 0.7)
        self.assertEqual(self.collector.turns, [{"role": "user", "text": "你好", "time": 0.5, "granularity": "turn"}])

    def test_late_user_transcription_precedes_the_reply_already_in_progress(self):
        self.collector.add("response.audio_transcript.delta", {"response_id": "greeting", "delta": "欢迎"}, 0.2)
        self.collector.add("conversation.item.input_audio_transcription.completed", {"item_id": "u1", "transcript": "第一个问题"}, 1.0)
        self.collector.add("response.audio_transcript.delta", {"response_id": "r1", "delta": "第一个回答"}, 1.5)
        self.collector.add("response.audio_transcript.delta", {"response_id": "r2", "delta": "第二个回答"}, 5.0)
        self.collector.add("conversation.item.input_audio_transcription.completed", {"item_id": "u2", "transcript": "第二个问题"}, 5.2)

        self.assertEqual(
            [(turn["role"], turn["text"]) for turn in self.collector.turns],
            [
                ("assistant", "欢迎"),
                ("user", "第一个问题"),
                ("assistant", "第一个回答"),
                ("user", "第二个问题"),
                ("assistant", "第二个回答"),
            ],
        )

    def test_blank_fragments_are_ignored_but_internal_spaces_are_preserved(self):
        self.collector.add("response.audio_transcript.delta", {"response_id": "r1", "delta": "hello"}, 0.2)
        self.collector.add("response.audio_transcript.delta", {"response_id": "r1", "delta": " world"}, 0.3)
        self.collector.add("response.audio_transcript.delta", {"response_id": "r1", "delta": ""}, 0.4)
        self.assertEqual(self.collector.turns[0]["text"], "hello world")


if __name__ == "__main__":
    unittest.main()
