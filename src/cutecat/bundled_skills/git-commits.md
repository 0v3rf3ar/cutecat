# Git commits and pull requests

Use when committing, writing a commit message, branching, or opening a PR.

## The message

Say **why**, not what. The diff already shows what changed; it cannot show what
you were thinking.

```
<type>(<scope>): <imperative summary, ≤ 50 chars, no full stop>

Why this change is needed — the problem, not the patch. Wrap at 72.
What the reader would otherwise have to reverse-engineer from the diff.

Fixes #123
```

`type` is one of: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `build`,
`ci`, `chore`.

**Good:**

```
fix(parser): keep the exit code when a command ends with a redirect

The wrapper appended `printf` after the user's command, so $? became the
printf's status and every failing command reported success. Capture $? into
__rc first and exit with it.
```

**Bad:** `fix bug`, `updates`, `changed parser.py`, `WIP`, `address review
comments` — none of these mean anything in six months' time.

## Rules

- **One logical change per commit.** A fix and a refactor in one commit cannot
  be reverted, reviewed, or bisected separately.
- **Stage precisely.** Read `git diff --staged` before committing — not
  `git commit -am` on autopilot. Debug prints and stray files get in that way.
- **Never commit secrets, credentials, or build artifacts.** Check `git status`
  for anything unexpected and respect (or update) `.gitignore`. A secret pushed
  once is compromised forever, even if the next commit deletes it.
- **Work on a branch**, not straight on `main`.
- **Never rewrite published history** (`push --force`, rebasing a shared branch)
  without being asked. `--force-with-lease` if you must.
- **Don't commit or push unless you were asked to.** Show what you'd commit
  first.

## Before committing

```
- [ ] git status        — nothing unexpected staged
- [ ] git diff --staged — no debug prints, no secrets, no unrelated churn
- [ ] tests pass
```

## Pull requests

Title reads like a commit summary. The body answers three questions:

```markdown
## What
One or two sentences.

## Why
The problem this solves. Link the issue.

## How to verify
The command a reviewer runs, and what they should see.
```

Keep PRs small. A 200-line PR gets a real review; a 2000-line PR gets "LGTM".
