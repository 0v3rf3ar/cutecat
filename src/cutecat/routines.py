from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from cutecat import config as config_mod

PRESETS = {
    #                min hour dom mon dow
    "hourly":   "0 * * * *",
    "daily":    "0 9 * * *",
    "weekdays": "0 9 * * 1-5",
    "weekly":   "0 9 * * 1",
}

PERMISSIONS = ("safe", "auto")


class RoutineError(Exception):
    ...


def routines_file():
    return config_mod.CUTECAT_DIR / "routines.jsonl"


#cron


def parse_cron(expr: str) -> list[set[int]]:
    bounds = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
    fields = (expr or "").split()
    if len(fields) != 5:
        raise RoutineError(
            f"a cron expression has 5 fields (min hour day month weekday): {expr!r}"
        )
    parsed: list[set[int]] = []
    for field, (low, high) in zip(fields, bounds):
        allowed: set[int] = set()
        for part in field.split(","):
            step = 1
            if "/" in part:
                part, _, raw_step = part.partition("/")
                if not raw_step.isdigit() or int(raw_step) < 1:
                    raise RoutineError(f"bad step in cron field: {field!r}")
                step = int(raw_step)
            if part in ("*", ""):
                start, end = low, high
            elif "-" in part:
                a, _, b = part.partition("-")
                if not (a.isdigit() and b.isdigit()):
                    raise RoutineError(f"bad range in cron field: {field!r}")
                start, end = int(a), int(b)
            elif part.isdigit():
                start = end = int(part)
            else:
                raise RoutineError(f"bad cron field: {field!r}")
            if start < low or end > high or start > end:
                raise RoutineError(f"cron field out of range ({low}-{high}): {field!r}")
            allowed.update(range(start, end + 1, step))
        if not allowed:
            raise RoutineError(f"cron field matches nothing: {field!r}")
        parsed.append(allowed)
    return parsed


def cron_matches(expr: str, when: datetime) -> bool:
    minute, hour, dom, month, dow = parse_cron(expr)
    # cron's weekday: 0 = Sunday; python's: 0 = Monday
    weekday = (when.weekday() + 1) % 7
    return (
        when.minute in minute
        and when.hour in hour
        and when.day in dom
        and when.month in month
        and weekday in dow
    )


def next_run(expr: str, after: datetime | None = None) -> datetime | None:
    start = (after or datetime.now()).replace(second=0, microsecond=0)
    when = start + timedelta(minutes=1)
    for _ in range(366 * 24 * 60):
        if cron_matches(expr, when):
            return when
        when += timedelta(minutes=1)
    return None


def describe(routine: dict) -> str:
    if not routine.get("enabled", True):
        return "paused"
    once = routine.get("once_at")
    if once:
        if routine.get("last_run"):
            return f"ran once at {once[:16].replace('T', ' ')}"
        return f"once at {once[:16].replace('T', ' ')}"
    cron = routine.get("cron")
    if not cron:
        return "manual only"
    upcoming = next_run(cron)
    for name, preset in PRESETS.items():
        if preset == cron:
            return f"{name} (next {upcoming:%a %H:%M})" if upcoming else name
    return f"{cron} (next {upcoming:%a %d %b %H:%M})" if upcoming else cron


#storage


def load() -> list[dict]:
    path = routines_file()
    if not path.exists():
        return []
    try:
        raw = config_mod.read_text(path)
    except OSError:
        return []
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("id"):
            out.append(item)
    return out


def save(routines: list[dict]) -> None:
    config_mod.ensure_dirs()
    body = "\n".join(
        json.dumps(r, separators=(",", ":"), ensure_ascii=False) for r in routines
    )
    config_mod.write_text(routines_file(), body + ("\n" if body else ""))


def find(name_or_id: str) -> dict | None:
    needle = (name_or_id or "").strip().lower()
    if not needle:
        return None
    items = load()
    for r in items:
        if r.get("name", "").lower() == needle:
            return r
    matches = [r for r in items if r["id"].startswith(needle)]
    return matches[0] if len(matches) == 1 else None


def create(name: str, prompt: str, *, cron: str | None = None,
           once_at: str | None = None, cwd: str | None = None,
           permissions: str = "safe", model: str | None = None,
           provider: str | None = None) -> dict:
    import os

    name = (name or "").strip()
    prompt = (prompt or "").strip()
    if not name:
        raise RoutineError("a routine needs a name")
    if not prompt:
        raise RoutineError("a routine needs a prompt — what should it do?")
    if find(name):
        raise RoutineError(f"a routine named {name!r} already exists")
    if permissions not in PERMISSIONS:
        raise RoutineError(f"permissions must be one of {', '.join(PERMISSIONS)}")
    if cron:
        cron = PRESETS.get(cron.strip().lower(), cron.strip())
        parse_cron(cron)  # raises on nonsense
    routine = {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "prompt": prompt,
        "cwd": cwd or os.getcwd(),
        "cron": cron,
        "once_at": once_at,
        "enabled": True,
        "permissions": permissions,
        "provider": provider,
        "model": model,
        "created": config_mod.now_iso(),
        "last_run": None,
        "last_status": None,
        "last_session": None,
        "runs": 0,
    }
    items = load()
    items.append(routine)
    save(items)
    return routine


def update(routine: dict) -> None:
    items = [r if r["id"] != routine["id"] else routine for r in load()]
    save(items)


def remove(name_or_id: str) -> dict:
    routine = find(name_or_id)
    if routine is None:
        raise RoutineError(f"no routine matching {name_or_id!r}")
    save([r for r in load() if r["id"] != routine["id"]])
    return routine


def set_enabled(name_or_id: str, enabled: bool) -> dict:
    routine = find(name_or_id)
    if routine is None:
        raise RoutineError(f"no routine matching {name_or_id!r}")
    routine["enabled"] = enabled
    update(routine)
    return routine


#due


def is_due(routine: dict, when: datetime, last_tick: datetime | None = None) -> bool:
    if not routine.get("enabled", True):
        return False
    once = routine.get("once_at")
    if once:
        if routine.get("last_run"):
            return False  # a one-off fires exactly once
        try:
            due_at = datetime.fromisoformat(once)
        except ValueError:
            return False
        return when >= due_at
    cron = routine.get("cron")
    if not cron:
        return False  # manual-only
    minute = when.replace(second=0, microsecond=0)
    if last_tick is None:
        return cron_matches(cron, minute)
    cursor = max(
        last_tick.replace(second=0, microsecond=0) + timedelta(minutes=1),
        minute - timedelta(days=1),
    )
    while cursor <= minute:
        if cron_matches(cron, cursor):
            return True
        cursor += timedelta(minutes=1)
    return False


def due_now(when: datetime | None = None,
            last_tick: datetime | None = None) -> list[dict]:
    when = when or datetime.now()
    return [r for r in load() if is_due(r, when, last_tick)]


#scheduling

TASK_NAME = "cutecat-routines"


def cutecat_argv() -> list[str]:
    import shutil
    import sys

    exe = shutil.which("cutecat")
    if exe:
        return [exe]
    return [sys.executable or "python3", "-m", "cutecat"]


# characters that never need quoting in a shell, a systemd line, or a task
_BARE = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./:-@%+=,"
)


def _shell_command(argv: list[str]) -> str:
    import shlex

    return " ".join(shlex.quote(part) for part in argv)


def _win_command(argv: list[str]) -> str:
    return " ".join(
        p if p and all(c in _BARE for c in p) else '"' + p.replace('"', '""') + '"'
        for p in argv
    )


def _systemd_exec(argv: list[str]) -> str:
    out = []
    for part in argv:
        if part and all(c in _BARE for c in part):
            out.append(part)
        else:
            esc = part.replace("\\", "\\\\").replace('"', '\\"').replace("$", "$$")
            out.append(f'"{esc}"')
    return " ".join(out)


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _has_systemd() -> bool:
    return bool(shutil_which("systemctl")) and Path("/run/systemd/system").is_dir()


def launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "ai.cutecat.routines.plist"


def launch_agent_plist(argv: list[str]) -> str:
    """A launchd agent that runs `<argv> routines tick` every minute."""
    args = "".join(
        f"        <string>{_xml_escape(part)}</string>\n"
        for part in (argv + ["routines", "tick"])
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "  <dict>\n"
        "    <key>Label</key><string>ai.cutecat.routines</string>\n"
        "    <key>ProgramArguments</key>\n"
        "    <array>\n"
        f"{args}"
        "    </array>\n"
        "    <key>StartInterval</key><integer>60</integer>\n"
        "    <key>RunAtLoad</key><false/>\n"
        "  </dict>\n"
        "</plist>\n"
    )


def scheduler(platform: str | None = None, *, systemd: bool | None = None) -> dict:
    import sys

    platform = platform or ("nt" if os.name == "nt" else sys.platform)
    argv = cutecat_argv() + ["routines", "tick"]

    if platform in ("nt", "win32"):
        return {
            "kind": "schtasks",
            "name": "the Windows Task Scheduler",
            "install": [
                "schtasks", "/Create", "/F", "/SC", "MINUTE", "/MO", "1",
                "/TN", TASK_NAME, "/TR", _win_command(argv),
            ],
            "uninstall": ["schtasks", "/Delete", "/F", "/TN", TASK_NAME],
        }
    if platform == "darwin":
        return {
            "kind": "launchd",
            "name": "launchd",
            "plist": str(launch_agent_path()),
            "install": ["launchctl", "load", "-w", str(launch_agent_path())],
            "uninstall": ["launchctl", "unload", "-w", str(launch_agent_path())],
        }
    if platform.startswith("linux"):
        use_systemd = _has_systemd() if systemd is None else systemd
        if use_systemd:
            return {
                "kind": "systemd",
                "name": "a systemd user timer",
                "unit": f"{TASK_NAME}.timer",
                "service": str(_systemd_dir() / f"{TASK_NAME}.service"),
                "timer": str(_systemd_dir() / f"{TASK_NAME}.timer"),
            }
    return {
        "kind": "cron",
        "name": "cron",
        "line": f"* * * * * {_shell_command(argv)}",
        "install": None,      # we edit the crontab ourselves
        "uninstall": None,
    }


def _crontab(lines: list[str] | None = None) -> list[str]:
    """Read (or write) the user's crontab."""
    import subprocess

    if lines is None:
        try:
            out = subprocess.run(
                ["crontab", "-l"], capture_output=True, text=True,
                errors="replace", timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RoutineError(f"could not read your crontab: {exc}") from exc
        if out.returncode != 0 and "no crontab" not in (out.stderr or "").lower():
            raise RoutineError(out.stderr.strip() or "could not read your crontab")
        return (out.stdout or "").splitlines()
    body = "\n".join(lines).strip() + "\n"
    try:
        done = subprocess.run(
            ["crontab", "-"], input=body, text=True, capture_output=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RoutineError(f"could not write your crontab: {exc}") from exc
    if done.returncode != 0:
        raise RoutineError(done.stderr.strip() or "could not write your crontab")
    return lines


def _install_systemd_timer() -> str:
    import subprocess

    exec_line = _systemd_exec(cutecat_argv() + ["routines", "tick"])
    unit_dir = _systemd_dir()
    try:
        unit_dir.mkdir(parents=True, exist_ok=True)
        (unit_dir / f"{TASK_NAME}.service").write_text(
            "[Unit]\n"
            "Description=cutecat routines\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            f"ExecStart={exec_line}\n",
            encoding="utf-8",
        )
        (unit_dir / f"{TASK_NAME}.timer").write_text(
            "[Unit]\n"
            "Description=run cutecat routines every minute\n\n"
            "[Timer]\n"
            "OnCalendar=minutely\n"
            "Persistent=true\n\n"
            "[Install]\n"
            "WantedBy=timers.target\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise RoutineError(f"could not write the systemd units: {exc}") from exc

    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    done = subprocess.run(
        ["systemctl", "--user", "enable", "--now", f"{TASK_NAME}.timer"],
        capture_output=True, text=True, errors="replace", timeout=30,
    )
    if done.returncode != 0:
        raise RoutineError(done.stderr.strip() or "systemctl refused the timer")
    return (
        f"installed a systemd user timer ({TASK_NAME}.timer), ticking every minute.\n"
        f"  status: systemctl --user list-timers {TASK_NAME}.timer\n"
        "  tip:    run 'loginctl enable-linger $USER' so it ticks with no session"
    )


def install_scheduler() -> str:
    import subprocess

    spec = scheduler()
    if spec["kind"] == "cron":
        lines = [ln for ln in _crontab() if TASK_NAME not in ln]
        lines.append(f"{spec['line']}  # {TASK_NAME}")
        _crontab(lines)
        return f"added a cron entry: {spec['line']}"

    if spec["kind"] == "systemd":
        return _install_systemd_timer()

    if spec["kind"] == "launchd":
        path = launch_agent_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(launch_agent_plist(cutecat_argv()), encoding="utf-8")
        except OSError as exc:
            raise RoutineError(f"could not write {path}: {exc}") from exc
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True)

    try:
        done = subprocess.run(spec["install"], capture_output=True, text=True,
                              errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RoutineError(f"could not set up {spec['name']}: {exc}") from exc
    if done.returncode != 0:
        raise RoutineError(
            (done.stderr or done.stdout or "").strip()
            or f"{spec['name']} refused the job"
        )
    return f"installed into {spec['name']}"


def uninstall_scheduler() -> str:
    import subprocess

    spec = scheduler()
    if spec["kind"] == "cron":
        lines = [ln for ln in _crontab() if TASK_NAME not in ln]
        _crontab(lines)
        return "removed the cron entry"
    if spec["kind"] == "systemd":
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", spec["unit"]],
            capture_output=True,
        )
        Path(spec["timer"]).unlink(missing_ok=True)
        Path(spec["service"]).unlink(missing_ok=True)
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        return "removed the systemd user timer"
    try:
        subprocess.run(spec["uninstall"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RoutineError(f"could not remove it from {spec['name']}: {exc}") from exc
    if spec["kind"] == "launchd":
        launch_agent_path().unlink(missing_ok=True)
    return f"removed from {spec['name']}"


#services

def _systemd_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def install_service(name: str, args: str) -> str:
    import subprocess
    import sys

    plat = "nt" if os.name == "nt" else sys.platform
    argv = cutecat_argv() + args.split()
    unit = f"cutecat-{name}"

    if plat.startswith("linux") and shutil_which("systemctl"):
        path = _systemd_dir() / f"{unit}.service"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "[Unit]\n"
            f"Description=cutecat {name}\n"
            "After=network-online.target\n\n"
            "[Service]\n"
            f"ExecStart={_systemd_exec(argv)}\n"
            "Restart=always\n"
            "RestartSec=5\n\n"
            "[Install]\n"
            "WantedBy=default.target\n",
            encoding="utf-8",
        )
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        done = subprocess.run(
            ["systemctl", "--user", "enable", "--now", unit],
            capture_output=True, text=True,
        )
        if done.returncode != 0:
            raise RoutineError(done.stderr.strip() or "systemctl refused the service")
        return (f"installed {unit} (systemd --user). It starts now and at login.\n"
                "  logs:   journalctl --user -u " + unit + " -f\n"
                "  tip:    run 'loginctl enable-linger $USER' so it runs with no session")

    if plat == "darwin":
        path = Path.home() / "Library" / "LaunchAgents" / f"ai.cutecat.{name}.plist"
        path.parent.mkdir(parents=True, exist_ok=True)
        prog = "".join(f"      <string>{_xml_escape(p)}</string>\n" for p in argv)
        path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict>\n'
            f"  <key>Label</key><string>ai.cutecat.{name}</string>\n"
            "  <key>ProgramArguments</key><array>\n" + prog + "  </array>\n"
            "  <key>KeepAlive</key><true/>\n"
            "  <key>RunAtLoad</key><true/>\n"
            "</dict></plist>\n",
            encoding="utf-8",
        )
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
        subprocess.run(["launchctl", "load", "-w", str(path)], capture_output=True)
        return f"installed {path} (launchd). It starts now and at login."

    raise RoutineError(
        "no supported service manager here. Run it under your own supervisor:\n"
        f"  {_shell_command(argv)}"
    )


def uninstall_service(name: str) -> str:
    import subprocess
    import sys

    plat = "nt" if os.name == "nt" else sys.platform
    unit = f"cutecat-{name}"
    if plat.startswith("linux") and shutil_which("systemctl"):
        subprocess.run(["systemctl", "--user", "disable", "--now", unit],
                       capture_output=True)
        (_systemd_dir() / f"{unit}.service").unlink(missing_ok=True)
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        return f"removed {unit}"
    if plat == "darwin":
        path = Path.home() / "Library" / "LaunchAgents" / f"ai.cutecat.{name}.plist"
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
        path.unlink(missing_ok=True)
        return f"removed ai.cutecat.{name}"
    raise RoutineError("nothing installed by cutecat to remove here")


def shutil_which(cmd: str) -> str | None:
    import shutil
    return shutil.which(cmd)


def record_run(routine: dict, status: str, session_id: str | None) -> None:
    routine["last_run"] = config_mod.now_iso()
    routine["last_status"] = status
    routine["last_session"] = session_id
    routine["runs"] = int(routine.get("runs") or 0) + 1
    if routine.get("once_at"):
        routine["enabled"] = False  # fired; don't fire again
    update(routine)


def summary(routine: dict) -> dict[str, Any]:
    return {
        "id": routine["id"],
        "name": routine["name"],
        "when": describe(routine),
        "permissions": routine.get("permissions", "safe"),
        "last": (routine.get("last_status") or "never run"),
    }
