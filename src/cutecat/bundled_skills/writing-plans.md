# Writing an implementation plan

Use when a change touches several files, has an ordering constraint, or would be
expensive to get wrong — and whenever you are asked to plan rather than build.

A plan is not an essay. It is the ordered list of steps you'd want if you had to
hand the work to someone else halfway through.

## Investigate first, then write

Read the code before planning it. A plan written from assumptions is fiction:
open the files, find the call sites, run the tests, and check what already
exists. State what you found.

## The shape

```markdown
## Goal
One sentence. What is true when this is done that isn't true now.

## Context
What exists today, with file:line pointers. What constrains the design.

## Approach
The design, in a paragraph. Say why this one and what you rejected.

## Steps
1. <change> — <file> — verified by <command / test>
2. ...
Each step: small, independently verifiable, leaves the tree working.

## Risks
What could break, what you're unsure of, what you'd check first if it did.

## Out of scope
What you are deliberately not doing.
```

## Rules

- **Every step names how it is verified.** A step you can't check is a step you
  can't trust.
- **Order by dependency, not by file.** If step 3 can't run until step 1 lands,
  say so.
- **Keep each step to one idea.** "Refactor the parser and add caching" is two.
- **Say what you don't know.** An honest open question is worth more than a
  confident guess that sends the work down the wrong path.
- **No code in the plan** beyond a signature or a key snippet. The plan is for
  deciding; the code is for after.
