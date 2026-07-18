<div align="center">

# cutecat

**A fast, self-contained AI agent for coding and automation — right in your terminal.**

<pre>
   /\_/\
  ( o.o )
   > ^ <
</pre>

Point it at any model, and it reads your project, runs real shell commands,
edits code with reviewable diffs, drives a headless browser, and runs
unattended on a schedule. One binary. No runtime. No lock-in.

<br>

[![License: MIT](https://img.shields.io/badge/license-MIT-000000?style=flat-square)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org)
[![Platforms](https://img.shields.io/badge/platform-linux%20·%20macOS%20·%20windows-4c4c4c?style=flat-square)](#install)

</div>

---

cutecat turns any OpenAI- or Anthropic-compatible model into an autonomous
coding and automation agent. It works in small, reviewable steps — showing each
command and each diff, and asking before it changes anything — so you stay in
control while it does the tedious work.

> **Status:** early days (`0.x`) and under active development. It's usable
> day-to-day, but expect the occasional rough edge and breaking change. Bug
> reports and PRs are very welcome — [open an issue](../../issues).

```console
$ cutecat
❯ find every TODO in the codebase, group them by file, and write a triage.md

  ⚙ running · rg -n "TODO" --stats · 0m1s
  ⚙ writing · triage.md
  Done — 23 TODOs across 9 files, sorted by area and written to triage.md.
```

## Why cutecat

- **⚡ Fast** — a single compiled binary that starts instantly, streams replies
  token-by-token, and keeps token use low (`/compact` folds a long chat into a
  short summary). No Node, no Electron, no background daemons.
- **🎯 Simple** — one command to connect, one to run. Your keys are remembered,
  the shell is real, and it just works on Linux, macOS, and Windows.
- **🔧 Flexible** — 8+ providers plus **any** custom OpenAI/Anthropic endpoint,
  encrypted storage, and a Discord front-end — compose it however your
  workflow needs.
- **🚀 Powerful** — a persistent shell, git-style diffs, a real headless
  browser, scheduled routines that run unattended, and a plan-then-build mode
  for larger tasks.

## Install

cutecat ships as a single self-contained binary — no Python, no dependencies,
nothing to build. Download the file for your platform from the
[**Releases**](../../releases) page:

| Platform | Download |
|---|---|
| Linux · x86_64 | `cutecat-<version>-linux-x86_64.tar.gz` |
| Linux · arm64 | `cutecat-<version>-linux-arm64.tar.gz` |
| macOS · Apple Silicon | `cutecat-<version>-macos-silicon.zip` |
| Windows · x86_64 | `cutecat-<version>-windows-x86_64.zip` |

Unpack it and run:

```bash
tar -xzf cutecat-*-linux-*.tar.gz   # Linux  (on macOS: unzip the .zip)
./cutecat
```

On Windows, unzip the archive and run `cutecat.exe`.

### Run from source

Prefer to build it yourself (or don't want to run a prebuilt binary)? You only
need Python 3.10+:

```bash
git clone https://github.com/0v3rf3ar/cutecat
cd cutecat
pip install -e .
cutecat
```

## Quickstart

```text
1.  /connect          pick a provider, paste your key, choose a model  (once)
2.  ask for anything  "fix the failing test", "summarise yesterday's commits"
3.  it works step by step, showing commands and diffs, and asks before writing
```

Type `/` for the command list, or `/help`. Press `esc` to stop it any time.

## What it does

| | |
|---|---|
| **Edit code** | surgical, reviewable `edit_file` diffs — never blind whole-file rewrites |
| **Run commands** | a real persistent shell; read-only commands run freely, writes ask first |
| **Browse the web** | headless Chromium that runs JS — page text, full-page screenshots, PDFs |
| **Automate** | save a prompt as a **routine** and run it on a schedule, unattended |
| **Plan → build** | `/agents plan` writes a `PLAN.md`; switch to build and it executes it |
| **Skills** | 30 built-in engineering playbooks (TDD, debugging, review, security, …) |
| **Sessions** | every chat is saved and resumable; `/compact` shrinks a long one |
| **Encrypt** | `cutecat --encrypt` locks chats and API keys behind a passphrase (AES-256) |

## Built for automation

cutecat is designed to run where you aren't — on a server, on a schedule, or
behind a chat window:

- **Routines** — `cutecat routines --add nightly --prompt "..." --every daily`
  runs a task unattended via cron / launchd / Task Scheduler, in a `safe`
  (read-only) mode by default.
- **Headless & scriptable** — drive it from a git hook, CI job, or deploy
  script; the same agent core powers the terminal, routines, and the bot.
- **Discord bot** — run it on a VPS and chat with your agent from anywhere;
  owner-only, single-channel, with voice-message transcription.
- **One file to ship** — the compiled binary carries everything (agent,
  browser hooks, optional voice) so a VPS needs no Python and no `pip`.

## Providers

Connect to **OpenAI · Anthropic (Claude) · Google Gemini · DeepSeek · xAI
(Grok) · Perplexity · Ollama Cloud** — or **Custom API** to point at any
OpenAI- or Anthropic-compatible endpoint (self-hosted models, gateways, LM
Studio, vLLM, LiteLLM, OpenRouter, …). Keys are stored per provider, and the
model list is fetched live.

## Documentation

📖 **[Read the full guide → DOCS.md](DOCS.md)** — every command, the permission
model, routines, the browser, providers, encryption, and the Discord bot.

## License

Released under the [MIT License](LICENSE).
