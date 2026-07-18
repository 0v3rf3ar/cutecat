from __future__ import annotations

import difflib

Row = tuple[str, "int | None", "int | None", str]


def compute_diff(old: str, new: str, context: int = 3) -> list[list[Row]]:
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)

    hunks: list[list[Row]] = []
    for group in matcher.get_grouped_opcodes(context):
        rows: list[Row] = []
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for off in range(i2 - i1):
                    rows.append(("ctx", i1 + off + 1, j1 + off + 1, old_lines[i1 + off]))
            else:
                for off in range(i2 - i1):
                    rows.append(("del", i1 + off + 1, None, old_lines[i1 + off]))
                for off in range(j2 - j1):
                    rows.append(("add", None, j1 + off + 1, new_lines[j1 + off]))
        if rows:
            hunks.append(rows)
    return hunks


def diff_stats(hunks: list[list[Row]]) -> tuple[int, int]:
    added = removed = 0
    for rows in hunks:
        for kind, _o, _n, _t in rows:
            if kind == "add":
                added += 1
            elif kind == "del":
                removed += 1
    return added, removed
