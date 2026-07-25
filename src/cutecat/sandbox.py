from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

IS_WINDOWS = os.name == "nt"

_CD_RE = re.compile(r"(?:^|[;&|]\s*)\s*(?:cd|chdir|pushd|Set-Location|sl)\s+([^\s;&|]+)", re.I)
_REDIRECT_RE = re.compile(r"(?:\d?>>?|&>)\s*([^\s;&|]+)")

_NULL_SINKS = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty", "&1", "&2", "nul", "NUL"}

# read their arguments
_READERS = {
    "cat", "less", "more", "head", "tail", "grep", "egrep", "fgrep", "rg", "ag",
    "find", "fd", "ls", "ll", "la", "dir", "stat", "file", "wc", "diff", "cmp",
    "du", "df", "readlink", "realpath", "basename", "dirname", "awk", "sed",
    "sort", "uniq", "cut", "nl", "xxd", "od", "strings", "tree", "which",
}


class Sandbox:
    """A directory the agent may write inside. Reads are never restricted;
    writes outside the root are refused rather than offered to the user."""

    def __init__(self, root: str | None, enabled: bool = True):
        self.enabled = enabled and bool(root)
        try:
            self.root = Path(root).expanduser().resolve() if root else None
        except (OSError, RuntimeError):
            self.root = None
            self.enabled = False

    @property
    def label(self) -> str:
        return str(self.root) if self.root else "anywhere"

    def contains(self, path: Path | str, cwd: str | None = None) -> bool:
        if not self.enabled or self.root is None:
            return True
        try:
            target = Path(path).expanduser()
            if not target.is_absolute() and cwd:
                target = Path(cwd) / target
            resolved = self._resolve(target)
        except (OSError, RuntimeError, ValueError):
            return False
        return resolved == self.root or self.root in resolved.parents

    @staticmethod
    def _resolve(target: Path) -> Path:
        """Resolve without requiring the path to exist, so a not-yet-created
        file is judged by where it *would* land."""
        return Path(os.path.normpath(str(target.expanduser().absolute())))

    def deny(self, path: Path | str) -> str:
        return (
            f"error: {path} is outside the workspace ({self.root}). "
            "This agent may only create or change files under the workspace. "
            "Work inside it, or ask the user to move the workspace."
        )

    def check_path(self, path: Path | str, cwd: str | None = None) -> str | None:
        return None if self.contains(path, cwd) else self.deny(path)

    def check_command(self, command: str, cwd: str | None = None) -> str | None:
        """Refuse a command that would write, or move the shell, outside the root."""
        if not self.enabled:
            return None
        for raw in _CD_RE.findall(command):
            target = _unquote(raw)
            if target and not _is_placeholder(target) and not self.contains(target, cwd):
                return (
                    f"error: refusing to cd outside the workspace ({self.root}). "
                    f"The shell must stay under the workspace; {target} is outside it."
                )
        for raw in _REDIRECT_RE.findall(command):
            target = _unquote(raw)
            if target in _NULL_SINKS or _is_placeholder(target):
                continue
            if not self.contains(target, cwd):
                return self.deny(target)
        for target in write_targets(command):
            if not self.contains(target, cwd):
                return self.deny(target)
        return None


def _unquote(token: str) -> str:
    return token.strip().strip("'\"")


def _is_placeholder(token: str) -> bool:
    """A variable or glob resolves at run time; judging it statically is noise."""
    return not token or any(c in token for c in "$*?%") or token.startswith("-")


def write_targets(command: str) -> list[str]:
    """Path-looking arguments of commands that create or modify them."""
    out: list[str] = []
    for segment in re.split(r"\|\||&&|;|\||&(?!>)", command):
        try:
            parts = shlex.split(segment, posix=not IS_WINDOWS)
        except ValueError:
            parts = segment.split()
        if not parts:
            continue
        tool = parts[0].rsplit("/", 1)[-1].lower()
        if tool in _READERS:
            continue
        for arg in parts[1:]:
            if _is_placeholder(arg) or not _looks_like_path(arg):
                continue
            out.append(arg)
    return out


def _looks_like_path(token: str) -> bool:
    if token.startswith(("/", "~", "./", "../")):
        return True
    if IS_WINDOWS and re.match(r"^[a-zA-Z]:[\\/]", token):
        return True
    return False


def default_root(cfg: dict, cwd: str | None = None) -> str:
    configured = cfg.get("workspace")
    return configured or cwd or os.getcwd()


def from_config(cfg: dict, cwd: str | None = None) -> Sandbox:
    mode = (cfg.get("sandbox") or "workspace").lower()
    if mode in ("off", "none", "false"):
        return Sandbox(None, enabled=False)
    return Sandbox(default_root(cfg, cwd), enabled=True)
