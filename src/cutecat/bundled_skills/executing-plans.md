# Executing a plan

Use when working through a plan (a PLAN.md, an issue, a checklist) rather than a
single ad-hoc change.

## The loop

For each step, in order:

```
- [ ] 1. Re-read the step. Do only what it says.
- [ ] 2. Make the change.
- [ ] 3. Run the step's verification (its test, its command).
- [ ] 4. Green? Report it in one line and move on.
- [ ] 5. Red? Fix it before touching the next step.
```

Show progress as you go — tick the steps off. A plan silently executed to the
end is impossible to follow and impossible to stop.

## Rules

- **Never skip ahead.** If step 4 looks easy and step 2 looks dull, do step 2.
  The order usually encodes a dependency someone thought about.
- **Never batch the verification.** Running the tests once at the end means a
  failure could come from any of six changes.
- **Stay inside the plan.** If you spot something else worth fixing, note it and
  keep going. Unplanned "while I was in there" changes are how a reviewable diff
  becomes an unreviewable one.
- **Stop when the plan is wrong.** Plans are written before contact with the
  code. If a step turns out to be impossible or mistaken, stop and say so, with
  what you found — don't improvise a different design silently.
- **Leave the tree working at every step.** If a step can't leave it green,
  the plan needed a different split.

## When you finish

Re-read the goal, not the steps: did you achieve the thing, or just complete the
list? Then run the full suite once, and report what changed, what you verified,
and anything you deliberately left undone.
