from __future__ import annotations

DISCORD_LIMIT = 2000
CHUNK_LIMIT = 1900
FENCE = "```"

DISCORD_BREVITY = (
    "# you are answering in Discord, not a terminal\n\n"
    "Keep replies short — a few sentences, not an essay. Lead with the answer. "
    "Do NOT narrate your steps, restate the question, explain what you are about "
    "to do, or pad with pleasantries; just do the task and give the result. "
    "When you show code or a diff, show only the part that matters, in a fenced "
    "code block. Prefer one short message: only go long when the content "
    "genuinely needs it (a whole file the user asked for). Use Discord markdown; "
    "no terminal-only tricks."
)


def _fence_language(line: str) -> str | None:
    stripped = line.strip()
    if stripped.startswith(FENCE):
        return stripped[len(FENCE):].strip()
    return None


def split_message(text: str, limit: int = CHUNK_LIMIT) -> list[str]:
    text = (text or "").rstrip("\n")
    if not text:
        return [""]
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    cur: list[str] = []
    size = 0
    open_lang: str | None = None  # the language of the currently-open fence

    def flush(reopen: bool) -> None:
        nonlocal cur, size
        body = "\n".join(cur)
        if open_lang is not None:
            body += "\n" + FENCE      # close the block so the chunk is valid
        chunks.append(body)
        cur, size = [], 0
        if reopen and open_lang is not None:
            opener = FENCE + open_lang
            cur.append(opener)
            size = len(opener) + 1

    for raw in text.split("\n"):
        # Break a single over-long line into pieces that each fit.
        pieces: list[str] = []
        room = limit - len(FENCE) - 2
        line = raw
        while len(line) > room:
            pieces.append(line[:room])
            line = line[room:]
        pieces.append(line)

        for piece in pieces:
            need = len(piece) + 1
            reserve = len("\n" + FENCE) if open_lang is not None else 0
            if cur and size + need + reserve > limit:
                flush(reopen=True)
            cur.append(piece)
            size += need
            lang = _fence_language(piece)
            if lang is not None:
                open_lang = None if open_lang is not None else lang

    if cur:
        chunks.append("\n".join(cur))
    return [c for c in chunks if c] or [""]


#access


def configured(cfg: dict) -> bool:
    d = cfg.get("discord") or {}
    return bool(d.get("token") and d.get("owner_id") and d.get("channel_id"))


def is_allowed(cfg: dict, *, author_id, channel_id, parent_channel_id=None,
               is_bot: bool = False) -> bool:
    if is_bot:
        return False
    d = cfg.get("discord") or {}
    owner, channel = d.get("owner_id"), d.get("channel_id")
    if not owner or not channel:
        return False
    if str(author_id) != str(owner):
        return False
    return str(channel_id) == str(channel) or str(parent_channel_id or "") == str(channel)


#status line


def fmt_duration(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"0m{s:02d}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m {s:02d}s"


_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def status_line(phase: str, detail: str, seconds: float, tick: int = 0) -> str:
    spin = _SPINNER[tick % len(_SPINNER)]
    icon = {"thinking": spin, "running": "⚙", "working": "🔧",
            "waiting": "⏸"}.get(phase, spin)
    label = {"thinking": "thinking", "running": "running", "working": "working",
             "waiting": "waiting for you"}.get(phase, phase)
    dur = fmt_duration(seconds)
    if detail:
        return f"{icon} {label} · {detail} · {dur}"
    return f"{icon} {label} · {dur}"


#uploads


def upload_limit_bytes(cfg: dict) -> int:
    d = cfg.get("discord") or {}
    mb = d.get("max_upload_mb") or 10
    try:
        mb = int(mb)
    except (TypeError, ValueError):
        mb = 10
    return max(1, mb) * 1024 * 1024
