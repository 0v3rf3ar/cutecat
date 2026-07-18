# Writing a skill

Use when the user asks for a new skill, or when you notice you're being given the
same instructions for the third time — that's a skill trying to exist.

A cutecat skill is a plain `.md` file in `~/.cutecat/skills/`. When it's enabled,
its **whole text is appended to the system prompt on every turn**. So the only
question that matters is: does each line earn its tokens?

## The shape

```markdown
# <Title>

Use when <the situation that should trigger this>.

<The one principle, stated plainly.>

## Workflow / Rules
- Concrete, checkable instructions.
- A short worked example beats a paragraph of advice.
```

## Rules

- **Open with "Use when …"** — a skill the model can't tell when to apply is a
  skill it applies at the wrong moment.
- **Assume the model is competent.** Don't explain what a PDF is, what a test is,
  or what git does. Add only what it *doesn't* already know: your conventions,
  your constraints, the trap it keeps falling into.
- **Keep it under ~80 lines.** Long skills crowd out the conversation. If it's
  growing, it's two skills.
- **Be specific enough to check.** "Handle errors well" is unusable. "Never
  `except: pass`; re-raise with `from exc`" is followable, and a reviewer can
  tell whether it was followed.
- **Show, don't describe.** One before/after pair teaches more than five bullets.
- **No time-sensitive content** ("as of this year", "the new API"). It rots.
- **One idea per skill.** A "misc-tips" skill will never trigger at the right
  time, because it has no right time.

## Test it

Turn it on, give the agent a task the skill should change the behaviour of, and
see whether the behaviour actually changed. If you can't tell the difference with
it on and off, the skill isn't earning its place — sharpen it or delete it.
