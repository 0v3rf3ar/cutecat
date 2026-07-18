# Secure coding

Use when writing or reviewing code that handles user input, authentication,
secrets, files, network requests, or a shell — and whenever asked for a security
review.

The rule behind all of the below: **never mix untrusted data with code or
commands.** Keep them in separate channels, and let the interpreter — SQL driver,
shell, template engine — do the separating.

## The checklist

**Injection** — data must never be parsed as code.
- SQL: parameterised queries only. `execute("… WHERE id = ?", (user_id,))`.
  Never build SQL with f-strings or `+`, not even "just for an int".
- Shell: pass an argv list, never a string. `subprocess.run(["git", "log",
  branch])`, never `shell=True` with interpolation.
- Never `eval`, `exec`, `pickle.loads`, or `yaml.load` on anything a user can
  influence. (`yaml.safe_load`.)
- HTML: escape by default; a template engine's autoescape is your friend. Only
  mark trusted HTML safe.

**Secrets**
- Never in the source, never in git, never in a log line, never in an error
  message returned to the user. Read them from the environment or a secret store.
- If a secret was ever committed, it is compromised — rotate it; deleting the
  file is not enough.
- Don't log request bodies or headers wholesale: that is how passwords and
  tokens end up in the log aggregator.

**Authentication and authorisation**
- Authorise on the **server**, for **this** user, on **every** request — not just
  in the UI that hides the button.
- Check ownership of the object, not just that someone is logged in
  (`GET /invoice/1234` must check *whose* invoice 1234 is).
- Passwords: `bcrypt`/`argon2`/`scrypt`. Never a raw SHA, never your own scheme.
- Compare secrets and tokens with a constant-time compare (`hmac.compare_digest`).

**Paths and files**
- A user-supplied filename can be `../../etc/passwd`. Resolve it and check it is
  still inside the directory you meant (`Path(base, name).resolve()` then verify
  `base` is a parent).
- Don't extract archives blindly (zip-slip); check each member's path first.
- Create temp files with `mkstemp`, not a predictable name in `/tmp`.

**Network and crypto**
- TLS verification stays **on**. `verify=False` is not a fix.
- Use a vetted library. Never invent a crypto scheme, never use ECB, never reuse
  a nonce, never seed with `random` (use `secrets`).

**Errors**
- Fail closed: on an error, deny. A `try/except: pass` around a permission check
  is a vulnerability.
- Show the user a generic message; log the detail server-side.

## Reporting

For each finding: **where**, **what an attacker does**, **what it costs**, and
**the fix**. Rank by exploitability × impact — not by how easy it was to spot.

Do not claim code is "secure". Say what you checked and what you found.
