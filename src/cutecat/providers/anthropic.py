from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterator

import requests

from cutecat.providers.base import Provider, ProviderError

BASE_URL = "https://api.anthropic.com/v1"
API_VERSION = "2023-06-01"
TIMEOUT = 15
CHAT_TIMEOUT = 600
MAX_TOKENS = 8192


class AnthropicProvider(Provider):
    id = "claude"
    display_name = "Claude (Anthropic)"
    description = "Claude models from Anthropic"
    supports_images = True   # Claude 3+ takes images; no audio input
    # Instance-overridable so a custom endpoint can point elsewhere.
    BASE_URL = BASE_URL

    def _headers(self, api_key: str) -> dict[str, str]:
        return {
            "x-api-key": api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }

    def validate_key(self, api_key: str) -> bool:
        try:
            resp = requests.get(
                f"{self.BASE_URL}/models", headers=self._headers(api_key), timeout=TIMEOUT
            )
        except requests.RequestException as exc:
            raise ProviderError(f"Could not reach Anthropic: {exc}") from exc
        if resp.status_code in (401, 403):
            return False
        return resp.status_code < 400

    def list_models(self, api_key: str) -> list[str]:
        try:
            resp = requests.get(
                f"{self.BASE_URL}/models", headers=self._headers(api_key), timeout=TIMEOUT
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise ProviderError(f"Failed to list models: {exc}") from exc
        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise ProviderError("Anthropic returned an unexpected response") from exc
        raw = data.get("data") if isinstance(data, dict) else None
        ids = [
            m.get("id")
            for m in (raw or [])
            if isinstance(m, dict) and isinstance(m.get("id"), str)
        ]
        # Newest first (ids sort roughly by generation).
        return sorted((m for m in ids if m), reverse=True)

    #translate

    def _split(self, messages: list[dict]) -> tuple[str, list[dict]]:
        """Return (system_text, anthropic_messages)."""
        system_parts: list[str] = []
        out: list[dict] = []
        id_queue: deque[str] = deque()
        n = 0
        for m in messages:
            role = m.get("role")
            if role == "system":
                if m.get("content"):
                    system_parts.append(m["content"])
            elif role == "user":
                if m.get("media"):
                    out.append({"role": "user", "content": self._media_blocks(m)})
                else:
                    out.append({"role": "user", "content": m.get("content", "")})
            elif role == "assistant":
                blocks: list[dict] = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for tc in m.get("tool_calls") or []:
                    fn = tc.get("function", {})
                    cid = f"toolu_{n}"
                    n += 1
                    id_queue.append(cid)
                    args = fn.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {"_raw": args}
                    blocks.append(
                        {"type": "tool_use", "id": cid, "name": fn.get("name", ""), "input": args}
                    )
                if not blocks:
                    blocks = [{"type": "text", "text": ""}]
                out.append({"role": "assistant", "content": blocks})
            elif role == "tool":
                cid = id_queue.popleft() if id_queue else f"toolu_{n}"
                block = {
                    "type": "tool_result",
                    "tool_use_id": cid,
                    "content": m.get("content", ""),
                }
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
        return "\n\n".join(system_parts), out

    def _media_blocks(self, m: dict) -> list[dict]:
        """A user message with images, in Anthropic's content-block shape.
        Claude has no audio input, so audio is dropped (the text still goes)."""
        blocks: list[dict] = []
        text = m.get("content") or ""
        if text:
            blocks.append({"type": "text", "text": text})
        for item in m.get("media") or []:
            if item.get("kind") == "image" and item.get("b64") and self.supports_images:
                blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": item.get("mime") or "image/png",
                        "data": item["b64"],
                    },
                })
        return blocks or [{"type": "text", "text": text}]

    @staticmethod
    def _tools(tools: list[dict]) -> list[dict]:
        out = []
        for t in tools:
            fn = t.get("function", t)
            out.append(
                {
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters")
                    or {"type": "object", "properties": {}},
                }
            )
        return out

    #chat

    def stream_chat(
        self,
        api_key: str,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> Iterator[tuple[str, object]]:
        system_text, msgs = self._split(messages)
        payload: dict = {
            "model": model,
            "max_tokens": MAX_TOKENS,
            "messages": msgs,
            "stream": True,
        }
        if system_text:
            payload["system"] = system_text
        if tools:
            payload["tools"] = self._tools(tools)

        # index -> {"name": str, "args": str} for in-flight tool_use blocks
        tool_blocks: dict[int, dict] = {}
        tokens = {"input": 0, "output": 0}   # Anthropic reports these in the stream
        try:
            with requests.post(
                f"{self.BASE_URL}/messages",
                headers=self._headers(api_key),
                json=payload,
                stream=True,
                timeout=CHAT_TIMEOUT,
            ) as resp:
                if resp.status_code in (401, 403):
                    raise ProviderError("Anthropic rejected the API key")
                if resp.status_code >= 400:
                    raise ProviderError(self._error_text(resp))
                for line in resp.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw:
                        continue
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(data, dict):
                        continue
                    etype = data.get("type")
                    if etype == "error":
                        raise ProviderError(_msg(data.get("error")))
                    elif etype == "message_start":
                        msg = data.get("message")
                        u = msg.get("usage") if isinstance(msg, dict) else None
                        if isinstance(u, dict):
                            tokens["input"] = int(u.get("input_tokens") or 0)
                    elif etype == "message_delta":
                        u = data.get("usage")
                        if isinstance(u, dict) and u.get("output_tokens"):
                            tokens["output"] = int(u["output_tokens"])
                    elif etype == "content_block_start":
                        cb = data.get("content_block")
                        if not isinstance(cb, dict):
                            cb = {}
                        if cb.get("type") == "tool_use":
                            index = data.get("index", 0)
                            tool_blocks[index if isinstance(index, int) else 0] = {
                                "name": str(cb.get("name") or ""),
                                "args": "",
                            }
                    elif etype == "content_block_delta":
                        delta = data.get("delta")
                        if not isinstance(delta, dict):
                            continue
                        dtype = delta.get("type")
                        if dtype == "text_delta" and delta.get("text"):
                            yield ("content", delta["text"])
                        elif dtype == "thinking_delta" and delta.get("thinking"):
                            yield ("thinking", delta["thinking"])
                        elif dtype == "input_json_delta":
                            slot = tool_blocks.get(data.get("index", 0))
                            if slot is not None:
                                slot["args"] += delta.get("partial_json", "")
                    elif etype == "content_block_stop":
                        slot = tool_blocks.pop(data.get("index", 0), None)
                        if slot and slot["name"]:
                            raw_args = slot["args"].strip()
                            try:
                                args = json.loads(raw_args) if raw_args else {}
                            except json.JSONDecodeError:
                                args = {"_raw": slot["args"]}
                            yield ("tool_call", {"name": slot["name"], "arguments": args})
                    elif etype == "message_stop":
                        if tokens["input"] or tokens["output"]:
                            yield ("usage", dict(tokens))
                        break
        except requests.RequestException as exc:
            raise ProviderError(f"Chat request failed: {exc}") from exc

    @staticmethod
    def _error_text(resp: requests.Response) -> str:
        try:
            return _msg(resp.json()) or f"HTTP {resp.status_code}"
        except ValueError:  # includes requests' JSONDecodeError
            text = (resp.text or "").strip()
            return text[:300] if text else f"HTTP {resp.status_code}"


def _msg(err: object) -> str:
    if isinstance(err, list):
        return "; ".join(_msg(e) for e in err if e) if err else ""
    if isinstance(err, dict):
        if "error" in err:
            return _msg(err["error"])
        msg = err.get("message")
        return str(msg) if msg else str(err)
    return str(err)
