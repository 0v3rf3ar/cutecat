from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading
import time

IS_WINDOWS = os.name == "nt"
CWD_MARK = "__CUTECAT_CWD__:"

NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

POSIX_SHELLS = ("bash", "zsh", "sh", "dash", "ksh", "mksh", "ash", "busybox")


def _posix_shell() -> str:
    env_shell = os.environ.get("SHELL") or ""
    if (
        env_shell
        and os.path.basename(env_shell) in POSIX_SHELLS
        and os.path.exists(env_shell)
    ):
        return env_shell
    for candidate in ("/bin/bash", "/usr/bin/bash", "/bin/sh"):
        if os.path.exists(candidate):
            return candidate
    return shutil.which("bash") or shutil.which("sh") or "/bin/sh"


def _windows_shell() -> tuple[str, str]:
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell:
        return ("powershell", powershell)
    return ("cmd", os.environ.get("COMSPEC") or "cmd.exe")


class Job:
    _next_id = 1

    def __init__(self, command: str):
        self.id = Job._next_id
        Job._next_id += 1
        self.command = command
        self.proc: subprocess.Popen | None = None
        self._chunks: list[str] = []
        self._lock = threading.Lock()
        self.exit_code: int | None = None
        self.finished = threading.Event()
        self.cwd_after: str | None = None
        self.backgrounded = False
        self.started = time.monotonic()
        self.last_output = self.started

    def _append(self, text: str) -> None:
        with self._lock:
            self._chunks.append(text)
            self.last_output = time.monotonic()

    @property
    def silent_for(self) -> float:
        """Seconds since it last said anything. A command can be busy and quiet
        (a compile) or hung and quiet — the caller decides, but it cannot
        decide without this."""
        return time.monotonic() - self.last_output

    @property
    def ran_for(self) -> float:
        return time.monotonic() - self.started

    def output(self) -> str:
        with self._lock:
            text = "".join(self._chunks)
        # Strip the trailing cwd marker line from what we show.
        idx = text.rfind("\n" + CWD_MARK)
        if idx != -1:
            text = text[:idx]
        elif text.startswith(CWD_MARK):
            text = ""
        return text.strip("\n")

    @property
    def running(self) -> bool:
        return not self.finished.is_set()


class CommandRunner:
    def __init__(self, cwd: str | None = None):
        self.cwd = cwd or os.getcwd()
        # The shell follows the operating system: PowerShell/cmd on Windows,
        # bash/sh everywhere else.
        if IS_WINDOWS:
            self.kind, self.exe = _windows_shell()
        else:
            self.kind, self.exe = "posix", _posix_shell()
        self.env = dict(os.environ)
        if IS_WINDOWS:
            # There is no `cat` in a bare cmd.exe; an empty pager means "don't
            # page", which is what we actually want.
            self.env["GIT_PAGER"] = ""
            self.env["PAGER"] = ""
        else:
            self.env.setdefault("PAGER", "cat")
            self.env["GIT_PAGER"] = "cat"

    @property
    def name(self) -> str:
        return {"posix": "bash", "cmd": "cmd.exe", "powershell": "PowerShell"}[self.kind]

    # ------------------------------------------------------------ running

    def _argv(self, command: str) -> tuple[list[str], dict]:
        if self.kind == "cmd":  # pragma: no cover - Windows only
            wrapped = (
                f"{command}\r\nset __rc=%errorlevel%\r\n"
                f"echo {CWD_MARK}%CD%\r\nexit /b %__rc%"
            )
            return (
                [self.exe, "/c", wrapped],
                dict(creationflags=NEW_PROCESS_GROUP),
            )
        if self.kind == "powershell":  # pragma: no cover - Windows only
            # $LASTEXITCODE is only set by native executables; for cmdlets we
            # fall back to $? (True/False). It starts out $null in a fresh -Command.
            wrapped = (
                f"{command}\n"
                "$__rc = if ($null -ne $LASTEXITCODE) { $LASTEXITCODE }"
                " elseif ($?) { 0 } else { 1 }\n"
                f'Write-Output "{CWD_MARK}$((Get-Location).Path)"\n'
                "exit $__rc"
            )
            return (
                [self.exe, "-NoProfile", "-NonInteractive", "-Command", wrapped],
                dict(creationflags=NEW_PROCESS_GROUP),
            )
        wrapped = (
            f"{command}\n__rc=$?\n"
            f"printf '\\n{CWD_MARK}%s\\n' \"$PWD\"\nexit $__rc"
        )
        return ([self.exe, "-c", wrapped], dict(start_new_session=True))

    def run(self, command: str) -> Job:
        job = Job(command)
        argv, kwargs = self._argv(command)

        job.proc = subprocess.Popen(
            argv,
            cwd=self.cwd if os.path.isdir(self.cwd) else None,
            env=self.env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            text=True,
            encoding="utf-8",
            errors="replace",  # non-UTF-8 bytes become �, never crash
            **kwargs,
        )
        threading.Thread(target=self._pump, args=(job,), daemon=True).start()
        return job

    def _pump(self, job: Job) -> None:
        assert job.proc is not None
        try:
            for line in job.proc.stdout:  # type: ignore[union-attr]
                if line.startswith(CWD_MARK):
                    job.cwd_after = line[len(CWD_MARK):].strip() or job.cwd_after
                    continue
                job._append(line)
        except Exception:
            pass
        finally:
            job.proc.wait()
            job.exit_code = job.proc.returncode
            job.finished.set()

    #control

    def wait(self, job: Job, poll: float = 0.15) -> bool:
        return job.finished.wait(poll)

    def terminate(self, job: Job) -> None:
        proc = job.proc
        if proc is None or job.finished.is_set():
            return

        def kill_group(sig: int):
            return lambda: os.killpg(os.getpgid(proc.pid), sig)

        if IS_WINDOWS:  # pragma: no cover - Windows only
            steps = [
                lambda: proc.send_signal(signal.CTRL_BREAK_EVENT),
                proc.terminate,  # TerminateProcess
                proc.kill,
            ]
        else:
            steps = [
                kill_group(signal.SIGINT),
                kill_group(signal.SIGTERM),
                kill_group(signal.SIGKILL),
            ]
        for step in steps:
            if job.finished.wait(0):
                return
            try:
                step()
            except (ProcessLookupError, OSError, ValueError):
                return
            if job.finished.wait(1.0):
                return

    def adopt_cwd(self, job: Job) -> None:
        if job.cwd_after and os.path.isdir(job.cwd_after):
            self.cwd = job.cwd_after

    def close(self) -> None:
        pass


def shell_kind() -> str:
    return _windows_shell()[0] if IS_WINDOWS else "posix"


def create_shell(cwd: str | None = None) -> CommandRunner:
    return CommandRunner(cwd)
