# Error handling

Use when writing code that can fail — I/O, network, parsing, user input — and
when reviewing a `try/except` that makes you uneasy.

**An error is information.** The only unforgivable thing is to destroy it.

## The rules

- **Never swallow an exception.** `except: pass` and `catch (e) {}` turn a bug
  into a mystery — the symptom appears somewhere else, hours later, with no
  trace. If you truly mean to ignore it, say why in a comment, and log it.
- **Catch what you can handle.** `except Exception` around three lines because
  one of them might raise `KeyError` will also swallow the typo that raises
  `AttributeError`. Catch the specific type.
- **Catch it where you can do something about it.** A retry belongs at the call
  site that knows the operation is idempotent; a user-facing message belongs at
  the boundary. In between, let it propagate.
- **Never lose the cause.** `raise ParseError("bad config") from exc`. Python's
  `from`, JS's `{ cause }`, Go's `%w`. A stack trace that starts at your wrapper
  is half a stack trace.
- **Put the value in the message.** `f"unknown provider: {name!r}"` beats
  "invalid input" — you will read this in a log with no debugger attached.
- **Fail fast on programmer error, gracefully on user error.** A missing config
  key at startup should crash loudly. A malformed request should return a 400.
- **Errors are part of the API.** Decide what a caller can catch and document it.
  Leaking a `psycopg2.IntegrityError` out of your `save_user()` binds every
  caller to your database driver.

## Retries

Only for transient failures (network, 5xx, lock timeout) and only for idempotent
operations. Exponential backoff with jitter, a cap on attempts, and a total
deadline. Retrying a non-idempotent `POST` is how you double-charge someone.

## The shape of a good handler

```python
try:
    resp = session.post(url, json=payload, timeout=10)
    resp.raise_for_status()
except requests.Timeout as exc:
    raise UpstreamUnavailable(f"{url} timed out after 10s") from exc
except requests.HTTPError as exc:
    # 4xx is our bug, 5xx is theirs — they are not the same failure
    if 400 <= exc.response.status_code < 500:
        raise BadRequest(_safe_detail(exc.response)) from exc
    raise UpstreamUnavailable(f"{url} returned {exc.response.status_code}") from exc
```
