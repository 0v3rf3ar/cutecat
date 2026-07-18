# Concurrency

Use when writing or reviewing threads, async code, workers, or anything where two
things touch the same state — and whenever a bug is intermittent.

**If two things can read and write the same state, assume they will, at the
worst possible moment.** Concurrency bugs don't reproduce, don't appear in tests,
and appear in production under load.

## The shapes to recognise

- **Check-then-act.** `if not exists(x): create(x)` — two callers both check,
  both create. Make it atomic instead: a unique constraint, `INSERT … ON
  CONFLICT`, `setdefault`, a `CREATE_NEW` open flag.
- **Read-modify-write.** `count = get(); set(count + 1)` — one of the increments
  vanishes. Use an atomic increment, or a compare-and-set, or a transaction.
- **Shared mutable default / global.** A module-level dict, a cached client, a
  class attribute. Fine until two requests mutate it.
- **The lock you forgot to hold** on one path out of five.
- **Deadlock**: two locks, taken in different orders. Always take them in the
  same order, everywhere, and hold them for as little as possible.

## Rules

- **Don't share state.** The cheapest concurrency bug is the one you can't have:
  pass copies, use immutable data, give each worker its own connection, put the
  contention in a queue or in the database and let it arbitrate.
- **The database is a concurrency primitive.** A unique index, a transaction, a
  `SELECT … FOR UPDATE` — better than a lock in your process, because it works
  across processes and machines too.
- **Never sleep to fix a race.** It isn't a fix; it's a longer window.
- **In async code, never block the loop.** A synchronous `requests.get` or a
  `time.sleep` inside `async def` stalls everything. Use the async client, or
  push it to a thread pool.
- **Bound everything.** An unbounded queue, an unbounded thread pool, an
  unlimited fan-out of tasks — all of them are memory exhaustion under load.
- **A timeout on every wait.** A lock, a queue, a network call. Without one,
  "it hung" is the whole bug report.

## Testing it

You cannot prove correctness by running it once. Loop it, add concurrency, and
use the tools: `pytest -p xdist`, a stress loop, ThreadSanitizer, `go test
-race`. And prefer to make the race impossible rather than unlikely.
