# Debugging

Use when something is broken, failing, flaky, or behaving unexpectedly — a
crash, a failing test, a wrong result, a hang.

**Find the cause before you change anything.** A fix you can't explain is a
guess, and guesses move the bug rather than remove it.

## Workflow

```
- [ ] 1. Reproduce it, reliably
- [ ] 2. Read the actual error, all of it
- [ ] 3. Narrow it to the smallest failing case
- [ ] 4. Form one hypothesis and test it
- [ ] 5. Fix the cause, not the symptom
- [ ] 6. Prove it: the repro now passes, nothing else broke
```

**1. Reproduce it.** Get a command that fails every time. If it only fails
sometimes, run it in a loop (`for i in $(seq 20); do …; done`) and find what
makes it flip — order, timing, state left behind, a clock, a random seed.
Without a repro you cannot know you've fixed it.

**2. Read the error.** The whole stack trace, bottom to top: the last frame in
*your* code is usually where to look. Note the exact values in the message. Do
not skim it; the answer is often written there.

**3. Narrow it.** Cut the input down, comment out half, or `git bisect` if it
used to work. Keep halving until the failing surface is a handful of lines. If
it used to work, `git log -p <file>` on what changed is faster than reasoning.

**4. One hypothesis at a time.** State it out loud: *"the cache returns a stale
row because the key omits the tenant id."* Then test that specific claim — print
the key, assert the invariant, add a breakpoint. If the evidence contradicts
you, discard the hypothesis; do not patch it up.

**5. Fix the cause.** Ask "why did this happen?" until you reach something worth
changing. A `try/except` around a crash, a `None` check on a value that should
never be `None`, a `sleep()` before a race — these hide bugs; they don't fix
them.

**6. Prove it.** Re-run the repro. Run the whole test suite. Then add a test
that fails without your fix, so it can never come back silently.

## Tools, in the order to reach for them

1. **Print/log the values.** Unfashionable and usually fastest. Print the thing
   you assume is true; that assumption is where the bug lives.
2. **A real debugger** when the state is deep (`pdb`/`breakpoint()`, `node
   --inspect`, `dlv`, `lldb`). Better than ten print cycles for a complex object.
3. **`git bisect`** when it worked before and doesn't now.
4. **Narrow the world**: reduce concurrency to 1, pin the seed, disable the
   cache. Turn a heisenbug into a deterministic one.

## Rules

- **Never "fix" a test by loosening it** (widening a tolerance, adding a retry,
  deleting an assert) unless the test itself is provably wrong.
- **Report what you found**, not just what you changed: the cause, the evidence,
  the fix, and how you verified it.
- If you're stuck after two failed hypotheses, say so and show what you ruled
  out — that is progress and worth reporting.
