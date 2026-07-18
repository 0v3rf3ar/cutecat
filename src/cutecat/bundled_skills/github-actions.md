# CI with GitHub Actions

Use when writing or fixing a workflow, when CI is failing but the tests pass
locally, or when the pipeline is slow.

## A workflow that behaves

```yaml
name: ci
on:
  push: { branches: [main] }
  pull_request:

# A new push cancels the run still in flight for the same branch.
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 15          # never let a hung job burn an hour
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip            # the cache is usually the whole speed problem
      - run: pip install -e ".[dev]"
      - run: pytest -q
```

## Rules

- **Pin actions to a major version at least** (`@v4`), and to a SHA for anything
  that touches secrets — a compromised tag can exfiltrate them.
- **`timeout-minutes` on every job.** The default is six hours.
- **Never echo a secret**, and remember `set -x` and a failing curl both can.
  Secrets aren't passed to workflows from forked PRs — that's a feature, and it's
  why "it works on my branch but not on the PR" happens.
- **`pull_request_target` runs with your secrets against someone else's code.**
  Do not use it to run their tests. This is the classic CI compromise.
- **Cache the dependency directory, not the whole thing**, and key it on the
  lockfile's hash.
- **Make CI reproducible locally.** If the only way to test the pipeline is to
  push, you will push twenty times. Put the commands in a Makefile and have CI
  call *that*.

## When CI fails but local passes

In order of likelihood: a different version (python/node/OS), a missing env var
or service, a test that depends on files another test left behind (CI runs
clean), a timezone or locale difference, a test that races and only loses on a
slow shared runner, or something not committed. Print the version and the env in
the failing job before you theorise.
