# Shell scripting

Use when writing a shell script, a Makefile target, or a non-trivial one-liner
that someone will run again.

## The header, always

```bash
#!/usr/bin/env bash
set -euo pipefail      # exit on error, on unset var, and on a failing pipe stage
IFS=$'\n\t'            # word-split on newlines/tabs, not spaces
```

Without `-e` a script keeps running after a failed step and does the next thing
to the wrong state. Without `pipefail`, `false | tee log` succeeds.

## Rules

- **Quote every expansion.** `"$file"`, `"$@"`, `"${arr[@]}"`. An unquoted `$f`
  breaks on the first filename with a space and is a command injection when the
  value comes from outside.
- **`"$@"`, never `$*`.** The latter flattens your arguments into one string.
- **Prefer `[[ ]]` to `[ ]`** in bash, and `-z`/`-n` for emptiness.
- **`$(cmd)`, not backticks.** Nestable and readable.
- **Check that a command exists** before relying on it:
  `command -v jq >/dev/null || { echo "needs jq" >&2; exit 1; }`
- **Write errors to stderr and exit non-zero.** A script that prints "failed" and
  exits 0 will be trusted by the thing that calls it.
- **`mktemp` for temp files**, and `trap 'rm -rf "$tmp"' EXIT` to clean up on
  every exit path.
- **Don't parse `ls`.** Use a glob, or `find -print0` with `read -d ''`.
- **Run `shellcheck`.** It finds the quoting bug you just wrote. Every time.

## When to stop writing shell

The moment you need arrays of structs, arithmetic beyond counting, JSON beyond a
`jq` filter, or error handling with more than one branch — the script wants to be
Python. Say so rather than building a 400-line bash monument.
