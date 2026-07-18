from __future__ import annotations

from collections.abc import Iterator

from cutecat.providers.anthropic import AnthropicProvider
from cutecat.providers.base import Provider, ProviderError
from cutecat.providers.openai_compat import OpenAICompatibleProvider


class _CustomOpenAI(OpenAICompatibleProvider):
    id = "custom"
    display_name = "Custom API"

    def __init__(self, base_url: str):
        self.BASE_URL = base_url


class _CustomAnthropic(AnthropicProvider):
    id = "custom"
    display_name = "Custom API"

    def __init__(self, base_url: str):
        self.BASE_URL = base_url


class CustomProvider(Provider):

    id = "custom"
    display_name = "Custom API"
    description = "your own endpoint — OpenAI- or Anthropic-compatible"
    # optimistic; a text-only model ignores images, and tool-call refusals fall
    # back to plain chat
    supports_tools = True
    supports_images = True

    @staticmethod
    def settings() -> tuple[str, str]:
        """(base_url, wire) from config. Raises if it hasn't been set up."""
        from cutecat import config as config_mod

        c = config_mod.load_config().get("custom") or {}
        base = (c.get("base_url") or "").strip().rstrip("/")
        wire = (c.get("wire") or "openai").strip().lower()
        if not base:
            raise ProviderError(
                "no custom endpoint set — run /connect and pick Custom API")
        return base, (wire if wire in ("openai", "anthropic") else "openai")

    def _delegate(self) -> Provider:
        base, wire = self.settings()
        return _CustomAnthropic(base) if wire == "anthropic" else _CustomOpenAI(base)

    def validate_key(self, api_key: str) -> bool:
        return self._delegate().validate_key(api_key)

    def list_models(self, api_key: str) -> list[str]:
        return self._delegate().list_models(api_key)

    def stream_chat(
        self,
        api_key: str,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> Iterator[tuple[str, object]]:
        yield from self._delegate().stream_chat(api_key, model, messages, tools)
