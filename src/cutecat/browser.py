from __future__ import annotations

import html as html_mod
import os
import re
import shutil
import subprocess
import sys
import tempfile

DEFAULT_TIMEOUT = 60
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 900
DEFAULT_WAIT_MS = 5000

_BINARIES = (
    "chromium", "chromium-browser", "chrome", "google-chrome",
    "google-chrome-stable", "brave-browser", "microsoft-edge",
)

# Where the browsers hide when they aren't on PATH.
_MAC_PATHS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)
_WIN_PATHS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Chromium\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
)

INSTALL_HINT = (
    "no Chrome/Chromium found. Install one (Fedora: sudo dnf install chromium · "
    "Debian/Ubuntu: sudo apt install chromium · macOS: brew install --cask chromium · "
    "Windows: winget install Google.Chrome), or set \"chromium\" in "
    "~/.cutecat/config.json to the browser's full path."
)


class BrowserError(Exception):
    """No browser, or the browser failed."""


def find_browser(configured: str | None = None) -> str | None:
    """The browser to drive: the configured one, else whatever is installed."""
    if configured:
        configured = configured.strip()
        if os.path.isfile(configured) or shutil.which(configured):
            return configured
        raise BrowserError(f'"chromium" in your config is not a browser: {configured}')
    for name in _BINARIES:
        found = shutil.which(name)
        if found:
            return found
    candidates = _MAC_PATHS if sys.platform == "darwin" else (
        _WIN_PATHS if os.name == "nt" else ()
    )
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _run(browser: str, url: str, extra: list[str], timeout: int) -> subprocess.CompletedProcess:
    # private profile dir, so headless starts even with the browser already open
    with tempfile.TemporaryDirectory(
        prefix="cutecat-browser-", ignore_cleanup_errors=True
    ) as profile:
        argv = [
            browser,
            "--headless",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            f"--user-data-dir={profile}",
            *extra,
            url,
        ]
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, errors="replace", timeout=timeout
            )
        except FileNotFoundError as exc:
            raise BrowserError(f"could not run {browser}: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise BrowserError(f"the page took longer than {timeout}s to load") from exc
        # Chrome's sandbox can't start as root or in some containers; that is
        # the one failure worth retrying, with the sandbox off.
        blob = (proc.stderr or "") + (proc.stdout or "")
        if proc.returncode != 0 and re.search(r"sandbox|namespace", blob, re.I):
            proc = subprocess.run(
                [argv[0], "--no-sandbox", *argv[1:]],
                capture_output=True, text=True, errors="replace", timeout=timeout,
            )
        return proc


def fetch_html(browser: str, url: str, wait_ms: int = DEFAULT_WAIT_MS,
               timeout: int = DEFAULT_TIMEOUT) -> str:
    """The page's HTML *after* its JavaScript has run."""
    proc = _run(
        browser, url,
        [f"--virtual-time-budget={wait_ms}", "--dump-dom"],
        timeout,
    )
    if not proc.stdout.strip():
        raise BrowserError(
            f"the browser returned nothing for {url}"
            + (f": {proc.stderr.strip()[:200]}" if proc.stderr.strip() else "")
        )
    return proc.stdout


def capture(browser: str, url: str, out_path: str, *, pdf: bool = False,
            full_page: bool = False,
            width: int = DEFAULT_WIDTH, height: int = DEFAULT_HEIGHT,
            wait_ms: int = DEFAULT_WAIT_MS, timeout: int = DEFAULT_TIMEOUT) -> int:
    """Screenshot (PNG) or print (PDF) the page to out_path. Returns its size.

    A full-page screenshot goes through the DevTools protocol: Chrome's command
    line can only capture the viewport."""
    if full_page and not pdf:
        return _capture_full_page(
            browser, url, out_path, width=width, height=height,
            wait_ms=wait_ms, timeout=timeout,
        )
    flag = f"--print-to-pdf={out_path}" if pdf else f"--screenshot={out_path}"
    extra = [flag, f"--virtual-time-budget={wait_ms}"]
    if not pdf:
        extra.append(f"--window-size={width},{height}")
    proc = _run(browser, url, extra, timeout)
    if not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:200]
        raise BrowserError(f"the browser wrote no file{': ' + detail if detail else ''}")
    return os.path.getsize(out_path)


def _capture_full_page(browser: str, url: str, out_path: str, *, width: int,
                       height: int, wait_ms: int, timeout: int) -> int:
    from cutecat import cdp

    try:
        with cdp.Browser(browser, timeout=timeout) as chrome:
            png = chrome.screenshot(
                url, width=width, height=height, wait_ms=wait_ms, full_page=True
            )
    except cdp.CDPError as exc:
        raise BrowserError(f"full-page screenshot failed: {exc}") from exc
    except OSError as exc:
        raise BrowserError(f"full-page screenshot failed: {exc}") from exc
    with open(out_path, "wb") as fh:
        fh.write(png)
    return len(png)


#html -> text

_DROP = re.compile(r"<(script|style|noscript|template|svg)\b.*?</\1>", re.S | re.I)
_BREAKS = re.compile(r"</(p|div|li|tr|h[1-6]|section|article|header|footer|blockquote)>"
                     r"|<br\s*/?>", re.I)
_TAGS = re.compile(r"<[^>]+>")
_BLANKS = re.compile(r"\n{3,}")


def to_text(html: str) -> str:
    """A readable plain-text rendering of a page — no external dependency."""
    text = _DROP.sub(" ", html)
    text = _BREAKS.sub("\n", text)
    text = _TAGS.sub(" ", text)
    text = html_mod.unescape(text)
    lines = [re.sub(r"[ \t\xa0]+", " ", line).strip() for line in text.splitlines()]
    return _BLANKS.sub("\n\n", "\n".join(line for line in lines if line)).strip()
