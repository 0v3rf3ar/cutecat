import argparse
import sys

from cutecat import __version__


def cat_banner(caption: str, eyes: str = "^ ^", mouth: str = "w") -> str:
    return (
        "   /\\_/\\\n"
        "  ( " + eyes + " )   " + caption + "\n"
        "   > " + mouth + " <"
    )


_SUBCOMMANDS = ("routines", "skill", "discord", "sessions")
_TOP_OPTIONS = (
    "--resume", "--continue", "-c", "--encrypt", "--decrypt",
    "--version", "-v", "--help", "-h",
)


def _closest(token: str, candidates) -> str | None:
    import difflib

    matches = difflib.get_close_matches(token, list(candidates), n=1, cutoff=0.6)
    return matches[0] if matches else None


def _unknown(token: str, kind: str, candidates, help_hint: str) -> "SystemExit":
    """SystemExit for an unrecognised token, suggesting the closest match."""
    guess = _closest(token, candidates)
    did = f"  did you mean '{guess}'?\n" if guess else ""
    return SystemExit(f"cutecat: unknown {kind} '{token}'\n{did}  {help_hint}")


def _ask_passphrase(prompt: str = "passphrase: ") -> str:
    """Read a passphrase without echoing it (never from a pipe: an encryption
    passphrase typed into a script's stdin would end up in shell history)."""
    import getpass

    try:
        return getpass.getpass(prompt)
    except (EOFError, KeyboardInterrupt):
        raise SystemExit("\ncutecat: cancelled") from None


def _encrypt_command() -> None:
    """`cutecat --encrypt` — AES-256 your settings and chats behind a passphrase."""
    from cutecat import config as config_mod, crypto

    config_mod.ensure_dirs()
    if crypto.is_encrypted():
        raise SystemExit(
        )
    passphrase = _ask_passphrase("new passphrase: ")
    if len(passphrase) < 8:
        raise SystemExit("cutecat: use a passphrase of at least 8 characters")
    if passphrase != _ask_passphrase("repeat passphrase: "):
        raise SystemExit("cutecat: the passphrases did not match")
    try:
        count, legacy = crypto.enable(passphrase)
    except crypto.CryptoError as exc:
        raise SystemExit(f"cutecat: {exc}") from None
    print(f"encrypted {count} file(s) with AES-256-GCM: your settings and chats")
    if legacy is not None:
        print(f"destroyed a stale plaintext copy of your api key at {legacy}")
    print("cutecat will ask for this passphrase at startup. There is no recovery")
    print("if you lose it — nothing but the passphrase can open these files.")


def _decrypt_command() -> None:
    from cutecat import config as config_mod, crypto

    config_mod.ensure_dirs()
    if not crypto.is_encrypted():
        raise SystemExit("cutecat: not encrypted — nothing to do")
    try:
        count = crypto.disable(_ask_passphrase())
    except crypto.CryptoError as exc:
        raise SystemExit(f"cutecat: {exc}") from None
    print(f"decrypted {count} file(s) — settings and chats are plain text again")


def _unlock_or_exit() -> None:
    from cutecat import crypto

    if not crypto.is_encrypted() or crypto.is_unlocked():
        return
    for attempt in range(3):
        try:
            crypto.unlock(_ask_passphrase())
            return
        except crypto.CryptoError as exc:
            left = 2 - attempt
            print(f"cutecat: {exc}" + (f" — {left} tries left" if left else ""))
    raise SystemExit("cutecat: locked")


ROUTINE_USAGE = """\
cutecat routines [option]

  --list                    show your routines and when they run next (default)
  --show   <name>           the full definition and its last run
  --add    <name> [options] create one (see below)
  --run    <name> [--text T]  run it right now, in this terminal
  --remove <name>           delete it
  --enable|--disable <name> resume or pause its schedule
  --serve                   stay running and fire routines when they're due
  --tick                    fire anything due right now, then exit
  --install                 let the OS run routines for you, even when cutecat
                            is closed (cron / launchd / Task Scheduler)
  --uninstall               undo that

--add options:
  --prompt "..."     what the routine should do          (required)
  --every PRESET     hourly | daily | weekdays | weekly
  --cron "M H D M W" a cron expression (minimum: hourly)
  --at "YYYY-MM-DD HH:MM"  run once, then auto-disable
  --dir PATH         working directory   (default: here)
  --allow-writes     let it edit files and run any command, unattended
                     (default: safe — read-only commands only)

examples:
  cutecat routines --add standup --prompt "summarise yesterday's git log" --every daily
  cutecat routines --add deps --prompt "check for outdated deps and open a PR" \\
      --cron "0 9 * * 1" --allow-writes
  cutecat routines --run standup --text "focus on the parser work"
"""


_ROUTINE_ACTIONS = {
    "list", "show", "add", "run", "rm", "remove", "delete",
    "enable", "disable", "tick", "install", "uninstall", "serve", "help",
}


def _routines_command(args: list[str]) -> None:
    from cutecat import headless, routines as routines_mod

    # flags are the interface; bare words still accepted so installed schedulers keep firing
    if args and args[0].startswith("--") and args[0][2:] in _ROUTINE_ACTIONS:
        args = [args[0][2:], *args[1:]]

    sub = args[0] if args else "list"
    rest = args[1:]

    def get(flag: str, default=None):
        return rest[rest.index(flag) + 1] if flag in rest and rest.index(flag) + 1 < len(rest) else default

    try:
        if sub in ("help", "-h", "--help"):
            print(ROUTINE_USAGE)

        elif sub == "list":
            items = routines_mod.load()
            if not items:
                print("no routines yet — cutecat routines --help")
                return
            width = max(len(r["name"]) for r in items)
            for r in items:
                s = routines_mod.summary(r)
                flag = "" if r.get("permissions") == "safe" else "  [writes]"
                print(f"{s['name']:<{width}}  {s['when']:<34} {s['last']}{flag}")

        elif sub == "show":
            routine = routines_mod.find(rest[0] if rest else "")
            if routine is None:
                raise routines_mod.RoutineError("no such routine")
            for key in ("name", "id", "cwd", "cron", "once_at", "permissions",
                        "enabled", "runs", "last_run", "last_status", "last_session"):
                if routine.get(key) is not None:
                    print(f"{key:<12} {routine[key]}")
            print(f"{'next':<12} {routines_mod.describe(routine)}")
            print(f"\n{routine['prompt']}")

        elif sub == "add":
            if not rest:
                raise routines_mod.RoutineError("a routine needs a name")
            routine = routines_mod.create(
                rest[0],
                get("--prompt") or "",
                cron=get("--every") or get("--cron"),
                once_at=_parse_when(get("--at")),
                cwd=get("--dir"),
                permissions="auto" if "--allow-writes" in rest else "safe",
            )
            print(f"created {routine['name']} — {routines_mod.describe(routine)}")
            if routine["permissions"] == "auto":
                print("  it may edit files and run any command, with no one to ask.")
            else:
                print("  safe mode: read-only commands only (--allow-writes to change)")
            if routine.get("cron") or routine.get("once_at"):
                print("  run 'cutecat routines --serve' (or 'cutecat routines --install')")
                print("  to actually fire it — nothing runs unless a scheduler is up.")

        elif sub == "run":
            routine = routines_mod.find(rest[0] if rest else "")
            if routine is None:
                raise routines_mod.RoutineError("no such routine")
            status, session = headless.run_routine(routine, get("--text"), log=print)
            if session:
                print(f"\nopen it with: cutecat --resume {session[:8]}")
            if status != "ok":
                raise SystemExit(1)

        elif sub in ("rm", "remove", "delete"):
            print(f"deleted {routines_mod.remove(rest[0] if rest else '')['name']}")

        elif sub in ("enable", "disable"):
            routine = routines_mod.set_enabled(
                rest[0] if rest else "", sub == "enable"
            )
            print(f"{routine['name']}: {routines_mod.describe(routine)}")

        elif sub == "tick":
            _fire_due(routines_mod, headless, None)

        elif sub == "install":
            spec = routines_mod.scheduler()
            print(routines_mod.install_scheduler())
            print(f"{spec['name']} will now run your routines every minute,")
            print("even when cutecat is closed. Undo with: cutecat routines --uninstall")

        elif sub == "uninstall":
            print(routines_mod.uninstall_scheduler())

        elif sub == "serve":
            _serve(routines_mod, headless)

        else:
            _opts = ("--list", "--show", "--add", "--run", "--remove",
                     "--enable", "--disable", "--serve", "--tick",
                     "--install", "--uninstall", "--help")
            token = sub if str(sub).startswith("-") else f"--{sub}"
            raise _unknown(token, "routines option", _opts,
                           "see cutecat routines --help")
    except routines_mod.RoutineError as exc:
        raise SystemExit(f"cutecat: {exc}") from None


def _parse_when(raw: str | None) -> str | None:
    """--at accepts "YYYY-MM-DD HH:MM" (or an ISO timestamp)."""
    from datetime import datetime

    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).isoformat(timespec="minutes")
        except ValueError:
            continue
    from cutecat import routines as routines_mod

    raise routines_mod.RoutineError(f'--at wants "YYYY-MM-DD HH:MM", got {raw!r}')


def _fire_due(routines_mod, headless, last_tick) -> int:
    from datetime import datetime

    due = routines_mod.due_now(datetime.now(), last_tick)
    for routine in due:
        print(f"[{datetime.now():%H:%M}] firing {routine['name']}")
        try:
            headless.run_routine(routine, log=print)
        except routines_mod.RoutineError as exc:
            print(f"  cutecat: {exc}")
    return len(due)


def _serve(routines_mod, headless) -> None:
    import time
    from datetime import datetime

    count = len([r for r in routines_mod.load() if r.get("enabled", True)])
    print(f"cutecat routines: watching {count} routine(s). ctrl-c to stop.")
    last_tick = datetime.now()
    try:
        while True:
            time.sleep(20)
            now = datetime.now()
            # Routines are re-read every tick, so adding one takes effect
            # without restarting the scheduler.
            _fire_due(routines_mod, headless, last_tick)
            last_tick = now
    except KeyboardInterrupt:
        print("\nstopped.")


SKILL_USAGE = """\
cutecat skill <options>     manage the skills the agent can follow

  --list                    show your skills, and which are on
  --show NAME               print a skill
  --fetch URL               download a .md and add it (named after the file)
  --path FILE               add a .md from your disk
  --new NAME                create a starter skill to edit
  --export NAME DEST        copy a skill out to share it
  --enable NAME             turn a skill on
  --disable NAME            turn a skill off
  --remove NAME             delete it
  --reset                   put back the skills that ship with cutecat

  --name NAME               name it yourself (with --fetch / --path)
  --force                   overwrite a skill of the same name
  --yes                     don't ask before saving a fetched skill

examples:
  cutecat skill --list
  cutecat skill --fetch https://github.com/user/repo/blob/main/skills/tdd.md
  cutecat skill --path ~/notes/our-style.md --name house-style --enable
  cutecat skill --new deploy-checklist
"""


def _skill_command(args: list[str]) -> None:
    from cutecat import skills as skills_mod

    def value(flag: str, default=None):
        if flag in args:
            i = args.index(flag) + 1
            if i < len(args) and not args[i].startswith("--"):
                return args[i]
        return default

    force = "--force" in args
    assume_yes = "--yes" in args or "-y" in args
    name_override = value("--name")

    _skill_opts = (
        "--list", "--show", "--fetch", "--path", "--new", "--export",
        "--enable", "--disable", "--remove", "--delete", "--reset",
        "--name", "--force", "--yes", "--help",
    )
    try:
        if not args or "--help" in args or "-h" in args or "help" in args:
            print(SKILL_USAGE)
            return

        for a in args:
            if a.startswith("--") and a not in _skill_opts:
                raise _unknown(a, "skill option", _skill_opts,
                               "see cutecat skill --help")

        if "--list" in args or args == ["list"]:
            items = skills_mod.listing()
            if not items:
                print("no skills — cutecat skill --help")
                return
            width = max(len(s["name"]) for s in items)
            on = sum(s["on"] for s in items)
            for s in items:
                mark = "[x]" if s["on"] else "[ ]"
                tag = "" if s["bundled"] else "   (yours)"
                print(f"{mark} {s['name']:<{width}}  {s['lines']:>3} lines{tag}")
            print(f"\n{on} of {len(items)} enabled · toggle in the chat with /skills")
            return

        if "--show" in args:
            print(skills_mod.read(value("--show") or ""), end="")
            return

        if "--reset" in args:
            put_back = skills_mod.reset(force=force)
            print(
                f"restored {len(put_back)} bundled skill(s): {', '.join(put_back)}"
                if put_back else
                "nothing to restore (use --force to overwrite your edits)"
            )
            return

        if "--new" in args:
            path = skills_mod.new(value("--new") or "")
            print(f"created {path}\nedit it, then turn it on with /skills")
            return

        if "--export" in args:
            i = args.index("--export")
            if i + 1 >= len(args) or args[i + 1].startswith("--"):
                raise skills_mod.SkillError(
                    "usage: cutecat skill --export <name> [destination]"
                )
            dest = args[i + 2] if i + 2 < len(args) and not args[i + 2].startswith("--") else "."
            print(f"wrote {skills_mod.export(args[i + 1], dest)}")
            return

        if "--remove" in args or "--delete" in args:
            path = skills_mod.remove(value("--remove") or value("--delete") or "")
            print(f"deleted {path.stem}")
            return

        if "--enable" in args and not ("--fetch" in args or "--path" in args):
            print(f"{skills_mod.set_enabled(value('--enable') or '', True)}: on")
            return

        if "--disable" in args:
            print(f"{skills_mod.set_enabled(value('--disable') or '', False)}: off")
            return

        if "--fetch" in args:
            url = value("--fetch") or ""
            print(f"fetching {skills_mod.raw_url(url)}")
            name, body = skills_mod.fetch(url, name_override)
        elif "--path" in args:
            name, body = skills_mod.add_from_path(value("--path") or "", name_override)
        else:
            raise skills_mod.SkillError("nothing to do — see cutecat skill --help")

        if skills_mod.skill_path(name).exists() and not force:
            raise skills_mod.SkillError(
                f"a skill called {name!r} already exists — pass --force to replace it"
            )

        lines = body.splitlines()
        print(f"\n--- {name} · {len(lines)} lines " + "-" * 30)
        for line in lines[:12]:
            print(f"  {line}")
        if len(lines) > 12:
            print(f"  … {len(lines) - 12} more lines")
        print("-" * 50)
        for note in skills_mod.warnings(body):
            print(f"note: {note}")

        if not assume_yes:
            # A skill is instructions the model follows, not data. Look before
            # you install one from the internet.
            print("\nA skill goes into the AI's prompt and it will follow it.")
            try:
                answer = input(f"add it as '{name}'? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                raise SystemExit("\ncutecat: cancelled") from None
            if answer not in ("y", "yes"):
                raise SystemExit("cutecat: not added")

        path = skills_mod.copy_into(name, body, force=force)
        print(f"added {path}")
        if "--enable" in args:
            skills_mod.set_enabled(name, True)
            print(f"{name}: on")
        else:
            print(f"turn it on with /skills, or: cutecat skill --enable {name}")

    except skills_mod.SkillError as exc:
        raise SystemExit(f"cutecat: {exc}") from None


DISCORD_USAGE = """\
cutecat discord [option]      chat with cutecat from Discord (the bot runs here)

  -r, --run        start the bot (the default) — answers only you, only your channel
  --setup          set the token, your user id, and the channel, interactively
  --status         show the current Discord configuration (token hidden)
  --check          check this machine can run the bot (discord.py + voice libs)
  --install        run the bot as a service (systemd / launchd), always on
  --uninstall      stop running it as a service
  -h, --help       show this help

Before running, enable the Message Content Intent for the bot in the Discord
developer portal (Bot → Privileged Gateway Intents).
"""

_DISCORD_ACTIONS = {
    "-r": "run", "--run": "run", "run": "run",
    "--setup": "setup", "setup": "setup",
    "--status": "status", "status": "status",
    "--check": "check", "check": "check",
    "--install": "install", "install": "install",
    "--uninstall": "uninstall", "uninstall": "uninstall",
}


def _discord_command(args: list[str]) -> None:
    from cutecat import config as config_mod, discord_format as fmt

    if any(a in ("-h", "--help", "help") for a in args):
        print(DISCORD_USAGE)
        return

    _opts = ("-r", "--run", "--setup", "--status", "--check",
             "--install", "--uninstall", "--help")
    actions = []
    for a in args:
        if a not in _DISCORD_ACTIONS:
            raise _unknown(a, "discord option", _opts,
                           "see cutecat discord --help")
        actions.append(_DISCORD_ACTIONS[a])
    action = actions[0] if actions else "run"

    cfg = config_mod.load_config()

    if action == "status":
        d = cfg.get("discord") or {}
        print("Discord bot:", "configured" if fmt.configured(cfg) else "not set up")
        print(f"  token:      {'set' if d.get('token') else '(none)'}")
        print(f"  owner_id:   {d.get('owner_id') or '(none)'}")
        print(f"  channel_id: {d.get('channel_id') or '(none)'}")
        print(f"  guild_id:   {d.get('guild_id') or '(none)'}")
        print(f"  voice (stt):{d.get('stt') or 'off'}")
        return

    if action == "setup":
        _discord_setup(cfg, config_mod, fmt)
        return

    if action == "check":
        _discord_check(cfg)
        return

    if action in ("install", "uninstall"):
        from cutecat import routines as routines_mod

        try:
            if action == "install":
                if not fmt.configured(cfg):
                    raise SystemExit("cutecat: run 'cutecat discord --setup' first")
                print(routines_mod.install_service("discord", "discord --run"))
            else:
                print(routines_mod.uninstall_service("discord"))
        except routines_mod.RoutineError as exc:
            raise SystemExit(f"cutecat: {exc}") from None
        return

    # default (or -r/--run): run the bot here
    if not fmt.configured(cfg):
        raise SystemExit(
            "cutecat: Discord isn't set up. Run 'cutecat discord --setup' first.")
    try:
        from cutecat import discord_bot
    except ImportError:
        raise SystemExit(
            "cutecat: the Discord bot needs discord.py — install it with:\n"
            "  pip install 'cutecat[discord]'   (or: pip install discord.py)"
        ) from None
    discord_bot.run(cfg)


def _discord_setup(cfg, config_mod, fmt) -> None:
    print("Set up the Discord bot. Leave a line blank to keep the current value.\n")
    d = cfg.setdefault("discord", {})

    def ask(label, key, secret=False):
        cur = d.get(key)
        shown = "set" if (secret and cur) else (cur or "")
        prompt = f"{label}" + (f" [{shown}]" if shown else "") + ": "
        try:
            if secret:
                import getpass
                val = getpass.getpass(prompt).strip()
            else:
                val = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            raise SystemExit("\ncutecat: cancelled") from None
        if val:
            d[key] = val

    ask("Bot token (from the Discord developer portal)", "token", secret=True)
    ask("Your Discord user id (enable Developer Mode → right-click yourself → Copy ID)",
        "owner_id")
    ask("The channel id it should live in (right-click the channel → Copy ID)",
        "channel_id")
    ask("Your server id (optional, makes slash commands appear instantly)", "guild_id")
    config_mod.save_config(cfg)
    print("\nsaved." + ("" if fmt.configured(cfg) else
          "  (still missing token / owner_id / channel_id)"))
    print("start it with: cutecat discord --run")


def _discord_check(cfg) -> None:
    import os
    import sys

    frozen = getattr(sys, "frozen", False) or "__compiled__" in globals() or \
        globals().get("__nuitka_binary_dir") is not None
    print(f"python:     {sys.version.split()[0]}"
          f"  ({'standalone binary' if frozen else 'pip install'})")

    try:
        import discord
        print(f"discord.py: {discord.__version__}  — ok")
    except Exception as exc:  # noqa: BLE001
        print(f"discord.py: MISSING — {type(exc).__name__}: {exc}")
        print("            pip install 'cutecat[discord]'")

    d = cfg.get("discord") or {}
    stt = (d.get("stt") or "").lower()
    print(f"voice stt:  {stt or 'off'}"
          + ("" if stt else "  (set discord.stt to \"local\" or \"api\" to enable)"))

    # Only the 'local' path needs faster-whisper; 'api' just needs requests.
    if stt == "local":
        try:
            from faster_whisper import WhisperModel  # noqa: F401
            print("faster-whisper: import ok — local voice transcription available")
        except Exception as exc:  # noqa: BLE001
            print(f"faster-whisper: FAILED — {type(exc).__name__}: {exc}")
            if os.environ.get("CUTECAT_VOICE_TRACEBACK"):
                import traceback
                traceback.print_exc()
            if frozen:
                print("            the library is bundled; a system library it needs is")
                print("            likely missing — try: apt install libgomp1 libstdc++6")
                print("            (set CUTECAT_VOICE_TRACEBACK=1 for the full traceback)")
            else:
                print("            pip install 'cutecat[voice]'")


def _print_help() -> None:
    # curious, here-to-help face
    print(cat_banner(f"cutecat {__version__} — a fast AI agent for your terminal",
                     eyes="o.o", mouth="-"))
    print(f"""
usage:
  cutecat                       start a new session
  cutecat <subcommand> ...      run a subcommand (below)
  cutecat [options]

subcommands:
  sessions                      list your past sessions
  skill [options]               add / list / remove skills   (cutecat skill --help)
  routines [options]            prompts that run on a schedule  (cutecat routines --help)
  discord [options]             chat with cutecat from Discord  (cutecat discord --help)

options:
  --continue, -c                resume the most recent session
  --resume ID                   resume a session by id (or a unique prefix)
  --encrypt                     put your chats and keys behind a passphrase (AES-256)
  --decrypt                     turn encryption back off
  --version                     print the version
  -h, --help                    show this help

Inside a session, type / to see the chat commands, or /help.""")


def _sessions_command(args: list[str]) -> None:
    from cutecat import config as config_mod

    if args and args[0] in ("-h", "--help", "help"):
        print("cutecat sessions            list your past sessions, newest first\n"
              "  resume with:  cutecat --resume <id>   (or --continue for the latest)")
        return
    sessions = config_mod.list_sessions()
    if not sessions:
        print("no sessions yet")
        return
    limit = 30
    for s in sessions[:limit]:
        sid = (s.get("id") or "")[:8]
        title = (s.get("title") or "(untitled)")[:48]
        when = (s.get("updated") or "")[:16].replace("T", " ")
        print(f"{sid}  {when}  {title}")
    if len(sessions) > limit:
        print(f"… and {len(sessions) - limit} more")
    print("\nresume:  cutecat --resume <id>   ·   latest:  cutecat --continue")


def _silence_tracebacks() -> None:
    import threading

    from cutecat.app import write_crash_log

    def quiet_thread_hook(args) -> None:
        if args.exc_value is not None:
            write_crash_log(args.exc_value)

    def quiet_hook(exc_type, exc, _tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            return
        path = write_crash_log(exc)
        print(f"cutecat: {exc_type.__name__}: {exc}", file=sys.stderr)
        if path is not None:
            print(f"the details are in {path}", file=sys.stderr)

    threading.excepthook = quiet_thread_hook
    sys.excepthook = quiet_hook


def _use_bundled_certs() -> None:
    if not getattr(sys, "frozen", False):
        return

    import os

    # An explicit store wins — a company CA or a proxy's MITM cert lives there.
    if os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR"):
        return

    import ssl

    paths = ssl.get_default_verify_paths()
    if (paths.cafile and os.path.isfile(paths.cafile)) or (
        paths.capath and os.path.isdir(paths.capath)
    ):
        return  # the system store is where this OpenSSL expects it

    try:
        import certifi
    except ImportError:
        return

    bundle = certifi.where()
    if os.path.isfile(bundle):
        os.environ["SSL_CERT_FILE"] = bundle


def main() -> None:
    _silence_tracebacks()
    _use_bundled_certs()
    try:
        _main()
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except SystemExit:
        raise
    except Exception as exc:
        from cutecat.app import write_crash_log

        path = write_crash_log(exc)
        print(f"cutecat: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        if path is not None:
            print(f"the details are in {path}", file=sys.stderr)
        raise SystemExit(1) from None


def _main() -> None:
    argv = sys.argv[1:]

    if argv and argv[0] in ("routines", "routine"):
        _unlock_or_exit()
        _routines_command(argv[1:])
        return

    if argv and argv[0] in ("skill", "skills"):
        _unlock_or_exit()
        _skill_command(argv[1:])
        return

    if argv and argv[0] == "discord":
        _unlock_or_exit()
        _discord_command(argv[1:])
        return

    if argv and argv[0] == "sessions":
        _unlock_or_exit()
        _sessions_command(argv[1:])
        return

    if argv and argv[0] in ("-h", "--help"):
        _print_help()
        return
    if argv and argv[0] in ("-v", "--version"):
        # a proud grin
        print(cat_banner(f"cutecat {__version__}", eyes="^ ^", mouth="w"))
        return

    if argv:
        first = argv[0]
        if not first.startswith("-") and first not in _SUBCOMMANDS:
            raise _unknown(first, "command", _SUBCOMMANDS,
                           "run 'cutecat --help' for the list of commands")
        if first.startswith("-") and first not in _TOP_OPTIONS:
            raise _unknown(first, "option", _TOP_OPTIONS,
                           "run 'cutecat --help' for usage")

    parser = argparse.ArgumentParser(
        prog="cutecat",
        description="A simple, fast AI agent for your terminal.",
        add_help=False,
    )
    parser.add_argument("--resume", metavar="ID", help=argparse.SUPPRESS)
    parser.add_argument("--continue", "-c", dest="cont", action="store_true",
                        help=argparse.SUPPRESS)
    parser.add_argument("--encrypt", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--decrypt", action="store_true", help=argparse.SUPPRESS)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code:
            print("run 'cutecat --help' for usage", file=sys.stderr)
        raise

    if args.encrypt and args.decrypt:
        raise SystemExit("cutecat: --encrypt and --decrypt are opposites")
    if args.encrypt:
        _encrypt_command()
        return
    if args.decrypt:
        _decrypt_command()
        return

    from cutecat import config as config_mod

    _unlock_or_exit()

    session = None
    if args.resume:
        session_id = config_mod.resolve_session(args.resume)
        session = config_mod.load_session(session_id) if session_id else None
        if session is None:
            raise SystemExit(
                f"cutecat: no session matching '{args.resume}'"
                f" in {config_mod.SESSIONS_DIR}"
            )
    elif args.cont:
        recent = config_mod.list_sessions()
        if not recent:
            raise SystemExit("cutecat: no previous sessions to continue")
        session = config_mod.load_session(recent[0]["id"])
        if session is None:
            raise SystemExit("cutecat: could not open the most recent session")

    from cutecat.app import CuteCatApp

    app = CuteCatApp(session=session)
    app.run()

    if getattr(app, "crash", None):
        log_path, session_id = app.crash
        print("cutecat: sorry — something went wrong and it had to close.",
              file=sys.stderr)
        if log_path is not None:
            print(f"  what happened is written in {log_path}", file=sys.stderr)
        if session_id:
            print(f"  your chat is safe: cutecat --resume {session_id[:8]}",
                  file=sys.stderr)
        raise SystemExit(1)

    resume = getattr(app, "resume_id", None)
    if resume:
        # a wink goodbye
        print(cat_banner(f"cutecat --resume {resume[:8]}", eyes="^.-", mouth="w"))


if __name__ == "__main__":
    main()
