from __future__ import annotations

import math
import os
import random
import threading
from pathlib import Path
from time import monotonic

from rich.text import Text

from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.theme import Theme as AppTheme
from textual.widgets import (
    Collapsible,
    Input,
    Markdown,
    OptionList,
    Rule,
    Static,
    TextArea,
)
from textual.widgets.option_list import Option
from textual.widgets._markdown import MarkdownFence
from textual.worker import get_current_worker

from cutecat import __version__
from cutecat import clipboard
from cutecat import config as config_mod
from cutecat import routines as routines_mod
from cutecat import agent as agent_mod
from cutecat import sandbox as sandbox_mod
from cutecat import tools as tools_mod
from cutecat.providers import PROVIDERS, get_provider
from cutecat.providers.base import Provider, ProviderError
from cutecat.shell import create_shell, shell_kind
from cutecat.tools import ToolContext

SCHEDULE_PROMPT = (
    "Turn the user's request into a routine: a prompt cutecat will run "
    "unattended, on a schedule.\n\n"
    "Reply with ONLY a JSON object, no prose and no code fence:\n"
    '{{"name": "short-kebab-name", "prompt": "...", "cron": "M H D M W", '
    '"once_at": null}}\n\n'
    "- prompt: what the agent should do, written as a complete, self-contained "
    "instruction. Nobody will be there to answer questions, so spell out what "
    "to do and what a good result looks like.\n"
    "- cron: a 5-field cron expression (minute hour day month weekday) for a "
    "recurring routine. The minimum interval is hourly.\n"
    '- once_at: an ISO timestamp ("2026-07-20T09:00") for a one-off run '
    "instead, and then set cron to null.\n"
    "- Use exactly one of cron or once_at; set the other to null.\n"
    "The current local time is {now}. Interpret 'tomorrow', 'in two weeks', "
    "'every weekday at 9' against it."
)

TITLE_PROMPT = (
    "Generate a very short title (3 to 6 words) summarizing the user's request. "
    "Reply with ONLY the title — no quotes, no punctuation at the end, no prefix."
)

WHITE = "#ffffff"
TEXT = "#d8d8d8"
GREY = "#8a8a8a"
DIM = "#5a5a5a"
BLACK = "#000000"
BAR_BG = "#1a1a1a"

PALETTE = {
    "dark": {
        "bg": "#000000", "bar": "#1a1a1a", "panel": "#202020", "hover": "#1f1f1f",
        "text": "#d8d8d8", "strong": "#ffffff", "muted": "#8a8a8a",
        "faint": "#5a5a5a", "userbar": "#3a3a3a",
        "userbg": "#333333",
        "sel-bg": "#ffffff", "sel-fg": "#000000",
    },
    "light": {
        "bg": "#ffffff", "bar": "#e8e8e8", "panel": "#dcdcdc", "hover": "#d4d4d4",
        "text": "#1a1a1a", "strong": "#000000", "muted": "#666666",
        "faint": "#9a9a9a", "userbar": "#cfcfcf",
        "userbg": "#a0a0a0",
        "sel-bg": "#000000", "sel-fg": "#ffffff",
    },
    "default": {
        "bg": "ansi_default", "bar": "ansi_default", "panel": "ansi_default",
        "hover": "ansi_bright_black", "text": "ansi_default", "strong": "ansi_default",
        "muted": "ansi_bright_black", "faint": "ansi_bright_black",
        "userbar": "ansi_bright_black", "userbg": "ansi_default",
        "sel-bg": "ansi_bright_black", "sel-fg": "ansi_default",
    },
    "matrix": {
        "bg": "#000000", "bar": "#02160a", "panel": "#04220e", "hover": "#03190b",
        "text": "#22dd44", "strong": "#00ff41", "muted": "#16a62e",
        "faint": "#0a6b1c", "userbar": "#0a5c22", "userbg": "#052b10",
        "sel-bg": "#00ff41", "sel-fg": "#000000",
    },
    "hacker-red": {  # matrix, but red
        "bg": "#000000", "bar": "#160202", "panel": "#220404", "hover": "#190303",
        "text": "#ff5555", "strong": "#ff2b2b", "muted": "#c21e1e",
        "faint": "#7a1414", "userbar": "#5c0a0a", "userbg": "#2b0505",
        "sel-bg": "#ff2b2b", "sel-fg": "#000000",
    },
    "phosphor": {  # amber CRT glow
        "bg": "#000000", "bar": "#161002", "panel": "#221803", "hover": "#191203",
        "text": "#ffc966", "strong": "#ffb000", "muted": "#cc8800",
        "faint": "#7a5200", "userbar": "#5c3f0a", "userbg": "#2b1d05",
        "sel-bg": "#ffb000", "sel-fg": "#000000",
    },
    "tron": {  # cyan on black
        "bg": "#000000", "bar": "#021616", "panel": "#042222", "hover": "#031919",
        "text": "#4dffff", "strong": "#00fff0", "muted": "#00b3b3",
        "faint": "#006666", "userbar": "#0a5c5c", "userbg": "#052b2b",
        "sel-bg": "#00fff0", "sel-fg": "#000000",
    },
    "frost": {  # icy blue
        "bg": "#000000", "bar": "#02060f", "panel": "#040e1a", "hover": "#03080f",
        "text": "#66b5ff", "strong": "#3aa0ff", "muted": "#2b7ac2",
        "faint": "#164166", "userbar": "#0a2c5c", "userbg": "#05132b",
        "sel-bg": "#3aa0ff", "sel-fg": "#000000",
    },
    "synthwave": {  # neon purple
        "bg": "#000000", "bar": "#0d0216", "panel": "#150422", "hover": "#0f0319",
        "text": "#d580ff", "strong": "#c74dff", "muted": "#9a2ee6",
        "faint": "#5a1a8f", "userbar": "#3a0a5c", "userbg": "#1c052b",
        "sel-bg": "#c74dff", "sel-fg": "#000000",
    },
    "flamingo": {  # hot pink
        "bg": "#000000", "bar": "#16020a", "panel": "#22040e", "hover": "#19030b",
        "text": "#ff8fbb", "strong": "#ff5fa0", "muted": "#c23a70",
        "faint": "#7a2545", "userbar": "#5c0a2c", "userbg": "#2b0513",
        "sel-bg": "#ff5fa0", "sel-fg": "#000000",
    },
    "forest": {  # a softer green on deep green-black
        "bg": "#0f1a14", "bar": "#0c1610", "panel": "#16241c", "hover": "#101c16",
        "text": "#c8e0cf", "strong": "#5fd88a", "muted": "#3a9e64",
        "faint": "#245c3d", "userbar": "#1c4d33", "userbg": "#122b1d",
        "sel-bg": "#5fd88a", "sel-fg": "#0f1a14",
    },
    "dracula": {
        "bg": "#282a36", "bar": "#21222c", "panel": "#343746", "hover": "#2c2e3b",
        "text": "#f8f8f2", "strong": "#ff79c6", "muted": "#bd93f9",
        "faint": "#6272a4", "userbar": "#44475a", "userbg": "#343746",
        "sel-bg": "#ff79c6", "sel-fg": "#282a36",
    },
    "nord": {
        "bg": "#2e3440", "bar": "#272c36", "panel": "#3b4252", "hover": "#333a47",
        "text": "#d8dee9", "strong": "#88c0d0", "muted": "#81a1c1",
        "faint": "#4c566a", "userbar": "#434c5e", "userbg": "#3b4252",
        "sel-bg": "#88c0d0", "sel-fg": "#2e3440",
    },
    "gruvbox": {
        "bg": "#282828", "bar": "#1d2021", "panel": "#3c3836", "hover": "#32302f",
        "text": "#ebdbb2", "strong": "#fe8019", "muted": "#b8bb26",
        "faint": "#928374", "userbar": "#504945", "userbg": "#3c3836",
        "sel-bg": "#fabd2f", "sel-fg": "#282828",
    },
    "monokai": {
        "bg": "#272822", "bar": "#1e1f1a", "panel": "#33342c", "hover": "#2b2c25",
        "text": "#f8f8f2", "strong": "#a6e22e", "muted": "#66d9ef",
        "faint": "#75715e", "userbar": "#49483e", "userbg": "#33342c",
        "sel-bg": "#a6e22e", "sel-fg": "#272822",
    },
    "solarized-dark": {
        "bg": "#002b36", "bar": "#01313d", "panel": "#073642", "hover": "#052f38",
        "text": "#93a1a1", "strong": "#2aa198", "muted": "#268bd2",
        "faint": "#586e75", "userbar": "#0a4b58", "userbg": "#073642",
        "sel-bg": "#2aa198", "sel-fg": "#002b36",
    },
    "solarized-light": {
        "bg": "#fdf6e3", "bar": "#eee8d5", "panel": "#e4ddc8", "hover": "#e9e2cd",
        "text": "#586e75", "strong": "#268bd2", "muted": "#657b83",
        "faint": "#93a1a1", "userbar": "#d9d2bd", "userbg": "#cfc8b3",
        "sel-bg": "#268bd2", "sel-fg": "#fdf6e3",
    },
    "sepia": {  # warm paper
        "bg": "#f4ecd8", "bar": "#e8dcc0", "panel": "#e0d3b3", "hover": "#e4d8bd",
        "text": "#5b4636", "strong": "#3a2c1e", "muted": "#8a7355",
        "faint": "#b0a084", "userbar": "#d8c9a8", "userbg": "#cdbb95",
        "sel-bg": "#5b4636", "sel-fg": "#f4ecd8",
    },
    "midnight": {  # deep navy
        "bg": "#0a0e1a", "bar": "#0d1220", "panel": "#141a2e", "hover": "#0f1524",
        "text": "#c6d0e0", "strong": "#8fb3ff", "muted": "#5a7bb5",
        "faint": "#37456b", "userbar": "#1e2b4d", "userbg": "#141a2e",
        "sel-bg": "#8fb3ff", "sel-fg": "#0a0e1a",
    },
    "catppuccin": {  # Catppuccin Mocha — pastel, two accent hues
        "bg": "#1e1e2e", "bar": "#181825", "panel": "#313244", "hover": "#292c3c",
        "text": "#cdd6f4", "strong": "#cba6f7", "muted": "#89b4fa",
        "faint": "#6c7086", "userbar": "#45475a", "userbg": "#313244",
        "sel-bg": "#cba6f7", "sel-fg": "#1e1e2e",
    },
    "tokyo-night": {
        "bg": "#1a1b26", "bar": "#16161e", "panel": "#24283b", "hover": "#1e2030",
        "text": "#c0caf5", "strong": "#bb9af7", "muted": "#7aa2f7",
        "faint": "#565f89", "userbar": "#414868", "userbg": "#24283b",
        "sel-bg": "#bb9af7", "sel-fg": "#1a1b26",
    },
    "everforest": {  # green + aqua on warm grey
        "bg": "#2d353b", "bar": "#232a2e", "panel": "#343f44", "hover": "#2b3339",
        "text": "#d3c6aa", "strong": "#a7c080", "muted": "#7fbbb3",
        "faint": "#859289", "userbar": "#4f5b58", "userbg": "#3d484d",
        "sel-bg": "#a7c080", "sel-fg": "#2d353b",
    },
    "kanagawa": {  # muted, orange + blue
        "bg": "#1f1f28", "bar": "#16161d", "panel": "#2a2a37", "hover": "#223249",
        "text": "#dcd7ba", "strong": "#ff9e3b", "muted": "#7e9cd8",
        "faint": "#727169", "userbar": "#363646", "userbg": "#2a2a37",
        "sel-bg": "#ff9e3b", "sel-fg": "#1f1f28",
    },
    "vaporwave": {  # pink + cyan on deep purple
        "bg": "#1a0b2e", "bar": "#150826", "panel": "#2a1450", "hover": "#1f0f3a",
        "text": "#ff9ff3", "strong": "#ff6ec7", "muted": "#48d1ff",
        "faint": "#8a5fb5", "userbar": "#3d1a6b", "userbg": "#24104a",
        "sel-bg": "#ff6ec7", "sel-fg": "#1a0b2e",
    },
    "cobalt": {  # deep blue, yellow + orange accents
        "bg": "#002240", "bar": "#001a33", "panel": "#003052", "hover": "#00253f",
        "text": "#c5d9f0", "strong": "#ffc600", "muted": "#ff9d00",
        "faint": "#4a6b8a", "userbar": "#0a3a5c", "userbg": "#063050",
        "sel-bg": "#ffc600", "sel-fg": "#002240",
    },
    "ember": {  # warm — orange + amber embers
        "bg": "#1a1210", "bar": "#150d0b", "panel": "#2a1c17", "hover": "#1f1512",
        "text": "#f0d0c0", "strong": "#ff6b35", "muted": "#f7c548",
        "faint": "#8a5a45", "userbar": "#4d2b1a", "userbg": "#2b1a12",
        "sel-bg": "#ff6b35", "sel-fg": "#1a1210",
    },
    "catppuccin-latte": {  # Catppuccin Latte — the light flavour
        "bg": "#eff1f5", "bar": "#e6e9ef", "panel": "#ccd0da", "hover": "#dce0e8",
        "text": "#4c4f69", "strong": "#8839ef", "muted": "#1e66f5",
        "faint": "#9ca0b0", "userbar": "#bcc0cc", "userbg": "#acb0be",
        "sel-bg": "#8839ef", "sel-fg": "#eff1f5",
    },
    "parchment": {  # warm cream, brown ink
        "bg": "#f5eeda", "bar": "#ebe2c8", "panel": "#e0d5b7", "hover": "#e8dfc4",
        "text": "#4a3f2f", "strong": "#8b4513", "muted": "#a0763c",
        "faint": "#b5a583", "userbar": "#d5c9a5", "userbg": "#cabb92",
        "sel-bg": "#8b4513", "sel-fg": "#f5eeda",
    },
    "rosewater": {  # soft pink light
        "bg": "#fdf2f4", "bar": "#f8e6ea", "panel": "#f0d5dc", "hover": "#f5dfe4",
        "text": "#5c3742", "strong": "#c94f7c", "muted": "#d98a9e",
        "faint": "#c9a3ad", "userbar": "#ecccd4", "userbg": "#e3bcc6",
        "sel-bg": "#c94f7c", "sel-fg": "#fdf2f4",
    },
    "meadow": {  # soft green light
        "bg": "#f0f5e8", "bar": "#e4ecd4", "panel": "#d5e0bf", "hover": "#dce6ca",
        "text": "#3a4a2c", "strong": "#4a7c2f", "muted": "#6b9a4a",
        "faint": "#a3b58a", "userbar": "#cdd9b8", "userbg": "#bfcfa5",
        "sel-bg": "#4a7c2f", "sel-fg": "#f0f5e8",
    },
}

LIGHT_THEMES = {
    "light", "solarized-light", "sepia",
    "catppuccin-latte", "parchment", "rosewater", "meadow",
}

THEME_ORDER = (
    "default", "dark", "matrix", "hacker-red", "phosphor", "tron", "frost", "synthwave",
    "flamingo", "forest", "ember", "vaporwave", "cobalt", "midnight",
    "catppuccin", "tokyo-night", "everforest", "kanagawa", "dracula", "nord",
    "gruvbox", "monokai", "solarized-dark",
    "light", "solarized-light", "sepia", "catppuccin-latte", "parchment",
    "rosewater", "meadow",
)
_ordered = [t for t in THEME_ORDER if t in PALETTE]
THEME_CHOICES = (*_ordered, *[t for t in PALETTE if t not in _ordered], "system")

# Diff colors (as requested).
DIFF_DEL_BG = "#3D0100"
DIFF_DEL_FG = "#DC5A5A"
DIFF_ADD_BG = "#022800"
DIFF_ADD_FG = "#50C850"

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

THINKING_VERBS = (
    "thinking", "pondering", "brewing", "mulling", "scheming", "plotting",
    "ruminating", "cogitating", "calculating", "daydreaming", "meditating",
    "chewing on it",
)
FOOTER_VERBS = (
    "took", "baked for", "brewed for", "cooked for", "simmered for",
    "stewed for", "toasted in", "whipped up in", "crafted in", "forged in",
    "distilled in", "conjured in",
)

def _cc_vars(mode: str) -> dict:
    """Theme variables the CSS reads as $cc-*, plus the selection highlight."""
    p = PALETTE[mode]
    v = {f"cc-{k}": val for k, val in p.items() if not k.startswith("sel-")}
    v["screen-selection-background"] = p["sel-bg"]
    v["screen-selection-foreground"] = p["sel-fg"]
    return v


def _build_theme(mode: str) -> AppTheme:
    p = PALETTE[mode]
    return AppTheme(
        name=f"cutecat-{mode}",
        primary=p["text"],
        secondary=p["muted"],
        accent=p["muted"],
        foreground=p["text"],
        background=p["bg"],
        surface=p["bar"],
        panel=p["panel"],
        success=p["muted"],
        warning=p["strong"],
        error=p["strong"],
        dark=(mode not in LIGHT_THEMES),
        variables=_cc_vars(mode),
    )


THEME_MODES = tuple(PALETTE.keys())
CUTECAT_THEMES = {mode: _build_theme(mode) for mode in THEME_MODES}
CSS_VAR_DEFAULTS = _cc_vars("dark")


THEME_POLL = 2.0
THEME_SLOW_POLL = 10.0
THEME_SIGNALS = ("color-scheme", "appearance", "gtk-theme", "themename")


def _mode_in(text: str) -> str | None:
    """'light'/'dark' as named in a settings value ('prefer-dark', ...)."""
    text = text.lower()
    if "light" in text:
        return "light"
    if "dark" in text:
        return "dark"
    return None


def _run(cmd: list[str]) -> str:
    import subprocess

    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, errors="replace", timeout=2
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout if out.returncode == 0 else ""


def _portal_theme() -> str | None:
    for method in ("ReadOne", "Read"):
        out = _run([
            "gdbus", "call", "--session",
            "--dest", "org.freedesktop.portal.Desktop",
            "--object-path", "/org/freedesktop/portal/desktop",
            "--method", f"org.freedesktop.portal.Settings.{method}",
            "org.freedesktop.appearance", "color-scheme",
        ])
        if "uint32" not in out:
            continue
        value = out.split("uint32", 1)[1].strip(" <>(),\n")
        if value.startswith("1"):
            return "dark"
        if value.startswith("2"):
            return "light"
    return None


def _gsettings_theme() -> str | None:
    schemas = (
        "org.gnome.desktop.interface",
        "org.cinnamon.desktop.interface",
        "org.mate.interface",
    )
    for schema in schemas:
        mode = _mode_in(_run(["gsettings", "get", schema, "color-scheme"]))
        if mode:
            return mode
    for schema in schemas:
        name = _run(["gsettings", "get", schema, "gtk-theme"]).strip().strip("'\"")
        if name:
            return "dark" if "dark" in name.lower() else "light"
    return None


def _kde_theme() -> str | None:
    name = _run(["kreadconfig6", "--group", "General", "--key", "ColorScheme"]) or _run(
        ["kreadconfig5", "--group", "General", "--key", "ColorScheme"]
    )
    if not name.strip():
        try:
            kdeglobals = Path.home() / ".config" / "kdeglobals"
            for line in kdeglobals.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines():
                if line.startswith("ColorScheme="):
                    name = line.split("=", 1)[1]
                    break
        except OSError:
            return None
    if not name.strip():
        return None
    return "dark" if "dark" in name.lower() else "light"


def _xfce_theme() -> str | None:
    """XFCE (and anything else driven by xsettings)."""
    name = _run(["xfconf-query", "-c", "xsettings", "-p", "/Net/ThemeName"]).strip()
    if not name:
        return None
    return "dark" if "dark" in name.lower() else "light"


def detect_desktop_theme() -> str | None:
    import sys

    try:
        if sys.platform == "darwin":
            # The key only exists in dark mode; absent means light.
            out = _run(["defaults", "read", "-g", "AppleInterfaceStyle"])
            return "dark" if "Dark" in out else "light"
        if os.name == "nt":  # pragma: no cover
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if val else "dark"
        # Unix desktops, most authoritative first.
        for probe in (_portal_theme, _gsettings_theme, _kde_theme, _xfce_theme):
            mode = probe()
            if mode:
                return mode
        return _mode_in(os.environ.get("GTK_THEME", ""))
    except Exception:
        return None


def _theme_monitor_cmd() -> list[str] | None:
    import shutil
    import sys

    if sys.platform == "darwin" or os.name == "nt":
        return None
    if shutil.which("gdbus"):
        return ["gdbus", "monitor", "--session",
                "--dest", "org.freedesktop.portal.Desktop"]
    if shutil.which("gsettings"):
        return ["gsettings", "monitor", "org.gnome.desktop.interface"]
    return None


def _start_theme_monitor():
    import subprocess

    cmd = _theme_monitor_cmd()
    if cmd is None:
        return None
    try:
        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            errors="replace",
        )
    except OSError:
        return None


def _read_monitor_line(stream, timeout: float) -> str | None:
    import select

    try:
        ready, _, _ = select.select([stream], [], [], timeout)
    except (OSError, ValueError):
        return None
    if not ready:
        return None
    return stream.readline() or None


def detect_system_theme() -> str:
    fgbg = os.environ.get("COLORFGBG", "")
    if ";" in fgbg:
        try:
            bg = int(fgbg.split(";")[-1])
            return "light" if bg >= 7 else "dark"
        except ValueError:
            pass
    return detect_desktop_theme() or "dark"


def _clean_title(raw: str) -> str:
    title = raw.strip().splitlines()[0] if raw.strip() else ""
    title = title.strip().strip("\"'`").strip()
    if title.endswith((".", ":", "!", "?")):
        title = title[:-1].strip()
    if len(title) > 60:
        title = title[:57].rstrip() + "…"
    return title


def _common_prefix(items: list[str]) -> str:
    if not items:
        return ""
    p = items[0]
    for s in items[1:]:
        while not s.startswith(p):
            p = p[:-1]
    return p


def write_crash_log(error: BaseException, session_id: str = "") -> Path | None:
    import platform
    import traceback

    try:
        config_mod.ensure_dirs()
        path = config_mod.CUTECAT_DIR / "crash.log"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(
                f"\n{'=' * 70}\n{config_mod.now_iso()}  cutecat {__version__}"
                f"  python {platform.python_version()}  {platform.platform()}\n"
            )
            if session_id:
                fh.write(f"session {session_id}  (cutecat --resume {session_id[:8]})\n")
            fh.write("".join(traceback.format_exception(error)))
        return path
    except Exception:
        return None  # even the crash reporter must not raise


def _unexpected(exc: BaseException) -> str:
    detail = str(exc).strip() or exc.__class__.__name__
    return f"something went wrong talking to the provider: {detail[:300]}"


def fmt_duration(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m {s:02d}s"


def progress_bar(frac: float, cells: int = 40) -> str:
    frac = max(0.0, min(1.0, frac))
    filled = round(frac * cells)
    return "▰" * filled + "▱" * (cells - filled) + f" {int(frac * 100)}%"


SYNTAX_THEME = "monokai"


def lexer_for_path(path: str) -> str:
    try:
        from pygments.lexers import get_lexer_for_filename

        return get_lexer_for_filename(path).aliases[0]
    except Exception:
        return "text"


def highlight_code(code: str, language: str):
    from rich.style import Style
    from rich.syntax import Syntax
    from rich.text import Span, Text
    from textual.content import Content

    def strip_bg(style):
        if isinstance(style, str):
            style = Style.parse(style)
        return Style(
            color=style.color, bold=style.bold, dim=style.dim,
            italic=style.italic, underline=style.underline, blink=style.blink,
            reverse=style.reverse, conceal=style.conceal, strike=style.strike,
            overline=style.overline,
        )

    syntax = Syntax(code, language or "text", theme=SYNTAX_THEME, background_color="default")
    rich_text = syntax.highlight(code)
    rich_text.rstrip()
    stripped = Text(rich_text.plain)
    stripped.spans = [Span(s.start, s.end, strip_bg(s.style)) for s in rich_text.spans]
    return Content.from_rich_text(stripped)


class _CodeGutter(Static):

    ALLOW_SELECT = False


class CuteFence(MarkdownFence):

    DEFAULT_CSS = """
    CuteFence {
        background: transparent;
        padding: 0;
        margin: 1 0 1 3;
        height: auto;
        layout: horizontal;
        overflow-x: auto;
        overflow-y: hidden;
        scrollbar-size-horizontal: 1;
    }
    CuteFence > _CodeGutter {
        width: auto;
        color: #5a5a5a;
        background: transparent;
        padding: 0 1 0 0;
    }
    CuteFence > .cf-code {
        width: auto;
        background: transparent;
    }
    """

    @classmethod
    def highlight(cls, code, language, ansi=False, dark=True):
        return highlight_code(code, language)

    def _gutter(self) -> str:
        n = self.code.rstrip("\n").count("\n") + 1
        w = len(str(n))
        return "\n".join(f"{i:>{w}}" for i in range(1, n + 1))

    def compose(self) -> ComposeResult:
        yield _CodeGutter(self._gutter())
        yield Static(self._highlighted_code, classes="cf-code")

    def notify_style_update(self) -> None:
        self._highlighted_code = self.highlight(self.code, self.lexer)
        try:
            self.query_one(".cf-code", Static).update(self._highlighted_code)
        except Exception:
            pass


class CuteMarkdown(Markdown):

    BLOCKS = {**Markdown.BLOCKS, "fence": CuteFence, "code_block": CuteFence}


class _JumpPill(Static):

    ALLOW_SELECT = False

    def __init__(self, text: str = "", *, action=None, **kwargs) -> None:
        super().__init__(text, **kwargs)
        self._action = action

    def on_click(self, event: events.Click) -> None:
        event.stop()
        if self._action is not None:
            self._action()


class _DiffGutter(Static):
    """Non-selectable line number + +/- marker for a diff row."""

    ALLOW_SELECT = False


class DiffBlock(Vertical):
    """A git-style diff preview: removed lines on dark red, added lines on
    dark green, full-width. Line numbers and markers live in a non-selectable
    gutter, so selecting the diff copies clean code."""

    DEFAULT_CSS = f"""
    DiffBlock {{ height: auto; margin: 1 0 1 3; background: transparent; }}
    DiffBlock > .diff-head {{ color: {GREY}; text-style: bold; padding: 0 1; }}
    DiffBlock .diff-row {{ height: auto; width: 1fr; layout: horizontal; }}
    DiffBlock .diff-del {{ background: {DIFF_DEL_BG}; }}
    DiffBlock .diff-add {{ background: {DIFF_ADD_BG}; }}
    DiffBlock .diff-del > _DiffGutter {{ color: {DIFF_DEL_FG}; }}
    DiffBlock .diff-add > _DiffGutter {{ color: {DIFF_ADD_FG}; }}
    DiffBlock .diff-ctx > _DiffGutter {{ color: {DIM}; }}
    DiffBlock _DiffGutter {{ width: auto; background: transparent; padding: 0 1 0 0; }}
    DiffBlock .diff-code {{ width: 1fr; background: transparent; }}
    """

    _MARK = {"ctx": " ", "del": "-", "add": "+"}

    def __init__(self, path: str, hunks: list, added: int, removed: int) -> None:
        super().__init__()
        self._path = path
        self._hunks = hunks
        self._added = added
        self._removed = removed
        self._lexer = lexer_for_path(path)

    def _code(self, text: str):
        if not text:
            return " "
        try:
            return highlight_code(text, self._lexer)
        except Exception:
            return text

    def compose(self) -> ComposeResult:
        head = Text()
        head.append(f"{self._path}  ", style=f"bold {self.app.c('strong')}")
        head.append(f"+{self._added}", style=DIFF_ADD_FG)
        head.append(" ", style=self.app.c("muted"))
        head.append(f"-{self._removed}", style=DIFF_DEL_FG)
        yield Static(head, classes="diff-head")

        width = 1
        for rows in self._hunks:
            for _kind, old_no, new_no, _text in rows:
                width = max(width, len(str(old_no or new_no or "")))

        for hi, rows in enumerate(self._hunks):
            if hi:
                with Horizontal(classes="diff-row diff-ctx"):
                    yield _DiffGutter(" " * (width + 1) + "⋯")
                    yield Static("", classes="diff-code")
            for kind, old_no, new_no, text in rows:
                num = old_no if kind == "del" else new_no
                gutter = f"{num:>{width}} {self._MARK[kind]}"
                with Horizontal(classes=f"diff-row diff-{kind}"):
                    yield _DiffGutter(gutter)
                    yield Static(self._code(text), classes="diff-code")


class PickerList(OptionList):
    def _move(self, direction: int) -> None:
        from textual import _widget_navigation

        nxt = _widget_navigation.find_next_enabled_no_wrap(
            self.options, anchor=self.highlighted, direction=direction
        )
        if nxt is not None:              # None == already at that edge; stay put
            self.highlighted = nxt

    def action_cursor_down(self) -> None:
        self._move(1)

    def action_cursor_up(self) -> None:
        self._move(-1)

    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        event.prevent_default()
        event.stop()
        self.action_cursor_down()

    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.prevent_default()
        event.stop()
        self.action_cursor_up()


class PromptArea(TextArea):

    MAX_LINES = 8

    class Submitted(Message):
        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    def __init__(self, **kwargs) -> None:
        super().__init__(soft_wrap=True, **kwargs)
        self.show_line_numbers = False
        self.highlight_cursor_line = False
        self.input_history: list[str] = []
        self._pos: int | None = None
        self._draft = ""
        self._pastes: list[tuple[str, str]] = []

    def _complete_command(self) -> bool:
        text = self.text
        if not text.startswith("/") or " " in text or "\n" in text:
            return False
        matches = [name for name in COMMAND_NAMES if name.startswith(text.lower())]
        if not matches:
            return False
        if len(matches) == 1:
            self.set_text(matches[0] + " ")
        else:
            common = _common_prefix(matches)
            if len(common) > len(text):
                self.set_text(common)
        return True

    def autosize(self) -> None:
        height = max(1, min(self.MAX_LINES, self.wrapped_document.height))
        self.styles.height = height

    def set_text(self, text: str) -> None:
        self.load_text(text)
        self.move_cursor(self.document.end)
        self.autosize()

    def remember(self, line: str) -> None:
        if line and (not self.input_history or self.input_history[-1] != line):
            self.input_history.append(line)
        self._pos = None

    def resolve_pastes(self, text: str) -> str:
        for placeholder, content in self._pastes:
            if placeholder in text:
                text = text.replace(placeholder, content, 1)
        self._pastes.clear()
        return text

    def _history_older(self) -> None:
        if not self.input_history:
            return
        if self._pos is None:
            self._draft = self.text
            self._pos = len(self.input_history) - 1
        elif self._pos > 0:
            self._pos -= 1
        self.set_text(self.input_history[self._pos])

    def _history_newer(self) -> None:
        if self._pos is None:
            return
        self._pos += 1
        if self._pos >= len(self.input_history):
            self._pos = None
            self.set_text(self._draft)
        else:
            self.set_text(self.input_history[self._pos])

    def _cursor_visual_row(self) -> int:
        return self.wrapped_document.location_to_offset(self.cursor_location).y

    async def _on_key(self, event: events.Key) -> None:
        if getattr(self.app, "key_debug", False) and event.key != "escape":
            event.stop()
            event.prevent_default()
            self.app.report_key(event)
            return
        # While a permission popup is up it owns the keyboard and all other
        # typing is swallowed (esc bubbles to the global cancel binding).
        if getattr(self.app, "mode", None) == CHOICE:
            if event.key == "escape":
                return
            event.stop()
            event.prevent_default()
            self.app._choice_key(event.key)
            return
        # Tab completes a slash command (e.g. "/mod" -> "/model ").
        if event.key == "tab" and self._complete_command():
            event.stop()
            event.prevent_default()
            return
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            # A line ending in a backslash starts a new line; otherwise send.
            row = self.cursor_location[0]
            line = str(self.document.get_line(row))
            if line.endswith("\\") and self.cursor_at_end_of_line:
                self.action_delete_left()
                self.insert("\n")
                self.autosize()
                return
            self.post_message(self.Submitted(self.text))
            return
        # history only at the visual top/bottom, so wrapped text scrolls first
        if event.key == "up" and self._cursor_visual_row() == 0:
            event.stop()
            event.prevent_default()
            self._history_older()
            return
        if (
            event.key == "down"
            and self._cursor_visual_row() >= self.wrapped_document.height - 1
        ):
            event.stop()
            event.prevent_default()
            self._history_newer()
            return
        await super()._on_key(event)

    async def _on_paste(self, event: events.Paste) -> None:
        # insert ourselves + prevent_default, or TextArea._on_paste also fires
        # and pastes twice
        event.stop()
        event.prevent_default()
        text = event.text
        if not text:
            return
        lines = text.splitlines() or [""]
        if len(lines) > 2 or len(text) > 400:
            # Collapse a big paste to a placeholder; the full text is restored
            # by resolve_pastes() when the message is sent.
            placeholder = f"[pasted {len(lines)} lines]"
            self._pastes.append((placeholder, text))
            self.insert(placeholder)
        else:
            self.insert(text)
        self.autosize()

    def on_resize(self, event: events.Resize) -> None:
        self.autosize()


NORMAL = "normal"
PICK_PROVIDER = "pick-provider"  # (legacy; connect/model/sessions use PICK now)
ENTER_KEY = "enter-key"
ENTER_URL = "enter-url"  # typing a base URL for the Custom API provider
PICK_MODEL = "pick-model"
PICK = "pick"  # scrollable OptionList picker (model, sessions, theme, provider)
CHOICE = "choice"  # blocking y/n or wait/kill prompt driven by the agent worker

# Streaming phases.
THINKING = "thinking"
RESPONDING = "responding"




TIPS = (
    "end a line with \\ and press enter to write a second line",
    "press esc to stop a running command · ctrl+b to send it to the background",
    "/compact summarises the chat so far, so reopening it costs far fewer tokens",
    "drag with the mouse to select any text, then ctrl+shift+c to copy it",
    "/agents plan writes a detailed PLAN.md; switch back to build and it executes it",
    "/editor <binary> picks your editor · /editor alone composes in it",
    "answer a edit a prompt with 'a' to allow every edit for the rest of the session",
    "click a command's collapsed line to see its output, click again to hide it",
    "resume any past chat with cutecat --resume <id>, or /sessions from inside",
    "ask for a screenshot of a page — a real headless browser renders it",
    "/theme system follows your OS, switching live when you flip dark/light",
    "cutecat --encrypt puts your chats and api keys behind a passphrase",
    "keys are remembered per provider — /connect new replaces one",
    "scroll up and a pill appears: click it to jump back to the bottom",
    "/model switches model without losing the conversation",
)


class Cat:
    """The welcome cat's face.

    It blinks now and then, glances about while the agent is working, and looks
    pleased with itself for a moment when an answer lands. All of the state is
    here (not in the app) so it can be driven by a clock in a test.
    """

    IDLE = ("o.o", "^")        # (eyes, mouth)
    BLINK = "-.-"
    HAPPY = ("^.^", "w")
    THINKING = ("o.o", "O.o", "o.O", "-.o")   # eyes darting about
    BLINK_FOR = 0.16           # a blink is quick
    BLINK_EVERY = (3.0, 8.0)   # ...and irregular, or it looks like a metronome
    HAPPY_FOR = 3.0

    def __init__(self):
        self.blink_until = 0.0
        self.next_blink = random.uniform(*self.BLINK_EVERY)
        self.happy_until = 0.0

    def pleased(self, now: float) -> None:
        """Called when the agent finishes an answer."""
        self.happy_until = now + self.HAPPY_FOR

    def frame(self, now: float, busy: bool) -> tuple[str, str]:
        """(eyes, mouth) for this instant."""
        if now < self.blink_until:
            return (self.BLINK, self.HAPPY[1] if now < self.happy_until else self.IDLE[1])
        if now >= self.next_blink:
            self.blink_until = now + self.BLINK_FOR
            self.next_blink = now + random.uniform(*self.BLINK_EVERY)
            return (self.BLINK, self.IDLE[1])
        if busy:
            # a slow, deliberate look around — one change every half second
            return (self.THINKING[int(now * 2) % len(self.THINKING)], "·")
        if now < self.happy_until:
            return self.HAPPY
        return self.IDLE


def _welcome(app, cwd: str, resumed: bool = False) -> Text:
    #    /\_/\    cutecat v{version}
    #   ( o.o )   Directory: /some/path            (dimmer)   <- eyes blink
    #    > ^ <    [resumed · ] tip: <one of TIPS>   (dim)      <- mouth
    strong, muted, faint = app.c("strong"), app.c("muted"), app.c("faint")
    eyes, mouth = app.cat_face
    home = os.path.expanduser("~")
    if home and (cwd == home or cwd.startswith(home + os.sep)):
        cwd = "~" + cwd[len(home):]
    t = Text()
    t.append("   /\\_/\\".ljust(12), style=strong)
    t.append(f"cutecat v{__version__}\n", style=f"bold {strong}")
    t.append(f"  ( {eyes} )".ljust(12), style=strong)
    t.append(f"Directory: {cwd}\n", style=muted)
    t.append(f"   > {mouth} <".ljust(12), style=strong)
    if resumed:
        t.append("resumed · ", style=faint)
    t.append("tip: ", style=muted)
    t.append(app.tip, style=faint)
    return t


PLAN_FILE = "PLAN.md"

SHELL_DIRECTIVES = {
    "posix": (
        "# your shell\n\n"
        "`run_command` runs in a POSIX shell (bash/sh) on a Unix-like system."
        " Use POSIX syntax and Unix tools."
    ),
    "powershell": (
        "# your shell\n\n"
        "You are on Windows. `run_command` runs in **PowerShell** — use"
        " PowerShell syntax (`Get-ChildItem`, `Get-Content`, `Select-String`,"
        " `$env:VAR`, `Remove-Item`), NOT bash. Unix tools like `ls`, `cat`,"
        " `grep`, `rm` are not available (some exist as aliases, but do not"
        " rely on them). Paths use backslashes."
    ),
    "cmd": (
        "# your shell\n\n"
        "You are on Windows. `run_command` runs in **cmd.exe** — use cmd"
        " syntax (`dir`, `type`, `copy`, `del`, `findstr`, `%VAR%`), NOT bash"
        " and NOT PowerShell cmdlets. Paths use backslashes."
    ),
}

DELEGATE_DIRECTIVE = (
    "# delegating\n\n"
    "`set_tasks` and `run_agent` are yours to manage the work itself.\n\n"
    "- Post a `set_tasks` list once the job needs three or more steps, and "
    "restack it as you finish each one. One step is 'running' at a time.\n"
    "- Send a self-contained chunk to `run_agent` when finding the answer would "
    "cost many tool calls whose output you don't need to keep — searching a "
    "large tree, reading a pile of files to answer one question. It reports "
    "back a summary, and the digging never enters this conversation.\n"
    "- Do it yourself when it is one command, one file, or when you need the "
    "raw output in front of you."
)

SUBAGENT_STEPS = 15

_SUBAGENT_BASE = (
    "You are a subagent working for another AI agent, not for a human. You "
    "cannot see its conversation and cannot ask it anything — work only from "
    "the task you were given.\n\n"
    "Your reply is the ONLY thing that reaches it, so answer with the findings "
    "themselves: the file paths, line numbers, names, and facts it asked for. "
    "No preamble, no offers to help further, no description of how you looked. "
    "Be complete but tight — every token you write is a token it must read.\n\n"
    "Work under `{root}`."
)

SUBAGENT_PROMPTS = {
    "explore": _SUBAGENT_BASE + (
        "\n\nInvestigate only. Do not create, edit, or delete anything, and do "
        "not run commands that change the system."
    ),
    "build": _SUBAGENT_BASE + (
        "\n\nYou may edit and create files to complete the task. Report what you "
        "changed, by path."
    ),
}

SANDBOX_DIRECTIVE = (
    "# your workspace\n\n"
    "You may create and change files only under `{root}`. Everything you build"
    " for the user goes there; relative paths resolve there. Reading outside is"
    " fine, but a write outside is refused — do not retry it, do not try to work"
    " around it, and never `cd` out of the workspace. If a task genuinely needs"
    " to write elsewhere, say so and let the user decide.\n\n"
    "Inside the workspace you do not need permission for ordinary work: creating"
    " files, editing, building, running tests and scripts all go ahead"
    " immediately. Just do them."
)

BUILD_DIRECTIVE = (
    "# agent mode: build\n\n"
    "You are in BUILD mode — carry out the user's request directly using your"
    f" tools. If a file named `{PLAN_FILE}` exists in the working directory,"
    " read it first and execute it step by step, checking off each step as you"
    " finish it."
)

PLAN_DIRECTIVE = (
    "# agent mode: plan\n\n"
    "You are in PLAN mode. Do NOT make any changes, run mutating commands, or"
    " implement anything. Instead, investigate as needed (read-only) and write"
    f" a single detailed implementation plan to `{PLAN_FILE}` in the working"
    " directory using create_file. The plan must be thorough enough that"
    " another agent can execute it without further questions: goal, affected"
    " files, step-by-step changes, commands to run, and how to verify. When the"
    f" user later switches to build mode, that agent will read `{PLAN_FILE}` and"
    " execute it. After writing the plan, briefly summarise it and stop."
)

COMPACT_PROMPT = (
    "You are compacting a conversation between a user and an AI coding agent so"
    " it can continue seamlessly with far less context. This must be done with"
    " PRECISION: the summary replaces the entire history, so anything you leave"
    " out is lost for good. Err on the side of keeping detail — it is far worse"
    " to drop a load-bearing fact than to be a little long.\n\n"
    "Preserve, exactly and specifically:\n"
    "- The user's goals, intent, and any constraints or preferences they stated"
    " (quote them verbatim when the wording matters).\n"
    "- Every decision made and the reasoning behind it, so it is not relitigated.\n"
    "- Concrete facts discovered: exact file paths, function/class/variable"
    " names, config keys, versions, URLs, IDs — copy them literally, never"
    " paraphrase an identifier.\n"
    "- Commands run and their outcomes, edits applied (which files, what"
    " changed), and errors hit with their fixes.\n"
    "- The current state of the work and any open TODOs or next steps.\n\n"
    "Use short markdown sections and bullet points. Be concise in prose but"
    " never at the cost of a specific detail. No pleasantries or preamble —"
    " output only the summary."
)

COMPACT_PREFIX = "[Compacted summary of the earlier conversation — continue from here.]\n\n"


def _transcript(messages: list[dict]) -> str:
    """Flatten the stored history into a plain transcript for summarising."""
    out: list[str] = []
    for m in messages:
        role = m.get("role")
        if role == "user":
            out.append(f"User: {m.get('content', '')}")
        elif role == "assistant":
            content = m.get("content") or ""
            if content:
                out.append(f"Assistant: {content}")
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function", {})
                out.append(f"Assistant → tool {fn.get('name')}({fn.get('arguments')})")
        elif role == "tool":
            result = str(m.get("content", ""))
            if len(result) > 2000:
                result = result[:2000] + " …(truncated)"
            out.append(f"Tool {m.get('tool_name', '')} → {result}")
    return "\n".join(out)


COMMANDS = (
    ("/connect", "connect to an API (keys are remembered · /connect new to replace)"),
    ("/model", "switch the active model"),
    ("/skills", "turn skills on/off (type to search, enter toggles)"),
    ("/editor", "compose your message in an external editor"),
    ("/theme", "default, dark, light, system, or a named theme"),
    ("/config", "edit your settings (config.json) in an editor"),
    ("/new", "start a fresh session"),
    ("/sessions", "open one of your previous sessions"),
    ("/schedule", "save this as a routine that runs on a schedule"),
    ("/routines", "list your routines — run, pause, or delete one"),
    ("/agents", "switch agent: build (execute) or plan (write PLAN.md)"),
    ("/compact", "summarise the history so far to save tokens"),
    ("/clear", "clear the current conversation"),
    ("/help", "list the commands"),
    ("/exit", "quit (also /quit or ctrl+d)"),
)
COMMAND_NAMES = [c[0] for c in COMMANDS]

COMMAND_HELP = {
    "/connect": (
        "/connect  ·  /connect new\n\n"
        "Connect to an API. Pick a provider, paste your key (hidden), pick a "
        "model. Your key is remembered per provider, so next time /connect goes "
        "straight to the model list.\n\n"
        "/connect new — enter a different key for a provider (e.g. after you "
        "rotated it, or pasted the wrong one)."
    ),
    "/model": (
        "/model\n\n"
        "Switch the active model without losing the conversation. The list is "
        "fetched live from the provider you're connected to."
    ),
    "/skills": (
        "/skills\n\n"
        "Turn skills on or off — a scrollable checklist. Type to search, enter "
        "toggles the highlighted skill, esc closes. Enabled skills are appended "
        "to the system prompt. Add your own with 'cutecat skill' on the command "
        "line, or drop .md files into ~/.cutecat/skills/."
    ),
    "/editor": (
        "/editor  ·  /editor <binary>\n\n"
        "Compose your next message in a real editor. /editor alone opens it; "
        "/editor <binary> sets which (e.g. /editor nano, /editor \"code -w\"). "
        "With nothing set it uses $VISUAL/$EDITOR, then nvim/vim/vi."
    ),
    "/theme": (
        "/theme  ·  /theme default|dark|light|system|<name>\n\n"
        "Change the colour theme. 'default' uses your terminal's own background "
        "and text colour (nothing of ours). 'system' follows your OS and "
        "switches live when you flip your desktop between dark and light."
    ),
    "/config": (
        "/config\n\n"
        "Open your settings (config.json) in your editor. When the store is "
        "encrypted you still edit plain JSON — it's decrypted for editing and "
        "re-encrypted when you save. Invalid JSON is refused, not saved. Uses "
        "the same editor as /editor ($VISUAL/$EDITOR, or set one with /editor)."
    ),
    "/new": "/new\n\nStart a fresh session. The current one is saved first.",
    "/sessions": (
        "/sessions\n\n"
        "Open one of your previous sessions — a searchable list, newest first. "
        "From the terminal you can also resume by id: cutecat --resume <id>, or "
        "cutecat --continue for the most recent."
    ),
    "/schedule": (
        "/schedule <what to do, and when>\n\n"
        "Turn a plain-English request into a routine that runs unattended.\n"
        "  /schedule every weekday at 9am, summarise yesterday's commits\n"
        "  /schedule tomorrow at 6pm, remind me to cut the release  (a one-off)\n\n"
        "cutecat drafts it and asks what it may do (safe = read-only, or allow "
        "writes). Routines only fire while a scheduler runs — 'cutecat routines "
        "serve', or 'cutecat routines install'."
    ),
    "/routines": (
        "/routines\n\n"
        "List your routines. Pick one to run it now, pause it, or delete it. "
        "Manage them from the terminal too with 'cutecat routines'."
    ),
    "/agents": (
        "/agents\n\n"
        "Switch agent. build (the default) carries out your requests directly. "
        "plan changes nothing — it investigates and writes a detailed PLAN.md, "
        "which build then reads and executes when you switch back."
    ),
    "/compact": (
        "/compact\n\n"
        "Summarise the conversation so far and replace the history with just "
        "that summary, so reopening the session or switching models doesn't "
        "re-read everything. Reduces the tokens sent to the model."
    ),
    "/clear": "/clear\n\nClear the current conversation (history and screen). The session id stays.",
    "/help": (
        "/help  ·  /help <command>\n\n"
        "/help lists every command. /help <command> shows detailed help for "
        "one (e.g. /help /connect, or /help connect)."
    ),
    "/exit": "/exit  ·  /quit  ·  ctrl+d\n\nQuit cutecat, back to your terminal.",
}


class CuteCatApp(App):
    AUTO_FOCUS = "#input"

    CSS = f"""
    Screen {{
        background: $cc-bg;
        color: $cc-text;
    }}
    #topbar {{
        dock: top;
        height: 1;
        background: $cc-bar;
        padding: 0 1;
    }}
    #app-name {{
        width: auto;
        color: $cc-strong;
        text-style: bold;
        background: $cc-bar;
    }}
    #status {{
        width: 1fr;
        text-align: right;
        color: $cc-muted;
        background: $cc-bar;
    }}
    #chat-area {{
        height: 1fr;
        layers: base overlay;
        background: $cc-bg;
    }}
    /* No scrollbar: the chat still scrolls (wheel, pgup/pgdn, ctrl+End) and
       the jump pills show you when you are away from the bottom. */
    #chat {{
        layer: base;
        height: 1fr;
        padding: 1 1 0 1;
        background: $cc-bg;
        scrollbar-size-vertical: 0;
    }}
    .overlay-bar {{
        layer: overlay;
        width: 1fr;
        height: auto;
        align-horizontal: center;
        background: transparent;
        display: none;
    }}
    #overlay-top {{ dock: top; }}
    #overlay-bottom {{ dock: bottom; }}
    #jump-prev, #jump-bottom {{
        width: auto;
        height: 1;
        padding: 0 1;
        background: $cc-userbar;
        color: $cc-strong;
    }}
    .msg {{
        width: 100%;
        margin-bottom: 1;
        padding: 0 1;
    }}
    .user {{
        background: $cc-userbg;
        color: $cc-strong;
    }}
    .system {{
        color: $cc-muted;
    }}
    .welcome {{
        /* keep the cat's rows on their own lines: a long path is cropped
           with an … at the edge, never wrapped onto the next row */
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }}
    .tool {{
        color: $cc-faint;
        margin: 0 0 1 2;
    }}
    Collapsible.cmd {{
        margin: 0 0 1 2;
        padding: 0;
        border: none;
        background: $cc-bg;
    }}
    Collapsible.cmd CollapsibleTitle {{
        color: $cc-muted;
        background: $cc-bg;
        padding: 0 1;
    }}
    Collapsible.cmd CollapsibleTitle:hover {{
        color: $cc-strong;
        background: $cc-hover;
    }}
    Collapsible.cmd Contents {{
        padding: 0 1 0 3;
        background: $cc-bg;
    }}
    Markdown.assistant {{
        margin: 0 0 1 0;
        padding: 0 1;
        background: $cc-bg;
    }}
    Markdown.assistant .code_inline {{
        background: transparent;
        color: $cc-strong;
        text-style: bold;
    }}
    .error {{
        background: $cc-panel;
        color: $cc-strong;
    }}
    #bottom {{
        dock: bottom;
        height: auto;
        background: $cc-bg;
    }}
    #indicator {{
        height: 1;
        padding: 0 1;
        color: $cc-muted;
        background: $cc-bg;
        display: none;
    }}
    #taskpanel {{
        display: none;
        height: auto;
        padding: 0 1;
        color: $cc-muted;
        background: $cc-bg;
    }}
    #popup {{
        display: none;
        height: auto;
        margin: 0 1 1 1;
        padding: 0 1;
        background: $cc-panel;
        border: round $cc-muted;
    }}
    #popup-q {{
        height: auto;
        color: $cc-strong;
        background: $cc-panel;
    }}
    #popup-opts {{
        height: auto;
        margin-top: 1;
        color: $cc-muted;
        background: $cc-panel;
    }}
    #cmdpreview {{
        display: none;
        height: auto;
        padding: 0 1;
        margin: 0 1;
        background: $cc-panel;
        color: $cc-text;
    }}
    /* The box must be able to hold everything inside it: border (2) + title (1)
       + search (1) + the list. If it can't, the container silently clips the
       bottom rows of the list — and the selection can sit in one of them. The
       list's own height is clamped at runtime to what the screen has room for
       (see _fit_picker). */
    #picker {{
        display: none;
        height: auto;
        max-height: 16;
        margin: 0 1 1 1;
        background: $cc-panel;
        border: round $cc-muted;
    }}
    #picker-title {{
        height: 1;
        padding: 0 1;
        color: $cc-muted;
        background: $cc-panel;
    }}
    #picker-list {{
        height: auto;
        max-height: 12;
        background: $cc-panel;
        border: none;
        padding: 0;
        scrollbar-size-vertical: 1;
    }}
    #picker-search {{
        height: 1;
        padding: 0 1;
        color: $cc-strong;
        background: $cc-panel;
    }}
    #picker-list > .option-list--option {{
        padding: 0 1;
        color: $cc-text;
    }}
    /* Inverse, so the selected row is unmistakable wherever it is in the list. */
    #picker-list > .option-list--option-highlighted {{
        background: $cc-strong;
        color: $cc-bg;
        text-style: bold;
    }}
    /* The input section carries no background of its own, in either theme:
       it sits straight on the page. */
    .input-rule {{
        height: 1;
        margin: 0;
        color: $cc-faint;
        background: transparent;
    }}
    #inputbar {{
        height: auto;
        background: transparent;
        padding: 0 1;
    }}
    #prompt {{
        width: 2;
        height: 1;
        color: $cc-strong;
        text-style: bold;
        background: transparent;
    }}
    #input {{
        border: none;
        height: 1;
        padding: 0;
        background: transparent;
        color: $cc-strong;
        scrollbar-size-vertical: 0;
    }}
    #input .text-area--cursor-line {{
        background: transparent;
    }}
    #keyinput {{
        display: none;
        border: none;
        height: 1;
        padding: 0;
        width: 1fr;
        background: transparent;
        color: $cc-strong;
    }}
    """

    BINDINGS = [
        Binding("ctrl+c", "copy", show=False, priority=True),
        Binding("ctrl+shift+c", "copy", show=False, priority=True),
        Binding("ctrl+d", "quit", show=False, priority=True),
        Binding("escape", "cancel", show=False),
        Binding("ctrl+end", "jump_bottom", show=False, priority=True),
        Binding("ctrl+b", "background_command", show=False, priority=True),
        Binding("pageup", "chat_up", show=False),
        Binding("pagedown", "chat_down", show=False),
    ]

    def __init__(self, session: dict | None = None) -> None:
        super().__init__()
        self.cfg = config_mod.load_config()
        self.cwd = os.getcwd()
        self._sandbox = sandbox_mod.from_config(self.cfg, self.cwd)
        self._resumed = session is not None
        session = session or {}
        self.session_id: str = session.get("id") or config_mod.new_session_id()
        self._session_created: str = session.get("created") or config_mod.now_iso()
        self.messages: list[dict] = list(session.get("messages") or [])
        self._session_history: list[str] = list(session.get("input_history") or [])
        self._chat_title: str = session.get("title") or ""
        self._title_started = bool(self._chat_title)
        self._agent_mode = self.cfg.get("agent_mode") or "build"
        self.tip = random.choice(TIPS)  # a fresh one each session
        self.cat = Cat()
        self.cat_face = Cat.IDLE
        self._storage_warned = False   # only nag once if the disk is unwritable
        self.crash: tuple | None = None  # set if we had to close on an error
        self.resume_id: str | None = None  # set on exit if the chat is worth resuming
        self._tools_disabled = False  # set when a provider rejects tool calls
        self._tok_in = int(session.get("tokens_in") or 0)   # tokens used this session
        self._tok_out = int(session.get("tokens_out") or 0)
        self._tok_cached = int(session.get("tokens_cached") or 0)
        self._system = self._build_system_prompt()
        self.mode = NORMAL
        self._busy = False
        self._op = 0  # bumped on cancel; stale worker callbacks are dropped
        self._pending_provider: Provider | None = None
        self._pending_key: str | None = None
        self._pending_custom_wire = "openai"  # /connect Custom API: chosen wire
        self._theme_gen = 0              # bumped to retire the theme watcher
        self._theme_proc = None          # the `gsettings monitor` subprocess
        self._pending_key_saved = False  # is the key being checked one we stored?
        self._pending_routine: dict | None = None  # /schedule + /routines in flight
        self._force_new_key = False      # /connect new: ask even if a key is saved
        self._stream_target: Markdown | None = None
        self._stream_text = ""
        self._pending_md: str | None = None
        self._inflight = False
        self._phase = THINKING
        self._verb = THINKING_VERBS[0]
        self._net_label: str | None = None
        self._t_start = 0.0
        self._t_content: float | None = None
        self._timer = None
        self._progress = False           # status line shows a progress bar (/compact)
        self._progress_frac: float | None = None  # set to snap the bar to a value
        self.key_debug = False
        self._dark = True
        self._mode = "dark"
        self._shell = None
        self._tmp_granted = False
        self._allow_all_edits = False
        self._allowed_kinds: set[str] = set()
        self._tasks: list[dict] = []
        self._tasks_started = 0.0
        self._subagents: dict[int, dict] = {}
        self._next_agent_id = 1
        self._agent_cancel = lambda: False
        self._stick_bottom = True
        self._user_msgs: list[tuple[Static, str]] = []
        self._running_job = None        # command currently in the foreground
        self._cmd_control = None         # "terminate" | "background" from keys
        self._cmd_widget: Collapsible | None = None
        self._cmd_body: Static | None = None
        self._bg_jobs: list = []         # backgrounded jobs still running
        self._agent_cancel = lambda: False
        self._choice_event: threading.Event | None = None
        self._choice_result = ""
        self._choice_options: list | None = None
        self._choice_default = ""
        self._choice_index = 0
        self._picker_values: list = []      # the values currently shown
        self._picker_all: list = []          # every option, before the search
        self._picker_filter = ""             # what you have typed to search
        self._picker_title = ""
        self._picker_on_select = None
        self._picker_on_toggle = None        # set for checklist pickers (/skills)
        self._picker_on_close = None
        self._picker_on_preview = None       # live preview (/theme)
        self._picker_on_cancel = None
        self._picker_committed = False

    #layout

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Static("0 tokens", id="app-name")
            yield Static("", id="status")
        with Container(id="chat-area"):
            yield VerticalScroll(id="chat")
            with Container(id="overlay-top", classes="overlay-bar"):
                yield _JumpPill(id="jump-prev", action=self.action_jump_prev)
            with Container(id="overlay-bottom", classes="overlay-bar"):
                yield _JumpPill(
                    "Jump to the bottom (ctrl+End) ↓",
                    id="jump-bottom",
                    action=self.action_jump_bottom,
                )
        with Vertical(id="bottom"):
            yield Static("", id="taskpanel")
            yield Static("", id="indicator")
            with Vertical(id="popup"):
                yield Static("", id="popup-q")
                yield Static("", id="popup-opts")
            with Vertical(id="picker"):
                yield Static("", id="picker-title")
                yield Static("", id="picker-search")
                yield PickerList(id="picker-list")
            yield Static("", id="cmdpreview")
            yield Rule(line_style="solid", classes="input-rule")
            with Horizontal(id="inputbar"):
                yield Static("❯", id="prompt")
                yield PromptArea(id="input")
                yield Input(id="keyinput", password=True)
            yield Rule(line_style="solid", classes="input-rule")

    def get_theme_variable_defaults(self) -> dict:
        # Lets the CSS reference $cc-* variables before a theme is registered.
        return dict(CSS_VAR_DEFAULTS)

    def c(self, name: str) -> str:
        val = PALETTE.get(self._mode, PALETTE["dark"])[name]
        # 'default' theme uses ANSI names ("ansi_..."); Rich wants them unprefixed
        if val.startswith("ansi_"):
            return val[len("ansi_"):]
        return val

    def _apply_theme(self, choice: str) -> None:
        self._set_mode(detect_system_theme() if choice == "system" else choice)

    def _set_mode(self, mode: str) -> None:
        if mode not in PALETTE:
            mode = "dark"
        self._mode = mode
        self._dark = mode not in LIGHT_THEMES
        self.theme = f"cutecat-{mode}"

    #live system theme

    def _start_theme_watch(self) -> None:
        self._theme_gen += 1
        self._stop_theme_watch()
        if (self.cfg.get("theme") or "dark") == "system":
            self._theme_watcher(self._theme_gen)

    def _stop_theme_watch(self) -> None:
        proc, self._theme_proc = self._theme_proc, None
        if proc is not None:
            try:
                proc.terminate()  # unblocks the worker's read on the monitor
            except Exception:
                pass

    @work(thread=True, group="theme")
    def _theme_watcher(self, gen: int) -> None:
        import time

        current = detect_desktop_theme() or detect_system_theme()
        monitor = _start_theme_monitor()
        self._theme_proc = monitor
        stream = monitor.stdout if monitor is not None else None
        interval = THEME_SLOW_POLL if stream is not None else THEME_POLL
        try:
            waited = 0.0
            while gen == self._theme_gen:
                woken = False
                if stream is not None:
                    # Wait on the pipe in short slices rather than blocking, so
                    # a retired watcher always notices and never holds up quit.
                    line = _read_monitor_line(stream, 0.25)
                    if line is None and monitor.poll() is not None:
                        stream = None  # monitor died: carry on polling
                        interval = THEME_POLL
                    elif line and any(s in line.lower() for s in THEME_SIGNALS):
                        woken = True
                    waited += 0.25
                else:
                    time.sleep(0.25)
                    waited += 0.25
                if not woken and waited < interval:
                    continue
                waited = 0.0
                if gen != self._theme_gen:
                    return
                mode = detect_desktop_theme()
                if mode and mode != current:
                    current = mode
                    self.call_from_thread(self._system_theme_changed, mode, gen)
        finally:
            if monitor is not None:
                for stop in (monitor.terminate, monitor.kill):
                    try:
                        stop()
                    except Exception:
                        pass

    def _system_theme_changed(self, mode: str, gen: int) -> None:
        if gen != self._theme_gen or (self.cfg.get("theme") or "dark") != "system":
            return
        if (mode == "dark") == self._dark:
            return  # already showing it
        self._set_mode(mode)
        self._refresh_welcome()  # switches silently: no note in the chat

    def _handle_exception(self, error: Exception) -> None:
        self._return_code = 1
        # Still record it, so the test pilot can re-raise and a bug can't hide.
        if self._exception is None:
            self._exception = error
            self._exception_event.set()
        try:
            self.crash = (write_crash_log(error, self.session_id), self.session_id)
        except Exception:
            self.crash = (None, self.session_id)
        self._exit_renderables.clear()   # nothing rich, no traceback, no locals
        self._close_messages_no_wait()

    def _refresh_welcome(self) -> None:
        try:
            widget = next(iter(self.chat.query(".welcome")))
            widget.update(_welcome(self, self.cwd, resumed=self._resumed))
        except StopIteration:
            pass

    CAT_TICK = 0.2

    def _tick_cat(self) -> None:
        try:
            face = self.cat.frame(monotonic(), self._busy)
            if face != self.cat_face:
                self.cat_face = face
                self._refresh_welcome()
        except Exception:
            pass

    def on_mount(self) -> None:
        for theme in CUTECAT_THEMES.values():
            self.register_theme(theme)
        self._dark = True
        self._mode = "dark"
        self._apply_theme(self.cfg.get("theme") or "dark")
        self._start_theme_watch()
        self.set_interval(self.CAT_TICK, self._tick_cat)  # blink, glance, purr
        self._refresh_status()
        self._refresh_tokens()  # a resumed session carries its token count in
        self.add_msg(_welcome(self, self.cwd, resumed=self._resumed), "system", "welcome")
        self.input.input_history = self._session_history
        for message in self.messages:
            if message["role"] == "user":
                self._echo_user(message["content"])
            elif message["role"] == "assistant" and message.get("content", "").strip():
                self._make_assistant_widget(message["content"])
            # tool messages and tool-call-only assistant turns aren't replayed
        short = self.session_id[:8]
        self.set_terminal_title(
            f"{self._chat_title} - {short}" if self._chat_title else f"cutecat - {short}"
        )
        self.watch(self.chat, "scroll_y", lambda: self._update_jump_pills())
        self.call_after_refresh(self._update_jump_pills)

    def set_terminal_title(self, title: str) -> None:
        clean = title.replace("\x07", " ").replace("\x1b", " ").strip()
        driver = getattr(self, "_driver", None)
        if driver is None:
            return
        try:
            driver.write("\x1b]7;\x1b\\")          # clear the reported cwd
            driver.write(f"\x1b]0;{clean}\x07")     # icon + window title
            driver.write(f"\x1b]2;{clean}\x07")     # window title (belt & braces)
            driver.flush()
        except Exception:
            pass

    @property
    def chat(self) -> VerticalScroll:
        return self.query_one("#chat", VerticalScroll)

    @property
    def input(self) -> PromptArea:
        return self.query_one("#input", PromptArea)

    @property
    def key_input(self) -> Input:
        return self.query_one("#keyinput", Input)

    @property
    def indicator(self) -> Static:
        return self.query_one("#indicator", Static)

    def add_msg(self, renderable, *classes: str) -> Static:
        widget = Static(renderable, classes=" ".join(("msg",) + classes))
        self.chat.mount(widget)
        self._autoscroll()
        return widget

    def _autoscroll(self) -> None:
        if self._stick_bottom:
            self.chat.scroll_end(animate=False)

    def add_error(self, message: str) -> None:
        self.add_msg(Text(f"error: {message}"), "error")

    def add_note(self, message: str) -> Static:
        return self.add_msg(Text(message), "system")

    def _refresh_status(self) -> None:
        if config_mod.is_connected(self.cfg):
            status = f"{self.cfg['provider']} · {self.cfg['model']}"
        else:
            status = "not connected"
        self.query_one("#status", Static).update(status)

    @staticmethod
    def _fmt_tokens(n: int) -> str:
        if n < 1000:
            return str(n)
        if n < 1_000_000:
            return f"{n / 1000:.1f}k".replace(".0k", "k")
        return f"{n / 1_000_000:.2f}M"

    def _refresh_tokens(self) -> None:
        sent = self._fmt_tokens(self._tok_in)
        reply = self._fmt_tokens(self._tok_out)
        label = f"↑{sent} sent  ↓{reply} reply"
        if self._tok_cached:
            label += f"  ⚡{self._fmt_tokens(self._tok_cached)} cached"
        self.query_one("#app-name", Static).update(label)

    def _add_tokens(self, inp: int, out: int, cached: int = 0) -> None:
        self._tok_in += inp
        self._tok_out += out
        self._tok_cached += cached
        self._refresh_tokens()

    #session

    def _build_system_prompt(self) -> str:
        parts = [config_mod.system_prompt()]
        enabled = self.cfg.get("skills") or {}
        for name in config_mod.list_skills():
            if enabled.get(name):
                content = config_mod.read_skill(name)
                if content:
                    parts.append(f"## skill: {name}\n\n{content}")
        parts.append(SHELL_DIRECTIVES[shell_kind()])
        parts.append(DELEGATE_DIRECTIVE)
        if self._sandbox.enabled:
            parts.append(SANDBOX_DIRECTIVE.format(root=self._sandbox.root))
        parts.append(PLAN_DIRECTIVE if self._agent_mode == "plan" else BUILD_DIRECTIVE)
        return "\n\n".join(parts)

    def _save_config(self) -> None:
        try:
            config_mod.save_config(self.cfg)
        except config_mod.StorageError as exc:
            self.add_error(str(exc))

    def _save_session(self) -> None:
        try:
            raw_history = list(self.input.input_history)
            self._session_history = raw_history
        except Exception:
            raw_history = getattr(self, "_session_history", [])
        # slash commands are recallable in-session but not worth saving
        history = [h for h in raw_history if not h.startswith("/")]
        if not self.messages and not history:
            return  # don't litter sessions/ with empty files
        try:
            config_mod.save_session(
                {
                    "id": self.session_id,
                    "created": self._session_created,
                    "title": self._chat_title,
                    "provider": self.cfg.get("provider"),
                    "model": self.cfg.get("model"),
                    "messages": self.messages,
                    "input_history": history[-200:],
                    "tokens_in": self._tok_in,
                    "tokens_out": self._tok_out,
                    "tokens_cached": self._tok_cached,
                }
            )
        except config_mod.StorageError as exc:
            if not self._storage_warned:
                self._storage_warned = True
                self.add_error(f"{exc} — the chat is still here, but not on disk")

    #input

    def _echo_user(self, text: str) -> None:
        # Sending something always jumps you back to the bottom.
        self._stick_bottom = True
        widget = self.add_msg(Text(f"❯ {text}"), "user")
        self._user_msgs.append((widget, text))

    def _set_key_entry(self, active: bool) -> None:
        self.input.display = not active
        self.key_input.display = active
        if active:
            self.key_input.focus()
        else:
            self.key_input.value = ""
            self.input.focus()

    def on_prompt_area_submitted(self, event: PromptArea.Submitted) -> None:
        text = self.input.resolve_pastes(event.value).strip()
        self.input.set_text("")

        if self.mode == CHOICE:
            return  # answered in the popup menu, not by submit
        if self.mode == PICK:
            return  # handled by the OptionList (arrow-navigate + enter)
        if self.mode == ENTER_URL:
            self._submit_custom_url(text)
            return
        if not text:
            return
        self.input.remember(text)
        self._save_session()
        self._echo_user(text)

        if text.startswith("/"):
            self._run_command(text)
        else:
            self._chat(text)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self.mode != ENTER_KEY:
            return
        key = event.value.strip()
        self._set_key_entry(False)
        self._submit_key(key)

    #commands

    def _show_help(self, arg: str) -> None:
        """/help lists the commands; /help <command> explains one."""
        strong, muted, faint = self.c("strong"), self.c("muted"), self.c("faint")
        if arg:
            name = arg if arg.startswith("/") else "/" + arg
            name = name.lower()
            if name not in COMMAND_NAMES:
                self.add_error(f"no command {name} — /help lists them all")
                return
            detail = COMMAND_HELP.get(name) or dict(COMMANDS).get(name, "")
            t = Text()
            head, _, body = detail.partition("\n")
            t.append(head + "\n", style=f"bold {strong}")
            if body:
                t.append(body.lstrip("\n"), style=muted)
            self.add_msg(t, "system")
            return
        t = Text()
        for cmd_name, desc in COMMANDS:
            t.append(f"{cmd_name:<11}", style=f"bold {strong}")
            t.append(f"{desc}\n", style=muted)
        t.append("\n/help <command>", style=f"bold {strong}")
        t.append(" for detail on one", style=faint)
        self.add_msg(t, "system")

    def _run_command(self, text: str) -> None:
        cmd = text.split(maxsplit=1)[0].lower()
        if cmd in ("/exit", "/quit"):
            self.exit()
        elif cmd == "/help":
            arg = text.split(maxsplit=1)[1].strip() if " " in text else ""
            self._show_help(arg)
        elif cmd == "/clear":
            self._reset_conversation()
        elif cmd == "/connect":
            self._start_connect(text.split(maxsplit=1)[1] if " " in text else "")
        elif cmd == "/model":
            self._start_model_switch()
        elif cmd == "/skills":
            self._start_skills()
        elif cmd == "/editor":
            self._editor_command_or_set(
                text.split(maxsplit=1)[1].strip() if " " in text else ""
            )
        elif cmd == "/theme":
            self._set_theme(text.split(maxsplit=1)[1].strip() if " " in text else "")
        elif cmd == "/config":
            self._open_config()
        elif cmd == "/new":
            self._new_session()
        elif cmd == "/sessions":
            self._start_sessions()
        elif cmd == "/schedule":
            self._start_schedule(text.split(maxsplit=1)[1] if " " in text else "")
        elif cmd == "/routines":
            self._start_routines()
        elif cmd == "/agents":
            self._start_agents()
        elif cmd == "/compact":
            self._start_compact()
        elif cmd == "/keys":
            self.key_debug = True
            self.add_note("key debug — press keys to see what your terminal sends · esc to exit")
        else:
            self.add_error(f"unknown command: {cmd} — type /help for a list")

    def _reset_conversation(self) -> None:
        self.messages.clear()
        self._user_msgs.clear()
        self._clear_tasks()
        self._stick_bottom = True
        self.chat.remove_children()
        self.add_msg(_welcome(self, self.cwd, resumed=self._resumed), "system", "welcome")
        self._save_session()
        self._update_jump_pills()

    def _guard_busy(self) -> bool:
        if self._busy:
            self.add_note("still working — press esc to cancel first")
            return True
        return False

    #scrollable picker

    def _open_picker(self, title, options, on_select, highlight=None,
                     on_toggle=None, on_close=None, on_preview=None,
                     on_cancel=None) -> None:
        self._picker_all = list(options)
        self._picker_on_select = on_select
        self._picker_on_toggle = on_toggle
        self._picker_on_close = on_close   # a checklist reports itself on esc
        self._picker_on_preview = on_preview
        self._picker_on_cancel = on_cancel
        self._picker_committed = False
        self._picker_filter = ""
        self._picker_title = title
        self._fit_picker()
        self._render_picker(highlight=highlight)
        self.query_one("#picker", Vertical).display = True
        self.query_one("#picker-list", OptionList).focus()
        self.mode = PICK

    # Rows the picker's chrome costs: 2 border + 1 title + 1 search.
    PICKER_CHROME = 4
    PICKER_MAX_ROWS = 12

    def _fit_picker(self) -> None:
        room = self.size.height - self.PICKER_CHROME - 6  # topbar, input, rules
        rows = max(3, min(self.PICKER_MAX_ROWS, room))
        self.query_one("#picker-list", OptionList).styles.max_height = rows

    def on_resize(self, event: events.Resize) -> None:
        # A terminal that shrinks under an open picker must not re-introduce
        # the clipping.
        if self.mode == PICK:
            self._fit_picker()
            ol = self.query_one("#picker-list", OptionList)
            self.call_after_refresh(lambda: self._scroll_picker_highlight(ol))

    def _render_picker(self, highlight: int | None = None) -> None:
        needle = self._picker_filter.lower()
        shown = [
            (label, value) for label, value in self._picker_all
            # a section header (value None) only survives if the filter is empty
            if (value is None and not needle) or (value is not None and needle in label.lower())
        ]
        keep = None
        if highlight is None:
            ol_old = self.query_one("#picker-list", OptionList)
            idx = ol_old.highlighted
            if idx is not None and 0 <= idx < len(self._picker_values):
                keep = self._picker_values[idx]

        self._picker_values = [value for _label, value in shown]
        ol = self.query_one("#picker-list", OptionList)
        ol.clear_options()
        ol.add_options(
            [Option(Text(label), disabled=value is None) for label, value in shown]
        )

        if shown:
            if keep is not None and keep in self._picker_values:
                idx = self._picker_values.index(keep)
            else:
                idx = highlight if highlight is not None else 0
                idx = max(0, min(idx, len(shown) - 1))
            # Never land the highlight on a disabled section header.
            while idx < len(shown) and shown[idx][1] is None:
                idx += 1
            ol.highlighted = min(idx, len(shown) - 1)

        keys = (
            "↑↓ move · enter toggles · esc close"
            if self._picker_on_toggle is not None
            else "↑↓ move · enter chooses · esc cancel"
        )
        self.query_one("#picker-title", Static).update(
            Text(f"{self._picker_title}   {keys}", style=self.c("muted"))
        )
        if self._picker_filter:
            search = Text("search: ", style=self.c("muted"))
            search.append(self._picker_filter, style=f"bold {self.c('strong')}")
            if not shown:
                search.append("   no matches", style=self.c("faint"))
        else:
            search = Text("type to search", style=self.c("faint"))
        self.query_one("#picker-search", Static).update(search)
        self.call_after_refresh(lambda: self._scroll_picker_highlight(ol))

    @staticmethod
    def _scroll_picker_highlight(ol: OptionList) -> None:
        try:
            ol.scroll_to_highlight()
        except Exception:
            pass

    def _picker_key(self, event: events.Key) -> bool:
        if self.mode != PICK:
            return False
        if event.key == "backspace":
            if self._picker_filter:
                self._picker_filter = self._picker_filter[:-1]
                self._render_picker(highlight=0)
            return True
        if event.key == "ctrl+u":
            if self._picker_filter:
                self._picker_filter = ""
                self._render_picker(highlight=0)
            return True
        char = event.character
        if char and char.isprintable():
            self._picker_filter += char
            self._render_picker(highlight=0)
            return True
        return False

    def on_key(self, event: events.Key) -> None:
        # the input usually swallows these first; this catches the case where
        # something else holds focus
        if self.mode == CHOICE and event.key != "escape":
            if self._choice_key(event.key):
                event.stop()
                event.prevent_default()
            return
        if self._picker_key(event):
            event.stop()
            event.prevent_default()
            return
        if self._autofocus_prompt(event):
            event.stop()
            event.prevent_default()

    def _autofocus_prompt(self, event: events.Key) -> bool:
        if self.mode != NORMAL:
            return False  # a popup/picker/key-entry owns the keyboard
        char = event.character
        if not char or len(char) != 1 or not char.isprintable():
            return False  # leave navigation keys and shortcuts alone
        if isinstance(self.focused, (Input, TextArea)):
            return False  # already in a text field — let it handle the key
        if not self.input.display:
            return False  # prompt is hidden (e.g. key entry)
        self.input.focus()
        self.input.insert(char)
        return True

    def _close_picker(self) -> None:
        self.query_one("#picker", Vertical).display = False
        on_close = self._picker_on_close
        on_cancel = self._picker_on_cancel
        committed = self._picker_committed
        self._picker_on_select = None
        self._picker_on_toggle = None
        self._picker_on_close = None
        self._picker_on_preview = None
        self._picker_on_cancel = None
        self._picker_values = []
        self._picker_all = []
        self._picker_filter = ""
        if self.mode == PICK:
            self.mode = NORMAL
        self.input.focus()
        if on_cancel is not None and not committed:
            on_cancel()
        if on_close is not None:
            on_close()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if self.mode != PICK:
            return
        self._scroll_picker_highlight(event.option_list)
        if self._picker_on_preview is not None:
            idx = event.option_index
            if 0 <= idx < len(self._picker_values):
                value = self._picker_values[idx]
                if value is not None:
                    self._picker_on_preview(value)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if self.mode != PICK:
            return
        idx = event.option_index
        value = self._picker_values[idx] if 0 <= idx < len(self._picker_values) else None
        if value is None:
            return
        if self._picker_on_toggle is not None:
            label = self._picker_on_toggle(value)
            if label is not None:
                event.option_list.replace_option_prompt_at_index(idx, Text(label))
                event.option_list.highlighted = idx
                self._picker_all = [
                    (label if v == value else lbl, v) for lbl, v in self._picker_all
                ]
            return
        callback = self._picker_on_select
        self._picker_committed = True   # a real choice: don't revert the preview
        self._close_picker()
        if callback is not None:
            callback(value)

    #/theme

    THEME_CHOICES = THEME_CHOICES  # set at module scope below

    def _set_theme(self, arg: str) -> None:
        arg = (arg or "").lower().strip()
        if not arg:
            choices = list(self.THEME_CHOICES)
            current = self.cfg.get("theme") or "dark"
            hi = choices.index(current) if current in choices else 0
            self._theme_before = current
            self._open_picker(
                "theme", [(c, c) for c in choices], self._apply_theme_choice,
                highlight=hi, on_preview=self._preview_theme,
                on_cancel=self._revert_theme,
            )
            return
        if arg not in self.THEME_CHOICES:
            self.add_error("theme: dark, light, matrix, system, or a named theme"
                           " (see /help theme)")
            return
        self._apply_theme_choice(arg)

    def _preview_theme(self, choice: str) -> None:
        self._apply_theme(choice)
        self._refresh_welcome()

    def _revert_theme(self) -> None:
        before = getattr(self, "_theme_before", None)
        if before:
            self._apply_theme(before)
            self._refresh_welcome()

    def _apply_theme_choice(self, arg: str) -> None:
        self._apply_theme(arg)
        self.cfg["theme"] = arg
        self._save_config()
        self._start_theme_watch()   # 'system' keeps following the OS; others stop it
        self._refresh_welcome()

    #/editor

    def _editor_command(self) -> list[str] | None:
        import shlex
        import shutil
        import sys

        chosen = (self.cfg.get("editor") or "").strip()
        if chosen:
            try:
                parts = shlex.split(chosen)
            except ValueError:
                parts = chosen.split()
            if parts and (shutil.which(parts[0]) or os.path.isfile(parts[0])):
                return parts
            if parts:
                self.add_error(
                    f"editor from config.json not found: {parts[0]}"
                    " — falling back to $EDITOR"
                )
        env = os.environ.get("VISUAL") or os.environ.get("EDITOR")
        if env:
            return env.split()
        if os.name == "nt":  # pragma: no cover
            return ["notepad"]
        for name in ("nvim", "vim", "vi"):
            if shutil.which(name):
                return [name]
        if sys.platform == "darwin":  # TextEdit as a last resort
            return ["open", "-e", "-W"]
        return None

    def _editor_command_or_set(self, arg: str) -> None:
        """`/editor` composes a message; `/editor <binary>` sets which editor to
        use from now on (the same thing as "editor" in config.json)."""
        if not arg:
            self._open_editor()
            return
        import shlex
        import shutil

        try:
            parts = shlex.split(arg)
        except ValueError:
            parts = arg.split()
        if not parts:
            self.add_error("usage: /editor <binary>   e.g. /editor nano")
            return
        if not (shutil.which(parts[0]) or os.path.isfile(parts[0])):
            self.add_error(f"no such editor: {parts[0]}")
            return
        self.cfg["editor"] = arg
        self._save_config()
        self.add_note(f"editor: {arg} · /editor with no argument opens it")

    def _open_editor(self) -> None:
        if self._guard_busy():
            return
        editor = self._editor_command()
        if editor is None:
            self.add_error("no editor found (set $EDITOR, or install nvim/vim)")
            return
        import subprocess
        import tempfile

        path = tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", prefix="cutecat-", delete=False
        )
        path.write(self.input.text)
        path.close()
        try:
            with self.suspend():
                subprocess.run([*editor, path.name])
            content = open(path.name, encoding="utf-8", errors="replace").read().rstrip("\n")
        except Exception as exc:
            self.add_error(f"editor failed: {exc}")
            content = None
        finally:
            from cutecat import crypto

            if crypto.is_unlocked():
                crypto.shred(Path(path.name))
            else:
                try:
                    os.unlink(path.name)
                except OSError:
                    pass
        if content is not None:
            self.input.set_text(content)
            self.input.focus()

    def _open_config(self) -> None:
        if self._guard_busy():
            return
        editor = self._editor_command()
        if editor is None:
            self.add_error("no editor found (set $EDITOR, or install nvim/vim)")
            return
        import json
        import subprocess
        import tempfile

        from cutecat import crypto

        try:
            if config_mod.CONFIG_FILE.exists():
                data = json.loads(config_mod.read_text(config_mod.CONFIG_FILE))
            else:
                data = self.cfg
            original = json.dumps(data, indent=2, default=str)
        except Exception as exc:
            self.add_error(f"could not read config: {exc}")
            return

        config_mod.ensure_dirs()
        handle = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", prefix="config-edit-",
            dir=str(config_mod.CUTECAT_DIR), delete=False,
        )
        handle.write(original)
        handle.close()
        edited = None
        try:
            with self.suspend():
                subprocess.run([*editor, handle.name])
            edited = open(handle.name, encoding="utf-8", errors="replace").read()
        except Exception as exc:
            self.add_error(f"editor failed: {exc}")
        finally:
            if crypto.is_unlocked():
                crypto.shred(Path(handle.name))
            else:
                try:
                    os.unlink(handle.name)
                except OSError:
                    pass

        if edited is None:
            return
        if edited.strip() == original.strip():
            self.add_note("config unchanged")
            return
        try:
            parsed = json.loads(edited)
            if not isinstance(parsed, dict):
                raise ValueError("the config must be a JSON object { ... }")
        except (json.JSONDecodeError, ValueError) as exc:
            self.add_error(f"not saved — invalid JSON: {exc}")
            return
        try:
            config_mod.save_config(parsed)   # re-encrypts if the store is unlocked
        except Exception as exc:
            self.add_error(f"could not save config: {exc}")
            return
        # reload through the loader, then re-apply what takes effect live
        self.cfg = config_mod.load_config()
        self._apply_theme(self.cfg.get("theme") or "dark")
        self._start_theme_watch()
        self._refresh_status()
        self._refresh_welcome()
        self.add_note("config saved")

    #/new, /sessions

    def _new_session(self) -> None:
        if self._guard_busy():
            return
        self._save_session()
        self._load_into_session(None)
        self.add_note("started a fresh session")

    def _start_sessions(self) -> None:
        if self._guard_busy():
            return
        sessions = config_mod.list_sessions()
        sessions = [s for s in sessions if s["id"] != self.session_id][:30]
        if not sessions:
            self.add_note("no other sessions yet")
            return
        options = []
        for s in sessions:
            title = s.get("title") or "(untitled)"
            label = f"{title}   {s['id'][:8]} · {s.get('updated', '')[:10]}"
            options.append((label, s["id"]))
        self._open_picker("your sessions", options, self._open_session_id)

    def _open_session_id(self, session_id: str) -> None:
        self._save_session()
        loaded = config_mod.load_session(session_id)
        if loaded is None:
            self.add_error("could not open that session")
            return
        self._load_into_session(loaded)
        self.add_note(f"opened session {session_id[:8]}")

    def _load_into_session(self, session: dict | None) -> None:
        self._op += 1  # invalidate any in-flight worker callbacks
        session = session or {}
        self.session_id = session.get("id") or config_mod.new_session_id()
        self._session_created = session.get("created") or config_mod.now_iso()
        self.messages = list(session.get("messages") or [])
        self._chat_title = session.get("title") or ""
        self._title_started = bool(self._chat_title)
        self._tools_disabled = False
        self.tip = random.choice(TIPS)  # opening a session shows a new tip
        self._resumed = bool(session)
        self._tok_in = int(session.get("tokens_in") or 0)
        self._tok_out = int(session.get("tokens_out") or 0)
        self._tok_cached = int(session.get("tokens_cached") or 0)
        self._clear_tasks()
        self._user_msgs.clear()
        self._stick_bottom = True
        self._refresh_tokens()
        self.chat.remove_children()
        self.add_msg(_welcome(self, self.cwd, resumed=self._resumed), "system", "welcome")
        self.input.input_history = list(session.get("input_history") or [])
        for message in self.messages:
            if message["role"] == "user":
                self._echo_user(message["content"])
            elif message["role"] == "assistant" and message.get("content", "").strip():
                self._make_assistant_widget(message["content"])
        short = self.session_id[:8]
        self.set_terminal_title(
            f"{self._chat_title} - {short}" if self._chat_title else f"cutecat - {short}"
        )
        self._update_jump_pills()

    #/connect

    def _start_connect(self, arg: str = "") -> None:
        if self._guard_busy():
            return
        arg = (arg or "").strip().lower()
        if arg and arg not in ("new", "reset"):
            self.add_note("usage: /connect · /connect new (enter a different api key)")
            return
        self._force_new_key = bool(arg)
        saved = self.cfg.get("api_keys") or {}

        def label(p: Provider) -> str:
            mark = "   (key saved)" if saved.get(p.id) else ""
            return f"{p.display_name} — {p.description}{mark}"

        options: list[tuple[str, object]] = [(label(p), p.id) for p in PROVIDERS]
        self._open_picker("available APIs", options, self._choose_provider)

    def _choose_provider(self, provider_id: str) -> None:
        provider = get_provider(provider_id)
        if provider is None:  # config or picker out of step with the registry
            self.add_error("unknown provider — run /connect again")
            return
        self._pending_provider = provider
        if provider_id == "custom":
            self._start_custom_setup()
            return
        saved = config_mod.get_api_key(self.cfg, provider_id)
        if saved and not self._force_new_key:
            self.add_note(
                f"using your saved {provider.display_name} key"
                " · /connect new to enter a different one"
            )
            self._check_key(saved, saved=True)
            return
        self._prompt_for_key()

    #custom API

    def _start_custom_setup(self) -> None:
        """Pick the wire format for a custom endpoint, then its base URL."""
        current = (self.cfg.get("custom") or {}).get("wire") or "openai"
        options = [
            ("OpenAI-compatible  ·  Chat Completions API (most services)", "openai"),
            ("Anthropic-compatible  ·  Messages API", "anthropic"),
        ]
        hi = 1 if str(current).lower() == "anthropic" else 0
        self._open_picker(
            "custom API type", options, self._choose_custom_wire, highlight=hi
        )

    def _choose_custom_wire(self, wire: str) -> None:
        self._pending_custom_wire = wire if wire in ("openai", "anthropic") else "openai"
        current = (self.cfg.get("custom") or {}).get("base_url") or ""
        example = ".../v1  (OpenAI)" if self._pending_custom_wire == "openai" \
            else ".../v1  (Anthropic)"
        self.add_note(
            f"enter the base URL for your endpoint — e.g. {example}"
            + (f" · current: {current}" if current else "")
            + " · esc to cancel"
        )
        self.mode = ENTER_URL
        self.input.set_text(current)   # pre-fill so an existing URL can be edited
        self.input.focus()

    def _submit_custom_url(self, url: str) -> None:
        url = (url or "").strip().rstrip("/")
        self.input.set_text("")
        self.mode = NORMAL
        if not url:
            self._pending_provider = None
            self.add_note("cancelled — no URL entered")
            return
        if not url.lower().startswith(("http://", "https://")):
            self.add_error("the base URL must start with http:// or https://")
            self._choose_custom_wire(self._pending_custom_wire)  # ask again
            return
        self.cfg["custom"] = {"base_url": url, "wire": self._pending_custom_wire}
        self._save_config()
        self.add_note(f"custom endpoint: {url}  ({self._pending_custom_wire})")
        # Now the key (reuse the saved one unless /connect new).
        saved = config_mod.get_api_key(self.cfg, "custom")
        if saved and not self._force_new_key:
            self.add_note("using your saved key · /connect new to enter a different one")
            self._check_key(saved, saved=True)
        else:
            self._prompt_for_key()

    def _prompt_for_key(self) -> None:
        name = self._pending_provider.display_name if self._pending_provider else "API"
        self.add_note(
            f"enter your {name} api key (input is hidden) · enter to cancel"
        )
        self.mode = ENTER_KEY
        self._set_key_entry(True)

    def _submit_key(self, raw: str) -> None:
        # Whatever gets pasted, salvage a usable key from it (quotes, a
        # `Bearer ` prefix, stray newlines) — an empty result means cancel.
        key = config_mod.clean_api_key(raw)
        if not key:
            self.mode = NORMAL
            self._pending_provider = None
            self.add_note("cancelled — no api key entered")
            return
        if self._pending_provider is None:
            self.mode = NORMAL
            self.add_error("no provider selected — run /connect again")
            return
        self._echo_user("•" * 8)
        self.mode = NORMAL
        self._check_key(key, saved=False)

    def _check_key(self, key: str, *, saved: bool) -> None:
        self._busy = True
        self._pending_key = key
        self._pending_key_saved = saved
        self._start_indicator("validating key")
        self._connect_worker(self._pending_provider, key, self._op)

    @work(thread=True, group="net")
    def _connect_worker(self, provider: Provider, key: str, op: int) -> None:
        try:
            ok = provider.validate_key(key)
            models = provider.list_models(key) if ok else []
        except ProviderError as exc:
            self.call_from_thread(self._net_failed, str(exc), op)
            return
        except Exception as exc:  # never take the app down over a bad reply
            self.call_from_thread(self._net_failed, _unexpected(exc), op)
            return
        self.call_from_thread(self._connect_validated, ok, models, op)

    def _net_failed(self, message: str, op: int) -> None:
        if op != self._op:
            return
        self._busy = False
        self._stop_indicator()
        self.add_error(message)

    def _connect_validated(self, ok: bool, models: list[str], op: int) -> None:
        if op != self._op:
            return
        self._busy = False
        self._stop_indicator()
        if not ok:
            self._key_rejected()
            return
        self._show_model_picker(models)

    def _key_rejected(self) -> None:
        provider = self._pending_provider
        name = provider.display_name if provider else "the provider"
        if self._pending_key_saved and provider is not None:
            config_mod.forget_api_key(self.cfg, provider.id)
            self._save_config()
            self.add_error(
                f"your saved {name} key was rejected — it may have been revoked"
            )
        else:
            self.add_error(f"{name} rejected that api key — check it and try again")
        self._pending_key = None
        self._prompt_for_key()

    def _show_model_picker(self, models: list[str]) -> None:
        if not models:
            self.add_error("no models are available for this account")
            return
        current = self.cfg.get("model")
        options = [(m + ("  (current)" if m == current else ""), m) for m in models]
        hi = models.index(current) if current in models else 0
        self._open_picker("available models", options, self._choose_model, highlight=hi)

    def _choose_model(self, model: str) -> None:
        if self._pending_provider is not None and self._pending_key:
            self.cfg["provider"] = self._pending_provider.id
            self.cfg["api_key"] = self._pending_key
            # Remember it per provider, so picking this provider again never
            # asks for the key a second time.
            config_mod.set_api_key(self.cfg, self._pending_provider.id, self._pending_key)
            self._pending_provider = None
            self._pending_key = None
        self.cfg["model"] = model
        self._tools_disabled = False  # new provider/model — re-enable tools
        self._save_config()
        self._refresh_status()
        self.add_note(f"connected — {self.cfg['provider']} · {model}")

    #/model

    def _start_model_switch(self) -> None:
        if self._guard_busy():
            return
        if not self.cfg.get("provider") or not self.cfg.get("api_key"):
            self.add_error("not connected yet — run /connect first")
            return
        provider = get_provider(self.cfg["provider"])
        if provider is None:
            self.add_error("unknown provider in config — run /connect again")
            return
        self._busy = True
        self._start_indicator("fetching models")
        self._models_worker(provider, self.cfg["api_key"], self._op)

    @work(thread=True, group="net")
    def _models_worker(self, provider: Provider, key: str, op: int) -> None:
        try:
            models = provider.list_models(key)
        except ProviderError as exc:
            self.call_from_thread(self._net_failed, str(exc), op)
            return
        except Exception as exc:
            self.call_from_thread(self._net_failed, _unexpected(exc), op)
            return
        self.call_from_thread(self._models_listed, models, op)

    def _models_listed(self, models: list[str], op: int) -> None:
        if op != self._op:
            return
        self._busy = False
        self._stop_indicator()
        self._show_model_picker(models)

    #/skills

    def _skill_label(self, name: str) -> str:
        on = bool((self.cfg.get("skills") or {}).get(name))
        return f"[{'x' if on else ' '}] {name}"

    def _start_skills(self) -> None:
        if self._guard_busy():
            return
        names = config_mod.list_skills()
        if not names:
            self.add_note(f"no skills found — put .md files in {config_mod.SKILLS_DIR}")
            return
        self._skill_names = names
        self._open_picker(
            "skills",
            [(self._skill_label(n), n) for n in names],
            on_select=None,
            on_toggle=self._toggle_skill,
            on_close=self._finish_skills,
        )

    def _toggle_skill(self, name: str) -> str:
        skills = self.cfg.setdefault("skills", {})
        skills[name] = not skills.get(name, False)
        self._save_config()
        self._system = self._build_system_prompt()  # takes effect on the next turn
        return self._skill_label(name)

    def _finish_skills(self) -> None:
        enabled = [n for n in self._skill_names
                   if (self.cfg.get("skills") or {}).get(n)]
        self.add_note(
            f"skills on: {', '.join(enabled)}" if enabled else "no skills enabled"
        )

    # /schedule, /routines

    def _start_schedule(self, description: str) -> None:
        if self._guard_busy():
            return
        if not description:
            self.add_note(
                "usage: /schedule <what to do, and when>  ·  e.g."
                " /schedule every weekday at 9am, summarise yesterday's commits"
            )
            return
        if not config_mod.is_connected(self.cfg):
            self.add_error("not connected — run /connect first")
            return
        provider = get_provider(self.cfg["provider"])
        if provider is None:
            self.add_error("unknown provider in config — run /connect again")
            return
        self._busy = True
        self._start_indicator("drafting the routine")
        self._schedule_worker(
            provider, self.cfg["api_key"], self.cfg["model"], description, self._op
        )

    @work(thread=True, group="net")
    def _schedule_worker(self, provider: Provider, key: str, model: str,
                         description: str, op: int) -> None:
        from datetime import datetime

        now = datetime.now().astimezone()
        messages = [
            {"role": "system", "content": SCHEDULE_PROMPT.format(
                now=now.strftime("%Y-%m-%d %H:%M (%A)")
            )},
            {"role": "user", "content": description},
        ]
        raw = ""
        try:
            for kind, payload in provider.stream_chat(key, model, messages, tools=None):
                if kind == "content" and payload:
                    raw += payload
        except ProviderError as exc:
            self.call_from_thread(self._net_failed, str(exc), op)
            return
        except Exception as exc:
            self.call_from_thread(self._net_failed, _unexpected(exc), op)
            return
        self.call_from_thread(self._schedule_drafted, raw, op)

    def _schedule_drafted(self, raw: str, op: int) -> None:
        import json

        if op != self._op:
            return
        self._busy = False
        self._stop_indicator()
        body = raw.strip()
        if "```" in body:  # models like to fence their json
            body = body.split("```")[1].removeprefix("json").strip()
        try:
            spec = json.loads(body)
            name = str(spec["name"]).strip()
            prompt = str(spec["prompt"]).strip()
        except (ValueError, KeyError, TypeError):
            self.add_error("could not turn that into a routine — try rephrasing it")
            return
        cron = spec.get("cron") or None
        once = spec.get("once_at") or None
        self._pending_routine = {
            "name": name, "prompt": prompt, "cron": cron, "once_at": once,
        }
        t = Text()
        t.append("routine\n", style=f"bold {self.c('strong')}")
        t.append(f"  {name}\n", style=self.c("strong"))
        when = cron or (f"once at {once}" if once else "manual only")
        t.append(f"  when: {when}\n", style=self.c("muted"))
        t.append(f"  in:   {self.cwd}\n", style=self.c("muted"))
        t.append(f"  {prompt}", style=self.c("faint"))
        self.add_msg(t, "system")
        self._open_picker(
            "create this routine?",
            [
                ("safe — it may only look, never change anything", "safe"),
                ("allow writes — it may edit files and run any command, unattended",
                 "auto"),
            ],
            self._create_routine,
        )

    def _create_routine(self, permissions: str) -> None:
        spec = self._pending_routine
        self._pending_routine = None
        if not spec:
            return
        try:
            routine = routines_mod.create(
                spec["name"], spec["prompt"],
                cron=spec.get("cron"), once_at=spec.get("once_at"),
                cwd=self.cwd, permissions=permissions,
                provider=self.cfg.get("provider"), model=self.cfg.get("model"),
            )
        except routines_mod.RoutineError as exc:
            self.add_error(str(exc))
            return
        self.add_note(f"routine '{routine['name']}' — {routines_mod.describe(routine)}")
        if routine.get("cron") or routine.get("once_at"):
            self.add_note(
                "start the scheduler so it can fire: cutecat routines serve"
                "  (or run it now from /routines)"
            )

    def _start_routines(self) -> None:
        if self._guard_busy():
            return
        items = routines_mod.load()
        if not items:
            self.add_note(
                "no routines yet — /schedule <what to do, and when> creates one"
            )
            return
        options = []
        for r in items:
            mark = "" if r.get("permissions") == "safe" else "  [writes]"
            options.append(
                (f"{r['name']}   {routines_mod.describe(r)}{mark}", r["id"])
            )
        self._open_picker("your routines", options, self._pick_routine)

    def _pick_routine(self, routine_id: str) -> None:
        routine = routines_mod.find(routine_id)
        if routine is None:
            self.add_error("that routine is gone")
            return
        self._pending_routine = routine
        paused = not routine.get("enabled", True)
        self._open_picker(
            routine["name"],
            [
                ("run it now", "run"),
                ("resume" if paused else "pause", "toggle"),
                ("delete", "delete"),
            ],
            self._routine_action,
        )

    def _routine_action(self, action: str) -> None:
        routine = self._pending_routine
        self._pending_routine = None
        if routine is None:
            return
        if action == "delete":
            routines_mod.remove(routine["id"])
            self.add_note(f"deleted routine '{routine['name']}'")
            return
        if action == "toggle":
            updated = routines_mod.set_enabled(
                routine["id"], not routine.get("enabled", True)
            )
            self.add_note(f"{updated['name']}: {routines_mod.describe(updated)}")
            return
        # run it now, in the background, and report back
        self._busy = True
        self._start_indicator(f"routine · {routine['name']}")
        self._routine_worker(routine, self._op)

    @work(thread=True, group="chat")
    def _routine_worker(self, routine: dict, op: int) -> None:
        from cutecat import headless

        try:
            status, session_id = headless.run_routine(routine)
        except Exception as exc:
            self.call_from_thread(self._net_failed, _unexpected(exc), op)
            return
        self.call_from_thread(self._routine_finished, routine["name"], status,
                              session_id, op)

    def _routine_finished(self, name: str, status: str, session_id: str | None,
                          op: int) -> None:
        if op != self._op:
            return
        self._busy = False
        self._stop_indicator()
        if status == "ok":
            self.add_note(f"routine '{name}' finished · /sessions to read the run")
        else:
            self.add_error(f"routine '{name}': {status}")

    #/agents

    def _start_agents(self) -> None:
        if self._guard_busy():
            return
        options = [
            ("build — carry out tasks directly (default)", "build"),
            ("plan — write a detailed PLAN.md instead of executing", "plan"),
        ]
        hi = 1 if self._agent_mode == "plan" else 0
        self._open_picker("agent mode", options, self._choose_agent_mode, highlight=hi)

    def _choose_agent_mode(self, mode: str) -> None:
        self._agent_mode = mode
        self.cfg["agent_mode"] = mode
        self._save_config()
        self._system = self._build_system_prompt()
        if mode == "plan":
            self.add_note(
                f"agent: plan — describe what you want and it writes {PLAN_FILE}"
                " (no changes made)"
            )
        else:
            self.add_note(f"agent: build — executing tasks; reads {PLAN_FILE} if present")

    #/compact

    def _start_compact(self) -> None:
        if self._guard_busy():
            return
        if not config_mod.is_connected(self.cfg):
            self.add_error("not connected — run /connect first")
            return
        if len([m for m in self.messages if m.get("role") in ("user", "assistant")]) < 2:
            self.add_note("nothing worth compacting yet")
            return
        provider = get_provider(self.cfg["provider"])
        if provider is None:
            self.add_error("unknown provider in config — run /connect again")
            return
        self._busy = True
        self._inflight = True
        self._start_indicator("compacting", progress=True)
        self._compact_worker(provider, self.cfg["api_key"], self.cfg["model"], self._op)

    @work(thread=True, group="chat")
    def _compact_worker(self, provider: Provider, key: str, model: str, op: int) -> None:
        req = [
            {"role": "system", "content": COMPACT_PROMPT},
            {"role": "user", "content": _transcript(self.messages)},
        ]
        summary = ""
        try:
            for kind, payload in provider.stream_chat(key, model, req, tools=None):
                if op != self._op:
                    return
                if kind == "content" and payload:
                    summary += payload
        except ProviderError as exc:
            self.call_from_thread(self._agent_error, f"compaction failed: {exc}", op)
            return
        except Exception as exc:
            self.call_from_thread(self._agent_error, _unexpected(exc), op)
            return
        self.call_from_thread(self._apply_compaction, summary.strip(), op)

    def _apply_compaction(self, summary: str, op: int) -> None:
        if op != self._op:
            return
        self._busy = False
        self._inflight = False
        self._progress_frac = 1.0
        self._tick_indicator()
        self._stop_indicator()
        if not summary:
            self.add_error("compaction produced nothing — history left unchanged")
            return
        # Replace the whole history with the summary as a single user turn.
        self.messages = [{"role": "user", "content": COMPACT_PREFIX + summary}]
        self._user_msgs.clear()
        self._stick_bottom = True
        self.chat.remove_children()
        self.add_msg(_welcome(self, self.cwd, resumed=self._resumed), "system", "welcome")
        self.add_note("compacted — reopening or switching models now reads only this summary:")
        self._make_assistant_widget(summary)
        self._save_session()
        self._update_jump_pills()

    #agent chat

    def _ensure_shell(self):
        if self._shell is None:
            self._shell = create_shell(self.cwd)
        return self._shell

    def _chat(self, text: str) -> None:
        if self._busy:
            self.add_note("still working — press esc to cancel first")
            return
        if not config_mod.is_connected(self.cfg):
            self.add_error("not connected — run /connect first")
            return
        provider = get_provider(self.cfg["provider"])
        if provider is None:
            self.add_error("unknown provider in config — run /connect again")
            return

        self.messages.append({"role": "user", "content": text})
        self._clear_tasks()  # last turn's list is not this turn's
        # Name the terminal tab from the first thing the user asks for.
        if not self._title_started:
            self._title_started = True
            self._title_worker(provider, self.cfg["api_key"], self.cfg["model"], text)
        self._busy = True
        self._inflight = True
        self._stream_text = ""
        self._stream_target = None
        self._phase = THINKING
        self._verb = random.choice(THINKING_VERBS)
        self._start_indicator()
        self._agent_worker(
            provider, self.cfg["api_key"], self.cfg["model"], self._op
        )

    @work(thread=True, group="title")
    def _title_worker(self, provider: Provider, key: str, model: str, text: str) -> None:
        messages = [
            {"role": "system", "content": TITLE_PROMPT},
            {"role": "user", "content": text},
        ]
        title = ""
        try:
            for kind, payload in provider.stream_chat(key, model, messages):
                if kind == "content":
                    title += payload
        except Exception:
            return  # a title is cosmetic — never surface or crash on it
        title = _clean_title(title)
        if title:
            self.call_from_thread(self._apply_title, title)

    def _apply_title(self, title: str) -> None:
        self._chat_title = title
        self.set_terminal_title(f"{title} - {self.session_id[:8]}")
        self._save_session()

    # -- blocking popup prompts driven from the worker thread --

    def _await_choice(self, question: str, options: list[tuple], default: str) -> str:
        event = threading.Event()
        self._choice_event = event
        self._choice_result = default
        self._choice_options = list(options)
        self._choice_default = default
        self.call_from_thread(self._enter_choice, question, options)
        event.wait()
        return self._choice_result

    def _enter_choice(self, question: str, options: list[tuple]) -> None:
        self.query_one("#popup-q", Static).update(Text(question, style=self.c("strong")))
        self._choice_options = list(options)
        self._choice_index = 0  # allow; esc still denies
        self._render_choice()
        self.query_one("#popup", Vertical).display = True
        self.mode = CHOICE
        self._idle_indicator("waiting for you")

    def _render_choice(self) -> None:
        options = self._choice_options or []
        opts = Text()
        for i, (_key, label, _result) in enumerate(options):
            if i:
                opts.append("\n")
            if i == self._choice_index:
                opts.append(" ❯ ", style=f"bold {self.c('strong')}")
                opts.append(label, style=f"bold {self.c('bg')} on {self.c('strong')}")
            else:
                opts.append("   ")
                opts.append(label, style=self.c("muted"))
        opts.append("\n\n")
        opts.append("↑↓", style=self.c("strong"))
        opts.append(" choose · ", style=self.c("faint"))
        opts.append("enter", style=self.c("strong"))
        opts.append(" confirm · ", style=self.c("faint"))
        opts.append("esc", style=self.c("strong"))
        opts.append(" cancel", style=self.c("faint"))
        self.query_one("#popup-opts", Static).update(opts)

    def _move_choice(self, delta: int) -> None:
        options = self._choice_options or []
        if not options:
            return
        self._choice_index = (self._choice_index + delta) % len(options)
        self._render_choice()

    def _choice_key(self, key: str) -> bool:
        """Drive the popup menu. Returns False for keys it doesn't own."""
        options = self._choice_options or []
        if key in ("down", "right", "tab"):
            self._move_choice(1)
        elif key in ("up", "left", "shift+tab"):
            self._move_choice(-1)
        elif key == "enter":
            if 0 <= self._choice_index < len(options):
                self._resolve_choice(options[self._choice_index][2])
            else:
                self._resolve_choice(self._choice_default)
        else:
            # a letter jumps to its option, but still waits for enter
            for i, (accel, _label, _result) in enumerate(options):
                if key == accel:
                    self._choice_index = i
                    self._render_choice()
                    return True
            return False
        return True

    def _hide_popup(self) -> None:
        self.query_one("#popup", Vertical).display = False
        self._choice_options = None

    def _resolve_choice(self, result: str) -> None:
        self.mode = NORMAL
        self._hide_popup()
        self._idle_indicator()  # back to work (or off, if the turn is over)
        self._choice_result = result
        if self._choice_event is not None:
            self._choice_event.set()
            self._choice_event = None

    _PERMIT = [("y", "allow", "y"), ("n", "deny", "n")]
    _PERMIT_EDIT = [
        ("y", "allow", "y"),
        ("a", "allow all edits", "a"),
        ("n", "deny", "n"),
    ]

    def _ask_permission(self, title: str, detail: str) -> bool:
        answer = self._await_choice(f"{title}\n{detail}", self._PERMIT, "n")
        return answer == "y"

    def _ask_command(self, command: str, reason: str, kind: str) -> bool:
        options = list(self._PERMIT)
        if kind:
            options.insert(1, ("a", f"allow '{kind}' this session", "a"))
        answer = self._await_choice(f"run: {command}\n{reason}", options, "n")
        if answer == "a" and kind:
            self._allowed_kinds.add(kind)
            return True
        return answer == "y"

    def _ask_edit(self, title: str, detail: str) -> bool:
        if self._allow_all_edits:
            return True
        answer = self._await_choice(f"{title}\n{detail}", self._PERMIT_EDIT, "n")
        if answer == "a":
            self._allow_all_edits = True
            return True
        return answer == "y"

    def _ask_tmp(self) -> bool:
        if self._tmp_granted:
            return True
        answer = self._await_choice(
            "Allow the agent to use the temp directory for the rest of this session?",
            self._PERMIT,
            "n",
        )
        if answer == "y":
            self._tmp_granted = True
            return True
        return False

    #task panel

    GLYPH = {"running": "◼", "pending": "◻", "done": "✔", "agent": "◆"}
    SHOW_DONE = 3

    def _set_tasks(self, tasks: list) -> None:
        self.call_from_thread(self._apply_tasks, tasks)

    def _apply_tasks(self, tasks: list) -> None:
        if not self._tasks:
            self._tasks_started = monotonic()
        self._tasks = tasks
        self._refresh_tasks()

    def _clear_tasks(self) -> None:
        self._tasks = []
        self._subagents = {}
        self._refresh_tasks()

    def _refresh_tasks(self) -> None:
        panel = self.query_one("#taskpanel", Static)
        if not self._tasks and not self._subagents:
            panel.display = False
            return
        panel.update(self._task_text())
        panel.display = True

    def _task_text(self) -> Text:
        running = [t for t in self._tasks if t["status"] == "running"]
        pending = [t for t in self._tasks if t["status"] == "pending"]
        done = [t for t in self._tasks if t["status"] == "done"]
        live = list(self._subagents.values())

        out = Text()
        head = running[0]["title"] if running else (
            live[0]["description"] if live else "working"
        )
        elapsed = fmt_duration(monotonic() - self._tasks_started)
        out.append(f" {head}… ", style=self.c("strong"))
        out.append(f"({elapsed} · ↓{self._fmt_tokens(self._tok_out)} tokens)",
                   style=self.c("faint"))

        for agent in live:
            out.append("\n   ")
            out.append(self.GLYPH["agent"], style=self.c("strong"))
            spent = fmt_duration(monotonic() - agent["started"])
            out.append(f" {agent['description']} ", style=self.c("text"))
            out.append(f"· {spent}", style=self.c("faint"))
        for task in running + pending:
            style = self.c("text") if task["status"] == "running" else self.c("muted")
            out.append("\n   ")
            out.append(self.GLYPH[task["status"]], style=style)
            out.append(f" {task['title']}", style=style)
        for task in done[-self.SHOW_DONE:]:
            out.append("\n   ")
            out.append(self.GLYPH["done"], style=self.c("muted"))
            out.append(f" {task['title']}", style=self.c("faint"))
        hidden = len(done) - self.SHOW_DONE
        if hidden > 0:
            out.append(f"\n    … +{hidden} completed", style=self.c("faint"))
        return out

    #subagents

    def _spawn_agent(self, description: str, prompt: str, kind: str) -> str:
        """Run a nested agent on its own context and return only its answer, so
        the work it did to get there never enters this conversation."""
        provider = get_provider(self.cfg["provider"])
        if provider is None:
            return "error: no provider connected"
        agent_id = self._next_agent_id
        self._next_agent_id += 1
        self.call_from_thread(
            self._agent_appeared, agent_id, description, monotonic()
        )
        messages = [{"role": "user", "content": prompt}]
        ctx = ToolContext(
            shell=self._ensure_shell(),
            ask_permission=self._ask_permission,
            ask_tmp=self._ask_tmp,
            note=lambda _t: None,
            is_cancelled=self._agent_cancel,
            run_job=self._run_job,
            show_diff=self._show_diff,
            ask_edit=self._ask_edit,
            chromium=self.cfg.get("chromium"),
            workspace=self.cfg.get("workspace"),
            sandbox=self._sandbox,
            allow_kind=lambda k: k in self._allowed_kinds,
            ask_command=self._ask_command,
        )
        system = SUBAGENT_PROMPTS[kind].format(root=self._sandbox.label)
        answer = ""
        try:
            for event in agent_mod.run_agent(
                provider, self.cfg["api_key"], self.cfg["model"], system,
                messages, ctx,
                tools_enabled=not self._tools_disabled,
                max_steps=SUBAGENT_STEPS,
                cancelled=self._agent_cancel,
            ):
                if isinstance(event, agent_mod.Usage):
                    self.call_from_thread(
                        self._add_tokens, event.input, event.output, event.cached
                    )
                elif isinstance(event, agent_mod.ToolStarted):
                    self.call_from_thread(
                        self._idle_indicator, f"{description} · {event.name}"
                    )
                elif isinstance(event, agent_mod.Done):
                    answer = event.answer
                elif isinstance(event, agent_mod.Failed):
                    answer = f"the subagent stopped: {event.message}"
        finally:
            self.call_from_thread(self._agent_finished, agent_id)
        return answer or "the subagent returned nothing"

    def _agent_appeared(self, agent_id: int, description: str, started: float) -> None:
        if not self._tasks and not self._subagents:
            self._tasks_started = started
        self._subagents[agent_id] = {"description": description, "started": started}
        self._refresh_tasks()

    def _agent_finished(self, agent_id: int) -> None:
        self._subagents.pop(agent_id, None)
        self._refresh_tasks()

    def _tool_note(self, text: str) -> None:
        self.call_from_thread(self._add_tool_note, text)

    def _add_tool_note(self, text: str) -> None:
        self.add_msg(Text(text), "system")

    #commands

    def _run_job(self, command: str) -> str:
        job = self._shell.run(command)
        self._running_job = job
        self._cmd_control = None
        self.call_from_thread(self._cmd_start, job)
        while not job.finished.wait(0.15):
            if self._agent_cancel():
                self._shell.terminate(job)
                job.finished.wait(3)
                self._running_job = None
                self.call_from_thread(self._cmd_finish, job, "cancelled")
                return "error: cancelled by user"
            if self._cmd_control == "terminate":
                self._shell.terminate(job)
                job.finished.wait(3)
                break
            if self._cmd_control == "background":
                self._running_job = None
                self._bg_jobs.append(job)
                self.call_from_thread(self._cmd_backgrounded, job)
                self._watch_bg_job(job)
                return (
                    f"Command sent to the background (job #{job.id}). It keeps "
                    "running; you'll get its output when it finishes. Continue "
                    "with other work in the meantime."
                )
            self.call_from_thread(self._cmd_update, job)
        # finished or terminated
        self._shell.adopt_cwd(job)
        self._running_job = None
        state = "terminated" if self._cmd_control == "terminate" else "done"
        self.call_from_thread(self._cmd_finish, job, state)
        return tools_mod.format_job_result(
            command, job.exit_code, job.output(),
            ran_for=job.ran_for, silent_for=job.silent_for,
        )

    def _cmd_title(self, job, suffix: str) -> str:
        return f"$ {self._short_cmd(job.command)}   {suffix}"

    def _cmd_start(self, job) -> None:
        self._cmd_body = Static(Text("running…"))
        self._cmd_widget = Collapsible(
            self._cmd_body, title=self._cmd_title(job, "running…"),
            collapsed=True, classes="cmd",
        )
        self.chat.mount(self._cmd_widget)
        self._autoscroll()
        self._start_indicator(f"running · {self._short_cmd(job.command)} · esc stop · ctrl+b background")

    def _cmd_update(self, job) -> None:
        if self._cmd_body is not None:
            out = job.output()
            self._cmd_body.update(Text(out[-4000:] or "running…"))
        label = f"running · {self._short_cmd(job.command)}"
        if job.silent_for >= tools_mod.QUIET_COMMAND:
            label += f" · quiet {int(job.silent_for)}s"
        self._net_label = f"{label} · esc stop · ctrl+b background"

    def _cmd_finish(self, job, state: str) -> None:
        self._idle_indicator()
        if self._cmd_widget is None:
            return
        out = job.output()
        lines = out.count("\n") + 1 if out else 0
        if state == "cancelled":
            suffix = "cancelled"
        elif state == "terminated":
            suffix = f"stopped · {lines} lines"
        else:
            suffix = f"exit {job.exit_code} · {lines} lines"
        self._set_collapsible_title(self._cmd_widget, self._cmd_title(job, suffix))
        if self._cmd_body is not None:
            self._cmd_body.update(Text(out or "(no output)"))
        self._cmd_widget = None
        self._cmd_body = None
        self._autoscroll()

    def _cmd_backgrounded(self, job) -> None:
        self._idle_indicator()
        if self._cmd_widget is not None:
            self._set_collapsible_title(
                self._cmd_widget, self._cmd_title(job, f"running in background (#{job.id})")
            )
        self._cmd_widget = None
        self._cmd_body = None
        self.add_note(f"job #{job.id} running in background")

    @work(thread=True, group="bgjobs")
    def _watch_bg_job(self, job) -> None:
        job.finished.wait()
        self.call_from_thread(self._bg_job_done, job)

    def _bg_job_done(self, job) -> None:
        if job in self._bg_jobs:
            self._bg_jobs.remove(job)
        out = job.output()
        lines = out.count("\n") + 1 if out else 0
        body = Static(Text(out or "(no output)"))
        col = Collapsible(
            body,
            title=self._cmd_title(job, f"background #{job.id} · exit {job.exit_code} · {lines} lines"),
            collapsed=True, classes="cmd",
        )
        self.chat.mount(col)
        self._autoscroll()
        # Make the result available to the agent on its next turn.
        self.messages.append(
            {
                "role": "user",
                "content": (
                    f"[background job #{job.id} finished] $ {job.command}\n"
                    + tools_mod.format_job_result(job.command, job.exit_code, out)
                ),
            }
        )
        self._save_session()

    @staticmethod
    def _short_cmd(command: str) -> str:
        c = " ".join(command.split())
        return c if len(c) <= 40 else c[:39] + "…"

    def _set_collapsible_title(self, collapsible: Collapsible, title: str) -> None:
        try:
            collapsible.title = title
        except Exception:
            pass

    def _show_diff(self, path: str, hunks: list, added: int, removed: int) -> None:
        self.call_from_thread(self._mount_diff, path, hunks, added, removed)

    def _mount_diff(self, path: str, hunks: list, added: int, removed: int) -> None:
        self.chat.mount(DiffBlock(path, hunks, added, removed))
        self._autoscroll()

    @work(thread=True, group="chat")
    def _agent_worker(self, provider: Provider, key: str, model: str, op: int) -> None:
        worker = get_current_worker()

        def cancelled() -> bool:
            return worker.is_cancelled or op != self._op

        self._agent_cancel = cancelled
        ctx = ToolContext(
            shell=self._ensure_shell(),
            ask_permission=self._ask_permission,
            ask_tmp=self._ask_tmp,
            note=self._tool_note,
            is_cancelled=cancelled,
            run_job=self._run_job,
            show_diff=self._show_diff,
            ask_edit=self._ask_edit,
            chromium=self.cfg.get("chromium"),
            workspace=self.cfg.get("workspace"),
            sandbox=self._sandbox,
            allow_kind=lambda kind: kind in self._allowed_kinds,
            ask_command=self._ask_command,
            set_tasks=self._set_tasks,
            spawn=self._spawn_agent,
        )
        for event in agent_mod.run_agent(
            provider, key, model, self._system, self.messages, ctx,
            tools_enabled=not self._tools_disabled, cancelled=cancelled,
            extra_schemas=[tools_mod.TASK_SCHEMA, tools_mod.AGENT_SCHEMA],
        ):
            if cancelled():
                return
            if isinstance(event, agent_mod.TurnStarted):
                self.call_from_thread(self._begin_segment, op)
            elif isinstance(event, agent_mod.Content):
                self.call_from_thread(self._stream_chunk, event.full, op)
            elif isinstance(event, agent_mod.Usage):
                self.call_from_thread(
                    self._add_tokens, event.input, event.output, event.cached
                )
            elif isinstance(event, agent_mod.ToolsDisabled):
                self._tools_disabled = True
                self.call_from_thread(self._tool_note, event.reason)
            elif isinstance(event, agent_mod.ToolStarted):
                # Name the tool in the status line, so a slow read/browse
                # doesn't look like the agent has stalled.
                self.call_from_thread(self._idle_indicator, f"working · {event.name}")
            elif isinstance(event, agent_mod.ToolFinished):
                # both draw themselves elsewhere
                if event.name not in ("run_command", "set_tasks"):
                    self.call_from_thread(
                        self._show_tool_result, event.name, event.result, op
                    )
            elif isinstance(event, agent_mod.Done):
                self.call_from_thread(self._agent_done, op)
            elif isinstance(event, agent_mod.Failed):
                self.call_from_thread(self._agent_error, event.message, op)
            # Thinking is hidden reasoning — the TUI drops it, as it always has.

    def _start_indicator(self, label: str | None = None, progress: bool = False) -> None:
        self._net_label = label
        self._progress = progress
        self._progress_frac = None
        self._t_start = monotonic()
        self._t_content = None
        self.indicator.display = True
        self._tick_indicator()
        if self._timer is None:
            self._timer = self.set_interval(0.1, self._tick_indicator)

    def _stop_indicator(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self.indicator.display = False

    def _idle_indicator(self, label: str = "working") -> None:
        if self._inflight:
            self._start_indicator(label)
        else:
            self._stop_indicator()

    def _tick_indicator(self) -> None:
        try:
            self._tick_indicator_inner()
        except Exception:
            pass  # a timer that raises is fatal in Textual; the status line is not

    def _tick_indicator_inner(self) -> None:
        now = monotonic()
        frame = SPINNER[int(now * 10) % len(SPINNER)]
        if self._progress:
            # duration unknown: ease toward 100% and hold just short until done
            if self._progress_frac is not None:
                frac = self._progress_frac
            else:
                frac = min(0.99, 1 - math.exp(-(now - self._t_start) / 12.0))
            cells = max(10, min(40, self.size.width - 24))
            label = f"{frame} {self._net_label} · {progress_bar(frac, cells)}"
        elif self._net_label is not None:
            label = f"{frame} {self._net_label} · {fmt_duration(now - self._t_start)}"
        elif self._phase == THINKING:
            label = f"{frame} {self._verb} · {fmt_duration(now - self._t_start)}"
        else:
            label = (
                f"{frame} responding · {fmt_duration(now - self._t_content)}"
                f" · thought {fmt_duration(self._t_content - self._t_start)}"
            )
        self.indicator.update(Text(label))
        if self._tasks or self._subagents:
            self._refresh_tasks()  # keeps the elapsed clock live
        self._flush_md()  # push the latest streamed markdown at the tick rate

    def _begin_segment(self, op: int) -> None:
        if op != self._op:
            return
        self._flush_md()  # finalize the previous segment's bubble
        self._stream_target = None
        self._stream_text = ""
        self._phase = THINKING
        self._verb = random.choice(THINKING_VERBS)
        self._t_content = None
        self._start_indicator()

    def _make_assistant_widget(self, text: str = "") -> Markdown:
        widget = CuteMarkdown(text, classes="msg assistant")
        self.chat.mount(widget)
        self._autoscroll()
        return widget

    def _stream_chunk(self, reply: str, op: int) -> None:
        if op != self._op:
            return
        if self._t_content is None:
            self._t_content = monotonic()
            self._phase = RESPONDING
        if self._stream_target is None:
            self._stream_target = self._make_assistant_widget()
        self._pending_md = reply
        self._stream_text = reply

    def _flush_md(self) -> None:
        if self._stream_target is not None and self._pending_md is not None:
            self._stream_target.update(self._pending_md)
            self._pending_md = None
            self._autoscroll()

    def _show_tool_result(self, name: str, result: str, op: int) -> None:
        if op != self._op:
            return
        lines = result.count("\n") + 1
        if lines <= 3:
            self.add_msg(Text(result), "tool")
        else:
            # long results collapse; click to see them, click again to hide
            body = Static(Text(result))
            col = Collapsible(
                body, title=f"{name} · {lines} lines", collapsed=True, classes="cmd"
            )
            self.chat.mount(col)
        self._autoscroll()

    def _agent_error(self, message: str, op: int) -> None:
        if op != self._op:
            return
        self._flush_md()
        self._busy = False
        self._inflight = False
        self._stop_indicator()
        if self._stream_target is not None and not self._stream_text:
            self._stream_target.remove()
        self._stream_target = None
        self.add_error(message)
        self._save_session()

    def _agent_done(self, op: int) -> None:
        if op != self._op:
            return
        self._flush_md()
        self._busy = False
        self._inflight = False
        self.cat.pleased(monotonic())  # a job well done
        self._stop_indicator()
        self._stream_target = None
        verb = random.choice(FOOTER_VERBS)
        self.add_msg(Text(f"{verb} {fmt_duration(monotonic() - self._t_start)}"), "system")
        self._save_session()

    #actions

    def report_key(self, event: events.Key) -> None:
        self.add_note(f"key: {event.key}   character: {event.character!r}")

    def action_cancel(self) -> None:
        if self.key_debug:
            self.key_debug = False
            self.add_note("key debug off")
            return
        if self.mode == PICK:
            self._close_picker()
            self.add_note("cancelled")
            return
        if self.mode == ENTER_KEY:
            self.mode = NORMAL
            self._set_key_entry(False)
            self._pending_provider = None
            self._pending_key = None
            self.add_note("cancelled")
            return
        if self.mode == ENTER_URL:
            self.mode = NORMAL
            self.input.set_text("")
            self._pending_provider = None
            self.add_note("cancelled")
            return
        # While a command is running, esc stops just that command; the agent
        # carries on with the result. Press esc again to abort the whole task.
        if self._running_job is not None and self._cmd_control is None:
            self._cmd_control = "terminate"
            self.add_note("stopping command…")
            return
        # Abort the whole request first, then release any pending prompt so
        # the blocked worker unwinds and sees the bumped op.
        was_choice = self.mode == CHOICE
        self.mode = NORMAL
        if was_choice:
            self._hide_popup()
        if not self._busy:
            if was_choice and self._choice_event is not None:
                self._choice_event.set()
                self._choice_event = None
            return
        self._op += 1
        self.workers.cancel_group(self, "chat")
        self.workers.cancel_group(self, "net")
        if self._choice_event is not None:
            self._choice_result = ""
            self._choice_event.set()
            self._choice_event = None
        self._busy = False
        self._inflight = False
        self._pending_md = None
        self._stop_indicator()
        if self._stream_target is not None and not self._stream_text:
            self._stream_target.remove()
        self._stream_target = None
        self.add_note("cancelled")

    def action_background_command(self) -> None:
        if self._running_job is not None and self._cmd_control is None:
            self._cmd_control = "background"

    def action_copy(self) -> None:
        selected = self.screen.get_selected_text()
        if not selected:
            return
        if clipboard.copy(selected):
            self.add_note(f"copied {len(selected)} chars")
        else:
            self.copy_to_clipboard(selected)  # OSC 52 fallback
            self.add_note(f"copied {len(selected)} chars (via terminal)")

    def action_chat_up(self) -> None:
        self.chat.scroll_page_up(animate=False)

    def action_chat_down(self) -> None:
        self.chat.scroll_page_down(animate=False)

    # -- jump pills (shown while scrolled up) --

    def _update_jump_pills(self) -> None:
        try:
            chat = self.chat
        except Exception:
            return
        max_y = chat.max_scroll_y
        at_bottom = chat.scroll_y >= max_y - 0.5
        self._stick_bottom = at_bottom
        scrolled = (not at_bottom) and max_y > 0
        self.query_one("#overlay-bottom").display = scrolled

        target = self._prev_user_target() if scrolled else None
        top_bar = self.query_one("#overlay-top")
        if target is not None:
            _, text = target
            preview = " ".join(text.split())
            if len(preview) > 44:
                preview = preview[:43] + "…"
            self.query_one("#jump-prev", Static).update(f"↑ {preview}")
            top_bar.display = True
        else:
            top_bar.display = False

    def _prev_user_target(self):
        chat_top = self.chat.content_region.y
        above = [(w, t) for (w, t) in self._user_msgs if w.region.y < chat_top]
        if not above:
            return None
        return max(above, key=lambda wt: wt[0].region.y)

    def action_jump_bottom(self) -> None:
        self._stick_bottom = True
        self.chat.scroll_end(animate=True)
        self.call_after_refresh(self._update_jump_pills)

    def action_jump_prev(self) -> None:
        target = self._prev_user_target()
        if target is not None:
            self.chat.scroll_to_widget(target[0], top=True, animate=True)

    # keep the input sized to its content as the user types
    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self.input.autosize()
        self._update_cmd_preview()

    def _update_cmd_preview(self) -> None:
        try:
            preview = self.query_one("#cmdpreview", Static)
        except Exception:
            return
        text = self.input.text
        if self.mode != NORMAL or not text.startswith("/") or " " in text or "\n" in text:
            preview.display = False
            return
        matches = [c for c in COMMANDS if c[0].startswith(text.lower())]
        if not matches:
            preview.display = False
            return
        strong, muted = self.c("strong"), self.c("muted")
        t = Text()
        for i, (name, desc) in enumerate(matches):
            if i:
                t.append("\n")
            t.append(f"{name:<11}", style=f"bold {strong}")
            t.append(desc, style=muted)
        preview.update(t)
        preview.display = True

    def on_unmount(self) -> None:
        self._theme_gen += 1  # retires the theme watcher thread
        self._stop_theme_watch()
        # Save on the way out, and remember what to print so the user can
        # resume — the id is no longer shown at the top, only on exit.
        self._save_session()
        if self.messages:
            self.resume_id = self.session_id
        if self._shell is not None:
            self._shell.close()
