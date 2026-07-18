from __future__ import annotations

import os
import shutil
import subprocess
import sys


UTF8 = "utf-8"
# clip.exe mangles UTF-8; it wants UTF-16LE with a BOM
UTF16 = "utf-16-le-bom"


def _encode(text: str, encoding: str) -> bytes:
    if encoding == UTF16:
        return b"\xff\xfe" + text.encode("utf-16-le")
    return text.encode(UTF8)


def _candidates() -> list[tuple[list[str], str]]:
    """(command, encoding) pairs to try, best first."""
    if sys.platform == "darwin":
        return [(["pbcopy"], UTF8)]
    if os.name == "nt":
        return [
            (["clip"], UTF16),
            (["powershell", "-NoProfile", "-Command",
              "Set-Clipboard -Value ([Console]::In.ReadToEnd())"], UTF8),
        ]
    cmds: list[tuple[list[str], str]] = []
    if os.environ.get("WAYLAND_DISPLAY"):
        cmds.append((["wl-copy"], UTF8))
    cmds.append((["xclip", "-selection", "clipboard"], UTF8))
    cmds.append((["xsel", "--clipboard", "--input"], UTF8))
    cmds.append((["wl-copy"], UTF8))  # last resort without WAYLAND_DISPLAY set
    return cmds


def copy(text: str) -> bool:
    for cmd, encoding in _candidates():
        if not shutil.which(cmd[0]):
            continue
        try:
            subprocess.run(
                cmd, input=_encode(text, encoding), check=True, timeout=5,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return True
        except (subprocess.SubprocessError, OSError):
            continue
    return False
