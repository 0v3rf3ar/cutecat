from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APP_NAME = "cutecat"

CUTECAT_DIR = Path.home() / ".cutecat"
CONFIG_FILE = CUTECAT_DIR / "config.json"
SKILLS_DIR = CUTECAT_DIR / "skills"
SESSIONS_DIR = CUTECAT_DIR / "sessions"
SYSTEM_PROMPT_FILE = CUTECAT_DIR / "SYSTEM.md"

DEFAULT_SYSTEM_PROMPT = """\
You are cutecat, an AI coding agent in the user's terminal.

# how you work

- Own the task end to end. Keep going until it is done; stop only when it is
  finished or you need something only the user can give you.
- Act, don't narrate. Use your tools instead of describing what you would do,
  and don't announce a plan you are about to carry out anyway.
- If something is ambiguous, take the most reasonable reading, say so in one
  line, and continue.
- Answer in as few words as the question allows — often one line. No preamble,
  no summary of what you just did when the diffs already show it, no "let me
  know if you need anything else". Skip headings and bullets for short
  answers; they are for structure, not decoration.
- Never invent a fact, a file, or an API. Check instead.

# tools

- `run_command` runs in a real, persistent shell: cwd and environment survive
  between calls. Explore with it (ls, find, grep), build, and test.
- Never run something that blocks forever or wants input — no editors, pagers,
  REPLs, or foreground servers. Use `--no-pager`, pipe to `cat`, add a flag to
  make it exit.
- Commands have NO timeout. If one is backgrounded you are told so: do not
  wait for it and do not re-run it — carry on, its output arrives later.
- `browse` runs a page's JavaScript in a real headless browser. Use it when
  `curl` returns an empty shell, or for a screenshot or PDF. For APIs and
  plain files, `curl` is still right.

# editing code

- Change an existing file with `edit_file` — never `create_file`, never a
  shell redirect. `create_file` is for new files only.
- `read_file` first, so `old_string` matches byte for byte.
- Keep `old_string` just big enough to be unique. Never paste a whole file.
- Prefer several small edits over one sweeping rewrite.

# git and github

- Use `git`, and `gh` for anything on GitHub; check `gh auth status` first.
- Inspect before you act, work on a branch, stage precisely, and write commit
  subjects in the imperative with a body explaining *why* when it isn't
  obvious.
- Never commit secrets or build artifacts. Respect .gitignore.

# skills

Skill instructions may follow. Follow one when it applies to the task.
"""

# past defaults; only these are upgraded, never a user's edits
_SHIPPED_PROMPTS = {
    "41af9d153d0a4dd09a51f7e7a5c40cf8c950416484aeea906b50a4b9bdb0e26e",
}

_DEFAULTS: dict[str, Any] = {
    "provider": None,
    "api_key": None,      # the active provider's key (mirrors api_keys[provider])
    "api_keys": {},       # provider id -> key, so /connect never re-asks
    "model": None,
    "skills": {},
    "theme": "dark",
    "agent_mode": "build",  # "build" (execute) or "plan" (write PLAN.md)
    "editor": None,      # binary used by /editor, e.g. "nano" or "code -w";
                         # empty falls back to $VISUAL/$EDITOR
    "chromium": None,    # path to Chrome/Chromium for the browse tool;
                         # empty means "find whatever is installed"
    # agent may only read/write under here; None = no restriction
    "workspace": None,
    # write boundary: "workspace" (default, the launch directory) or "off"
    "sandbox": "workspace",
    # the "Custom API" option; key lives in api_keys["custom"]
    "custom": {
        "base_url": None,    # e.g. https://gateway.example.com/v1
        "wire": "openai",    # "openai" (Chat Completions) or "anthropic" (Messages)
    },
    # The Discord bot. Empty/None disables it. See `cutecat discord`.
    "discord": {
        "token": None,        # bot token — treat like an SSH key to this box
        "owner_id": None,     # your Discord user id: the ONLY one it answers
        "channel_id": None,   # the one channel it listens and replies in
        "guild_id": None,     # your server (for scoping slash commands)
        "max_upload_mb": 10,  # 25/50/100 if the server is boosted
        "stt": None,          # transcription for voice: None|"local"|"api"
    },
}

# Sessions are JSONL: first line metadata, then one message/history entry per line.
SESSION_EXT = ".jsonl"


def ensure_dirs() -> None:
    first_run = not SKILLS_DIR.exists()
    for directory in (CUTECAT_DIR, SKILLS_DIR, SESSIONS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    if not SYSTEM_PROMPT_FILE.exists():
        SYSTEM_PROMPT_FILE.write_text(DEFAULT_SYSTEM_PROMPT, encoding="utf-8")
    else:
        _upgrade_system_prompt()
    if first_run:
        install_bundled_skills()
    _migrate_legacy_config()


def _upgrade_system_prompt() -> None:
    try:
        current = SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")
    except OSError:
        return
    digest = hashlib.sha256(current.encode("utf-8")).hexdigest()
    if digest in _SHIPPED_PROMPTS and current != DEFAULT_SYSTEM_PROMPT:
        try:
            SYSTEM_PROMPT_FILE.write_text(DEFAULT_SYSTEM_PROMPT, encoding="utf-8")
        except OSError:
            pass


def install_bundled_skills(overwrite: bool = False) -> list[str]:
    bundled = Path(__file__).parent / "bundled_skills"
    if not bundled.is_dir():
        return []
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    installed = []
    for source in sorted(bundled.glob("*.md")):
        target = SKILLS_DIR / source.name
        if target.exists() and not overwrite:
            continue
        try:
            shutil.copyfile(source, target)
            installed.append(source.stem)
        except OSError:
            pass
    return installed


def legacy_config_file() -> Path | None:
    try:
        from platformdirs import user_config_dir

        legacy = Path(user_config_dir(APP_NAME, appauthor=False)) / "config.json"
        return legacy if legacy.exists() else None
    except Exception:
        return None


def _migrate_legacy_config() -> None:
    if CONFIG_FILE.exists():
        return
    legacy = legacy_config_file()
    if legacy is None:
        return
    try:
        shutil.copy2(legacy, CONFIG_FILE)
    except OSError:
        pass


#file i/o

def read_text(path: Path) -> str:
    from cutecat import crypto

    data = path.read_bytes()
    if crypto.looks_encrypted(data):
        return crypto.decrypt(data).decode("utf-8", errors="replace")
    return data.decode("utf-8", errors="replace")


def write_text(path: Path, text: str) -> None:
    from cutecat import crypto

    data = text.encode("utf-8")
    if crypto.is_unlocked():
        data = crypto.encrypt(data)
    path.write_bytes(data)


def load_config() -> dict[str, Any]:
    ensure_dirs()
    if not CONFIG_FILE.exists():
        return json.loads(json.dumps(_DEFAULTS))
    try:
        data = json.loads(read_text(CONFIG_FILE))
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(_DEFAULTS))
    merged = json.loads(json.dumps(_DEFAULTS))
    if isinstance(data, dict):
        for key, value in data.items():
            if (isinstance(value, dict) and isinstance(merged.get(key), dict)):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
    for key in ("skills", "api_keys", "discord", "custom"):
        if not isinstance(merged.get(key), dict):
            merged[key] = json.loads(json.dumps(_DEFAULTS[key]))
    provider, api_key = merged.get("provider"), merged.get("api_key")
    if provider and api_key and provider not in merged["api_keys"]:
        merged["api_keys"][provider] = api_key
    elif provider and not api_key:
        merged["api_key"] = merged["api_keys"].get(provider)
    return merged


#api keys


def clean_api_key(raw: str) -> str:
    key = "".join(ch for ch in (raw or "") if ch.isprintable()).strip()
    if "=" in key and key.lower().startswith(("export ", "set ")):
        key = key.split("=", 1)[1].strip()
    for quote in ("'", '"'):
        if len(key) >= 2 and key.startswith(quote) and key.endswith(quote):
            key = key[1:-1].strip()
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    return key


def get_api_key(cfg: dict[str, Any], provider_id: str) -> str | None:
    keys = cfg.get("api_keys") or {}
    return keys.get(provider_id) or None


def set_api_key(cfg: dict[str, Any], provider_id: str, key: str) -> None:
    cfg.setdefault("api_keys", {})[provider_id] = key


def forget_api_key(cfg: dict[str, Any], provider_id: str) -> None:
    (cfg.get("api_keys") or {}).pop(provider_id, None)


class StorageError(Exception):
    ...

def save_config(cfg: dict[str, Any]) -> None:
    try:
        ensure_dirs()
        write_text(CONFIG_FILE, json.dumps(cfg, indent=2, default=str))
    except OSError as exc:
        raise StorageError(f"could not save your settings: {exc}") from exc
    try:
        os.chmod(CONFIG_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def is_connected(cfg: dict[str, Any]) -> bool:
    return bool(cfg.get("provider") and cfg.get("api_key") and cfg.get("model"))


#system prompt


def system_prompt() -> str:
    ensure_dirs()
    try:
        return SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_SYSTEM_PROMPT


#skills


def list_skills() -> list[str]:
    ensure_dirs()
    return sorted(p.stem for p in SKILLS_DIR.glob("*.md"))


def read_skill(name: str) -> str | None:
    path = SKILLS_DIR / f"{name}.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


#sessions


def new_session_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_META_KEYS = ("id", "created", "updated", "title", "provider", "model",
              "tokens_in", "tokens_out", "tokens_cached")


def _compact(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, default=str)


def save_session(session: dict[str, Any]) -> None:
    try:
        _save_session(session)
    except OSError as exc:
        raise StorageError(f"could not save this chat: {exc}") from exc


def _save_session(session: dict[str, Any]) -> None:
    ensure_dirs()
    session["updated"] = now_iso()
    meta = {k: session.get(k) for k in _META_KEYS if session.get(k) is not None}
    lines = [_compact(meta)]
    for msg in session.get("messages") or []:
        lines.append(_compact(msg))
    for entry in session.get("input_history") or []:
        lines.append(_compact({"h": entry}))
    path = SESSIONS_DIR / f"{session['id']}{SESSION_EXT}"
    write_text(path, "\n".join(lines) + "\n")
    legacy = SESSIONS_DIR / f"{session['id']}.json"
    if legacy.exists():
        try:
            legacy.unlink()
        except OSError:
            pass


def _session_ids() -> list[str]:
    ensure_dirs()
    ids: set[str] = set()
    for pattern in (f"*{SESSION_EXT}", "*.json"):
        for p in SESSIONS_DIR.glob(pattern):
            ids.add(p.stem)
    return sorted(ids)


def resolve_session(prefix: str) -> str | None:
    matches = [sid for sid in _session_ids() if sid.startswith(prefix)]
    return matches[0] if len(matches) == 1 else None


def load_session(session_id: str) -> dict[str, Any] | None:
    jsonl = SESSIONS_DIR / f"{session_id}{SESSION_EXT}"
    if jsonl.exists():
        return _load_jsonl(jsonl)
    legacy = SESSIONS_DIR / f"{session_id}.json"
    try:
        return json.loads(read_text(legacy))
    except (OSError, json.JSONDecodeError):
        return None


def _load_jsonl(path: Path) -> dict[str, Any] | None:
    try:
        raw = read_text(path).splitlines()
    except OSError:
        return None
    session: dict[str, Any] = {"messages": [], "input_history": []}
    meta_seen = False
    for line in raw:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not meta_seen:
            session.update(obj)
            meta_seen = True
        elif "role" in obj:
            session["messages"].append(obj)
        elif "h" in obj:
            session["input_history"].append(obj["h"])
    return session if meta_seen else None


def _read_meta(path: Path) -> dict[str, Any] | None:
    try:
        if path.suffix == SESSION_EXT:
            first = read_text(path).split("\n", 1)[0].strip()
            return json.loads(first) if first else None
        return json.loads(read_text(path))
    except (OSError, ValueError):
        return None


def list_sessions() -> list[dict[str, Any]]:
    ensure_dirs()
    by_id: dict[str, dict[str, Any]] = {}
    for pattern in ("*.json", f"*{SESSION_EXT}"):
        for path in SESSIONS_DIR.glob(pattern):
            data = _read_meta(path)
            if data is None:
                continue
            sid = data.get("id") or path.stem
            by_id[sid] = {
                "id": sid,
                "title": data.get("title") or "",
                "created": data.get("created") or "",
                "updated": data.get("updated") or "",
            }
    out = list(by_id.values())
    out.sort(key=lambda s: s.get("updated") or "", reverse=True)
    return out
