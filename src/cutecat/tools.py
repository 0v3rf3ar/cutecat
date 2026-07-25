from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from pathlib import Path

from cutecat import policy
from cutecat.diff import compute_diff, diff_stats

MAX_TOOL_OUTPUT = 10_000
MAX_READ_LINES = 2000

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Run a shell command in a real, persistent terminal (cwd and "
                "environment persist between calls). For inspecting, searching, "
                "building and testing."
            ),
            "parameters": {
                "type": "object",
                "required": ["command"],
                "properties": {
                    "command": {"type": "string", "description": "The command line."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a text file, with line numbers. Read before editing. Use "
                "offset/limit to take only the part you need."
            ),
            "parameters": {
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string"},
                    "offset": {"type": "integer", "description": "1-based start line."},
                    "limit": {"type": "integer", "description": "Max lines."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Replace an exact snippet in an existing file. old_string must be "
                "copied verbatim and be unique — send only the lines that change, "
                "never the whole file."
            ),
            "parameters": {
                "type": "object",
                "required": ["path", "old_string", "new_string"],
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string", "description": "Exact text, unique."},
                    "new_string": {"type": "string"},
                    "replace_all": {
                        "type": "boolean",
                        "description": "Replace every occurrence.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": (
                "Create a new file. To change an existing one, use edit_file."
            ),
            "parameters": {
                "type": "object",
                "required": ["path", "content"],
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string", "description": "Full contents."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browse",
            "description": (
                "Open a URL in headless Chrome, running the page's JavaScript. "
                "Use when curl returns an empty shell, or to capture a page."
            ),
            "parameters": {
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string"},
                    "action": {
                        "type": "string",
                        "enum": ["text", "html", "screenshot", "pdf"],
                        "description": "Default text.",
                    },
                    "path": {"type": "string", "description": "Where to save a capture."},
                    "full_page": {
                        "type": "boolean",
                        "description": "Whole page, not just the viewport. Default true.",
                    },
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                    "wait_ms": {"type": "integer", "description": "Script time, default 5000."},
                },
            },
        },
    },
]


TASK_SCHEMA = {
    "type": "function",
    "function": {
        "name": "set_tasks",
        "description": (
            "Post your plan for work that takes three or more steps, then call "
            "again to restack it as you go: exactly one step 'running', finished "
            "ones 'done'. The user watches this list. Skip it for short work."
        ),
        "parameters": {
            "type": "object",
            "required": ["tasks"],
            "properties": {
                "tasks": {
                    "type": "array",
                    "description": "The full list, in order, every time.",
                    "items": {
                        "type": "object",
                        "required": ["title", "status"],
                        "properties": {
                            "title": {"type": "string", "description": "A few words."},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "running", "done"],
                            },
                        },
                    },
                },
            },
        },
    },
}

AGENT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "run_agent",
        "description": (
            "Hand a self-contained piece of work to a subagent, which does it in "
            "its own context and reports back a summary. Use it to keep bulky "
            "work out of this conversation — searching a large codebase, reading "
            "many files to answer one question, or an independent chunk of a "
            "bigger task. Give it everything it needs: it cannot see this "
            "conversation. Do not use it for a single command or file read."
        ),
        "parameters": {
            "type": "object",
            "required": ["description", "prompt"],
            "properties": {
                "description": {
                    "type": "string",
                    "description": "A few words naming the job, for the user.",
                },
                "prompt": {
                    "type": "string",
                    "description": (
                        "The full task, self-contained: what to do, where to "
                        "look, and exactly what to report back."
                    ),
                },
                "kind": {
                    "type": "string",
                    "enum": ["explore", "build"],
                    "description": (
                        "explore (default) investigates and reports without "
                        "changing anything; build may edit files."
                    ),
                },
            },
        },
    },
}

_STATUS_VALUES = ("pending", "running", "done")


def set_tasks(ctx: ToolContext, args: dict) -> str:
    raw = args.get("tasks")
    if not isinstance(raw, list) or not raw:
        return "error: tasks must be a non-empty array"
    tasks = []
    for item in raw:
        if not isinstance(item, dict):
            return "error: each task must be an object with title and status"
        title = _str_arg(item, "title")
        status = (_str_arg(item, "status") or "pending").lower()
        if not title:
            continue
        if status not in _STATUS_VALUES:
            status = "pending"
        tasks.append({"title": title[:80], "status": status})
    if not tasks:
        return "error: no usable tasks"
    sink = getattr(ctx, "set_tasks", None)
    if sink is not None:
        sink(tasks)
    done = sum(1 for t in tasks if t["status"] == "done")
    return f"tasks updated ({done}/{len(tasks)} done)"


def run_agent(ctx: ToolContext, args: dict) -> str:
    spawn = getattr(ctx, "spawn", None)
    if spawn is None:
        return "error: subagents aren't available here — do the work yourself"
    description = _str_arg(args, "description") or "subagent"
    prompt = _str_arg(args, "prompt")
    if not prompt:
        return "error: prompt is required and must describe the whole task"
    kind = (_str_arg(args, "kind") or "explore").lower()
    if kind not in ("explore", "build"):
        kind = "explore"
    try:
        return spawn(description, prompt, kind)
    except Exception as exc:
        return f"error: the subagent failed: {exc.__class__.__name__}: {exc}"


def _truncate(text: str) -> str:
    if len(text) <= MAX_TOOL_OUTPUT:
        return text
    head = text[: MAX_TOOL_OUTPUT]
    return head + f"\n...[truncated {len(text) - MAX_TOOL_OUTPUT} chars]"


class ToolContext:

    def __init__(
        self,
        shell,
        ask_permission: Callable[[str, str], bool],
        ask_tmp: Callable[[], bool],
        note: Callable[[str], None],
        is_cancelled: Callable[[], bool],
        run_job: Callable[[str], str],
        show_diff: Callable[[str, list, int, int], None] | None = None,
        ask_edit: Callable[[str, str], bool] | None = None,
        chromium: str | None = None,
        workspace: str | None = None,
        send_file: Callable[[str, str | None], str] | None = None,
        sandbox=None,
        allow_kind: Callable[[str], bool] | None = None,
        ask_command: Callable[[str, str, str], bool] | None = None,
        set_tasks: Callable[[list], None] | None = None,
        spawn: Callable[[str, str, str], str] | None = None,
    ):
        self.shell = shell
        # Optional path to a Chrome/Chromium for the browse tool ("chromium" in
        # config.json); None means "find whatever is installed".
        self.chromium = chromium
        # The agent may only read/write under this directory. None = anywhere.
        self.workspace = workspace
        # write boundary; reads pass through
        self.sandbox = sandbox
        # (kind) -> already allowed this session?
        self.allow_kind = allow_kind or (lambda _k: False)
        self.ask_command = ask_command or (
            lambda command, reason, _kind: ask_permission(f"run: {command}", reason)
        )
        # unset = not offered
        self.set_tasks = set_tasks
        self.spawn = spawn
        # A frontend-provided tool that sends a file to the user (Discord).
        # When set, the send_file tool is offered to the model.
        self.send_file = send_file
        self.ask_permission = ask_permission   # (title, detail) -> granted?
        self.ask_tmp = ask_tmp                  # () -> granted? (cached by app)
        self.note = note                        # (text) -> show a status line
        self.is_cancelled = is_cancelled        # () -> should we abort?
        # Runs a command as a live job (no timeout; user can stop/background
        # it) and returns the result string. Owned by the app/UI.
        self.run_job = run_job
        self.show_diff = show_diff              # (path, hunks, added, removed)
        # File edits offer an "allow all edits this session" option; falls
        # back to plain permission if not provided.
        self.ask_edit = ask_edit or ask_permission

    def outside_workspace(self, target: Path) -> str | None:
        if not self.workspace:
            return None
        try:
            root = Path(self.workspace).expanduser().resolve()
            resolved = target.expanduser().resolve()
        except (OSError, RuntimeError):
            return f"error: could not resolve {target}"
        if resolved != root and root not in resolved.parents:
            return (
                f"error: {target} is outside the workspace ({root}); "
                "this agent may only touch files under there"
            )
        return None

    def preview_diff(self, path: str, old: str, new: str) -> tuple[int, int]:
        hunks = compute_diff(old, new)
        added, removed = diff_stats(hunks)
        if self.show_diff is not None:
            self.show_diff(path, hunks, added, removed)
        return added, removed


def command_kind(command: str) -> str:
    head = command.strip().split()
    if not head:
        return ""
    tool = head[0].rsplit("/", 1)[-1].lower()
    if tool in ("git", "gh", "npm", "pnpm", "yarn", "docker", "cargo", "go", "pip"):
        sub = head[1].lower() if len(head) > 1 else ""
        return f"{tool} {sub}".strip()
    return tool


def run_command(ctx: ToolContext, args: dict) -> str:
    command = _str_arg(args, "command")
    if not command:
        return "error: no command provided"

    decision = policy.classify(command)
    if decision.touches_tmp and not ctx.ask_tmp():
        return "error: user denied access to the temp directory"

    if decision.verdict != policy.ALLOW:
        cwd = getattr(ctx.shell, "cwd", None)
        blocked = _sandbox_blocked_command(ctx, command, cwd)
        if blocked:
            return blocked

    if _needs_asking(ctx, decision, command):
        if not ctx.ask_command(command, decision.reason, command_kind(command)):
            return "error: user denied permission to run this command"

    return ctx.run_job(command)


def _needs_asking(ctx: ToolContext, decision, command: str) -> bool:
    if decision.verdict == policy.ALLOW:
        return False
    if ctx.allow_kind(command_kind(command)):
        return False
    if decision.verdict == policy.DANGER:
        return True
    return not _sandboxed(ctx)  # a write, already confined


def _sandboxed(ctx: ToolContext) -> bool:
    box = getattr(ctx, "sandbox", None)
    return bool(box is not None and getattr(box, "enabled", False))


def _sandbox_blocked_command(ctx: ToolContext, command: str, cwd) -> str | None:
    box = getattr(ctx, "sandbox", None)
    if box is None:
        return None
    return box.check_command(command, cwd)


def _write_blocked(ctx: ToolContext, target: Path) -> str | None:
    blocked = _ws_blocked(ctx, target)
    if blocked:
        return blocked
    box = getattr(ctx, "sandbox", None)
    if box is None:
        return None
    return box.check_path(target, getattr(ctx.shell, "cwd", None))


SLOW_COMMAND = 60.0
QUIET_COMMAND = 30.0


def format_job_result(command: str, exit_code, output: str,
                      ran_for: float = 0.0, silent_for: float = 0.0) -> str:
    body = output or "(no output)"
    code = "interrupted" if exit_code is None else exit_code
    notes = []
    if ran_for >= SLOW_COMMAND:
        notes.append(f"took {int(ran_for)}s")
    if silent_for >= QUIET_COMMAND and ran_for >= SLOW_COMMAND:
        notes.append(
            f"produced no output for its last {int(silent_for)}s — if you run it "
            "again, expect the same wait, so use a faster command or send it to "
            "the background instead of repeating it"
        )
    head = f"exit code: {code}"
    if notes:
        head += " (" + "; ".join(notes) + ")"
    return _truncate(f"{head}\n{body}")


#arguments


def _str_arg(args: dict, name: str) -> str:
    value = args.get(name)
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return ""
    return str(value).strip()


def _int_arg(args: dict, name: str, default: int, low: int = 0,
             high: int = 1_000_000) -> int | str:
    """The int, or an error string the caller should return as-is."""
    value = args.get(name)
    if value is None or value == "":
        return default
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return f"error: {name} must be a number, got {value!r}"
    if not (low <= number <= high):
        return f"error: {name} must be between {low} and {high}, got {number}"
    return number


def _bool_arg(args: dict, name: str, default: bool) -> bool:
    value = args.get(name)
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "no", "0", "")
    return bool(value)


def _resolve(ctx: ToolContext, path: str) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = Path(ctx.shell.cwd) / target
    return target


def _ws_blocked(ctx, target: Path) -> str | None:
    check = getattr(ctx, "outside_workspace", None)
    return check(target) if callable(check) else None


#newlines


def _read_source(target: Path) -> tuple[str, str]:
    raw = target.read_bytes().decode("utf-8", errors="replace")
    crlf = raw.count("\r\n")
    lf = raw.count("\n") - crlf
    newline = "\r\n" if crlf > lf else "\n"
    return raw.replace("\r\n", "\n"), newline


def _write_source(target: Path, text: str, newline: str) -> None:
    data = text.replace("\r\n", "\n")
    if newline != "\n":
        data = data.replace("\n", newline)
    target.write_bytes(data.encode("utf-8"))


def read_file(ctx: ToolContext, args: dict) -> str:
    path = _str_arg(args, "path")
    if not path:
        return "error: no path provided"
    offset = _int_arg(args, "offset", 1, low=1)
    if isinstance(offset, str):
        return offset
    limit = _int_arg(args, "limit", MAX_READ_LINES, low=1)
    if isinstance(limit, str):
        return limit
    target = _resolve(ctx, path)
    blocked = _ws_blocked(ctx, target)
    if blocked:
        return blocked
    if policy.touches_tmp(str(target)) and not ctx.ask_tmp():
        return "error: user denied access to the temp directory"
    if target.is_dir():
        return f"error: {target} is a directory — use run_command with ls to list it"
    try:
        text, _newline = _read_source(target)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return f"error: {exc}"

    lines = text.splitlines()
    chosen = lines[offset - 1 : offset - 1 + limit]
    ctx.note(f"read {target}")
    width = len(str(offset + len(chosen)))
    numbered = "\n".join(
        f"{offset + i:>{width}}\t{line}" for i, line in enumerate(chosen)
    )
    trailer = ""
    if offset - 1 + limit < len(lines):
        trailer = f"\n...[{len(lines) - (offset - 1 + limit)} more lines]"
    return _truncate(numbered + trailer) or "(empty file)"


def edit_file(ctx: ToolContext, args: dict) -> str:
    path = _str_arg(args, "path")
    old = args.get("old_string")
    new = args.get("new_string")
    replace_all = _bool_arg(args, "replace_all", False)
    if not path:
        return "error: no path provided"
    if old is None or new is None:
        return "error: old_string and new_string are required"
    if not isinstance(old, str) or not isinstance(new, str):
        return "error: old_string and new_string must be text"
    if old == new:
        return "error: old_string and new_string are identical — nothing to change"

    target = _resolve(ctx, path)
    blocked = _write_blocked(ctx, target)
    if blocked:
        return blocked
    if policy.touches_tmp(str(target)) and not ctx.ask_tmp():
        return "error: user denied access to the temp directory"
    try:
        content, newline = _read_source(target)
    except (OSError, UnicodeDecodeError) as exc:
        return f"error: {exc} (use create_file for a new file)"

    count = content.count(old)
    if count == 0:
        return (
            "error: old_string not found in the file. Read the file again and "
            "copy the exact text (including whitespace)."
        )
    if count > 1 and not replace_all:
        return (
            f"error: old_string appears {count} times. Add more surrounding "
            "context to make it unique, or pass replace_all=true."
        )

    updated = content.replace(old, new) if replace_all else content.replace(old, new, 1)
    if updated == content:
        return "error: the edit would not change the file"

    added, removed = ctx.preview_diff(str(target), content, updated)
    if not _sandboxed(ctx) and not ctx.ask_edit(f"edit {target}", f"+{added} -{removed}"):
        return "error: user denied the edit"

    try:
        _write_source(target, updated, newline)  # keeps the file's own newlines
    except OSError as exc:
        return f"error: {exc}"
    ctx.note(f"edited {target}")
    return f"edited {target} (+{added} -{removed})"


def create_file(ctx: ToolContext, args: dict) -> str:
    path = _str_arg(args, "path")
    content = args.get("content")
    if content is None:
        content = ""
    if not isinstance(content, str):
        return "error: content must be text"
    if not path:
        return "error: no path provided"

    target = _resolve(ctx, path)
    blocked = _write_blocked(ctx, target)
    if blocked:
        return blocked
    if policy.touches_tmp(str(target)) and not ctx.ask_tmp():
        return "error: user denied access to the temp directory"

    old = ""
    newline = os.linesep
    if target.exists():
        try:
            old, newline = _read_source(target)
        except (OSError, UnicodeDecodeError):
            old = ""
    added, removed = ctx.preview_diff(str(target), old, content)
    verb = "overwrite" if old else "create"
    if not _sandboxed(ctx) and not ctx.ask_edit(f"{verb} {target}", f"+{added} -{removed}"):
        return f"error: user denied permission to {verb} this file"

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_source(target, content, newline)
    except OSError as exc:
        return f"error: {exc}"
    ctx.note(f"wrote {target}")
    return f"wrote {target} ({len(content)} bytes)"


MAX_PAGE_CHARS = 20_000


def browse(ctx: ToolContext, args: dict) -> str:
    from cutecat import browser as browser_mod

    url = _str_arg(args, "url")
    action = (_str_arg(args, "action") or "text").lower()
    if not url:
        return "error: no url provided"
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    if action not in ("text", "html", "screenshot", "pdf"):
        return f"error: unknown action '{action}' (text, html, screenshot, pdf)"

    try:
        exe = browser_mod.find_browser(ctx.chromium)
    except browser_mod.BrowserError as exc:
        return f"error: {exc}"
    if exe is None:
        return f"error: {browser_mod.INSTALL_HINT}"

    wait_ms = _int_arg(args, "wait_ms", browser_mod.DEFAULT_WAIT_MS, low=0, high=120_000)
    if isinstance(wait_ms, str):
        return wait_ms
    width = _int_arg(args, "width", browser_mod.DEFAULT_WIDTH, low=64, high=10_000)
    if isinstance(width, str):
        return width
    height = _int_arg(args, "height", browser_mod.DEFAULT_HEIGHT, low=64, high=10_000)
    if isinstance(height, str):
        return height

    if action in ("text", "html"):
        ctx.note(f"browsing {url}")
        try:
            html = browser_mod.fetch_html(exe, url, wait_ms=wait_ms)
        except browser_mod.BrowserError as exc:
            return f"error: {exc}"
        body = html if action == "html" else browser_mod.to_text(html)
        if len(body) > MAX_PAGE_CHARS:
            body = body[:MAX_PAGE_CHARS] + f"\n...[truncated, {len(body)} chars total]"
        return body or "(the page rendered empty)"

    suffix = "pdf" if action == "pdf" else "png"
    path = _str_arg(args, "path") or f"screenshot.{suffix}"
    target = _resolve(ctx, path)
    blocked = _write_blocked(ctx, target)
    if blocked:
        return blocked
    if policy.touches_tmp(str(target)) and not ctx.ask_tmp():
        return "error: user denied access to the temp directory"
    verb = "save a PDF of" if action == "pdf" else "screenshot"
    if not _sandboxed(ctx) and not ctx.ask_permission(f"{verb} {url}", f"writes {target}"):
        return f"error: user denied permission to {verb} this page"

    ctx.note(f"capturing {url}")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        size = browser_mod.capture(
            exe, url, str(target),
            pdf=(action == "pdf"),
            full_page=_bool_arg(args, "full_page", True),
            width=width,
            height=height,
            wait_ms=wait_ms,
        )
    except (browser_mod.BrowserError, OSError) as exc:
        return f"error: {exc}"
    ctx.note(f"saved {target}")
    return f"saved {target} ({size} bytes)"


def send_file(ctx: ToolContext, args: dict) -> str:
    """Deliver a file to the user. Only available on frontends that can (Discord);
    ctx.send_file does the actual sending."""
    sender = getattr(ctx, "send_file", None)
    if sender is None:
        return "error: sending files isn't available here"
    path = _str_arg(args, "path")
    if not path:
        return "error: no path provided"
    target = _resolve(ctx, path)
    blocked = _ws_blocked(ctx, target)
    if blocked:
        return blocked
    if not target.is_file():
        return f"error: no such file: {target}"
    caption = _str_arg(args, "caption") or None
    try:
        return sender(str(target), caption)
    except Exception as exc:
        return f"error: could not send {target}: {exc}"

SEND_FILE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "send_file",
        "description": (
            "Send a file (an image, a document, a screenshot) to the user so it "
            "appears in the chat. Use this whenever the user asks you to send, "
            "show, or share a file — do not just describe it. Give the path to an "
            "existing file."
        ),
        "parameters": {
            "type": "object",
            "required": ["path"],
            "properties": {
                "path": {"type": "string", "description": "Path to the file to send."},
                "caption": {"type": "string", "description": "A short caption (optional)."},
            },
        },
    },
}


DISPATCH = {
    "run_command": run_command,
    "read_file": read_file,
    "edit_file": edit_file,
    "create_file": create_file,
    "browse": browse,
    "send_file": send_file,
    "set_tasks": set_tasks,
    "run_agent": run_agent,
}


def execute(ctx: ToolContext, name: str, args: dict) -> str:
    """Run a tool. This never raises: whatever goes wrong, the model gets an
    error string back and can decide what to do about it. A tool that threw
    would abort the whole turn instead."""
    fn = DISPATCH.get(name)
    if fn is None:
        known = ", ".join(sorted(DISPATCH))
        return f"error: unknown tool {name!r} — the tools are: {known}"
    if args is None:
        args = {}
    if isinstance(args, str):
        # Some providers hand back the arguments as a JSON string.
        try:
            args = json.loads(args)
        except ValueError:
            return f"error: could not parse the arguments for {name}: {args[:200]!r}"
    if not isinstance(args, dict):
        return f"error: the arguments for {name} must be an object, got {type(args).__name__}"
    try:
        result = fn(ctx, args)
    except Exception as exc:  # a bug in a tool must not kill the turn
        return f"error: {name} failed: {exc.__class__.__name__}: {exc}"
    if not isinstance(result, str):
        return str(result)
    return result
