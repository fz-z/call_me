"""Explicit provider factory. Unknown providers never fall back to pipeline mode."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .base import RealtimeRuntimeConfig, RealtimeRuntimeError


ProviderBuilder = Callable[[RealtimeRuntimeConfig], Any]
_PROVIDER_BUILDERS: dict[str, ProviderBuilder] = {}


def register_realtime_provider(provider: str, builder: ProviderBuilder) -> None:
    normalized_provider = provider.strip().lower()
    if not normalized_provider:
        raise ValueError("provider must not be empty")
    _PROVIDER_BUILDERS[normalized_provider] = builder


def create_realtime_provider(config: RealtimeRuntimeConfig) -> Any:
    provider = config.provider.strip().lower()
    builder = _PROVIDER_BUILDERS.get(provider)
    if builder is None:
        raise RealtimeRuntimeError(f"Unsupported realtime provider: {config.provider}")
    try:
        return builder(config)
    except RealtimeRuntimeError:
        raise
    except Exception as exc:
        raise RealtimeRuntimeError(f"Failed to initialize realtime provider: {config.provider}") from exc
