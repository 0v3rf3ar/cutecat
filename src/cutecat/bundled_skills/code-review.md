# Code review

Use when asked to review code, a diff, a pull request, or "what do you think of
this?" — and before proposing your own large change.

Review for **correctness first**. Style opinions are cheap; a bug shipped is
expensive. Say what is wrong, why it's wrong, and what would happen — a review
comment without a failure case is just taste.

## What to look for, in priority order

**1. Correctness**
- Off-by-one, wrong operator, inverted condition, wrong variable in a copy-paste
- Edge cases: empty input, one element, zero, negative, `None`/`null`, missing key,
  unicode, a very large value
- Error paths: what happens when this call fails? Is the error swallowed?
- Concurrency: shared mutable state, a check-then-act race, a lock not held
- Resource leaks: file/socket/handle not closed on the error path

**2. Contracts**
- Does it do what its name and docstring claim?
- Are callers updated? (`grep` for every call site — do not assume.)
- Does it break an existing API, on-disk format, or database schema? Is there a
  migration for data written by the old version?

**3. Security** (if it touches input, auth, files, or a shell)
- User input reaching SQL, a shell, `eval`, or a file path
- Secrets in code, in logs, or in an error message
- Authorization checked on the *server*, for *this* user, on *every* path

**4. Tests**
- Is there a test that fails without this change?
- Does it test behaviour, or just re-state the implementation?

**5. Then, and only then**: naming, duplication, structure, dead code.

## How to report it

Group by severity, and be concrete:

```
BUG   parser.py:88 — `chunk[i+1]` reads past the end when the input ends with a
      backslash. `parse("a\\")` raises IndexError. Guard with `i+1 < len(chunk)`.

RISK  api.py:41 — the 500 handler logs `request.body`, which contains the
      password on /login. Log the request id instead.

NIT   utils.py:12 — `tmp2` could be `parsed_rows`.
```

Rules:
- **Quote the file and line.** A review that says "the error handling is weak" is
  not actionable.
- **Give the failing input** where you can. It turns an opinion into a fact.
- **Say when something is fine.** If the change is correct, say so plainly
  rather than inventing nits to look thorough.
- **Don't rewrite it in your own style.** Match the conventions already in the
  file — reviews that impose a personal idiom get ignored.
