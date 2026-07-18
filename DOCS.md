<div align="center">

# cutecat — the guide

Everything cutecat can do, in one place.
The [README](README.md) gets you installed and running; this is the rest.

</div>

---

### Contents

**Getting things done**
&nbsp;·&nbsp; [Commands](#commands)
&nbsp;·&nbsp; [Using the interface](#using-the-interface)
&nbsp;·&nbsp; [The coding agent](#the-coding-agent)
&nbsp;·&nbsp; [Shell access & permissions](#shell-access-and-permissions)
&nbsp;·&nbsp; [Git and GitHub](#git-and-github)
&nbsp;·&nbsp; [Browsing (headless Chromium)](#browsing-headless-chromium)

**Automation & agents**
&nbsp;·&nbsp; [Routines](#routines)
&nbsp;·&nbsp; [Agents: build vs plan](#agents-build-vs-plan)
&nbsp;·&nbsp; [Skills](#skills)
&nbsp;·&nbsp; [Sessions](#sessions)
&nbsp;·&nbsp; [Compacting](#compacting)
&nbsp;·&nbsp; [Discord bot](#discord-bot)

**Setup & config**
&nbsp;·&nbsp; [Providers & API keys](#providers-and-api-keys)
&nbsp;·&nbsp; [Editor](#editor)
&nbsp;·&nbsp; [Theme](#theme)
&nbsp;·&nbsp; [Encryption](#encrypting-your-chats-and-settings)
&nbsp;·&nbsp; [Windows](#windows)

**Shipping**
&nbsp;·&nbsp; [Where everything lives](#where-everything-lives)

---

## Commands

Type `/` in the chat to see a live preview of the commands as you type, and press
`Tab` to autocomplete (`/mod` → `/model`).

| command | what it does |
| --- | --- |
| `/connect` | connect to an API — keys are remembered per provider (`/connect new` replaces one) |
| `/model` | switch the active model without losing the conversation |
| `/schedule` | save a prompt as a [routine](#routines) that runs on a schedule |
| `/routines` | list your routines — run, pause, or delete one |
| `/agents` | switch agent: **build** (execute) or **plan** (write `PLAN.md`) |
| `/compact` | summarise the history so far, so it costs far fewer tokens |
| `/sessions` | open one of your previous sessions |
| `/new` | start a fresh session |
| `/clear` | clear the current conversation |
| `/skills` | turn skills on/off — a checklist: type to search, `enter` toggles |
| `/editor` | compose in your editor (`/editor <binary>` sets which) |
| `/config` | edit your settings (`config.json`) in your editor — decrypts to edit, re-encrypts on save |
| `/theme` | pick a theme — **live preview** as you move; 30 including `default`, `matrix`, `hacker-red`, `catppuccin`, … |
| `/help` | list the commands · `/help <command>` explains one |
| `/exit` | quit (also `/quit`, or `ctrl+d`) |

And on the command line:

Run `cutecat --help` for this list; **subcommands are shown above the options**.

| command | what it does |
| --- | --- |
| `cutecat` | start a new session |
| `cutecat --continue` / `-c` | resume the most recent session |
| `cutecat --resume <id>` | resume a session by id (or a unique prefix) |
| `cutecat sessions` | list your past sessions (so you know what to resume) |
| `cutecat skill <options>` | add/list/remove [skills](#skills) — `--list`, `--fetch`, `--path`, … |
| `cutecat routines [options]` | manage [routines](#routines) — `--list`, `--add`, `--run`, `--serve`, `--install`, … |
| `cutecat discord [options]` | the [Discord bot](#discord-bot) — `--setup`, `--run`, `--install`, … |
| `cutecat --encrypt` / `--decrypt` | put your chats and keys behind a [passphrase](#encrypting-your-chats-and-settings) |
| `cutecat --version` / `-v` | print the version (with a smiling cutecat) |

## Using the interface

Your messages appear as grey bars prefixed with `❯`; replies stream in as
markdown, with syntax-highlighted code blocks whose line numbers live in a
separate, unselectable column (so copied code is always clean source).

**Pickers** — `/model`, `/theme`, `/sessions`, `/routines`, `/skills`, the
provider list — all behave the same way:

- `↑`/`↓` (or the mouse wheel) moves the selection, which always stays in view
- **just start typing to search**; `backspace` deletes, `ctrl+u` clears
- `enter` chooses · `esc` cancels

`/skills` is a checklist: `enter` ticks the highlighted skill on or off and
leaves the list open, so you can search, tick several, and `esc` when done.

Keys: `enter` sends; to insert a line break, **end the line with `\` and
press enter** (the input grows up to 8 lines); `up`/`down` move between lines
and recall input history at the top/bottom edge; `ctrl+shift+c` copies the
selection; `esc` cancels a running request, task, or open prompt; `pgup`/
`pgdn` scrolls the chat; `ctrl+End` jumps to the bottom. Pasting a long
multi-line text collapses it to `[pasted N lines]` in the input — the full
text is sent.

When you scroll up, two clickable pills float over the chat: a **"Jump to the
bottom ↓"** pill at the bottom, and a **"↑ &lt;your previous input&gt;"** pill
at the top that scrolls to the previous message you sent (click again to keep
going up).

**Copy/paste.** Drag with the mouse to select any text on screen — replies, code,
anything (the selection highlights in inverse); `ctrl+c` or `ctrl+shift+c` copies
it to the system clipboard (via `wl-copy`/`xclip`/`xsel`/`pbcopy`/`clip`, falling
back to the terminal's OSC 52). `ctrl+shift+v` pastes.

**While the agent works** the status line above the input stays up for the whole
turn and says what it's doing: `pondering`, `running · npm test`, `working ·
browse`, or `waiting for you` while a permission popup is open. When it goes
away, the agent is genuinely done — and every finished answer ends with how long
it took (`baked for 17s`).

## Providers and API keys

`/connect` lists every API you can connect to; pick one, paste your key, then
choose a model. The choices are:

- **Ollama Cloud** — hosted models on ollama.com
- **ChatGPT (OpenAI)** — GPT models
- **Claude (Anthropic)** — Claude models
- **Google Gemini** — Gemini models (has a free tier)
- **DeepSeek** — chat & reasoner models
- **Perplexity** — web-connected Sonar models
- **Grok (xAI)** — Grok models
- **Custom API** — your own endpoint (see below)

**Custom API.** Point cutecat at any OpenAI- or Anthropic-compatible service —
a self-hosted model, a gateway/proxy, LM Studio, vLLM, LiteLLM, OpenRouter, and
so on. Pick **Custom API** in `/connect`, choose the wire format (**OpenAI** =
the Chat Completions API, or **Anthropic** = the Messages API), enter the base
URL (e.g. `https://your-host/v1`), then the key — cutecat fetches the available
models from the endpoint and works exactly like a built-in provider (streaming,
tools, the model picker). The base URL and wire live under `"custom"` in
`config.json`; the key is stored like any other provider's. To change the
endpoint later, run `/connect` and pick Custom API again (the current URL is
pre-filled).

**Your keys are remembered per provider.** You enter a key once; from then on
`/connect` → provider goes straight to the model list. To replace a key (it was
rotated, or you pasted the wrong one), run `/connect new`. A key that the
provider rejects is never kept — cutecat says so and asks again. Keys live in
`~/.cutecat/config.json`, which is written owner-read/write only.

They all support the same agent loop: streaming replies, hidden reasoning, and
tool calls (run_command / read_file / edit_file / create_file). The model list
for each is fetched live from the provider, so new models appear automatically.
Under the hood, most speak the OpenAI chat-completions format; Claude uses
Anthropic's Messages API — cutecat translates its tool calls and history to
each provider's shape for you.

## The coding agent

cutecat can read a project and edit code through five tools: `run_command`
(explore with ls/grep/find, run builds/tests), `read_file` (numbered, with
offset/limit so it reads only what it needs), `edit_file`, `create_file`, and
`browse` (a headless browser — see below).

Edits are **surgical, not rewrites**: `edit_file` replaces one exact snippet
(`old_string` → `new_string`), so a one-line change costs a few tokens
instead of resending the whole file. Every edit is shown as a **git-style
diff** in the chat before it's applied — removed lines on dark red with a
`-`, added lines on dark green with a `+`, syntax-highlighted, with line
numbers in a non-selectable gutter — and you approve it in the popup. Answer
`y` to apply once, `n` to reject, or `a` to allow every edit for the rest of
the session (so it stops asking). The line numbers and markers never end up
in copied code.

## Shell access and permissions

The agent has real access to your system through a **persistent shell**
(one live bash/zsh on Unix, cmd on Windows — `cd` and env vars persist
between its commands). It can inspect files, run builds, and use `curl`.

- **Read-only commands run without asking** — a large allowlist of
  information-only tools (`ls`, `cat`, `grep`, `find`, `df`, `free`, `ps`,
  `ping`, `dig`, `whois`, `curl`, `git status/log`, `--version`, …).
- **Commands that change something ask first** — writing/creating files,
  redirections (`>`), `sudo`, installing, `git commit`, running scripts,
  etc. Answer `y` to allow, anything else denies.
- **Editing/creating files** (`edit_file`, `create_file`) always shows a diff
  and asks.
- **Temp directory** (`/tmp`, `%TEMP%`) is gated once per session, then
  remembered.
- **Commands have no timeout** and never get stuck. While one runs you can
  press `esc` to stop just that command (the agent carries on with the
  result), or `ctrl+b` to send it to the **background** so the agent keeps
  working — its output is delivered to the agent when it finishes.
- **Command output isn't dumped into the chat.** Each command appears as a
  collapsed line (`$ npm test   exit 0 · 42 lines`); click it to see the
  output, click again to collapse it away.

## Git and GitHub

cutecat drives `git` and the **`gh` GitHub CLI** through its shell, so it can
inspect history, branch, stage, commit, push, open PRs, and create repos.
Read-only commands (`git status/log/diff`, `gh pr list`, `gh repo view`, …)
run freely; anything that writes (`git commit/push`, `gh repo create`,
`gh pr merge`, …) asks you first.

Install the CLI and log in once:

```bash
# Fedora: sudo dnf install gh   ·   macOS: brew install gh
gh auth login
```

Permission requests appear as a **popup just above the input**, not in the
chat. Answer with a single key: `y` allow, `n` deny (the agent keeps going
and gets the refusal), `esc` cancel the whole task.

Copy/paste: **drag with the mouse to select** any text on screen — replies,
code, anything (the selection highlights in inverse); press `ctrl+c` or
`ctrl+shift+c` to copy it to the system clipboard (uses `wl-copy`/`xclip`/
`xsel`/`pbcopy`/`clip`, falling back to the terminal's OSC 52).
`ctrl+shift+v` pastes.

Code blocks are syntax-highlighted with a line-number gutter and no
background. The line numbers are a separate, unselectable column, so copied
code is always clean source — no numbers.

## Browsing (headless Chromium)

curl only gets you the bytes a server sends — on a page that renders itself in
JavaScript, that's an empty shell. So cutecat also has a **`browse`** tool that
drives a real headless Chrome/Chromium: it loads the page, runs its scripts, and
gives the agent what a human would actually see.

- **text** (default) — the readable text of the rendered page
- **html** — the rendered DOM
- **screenshot** — a PNG (`"take a screenshot of example.com"`)
- **pdf** — the page printed to PDF

Screenshots are **full-page by default** — the whole document, not just the
first screenful. Chrome's command line can only capture the viewport, so these
go over the DevTools protocol instead (cutecat speaks it directly; no Selenium,
no Playwright, no extra dependency). Ask for `full_page: false` if you only want
what's above the fold.

Reading a page needs no permission (same as `curl`); **saving a PNG or PDF asks
first**, like any other file write. Each run uses a throwaway profile, so it
never touches — or is blocked by — the browser you already have open.

It uses whatever is installed (`chromium`, `google-chrome`, `brave`, `msedge`,
including the usual macOS/Windows install paths). To pin a specific one, set
`"chromium"` in `~/.cutecat/config.json` to its full path. With no browser
installed, the tool says so and tells you how to install one — nothing else
breaks.

## Routines

A **routine** is a saved prompt that cutecat runs for you, unattended, on a
schedule — the same idea as [Claude Code's
routines](https://code.claude.com/docs/en/routines), except these run on your
machine instead of Anthropic's cloud.

Create one from the chat, in plain English:

```
/schedule every weekday at 9am, summarise yesterday's commits and list what's unfinished
```

cutecat drafts the routine (name, prompt, cron), shows it to you, and asks what
it's allowed to do. `/routines` lists them — pick one to run it now, pause it, or
delete it. Everything is also on the CLI:

```bash
cutecat routines --list
cutecat routines --add standup --prompt "summarise yesterday's git log" --every daily
cutecat routines --add deps --prompt "check for outdated deps" --cron "0 9 * * 1"
cutecat routines --add cleanup --prompt "remove the old flag" --at "2026-08-01 09:00"
cutecat routines --run standup --text "focus on the parser work"
cutecat routines --serve        # stay up and fire routines when they come due
cutecat routines --tick         # fire whatever is due, then exit (put this in cron)
```

**Triggers.** `--every hourly|daily|weekdays|weekly`, any 5-field `--cron`
expression, or `--at` for a one-off that fires once and disables itself.

Nothing fires unless a scheduler is running. The easy way, on **any** OS:

```bash
cutecat routines --install   # and: cutecat routines --uninstall
```

That hands the job to whatever your system uses — **cron** on Linux, a
**launchd** agent on macOS, the **Task Scheduler** on Windows — so routines keep
running with cutecat closed. It's idempotent, and it leaves your other cron jobs
alone. Prefer to keep it in a terminal instead? `cutecat routines serve` works
everywhere too, and a `--serve` that was asleep at the appointed minute still
catches up on its next tick. `cutecat routines --run <name> [--text "..."]` is the on-demand trigger:
any deploy script, git hook, or CI job can fire a routine and hand it context,
which is the local equivalent of Claude Code's API trigger.

**Permissions — read this part.** A routine has no human to ask, so what it may
do is fixed when you create it:

| | |
| --- | --- |
| `safe` (default) | read-only commands and file reads. Edits, writes and anything that changes the system are **refused**. |
| `--allow-writes` | everything, unattended: a real shell on your machine with no one watching. |

Claude Code can default to full autonomy because its routines run in a throwaway
cloud sandbox. Yours don't — so cutecat defaults to `safe`, and you opt in per
routine. Only use `--allow-writes` for a prompt you have read and trust.

**Runs.** Every run is saved as an ordinary session: `/sessions` shows it, and
`cutecat --resume <id>` opens the transcript or lets you carry on the
conversation by hand. `cutecat routines --list` shows the last status of each.

## Agents: build vs plan

`/agents` switches between two agents. **build** (the default) carries out your
requests directly, and if a `PLAN.md` exists in the working directory it reads
and executes it step by step. **plan** doesn't change anything — whatever you
describe, it investigates read-only and writes a detailed `PLAN.md` in the
project directory. Switch back to build later and it picks up that plan and
executes it. The choice is remembered across sessions.

## Sessions

Every launch is a new session with its own uuid and its own input history
(the up arrow never shows entries from other sessions). From your first
message the agent generates a short title and sets it as your **terminal tab
title** in the form `Title - <session-id>` (via OSC, so it works in any
terminal); the title is saved with the session and restored on resume.

The **top-left shows the tokens used this session, sent and reply separately** —
`↑2.2k sent  ↓0.3k reply`. "Sent" is what goes to the model each turn (mostly the
system prompt, the tool definitions, and the growing history — so even a one-word
message sends ~2k); "reply" is what it wrote back. When you quit, cutecat prints
the line to pick the conversation back up:

```
cutecat --resume <id>
```

You can resume any session that way (a full uuid or a unique prefix), or
`cutecat --continue` for the most recent, or `/sessions` from inside.

## Compacting

Long sessions accumulate a lot of history. `/compact` asks the model to
summarise the conversation so far, then replaces the stored history with just
that summary — so reopening the session, or switching to another model, doesn't
have to re-read everything. Sessions are stored in a lightweight line-based
format (one record per line) rather than pretty-printed JSON, keeping the files
small.

## Skills

A skill is a markdown file of instructions the agent follows when it's relevant.
`/skills` opens a searchable checklist: `↑`/`↓` to move, **type to search**,
**`enter` to turn a skill on or off**, `esc` when you're done. The ones you enable
are appended to the system prompt and remembered in `config.json`.

**Thirty programming skills ship with cutecat** and are installed into
`~/.cutecat/skills/` on first run. They arrive **turned off** — enable the ones
you want with `/skills`. The topics follow what the well-known skill collections
converge on ([karanb192/awesome-claude-skills](https://github.com/karanb192/awesome-claude-skills),
[VoltAgent/awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills)),
rewritten for cutecat's format:

| | |
| --- | --- |
| **Working** | `debugging` · `reading-unfamiliar-code` · `writing-plans` · `executing-plans` · `brainstorming` |
| **Testing** | `testing` · `tdd` · `flaky-tests` · `web-app-testing` |
| **Changing code** | `refactoring` · `error-handling` · `concurrency` · `performance` |
| **Review & git** | `code-review` · `receiving-code-review` · `git-commits` · `git-worktrees` · `finishing-a-branch` |
| **Systems** | `api-design` · `database-migrations` · `observability` · `secure-coding` |
| **Ops** | `docker` · `github-actions` · `bash-scripting` · `dependency-upgrades` |
| **Languages** | `python-idioms` · `typescript-idioms` |
| **Writing** | `writing-docs` · `writing-skills` |

They encode the craft that models routinely skip: reproduce before you fix,
profile before you optimise, watch the test fail before you make it pass, expand
before you contract a schema, never build SQL with an f-string.

**Add more from anywhere.** `cutecat skill` manages them from the command line:

```bash
cutecat skill --list                      # what you have, and what's on
cutecat skill --fetch <url>               # download a .md and add it
cutecat skill --path ~/notes/style.md     # add one from your disk
cutecat skill --new deploy-checklist      # a starter skill to edit
cutecat skill --enable tdd                # (also --disable, --remove)
cutecat skill --show tdd                  # print one
cutecat skill --export tdd ./tdd.md       # copy one out to share
cutecat skill --reset                     # put the bundled ones back
```

`--fetch` takes the GitHub link you'd copy from your browser and turns it into
the raw file for you. The skill is named after the file, minus the `.md` — and a
file literally called `SKILL.md` is named after its directory, which is how the
public collections lay them out, so
`.../skills/docx/SKILL.md` becomes the `docx` skill. Use `--name` to override it,
`--force` to replace an existing one, `--enable` to turn it on straight away.

**A fetched skill is instructions, not data** — the model reads it and follows it.
So `--fetch` shows you what it downloaded, warns you if it's very long (an
enabled skill is loaded in full on *every* turn) or if it references files it
couldn't fetch, and asks before saving. `--yes` skips the question in a script.

**Write your own** — drop any `.md` file into `~/.cutecat/skills/`, or start from
`cutecat skill --new <name>`. Keep it short, open with a title and a "use when …"
line so the model knows when it applies, and be concrete: a checklist and a
worked example beat a paragraph of advice. cutecat never overwrites a skill file
you have edited.

## Editor

`/editor` opens your message in a real editor. Which one is up to you — set
`"editor"` in `~/.cutecat/config.json` to any binary, with arguments if you want
them:

```json
"editor": "code -w"
```

`/editor <binary>` (e.g. `/editor nano`, `/editor /usr/bin/emacs -nw`) sets the
same thing from the chat and saves it. With nothing set, cutecat falls back to
`$VISUAL`/`$EDITOR`, then to nvim/vim/vi (notepad on Windows, TextEdit on macOS).

## Theme

`/theme` opens a picker with **live preview** — the whole UI recolours as you
arrow through the list, `enter` keeps the one you're on, `esc` puts back what you
had. There are **30 themes** (7 with a light background):

- **`default`:** your terminal's own background and text colour — cutecat paints
  nothing of its own, so it matches whatever your terminal theme is (light or dark)
- **on black:** `matrix` (green), `hacker-red`, `phosphor` (amber CRT), `tron`
  (cyan), `frost` (blue), `synthwave` (purple), `flamingo` (pink), `forest`
- **multi-colour dark:** `ember`, `vaporwave`, `cobalt`, `midnight`, `catppuccin`
  (Mocha), `tokyo-night`, `everforest`, `kanagawa`, `dracula`, `nord`, `gruvbox`,
  `monokai`, `solarized-dark`
- **light:** `light`, `solarized-light`, `sepia`, `catppuccin-latte`,
  `parchment`, `rosewater`, `meadow`

plus `system`. `/theme <name>` sets one directly. With **system**, cutecat keeps
following your desktop: flip your OS between dark and light while it's running
and the UI switches over immediately, no restart and nothing printed in the
chat. `dark` and `light` pin the theme and stop following.

It reads the theme from whatever your system offers, in this order:

| OS / desktop | how it's read |
| --- | --- |
| GNOME, KDE Plasma, XFCE, Sway, … | `xdg-desktop-portal` (`org.freedesktop.appearance`) |
| GNOME, Cinnamon, MATE, Budgie | `gsettings` (`color-scheme`, else the GTK theme name) |
| KDE Plasma | `kreadconfig6`/`kreadconfig5`, else `~/.config/kdeglobals` |
| XFCE | `xfconf-query` (`/Net/ThemeName`) |
| macOS | `AppleInterfaceStyle` |
| Windows | `AppsUseLightTheme` in the registry |

Changes arrive as events where the desktop can send them (the portal's
`SettingChanged` signal, or `gsettings monitor`), so the switch is instant and
there's no polling. Where it can't (macOS, Windows), and as a backstop
everywhere else, the setting is simply re-read on a timer.

## Discord bot

Chat with cutecat from the Discord app — on your phone, anywhere — while the bot
runs on your machine or a VPS. It answers **only you**, **only in one channel**,
and it drives the same agent as the terminal.

```bash
cutecat discord --setup          # token, your user id, the channel
cutecat discord --run            # start it (foreground)
cutecat discord --install        # or: run it as an always-on service (systemd/launchd)
```

**Set-up.** Create a bot at the [Discord developer
portal](https://discord.com/developers/applications), enable its **Message
Content Intent** (Bot → Privileged Gateway Intents), invite it to your server,
and copy the bot token, your own user id, and the channel id (Developer Mode →
right-click → Copy ID). `cutecat discord --setup` asks for these. Connect a model
the normal way with `/connect` in the terminal — **API keys never go through
Discord.**

**Access.** Default-deny: a message is answered only if it's from your user id,
in your channel (or a thread under it). Everything else is ignored in silence.
The bot token is equivalent to a shell account on the machine — keep it out of
any repo (it lives in `config.json`, or encrypt the store).

**The channel stays clean.** While it works you see one status line (`⚙ running ·
npm test · 0m22s`) that's **deleted when it's done** — no thinking, no command
output, no clutter. The answer is one message; if it's too long for Discord's
2000-character limit it continues in more messages, split so a code block is
never cut in half. Replies are kept short by design (a brevity instruction the
terminal doesn't use).

**Everything works there:**

| in Discord | |
| --- | --- |
| just type | chat with the agent |
| `/model` `/skills` `/agents` `/compact` | same as the terminal, with autocomplete |
| `/new` | fresh conversation |
| `/clear` | delete your messages, the bot's, and the history |
| `/stop` | cancel what it's doing |
| `/routines` | list your routines |
| permission | **buttons** (Allow / Deny / Allow-all), not a keypress |
| "send me the screenshot" | it uploads the file to the channel |
| attach a file | the agent reads it |
| a **voice message** | transcribed, then answered in text (see below) |

**Voice and images.** A multimodal model gets them **directly**: send an image to
Gemini, OpenAI or Claude and it sees it; send a voice message to Gemini and it
hears it. With a text-only model, voice falls back to **transcription** — set
`discord.stt` to `"local"` (faster-whisper, bundled in the binary and run on
the machine) or `"api"` (an OpenAI-compatible endpoint) — and an image
becomes a note that the model can't see it. The media only counts against the
turn it arrives on; it isn't stored in the chat history.

**Workspace.** Set `"workspace"` in `config.json` to a directory and the agent —
in Discord *and* the terminal — may only read and write under it. This bounds the
blast radius, which matters most when a remote chat can run commands on your box.

**Deploy.** `cutecat discord --install` registers it as a `systemd --user` service
(Linux/VPS) or a launchd agent (macOS) that restarts on failure and at boot. On a
headless VPS, run `loginctl enable-linger $USER` so it keeps running with no
login session. The bot connects *outbound* to Discord — no open ports, no public
IP, works behind NAT.

See `PLAN.md` for the full design and what's still on the list (live testing needs
your token; direct-audio-to-model and channel-posted routine results are
follow-ups).

## Windows

**The shell follows the operating system — there is nothing to configure.** On
Windows cutecat runs commands in PowerShell when it's installed (`pwsh` or
`powershell`) and falls back to cmd.exe; everywhere else it uses bash/sh. The
agent is told which shell it's driving, so it writes PowerShell cmdlets, cmd
syntax, or POSIX accordingly rather than guessing — and `cd` carries between
commands in all of them, exactly as it does in a real terminal.

The permission model works the same way there: `dir`, `type`, `where`, `findstr`,
`tasklist`, `ipconfig`, `Get-*`, `Select-String`, `Test-Path` and friends run
without asking, while anything that writes — `del`, `copy`, `reg`, `net`,
`schtasks`, `Remove-Item`, `Set-Content`, `Out-File`, `runas` — asks first. A
PowerShell script block (`… | Where-Object { Remove-Item $_ }`) always asks,
since a brace can hide anything.

Files keep the line endings they already have: an LF file stays LF and a CRLF
file stays CRLF, whichever OS you're on. A brand-new file gets the local
convention (CRLF on Windows, LF elsewhere).

## Encrypting your chats and settings

Your API keys and every chat live in `~/.cutecat`. Put them behind a passphrase:

```bash
cutecat --encrypt     # asks for a new passphrase (twice)
cutecat --decrypt     # asks for it, puts everything back to plain text
```

While encrypted, `config.json` and every session file are **AES-256-GCM**
ciphertext: the key is scrypt-derived from your passphrase (N=2¹⁷ — about a
quarter-second and 128MB of memory *per guess*, so brute-forcing is expensive),
each file gets a fresh nonce, and GCM's authentication means a tampered file is
rejected rather than quietly decrypting to garbage. cutecat asks for the
passphrase once at startup and keeps the key in memory only; new chats are
written encrypted.

**There is no recovery, by design.** The passphrase is stored nowhere — no hint,
no escrow, no reset. If you lose it, those chats and keys are gone for good, and
that is exactly what makes them safe.

Encrypting also cleans up after itself: the plaintext it replaces is overwritten
before being unlinked, and a stale pre-0.3 copy of your config (in
`~/.config/cutecat/`, which holds an api key in the clear) is destroyed. While
encrypted, the temp file `/editor` writes your draft to is scrubbed too.

What is *not* encrypted: `SYSTEM.md`, your `skills/`, and any `PLAN.md` the plan
agent writes into your project — none of which hold secrets. And overwriting is
best-effort: on a copy-on-write filesystem (btrfs, ZFS) or an SSD, freed blocks
can survive underneath, so full-disk encryption is still the right backstop.

## Where everything lives

All state lives in `~/.cutecat` on every OS:

```
~/.cutecat/config.json     settings: provider, api keys (one per provider),
                           model, theme, editor, agent mode, browser
~/.cutecat/SYSTEM.md       the agent's system prompt — edit it freely
~/.cutecat/skills/*.md     skills, toggled with /skills
~/.cutecat/sessions/*.jsonl  one file per chat, named by uuid
~/.cutecat/routines.jsonl  your routines
~/.cutecat/encrypted.json  only if you ran --encrypt: the salt, never the key
```

Sessions are line-based (one record per line) rather than pretty-printed JSON,
which keeps them small. `config.json` is written owner-read/write only, since
your API keys are in it.

The settings you can only set by editing `config.json` (everything else has a
command):

| key | what it does |
| --- | --- |
| `"editor"` | the binary `/editor` opens, e.g. `"code -w"` — see [Editor](#editor) |
| `"chromium"` | full path to the browser `browse` should use — see [Browsing](#browsing-headless-chromium) |
