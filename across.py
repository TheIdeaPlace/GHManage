"""Across Repositories (#130): one kind of thing (releases, runs, commits…)
from every repository you've chosen, in one list. No wx.

Each repository is read side by side, a few at a time. A repository that
can't be read is named with the reason, never quietly left out. Rows are
merged newest first, or grouped by repository, and ``]`` / ``[`` move
between repositories (``next_repo``).

Issues and pull requests come back as gh_data.Item with ``repo`` set, so
they behave as in My Work; everything else is wrapped in a Row that names
its repository.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Optional

import gh_data

# (kind, label, noun one, noun many), in the order Categories mode lists them
# and Ctrl+1 to Ctrl+8 pick them.
CATEGORIES = (
    ("issues", "Issues & PRs", "issue or pull request", "issues and pull requests"),
    ("releases", "Releases", "release", "releases"),
    ("runs", "Workflow Runs", "workflow run", "workflow runs"),
    ("commits", "Commits", "commit", "commits"),
    ("tags", "Tags", "tag", "tags"),
    ("milestones", "Milestones", "milestone", "milestones"),
    ("discussions", "Discussions", "discussion", "discussions"),
    ("alerts", "Security Alerts", "security alert", "security alerts"),
)
KINDS = tuple(c[0] for c in CATEGORIES)
LABELS = {c[0]: c[1] for c in CATEGORIES}
NOUNS = {c[0]: (c[2], c[3]) for c in CATEGORIES}

# Repositories read at once: enough to be quick, few enough not to trip
# GitHub's limit on requests at a time.
WORKERS = 6


@dataclass
class Row:
    """One item from one repository, for the kinds that don't name their
    repository themselves."""
    repo: str
    item: object
    when: str = ""        # ISO date the list is ordered by; "" for none

    @property
    def url(self) -> str:
        return getattr(self.item, "url", "") or ""

    def to_row(self, columns: list[str]) -> dict[str, str]:
        inner = self.item.to_row([c for c in columns if c != "repo"])
        return {c: (self.repo if c == "repo" else inner.get(c, "")) for c in columns}


@dataclass
class Result:
    kind: str
    rows: list = field(default_factory=list)       # Row, or Item for issues
    repos: list = field(default_factory=list)      # the repositories asked, in order
    failed: dict = field(default_factory=dict)     # repo -> why it couldn't be read
    notes: dict = field(default_factory=dict)      # repo -> why it has none (off, no rights)

    def empty_repos(self) -> list[str]:
        """Repositories that answered with nothing."""
        have = {repo_of(r) for r in self.rows}
        return [r for r in self.repos if r not in have and r not in self.failed]


def repo_of(row) -> str:
    return getattr(row, "repo", "") or ""


def when_of(row) -> str:
    if isinstance(row, Row):
        return row.when
    return getattr(row, "updated_at", "") or getattr(row, "created_at", "") or ""


def name_of(row) -> str:
    """What "by name" sorts on: a title, a tag, a message."""
    item = row.item if isinstance(row, Row) else row
    for attr in ("title", "name", "tag", "message", "summary"):
        value = getattr(item, attr, "")
        if value:
            return str(value).lower()
    return ""


def latest_release(releases: list) -> list:
    """The release GitHub calls Latest: the newest that is neither a draft
    nor a prerelease; failing that, the newest that isn't a draft."""
    for pick in (lambda r: not r.draft and not r.prerelease, lambda r: not r.draft):
        found = [r for r in releases if pick(r)]
        if found:
            return [max(found, key=lambda r: r.created_at or "")]
    return []


def why_failed(exc: Exception) -> str:
    """A short reason a repository couldn't be read, for the status bar."""
    text = str(exc).strip()
    low = text.lower()
    if "could not resolve to a repository" in low or "not found (http 404)" in low \
            or "http 404" in low:
        return "not found, or no access"
    if "http 403" in low:
        return "no access"
    if "http 502" in low or "http 504" in low or "timed out" in low:
        return "GitHub didn't answer in time"
    first = text.splitlines()[0] if text else type(exc).__name__
    for prefix in ("gh: ", "GraphQL: "):
        if first.startswith(prefix):
            first = first[len(prefix):]
    return first.rstrip(" .")


def _one(kind: str, repo: str, limit: int, state: str, latest_only: bool,
         item_filter) -> tuple[list, str]:
    """(rows, note) for one repository. A note says why there are none
    when that isn't simply "none" (discussions off, no rights)."""
    if kind == "issues":
        where = gh_data.resolve_issue_repo(repo) or repo
        items = (gh_data.fetch_issues(where, state, limit, item_filter=item_filter)
                 + gh_data.fetch_prs(where, state, limit, item_filter=item_filter))
        for it in items:
            it.repo = where
        return items, ""
    if kind == "releases":
        rel = gh_data.fetch_releases(repo, limit)
        if latest_only:
            rel = latest_release(rel)
        return [Row(repo, r, r.created_at or "") for r in rel], ""
    if kind == "runs":
        return [Row(repo, r, r.created_at or "") for r in gh_data.fetch_workflow_runs(repo, limit)], ""
    if kind == "commits":
        return [Row(repo, c, c.date or "") for c in gh_data.fetch_commits(repo, "", limit)], ""
    if kind == "tags":
        return [Row(repo, t, "") for t in gh_data.fetch_tags(repo, limit)], ""
    if kind == "milestones":
        ms = gh_data.fetch_milestones(repo, state, limit)
        return [Row(m.repo or repo, m, m.updated_at or m.created_at or "") for m in ms], ""
    if kind == "discussions":
        found = gh_data.fetch_discussions(repo, state, limit)
        if not found.enabled:
            return [], "Discussions are off"
        return [Row(repo, d, d.updated_at or d.created_at or "") for d in found.items], ""
    if kind == "alerts":
        report = gh_data.fetch_security_alerts(repo, state, limit)
        note = " ".join(report.notes()) if not report.alerts else ""
        return [Row(repo, a, a.created_at or "") for a in report.alerts], note
    raise ValueError(kind)


def fetch(kind: str, repos: list[str], limit: int = 30, state: str = "open",
          latest_only: bool = False, item_filter=None,
          progress: Optional[Callable[[int, int], None]] = None,
          workers: int = WORKERS) -> Result:
    """``kind`` from each of ``repos``, read side by side. ``progress(done,
    total)`` is called from worker threads as each repository answers."""
    result = Result(kind, repos=list(repos))
    found: dict[str, list] = {}
    done = 0

    def read(repo: str):
        try:
            return repo, _one(kind, repo, limit, state, latest_only, item_filter), None
        except Exception as exc:  # noqa: BLE001 - one repository mustn't sink the rest
            return repo, ([], ""), why_failed(exc)

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(repos) or 1))) as pool:
        futures = [pool.submit(read, repo) for repo in repos]
        for future in as_completed(futures):
            repo, (rows, note), error = future.result()
            done += 1
            if error:
                result.failed[repo] = error
            else:
                found[repo] = rows
                if note:
                    result.notes[repo] = note
            if progress:
                progress(done, len(repos))
    for repo in repos:  # the chosen order, so grouping follows it
        result.rows.extend(found.get(repo, []))
    return result


def order(rows: list, repos: list[str], newest: bool = True, by_name: bool = False,
          grouped: bool = False) -> list:
    """Rows newest first (or oldest, or by name), across repositories, or
    ``grouped`` by repository in ``repos`` order with that order inside each.
    Rows with no date (tags) keep the order their repository gave them."""
    position = {r.lower(): i for i, r in enumerate(repos)}

    def within(seq: list) -> list:
        if by_name:
            return sorted(seq, key=name_of)
        dated = [r for r in seq if when_of(r)]
        undated = [r for r in seq if not when_of(r)]
        dated = sorted(dated, key=when_of, reverse=newest)
        return dated + undated

    if not grouped:
        return within(rows)
    out = []
    for repo in sorted({repo_of(r) for r in rows},
                       key=lambda name: position.get(name.lower(), len(position))):
        out.extend(within([r for r in rows if repo_of(r) == repo]))
    return out


def next_repo(rows: list, index: int, step: int) -> int:
    """``]`` (step 1) and ``[`` (step -1): the next row from a different
    repository than row ``index``'s, going that way; for ``[``, the first
    row of that repository's run. -1 when there is none."""
    if not rows or not (0 <= index < len(rows)):
        return -1
    here = repo_of(rows[index])
    i = index + step
    while 0 <= i < len(rows) and repo_of(rows[i]) == here:
        i += step
    if not (0 <= i < len(rows)):
        return -1
    if step < 0:
        there = repo_of(rows[i])
        while i - 1 >= 0 and repo_of(rows[i - 1]) == there:
            i -= 1
    return i


def status(result: Result, shown: int) -> str:
    """The status bar after a load: what came back, and from where."""
    one, many = NOUNS[result.kind]
    n = len(result.repos)
    count = f"{shown:,} {one if shown == 1 else many}"
    text = f"{LABELS[result.kind]} from {n} {'repository' if n == 1 else 'repositories'}: {count}."
    empty = result.empty_repos()
    if empty and len(empty) < n:
        text += f" {len(empty)} {'has' if len(empty) == 1 else 'have'} none."
    if result.failed:
        why = "; ".join(f"{repo}: {reason}" for repo, reason in result.failed.items())
        text += f" Couldn't read {why}."
    return text
