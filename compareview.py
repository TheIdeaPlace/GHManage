"""What is said and shown about a comparison of two branches, tags or commits:
words only, so they can be tested without a window."""

from __future__ import annotations

import re

import diffview
from gh_data import COMPARE_MAX_FILES, CompareResult

FILES, AHEAD, BEHIND = "files", "ahead", "behind"
LIST_NAMES = {FILES: "Changed files", AHEAD: "Commits ahead", BEHIND: "Commits behind"}


def _commits(n: int) -> str:
    return f"{n:,} commit{'s' if n != 1 else ''}"


def name(r: CompareResult) -> str:
    """``feature compared with main``. An address that names only the head
    has no base until GitHub has been asked what the default branch is."""
    return f"{r.head or 'the default branch'} compared with {r.base or 'the default branch'}"


def _short(ref: str) -> str:
    """A ref to say on every row: a whole SHA cut down as a commit's row has it."""
    return ref[:8] if re.fullmatch(r"[0-9a-f]{12,40}", ref) else ref


def naming(r: CompareResult) -> str:
    """Which two these are, for a row in Full mode and the top of the details."""
    return f"Comparing: {_short(r.head)} with {_short(r.base)}"


def with_naming(text: str, r: CompareResult) -> str:
    """A row's ``text`` with the two on the end, as columns.row_text joins parts:
    nothing to join to an empty row, and only a space after a finished phrase."""
    words = naming(r)
    if not text.strip():
        return words
    return f"{text} {words}" if text.rstrip()[-1] in ".?!:;" else f"{text}; {words}"


def relation(r: CompareResult) -> str:
    """How the two stand, in a sentence."""
    if r.base == r.head:
        return f"{r.head} is being compared with itself, so there is nothing to show."
    if not r.ahead_by and not r.behind_by:
        return f"{r.head} and {r.base} are identical."
    if r.ahead_by and r.behind_by:
        return (f"{r.head} and {r.base} have diverged: {r.head} is {_commits(r.ahead_by)} "
                f"ahead and {r.behind_by:,} behind.")
    if r.ahead_by:
        return f"{r.head} is {_commits(r.ahead_by)} ahead of {r.base}."
    return f"{r.head} is {_commits(r.behind_by)} behind {r.base}."


def files_note(r: CompareResult) -> str:
    """The files' totals, and that GitHub stopped listing them if it did."""
    if not r.files:
        return ""
    note = diffview.totals_message(r.files)
    if len(r.files) >= COMPARE_MAX_FILES:
        note = (f"{note} GitHub lists only the first {COMPARE_MAX_FILES} files, "
                "so the totals are of those.")
    return note


def pull_note(r: CompareResult) -> str:
    if r.pull is None:
        return ""
    title = f": {r.pull.title}" if r.pull.title else ""
    return f"Pull request #{r.pull.number} is open{title}."


def summary(r: CompareResult) -> str:
    """The whole comparison, for when it arrives."""
    return " ".join(p for p in (relation(r), files_note(r), pull_note(r)) if p)


def lists_of(r: CompareResult) -> list[str]:
    """The lists this comparison has something in."""
    found = []
    if r.files:
        found.append(FILES)
    if r.commits:
        found.append(AHEAD)
    if r.behind_commits:
        found.append(BEHIND)
    return found


def first_list(r: CompareResult) -> str:
    """Where a comparison opens: what head changed, or if nothing, what it has
    or lacks. Identical, the empty list of files."""
    found = lists_of(r)
    return found[0] if found else FILES


def next_list(r: CompareResult, current: str) -> str:
    """The list after ``current``, round to the first. ``current`` if alone."""
    found = lists_of(r)
    if not found:
        return current
    if current not in found:
        return found[0]
    return found[(found.index(current) + 1) % len(found)]


def commits_of(r: CompareResult, which: str) -> list:
    return r.behind_commits if which == BEHIND else r.commits


def list_said(r: CompareResult, which: str) -> str:
    """A list's name and how many it holds, and if not all, how many of what."""
    if which == FILES:
        return f"{LIST_NAMES[FILES]}: {diffview.totals_message(r.files)}"
    commits = commits_of(r, which)
    total = r.behind_by if which == BEHIND else r.ahead_by
    if total > len(commits):
        return f"{LIST_NAMES[which]}: the newest {len(commits):,} of {total:,}."
    return f"{LIST_NAMES[which]}: {len(commits):,}."


def pull_prefill(r: CompareResult) -> tuple[str, str]:
    """A new pull request's title and description, as github.com offers them:
    one commit's message, or else the head branch's name in words."""
    if len(r.commits) == 1:
        subject, _, body = r.commits[0].message.partition("\n")
        return subject.strip(), body.strip()
    words = r.head.rsplit("/", 1)[-1].replace("-", " ").replace("_", " ").strip()
    return (words[:1].upper() + words[1:]) if words else r.head, ""
