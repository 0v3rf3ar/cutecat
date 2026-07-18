from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterator

import requests

from cutecat.providers.base import Provider, ProviderError

TIMEOUT = 15
CHAT_TIMEOUT = 600

_NON_CHAT = (
    "embedding", "whisper", "tts", "audio", "transcribe", "dall-e", "dalle",
    "image", "moderation", "realtime", "search", "-edit", "babbage", "davinci",
    "ada", "curie", "rerank", "guard", "computer-use", "codex-mini",
    "flux", "sdxl", "stable-diffusion", "eleven", "kokoro", "playai", "imagen",
    "veo", "sora", "riffusion", "midjourney", "recraft", "ideogram", "speech",
    "voice", "upscale",
)


class OpenAICompatibleProvider(Provider):

    BASE_URL: str = ""
    STATIC_MODELS: list[str] = []
    FILTER_CHAT_MODELS: bool = False
    TOOL_CALL_FALLBACK_EXTRA: dict | None = None
    SEND_USAGE: bool = True

    def _headers(self, api_key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}"}

    def _normalize_model_id(self, model_id: str) -> str:
        """Clean an id from /models into what /chat/completions expects."""
        return model_id

    #validate

    def validate_key(self, api_key: str) -> bool:
        try:
            resp = requests.get(
                f"{self.BASE_URL}/models",
                headers=self._headers(api_key),
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            raise ProviderError(f"Could not reach {self.display_name}: {exc}") from exc
        if resp.status_code in (401, 403):
            return False
        return True

    #list

    def list_models(self, api_key: str) -> list[str]:
        try:
            resp = requests.get(
                f"{self.BASE_URL}/models",
                headers=self._headers(api_key),
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            if self.STATIC_MODELS:
                return list(self.STATIC_MODELS)
            raise ProviderError(f"Failed to list models: {exc}") from exc
        if resp.status_code in (401, 403):
            raise ProviderError(f"{self.display_name} rejected the API key")
        if resp.status_code >= 400 or not resp.content:
            if self.STATIC_MODELS:
                return list(self.STATIC_MODELS)
            raise ProviderError(f"{self.display_name} could not list models")
        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            if self.STATIC_MODELS:
                return list(self.STATIC_MODELS)
            raise ProviderError(
                f"{self.display_name} returned an unexpected response"
            ) from exc
        raw = data.get("data") if isinstance(data, dict) else data
        if not isinstance(raw, list):
            raw = []
        ids = []
        for entry in raw:
            model_id = entry.get("id") if isinstance(entry, dict) else entry
            if isinstance(model_id, str) and model_id:
                ids.append(self._normalize_model_id(model_id))
        if self.FILTER_CHAT_MODELS:
            ids = [m for m in ids if not any(k in m.lower() for k in _NON_CHAT)]
        ids = sorted(set(ids))
        if not ids and self.STATIC_MODELS:
            return list(self.STATIC_MODELS)
        return ids

    #chat

    def _to_openai_messages(self, messages: list[dict]) -> list[dict]:
        """Translate cutecat's Ollama-style history into OpenAI's shape:
        assistant tool_calls need ids + string arguments, and tool results
        reference that id via tool_call_id (paired in call order)."""
        out: list[dict] = []
        id_queue: deque[str] = deque()
        n = 0
        for m in messages:
            role = m.get("role")
            if role == "assistant" and m.get("tool_calls"):
                tcs = []
                for tc in m["tool_calls"]:
                    fn = tc.get("function", {})
                    cid = f"call_{n}"
                    n += 1
                    id_queue.append(cid)
                    args = fn.get("arguments", {})
                    args_str = args if isinstance(args, str) else json.dumps(args)
                    out_tc = {
                        "id": cid,
                        "type": "function",
                        "function": {"name": fn.get("name", ""), "arguments": args_str},
                    }
                    # replay opaque data (Gemini's thought_signature) verbatim
                    if tc.get("extra_content"):
                        out_tc["extra_content"] = tc["extra_content"]
                    elif self.TOOL_CALL_FALLBACK_EXTRA is not None:
                        out_tc["extra_content"] = self.TOOL_CALL_FALLBACK_EXTRA
                    tcs.append(out_tc)
                out.append(
                    {"role": "assistant", "content": m.get("content") or None, "tool_calls": tcs}
                )
            elif role == "tool":
                cid = id_queue.popleft() if id_queue else f"call_{n}"
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": cid,
                        "content": m.get("content", ""),
                    }
                )
            elif role == "user" and m.get("media"):
                out.append({"role": "user", "content": self._media_content(m)})
            else:
                out.append({"role": role, "content": m.get("content", "")})
        return out

    def _media_content(self, m: dict) -> list[dict]:
        """A user message with images/audio, in OpenAI's multimodal shape.
        Media this provider can't take is dropped (the text still goes)."""
        parts: list[dict] = []
        text = m.get("content") or ""
        if text:
            parts.append({"type": "text", "text": text})
        for item in m.get("media") or []:
            kind = item.get("kind")
            b64 = item.get("b64")
            if not b64:
                continue
            if kind == "image" and self.supports_images:
                mime = item.get("mime") or "image/png"
                parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                })
            elif kind == "audio" and self.supports_audio:
                parts.append({
                    "type": "input_audio",
                    "input_audio": {"data": b64, "format": item.get("format") or "wav"},
                })
        return parts or [{"type": "text", "text": text}]

    def stream_chat(
        self,
        api_key: str,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> Iterator[tuple[str, object]]:
        payload: dict = {
            "model": model,
            "messages": self._to_openai_messages(messages),
            "stream": True,
        }
        if self.SEND_USAGE:
            payload["stream_options"] = {"include_usage": True}
        if tools:
            payload["tools"] = tools
        headers = {**self._headers(api_key), "Content-Type": "application/json"}
        tool_accum: dict[int, dict] = {}
        try:
            with requests.post(
                f"{self.BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
                stream=True,
                timeout=CHAT_TIMEOUT,
            ) as resp:
                if resp.status_code in (401, 403):
                    raise ProviderError(f"{self.display_name} rejected the API key")
                if resp.status_code >= 400:
                    raise ProviderError(self._error_text(resp))
                for line in resp.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if line == "[DONE]":
                        break
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(data, dict):
                        continue
                    if data.get("error"):
                        raise ProviderError(_msg(data["error"]))
                    usage = _usage(data.get("usage"))
                    if usage:
                        yield ("usage", usage)   # the final chunk carries this
                    choices = data.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    choice = choices[0]
                    if not isinstance(choice, dict):
                        continue
                    delta = choice.get("delta")
                    if not isinstance(delta, dict):
                        continue
                    reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                    if reasoning:
                        yield ("thinking", str(reasoning))
                    content = delta.get("content")
                    if content:
                        yield ("content", content if isinstance(content, str) else str(content))
                    calls = delta.get("tool_calls")
                    for tc in calls if isinstance(calls, list) else []:
                        if not isinstance(tc, dict):
                            continue
                        idx = tc.get("index", 0)
                        if not isinstance(idx, int):
                            idx = 0
                        slot = tool_accum.setdefault(
                            idx, {"name": "", "arguments": "", "extra": None}
                        )
                        fn = tc.get("function")
                        if not isinstance(fn, dict):
                            fn = {}
                        if isinstance(fn.get("name"), str) and fn["name"]:
                            slot["name"] = fn["name"]
                        chunk = fn.get("arguments")
                        if isinstance(chunk, str) and chunk:
                            slot["arguments"] += chunk
                        # Gemini 3 & friends attach a signed reasoning blob here
                        # that must be echoed back on the next turn.
                        if tc.get("extra_content"):
                            slot["extra"] = tc["extra_content"]
        except requests.RequestException as exc:
            raise ProviderError(f"Chat request failed: {exc}") from exc

        for idx in sorted(tool_accum):
            slot = tool_accum[idx]
            if not slot["name"]:
                continue
            raw = slot["arguments"].strip()
            try:
                args = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                args = {"_raw": slot["arguments"]}
            event = {"name": slot["name"], "arguments": args}
            if slot.get("extra"):
                event["extra"] = slot["extra"]
            yield ("tool_call", event)

    @staticmethod
    def _error_text(resp: requests.Response) -> str:
        try:
            return _msg(resp.json()) or f"HTTP {resp.status_code}"
        except ValueError:  # includes requests' JSONDecodeError
            text = (resp.text or "").strip()
            return text[:300] if text else f"HTTP {resp.status_code}"


def _usage(u: object) -> dict | None:
    """Token counts from an OpenAI-shaped usage object, or None."""
    if not isinstance(u, dict):
        return None
    try:
        inp = int(u.get("prompt_tokens") or 0)
        out = int(u.get("completion_tokens") or 0)
    except (TypeError, ValueError):
        return None
    return {"input": inp, "output": out} if (inp or out) else None


def _msg(err: object) -> str:
    """Pull a human message out of whatever shape an error body takes —
    a dict, an {"error": ...} wrapper, or a list of those (Gemini)."""
    if isinstance(err, list):
        return "; ".join(_msg(e) for e in err if e) if err else ""
    if isinstance(err, dict):
        if "error" in err:
            return _msg(err["error"])
        msg = err.get("message")
        return str(msg) if msg else str(err)
    return str(err)


#providers


class OpenAIProvider(OpenAICompatibleProvider):
    id = "openai"
    display_name = "ChatGPT (OpenAI)"
    description = "GPT models from OpenAI"
    BASE_URL = "https://api.openai.com/v1"
    FILTER_CHAT_MODELS = True
    supports_images = True   # GPT-4o and later; a text model just ignores it


class GoogleProvider(OpenAICompatibleProvider):
    id = "google"
    display_name = "Google Gemini"
    description = "Gemini models — has a free tier"
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
    supports_images = True   # Gemini is natively multimodal
    supports_audio = True
    TOOL_CALL_FALLBACK_EXTRA = {
        "google": {"thought_signature": "skip_thought_signature_validator"}
    }

    def _normalize_model_id(self, model_id: str) -> str:
        return model_id[len("models/"):] if model_id.startswith("models/") else model_id


class DeepSeekProvider(OpenAICompatibleProvider):
    id = "deepseek"
    display_name = "DeepSeek"
    description = "DeepSeek chat & reasoner models"
    BASE_URL = "https://api.deepseek.com/v1"


class PerplexityProvider(OpenAICompatibleProvider):
    id = "perplexity"
    display_name = "Perplexity"
    description = "Sonar web-connected models (chat only)"
    BASE_URL = "https://api.perplexity.ai"
    supports_tools = False
    SEND_USAGE = False   # Perplexity streams don't take stream_options cleanly
    STATIC_MODELS = [
        "sonar",
        "sonar-pro",
        "sonar-reasoning",
        "sonar-reasoning-pro",
        "sonar-deep-research",
    ]


class GrokProvider(OpenAICompatibleProvider):
    id = "grok"
    display_name = "Grok (xAI)"
    description = "Grok models from xAI"
    BASE_URL = "https://api.x.ai/v1"
