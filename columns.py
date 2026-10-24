"""Columns of a list, and how a row of them reads to a screen reader.

Nothing here knows about GitHub or wx, so it can move into app-kit for the
other apps to share. ``gh_columns`` describes GHManage's own columns.

A native list reads its cells in column order, so the cell text and the order
of the columns are what a screen reader says. Field names, when they're
spoken, go into the cells themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, Mapping, Sequence

# A text column needs its name to make sense ("Author: Kelly"); a state
# column's value already says what it is ("open", "success"), so it is never
# given one — "State: open" is only noise.
TEXT = "text"
STATE = "state"


@dataclass(frozen=True)
class ColumnDef:
    id: str            # the key a row's values are stored under; never shown
    heading: str       # the column heading, and the name spoken before a value
    kind: str = TEXT
    width: int = 100
    spoken_label: str = ""  # when the name spoken should differ from the heading

    @property
    def label(self) -> str:
        return self.spoken_label or self.heading

    def with_(self, **changes) -> "ColumnDef":
        return replace(self, **changes)


@dataclass(frozen=True)
class ColumnSet:
    """The columns one kind of list can show, and those it shows at first."""
    id: str
    name: str
    columns: tuple[ColumnDef, ...]
    defaults: tuple[str, ...]

    @property
    def ids(self) -> list[str]:
        return [c.id for c in self.columns]

    def column(self, col_id: str) -> ColumnDef:
        for c in self.columns:
            if c.id == col_id:
                return c
        return ColumnDef(col_id, col_id)

    def defs(self, ids: Iterable[str]) -> list[ColumnDef]:
        return [self.column(i) for i in ids]


def cell_text(col: ColumnDef, value: str, speak_labels: bool) -> str:
    """One cell: the value, with the column's name before it when names are
    spoken and the column needs one. An empty cell stays empty."""
    if not speak_labels:
        return value
    if not (value or "").strip():
        return ""
    if col.kind == TEXT:
        return f"{col.label}: {value}"
    return value


def row_text(values: Mapping[str, str], columns: Sequence[ColumnDef],
             speak_labels: bool = True, separator: str = ", ") -> str:
    """A whole row as one line, in column order, empty cells left out."""
    parts = [cell_text(c, values.get(c.id, "") or "", speak_labels) for c in columns]
    parts = [p.strip() for p in parts if p and p.strip()]
    if not parts:
        return ""
    out = parts[0]
    for p in parts[1:]:
        # "Title: Fix crash." then ", Author" reads as a stumble; a part that
        # already ends a phrase only needs the space.
        if separator.startswith(",") and out[-1] in ".?!:;":
            out += " " + p
        else:
            out += separator + p
    return out
