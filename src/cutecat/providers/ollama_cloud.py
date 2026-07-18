from __future__ import annotations

import json
from collections.abc import Iterator

import requests

from cutecat.providers.base import Provider, ProviderError

BASE_URL = "https://ollama.com/api"
TIMEOUT = 15
CHAT_TIMEOUT = 300


class OllamaCloudProvider(Provider):
    id = "ollama-cloud"
    display_name = "Ollama Cloud"
    description = "Hosted models on ollama.com"

    def _headers(self, api_key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}"}

    def validate_key(self, api_key: str) -> bool:
        try:
            resp = requests.post(
                f"{BASE_URL}/me", headers=self._headers(api_key), timeout=TIMEOUT
            )
        except requests.RequestException as exc:
            raise ProviderError(f"Could not reach Ollama Cloud: {exc}") from exc
        if resp.status_code in (401, 403):
            return False
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise ProviderError(f"Ollama Cloud returned an error: {exc}") from exc
        return True

    def list_models(self, api_key: str) -> list[str]:
        try:
            resp = requests.get(
                f"{BASE_URL}/tags", headers=self._headers(api_key), timeout=TIMEOUT
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise ProviderError(f"Failed to list models: {exc}") from exc
        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise ProviderError("Ollama Cloud returned an unexpected response") from exc
        raw = data.get("models") if isinstance(data, dict) else None
        models = [
            m.get("name") or m.get("model")
            for m in (raw or [])
            if isinstance(m, dict)
        ]
        return sorted(m for m in models if isinstance(m, str) and m)

    def stream_chat(
        self,
        api_key: str,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> Iterator[tuple[str, object]]:
        payload = {"model": model, "messages": messages, "stream": True}
        if tools:
            payload["tools"] = tools
        try:
            with requests.post(
                f"{BASE_URL}/chat",
                headers=self._headers(api_key),
                json=payload,
                stream=True,
                timeout=CHAT_TIMEOUT,
            ) as resp:
                if resp.status_code in (401, 403):
                    raise ProviderError("Ollama Cloud rejected the API key")
                resp.raise_for_status()
                for line in resp.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    # Never assume the shape of a streamed chunk.
                    if not isinstance(data, dict):
                        continue
                    if data.get("error"):
                        raise ProviderError(str(data["error"]))
                    message = data.get("message")
                    if not isinstance(message, dict):
                        message = {}
                    thinking = message.get("thinking")
                    if thinking:
                        yield ("thinking", str(thinking))
                    content = message.get("content")
                    if content:
                        yield ("content", content if isinstance(content, str) else str(content))
                    calls = message.get("tool_calls")
                    for call in calls if isinstance(calls, list) else []:
                        if not isinstance(call, dict):
                            continue
                        fn = call.get("function")
                        if not isinstance(fn, dict):
                            continue
                        args = fn.get("arguments", {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except json.JSONDecodeError:
                                args = {"_raw": args}
                        if not isinstance(args, dict):
                            args = {"_raw": args}
                        name = fn.get("name")
                        if not isinstance(name, str) or not name:
                            continue
                        yield ("tool_call", {"name": name, "arguments": args})
                    if data.get("done"):
                        # The final chunk carries token counts.
                        inp = data.get("prompt_eval_count")
                        out = data.get("eval_count")
                        if isinstance(inp, int) or isinstance(out, int):
                            yield ("usage", {"input": int(inp or 0),
                                             "output": int(out or 0)})
                        break
        except requests.RequestException as exc:
            raise ProviderError(f"Chat request failed: {exc}") from exc
