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


def names_cell(position: int) -> bool:
    """Whether the cell at this position may carry its column's name. Never
    the first: it is the row's name, read first, and typing a letter in a
    list jumps by it — "Repository: ..." on every row would stop "g" finding
    the repositories starting with g."""
    return position > 0


def row_text(values: Mapping[str, str], columns: Sequence[ColumnDef],
             speak_labels: bool = True, separator: str = ", ") -> str:
    """A whole row as one line, in column order, empty cells left out. The
    first column is never named (see ``names_cell``)."""
    parts = [cell_text(c, values.get(c.id, "") or "", speak_labels and names_cell(i))
             for i, c in enumerate(columns)]
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


def reconcile(saved, column_set: ColumnSet) -> list[str]:
    """A saved layout made safe to use: columns the set no longer has, and
    repeats, are dropped, the saved order kept. Columns added since stay off
    until chosen. Nothing usable left means the set's defaults."""
    known = set(column_set.ids)
    out: list[str] = []
    for col_id in saved if isinstance(saved, (list, tuple)) else []:
        if isinstance(col_id, str) and col_id in known and col_id not in out:
            out.append(col_id)
    return out or list(column_set.defaults)


class LayoutEditor:
    """The columns a list shows, being changed: what a Columns dialog does,
    without the dialog, so the rules are the same wherever it's drawn and can
    be tested without windows. Each action returns False when there was
    nothing it could do (already at the top, the last column), for the
    dialog to say so."""

    def __init__(self, column_set: ColumnSet, shown) -> None:
        self.column_set = column_set
        self.shown: list[str] = reconcile(shown, column_set)

    def available(self) -> list[str]:
        """The columns not shown, in the set's order."""
        return [i for i in self.column_set.ids if i not in self.shown]

    def add(self, available_index: int) -> bool:
        """Show an available column, at the end of the row."""
        rest = self.available()
        if not 0 <= available_index < len(rest):
            return False
        self.shown.append(rest[available_index])
        return True

    def remove(self, index: int) -> bool:
        """Stop showing a column. The last one always stays."""
        if not 0 <= index < len(self.shown) or len(self.shown) == 1:
            return False
        del self.shown[index]
        return True

    def move(self, index: int, target: int) -> bool:
        if not (0 <= index < len(self.shown) and 0 <= target < len(self.shown)) \
                or index == target:
            return False
        self.shown.insert(target, self.shown.pop(index))
        return True

    def reset(self) -> None:
        self.shown = list(self.column_set.defaults)

    def changed_from(self, saved) -> bool:
        return self.shown != reconcile(saved, self.column_set)
