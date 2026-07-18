# Upgrading dependencies

Use when bumping a library, updating a lockfile, dealing with a vulnerability
alert, or when the user says "update the deps".

**Small, verifiable steps.** Upgrading forty packages in one commit means the
one that broke the build is unfindable.

## The order

```
- [ ] 1. Is the tree green NOW? Establish the baseline first.
- [ ] 2. Security fixes first, then patch, then minor, then major.
- [ ] 3. One major upgrade per commit. Group patches if they're quiet.
- [ ] 4. Read the CHANGELOG for anything major. Not the diff — the changelog.
- [ ] 5. Run the tests. Then run the app, not just the tests.
- [ ] 6. Commit the lockfile with the manifest, in the same commit.
```

## Rules

- **Never bump a major version blind.** Semver's promise is that majors break
  things. Find the migration guide; if there isn't one, budget more time.
- **Commit the lockfile.** A lockfile that drifts from the manifest is how "works
  on my machine" happens.
- **Don't loosen a pin to make a conflict go away.** Understand why they
  conflict. `>=1.0` on a transitive dep is a future 3am page.
- **Check what a "harmless" bump actually pulls in.** A patch release can add a
  new transitive dependency. `pip install --dry-run`, `npm ls <pkg>`, `cargo
  tree` before you trust it.
- **A vulnerability alert needs judgement, not obedience.** Is the vulnerable
  code path one you actually call? A CVE in a dev-only tool is not the same as
  one in your request handler. Say which it is.
- **Tests passing is not enough** for a big upgrade — run the thing. Type
  checkers and test suites don't catch a changed default, a changed timezone
  behaviour, or a slower query plan.

## Reporting

Say what you upgraded, what changed behaviourally (not just the version
numbers), what you verified, and what you couldn't verify.
