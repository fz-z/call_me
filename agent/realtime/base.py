"""Shared contracts for provider-backed realtime voice sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class RealtimeRuntimeError(RuntimeError):
    """A realtime provider or runtime operation could not be completed safely."""


@dataclass(frozen=True)
class RealtimeRuntimeConfig:
    provider: str
    model: str
    endpoint: str
    api_key: str
    provider_voice_id: str
    system_prompt: str

    def redacted(self) -> dict[str, str]:
        """Return diagnostics-safe configuration without usable credentials."""
        return {
            "provider": self.provider,
            "model": self.model,
            "endpoint": self.endpoint,
            "api_key": "***",
            "provider_voice_id": "***",
            "system_prompt": self.system_prompt,
        }


@dataclass(frozen=True)
class RealtimeEvent:
    type: str
    data: dict[str, Any]


class RealtimeProviderAdapter(Protocol):
    """A provider adapter drives a bridge for one realtime call session."""

    async def run(self, config: RealtimeRuntimeConfig, bridge: Any) -> None:
        """Run until the room or provider session closes."""

    async def close(self) -> None:
        """Release provider resources. Must be safe to call repeatedly."""
