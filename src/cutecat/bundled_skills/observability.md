# Logging and observability

Use when adding logging, when asked why something is hard to debug in
production, or when working on a service where you can't attach a debugger.

**Logs are written for the person reading them at 3am with no context.** That
person is usually you. Write for them.

## What to log

- **The boundaries**: a request in (method, path, user, request id), a response
  out (status, duration), a call to an external service (which one, how long, did
  it work).
- **Every decision that isn't obvious from the code path**: "skipped: already
  processed", "falling back to cache".
- **Every error, with its cause and its context** — the id of the thing that
  failed, not just "failed".

## What not to log

- **Secrets.** Tokens, passwords, API keys, session cookies, full request bodies
  and headers on an auth endpoint. Once it's in the log aggregator it's in ten
  more systems, all with looser access than your database.
- **Personal data** you wouldn't put in an email. Log the user *id*, not the
  email address.
- **A log line per row** in a loop over a million rows. Log the summary.

## How

Structured, one event per line, with a correlation id threaded through
everything so a single request can be pulled out of the noise:

```python
log.info("charge.failed", extra={
    "request_id": ctx.request_id, "order_id": order.id,
    "gateway": "stripe", "code": err.code, "attempt": attempt,
})
```

Levels that mean something:
`DEBUG` for developers, `INFO` for what happened, `WARN` for "recovered, but
someone should know", `ERROR` for "a user is affected". If everything is ERROR,
nothing is.

## The three questions a service must answer

1. **Is it up?** — a health endpoint, and a rate of 5xx.
2. **Is it slow?** — latency as a *percentile* (p50/p95/p99). An average hides
   the tail, and the tail is what users feel.
3. **What happened to *this* request?** — a correlation id in every line.

If your change makes any of those harder to answer, it isn't finished.
