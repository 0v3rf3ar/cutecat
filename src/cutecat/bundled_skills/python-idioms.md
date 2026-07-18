# Python

Use when writing or reviewing Python.

## Idioms that matter

```python
# Iterate the thing, not the index
for line in lines: ...                     # not: for i in range(len(lines))
for i, line in enumerate(lines, start=1): ...

# Comprehensions for mapping/filtering; a loop when there are side effects
names = [u.name for u in users if u.active]

# Context managers own resources — no manual close, correct on the error path
with open(path, encoding="utf-8") as f: ...

# EAFP over LBYL for things that are usually there
try:
    value = cfg["key"]
except KeyError:
    value = default
# or just: cfg.get("key", default)

# f-strings, with !r when you're reporting a value in an error
raise ValueError(f"unknown provider: {name!r}")

# pathlib, not os.path string surgery
(root / "config" / "app.json").read_text(encoding="utf-8")
```

## Traps that bite

- **Mutable default argument.** `def f(items=[])` — that list is created once and
  shared across every call. Use `None` and build inside.
- **Late binding in closures.** `[lambda: i for i in range(3)]` all return 2.
  Bind it: `lambda i=i: i`.
- **`except Exception` catching your typos.** Catch the specific exception.
- **Modifying a list while iterating it.** Iterate over a copy, or build a new
  list.
- **`is` for value comparison.** `is` is identity: use it only for `None`, `True`,
  `False`.
- **Text vs bytes.** Decode at the boundary, work in `str`, encode on the way out.
  Always pass `encoding=` — the default is the locale's, and it differs on
  Windows.
- **A bare `assert` for validation.** `python -O` removes them. Raise instead.

## Conventions

Type hints on public functions. Docstrings that say *why*, not what. `ruff` /
`black` if the project uses them — match the project, always. Standard library
before a dependency: `dataclasses`, `pathlib`, `itertools`, `collections`,
`functools.lru_cache` cover an astonishing amount.
