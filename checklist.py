"""A list of things to check and uncheck, as Set Labels, Set Assignees and
Set Projects show it (#122). No wx.

Each row says its own state, "bug, checked", rather than relying on a check
box drawn beside it: wx's checklist on Windows is drawn by the app, and a
screen reader can't always tell what it shows. Space changes the row, and
what it now is gets said.
"""

from __future__ import annotations

CHECKED = "checked"
UNCHECKED = "not checked"


class Checklist:
    """``options`` in the order given, with ``checked`` ticked. Something
    checked that isn't among the options (an assignee who can no longer be
    assigned, a closed project) is added at the end, so the list never hides
    what the item has."""

    def __init__(self, options: list[str], checked: list[str]) -> None:
        self.names = list(dict.fromkeys(options))
        for name in checked:
            if name not in self.names:
                self.names.append(name)
        self._start = {n for n in checked}
        self.on = set(self._start)
        self.new: list[str] = []   # added in the box, to be created on save

    def add(self, name: str) -> tuple[int, str]:
        """A new one (New Label…, New Project…), checked: its row and what to
        say. One already listed is checked instead of added twice."""
        name = name.strip()
        match = next((i for i, n in enumerate(self.names) if n.lower() == name.lower()), None)
        if match is not None:
            self.on.add(self.names[match])
            return match, f"{self.names[match]} is already listed, now {CHECKED}"
        self.names.append(name)
        self.new.append(name)
        self.on.add(name)
        return len(self.names) - 1, f"{name} added, {CHECKED}"

    def __len__(self) -> int:
        return len(self.names)

    def row(self, i: int) -> str:
        name = self.names[i]
        state = CHECKED if name in self.on else UNCHECKED
        return f"{name}, {state}, new" if name in self.new else f"{name}, {state}"

    def to_create(self) -> list[str]:
        """The new ones still checked: those to create on save."""
        return [n for n in self.new if n in self.on]

    def rows(self) -> list[str]:
        return [self.row(i) for i in range(len(self.names))]

    def toggle(self, i: int) -> str:
        """Check or uncheck row ``i``; what it is now, to say: "bug checked"."""
        name = self.names[i]
        if name in self.on:
            self.on.discard(name)
            return f"{name} {UNCHECKED}"
        self.on.add(name)
        return f"{name} {CHECKED}"

    def chosen(self) -> list[str]:
        """The checked ones, in list order."""
        return [n for n in self.names if n in self.on]

    @property
    def changed(self) -> bool:
        return self.on != self._start

    def added(self) -> list[str]:
        return [n for n in self.names if n in self.on and n not in self._start]

    def removed(self) -> list[str]:
        return [n for n in self.names if n in self._start and n not in self.on]

    def summary(self) -> str:
        """"2 checked: bug, docs", or "None checked"."""
        chosen = self.chosen()
        if not chosen:
            return "None checked"
        return f"{len(chosen)} checked: {', '.join(chosen)}"


def change_said(number: int, what: str, added: list[str], removed: list[str],
                now: list[str]) -> str:
    """What to say once a change has gone through, e.g. "#5: added bug,
    removed docs. Labels now: bug, ui." or "#5 has no assignees."."""
    parts = []
    if added:
        parts.append(f"added {', '.join(added)}")
    if removed:
        parts.append(f"removed {', '.join(removed)}")
    if not now:
        return f"#{number}: {', '.join(parts)}. No {what.lower()} now." if parts \
            else f"#{number} has no {what.lower()}."
    return f"#{number}: {', '.join(parts)}. {what} now: {', '.join(now)}."
