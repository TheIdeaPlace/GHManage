"""A repository's files as text to read: what the details panel shows in the
Files view (a file, a folder entry, a file's blame) and in File History (one
commit's changes to the file).

One line out per line in: line N of a file is line N of the panel, after a
first line that names it, so a screen reader's line navigation matches the
file. No wx here, so it can be tested without a window.
"""

from __future__ import annotations

import re

import diffview
from gh_data import MAX_FILE_BYTES, BlameRange, ChangedFile, Commit, RepoFile

MARKDOWN_SUFFIXES = (".md", ".markdown")
# An ATX heading: up to three spaces, one to six #, then a space or the end.
_HEADING = re.compile(r"^ {0,3}#{1,6}(?:\s|$)")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
# Read this much of a file to decide whether it is text.
_SNIFF = 8000


def _count(n: int, one: str, many: str) -> str:
    return f"{n:,} {one if n == 1 else many}"


def file_lines(text: str) -> list[str]:
    """A file's lines, as the panel shows them: split only at line breaks
    (not at the form feeds and separators ``str.splitlines`` also splits at,
    which would put the panel's lines out of step with the file's), without
    the empty "line" after a final newline."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def is_binary(text: str) -> bool:
    """Whether a file is not text: it has a NUL byte, or is mostly bytes
    that aren't UTF-8 (each became a replacement character)."""
    head = text[:_SNIFF]
    if "\x00" in head:
        return True
    return bool(head) and head.count("�") > len(head) // 10


def is_markdown(path: str) -> bool:
    return path.lower().endswith(MARKDOWN_SUFFIXES)


def markdown_headings(lines: list[str]) -> list[int]:
    """The index of each Markdown heading among ``lines``, leaving out
    lines starting with # inside a fenced code block (a shell comment)."""
    found: list[int] = []
    fence = ""
    for i, line in enumerate(lines):
        m = _FENCE.match(line)
        if m:
            mark = m.group(1)
            if not fence:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence):
                fence = ""
            continue
        if not fence and _HEADING.match(line):
            found.append(i)
    return found


def folder_label(repo: str, path: str) -> str:
    """``src/``, or for the top of the repository its name: ``GHManage/``."""
    if path:
        return f"{path}/"
    return f"{(repo or '').rsplit('/', 1)[-1]}/"


def folder_summary(files: list[RepoFile], truncated: bool = False) -> str:
    """``3 folders, 12 files.``"""
    if not files:
        return "Empty folder."
    counts: dict[str, int] = {}
    for f in files:
        counts[f.kind] = counts.get(f.kind, 0) + 1
    words = {"dir": ("folder", "folders"), "file": ("file", "files"),
             "link": ("link", "links"), "submodule": ("submodule", "submodules")}
    parts = [_count(counts[k], *words[k]) for k in words if counts.get(k)]
    said = ", ".join(parts) + "."
    if truncated:
        said += " GitHub cut this folder's list short."
    return said


def too_big(f: RepoFile) -> bool:
    return f.size > MAX_FILE_BYTES


def entry_text(f: RepoFile, target: str | None = None) -> str:
    """What the panel says for a row that isn't a file to read: a folder,
    a submodule, a link (with where it points, once known), or a file too
    large to show."""
    if f.kind == "dir":
        return f"{f.path}/: a folder."
    if f.kind == "submodule":
        return f"{f.path}: a submodule, another repository, at commit {f.sha[:7]}."
    if f.kind == "link":
        if target is None:
            return f"{f.path}: a link."
        return f"{f.path}: a link to {target.strip()}."
    return f"{f.path}: {f.size_human()}, too large to show here."


def file_text(f: RepoFile, text: str) -> tuple[str, list[int]]:
    """A file's text to read, and the panel line of each Markdown heading
    for Alt+N and Alt+P. The first line names the file and its length;
    line N of the file is line N of the panel."""
    if is_binary(text):
        return f"{f.path}: a binary file, {f.size_human()}.", []
    lines = file_lines(text)
    if not lines:
        return f"{f.path}: empty.", []
    head = f"{f.path}: {_count(len(lines), 'line', 'lines')}."
    starts = [i + 1 for i in markdown_headings(lines)] if is_markdown(f.path) else []
    return "\n".join([head] + lines), starts


def _merge(ranges: list[BlameRange]) -> list[BlameRange]:
    """Next-door runs from the same commit as one."""
    out: list[BlameRange] = []
    for r in ranges:
        if out and out[-1].sha == r.sha and out[-1].end + 1 >= r.start:
            last = out[-1]
            out[-1] = BlameRange(last.start, max(last.end, r.end), last.sha, last.short_sha,
                                 last.headline, last.author, last.date)
        else:
            out.append(r)
    return out


def blame_heading(r: BlameRange) -> str:
    """``Lines 10 to 14: alice, 2026-09-01, abc1234 Fix the parser``"""
    where = f"Line {r.start}" if r.start == r.end else f"Lines {r.start} to {r.end}"
    who = ", ".join(x for x in (r.author or "unknown", r.date[:10], r.short_sha) if x)
    return f"{where}: {who} {r.headline}".rstrip()


def blame_text(path: str, text: str, ranges: list[BlameRange]) -> tuple[str, list[int]]:
    """A file in runs of lines, each headed by who last changed it, when
    and in which commit; and the panel line of each heading."""
    lines = file_lines(text)
    runs = _merge([r for r in ranges if r.start >= 1 and r.end >= r.start])
    if not runs:
        return f"{path}: GitHub has no blame for this file.", []
    out = [f"{path}: who last changed each line, in {_count(len(runs), 'run', 'runs')}."]
    starts: list[int] = []
    for r in runs:
        starts.append(len(out))
        out.append(blame_heading(r))
        out += [lines[i - 1] if i - 1 < len(lines) else "" for i in range(r.start, r.end + 1)]
    return "\n".join(out), starts


def commit_heading(c: Commit) -> str:
    """``Commit abc12345, Kelly, 2026-09-01: Fix the parser``"""
    who = ", ".join(x for x in (c.short_sha, c.author, c.date[:10]) if x)
    return f"Commit {who}: {c.message}" if c.message else f"Commit {who}"


LOADING = "Getting the changes…"


def history_text(c: Commit, path: str, f: ChangedFile | None, style: str = diffview.DEFAULT,
                 loading: bool = False) -> tuple[str, list[int]]:
    """One commit of a file's history: which commit, then what it did to
    the file, marked as Changed Files marks it; and where each run of
    changes starts."""
    head = [commit_heading(c), ""]
    if loading:
        return "\n".join(head + [LOADING]), []
    if f is None:
        return "\n".join(head + [f"GitHub doesn't list {path} among this commit's files."]), []
    text, starts = diffview.file_text(f, style)
    return "\n".join(head) + "\n" + text, [s + len(head) for s in starts]
