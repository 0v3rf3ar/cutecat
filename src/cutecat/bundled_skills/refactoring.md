# Refactoring

Use when restructuring code without changing what it does — extracting a
function, renaming, splitting a file, removing duplication, paying down debt.

**A refactor changes structure, never behaviour.** If behaviour changes, it is
not a refactor, and it must not be smuggled into one. Never mix a refactor and a
fix in the same commit: when something breaks afterwards, nobody can tell which
half did it.

## Workflow

```
- [ ] 1. Green before: run the tests, confirm they pass
- [ ] 2. Is it covered? If not, write the characterisation test first
- [ ] 3. One mechanical step at a time
- [ ] 4. Run the tests after each step
- [ ] 5. Green after, with no test changed
```

**Characterisation test.** Before touching code you don't have tests for, write a
test that captures what it does *today* — bugs and all. That test is your safety
net; it tells you the moment you change behaviour by accident.

**One step at a time.** Rename, then run. Extract, then run. Move, then run. A
refactor that touches thirty files in one leap cannot be verified or reviewed,
and it cannot be bisected when it breaks.

**Tests must not change.** If you have to edit a test to make a refactor pass,
you changed behaviour. Stop and work out which.

## Smells worth fixing

- **The same three lines in four places.** Extract — but only after the third
  copy. Two copies is often a coincidence; the wrong abstraction is more
  expensive than duplication.
- **A function you have to scroll.** Split it at the seams where the local
  variables change meaning.
- **A boolean parameter** (`render(x, True)`). Usually two functions wearing a
  trenchcoat.
- **A comment explaining what the next line does.** Rename the thing instead.
- **Deep nesting.** Return early; handle the error case first and get it out of
  the way.
- **Dead code.** Delete it. It isn't documentation, and git remembers.

## Restraint

- **Don't refactor code you were asked to fix**, unless the mess is the reason
  for the bug. Say what you'd change and let the user decide.
- **Match the surrounding style** even when you dislike it. Consistency beats
  your preference; a file with two idioms is worse than one with an unfashionable
  idiom.
- **Leave it working at every commit.** A refactor is only finished when the
  suite is green and nothing else changed.
