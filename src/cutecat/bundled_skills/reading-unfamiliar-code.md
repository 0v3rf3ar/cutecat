# Reading an unfamiliar codebase

Use when dropped into a project you don't know and asked to change, fix, or
explain something in it — the first thing to do before touching anything.

Do not start by reading files in alphabetical order. Start from the outside and
follow the thread to the thing you were asked about.

## The route in

```
- [ ] 1. What is this? README, package.json/pyproject, Makefile scripts.
- [ ] 2. How is it run and tested? The commands are the contract.
- [ ] 3. Where does it start? main, the entry point, the routes, the CLI.
- [ ] 4. Find your thing. grep for the user-visible string, not the concept.
- [ ] 5. Read outward from there: who calls it, what it calls.
- [ ] 6. Check the tests for it — they are executable documentation.
```

**grep for the symptom, not the abstraction.** The error message the user saw,
the label on the button, the config key — these are unique and lead straight to
the code. "Where is the authentication handled" leads to forty files.

```bash
grep -rn "Invalid session token" --include=*.py .   # the exact string
git log --oneline -20 -- path/to/file               # why is it like this?
git log -S "some_function" --oneline                # when did this appear?
```

**Let git tell you.** `git log -p` on the file you're about to change is often
faster than reading the file — it shows what the last person was trying to do,
and the commit message may explain the weird bit you were about to "clean up".

## Rules

- **Read before you write.** Every time. `read_file` the exact region you intend
  to change, with enough context to be sure.
- **Follow the conventions you find**, even the ones you dislike. Consistency is
  worth more than your preference — you're a visitor.
- **Don't trust the comments; trust the tests.** Comments rot; tests are run.
- **Say what you learned** in a couple of lines before you propose a change. If
  your mental model is wrong, that's when the user can correct you — cheaply.
