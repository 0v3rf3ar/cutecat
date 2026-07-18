from cutecat.providers.anthropic import AnthropicProvider
from cutecat.providers.base import Provider
from cutecat.providers.custom import CustomProvider
from cutecat.providers.ollama_cloud import OllamaCloudProvider
from cutecat.providers.openai_compat import (
    DeepSeekProvider,
    GoogleProvider,
    GrokProvider,
    OpenAIProvider,
    PerplexityProvider,
)

# Registry of connectable APIs, shown by /connect. Add new providers here.
PROVIDERS: list[Provider] = [
    OllamaCloudProvider(),
    OpenAIProvider(),
    AnthropicProvider(),
    GoogleProvider(),
    DeepSeekProvider(),
    PerplexityProvider(),
    GrokProvider(),
    CustomProvider(),
]


def get_provider(provider_id: str) -> Provider | None:
    for provider in PROVIDERS:
        if provider.id == provider_id:
            return provider
    return None


__all__ = ["Provider", "PROVIDERS", "get_provider"]
