from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from cutecat import config as config_mod

MAX_SKILL_BYTES = 200_000
# An enabled skill is loaded in full on every turn, so a long one is expensive.
LONG_SKILL_LINES = 150


class SkillError(Exception):
    ...


def skill_path(name: str) -> Path:
    return config_mod.SKILLS_DIR / f"{name}.md"


def clean_name(raw: str) -> str:
    name = unquote((raw or "").strip()).replace("\\", "/").split("/")[-1]
    if name.lower().endswith(".md"):
        name = name[:-3]
    if name.lower().endswith(".markdown"):
        name = name[:-9]
    name = re.sub(r"[^\w.-]+", "-", name).strip("-.").lower()
    if not name:
        raise SkillError("that doesn't give a usable skill name — pass --name")
    return name


def raw_url(url: str) -> str:
    m = re.match(
        r"https?://github\.com/([^/]+)/([^/]+)/(?:blob|raw)/([^/]+)/(.+)", url
    )
    if m:
        owner, repo, ref, path = m.groups()
        return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
    return url


def name_from_url(url: str) -> str:
    path = urlparse(url).path
    tail = path.rstrip("/").split("/")[-1] or ""
    if tail.lower() in ("skill.md", "readme.md"):
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2:
            return clean_name(parts[-2])
    return clean_name(tail)


def _validate(name: str, body: str, source: str) -> None:
    if not body.strip():
        raise SkillError(f"{source} is empty")
    if len(body.encode("utf-8")) > MAX_SKILL_BYTES:
        raise SkillError(f"{source} is too big to be a skill ({len(body)} chars)")
    if "\x00" in body:
        raise SkillError(f"{source} is not text")


def warnings(body: str) -> list[str]:
    """Things worth telling the user about a skill, without refusing it."""
    notes = []
    lines = body.splitlines()
    if len(lines) > LONG_SKILL_LINES:
        notes.append(
            f"it is {len(lines)} lines — an enabled skill is loaded in full on"
            " every turn, so this one will cost real tokens"
        )
    if body.lstrip().startswith("---"):
        notes.append(
            "it starts with YAML frontmatter (from another agent's format);"
            " cutecat ignores it, it just costs a few tokens"
        )
    if re.search(r"\]\(\.{0,2}/", body):
        notes.append(
            "it links to other files in its repo, which were NOT fetched —"
            " cutecat skills are a single file"
        )
    return notes


def save(name: str, body: str, *, force: bool = False) -> Path:
    config_mod.ensure_dirs()
    target = skill_path(name)
    if target.exists() and not force:
        raise SkillError(f"a skill called {name!r} already exists — pass --force")
    target.write_text(body, encoding="utf-8")
    return target


def add_from_path(source: str, name: str | None = None, *, force: bool = False):
    path = Path(source).expanduser()
    if not path.is_file():
        raise SkillError(f"no such file: {path}")
    try:
        body = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise SkillError(f"could not read {path}: {exc}") from exc
    name = clean_name(name or path.name)
    _validate(name, body, str(path))
    return name, body


def fetch(url: str, name: str | None = None):
    import requests

    url = raw_url(url.strip())
    if not re.match(r"https?://", url, re.I):
        raise SkillError(f"not a url: {url}")
    try:
        resp = requests.get(url, timeout=30)
    except requests.RequestException as exc:
        raise SkillError(f"could not fetch {url}: {exc}") from exc
    if resp.status_code >= 400:
        raise SkillError(f"{url} returned HTTP {resp.status_code}")
    ctype = resp.headers.get("content-type", "")
    if "html" in ctype.lower():
        raise SkillError(
            f"{url} returned a web page, not a markdown file"
            " — link to the raw .md (on GitHub, the 'Raw' button)"
        )
    body = resp.text
    name = clean_name(name) if name else name_from_url(url)
    _validate(name, body, url)
    return name, body


def remove(name: str) -> Path:
    name = clean_name(name)
    path = skill_path(name)
    if not path.exists():
        raise SkillError(f"no skill called {name!r}")
    path.unlink()
    cfg = config_mod.load_config()
    if (cfg.get("skills") or {}).pop(name, None) is not None:
        config_mod.save_config(cfg)
    return path


def set_enabled(name: str, enabled: bool) -> str:
    name = clean_name(name)
    if not skill_path(name).exists():
        raise SkillError(f"no skill called {name!r}")
    cfg = config_mod.load_config()
    cfg.setdefault("skills", {})[name] = enabled
    config_mod.save_config(cfg)
    return name


def read(name: str) -> str:
    name = clean_name(name)
    path = skill_path(name)
    if not path.exists():
        raise SkillError(f"no skill called {name!r}")
    return path.read_text(encoding="utf-8", errors="replace")


def listing() -> list[dict]:
    cfg = config_mod.load_config()
    enabled = cfg.get("skills") or {}
    out = []
    for name in config_mod.list_skills():
        path = skill_path(name)
        try:
            lines = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            lines = 0
        out.append({
            "name": name,
            "on": bool(enabled.get(name)),
            "lines": lines,
            "bundled": (Path(__file__).parent / "bundled_skills" / f"{name}.md").exists(),
        })
    return out


def reset(force: bool = False) -> list[str]:
    return config_mod.install_bundled_skills(overwrite=force)


def export(name: str, dest: str) -> Path:
    """Copy a skill out, to share it."""
    body = read(name)
    target = Path(dest).expanduser()
    if target.is_dir():
        target = target / f"{clean_name(name)}.md"
    target.write_text(body, encoding="utf-8")
    return target


def new(name: str) -> Path:
    name = clean_name(name)
    title = name.replace("-", " ").capitalize()
    body = (
        f"# {title}\n\n"
        "Use when <the situation that should trigger this skill>.\n\n"
        "<The one principle, stated plainly.>\n\n"
        "## Rules\n\n"
        "- Concrete, checkable instructions.\n"
        "- A short worked example beats a paragraph of advice.\n"
    )
    return save(name, body)


def copy_into(name: str, body: str, *, force: bool = False) -> Path:
    return save(name, body, force=force)


__all__ = [
    "SkillError", "add_from_path", "clean_name", "copy_into", "export", "fetch",
    "listing", "name_from_url", "new", "raw_url", "read", "remove", "reset",
    "set_enabled", "skill_path", "warnings",
]
