from __future__ import annotations

from datetime import datetime
from typing import Callable

from cutecat import agent as agent_mod
from cutecat import config as config_mod
from cutecat import routines as routines_mod
from cutecat import tools as tools_mod
from cutecat.providers import get_provider
from cutecat.providers.base import ProviderError
from cutecat.shell import create_shell, shell_kind
from cutecat.tools import ToolContext

MAX_STEPS = 25


class HeadlessRun:

    def __init__(self, cwd: str, permissions: str = "safe",
                 log: Callable[[str], None] = lambda _m: None):
        self.cwd = cwd
        self.permissions = permissions if permissions in routines_mod.PERMISSIONS else "safe"
        self.log = log
        self.messages: list[dict] = []
        self.denied: list[str] = []

    # -- the permission model, with no human to ask

    def _allow(self, what: str) -> bool:
        if self.permissions == "auto":
            self.log(f"  allow (auto): {what}")
            return True
        self.denied.append(what)
        self.log(f"  REFUSED (safe mode): {what}")
        return False

    def _run_job(self, command: str) -> str:
        """run_command already asked _allow for anything that writes; a
        read-only command gets here directly."""
        self.log(f"  $ {command}")
        job = self.shell.run(command)
        job.finished.wait(timeout=900)  # 15 minutes is plenty, and never forever
        if job.running:
            self.shell.terminate(job)
            job.finished.wait(10)
            return "error: the command was still running after 15 minutes and was stopped"
        self.shell.adopt_cwd(job)
        return tools_mod.format_job_result(command, job.exit_code, job.output())

    def context(self, chromium: str | None) -> ToolContext:
        return ToolContext(
            shell=self.shell,
            ask_permission=lambda title, detail: self._allow(f"{title} ({detail})"),
            ask_tmp=lambda: self._allow("use the temp directory"),
            note=lambda text: self.log(f"  {text}"),
            is_cancelled=lambda: False,
            run_job=self._run_job,
            show_diff=None,
            ask_edit=lambda title, detail: self._allow(f"{title} ({detail})"),
            chromium=chromium,
        )

    # -- the loop

    def run(self, prompt: str, *, provider, key: str, model: str,
            system: str) -> str:
        """Drive the agent to completion. Returns its final answer. Runs on the
        shared agent core, logging each event instead of drawing it."""
        self.shell = create_shell(self.cwd)
        self.messages = [{"role": "user", "content": prompt}]
        ctx = self.context(config_mod.load_config().get("chromium"))
        answer = ""
        try:
            for event in agent_mod.run_agent(
                provider, key, model, system, self.messages, ctx,
                max_steps=MAX_STEPS,
            ):
                if isinstance(event, agent_mod.ToolStarted):
                    self.log(f"  → {event.name}")
                elif isinstance(event, agent_mod.ToolsDisabled):
                    self.log(f"  {event.reason}")
                elif isinstance(event, agent_mod.Done):
                    answer = event.answer
                    if answer.strip():
                        self.log(answer.strip())
                elif isinstance(event, agent_mod.Failed):
                    self.log(f"  {event.message}")
                    raise ProviderError(event.message)
            return answer
        finally:
            self.shell.close()


def build_system_prompt(cfg: dict, permissions: str) -> str:
    from cutecat.app import BUILD_DIRECTIVE, SHELL_DIRECTIVES

    parts = [config_mod.system_prompt()]
    enabled = cfg.get("skills") or {}
    for name in config_mod.list_skills():
        if enabled.get(name):
            body = config_mod.read_skill(name)
            if body:
                parts.append(f"## skill: {name}\n\n{body}")
    parts.append(SHELL_DIRECTIVES[shell_kind()])
    parts.append(BUILD_DIRECTIVE)
    if permissions == "auto":
        parts.append(
            "# routine\n\nYou are running as an unattended routine. Nobody is "
            "watching, so never ask a question or wait for input: decide, act, "
            "and finish the task. State clearly at the end what you did."
        )
    else:
        parts.append(
            "# routine\n\nYou are running as an unattended routine in SAFE mode. "
            "Nobody is watching, so never ask a question or wait for input. You "
            "may run read-only commands and read files, but anything that "
            "changes the system (editing or creating files, writing commands) "
            "will be refused. Investigate and report; do not try to change "
            "things. State your findings at the end."
        )
    return "\n\n".join(parts)


def run_routine(routine: dict, text: str | None = None,
                log: Callable[[str], None] = lambda _m: None) -> tuple[str, str | None]:
    cfg = config_mod.load_config()
    provider_id = routine.get("provider") or cfg.get("provider")
    model = routine.get("model") or cfg.get("model")
    provider = get_provider(provider_id) if provider_id else None
    key = config_mod.get_api_key(cfg, provider_id) if provider_id else None
    if provider is None or not key or not model:
        raise routines_mod.RoutineError(
            "not connected — run cutecat and use /connect before scheduling routines"
        )

    prompt = routine["prompt"]
    if text:
        prompt = f"{prompt}\n\n## context for this run\n\n{text}"

    permissions = routine.get("permissions", "safe")
    started = datetime.now()
    log(f"routine {routine['name']} · {provider_id} · {model} · {permissions} mode")
    run = HeadlessRun(routine.get("cwd") or ".", permissions, log)
    session_id = config_mod.new_session_id()
    try:
        run.run(
            prompt,
            provider=provider,
            key=key,
            model=model,
            system=build_system_prompt(cfg, permissions),
        )
        status = "ok"
    except ProviderError as exc:
        log(f"  failed: {exc}")
        status = f"failed: {exc}"
    except Exception as exc:  # never let a routine take the process down
        log(f"  failed: {exc}")
        status = f"failed: {exc.__class__.__name__}: {exc}"

    config_mod.save_session(
        {
            "id": session_id,
            "created": started.astimezone().isoformat(timespec="seconds"),
            "title": f"routine: {routine['name']}",
            "provider": provider_id,
            "model": model,
            "messages": run.messages,
            "input_history": [],
        }
    )
    if run.denied:
        status = f"{status} · {len(run.denied)} action(s) refused in safe mode"
    routines_mod.record_run(routine, status, session_id)
    took = (datetime.now() - started).seconds
    log(f"  {status} · {took}s · session {session_id[:8]}")
    return status, session_id
