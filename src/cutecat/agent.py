from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from cutecat import tools as tools_mod
from cutecat.providers.base import Provider, ProviderError
from cutecat.tools import TOOL_SCHEMAS, ToolContext

MAX_AGENT_STEPS = 25

# stale tool output
KEEP_RESULTS_VERBATIM = 4
ELIDE_LONGER_THAN = 600

REPEAT_LIMIT = 3

_TOOL_REJECTION = ("tool", "function", "unsupported", "not support")

_WRAP_UP = (
    "You have used up the tool budget for this turn. Stop calling tools and "
    "reply now: what you found or changed, and what is left to do. If you were "
    "stuck in a loop, say what blocked you."
)


#events


@dataclass
class Event:
    """Base class; every event is one of the subclasses below."""


@dataclass
class TurnStarted(Event):
    """A new round with the model begins. A reply that follows a tool call is a
    fresh turn, so a frontend can start a new bubble/message for it."""


@dataclass
class Thinking(Event):
    """Hidden reasoning tokens. Frontends may ignore these (Discord does)."""
    text: str


@dataclass
class Content(Event):
    """Answer tokens. `delta` is the new text, `full` the answer so far."""
    delta: str
    full: str


@dataclass
class ToolStarted(Event):
    name: str
    arguments: dict


@dataclass
class ToolFinished(Event):
    name: str
    result: str


@dataclass
class Usage(Event):
    """Token counts the provider reported for one request. `cached` is the part
    of `input` that was served from the prompt cache."""
    input: int
    output: int
    cached: int = 0


@dataclass
class ToolsDisabled(Event):
    """The provider wouldn't accept tools; the agent continues as a plain chat."""
    reason: str


@dataclass
class Done(Event):
    """The agent finished cleanly. `answer` is its final message."""
    answer: str


@dataclass
class Failed(Event):
    """The turn could not complete. `message` is safe to show a user."""
    message: str


def _call_key(name: str, arguments) -> str:
    try:
        return name + "|" + json.dumps(arguments, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return name + "|" + str(arguments)


def _repeat_warning(name: str, count: int) -> str:
    return (
        f"error: you have already called {name} with these exact arguments "
        f"{count} times in this turn and it was not run again. Repeating it will "
        "not give a different answer. Change something: use different arguments, "
        "a different tool, or accept the result you already have and move on. If "
        "you are stuck, say so instead of retrying."
    )


def _elide(name: str, content: str) -> str:
    """Keep the head — for a command that's the exit code — and the tail, which
    is usually the error. Drop the middle."""
    lines = content.splitlines()
    kept = lines[:2] + ["   ...", f"   [{len(lines) - 5} lines elided]", "   ..."] + lines[-3:]
    return "\n".join(kept) + f"\n[full {name} output dropped from context]"


def prune(messages: list[dict]) -> list[dict]:
    """A cheaper view of the history to send. Never mutates the session."""
    out: list[dict] = []
    seen = 0
    for m in reversed(messages):
        if m.get("role") == "tool":
            seen += 1
            content = m.get("content") or ""
            if seen > KEEP_RESULTS_VERBATIM and len(content) > ELIDE_LONGER_THAN:
                m = {**m, "content": _elide(m.get("tool_name") or "tool", content)}
        out.append(m)
    out.reverse()
    return out


def _unexpected(exc: BaseException) -> str:
    detail = str(exc).strip() or exc.__class__.__name__
    return f"something went wrong talking to the provider: {detail[:300]}"


def _assistant_message(content: str, calls: list[dict]) -> dict:
    """Build the assistant turn to append to the transcript, carrying any opaque
    provider data (e.g. Gemini's thought_signature) that must be replayed."""
    msg: dict = {"role": "assistant", "content": content}
    if calls:
        tool_calls = []
        for c in calls:
            tc: dict = {
                "type": "function",
                "function": {"name": c["name"], "arguments": c["arguments"]},
            }
            if c.get("extra"):
                tc["extra_content"] = c["extra"]
            tool_calls.append(tc)
        msg["tool_calls"] = tool_calls
    return msg


def _wrap_up(
    provider: Provider,
    key: str,
    model: str,
    system: str,
    messages: list[dict],
    cancelled: Callable[[], bool],
) -> Iterator[Event]:
    """Out of steps. Rather than dropping the turn on the floor, spend one more
    call — with no tools, so it cannot start again — asking for an account of
    where things got to."""
    api_messages = [
        {"role": "system", "content": system},
        *prune(messages),
        {"role": "user", "content": _WRAP_UP},
    ]
    yield TurnStarted()
    content = ""
    try:
        for kind, payload in provider.stream_chat(key, model, api_messages, tools=None):
            if cancelled():
                return
            if kind == "content" and payload:
                content += payload
                yield Content(payload, content)
            elif kind == "usage" and isinstance(payload, dict):
                yield Usage(int(payload.get("input") or 0),
                            int(payload.get("output") or 0),
                            int(payload.get("cached") or 0))
    except ProviderError:
        yield Failed("stopped after too many steps")
        return
    if content:
        messages.append({"role": "assistant", "content": content})
        yield Done(content)
    else:
        yield Failed("stopped after too many steps")


def run_agent(
    provider: Provider,
    key: str,
    model: str,
    system: str,
    messages: list[dict],
    ctx: ToolContext,
    *,
    tools_enabled: bool = True,
    extra_schemas: list[dict] | None = None,
    max_steps: int = MAX_AGENT_STEPS,
    cancelled: Callable[[], bool] = lambda: False,
) -> Iterator[Event]:
    """Drive the agent to completion, yielding events. Mutates `messages`.
    """
    tools_disabled = not tools_enabled
    all_tools = TOOL_SCHEMAS + list(extra_schemas or [])
    seen_calls: dict[str, int] = {}
    try:
        for _step in range(max_steps):
            if cancelled():
                return
            yield TurnStarted()
            content = ""
            calls: list[dict] = []
            api_messages = [{"role": "system", "content": system}, *prune(messages)]
            use_tools = provider.supports_tools and not tools_disabled
            sent_tools = all_tools if use_tools else None
            try:
                for kind, payload in provider.stream_chat(
                    key, model, api_messages, tools=sent_tools
                ):
                    if cancelled():
                        return
                    if kind == "thinking" and payload:
                        yield Thinking(str(payload))
                    elif kind == "content" and payload:
                        content += payload
                        yield Content(payload, content)
                    elif kind == "tool_call":
                        calls.append(payload)
                    elif kind == "usage" and isinstance(payload, dict):
                        yield Usage(int(payload.get("input") or 0),
                                    int(payload.get("output") or 0),
                                    int(payload.get("cached") or 0))
            except ProviderError as exc:
                # A provider that rejects the tool schema, before producing
                # anything, gets one retry as a plain chat assistant.
                low = str(exc).lower()
                if (
                    sent_tools is not None
                    and not content
                    and not calls
                    and any(k in low for k in _TOOL_REJECTION)
                ):
                    tools_disabled = True
                    yield ToolsDisabled(
                        "this provider rejected tools — continuing chat-only"
                    )
                    continue
                yield Failed(str(exc))
                return

            messages.append(_assistant_message(content, calls))

            if not calls:
                yield Done(content)
                return

            for call in calls:
                if cancelled():
                    return
                name = call["name"]
                arguments = call.get("arguments") or {}
                call_key = _call_key(name, arguments)
                seen_calls[call_key] = seen_calls.get(call_key, 0) + 1
                yield ToolStarted(name, arguments)
                if seen_calls[call_key] > REPEAT_LIMIT:
                    result = _repeat_warning(name, REPEAT_LIMIT)
                else:
                    result = tools_mod.execute(ctx, name, call["arguments"])
                messages.append(
                    {"role": "tool", "tool_name": name, "content": result}
                )
                yield ToolFinished(name, result)

        yield from _wrap_up(provider, key, model, system, messages, cancelled)
    except ProviderError as exc:
        yield Failed(str(exc))
    except Exception as exc:  # a malformed reply must never kill a frontend
        yield Failed(_unexpected(exc))
