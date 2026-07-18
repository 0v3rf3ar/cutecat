# Writing documentation

Use when writing or updating a README, a docstring, a comment, or a guide.

**Write for the person who arrives knowing nothing and needs something to work in
five minutes.** They are not reading for pleasure; they are looking for the one
line that unblocks them.

## A README, in order

1. **What it is** — one sentence, no marketing.
2. **How to install it** — the exact commands, copy-pasteable.
3. **The smallest thing that works** — a first success, in under a minute.
4. **The common tasks** — the five things people actually do.
5. **Everything else** — links out, so this page stays short.

If it can't be scanned in thirty seconds, it will be skimmed and abandoned.

## Rules

- **Show the command, not a description of the command.** "Run the tests with
  `pytest -q`" beats "the test suite can be executed with the usual tooling".
- **Every example must run.** Copy it, paste it, run it. A README that lies is
  worse than one that's missing — it burns trust and an hour.
- **Say the failure modes.** "If you get `ModuleNotFoundError`, you didn't
  activate the venv." That paragraph saves more time than any other.
- **Document why, not what.** The code says what it does. A comment earns its
  place by explaining the constraint, the workaround, the reason for the weird
  bit — the thing the next reader would otherwise "clean up" and break.
- **Delete comments that restate the line below.** They rot into lies.
- **Update the docs in the same commit as the change.** Docs updated "later" are
  docs that are wrong.
- **No time-sensitive wording.** "Currently", "soon", "the new API" all age
  badly. Write it as it is, or date it.

## Comments worth writing

```python
# The browser can still be flushing its profile as we tear it down, and a
# leftover temp file is not worth an exception.
ignore_cleanup_errors=True
```

That comment survives a refactor. `# set the flag to true` does not.
