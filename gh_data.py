"""Data layer for ghviewer — shells out to the `gh` CLI for all operations."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
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
            "+/-": f"+{self.additions}/-{self.deletions}" if self.is_pr else "",
            "files": str(self.changed_files) if self.is_pr else "",
            "base": self.base_branch if self.is_pr else "",
            "head": self.head_branch if self.is_pr else "",
            "repo": self.repo,
            "why": self.why,
        }
        return {col: mapping.get(col, "") for col in columns}

    def to_accessible_string(self, columns: list[str]) -> str:
        """Return a screen-reader-friendly string with field names included."""
        row = self.to_row(columns)
        parts = [f"{col}: {val}" for col, val in row.items() if val]
        return ", ".join(parts)


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
                base_branch=row.get("baseRefName", ""),
                head_branch=row.get("headRefName", ""),
            )
        )
    return items


def fetch_issues(
    repo: Optional[str], state: str = "open", limit: int = 30, label: str = ""
) -> list[Item]:
    """Fetch issues (excluding PRs) for the repo.

    ``gh issue list`` defaults to only 30 items and returns newest first.
    Pass ``limit`` to control how many are fetched.

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
    if effective:
        args += ["--repo", effective]
    return _parse_issues(_run_gh(args))


def fetch_prs(
    repo: Optional[str], state: str = "open", limit: int = 30, label: str = ""
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
    if effective:
        args += ["--repo", effective]
    return _parse_prs(_run_gh(args))


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

    def to_accessible_string(self, columns: list[str]) -> str:
        row = self.to_row(columns)
        parts = [f"{col}: {val}" for col, val in row.items() if val]
        return ", ".join(parts)


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


@dataclass
class OrgEntry:
    """An organization you belong to, as an entry in the repository list."""

    login: str
    admin: bool = False               # you can administer it
    repo_count: Optional[int] = None  # the repositories in it you can see


@dataclass
class RepoListing:
    """What the repository list is built from."""

    repos: list[dict]                 # your own, most recently pushed first
    orgs: list[OrgEntry] = field(default_factory=list)
    # How many repositories others have shared with you, outside your
    # organizations; None when there were too many to count in one page.
    shared: Optional[int] = 0


def list_repos(limit: int = 100) -> RepoListing:
    """Your own repositories, your organizations, and what is shared with you.

    One GraphQL query for all three, so the list waits no longer than it did
    for your repositories alone. Not `gh repo list`, which can't say which
    organizations you are in.

    An organization's repositories aren't mixed in with yours: someone in a
    big organization (W3C has over a thousand) would find their own repos
    lost among them. Each organization becomes an entry of its own instead,
    with its count, and its repositories are fetched when it is opened.

    Shared counts the repositories you are a collaborator on, less those in
    your organizations: you stay a collaborator on a repo you move into an
    organization, and it is already under that organization's entry.
    """
    first = max(1, min(limit, 100))
    own_part = (
        "own: repositories(first: %d, ownerAffiliations: [OWNER], "
        "orderBy: {field: PUSHED_AT, direction: DESC}) "
        "{ nodes { nameWithOwner description pushedAt } } " % first
    )
    extras = (
        "shared: repositories(first: 100, ownerAffiliations: [COLLABORATOR]) "
        "{ nodes { owner { login } } } "
        "organizations(first: 100) "
        "{ nodes { login viewerCanAdminister repositories { totalCount } } } "
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
    orgs: list[OrgEntry] = []
    # An organization that blocks gh's access leaves a null in its place.
    for node in (viewer.get("organizations") or {}).get("nodes") or []:
        if not node or not node.get("login"):
            continue
        count = (node.get("repositories") or {}).get("totalCount")
        orgs.append(OrgEntry(node["login"], bool(node.get("viewerCanAdminister")),
                             count if isinstance(count, int) else None))
    # The ones you run first, then by name.
    orgs.sort(key=lambda o: (not o.admin, o.login.lower()))
    shared_nodes = (viewer.get("shared") or {}).get("nodes")
    if shared_nodes is None:
        shared = 0  # couldn't be had; the entry is left out rather than wrong
    else:
        mine = {o.login.lower() for o in orgs}
        shared = sum(1 for n in shared_nodes
                     if n and ((n.get("owner") or {}).get("login") or "").lower() not in mine)
        # A full page with some outside your organizations may have more
        # after it, so no count. A full page of only your organizations'
        # (someone added to a hundred of W3C's) is taken to have none: an
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

    def to_accessible_string(self, columns: list[str]) -> str:
        row = self.to_row(columns)
        return ", ".join(f"{col}: {val}" for col, val in row.items() if val)


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

    def to_accessible_string(self, columns: list[str]) -> str:
        row = self.to_row(columns)
        parts = [f"{col}: {val}" for col, val in row.items() if val]
        return ", ".join(parts)


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

    def to_row(self, columns: list[str]) -> dict[str, str]:
        mapping = {
            "sha": self.short_sha,
            # First line only: a commit fetched on its own carries its whole
            # message, and a row should not read the body out.
            "message": (self.message.splitlines() or [""])[0][:80],
            "author": self.author,
            "date": self.date[:10] if self.date else "",
            "files": str(self.files_changed) if self.files_changed else "",
            "+/-": f"+{self.additions}/-{self.deletions}" if self.additions or self.deletions else "",
        }
        return {col: mapping.get(col, "") for col in columns}

    def to_accessible_string(self, columns: list[str]) -> str:
        row = self.to_row(columns)
        parts = [f"{col}: {val}" for col, val in row.items() if val]
        return ", ".join(parts)


COMMIT_COLUMNS = ["sha", "message", "author", "date", "files", "+/-"]
COMMIT_DEFAULT_COLUMNS = ["sha", "message", "author", "date"]


def fetch_commits(repo: Optional[str], branch: str = "", limit: int = 100) -> list[Commit]:
    """Fetch commits for the repo (optionally for a specific branch)."""
    endpoint = "repos/{owner}/{repo}/commits"
    if branch:
        endpoint += f"?sha={branch}"
    endpoint += f"&per_page={limit}" if branch else f"?per_page={limit}"
    rows = _api_json([endpoint, "-q",
                      f"[.[] | {{sha, message: .commit.message, author: .commit.author.name, date: .commit.author.date, url: .html_url}}]"],
                     repo)
    if not isinstance(rows, list):
        return []
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
        ))
    return commits


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

    def to_accessible_string(self, columns: list[str]) -> str:
        row = self.to_row(columns)
        parts = [f"{col}: {val}" for col, val in row.items() if val]
        return ", ".join(parts)


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

    def to_accessible_string(self, columns: list[str]) -> str:
        row = self.to_row(columns)
        parts = [f"{col}: {val}" for col, val in row.items() if val]
        return ", ".join(parts)


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

    def to_accessible_string(self, columns: list[str]) -> str:
        row = self.to_row(columns)
        parts = [f"{col}: {val}" for col, val in row.items() if val]
        return ", ".join(parts)


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

    def to_accessible_string(self, columns: list[str]) -> str:
        row = self.to_row(columns)
        parts = [f"{col}: {val}" for col, val in row.items() if val]
        return ", ".join(parts)


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

    def to_accessible_string(self, columns: list[str]) -> str:
        row = self.to_row(columns)
        parts = [f"{col}: {val}" for col, val in row.items() if val]
        return ", ".join(parts)


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

    def to_accessible_string(self, columns: list[str]) -> str:
        row = self.to_row(columns)
        parts = [f"{col}: {val}" for col, val in row.items() if val]
        return ", ".join(parts)


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

    def to_accessible_string(self, columns: list[str]) -> str:
        row = self.to_row(columns)
        parts = [f"{col}: {val}" for col, val in row.items() if val]
        return ", ".join(parts)


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

    def to_accessible_string(self, columns: list[str]) -> str:
        row = self.to_row(columns)
        parts = [f"{col}: {val}" for col, val in row.items() if val]
        return ", ".join(parts)


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

    def to_accessible_string(self, columns: list[str]) -> str:
        row = self.to_row(columns)
        return ", ".join(f"{col}: {val}" for col, val in row.items() if val)


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


def _graphql(query: str) -> dict:
    """Run a GraphQL query and return the reply, partial or not.

    Not `_run_gh`: when part of a query can't be resolved (a deleted PR, a
    repo you can no longer read), gh prints the data it *did* get and still
    exits 1, and `_run_gh` would throw that data away. The query also goes in
    on stdin rather than the command line, so its length is never a problem.
    """
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            [_find_gh(), "api", "graphql", "--input", "-"],
            input=json.dumps({"query": query}),
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

    def to_accessible_string(self, columns: list[str]) -> str:
        row = self.to_row(columns)
        return ", ".join(f"{col}: {val}" for col, val in row.items() if val)


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

    def to_accessible_string(self, columns: list[str]) -> str:
        row = self.to_row(columns)
        return ", ".join(f"{col}: {val}" for col, val in row.items() if val)


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


