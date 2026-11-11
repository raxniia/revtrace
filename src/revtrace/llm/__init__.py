from __future__ import annotations

from ..config import Settings
from .base import Completion, LLMError, Message, Provider, ToolCall, ToolSpec, Usage

__all__ = ["Completion", "LLMError", "Message", "Provider", "ToolCall", "ToolSpec", "Usage", "get_provider"]


def get_provider(settings: Settings) -> Provider:
    if settings.provider == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings.model, settings.api_key, settings.base_url)
    if settings.provider == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(settings.model, settings.api_key, settings.base_url)
    raise LLMError(f"No LLM provider configured (REVTRACE_PROVIDER={settings.provider or 'unset'})")
