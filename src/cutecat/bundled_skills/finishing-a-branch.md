# Finishing a branch

Use when a piece of work is done and you're deciding how to land it: what to
squash, what to merge, what to delete.

## Before you land anything

```
- [ ] the full test suite passes on the branch
- [ ] git diff main...HEAD — read it as a reviewer would, top to bottom
- [ ] no debug prints, no commented-out code, no stray files
- [ ] no secrets, no credentials, no build artifacts
- [ ] the branch is up to date with main, and still green after that
```

Read your own diff. It is the single highest-yield review there is, and the one
most often skipped.

## History: what to keep

The question is what a reader in a year will want. They want commits that are
*meaningful*, not commits that are *chronological*.

- **Squash** the noise: "fix typo", "address review", "wip", "oops". These carry
  no information.
- **Keep** genuinely separate logical changes as separate commits — a refactor
  and the feature it enabled should stay apart, so either can be reverted alone.
- **Rebase onto main** to get a straight history; **merge** if the project's
  convention is merge commits. Follow the repo, not your preference — look at
  `git log --oneline --graph -20` and do what it does.

## Rules

- **Never force-push a branch someone else is on** without asking.
  `--force-with-lease` over `--force`, always.
- **Don't rewrite main.** Ever.
- **Delete the branch after it lands** — locally and on the remote. Stale
  branches are noise, and the commits live on in main.
- **Ask before merging or pushing.** Show what will land; let the user pull the
  trigger.
