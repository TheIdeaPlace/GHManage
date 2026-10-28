"""A gist as text to read in the details panel (no wx).

The Gists view (#90) lists your gists; selecting one shows its fields and
then each of its files, headed by its name, a line of the file to a line of
the panel. Alt+N and Alt+P move between the file headings.
"""

from __future__ import annotations

import codeview
from gh_data import Gist, GistFile, _local_time

RULE = "─" * 60


def _size(n: int) -> str:
    if n < 1024:
        return f"{n:,} byte{'' if n == 1 else 's'}"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def file_heading(f: GistFile, number: int, total: int) -> str:
    """``File 2 of 3: notes.md — Markdown, 1.2 KB``"""
    about = ", ".join(x for x in (f.language, _size(f.size)) if x)
    return f"File {number} of {total}: {f.name} — {about}"


def file_body(f: GistFile) -> list[str]:
    """A file's lines, or why there are none to show."""
    if f.content is None:
        return ["Too large to show here. Ctrl+O opens the gist on GitHub."]
    if codeview.is_binary(f.content):
        return ["Not text. Ctrl+O opens the gist on GitHub."]
    lines = codeview.file_lines(f.content)
    if not lines:
        return ["(empty)"]
    if f.truncated:
        lines.append("")
        lines.append(f"GitHub sent only the start of {f.name}. "
                     "Ctrl+O opens the gist on GitHub, with all of it.")
    return lines


def gist_text(g: Gist) -> tuple[str, list[int]]:
    """The gist to read, and the panel line of each file's heading."""
    n = len(g.files)
    lines = [f"Gist: {g.title}"]
    if g.description.strip() and g.description.strip() != g.title:
        lines.extend(["Description:"] + g.description.strip().splitlines())
    lines.append(f"{g.visibility}, {n} file{'' if n == 1 else 's'}")
    lines.append(f"Updated: {_local_time(g.updated_at)}")
    lines.append(f"Created: {_local_time(g.created_at)}")
    lines.append(f"Comments: {g.comments}")
    lines.append("URL:")
    lines.append(g.url or "(none)")
    lines.append("")
    lines.append(RULE)
    positions: list[int] = []
    if not g.loaded:
        lines.append("")
        lines.append("Getting the files' text…")
        return "\n".join(lines), positions
    for i, f in enumerate(g.files, 1):
        lines.append("")
        positions.append(len(lines))
        lines.append(file_heading(f, i, n))
        lines.extend(file_body(f))
    if g.files_truncated:
        lines.append("")
        lines.append("GitHub listed only some of this gist's files. "
                     "Ctrl+O opens it on GitHub, with all of them.")
    return "\n".join(lines), positions


def status_message(gists: list[Gist], limit: int) -> str:
    n = len(gists)
    if not n:
        return "Gists — you have no gists."
    secret = sum(1 for g in gists if not g.public)
    more = " Ctrl++ loads more." if n >= limit else ""
    return (f"Gists — {n} gist{'' if n == 1 else 's'}, {secret} secret.{more}")
