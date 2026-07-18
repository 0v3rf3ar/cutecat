from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator


class ProviderError(Exception):
    ...

class Provider(ABC):
    id: str
    display_name: str
    description: str
    supports_tools: bool = True
    supports_images: bool = False
    supports_audio: bool = False
    audio_formats: tuple[str, ...] = ("wav", "mp3")

    @abstractmethod
    def validate_key(self, api_key: str) -> bool:
        ...

    @abstractmethod
    def list_models(self, api_key: str) -> list[str]:
        ...

    @abstractmethod
    def stream_chat(
        self,
        api_key: str,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> Iterator[tuple[str, object]]:
        ...
