# Performance

Use when something is slow, when asked to optimise, or when asked "why does this
take so long?"

**Measure first. Always.** Intuition about what is slow is wrong often enough
that acting on it wastes the effort. An optimisation without a before-and-after
number is not an optimisation; it's a guess that also made the code worse.

## Workflow

```
- [ ] 1. Reproduce the slowness with a command and a number
- [ ] 2. Profile it — find where the time actually goes
- [ ] 3. Fix the biggest cost, one change
- [ ] 4. Measure again; keep it only if it actually won
- [ ] 5. Check correctness — the tests still pass
```

**1. Get a number.** `time ./thing`, or a benchmark that runs the slow path.
Without a baseline you cannot claim an improvement. State the target: "3.2s
today, needs to be under 1s."

**2. Profile.** Do not read the code looking for slow-looking lines.

```bash
python -X importtime -c 'import app'        # slow startup
python -m cProfile -s cumtime app.py | head -30
py-spy top -- python app.py                 # a running process
node --cpu-prof app.js                      # node
perf record ./bin && perf report            # native
```

For anything talking to a database or an API, count the calls before you time
them — the answer is usually the count, not the speed.

**3. Fix the biggest cost.** In order of how often it's the answer:

- **Doing it N times instead of once** — the N+1 query, a call in a loop that
  could be one batched call, re-reading a file per item.
- **The wrong shape** — a linear scan of a list inside a loop (O(n²)) where a
  `set`/`dict` lookup is O(1). This is the single most common real fix.
- **Doing it at all** — cache it, or skip the work when the input hasn't
  changed. The fastest code is the code that doesn't run.
- **Doing it eagerly** — load lazily, stream instead of reading the whole file,
  paginate.
- **Blocking on I/O one at a time** — issue the requests concurrently.

Only then reach for micro-optimisation, a rewrite, or a faster language. Those
are the last resort, not the first.

**4. Measure again.** Same command, same conditions. If it didn't move the
number, **revert it** — you have added complexity for nothing.

## Rules

- **Never trade correctness for speed.** Run the tests after every optimisation.
- **Don't optimise what isn't hot.** A 90% saving on 1% of the runtime is 0.9%.
- **Report honestly**: "3.2s → 0.4s, from replacing the linear scan in
  `resolve()` with a dict lookup." If it barely moved, say that too.
