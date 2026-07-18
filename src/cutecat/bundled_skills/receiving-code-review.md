# Receiving code review

Use when the user gives you feedback on a change you made, points out a mistake,
or says "that's not right".

The feedback is about the code, not about you. There is nothing to defend.

## For each comment

```
- [ ] Understand it. If you don't, ask — don't guess and "fix" the wrong thing.
- [ ] Decide: agree → change it. Disagree → say why, with evidence.
- [ ] Make the change small and separate.
- [ ] Re-run the tests.
- [ ] Reply to each point: what you changed, or why you didn't.
```

## Rules

- **Never silently ignore a comment.** Answer every one, even if the answer is
  "you're right, but it's out of scope — here's what I'd do instead."
- **Disagreeing is allowed — with evidence.** "That would break streaming:
  `stream.py:88` relies on the buffer being unbounded." Not "I prefer it this
  way." If you're right, the user needs to know; if you're wrong, you find out
  cheaply.
- **Never agree just to be agreeable.** Caving to a wrong review comment puts a
  bug in the code and blames the reviewer for it later.
- **Fix the class, not the instance.** If a reviewer finds one off-by-one, look
  for the other three before you reply.
- **Don't spiral.** A comment on the parser is not permission to rewrite the
  parser. Change what was asked; note anything else you noticed.
- **When it's a real bug, say so plainly** and close the loop: "Good catch — that
  dropped the last row. Fixed, and added a test that fails without the fix." The
  test is the part that stops the same comment coming back.
