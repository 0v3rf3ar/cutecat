from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from pathlib import Path
from time import monotonic

import discord

from cutecat import agent as agent_mod
from cutecat import config as config_mod
from cutecat import discord_format as fmt
from cutecat import tools as tools_mod
from cutecat.providers import get_provider
from cutecat.providers.base import Provider
from cutecat.shell import create_shell, shell_kind
from cutecat.tools import ToolContext

EDIT_EVERY = 1.4          # seconds between edits to the streaming answer
STATUS_EVERY = 2.0        # seconds between status-line updates
PERMISSION_TIMEOUT = 300  # auto-deny a permission prompt after 5 minutes


#session


class Session:

    def __init__(self, cfg: dict, channel_id: int):
        self.channel_id = channel_id
        self.id = config_mod.new_session_id()
        self.created = config_mod.now_iso()
        self.messages: list[dict] = []
        self.title = ""
        self.agent_mode = cfg.get("agent_mode") or "build"
        self.tools_disabled = False
        self.cwd = cfg.get("workspace") or "."
        self.shell = None
        self.busy = False
        self.cancel = False

    def ensure_shell(self):
        if self.shell is None:
            self.shell = create_shell(self.cwd)
        return self.shell

    def save(self, cfg: dict) -> None:
        if not self.messages:
            return
        try:
            config_mod.save_session({
                "id": self.id,
                "created": self.created,
                "title": self.title or "discord",
                "provider": cfg.get("provider"),
                "model": cfg.get("model"),
                "messages": self.messages,
                "input_history": [],
            })
        except config_mod.StorageError:
            pass  # a full disk should not stop the conversation

    def reset(self, cfg: dict) -> None:
        if self.shell is not None:
            self.shell.close()
            self.shell = None
        self.__init__(cfg, self.channel_id)


def build_system_prompt(cfg: dict, agent_mode: str) -> str:
    from cutecat.app import BUILD_DIRECTIVE, PLAN_DIRECTIVE, SHELL_DIRECTIVES

    parts = [config_mod.system_prompt()]
    enabled = cfg.get("skills") or {}
    for name in config_mod.list_skills():
        if enabled.get(name):
            body = config_mod.read_skill(name)
            if body:
                parts.append(f"## skill: {name}\n\n{body}")
    parts.append(SHELL_DIRECTIVES[shell_kind()])
    parts.append(PLAN_DIRECTIVE if agent_mode == "plan" else BUILD_DIRECTIVE)
    parts.append(fmt.DISCORD_BREVITY)
    return "\n\n".join(parts)


#permission


class PermissionView(discord.ui.View):

    def __init__(self, owner_id: int, allow_all: bool):
        super().__init__(timeout=PERMISSION_TIMEOUT)
        self.owner_id = owner_id
        self.result = "n"
        self.event = threading.Event()
        if not allow_all:
            self.remove_item(self.allow_all)

    async def _finish(self, interaction: discord.Interaction, result: str, label: str):
        if interaction.user.id != self.owner_id:
            return
        self.result = result
        for child in self.children:
            child.disabled = True
        self.stop()
        try:
            await interaction.response.edit_message(content=label, view=None)
        except discord.HTTPException:
            pass
        finally:
            self.event.set()

    @discord.ui.button(label="Allow", style=discord.ButtonStyle.success)
    async def allow(self, interaction, button):
        await self._finish(interaction, "y", "✅ allowed")

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger)
    async def deny(self, interaction, button):
        await self._finish(interaction, "n", "🚫 denied")

    @discord.ui.button(label="Allow all edits here", style=discord.ButtonStyle.secondary)
    async def allow_all(self, interaction, button):
        await self._finish(interaction, "a", "✅ allowing all edits in this session")

    async def on_timeout(self):
        self.result = "n"
        self.event.set()


#the bot


class CuteCatBot(discord.Client):
    def __init__(self, cfg: dict):
        intents = discord.Intents.default()
        intents.message_content = True  # privileged; enable it in the dev portal
        super().__init__(intents=intents)
        self.cfg = cfg
        self.dcfg = cfg.get("discord") or {}
        self.owner_id = int(self.dcfg["owner_id"])
        self.channel_id = int(self.dcfg["channel_id"])
        self.tree = discord.app_commands.CommandTree(self)
        self.sessions: dict[int, Session] = {}
        self.allow_all_edits: set[int] = set()  # channel ids
        _register_commands(self)

    # -- lifecycle

    async def setup_hook(self) -> None:
        guild_id = self.dcfg.get("guild_id")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)  # instant in one guild
        else:
            await self.tree.sync()  # global, up to an hour to appear

    async def on_ready(self):
        print(f"cutecat discord: online as {self.user} · "
              f"answering owner {self.owner_id} in channel {self.channel_id}")

    def session_for(self, channel) -> Session:
        cid = channel.id
        if cid not in self.sessions:
            self.sessions[cid] = Session(self.cfg, cid)
        return self.sessions[cid]

    def _allowed(self, message: discord.Message) -> bool:
        parent = getattr(message.channel, "parent_id", None)
        return fmt.is_allowed(
            self.cfg,
            author_id=message.author.id,
            channel_id=message.channel.id,
            parent_channel_id=parent,
            is_bot=message.author.bot,
        )

    # -- messages

    async def on_message(self, message: discord.Message):
        if message.author.id == (self.user.id if self.user else 0):
            return
        if not self._allowed(message):
            return  # silence: not the owner, or not the channel
        text = message.content or ""
        media: list[dict] = []
        if message.attachments:
            text, media = await self._absorb_attachments(message, text)
        if not text.strip() and not media:
            return
        session = self.session_for(message.channel)
        if session.busy:
            await message.channel.send("still working — /stop to cancel first")
            return
        await self._run_turn(message.channel, session, text, media)

    async def _absorb_attachments(self, message, text: str):
        import base64

        from cutecat import discord_voice

        provider = get_provider(self.cfg.get("provider"))
        can_image = bool(provider and provider.supports_images)
        can_audio = bool(provider and provider.supports_audio)
        extra: list[str] = []
        media: list[dict] = []

        for att in message.attachments:
            ctype = (att.content_type or "").lower()
            is_voice = bool(getattr(att, "flags", None)
                            and att.flags.value & (1 << 13))
            if is_voice or ctype.startswith("audio/"):
                sent_as_audio = False
                if can_audio:
                    data = await att.read()
                    fmt = _audio_format(att.filename, ctype)
                    # Discord sends ogg/opus; most APIs want wav or mp3
                    if fmt not in provider.audio_formats:
                        wav = await asyncio.to_thread(discord_voice.to_wav, data)
                        if wav is not None:
                            data, fmt = wav, "wav"
                    if fmt in provider.audio_formats:
                        media.append({"kind": "audio",
                                      "b64": base64.b64encode(data).decode(),
                                      "format": fmt})
                        extra.append("[voice message attached]")
                        sent_as_audio = True
                if not sent_as_audio:
                    note = None
                    try:
                        note = await message.channel.send("🎧 transcribing your voice message…")
                    except discord.HTTPException:
                        pass
                    said = await discord_voice.transcribe(self.cfg, att)
                    if note is not None:
                        try:
                            await note.delete()
                        except discord.HTTPException:
                            pass
                    extra.append(f"[voice message] {said}")
            elif ctype.startswith("image/"):
                if can_image:
                    data = await att.read()
                    media.append({"kind": "image",
                                  "b64": base64.b64encode(data).decode(),
                                  "mime": ctype or "image/png"})
                    extra.append(f"[image attached: {att.filename}]")
                else:
                    extra.append(f"[an image was sent ({att.filename}) but this "
                                 "model can't see images]")
            elif ctype.startswith(("text/", "application/json")):
                body = (await att.read())[:100_000].decode("utf-8", "replace")
                extra.append(f"[attached file {att.filename}]\n{body}")
            else:
                dest = Path(self.cfg.get("workspace") or ".") / att.filename
                try:
                    await att.save(dest)
                    extra.append(f"[saved attachment to {dest}]")
                except OSError as exc:
                    extra.append(f"[could not save {att.filename}: {exc}]")

        if extra:
            text = (text + "\n\n" + "\n\n".join(extra)).strip()
        return text, media

    async def _run_turn(self, channel, session: Session, text: str,
                        media: list[dict] | None = None):
        provider = get_provider(self.cfg.get("provider"))
        key = config_mod.get_api_key(self.cfg, self.cfg.get("provider"))
        model = self.cfg.get("model")
        if provider is None or not key or not model:
            await channel.send("not connected — run `cutecat` on the server and use "
                               "`/connect` (keys never go through Discord)")
            return

        session.busy = True
        session.cancel = False
        user_msg: dict = {"role": "user", "content": text}
        if media:
            user_msg["media"] = media   # transient — stripped before saving
        session.messages.append(user_msg)
        turn = Turn(self, channel, session, provider, key, model)
        try:
            await turn.run()
        finally:
            session.busy = False
            user_msg.pop("media", None)
            session.save(self.cfg)


#one turn


class Turn:
    def __init__(self, bot: CuteCatBot, channel, session: Session,
                 provider: Provider, key: str, model: str):
        self.bot = bot
        self.channel = channel
        self.session = session
        self.provider = provider
        self.key = key
        self.model = model
        self.loop = asyncio.get_running_loop()

        self.status_msg: discord.Message | None = None
        self.answer_msgs: list[discord.Message] = []
        self.answer_text = ""
        self.phase = "thinking"
        self.detail = ""
        self.started = datetime.now()
        self.last_edit = 0.0
        self.tick = 0

    async def run(self):
        self.status_msg = await self.channel.send(
            fmt.status_line("thinking", "", 0, 0))
        status_task = asyncio.create_task(self._status_loop())
        try:
            await asyncio.to_thread(self._drive)
            await self._flush_answer(final=True)
        finally:
            status_task.cancel()
            if self.status_msg is not None:
                try:
                    await self.status_msg.delete()   # clean channel: no clutter
                except discord.HTTPException:
                    pass

    # -- the status line, edited on a timer

    async def _status_loop(self):
        try:
            while True:
                await asyncio.sleep(STATUS_EVERY)
                self.tick += 1
                secs = (datetime.now() - self.started).total_seconds()
                if self.status_msg is not None and not self.session.cancel:
                    try:
                        await self.status_msg.edit(
                            content=fmt.status_line(self.phase, self.detail, secs, self.tick))
                    except discord.HTTPException:
                        pass
        except asyncio.CancelledError:
            pass

    # -- the answer, streamed and chunked

    async def _put_answer(self, text: str, final: bool):
        self.answer_text = text
        chunks = fmt.split_message(text) if text.strip() else []
        for i, chunk in enumerate(chunks):
            if i < len(self.answer_msgs):
                if self.answer_msgs[i].content != chunk:
                    try:
                        await self.answer_msgs[i].edit(content=chunk)
                    except discord.HTTPException:
                        pass
            else:
                self.answer_msgs.append(await self.channel.send(chunk))

    async def _flush_answer(self, final: bool):
        if self.answer_text.strip():
            await self._put_answer(self.answer_text, final)

    # -- the agent, on a worker thread

    def _drive(self):
        ctx = ToolContext(
            shell=self.session.ensure_shell(),
            ask_permission=self._ask_permission,
            ask_tmp=lambda: self._ask_permission("use the temp directory", ""),
            note=lambda _t: None,       # Discord shows only the status line
            is_cancelled=lambda: self.session.cancel,
            run_job=self._run_command,
            ask_edit=self._ask_edit,
            chromium=self.bot.cfg.get("chromium"),
            workspace=self.bot.cfg.get("workspace"),
            send_file=self._send_file,
        )
        system = build_system_prompt(self.bot.cfg, self.session.agent_mode)
        extra = [tools_mod.SEND_FILE_SCHEMA]  # Discord can deliver files
        for event in agent_mod.run_agent(
            self.provider, self.key, self.model, system, self.session.messages, ctx,
            tools_enabled=not self.session.tools_disabled,
            extra_schemas=extra,
            cancelled=lambda: self.session.cancel,
        ):
            if self.session.cancel:
                return
            if isinstance(event, agent_mod.Content):
                self.phase = "thinking"
                # keep the latest text but only push on a timer — editing on
                # every chunk hits Discord's rate limit; the final flush catches up
                self.answer_text = event.full
                now = monotonic()
                if now - self.last_edit >= EDIT_EVERY:
                    self.last_edit = now
                    self._async(self._put_answer(event.full, False))
            elif isinstance(event, agent_mod.ToolStarted):
                self.phase = "working"
                self.detail = event.name
            elif isinstance(event, agent_mod.ToolsDisabled):
                self.session.tools_disabled = True
            elif isinstance(event, agent_mod.Failed):
                self._async(self.channel.send(f"⚠ {event.message}"))

    def _async(self, coro):
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            return fut.result(timeout=60)
        except Exception:
            return None

    # -- tools that reach into Discord

    def _run_command(self, command: str) -> str:
        job = self.session.shell.run(command)
        self.phase, self.detail = "running", _short(command)
        job.finished.wait(timeout=900)
        if job.running:
            self.session.shell.terminate(job)
            job.finished.wait(10)
            return "error: the command ran for 15 minutes and was stopped"
        self.session.shell.adopt_cwd(job)
        return tools_mod.format_job_result(
            command, job.exit_code, job.output(),
            ran_for=job.ran_for, silent_for=job.silent_for,
        )

    def _ask_permission(self, title: str, detail: str) -> bool:
        return self._permission(title, detail, allow_all=False) == "y"

    def _ask_edit(self, title: str, detail: str) -> bool:
        if self.channel.id in self.bot.allow_all_edits:
            return True
        result = self._permission(title, detail, allow_all=True)
        if result == "a":
            self.bot.allow_all_edits.add(self.channel.id)
            return True
        return result == "y"

    def _permission(self, title: str, detail: str, allow_all: bool) -> str:
        self.phase = "waiting"
        body = f"**{title}**" + (f"\n{detail}" if detail else "")

        async def _post() -> PermissionView:
            view = PermissionView(self.bot.owner_id, allow_all)
            await self.channel.send(body[:1900], view=view)
            return view

        view = self._async(_post())
        if view is None:            # the prompt could not be sent
            return "n"
        view.event.wait(PERMISSION_TIMEOUT + 5)
        self.phase = "working"
        return view.result

    def _send_file(self, path: str, caption: str | None) -> str:
        limit = fmt.upload_limit_bytes(self.bot.cfg)
        p = Path(path)
        try:
            size = p.stat().st_size
        except OSError as exc:
            return f"error: {exc}"
        if size > limit:
            return (f"error: {p.name} is {size // 1024 // 1024}MB, over the "
                    f"{limit // 1024 // 1024}MB Discord limit")

        async def upload():
            await self.channel.send(
                content=caption or None,
                file=discord.File(str(p), filename=p.name))
        self._async(upload())
        return f"sent {p.name} to the user"


def _short(command: str, n: int = 40) -> str:
    command = " ".join(command.split())
    return command if len(command) <= n else command[:n - 1] + "…"


def _audio_format(filename: str, content_type: str) -> str:
    for ext in ("wav", "mp3", "ogg", "webm", "m4a", "flac", "opus"):
        if name.endswith("." + ext) or ext in content_type:
            return "ogg" if ext == "opus" else ext
    return "ogg"  # Discord voice messages are ogg/opus


#slash cmds


def _register_commands(bot: CuteCatBot):
    tree = bot.tree

    def owner_only(interaction: discord.Interaction) -> bool:
        return (interaction.user.id == bot.owner_id
                and interaction.channel_id in (bot.channel_id, *bot.sessions))

    @tree.command(description="Cancel what the agent is doing right now")
    async def stop(interaction: discord.Interaction):
        if not owner_only(interaction):
            return await interaction.response.send_message("not for you", ephemeral=True)
        session = bot.sessions.get(interaction.channel_id)
        if session and session.busy:
            session.cancel = True
            await interaction.response.send_message("⏹ stopping", ephemeral=True)
        else:
            await interaction.response.send_message("nothing running", ephemeral=True)

    @tree.command(description="Start a fresh conversation (clears history)")
    async def new(interaction: discord.Interaction):
        if not owner_only(interaction):
            return await interaction.response.send_message("not for you", ephemeral=True)
        bot.session_for(interaction.channel).reset(bot.cfg)
        await interaction.response.send_message("🆕 fresh session", ephemeral=True)

    @tree.command(description="Delete the chat here (your messages, mine, and history)")
    async def clear(interaction: discord.Interaction):
        if not owner_only(interaction):
            return await interaction.response.send_message("not for you", ephemeral=True)
        await interaction.response.send_message("🧹 clearing…", ephemeral=True)
        bot.session_for(interaction.channel).reset(bot.cfg)
        deleted = await _purge_channel(interaction.channel)
        try:
            await interaction.edit_original_response(
                content=f"🧹 cleared {deleted} message(s) and the history")
        except discord.HTTPException:
            pass

    @tree.command(description="Switch the model")
    @discord.app_commands.describe(name="the model to use")
    async def model(interaction: discord.Interaction, name: str):
        if not owner_only(interaction):
            return await interaction.response.send_message("not for you", ephemeral=True)
        bot.cfg["model"] = name
        config_mod.save_config(bot.cfg)
        await interaction.response.send_message(f"model → {name}", ephemeral=True)

    @model.autocomplete("name")
    async def model_ac(interaction, current: str):
        provider = get_provider(bot.cfg.get("provider"))
        key = config_mod.get_api_key(bot.cfg, bot.cfg.get("provider"))
        try:
            models = provider.list_models(key) if provider and key else []
        except Exception:
            models = []
        return [discord.app_commands.Choice(name=m, value=m)
                for m in models if current.lower() in m.lower()][:25]

    @tree.command(description="Agent mode: build (do it) or plan (write PLAN.md)")
    @discord.app_commands.describe(mode="build or plan")
    @discord.app_commands.choices(mode=[
        discord.app_commands.Choice(name="build — carry out tasks", value="build"),
        discord.app_commands.Choice(name="plan — write PLAN.md", value="plan"),
    ])
    async def agents(interaction, mode: discord.app_commands.Choice[str]):
        if not owner_only(interaction):
            return await interaction.response.send_message("not for you", ephemeral=True)
        bot.session_for(interaction.channel).agent_mode = mode.value
        bot.cfg["agent_mode"] = mode.value
        config_mod.save_config(bot.cfg)
        await interaction.response.send_message(f"agent → {mode.value}", ephemeral=True)

    @tree.command(description="Turn a skill on or off")
    @discord.app_commands.describe(name="skill name")
    async def skills(interaction: discord.Interaction, name: str):
        if not owner_only(interaction):
            return await interaction.response.send_message("not for you", ephemeral=True)
        cur = bot.cfg.setdefault("skills", {})
        if name not in config_mod.list_skills():
            return await interaction.response.send_message(
                f"no skill {name!r}", ephemeral=True)
        cur[name] = not cur.get(name, False)
        config_mod.save_config(bot.cfg)
        await interaction.response.send_message(
            f"skill {name} {'on' if cur[name] else 'off'}", ephemeral=True)

    @skills.autocomplete("name")
    async def skills_ac(interaction, current: str):
        return [discord.app_commands.Choice(name=s, value=s)
                for s in config_mod.list_skills() if current.lower() in s.lower()][:25]

    @tree.command(description="Summarise the conversation so far to save tokens")
    async def compact(interaction: discord.Interaction):
        if not owner_only(interaction):
            return await interaction.response.send_message("not for you", ephemeral=True)
        session = bot.session_for(interaction.channel)
        if not session.messages:
            return await interaction.response.send_message("nothing to compact", ephemeral=True)
        await interaction.response.send_message("compacting…", ephemeral=True)
        summary = await asyncio.to_thread(_compact_sync, bot.cfg, session.messages)
        if summary:
            session.messages = [{"role": "user",
                                 "content": "Summary of the conversation so far:\n\n" + summary}]
            await interaction.edit_original_response(content="🗜 compacted")
        else:
            await interaction.edit_original_response(content="couldn't compact")

    @tree.command(description="List your routines")
    async def routines(interaction: discord.Interaction):
        if not owner_only(interaction):
            return await interaction.response.send_message("not for you", ephemeral=True)
        from cutecat import routines as R
        items = R.load()
        if not items:
            return await interaction.response.send_message(
                "no routines — say “every weekday at 9, summarise commits” and I’ll offer to make one",
                ephemeral=True)
        lines = [f"• **{r['name']}** — {R.describe(r)}" for r in items]
        await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)


async def _purge_channel(channel) -> int:
    deleted = 0
    try:
        removed = await channel.purge(limit=None)   # bulk, <14 days
        deleted += len(removed)
    except (discord.HTTPException, AttributeError):
        pass
    # the stragglers older than 14 days
    try:
        async for msg in channel.history(limit=None):
            try:
                await msg.delete()
                deleted += 1
            except discord.HTTPException:
                pass
    except discord.HTTPException:
        pass
    return deleted


def _compact_sync(cfg: dict, messages: list[dict]) -> str:
    from cutecat.app import COMPACT_PROMPT, _transcript

    provider = get_provider(cfg.get("provider"))
    key = config_mod.get_api_key(cfg, cfg.get("provider"))
    model = cfg.get("model")
    if not (provider and key and model):
        return ""
    req = [{"role": "system", "content": COMPACT_PROMPT},
           {"role": "user", "content": _transcript(messages)}]
    out = ""
    try:
        for kind, payload in provider.stream_chat(key, model, req, tools=None):
            if kind == "content" and payload:
                out += payload
    except Exception:
        return ""
    return out.strip()


#entry


def run(cfg: dict) -> None:
    if not fmt.configured(cfg):
        raise SystemExit(
            "cutecat: Discord isn't set up. Run 'cutecat discord setup' first.")
    token = (cfg.get("discord") or {}).get("token")
    bot = CuteCatBot(cfg)
    try:
        bot.run(token, log_handler=None)
    except discord.LoginFailure:
        raise SystemExit("cutecat: Discord rejected the bot token") from None
    except discord.PrivilegedIntentsRequired:
        raise SystemExit(
            "cutecat: enable the Message Content Intent for this bot in the "
            "Discord developer portal (Bot → Privileged Gateway Intents)."
        ) from None
