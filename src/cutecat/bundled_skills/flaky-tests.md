# Flaky tests

Use when a test passes sometimes and fails other times, or when a test suite is
"just a bit unreliable" — and when writing tests for anything async.

A flaky test is a real bug, either in the test or in the code. It is never
"just flaky". Treat it as a defect, because a suite people don't trust is a
suite people stop reading.

## Find out which kind it is

Run it in a loop until it fails, so you have something to work with:

```bash
for i in $(seq 50); do pytest path/to/test.py::test_name -q || break; done
```

Then look for the usual causes, in order of how often they're the answer:

1. **Waiting on time instead of on a condition.** `sleep(0.5)` then assert. It
   passes on your laptop and fails on a loaded CI box.
2. **Shared state between tests.** A module global, a file on disk, a row in the
   database, an env var. Reveal it by running the tests in a random order, or
   the one test alone (`pytest -p no:randomly path::test` vs the full suite).
3. **Order dependence.** Test B only passes because test A ran first.
4. **Real time, real network, real randomness.** The clock ticks over midnight,
   DNS hiccups, an unseeded shuffle.
5. **Concurrency in the code under test.** The test is right and the code has a
   race. This is the good outcome: you found a real bug.

## The fix: wait for the condition, not the clock

```python
# bad — a race with extra steps
start_server(); time.sleep(1); assert ping() == 200

# good — poll for the thing you actually need, with a timeout
deadline = time.monotonic() + 5
while time.monotonic() < deadline:
    if ping() == 200:
        break
    time.sleep(0.02)
else:
    raise AssertionError("server did not come up in 5s")
```

Same idea everywhere: `expect(locator).toBeVisible()` in Playwright, `waitFor`
in testing-library, a condition variable rather than a sleep.

## Rules

- **Never `@retry` a flaky test.** That's a bug with a mute button.
- **Never delete or skip it** to get the suite green, unless the user says to —
  and then say what you're hiding.
- **Freeze what you can control**: fake the clock, seed the RNG, isolate the
  temp dir, roll back the database per test.
- **Prove the fix**: run it 50 times green before calling it done.
