"""A changed file as text to read: what the details panel shows for a row of
the Changed Files view, and what is said when the view loads.

The lines themselves are marked by app-kit's ``difftext``, which The Chat
Place uses too, so a change reads the same in both apps and the marking
styles are chosen from the same list. No wx here, so it can be tested
without a window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

from theideaplace_appkit import difftext

from gh_data import ChangedFile, ReviewComment

STYLES = difftext.STYLES
LABELS = difftext.LABELS
DEFAULT = difftext.DEFAULT
SYMBOLS_NOTE = difftext.SYMBOLS_NOTE
# The styles that mark lines with symbols, which a screen reader speaks only
# at a punctuation level that reads them.
SYMBOL_STYLES = (difftext.SYMBOLS, difftext.CHANGED)
NOTE_MARK = "\\"  # difftext's mark for "\ No newline at end of file"


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def file_summary(f: ChangedFile) -> str:
    """``path: modified, 3 lines added, 1 removed.`` A rename names where
    the file was."""
    what = f.status_display.lower()
    if f.previous_filename and f.previous_filename != f.filename:
        what = f"{what} from {f.previous_filename}"
    return (f"{f.filename}: {what}, "
            f"{_count(f.additions, 'line', 'lines')} added, {f.deletions} removed.")


def _no_lines(f: ChangedFile) -> str:
    """Why there are no lines to show."""
    if f.additions or f.deletions:
        return ("GitHub doesn't show the lines of a change this large. "
                "Ctrl+O opens the file on GitHub.")
    if f.previous_filename and f.previous_filename != f.filename:
        return "No lines changed, only the name."
    return "No lines to show: a binary file, or one with no text."


# Why a line of a file's text can't take a comment (M in Changed Files).
ON_SUMMARY = "That's the file's summary. Comments go on a line of the changes."
ON_WHERE = "That line says where a run of changes is. Comments go on a line of the changes."
ON_NOTE = "That's a note about the line above it. Comments go on a line of the changes."
ON_COMMENT = "That's a comment. Comments go on a line of the changes."
ON_OTHER = "Comments go on a line of the changes. Move to one first."
NO_LINES = "GitHub doesn't show this file's lines, so there is no line to comment on."

EARLIER_HEADING = "Earlier comments, on lines changed since:"
FILE_HEADING = "Comments on the whole file:"
NOT_SHOWN_HEADING = "Comments on lines not shown here:"

# Where a comment would go: ("RIGHT", 12) is line 12 of the file after the
# change (an added or unchanged line); ("LEFT", 12) line 12 before it (a
# removed one). A string is why that line can't take one.
Target = Union[Tuple[str, int], str]


@dataclass
class FileView:
    """A changed file as the details panel shows it."""
    text: str
    # Where Alt+N and Alt+P stop: (line from 0, how many lines, "change" or
    # "comment"), in order down the text.
    stops: List[Tuple[int, int, str]] = field(default_factory=list)
    # For each line of ``text``, where a comment on it would go, or why none can.
    targets: List[Target] = field(default_factory=list)

    def target(self, line: int) -> Target:
        if 0 <= line < len(self.targets):
            return self.targets[line]
        return ON_OTHER


def _order(lines: List[str], style: str) -> List[int]:
    """Which of a hunk's lines each line ``difftext.render_lines`` gives
    is, in order: the same order as theirs, so the CHANGED style's pairs
    (each removed line, then the line that replaced it) are followed."""
    marks = [difftext._mark(line) for line in lines]
    if style != difftext.CHANGED:
        return list(range(len(lines)))

    def run(i: int, mark: str) -> Tuple[List[List[int]], int]:
        groups: List[List[int]] = []
        while i < len(marks) and marks[i] == mark:
            group = [i]
            i += 1
            while i < len(marks) and marks[i] == NOTE_MARK:
                group.append(i)
                i += 1
            groups.append(group)
        return groups, i

    out: List[int] = []
    i = 0
    while i < len(marks):
        if marks[i] != "-":
            out.append(i)
            i += 1
            continue
        removed, i = run(i, "-")
        added, i = run(i, "+")
        pairs = min(len(removed), len(added))
        for old, new in zip(removed[:pairs], added[:pairs]):
            out += old + new
        for group in removed[pairs:] + added[pairs:]:
            out += group
    return out


def _numbers(hunk: difftext.Hunk) -> List[Tuple[str, Optional[int], Optional[int]]]:
    """Each of a hunk's lines' mark, and its line number in the old file and
    in the new one (None where it has none: an added line in the old file)."""
    old, new = hunk.old_start, hunk.new_start
    out: List[Tuple[str, Optional[int], Optional[int]]] = []
    for line in hunk.lines:
        mark = difftext._mark(line)
        if mark == "+":
            out.append((mark, None, new))
            new += 1
        elif mark == "-":
            out.append((mark, old, None))
            old += 1
        elif mark == " ":
            out.append((mark, old, new))
            old += 1
            new += 1
        else:
            out.append((mark, None, None))
    return out


def _comment_lines(c: ReviewComment, reply: bool, earlier: bool = False) -> List[str]:
    """``Comment by alice: …``, the rest of its text indented under it; a
    reply ``Reply by bob: …``, indented under the comment it answers."""
    indent = "  " if reply else ""
    where = ""
    if not reply:
        if earlier and c.line is None and c.original_line:
            where = f" on line {c.original_line} as it was"
        elif c.start_line and c.line and c.start_line != c.line:
            where = f" on lines {c.start_line} to {c.line}"
        elif earlier and c.line:
            where = f" on line {c.line}"  # a line not shown here
    body = c.body.replace("\r\n", "\n").rstrip().split("\n")
    who = "Reply by" if reply else "Comment by"
    out = [f"{indent}{who} {c.author}{where}: {body[0]}".rstrip()]
    out += [f"{indent}  {line}" if line.strip() else "" for line in body[1:]]
    return out


def file_view(f: ChangedFile, style: str = DEFAULT,
              comments: Optional[List[ReviewComment]] = None) -> FileView:
    """The file's summary and its changed lines in ``style``, each review
    comment straight after the line it is on with its replies, and those on
    lines changed since (or on the whole file) at the end."""
    lines = [file_summary(f)]
    targets: List[Target] = [ON_SUMMARY]
    stops: List[Tuple[int, int, str]] = []

    # Threads: each first comment, and the replies to it in order. A reply
    # to a comment that isn't here any more starts a thread of its own.
    comments = comments or []
    ids = {c.id for c in comments}
    roots = [c for c in comments if c.in_reply_to is None or c.in_reply_to not in ids]
    root_ids = {c.id for c in roots}
    parent = {c.id: c.in_reply_to for c in comments}

    def root_of(c: ReviewComment) -> int:
        # GitHub points a reply at its thread's first comment; follow a
        # reply to a reply up to it all the same.
        rid, seen = c.in_reply_to, {c.id}
        while rid not in root_ids and rid in parent and rid not in seen:
            seen.add(rid)
            rid = parent[rid]
        return rid

    replies: Dict[int, List[ReviewComment]] = {}
    for c in comments:
        if c.id not in root_ids:
            replies.setdefault(root_of(c), []).append(c)
    anchored: Dict[Tuple[str, int], List[ReviewComment]] = {}
    for c in roots:
        if c.line and not c.on_file:
            anchored.setdefault((c.side or "RIGHT", c.line), []).append(c)

    def add_thread(root: ReviewComment, earlier: bool = False) -> None:
        for n, c in enumerate([root] + replies.get(root.id, [])):
            text = _comment_lines(c, reply=n > 0, earlier=earlier)
            stops.append((len(lines), len(text), "comment"))
            lines.extend(text)
            targets.extend([ON_COMMENT] * len(text))

    hunks = difftext.parse_unified(f.patch) if f.patch else []
    if not hunks:
        lines += ["", _no_lines(f)]
        targets += [NO_LINES, NO_LINES]
    placed: set = set()
    for hunk in hunks:
        lines.append("")
        targets.append(ON_OTHER)
        stops.append((len(lines), 1, "change"))
        lines.append(difftext.where(hunk))
        targets.append(ON_WHERE)
        numbers = _numbers(hunk)
        rendered = difftext.render_lines(hunk.lines, style)
        for i, text in zip(_order(hunk.lines, style), rendered):
            mark, old, new = numbers[i]
            lines.append(text)
            keys: List[Tuple[str, int]] = []
            if mark == "+":
                targets.append(("RIGHT", new))
                keys = [("RIGHT", new)]
            elif mark == "-":
                targets.append(("LEFT", old))
                keys = [("LEFT", old)]
            elif mark == " ":
                # GitHub takes a comment on an unchanged line on the new side.
                targets.append(("RIGHT", new))
                keys = [("RIGHT", new), ("LEFT", old)]
            else:
                targets.append(ON_NOTE)
            for key in keys:
                for root in anchored.pop(key, []):
                    placed.add(root.id)
                    add_thread(root)

    unplaced = [c for c in roots if not c.on_file and c.id not in placed]
    for heading, group, earlier in (
            (FILE_HEADING, [c for c in roots if c.on_file], False),
            # Still on a line, but one not shown: the file's lines aren't
            # given, or the line is outside the runs of changes.
            (NOT_SHOWN_HEADING, [c for c in unplaced if c.line], True),
            (EARLIER_HEADING, [c for c in unplaced if not c.line], True)):
        if not group:
            continue
        lines += ["", heading]
        targets += [ON_OTHER, ON_OTHER]
        for root in group:
            add_thread(root, earlier=earlier)
    return FileView("\n".join(lines), stops, targets)


def file_text(f: ChangedFile, style: str = DEFAULT) -> tuple[str, list[int]]:
    """The file's summary and its changed lines in ``style``, and the line
    number (from 0) of each "Lines 10 to 15:" that starts a run of changes,
    for Alt+N and Alt+P to move between them."""
    view = file_view(f, style)
    return view.text, [line for line, _, kind in view.stops if kind == "change"]


def comment_count(n: int) -> str:
    """``1 comment``, ``3 comments``."""
    return _count(n, "comment", "comments")


def totals_message(files: list[ChangedFile]) -> str:
    """``3 files changed, 40 lines added, 12 removed.``"""
    if not files:
        return "No files changed."
    added = sum(f.additions for f in files)
    removed = sum(f.deletions for f in files)
    return (f"{_count(len(files), 'file', 'files')} changed, "
            f"{_count(added, 'line', 'lines')} added, {removed} removed.")


def is_symbol_style(style: str) -> bool:
    return style in SYMBOL_STYLES
