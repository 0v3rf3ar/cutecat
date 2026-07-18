"""Headless end-to-end test of the cutecat UI.

Run with: python tests/test_tui.py
Drives the app with a fake provider: /help, the full /connect flow,
agent system prompt, skills toggling, sessions + resume, streaming chat
with thinking phase, multiline input, paste collapsing, history recall,
timing footer, and a monochrome style audit.
"""
import asyncio
import contextlib
import inspect
import io
import sys
import threading
from time import monotonic
import os
import tempfile
from pathlib import Path

from cutecat import config as config_mod

tmp = Path(tempfile.mkdtemp())
config_mod.CUTECAT_DIR = tmp
config_mod.CONFIG_FILE = tmp / "config.json"
config_mod.SKILLS_DIR = tmp / "skills"
config_mod.SESSIONS_DIR = tmp / "sessions"
config_mod.SYSTEM_PROMPT_FILE = tmp / "SYSTEM.md"
# Start from an empty config, and keep the real user's pre-0.3 platformdirs
# config out of this entirely: it must be neither imported (it holds their key)
# nor shredded by the encryption test.
config_mod._migrate_legacy_config = lambda: None
config_mod.legacy_config_file = lambda: None

from cutecat.providers import PROVIDERS
from cutecat.providers.base import Provider


class FakeProvider(Provider):
    id = "fake"
    display_name = "Fake API"
    description = "test provider"
    last_messages = None
    last_tools = None
    # A queue of scripted turns; each turn is a list of (kind, payload) events.
    # If empty, falls back to the default single-turn reply.
    scripted_turns = []

    def validate_key(self, key):
        return key == "good-key"

    def list_models(self, key):
        return ["mini-model", "maxi-model"]

    def stream_chat(self, key, model, messages, tools=None):
        import time
        # the concurrent title-generation call is identified by its prompt
        if messages and messages[0].get("content", "").startswith("Generate a very short title"):
            yield ("content", "Fix The Widget")
            return
        FakeProvider.last_messages = messages
        FakeProvider.last_tools = tools
        if FakeProvider.scripted_turns:
            yield from FakeProvider.scripted_turns.pop(0)
            return
        time.sleep(0.2)  # keep the indicator visible long enough to assert on
        yield ("thinking", "let me think")
        yield ("content", "Hello **world**")
        yield ("content", "!\n\n```python\nprint(1)\n```")


from cutecat.providers.custom import CustomProvider as _CustomProvider
PROVIDERS[:] = [FakeProvider(), _CustomProvider()]

from textual import events
from textual.widgets import Static
from cutecat.app import CuteCatApp


def text_of(w):
    v = w.render()
    plain = getattr(v, "plain", None)
    return plain if plain is not None else str(v)


def chat_texts(app):
    return [text_of(w) for w in app.chat.query(Static)]


def has_cat(app):
    """The cat's face changes (it blinks), so match the shape, not one frame."""
    import re
    return any(re.search(r"\(\s\S\.\S\s\)", t) for t in chat_texts(app))


def popup_text(app):
    return text_of(app.query_one("#popup-q")) + " " + text_of(app.query_one("#popup-opts"))


async def submit(app, pilot, text):
    app.input.set_text(text)
    await pilot.press("enter")
    await pilot.pause()


async def wait_for(pilot, cond, tries=200):
    for _ in range(tries):
        if cond():
            return True
        await pilot.pause()
    return False


async def pick_value(app, pilot, value):
    """Select the option whose stored value == value from the scrollable picker."""
    from textual.widgets import OptionList
    idx = app._picker_values.index(value)
    app.query_one("#picker-list", OptionList).highlighted = idx
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()


async def main():
    app = CuteCatApp()
    async with app.run_test(size=(90, 32)) as pilot:
        # black background
        bg = app.screen.styles.background
        assert (bg.r, bg.g, bg.b) == (0, 0, 0), f"screen bg not black: {bg}"

        # bottom stack: indicator, permission popup, a rule, the input, a rule
        assert app.indicator.display is False
        assert app.query_one("#popup").display is False
        kids = [(w.id, type(w).__name__) for w in app.query_one("#bottom").children]
        assert [k[0] for k in kids][:2] == ["indicator", "popup"], kids
        assert "inputbar" in [k[0] for k in kids]

        # welcome cat
        assert has_cat(app), "no cat in welcome"

        # the cat is animated: a blink redraws the welcome, live
        assert app.cat_face == app.cat.IDLE
        assert any("( o.o )" in t for t in chat_texts(app)), chat_texts(app)[0]
        app.cat.next_blink = 0.0          # due to blink on the next tick
        app._tick_cat()
        await pilot.pause()
        assert app.cat_face[0] == app.cat.BLINK, "the cat did not blink"
        assert any("( -.- )" in t for t in chat_texts(app)), "the blink was not drawn"
        app.cat.blink_until = 0.0
        app.cat.next_blink = monotonic() + 60
        app._tick_cat()
        await pilot.pause()
        assert any("( o.o )" in t for t in chat_texts(app)), "the eyes stayed shut"
        # the description line is gone — the welcome is the cat, the version,
        # the directory, and a tip
        assert not any("A fast AI agent" in t for t in chat_texts(app)), (
            "the description line came back"
        )

        # every session opens with a tip
        from cutecat.app import TIPS
        assert app.tip in TIPS
        assert any(f"tip: {app.tip}" in t for t in chat_texts(app)), "no tip in welcome"

        # /help
        await submit(app, pilot, "/help")
        assert any("/model" in t and "switch the active model" in t for t in chat_texts(app))

        # user message bar styling
        user_bars = list(app.chat.query(".user"))
        assert user_bars, "no user bar for /help"
        bar = user_bars[-1]
        assert text_of(bar).startswith("❯ /help")
        bg = bar.styles.background
        assert bg.r == bg.g == bg.b, f"user bg not grey: {bg}"
        fg = bar.styles.color
        assert fg.r == fg.g == fg.b == 0xFF, f"user fg not white: {fg}"
        # the bar steps away from the page in each theme: lighter than black on
        # dark, darker than white on light — and never so far it stops being a
        # quiet grey
        from cutecat.app import PALETTE
        for theme, page in (("dark", 0x00), ("light", 0xFF)):
            shade = int(PALETTE[theme]["userbg"][1:3], 16)
            gap = abs(shade - page)
            assert 0x28 <= gap <= 0x70, f"{theme} user bar {gap:#x} from the page"

        # newlines: only "\\ + enter" adds a line (shift/ctrl+enter/ctrl+j are gone)
        app.input.set_text("one")
        await pilot.press("ctrl+j")   # must NOT insert a newline anymore
        await pilot.pause()
        assert app.input.text == "one", "ctrl+j should no longer add a line"
        app.input.set_text("first\\")
        await pilot.press("enter")
        for ch in "second":
            await pilot.press(ch)
        await pilot.pause()
        assert app.input.text == "first\nsecond", repr(app.input.text)
        assert int(app.input.styles.height.value) == 2
        assert not any(t.startswith("❯ first") for t in chat_texts(app)), "sent instead of newline"
        app.input.set_text("")
        assert int(app.input.styles.height.value) == 1

        # the whole input section carries no background at all, in both themes;
        # separator rules sit above & below it
        from textual.widgets import Rule as _Rule
        for theme in ("dark", "light"):
            app._apply_theme(theme)
            await pilot.pause()
            for sel in ("#inputbar", "#input", "#prompt", "#keyinput", ".input-rule"):
                for widget in app.query(sel):
                    bg = widget.styles.background
                    assert bg.a == 0, f"{sel} has a background in {theme}: {bg}"
        app._apply_theme("dark")
        await pilot.pause()
        bottom_kids = [type(w).__name__ for w in app.query_one("#bottom").children]
        assert bottom_kids.count("Rule") == 2, f"missing input rules: {bottom_kids}"
        assert bottom_kids.index("Horizontal") - 1 == bottom_kids.index("Rule"), "no rule above input"

        # /keys debug mode: echoes key names, esc exits
        await submit(app, pilot, "/keys")
        assert app.key_debug is True
        await pilot.press("a")
        await pilot.pause()
        assert any(t.startswith("key: a") for t in chat_texts(app)), "key not echoed"
        assert app.input.text == "", "debug keys leaked into input"
        await pilot.press("escape")
        await pilot.pause()
        assert app.key_debug is False

        # wrapped input: up/down move through visual lines first, history
        # only when there is no line to move to in that direction
        long_text = "word " * 50  # wraps to several visual lines
        app.input.set_text(long_text)
        await pilot.pause()
        rows = app.input.wrapped_document.height
        assert rows >= 3, f"text did not wrap: {rows} rows"
        assert app.input._cursor_visual_row() == rows - 1, "cursor not on last row"
        for step in range(rows - 1):
            await pilot.press("up")
            assert app.input.text == long_text, f"history recalled mid-text (step {step})"
        assert app.input._cursor_visual_row() == 0
        await pilot.press("up")  # now at top: no upper line -> previous input
        assert app.input.text == "/keys", repr(app.input.text)
        await pilot.press("down")  # single line: no lower line -> newer (draft)
        assert app.input.text == long_text, "draft not restored"
        app.input.set_text("")

        # /connect flow — provider is a scrollable picker now
        await submit(app, pilot, "/connect")
        assert app.mode == "pick", app.mode
        assert app.query_one("#picker").display is True
        await pick_value(app, pilot, "fake")  # the Fake provider
        assert app.mode == "enter-key"
        assert app.key_input.display is True, "key input not shown"
        assert app.input.display is False, "prompt area still shown"
        assert app.key_input.password is True, "key input not masked"
        assert app.key_input.has_focus, "key input not focused"

        # a rejected key says so and asks again instead of dumping you out
        app.key_input.value = "nope"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert any("rejected that api key" in t for t in chat_texts(app)), chat_texts(app)[-3:]
        assert app.mode == "enter-key", "did not re-prompt after a bad key"
        assert app.key_input.display is True

        # an empty key cancels cleanly
        app.key_input.value = "   "
        await pilot.press("enter")
        await pilot.pause()
        assert app.mode == "normal"
        assert any("cancelled" in t for t in chat_texts(app))

        await submit(app, pilot, "/connect")
        await pick_value(app, pilot, "fake")
        # a messy paste (quotes, a Bearer prefix, whitespace) still works
        app.key_input.value = '  "Bearer good-key"  '
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.input.display is True
        assert app.key_input.display is False
        assert app.mode == "pick", "model picker not shown"
        assert not any("good-key" in t for t in chat_texts(app)), "api key echoed!"
        opts = app.query_one("#picker-list").option_count
        assert opts == 2, f"model picker options: {opts}"

        await pick_value(app, pilot, "maxi-model")
        assert app.mode == "normal"
        cfg = config_mod.load_config()
        assert cfg == {
            "provider": "fake",
            "api_key": "good-key",
            "api_keys": {"fake": "good-key"},
            "model": "maxi-model",
            "skills": {},
            "theme": "dark",
            "agent_mode": "build",
            "editor": None,
            "chromium": None,
            "workspace": None,
            "custom": {"base_url": None, "wire": "openai"},
            "discord": {"token": None, "owner_id": None, "channel_id": None,
                        "guild_id": None, "max_upload_mb": 10, "stt": None},
        }, cfg
        status = app.query_one("#status", Static)
        assert "maxi-model" in text_of(status)

        # the key is remembered: /connect skips straight to the model picker
        await submit(app, pilot, "/connect")
        picker = app.query_one("#picker-list")
        labels = [
            str(picker.get_option_at_index(i).prompt)
            for i in range(picker.option_count)
        ]
        assert any("(key saved)" in lb for lb in labels), labels
        await pick_value(app, pilot, "fake")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.mode == "pick", "saved key not reused — asked again"
        assert any("using your saved" in t for t in chat_texts(app))
        await pilot.press("escape")
        await pilot.pause()

        # /connect new forces a fresh key even when one is saved
        await submit(app, pilot, "/connect new")
        await pick_value(app, pilot, "fake")
        assert app.mode == "enter-key", "/connect new did not ask for a key"
        await pilot.press("escape")
        await pilot.pause()
        assert app.mode == "normal"

        # Custom API: pick a wire, enter a base URL, then it asks for the key.
        await submit(app, pilot, "/connect")
        await pick_value(app, pilot, "custom")          # -> wire picker
        assert app.mode == "pick", "custom did not open the wire picker"
        await pick_value(app, pilot, "anthropic")       # -> URL entry
        assert app.mode == "enter-url", "did not ask for the base URL"
        app.input.set_text("https://my-gw.example.com/v1/")   # trailing slash trimmed
        await pilot.press("enter"); await pilot.pause()
        assert app.cfg["custom"] == {"base_url": "https://my-gw.example.com/v1",
                                     "wire": "anthropic"}, app.cfg["custom"]
        assert config_mod.load_config()["custom"]["base_url"].endswith("/v1"), "url not saved"
        assert app.mode == "enter-key", "custom did not go on to ask for a key"
        await pilot.press("escape"); await pilot.pause()
        assert app.mode == "normal"
        # a non-http URL is refused and it asks again
        await submit(app, pilot, "/connect")
        await pick_value(app, pilot, "custom")
        await pick_value(app, pilot, "openai")
        app.input.set_text("ftp://nope")
        await pilot.press("enter"); await pilot.pause()
        assert any("must start with http" in t for t in chat_texts(app)), "bad URL not caught"
        assert app.mode == "enter-url", "did not re-ask after a bad URL"
        await pilot.press("escape"); await pilot.pause()
        assert app.mode == "normal"

        # chat round-trip: thinking hidden, streaming, timing footer
        from cutecat.app import FOOTER_VERBS, THINKING_VERBS
        await submit(app, pilot, "hi there")
        assert app.indicator.display is True, "indicator not shown while working"
        ind = text_of(app.indicator)
        assert any(verb in ind for verb in THINKING_VERBS), ind
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.messages[-1]["role"] == "assistant"
        assert app.messages[-1]["content"].startswith("Hello **world**")
        # assistant reply renders as a selectable Markdown widget (Textual can
        # select those; Rich renderables come back empty)
        from textual.widgets import Markdown as _MD
        assert len(app.chat.query(_MD)) > 0, "assistant reply is not a Markdown widget"
        assert any(t.startswith("❯ hi there") for t in chat_texts(app))
        assert not any("let me think" in t for t in chat_texts(app)), "thinking text leaked"
        assert any(
            any(t.startswith(verb + " ") or t.startswith(verb) for verb in FOOTER_VERBS)
            and t.rstrip().endswith("s")
            for t in chat_texts(app)
        ), "no timing footer"
        assert app._timer is None, "indicator timer not stopped"
        assert app.indicator.display is False, "indicator still visible"
        assert not any("responding" in t for t in chat_texts(app)), (
            "indicator leaked into chat"
        )

        # the first message generates a terminal-tab title from that message
        assert await wait_for(pilot, lambda: app._chat_title == "Fix The Widget"), (
            f"title not generated: {app._chat_title!r}"
        )
        # set_terminal_title emits the cross-platform OSC 0 sequence
        osc = []
        real_driver = app._driver
        app._driver = type(
            "D", (), {"write": lambda s, d: osc.append(d), "flush": lambda s: None}
        )()
        app.set_terminal_title("hello tab")
        app._driver = real_driver
        assert "\x1b]0;hello tab\x07" in osc, osc          # OSC 0 title
        assert any(s.startswith("\x1b]7;") for s in osc)   # OSC 7 cwd clear
        # _clean_title trims quotes/punctuation
        from cutecat.app import _clean_title
        assert _clean_title('  "Do The Thing."  ') == "Do The Thing"

        # agent system prompt is sent as the first message, tools are attached
        sent_messages = FakeProvider.last_messages
        assert sent_messages[0]["role"] == "system", sent_messages[0]
        assert "agent" in sent_messages[0]["content"], "agent prompt missing"
        assert sent_messages[1] == {"role": "user", "content": "hi there"}
        assert FakeProvider.last_tools is not None, "tools not sent to provider"
        names = {t["function"]["name"] for t in FakeProvider.last_tools}
        assert {"run_command", "create_file"} <= names, names

        import os as _os
        import tempfile as _tf
        # /tmp paths are fine for the *action* tests below because the tmp
        # gate is granted (and cached) by the dedicated tmp test first.
        workdir = Path(_tf.mkdtemp())

        # --- read-only command auto-runs (no permission) ---
        FakeProvider.scripted_turns = [
            [("content", "let me check"),
             ("tool_call", {"name": "run_command",
                            "arguments": {"command": "echo tool-output-123"}})],
            [("content", "the answer is 123")],
        ]
        await submit(app, pilot, "run a command")
        assert await wait_for(pilot, lambda: not app._busy), "agent loop stuck"
        assert app.mode == "normal", "read-only command should not prompt"
        # output is NOT dumped into the chat: it's a collapsed, clickable entry
        from textual.widgets import Collapsible as _Col
        cols = list(app.chat.query(_Col))
        assert cols, "command not shown as a collapsible"
        cmd_col = cols[-1]
        assert "echo tool-output-123" in cmd_col.title and "exit 0" in cmd_col.title, cmd_col.title
        assert cmd_col.collapsed is True, "command output should start collapsed"
        body = text_of(cmd_col.query_one(Static))
        assert "tool-output-123" in body, f"output not in collapsible: {body!r}"
        assert app.messages[-1]["content"] == "the answer is 123"
        roles = [m["role"] for m in app.messages]
        assert "tool" in roles, roles
        assert "tool-output-123" in next(m for m in app.messages if m["role"] == "tool")["content"]

        # --- long command: NO timeout, esc terminates it, agent carries on ---
        FakeProvider.scripted_turns = [
            [("tool_call", {"name": "run_command", "arguments": {"command": "sleep 60"}})],
            [("content", "stopped ok")],
        ]
        await submit(app, pilot, "long one")
        assert await wait_for(pilot, lambda: app._running_job is not None), "job never ran"
        await pilot.pause()
        assert app._busy and app._running_job.running, "should still be running (no timeout)"
        app.action_cancel()  # esc stops just this command
        assert await wait_for(pilot, lambda: not app._busy), "esc did not stop the command"
        assert app.messages[-1]["content"] == "stopped ok", "agent did not continue after stop"

        # --- ctrl+b backgrounds a command; agent keeps working ---
        FakeProvider.scripted_turns = [
            [("tool_call", {"name": "run_command",
                            "arguments": {"command": "sleep 1; echo BGRESULT"}})],
            [("content", "carried on")],
        ]
        await submit(app, pilot, "background one")
        assert await wait_for(pilot, lambda: app._running_job is not None)
        app.action_background_command()
        assert await wait_for(pilot, lambda: not app._busy), "agent stuck after backgrounding"
        assert app.messages[-1]["content"] == "carried on", "agent did not continue"
        # its output is delivered to the agent once it finishes
        assert await wait_for(
            pilot,
            lambda: any("BGRESULT" in str(m.get("content", "")) for m in app.messages),
            600,
        ), "background result never delivered"

        # --- /tmp access is gated once per session, then cached ---
        assert app._tmp_granted is False
        FakeProvider.scripted_turns = [
            [("tool_call", {"name": "run_command",
                            "arguments": {"command": "ls /tmp"}})],
            [("content", "listed tmp")],
        ]
        await submit(app, pilot, "list tmp")
        assert await wait_for(pilot, lambda: app.mode == "choice"), "no tmp prompt"
        # prompt is a popup, NOT a chat message
        assert app.query_one("#popup").display is True, "popup not shown"
        assert "temp directory" in popup_text(app), "not a tmp prompt"
        assert not any("temp directory" in t for t in chat_texts(app)), "prompt leaked to chat"
        await pilot.press("y")
        assert await wait_for(pilot, lambda: not app._busy)
        assert app.query_one("#popup").display is False, "popup not hidden after answer"
        assert app._tmp_granted is True, "tmp grant not cached"
        # a second /tmp read must NOT ask again
        FakeProvider.scripted_turns = [
            [("tool_call", {"name": "run_command",
                            "arguments": {"command": "ls /tmp"}})],
            [("content", "again")],
        ]
        await submit(app, pilot, "list tmp again")
        assert await wait_for(pilot, lambda: not app._busy)
        assert app.mode == "normal", "tmp re-asked despite cached grant"

        # --- action command asks permission; granting runs it ---
        marker = str(workdir / "made_by_agent.txt")
        _os.path.exists(marker) and _os.remove(marker)
        FakeProvider.scripted_turns = [
            [("tool_call", {"name": "run_command",
                            "arguments": {"command": f"touch {marker}"}})],
            [("content", "created it")],
        ]
        await submit(app, pilot, "make a file")
        assert await wait_for(pilot, lambda: app.mode == "choice"), "no permission prompt"
        assert "touch" in popup_text(app), "command not shown in popup"
        assert "allow" in popup_text(app) and "deny" in popup_text(app), "options missing"
        assert not _os.path.exists(marker), "ran before permission granted"
        await pilot.press("y")
        assert await wait_for(pilot, lambda: not app._busy), "agent stuck after grant"
        assert _os.path.exists(marker), "command did not run after grant"
        _os.remove(marker)

        # --- denying permission blocks the command ---
        marker2 = str(workdir / "should_not_exist.txt")
        FakeProvider.scripted_turns = [
            [("tool_call", {"name": "run_command",
                            "arguments": {"command": f"touch {marker2}"}})],
            [("content", "ok, skipped")],
        ]
        await submit(app, pilot, "make another file")
        assert await wait_for(pilot, lambda: app.mode == "choice"), "no permission prompt"
        await pilot.press("n")
        assert await wait_for(pilot, lambda: not app._busy)
        assert not _os.path.exists(marker2), "command ran despite denial"
        assert any(
            m["role"] == "tool" and "denied" in m["content"] for m in app.messages
        ), "denial not recorded"

        # --- create_file tool always asks, then writes real content ---
        made = workdir / "hello_agent.py"
        made.exists() and made.unlink()
        FakeProvider.scripted_turns = [
            [("tool_call", {"name": "create_file",
                            "arguments": {"path": str(made), "content": "print('hi')\n"}})],
            [("content", "wrote it")],
        ]
        await submit(app, pilot, "write hello.py")
        assert await wait_for(pilot, lambda: app.mode == "choice"), "create_file did not ask"
        await pilot.press("y")
        assert await wait_for(pilot, lambda: not app._busy)
        assert made.read_text() == "print('hi')\n", "file content wrong"

        # --- edit_file: surgical edit shows a colored diff, then applies ---
        from cutecat.app import DiffBlock
        from textual.events import MouseMove
        edit_target = workdir / "prog.py"
        edit_target.write_text("def add(a, b):\n    return a + b\nprint(add(1, 2))\n")
        FakeProvider.scripted_turns = [
            [("tool_call", {"name": "edit_file", "arguments": {
                "path": str(edit_target),
                "old_string": "    return a + b",
                "new_string": "    result = a + b\n    return result"}})],
            [("content", "done editing")],
        ]
        diffs_before = len(app.chat.query(DiffBlock))
        await submit(app, pilot, "edit prog.py")
        assert await wait_for(pilot, lambda: app.mode == "choice"), "edit did not ask"
        # a diff preview is shown (a DiffBlock), NOT a whole-file rewrite
        diffs = app.chat.query(DiffBlock)
        assert len(diffs) == diffs_before + 1, "no diff preview shown"
        diff = diffs.last()
        assert diff.styles.margin.left == 3, f"diff not indented: {diff.styles.margin}"
        del_rows = list(diff.query(".diff-del"))
        add_rows = list(diff.query(".diff-add"))
        assert del_rows and add_rows, "diff missing add/del rows"
        assert (del_rows[0].styles.background.r, del_rows[0].styles.background.g,
                del_rows[0].styles.background.b) == (0x3D, 0x01, 0x00), "wrong removed bg"
        assert (add_rows[0].styles.background.r, add_rows[0].styles.background.g,
                add_rows[0].styles.background.b) == (0x02, 0x28, 0x00), "wrong added bg"
        # diff code is syntax-highlighted (colored spans) on top of the row bg
        add_code = add_rows[0].query_one(".diff-code", Static).render()
        add_colors = {
            str(sp.style).split(" on ")[0].strip()
            for sp in getattr(add_code, "spans", [])
            if str(sp.style).split(" on ")[0].strip().startswith("rgb")
        }
        assert len(add_colors) >= 2, f"diff code not syntax highlighted: {add_colors}"
        assert edit_target.read_text().count("result") == 0, "edited before approval"
        # the first edit prompt offers "allow all edits" — choose it
        assert "allow all edits" in popup_text(app), "no allow-all option"
        assert app._allow_all_edits is False
        await pilot.press("a")
        assert await wait_for(pilot, lambda: not app._busy)
        assert "result = a + b" in edit_target.read_text(), "edit not applied"
        assert app._allow_all_edits is True, "allow-all not remembered"
        assert app.messages[-1]["content"] == "done editing"

        # a subsequent edit must apply WITHOUT asking
        FakeProvider.scripted_turns = [
            [("tool_call", {"name": "edit_file", "arguments": {
                "path": str(edit_target),
                "old_string": "print(add(1, 2))",
                "new_string": "print(add(10, 20))"}})],
            [("content", "and again")],
        ]
        await submit(app, pilot, "another edit")
        assert await wait_for(pilot, lambda: not app._busy), "second edit stuck"
        assert app.mode == "normal", "asked again despite allow-all"
        assert "add(10, 20)" in edit_target.read_text(), "second edit not applied"
        app._allow_all_edits = False  # reset so later tests are unaffected

        # selecting the diff copies clean code — no line numbers or +/- markers
        code_cells = list(diff.query(".diff-code"))
        diff.scroll_visible(animate=False); await pilot.pause()
        c0 = code_cells[0].region
        assert 0 <= c0.y < app.size.height
        await pilot.mouse_down(offset=(c0.x, c0.y))
        await pilot._post_mouse_events([MouseMove], offset=(min(c0.x + 15, app.size.width - 1), c0.y + 1), button=1)
        await pilot.mouse_up(offset=(min(c0.x + 15, app.size.width - 1), c0.y + 1))
        await pilot.pause()
        dsel = app.screen.get_selected_text() or ""
        assert not any(ln[:1] in "+-" or ln[:1].isdigit() for ln in dsel.split("\n") if ln), (
            f"diff markers/numbers leaked into selection: {dsel!r}"
        )
        app.screen.clear_selection()

        made.unlink()
        FakeProvider.scripted_turns = []  # back to default reply for later tests

        # session file persisted with the conversation (incl. tool messages)
        session_file = config_mod.SESSIONS_DIR / f"{app.session_id}{config_mod.SESSION_EXT}"
        assert session_file.exists(), "session not saved"
        saved = config_mod.load_session(app.session_id)
        assert saved is not None, "session did not load back"
        assert any(
            m.get("content", "").startswith("Hello **world**") for m in saved["messages"]
        )
        assert any(m["role"] == "tool" for m in saved["messages"]), "tool msgs not saved"
        assert "hi there" in saved["input_history"]
        assert saved["messages"][0]["role"] == "user", "system prompt must not be persisted"
        # slash commands are recallable in-session but never written to the file:
        # they aren't part of the conversation and only bloat it
        assert "/help" in app.input.input_history, "command not recallable with up"
        assert not [h for h in saved["input_history"] if h.startswith("/")], (
            f"commands persisted: {saved['input_history']}"
        )

        # top bar: session tokens at top-left, sent vs reply SEPARATELY (the
        # session id is printed on exit instead); cwd shown in the welcome
        app_name = app.query_one("#app-name", Static)
        assert "sent" in text_of(app_name) and "reply" in text_of(app_name), text_of(app_name)
        # the welcome collapses $HOME to ~, so match the displayed form
        _home = os.path.expanduser("~")
        _shown = ("~" + app.cwd[len(_home):]
                  if app.cwd == _home or app.cwd.startswith(_home + os.sep)
                  else app.cwd)
        assert any(_shown in t for t in chat_texts(app)), "cwd not shown in welcome"

        # tokens: the header shows the two running counts, saved/restored
        app._add_tokens(2100, 340)
        header = text_of(app_name)
        assert "↑2.1k sent" in header and "↓340 reply" in header, header
        assert app._fmt_tokens(999) == "999" and app._fmt_tokens(2400) == "2.4k"
        assert app._fmt_tokens(1_500_000) == "1.50M"
        # the count is persisted, and on exit a resume line is prepared
        app._save_session()
        saved2 = config_mod.load_session(app.session_id)
        assert saved2.get("tokens_in") == app._tok_in, saved2
        assert app.messages, "no messages to make a resume line from"

        # text selection: dragging over on-screen text selects it, and the
        # selection highlight is a visible inverse (white bg / black fg)
        # code blocks: line-number gutter that is NOT copied, no background
        from cutecat.app import CuteFence, _CodeGutter
        from textual.events import MouseMove
        md = app._make_assistant_widget("```python\na = 1\nb = 2\nprint(a+b)\n```")
        assert await wait_for(pilot, lambda: bool(md.query(CuteFence))), "fence not rendered"
        fence = md.query_one(CuteFence)
        assert fence.styles.margin.left == 3, f"code not indented: {fence.styles.margin}"
        gutter = fence.query_one(_CodeGutter)
        assert fence._gutter() == "1\n2\n3", repr(fence._gutter())
        assert gutter.ALLOW_SELECT is False, "gutter must be unselectable"
        bg = fence.styles.background
        assert bg.a == 0, f"code block has a background: {bg}"
        code_body = fence.query_one(".cf-code", Static)
        code_body.scroll_visible(animate=False); await pilot.pause()
        cr = code_body.region
        assert 0 <= cr.y < app.size.height, f"code not visible: {cr}"
        x1 = min(cr.x + 12, app.size.width - 1)
        y1 = min(cr.y + 2, app.size.height - 2)
        await pilot.mouse_down(offset=(cr.x, cr.y))
        await pilot._post_mouse_events([MouseMove], offset=(x1, y1), button=1)
        await pilot.mouse_up(offset=(x1, y1))
        await pilot.pause()
        picked = app.screen.get_selected_text()
        assert picked and "a = 1" in picked, f"code not selectable: {picked!r}"
        # clean code lines start with a/b/p — a leaked gutter would prefix a digit
        assert not any(ln[:1].isdigit() for ln in picked.split("\n") if ln), (
            f"line numbers leaked into selection: {picked!r}"
        )
        md.remove(); await pilot.pause()
        app.screen.clear_selection()

        from cutecat.app import CUTECAT_THEMES
        assert app.ALLOW_SELECT is True
        assert CUTECAT_THEMES["dark"].variables["screen-selection-background"] == "#ffffff"
        from textual.events import MouseMove
        app.chat.scroll_home(animate=False)
        await pilot.pause()
        w = app.chat.query(Static)[0]  # welcome, now visible at the top
        row = w.region.y
        assert 0 <= row < app.size.height, f"widget not visible: row {row}"
        await pilot.mouse_down(offset=(w.region.x + 1, row))
        await pilot._post_mouse_events([MouseMove], offset=(w.region.x + 6, row), button=1)
        await pilot.mouse_up(offset=(w.region.x + 6, row))
        await pilot.pause()
        assert app.screen.get_selected_text(), "drag did not select any text"

        # ctrl+shift+c copies the current screen selection to the system
        # clipboard (via cutecat.clipboard.copy, not the terminal-only OSC 52)
        from cutecat import clipboard as clipmod
        copied = []
        clipmod.copy = lambda text: (copied.append(text) or True)
        app.screen.get_selected_text = lambda: "selected sample"
        await pilot.press("ctrl+shift+c")
        await pilot.pause()
        assert copied == ["selected sample"], copied
        # ctrl+c must copy too (not quit) — terminals fold ctrl+shift+c into it
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert app.is_running, "ctrl+c quit the app"
        assert copied == ["selected sample", "selected sample"], copied

        # paste collapsing: shown as a placeholder, sent as the real text
        app.input.focus()  # the drag-select test above moved focus to the chat
        await pilot.pause()
        before = len(app.messages)
        app.input.post_message(events.Paste("l1\nl2\nl3\nl4"))
        await pilot.pause()
        assert "[pasted 4 lines]" in app.input.text, repr(app.input.text)
        await pilot.press("enter")
        assert await wait_for(pilot, lambda: len(app.messages) > before and not app._busy)
        sent = next(m["content"] for m in reversed(app.messages) if m["role"] == "user")
        assert "l1\nl2\nl3\nl4" in sent, repr(sent)
        assert "[pasted" not in sent, repr(sent)

        # pasting inserts the text exactly once. Textual dispatches Paste to
        # every _on_paste in the MRO, so deferring to super() used to make
        # TextArea insert it a second time (short pastes only).
        app.input.set_text("")
        app.input.focus()
        await pilot.pause()
        app.input.post_message(events.Paste("hello"))
        await pilot.pause()
        assert app.input.text == "hello", f"paste duplicated: {app.input.text!r}"
        app.input.post_message(events.Paste(" world"))
        await pilot.pause()
        assert app.input.text == "hello world", repr(app.input.text)
        # a multi-line paste still collapses to a placeholder, also exactly once
        app.input.set_text("")
        await pilot.pause()
        app.input.post_message(events.Paste("a\nb\nc\nd"))
        await pilot.pause()
        assert app.input.text == "[pasted 4 lines]", repr(app.input.text)
        assert app.input.resolve_pastes(app.input.text) == "a\nb\nc\nd"
        app.input.set_text("")
        await pilot.pause()

        # no scrollbar on the chat or the input — but they still scroll
        assert app.chat.styles.scrollbar_size_vertical == 0, "chat scrollbar back"
        assert app.input.styles.scrollbar_size_vertical == 0, "input scrollbar back"

        # jump pills: hidden at the bottom, shown when scrolled up
        app.input.focus(); await pilot.pause()
        assert app.query_one("#overlay-bottom").display is False, "pill shown at bottom"
        # add enough content to make the chat scrollable, then scroll up
        for i in range(15):
            app.add_msg(f"filler line {i}\nmore\nmore", "system")
        await pilot.pause()
        app.chat.scroll_to(y=0, animate=False)
        await pilot.pause(); await pilot.pause()
        jb = app.query_one("#jump-bottom")
        assert app.query_one("#overlay-bottom").display is True, "no jump-to-bottom pill"
        assert "Jump to the bottom" in text_of(jb)
        # background is on the text only (pill has auto width + grey bg)
        assert str(jb.styles.width) == "auto", jb.styles.width
        bg = jb.styles.background
        assert bg.r == bg.g == bg.b and bg.a != 0, f"pill has no grey bg: {bg}"
        # jump-prev shows the previous user input; both go away at the bottom
        assert app.query_one("#overlay-top").display is True, "no previous-input pill"
        assert text_of(app.query_one("#jump-prev")).startswith("↑"), "no prev preview"
        app.action_jump_bottom()  # animated: the pill hides once it lands
        assert await wait_for(
            pilot, lambda: app.query_one("#overlay-bottom").display is False
        ), "pill stuck after jump"

        # /clear
        await submit(app, pilot, "/clear")
        assert app.messages == []
        assert has_cat(app), "welcome not restored"

        # history recall at boundaries: up on first line -> older entries
        await pilot.press("up")
        assert app.input.text == "/clear", repr(app.input.text)
        await pilot.press("up")
        assert "l1" in app.input.text, "multiline paste entry not recalled"
        # down on last line -> newer entry
        await pilot.press("down")
        assert app.input.text == "/clear"
        await pilot.press("down")
        assert app.input.text == "", "draft not restored"

        # the selection must stay visible however far you scroll, and every
        # picker must be searchable
        from textual.widgets import OptionList as _OL2
        many = [(f"model-{i:03d}", f"model-{i:03d}") for i in range(60)]
        app._open_picker("many", many, lambda v: None)
        await pilot.pause()
        picker = app.query_one("#picker-list", _OL2)

        def highlight_visible() -> bool:
            """Is the highlighted row inside the scrolled viewport? (Textual maps
            an option index to its content line in _index_to_line.)"""
            idx = picker.highlighted
            picker._update_lines()
            line = picker._index_to_line[idx]
            height = picker._heights[idx]
            top = picker.scroll_offset.y
            bottom = top + picker.scrollable_content_region.height
            return top <= line and line + height <= bottom

        # the list must FIT inside the picker's box. If it doesn't, the
        # container clips the bottom rows — and Textual still calls them
        # "scrolled into view", because they are visible inside the *list*.
        box = app.query_one("#picker")
        assert picker.region.bottom <= box.content_region.bottom, (
            f"the list is clipped by its container: list ends at "
            f"{picker.region.bottom}, box content ends at {box.content_region.bottom}"
        )
        assert box.region.bottom <= app.size.height, "the picker runs off the screen"

        def drawn(idx: int) -> bool:
            """Is option `idx` actually painted on screen right now?"""
            picker._update_lines()
            y = picker.region.y + (picker._index_to_line[idx] - picker.scroll_offset.y)
            return picker.region.y <= y < picker.region.bottom

        for _ in range(50):                     # far down
            await pilot.press("down")
        await pilot.pause()
        assert picker.highlighted == 50, picker.highlighted
        assert highlight_visible(), "selection scrolled out of view going down"
        assert drawn(picker.highlighted), "the selected row is not painted on screen"

        for _ in range(9):                      # all the way to the last option
            await pilot.press("down")
        await pilot.pause()
        assert picker.highlighted == 59
        assert drawn(59), "the last option is not painted (clipped by the box)"
        # at the bottom, DOWN does NOT wrap back to the top — it stays put
        for _ in range(5):
            await pilot.press("down")
        await pilot.pause()
        assert picker.highlighted == 59, "the list wrapped around at the bottom"
        for _ in range(59):                     # and all the way back up
            await pilot.press("up")
        await pilot.pause()
        assert picker.highlighted == 0
        assert highlight_visible(), "selection scrolled out of view going up"
        assert drawn(0), "the first option is not painted"
        # at the top, UP does NOT wrap to the bottom either
        for _ in range(5):
            await pilot.press("up")
        await pilot.pause()
        assert picker.highlighted == 0, "the list wrapped around at the top"

        # the mouse wheel moves the selection, so it can never drift off-screen
        await pilot.hover("#picker-list")
        for _ in range(20):
            await pilot.press("down")           # somewhere in the middle
        before = picker.highlighted
        wheel = events.MouseScrollDown(
            widget=picker, x=1, y=1, delta_x=0, delta_y=1, button=0,
            shift=False, meta=False, ctrl=False,
        )
        picker.post_message(wheel)
        await pilot.pause()
        assert picker.highlighted == before + 1, "the wheel scrolled without the selection"
        assert highlight_visible(), "wheel left the selection off-screen"

        # search: type to filter, enter chooses from what's left
        for ch in "042":
            await pilot.press(ch)
        await pilot.pause()
        assert app._picker_values == ["model-042"], app._picker_values
        assert picker.highlighted == 0, "highlight not reset onto the match"
        await pilot.press("escape")
        await pilot.pause()
        assert app.mode == "normal"

        # the status indicator stays up for the WHOLE turn: it used to be
        # switched off when a command finished, so while the agent went back to
        # the model (and streamed its reply) nothing showed it was still busy
        seen = []
        real_finish = app._cmd_finish

        def spy_finish(job, state):
            real_finish(job, state)
            seen.append(("after command", app.indicator.display, app._timer is not None))

        app._cmd_finish = spy_finish
        FakeProvider.scripted_turns = [
            [("tool_call", {"name": "run_command",
                            "arguments": {"command": "echo one"}})],
            [("content", "all done")],
        ]
        await submit(app, pilot, "run something")
        assert await wait_for(pilot, lambda: not app._busy, tries=400), "turn never ended"
        app._cmd_finish = real_finish
        assert seen, "the command never finished"
        for label, shown, ticking in seen:
            assert shown, f"indicator hidden {label} while the agent was still working"
            assert ticking, f"indicator timer stopped {label} (streaming would freeze)"
        # and it does go away once the turn is actually over
        assert app.indicator.display is False, "indicator left on after the turn"
        assert app._timer is None
        assert app.messages[-1]["content"] == "all done"
        FakeProvider.scripted_turns = []


        # monochrome audit: every widget's resolved color/background is greyscale
        # (syntax highlighting inside code lives in widget *content*, not styles)
        bad = []
        for w in app.query("*"):
            for attr in ("color", "background"):
                c = getattr(w.styles, attr, None)
                if c is not None and not (c.r == c.g == c.b):
                    bad.append((w, attr, c))
        assert not bad, f"non-grey widget styles: {bad}"

        # duration formatting
        from cutecat.app import fmt_duration
        assert fmt_duration(5) == "5s"
        assert fmt_duration(130) == "2m 10s"
        assert fmt_duration(3725) == "1h 02m 05s"

    # ---------------- second app: session isolation + skills ----------------
    config_mod.SKILLS_DIR.mkdir(exist_ok=True)
    (config_mod.SKILLS_DIR / "brief.md").write_text("Be extremely brief.")
    (config_mod.SKILLS_DIR / "pirate.md").write_text("Always talk like a pirate.")

    app2 = CuteCatApp()
    async with app2.run_test(size=(90, 32)) as pilot:
        assert app2.session_id != app.session_id, "session id not fresh"
        assert app2.input.input_history == [], "input history leaked across sessions"

        # /skills is a searchable checklist: type to filter, enter toggles,
        # esc closes
        from textual.widgets import OptionList as _OL

        def labels(app):
            """What each row actually PAINTS. A plain-str prompt goes through
            Textual's markup parser, which eats "[x]" as a tag — so asserting on
            str(prompt) would have passed while the screen showed no checkbox."""
            from rich.text import Text as _Text
            from textual.content import Content

            ol = app.query_one("#picker-list", _OL)
            out = []
            for i in range(ol.option_count):
                prompt = ol.get_option_at_index(i).prompt
                out.append(
                    prompt.plain if isinstance(prompt, _Text)
                    else Content.from_markup(str(prompt)).plain
                )
            return out

        # the guard: a raw string really would lose the tick
        from textual.content import Content as _Content
        assert _Content.from_markup("[x] skill").plain != "[x] skill", (
            "markup no longer eats [x] — the Text() wrapper may be unnecessary"
        )

        await submit(app2, pilot, "/skills")
        assert app2.mode == "pick", "/skills did not open the scrollable picker"
        ol = app2.query_one("#picker-list", _OL)
        assert "[ ] pirate" in labels(app2) and "[ ] brief" in labels(app2), labels(app2)

        # typing filters the list
        for ch in "pir":
            await pilot.press(ch)
        await pilot.pause()
        assert app2._picker_filter == "pir"
        assert labels(app2) == ["[ ] pirate"], labels(app2)
        assert "search: pir" in text_of(app2.query_one("#picker-search"))

        await pilot.press("enter")           # enter toggles, list stays open
        await pilot.pause()
        assert config_mod.load_config()["skills"]["pirate"] is True, "enter did not enable"
        assert labels(app2) == ["[x] pirate"], labels(app2)
        assert app2.mode == "pick", "the list closed on enter"

        await pilot.press("enter")           # and off again
        await pilot.pause()
        assert config_mod.load_config()["skills"]["pirate"] is False
        assert labels(app2) == ["[ ] pirate"]
        await pilot.press("enter")           # leave it on

        # backspace clears the search and the tick survives the rebuild
        for _ in range(3):
            await pilot.press("backspace")
        await pilot.pause()
        assert app2._picker_filter == ""
        assert "[x] pirate" in labels(app2), labels(app2)
        assert "[ ] brief" in labels(app2), "the other skills came back"

        # a search that matches nothing says so, rather than looking broken
        for ch in "zzz":
            await pilot.press(ch)
        await pilot.pause()
        assert labels(app2) == [], labels(app2)
        assert "no matches" in text_of(app2.query_one("#picker-search"))
        await pilot.press("ctrl+u")           # clear the search
        await pilot.pause()
        assert app2._picker_filter == "" and len(labels(app2)) > 1

        await pilot.press("escape")           # esc closes and reports
        await pilot.pause()
        assert app2.mode == "normal", "esc did not close the checklist"
        assert config_mod.load_config()["skills"]["pirate"] is True, "toggle not kept"
        assert any("skills on: pirate" in t for t in chat_texts(app2))

        # typing in the chat is unaffected (the picker only grabs keys when open)
        app2.input.set_text("")
        app2.input.focus()
        await pilot.pause()
        for ch in ("a", "space", "b"):
            await pilot.press(ch)
        await pilot.pause()
        assert app2.input.text == "a b", repr(app2.input.text)
        app2.input.set_text("")

        await submit(app2, pilot, "ahoy")
        await app2.workers.wait_for_complete()
        await pilot.pause()
        sysmsg = FakeProvider.last_messages[0]["content"]
        assert "skill: pirate" in sysmsg, "enabled skill not in system prompt"
        assert "talk like a pirate" in sysmsg
        assert "skill: brief" not in sysmsg, "disabled skill leaked into prompt"
    sid2 = app2.session_id

    # ---------------- third app: --resume ----------------
    resolved = config_mod.resolve_session(sid2[:8])
    assert resolved == sid2, f"prefix resolution failed: {resolved}"
    loaded = config_mod.load_session(resolved)
    app3 = CuteCatApp(session=loaded)
    async with app3.run_test(size=(90, 32)) as pilot:
        assert app3.session_id == sid2
        assert app3.messages[-1]["role"] == "assistant"
        assert any(t.startswith("❯ ahoy") for t in chat_texts(app3)), (
            "resumed messages not re-rendered"
        )
        assert any("resumed" in t for t in chat_texts(app3))
        # the title generated in the earlier session is restored (not regenerated)
        assert app3._chat_title == "Fix The Widget", app3._chat_title
        assert app3._title_started is True
        await pilot.press("up")
        assert app3.input.text == "ahoy", "resumed input history not recalled"

    # ---------------- fourth app: slash commands, / preview, themes ----------
    from cutecat.app import COMMANDS
    app4 = CuteCatApp()
    async with app4.run_test(size=(90, 30)) as pilot:
        app4.cfg = {"provider": "fake", "api_key": "good-key", "model": "maxi-model",
                    "skills": {}, "theme": "dark"}
        pv = app4.query_one("#cmdpreview", Static)

        # `/` shows a live command preview, filtering as you type
        app4.input.set_text("/"); await pilot.pause()
        assert pv.display is True and "/theme" in text_of(pv), "no command preview"
        app4.input.set_text("/th"); await pilot.pause()
        assert "/theme" in text_of(pv) and "/connect" not in text_of(pv), "preview not filtered"
        app4.input.set_text(""); await pilot.pause()
        assert pv.display is False, "preview not hidden when empty"

        # Tab completes a partial command
        app4.input.set_text("/mod"); await pilot.press("tab"); await pilot.pause()
        assert app4.input.text == "/model ", repr(app4.input.text)
        app4.input.set_text("/s"); await pilot.press("tab"); await pilot.pause()
        assert app4.input.text == "/s", "ambiguous prefix should not over-complete"
        app4.input.set_text(""); await pilot.pause()

        # /theme opens a scrollable picker: arrow-navigate, enter to choose
        from textual.widgets import OptionList as _OL
        await submit(app4, pilot, "/theme")
        assert app4.mode == "pick" and app4.query_one("#picker").display is True
        from cutecat.app import PALETTE
        ol = app4.query_one("#picker-list", _OL)
        assert ol.has_focus and ol.option_count == len(CuteCatApp.THEME_CHOICES)
        assert ol.option_count >= 18, "the extra themes aren't in the picker"

        # LIVE PREVIEW: moving the highlight applies the theme instantly
        await submit(app4, pilot, "/theme dark")   # a known starting point
        await submit(app4, pilot, "/theme")        # open the picker
        ol = app4.query_one("#picker-list", _OL)
        red = app4._picker_values.index("hacker-red")
        ol.highlighted = red
        await pilot.pause()
        assert app4._mode == "hacker-red", "preview did not apply on highlight"
        assert app4.c("strong") == "#ff2b2b", "hacker-red is not red"
        # ...but it's only a preview until you commit — nothing saved yet
        assert config_mod.load_config()["theme"] != "hacker-red", "preview saved early"
        # ESC reverts to what was active before opening the picker
        await pilot.press("escape"); await pilot.pause()
        assert app4._mode == "dark", "esc did not revert the preview"

        # ENTER commits the highlighted theme and saves it
        await submit(app4, pilot, "/theme")
        ol = app4.query_one("#picker-list", _OL)
        ol.highlighted = app4._picker_values.index("matrix")
        await pilot.pause()
        await pilot.press("enter"); await pilot.pause()
        assert app4._mode == "matrix" and app4._dark is True
        assert app4.c("strong").lower() == "#00ff41" and app4.c("bg") == "#000000"
        assert config_mod.load_config()["theme"] == "matrix", "matrix not persisted"

        # every choice (except 'system') maps to a real palette
        for name in CuteCatApp.THEME_CHOICES:
            assert name == "system" or name in PALETTE, f"no palette for {name}"

        # the theme set: many themes, at least 6 light, no plain colour names,
        # catppuccin present
        from cutecat.app import LIGHT_THEMES
        assert len(PALETTE) >= 29, f"only {len(PALETTE)} themes"
        assert len(LIGHT_THEMES) >= 6, f"only {len(LIGHT_THEMES)} light themes"
        assert not ({"pink", "purple", "cyan", "blue", "amber"} & set(PALETTE)), \
            "a plain colour name is still a theme"
        assert "catppuccin" in PALETTE and "catppuccin-latte" in PALETTE
        assert "hacker-red" in PALETTE and PALETTE["hacker-red"]["strong"] == "#ff2b2b"

        # the 'default' theme rides the terminal's own colours (ANSI, not hex),
        # and c() maps the ANSI names to Rich's spelling for Rich Text.
        assert "default" in PALETTE
        assert PALETTE["default"]["bg"] == "ansi_default"
        await submit(app4, pilot, "/theme default")
        assert app4._mode == "default", "default theme not applied"
        assert app4.c("text") == "default", "ANSI name not mapped for Rich"
        assert app4.c("muted") == "bright_black"
        from rich.text import Text as _RT   # the mapped colours must be valid Rich styles
        _RT("x", style=app4.c("text")); _RT("y", style=f"bold {app4.c('strong')}")
        await submit(app4, pilot, "/theme dark")

        # a light theme previews too (light background applied instantly)
        await submit(app4, pilot, "/theme")
        ol = app4.query_one("#picker-list", _OL)
        ol.highlighted = app4._picker_values.index("catppuccin-latte")
        await pilot.pause()
        assert app4._dark is False, "a light theme did not flip to a light UI"
        assert app4._mode == "catppuccin-latte"
        await pilot.press("escape"); await pilot.pause()   # revert

        # /theme <name> also works directly; a bad name is rejected
        await submit(app4, pilot, "/theme dracula")
        assert app4._mode == "dracula"
        await submit(app4, pilot, "/theme rainbow")
        assert app4._mode == "dracula", "a bad theme name changed the theme"

        # a theme change adds NO note to the chat — only the echoed command line,
        # never a "theme: …" confirmation. The recolour is the feedback.
        before_theme = len(chat_texts(app4))
        await submit(app4, pilot, "/theme dracula")
        assert app4._mode == "dracula"
        after_theme = chat_texts(app4)
        # exactly one new line, and it's the echoed command — not a "theme:" note
        assert len(after_theme) == before_theme + 1, "a theme change logged a note"
        assert after_theme[-1].startswith("❯ /theme"), "unexpected line after /theme"

        await submit(app4, pilot, "/theme dark")
        # esc cancels an open picker
        await submit(app4, pilot, "/theme")
        await pilot.press("escape"); await pilot.pause()
        assert app4.query_one("#picker").display is False and app4.mode == "normal"

        # /config opens config.json in an editor; a valid edit is saved (through
        # the encrypting writer) and applied live. A fake editor stands in.
        import contextlib as _cl
        import json as _json
        import subprocess as _sp
        app4.cfg["theme"] = "dark"
        config_mod.save_config(app4.cfg)
        _orig_editor, _orig_suspend, _orig_run = (
            app4._editor_command, app4.suspend, _sp.run)
        app4._editor_command = lambda: ["true"]
        app4.suspend = lambda: _cl.nullcontext()
        try:
            def _fake_edit(cmd, *a, **k):   # rewrite the temp file the editor was handed
                path = cmd[-1]
                data = _json.loads(open(path).read())
                data["theme"] = "matrix"
                open(path, "w").write(_json.dumps(data, indent=2))
            _sp.run = _fake_edit
            await submit(app4, pilot, "/config")
            await pilot.pause()
            assert config_mod.load_config().get("theme") == "matrix", "/config did not save"
            assert app4._mode == "matrix", "/config did not apply the edit live"
            assert any("config saved" in t for t in chat_texts(app4)), "no 'config saved' note"

            # invalid JSON is refused, the old config kept
            _sp.run = lambda cmd, *a, **k: open(cmd[-1], "w").write("{ not valid json ")
            await submit(app4, pilot, "/config")
            await pilot.pause()
            assert config_mod.load_config().get("theme") == "matrix", "bad JSON overwrote config"
            assert any("invalid JSON" in t for t in chat_texts(app4)), "no invalid-JSON error"
        finally:
            app4._editor_command, app4.suspend, _sp.run = (
                _orig_editor, _orig_suspend, _orig_run)
        await submit(app4, pilot, "/theme dark")

        # /help lists ONLY commands (no key hints)
        await submit(app4, pilot, "/help")
        joined = " ".join(chat_texts(app4))
        assert all(name in joined for name, _ in COMMANDS), "help missing commands"
        assert "pgup" not in joined and "\\ + enter" not in joined, "help has non-commands"

        # /help <command> shows detail for one command (with or without the slash)
        from cutecat.app import COMMAND_HELP
        await submit(app4, pilot, "/help connect")
        texts = chat_texts(app4)
        assert any("/connect new" in t for t in texts), "no detailed connect help"
        await submit(app4, pilot, "/help /compact")
        assert any("replace the history" in t for t in chat_texts(app4)), "no compact detail"
        # an unknown command is a clear error, not detail
        before = len(chat_texts(app4))
        await submit(app4, pilot, "/help nope")
        assert any("no command /nope" in t for t in chat_texts(app4)), "unknown /help arg"
        # every command in the menu is reachable by /help <name>
        for name, _ in COMMANDS:
            detail = COMMAND_HELP.get(name)
            assert detail is None or detail.startswith(name), (name, detail)

        # /theme light -> white bg; dark -> black; persisted
        await submit(app4, pilot, "/theme light")
        bg = app4.screen.styles.background
        assert (bg.r, bg.g, bg.b) == (255, 255, 255) and app4._dark is False, f"light: {bg}"
        await submit(app4, pilot, "/theme dark")
        bg = app4.screen.styles.background
        assert (bg.r, bg.g, bg.b) == (0, 0, 0), f"dark: {bg}"
        assert config_mod.load_config()["theme"] == "dark", "theme not saved"

        # /new starts a fresh session; /sessions can reopen the old one
        await submit(app4, pilot, "make a note")
        assert await wait_for(pilot, lambda: not app4._busy)
        old_id = app4.session_id
        await submit(app4, pilot, "/new")
        assert app4.session_id != old_id and app4.messages == [], "/new not fresh"
        await submit(app4, pilot, "/sessions")
        assert app4.mode == "pick", "/sessions did not open picker"
        assert old_id in app4._picker_values, "old session not in picker"
        await pick_value(app4, pilot, old_id)
        assert app4.session_id == old_id and app4.messages, "did not reopen session"

        # /editor resolves an editor command (honors $EDITOR, else nvim/vim/vi)
        ed = app4._editor_command()
        assert ed is None or (isinstance(ed, list) and ed), ed
        import os as _os
        _os.environ.pop("EDITOR", None); _os.environ.pop("VISUAL", None)
        ed2 = app4._editor_command()
        assert ed2 is None or ed2[0] in ("nvim", "vim", "vi", "notepad", "open"), ed2

        # /agents switches to plan mode: system prompt gains the plan directive
        from cutecat.app import PLAN_FILE
        await submit(app4, pilot, "/agents")
        assert app4.mode == "pick", "/agents did not open picker"
        await pick_value(app4, pilot, "plan")
        assert app4._agent_mode == "plan", "did not switch to plan"
        assert PLAN_FILE in app4._system and "PLAN mode" in app4._system
        assert config_mod.load_config()["agent_mode"] == "plan", "mode not saved"
        await submit(app4, pilot, "/agents")
        await pick_value(app4, pilot, "build")
        assert app4._agent_mode == "build" and "build" in app4._system.lower()

        # /compact replaces history with a single summary user turn
        FakeProvider.scripted_turns = [[("content", "SUMMARY: did stuff")]]
        await submit(app4, pilot, "/compact")
        assert await wait_for(pilot, lambda: not app4._busy)
        assert len(app4.messages) == 1 and app4.messages[0]["role"] == "user"
        assert "SUMMARY: did stuff" in app4.messages[0]["content"], app4.messages
        FakeProvider.scripted_turns = []

        # /schedule turns a description into a routine (the model drafts it,
        # you pick what it's allowed to do)
        from cutecat import routines as R
        for leftover in R.load():
            R.remove(leftover["id"])
        FakeProvider.scripted_turns = [[("content",
            '{"name": "morning", "prompt": "summarise the commits",'
            ' "cron": "0 9 * * 1-5", "once_at": null}')]]
        await submit(app4, pilot, "/schedule every weekday at 9, summarise commits")
        assert await wait_for(pilot, lambda: app4.mode == "pick"), "no confirm picker"
        await pick_value(app4, pilot, "safe")
        made = R.find("morning")
        assert made is not None, "routine not created"
        assert made["cron"] == "0 9 * * 1-5" and made["permissions"] == "safe", made
        assert made["prompt"] == "summarise the commits"
        assert made["provider"] == "fake" and made["cwd"] == app4.cwd

        # /routines lists it; the action picker can pause it
        await submit(app4, pilot, "/routines")
        assert app4.mode == "pick", "/routines did not open the picker"
        await pick_value(app4, pilot, made["id"])
        assert app4.mode == "pick", "no action picker"
        await pick_value(app4, pilot, "toggle")
        assert R.find("morning")["enabled"] is False, "pause did not stick"

        # and delete it
        await submit(app4, pilot, "/routines")
        await pick_value(app4, pilot, made["id"])
        await pick_value(app4, pilot, "delete")
        assert R.find("morning") is None, "delete did not stick"
        FakeProvider.scripted_turns = []

        # /theme system follows the OS theme live; a fixed theme does not
        from cutecat.app import _mode_in
        assert _mode_in("color-scheme: 'prefer-dark'") == "dark"
        assert _mode_in("'prefer-light'") == "light"
        assert _mode_in("'default'") is None

        await submit(app4, pilot, "/theme dark")
        assert app4._theme_proc is None, "watcher running for a fixed theme"
        gen = app4._theme_gen
        app4._system_theme_changed("light", gen)  # must be ignored
        await pilot.pause()
        assert app4._dark is True, "fixed theme followed the system anyway"

        await submit(app4, pilot, "/theme system")
        now = "dark" if app4._dark else "light"
        other = "light" if now == "dark" else "dark"
        before = len(chat_texts(app4))
        app4._system_theme_changed(other, app4._theme_gen)
        await pilot.pause()
        assert app4._dark == (other == "dark"), "system theme change not applied"
        assert app4.theme == f"cutecat-{other}", app4.theme
        # an automatic switch is silent: nothing is written to the chat
        assert len(chat_texts(app4)) == before, "automatic theme change logged"
        # an event from a retired watcher is ignored
        app4._system_theme_changed(now, app4._theme_gen - 1)
        await pilot.pause()
        assert app4._dark == (other == "dark"), "stale watcher event applied"
        await submit(app4, pilot, "/theme dark")  # stops the watcher thread

        # editor: any binary you like, from config.json or /editor <binary>
        import sys as _sys
        await submit(app4, pilot, f"/editor {_sys.executable}")
        assert app4.cfg["editor"] == _sys.executable
        assert config_mod.load_config()["editor"] == _sys.executable, "editor not saved"
        assert app4._editor_command() == [_sys.executable], app4._editor_command()
        await submit(app4, pilot, "/editor /definitely/not/here")
        assert any("no such editor" in t for t in chat_texts(app4))
        assert app4.cfg["editor"] == _sys.executable, "bad editor overwrote the good one"
        # arguments are allowed, and a broken setting falls back to $EDITOR
        app4.cfg["editor"] = f"{_sys.executable} -c pass"
        assert app4._editor_command() == [_sys.executable, "-c", "pass"]
        app4.cfg["editor"] = "/nope/nope"
        os.environ["EDITOR"] = "vi"
        assert app4._editor_command() == ["vi"], "did not fall back to $EDITOR"
        assert any("falling back" in t for t in chat_texts(app4))
        app4.cfg["editor"] = None
        config_mod.save_config(app4.cfg)

    # ---------------- fifth app: prompt auto-focus after focus wanders --------
    app5 = CuteCatApp()
    async with app5.run_test(size=(90, 30)) as pilot:
        # Focus off the prompt (as if you clicked in the chat to scroll); a
        # letter or number then lands back in the prompt carrying that key.
        app5.set_focus(None)
        assert app5.focused is not app5.input
        await pilot.press("h"); await pilot.press("i"); await pilot.press("5")
        assert app5.focused is app5.input, "prompt not refocused on typing"
        assert app5.input.text == "hi5", repr(app5.input.text)

        class _CharKey:  # stand-in for a printable key event
            def __init__(self, c): self.character = c

        # Any printable character refocuses — letters, numbers, and every one
        # of the punctuation/symbol keys, not just alphanumerics.
        for ch in "></?,\\'\":;]}[{|!@#$%^&*()_+-=`~." + "aZ0":
            app5.input.set_text(""); app5.set_focus(None)
            fired = app5._autofocus_prompt(_CharKey(ch))
            await pilot.pause()  # let the focus change settle
            assert fired is True, f"{ch!r} did not refocus"
            assert app5.input.text == ch and app5.focused is app5.input, repr(ch)

        # Space refocuses too, carrying the space into the prompt.
        app5.input.set_text(""); app5.set_focus(None)
        fired = app5._autofocus_prompt(_CharKey(" "))
        await pilot.pause()
        assert fired is True and app5.input.text == " ", repr(app5.input.text)
        assert app5.focused is app5.input, "space did not refocus the prompt"

        # Navigation keys and shortcuts are still left alone when focus is away.
        app5.input.set_text(""); app5.set_focus(None)
        for nav in ("pageup", "pagedown", "up", "down", "escape"):
            await pilot.press(nav)
        assert app5.input.text == "", f"nav key leaked into prompt: {app5.input.text!r}"

        # A y/n permission popup owns the keyboard — autofocus stays out of it.
        app5.set_focus(None)
        app5.mode = "choice"
        assert app5._autofocus_prompt(_CharKey("y")) is False, "stole the popup's key"
        app5.mode = "normal"

    # -------------- sixth app: welcome art survives a long path on a narrow --
    app6 = CuteCatApp()
    async with app6.run_test(size=(28, 20)) as pilot:
        from cutecat.app import _welcome
        app6.cwd = "/home/nobody/projects/really/deeply/nested/dir/my-project"
        app6.chat.remove_children()
        w = app6.add_msg(_welcome(app6, app6.cwd), "system", "welcome")
        await pilot.pause()
        # the cat is three rows; a long path must be cropped, not wrapped, so
        # the welcome never grows past those three rows
        assert w.size.height == 3, f"welcome art parted into {w.size.height} rows"

    _test_providers()
    _test_new_features()
    _test_key_handling()
    _test_theme_detection()
    _test_encryption()
    _test_cross_platform()
    _test_newlines()
    _test_browser()
    _test_routines()
    _test_bundled_skills()
    _test_skill_management()
    _test_cat()
    _test_hostile_inputs()
    _test_no_tracebacks()
    _test_routine_scheduling()
    _test_agent_core()
    _test_discord_format()
    _test_workspace_and_send_file()
    _test_discord_bot()
    _test_multimodal()
    _test_supported_python_syntax()
    _test_cli_extras()
    _test_progress_and_compact()
    print("ALL TUI TESTS PASSED")


def _test_progress_and_compact():
    """The /compact progress bar renders like the requested block bar, and the
    compaction prompt insists on precision."""
    from cutecat.app import progress_bar, COMPACT_PROMPT

    # 40-cell bar, filled/empty blocks + a percentage, matching the ask
    bar = progress_bar(0.17)
    assert bar == "▰" * 7 + "▱" * 33 + " 17%", bar
    assert progress_bar(0.0, 10) == "▱" * 10 + " 0%"
    assert progress_bar(1.0, 10) == "▰" * 10 + " 100%"
    # out-of-range fractions are clamped, not crash or overflow
    assert progress_bar(2.0, 10).endswith("100%")
    assert progress_bar(-1.0, 10).endswith("0%")

    # the compaction prompt tells the model to be precise and keep specifics
    low = COMPACT_PROMPT.lower()
    assert "precision" in low and "lost" in low, "compact prompt lost its precision guidance"
    assert "verbatim" in low or "literally" in low, "compact prompt does not demand exact detail"


def _test_cli_extras():
    """--help ordering (subcommands above options), the sessions subcommand,
    and --continue resuming the most recent session."""
    from cutecat import cli

    # the cutecat banner: a face + caption, on 3 lines, with a custom face
    banner = cli.cat_banner("hello there", eyes="^ ^", mouth="w")
    assert "( ^ ^ )" in banner and "> w <" in banner and "hello there" in banner
    assert banner.count("\n") == 2 and "/\\_/\\" in banner
    # each part wears a DIFFERENT face
    assert "( o.o )" in cli.cat_banner("x", eyes="o.o", mouth="-")

    # --help: subcommands before options, with the curious-face cat on top
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli._print_help()
    help_text = buf.getvalue()
    assert "( o.o )" in help_text, "no cutecat in the help menu"
    assert help_text.index("subcommands:") < help_text.index("options:"), (
        "options are listed before subcommands"
    )
    for sub in ("sessions", "skill", "routines", "discord"):
        assert sub in help_text, f"{sub} missing from --help"
    for opt in ("--continue", "--resume", "--encrypt", "--version"):
        assert opt in help_text, f"{opt} missing from --help"

    # subcommands take OPTIONS now, not bare words: `discord --run`, not
    # `discord run`. The flags parse (and legacy words still work quietly).
    assert cli._DISCORD_ACTIONS["--run"] == "run" and cli._DISCORD_ACTIONS["-r"] == "run"
    for form in ("--run", "--setup", "--status", "--check", "--install", "--uninstall"):
        assert form in cli._DISCORD_ACTIONS, f"{form} not a discord option"
    assert "-r, --run" in cli.DISCORD_USAGE and "discord [option]" in cli.DISCORD_USAGE
    # an unknown discord option is rejected, not treated as the default action
    try:
        cli._discord_command(["--bogus"])
        raise AssertionError("unknown discord option was accepted")
    except SystemExit as exc:
        assert "unknown discord option" in str(exc)
    # routines usage is flag-driven; the action-word normaliser is present
    assert "--add" in cli.ROUTINE_USAGE and "--list" in cli.ROUTINE_USAGE
    assert "run" in cli._ROUTINE_ACTIONS and "tick" in cli._ROUTINE_ACTIONS

    # "did you mean?" — a typo suggests the closest command/option everywhere
    assert cli._closest("discrod", cli._SUBCOMMANDS) == "discord"
    assert cli._closest("--resme", cli._TOP_OPTIONS) == "--resume"
    assert cli._closest("wxyz", cli._SUBCOMMANDS) is None   # nothing close -> no guess

    def _err(fn, args):
        try:
            fn(args)
        except SystemExit as exc:
            return str(exc)
        return ""

    import sys as _sys
    def _main_err(argv):
        _sys.argv = ["cutecat", *argv]
        try:
            cli._main()
        except SystemExit as exc:
            return str(exc)
        return ""

    assert "did you mean 'discord'?" in _main_err(["discrod"])
    assert "unknown command 'discrod'" in _main_err(["discrod"])
    assert "did you mean '--resume'?" in _main_err(["--resme", "x"])
    assert "did you mean '--status'?" in _err(cli._discord_command, ["--staus"])
    assert "did you mean '--list'?" in _err(cli._routines_command, ["--lst"])
    assert "did you mean '--fetch'?" in _err(cli._skill_command, ["--fecth", "x"])
    # a real command still runs (no "unknown command" false positive)
    with contextlib.redirect_stdout(io.StringIO()):
        assert "unknown command" not in _main_err(["sessions"])

    # 'cutecat sessions' lists them newest-first with resume hints
    for leftover in config_mod.list_sessions():
        pass
    config_mod.save_session({"id": "old-1111", "title": "older",
                             "messages": [{"role": "user", "content": "a"}],
                             "input_history": []})
    import time as _t
    _t.sleep(1.05)  # updated timestamps have second resolution
    config_mod.save_session({"id": "new-2222", "title": "newer",
                             "messages": [{"role": "user", "content": "b"}],
                             "input_history": []})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli._sessions_command([])
    listing = buf.getvalue()
    assert "newer" in listing and "older" in listing, listing
    assert listing.index("new-2222") < listing.index("old-1111"), "not newest-first"
    assert "--resume" in listing and "--continue" in listing, "no resume hint"

    # --continue targets the most recent session
    recent = config_mod.list_sessions()
    assert recent[0]["id"] == "new-2222", "list_sessions not newest-first"


def _test_multimodal():
    """A user message can carry images/audio; each provider translates the media
    it supports and silently drops the rest (the text always goes)."""
    from cutecat.providers.anthropic import AnthropicProvider
    from cutecat.providers.openai_compat import (
        DeepSeekProvider, GoogleProvider, OpenAIProvider,
    )

    msg = {"role": "user", "content": "what is this?", "media": [
        {"kind": "image", "b64": "IMG", "mime": "image/png"},
        {"kind": "audio", "b64": "AUD", "format": "ogg"},
    ]}

    # OpenAI: images yes, audio no → only the image part
    parts = OpenAIProvider()._to_openai_messages([msg])[0]["content"]
    types = {p["type"] for p in parts}
    assert "image_url" in types and "input_audio" not in types, types
    assert any("IMG" in p.get("image_url", {}).get("url", "") for p in parts)

    # Gemini: both image and audio
    types = {p["type"] for p in GoogleProvider()._to_openai_messages([msg])[0]["content"]}
    assert {"image_url", "input_audio"} <= types, types

    # DeepSeek: no multimodal → text only, never a crash
    parts = DeepSeekProvider()._to_openai_messages([msg])[0]["content"]
    assert all(p["type"] == "text" for p in parts), parts

    # Claude: image block, audio dropped
    _sys, cm = AnthropicProvider()._split([msg])
    btypes = {b["type"] for b in cm[0]["content"]}
    assert "image" in btypes and "audio" not in btypes, btypes

    # a plain message is untouched (content stays a string)
    assert OpenAIProvider()._to_openai_messages(
        [{"role": "user", "content": "hi"}])[0]["content"] == "hi"

    # capability flags are set where expected
    assert GoogleProvider().supports_images and GoogleProvider().supports_audio
    assert OpenAIProvider().supports_images and not OpenAIProvider().supports_audio
    assert AnthropicProvider().supports_images and not AnthropicProvider().supports_audio


def _test_supported_python_syntax():
    """A backslash inside an f-string EXPRESSION is legal on Python 3.12+ but a
    SyntaxError before it — which silently broke a binary built with 3.11 (the
    cat's /\\_/\\ in an f-string). ast.parse(feature_version=…) does NOT catch
    this (the 3.12 tokenizer change isn't rolled back), so we walk the f-string
    nodes and check each expression's source for a backslash — the actual thing
    that fails on 3.10/3.11.
    """
    import ast
    from pathlib import Path as _Path

    src = _Path(config_mod.__file__).parent
    failures = []
    for path in sorted(src.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(text, filename=str(path))):
            if isinstance(node, ast.FormattedValue):
                seg = ast.get_source_segment(text, node.value)
                if seg and "\\" in seg:
                    failures.append(f"{path.name}:{node.lineno}: backslash in "
                                    f"f-string expression: {seg!r}")
    assert not failures, (
        "these break on Python < 3.12 (rewrite with .ljust/.format or a temp "
        "variable):\n  " + "\n  ".join(failures)
    )


def _test_discord_format():
    """The pure Discord helpers: brevity, chunking, allowlist, status, uploads.
    These need no discord.py and carry the load-bearing logic."""
    from cutecat import discord_format as D

    # brevity directive is real and says the important things
    assert "short" in D.DISCORD_BREVITY.lower() and "Discord" in D.DISCORD_BREVITY

    # split_message: every chunk fits, fences stay balanced, nothing is lost
    def fits_and_valid(text, limit):
        chunks = D.split_message(text, limit)
        for c in chunks:
            assert len(c) <= limit, f"chunk {len(c)} > {limit}"
            assert c.count("```") % 2 == 0, f"unbalanced fence: {c!r}"
        seen = "".join(
            "\n".join(l for l in c.split("\n") if not l.strip().startswith("```"))
            for c in chunks
        ).replace("\n", "").replace(" ", "")
        want = "\n".join(
            l for l in text.split("\n") if not l.strip().startswith("```")
        ).replace("\n", "").replace(" ", "")
        assert seen == want, "content changed across the split"
        return chunks

    assert D.split_message("hi") == ["hi"]
    assert D.split_message("") == [""]
    fits_and_valid("\n".join(f"line {i} words words" for i in range(40)), 100)
    code = "intro\n```python\n" + "\n".join(f"x{i}={i}" for i in range(60)) + "\n```\nend"
    chunks = fits_and_valid(code, 120)
    reopened = [c for c in chunks if c.startswith("```")]
    assert any("python" in c.split("\n")[0] for c in reopened), "language dropped on split"
    fits_and_valid("A" * 5000, 200)                      # a single monster line
    real = ("Here.\n\n```diff\n"
            + "\n".join(f"- old line {i} of the file\n+ new line {i} of the file"
                        for i in range(120))
            + "\n```\nDone.")
    assert len(real) > D.CHUNK_LIMIT, "test answer isn't actually over the limit"
    got = fits_and_valid(real, D.CHUNK_LIMIT)
    assert len(got) >= 2, "a huge answer should become several messages"

    # allowlist: only the owner, only the channel (or a thread under it)
    cfg = {"discord": {"token": "t", "owner_id": "1", "channel_id": "9"}}
    assert D.configured(cfg)
    assert D.is_allowed(cfg, author_id=1, channel_id=9)
    assert D.is_allowed(cfg, author_id="1", channel_id=999, parent_channel_id=9)  # thread
    assert not D.is_allowed(cfg, author_id=2, channel_id=9), "answered a stranger"
    assert not D.is_allowed(cfg, author_id=1, channel_id=5), "answered wrong channel"
    assert not D.is_allowed(cfg, author_id=1, channel_id=9, is_bot=True), "answered a bot"
    assert not D.configured({"discord": {}}), "empty config counts as configured"

    # status line and upload limit
    assert "running" in D.status_line("running", "npm test", 22) and "npm test" in D.status_line("running", "npm test", 22)
    assert "waiting" in D.status_line("waiting", "", 3)
    assert D.upload_limit_bytes({"discord": {"max_upload_mb": 25}}) == 25 * 1024 * 1024
    assert D.upload_limit_bytes({"discord": {}}) == 10 * 1024 * 1024


def _test_workspace_and_send_file():
    """The workspace blast-radius limiter, and the send_file tool."""
    from cutecat import tools as T

    root = tmp / "ws"
    (root / "sub").mkdir(parents=True, exist_ok=True)
    (root / "sub" / "ok.txt").write_text("inside\n", encoding="utf-8")
    (tmp / "outside.txt").write_text("outside\n", encoding="utf-8")

    sent = []

    class Ctx:
        class shell:
            cwd = str(root)
        chromium = None
        workspace = str(root)
        ask_tmp = staticmethod(lambda: True)
        note = staticmethod(lambda _m: None)
        ask_permission = staticmethod(lambda *_a: True)
        ask_edit = staticmethod(lambda *_a: True)
        preview_diff = staticmethod(lambda *_a: (1, 1))
        run_job = staticmethod(lambda c: "exit code: 0")
        is_cancelled = staticmethod(lambda: False)
        show_diff = None
        send_file = staticmethod(lambda path, cap: sent.append((path, cap)) or "sent")
        outside_workspace = T.ToolContext.outside_workspace

    # a real ToolContext, to exercise outside_workspace exactly
    ctx = T.ToolContext(
        shell=Ctx.shell, ask_permission=lambda *a: True, ask_tmp=lambda: True,
        note=lambda _t: None, is_cancelled=lambda: False,
        run_job=lambda c: "ok", workspace=str(root),
        send_file=lambda path, cap: sent.append((path, cap)) or f"sent {path}",
    )

    # inside the workspace: fine
    out = T.execute(ctx, "read_file", {"path": str(root / "sub" / "ok.txt")})
    assert "inside" in out, out
    # outside: refused, for read AND write
    out = T.execute(ctx, "read_file", {"path": str(tmp / "outside.txt")})
    assert "outside the workspace" in out, out
    out = T.execute(ctx, "create_file", {"path": str(tmp / "new.txt"), "content": "x"})
    assert "outside the workspace" in out and not (tmp / "new.txt").exists(), out
    # a traversal attempt is resolved and blocked
    out = T.execute(ctx, "read_file", {"path": str(root / ".." / "outside.txt")})
    assert "outside the workspace" in out, out

    # send_file: delivers a real file, refuses a missing one and one outside
    out = T.execute(ctx, "send_file", {"path": str(root / "sub" / "ok.txt"),
                                       "caption": "here"})
    assert out.startswith("sent") and sent and sent[-1][1] == "here", (out, sent)
    assert "no such file" in T.execute(ctx, "send_file", {"path": str(root / "nope")})
    assert "outside the workspace" in T.execute(
        ctx, "send_file", {"path": str(tmp / "outside.txt")})

    # with no send_file callback, the tool says so instead of crashing
    ctx2 = T.ToolContext(
        shell=Ctx.shell, ask_permission=lambda *a: True, ask_tmp=lambda: True,
        note=lambda _t: None, is_cancelled=lambda: False, run_job=lambda c: "ok")
    assert "isn't available" in T.execute(ctx2, "send_file", {"path": "x"})
    assert T.SEND_FILE_SCHEMA["function"]["name"] == "send_file"


def _test_discord_bot():
    """The bot constructs and registers its slash commands. Skipped where
    discord.py isn't installed (it's an optional extra)."""
    try:
        from cutecat import discord_bot
    except ImportError:
        print("  (discord.py not installed: skipped bot construction)")
        return

    cfg = {
        "provider": "fake", "model": "m", "api_keys": {"fake": "k"}, "skills": {},
        "agent_mode": "build", "workspace": None,
        "discord": {"token": "x", "owner_id": "111", "channel_id": "222",
                    "guild_id": "333", "max_upload_mb": 10, "stt": None},
    }
    bot = discord_bot.CuteCatBot(cfg)
    cmds = {c.name for c in bot.tree.get_commands()}
    assert {"stop", "new", "clear", "model", "agents", "skills", "compact",
            "routines"} <= cmds, cmds
    assert bot.owner_id == 111 and bot.channel_id == 222

    # the brevity directive reaches the system prompt
    sp = discord_bot.build_system_prompt(cfg, "build")
    assert "answering in Discord" in sp

    # permission view: 3 buttons with allow-all, 2 without
    assert len(discord_bot.PermissionView(111, True).children) == 3
    assert len(discord_bot.PermissionView(111, False).children) == 2

    # clicking a button must ACK the interaction BEFORE releasing the agent
    # thread (event.set), or Discord shows "This interaction failed". The fake
    # ack never suspends, so the coroutine runs to completion in one .send().
    def _drive(coro):
        try:
            coro.send(None)
        except StopIteration:
            pass

    view = discord_bot.PermissionView(111, True)

    class _Resp:
        async def edit_message(self, **_k):
            assert not view.event.is_set(), "agent released before the click was acked"

    class _Inter:
        class user:
            id = 111
        response = _Resp()

    _drive(view._finish(_Inter(), "y", "✅ allowed"))
    assert view.result == "y" and view.event.is_set(), "click not recorded"
    # a non-owner click is ignored (no result, no release)
    view2 = discord_bot.PermissionView(111, True)

    class _Other:
        class user:
            id = 999
        response = _Resp()
    _drive(view2._finish(_Other(), "y", "x"))
    assert not view2.event.is_set(), "a non-owner click released the agent"

    # regression: the permission view MUST be built on the event loop. A view
    # built off-loop (in a thread with no running loop, like cutecat's agent
    # worker) has a None stopped-future, and discord.py's _dispatch_item then
    # silently drops every button click → "This interaction failed". Built on
    # the loop, the same call arms a dispatch task.
    import threading as _th
    off = {}

    def _build_off_loop():
        v = discord_bot.PermissionView(111, True)   # no running loop here
        off["dispatch"] = v._dispatch_item(v.children[0], None)
    _th_ = _th.Thread(target=_build_off_loop)
    _th_.start(); _th_.join()
    assert off["dispatch"] is None, "off-loop view unexpectedly dispatched a click"

    on = discord_bot.PermissionView(111, True)      # built on the running loop
    task = on._dispatch_item(on.children[0], None)
    assert task is not None, "a loop-built view must be able to dispatch clicks"
    task.cancel()

    # a session resets cleanly
    s = discord_bot.Session(cfg, 222)
    s.messages.append({"role": "user", "content": "hi"})
    s.reset(cfg)
    assert s.messages == [] and s.agent_mode == "build"


def _test_agent_core():
    """The shared agent loop (agent.run_agent) that the TUI, routines, and the
    Discord bot will all run on. It emits events and never raises."""
    from cutecat import agent, tools as tools_mod

    class Ctx:
        class shell:
            cwd = str(tmp)
        chromium = None
        ask_tmp = staticmethod(lambda: True)
        note = staticmethod(lambda _m: None)
        ask_permission = staticmethod(lambda *_a: True)
        ask_edit = staticmethod(lambda *_a: True)
        preview_diff = staticmethod(lambda *_a: (1, 1))
        run_job = staticmethod(lambda cmd: "exit code: 0\nhi")
        is_cancelled = staticmethod(lambda: False)
        show_diff = None

    def run(turns, **kw):
        FakeProvider.scripted_turns = list(turns)
        messages = [{"role": "user", "content": "do it"}]
        events = list(agent.run_agent(
            FakeProvider(), "k", "m", "system prompt", messages, Ctx, **kw
        ))
        FakeProvider.scripted_turns = []
        return events, messages

    # a plain answer: TurnStarted, streamed Content, then Done
    events, messages = run([[("content", "hello "), ("content", "world")]])
    kinds = [type(e).__name__ for e in events]
    assert kinds == ["TurnStarted", "Content", "Content", "Done"], kinds
    assert events[-1].answer == "hello world"
    assert events[1].full == "hello " and events[2].full == "hello world"
    assert messages[-1] == {"role": "assistant", "content": "hello world"}

    # a provider that reports token usage surfaces a Usage event
    events, _ = run([[("content", "hi"), ("usage", {"input": 100, "output": 20})]])
    usage = [e for e in events if isinstance(e, agent.Usage)]
    assert len(usage) == 1 and usage[0].input == 100 and usage[0].output == 20

    # a tool call: the loop runs the tool, feeds the result back, then answers.
    # It also proves the transcript is well-formed (assistant tool_calls, then a
    # tool result) — the thing every provider translation depends on.
    events, messages = run([
        [("tool_call", {"name": "run_command", "arguments": {"command": "echo hi"}})],
        [("content", "done")],
    ])
    names = [type(e).__name__ for e in events]
    assert names == ["TurnStarted", "ToolStarted", "ToolFinished",
                     "TurnStarted", "Content", "Done"], names
    started = next(e for e in events if isinstance(e, agent.ToolStarted))
    assert started.name == "run_command" and started.arguments == {"command": "echo hi"}
    assert messages[1]["role"] == "assistant" and messages[1]["tool_calls"][0]["function"]["name"] == "run_command"
    assert messages[2]["role"] == "tool" and "hi" in messages[2]["content"]

    # opaque provider data (Gemini's thought_signature) is carried into the
    # transcript so it can be replayed
    events, messages = run([
        [("tool_call", {"name": "read_file", "arguments": {"path": "x"},
                        "extra": {"sig": "abc"}})],
        [("content", "ok")],
    ])
    assert messages[1]["tool_calls"][0]["extra_content"] == {"sig": "abc"}

    # a provider error becomes a Failed event, not a raise
    events, _ = run([ProviderErrorTurn()])
    assert isinstance(events[-1], agent.Failed), [type(e).__name__ for e in events]
    assert "boom" in events[-1].message

    # cancel stops the stream cleanly: no Done, no Failed
    stop = {"n": 0}

    def cancel_after_two():
        stop["n"] += 1
        return stop["n"] > 2

    events, _ = run([[("content", "a"), ("content", "b"), ("content", "c")]],
                    cancelled=cancel_after_two)
    assert not any(isinstance(e, (agent.Done, agent.Failed)) for e in events), events

    # a provider that rejects tools degrades to chat-only and retries
    events, _ = run([RejectToolsTurn(), [("content", "plain answer")]])
    assert any(isinstance(e, agent.ToolsDisabled) for e in events), events
    assert isinstance(events[-1], agent.Done) and events[-1].answer == "plain answer"

    # max steps ends in Failed, never an infinite loop
    loop_turn = [("tool_call", {"name": "read_file", "arguments": {"path": "x"}})]
    events, _ = run([list(loop_turn) for _ in range(50)], max_steps=3)
    assert isinstance(events[-1], agent.Failed) and "too many steps" in events[-1].message


class ProviderErrorTurn(list):
    """A scripted turn that makes the fake provider raise mid-stream."""
    def __iter__(self):
        from cutecat.providers.base import ProviderError
        raise ProviderError("boom")
        yield  # pragma: no cover


class RejectToolsTurn(list):
    """A turn that rejects tools before producing anything (like Perplexity)."""
    def __iter__(self):
        from cutecat.providers.base import ProviderError
        raise ProviderError("this model does not support tools")
        yield  # pragma: no cover


def _test_no_tracebacks():
    """A crash must never show the user python. Textual's default is a Rich
    traceback WITH LOCALS — which can contain an api key — printed straight into
    the terminal. We replace that path entirely."""
    from cutecat.app import CuteCatApp

    # our handler must not defer to Textual's (that is what renders the traceback)
    assert CuteCatApp._handle_exception is not CuteCatApp.__mro__[1]._handle_exception, (
        "the app inherits Textual's traceback screen"
    )
    source = inspect.getsource(CuteCatApp._handle_exception)
    assert "super()._handle_exception" not in source, (
        "still defers to Textual's traceback renderer"
    )
    assert "_exit_renderables" in source and "clear" in source, (
        "the pending Rich renderables are not discarded"
    )

    # the CLI silences stray tracebacks too
    from cutecat import cli

    assert hasattr(cli, "_silence_tracebacks")
    real_hook, real_thread_hook = sys.excepthook, threading.excepthook
    try:
        cli._silence_tracebacks()
        assert sys.excepthook is not real_hook, "sys.excepthook not replaced"
        assert threading.excepthook is not real_thread_hook
        # a thread that dies writes to the log, and prints nothing at all
        log = config_mod.CUTECAT_DIR / "crash.log"
        log.unlink(missing_ok=True)

        def explodes():
            raise RuntimeError("in a thread, with secret=sk-DO-NOT-PRINT")

        buf = io.StringIO()
        with contextlib.redirect_stderr(buf), contextlib.redirect_stdout(buf):
            t = threading.Thread(target=explodes)
            t.start()
            t.join()
        printed = buf.getvalue()
        assert "Traceback" not in printed and "sk-DO-NOT-PRINT" not in printed, printed
        assert log.exists() and "RuntimeError" in log.read_text(encoding="utf-8"), (
            "the thread's error was lost entirely"
        )
        log.unlink(missing_ok=True)
    finally:
        sys.excepthook, threading.excepthook = real_hook, real_thread_hook


def _test_routine_scheduling():
    """Routines must be schedulable on every OS, not just where cron exists."""
    from cutecat import routines as R

    # Linux prefers a systemd user timer; without systemd it falls back to cron.
    linux = R.scheduler("linux", systemd=False)
    linux_systemd = R.scheduler("linux", systemd=True)
    bsd = R.scheduler("freebsd14")
    mac = R.scheduler("darwin")
    win = R.scheduler("nt")

    assert linux["kind"] == "cron" and bsd["kind"] == "cron", (linux, bsd)
    assert "routines tick" in linux["line"] and linux["line"].startswith("* * * * *")
    assert mac["kind"] == "launchd" and win["kind"] == "schtasks"

    assert linux["line"].endswith("routines tick"), "cron tick has a stray flag"

    # systemd: a user timer + its oneshot service, both named for the task
    assert linux_systemd["kind"] == "systemd", linux_systemd
    assert linux_systemd["unit"] == f"{R.TASK_NAME}.timer"
    assert linux_systemd["service"].endswith(f"{R.TASK_NAME}.service")
    assert linux_systemd["timer"].endswith(f"{R.TASK_NAME}.timer")

    # macOS: a launchd agent that fires every minute
    plist = R.launch_agent_plist(["/usr/local/bin/cutecat"])
    assert "<key>StartInterval</key><integer>60</integer>" in plist, plist
    assert "<string>routines</string>" in plist and "<string>tick</string>" in plist
    assert str(R.launch_agent_path()).endswith("LaunchAgents/ai.cutecat.routines.plist")

    # Windows: a scheduled task, every minute, replacing any previous one
    argv = win["install"]
    assert argv[:2] == ["schtasks", "/Create"] and "/F" in argv
    assert "MINUTE" in argv and R.TASK_NAME in argv
    assert any("routines tick" in a for a in argv), argv
    assert win["uninstall"][:2] == ["schtasks", "/Delete"]

    # cron: installing is idempotent, and uninstalling leaves your other jobs alone
    fake = ["0 3 * * * /usr/bin/backup", "@reboot /usr/bin/thing"]

    def crontab(lines=None):
        nonlocal fake
        if lines is None:
            return list(fake)
        fake = list(lines)
        return fake

    real_crontab, real_sched = R._crontab, R.scheduler
    R._crontab = crontab
    R.scheduler = lambda platform=None: real_sched("linux", systemd=False)
    try:
        R.install_scheduler()
        R.install_scheduler()          # twice
        entries = [ln for ln in fake if R.TASK_NAME in ln]
        assert len(entries) == 1, f"installed twice: {fake}"
        assert "routines tick" in entries[0]
        assert "/usr/bin/backup" in "\n".join(fake), "clobbered another cron job"
        R.uninstall_scheduler()
        assert not [ln for ln in fake if R.TASK_NAME in ln], fake
        assert len(fake) == 2, "removed someone else's cron jobs"
    finally:
        R._crontab, R.scheduler = real_crontab, real_sched


def _test_hostile_inputs():
    """Nothing a model, a provider, a file, or a user can send may raise.

    Tool arguments come from a language model: a number can be the string "ten",
    a path can be a list, the whole argument object can be missing. Every one of
    these must come back as an error string the model can read and correct — a
    raised exception would abort the turn instead.
    """
    from cutecat import policy, routines as R, skills as S, tools as T

    class Ctx:
        class shell:
            cwd = str(tmp)
        chromium = None
        ask_tmp = staticmethod(lambda: True)
        note = staticmethod(lambda _m: None)
        ask_permission = staticmethod(lambda *_a: False)   # deny everything
        ask_edit = staticmethod(lambda *_a: False)
        preview_diff = staticmethod(lambda *_a: (0, 0))
        run_job = staticmethod(lambda cmd: "exit code: 0\n")
        is_cancelled = staticmethod(lambda: False)
        show_diff = None

    junk = [
        None, {}, [], "", "not-json", 42, 3.14, True,
        {"path": None}, {"path": []}, {"path": {"a": 1}}, {"path": 12345},
        {"path": ""}, {"path": "   "}, {"path": "/nonexistent/nope.txt"},
        {"path": str(tmp)},                                   # a directory
        {"path": "x.txt", "offset": "ten"},                   # not a number
        {"path": "x.txt", "offset": -5},                      # out of range
        {"path": "x.txt", "limit": 10**12},                   # absurd
        {"path": "x.txt", "offset": {"n": 1}},
        {"command": None}, {"command": []}, {"command": "\x00"},
        {"old_string": "a"},                                  # missing new_string
        {"path": "x.txt", "old_string": 1, "new_string": 2},  # not text
        {"path": "x.txt", "old_string": "a", "new_string": "a"},   # identical
        {"path": "x.txt", "content": ["not", "text"]},
        {"url": None}, {"url": "not a url"}, {"url": "x.com", "action": "dance"},
        {"url": "x.com", "action": "screenshot", "width": "wide"},
        {"url": "x.com", "wait_ms": -1},
        {"url": "x" * 5000},
        '{"path": "x.txt"}',                                  # args as a json string
        '{"broken json',
    ]
    (tmp / "x.txt").write_text("one\ntwo\n", encoding="utf-8")

    for name in list(T.DISPATCH) + ["no_such_tool"]:
        for args in junk:
            out = T.execute(Ctx, name, args)   # must not raise, ever
            assert isinstance(out, str), (name, args, type(out))
            assert out, f"{name}({args!r}) returned nothing"

    # and the tool still works when the arguments are sane
    ok = T.execute(Ctx, "read_file", {"path": str(tmp / "x.txt")})
    assert "one" in ok and not ok.startswith("error"), ok
    # a number given as a string is accepted (models do this constantly)
    ok = T.execute(Ctx, "read_file", {"path": str(tmp / "x.txt"), "limit": "1"})
    assert "one" in ok and "two" not in ok, ok

    # the command classifier must survive anything a model writes
    for cmd in ["", "   ", "\x00", "a" * 10000, "ls |", "|| rm -rf /", "$(", "`",
                "ls; rm -rf /", "echo 'unclosed", "\n\n", "🐈 --version"]:
        d = policy.classify(cmd)
        assert isinstance(d.allowed, bool)

    # a corrupt session file must not take the app down with it
    bad = config_mod.SESSIONS_DIR / "corrupt.jsonl"
    bad.write_text("not json at all\n{\"role\":\"user\"}\n", encoding="utf-8")
    assert config_mod.load_session("corrupt") is None or True  # no exception
    config_mod.list_sessions()   # must not raise even with junk in the directory
    bad.write_bytes(b"\xff\xfe\x00binary")
    config_mod.list_sessions()
    bad.unlink()

    # a hostile cron / routine
    for expr in ["", "* * * *", "*/0 * * * *", "x x x x x", "99 99 99 99 99",
                 "0 9 * * 1-5" + " " * 100]:
        try:
            R.parse_cron(expr)
        except R.RoutineError:
            pass  # a clear error is the correct outcome
    for routine in [{}, {"enabled": True}, {"enabled": True, "cron": "nonsense"},
                    {"enabled": True, "once_at": "not-a-date"}]:
        try:
            R.is_due(routine, datetime_now())
        except R.RoutineError:
            pass   # never anything else

    # skill names from hostile sources
    for raw in ["../../etc/passwd", "C:\\windows\\system32\\x.md", "a" * 500,
                "..%2f..%2fx.md", "sk ill.MD"]:
        name = S.clean_name(raw)
        assert "/" not in name and "\\" not in name and ".." not in name, name

    # --- an unwritable disk: say so, don't die ---------------------------
    import os as _os

    sessions = config_mod.SESSIONS_DIR
    config_mod.save_config(config_mod.load_config())      # works normally
    _os.chmod(sessions, 0o500)
    try:
        config_mod.save_session({"id": "cannot-write", "messages": [{"role": "user",
                                                                     "content": "x"}]})
        raise AssertionError("a failed write was swallowed in silence")
    except config_mod.StorageError as exc:
        assert "could not save" in str(exc), exc
    finally:
        _os.chmod(sessions, 0o700)

    # --- a crash leaves something you can act on -------------------------
    from cutecat.app import write_crash_log

    log = write_crash_log(RuntimeError("boom"), "abcd1234-efgh")
    assert log is not None and log.exists()
    body = log.read_text(encoding="utf-8")
    assert "RuntimeError: boom" in body, "no traceback in the crash log"
    assert "cutecat --resume abcd1234" in body, "no way to get the chat back"
    log.unlink()

    # --- a malformed stream from a provider ------------------------------
    # A gateway, a proxy, or a bad day can send half-shaped JSON. One bad chunk
    # must not lose the whole reply (these all used to raise AttributeError).
    from cutecat.providers.anthropic import AnthropicProvider
    from cutecat.providers.base import ProviderError
    from cutecat.providers.ollama_cloud import OllamaCloudProvider
    from cutecat.providers.openai_compat import OpenAIProvider
    import cutecat.providers.anthropic as an_mod
    import cutecat.providers.ollama_cloud as ol_mod
    import cutecat.providers.openai_compat as oc_mod

    hostile = [
        "data: {broken json", "data: []", "data: null",
        'data: {"choices": "not-a-list"}', 'data: {"choices": [{}]}',
        'data: {"choices": [{"delta": null}]}',
        'data: {"choices": [{"delta": {"tool_calls": "nope"}}]}',
        'data: {"choices": [{"delta": {"tool_calls": [{"function": {"arguments": "{bad"}}]}}]}',
        'data: {"type": "content_block_delta"}',
        'data: {"type":"content_block_start","content_block":"nope"}',
        'data: {"type":"content_block_delta","delta":[1,2]}',
        '{"message": null}', '{"message": {"tool_calls": "x"}}',
        '{"message": {"tool_calls": [{"function": null}]}}',
        "[1,2,3]", "not json", "data: [DONE]", "",
    ]

    class _Stream:
        status_code = 200
        headers = {}
        content = b"x"
        text = ""

        def iter_lines(self, *_a, **_k):
            yield from hostile

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            pass

        def json(self):
            return {}

        def raise_for_status(self):
            pass

    for mod, provider in (
        (oc_mod, OpenAIProvider()),
        (an_mod, AnthropicProvider()),
        (ol_mod, OllamaCloudProvider()),
    ):
        real_post = mod.requests.post
        mod.requests.post = lambda *_a, **_k: _Stream()
        try:
            events = list(provider.stream_chat("k", "m", [{"role": "user", "content": "hi"}]))
            for kind, payload in events:
                assert kind in ("content", "thinking", "tool_call"), kind
                if kind == "tool_call":
                    assert isinstance(payload["arguments"], dict), payload
        except ProviderError:
            pass  # a clear provider error is a fine outcome; a crash is not
        finally:
            mod.requests.post = real_post


def datetime_now():
    from datetime import datetime
    return datetime.now()


def _test_cat():
    """The cat blinks, watches its work, and looks pleased when it's done."""
    from cutecat.app import Cat

    cat = Cat()
    assert cat.frame(0.0, busy=False) == Cat.IDLE, "the cat starts mid-blink"

    # it blinks, but only for a moment, and then goes back to normal
    cat.next_blink = 1.0
    assert cat.frame(1.0, busy=False)[0] == Cat.BLINK, "it never blinks"
    assert cat.frame(1.1, busy=False)[0] == Cat.BLINK, "the blink was one frame"
    assert cat.frame(1.0 + Cat.BLINK_FOR + 0.01, busy=False) == Cat.IDLE, (
        "the cat's eyes stayed shut"
    )
    # and the next blink is a few seconds away, not immediately
    assert cat.next_blink >= 1.0 + Cat.BLINK_EVERY[0]

    # blinks are irregular — a fixed interval would read as a metronome
    gaps = set()
    for _ in range(20):
        c = Cat()
        gaps.add(round(c.next_blink, 3))
    assert len(gaps) > 5, f"the blink interval is fixed: {gaps}"

    # while the agent works, its eyes move about
    working = Cat()
    working.next_blink = 1e9  # don't blink during this check
    seen = {working.frame(t / 4, busy=True)[0] for t in range(12)}
    assert len(seen) > 1, f"the cat is frozen while working: {seen}"
    assert working.frame(0.0, busy=True)[1] == "·", "no concentrating face"

    # and it's pleased with itself for a few seconds after an answer
    done = Cat()
    done.next_blink = 1e9
    done.pleased(10.0)
    assert done.frame(10.5, busy=False) == Cat.HAPPY, "not pleased"
    assert done.frame(10.0 + Cat.HAPPY_FOR + 0.1, busy=False) == Cat.IDLE, (
        "the cat is permanently smug"
    )


def _test_skill_management():
    """`cutecat skill`: adding from a path or a URL, listing, removing."""
    from cutecat import skills as S

    # a URL you'd actually copy from a browser is turned into the raw file
    assert S.raw_url("https://github.com/o/r/blob/main/skills/tdd.md") == (
        "https://raw.githubusercontent.com/o/r/main/skills/tdd.md"
    )
    assert S.raw_url("https://example.com/x.md") == "https://example.com/x.md"

    # the name comes from the file, minus the .md
    assert S.name_from_url("https://x.dev/skills/Deep-Debugging.MD") == "deep-debugging"
    # ...except SKILL.md, which is named after its directory (how the public
    # collections lay them out)
    assert S.name_from_url("https://raw.x/o/r/main/skills/docx/SKILL.md") == "docx"
    assert S.name_from_url("https://raw.x/o/r/main/skills/pdf/readme.md") == "pdf"
    assert S.clean_name("My Skill.md") == "my-skill"
    assert S.clean_name("../../etc/passwd") == "passwd", "path traversal in a name"
    for bad in ("", "   ", "///"):
        try:
            S.clean_name(bad)
            raise AssertionError(f"accepted {bad!r} as a name")
        except S.SkillError:
            pass

    # --path
    src = tmp / "house.md"
    src.write_text("# House style\n\nUse when writing our code.\n", encoding="utf-8")
    name, body = S.add_from_path(str(src), "house-style")
    assert name == "house-style" and "House style" in body
    S.copy_into(name, body)
    assert S.skill_path("house-style").exists()
    assert "house-style" in config_mod.list_skills()

    # it will not silently overwrite
    try:
        S.copy_into("house-style", "# other\n")
        raise AssertionError("overwrote an existing skill")
    except S.SkillError:
        pass
    S.copy_into("house-style", "# House style\n\nUse when x.\n", force=True)

    # enable / disable go through config, so /skills sees them
    S.set_enabled("house-style", True)
    assert config_mod.load_config()["skills"]["house-style"] is True
    entry = next(s for s in S.listing() if s["name"] == "house-style")
    assert entry["on"] is True and entry["bundled"] is False, entry
    assert any(s["bundled"] for s in S.listing()), "bundled skills not marked"
    S.set_enabled("house-style", False)
    assert config_mod.load_config()["skills"]["house-style"] is False

    # --fetch, with the network faked
    from cutecat import skills as skills_mod
    import requests as _requests

    class _Resp:
        status_code = 200
        headers = {"content-type": "text/plain"}
        text = "# Fetched\n\nUse when testing.\n"

    real_get = _requests.get
    _requests.get = lambda *a, **k: _Resp()
    try:
        name, body = skills_mod.fetch(
            "https://github.com/o/r/blob/main/skills/reviewing-prs.md"
        )
        assert name == "reviewing-prs" and "Fetched" in body, (name, body)
        skills_mod.copy_into(name, body)
        assert "reviewing-prs" in config_mod.list_skills()

        # a page instead of a file is refused with a useful message
        class _Html(_Resp):
            headers = {"content-type": "text/html; charset=utf-8"}

        _requests.get = lambda *a, **k: _Html()
        try:
            skills_mod.fetch("https://github.com/o/r/blob/main/x.md")
            raise AssertionError("accepted an html page as a skill")
        except S.SkillError as exc:
            assert "web page" in str(exc), exc

        class _Missing(_Resp):
            status_code = 404

        _requests.get = lambda *a, **k: _Missing()
        try:
            skills_mod.fetch("https://x.dev/nope.md")
            raise AssertionError("accepted a 404")
        except S.SkillError as exc:
            assert "404" in str(exc), exc
    finally:
        _requests.get = real_get

    # warnings — said, not enforced
    assert S.warnings("# ok\n\nUse when x.\n") == []
    notes = " ".join(S.warnings("---\nname: x\n---\n" + "line\n" * 200))
    assert "loaded in full" in notes and "frontmatter" in notes, notes

    # --new gives a skill in cutecat's shape
    path = S.new("deploy-checklist")
    made = path.read_text(encoding="utf-8")
    assert made.startswith("# Deploy checklist") and "Use when" in made

    # --export copies it out
    out = S.export("house-style", str(tmp / "exported"))
    assert out.read_text(encoding="utf-8").startswith("# House style")

    # --remove deletes the file and forgets the setting
    S.set_enabled("house-style", True)
    S.remove("house-style")
    assert not S.skill_path("house-style").exists()
    assert "house-style" not in config_mod.load_config()["skills"], "setting lingered"
    for leftover in ("reviewing-prs", "deploy-checklist"):
        S.remove(leftover)
    try:
        S.remove("never-existed")
        raise AssertionError("removed a skill that isn't there")
    except S.SkillError:
        pass


def _test_bundled_skills():
    """The programming skills that ship with cutecat: installed on first run,
    never overwriting one you edited, and off until you enable them."""
    from pathlib import Path as _Path

    shipped = _Path(config_mod.__file__).parent / "bundled_skills"
    names = sorted(p.stem for p in shipped.glob("*.md"))
    assert len(names) >= 25, f"only {len(names)} skills ship"
    assert {"debugging", "code-review", "testing", "refactoring", "git-commits",
            "performance", "secure-coding", "tdd", "writing-plans",
            "executing-plans", "brainstorming", "flaky-tests", "concurrency",
            "error-handling", "api-design", "database-migrations", "docker",
            "github-actions", "bash-scripting", "observability",
            "python-idioms", "typescript-idioms", "web-app-testing",
            "reading-unfamiliar-code", "git-worktrees", "finishing-a-branch",
            "dependency-upgrades", "receiving-code-review", "writing-docs",
            "writing-skills"} <= set(names), sorted(set(names))

    for skill in shipped.glob("*.md"):
        body = skill.read_text(encoding="utf-8")
        # a skill is loaded in full when enabled, so it has to stay small
        assert len(body.splitlines()) < 120, f"{skill.name} is too long to enable"
        assert body.startswith("# "), f"{skill.name} has no title"
        assert "Use when" in body, f"{skill.name} never says when it applies"

    # a fresh ~/.cutecat gets them, turned off
    fresh = _Path(tempfile.mkdtemp())
    real_dirs = (config_mod.CUTECAT_DIR, config_mod.SKILLS_DIR,
                 config_mod.SESSIONS_DIR, config_mod.SYSTEM_PROMPT_FILE,
                 config_mod.CONFIG_FILE)
    try:
        config_mod.CUTECAT_DIR = fresh
        config_mod.SKILLS_DIR = fresh / "skills"
        config_mod.SESSIONS_DIR = fresh / "sessions"
        config_mod.SYSTEM_PROMPT_FILE = fresh / "SYSTEM.md"
        config_mod.CONFIG_FILE = fresh / "config.json"
        config_mod.ensure_dirs()
        assert sorted(config_mod.list_skills()) == names, "not installed on first run"
        assert config_mod.load_config()["skills"] == {}, "a skill was enabled for me"

        # an edited skill is never clobbered
        mine = config_mod.SKILLS_DIR / "debugging.md"
        mine.write_text("# mine\n", encoding="utf-8")
        config_mod.install_bundled_skills()
        assert mine.read_text() == "# mine\n", "overwrote a skill I had edited"
        assert config_mod.install_bundled_skills(overwrite=True), "cannot force a refresh"
        assert mine.read_text() != "# mine\n", "overwrite=True did nothing"
    finally:
        (config_mod.CUTECAT_DIR, config_mod.SKILLS_DIR, config_mod.SESSIONS_DIR,
         config_mod.SYSTEM_PROMPT_FILE, config_mod.CONFIG_FILE) = real_dirs


def _test_routines():
    """Routines: cron maths, storage, and unattended runs (safe vs writes)."""
    from datetime import datetime
    from cutecat import headless, routines as R

    # --- cron ------------------------------------------------------------
    assert R.cron_matches("0 9 * * *", datetime(2026, 7, 14, 9, 0))
    assert not R.cron_matches("0 9 * * *", datetime(2026, 7, 14, 9, 1))
    assert R.cron_matches("*/15 * * * *", datetime(2026, 7, 14, 3, 45))
    assert R.cron_matches("0 9 * * 1-5", datetime(2026, 7, 14, 9, 0))   # a Tuesday
    assert not R.cron_matches("0 9 * * 1-5", datetime(2026, 7, 12, 9, 0))  # Sunday
    assert R.cron_matches("0 9 * * 0", datetime(2026, 7, 12, 9, 0)), "sunday is 0"
    nxt = R.next_run("0 9 * * *", datetime(2026, 7, 14, 10, 0))
    assert nxt == datetime(2026, 7, 15, 9, 0), nxt
    for bad in ("* * * *", "99 * * * *", "0 9 * * 9", "x * * * *", "*/0 * * * *"):
        try:
            R.parse_cron(bad)
            raise AssertionError(f"accepted bad cron {bad!r}")
        except R.RoutineError:
            pass

    # --- storage ---------------------------------------------------------
    for existing in R.load():
        R.remove(existing["id"])
    made = R.create("standup", "summarise the day", cron="daily", cwd=str(tmp))
    assert made["cron"] == R.PRESETS["daily"], made["cron"]
    assert made["permissions"] == "safe", "writes must be opt-in"
    assert R.find("standup")["id"] == made["id"]
    assert R.find(made["id"][:6])["id"] == made["id"], "id prefix lookup"
    try:
        R.create("standup", "again")
        raise AssertionError("duplicate name accepted")
    except R.RoutineError:
        pass
    assert R.set_enabled("standup", False)["enabled"] is False
    assert R.describe(R.find("standup")) == "paused"
    R.set_enabled("standup", True)

    # --- due --------------------------------------------------------------
    nine = datetime(2026, 7, 14, 9, 0)
    assert R.is_due(R.find("standup"), nine), "not due at its cron minute"
    assert not R.is_due(R.find("standup"), datetime(2026, 7, 14, 9, 1))
    # a scheduler that slept through 09:00 still catches it on the next tick
    assert R.is_due(R.find("standup"), datetime(2026, 7, 14, 9, 5),
                    last_tick=datetime(2026, 7, 14, 8, 58)), "missed minute not caught up"
    paused = R.set_enabled("standup", False)
    assert not R.is_due(paused, nine), "a paused routine fired"
    R.set_enabled("standup", True)

    # a one-off is due once, then never again
    once = R.create("cleanup", "remove the flag", once_at="2026-01-01T09:00",
                    cwd=str(tmp))
    assert R.is_due(once, datetime(2026, 7, 14, 9, 0)), "one-off never fired"
    R.record_run(once, "ok", "sess-1")
    fired = R.find("cleanup")
    assert not R.is_due(fired, datetime(2026, 7, 14, 9, 0)), "one-off fired twice"
    assert fired["enabled"] is False, "one-off did not auto-disable"
    R.remove("cleanup")

    # --- an unattended run ------------------------------------------------
    # the harness's config is connected to FakeProvider
    cfg = config_mod.load_config()
    assert cfg["provider"] == "fake" and cfg["model"], cfg
    workdir = tmp / "routine-work"
    workdir.mkdir(exist_ok=True)
    runme = R.create("check", "look around", cron="hourly", cwd=str(workdir))

    # a read-only command runs, then the agent answers
    FakeProvider.scripted_turns = [
        [("tool_call", {"name": "run_command", "arguments": {"command": "echo hi"}})],
        [("content", "I looked, all good")],
    ]
    status, session_id = headless.run_routine(runme)
    assert status == "ok", status
    assert FakeProvider.last_tools is not None, "the routine ran without tools"
    saved = config_mod.load_session(session_id)
    assert saved is not None, "the run was not saved as a session"
    assert saved["title"] == "routine: check"
    assert any(m["role"] == "tool" and "hi" in m["content"] for m in saved["messages"]), (
        saved["messages"]
    )
    assert saved["messages"][-1]["content"] == "I looked, all good"
    after = R.find("check")
    assert after["runs"] == 1 and after["last_status"] == "ok", after
    assert after["last_session"] == session_id

    # SAFE mode: a write is refused, and the refusal is reported
    FakeProvider.scripted_turns = [
        [("tool_call", {"name": "create_file",
                        "arguments": {"path": str(workdir / "nope.txt"),
                                      "content": "x"}})],
        [("content", "could not write")],
    ]
    status, session_id = headless.run_routine(R.find("check"))
    assert not (workdir / "nope.txt").exists(), "safe mode wrote a file!"
    assert "refused" in status, status
    saved = config_mod.load_session(session_id)
    assert any("denied" in m.get("content", "") for m in saved["messages"]), saved

    # a routine with writes allowed may actually write
    writer = R.create("writer", "write the file", cwd=str(workdir),
                      permissions="auto")
    FakeProvider.scripted_turns = [
        [("tool_call", {"name": "create_file",
                        "arguments": {"path": str(workdir / "yes.txt"),
                                      "content": "written"}})],
        [("content", "done")],
    ]
    status, _ = headless.run_routine(writer)
    assert status == "ok", status
    assert (workdir / "yes.txt").read_text() == "written", "writes mode could not write"

    # run-specific context (the API-trigger equivalent) reaches the prompt
    FakeProvider.scripted_turns = [[("content", "ack")]]
    headless.run_routine(R.find("check"), text="ALERT-42 fired")
    sent = FakeProvider.last_messages
    assert "ALERT-42 fired" in sent[1]["content"], sent[1]["content"]
    assert "look around" in sent[1]["content"], "the saved prompt was dropped"
    # and the system prompt tells it nobody is watching
    assert "unattended" in sent[0]["content"], sent[0]["content"][:200]

    FakeProvider.scripted_turns = []
    for leftover in R.load():
        R.remove(leftover["id"])


def _test_browser():
    """The headless-browser tool. The render test runs against a local server,
    so the suite still needs no network."""
    from cutecat import browser, tools as tools_mod

    # html -> readable text
    html = """
      <html><head><style>p{color:red}</style><script>var x = 1 < 2;</script></head>
      <body><h1>Title &amp; more</h1><p>First para.</p><p>Second&nbsp;para.</p>
      <ul><li>one</li><li>two</li></ul></body></html>
    """
    text = browser.to_text(html)
    assert "Title & more" in text, text
    assert "var x" not in text and "color:red" not in text, "script/style leaked"
    assert "First para." in text and "one" in text and "two" in text, text
    assert "\n\n\n" not in text, "blank lines not collapsed"

    # a configured browser that doesn't exist is a clear error, not a crash
    try:
        browser.find_browser("/no/such/browser")
        raise AssertionError("accepted a bogus browser path")
    except browser.BrowserError as exc:
        assert "not a browser" in str(exc), exc

    class Ctx:
        class shell:
            cwd = str(tmp)
        chromium = None
        ask_tmp = staticmethod(lambda: True)
        note = staticmethod(lambda _m: None)
        ask_permission = staticmethod(lambda _t, _d: True)
        ask_edit = ask_permission

    assert tools_mod.browse(Ctx, {}).startswith("error: no url")
    assert "unknown action" in tools_mod.browse(Ctx, {"url": "x.com", "action": "dance"})
    assert "browse" in tools_mod.DISPATCH
    names = {t["function"]["name"] for t in tools_mod.TOOL_SCHEMAS}
    assert "browse" in names, names

    # writing a file asks first, and a refusal is honoured
    class Deny(Ctx):
        ask_permission = staticmethod(lambda _t, _d: False)

    out = tools_mod.browse(Deny, {"url": "example.com", "action": "screenshot"})
    assert out.startswith("error: user denied"), out

    exe = browser.find_browser()
    if exe is None:  # no Chrome/Chromium here — the rest needs one
        print("  (no browser installed: skipped the render test)")
        return

    # a page whose content only exists after JavaScript runs — the whole point
    # of this tool over curl
    import http.server, socketserver, threading

    page = (b"<html><body><div id=a>LOADING</div><script>"
            b"document.getElementById('a').innerHTML='<h1>Hello JS</h1>';"
            b"</script></body></html>")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *a):
            pass

    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as httpd:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/"
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        text = tools_mod.browse(Ctx, {"url": url, "wait_ms": 2000})
        assert "Hello JS" in text, f"javascript did not run: {text!r}"
        assert "LOADING" not in text, "got the pre-render DOM"

        shot = tmp / "shot.png"
        out = tools_mod.browse(Ctx, {"url": url, "action": "screenshot",
                                     "path": str(shot), "width": 400, "height": 300,
                                     "full_page": False, "wait_ms": 2000})
        assert out.startswith("saved"), out
        assert _png_size(shot) == (400, 300), _png_size(shot)
        httpd.shutdown()

    # full-page screenshots go through the DevTools protocol, because Chrome's
    # command line can only ever capture the viewport
    tall = (b"<html><body style='margin:0'>"
            + b"".join(b"<div style='height:200px'>row</div>" for _ in range(20))
            + b"</body></html>")

    class TallHandler(Handler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(tall)))
            self.end_headers()
            self.wfile.write(tall)

    with socketserver.TCPServer(("127.0.0.1", 0), TallHandler) as httpd:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/"
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        full = tmp / "full.png"
        out = tools_mod.browse(Ctx, {"url": url, "action": "screenshot",
                                     "path": str(full), "width": 800, "height": 600,
                                     "wait_ms": 1000})  # full_page defaults to True
        assert out.startswith("saved"), out
        width, height = _png_size(full)
        assert width == 800, width
        # the document is ~4000px tall; a viewport shot would be 600
        assert height > 3000, f"not a full-page capture: {width}x{height}"
        httpd.shutdown()


def _png_size(path):
    import struct
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n", "not a png"
    return struct.unpack(">II", header[16:24])


def _test_cross_platform():
    """The Windows/fish/newline paths. We can't run Windows here, so the logic
    is driven directly with the platform switches flipped."""
    import signal
    from cutecat import clipboard, policy, shell as shell_mod
    from cutecat.app import SHELL_DIRECTIVES

    # --- shell selection ------------------------------------------------
    # fish/csh cannot run our POSIX wrapper, so $SHELL must be ignored for them
    real_shell = os.environ.get("SHELL")
    try:
        os.environ["SHELL"] = "/usr/bin/fish"
        picked = shell_mod._posix_shell()
        assert os.path.basename(picked) != "fish", f"handed the wrapper to fish: {picked}"
        assert os.path.basename(picked) in shell_mod.POSIX_SHELLS, picked
        os.environ["SHELL"] = "/bin/bash"
        if os.path.exists("/bin/bash"):
            assert shell_mod._posix_shell() == "/bin/bash", "ignored a usable $SHELL"
    finally:
        if real_shell is None:
            os.environ.pop("SHELL", None)
        else:
            os.environ["SHELL"] = real_shell

    # a POSIX command still runs, reports its exit code, and carries cwd
    runner = shell_mod.create_shell(os.getcwd())
    assert runner.kind == "posix" and runner.name == "bash"
    job = runner.run("cd / && echo hello")
    job.finished.wait(10)
    assert job.exit_code == 0, job.exit_code
    assert job.output().strip() == "hello", repr(job.output())
    runner.adopt_cwd(job)
    assert runner.cwd == "/", f"cd did not carry over: {runner.cwd}"
    # the command's own exit code survives the wrapper's trailing lines
    job = runner.run("false")
    job.finished.wait(10)
    assert job.exit_code == 1, f"exit code lost: {job.exit_code}"

    # terminate() must not reach for signals this platform lacks. Windows has
    # no SIGKILL — the old code built that tuple unconditionally and blew up.
    job = runner.run("sleep 30")
    runner.terminate(job)
    assert job.finished.wait(5), "terminate did not stop the job"
    if not shell_mod.IS_WINDOWS:
        assert hasattr(signal, "SIGKILL")

    # --- windows shell choice (pure logic, runs anywhere) ---------------
    # the shell follows the OS: nothing to configure. On Windows that is
    # PowerShell when it's installed, else cmd.exe.
    kind, exe = shell_mod._windows_shell()
    assert kind in ("cmd", "powershell") and exe, (kind, exe)
    assert kind == "cmd", "no PowerShell here, so it must fall back to cmd"
    assert shell_mod.shell_kind() == ("posix" if not shell_mod.IS_WINDOWS else kind)

    # each shell gets a wrapper in its own syntax, preserving exit code + cwd
    win = shell_mod.CommandRunner.__new__(shell_mod.CommandRunner)
    win.exe, win.kind = "cmd.exe", "cmd"
    argv, kwargs = win._argv("dir")
    assert argv[:2] == ["cmd.exe", "/c"] and "%errorlevel%" in argv[2]
    assert shell_mod.CWD_MARK in argv[2] and "%CD%" in argv[2]
    win.exe, win.kind = "powershell.exe", "powershell"
    argv, kwargs = win._argv("Get-ChildItem")
    assert "-NoProfile" in argv and "-Command" in argv
    script = argv[-1]
    assert "$LASTEXITCODE" in script and "exit $__rc" in script
    assert shell_mod.CWD_MARK in script and "Get-Location" in script
    assert "creationflags" in kwargs, "no new process group on Windows"

    # the model is told which syntax to write, or it will send bash to cmd.exe
    assert "PowerShell" in SHELL_DIRECTIVES["powershell"]
    assert "cmd.exe" in SHELL_DIRECTIVES["cmd"]
    assert "POSIX" in SHELL_DIRECTIVES["posix"]

    # --- windows command allowlist --------------------------------------
    for cmd in ("dir", "type file.txt", "where python", "findstr /i foo *.txt",
                "tasklist", "ipconfig /all", "systeminfo", "ver", "getmac",
                "Get-ChildItem", "Get-Content .\\a.txt", "Select-String foo *.py",
                "gci | Sort-Object Name", "Test-Path a.txt", "gcm python"):
        assert policy.classify(cmd).allowed, f"read-only command asks: {cmd}"
    for cmd in ("del a.txt", "copy a b", "move a b", "rmdir /s /q x", "attrib +r a",
                "reg add HKCU\\x /v y /d z", "net user bob /add", "netsh int ip set",
                "schtasks /create /tn x /tr y", "wmic process call create calc",
                "runas /user:admin cmd", "Remove-Item a.txt", "Set-Content a.txt x",
                "New-Item x", "Out-File a.txt", "Start-Process calc",
                "Invoke-WebRequest http://x -OutFile a.zip",
                "Get-ChildItem | Where-Object { Remove-Item $_ }",
                "Get-Process | ForEach-Object { Stop-Process $_ }"):
        assert not policy.classify(cmd).allowed, f"writing command runs unasked: {cmd}"
    assert policy.touches_tmp("type %TEMP%\\x") and policy.touches_tmp("gc $env:TEMP\\x")

    # --- clipboard encoding ---------------------------------------------
    # clip.exe decodes stdin with the console codepage; UTF-8 arrives mangled,
    # UTF-16LE with a BOM does not.
    blob = clipboard._encode("héllo →", clipboard.UTF16)
    assert blob.startswith(b"\xff\xfe") and blob.decode("utf-16") == "héllo →"
    assert clipboard._encode("héllo", clipboard.UTF8) == "héllo".encode("utf-8")
    for cmd, enc in clipboard._candidates():
        assert enc in (clipboard.UTF8, clipboard.UTF16) and isinstance(cmd, list)


def _test_newlines():
    """Files keep the line endings they already had; new files get this OS's."""
    from cutecat import tools as tools_mod

    class Ctx:
        class shell:
            cwd = str(tmp)
        ask_tmp = staticmethod(lambda: True)
        note = staticmethod(lambda _msg: None)
        preview_diff = staticmethod(lambda *a: (1, 1))
        ask_edit = staticmethod(lambda *a: True)

    # a CRLF file stays CRLF through an edit, even on Linux
    crlf = tmp / "crlf.txt"
    crlf.write_bytes(b"alpha\r\nbeta\r\ngamma\r\n")
    out = tools_mod.edit_file(Ctx, {"path": str(crlf), "old_string": "beta",
                                    "new_string": "BETA"})
    assert not out.startswith("error"), out
    raw = crlf.read_bytes()
    assert raw == b"alpha\r\nBETA\r\ngamma\r\n", raw
    # the model matched against "\n" text even though the file is CRLF
    text, newline = tools_mod._read_source(crlf)
    assert newline == "\r\n" and "\r" not in text

    # an LF file stays LF (this is what silently broke on Windows before)
    lf = tmp / "lf.txt"
    lf.write_bytes(b"one\ntwo\n")
    out = tools_mod.edit_file(Ctx, {"path": str(lf), "old_string": "two",
                                    "new_string": "TWO"})
    assert not out.startswith("error"), out
    assert lf.read_bytes() == b"one\nTWO\n", lf.read_bytes()

    # overwriting an existing file keeps its convention; a new file gets the OS's
    tools_mod.create_file(Ctx, {"path": str(crlf), "content": "x\ny\n"})
    assert crlf.read_bytes() == b"x\r\ny\r\n", crlf.read_bytes()
    fresh = tmp / "fresh.txt"
    tools_mod.create_file(Ctx, {"path": str(fresh), "content": "a\nb\n"})
    expected = ("a\nb\n").replace("\n", os.linesep).encode()
    assert fresh.read_bytes() == expected, fresh.read_bytes()


def _test_encryption():
    """--encrypt / --decrypt: the store round-trips, and while it is encrypted
    nothing readable is left on disk."""
    from cutecat import crypto

    cfg = config_mod.load_config()
    cfg["api_key"] = "sk-top-secret"
    cfg["api_keys"] = {"fake": "sk-top-secret"}
    config_mod.save_config(cfg)
    config_mod.save_session({
        "id": "enc-test-session",
        "title": "private",
        "messages": [{"role": "user", "content": "my secret plan"}],
        "input_history": ["my secret plan"],
    })
    session_file = config_mod.SESSIONS_DIR / f"enc-test-session{config_mod.SESSION_EXT}"

    assert not crypto.is_encrypted()
    count, legacy = crypto.enable("correct horse battery")
    assert count >= 2, f"encrypted too few files: {count}"
    assert legacy is None, "the test must not touch the real legacy config"
    assert crypto.is_encrypted() and crypto.is_unlocked()

    # nothing readable left on disk
    for path in (config_mod.CONFIG_FILE, session_file):
        raw = path.read_bytes()
        assert crypto.looks_encrypted(raw), f"{path.name} not encrypted"
        assert b"sk-top-secret" not in raw and b"my secret plan" not in raw, path.name

    # unlocked: everything reads back, and writes stay encrypted
    assert config_mod.load_config()["api_key"] == "sk-top-secret"
    assert config_mod.load_session("enc-test-session")["messages"][0]["content"] == (
        "my secret plan"
    )
    assert "private" in [s["title"] for s in config_mod.list_sessions()]
    config_mod.save_config(config_mod.load_config())
    assert crypto.looks_encrypted(config_mod.CONFIG_FILE.read_bytes())

    # locked: reads fail loudly rather than quietly returning defaults (which
    # would let us overwrite the encrypted store with an empty one)
    crypto.lock()
    try:
        config_mod.load_config()
        raise AssertionError("read the config while locked")
    except crypto.CryptoError:
        pass
    try:
        crypto.unlock("wrong passphrase")
        raise AssertionError("a wrong passphrase was accepted")
    except crypto.CryptoError:
        pass
    crypto.unlock("correct horse battery")
    assert config_mod.load_config()["api_key"] == "sk-top-secret"

    # GCM is authenticated: a flipped bit is caught, not decrypted to garbage
    blob = bytearray(session_file.read_bytes())
    blob[-1] ^= 0x01
    session_file.write_bytes(bytes(blob))
    try:
        config_mod.load_session("enc-test-session")
        raise AssertionError("a tampered session was accepted")
    except crypto.CryptoError:
        pass
    config_mod.save_session({"id": "enc-test-session", "title": "private",
                             "messages": [], "input_history": []})

    # and back to plain text
    assert crypto.disable("correct horse battery") >= 2
    assert not crypto.is_encrypted() and not crypto.is_unlocked()
    assert "sk-top-secret" in config_mod.CONFIG_FILE.read_text(encoding="utf-8")
    assert config_mod.load_config()["api_key"] == "sk-top-secret"

    # a stale plaintext copy of the key elsewhere on disk is destroyed, not
    # left sitting next to an encrypted store (a stand-in, never the real one)
    stale = tmp / "stale-config.json"
    stale.write_text('{"api_key": "sk-top-secret"}', encoding="utf-8")
    config_mod.legacy_config_file = lambda: stale
    try:
        _, killed = crypto.enable("correct horse battery")
        assert killed == stale and not stale.exists(), "stale plaintext key survived"
    finally:
        config_mod.legacy_config_file = lambda: None
        crypto.disable("correct horse battery")

    # shred overwrites before unlinking
    victim = tmp / "victim.txt"
    victim.write_text("secret" * 100, encoding="utf-8")
    crypto.shred(victim)
    assert not victim.exists()


def _test_theme_detection():
    """Each desktop's probe, with its real command output faked (we can only
    run one desktop here, but every parser must handle its own dialect)."""
    from cutecat import app as app_mod

    def fake(outputs):
        def run(cmd):
            joined = " ".join(cmd)
            for needle, out in outputs.items():
                if needle in joined:
                    return out
            return ""
        return run

    real_run = app_mod._run
    try:
        # xdg-desktop-portal (GNOME, KDE, XFCE, Sway): 1 = dark, 2 = light
        app_mod._run = fake({"Settings.ReadOne": "(<<uint32 1>>,)\n"})
        assert app_mod._portal_theme() == "dark"
        app_mod._run = fake({"Settings.ReadOne": "(<<uint32 2>>,)\n"})
        assert app_mod._portal_theme() == "light"
        app_mod._run = fake({"Settings.ReadOne": "(<<uint32 0>>,)\n"})
        assert app_mod._portal_theme() is None, "no-preference must not decide"
        # older portals only have the deprecated Read method
        app_mod._run = fake({"Settings.Read ": "(<<uint32 1>>,)\n"})
        assert app_mod._portal_theme() == "dark"

        # GNOME (modern key), and Cinnamon / MATE (older: the gtk theme name)
        app_mod._run = fake({"org.gnome.desktop.interface color-scheme": "'prefer-dark'\n"})
        assert app_mod._gsettings_theme() == "dark"
        app_mod._run = fake({"org.cinnamon.desktop.interface color-scheme": "'prefer-light'\n"})
        assert app_mod._gsettings_theme() == "light"
        app_mod._run = fake({"org.mate.interface gtk-theme": "'Yaru-dark'\n"})
        assert app_mod._gsettings_theme() == "dark"
        app_mod._run = fake({"org.gnome.desktop.interface gtk-theme": "'Adwaita'\n"})
        assert app_mod._gsettings_theme() == "light"

        # KDE Plasma (Plasma 6 and 5) and XFCE
        app_mod._run = fake({"kreadconfig6": "BreezeDark\n"})
        assert app_mod._kde_theme() == "dark"
        app_mod._run = fake({"kreadconfig5": "BreezeLight\n"})
        assert app_mod._kde_theme() == "light"
        app_mod._run = fake({"xfconf-query": "Adwaita-dark\n"})
        assert app_mod._xfce_theme() == "dark"
        app_mod._run = fake({"xfconf-query": "Greybird\n"})
        assert app_mod._xfce_theme() == "light"
        app_mod._run = fake({})
        assert app_mod._xfce_theme() is None, "xfconf absent must not decide"
    finally:
        app_mod._run = real_run

    # this machine's real desktop must give a usable answer either way
    assert app_mod.detect_system_theme() in ("dark", "light")


def _test_key_handling():
    """Saved-per-provider keys, key sanitising, and junk in config.json."""
    import json as _json

    # whatever the user pastes, we get the key out of it
    clean = config_mod.clean_api_key
    assert clean('  "sk-abc123"  ') == "sk-abc123"
    assert clean("Bearer sk-abc123") == "sk-abc123"
    assert clean("export OPENAI_API_KEY=sk-abc123") == "sk-abc123"
    assert clean("sk-abc\n123\r") == "sk-abc123", repr(clean("sk-abc\n123\r"))
    assert clean("   ") == "" and clean("") == "" and clean(None) == ""

    cfg = {"api_keys": {}}
    config_mod.set_api_key(cfg, "openai", "sk-1")
    assert config_mod.get_api_key(cfg, "openai") == "sk-1"
    assert config_mod.get_api_key(cfg, "claude") is None
    config_mod.forget_api_key(cfg, "openai")
    assert config_mod.get_api_key(cfg, "openai") is None
    config_mod.forget_api_key(cfg, "nobody")  # must not raise

    saved = config_mod.CONFIG_FILE.read_text(encoding="utf-8")
    try:
        # a pre-0.16 config (single api_key) is filed under its provider
        config_mod.CONFIG_FILE.write_text(
            _json.dumps({"provider": "openai", "api_key": "sk-old", "model": "gpt-x"}),
            encoding="utf-8",
        )
        cfg = config_mod.load_config()
        assert cfg["api_keys"] == {"openai": "sk-old"}, cfg["api_keys"]

        # a hand-mangled config must not crash us: wrong types, wrong top level
        config_mod.CONFIG_FILE.write_text(
            _json.dumps({"provider": "openai", "api_keys": "not-a-dict", "skills": 7}),
            encoding="utf-8",
        )
        cfg = config_mod.load_config()
        assert cfg["api_keys"] == {} and cfg["skills"] == {}, cfg
        config_mod.CONFIG_FILE.write_text("[1, 2, 3]", encoding="utf-8")
        assert config_mod.load_config()["provider"] is None
        config_mod.CONFIG_FILE.write_text("{not json", encoding="utf-8")
        assert config_mod.load_config()["model"] is None
    finally:
        config_mod.CONFIG_FILE.write_text(saved, encoding="utf-8")

    # a provider handing back a nonsense /models body yields no models, no crash
    from cutecat.providers.openai_compat import OpenAIProvider

    class _Resp:
        status_code = 200
        content = b"x"

        def json(self):
            return {"data": ["gpt-plain-string", {"no_id": 1}, None, {"id": "gpt-x"}]}

    import cutecat.providers.openai_compat as oc

    real_get = oc.requests.get
    oc.requests.get = lambda *a, **k: _Resp()
    try:
        assert OpenAIProvider().list_models("k") == ["gpt-plain-string", "gpt-x"]
    finally:
        oc.requests.get = real_get


def _test_new_features():
    """Session JSONL round-trip, agent-mode prompt, tool support."""
    # --- session persistence in the new lighter format -------------------
    sess = {
        "id": "abc12345-test",
        "created": "2026-07-14T00:00:00+00:00",
        "title": "demo",
        "provider": "openai",
        "model": "gpt-x",
        "messages": [
            {"role": "user", "content": "line1\nline2 with , comma and \"quotes\""},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"type": "function", "function": {"name": "run_command", "arguments": {"command": "ls"}}}
                ],
            },
            {"role": "tool", "tool_name": "run_command", "content": "ok"},
        ],
        "input_history": ["ls", "multi\nline entry"],
    }
    config_mod.save_session(sess)
    path = config_mod.SESSIONS_DIR / f"{sess['id']}{config_mod.SESSION_EXT}"
    assert path.exists(), "jsonl session not written"
    back = config_mod.load_session(sess["id"])
    assert back["messages"] == sess["messages"], "messages did not round-trip"
    assert back["input_history"] == sess["input_history"], "history did not round-trip"
    assert back["title"] == "demo" and back["model"] == "gpt-x"
    assert sess["id"] in [s["id"] for s in config_mod.list_sessions()], "not listed"
    assert config_mod.resolve_session("abc12345") == sess["id"], "prefix resolve failed"
    # Lighter than the old indent=2 JSON blob.
    import json as _json
    heavy = len(_json.dumps(sess, indent=2))
    assert path.stat().st_size < heavy, "jsonl not smaller than pretty json"

    # --- provider tool-support flag -------------------------------------
    from cutecat.providers.openai_compat import OpenAIProvider, PerplexityProvider
    assert PerplexityProvider().supports_tools is False, "perplexity should be chat-only"
    assert OpenAIProvider().supports_tools is True

    # --- agent-mode system prompt ---------------------------------------
    from cutecat.app import BUILD_DIRECTIVE, PLAN_DIRECTIVE, PLAN_FILE
    assert PLAN_FILE in PLAN_DIRECTIVE and "PLAN" in BUILD_DIRECTIVE
    assert "do not" in PLAN_DIRECTIVE.lower() or "not make any changes" in PLAN_DIRECTIVE.lower()


def _test_providers():
    """Provider classes + the OpenAI/Anthropic history translations.

    (The test harness swaps the PROVIDERS registry for a FakeProvider, so we
    exercise the real classes directly rather than the global list.)"""
    from cutecat.providers.anthropic import AnthropicProvider
    from cutecat.providers.openai_compat import (
        DeepSeekProvider,
        GoogleProvider,
        GrokProvider,
        OpenAIProvider,
        PerplexityProvider,
    )

    ids = {
        p.id
        for p in (
            OpenAIProvider(), AnthropicProvider(), GoogleProvider(),
            DeepSeekProvider(), PerplexityProvider(), GrokProvider(),
        )
    }
    for pid in ("openai", "claude", "google", "deepseek", "perplexity", "grok"):
        assert pid in ids, f"missing provider {pid}"

    # the Custom API provider: reads base_url + wire from config and dispatches
    # to the OpenAI (Chat Completions) or Anthropic (Messages) delegate.
    from cutecat.providers.custom import (
        CustomProvider, _CustomAnthropic, _CustomOpenAI,
    )
    from cutecat.providers.base import ProviderError
    cust = CustomProvider()
    assert cust.id == "custom"
    _keep_cfg = config_mod.load_config()   # restore afterwards for later tests
    try:
        # unconfigured -> a clear error, never a crash
        config_mod.save_config({})
        try:
            cust.settings()
            raise AssertionError("settings() should raise when unconfigured")
        except ProviderError:
            pass
        # openai wire, trailing slash trimmed
        config_mod.save_config({"custom": {"base_url": "https://gw/v1/", "wire": "openai"}})
        d = cust._delegate()
        assert isinstance(d, _CustomOpenAI) and d.BASE_URL == "https://gw/v1"
        # anthropic wire
        config_mod.save_config({"custom": {"base_url": "https://anth", "wire": "anthropic"}})
        d = cust._delegate()
        assert isinstance(d, _CustomAnthropic) and d.BASE_URL == "https://anth"
        # an unknown wire falls back to openai
        config_mod.save_config({"custom": {"base_url": "https://x", "wire": "weird"}})
        assert isinstance(cust._delegate(), _CustomOpenAI)
    finally:
        config_mod.save_config(_keep_cfg)
    # the free tier was removed
    import cutecat.providers as _prov
    assert not any("naga" in p.id or "free" in p.id for p in _prov.PROVIDERS), \
        "a free provider is still registered"
    assert not hasattr(_prov.PROVIDERS[0], "free"), "the 'free' flag lingers"

    history = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"type": "function", "function": {"name": "run_command", "arguments": {"command": "ls"}}}
            ],
        },
        {"role": "tool", "tool_name": "run_command", "content": "out"},
    ]

    # OpenAI: tool_call id must equal the following tool_call_id; args stringified.
    oai = OpenAIProvider()._to_openai_messages(history)
    call_id = oai[2]["tool_calls"][0]["id"]
    assert oai[2]["content"] is None, "assistant content should be None with only tools"
    assert isinstance(oai[2]["tool_calls"][0]["function"]["arguments"], str), "args not stringified"
    assert oai[3]["tool_call_id"] == call_id, "tool result id not paired"

    # Anthropic: system split out, tool_use/tool_result paired, results in a user turn.
    ap = AnthropicProvider()
    system_text, msgs = ap._split(history)
    assert system_text == "sys", system_text
    tool_use = msgs[1]["content"][0]
    assert tool_use["type"] == "tool_use" and tool_use["input"] == {"command": "ls"}
    tool_res = msgs[2]["content"][0]
    assert msgs[2]["role"] == "user" and tool_res["type"] == "tool_result"
    assert tool_res["tool_use_id"] == tool_use["id"], "anthropic ids not paired"
    schema = ap._tools([{"type": "function", "function": {"name": "x", "description": "d", "parameters": {"type": "object"}}}])
    assert schema[0] == {"name": "x", "description": "d", "input_schema": {"type": "object"}}, schema

    # Gemini 3: a tool call's opaque extra_content must survive the round-trip
    # so the signed thought_signature can be echoed back next turn.
    sig = {"google": {"thought_signature": "abc123"}}
    hist2 = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "type": "function",
                    "function": {"name": "run_command", "arguments": {"command": "ls"}},
                    "extra_content": sig,
                }
            ],
        },
        {"role": "tool", "tool_name": "run_command", "content": "ok"},
    ]
    replayed = OpenAIProvider()._to_openai_messages(hist2)
    assert replayed[0]["tool_calls"][0].get("extra_content") == sig, "signature dropped"

    # A captured signature always wins over the fallback sentinel.
    g_replayed = GoogleProvider()._to_openai_messages(hist2)
    assert g_replayed[0]["tool_calls"][0]["extra_content"] == sig, "google clobbered real sig"

    # Gemini: an unsigned tool call gets the documented skip sentinel; a plain
    # OpenAI-compatible provider adds nothing.
    unsigned = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"type": "function", "function": {"name": "run_command", "arguments": {"command": "ls"}}}
            ],
        },
        {"role": "tool", "tool_name": "run_command", "content": "ok"},
    ]
    g_tc = GoogleProvider()._to_openai_messages(unsigned)[0]["tool_calls"][0]
    assert g_tc["extra_content"]["google"]["thought_signature"] == "skip_thought_signature_validator"
    assert "extra_content" not in OpenAIProvider()._to_openai_messages(unsigned)[0]["tool_calls"][0]

    # The error parser must never crash, whatever shape the body takes —
    # this is the exact list body Gemini returned that used to raise.
    from cutecat.providers.openai_compat import _msg as _oai_msg
    gemini_body = [{"error": {"code": 400, "message": "missing thought_signature", "status": "INVALID_ARGUMENT"}}]
    assert _oai_msg(gemini_body) == "missing thought_signature", _oai_msg(gemini_body)
    assert _oai_msg({"error": {"message": "bad key"}}) == "bad key"
    assert _oai_msg("plain string") == "plain string"


asyncio.run(main())
