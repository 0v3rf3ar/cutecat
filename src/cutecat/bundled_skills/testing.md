# Testing

Use when writing, fixing, or being asked for tests — and after fixing any bug.

A test is only worth its runtime if it can **fail**. Before you write one, ask:
"what change to the code would make this test go red?" If the answer is
"nothing", don't write it.

## Write the test that catches the bug

After a bug fix, the first test to write is the one that **fails without the
fix**. Verify that: stash the fix, watch it go red, restore it, watch it go
green. A regression test you never saw fail may be testing nothing.

## What to test

For any function, walk the same four categories:

| | example |
| --- | --- |
| the happy path | one representative, normal input |
| the edges | empty, one item, zero, negative, max, `None`, missing key, unicode |
| the errors | bad input raises the right error, with a useful message |
| the contract | the invariant that must always hold (round-trip, idempotence, ordering) |

Table-driven tests keep this cheap:

```python
@pytest.mark.parametrize("raw, expected", [
    ("1h", 3600), ("90m", 5400), ("0s", 0), ("", None), ("banana", None),
])
def test_parse_duration(raw, expected):
    assert parse_duration(raw) == expected
```

## Rules

- **Test behaviour, not implementation.** Assert on what the caller sees. A test
  that asserts a private method was called breaks on every refactor and catches
  no bugs.
- **One reason to fail.** If a test can go red for three reasons, its failure
  tells you nothing. Split it.
- **No logic in tests.** No `if`, no loops computing the expected value — write
  the expected value out literally. A test with a bug in it is worse than none.
- **Deterministic.** No real network, no real clock, no random seed, no
  dependence on test order or on files another test left behind. A flaky test
  gets ignored, and then so do the real failures.
- **Fast.** If the suite is slow, people stop running it. Fake the slow edges
  (network, sleep), keep the real logic real.
- **Don't mock what you're testing.** Mock the boundary (the HTTP call, the
  clock), never the thing under test — that only proves the mock works.
- **Assert the message, not just the type.** `pytest.raises(ValueError,
  match="unknown provider")` catches the wrong ValueError; a bare
  `pytest.raises(ValueError)` does not.

## Before you say it's done

Run the whole suite, not just your new test — the interesting failures are the
ones you didn't expect. If a test fails, **fix the code or the test, never the
assertion** just to make it pass.
