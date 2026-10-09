"""Builds the configured model provider. The only place that knows which adapters exist.

Switching providers is configuration only (``AUREVIA_AI_PROVIDER`` plus that provider's
key): nothing above the Model Gateway changes. Adapters are imported lazily, so a deployment
using one provider never loads the other's SDK.
"""

from __future__ import annotations

from typing import Protocol

from aurevia.config import Settings
from aurevia.providers.model import ModelProvider


class ClosableModelProvider(ModelProvider, Protocol):
    async def aclose(self) -> None: ...


def build_model_provider(settings: Settings) -> ClosableModelProvider | None:
    """The selected provider, or ``None`` when its key is not configured."""
    key = settings.provider_api_key
    if key is None:
        return None
    if settings.ai_provider == "gemini":
        from aurevia.providers.gemini_model import GeminiModelProvider

        return GeminiModelProvider(api_key=key.get_secret_value(), effort=settings.llm_effort)

    from aurevia.providers.anthropic_model import AnthropicModelProvider

    return AnthropicModelProvider(
        api_key=key.get_secret_value(),
        effort=settings.llm_effort,
        server_fallback=settings.resolved_fallback_policy == "server_default",
    )


def missing_key_variable(settings: Settings) -> str:
    """The environment variable to set for the selected provider (a name, never a value)."""
    return f"AUREVIA_{settings.ai_provider.upper()}_API_KEY"
