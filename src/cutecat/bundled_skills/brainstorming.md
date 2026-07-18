# Brainstorming a design

Use when the user is deciding *what* to build or *how* to structure it — an API,
a schema, an architecture — and before writing a plan for anything non-obvious.

Your job here is not to produce code. It is to make the trade-offs visible so the
user can choose.

## Ask before you answer

The first useful move is usually a question. Ask about the things that change the
answer:

- **Scale**: ten records or ten million? Once a day or a thousand a second?
- **Consistency**: can this be stale for a minute? What must never be lost?
- **Who else touches it**: other services, other teams, existing clients?
- **Reversibility**: is this a door you can walk back through? (If yes, decide
  quickly and move on. If no, slow down.)
- **The real constraint**: deadline, headcount, an existing system you can't
  change?

Ask two or three, not ten. Then propose.

## Offer options, not a verdict

```markdown
## Option A — <name>
How it works, in two lines.
Good: …
Bad: …
Costs you: <complexity / latency / money / a migration>

## Option B — …

## Recommendation
A, because <the constraint that decides it>. B would be right if <the thing
that would have to be true>.
```

Two or three options. One is a lecture; five is a menu nobody can read.

## Rules

- **Always give a recommendation.** A survey with no opinion pushes the work back
  onto the user, which is the opposite of help.
- **Name the thing that decides it.** "Both are fine" is never true — find the
  constraint that breaks the tie.
- **Say what you'd regret.** The failure mode of each option, and how you'd know
  early that you picked wrong.
- **Prefer the boring option.** Novelty is a cost paid by whoever is on call.
- **Don't design past the requirement.** The generic, configurable, plugin-based
  version is usually a worse answer to a question nobody asked.
