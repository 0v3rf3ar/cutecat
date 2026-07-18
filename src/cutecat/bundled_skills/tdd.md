# Test-driven development

Use when adding a feature or fixing a bug and the user has asked for TDD, or
when the change is fiddly enough that you want the test to lead.

**Red → green → refactor.** In that order, one small cycle at a time.

```
- [ ] RED      write the smallest failing test. RUN IT. Watch it fail.
- [ ] GREEN    write the least code that makes it pass. Run it. Watch it pass.
- [ ] REFACTOR clean up with the test still green.
- [ ] repeat
```

**RED means you must actually see it fail.** A test you never watched fail may
be passing for the wrong reason — asserting nothing, testing the mock, or never
running at all. If it passes the first time you run it, the test is wrong, not
the code.

**GREEN means the least code.** Hardcode the answer if that's what makes it
pass. The next failing test is what forces you to generalise. This feels absurd
for one cycle and pays for itself the moment a case you hadn't considered
appears.

**REFACTOR is not optional.** Green is when you clean up — it's the only time
the tests can tell you that you broke something.

## Rules

- **One failing test at a time.** Not three; you cannot tell which fix did what.
- **Never write production code without a failing test asking for it.** If you
  can't write the test, you don't yet understand the requirement — that is the
  finding, and it's worth saying out loud.
- **Never edit the test to make it pass.** Change the code. The exception is a
  test that is provably testing the wrong thing; say so explicitly first.
- **Commit at each green.** A red working tree is not a place to stop.

## When TDD is not the answer

Exploration and spikes: when you don't yet know what the code should do, write
throwaway code first, learn, then delete it and start again with the test.
Say that's what you're doing rather than pretending to TDD.
