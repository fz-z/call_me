"""Turn-level call-log transcripts from incremental realtime provider events."""

from __future__ import annotations


class RealtimeTranscriptCollector:
    def __init__(self) -> None:
        self.turns: list[dict] = []
        self._responses: dict[str, dict] = {}
        self._users: dict[str, dict] = {}
        self._fallback_response = 0
        self._fallback_finalized = False

    def add(self, event_type: str, data: dict, elapsed: float) -> None:
        if not isinstance(data, dict):
            return
        if event_type == "conversation.item.input_audio_transcription.completed":
            text = data.get("transcript")
            if not isinstance(text, str) or not text.strip():
                return
            item_id = data.get("item_id")
            key = str(item_id) if item_id else None
            turn = self._users.get(key) if key is not None else None
            if turn is None:
                turn = {"role": "user", "text": text.strip(), "time": elapsed, "granularity": "turn"}
                self.turns.append(turn)
                if key is not None:
                    self._users[key] = turn
            else:
                turn["text"] = text.strip()
            return

        if event_type not in {"response.audio_transcript.delta", "response.audio_transcript.done"}:
            return
        field = "delta" if event_type.endswith(".delta") else "transcript"
        text = data.get(field)
        if not isinstance(text, str) or not text:
            return

        response_id = data.get("response_id") or data.get("item_id")
        if response_id:
            key = str(response_id)
        else:
            if self._fallback_finalized and event_type.endswith(".delta"):
                self._fallback_response += 1
                self._fallback_finalized = False
            key = f"fallback:{self._fallback_response}"

        response = self._responses.get(key)
        if response is None:
            if not text.strip():
                return
            turn = {"role": "assistant", "text": "", "time": elapsed, "granularity": "turn"}
            response = {"turn": turn, "parts": {}}
            self._responses[key] = response
            self.turns.append(turn)

        part_key = (data.get("item_id"), data.get("content_index", 0))
        parts = response["parts"]
        if event_type.endswith(".done"):
            parts[part_key] = text
            if not response_id:
                self._fallback_finalized = True
        else:
            parts[part_key] = parts.get(part_key, "") + text
        response["turn"]["text"] = "".join(parts.values()).strip()
