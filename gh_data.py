"""Data layer for ghviewer — shells out to the `gh` CLI for all operations."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional


class GhError(RuntimeError):
    """Raised when a `gh` command fails."""


# Where to look for `gh` beyond $PATH, on Unix.
#
# A .app launched from Finder, the Dock or Spotlight inherits launchd's PATH —
# /usr/bin:/bin:/usr/sbin:/sbin — and never reads the user's shell profile. So
# every normal way of installing gh on a Mac lands somewhere invisible to the
# packaged app, and plain `gh` raises FileNotFoundError for every single
# operation even though `which gh` in Terminal answers immediately. That looks
# like "the app is broken", not like a PATH problem, so search these directly.
_EXTRA_GH_DIRS = (
    "/opt/homebrew/bin",   # Homebrew on Apple Silicon — the common case
    "/usr/local/bin",      # Homebrew on Intel, and manual installs
    "/opt/local/bin",      # MacPorts
    os.path.expanduser("~/.local/bin"),
)

_gh_exe: Optional[str] = None


def _find_gh() -> str:
    """Return the path to the `gh` executable, resolved once and cached.

    Falls back to the bare name so the FileNotFoundError below still produces
    the install message rather than something less useful.
    """
    global _gh_exe
    if _gh_exe is not None:
        return _gh_exe

    # Escape hatch for anyone with gh somewhere unusual.
    override = os.environ.get("GHMANAGE_GH_PATH")
    if override:
        _gh_exe = override
        return _gh_exe

    search = os.environ.get("PATH", "")
    if sys.platform != "win32":
        parts = search.split(os.pathsep)
        search = os.pathsep.join(
            [search, *(d for d in _EXTRA_GH_DIRS if d not in parts)]
        )

    _gh_exe = shutil.which("gh", path=search) or "gh"
    return _gh_exe


def _run_gh(args: list[str], stdin: Optional[str] = None) -> str:
    """Run a `gh` command and return stdout, raising GhError on failure.

    ``stdin`` is fed to the command, for the `--body-file -` style options.
    """
    # On Windows, suppress the console window that subprocess would otherwise pop up.
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            [_find_gh(), *args],
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            creationflags=creationflags,
        )
    except FileNotFoundError:
        raise GhError(
            "The `gh` CLI was not found. Install it from https://cli.github.com/ "
            "(on macOS: brew install gh), then run `gh auth login`. If it is "
            "installed somewhere unusual, set GHMANAGE_GH_PATH to its full path."
        )
    except subprocess.CalledProcessError as exc:
        raise GhError(exc.stderr.strip() or f"`gh {' '.join(args)}` failed")
    return result.stdout


# ── Data model ─────────────────────────────────────────────────────────


@dataclass
class Item:
    """A single issue or pull request with full metadata."""

    number: int
    title: str
    state: str
    url: str
    is_pr: bool
    author: str = ""
    created_at: str = ""
    updated_at: str = ""
    body: str = ""
    labels: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    comments: int = 0
    comment_list: list[dict] = field(default_factory=list)
    # PR-specific
    is_draft: bool = False
    is_merged: bool = False
    review_status: str = ""
    additions: int = 0
    deletions: int = 0
    changed_files: int = 0
    # False when GitHub couldn't give the size of the change in time (a
    # list of very large pull requests, see fetch_prs): Changes and Files
    # are then blank rather than "+0/-0".
    has_stats: bool = True
    base_branch: str = ""
    head_branch: str = ""
    # Set when the item came from a search across repositories, which list
    # many repos' issues together; empty in a repo's own issues list.
    repo: str = ""
    # My Work: why it is on the list ("review requested", "assigned", …).
    why: str = ""

    @property
    def kind(self) -> str:
        return "PR" if self.is_pr else "ISSUE"

    @property
    def state_display(self) -> str:
        if self.is_pr and self.is_merged:
            return "MERGED"
        return self.state.upper()

    def to_row(self, columns: list[str]) -> dict[str, str]:
        """Return a dict of column-name -> display value for the given columns."""
        mapping = {
            "number": str(self.number),
            "type": self.kind,
            "state": self.state_display,
            "title": self.title,
            "author": self.author,
            "created": self.created_at[:10] if self.created_at else "",
            "updated": self.updated_at[:10] if self.updated_at else "",
            "labels": ", ".join(self.labels),
            "assignees": ", ".join(self.assignees),
            "comments": str(self.comments),
            "draft": "Yes" if self.is_draft else "No",
            "review": self.review_status,
            "+/-": (f"+{self.additions}/-{self.deletions}"
                    if self.is_pr and self.has_stats else ""),
            "files": str(self.changed_files) if self.is_pr and self.has_stats else "",
            "base": self.base_branch if self.is_pr else "",
            "head": self.head_branch if self.is_pr else "",
            "repo": self.repo,
            "why": self.why,
        }
        return {col: mapping.get(col, "") for col in columns}


# ── Column definitions ─────────────────────────────────────────────────


ALL_COLUMNS = [
    "number", "type", "state", "title", "author", "created", "updated",
    "labels", "assignees", "comments", "draft", "review", "+/-", "files",
    "base", "head",
]

DEFAULT_COLUMNS = ["number", "type", "state", "title"]

SORT_ORDERS = [
    "Number (newest first)",
    "Number (oldest first)",
    "Title (A-Z)",
    "Title (Z-A)",
    "Created (newest first)",
    "Created (oldest first)",
    "Updated (newest first)",
    "Updated (oldest first)",
    "Comments (most first)",
]


def sort_items(items: list[Item], sort_order: str) -> list[Item]:
    """Sort items according to the named sort order."""
    if sort_order.startswith("Number (newest"):
        return sorted(items, key=lambda i: i.number, reverse=True)
    elif sort_order.startswith("Number (oldest"):
        return sorted(items, key=lambda i: i.number)
    elif sort_order.startswith("Title (A-Z"):
        return sorted(items, key=lambda i: i.title.lower())
    elif sort_order.startswith("Title (Z-A"):
        return sorted(items, key=lambda i: i.title.lower(), reverse=True)
    elif sort_order.startswith("Created (newest"):
        return sorted(items, key=lambda i: i.created_at, reverse=True)
    elif sort_order.startswith("Created (oldest"):
        return sorted(items, key=lambda i: i.created_at)
    elif sort_order.startswith("Updated (newest"):
        return sorted(items, key=lambda i: i.updated_at, reverse=True)
    elif sort_order.startswith("Updated (oldest"):
        return sorted(items, key=lambda i: i.updated_at)
    elif sort_order.startswith("Comments"):
        return sorted(items, key=lambda i: i.comments, reverse=True)
    return items


# ── Fetching ───────────────────────────────────────────────────────────


# JSON fields to request from gh for issues
ISSUE_FIELDS = "number,title,state,url,author,createdAt,updatedAt,body,labels,assignees,comments"
PR_FIELDS = "number,title,state,url,author,createdAt,updatedAt,body,labels,assignees,comments,isDraft,mergedAt,reviewDecision,additions,deletions,changedFiles,baseRefName,headRefName"
# The size of each change is what makes GitHub time out (HTTP 502) on a
# page of very large pull requests (nvaccess/nvda's translation merges);
# without it the same page comes back.
PR_STAT_FIELDS = ("additions", "deletions", "changedFiles")
PR_LIGHT_FIELDS = ",".join(f for f in PR_FIELDS.split(",") if f not in PR_STAT_FIELDS)


def _parse_author(row: dict) -> str:
    a = row.get("author")
    if isinstance(a, dict):
        return a.get("login", "unknown")
    return str(a) if a else "unknown"


def _parse_comments(row: dict) -> tuple[int, list[dict]]:
    """Parse the comments field — gh returns a list of comment objects.

    Returns (count, list_of_comment_dicts).
    """
    raw = row.get("comments", [])
    if isinstance(raw, list):
        comments = []
        for c in raw:
            if isinstance(c, dict):
                author = c.get("author", {})
                author_login = author.get("login", "unknown") if isinstance(author, dict) else str(author)
                comments.append({
                    "author": author_login,
                    "body": c.get("body", "") or "",
                    "created_at": c.get("createdAt", ""),
                })
        return len(comments), comments
    if isinstance(raw, int):
        return raw, []
    return 0, []


def _as_rows(data: object) -> list:
    """``gh issue/pr list`` return an array, ``gh issue/pr view`` one object."""
    if isinstance(data, dict):
        return [data]
    return data if isinstance(data, list) else []


def _parse_issues(raw: str) -> list[Item]:
    if not raw.strip():
        return []
    rows = _as_rows(json.loads(raw))
    items: list[Item] = []
    for row in rows:
        items.append(
            Item(
                number=row["number"],
                title=row.get("title", ""),
                state=row.get("state", "open"),
                url=row.get("url", ""),
                is_pr=False,
                author=_parse_author(row),
                created_at=row.get("createdAt", ""),
                updated_at=row.get("updatedAt", ""),
                body=row.get("body", "") or "",
                labels=[l["name"] if isinstance(l, dict) else str(l) for l in row.get("labels", [])],
                assignees=[a["login"] if isinstance(a, dict) else str(a) for a in row.get("assignees", [])],
                comments=_parse_comments(row)[0],
                comment_list=_parse_comments(row)[1],
            )
        )
    return items


def _parse_prs(raw: str) -> list[Item]:
    if not raw.strip():
        return []
    rows = _as_rows(json.loads(raw))
    items: list[Item] = []
    for row in rows:
        items.append(
            Item(
                number=row["number"],
                title=row.get("title", ""),
                state=row.get("state", "open"),
                url=row.get("url", ""),
                is_pr=True,
                author=_parse_author(row),
                created_at=row.get("createdAt", ""),
                updated_at=row.get("updatedAt", ""),
                body=row.get("body", "") or "",
                labels=[l["name"] if isinstance(l, dict) else str(l) for l in row.get("labels", [])],
                assignees=[a["login"] if isinstance(a, dict) else str(a) for a in row.get("assignees", [])],
                comments=_parse_comments(row)[0],
                comment_list=_parse_comments(row)[1],
                is_draft=row.get("isDraft", False),
                is_merged=bool(row.get("mergedAt")),
                review_status=row.get("reviewDecision", "") or "",
                additions=row.get("additions", 0),
                deletions=row.get("deletions", 0),
                changed_files=row.get("changedFiles", 0),
                has_stats="additions" in row,
                base_branch=row.get("baseRefName", ""),
                head_branch=row.get("headRefName", ""),
            )
        )
    return items


def fetch_issues(
    repo: Optional[str], state: str = "open", limit: int = 30, label: str = "",
    milestone: "Optional[Milestone]" = None,
) -> list[Item]:
    """Fetch issues (excluding PRs) for the repo.

    ``gh issue list`` defaults to only 30 items and returns newest first.
    Pass ``limit`` to control how many are fetched.

    ``milestone`` restricts it to that milestone's issues (Enter in Milestones).

    ``label`` restricts the list to issues carrying that label — this is what
    the Labels view drills into. Filtering server-side rather than in the app
    matters: an unfiltered page of 100 may not contain a single issue with the
    label you picked.

    If ``repo`` is a fork, issues are fetched from its upstream parent,
    since forks have issues disabled on GitHub.
    """
    effective = resolve_issue_repo(repo)
    args = ["issue", "list", "--state", state, "--limit", str(limit), "--json", ISSUE_FIELDS]
    if label:
        args += ["--label", label]
    if milestone is not None:
        # By number: gh takes a number or a title, and a title such as
        # "2" would be read as milestone number 2.
        args += ["--milestone", str(milestone.number)]
    if effective:
        args += ["--repo", effective]
    return _parse_issues(_run_gh(args))


def fetch_prs(
    repo: Optional[str], state: str = "open", limit: int = 30, label: str = "",
    milestone: "Optional[Milestone]" = None,
) -> list[Item]:
    """Fetch pull requests for the repo.

    ``gh pr list`` defaults to only 30 items and returns newest first.
    Pass ``limit`` to control how many are fetched. ``label`` restricts the
    list to PRs carrying that label.

    If ``repo`` is a fork, PRs are fetched from its upstream parent so that
    PRs opened against the upstream repo are visible. Fork-local PRs are not
    shown in this case.
    """
    effective = resolve_issue_repo(repo)
    args = ["pr", "list", "--state", state, "--limit", str(limit), "--json", PR_FIELDS]
    if label:
        args += ["--label", label]
    if milestone is not None:
        # gh pr list has no --milestone; a search qualifier does it. GitHub
        # search can't escape a quote, so one in the title is left out.
        args += ["--search", 'milestone:"%s"' % milestone.title.replace('"', "")]
    if effective:
        args += ["--repo", effective]
    try:
        return _parse_prs(_run_gh(args))
    except GhError as exc:
        if not _is_timeout(exc):
            raise
    # Again without each change's size, which is what GitHub couldn't
    # work out in time; the list is still worth having.
    args[args.index(PR_FIELDS)] = PR_LIGHT_FIELDS
    return _parse_prs(_run_gh(args))


def _is_timeout(exc: GhError) -> bool:
    """GitHub gave up on the query: HTTP 502 or 504 from its GraphQL API."""
    text = str(exc)
    return "HTTP 502" in text or "HTTP 504" in text


def _is_no_such_number(exc: GhError) -> bool:
    """True when gh says the number is not a PR (or not an issue or PR at all).

    gh passes GitHub's GraphQL error through: "Could not resolve to a
    PullRequest with the number of N" or "Could not resolve to an issue or
    pull request with the number of N". A missing *repository* also reads
    "Could not resolve to a Repository", and that one is a real failure.
    """
    msg = str(exc).lower()
    return ("could not resolve to a pullrequest" in msg
            or "could not resolve to an issue or pull request" in msg)


def fetch_item_by_number(number: int, repo: Optional[str]) -> Optional[Item]:
    """Fetch a single issue or PR by number, regardless of state.

    Tries ``gh pr view`` first, then ``gh issue view``. The order matters:
    ``gh issue view`` happily returns a PR number as if it were an issue,
    losing every PR field, whereas ``gh pr view`` with the PR fields fails on
    an issue number. Returns ``None`` if the number is neither. Any other
    failure — offline, signed out, rate limited — raises GhError rather than
    passing for "no such number", which would tell the user something false.
    """
    effective = resolve_issue_repo(repo)
    for sub, fields, parser in (
        ("pr", PR_FIELDS, _parse_prs),
        ("issue", ISSUE_FIELDS, _parse_issues),
    ):
        args = [sub, "view", str(number), "--json", fields]
        if effective:
            args += ["--repo", effective]
        try:
            raw = _run_gh(args)
        except GhError as exc:
            if _is_no_such_number(exc):
                continue
            raise
        if not raw.strip():
            continue
        items = parser(raw)
        if items:
            return items[0]
    return None


# ── Labels ─────────────────────────────────────────────────────────────
#
# Labels belong to whichever repo owns the issues, so every function here
# resolves through ``resolve_issue_repo``: on a fork you browse the upstream
# issues, and a label list from the fork itself would not match them.


@dataclass
class Label:
    """An issue/PR label."""
    name: str
    color: str = ""
    description: str = ""
    url: str = ""
    is_default: bool = False

    def to_row(self, columns: list[str]) -> dict[str, str]:
        mapping = {
            "label": self.name,
            "description": self.description,
            "color": f"#{self.color}" if self.color else "",
            "default": "Yes" if self.is_default else "No",
        }
        return {col: mapping.get(col, "") for col in columns}


LABEL_COLUMNS = ["label", "description", "color", "default"]
LABEL_DEFAULT_COLUMNS = ["label", "description", "color"]

LABEL_FIELDS = "name,color,description,url,isDefault"


def _parse_labels(raw: str) -> list[Label]:
    if not raw.strip():
        return []
    rows = json.loads(raw)
    if not isinstance(rows, list):
        return []
    return [
        Label(
            name=row.get("name", ""),
            color=(row.get("color") or "").lstrip("#"),
            description=row.get("description") or "",
            url=row.get("url", ""),
            is_default=bool(row.get("isDefault")),
        )
        for row in rows
    ]


def fetch_labels(repo: Optional[str], limit: int = 100) -> list[Label]:
    """Fetch the repo's labels, sorted by name.

    Name order is the useful one here — a label list is something you scan for
    a name, not a feed. (``gh`` sorts by creation date by default.)
    """
    effective = resolve_issue_repo(repo)
    args = ["label", "list", "--limit", str(limit), "--sort", "name",
            "--json", LABEL_FIELDS]
    if effective:
        args += ["--repo", effective]
    try:
        return _parse_labels(_run_gh(args))
    except GhError as exc:
        # A repo with no labels at all is not an error worth surfacing —
        # `gh` exits non-zero for it, so translate that into an empty list.
        if "no labels found" in str(exc).lower():
            return []
        raise


def create_label(
    repo: Optional[str], name: str, color: str = "", description: str = ""
) -> None:
    """Create a label. An empty ``color`` lets GitHub pick one."""
    effective = resolve_issue_repo(repo)
    args = ["label", "create", name]
    if color:
        args += ["--color", color.lstrip("#")]
    if description:
        args += ["--description", description]
    if effective:
        args += ["--repo", effective]
    _run_gh(args)


def delete_label(repo: Optional[str], name: str) -> None:
    """Delete a label. ``--yes`` because the caller has already confirmed.

    Deleting a label removes it from every issue and PR that carries it, and
    GitHub offers no undo — confirm in the UI before calling this.
    """
    effective = resolve_issue_repo(repo)
    args = ["label", "delete", name, "--yes"]
    if effective:
        args += ["--repo", effective]
    _run_gh(args)


# ── Actions ────────────────────────────────────────────────────────────


def close_item(item: Item, repo: Optional[str]) -> None:
    """Close the given issue or PR via `gh`."""
    effective = resolve_issue_repo(repo)
    sub = "pr" if item.is_pr else "issue"
    args = [sub, "close", str(item.number)]
    if effective:
        args += ["--repo", effective]
    _run_gh(args)


def reopen_item(item: Item, repo: Optional[str]) -> None:
    """Reopen the given issue or PR via `gh`."""
    effective = resolve_issue_repo(repo)
    sub = "pr" if item.is_pr else "issue"
    args = [sub, "reopen", str(item.number)]
    if effective:
        args += ["--repo", effective]
    _run_gh(args)


def add_comment(item: Item, comment: str, repo: Optional[str]) -> None:
    """Add a comment to an issue or PR."""
    effective = resolve_issue_repo(repo)
    sub = "pr" if item.is_pr else "issue"
    args = [sub, "comment", str(item.number), "--body", comment]
    if effective:
        args += ["--repo", effective]
    _run_gh(args)


class IssueCreatedUnreadable(GhError):
    """The issue was created, but gh's reply didn't say which number it got."""


def create_issue(
    repo: Optional[str], title: str, body: str, effective: Optional[str] = None,
) -> tuple[int, str]:
    """Open a new issue and return its number and address.

    Goes to the repo the issues list shows, so on a fork that is the
    upstream, the same as every other issue action here. A caller that has
    already worked that out — to tell the user where it is going — passes it
    as ``effective``, so the issue goes exactly where it said. The body goes
    in on stdin rather than the command line, where a long one could exceed
    the length Windows allows.
    """
    effective = effective or resolve_issue_repo(repo)
    args = ["issue", "create", "--title", title, "--body-file", "-"]
    if effective:
        args += ["--repo", effective]
    out = _run_gh(args, stdin=body)
    # gh prints the new issue's address as its last line.
    url = next((ln.strip() for ln in reversed(out.splitlines()) if ln.strip()), "")
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    if not tail.isdigit():
        raise IssueCreatedUnreadable(
            f"The issue was created, but gh didn't say where: {out.strip()!r}"
        )
    return int(tail), url


def open_in_browser(item: Item) -> None:
    """Open the item's GitHub URL in the default browser."""
    if item.url:
        webbrowser.open(item.url)


# ── Repo helpers ───────────────────────────────────────────────────────


def detect_repo() -> Optional[str]:
    """Try to detect the owner/name of the current git repo via `gh`."""
    try:
        out = _run_gh(["repo", "view", "--json", "nameWithOwner"])
    except GhError:
        return None
    try:
        return json.loads(out).get("nameWithOwner")
    except json.JSONDecodeError:
        return None


ORG_COLUMNS = ["organization", "role", "repositories"]
ORG_DEFAULT_COLUMNS = ["organization", "role", "repositories"]


@dataclass
class OrgEntry:
    """An organization you belong to, a row in My Organizations."""

    login: str
    admin: bool = False               # you can administer it
    repo_count: Optional[int] = None  # the repositories in it you can see

    @property
    def url(self) -> str:
        return f"https://github.com/{self.login}"

    @property
    def role(self) -> str:
        return "owner" if self.admin else "member"

    def to_row(self, columns: list[str]) -> dict[str, str]:
        count = "" if self.repo_count is None else f"{self.repo_count:,}"
        mapping = {"organization": self.login, "role": self.role, "repositories": count}
        return {col: mapping.get(col, "") for col in columns}


@dataclass
class RepoListing:
    """What the repository list is built from."""

    repos: list[dict]                 # your own, most recently pushed first
    orgs: list[OrgEntry] = field(default_factory=list)
    # How many repositories others have shared with you, outside your
    # organizations; None when there were too many to count in one page.
    shared: Optional[int] = 0


_ORGS_FIELD = (
    "organizations(first: 100) "
    "{ nodes { login viewerCanAdminister repositories { totalCount } } } "
)


def _parse_orgs(viewer: dict) -> list[OrgEntry]:
    """The organizations in a GraphQL viewer reply, the ones you run first."""
    orgs: list[OrgEntry] = []
    # An organization that blocks gh's access leaves a null in its place.
    for node in (viewer.get("organizations") or {}).get("nodes") or []:
        if not node or not node.get("login"):
            continue
        count = (node.get("repositories") or {}).get("totalCount")
        orgs.append(OrgEntry(node["login"], bool(node.get("viewerCanAdminister")),
                             count if isinstance(count, int) else None))
    orgs.sort(key=lambda o: (not o.admin, o.login.lower()))
    return orgs


def fetch_orgs() -> list[OrgEntry]:
    """The organizations you belong to, for My Organizations."""
    reply = _graphql("{ viewer { " + _ORGS_FIELD + "} }")
    viewer = (reply.get("data") or {}).get("viewer")
    if viewer is None:
        errors = reply.get("errors") or []
        first_error = errors[0] if errors and isinstance(errors[0], dict) else {}
        raise GhError(first_error.get("message") or reply.get("message")
                      or "Couldn't list your organizations")
    return _parse_orgs(viewer)


def list_repos(limit: int = 100) -> RepoListing:
    """Your own repositories, your organizations, and what is shared with you.

    One GraphQL query for all three, so the list waits no longer than it did
    for your repositories alone. Not `gh repo list`, which can't say which
    organizations you are in.

    An organization's repositories aren't mixed in with yours: someone in a
    big organization (which may have thousands) would find their own repos
    lost among them. They are under My Organizations instead, each with
    its count, and an organization's repositories are fetched when it is
    opened.

    Shared counts the repositories you are a collaborator on, less those in
    your organizations: you stay a collaborator on a repo you move into an
    organization, and it is already under that organization's entry.
    """
    first = max(1, min(limit, 100))
    own_part = (
        "own: repositories(first: %d, ownerAffiliations: [OWNER], "
        "orderBy: {field: PUSHED_AT, direction: DESC}) "
        "{ nodes { nameWithOwner description pushedAt isArchived } } " % first
    )
    extras = (
        "shared: repositories(first: 100, ownerAffiliations: [COLLABORATOR]) "
        "{ nodes { owner { login } } } " + _ORGS_FIELD
    )
    reply = _graphql("{ viewer { " + own_part + extras + "} }")
    viewer = (reply.get("data") or {}).get("viewer") or {}
    own = (viewer.get("own") or {}).get("nodes")
    if own is None:
        # A token without read:org (a GH_TOKEN with only `repo`, say) fails
        # the whole query over `organizations`, not just that part. Your own
        # repos don't need it, so ask again for them alone.
        reply = _graphql("{ viewer { " + own_part + "} }")
        viewer = (reply.get("data") or {}).get("viewer") or {}
        own = (viewer.get("own") or {}).get("nodes")
    if own is None:
        # A GraphQL error, or a plain REST one such as a 401 for a token
        # that has expired, which comes back with only a message.
        errors = reply.get("errors") or []
        first_error = errors[0] if errors and isinstance(errors[0], dict) else {}
        message = (first_error.get("message") or reply.get("message")
                   or "Couldn't list your repositories")
        if str(reply.get("status")) == "401":
            message += ". Run gh auth login to sign in again."
        raise GhError(message)
    repos = [r for r in own if r and r.get("nameWithOwner")]
    orgs = _parse_orgs(viewer)
    shared_nodes = (viewer.get("shared") or {}).get("nodes")
    if shared_nodes is None:
        shared = 0  # couldn't be had; the entry is left out rather than wrong
    else:
        mine = {o.login.lower() for o in orgs}
        shared = sum(1 for n in shared_nodes
                     if n and ((n.get("owner") or {}).get("login") or "").lower() not in mine)
        # A full page with some outside your organizations may have more
        # after it, so no count. A full page of only your organizations'
        # (someone added to a hundred of a big organization's) is taken to have none: an
        # entry that opens on nothing is worse than one left out.
        if shared and len(shared_nodes) >= 100:
            shared = None
    return RepoListing(repos, orgs, shared)


def _api_pages(endpoint: str, limit: int, keep=None, max_pages=None) -> list[dict]:
    """Fetch up to ``limit`` entries of a paged REST list, 100 to a page.

    ``gh api --paginate`` would fetch every page there is, and someone with
    thousands of stars does not want to wait for all of them to see the first
    hundred. So pages are requested one at a time and the loop stops at the
    limit, or at a short page, which means there are no more.

    ``keep``, when given, says which entries count towards the limit; the
    rest are dropped, and further pages fetched to make up for them, up to
    ``max_pages`` in all.
    """
    sep = "&" if "?" in endpoint else "?"
    per_page = max(1, min(limit, 100))
    out: list[dict] = []
    page = 1
    while len(out) < limit:
        raw = _run_gh(["api", f"{endpoint}{sep}per_page={per_page}&page={page}"])
        rows = json.loads(raw) if raw.strip() else []
        if not isinstance(rows, list):
            break
        out.extend(r for r in rows if isinstance(r, dict) and (keep is None or keep(r)))
        if len(rows) < per_page or (max_pages and page >= max_pages):
            break
        page += 1
    return out[:limit]


REPO_COLUMNS = ["repo", "description", "language", "stars", "pushed", "owner"]
REPO_DEFAULT_COLUMNS = ["repo", "description", "language", "stars", "pushed"]


@dataclass
class RepoEntry:
    """A repository in the Starred or Watched list."""

    name: str                # OWNER/NAME
    description: str = ""
    url: str = ""
    language: str = ""
    stars: int = 0
    forks: int = 0
    open_issues: int = 0
    pushed_at: str = ""
    archived: bool = False
    fork: bool = False
    private: bool = False

    @property
    def owner(self) -> str:
        return self.name.split("/", 1)[0]

    def to_row(self, columns: list[str]) -> dict[str, str]:
        flags = [f for f, on in (("archived", self.archived), ("fork", self.fork),
                                 ("private", self.private)) if on]
        mapping = {
            "repo": self.name,
            # Flags lead the description, where they are read before the
            # prose rather than lost after it.
            "description": "; ".join(flags + [self.description] if self.description else flags),
            "language": self.language,
            "stars": f"{self.stars:,}",
            "pushed": self.pushed_at[:10] if self.pushed_at else "",
            "owner": self.owner,
        }
        return {col: mapping.get(col, "") for col in columns}


def _repo_entry(raw: dict) -> RepoEntry:
    """A REST repository object as a RepoEntry."""
    name = raw.get("full_name", "") or ""
    return RepoEntry(
        name=name,
        description=raw.get("description") or "",
        url=raw.get("html_url") or (f"https://github.com/{name}" if name else ""),
        language=raw.get("language") or "",
        stars=raw.get("stargazers_count") or 0,
        forks=raw.get("forks_count") or 0,
        open_issues=raw.get("open_issues_count") or 0,
        pushed_at=raw.get("pushed_at") or "",
        archived=bool(raw.get("archived")),
        fork=bool(raw.get("fork")),
        private=bool(raw.get("private")),
    )


def _count_items(endpoint: str) -> int:
    """How many entries a paged REST list holds, without fetching them.

    Asks for one entry per page: the response's Link header then names the
    last page, and with one entry to a page that is the count. With no Link
    header there is only the one page, so the count is what came back.
    """
    sep = "&" if "?" in endpoint else "?"
    raw = _run_gh(["api", "-i", f"{endpoint}{sep}per_page=1"])
    head, blank, body = raw.replace("\r\n", "\n").partition("\n\n")
    if not blank:
        # No end to the headers means no body to count either; better no
        # number than a 0 that looks like an answer.
        raise GhError(f"Unexpected reply counting {endpoint}")
    for line in head.splitlines():
        if line.lower().startswith("link:"):
            last = _last_page(line.split(":", 1)[1])
            if last is None:
                raise GhError(f"Couldn't read the page count for {endpoint}")
            return last
    try:
        rows = json.loads(body) if body.strip() else []
    except ValueError:
        raise GhError(f"Unexpected reply counting {endpoint}")
    return len(rows) if isinstance(rows, list) else 0


def _last_page(link: str) -> Optional[int]:
    """The page number of the rel="last" link in a Link header, or None.

    Read from the URL's query by name, not by position, so it holds whatever
    order GitHub puts per_page and page in.
    """
    from urllib.parse import parse_qs, urlsplit
    for part in link.split(","):
        url, _, params = part.partition(";")
        if 'rel="last"' not in params:
            continue
        query = parse_qs(urlsplit(url.strip().strip("<>")).query)
        pages = query.get("page")
        if pages and pages[0].isdigit():
            return int(pages[0])
    return None


def count_starred_repos() -> int:
    """How many repositories the signed-in user has starred."""
    return _count_items("user/starred")


def count_watched_repos() -> int:
    """How many repositories the signed-in user watches."""
    return _count_items("user/subscriptions")


def fetch_starred_repos(limit: int = 100) -> list[RepoEntry]:
    """Repositories the signed-in user has starred, most recently starred first."""
    return [
        _repo_entry(r) for r in _api_pages("user/starred", limit)
        if r.get("full_name")
    ]


def fetch_watched_repos(limit: int = 100) -> list[RepoEntry]:
    """Repositories the signed-in user is watching (subscribed to).

    GitHub watches your own repositories for you, so they are here as well.
    """
    return [
        _repo_entry(r) for r in _api_pages("user/subscriptions", limit)
        if r.get("full_name")
    ]


def fetch_org_repos(org: str, limit: int = 100) -> list[RepoEntry]:
    """An organization's repositories you can see, most recently pushed first."""
    return [
        _repo_entry(r) for r in _api_pages(f"orgs/{org}/repos?sort=pushed", limit)
        if r.get("full_name")
    ]


def fetch_shared_repos(limit: int = 100, orgs=()) -> list[RepoEntry]:
    """Repositories others have made you a collaborator on, most recently
    pushed first, less those owned by ``orgs`` (which have entries of their own).
    """
    skip = {o.lower() for o in orgs}

    def keep(r: dict) -> bool:
        owner = ((r.get("owner") or {}).get("login") or "").lower()
        return bool(r.get("full_name")) and owner not in skip

    # Each page beyond the first is a round trip, and someone who is a
    # collaborator on a thousand of their organization's repos would wait
    # for all of them to find the few others shared. Ten pages more than
    # the list asks for is plenty.
    return [
        _repo_entry(r) for r in
        _api_pages("user/repos?affiliation=collaborator&sort=pushed", limit, keep,
                   max_pages=10 + limit // 100)
    ]


def parent_repo(repo: Optional[str]) -> Optional[str]:
    """Return the ``OWNER/NAME`` of ``repo``'s upstream parent, or None.

    Forks on GitHub have issues disabled by default; the issues live on the
    parent (upstream) repo. Callers that fetch issues/PRs should use this to
    resolve the effective repo before calling ``gh issue list`` / ``gh pr list``.
    """
    if not repo:
        return None
    try:
        out = _run_gh(["repo", "view", repo, "--json", "isFork,parent"])
    except GhError:
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None
    if not data.get("isFork"):
        return None
    parent = data.get("parent")
    if isinstance(parent, dict):
        owner = parent.get("owner", {})
        owner_login = owner.get("login") if isinstance(owner, dict) else None
        name = parent.get("name")
        if owner_login and name:
            return f"{owner_login}/{name}"
    return None


def resolve_issue_repo(repo: Optional[str]) -> Optional[str]:
    """Return the repo to query for issues/PRs.

    For a fork, this is the upstream parent (forks have issues disabled).
    For a non-fork or when the parent can't be determined, returns ``repo``
    unchanged.
    """
    parent = parent_repo(repo)
    return parent if parent else repo


# ── Git metadata: branches, commits, tags, releases, workflow runs ────
#
# These use `gh api` (GitHub REST API) because `gh` doesn't have first-class
# commands for browsing branches/commits/tags.  All functions accept an
# optional ``repo`` (``OWNER/NAME``); when None, the API uses the current
# git repo context.


def _api(args: list[str], repo: Optional[str]) -> str:
    """Run ``gh api`` with the given endpoint args.

    ``gh api`` doesn't support ``--repo``. Instead, we substitute the
    owner/repo into the endpoint path directly when ``repo`` is provided.
    When ``repo`` is None, ``gh api`` uses the current git repo context
    and expands ``{owner}/{repo}`` placeholders automatically.
    """
    full_args = ["api"]
    if repo:
        # Replace {owner}/{repo} in the endpoint with the actual repo path
        owner_name = repo.replace("/", "/")
        substituted = []
        for arg in args:
            substituted.append(arg.replace("{owner}/{repo}", owner_name))
        full_args += substituted
    else:
        full_args += args
    return _run_gh(full_args)


def _api_json(args: list[str], repo: Optional[str]) -> list | dict:
    """Run ``gh api`` and parse JSON (list or dict)."""
    raw = _api(args, repo)
    if not raw.strip():
        return []
    return json.loads(raw)


@dataclass
class Branch:
    """A git branch with its latest commit info."""
    name: str
    commit_sha: str
    commit_message: str
    commit_author: str
    commit_date: str
    protected: bool = False
    ahead: int = 0       # ahead of default branch (only set when comparing)
    behind: int = 0      # behind default branch
    url: str = ""

    def to_row(self, columns: list[str]) -> dict[str, str]:
        mapping = {
            "branch": self.name,
            "last commit": self.commit_message[:60],
            "author": self.commit_author,
            "date": self.commit_date[:10] if self.commit_date else "",
            "protected": "Yes" if self.protected else "No",
            "ahead": str(self.ahead) if self.ahead else "",
            "behind": str(self.behind) if self.behind else "",
        }
        return {col: mapping.get(col, "") for col in columns}


BRANCH_COLUMNS = ["branch", "last commit", "author", "date", "protected", "ahead", "behind"]
BRANCH_DEFAULT_COLUMNS = ["branch", "last commit", "author", "date"]


def fetch_branches(repo: Optional[str], limit: int = 100) -> list[Branch]:
    """Fetch branches for the repo via GitHub REST API."""
    rows = _api_json(
        ["repos/{owner}/{repo}/branches", "--paginate", "-q",
         f"[.[] | {{name, sha: .commit.sha, protected}}] | .[0:{limit}]"],
        repo,
    )
    if not isinstance(rows, list):
        return []
    # Fetch each branch tip's commit details concurrently. Doing this serially
    # is an N+1 that makes the Branches view slow on repos with many branches;
    # a small thread pool keeps it responsive without hammering the API.
    shas = [row.get("sha", "") for row in rows]
    infos: list[dict] = [{}] * len(rows)
    to_fetch = [(i, sha) for i, sha in enumerate(shas) if sha]
    if to_fetch:
        with ThreadPoolExecutor(max_workers=min(8, len(to_fetch))) as pool:
            futures = {pool.submit(_fetch_commit_info, repo, sha): i
                       for i, sha in to_fetch}
            for fut in as_completed(futures):
                infos[futures[fut]] = fut.result()
    branches: list[Branch] = []
    for row, sha, commit_info in zip(rows, shas, infos):
        branches.append(Branch(
            name=row.get("name", ""),
            commit_sha=sha[:8] if sha else "",
            commit_message=commit_info.get("message", ""),
            commit_author=commit_info.get("author", ""),
            commit_date=commit_info.get("date", ""),
            protected=row.get("protected", False),
            url=f"https://github.com/{repo}/tree/{row.get('name', '')}" if repo else "",
        ))
    return branches


def _fetch_commit_info(repo: Optional[str], sha: str) -> dict:
    """Fetch commit message, author, date for a single SHA."""
    try:
        row = _api_json(
            [f"repos/{{owner}}/{{repo}}/commits/{sha}",
             "-q", "{message: .commit.message, author: .commit.author.name, date: .commit.author.date}"],
            repo,
        )
        if isinstance(row, dict):
            return row
    except GhError:
        pass
    return {}


@dataclass
class Commit:
    """A git commit."""
    sha: str
    short_sha: str
    message: str
    author: str
    date: str
    url: str = ""
    additions: int = 0
    deletions: int = 0
    files_changed: int = 0
    files: list[dict] = field(default_factory=list)
    # The branches it was listed from, the default branch first; empty when
    # not known (a commit opened on its own).
    branches: list[str] = field(default_factory=list)

    def to_row(self, columns: list[str]) -> dict[str, str]:
        mapping = {
            "sha": self.short_sha,
            # First line only: a commit fetched on its own carries its whole
            # message, and a row should not read the body out.
            "message": (self.message.splitlines() or [""])[0][:80],
            "author": self.author,
            "date": self.date[:10] if self.date else "",
            "branch": branch_summary(self.branches),
            "files": str(self.files_changed) if self.files_changed else "",
            "+/-": f"+{self.additions}/-{self.deletions}" if self.additions or self.deletions else "",
        }
        return {col: mapping.get(col, "") for col in columns}


COMMIT_COLUMNS = ["sha", "message", "author", "date", "branch", "files", "+/-"]
COMMIT_DEFAULT_COLUMNS = ["sha", "message", "author", "date"]

# ``fetch_commits`` branch meaning every branch. Git allows no "*" in a
# branch name, so it can't be mistaken for one.
ALL_BRANCHES = "*"
_ALL_BRANCHES_MAX = 100       # branches read, the most recently committed to first
_BRANCH_LIST_PAGES_MAX = 10   # pages of 100 branch names read to find those
_BRANCHES_PER_QUERY = 20      # keeps each history query small enough for GitHub
ALL_BRANCHES_PER_BRANCH_MAX = 100  # one page of GraphQL history holds no more


def branch_summary(branches: list[str], shown: int = 3) -> str:
    """"main, dev, fix and 4 more" — a row's worth of a commit's branches."""
    if len(branches) <= shown + 1:
        return ", ".join(branches)
    return f"{', '.join(branches[:shown])} and {len(branches) - shown} more"


# repo -> its default branch, looked up once a session: it seldom changes,
# and the Commits view would otherwise ask again on every load.
_default_branches: dict[str, str] = {}


def fetch_default_branch(repo: Optional[str]) -> str:
    """The repo's default branch name, or "" if it can't be had."""
    if repo and repo in _default_branches:
        return _default_branches[repo]
    try:
        name = _api(["repos/{owner}/{repo}", "-q", ".default_branch"], repo).strip()
    except GhError:
        return ""
    if repo and name:
        _default_branches[repo] = name
    return name


def fetch_commits(repo: Optional[str], branch: str = "", limit: int = 100) -> list[Commit]:
    """Fetch commits for the repo (optionally for a specific branch).

    Not for ``ALL_BRANCHES``: that is ``fetch_all_branch_commits``.
    """
    if branch == ALL_BRANCHES:
        raise ValueError("use fetch_all_branch_commits for every branch")
    endpoint = "repos/{owner}/{repo}/commits"
    if branch:
        endpoint += f"?sha={branch}"
    endpoint += f"&per_page={limit}" if branch else f"?per_page={limit}"
    rows = _api_json([endpoint, "-q",
                      f"[.[] | {{sha, message: .commit.message, author: .commit.author.name, date: .commit.author.date, url: .html_url}}]"],
                     repo)
    if not isinstance(rows, list):
        return []
    # Without a branch GitHub lists the default branch; name it for the column.
    branch_name = branch or (fetch_default_branch(repo) if rows else "")
    commits: list[Commit] = []
    for row in rows:
        sha = row.get("sha", "")
        msg = row.get("message", "")
        first_line = msg.split("\n")[0] if msg else ""
        commits.append(Commit(
            sha=sha,
            short_sha=sha[:8] if sha else "",
            message=first_line,
            author=row.get("author", ""),
            date=row.get("date", ""),
            url=row.get("url", ""),
            branches=[branch_name] if branch_name else [],
        ))
    return commits


def _graphql_repository(reply: dict) -> dict:
    """The ``repository`` of a GraphQL reply, or GhError saying why not."""
    data = reply.get("data") if isinstance(reply.get("data"), dict) else {}
    node = data.get("repository")
    if isinstance(node, dict):
        return node
    errors = reply.get("errors") or []
    message = errors[0].get("message", "") if errors and isinstance(errors[0], dict) else ""
    raise GhError(message or "GitHub returned no repository")


def _utc_date(stamp: str) -> str:
    """An ISO 8601 time in UTC with a Z, as REST gives commit dates.

    GraphQL may carry the author's own offset, and dates in different
    offsets neither sort as strings nor show the same day the other views do.
    """
    from datetime import datetime, timezone
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return stamp
    if when.tzinfo is None:
        return stamp
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_all_branch_commits(repo: Optional[str], limit: int = 100) -> tuple[list[Commit], int]:
    """The newest commits across branches, each commit once, newest first.

    GitHub has no list of every commit in a repository, so this reads the
    newest commits (at most 100) of each of the 100 most recently
    committed-to branches (of the first 1,000 by name, on a repository with
    more), plus the default branch, merges them and keeps
    the newest ``limit``. A commit on several branches is one commit naming
    each of them — each it is among the newest commits of, which for an
    older commit need not be every branch that has it.

    Returns the commits and how many branches couldn't be read: the
    others are still worth showing, but the list is then incomplete.
    """
    repo = repo or detect_repo()
    if not repo or "/" not in repo:
        raise GhError("No repository to list commits for")
    owner, name = repo.split("/", 1)
    # json.dumps gives a valid GraphQL string literal, quotes escaped
    where = f"owner: {json.dumps(owner)}, name: {json.dumps(name)}"
    # GitHub can't list branches by their latest commit (TAG_COMMIT_DATE
    # leaves them in no useful order; the live checks showed it), so read
    # each one's latest commit date and sort here.
    tips: list[tuple[str, str]] = []
    default = ""
    after = ""
    for _ in range(_BRANCH_LIST_PAGES_MAX):
        try:
            node = _graphql_repository(_graphql(
                f"{{ repository({where}) {{ defaultBranchRef {{ name }} "
                f'refs(refPrefix: "refs/heads/", first: 100{after}) '
                "{ pageInfo { hasNextPage endCursor } "
                "nodes { name target { ... on Commit { committedDate } } } } } }"
            ))
        except GhError:
            if not tips:
                raise
            break  # a later page failed: go on with the branches already listed
        default = (node.get("defaultBranchRef") or {}).get("name") or default
        refs = node.get("refs") or {}
        for r in refs.get("nodes") or []:
            if isinstance(r, dict) and r.get("name"):
                tips.append((r["name"], (r.get("target") or {}).get("committedDate") or ""))
        page = refs.get("pageInfo") or {}
        if not page.get("hasNextPage") or not page.get("endCursor"):
            break
        after = f", after: {json.dumps(page['endCursor'])}"
    tips.sort(key=lambda t: _utc_date(t[1]), reverse=True)
    names = [n for n, _ in tips]
    # The default branch leads, even when it is too quiet to be among the
    # most recently committed to.
    if default:
        if default in names:
            names.remove(default)
        names = [default] + names[:_ALL_BRANCHES_MAX - 1]
    names = names[:_ALL_BRANCHES_MAX]
    if not names:
        return [], 0

    per_branch = max(1, min(limit, ALL_BRANCHES_PER_BRANCH_MAX))
    history = (f"target {{ ... on Commit {{ history(first: {per_branch}) "
               "{ nodes { oid message url authoredDate author { name } } } } }")
    chunks = [names[i:i + _BRANCHES_PER_QUERY]
              for i in range(0, len(names), _BRANCHES_PER_QUERY)]

    def fetch_chunk(chunk: list[str]) -> dict[str, list[dict]]:
        """Each branch read to its commits; a branch it couldn't read, left out."""
        refs = " ".join(
            f"b{i}: ref(qualifiedName: {json.dumps('refs/heads/' + b)}) {{ {history} }}"
            for i, b in enumerate(chunk)
        )
        found = _graphql_repository(_graphql(f"{{ repository({where}) {{ {refs} }} }}"))
        out: dict[str, list[dict]] = {}
        for i, b in enumerate(chunk):
            ref = found.get(f"b{i}")
            if not isinstance(ref, dict):
                continue  # gone since it was listed, or an error in its part
            nodes = ((ref.get("target") or {}).get("history") or {}).get("nodes") or []
            out[b] = [n for n in nodes if isinstance(n, dict) and n.get("oid")]
        return out

    per_name: dict[str, list[dict]] = {}
    failure: Optional[GhError] = None
    with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as pool:
        for future in as_completed([pool.submit(fetch_chunk, c) for c in chunks]):
            try:
                per_name.update(future.result())
            except GhError as exc:
                failure = exc  # the other branches are still worth showing
    if failure is not None and not per_name:
        raise failure

    # Walk the branches in order, so each commit's list starts with the
    # default branch and then the most recently committed to.
    by_sha: dict[str, Commit] = {}
    for b in names:
        for n in per_name.get(b, []):
            commit = by_sha.get(n["oid"])
            if commit is None:
                author = n.get("author") or {}
                commit = by_sha[n["oid"]] = Commit(
                    sha=n["oid"],
                    short_sha=n["oid"][:8],
                    message=n.get("message") or "",
                    author=author.get("name") or "",
                    date=_utc_date(n.get("authoredDate") or ""),
                    url=n.get("url") or "",
                )
            commit.branches.append(b)
    commits = sorted(by_sha.values(), key=lambda c: c.date, reverse=True)
    return commits[:limit], len(names) - len(per_name)


def fetch_commit_detail(repo: Optional[str], sha: str) -> Commit:
    """Fetch full commit detail including file changes."""
    row = _api_json(
        [f"repos/{{owner}}/{{repo}}/commits/{sha}",
         "-q", "{sha, message: .commit.message, author: .commit.author.name, date: .commit.author.date, url: .html_url, additions: .stats.additions, deletions: .stats.deletions, files: [.files[] | {filename, status, additions, deletions}]}"],
        repo,
    )
    if not isinstance(row, dict):
        return Commit(sha=sha, short_sha=sha[:8], message="", author="", date="")
    msg = row.get("message", "")
    return Commit(
        sha=row.get("sha", sha),
        short_sha=row.get("sha", sha)[:8],
        message=msg,
        author=row.get("author", ""),
        date=row.get("date", ""),
        url=row.get("url", ""),
        additions=row.get("additions", 0),
        deletions=row.get("deletions", 0),
        files_changed=len(row.get("files", [])),
        files=row.get("files", []),
    )


@dataclass
class Tag:
    """A git tag."""
    name: str
    commit_sha: str
    url: str = ""

    def to_row(self, columns: list[str]) -> dict[str, str]:
        mapping = {
            "tag": self.name,
            "commit": self.commit_sha,
        }
        return {col: mapping.get(col, "") for col in columns}


TAG_COLUMNS = ["tag", "commit"]
TAG_DEFAULT_COLUMNS = ["tag", "commit"]


def fetch_tags(repo: Optional[str], limit: int = 100) -> list[Tag]:
    """Fetch tags for the repo."""
    rows = _api_json(
        [f"repos/{{owner}}/{{repo}}/tags?per_page={limit}",
         "-q", "[.[] | {name, sha: .commit.sha}]"],
        repo,
    )
    if not isinstance(rows, list):
        return []
    tags: list[Tag] = []
    for row in rows:
        sha = row.get("sha", "")
        tags.append(Tag(
            name=row.get("name", ""),
            commit_sha=sha[:8] if sha else "",
            url=f"https://github.com/{repo}/releases/tag/{row.get('name', '')}" if repo else "",
        ))
    return tags


def _size_human(size_bytes: int) -> str:
    """Format a byte count as B/KB/MB/GB."""
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size_bytes} B"


@dataclass
class ReleaseAsset:
    """A file attached to a release, with its download count.

    ``download_count`` is a lifetime running total kept by GitHub — it is not
    broken down by date, and there is no API that does so. To see downloads
    over time you have to snapshot these numbers yourself and diff them.
    """
    id: int
    name: str
    size_bytes: int
    download_count: int
    updated_at: str
    url: str = ""          # browser_download_url
    release_tag: str = ""

    def size_human(self) -> str:
        return _size_human(self.size_bytes)

    def to_row(self, columns: list[str]) -> dict[str, str]:
        mapping = {
            "name": self.name,
            "downloads": str(self.download_count),
            "size": self.size_human(),
            "date": self.updated_at[:10] if self.updated_at else "",
            "#": str(self.id),
        }
        return {col: mapping.get(col, "") for col in columns}


ASSET_COLUMNS = ["name", "downloads", "size", "date", "#"]
ASSET_DEFAULT_COLUMNS = ["name", "downloads", "size", "date"]


@dataclass
class Release:
    """A GitHub release."""
    tag: str
    name: str
    draft: bool
    prerelease: bool
    created_at: str
    url: str = ""
    body: str = ""
    id: int = 0
    assets: list[ReleaseAsset] = field(default_factory=list)

    @property
    def downloads(self) -> int:
        """Total downloads across every asset attached to this release."""
        return sum(a.download_count for a in self.assets)

    def to_row(self, columns: list[str]) -> dict[str, str]:
        mapping = {
            "tag": self.tag,
            "name": self.name,
            "draft": "Yes" if self.draft else "No",
            "prerelease": "Yes" if self.prerelease else "No",
            "date": self.created_at[:10] if self.created_at else "",
            "downloads": str(self.downloads),
            "assets": str(len(self.assets)),
        }
        return {col: mapping.get(col, "") for col in columns}


RELEASE_COLUMNS = ["tag", "name", "date", "downloads", "assets", "draft", "prerelease"]
RELEASE_DEFAULT_COLUMNS = ["tag", "name", "date", "downloads"]


def _parse_assets(rows: object, release_tag: str = "") -> list[ReleaseAsset]:
    """Build ReleaseAsset objects from the API's asset array."""
    if not isinstance(rows, list):
        return []
    assets: list[ReleaseAsset] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        assets.append(ReleaseAsset(
            id=row.get("id", 0),
            name=row.get("name", ""),
            size_bytes=row.get("size", 0) or 0,
            download_count=row.get("downloads", 0) or 0,
            updated_at=row.get("updated", "") or "",
            url=row.get("url", "") or "",
            release_tag=release_tag,
        ))
    return assets


# Shape of a single asset, shared by the releases list and the per-release fetch.
_ASSET_FIELDS = (
    "{id, name, size, downloads: .download_count, "
    "updated: .updated_at, url: .browser_download_url}"
)


def fetch_releases(repo: Optional[str], limit: int = 30) -> list[Release]:
    """Fetch releases for the repo, including each one's assets.

    Assets come back inline on the releases endpoint, so the download counts
    cost no extra API call.
    """
    rows = _api_json(
        [f"repos/{{owner}}/{{repo}}/releases?per_page={limit}",
         "-q", "[.[] | {tag: .tag_name, name, draft, prerelease, created: .created_at, "
               f"url: .html_url, body: .body, id, assets: [.assets[] | {_ASSET_FIELDS}]}}]"],
        repo,
    )
    if not isinstance(rows, list):
        return []
    releases: list[Release] = []
    for row in rows:
        tag = row.get("tag", "")
        releases.append(Release(
            tag=tag,
            name=row.get("name", ""),
            draft=row.get("draft", False),
            prerelease=row.get("prerelease", False),
            created_at=row.get("created", ""),
            url=row.get("url", ""),
            body=row.get("body", "") or "",
            id=row.get("id", 0),
            assets=_parse_assets(row.get("assets"), tag),
        ))
    return releases


def fetch_release_assets(
    repo: Optional[str], release_id: int, release_tag: str = "", limit: int = 100
) -> list[ReleaseAsset]:
    """Fetch the assets of a single release, newest download counts included."""
    rows = _api_json(
        [f"repos/{{owner}}/{{repo}}/releases/{release_id}/assets?per_page={limit}",
         "-q", f"[.[] | {_ASSET_FIELDS}]"],
        repo,
    )
    # Most-downloaded first: the count is the reason for opening this view, so the
    # answer should be the row you land on rather than something to hunt for.
    return sorted(_parse_assets(rows, release_tag),
                  key=lambda a: a.download_count, reverse=True)


def total_downloads(releases: list[Release]) -> int:
    """Total downloads across every asset of every release given."""
    return sum(r.downloads for r in releases)


@dataclass
class WorkflowRun:
    """A GitHub Actions workflow run."""
    name: str
    status: str       # queued, in_progress, completed
    conclusion: str   # success, failure, cancelled, None (if still running)
    branch: str
    event: str        # push, pull_request, workflow_dispatch
    created_at: str
    url: str = ""
    run_number: int = 0
    run_id: int = 0     # database id, used for the artifacts API

    def to_row(self, columns: list[str]) -> dict[str, str]:
        mapping = {
            "name": self.name,
            "status": self.status,
            "result": self.conclusion or "(running)",
            "branch": self.branch,
            "event": self.event,
            "date": self.created_at[:10] if self.created_at else "",
            "#": str(self.run_number),
        }
        return {col: mapping.get(col, "") for col in columns}


WORKFLOW_COLUMNS = ["name", "status", "result", "branch", "event", "date", "#"]
WORKFLOW_DEFAULT_COLUMNS = ["name", "status", "result", "branch", "date"]


def fetch_workflow_runs(repo: Optional[str], limit: int = 30) -> list[WorkflowRun]:
    """Fetch recent workflow runs for the repo."""
    rows = _api_json(
        [f"repos/{{owner}}/{{repo}}/actions/runs?per_page={limit}",
         "-q", "[.workflow_runs[] | {name, status, conclusion, branch: .head_branch, event, created: .created_at, url: .html_url, number: .run_number, id}]"],
        repo,
    )
    if not isinstance(rows, list):
        return []
    runs: list[WorkflowRun] = []
    for row in rows:
        runs.append(WorkflowRun(
            name=row.get("name", ""),
            status=row.get("status", ""),
            conclusion=row.get("conclusion") or "",
            branch=row.get("branch", ""),
            event=row.get("event", ""),
            created_at=row.get("created", ""),
            url=row.get("url", ""),
            run_number=row.get("number", 0),
            run_id=row.get("id", 0),
        ))
    return runs


def fetch_workflow_run(repo: Optional[str], run_id: int) -> WorkflowRun:
    """One run as it stands now — its status changes as it runs and reruns."""
    row = _api_json([f"repos/{{owner}}/{{repo}}/actions/runs/{run_id}"], repo)
    if not isinstance(row, dict):
        raise GhError(f"Unexpected reply about run {run_id}")
    return WorkflowRun(
        name=row.get("name") or "", status=row.get("status") or "",
        conclusion=row.get("conclusion") or "", branch=row.get("head_branch") or "",
        event=row.get("event") or "", created_at=row.get("created_at") or "",
        url=row.get("html_url") or "", run_number=row.get("run_number") or 0,
        run_id=row.get("id") or run_id,
    )


@dataclass
class Artifact:
    """A build artifact attached to a workflow run."""
    id: int
    name: str
    size_bytes: int
    expired: bool
    created_at: str
    run_id: int = 0

    def size_human(self) -> str:
        return _size_human(self.size_bytes)

    def to_row(self, columns: list[str]) -> dict[str, str]:
        mapping = {
            "name": self.name,
            "size": self.size_human(),
            "expired": "Yes" if self.expired else "No",
            "date": self.created_at[:10] if self.created_at else "",
            "#": str(self.id),
        }
        return {col: mapping.get(col, "") for col in columns}


ARTIFACT_COLUMNS = ["name", "size", "expired", "date", "#"]
ARTIFACT_DEFAULT_COLUMNS = ["name", "size", "expired", "date"]


def fetch_run_artifacts(repo: Optional[str], run_id: int, limit: int = 100) -> list[Artifact]:
    """Fetch the artifacts produced by a single workflow run."""
    rows = _api_json(
        [f"repos/{{owner}}/{{repo}}/actions/runs/{run_id}/artifacts?per_page={limit}",
         "-q", "[.artifacts[] | {id, name, size: .size_in_bytes, expired, created: .created_at}]"],
        repo,
    )
    if not isinstance(rows, list):
        return []
    artifacts: list[Artifact] = []
    for row in rows:
        artifacts.append(Artifact(
            id=row.get("id", 0),
            name=row.get("name", ""),
            size_bytes=row.get("size", 0),
            expired=row.get("expired", False),
            created_at=row.get("created", ""),
            run_id=run_id,
        ))
    return artifacts


def download_artifact(repo: Optional[str], run_id: int, name: str, dest_dir: str) -> None:
    """Download a run's artifact by name, extracting its contents into ``dest_dir``.

    Uses ``gh run download`` which fetches the artifact zip and unpacks it.
    Raises GhError if the artifact is missing or expired.
    """
    args = ["run", "download", str(run_id), "-n", name, "-D", dest_dir]
    if repo:
        args += ["-R", repo]
    _run_gh(args)


def delete_workflow_run(repo: Optional[str], run_id: int) -> None:
    """Delete a workflow run by its database id.

    Uses ``gh run delete``. Raises GhError on failure.
    """
    args = ["run", "delete", str(run_id)]
    if repo:
        args += ["-R", repo]
    _run_gh(args)


@dataclass
class Workflow:
    """A GitHub Actions workflow definition (a .github/workflows/*.yml file)."""
    id: int
    name: str
    path: str
    state: str        # active, disabled_manually, disabled_inactivity
    url: str = ""     # html_url of the workflow

    def to_row(self, columns: list[str]) -> dict[str, str]:
        mapping = {
            "name": self.name,
            "state": self.state,
            "path": self.path,
            "#": str(self.id),
        }
        return {col: mapping.get(col, "") for col in columns}


WORKFLOW_DEF_COLUMNS = ["name", "state", "path", "#"]
WORKFLOW_DEF_DEFAULT_COLUMNS = ["name", "state", "path"]


def fetch_workflows(repo: Optional[str], limit: int = 100) -> list[Workflow]:
    """Fetch the workflow definitions (files) configured for the repo."""
    rows = _api_json(
        [f"repos/{{owner}}/{{repo}}/actions/workflows?per_page={limit}",
         "-q", "[.workflows[] | {id, name, path, state, url: .html_url}]"],
        repo,
    )
    if not isinstance(rows, list):
        return []
    workflows: list[Workflow] = []
    for row in rows:
        workflows.append(Workflow(
            id=row.get("id", 0),
            name=row.get("name", ""),
            path=row.get("path", ""),
            state=row.get("state", ""),
            url=row.get("url", ""),
        ))
    return workflows


@dataclass
class WorkflowInput:
    """One ``workflow_dispatch`` input declared by a workflow file.

    Mirrors what GitHub's own "Run workflow" form is built from. ``type`` is one
    of choice, boolean, string, number, environment; anything unrecognised (or
    omitted, which GitHub treats as string) is presented as a text field.
    """
    name: str
    type: str = "string"
    description: str = ""
    default: str = ""
    required: bool = False
    options: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        """Text to label the control with. The description when there is one —
        that is what GitHub shows — otherwise the raw input name."""
        return self.description.strip() or self.name


@dataclass
class DispatchSpec:
    """What a workflow file at a given ref says about running it manually."""
    supports_dispatch: bool
    inputs: list[WorkflowInput] = field(default_factory=list)


def _parse_dispatch_spec(raw: str) -> DispatchSpec:
    """Parse ``on.workflow_dispatch`` out of workflow YAML.

    Split out from the fetch so it can be tested without touching the network.

    Note the ``on:`` key: YAML 1.1 parses a bare ``on`` as the boolean True, so
    the block is looked up under both. PyYAML's safe_load follows YAML 1.1 here
    and every GitHub workflow in existence uses the bare form, so the True
    lookup is the one that actually fires.
    """
    import yaml  # deferred: only needed when a manual run is being set up

    try:
        doc = yaml.safe_load(raw)
    except yaml.YAMLError:
        # An unparseable workflow is GitHub's problem, not ours; fall back to
        # the old substring behaviour so a manual run without inputs still works.
        return DispatchSpec(supports_dispatch="workflow_dispatch" in raw)

    if not isinstance(doc, dict):
        return DispatchSpec(supports_dispatch=False)

    triggers = doc.get("on", doc.get(True))

    # `on: workflow_dispatch` (scalar) and `on: [push, workflow_dispatch]` (list)
    # are both valid and carry no inputs.
    if triggers == "workflow_dispatch":
        return DispatchSpec(supports_dispatch=True)
    if isinstance(triggers, list):
        return DispatchSpec(supports_dispatch="workflow_dispatch" in triggers)
    if not isinstance(triggers, dict) or "workflow_dispatch" not in triggers:
        return DispatchSpec(supports_dispatch=False)

    block = triggers["workflow_dispatch"]
    # `workflow_dispatch:` with nothing under it parses as None — supported,
    # no inputs.
    if not isinstance(block, dict):
        return DispatchSpec(supports_dispatch=True)

    declared = block.get("inputs")
    if not isinstance(declared, dict):
        return DispatchSpec(supports_dispatch=True)

    inputs: list[WorkflowInput] = []
    for name, spec in declared.items():
        if not isinstance(spec, dict):
            spec = {}
        default = spec.get("default", "")
        # Booleans and numbers arrive typed from YAML; the dispatch payload and
        # every control we build want text.
        if isinstance(default, bool):
            default = "true" if default else "false"
        elif default is None:
            default = ""
        options = spec.get("options")
        inputs.append(WorkflowInput(
            name=str(name),
            type=str(spec.get("type", "string")),
            description=str(spec.get("description", "")),
            default=str(default),
            required=bool(spec.get("required", False)),
            options=[str(o) for o in options] if isinstance(options, list) else [],
        ))
    return DispatchSpec(supports_dispatch=True, inputs=inputs)


def fetch_environments(repo: Optional[str]) -> list[str]:
    """Names of the repo's configured deployment environments.

    Used to fill the choices for an ``environment``-typed input, which the
    workflow file declares without options — the web form looks them up the
    same way. Returns [] when the repo has none or the endpoint is unavailable
    (it 404s on some plans), leaving the caller with a free-text field rather
    than a dead end.
    """
    try:
        rows = _api_json(
            ["repos/{owner}/{repo}/environments", "-q", "[.environments[].name]"],
            repo,
        )
    except GhError:
        return []
    return [str(r) for r in rows] if isinstance(rows, list) else []


def fetch_dispatch_spec(
    repo: Optional[str], path: str, ref: Optional[str] = None
) -> DispatchSpec:
    """Read a workflow file and report whether/how it can be run manually.

    There is no API that returns a workflow's inputs — GitHub's own web form is
    built by parsing the workflow file at the selected ref, and this does the
    same thing. ``ref`` matters: a branch that adds an input has different
    inputs from the default branch, and running with the wrong set silently
    drops values.
    """
    endpoint = f"repos/{{owner}}/{{repo}}/contents/{path}"
    if ref:
        endpoint += f"?ref={ref}"
    raw = _api(
        [endpoint, "-H", "Accept: application/vnd.github.raw"],
        repo,
    )
    spec = _parse_dispatch_spec(raw)

    # An `environment` input declares no options; its choices are the repo's
    # environments. Only pay for the extra call when one is actually declared.
    if any(i.type == "environment" and not i.options for i in spec.inputs):
        names = fetch_environments(repo)
        if names:
            for i in spec.inputs:
                if i.type == "environment" and not i.options:
                    i.options = list(names)
    return spec


def workflow_supports_dispatch(repo: Optional[str], path: str) -> bool:
    """Return True if the workflow file declares a ``workflow_dispatch`` trigger."""
    return fetch_dispatch_spec(repo, path).supports_dispatch


def dispatch_workflow(
    repo: Optional[str],
    workflow_id: int,
    ref: str,
    inputs: Optional[dict[str, str]] = None,
) -> None:
    """Trigger a manual (workflow_dispatch) run of a workflow on ``ref``.

    ``ref`` is a branch or tag name. ``inputs`` maps declared input names to
    string values; GitHub rejects names the workflow does not declare, so pass
    only what came from its own schema.

    Raises GhError if the workflow doesn't support manual dispatch or the ref
    is invalid.
    """
    args = ["-X", "POST",
            f"repos/{{owner}}/{{repo}}/actions/workflows/{workflow_id}/dispatches",
            "-f", f"ref={ref}"]
    # `gh api` builds nested JSON from key[subkey]=value, which is exactly the
    # {"ref": ..., "inputs": {...}} shape this endpoint wants.
    for key, value in (inputs or {}).items():
        args += ["-f", f"inputs[{key}]={value}"]
    _api(args, repo)


@dataclass
class CompareResult:
    """Result of comparing two refs (branches/tags/SHAs)."""
    base: str
    head: str
    ahead_by: int
    behind_by: int
    commits: list[dict] = field(default_factory=list)   # {sha, message}
    files: list[dict] = field(default_factory=list)      # {filename, status, additions, deletions}


def fetch_compare(repo: Optional[str], base: str, head: str) -> CompareResult:
    """Compare two refs (branches/tags/SHAs) via the GitHub compare API.

    Returns the ahead/behind counts plus the commits that are on ``head`` but
    not ``base`` and the files that differ. The commit and file lists are
    capped at 100 entries each to keep the request fast; ``ahead_by`` and
    ``behind_by`` always reflect the true totals.
    """
    # NOTE: the path must be repos/{owner}/{repo}/compare/... — the slash
    # before "compare" is required or the API 404s.
    row = _api_json(
        [f"repos/{{owner}}/{{repo}}/compare/{base}...{head}",
         "-q", "{ahead: .ahead_by, behind: .behind_by, commits: [.commits[] | {sha: .sha, message: .commit.message}][0:100], files: [(.files // [])[] | {filename, status, additions, deletions}][0:100]}"],
        repo,
    )
    if not isinstance(row, dict):
        return CompareResult(base=base, head=head, ahead_by=0, behind_by=0)
    return CompareResult(
        base=base,
        head=head,
        ahead_by=row.get("ahead", 0),
        behind_by=row.get("behind", 0),
        commits=row.get("commits", []),
        files=row.get("files", []),
    )


# ── Changed files ──────────────────────────────────────────────────────
#
# What a pull request or a commit changed, file by file, with each file's
# lines as GitHub gives them: a "patch", the unified diff text of that file
# without its ---/+++ header. GitHub leaves the patch out for a binary file
# and for one whose changes are too big to show; those still have a row.

CHANGED_FILE_COLUMNS = ["path", "status", "added", "removed", "comments"]
CHANGED_FILE_DEFAULT_COLUMNS = ["path", "status", "added", "removed", "comments"]

# GitHub's word for a file's status, and the one shown. "Deleted" rather
# than GitHub's "removed": "Removed" is what a removed line is marked with.
FILE_STATUSES = {
    "added": "Added",
    "removed": "Deleted",
    "modified": "Modified",
    "renamed": "Renamed",
    "copied": "Copied",
    "changed": "Changed",
    "unchanged": "Unchanged",
}

# GitHub lists at most this many files of a pull request or a commit.
MAX_CHANGED_FILES = 3000


@dataclass
class ChangedFile:
    """One file a pull request or commit changed."""
    filename: str
    status: str = "modified"       # GitHub's word: added, removed, modified, renamed…
    additions: int = 0
    deletions: int = 0
    patch: Optional[str] = None    # None when GitHub doesn't show the lines
    previous_filename: str = ""    # set for a rename
    url: str = ""                  # the file on GitHub, as it is after the change
    # A pull request's review comments on the file, oldest first; None for a
    # commit's file, or when the comments couldn't be read.
    comments: Optional[list["ReviewComment"]] = None

    @property
    def status_display(self) -> str:
        return FILE_STATUSES.get(self.status, self.status.capitalize())

    def to_row(self, columns: list[str]) -> dict[str, str]:
        mapping = {
            "path": self.filename,
            "status": self.status_display,
            "added": str(self.additions),
            "removed": str(self.deletions),
            "comments": "" if self.comments is None else str(len(self.comments)),
        }
        return {c: mapping.get(c, "") for c in columns}


def _changed_file(row: dict) -> ChangedFile:
    patch = row.get("patch")
    return ChangedFile(
        filename=row.get("filename") or "",
        status=row.get("status") or "modified",
        additions=row.get("additions") or 0,
        deletions=row.get("deletions") or 0,
        patch=patch if isinstance(patch, str) else None,
        previous_filename=row.get("previous_filename") or "",
        url=row.get("blob_url") or "",
    )


def fetch_pr_files(pr_url: str) -> list[ChangedFile]:
    """The files a pull request changes, with their lines."""
    repo, number = _pr_parts(pr_url)
    rows = _api_pages(f"repos/{repo}/pulls/{number}/files", MAX_CHANGED_FILES)
    return [_changed_file(r) for r in rows]


def fetch_commit_files(repo: Optional[str], sha: str) -> list[ChangedFile]:
    """The files a commit changes, with their lines.

    The commit endpoint is one object, not a list, so ``_api_pages`` can't
    page it; its files are paged with the same parameters all the same.
    """
    files: list[ChangedFile] = []
    per_page = 100
    for page in range(1, MAX_CHANGED_FILES // per_page + 1):
        rows = _api_json(
            [f"repos/{{owner}}/{{repo}}/commits/{sha}?per_page={per_page}&page={page}",
             "-q", ".files // []"],
            repo,
        )
        if not isinstance(rows, list):
            break
        files.extend(_changed_file(r) for r in rows if isinstance(r, dict))
        if len(rows) < per_page:
            break
    return files


def fetch_pr_diff(pr_url: str) -> str:
    """A pull request's whole diff, as ``gh pr diff`` prints it."""
    _pr_parts(pr_url)
    return _run_gh(["pr", "diff", pr_url, "--color=never"])


def fetch_commit_diff(repo: Optional[str], sha: str) -> str:
    """A commit's whole diff, as ``git show`` would print its changes."""
    return _api(["-H", "Accept: application/vnd.github.diff",
                 f"repos/{{owner}}/{{repo}}/commits/{sha}"], repo)


def file_diff(f: ChangedFile) -> str:
    """One file's changes as a diff with its header, ready for a diff
    viewer or an editor: what ``gh pr diff`` would print for that file.
    Empty when GitHub didn't give the lines."""
    old = f.previous_filename or f.filename
    lines = [f"diff --git a/{old} b/{f.filename}"]
    if old != f.filename:
        lines += [f"rename from {old}", f"rename to {f.filename}"]
    if not f.patch:
        # A rename that changed no lines is still a diff, as git shows it.
        return "\n".join(lines) + "\n" if old != f.filename else ""
    lines.append("--- /dev/null" if f.status == "added" else f"--- a/{old}")
    lines.append("+++ /dev/null" if f.status == "removed" else f"+++ b/{f.filename}")
    patch = f.patch.replace("\r\n", "\n")
    return "\n".join(lines) + "\n" + patch + ("" if patch.endswith("\n") else "\n")


def fetch_pr_head_sha(pr_url: str) -> str:
    """The commit a pull request's branch is at now."""
    _pr_parts(pr_url)
    return _run_gh(["pr", "view", pr_url, "--json", "headRefOid",
                    "-q", ".headRefOid"]).strip()


# ── Review comments ────────────────────────────────────────────────────
#
# The comments reviewers leave on a pull request's lines. ``line`` is where
# the comment is in the diff as it is now, on ``side`` RIGHT (the new file)
# or LEFT (the old); GitHub sets it to null once later commits have changed
# the line, and ``original_line`` still says where it was. A reply's
# ``in_reply_to_id`` is the first comment of its thread.

MAX_REVIEW_COMMENTS = 3000


@dataclass
class ReviewComment:
    id: int
    path: str
    body: str = ""
    author: str = ""
    line: Optional[int] = None        # None: outdated, or on the whole file
    side: str = "RIGHT"
    start_line: Optional[int] = None  # set when it is on several lines
    original_line: Optional[int] = None
    in_reply_to: Optional[int] = None
    on_file: bool = False             # on the file as a whole, not a line
    created_at: str = ""
    url: str = ""


def _review_comment(row: dict) -> ReviewComment:
    def num(key: str) -> Optional[int]:
        value = row.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    return ReviewComment(
        id=row.get("id") or 0,
        path=row.get("path") or "",
        body=row.get("body") or "",
        author=((row.get("user") or {}).get("login") or "ghost"),
        line=num("line"),
        side=row.get("side") or "RIGHT",
        start_line=num("start_line"),
        original_line=num("original_line"),
        in_reply_to=num("in_reply_to_id"),
        on_file=row.get("subject_type") == "file",
        created_at=row.get("created_at") or "",
        url=row.get("html_url") or "",
    )


def fetch_pr_review_comments(pr_url: str) -> list[ReviewComment]:
    """A pull request's review comments, on every file, oldest first."""
    repo, number = _pr_parts(pr_url)
    rows = _api_pages(f"repos/{repo}/pulls/{number}/comments", MAX_REVIEW_COMMENTS)
    return [_review_comment(r) for r in rows]


def comments_by_path(comments: list[ReviewComment]) -> dict[str, list[ReviewComment]]:
    out: dict[str, list[ReviewComment]] = {}
    for c in comments:
        out.setdefault(c.path, []).append(c)
    return out


def add_review_comment(pr_url: str, commit_id: str, path: str, line: int,
                       side: str, body: str) -> None:
    """Comment on one line of a pull request's file: ``side`` RIGHT for a
    line of the new file (added or unchanged), LEFT for a removed one. The
    body goes in on stdin, so nothing in it is read as an option."""
    if side not in ("RIGHT", "LEFT"):
        raise ValueError(side)
    repo, number = _pr_parts(pr_url)
    payload = {"body": body, "commit_id": commit_id, "path": path,
               "line": line, "side": side}
    _run_gh(["api", "-X", "POST", f"repos/{repo}/pulls/{number}/comments",
             "--input", "-"], stdin=json.dumps(payload))


# ── A repository's files ───────────────────────────────────────────────
#
# A folder is read with the git trees API (``{ref}:{path}``) rather than
# the contents API: a tree says which entries are links and submodules, which
# the contents API lists as files, and it has no 1,000-entry cap. A file's
# text is its blob, by SHA, so it never depends on the ref or the path being
# spelt right in an address, and the same file on two branches is read once.

REPO_FILE_COLUMNS = ["name", "type", "size", "path"]
REPO_FILE_DEFAULT_COLUMNS = ["name", "type", "size"]

FILE_KINDS = {"dir": "Folder", "file": "File", "link": "Link", "submodule": "Submodule"}
_TREE_KINDS = {"tree": "dir", "blob": "file", "commit": "submodule"}

# Files larger than this are not shown in the details panel.
MAX_FILE_BYTES = 1024 * 1024


def _quote(text: str, safe: str = "") -> str:
    from urllib.parse import quote
    return quote(text, safe=safe)


def github_file_url(repo: str, ref: str, path: str, folder: bool = False) -> str:
    """A file or folder on github.com at ``ref``."""
    kind = "tree" if folder else "blob"
    tail = f"/{_quote(path, '/')}" if path else ""
    return f"https://github.com/{repo}/{kind}/{_quote(ref, '/')}{tail}"


@dataclass
class RepoFile:
    """One entry of a folder in a repository."""
    path: str                  # from the top of the repository
    kind: str = "file"         # dir, file, link or submodule
    size: int = 0              # bytes; 0 for folders and submodules
    sha: str = ""              # the blob, tree or (for a submodule) commit
    url: str = ""              # on github.com

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]

    @property
    def kind_display(self) -> str:
        return FILE_KINDS.get(self.kind, self.kind.capitalize())

    @property
    def is_dir(self) -> bool:
        return self.kind == "dir"

    def size_human(self) -> str:
        return _size_human(self.size) if self.kind in ("file", "link") else ""

    def to_row(self, columns: list[str]) -> dict[str, str]:
        mapping = {
            "name": self.name,
            "type": self.kind_display,
            "size": self.size_human(),
            "path": self.path,
        }
        return {c: mapping.get(c, "") for c in columns}


def _sort_files(files: list[RepoFile]) -> list[RepoFile]:
    """Folders first, then the rest; each by name, ignoring case."""
    return sorted(files, key=lambda f: (not f.is_dir, f.name.lower(), f.name))


def fetch_repo_folder(repo: str, ref: str, path: str = "") -> tuple[list[RepoFile], bool]:
    """The entries of folder ``path`` ("" for the top) at ``ref``, folders
    first, and whether GitHub cut the list short."""
    reply = _api_json([f"repos/{repo}/git/trees/{_quote(f'{ref}:{path}')}"], None)
    if not isinstance(reply, dict):
        return [], False
    files: list[RepoFile] = []
    for row in reply.get("tree") or []:
        if not isinstance(row, dict) or not row.get("path"):
            continue
        kind = _TREE_KINDS.get(row.get("type", ""), "file")
        if kind == "file" and row.get("mode") == "120000":
            kind = "link"
        full = f"{path}/{row['path']}" if path else row["path"]
        # GitHub has no page for a submodule at its path; the folder it is
        # in shows it, linked to its own repository.
        url = (github_file_url(repo, ref, path, folder=True) if kind == "submodule"
               else github_file_url(repo, ref, full, folder=kind == "dir"))
        files.append(RepoFile(
            path=full, kind=kind, size=row.get("size") or 0, sha=row.get("sha") or "",
            url=url,
        ))
    return _sort_files(files), bool(reply.get("truncated"))


def fetch_blob_text(repo: str, sha: str) -> str:
    """A file's contents as text: UTF-8, with anything that isn't replaced.
    A link's contents are the path it points to."""
    text = _api(["-H", "Accept: application/vnd.github.raw", f"repos/{repo}/git/blobs/{sha}"],
                None)
    return text[1:] if text.startswith("﻿") else text


def fetch_readme_path(repo: str) -> str | None:
    """Where the repository's README is on its default branch (``README.md``,
    ``docs/README.rst``, ``.github/README.md``…), as GitHub picks it for the
    repository's page; None when it has none."""
    try:
        # Only the path: the reply also carries the whole file, base64.
        path = _api([f"repos/{repo}/readme", "-q", ".path"], None).strip()
    except GhError as exc:
        if _is_not_found(exc):
            return None
        raise
    return path or None


def fetch_file_history(repo: str, path: str, ref: str, limit: int = 100) -> list[Commit]:
    """The commits that changed ``path`` on ``ref``, newest first. GitHub
    doesn't follow a file back past a rename."""
    rows = _api_pages(f"repos/{repo}/commits?path={_quote(path, '/')}&sha={_quote(ref)}", limit)
    commits: list[Commit] = []
    for row in rows:
        sha = row.get("sha") or ""
        info = row.get("commit") if isinstance(row.get("commit"), dict) else {}
        author = info.get("author") if isinstance(info.get("author"), dict) else {}
        commits.append(Commit(
            sha=sha,
            short_sha=sha[:8],
            message=_first_line(info.get("message") or ""),
            author=author.get("name") or _login_of(row.get("author")),
            date=author.get("date") or "",
            url=row.get("html_url") or "",
        ))
    return commits


def fetch_commit_file(repo: str, sha: str, path: str) -> Optional[ChangedFile]:
    """What commit ``sha`` did to ``path``, or None if it isn't among the
    commit's files."""
    for f in fetch_commit_files(repo, sha):
        if f.filename == path:
            return f
    return None


@dataclass
class BlameRange:
    """A run of lines last changed by one commit."""
    start: int                 # first line, from 1
    end: int                   # last line, inclusive
    sha: str = ""
    short_sha: str = ""
    headline: str = ""
    author: str = ""
    date: str = ""             # ISO 8601


_BLAME_QUERY = """query {
  repository(owner: %s, name: %s) {
    object(expression: %s) {
      ... on Commit {
        blame(path: %s) {
          ranges {
            startingLine endingLine
            commit { oid abbreviatedOid messageHeadline
                     author { name date user { login } } }
          }
        }
      }
    }
  }
}"""


def fetch_blame(repo: str, ref: str, path: str) -> list[BlameRange]:
    """Who last changed each line of ``path`` at ``ref``, in runs of lines,
    first line first."""
    owner, _, name = repo.partition("/")
    query = _BLAME_QUERY % tuple(json.dumps(v) for v in (owner, name, ref, path))
    node = _graphql_repository(_graphql(query))
    obj = node.get("object")
    if not isinstance(obj, dict):
        raise GhError(f"{ref} isn't a branch, tag or commit in {repo}")
    blame = obj.get("blame")
    if not isinstance(blame, dict):
        raise GhError(f"GitHub has no blame for {path} at {ref}")
    ranges: list[BlameRange] = []
    for r in blame.get("ranges") or []:
        if not isinstance(r, dict):
            continue
        commit = r.get("commit") if isinstance(r.get("commit"), dict) else {}
        author = commit.get("author") if isinstance(commit.get("author"), dict) else {}
        user = author.get("user") if isinstance(author.get("user"), dict) else {}
        ranges.append(BlameRange(
            start=r.get("startingLine") or 0,
            end=r.get("endingLine") or 0,
            sha=commit.get("oid") or "",
            short_sha=commit.get("abbreviatedOid") or (commit.get("oid") or "")[:7],
            headline=commit.get("messageHeadline") or "",
            author=author.get("name") or user.get("login") or "",
            date=_utc_date(author.get("date") or ""),
        ))
    return sorted(ranges, key=lambda b: b.start)


def fetch_ref_names(repo: str, limit: int = 300) -> tuple[list[str], list[str]]:
    """The names of a repository's branches and of its tags, for choosing
    which to look at. Names only: a branch's latest commit isn't needed."""
    branches = [r.get("name", "") for r in _api_pages(f"repos/{repo}/branches", limit)]
    tags = [r.get("name", "") for r in _api_pages(f"repos/{repo}/tags", limit)]
    return [b for b in branches if b], [t for t in tags if t]


# ── GitHub Pages ───────────────────────────────────────────────────────
#
# Three things are wanted here and only the first has a straightforward
# endpoint: the site's configuration, its publish history, and the pages it
# actually serves.
#
# **Publish history depends on how the site is built.** A classic site
# (``build_type: legacy``) is built by GitHub and its history lives on
# ``pages/builds``. A site published by Actions (``build_type: workflow``)
# never appears there — that endpoint returns an empty list for it — and its
# history has to be read from the ``github-pages`` deployments instead.
# Legacy sites have deployments *as well*, so the two lists cannot simply be
# merged without showing every publish twice. ``fetch_pages_builds`` falls
# back rather than merging.
#
# **The list of served pages has no endpoint at all.** It is derived from the
# git tree of the branch Pages publishes from — see ``fetch_pages_files``.


def _is_not_found(exc: GhError) -> bool:
    """True when a `gh api` failure was a 404 rather than a real error.

    Used where "the thing isn't there" is a normal answer: a repo with Pages
    switched off 404s on every Pages endpoint, and that is information, not a
    failure to report to the user.
    """
    return "404" in str(exc)


@dataclass
class PagesSite:
    """The Pages configuration for a repo, from ``repos/{owner}/{repo}/pages``."""
    url: str                       # html_url — the live site root
    status: str = ""               # built / building / errored; null for Actions-built sites
    source_branch: str = ""
    source_path: str = "/"         # "/" or "/docs" — the published subtree
    build_type: str = "legacy"     # legacy (built by GitHub) | workflow (built by Actions)
    https_enforced: bool = False
    cname: str = ""                # custom domain, if one is set
    public: bool = True
    custom_404: bool = False

    @property
    def built_by_actions(self) -> bool:
        return self.build_type == "workflow"

    @property
    def status_display(self) -> str:
        # An Actions-built site reports no status of its own — its state is
        # whatever its last deployment did.
        if self.status:
            return self.status
        return "built by Actions" if self.built_by_actions else "unknown"


def fetch_pages_site(repo: Optional[str]) -> Optional[PagesSite]:
    """Fetch the repo's Pages configuration, or None if Pages is not enabled."""
    try:
        row = _api_json(["repos/{owner}/{repo}/pages"], repo)
    except GhError as exc:
        if _is_not_found(exc):
            return None
        raise
    if not isinstance(row, dict):
        return None
    source = row.get("source") or {}
    return PagesSite(
        url=row.get("html_url", "") or "",
        status=row.get("status") or "",
        source_branch=source.get("branch", "") or "",
        source_path=source.get("path", "/") or "/",
        build_type=row.get("build_type") or "legacy",
        https_enforced=bool(row.get("https_enforced")),
        cname=row.get("cname") or "",
        public=bool(row.get("public", True)),
        custom_404=bool(row.get("custom_404")),
    )


@dataclass
class PagesBuild:
    """One publish of the site.

    ``kind`` records which endpoint the row came from — ``build`` for a site
    GitHub builds itself, ``deployment`` for one published by Actions. The two
    carry different detail: builds report how long they took and why they
    failed, deployments report only a state.
    """
    id: int
    status: str
    commit: str
    pusher: str
    created_at: str
    duration_ms: int = 0
    error: str = ""
    kind: str = "build"            # build | deployment
    url: str = ""                  # the commit this publish came from

    @property
    def short_commit(self) -> str:
        return self.commit[:8]

    def duration_human(self) -> str:
        # Deployments carry no duration, so this is blank for them rather than "0s".
        if not self.duration_ms:
            return ""
        return f"{self.duration_ms / 1000:.0f}s"

    def to_row(self, columns: list[str]) -> dict[str, str]:
        mapping = {
            "status": self.status,
            "commit": self.short_commit,
            "pusher": self.pusher,
            # Sites often publish several times a day, so date alone would make
            # consecutive rows indistinguishable. Minute precision is enough.
            "date": self.created_at[:16].replace("T", " ") if self.created_at else "",
            "duration": self.duration_human(),
            "kind": self.kind,
            "error": self.error,
            "#": str(self.id),
        }
        return {col: mapping.get(col, "") for col in columns}


PAGES_COLUMNS = ["status", "commit", "pusher", "date", "duration", "kind", "error", "#"]
PAGES_DEFAULT_COLUMNS = ["status", "commit", "pusher", "date", "duration"]


def _build_id_from_url(url: str) -> int:
    """A build's id, which the payload carries only inside its API URL.

    ``pages/builds`` rows have no ``id`` field — unlike every other list
    endpoint used here — so it has to be read off the end of ``.url``.
    """
    tail = (url or "").rstrip("/").rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def _fetch_pages_builds_legacy(repo: Optional[str], limit: int) -> list[PagesBuild]:
    """Publish history from ``pages/builds`` — empty for Actions-built sites."""
    try:
        rows = _api_json(
            [f"repos/{{owner}}/{{repo}}/pages/builds?per_page={limit}",
             "-q", "[.[] | {url, status, commit, pusher: .pusher.login, "
                   "created: .created_at, duration, error: .error.message}]"],
            repo,
        )
    except GhError as exc:
        if _is_not_found(exc):
            return []
        raise
    if not isinstance(rows, list):
        return []
    return [
        PagesBuild(
            id=_build_id_from_url(row.get("url", "") or ""),
            status=row.get("status", "") or "",
            commit=row.get("commit", "") or "",
            pusher=row.get("pusher", "") or "",
            created_at=row.get("created", "") or "",
            duration_ms=row.get("duration", 0) or 0,
            error=row.get("error", "") or "",
            kind="build",
            url=f"https://github.com/{repo}/commit/{row.get('commit', '')}" if repo else "",
        )
        for row in rows
        if isinstance(row, dict)
    ]


def _deployment_state(repo: Optional[str], deployment_id: int) -> str:
    """Latest state of one deployment (success / failure / in_progress / …)."""
    try:
        rows = _api_json(
            [f"repos/{{owner}}/{{repo}}/deployments/{deployment_id}/statuses?per_page=1",
             "-q", "[.[] | .state]"],
            repo,
        )
    except GhError:
        return ""
    if isinstance(rows, list) and rows:
        return str(rows[0])
    return ""


def _fetch_pages_deployments(repo: Optional[str], limit: int) -> list[PagesBuild]:
    """Publish history for an Actions-built site, from its github-pages deployments.

    The deployments list carries no state — that lives on a separate endpoint,
    one call per deployment — so the states are fetched concurrently, the same
    way branch commit info is.
    """
    try:
        rows = _api_json(
            [f"repos/{{owner}}/{{repo}}/deployments?environment=github-pages&per_page={limit}",
             "-q", "[.[] | {id, sha, creator: .creator.login, created: .created_at}]"],
            repo,
        )
    except GhError as exc:
        if _is_not_found(exc):
            return []
        raise
    if not isinstance(rows, list):
        return []
    rows = [row for row in rows if isinstance(row, dict)]
    states = [""] * len(rows)
    if rows:
        with ThreadPoolExecutor(max_workers=min(8, len(rows))) as pool:
            futures = {
                pool.submit(_deployment_state, repo, row.get("id", 0) or 0): i
                for i, row in enumerate(rows)
            }
            for fut in as_completed(futures):
                states[futures[fut]] = fut.result()
    return [
        PagesBuild(
            id=row.get("id", 0) or 0,
            status=state or "unknown",
            commit=row.get("sha", "") or "",
            pusher=row.get("creator", "") or "",
            created_at=row.get("created", "") or "",
            kind="deployment",
            url=f"https://github.com/{repo}/commit/{row.get('sha', '')}" if repo else "",
        )
        for row, state in zip(rows, states)
    ]


def fetch_pages_builds(repo: Optional[str], limit: int = 30) -> list[PagesBuild]:
    """Publish history for the repo's Pages site, newest first.

    Falls back to the github-pages deployments when ``pages/builds`` is empty,
    which is how an Actions-built site always reports. The two are never
    merged — legacy sites have deployments as well, and merging would list
    every publish twice.
    """
    builds = _fetch_pages_builds_legacy(repo, limit)
    if builds:
        return builds
    return _fetch_pages_deployments(repo, limit)


@dataclass
class PagesFile:
    """A file the site serves, paired with the URL it is served from."""
    path: str                # path inside the published subtree, e.g. "guide/setup.md"
    url: str                 # the live URL that file is reachable at
    size_bytes: int = 0

    def size_human(self) -> str:
        return _size_human(self.size_bytes)

    def to_row(self, columns: list[str]) -> dict[str, str]:
        mapping = {
            "page": self.path,
            "url": self.url,
            "size": self.size_human(),
        }
        return {col: mapping.get(col, "") for col in columns}


PAGEFILE_COLUMNS = ["page", "url", "size"]
PAGEFILE_DEFAULT_COLUMNS = ["page", "url"]

# Files Jekyll reads rather than publishes. Only relevant when Jekyll is
# actually running — a .nojekyll marker turns it off, and everything is then
# served exactly as committed.
_JEKYLL_SOURCE_ONLY = ("_config.yml", "_config.yaml", "Gemfile", "Gemfile.lock")
_MARKDOWN_SUFFIXES = (".md", ".markdown")


def _jekyll_hides(rel_path: str) -> bool:
    """True if Jekyll consumes this file instead of publishing it."""
    segments = rel_path.split("/")
    if any(seg.startswith("_") for seg in segments):
        return True
    return segments[-1] in _JEKYLL_SOURCE_ONLY


def _served_as(rel_path: str, jekyll: bool) -> str:
    """The path a file is served at, which is not the path it is stored at.

    Jekyll renders Markdown to HTML, so ``guide/setup.md`` in the repo is
    ``guide/setup.html`` on the site. Without Jekyll the two are the same.
    """
    if not jekyll:
        return rel_path
    for suffix in _MARKDOWN_SUFFIXES:
        if rel_path.endswith(suffix):
            return rel_path[: -len(suffix)] + ".html"
    return rel_path


def fetch_pages_files(
    repo: Optional[str], site: Optional[PagesSite], limit: int = 1000
) -> list[PagesFile]:
    """List the files the site serves, each with the URL it is served from.

    There is no API for "what does this site publish", so this reads the git
    tree of the branch Pages builds from and maps each file onto its live URL.
    Three things make that more than string concatenation:

    * A source path other than ``/`` (typically ``/docs``) publishes only that
      subtree, and the prefix is stripped from the URL.
    * Without a ``.nojekyll`` marker a legacy site runs through Jekyll, which
      renders Markdown to HTML and keeps its own ``_``-prefixed directories out
      of the output. A custom Jekyll config can do more than that, and none of
      it is visible from the tree.
    * For an **Actions-built site the tree is the source, not the output.**
      The workflow decides what actually ships, so treat the list as the
      files that went in rather than the pages that came out.

    Callers that need those caveats stated to the user should read
    ``site.built_by_actions`` — this returns a best-effort list either way.
    """
    if site is None or not site.source_branch:
        return []
    row = _api_json(
        [f"repos/{{owner}}/{{repo}}/git/trees/{site.source_branch}?recursive=1",
         "-q", '[.tree[] | select(.type == "blob") | {path, size}]'],
        repo,
    )
    # A tree over ~100k entries comes back truncated. No Pages site is that
    # large in practice, and the API offers no continuation for it.
    entries = [e for e in row if isinstance(e, dict)] if isinstance(row, list) else []
    prefix = site.source_path.strip("/")
    root = site.url.rstrip("/") + "/"
    nojekyll = f"{prefix}/.nojekyll".lstrip("/")
    jekyll = not site.built_by_actions and not any(
        e.get("path") == nojekyll for e in entries
    )

    files: list[PagesFile] = []
    for entry in entries:
        path = entry.get("path", "") or ""
        if prefix:
            if not path.startswith(prefix + "/"):
                continue
            rel = path[len(prefix) + 1:]
        else:
            rel = path
        if not rel or (jekyll and _jekyll_hides(rel)):
            continue
        files.append(PagesFile(
            path=rel,
            url=root + _served_as(rel, jekyll),
            size_bytes=entry.get("size", 0) or 0,
        ))
    files.sort(key=lambda f: f.path.lower())
    return files[:limit]


# ── Activity feed ───────────────────────────────────────────────────────
#
# What github.com shows on your dashboard: events from the people you follow
# and the repositories you star or watch. It comes from
# /users/{login}/received_events, which the API caps at the most recent 300
# events from the last 90 days.

ACTIVITY_COLUMNS = ["actor", "action", "repo", "title", "date"]
ACTIVITY_DEFAULT_COLUMNS = ["actor", "action", "repo", "title", "date"]

# The API returns no more than this, however many pages are asked for.
ACTIVITY_MAX = 300

_login: Optional[str] = None


def current_login() -> str:
    """The signed-in user's GitHub login, looked up once and cached."""
    global _login
    if _login is None:
        login = _run_gh(["api", "user", "-q", ".login"]).strip()
        if not login:
            raise GhError("Couldn't tell who is signed in to gh. Run `gh auth login`.")
        _login = login
    return _login


def _local_time(iso: str) -> str:
    """``2026-10-05T14:32:00Z`` as ``2026-10-05 07:32`` in local time.

    The activity list is about what happened recently, so the time of day
    matters in a way it doesn't for a commit or a release date.
    """
    if not iso:
        return ""
    from datetime import datetime
    try:
        stamp = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso[:16].replace("T", " ")
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone()
    return stamp.strftime("%Y-%m-%d %H:%M")


# Events whose object is the repository itself: "bob starred o/r", not
# "bob starred in o/r".
_REPO_OBJECT_EVENTS = ("WatchEvent", "ForkEvent", "SponsorshipEvent")


@dataclass
class ActivityEvent:
    """One entry in the activity feed: someone did something in a repo."""

    event_type: str          # GitHub's type, e.g. "IssuesEvent"
    actor: str
    repo: str                # OWNER/NAME the event happened in
    action: str              # what was done, in words: "opened issue #12"
    created_at: str = ""
    title: str = ""          # the issue, PR or release it was about, if any
    url: str = ""            # where to read this event on github.com
    body: str = ""           # comment, review or description text, if any
    event_id: str = ""       # GitHub's id for the event, unique in the feed
    verb: str = ""           # the payload's action: "opened", "closed", ...
    # What the event is about, when that is an issue, pull request, release
    # or discussion: its kind, number and own address (not a comment anchor).
    # This is what F favorites. Empty for events about a branch, a push or
    # the repository as a whole, which have nothing of their own to keep.
    subject_kind: str = ""   # "issue", "PR", "release", "discussion"
    number: int = 0
    subject_url: str = ""

    @property
    def pr_number(self) -> int:
        """The pull request this event was about, or 0."""
        return self.number if self.subject_kind == "PR" else 0

    @property
    def summary(self) -> str:
        """The whole event as one sentence: who, what, where."""
        if self.event_type == "PublicEvent":
            return f"{self.actor} made {self.repo} public"
        if self.event_type in _REPO_OBJECT_EVENTS:
            text = f"{self.actor} {self.action} {self.repo}"
            return f"{text} {self.title}" if self.title else text
        text = f"{self.actor} {self.action}"
        if self.repo:
            text += f" in {self.repo}"
        if self.title:
            text += f": {self.title}"
        return text

    def to_row(self, columns: list[str]) -> dict[str, str]:
        mapping = {
            "actor": self.actor,
            "action": self.action,
            "repo": self.repo,
            "title": self.title,
            "date": _local_time(self.created_at),
        }
        return {col: mapping.get(col, "") for col in columns}


def _ref_name(ref: str) -> str:
    """``refs/heads/main`` -> ``main``."""
    for prefix in ("refs/heads/", "refs/tags/"):
        if ref.startswith(prefix):
            return ref[len(prefix):]
    return ref


def _first_line(text: str) -> str:
    lines = (text or "").splitlines()
    return lines[0] if lines else ""


def _login_of(obj) -> str:
    return (obj or {}).get("login", "") or "" if isinstance(obj, dict) else ""


def _issue_action(verb: str, noun: str, number, payload: dict) -> str:
    """Words for an issue or PR event, naming who or what a verb applies to.

    "labeled pull request #3" three times over says nothing about which label,
    so the label, assignee or requested reviewer goes in the sentence.
    """
    ref = f"{noun} #{number}" if number else noun
    if verb in ("labeled", "unlabeled"):
        label = ((payload.get("label") or {}).get("name") or "") if isinstance(
            payload.get("label"), dict) else ""
        return f'{verb} {ref} "{label}"' if label else f"{verb} {ref}"
    if verb == "assigned":
        who = _login_of(payload.get("assignee"))
        return f"assigned {who} to {ref}" if who else f"assigned {ref}"
    if verb == "unassigned":
        who = _login_of(payload.get("assignee"))
        return f"unassigned {who} from {ref}" if who else f"unassigned {ref}"
    if verb == "review_requested":
        who = _login_of(payload.get("requested_reviewer"))
        return f"requested a review from {who} on {ref}" if who else f"requested a review on {ref}"
    return f"{verb} {ref}"


def parse_event(raw: dict) -> ActivityEvent:
    """Turn one REST event into words.

    Payloads vary by type, and GitHub has been trimming them (push events no
    longer always carry their commits, pull requests arrive without a title),
    so every field is read as optional and an unknown type still produces a
    readable row.
    """
    etype = raw.get("type", "") or ""
    actor_obj = raw.get("actor") or {}
    actor = actor_obj.get("display_login") or actor_obj.get("login", "") or ""
    repo = (raw.get("repo") or {}).get("name", "") or ""
    payload = raw.get("payload") or {}
    repo_url = f"https://github.com/{repo}" if repo else ""
    title = ""
    url = repo_url
    body = ""
    verb = payload.get("action", "") or ""
    subject_kind = ""
    number = 0
    subject_url = ""

    if etype == "WatchEvent":
        # Despite the name, a WatchEvent is a star.
        action = "starred"
    elif etype == "ForkEvent":
        forkee = payload.get("forkee") or {}
        action = "forked"
        if forkee.get("full_name"):
            title = f"to {forkee['full_name']}"
        url = forkee.get("html_url") or url
    elif etype == "CreateEvent":
        kind = payload.get("ref_type", "") or ""
        ref = payload.get("ref") or ""
        if kind == "repository":
            action = "created repository"
            body = payload.get("description") or ""
        else:
            action = f"created {kind} {ref}".strip()
            if kind == "branch" and ref:
                url = f"{repo_url}/tree/{ref}"
            elif kind == "tag" and ref:
                url = f"{repo_url}/releases/tag/{ref}"
    elif etype == "DeleteEvent":
        action = f"deleted {payload.get('ref_type', '') or ''} {payload.get('ref', '') or ''}".strip()
    elif etype == "PushEvent":
        branch = _ref_name(payload.get("ref", "") or "")
        commits = [c for c in (payload.get("commits") or []) if isinstance(c, dict)]
        size = payload.get("distinct_size") or payload.get("size") or len(commits)
        where = f" to {branch}" if branch else ""
        if size:
            action = f"pushed {size} commit{'s' if size != 1 else ''}{where}"
        else:
            action = f"pushed{where}"
        if commits:
            title = _first_line(commits[-1].get("message", ""))
            body = "\n".join(
                f"{(c.get('sha') or '')[:7]} {_first_line(c.get('message', ''))}".strip()
                for c in commits
            )
        before = payload.get("before") or ""
        head = payload.get("head") or ""
        if before and head and before.strip("0"):
            url = f"{repo_url}/compare/{before[:12]}...{head[:12]}"
        elif branch:
            url = f"{repo_url}/commits/{branch}"
    elif etype in ("IssuesEvent", "PullRequestEvent"):
        is_pr = etype == "PullRequestEvent"
        obj = payload.get("pull_request" if is_pr else "issue") or {}
        n = payload.get("number") or obj.get("number")
        verb = verb or "updated"
        if is_pr and verb == "closed" and obj.get("merged"):
            verb = "merged"
        action = _issue_action(verb, "pull request" if is_pr else "issue", n, payload)
        title = obj.get("title") or ""
        if obj.get("html_url"):
            url = obj["html_url"]
        elif n:
            url = f"{repo_url}/{'pull' if is_pr else 'issues'}/{n}"
        if verb == "opened":
            body = obj.get("body") or ""
        if isinstance(n, int) and n:
            subject_kind, number, subject_url = ("PR" if is_pr else "issue"), n, url
    elif etype == "IssueCommentEvent":
        issue = payload.get("issue") or {}
        comment = payload.get("comment") or {}
        n = issue.get("number")
        is_pr = "pull_request" in issue
        noun = "pull request" if is_pr else "issue"
        action = f"commented on {noun} #{n}" if n else "commented"
        title = issue.get("title") or ""
        url = comment.get("html_url") or issue.get("html_url") or url
        body = comment.get("body") or ""
        if isinstance(n, int) and n:
            subject_kind, number = ("PR" if is_pr else "issue"), n
            subject_url = issue.get("html_url") or (
                f"{repo_url}/{'pull' if is_pr else 'issues'}/{n}")
    elif etype in ("PullRequestReviewEvent", "PullRequestReviewCommentEvent"):
        pr = payload.get("pull_request") or {}
        n = pr.get("number")
        if etype == "PullRequestReviewEvent":
            review = payload.get("review") or {}
            phrase = {
                "approved": "approved",
                "changes_requested": "requested changes on",
            }.get((review.get("state") or "").lower(), "reviewed")
            url = review.get("html_url") or pr.get("html_url") or url
            body = review.get("body") or ""
        else:
            comment = payload.get("comment") or {}
            phrase = "commented on the review of"
            url = comment.get("html_url") or pr.get("html_url") or url
            body = comment.get("body") or ""
        action = f"{phrase} pull request #{n}" if n else f"{phrase} a pull request"
        title = pr.get("title") or ""
        if isinstance(n, int) and n:
            subject_kind, number = "PR", n
            subject_url = pr.get("html_url") or f"{repo_url}/pull/{n}"
    elif etype == "ReleaseEvent":
        release = payload.get("release") or {}
        verb = verb or "published"
        tag = release.get("tag_name") or ""
        action = f"{verb} release {tag}".strip()
        name = release.get("name") or ""
        title = name if name != tag else ""
        url = release.get("html_url") or url
        body = release.get("body") or ""
        if release.get("html_url"):
            subject_kind, subject_url = "release", release["html_url"]
    elif etype == "CommitCommentEvent":
        comment = payload.get("comment") or {}
        sha = (comment.get("commit_id") or "")[:7]
        action = f"commented on commit {sha}".strip()
        url = comment.get("html_url") or url
        body = comment.get("body") or ""
    elif etype == "PublicEvent":
        action = "made the repository public"
    elif etype == "MemberEvent":
        member = _login_of(payload.get("member"))
        action = f"{verb or 'added'} {member} as a collaborator".replace("  ", " ")
    elif etype == "GollumEvent":
        pages = [p for p in (payload.get("pages") or []) if isinstance(p, dict)]
        action = "edited the wiki"
        if pages:
            title = ", ".join(p["title"] for p in pages if p.get("title"))
            url = pages[0].get("html_url") or url
    elif etype == "DiscussionEvent":
        discussion = payload.get("discussion") or {}
        n = discussion.get("number")
        verb = verb or "updated"
        action = f"{verb} discussion #{n}" if n else f"{verb} a discussion"
        title = discussion.get("title") or ""
        url = discussion.get("html_url") or url
        if verb == "created":
            body = discussion.get("body") or ""
        if discussion.get("html_url"):
            subject_kind, subject_url = "discussion", discussion["html_url"]
            number = n if isinstance(n, int) else 0
    elif etype == "SponsorshipEvent":
        action = "sponsored"
    else:
        # "SomethingNewEvent" -> "something new", so a type added after this
        # was written still says roughly what happened.
        words = etype[:-5] if etype.endswith("Event") else etype
        action = "".join(f" {c.lower()}" if c.isupper() else c for c in words).strip()
        action = action or "did something"

    return ActivityEvent(
        event_type=etype,
        actor=actor,
        repo=repo,
        action=action,
        created_at=raw.get("created_at", "") or "",
        title=title,
        url=url,
        body=body,
        event_id=str(raw.get("id", "") or ""),
        verb=verb,
        subject_kind=subject_kind,
        number=number,
        subject_url=subject_url,
    )


# Pages of 100 the events API will serve; asking for a fourth is an HTTP 422.
_ACTIVITY_PAGES = ACTIVITY_MAX // 100

# Repositories per GraphQL query when looking up pull request titles. Keeps
# each query well inside GitHub's limits however busy the feed is.
_TITLE_QUERY_REPOS = 40


def _graphql(query: str, variables: dict | None = None) -> dict:
    """Run a GraphQL query and return the reply, partial or not.

    Not `_run_gh`: when part of a query can't be resolved (a deleted PR, a
    repo you can no longer read), gh prints the data it *did* get and still
    exits 1, and `_run_gh` would throw that data away. The query also goes in
    on stdin rather than the command line, so its length is never a problem.
    ``variables`` go with it as GraphQL variables: text someone typed (a
    comment) is passed that way, never pasted into the query.
    """
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    payload: dict = {"query": query}
    if variables:
        payload["variables"] = variables
    try:
        result = subprocess.run(
            [_find_gh(), "api", "graphql", "--input", "-"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
    except OSError as exc:
        raise GhError(str(exc))
    try:
        reply = json.loads(result.stdout) if result.stdout.strip() else None
    except ValueError:
        reply = None
    if not isinstance(reply, dict):
        raise GhError(result.stderr.strip() or "GraphQL query failed")
    return reply


def _fill_pr_titles(events: list[ActivityEvent]) -> None:
    """Look up the titles that pull request events no longer carry.

    GitHub trimmed the pull request in event payloads to little more than its
    number, so "opened pull request #341" arrives without saying what #341 is.
    GraphQL fetches every title in a query or two. Whatever can't be resolved
    comes back as null and that row simply goes without a title: the feed is
    worth showing anyway, so nothing here raises.
    """
    wanted: dict[str, set[int]] = {}
    for ev in events:
        if ev.pr_number and not ev.title and "/" in ev.repo:
            wanted.setdefault(ev.repo, set()).add(ev.pr_number)
    if not wanted:
        return

    found: dict[tuple[str, int], dict] = {}
    repos = sorted(wanted)
    for start in range(0, len(repos), _TITLE_QUERY_REPOS):
        chunk = repos[start:start + _TITLE_QUERY_REPOS]
        parts = []
        for i, repo in enumerate(chunk):
            owner, name = repo.split("/", 1)
            prs = " ".join(
                f"p{n}: pullRequest(number: {n}) {{ title body }}"
                for n in sorted(wanted[repo])
            )
            # json.dumps gives a valid GraphQL string literal, quotes escaped
            parts.append(
                f"r{i}: repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) {{ {prs} }}"
            )
        try:
            data = _graphql("{ " + " ".join(parts) + " }").get("data") or {}
        except Exception:  # noqa: BLE001 — titles are a nicety, never a failure
            continue
        if not isinstance(data, dict):
            continue
        for i, repo in enumerate(chunk):
            node = data.get(f"r{i}")
            if not isinstance(node, dict):
                continue
            for n in wanted[repo]:
                pr = node.get(f"p{n}")
                if isinstance(pr, dict):
                    found[(repo, n)] = pr

    for ev in events:
        pr = found.get((ev.repo, ev.pr_number))
        if pr and not ev.title:
            ev.title = pr.get("title") or ""
            if ev.verb == "opened" and not ev.body:
                ev.body = pr.get("body") or ""


def fetch_activity(limit: int = 100) -> tuple[list[ActivityEvent], bool]:
    """The signed-in user's activity feed, newest first.

    Returns the events and whether GitHub has more to give. Event pages are
    not reliably full (filtered events leave gaps, so a page of 100 can hold
    96), which is why a short page is not taken to be the last one here.
    """
    login = current_login()
    pages = max(1, min(-(-limit // 100), _ACTIVITY_PAGES))
    raw_events: list[dict] = []
    seen: set = set()
    exhausted = False
    read = 0
    for page in range(1, pages + 1):
        try:
            out = _run_gh([
                "api", f"users/{login}/received_events?per_page=100&page={page}",
            ])
            rows = json.loads(out) if out.strip() else []
        except (GhError, ValueError):
            if page == 1:
                raise
            # A later page failing should not cost the pages already read. It
            # says nothing about whether older events exist, so `more` stays
            # true and View More tries again.
            break
        if not isinstance(rows, list) or not rows:
            exhausted = True
            break
        read = page
        for r in rows:
            if not isinstance(r, dict):
                continue
            # Pages are offsets, so an event arriving between two requests
            # pushes one already read onto the next page as well.
            key = r.get("id")
            if key is not None:
                if key in seen:
                    continue
                seen.add(key)
            raw_events.append(r)
    events = [parse_event(r) for r in raw_events]
    # The API's order is close to newest first but not exact, and a list that
    # says "newest first" has to be. ISO timestamps sort as strings.
    events.sort(key=lambda e: e.created_at, reverse=True)
    _fill_pr_titles(events)
    more = not exhausted and read < _ACTIVITY_PAGES
    return events, more


# ── Notifications ──────────────────────────────────────────────────────
#
# The REST notifications API: GET /notifications lists threads (one per
# issue, pull request, release, discussion or CI run you are told about),
# newest first; PATCH marks one read, DELETE marks it done, PUT marks every
# one read. The `repo` scope gh asks for at login covers all of it.

# Status goes last: with only unread ones listed it would open every row
# with the same word.
NOTIFICATION_COLUMNS = ["reason", "type", "title", "repo", "updated", "status"]
NOTIFICATION_DEFAULT_COLUMNS = ["reason", "type", "title", "repo", "updated", "status"]

# GitHub's page size for notifications is at most 50, whatever is asked for.
_NOTIFICATION_PAGE = 50

# Why GitHub says it told you, in words.
_REASONS = {
    "approval_requested": "approval requested",
    "assign": "assigned",
    "author": "author",
    "ci_activity": "CI activity",
    "comment": "comment",
    "invitation": "invitation",
    "manual": "subscribed",
    "member_feature_requested": "feature requested",
    "mention": "mention",
    "review_requested": "review requested",
    "security_advisory_credit": "security credit",
    "security_alert": "security alert",
    "state_change": "state change",
    "subscribed": "watching",
    "team_mention": "team mention",
}

_SUBJECT_KINDS = {
    "Issue": "issue",
    "PullRequest": "PR",
    "Release": "release",
    "Discussion": "discussion",
    "Commit": "commit",
    "CheckSuite": "CI run",
    "RepositoryVulnerabilityAlert": "security alert",
    "RepositoryDependabotAlertsThread": "Dependabot alert",
    "RepositoryAdvisory": "security advisory",
    "RepositoryInvitation": "invitation",
}


@dataclass
class Notification:
    """One notification thread."""

    id: str
    title: str
    repo: str                 # OWNER/NAME
    reason: str = ""          # GitHub's code, e.g. "review_requested"
    subject_type: str = ""    # GitHub's type, e.g. "PullRequest"
    unread: bool = True
    updated_at: str = ""
    api_url: str = ""         # the subject's API address, when it has one
    url: str = ""             # where to read it on github.com
    number: int = 0           # issue or pull request number, else 0
    # Whether ``url`` is this thing's own page, or only the repository's page
    # for its kind (all its releases, all its runs) — not something to
    # favorite, since every notification of that kind shares it.
    own_page: bool = False

    @property
    def reason_display(self) -> str:
        return _REASONS.get(self.reason, self.reason.replace("_", " "))

    @property
    def kind(self) -> str:
        return _SUBJECT_KINDS.get(self.subject_type, self.subject_type)

    @property
    def is_item(self) -> bool:
        """An issue or pull request, which GHManage can open itself."""
        return bool(self.number) and self.subject_type in ("Issue", "PullRequest")

    def to_row(self, columns: list[str]) -> dict[str, str]:
        mapping = {
            "status": "unread" if self.unread else "read",
            "reason": self.reason_display,
            "type": self.kind,
            "title": f"#{self.number} {self.title}" if self.number else self.title,
            "repo": self.repo,
            "updated": _local_time(self.updated_at),
        }
        return {col: mapping.get(col, "") for col in columns}


def _notification_url(subject_type: str, api_url: str, repo: str) -> tuple[str, int, bool]:
    """The github.com address for a notification's subject, its number, and
    whether that address is the subject's own page.

    The API gives the subject's *API* address, which is not a page anyone can
    open: repos/o/r/pulls/12 is github.com/o/r/pull/12. Some subjects have no
    address at all (CI runs), or one that doesn't map without asking GitHub
    (a release by id); those fall back to the repository's page for that kind
    of thing.
    """
    base = f"https://github.com/{repo}" if repo else "https://github.com"
    prefix = f"https://api.github.com/repos/{repo}/"
    rest = api_url[len(prefix):] if api_url.lower().startswith(prefix.lower()) else ""
    parts = rest.split("/")
    if len(parts) == 2 and parts[1].isdigit():
        if parts[0] == "issues":
            return f"{base}/issues/{parts[1]}", int(parts[1]), True
        if parts[0] == "pulls":
            return f"{base}/pull/{parts[1]}", int(parts[1]), True
        if parts[0] == "discussions":
            return f"{base}/discussions/{parts[1]}", 0, True
    if len(parts) == 2 and parts[0] == "commits" and parts[1]:
        return f"{base}/commit/{parts[1]}", 0, True
    if len(parts) == 2 and parts[0] == "security-advisories" and parts[1]:
        return f"{base}/security/advisories/{parts[1]}", 0, True
    fallback = {
        "Release": "/releases",
        "Discussion": "/discussions",
        "CheckSuite": "/actions",
        "RepositoryVulnerabilityAlert": "/security",
        "RepositoryDependabotAlertsThread": "/security/dependabot",
        "RepositoryAdvisory": "/security/advisories",
        "RepositoryInvitation": "/invitations",
    }.get(subject_type, "")
    return base + fallback, 0, False


def parse_notification(raw: dict) -> Notification:
    subject = raw.get("subject") or {}
    repo = ((raw.get("repository") or {}).get("full_name")) or ""
    subject_type = subject.get("type") or ""
    api_url = subject.get("url") or ""
    url, number, own_page = _notification_url(subject_type, api_url, repo)
    return Notification(
        id=str(raw.get("id") or ""),
        title=subject.get("title") or "",
        repo=repo,
        reason=raw.get("reason") or "",
        subject_type=subject_type,
        unread=bool(raw.get("unread")),
        updated_at=raw.get("updated_at") or "",
        api_url=api_url,
        url=url,
        number=number,
        own_page=own_page,
    )


def release_page(api_url: str) -> str:
    """A release's github.com page, from its API address (repos/o/r/releases/<id>)."""
    try:
        data = json.loads(_run_gh(["api", api_url.split("api.github.com/", 1)[-1]]))
    except (GhError, ValueError):
        return ""
    return (data.get("html_url") or "") if isinstance(data, dict) else ""


def _api_page(endpoint: str) -> tuple[list, bool]:
    """One page of a REST list, and whether GitHub says there is a next one.

    The Link header's rel="next" is the only reliable answer: a full page
    may be the last, when the total is a whole number of pages.
    """
    raw = _run_gh(["api", "-i", endpoint])
    head, blank, body = raw.replace("\r\n", "\n").partition("\n\n")
    if not blank:
        raise GhError(f"Unexpected reply from {endpoint}")
    more = any(
        line.lower().startswith("link:") and 'rel="next"' in line
        for line in head.splitlines()
    )
    try:
        rows = json.loads(body) if body.strip() else []
    except ValueError:
        raise GhError(f"Unexpected reply from {endpoint}")
    return (rows if isinstance(rows, list) else []), more


def fetch_notifications(limit: int = 50, include_read: bool = False) -> tuple[list[Notification], bool]:
    """Your notifications, most recently updated first.

    Returns them and whether GitHub has more. Unread ones only unless
    ``include_read``, which is what github.com's inbox shows by default too.
    """
    base = "notifications?all=true" if include_read else "notifications?all=false"
    out: list[Notification] = []
    seen: set[str] = set()
    page = 1
    more = False
    while len(out) < limit:
        rows, more = _api_page(f"{base}&per_page={_NOTIFICATION_PAGE}&page={page}")
        for r in rows:
            if not isinstance(r, dict):
                continue
            note = parse_notification(r)
            # Pages are offsets into an inbox that changes as you read, so a
            # thread can turn up on two of them.
            if note.id in seen:
                continue
            seen.add(note.id)
            out.append(note)
        if not more:
            break
        page += 1
    if len(out) > limit:
        out = out[:limit]
        more = True
    return out, more


def count_unread_notifications() -> int:
    """How many unread notifications you have."""
    return _count_items("notifications")


def mark_notification_read(thread_id: str) -> None:
    _run_gh(["api", "-X", "PATCH", f"notifications/threads/{thread_id}"])


def mark_notification_done(thread_id: str) -> None:
    """Done: off the inbox for good, as the Done button on github.com does."""
    _run_gh(["api", "-X", "DELETE", f"notifications/threads/{thread_id}"])


def mark_all_notifications_read(last_read_at: str = "") -> None:
    """Every notification read, up to ``last_read_at`` when given (ISO 8601).

    Pass the time the list was loaded, so anything that arrived since — that
    you have not seen — stays unread. GitHub may finish this in the background.
    """
    args = ["api", "-X", "PUT", "notifications", "-F", "read=true"]
    if last_read_at:
        args += ["-f", f"last_read_at={last_read_at}"]
    _run_gh(args)


def unsubscribe_notification(thread_id: str) -> None:
    """Stop notifications for this thread until you comment or are mentioned."""
    _run_gh(["api", "-X", "DELETE", f"notifications/threads/{thread_id}/subscription"])


# ── Accounts ───────────────────────────────────────────────────────────
#
# gh keeps the accounts; GHManage only asks which there are and which is in
# use, and asks gh to switch. Only github.com accounts are offered: every
# other call here talks to github.com.


@dataclass
class Account:
    login: str
    host: str = "github.com"
    active: bool = False


def list_accounts() -> list[Account]:
    """The github.com accounts gh is signed in to, the one in use first."""
    # gh exits non-zero when any stored account's token has gone bad, but
    # still prints the list; that list is what is needed, bad entry and all.
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            [_find_gh(), "auth", "status", "--json", "hosts"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=creationflags,
        )
    except OSError as exc:
        raise GhError(str(exc))
    raw = result.stdout
    if not raw.strip():
        err = result.stderr.strip()
        if "unknown flag" in err:
            raise GhError("Switching accounts needs a newer gh. Update it from "
                          "https://cli.github.com/ and try again.")
        raise GhError(err or "gh didn't list its accounts.")
    try:
        hosts = (json.loads(raw) or {}).get("hosts") or {}
    except ValueError:
        raise GhError("gh's account list couldn't be read.")
    out = [
        Account(a.get("login") or "", host, bool(a.get("active")))
        for host, accounts in hosts.items() if host == "github.com"
        for a in (accounts or []) if isinstance(a, dict) and a.get("login")
    ]
    out.sort(key=lambda a: not a.active)
    return out


def switch_account(login: str, host: str = "github.com") -> None:
    """Make ``login`` the account gh uses — for GHManage and the terminal alike."""
    global _login
    _run_gh(["auth", "switch", "--hostname", host, "--user", login])
    _login = None  # current_login() must ask again


# ── Watching a repository ──────────────────────────────────────────────
#
# GitHub's three plain levels. The web's "Custom" (only issues, only
# releases, …) is not in the API.

WATCH_PARTICIPATING = "participating"
WATCH_ALL = "all"
WATCH_IGNORE = "ignore"


class MissingScope(GhError):
    """gh's sign-in lacks a permission this needs; ``scope`` names it."""

    def __init__(self, scope: str) -> None:
        super().__init__(
            f'This needs gh\'s "{scope}" permission, which gh doesn\'t ask for '
            f"when you sign in. Run this in a terminal, then try again:\n\n"
            f"gh auth refresh -h github.com -s {scope}"
        )
        self.scope = scope


def _scope_error(exc: GhError) -> Optional[MissingScope]:
    text = str(exc)
    if "needs the" in text and "scope" in text:
        m = re.search(r'needs the "([^"]+)" scope', text)
        return MissingScope(m.group(1) if m else "notifications")
    return None


# ── Deleting and archiving a repository ────────────────────────────────


@dataclass
class RepoAdmin:
    """What you may do to a repository as a whole."""
    admin: bool       # deleting and archiving both need admin rights
    archived: bool


def repo_admin(repo: str) -> RepoAdmin:
    """Whether you are an admin of ``repo``, and whether it is archived."""
    raw = _run_gh(["repo", "view", repo, "--json", "viewerPermission,isArchived"])
    try:
        data = json.loads(raw) if raw.strip() else {}
    except ValueError:
        raise GhError(f"Unexpected reply about {repo}")
    if not isinstance(data, dict):
        data = {}
    return RepoAdmin(admin=data.get("viewerPermission") == "ADMIN",
                     archived=bool(data.get("isArchived")))


def delete_repo(repo: str) -> None:
    """Delete ``repo`` on GitHub, with everything in it. ``--yes`` because the
    caller has had the name typed back; there is no undo.

    gh doesn't ask for the "delete_repo" permission at sign-in, so the first
    try usually fails with MissingScope, which says how to add it.
    """
    try:
        _run_gh(["repo", "delete", repo, "--yes"])
    except GhError as exc:
        missing = _scope_error(exc)
        if missing:
            raise missing
        if "Must have admin rights" in str(exc):
            # gh only names the missing scope for a classic token. A
            # fine-grained token, or one in GH_TOKEN, just gets the 403.
            raise GhError(f"{exc}\n\nIf gh signs in with a token, the token needs the "
                          '"delete_repo" scope, or for a fine-grained token, write access '
                          "to the repository's Administration.")
        raise


def set_archived(repo: str, archived: bool) -> None:
    """Archive ``repo`` (read-only, can be undone) or unarchive it."""
    _run_gh(["repo", "archive" if archived else "unarchive", repo, "--yes"])


def get_watch_level(repo: str) -> str:
    """How you watch ``repo``: all activity, ignoring, or participating only."""
    try:
        raw = _run_gh(["api", f"repos/{repo}/subscription"])
    except GhError as exc:
        missing = _scope_error(exc)
        if missing:
            raise missing
        if _is_not_found(exc):
            return WATCH_PARTICIPATING  # no subscription: the default
        raise
    try:
        data = json.loads(raw) if raw.strip() else {}
    except ValueError:
        raise GhError(f"Unexpected reply about watching {repo}")
    if not isinstance(data, dict):
        data = {}
    if data.get("ignored"):
        return WATCH_IGNORE
    return WATCH_ALL if data.get("subscribed") else WATCH_PARTICIPATING


def set_watch_level(repo: str, level: str) -> None:
    if level == WATCH_PARTICIPATING:
        args = ["api", "-X", "DELETE", f"repos/{repo}/subscription"]
    elif level == WATCH_ALL:
        args = ["api", "-X", "PUT", f"repos/{repo}/subscription", "-F", "subscribed=true"]
    elif level == WATCH_IGNORE:
        args = ["api", "-X", "PUT", f"repos/{repo}/subscription", "-F", "ignored=true"]
    else:
        raise ValueError(level)
    try:
        _run_gh(args)
    except GhError as exc:
        raise _scope_error(exc) or exc


# ── Search ─────────────────────────────────────────────────────────────
#
# GitHub's REST search endpoints, given the query exactly as typed:
# `gh search issues` splits and re-quotes its arguments, which mangles
# qualifiers such as review-requested:@me. Search has its own rate limit,
# 30 requests a minute, and returns at most 1,000 results for any query.

SEARCH_MAX = 1000

SEARCH_ITEM_COLUMNS = [
    "type", "number", "state", "title", "repo", "updated", "author", "labels", "comments",
]
SEARCH_ITEM_DEFAULT_COLUMNS = ["type", "number", "state", "title", "repo", "updated"]
MY_WORK_COLUMNS = ["why", "type", "number", "title", "repo", "updated", "author", "labels"]
MY_WORK_DEFAULT_COLUMNS = ["why", "type", "number", "title", "repo", "updated"]


def _search_page(kind: str, query: str, per_page: int, page: int) -> dict:
    raw = _run_gh([
        "api", "-X", "GET", f"search/{kind}",
        "-f", f"q={query}", "-f", f"per_page={per_page}", "-f", f"page={page}",
    ])
    try:
        data = json.loads(raw) if raw.strip() else {}
    except ValueError:
        raise GhError("Unexpected reply from GitHub search")
    return data if isinstance(data, dict) else {}


def _search(kind: str, query: str, limit: int, offset: int = 0) -> tuple[list[dict], int]:
    """Up to ``limit`` raw results from ``offset`` on, and the total GitHub
    says match. ``offset`` must be a whole number of pages of 100: View More
    asks only for the pages it hasn't got, since search allows 30 requests a
    minute and refetching from the start would run into that fast."""
    limit = max(1, min(limit, SEARCH_MAX - offset))
    per_page = 100 if offset else min(limit, 100)
    rows: list[dict] = []
    total = 0
    page = offset // 100 + 1
    while len(rows) < limit:
        data = _search_page(kind, query, per_page, page)
        total = int(data.get("total_count") or 0)
        items = [r for r in (data.get("items") or []) if isinstance(r, dict)]
        rows.extend(items)
        if len(items) < per_page or offset + len(rows) >= min(total, SEARCH_MAX):
            break
        page += 1
    return rows[:limit], total


def _repo_of(api_url: str) -> str:
    """OWNER/NAME from https://api.github.com/repos/OWNER/NAME."""
    tail = api_url.split("/repos/", 1)[-1] if "/repos/" in api_url else ""
    return "/".join(tail.split("/")[:2]) if tail.count("/") >= 1 else ""


def parse_search_item(raw: dict) -> Item:
    """An issue or pull request from the search API, as an Item."""
    pr = raw.get("pull_request")
    is_pr = isinstance(pr, dict)
    labels = [l.get("name", "") if isinstance(l, dict) else str(l) for l in raw.get("labels") or []]
    assignees = [a.get("login", "") for a in raw.get("assignees") or [] if isinstance(a, dict)]
    return Item(
        number=int(raw.get("number") or 0),
        title=raw.get("title") or "",
        state=(raw.get("state") or "open").upper(),
        url=raw.get("html_url") or "",
        is_pr=is_pr,
        author=_login_of(raw.get("user")),
        created_at=raw.get("created_at") or "",
        updated_at=raw.get("updated_at") or "",
        body=raw.get("body") or "",
        labels=labels,
        assignees=assignees,
        comments=int(raw.get("comments") or 0),
        is_draft=bool(raw.get("draft")),
        is_merged=bool(is_pr and pr.get("merged_at")),
        repo=_repo_of(raw.get("repository_url") or ""),
    )


def search_issues(query: str, limit: int = 100, offset: int = 0) -> tuple[list[Item], int]:
    """Issues and pull requests matching ``query``, best match first."""
    rows, total = _search("issues", query, limit, offset)
    return [parse_search_item(r) for r in rows], total


def search_repos(query: str, limit: int = 100, offset: int = 0) -> tuple[list[RepoEntry], int]:
    """Repositories matching ``query``, best match first."""
    rows, total = _search("repositories", query, limit, offset)
    return [_repo_entry(r) for r in rows if r.get("full_name")], total


# My Work: what needs you, one search per reason. Earlier reasons win when
# an item matches several — a PR you are asked to review and are also
# mentioned in is listed once, as a review.
MY_WORK_QUERIES = [
    ("review requested", "is:open is:pr review-requested:@me archived:false"),
    ("assigned", "is:open assignee:@me archived:false"),
    ("your pull request", "is:open is:pr author:@me archived:false"),
    ("your issue", "is:open is:issue author:@me archived:false"),
    ("mentioned", "is:open mentions:@me archived:false"),
]


def fetch_my_work(limit_each: int = 100) -> tuple[list[Item], set[str], list[str]]:
    """Open issues and pull requests that need you, grouped by why, most
    recently updated first in each group; the reasons that had more than
    ``limit_each``, so the count can say "100+"; and the reasons whose search
    failed (the rate limit, say), whose part is missing rather than all of it.
    """
    seen: set[str] = set()
    out: list[Item] = []
    capped: set[str] = set()
    failed: list[str] = []
    for why, query in MY_WORK_QUERIES:
        try:
            items, total = search_issues(query + " sort:updated-desc", limit_each)
        except GhError:
            failed.append(why)
            continue
        if total > len(items):
            capped.add(why)
        for item in items:
            if item.url in seen:
                continue
            seen.add(item.url)
            item.why = why
            out.append(item)
    order = {why: i for i, (why, _) in enumerate(MY_WORK_QUERIES)}
    out.sort(key=lambda it: it.updated_at, reverse=True)
    out.sort(key=lambda it: order.get(it.why, 99))
    if failed and len(failed) == len(MY_WORK_QUERIES):
        raise GhError("GitHub search isn't answering; try again in a minute.")
    return out, capped, failed


# ── Workflow run jobs, logs, rerun and cancel ─────────────────────────

JOB_COLUMNS = ["name", "status", "result", "duration", "failed step"]
JOB_DEFAULT_COLUMNS = ["name", "status", "result", "duration", "failed step"]


@dataclass
class JobStep:
    number: int
    name: str
    status: str = ""
    conclusion: str = ""


@dataclass
class WorkflowJob:
    """One job of a workflow run, with its steps."""

    id: int
    name: str
    status: str = ""
    conclusion: str = ""
    started_at: str = ""
    completed_at: str = ""
    url: str = ""
    steps: list[JobStep] = field(default_factory=list)

    @property
    def duration(self) -> str:
        from datetime import datetime
        try:
            start = datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
            end = datetime.fromisoformat(self.completed_at.replace("Z", "+00:00"))
        except ValueError:
            return ""
        seconds = int((end - start).total_seconds())
        if seconds < 0:
            return ""
        return f"{seconds // 60}m {seconds % 60}s" if seconds >= 60 else f"{seconds}s"

    @property
    def failed_steps(self) -> list[JobStep]:
        return [s for s in self.steps if s.conclusion == "failure"]

    def to_row(self, columns: list[str]) -> dict[str, str]:
        failed = self.failed_steps
        mapping = {
            "name": self.name,
            "status": self.status,
            "result": self.conclusion or "(running)",
            "duration": self.duration,
            "failed step": failed[0].name if failed else "",
        }
        return {col: mapping.get(col, "") for col in columns}


def _repo_args(repo: Optional[str]) -> list[str]:
    return ["-R", repo] if repo else []


def fetch_run_jobs(repo: Optional[str], run_id: int) -> list[WorkflowJob]:
    """The jobs of a run's latest attempt, in the order they ran."""
    rows: list = []
    page = 1
    while True:  # a big matrix has more than one page of jobs
        data = _api_json(
            [f"repos/{{owner}}/{{repo}}/actions/runs/{run_id}/jobs?per_page=100&page={page}"], repo)
        batch = (data.get("jobs") if isinstance(data, dict) else None) or []
        rows.extend(batch)
        total = int(data.get("total_count") or 0) if isinstance(data, dict) else 0
        if len(batch) < 100 or len(rows) >= total or page >= 10:
            break
        page += 1
    jobs = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        steps = [
            JobStep(int(s.get("number") or 0), s.get("name") or "",
                    s.get("status") or "", s.get("conclusion") or "")
            for s in r.get("steps") or [] if isinstance(s, dict)
        ]
        jobs.append(WorkflowJob(
            id=int(r.get("id") or 0), name=r.get("name") or "",
            status=r.get("status") or "", conclusion=r.get("conclusion") or "",
            started_at=r.get("started_at") or "", completed_at=r.get("completed_at") or "",
            url=r.get("html_url") or "", steps=steps,
        ))
    return jobs


# Terminal colour codes, which logs keep from the tools that wrote them.
_ANSI = re.compile(
    r"\x1b\[[0-9;:?]*[ -/]*[@-~]"           # CSI: colours, cursor moves, line clears
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"   # OSC: hyperlinks, titles
    r"|\x1b[()][A-Za-z0-9]"                  # character set switches
    r"|\^\[\[[0-9;:?]*[A-Za-z]"               # the same, written out as ^[[
)
# The timestamp GitHub puts at the start of every log line.
_STAMP = re.compile(r"^\ufeff?\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z ?")


def clean_log_line(line: str) -> str:
    """A log line as a person wants to read it: no colour codes, no stamp,
    and GitHub's ##[error] / ##[warning] markers in words."""
    line = _STAMP.sub("", _ANSI.sub("", line))
    for marker, word in (("##[error]", "ERROR: "), ("##[warning]", "WARNING: "),
                         ("##[group]", ""), ("##[endgroup]", ""), ("##[notice]", "NOTE: "),
                         ("##[command]", "Command: "), ("[command]", "Command: "),
                         ("##[debug]", "Debug: ")):
        if line.startswith(marker):
            return word + line[len(marker):]
    return line


def parse_run_log(text: str) -> list[tuple[str, str, list[str]]]:
    """``gh run view --log`` output as (job, step, cleaned lines), in order.

    Each line arrives as job TAB step TAB stamped text.
    """
    out: list[tuple[str, str, list[str]]] = []
    # "\n" only: splitlines() also breaks at form feeds and other characters
    # tools print mid-line, leaving a piece with no job and step in front.
    for raw in text.split("\n"):
        raw = raw.rstrip("\r")
        parts = raw.split("\t", 2)
        if len(parts) != 3:
            if out and raw.strip():
                out[-1][2].append(clean_log_line(raw))  # a piece of the line before
            continue
        job, step, rest = parts
        line = clean_log_line(rest)
        if line == "" and rest.strip().endswith("##[endgroup]"):
            continue
        if out and out[-1][0] == job and out[-1][1] == step:
            out[-1][2].append(line)
        else:
            out.append((job, step, [line]))
    return out


def fetch_failed_log(repo: Optional[str], run_id: int) -> list[tuple[str, str, list[str]]]:
    """The log of every failed step in a run, grouped by job and step."""
    try:
        raw = _run_gh(["run", "view", str(run_id), "--log-failed", *_repo_args(repo)])
    except GhError as exc:
        if "log not found" in str(exc).lower():
            return []
        raise
    return parse_run_log(raw)


def fetch_job_log(repo: Optional[str], run_id: int, job_id: int) -> list[tuple[str, str, list[str]]]:
    """One job's whole log, grouped by step."""
    raw = _run_gh(["run", "view", str(run_id), "--job", str(job_id), "--log", *_repo_args(repo)])
    return parse_run_log(raw)


@dataclass
class Annotation:
    level: str        # failure, warning, notice
    message: str
    path: str = ""
    line: int = 0
    title: str = ""


def fetch_job_annotations(repo: Optional[str], job_id: int) -> list[Annotation]:
    """What GitHub flagged in a job: the errors and warnings shown on the run's page.

    A job is a check run, and its id is the check run's id.
    """
    try:
        data = _api_json([f"repos/{{owner}}/{{repo}}/check-runs/{job_id}/annotations"], repo)
    except GhError:
        return []  # a nicety; the logs still say what happened
    return [
        Annotation(a.get("annotation_level") or "", a.get("message") or "",
                   a.get("path") or "", int(a.get("start_line") or 0), a.get("title") or "")
        for a in (data if isinstance(data, list) else []) if isinstance(a, dict)
    ]


def rerun_workflow_run(repo: Optional[str], run_id: int, failed_only: bool = False) -> None:
    args = ["run", "rerun", str(run_id), *_repo_args(repo)]
    if failed_only:
        args.append("--failed")
    _run_gh(args)


def cancel_workflow_run(repo: Optional[str], run_id: int) -> None:
    _run_gh(["run", "cancel", str(run_id), *_repo_args(repo)])


# ── Pull request actions ───────────────────────────────────────────────
#
# Each takes the pull request's own address, which gh accepts in place of a
# number. Not number + repo: on a fork, the repo has to be resolved to its
# upstream first, and if that lookup fails (it falls back to the fork) the
# same number is a different pull request — the wrong one to merge.

MERGE_METHODS = [("merge", "Create a merge commit"), ("squash", "Squash and merge"),
                 ("rebase", "Rebase and merge")]


def _pr_parts(pr_url: str) -> tuple[str, int]:
    """(OWNER/NAME, number) from https://github.com/OWNER/NAME/pull/N."""
    m = re.match(r"https?://[^/]+/([^/]+/[^/]+)/pull/(\d+)", pr_url or "")
    if not m:
        raise GhError(f"Not a pull request address: {pr_url!r}")
    return m.group(1), int(m.group(2))


@dataclass
class Check:
    name: str
    state: str           # SUCCESS, FAILURE, PENDING, SKIPPED, …
    bucket: str = ""     # pass, fail, pending, skipping, cancel
    workflow: str = ""
    link: str = ""
    description: str = ""


def fetch_pr_checks(pr_url: str) -> list[Check]:
    """A pull request's checks, failing ones first.

    gh exits non-zero when checks fail (1) or are still running (8) while
    printing them all the same, so its output is read whatever it exits with.
    """
    _pr_parts(pr_url)
    args = ["pr", "checks", pr_url, "--json", "name,state,bucket,link,workflow,description"]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            [_find_gh(), *args], capture_output=True, text=True, encoding="utf-8",
            errors="replace", creationflags=creationflags,
        )
    except OSError as exc:
        raise GhError(str(exc))
    out = result.stdout.strip()
    if not out:
        err = result.stderr.strip()
        if "no checks reported" in err:
            return []
        raise GhError(err or "gh didn't list the checks.")
    try:
        rows = json.loads(out)
    except ValueError:
        raise GhError("Unexpected reply listing checks")
    checks = [
        Check(r.get("name") or "", r.get("state") or "", r.get("bucket") or "",
              r.get("workflow") or "", r.get("link") or "", r.get("description") or "")
        for r in rows if isinstance(r, dict)
    ]
    order = {"fail": 0, "cancel": 1, "pending": 2, "pass": 3, "skipping": 4}
    checks.sort(key=lambda c: (order.get(c.bucket, 5), c.workflow, c.name))
    return checks


def allowed_merge_methods(pr_url: str) -> list[str]:
    """Which of merge, squash and rebase the pull request's repository allows."""
    repo, _ = _pr_parts(pr_url)
    raw = _run_gh(["repo", "view", repo, "--json",
                   "mergeCommitAllowed,squashMergeAllowed,rebaseMergeAllowed"])
    try:
        data = json.loads(raw)
    except ValueError:
        return [m for m, _ in MERGE_METHODS]
    allowed = {"merge": data.get("mergeCommitAllowed"), "squash": data.get("squashMergeAllowed"),
               "rebase": data.get("rebaseMergeAllowed")}
    return [m for m, _ in MERGE_METHODS if allowed.get(m, True)]


def merge_pr(pr_url: str, method: str, delete_branch: bool = False) -> str:
    """Merge, and say what actually happened: "merged"; "auto" when GitHub
    turned on auto-merge to wait for required checks; or "queued" when it
    accepted the request without merging yet (a merge queue)."""
    if method not in ("merge", "squash", "rebase"):
        raise ValueError(method)
    _pr_parts(pr_url)
    args = ["pr", "merge", pr_url, f"--{method}"]
    if delete_branch:
        args.append("--delete-branch")
    _run_gh(args)
    try:
        data = json.loads(_run_gh(["pr", "view", pr_url, "--json", "state,autoMergeRequest"]))
    except (GhError, ValueError):
        return "queued"
    if data.get("state") == "MERGED":
        return "merged"
    return "auto" if data.get("autoMergeRequest") else "queued"


def set_pr_ready(pr_url: str, ready: bool) -> None:
    """Ready for review, or (``ready=False``) back to a draft."""
    _pr_parts(pr_url)
    args = ["pr", "ready", pr_url]
    if not ready:
        args.append("--undo")
    _run_gh(args)


def review_pr(pr_url: str, kind: str, body: str = "") -> None:
    """Approve, request changes, or comment, as a review."""
    flag = {"approve": "--approve", "request-changes": "--request-changes",
            "comment": "--comment"}[kind]
    _pr_parts(pr_url)
    args = ["pr", "review", pr_url, flag]
    if body:
        args += ["--body-file", "-"]
    _run_gh(args, stdin=body or None)


def request_reviewers(pr_url: str, logins: list[str]) -> None:
    _pr_parts(pr_url)
    _run_gh(["pr", "edit", pr_url, "--add-reviewer", ",".join(logins)])


def update_pr_branch(pr_url: str) -> None:
    """Bring the pull request's branch up to date with its base (a merge)."""
    repo, number = _pr_parts(pr_url)
    _run_gh(["api", "-X", "PUT", f"repos/{repo}/pulls/{number}/update-branch"])




# ── Security alerts ────────────────────────────────────────────────────
#
# A repository's Dependabot, code scanning and secret scanning alerts, read
# together (#85). Read-only: nothing here dismisses or changes an alert.
#
# Each kind is switched on separately and needs its own rights, so each one
# fails on its own: Dependabot answers 403 "disabled", code scanning 404 "no
# analysis found" or 403 "not enabled", secret scanning 404 "disabled". gh
# adds a "needs the admin:repo_hook scope" hint to every one of those, which
# is wrong for them all, so the hint is only believed once "not set up" has
# been ruled out, and the scope named is always security_events.
#
# The three page differently: Dependabot refuses ``page=`` (HTTP 400) and
# pages by cursor in the Link header; the other two take ``page=``. Secret
# scanning's state is open or resolved and nothing else (``all`` is a 400),
# so View > State > All leaves the state out for every kind.

SECURITY_COLUMNS = ["kind", "severity", "package", "summary", "where", "state", "created",
                    "number", "updated"]
SECURITY_DEFAULT_COLUMNS = ["kind", "severity", "package", "summary", "where", "state",
                            "created"]

ALERT_DEPENDABOT = "dependabot"
ALERT_CODE = "code-scanning"
ALERT_SECRET = "secret-scanning"
ALERT_KINDS = (ALERT_DEPENDABOT, ALERT_CODE, ALERT_SECRET)
ALERT_KIND_LABELS = {
    ALERT_DEPENDABOT: "Dependabot",
    ALERT_CODE: "Code scanning",
    ALERT_SECRET: "Secret scanning",
}
SECURITY_SCOPE = "security_events"

# Most severe first. Code scanning gives a security severity (critical to
# low) for security rules; for the rest only the tool's own error, warning or
# note, which come after every security severity. Secret scanning gives none.
SEVERITY_RANK = {
    "critical": 0, "high": 1, "medium": 2, "moderate": 2, "low": 3,
    "error": 4, "warning": 5, "note": 6,
}
UNKNOWN_SEVERITY_RANK = 7

# View > State as each kind's states.
_ALERT_STATES = {
    "open": {ALERT_DEPENDABOT: "open", ALERT_CODE: "open", ALERT_SECRET: "open"},
    "closed": {ALERT_DEPENDABOT: "dismissed,fixed,auto_dismissed", ALERT_CODE: "closed",
               ALERT_SECRET: "resolved"},
}


@dataclass
class SecurityAlert:
    """One Dependabot, code scanning or secret scanning alert."""
    kind: str                     # ALERT_DEPENDABOT, ALERT_CODE or ALERT_SECRET
    number: int
    state: str                    # GitHub's word: open, dismissed, fixed, resolved…
    severity: str = ""            # lower case; "" when GitHub gives none
    package: str = ""             # the package, the rule, or the secret's type
    summary: str = ""
    where: str = ""               # manifest, file:line, or where the secret was found
    created_at: str = ""
    updated_at: str = ""
    url: str = ""
    ident: str = ""               # CVE or GHSA id, rule id, or secret type
    ident_noun: str = "ID"
    # Everything else the details panel shows; see alertview.alert_details.
    info: dict = field(default_factory=dict)

    @property
    def kind_display(self) -> str:
        return ALERT_KIND_LABELS.get(self.kind, self.kind)

    @property
    def state_display(self) -> str:
        return self.state.replace("_", "-")

    @property
    def severity_rank(self) -> int:
        if (self.kind == ALERT_SECRET and self.state == "open"
                and (self.info.get("validity") == "active" or self.info.get("publicly_leaked"))):
            # A secret that still works, or is out in public, has no severity
            # from GitHub but is as urgent as anything: it goes with the high ones.
            return SEVERITY_RANK["high"]
        return SEVERITY_RANK.get(self.severity, UNKNOWN_SEVERITY_RANK)

    def to_row(self, columns: list[str]) -> dict[str, str]:
        mapping = {
            "kind": self.kind_display,
            "severity": self.severity,
            "package": self.package,
            "summary": self.summary,
            "where": self.where,
            "state": self.state_display,
            "created": self.created_at[:10],
            "updated": self.updated_at[:10],
            "number": str(self.number) if self.number else "",
        }
        return {c: mapping.get(c, "") for c in columns}


@dataclass
class SecurityAlerts:
    """What the Security Alerts view shows: the alerts, most severe first,
    and a plain sentence for each kind GitHub wouldn't show."""
    alerts: list[SecurityAlert]
    unavailable: dict[str, str] = field(default_factory=dict)   # kind -> sentence
    missing_scope: list[str] = field(default_factory=list)      # kinds needing the scope
    full: list[str] = field(default_factory=list)               # kinds that hit the limit

    def notes(self) -> list[str]:
        """Sentences about the kinds that couldn't be read, in kind order;
        those that need gh's security_events permission are said once."""
        out = [self.unavailable[k] for k in ALERT_KINDS if k in self.unavailable]
        if self.missing_scope:
            out.append(scope_sentence(self.missing_scope))
        return out


def scope_sentence(kinds: list[str]) -> str:
    """One sentence for the kinds that need gh's security_events permission."""
    names = [ALERT_KIND_LABELS[k] for k in ALERT_KINDS if k in kinds] or ["Security"]
    names = [names[0]] + [n.lower() for n in names[1:]]
    joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return (f"{joined} alerts need gh's {SECURITY_SCOPE} permission. Run "
            f"gh auth refresh -h github.com -s {SECURITY_SCOPE} in a terminal, "
            f"then press R.")


def sort_alerts(alerts: list[SecurityAlert]) -> list[SecurityAlert]:
    """Most severe first (critical, high, medium, low, then the rest), then newest."""
    newest = sorted(alerts, key=lambda a: a.created_at, reverse=True)
    return sorted(newest, key=lambda a: a.severity_rank)


def _login(user) -> str:
    return (user.get("login") or "") if isinstance(user, dict) else ""


def _dependabot_alert(raw: dict) -> SecurityAlert:
    dep = raw.get("dependency") or {}
    pkg = dep.get("package") or {}
    adv = raw.get("security_advisory") or {}
    vuln = raw.get("security_vulnerability") or {}
    patched = (vuln.get("first_patched_version") or {}).get("identifier") or ""
    ghsa = adv.get("ghsa_id") or ""
    cve = adv.get("cve_id") or ""
    score = (adv.get("cvss") or {}).get("score")
    if not score:
        # Newer advisories score under cvss_severities; take the newest version given.
        sev = adv.get("cvss_severities") or {}
        for key in ("cvss_v4", "cvss_v3"):
            if (sev.get(key) or {}).get("score"):
                score = sev[key]["score"]
                break
    name = pkg.get("name") or ""
    eco = pkg.get("ecosystem") or ""
    return SecurityAlert(
        kind=ALERT_DEPENDABOT,
        number=raw.get("number") or 0,
        state=raw.get("state") or "",
        severity=(vuln.get("severity") or adv.get("severity") or "").lower(),
        package=f"{name} ({eco})" if name and eco else name,
        summary=adv.get("summary") or "",
        where=dep.get("manifest_path") or "",
        created_at=raw.get("created_at") or "",
        updated_at=raw.get("updated_at") or "",
        url=raw.get("html_url") or "",
        ident=cve or ghsa,
        ident_noun="CVE" if cve else "GHSA ID",
        info={
            "ghsa": ghsa, "cve": cve, "cvss": score or "",
            "description": adv.get("description") or "",
            "range": vuln.get("vulnerable_version_range") or "",
            "patched": patched,
            "scope": dep.get("scope") or "",
            "relationship": dep.get("relationship") or "",
            "advisory_url": f"https://github.com/advisories/{ghsa}" if ghsa else "",
            "dismissed_at": raw.get("dismissed_at") or "",
            "dismissed_by": _login(raw.get("dismissed_by")),
            "dismissed_reason": raw.get("dismissed_reason") or "",
            "dismissed_comment": raw.get("dismissed_comment") or "",
            "fixed_at": raw.get("fixed_at") or "",
            "auto_dismissed_at": raw.get("auto_dismissed_at") or "",
        },
    )


def _code_alert(raw: dict) -> SecurityAlert:
    rule = raw.get("rule") or {}
    tool = raw.get("tool") or {}
    inst = raw.get("most_recent_instance") or {}
    loc = inst.get("location") or {}
    path = loc.get("path") or ""
    line = loc.get("start_line") or 0
    rule_id = rule.get("id") or rule.get("name") or ""
    return SecurityAlert(
        kind=ALERT_CODE,
        number=raw.get("number") or 0,
        state=raw.get("state") or "",
        severity=(rule.get("security_severity_level") or rule.get("severity") or "").lower(),
        package=rule_id,
        summary=rule.get("description") or rule.get("name") or "",
        where=f"{path}:{line}" if path and line else path,
        created_at=raw.get("created_at") or "",
        updated_at=raw.get("updated_at") or "",
        url=raw.get("html_url") or "",
        ident=rule_id,
        ident_noun="Rule ID",
        info={
            "rule_description": rule.get("full_description") or "",
            "tool_severity": (rule.get("severity") or "").lower(),
            "tags": [t for t in rule.get("tags") or [] if isinstance(t, str)],
            "tool": " ".join(x for x in (tool.get("name"), tool.get("version")) if x),
            "path": path, "start_line": line, "end_line": loc.get("end_line") or 0,
            "ref": inst.get("ref") or "",
            "message": (inst.get("message") or {}).get("text") or "",
            "classifications": [c for c in inst.get("classifications") or []
                                if isinstance(c, str)],
            "dismissed_at": raw.get("dismissed_at") or "",
            "dismissed_by": _login(raw.get("dismissed_by")),
            "dismissed_reason": raw.get("dismissed_reason") or "",
            "dismissed_comment": raw.get("dismissed_comment") or "",
            "fixed_at": raw.get("fixed_at") or "",
        },
    )


def _secret_alert(raw: dict) -> SecurityAlert:
    secret_type = raw.get("secret_type") or ""
    first = raw.get("first_location_detected") or {}
    path = first.get("path") or ""
    line = first.get("start_line") or 0
    return SecurityAlert(
        kind=ALERT_SECRET,
        number=raw.get("number") or 0,
        state=raw.get("state") or "",
        severity="",
        package=secret_type,
        summary=raw.get("secret_type_display_name") or secret_type,
        where=f"{path}:{line}" if path and line else path,
        created_at=raw.get("created_at") or "",
        updated_at=raw.get("updated_at") or "",
        url=raw.get("html_url") or "",
        ident=secret_type,
        ident_noun="Secret Type",
        info={
            "validity": raw.get("validity") or "",
            "path": path, "start_line": line,
            "more_locations": bool(raw.get("has_more_locations")),
            "publicly_leaked": bool(raw.get("publicly_leaked")),
            "bypassed": bool(raw.get("push_protection_bypassed")),
            "bypassed_by": _login(raw.get("push_protection_bypassed_by")),
            "bypassed_at": raw.get("push_protection_bypassed_at") or "",
            "resolution": raw.get("resolution") or "",
            "resolved_by": _login(raw.get("resolved_by")),
            "resolved_at": raw.get("resolved_at") or "",
            "resolution_comment": raw.get("resolution_comment") or "",
        },
    )


_ALERT_PARSERS = {
    ALERT_DEPENDABOT: _dependabot_alert,
    ALERT_CODE: _code_alert,
    ALERT_SECRET: _secret_alert,
}


def _next_link(head: str) -> str:
    """The rel="next" address in an HTTP header block, or ""."""
    for line in head.splitlines():
        if not line.lower().startswith("link:"):
            continue
        for part in line.split(":", 1)[1].split(","):
            url, _, params = part.partition(";")
            if 'rel="next"' in params:
                return url.strip().strip("<>")
    return ""


def _api_cursor_pages(endpoint: str, limit: int) -> list[dict]:
    """Up to ``limit`` entries of a REST list paged by cursor (the Link
    header's next address), as Dependabot's alerts are."""
    sep = "&" if "?" in endpoint else "?"
    url = f"{endpoint}{sep}per_page={max(1, min(limit, 100))}"
    out: list[dict] = []
    while url and len(out) < limit:
        raw = _run_gh(["api", "-i", url])
        head, blank, body = raw.replace("\r\n", "\n").partition("\n\n")
        if not blank:
            raise GhError(f"Unexpected reply from {endpoint}")
        try:
            rows = json.loads(body) if body.strip() else []
        except ValueError:
            raise GhError(f"Unexpected reply from {endpoint}")
        if not isinstance(rows, list):
            break
        out.extend(r for r in rows if isinstance(r, dict))
        nxt = _next_link(head)
        # gh api takes a path; the Link header gives a whole address.
        url = nxt.split("api.github.com/", 1)[1] if "api.github.com/" in nxt else nxt
    return out[:limit]


def _alerts_endpoint(repo: str, kind: str, state: str) -> str:
    query = []
    wanted = _ALERT_STATES.get(state, {}).get(kind)
    if wanted:
        query.append(f"state={wanted}")
    if kind == ALERT_SECRET:
        query.append("hide_secret=true")  # never fetch the secret itself
    return f"repos/{repo}/{kind}/alerts" + (f"?{'&'.join(query)}" if query else "")


# What GitHub says when a kind simply isn't switched on.
_NOT_SET_UP = ("disabled", "not enabled", "no analysis found", "not set up")
_NOT_SET_UP_SENTENCES = {
    ALERT_DEPENDABOT: "Dependabot alerts aren't turned on for this repository.",
    ALERT_CODE: "Code scanning isn't set up on this repository.",
    ALERT_SECRET: "Secret scanning isn't turned on for this repository.",
}


def classify_alert_error(kind: str, exc: GhError) -> tuple[str, str]:
    """Why ``kind`` couldn't be read: ("off" | "scope" | "rights" | "error",
    a sentence). The sentence is "" for "scope", which is said once for all
    the kinds that need it (scope_sentence)."""
    # gh's own hint about a scope is wrong for these endpoints (it names
    # admin:repo_hook whatever the failure), so it is set aside: GitHub's
    # message is what says what happened.
    lines = []
    for ln in str(exc).splitlines():
        ln = ln.strip()
        if ln.startswith("{") and "}gh: " in ln:
            ln = ln[ln.index("}gh: ") + 1:]  # the reply's JSON, then gh's line
        if ln and not ln.startswith("{") and "scope" not in ln:
            lines.append(ln)
    text = "\n".join(lines)
    low = text.lower()
    label = ALERT_KIND_LABELS.get(kind, kind)
    if any(s in low for s in _NOT_SET_UP):
        return "off", _NOT_SET_UP_SENTENCES.get(kind, f"{label} isn't set up on this repository.")
    if ("not authorized" in low or "admin rights" in low or "must be an admin" in low):
        # What a repository you don't administer answers: Dependabot "You are
        # not authorized to perform this operation.", code scanning "You are
        # not authorized to read code scanning alerts." (both HTTP 403).
        return "rights", (f"{label} alerts need admin or security manager rights on this "
                          "repository.")
    if "not found" in low and "(http 404)" in low:
        # Secret scanning's answer without rights; one that is off says "disabled".
        return "rights", (f"{label} alerts can't be read here: either it isn't turned on, "
                          "or it needs admin or security manager rights on this repository.")
    if "not accessible by" in low:
        # A token GitHub won't let read security alerts: gh's sign-in lacks
        # the permission, or a fine-grained token lacks it.
        return "scope", ""
    first = lines[0] if lines else str(exc).strip()
    if first.startswith("gh: "):
        first = first[4:]
    return "error", f"Couldn't read {label.lower()} alerts: {first}"


def _fetch_alert_kind(repo: str, kind: str, state: str, limit: int) -> list[SecurityAlert]:
    endpoint = _alerts_endpoint(repo, kind, state)
    rows = (_api_cursor_pages(endpoint, limit) if kind == ALERT_DEPENDABOT
            else _api_pages(endpoint, limit))
    parse = _ALERT_PARSERS[kind]
    return [parse(r) for r in rows]


def fetch_security_alerts(repo: str, state: str = "open", limit: int = 100) -> SecurityAlerts:
    """``repo``'s Dependabot, code scanning and secret scanning alerts in
    ``state`` (open, closed or all), up to ``limit`` of each, most severe
    first. The three are read at once and each may fail on its own; what
    can be read is returned, with a sentence for each kind that couldn't be."""
    found: dict[str, list[SecurityAlert]] = {}
    failed: dict[str, GhError] = {}
    with ThreadPoolExecutor(max_workers=len(ALERT_KINDS)) as pool:
        futures = {pool.submit(_fetch_alert_kind, repo, k, state, limit): k
                   for k in ALERT_KINDS}
        for fut in as_completed(futures):
            kind = futures[fut]
            try:
                found[kind] = fut.result()
            except GhError as exc:
                failed[kind] = exc
            except ValueError as exc:
                # A reply that isn't JSON; the other kinds still show.
                failed[kind] = GhError(f"Unexpected reply from GitHub ({exc})")
    result = SecurityAlerts(alerts=[])
    for kind in ALERT_KINDS:
        if kind in failed:
            why, sentence = classify_alert_error(kind, failed[kind])
            if why == "scope":
                result.missing_scope.append(kind)
            else:
                result.unavailable[kind] = sentence
            continue
        alerts = found.get(kind, [])
        if len(alerts) >= limit:
            result.full.append(kind)
        result.alerts.extend(alerts)
    result.alerts = sort_alerts(result.alerts)
    return result


# ── Discussions ────────────────────────────────────────────────────────
#
# GitHub Discussions are GraphQL only. The list comes with each discussion's
# body (cheap, and what selecting one shows first); its comments and their
# replies are read when one is selected (fetch_discussion_comments).

DISCUSSION_COLUMNS = ["number", "category", "title", "author", "answered", "comments",
                      "updated", "created", "state", "upvotes"]
DISCUSSION_DEFAULT_COLUMNS = ["number", "category", "title", "author", "answered",
                              "comments", "updated"]

# GitHub's page size for a connection is at most 100.
_DISCUSSION_PAGE = 100
# Pages of 100 comments read for one discussion, and replies per comment.
DISCUSSION_COMMENT_PAGES = 10
DISCUSSION_REPLIES = 100


@dataclass
class DiscussionComment:
    """A comment on a discussion, or a reply to one (``replies`` empty)."""

    author: str
    body: str = ""
    created_at: str = ""
    url: str = ""
    is_answer: bool = False
    upvotes: int = 0
    minimized: bool = False
    replies: list["DiscussionComment"] = field(default_factory=list)
    reply_count: int = 0   # GitHub's count; more than ``replies`` when cut short


@dataclass
class Discussion:
    """A repository discussion."""

    number: int
    title: str
    url: str = ""
    node_id: str = ""        # what addDiscussionComment needs
    repo: str = ""
    category: str = ""
    author: str = ""
    created_at: str = ""
    updated_at: str = ""
    body: str = ""
    answerable: bool = False  # in a Q&A-style category, which takes an answer
    answered: bool = False
    answer_author: str = ""
    answer_chosen_at: str = ""
    closed: bool = False
    locked: bool = False
    upvotes: int = 0
    comment_count: int = 0
    # Read when it is selected: None until then.
    comments: Optional[list[DiscussionComment]] = None
    comments_cut: bool = False  # more comments than were read
    # Bumped by each newer reading of the comments (after M posts), so an
    # older read still on its way can't put back a list without the new one.
    comments_version: int = field(default=0, compare=False)

    @property
    def answered_display(self) -> str:
        if not self.answerable:
            return ""
        return "Answered" if self.answered else "Unanswered"

    @property
    def state_display(self) -> str:
        if self.closed:
            return "Closed, locked" if self.locked else "Closed"
        return "Locked" if self.locked else "Open"

    def to_row(self, columns: list[str]) -> dict[str, str]:
        mapping = {
            "number": str(self.number),
            "category": self.category,
            "title": self.title,
            "author": self.author,
            "answered": self.answered_display,
            "comments": str(self.comment_count),
            "updated": self.updated_at[:10] if self.updated_at else "",
            "created": self.created_at[:10] if self.created_at else "",
            "state": self.state_display,
            "upvotes": str(self.upvotes),
        }
        return {col: mapping.get(col, "") for col in columns}


@dataclass
class Discussions:
    """A repository's discussions, or why there are none to show."""

    items: list[Discussion]
    enabled: bool = True
    more: bool = False   # GitHub has more than were read
    total: int = 0


def _login_of(node) -> str:
    # A deleted account's posts have no author; GitHub shows them as "ghost".
    return (node.get("login") or "ghost") if isinstance(node, dict) else "ghost"


_DISCUSSION_FIELDS = """
  id number title url createdAt updatedAt body closed locked upvoteCount
  author { login }
  category { name isAnswerable }
  isAnswered answerChosenAt
  answer { author { login } }
  comments { totalCount }
"""

_DISCUSSIONS_QUERY = """
query($owner: String!, $name: String!, $first: Int!, $after: String,
      $states: [DiscussionState!]) {
  repository(owner: $owner, name: $name) {
    hasDiscussionsEnabled
    discussions(first: $first, after: $after, states: $states,
                orderBy: {field: UPDATED_AT, direction: DESC}) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes { %s }
    }
  }
}""" % _DISCUSSION_FIELDS


def _parse_discussion(node: dict, repo: str) -> Discussion:
    category = node.get("category") if isinstance(node.get("category"), dict) else {}
    answer = node.get("answer") if isinstance(node.get("answer"), dict) else None
    comments = node.get("comments") if isinstance(node.get("comments"), dict) else {}
    return Discussion(
        number=node.get("number") or 0,
        title=node.get("title") or "",
        url=node.get("url") or "",
        node_id=node.get("id") or "",
        repo=repo,
        category=category.get("name") or "",
        author=_login_of(node.get("author")),
        created_at=node.get("createdAt") or "",
        updated_at=node.get("updatedAt") or "",
        body=node.get("body") or "",
        answerable=bool(category.get("isAnswerable")),
        answered=bool(node.get("isAnswered")) or answer is not None,
        answer_author=_login_of(answer.get("author")) if answer else "",
        answer_chosen_at=node.get("answerChosenAt") or "",
        closed=bool(node.get("closed")),
        locked=bool(node.get("locked")),
        upvotes=node.get("upvoteCount") or 0,
        comment_count=comments.get("totalCount") or 0,
    )


def _graphql_error(reply: dict, fallback: str) -> GhError:
    """GhError with GitHub's first error message, else ``fallback``."""
    errors = reply.get("errors") or []
    message = errors[0].get("message", "") if errors and isinstance(errors[0], dict) else ""
    return GhError(message or fallback)


def _discussion_states(state: str) -> list[str] | None:
    """View > State as GraphQL's DiscussionState list; None for all."""
    return {"open": ["OPEN"], "closed": ["CLOSED"]}.get(state)


def fetch_discussions(repo: str, state: str = "open", limit: int = 100) -> Discussions:
    """A repository's discussions, most recently active first, up to ``limit``.

    ``state`` is View > State: open, closed or all. With discussions turned
    off the answer says so (``enabled`` False) rather than raising.
    """
    owner, _, name = repo.partition("/")
    found: list[Discussion] = []
    after = None
    total = 0
    more = False
    while len(found) < limit:
        variables = {"owner": owner, "name": name,
                     "first": min(_DISCUSSION_PAGE, limit - len(found)),
                     "after": after, "states": _discussion_states(state)}
        reply = _graphql(_DISCUSSIONS_QUERY, variables)
        node = _graphql_repository(reply)
        if not node.get("hasDiscussionsEnabled"):
            return Discussions(items=[], enabled=False)
        conn = node.get("discussions")
        if not isinstance(conn, dict):
            # Partial data: the repository came back but its discussions
            # didn't (a token without Discussions access, a timeout).
            raise _graphql_error(reply, f"GitHub didn't list {repo}'s discussions")
        total = conn.get("totalCount") or 0
        for raw in conn.get("nodes") or []:
            if isinstance(raw, dict):
                found.append(_parse_discussion(raw, repo))
        page = conn.get("pageInfo") if isinstance(conn.get("pageInfo"), dict) else {}
        more = bool(page.get("hasNextPage"))
        after = page.get("endCursor")
        if not more or not after:
            break
    return Discussions(items=found[:limit], more=more, total=total)


_DISCUSSION_COMMENTS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $after: String, $replies: Int!) {
  repository(owner: $owner, name: $name) {
    discussion(number: $number) {
      comments(first: 100, after: $after) {
        totalCount
        pageInfo { hasNextPage endCursor }
        nodes {
          author { login } body createdAt url isAnswer upvoteCount isMinimized
          replies(first: $replies) {
            totalCount
            nodes { author { login } body createdAt url isAnswer upvoteCount isMinimized }
          }
        }
      }
    }
  }
}"""


def _parse_discussion_comment(node: dict) -> DiscussionComment:
    replies = node.get("replies") if isinstance(node.get("replies"), dict) else {}
    parsed = [_parse_discussion_comment(r) for r in replies.get("nodes") or []
              if isinstance(r, dict)]
    return DiscussionComment(
        author=_login_of(node.get("author")),
        body=node.get("body") or "",
        created_at=node.get("createdAt") or "",
        url=node.get("url") or "",
        is_answer=bool(node.get("isAnswer")),
        upvotes=node.get("upvoteCount") or 0,
        minimized=bool(node.get("isMinimized")),
        replies=parsed,
        reply_count=max(replies.get("totalCount") or 0, len(parsed)),
    )


def fetch_discussion_comments(repo: str, number: int) -> tuple[list[DiscussionComment], bool]:
    """A discussion's comments, oldest first, each with its replies, and
    whether there were more than ``DISCUSSION_COMMENT_PAGES`` pages of them."""
    owner, _, name = repo.partition("/")
    comments: list[DiscussionComment] = []
    after = None
    for _ in range(DISCUSSION_COMMENT_PAGES):
        variables = {"owner": owner, "name": name, "number": number, "after": after,
                     "replies": DISCUSSION_REPLIES}
        reply = _graphql(_DISCUSSION_COMMENTS_QUERY, variables)
        node = _graphql_repository(reply)
        discussion = node.get("discussion")
        if not isinstance(discussion, dict):
            raise _graphql_error(reply, f"Discussion #{number} wasn't found in {repo}")
        conn = discussion.get("comments")
        if not isinstance(conn, dict):
            raise _graphql_error(reply, f"GitHub didn't give discussion #{number}'s comments")
        comments.extend(_parse_discussion_comment(c) for c in conn.get("nodes") or []
                        if isinstance(c, dict))
        page = conn.get("pageInfo") if isinstance(conn.get("pageInfo"), dict) else {}
        after = page.get("endCursor")
        if not page.get("hasNextPage") or not after:
            return comments, False
    return comments, True


_DISCUSSION_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    discussion(number: $number) { %s }
  }
}""" % _DISCUSSION_FIELDS


def fetch_discussion(repo: str, number: int) -> Discussion:
    """One discussion by number, for one that isn't in the list (closed, or
    not among the most recently active)."""
    owner, _, name = repo.partition("/")
    reply = _graphql(_DISCUSSION_QUERY, {"owner": owner, "name": name, "number": number})
    node = _graphql_repository(reply).get("discussion")
    if not isinstance(node, dict):
        raise _graphql_error(reply, f"Discussion #{number} wasn't found in {repo}")
    return _parse_discussion(node, repo)


_ADD_DISCUSSION_COMMENT = """
mutation($id: ID!, $body: String!) {
  addDiscussionComment(input: {discussionId: $id, body: $body}) {
    comment { url }
  }
}"""


def add_discussion_comment(discussion: Discussion, body: str) -> str:
    """Comment on ``discussion``; the new comment's address."""
    if not discussion.node_id:
        raise GhError(f"Discussion #{discussion.number} can't be commented on from here")
    reply = _graphql(_ADD_DISCUSSION_COMMENT, {"id": discussion.node_id, "body": body})
    data = reply.get("data") if isinstance(reply.get("data"), dict) else {}
    added = data.get("addDiscussionComment")
    if not isinstance(added, dict):
        raise _graphql_error(reply, "GitHub didn't take the comment")
    comment = added.get("comment") if isinstance(added.get("comment"), dict) else {}
    return comment.get("url") or ""


# ── Milestones ─────────────────────────────────────────────────────────
#
# REST repos/{o}/{r}/milestones?state=. Enter on one lists its issues and
# pull requests in Issues & PRs (fetch_issues / fetch_prs ``milestone``).

MILESTONE_COLUMNS = ["title", "due", "open", "closed", "done", "state", "description",
                     "updated"]
MILESTONE_DEFAULT_COLUMNS = ["title", "due", "open", "closed", "done", "state"]


@dataclass
class Milestone:
    """A repository milestone and how far along it is."""

    number: int
    title: str
    state: str = "open"      # "open" or "closed"
    description: str = ""
    due_on: str = ""
    open_issues: int = 0     # issues and pull requests, as GitHub counts them
    closed_issues: int = 0
    created_at: str = ""
    updated_at: str = ""
    closed_at: str = ""
    creator: str = ""
    url: str = ""
    repo: str = ""

    @property
    def total(self) -> int:
        return self.open_issues + self.closed_issues

    @property
    def percent_done(self) -> Optional[int]:
        """Closed as a whole percent of all, rounded down as GitHub shows it;
        None with nothing in it."""
        if not self.total:
            return None
        return self.closed_issues * 100 // self.total

    @property
    def done_display(self) -> str:
        pct = self.percent_done
        return "" if pct is None else f"{pct}%"

    @property
    def state_display(self) -> str:
        return self.state.capitalize()

    def to_row(self, columns: list[str]) -> dict[str, str]:
        mapping = {
            "title": self.title,
            "due": self.due_on[:10] if self.due_on else "",
            "open": str(self.open_issues),
            "closed": str(self.closed_issues),
            "done": self.done_display,
            "state": self.state_display,
            "description": _first_line_of(self.description),
            "updated": self.updated_at[:10] if self.updated_at else "",
        }
        return {col: mapping.get(col, "") for col in columns}


def _first_line_of(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def _parse_milestone(row: dict, repo: str) -> Milestone:
    creator = row.get("creator") if isinstance(row.get("creator"), dict) else {}
    return Milestone(
        number=row.get("number") or 0,
        title=row.get("title") or "",
        state=row.get("state") or "open",
        description=row.get("description") or "",
        due_on=row.get("due_on") or "",
        open_issues=row.get("open_issues") or 0,
        closed_issues=row.get("closed_issues") or 0,
        created_at=row.get("created_at") or "",
        updated_at=row.get("updated_at") or "",
        closed_at=row.get("closed_at") or "",
        creator=creator.get("login") or "",
        url=row.get("html_url") or "",
        repo=repo,
    )


def fetch_milestones(repo: Optional[str], state: str = "open",
                     limit: int = 100) -> list[Milestone]:
    """A repository's milestones in GitHub's order, the nearest due date
    first (those with none last). ``state`` is View > State.

    Like labels, a fork's are its upstream's, to match the issues listed.
    """
    effective = resolve_issue_repo(repo) or repo
    if state not in ("open", "closed", "all"):
        state = "open"
    rows = _api_pages(f"repos/{effective}/milestones?state={state}", limit)
    return [_parse_milestone(r, effective) for r in rows]


# ── Insights: traffic and contributors (#89) ───────────────────────────

INSIGHT_COLUMNS = ["section", "name", "count", "uniques"]
INSIGHT_DEFAULT_COLUMNS = ["section", "name", "count", "uniques"]

# What each section counts: (the count, the unique count), as said in a row.
INSIGHT_NOUNS = {
    "Views": ("view", "views", "unique visitor", "unique visitors"),
    "Clones": ("clone", "clones", "unique cloner", "unique cloners"),
    "Referrer": ("view", "views", "unique visitor", "unique visitors"),
    "Page": ("view", "views", "unique visitor", "unique visitors"),
    "Contributor": ("commit", "commits", "", ""),
}
# Contributors asked again while GitHub is still counting them (HTTP 202).
CONTRIBUTOR_RETRIES = 2
CONTRIBUTOR_WAIT = 2.0


def _counted(n: int, one: str, many: str) -> str:
    return f"{n:,} {one if n == 1 else many}"


@dataclass
class InsightRow:
    """One row of Insights: a total, a day, a referring site, a popular
    page or a contributor. ``section`` says which; the count cells say what
    they count ("1,234 views"), so a row reads on its own."""

    section: str             # Views, Clones, Referrer, Page, Contributor
    name: str                # "Last 14 days", "2026-10-27", "github.com", a page, a login
    count: int = 0
    uniques: Optional[int] = None  # None where there is no such count (contributors)
    url: str = ""
    detail: str = ""         # a page's path; a day's or total's period
    repo: str = ""

    @property
    def count_display(self) -> str:
        one, many, _, _ = INSIGHT_NOUNS.get(self.section, ("", "", "", ""))
        return _counted(self.count, one, many)

    @property
    def uniques_display(self) -> str:
        if self.uniques is None:
            return ""
        _, _, one, many = INSIGHT_NOUNS.get(self.section, ("", "", "", ""))
        return _counted(self.uniques, one, many)

    def to_row(self, columns: list[str]) -> dict[str, str]:
        mapping = {
            "section": self.section,
            "name": self.name,
            "count": self.count_display,
            "uniques": self.uniques_display,
        }
        return {col: mapping.get(col, "") for col in columns}


@dataclass
class Insights:
    """What Insights could read. ``traffic_error``: why there is no traffic
    ("" when there is); ``contributors_error`` likewise, with
    ``contributors_pending`` when GitHub was still counting."""

    rows: list[InsightRow] = field(default_factory=list)
    traffic_error: str = ""
    contributors_error: str = ""
    contributors_pending: bool = False

    def section(self, name: str) -> list[InsightRow]:
        return [r for r in self.rows if r.section == name]


def traffic_sentence(exc: GhError, repo: str) -> str:
    """Why there is no traffic, in a sentence."""
    text = str(exc)
    if "push access" in text.lower():
        return (f"Traffic needs push access to {repo}, which you don't have, "
                "so only contributors are shown.")
    return f"Couldn't read the traffic: {text}"


def _traffic_rows(repo: str, kind: str, data: dict) -> list[InsightRow]:
    """The total and each day of ``views`` or ``clones``, newest day first."""
    section = "Views" if kind == "views" else "Clones"
    page = f"https://github.com/{repo}/graphs/traffic"
    days = [d for d in data.get(kind) or [] if isinstance(d, dict)]
    first = days[0].get("timestamp", "")[:10] if days else ""
    last = days[-1].get("timestamp", "")[:10] if days else ""
    period = f"{first} to {last}" if first and last and first != last else first
    rows = [InsightRow(section, "Last 14 days", int(data.get("count") or 0),
                       int(data.get("uniques") or 0), page, period, repo)]
    for d in reversed(days):
        rows.append(InsightRow(section, (d.get("timestamp") or "")[:10],
                               int(d.get("count") or 0), int(d.get("uniques") or 0),
                               page, "", repo))
    return rows


def _fetch_traffic(repo: str) -> list[InsightRow]:
    """Views, clones, referrers and popular pages, read side by side."""
    endpoints = {
        "views": f"repos/{repo}/traffic/views",
        "clones": f"repos/{repo}/traffic/clones",
        "referrers": f"repos/{repo}/traffic/popular/referrers",
        "paths": f"repos/{repo}/traffic/popular/paths",
    }
    with ThreadPoolExecutor(max_workers=len(endpoints)) as pool:
        futures = {k: pool.submit(_api_json, [e], None) for k, e in endpoints.items()}
        got = {k: f.result() for k, f in futures.items()}  # the first failure raises
    page = f"https://github.com/{repo}/graphs/traffic"
    rows: list[InsightRow] = []
    for kind in ("views", "clones"):
        data = got[kind] if isinstance(got[kind], dict) else {}
        rows += _traffic_rows(repo, kind, data)
    for r in got["referrers"] if isinstance(got["referrers"], list) else []:
        if isinstance(r, dict):
            rows.append(InsightRow("Referrer", r.get("referrer") or "", int(r.get("count") or 0),
                                   int(r.get("uniques") or 0), page, "", repo))
    for p in got["paths"] if isinstance(got["paths"], list) else []:
        if isinstance(p, dict):
            path = p.get("path") or ""
            rows.append(InsightRow("Page", p.get("title") or path, int(p.get("count") or 0),
                                   int(p.get("uniques") or 0),
                                   f"https://github.com{path}" if path else page, path, repo))
    return rows


def _fetch_contributors(repo: str, limit: int) -> Optional[list[InsightRow]]:
    """Contributors with their commits on the default branch, most first;
    None while GitHub is still counting them (it answers 202 with no list)."""
    per_page = max(1, min(limit, 100))
    out: list[InsightRow] = []
    page = 1
    while len(out) < limit:
        raw = _run_gh(["api", f"repos/{repo}/contributors?per_page={per_page}&page={page}"])
        rows = json.loads(raw) if raw.strip() else []
        if not isinstance(rows, list):
            return None if page == 1 else out  # still counting
        for r in rows:
            if isinstance(r, dict) and r.get("login"):
                out.append(InsightRow("Contributor", r["login"],
                                      int(r.get("contributions") or 0), None,
                                      r.get("html_url") or f"https://github.com/{r['login']}",
                                      "", repo))
        if len(rows) < per_page:
            break
        page += 1
    return out[:limit]


def fetch_insights(repo: str, limit: int = 100) -> Insights:
    """Insights: the last 14 days' traffic (views, clones, referring sites,
    popular pages), which needs push access, and up to ``limit``
    contributors. Each part fails on its own and says why."""
    result = Insights()
    with ThreadPoolExecutor(max_workers=2) as pool:
        traffic = pool.submit(_fetch_traffic, repo)
        contributors = pool.submit(_contributors_with_retry, repo, limit)
        try:
            result.rows = traffic.result()
        except GhError as exc:
            result.traffic_error = traffic_sentence(exc, repo)
        try:
            people = contributors.result()
        except GhError as exc:
            people = []
            text = str(exc)
            if "too large" in text.lower():
                result.contributors_error = (
                    "GitHub won't list the contributors of a repository this large.")
            else:
                result.contributors_error = f"Couldn't read the contributors: {text}"
    if people is None:
        result.contributors_pending = True
        people = []
    result.rows += people
    return result


def _contributors_with_retry(repo: str, limit: int) -> Optional[list[InsightRow]]:
    for attempt in range(CONTRIBUTOR_RETRIES + 1):
        people = _fetch_contributors(repo, limit)
        if people is not None:
            return people
        if attempt < CONTRIBUTOR_RETRIES:
            time.sleep(CONTRIBUTOR_WAIT)
    return None
