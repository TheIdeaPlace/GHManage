"""A changed file as text to read: what the details panel shows for a row of
the Changed Files view, and what is said when the view loads.

The lines themselves are marked by app-kit's ``difftext``, which The Chat
Place uses too, so a change reads the same in both apps and the marking
styles are chosen from the same list. No wx here, so it can be tested
without a window.
"""

from __future__ import annotations

from theideaplace_appkit import difftext

from gh_data import ChangedFile

STYLES = difftext.STYLES
LABELS = difftext.LABELS
DEFAULT = difftext.DEFAULT
SYMBOLS_NOTE = difftext.SYMBOLS_NOTE
# The styles that mark lines with symbols, which a screen reader speaks only
# at a punctuation level that reads them.
SYMBOL_STYLES = (difftext.SYMBOLS, difftext.CHANGED)


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


def file_text(f: ChangedFile, style: str = DEFAULT) -> tuple[str, list[int]]:
    """The file's summary and its changed lines in ``style``, and the line
    number (from 0) of each "Lines 10 to 15:" that starts a run of changes,
    for Alt+N and Alt+P to move between them."""
    lines = [file_summary(f)]
    hunks = difftext.parse_unified(f.patch) if f.patch else []
    if not hunks:
        lines += ["", _no_lines(f)]
        return "\n".join(lines), []
    starts: list[int] = []
    for hunk in hunks:
        lines.append("")
        starts.append(len(lines))
        lines += difftext.render([hunk], style)[1:]
    return "\n".join(lines), starts


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
