#!/usr/bin/env python3
"""ghviewer — a wxPython GUI for browsing and managing GitHub issues & PRs.

Requires the `gh` CLI (https://cli.github.com/) and wxPython.
"""

from __future__ import annotations

import argparse
import re
import sys
import threading
import unicodedata
import webbrowser
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import unquote, urlsplit

import wx

import updater
from version import __version__ as APP_VERSION
from pinned_repos import add_pinned, load_pinned, remove_pinned
from favorites import FavoriteEntry, load_favorites, save_favorites, is_favorite, toggle_favorite
from saved_searches import (
    KIND_ISSUES, KIND_REPOS, SavedSearch, add_saved_search, load_saved_searches,
    remove_saved_search,
)

from gh_data import (
    ACTIVITY_COLUMNS,
    ACTIVITY_DEFAULT_COLUMNS,
    ACTIVITY_MAX,
    ALL_COLUMNS,
    ActivityEvent,
    NOTIFICATION_COLUMNS,
    NOTIFICATION_DEFAULT_COLUMNS,
    Notification,
    REPO_COLUMNS,
    REPO_DEFAULT_COLUMNS,
    RepoEntry,
    BRANCH_COLUMNS,
    BRANCH_DEFAULT_COLUMNS,
    COMMIT_COLUMNS,
    COMMIT_DEFAULT_COLUMNS,
    DEFAULT_COLUMNS,
    GhError,
    Item,
    LABEL_COLUMNS,
    LABEL_DEFAULT_COLUMNS,
    RELEASE_COLUMNS,
    RELEASE_DEFAULT_COLUMNS,
    SORT_ORDERS,
    TAG_COLUMNS,
    TAG_DEFAULT_COLUMNS,
    WORKFLOW_COLUMNS,
    WORKFLOW_DEFAULT_COLUMNS,
    WORKFLOW_DEF_COLUMNS,
    WORKFLOW_DEF_DEFAULT_COLUMNS,
    ARTIFACT_COLUMNS,
    ARTIFACT_DEFAULT_COLUMNS,
    ASSET_COLUMNS,
    ASSET_DEFAULT_COLUMNS,
    PAGES_COLUMNS,
    PAGES_DEFAULT_COLUMNS,
    PAGEFILE_COLUMNS,
    PAGEFILE_DEFAULT_COLUMNS,
    Artifact,
    Branch,
    Commit,
    Label,
    PagesBuild,
    PagesFile,
    PagesSite,
    Release,
    ReleaseAsset,
    Tag,
    Workflow,
    WorkflowRun,
    CompareResult,
    DispatchSpec,
    WorkflowInput,
    add_comment,
    close_item,
    IssueCreatedUnreadable,
    MERGE_METHODS,
    allowed_merge_methods,
    fetch_pr_checks,
    merge_pr,
    request_reviewers,
    review_pr,
    set_pr_ready,
    update_pr_branch,
    JOB_COLUMNS,
    JOB_DEFAULT_COLUMNS,
    WorkflowJob,
    cancel_workflow_run,
    fetch_failed_log,
    fetch_job_annotations,
    fetch_job_log,
    fetch_run_jobs,
    fetch_workflow_run,
    rerun_workflow_run,
    MY_WORK_COLUMNS,
    MY_WORK_DEFAULT_COLUMNS,
    SEARCH_ITEM_COLUMNS,
    SEARCH_ITEM_DEFAULT_COLUMNS,
    SEARCH_MAX,
    fetch_my_work,
    search_issues,
    search_repos,
    MissingScope,
    WATCH_ALL,
    WATCH_IGNORE,
    WATCH_PARTICIPATING,
    get_watch_level,
    list_accounts,
    set_watch_level,
    switch_account,
    create_issue,
    create_label,
    detect_repo,
    delete_label,
    delete_workflow_run,
    dispatch_workflow,
    download_artifact,
    fetch_branches,
    fetch_dispatch_spec,
    fetch_run_artifacts,
    fetch_compare,
    fetch_commits,
    fetch_commit_detail,
    fetch_issues,
    fetch_item_by_number,
    fetch_labels,
    fetch_pages_builds,
    fetch_pages_files,
    fetch_pages_site,
    fetch_prs,
    fetch_release_assets,
    fetch_releases,
    fetch_tags,
    total_downloads,
    fetch_workflow_runs,
    fetch_workflows,
    fetch_activity,
    fetch_notifications,
    count_unread_notifications,
    mark_all_notifications_read,
    mark_notification_done,
    mark_notification_read,
    release_page,
    unsubscribe_notification,
    list_repos,
    count_starred_repos,
    count_watched_repos,
    fetch_starred_repos,
    fetch_watched_repos,
    fetch_org_repos,
    fetch_orgs,
    fetch_shared_repos,
    OrgEntry,
    RepoListing,
    ORG_COLUMNS,
    ORG_DEFAULT_COLUMNS,
    open_in_browser,
    parent_repo,
    reopen_item,
    sort_items,
)


# ── Helpers ───────────────────────────────────────────────────────────


def _parse_repo_spec(value: str) -> str | None:
    """Parse a GitHub repo URL or OWNER/NAME into normalized OWNER/NAME.

    Accepts:
      - https://github.com/owner/name
      - https://github.com/owner/name.git
      - git@github.com:owner/name.git
      - owner/name
    Returns None if the input can't be parsed.
    """
    v = value.strip()
    if not v:
        return None
    # SSH form: git@github.com:owner/name.git
    if v.startswith("git@github.com:"):
        v = v[len("git@github.com:"):]
    # HTTPS form: strip scheme + host
    elif "github.com/" in v:
        v = v.split("github.com/", 1)[1]
    # Strip trailing .git
    if v.endswith(".git"):
        v = v[:-4]
    # Strip trailing slash or extra path (e.g. /issues, /pull/123)
    v = v.split("/", 2)
    if len(v) < 2 or not v[0] or not v[1]:
        return None
    owner, name = v[0], v[1].split("?", 1)[0].split("#", 1)[0]
    if not owner or not name:
        return None
    return f"{owner}/{name}"


@dataclass
class GitHubTarget:
    """Where a GitHub address points, in GHManage's terms.

    ``kind`` is one of:
      repo     the repository itself
      inside   a page in the repository GHManage has no view for (a file,
               the wiki, a discussion); it opens the repository
      item     an issue or pull request; ``ref`` is its number
      commit   a commit; ``ref`` is its SHA (possibly abbreviated)
      release  a release; ``ref`` is its tag
      run      a workflow run; ``ref`` is its id
      branch   a branch; ``ref`` is its name
      view     one of the repo's lists; ``ref`` is the view mode
      user     a person or organisation, not a repository; ``repo`` is empty
    """

    repo: str
    kind: str = "repo"
    ref: str = ""


# Repo sub-pages that map onto a whole view rather than one thing in it.
_URL_VIEWS = {
    "issues": "issues",
    "pulls": "issues",
    "branches": "branches",
    "commits": "commits",
    "tags": "tags",
    "releases": "releases",
    "actions": "workflow",
    "labels": "labels",
}

# github.com pages that are not OWNER/NAME, though they look like it.
_SITE_PAGES = {
    "about", "account", "advisories", "apps", "codespaces", "collections",
    "copilot", "dashboard", "enterprise", "enterprises", "explore", "features",
    "login", "logout", "marketplace", "new", "notifications", "organizations",
    "pricing", "pulls", "issues", "search", "security", "settings", "signup",
    "sponsors", "stars", "topics", "trending",
}

_GITHUB_HOSTS = ("github.com", "www.github.com")
# Underscores appear in Enterprise Managed User logins (name_shortcode).
_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_-]{0,38})$")
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{4,40}$")
# Pasted from email, chat or Markdown, an address arrives wrapped or followed
# by punctuation that is not part of it.
_WRAPPERS = "<>()[]{}\"'`"
_TRAILING = ".,;:!?"


def _clean_address(value: str) -> str:
    # Zero-width and other invisible format characters come along with
    # text copied out of rich editors and web pages.
    v = "".join(ch for ch in value if unicodedata.category(ch) != "Cf").strip()
    for _ in range(3):
        v = v.strip(_WRAPPERS).rstrip(_TRAILING).strip()
    return v


_URL_IN_TEXT = re.compile(r"https?://(?:www\.)?github\.com/[^\s<>\"'`]+", re.IGNORECASE)


def first_github_url(text: str) -> str:
    """The first github.com address in ``text`` that GHManage can open, or ""."""
    for match in _URL_IN_TEXT.finditer(text[:10000]):
        url = _clean_address(match.group(0))
        if parse_github_url(url):
            return url
    return ""


def parse_github_url(value: str) -> GitHubTarget | None:
    """Work out what a github.com address, or OWNER/NAME, points at.

    Addresses on other hosts (GitHub Enterprise, gists, raw files, the API)
    are not read: GHManage works with github.com through gh.
    """
    v = _clean_address(value)
    if not v:
        return None
    if v.lower().startswith("git@github.com:"):
        repo = _parse_repo_spec(v)
        return GitHubTarget(repo) if repo else None
    if "://" in v or v.lower().startswith(("github.com/", "www.github.com/")):
        if "://" not in v:
            v = "https://" + v
        parts_url = urlsplit(v)
        if parts_url.scheme.lower() not in ("http", "https"):
            return None
        if (parts_url.hostname or "").lower() not in _GITHUB_HOSTS:
            return None
        is_url = True
        path = parts_url.path
    elif "@" in v or ":" in v:
        return None
    else:
        is_url = False
        path = v.split("#", 1)[0].split("?", 1)[0]
    parts = [unquote(p) for p in path.split("/") if p]
    if not parts:
        return None
    if is_url and parts[0].lower() in ("orgs", "users") and len(parts) > 1:
        return GitHubTarget("", "user", parts[1])
    if is_url and parts[0].lower() in _SITE_PAGES:
        return None
    if len(parts) == 1:
        # github.com/someone is a profile. A bare word is not an address.
        if is_url and _OWNER_RE.match(parts[0]):
            return GitHubTarget("", "user", parts[0])
        return None
    owner, name = parts[0], parts[1]
    if name.endswith(".git"):
        name = name[:-4]
    if not _OWNER_RE.match(owner) or not _NAME_RE.match(name) or name in (".", ".."):
        return None
    repo = f"{owner}/{name}"
    rest = parts[2:]
    if not rest:
        return GitHubTarget(repo)
    section = rest[0]
    arg = rest[1] if len(rest) > 1 else ""
    if section in ("issues", "pull") and arg.isdigit():
        return GitHubTarget(repo, "item", arg)
    if section == "commit" and arg:
        sha = arg
        for suffix in (".patch", ".diff"):
            if sha.endswith(suffix):
                sha = sha[: -len(suffix)]
        if _SHA_RE.match(sha):
            return GitHubTarget(repo, "commit", sha)
        return GitHubTarget(repo, "inside")
    if section == "releases" and arg == "tag" and len(rest) > 2:
        return GitHubTarget(repo, "release", "/".join(rest[2:]))
    if section == "actions" and arg == "runs" and len(rest) > 2 and rest[2].isdigit():
        return GitHubTarget(repo, "run", rest[2])
    if section == "actions" and arg == "workflows":
        return GitHubTarget(repo, "view", "workflows")
    if section in ("tree", "commits") and len(rest) == 2:
        # tree/<name> is a branch, and commits/<name> its history. With more
        # after it, it is a folder, and where a branch name ends and the path
        # begins can't be told apart.
        return GitHubTarget(repo, "branch", arg)
    if section in _URL_VIEWS and len(rest) == 1:
        return GitHubTarget(repo, "view", _URL_VIEWS[section])
    return GitHubTarget(repo, "inside")


# ── Workflow run reports ────────────────────────────────────────────────

# Lines of each failed step's log in the "what failed" report: enough to
# hold the error and what led to it, short enough to read.
FAILED_TAIL_LINES = 40
# A job log longer than this keeps only its end, where failures are.
JOB_LOG_MAX_LINES = 20000


# gh labels every line this way when it can't tell the steps of a log apart,
# which happens on some repositories; the whole job's log then comes back.
UNKNOWN_STEP = "UNKNOWN STEP"

FAILED_CONCLUSIONS = ("failure", "timed_out", "startup_failure")


def format_failure_report(run, jobs: list, annotations: dict, failed_log: list) -> str:
    """What failed in ``run``, as text to read top to bottom.

    ``annotations`` maps job id to that job's annotations; ``failed_log`` is
    fetch_failed_log's (job, step, lines).
    """
    failed = [j for j in jobs if j.conclusion in FAILED_CONCLUSIONS]
    cancelled = [j for j in jobs if j.conclusion == "cancelled"]
    head = f"Run #{run.run_number} {run.name} on {run.branch} — {run.conclusion or run.status}"
    lines = [head]
    if not jobs:
        lines.append("It failed before any job started: a problem in the workflow file, or "
                     "it is waiting for someone to approve it. The run's page on GitHub says which.")
        return "\n".join(lines)
    if not failed and not cancelled:
        lines.append("No job failed.")
        return "\n".join(lines)
    if failed:
        lines.append(f"{len(failed)} of {len(jobs)} jobs failed: {', '.join(j.name for j in failed)}.")
    if cancelled:
        names = ", ".join(j.name for j in cancelled[:10])
        more = f" and {len(cancelled) - 10} more" if len(cancelled) > 10 else ""
        lines.append(f"{len(cancelled)} cancelled, often because another job failed first: "
                     f"{names}{more}.")
    for job in failed:
        lines.append("")
        lines.append("─" * 60)
        steps = job.failed_steps
        where = f" at step \"{steps[0].name}\"" if steps else ""
        took = f" after {job.duration}" if job.duration else ""
        lines.append(f"Job {job.name} — {job.conclusion}{where}{took}")
        lines.append("─" * 60)
        flagged = [a for a in annotations.get(job.id, []) if a.level == "failure"]
        if flagged:
            lines.append("")
            lines.append("What GitHub flagged:")
            for a in flagged:
                # An annotation on ".github" points into the raw log, not a
                # file; its line number means nothing here.
                place = f"{a.path} line {a.line}: " if a.path and a.path != ".github" and a.line else ""
                title = f"{a.title}: " if a.title else ""
                lines.append(f"  {place}{title}{a.message}")
        for log_job, step, step_lines in failed_log:
            if log_job != job.name:
                continue
            kept = [ln for ln in step_lines if ln.strip()]
            tail = kept[-FAILED_TAIL_LINES:]
            if step == UNKNOWN_STEP:
                name = f"the job's log (it failed at \"{steps[0].name}\")" if steps else "the job's log"
            else:
                name = f"\"{step}\""
            lines.append("")
            lines.append(f"Last {len(tail)} lines of {name}:" if len(tail) < len(kept)
                         else f"Log of {name}:")
            lines.extend(f"  {ln}" for ln in tail)
    lines.append("")
    lines.append("The whole log of a job: J for the jobs, then Enter on one.")
    return "\n".join(lines)


def format_job_log(job, log: list) -> tuple[str, int]:
    """A job's log as text, and the line its first error is on (or 0).

    A line number rather than a character offset: text controls count in
    UTF-16 units, so an emoji earlier in the log would put an offset off.
    """
    lines = [f"Log of job {job.name} — {job.conclusion or job.status}"]
    body: list[str] = []
    for _job, step, step_lines in log:
        if step != UNKNOWN_STEP:
            body.append("")
            body.append(f"── Step: {step} ──")
        body.extend(step_lines)
    if len(body) > JOB_LOG_MAX_LINES:
        dropped = len(body) - JOB_LOG_MAX_LINES
        body = body[dropped:]
        lines.append(f"(The first {dropped:,} lines are left out; this is the end of the log.)")
    lines.extend(body)
    first_error = next((i for i, ln in enumerate(lines) if ln.startswith("ERROR: ")), 0)
    return "\n".join(lines), first_error


# ── Copy ────────────────────────────────────────────────────────────────


@dataclass
class CopyValues:
    """What the Copy commands put on the clipboard for one item.

    ``ident`` is the short thing you would type to find the item again — an
    issue number, a SHA, a tag, a branch name — and ``ident_noun`` says which,
    for the status bar. ``text`` is the visible part of the Markdown link.
    """

    link: str = ""
    title: str = ""
    ident: str = ""
    ident_noun: str = "Name"
    text: str = ""

    @property
    def spoken_noun(self) -> str:
        """The noun as the status bar says it: lower case, acronyms kept,
        so a screen reader says "S H A" and not "shah"."""
        return " ".join(w if w.isupper() else w.lower() for w in self.ident_noun.split())

    @property
    def markdown(self) -> str:
        """``[#12 Fix the thing](https://…)``, or "" when there is no link."""
        if not self.link:
            return ""
        label = (self.text or self.title or self.ident or self.link)
        # Brackets and backslashes in a title would end or break the label.
        for ch in ("\\", "[", "]"):
            label = label.replace(ch, "\\" + ch)
        return f"[{label}]({self.link})"


def _utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _first_line(text: str) -> str:
    return text.splitlines()[0].strip() if text else ""


def copy_values(item) -> CopyValues | None:
    """The Copy commands' view of ``item``, or None for an unknown kind."""
    if isinstance(item, Item):
        # Across repositories (search, My Work) a bare #208 says too little.
        number = f"{item.repo}#{item.number}" if item.repo else f"#{item.number}"
        return CopyValues(item.url, item.title, number, "Number",
                          f"{number} {item.title}")
    if isinstance(item, Branch):
        return CopyValues(item.url, item.name, item.name, "Branch Name", item.name)
    if isinstance(item, Commit):
        msg = _first_line(item.message)
        return CopyValues(item.url, msg, item.sha, "SHA",
                          f"{item.short_sha} {msg}".strip())
    if isinstance(item, Tag):
        return CopyValues(item.url, item.name, item.name, "Tag", item.name)
    if isinstance(item, Release):
        title = item.name or item.tag
        text = f"{item.tag} {item.name}" if item.name and item.name != item.tag else item.tag
        return CopyValues(item.url, title, item.tag, "Tag", text)
    if isinstance(item, ReleaseAsset):
        return CopyValues(item.url, item.name, item.name, "File Name", item.name)
    if isinstance(item, Workflow):
        return CopyValues(item.url, item.name, item.path, "File Path", item.name)
    if isinstance(item, WorkflowRun):
        return CopyValues(item.url, item.name, str(item.run_id) if item.run_id else "", "Run ID",
                          f"{item.name} #{item.run_number}")
    if isinstance(item, WorkflowJob):
        return CopyValues(item.url, item.name, str(item.id) if item.id else "", "Job ID", item.name)
    if isinstance(item, Artifact):
        # Artifacts have no page of their own on github.com.
        return CopyValues("", item.name, item.name, "Name", item.name)
    if isinstance(item, Label):
        return CopyValues(item.url, item.name, item.name, "Label Name", item.name)
    if isinstance(item, PagesBuild):
        text = f"{item.commit[:7]} {item.status}".strip()
        return CopyValues(item.url, text, item.commit, "Commit", text)
    if isinstance(item, PagesFile):
        return CopyValues(item.url, item.path, item.path, "Path", item.path)
    if isinstance(item, RepoEntry):
        return CopyValues(item.url, item.name, item.name, "Repository Name", item.name)
    if isinstance(item, OrgEntry):
        return CopyValues(item.url, item.login, item.login, "Organization Name", item.login)
    if isinstance(item, ActivityEvent):
        # What the event is about, when it is about something with an address
        # of its own — the same thing F favorites.
        if item.number:
            number = f"#{item.number}"
            text = f"{number} {item.title}".strip()
            return CopyValues(item.subject_url or item.url, item.title or item.action,
                              number, "Number", text)
        if item.subject_kind == "release" and "/releases/tag/" in item.subject_url:
            tag = item.subject_url.split("/releases/tag/", 1)[1]
            text = f"{tag} {item.title}".strip()
            return CopyValues(item.subject_url, item.title or tag, tag, "Tag", text)
        return CopyValues(item.subject_url or item.url, item.title or item.summary,
                          item.repo, "Repository Name", item.title or item.summary)
    if isinstance(item, Notification):
        if item.number:
            number = f"#{item.number}"
            return CopyValues(item.url, item.title, number, "Number",
                              f"{number} {item.title}")
        return CopyValues(item.url, item.title, item.repo, "Repository Name", item.title)
    if isinstance(item, FavoriteEntry):
        # A favorite keeps no number or SHA of its own, only how it was
        # titled, so Copy Name and Copy Title give the same thing.
        return CopyValues(item.url, item.title, item.title, "Name", item.title)
    return None


def repo_copy_values(name: str) -> CopyValues:
    """Copy values for a repository named in the repository list."""
    return CopyValues(f"https://github.com/{name}", name, name, "Repository Name", name)


# ── IDs ─────────────────────────────────────────────────────────────────

ID_REFRESH = wx.NewIdRef()
ID_CLOSE_ITEM = wx.NewIdRef()
ID_REOPEN = wx.NewIdRef()
ID_COMMENT = wx.NewIdRef()
ID_OPEN_BROWSER = wx.NewIdRef()
ID_QUICK_MODE = wx.NewIdRef()
ID_FULL_MODE = wx.NewIdRef()
ID_STATE_OPEN = wx.NewIdRef()
ID_STATE_CLOSED = wx.NewIdRef()
ID_STATE_ALL = wx.NewIdRef()
ID_TAB_ISSUES = wx.NewIdRef()
ID_TAB_PRS = wx.NewIdRef()
ID_TAB_BOTH = wx.NewIdRef()
ID_COMMENT_DLG = wx.NewIdRef()
ID_GOTO = wx.NewIdRef()
ID_NEXT_COMMENT = wx.NewIdRef()
ID_PREV_COMMENT = wx.NewIdRef()
ID_VIEW_MORE = wx.NewIdRef()
ID_VIEW_ISSUES = wx.NewIdRef()
ID_VIEW_BRANCHES = wx.NewIdRef()
ID_VIEW_COMMITS = wx.NewIdRef()
ID_VIEW_TAGS = wx.NewIdRef()
ID_VIEW_RELEASES = wx.NewIdRef()
ID_VIEW_WORKFLOWS = wx.NewIdRef()
ID_VIEW_WORKFLOW = wx.NewIdRef()
ID_VIEW_LABELS = wx.NewIdRef()
ID_VIEW_FAVORITES = wx.NewIdRef()
ID_VIEW_PAGES = wx.NewIdRef()
ID_VIEW_ACTIVITY = wx.NewIdRef()
ID_VIEW_STARRED = wx.NewIdRef()
ID_VIEW_WATCHED = wx.NewIdRef()
ID_VIEW_SHARED = wx.NewIdRef()
ID_VIEW_ORGS = wx.NewIdRef()
ID_VIEW_NOTIFICATIONS = wx.NewIdRef()
ID_MARK_READ = wx.NewIdRef()
ID_MARK_ALL_READ = wx.NewIdRef()
ID_UNSUBSCRIBE = wx.NewIdRef()
ID_SHOW_READ = wx.NewIdRef()
ID_USER_GUIDE = wx.NewIdRef()
ID_GO_TO_EVENT_REPO = wx.NewIdRef()
ID_NEW_LABEL = wx.NewIdRef()
ID_DELETE_LABEL = wx.NewIdRef()
# Actions menu. ID_DELETE_ITEM is one item that deletes whatever the current
# view can delete, so a single Ctrl+D covers labels and workflow runs alike.
ID_DELETE_ITEM = wx.NewIdRef()
ID_ACT_RUN_WORKFLOW = wx.NewIdRef()
ID_ACT_DOWNLOAD_ARTIFACT = wx.NewIdRef()
ID_OPEN_PAGES_SITE = wx.NewIdRef()
ID_FILTER = wx.NewIdRef()
ID_SELECT_BRANCH = wx.NewIdRef()
ID_COMPARE_BRANCHES = wx.NewIdRef()
ID_OPEN_REPO = wx.NewIdRef()
ID_REMOVE_REPO = wx.NewIdRef()
ID_CHECK_UPDATES = wx.NewIdRef()
ID_NEW_ISSUE = wx.NewIdRef()
ID_SWITCH_ACCOUNT = wx.NewIdRef()
ID_SEARCH = wx.NewIdRef()
# Context menus: Enter's action in the item list, and the repository list's own.
ID_CTX_OPEN = wx.NewIdRef()
ID_REPO_OPEN = wx.NewIdRef()
ID_REPO_BROWSER = wx.NewIdRef()
ID_SEARCH_REPO = wx.NewIdRef()
ID_RUN_JOBS = wx.NewIdRef()
ID_PR_CHECKS = wx.NewIdRef()
ID_PR_REVIEW = wx.NewIdRef()
ID_PR_MERGE = wx.NewIdRef()
ID_PR_DRAFT = wx.NewIdRef()
ID_PR_REVIEWERS = wx.NewIdRef()
ID_PR_UPDATE = wx.NewIdRef()
ID_RUN_FAILED = wx.NewIdRef()
ID_RUN_RERUN = wx.NewIdRef()
ID_RUN_CANCEL = wx.NewIdRef()
ID_SAVE_SEARCH = wx.NewIdRef()
ID_VIEW_MY_WORK = wx.NewIdRef()
ID_VIEW_SEARCH_RESULTS = wx.NewIdRef()
ID_WATCH_SETTINGS = wx.NewIdRef()
ID_COPY_LINK = wx.NewIdRef()
ID_COPY_MARKDOWN = wx.NewIdRef()
ID_COPY_TITLE = wx.NewIdRef()
ID_COPY_IDENT = wx.NewIdRef()
ID_COPY_DETAILS = wx.NewIdRef()


# View modes
VIEW_ISSUES = "issues"
VIEW_BRANCHES = "branches"
VIEW_COMMITS = "commits"
VIEW_TAGS = "tags"
VIEW_RELEASES = "releases"
VIEW_WORKFLOWS = "workflows"   # workflow definitions (files)
VIEW_WORKFLOW = "workflow"     # workflow runs
VIEW_ARTIFACTS = "artifacts"   # artifacts of a single workflow run (drill-down)
VIEW_JOBS = "jobs"             # jobs of a single workflow run (drill-down)
VIEW_ASSETS = "assets"         # files attached to a single release (drill-down)
VIEW_LABELS = "labels"
VIEW_FAVORITES = "favorites"
VIEW_PAGES = "pages"           # GitHub Pages: site config + publish history
VIEW_PAGEFILES = "pagefiles"   # the pages that site serves (drill-down)
VIEW_ACTIVITY = "activity"     # your GitHub activity feed (not tied to a repo)
VIEW_STARRED = "starred"       # repositories you have starred
VIEW_WATCHED = "watched"       # repositories you watch
VIEW_NOTIFICATIONS = "notifications"  # your GitHub notifications
VIEW_MY_WORK = "my_work"       # open issues and PRs that need you, everywhere
VIEW_SEARCH_ISSUES = "search_issues"  # GitHub-wide search: issues and PRs
VIEW_SEARCH_REPOS = "search_repos"    # GitHub-wide search: repositories
VIEW_ORGS = "orgs"             # the organizations you belong to
VIEW_ORG = "org"               # one organization's repositories (drill-down; which: _org)
VIEW_SHARED = "shared"         # others' repositories you are a collaborator on

# Views that are not views *of a repo*, so they work with none selected.
REPOLESS_VIEWS = (VIEW_FAVORITES, VIEW_NOTIFICATIONS, VIEW_MY_WORK, VIEW_ACTIVITY,
                  VIEW_STARRED, VIEW_WATCHED, VIEW_SEARCH_ISSUES, VIEW_SEARCH_REPOS,
                  VIEW_ORGS, VIEW_ORG, VIEW_SHARED)
# The repoless views fetched from GitHub (Favorites is read from disk).
FEED_VIEWS = (VIEW_NOTIFICATIONS, VIEW_MY_WORK, VIEW_ACTIVITY, VIEW_STARRED,
              VIEW_WATCHED, VIEW_SEARCH_ISSUES, VIEW_SEARCH_REPOS, VIEW_ORGS, VIEW_ORG,
              VIEW_SHARED)
# Views listing issues and pull requests (Items), shown with the issue
# details. Only Issues & PRs is of one repo; the issue actions (close,
# reopen, comment) belong to it alone.
ITEM_VIEWS = (VIEW_ISSUES, VIEW_MY_WORK, VIEW_SEARCH_ISSUES)
SEARCH_VIEWS = (VIEW_SEARCH_ISSUES, VIEW_SEARCH_REPOS)
# Lists across repositories where G opens the selected row's repository here.
GO_TO_REPO_VIEWS = (VIEW_ACTIVITY, VIEW_NOTIFICATIONS, VIEW_MY_WORK, VIEW_SEARCH_ISSUES,
                    VIEW_SEARCH_REPOS)
# Views listing repositories; Enter on one opens it here.
REPO_LIST_VIEWS = (VIEW_STARRED, VIEW_WATCHED, VIEW_ORG, VIEW_SHARED)

# clientData of the pseudo-entries at the top of the repository list.
FAVORITES_ENTRY = "__favorites__"
NOTIFICATIONS_ENTRY = "__notifications__"
MY_WORK_ENTRY = "__my_work__"
# A saved search in the repo list: this prefix and its name.
SEARCH_ENTRY_PREFIX = "__search__:"
ACTIVITY_ENTRY = "__activity__"
STARRED_ENTRY = "__starred__"
WATCHED_ENTRY = "__watched__"
MY_ORGS_ENTRY = "__my_orgs__"
# Shown only when someone has shared a repository with you.
SHARED_ENTRY = "__shared__"
SHARED_LABEL = "Shared With Me"

# The category entries after ★ Favorites, in order, with their labels.
CATEGORY_ENTRIES = [
    # The four from 0.8.5 keep their places, so the keystrokes people have
    # learned from the top of the list still reach them; newer ones follow.
    (ACTIVITY_ENTRY, "Activity"),
    (STARRED_ENTRY, "Starred Repositories"),
    (WATCHED_ENTRY, "Watched Repositories"),
    (NOTIFICATIONS_ENTRY, "Notifications"),
    (MY_WORK_ENTRY, "My Work"),
    (MY_ORGS_ENTRY, "My Organizations"),
]
# Which repo-list entry stands for which view, both ways.
VIEW_ENTRIES = {
    VIEW_FAVORITES: FAVORITES_ENTRY,
    VIEW_NOTIFICATIONS: NOTIFICATIONS_ENTRY,
    VIEW_MY_WORK: MY_WORK_ENTRY,
    VIEW_ACTIVITY: ACTIVITY_ENTRY,
    VIEW_STARRED: STARRED_ENTRY,
    VIEW_WATCHED: WATCHED_ENTRY,
    VIEW_SHARED: SHARED_ENTRY,
    VIEW_ORGS: MY_ORGS_ENTRY,
}
ENTRY_VIEWS = {entry: view for view, entry in VIEW_ENTRIES.items()}
# The categories whose entry carries a count, like ★ Favorites (6), and how
# to ask GitHub for it. Activity has none: it is a feed, not a set of things.
COUNTED_ENTRIES = {
    NOTIFICATIONS_ENTRY: count_unread_notifications,
    STARRED_ENTRY: count_starred_repos,
    WATCHED_ENTRY: count_watched_repos,
}

USER_GUIDE_URL = "https://theideaplace.github.io/GHManage/"

# Drill-down views: pressing Backspace in the key view returns to its parent.
# These are the views you reach by activating an item in another view
# (a branch's commits, a run's artifacts), so Backspace is a natural "up".
PARENT_VIEW = {
    VIEW_COMMITS: VIEW_BRANCHES,
    VIEW_ARTIFACTS: VIEW_WORKFLOW,
    VIEW_JOBS: VIEW_WORKFLOW,
    VIEW_ASSETS: VIEW_RELEASES,
    VIEW_PAGEFILES: VIEW_PAGES,
    VIEW_ORG: VIEW_ORGS,
}

# Columns for the favorites view (mixed item types)
FAVORITES_COLUMNS = ["type", "repo", "title", "subtitle"]
FAVORITES_DEFAULT_COLUMNS = ["type", "repo", "title", "subtitle"]

# Column defaults per view mode
VIEW_COLUMNS = {
    VIEW_ISSUES: (DEFAULT_COLUMNS, ALL_COLUMNS),
    VIEW_BRANCHES: (BRANCH_DEFAULT_COLUMNS, BRANCH_COLUMNS),
    VIEW_COMMITS: (COMMIT_DEFAULT_COLUMNS, COMMIT_COLUMNS),
    VIEW_TAGS: (TAG_DEFAULT_COLUMNS, TAG_COLUMNS),
    VIEW_RELEASES: (RELEASE_DEFAULT_COLUMNS, RELEASE_COLUMNS),
    VIEW_WORKFLOWS: (WORKFLOW_DEF_DEFAULT_COLUMNS, WORKFLOW_DEF_COLUMNS),
    VIEW_WORKFLOW: (WORKFLOW_DEFAULT_COLUMNS, WORKFLOW_COLUMNS),
    VIEW_ARTIFACTS: (ARTIFACT_DEFAULT_COLUMNS, ARTIFACT_COLUMNS),
    VIEW_JOBS: (JOB_DEFAULT_COLUMNS, JOB_COLUMNS),
    VIEW_ASSETS: (ASSET_DEFAULT_COLUMNS, ASSET_COLUMNS),
    VIEW_LABELS: (LABEL_DEFAULT_COLUMNS, LABEL_COLUMNS),
    VIEW_FAVORITES: (FAVORITES_DEFAULT_COLUMNS, FAVORITES_COLUMNS),
    VIEW_PAGES: (PAGES_DEFAULT_COLUMNS, PAGES_COLUMNS),
    VIEW_PAGEFILES: (PAGEFILE_DEFAULT_COLUMNS, PAGEFILE_COLUMNS),
    VIEW_ACTIVITY: (ACTIVITY_DEFAULT_COLUMNS, ACTIVITY_COLUMNS),
    VIEW_STARRED: (REPO_DEFAULT_COLUMNS, REPO_COLUMNS),
    VIEW_WATCHED: (REPO_DEFAULT_COLUMNS, REPO_COLUMNS),
    VIEW_NOTIFICATIONS: (NOTIFICATION_DEFAULT_COLUMNS, NOTIFICATION_COLUMNS),
    VIEW_MY_WORK: (MY_WORK_DEFAULT_COLUMNS, MY_WORK_COLUMNS),
    VIEW_SEARCH_ISSUES: (SEARCH_ITEM_DEFAULT_COLUMNS, SEARCH_ITEM_COLUMNS),
    VIEW_SEARCH_REPOS: (REPO_DEFAULT_COLUMNS, REPO_COLUMNS),
    VIEW_ORGS: (ORG_DEFAULT_COLUMNS, ORG_COLUMNS),
    VIEW_ORG: (REPO_DEFAULT_COLUMNS, REPO_COLUMNS),
    VIEW_SHARED: (REPO_DEFAULT_COLUMNS, REPO_COLUMNS),
}


def is_repo_entry(data) -> bool:
    """Whether a repo-list entry's client data names a repository, rather
    than Favorites, a category or a saved search."""
    return (
        isinstance(data, str) and bool(data) and data != FAVORITES_ENTRY
        and data not in ENTRY_VIEWS and not data.startswith(SEARCH_ENTRY_PREFIX)
    )


# ── The item list ───────────────────────────────────────────────────────
#
# On Windows wx.ListCtrl is a native list view and screen readers read it
# properly, so nothing here changes for Windows.
#
# On macOS wx.ListCtrl is *not* native. wxWidgets falls back to its generic
# custom-drawn implementation, whose backing view is a plain wxNSView that
# paints its own rows:
#
#     wx.ListBox          -> NSScrollView          (native, VoiceOver reads it)
#     wx.TextCtrl         -> wxNSTextScrollView    (native, VoiceOver reads it)
#     wx.ListCtrl         -> wxNSView              (custom-drawn, invisible)
#     wx.DataViewListCtrl -> NSScrollView          (native, VoiceOver reads it)
#
# Nothing is exposed to the accessibility layer, so VoiceOver finds no table,
# no rows and no cells — the control reads as though it is not there at all,
# which is exactly how it was reported. This is not a labelling or a focus
# problem and cannot be fixed by naming the control or changing tab order; the
# widget has to be a real NSTableView. wx.dataview.DataViewListCtrl is one.
#
# So on macOS the list is a DataViewListCtrl wearing enough of wx.ListCtrl's
# interface that the ~800 lines of calling code do not care which one they got.
IS_MAC = sys.platform == "darwin"

if IS_MAC:
    import wx.dataview

    class ItemList(wx.dataview.DataViewListCtrl):
        """A native macOS table with the slice of wx.ListCtrl's API this app uses.

        Only what ghviewer actually calls is implemented. Rows are appended in
        order by _populate_filtered_list (InsertItem for column 0, then SetItem
        for the rest), which is why InsertItem can simply append a blank row and
        let SetItem fill it in.
        """

        def __init__(self, parent, name="", **kwargs):
            super().__init__(parent, style=wx.dataview.DV_ROW_LINES | wx.BORDER_SUNKEN)
            self.SetName(name)
            self._ncols = 0

        # ── columns ──────────────────────────────────────────────────────
        def InsertColumn(self, col, heading, width=-1):
            self.AppendTextColumn(heading, width=width if width > 0 else -1)
            self._ncols = self.GetColumnCount()

        def DeleteAllColumns(self):
            self.ClearColumns()
            self._ncols = 0

        # ── rows ─────────────────────────────────────────────────────────
        def InsertItem(self, row, text):
            # Callers always append in order, so `row` is the row about to be
            # created. Guard anyway: a mismatch here would silently misalign
            # every column against its item.
            if row != self.GetItemCount():
                raise RuntimeError(
                    f"ItemList.InsertItem expects sequential appends "
                    f"(got row {row}, have {self.GetItemCount()})"
                )
            self.AppendItem([text] + [""] * max(0, self._ncols - 1))
            return row

        def SetItem(self, row, col, text):
            self.SetTextValue(text, row, col)

        # ── selection ────────────────────────────────────────────────────
        def GetFirstSelected(self):
            row = self.GetSelectedRow()
            # DataViewCtrl reports wx.NOT_FOUND as an unsigned sentinel in some
            # builds; normalise anything out of range to "nothing selected".
            if row is None or row < 0 or row >= self.GetItemCount():
                return -1
            return row

        def Select(self, idx, on=True):
            if 0 <= idx < self.GetItemCount():
                if on:
                    self.SelectRow(idx)
                else:
                    self.UnselectRow(idx)

        def Focus(self, idx):
            if 0 <= idx < self.GetItemCount():
                self.EnsureVisible(self.RowToItem(idx))

        def EnsureVisible(self, row, column=None):
            # wx.ListCtrl takes a row number; DataViewCtrl wants an item and
            # raises TypeError on an int — which it did on every list load.
            if isinstance(row, int):
                if not 0 <= row < self.GetItemCount():
                    return
                row = self.RowToItem(row)
            if column is None:
                super().EnsureVisible(row)
            else:
                super().EnsureVisible(row, column)

else:
    class ItemList(wx.ListCtrl):
        """The Windows list: plain wx.ListCtrl, unchanged."""

        def __init__(self, parent, name="", **kwargs):
            super().__init__(
                parent,
                name=name,
                style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN,
                **kwargs,
            )


# ── Status bar ──────────────────────────────────────────────────────────


class _StatusText(wx.TextCtrl):
    """A piece of status bar text that keyboard focus can land on.

    A native status bar field cannot take focus, so each one is covered by a
    borderless read-only edit showing the same text. A screen reader reads an
    edit's value when it gets focus, and the native field underneath keeps its
    text too, so the screen reader's own read-the-status-bar command still works.
    """

    def __init__(self, parent: wx.Window, name: str) -> None:
        super().__init__(parent, name=name, style=wx.TE_READONLY | wx.BORDER_NONE)
        self.SetBackgroundColour(parent.GetBackgroundColour())

    def AcceptsFocusFromKeyboard(self) -> bool:
        # F6 and the arrow keys reach the status bar; Tab does not. Tab moves
        # between the repo list, item list and details panel, as it always has.
        return False


class _StatusButton(wx.Button):
    """A status bar item that does something when pressed."""

    def __init__(self, parent: wx.Window, name: str) -> None:
        super().__init__(parent, name=name, style=wx.BU_EXACTFIT)

    def AcceptsFocusFromKeyboard(self) -> bool:
        return False  # as _StatusText: F6 and arrows, not Tab


class NavStatusBar(wx.StatusBar):
    """The frame's status bar, split into items you can arrow between.

    F6 lands on the first item; Left and Right move from item to item, wrapping
    at either end. An item with no text is removed from the bar, so the arrows
    only ever stop on something worth reading. The message item is the
    exception — it always stays, so the bar is never empty to land on.
    """

    ITEMS = ("message", "keys", "filter", "mode", "update")
    _WIDTHS = {"message": -3, "keys": -3, "filter": -1, "mode": -1, "update": -2}

    def __init__(self, parent: wx.Window, on_update: "Callable[[], None]") -> None:
        super().__init__(parent, name="status_bar")
        self._texts: dict[str, str] = dict.fromkeys(self.ITEMS, "")
        self._controls: dict[str, wx.Window] = {}
        for key in self.ITEMS:
            if key == "update":
                ctrl = _StatusButton(self, name=key)
                ctrl.Bind(wx.EVT_BUTTON, lambda event: on_update())
            else:
                ctrl = _StatusText(self, name=key)
            ctrl.Hide()
            self._controls[key] = ctrl
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self._layout()

    def set_item(self, key: str, text: str) -> None:
        """Set one item's text. Empty text takes the item off the bar."""
        if self._texts[key] == text:
            return
        appearing_or_going = bool(self._texts[key]) != bool(text)
        self._texts[key] = text
        if appearing_or_going and key != "message":
            self._layout()
            return
        index = self._visible().index(key)
        self.SetStatusText(text, index)
        self._set_control_text(key, text)

    def focus_first(self) -> None:
        self._controls[self._visible()[0]].SetFocus()

    def _visible(self) -> list[str]:
        return [k for k in self.ITEMS if k == "message" or self._texts[k]]

    def _focused_item(self) -> str | None:
        focus = wx.Window.FindFocus()
        for key, ctrl in self._controls.items():
            if focus is ctrl:
                return key
        return None

    def _set_control_text(self, key: str, text: str) -> None:
        ctrl = self._controls[key]
        if isinstance(ctrl, wx.Button):
            ctrl.SetLabel(text.replace("&", "&&"))
        else:
            ctrl.ChangeValue(text)

    def _layout(self) -> None:
        visible = self._visible()
        focused = self._focused_item()
        self.SetFieldsCount(len(visible), [self._WIDTHS[k] for k in visible])
        for index, key in enumerate(visible):
            self.SetStatusText(self._texts[key], index)
            self._set_control_text(key, self._texts[key])
        for key, ctrl in self._controls.items():
            ctrl.Show(key in visible)
        self._place_controls()
        # Don't strand focus on an item that has just left the bar.
        if focused and focused not in visible:
            self.focus_first()

    def _place_controls(self) -> None:
        for index, key in enumerate(self._visible()):
            self._controls[key].SetRect(self.GetFieldRect(index).Deflate(1, 1))

    def _on_size(self, event: wx.SizeEvent) -> None:
        self._place_controls()
        event.Skip()

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        current = self._focused_item()
        if (
            current is None
            or event.HasAnyModifiers()
            or key not in (wx.WXK_LEFT, wx.WXK_RIGHT)
        ):
            event.Skip()
            return
        visible = self._visible()
        step = 1 if key == wx.WXK_RIGHT else -1
        target = visible[(visible.index(current) + step) % len(visible)]
        self._controls[target].SetFocus()


# ── Run Workflow: inputs dialog ─────────────────────────────────────────


class WorkflowInputsDialog(wx.Dialog):
    """Collects ``workflow_dispatch`` input values before a manual run.

    Built at runtime from the schema parsed out of the workflow file, the same
    way GitHub's own "Run workflow" form is. Control per declared type:

        choice / environment → wx.Choice
        boolean              → wx.CheckBox
        number / string      → wx.TextCtrl

    Accessibility: because the form is generated rather than hand-written,
    labelling has to be done deliberately. Every control gets a wx.StaticText
    placed immediately before it in the sizer *and* a matching SetName, so the
    accessible name is right whether the screen reader takes it from the
    associated label or from the control itself. A checkbox carries its own
    label, so it gets the name only — a separate StaticText would make it read
    twice. Controls are added in declaration order, which is the tab order.
    """

    def __init__(
        self,
        parent: wx.Window,
        workflow_name: str,
        branch: str,
        inputs: list["WorkflowInput"],
    ) -> None:
        super().__init__(
            parent,
            title=f"Run {workflow_name}",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._inputs = inputs
        self._controls: dict[str, wx.Window] = {}

        outer = wx.BoxSizer(wx.VERTICAL)
        heading = wx.StaticText(self, label=f"Run '{workflow_name}' on {branch}")
        outer.Add(heading, 0, wx.ALL, 10)

        grid = wx.BoxSizer(wx.VERTICAL)
        for spec in inputs:
            label = spec.label
            if spec.required:
                label += " (required)"

            if spec.type == "boolean":
                ctrl = wx.CheckBox(self, label=label)
                ctrl.SetValue(spec.default.strip().lower() == "true")
                ctrl.SetName(label)
                grid.Add(ctrl, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
            else:
                text = wx.StaticText(self, label=label)
                grid.Add(text, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
                if spec.options:
                    ctrl = wx.Choice(self, choices=spec.options)
                    # Preselect the declared default, else the first option —
                    # never leave a Choice unset, which reads as blank.
                    idx = spec.options.index(spec.default) if spec.default in spec.options else 0
                    ctrl.SetSelection(idx)
                else:
                    ctrl = wx.TextCtrl(self, value=spec.default)
                ctrl.SetName(label)
                grid.Add(ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

            self._controls[spec.name] = ctrl

        outer.Add(grid, 1, wx.EXPAND)
        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        outer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 10)

        self.SetSizerAndFit(outer)
        self.SetMinSize((420, -1))
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        if inputs:
            self._controls[inputs[0].name].SetFocus()

    def _on_ok(self, event: wx.CommandEvent) -> None:
        """Block OK on an empty required field, naming the field at fault."""
        for spec in self._inputs:
            if not spec.required:
                continue
            ctrl = self._controls[spec.name]
            if isinstance(ctrl, wx.TextCtrl) and not ctrl.GetValue().strip():
                wx.MessageBox(
                    f"{spec.label} is required.",
                    "Run Workflow",
                    wx.OK | wx.ICON_INFORMATION,
                    self,
                )
                ctrl.SetFocus()
                return
        event.Skip()

    def values(self) -> dict[str, str]:
        """The collected inputs, as the strings the dispatch payload wants."""
        out: dict[str, str] = {}
        for spec in self._inputs:
            ctrl = self._controls[spec.name]
            if isinstance(ctrl, wx.CheckBox):
                out[spec.name] = "true" if ctrl.GetValue() else "false"
            elif isinstance(ctrl, wx.Choice):
                out[spec.name] = ctrl.GetStringSelection()
            else:
                out[spec.name] = ctrl.GetValue().strip()
        return out


# ── New label dialog ────────────────────────────────────────────────────


class NewLabelDialog(wx.Dialog):
    """Collects the name, description, and colour for a new label.

    Same labelling discipline as WorkflowInputsDialog: every field gets a
    StaticText immediately before it *and* a matching SetName, so the
    accessible name is right whichever the screen reader picks up. Tab order
    is declaration order: name, description, colour.

    Colour is optional — GitHub picks one when it is left blank, which is the
    fastest path and the reason the field comes last.
    """

    def __init__(self, parent: wx.Window, repo: str) -> None:
        super().__init__(
            parent,
            title="New Label",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(
            wx.StaticText(self, label=f"Create a label in {repo}"),
            0, wx.ALL, 10,
        )

        fields = wx.BoxSizer(wx.VERTICAL)

        def add_field(label: str, hint: str = "") -> wx.TextCtrl:
            text = wx.StaticText(self, label=label)
            fields.Add(text, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
            ctrl = wx.TextCtrl(self)
            ctrl.SetName(label)
            if hint:
                ctrl.SetHint(hint)
            fields.Add(ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
            return ctrl

        self.name_ctrl = add_field("Name (required)")
        self.desc_ctrl = add_field("Description")
        self.color_ctrl = add_field(
            "Colour, 6-digit hex (optional — GitHub picks one if blank)",
            "e.g. d73a4a",
        )

        outer.Add(fields, 1, wx.EXPAND)
        outer.Add(
            self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL),
            0, wx.ALIGN_RIGHT | wx.ALL, 10,
        )
        self.SetSizerAndFit(outer)
        self.SetMinSize((460, -1))
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self.name_ctrl.SetFocus()

    def _on_ok(self, event: wx.CommandEvent) -> None:
        """Validate before closing so `gh` never fails on something we can see."""
        if not self.name_ctrl.GetValue().strip():
            wx.MessageBox(
                "A label needs a name.", "New Label",
                wx.OK | wx.ICON_INFORMATION, self,
            )
            self.name_ctrl.SetFocus()
            return
        color = self.color_ctrl.GetValue().strip().lstrip("#")
        if color and (len(color) != 6 or any(c not in "0123456789abcdefABCDEF" for c in color)):
            wx.MessageBox(
                f"'{color}' is not a colour. Give 6 hex digits, such as d73a4a, "
                "or leave the field blank to let GitHub choose.",
                "New Label",
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            self.color_ctrl.SetFocus()
            return
        event.Skip()

    def values(self) -> tuple[str, str, str]:
        """(name, colour, description) — colour without its leading #."""
        return (
            self.name_ctrl.GetValue().strip(),
            self.color_ctrl.GetValue().strip().lstrip("#"),
            self.desc_ctrl.GetValue().strip(),
        )


# ── Search dialog ───────────────────────────────────────────────────────


class SearchDialog(wx.Dialog):
    """What to search GitHub for, and how.

    The query is GitHub's own search syntax, passed through untouched, so
    every qualifier github.com accepts works here. Labelled as the other
    dialogs: a StaticText before each control and a matching SetName.
    """

    KINDS = [(KIND_ISSUES, "Issues and pull requests"), (KIND_REPOS, "Repositories")]

    def __init__(self, parent: wx.Window, kind: str = KIND_ISSUES, query: str = "",
                 select: bool = True) -> None:
        super().__init__(parent, title="Search GitHub",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        outer = wx.BoxSizer(wx.VERTICAL)

        label = "&Search for"
        outer.Add(wx.StaticText(self, label=label), 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.kind_ctrl = wx.Choice(self, choices=[name for _, name in self.KINDS])
        self.kind_ctrl.SetName(label.replace("&", ""))
        keys = [k for k, _ in self.KINDS]
        self.kind_ctrl.SetSelection(keys.index(kind) if kind in keys else 0)
        outer.Add(self.kind_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # The example is in the label itself, so a screen reader says it as
        # it lands on the field; the longer help below is for reading on.
        label = "&Query, with GitHub's qualifiers, such as is:open label:bug author:@me"
        outer.Add(wx.StaticText(self, label=label), 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.query_ctrl = wx.TextCtrl(self, value=query)
        self.query_ctrl.SetName(label.replace("&", ""))
        self.query_ctrl.SetHint("is:open label:bug repo:owner/name")
        outer.Add(self.query_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        help_text = (
            "Words and GitHub's qualifiers, for example:\n"
            "  is:open is:issue label:bug repo:nvaccess/nvda\n"
            "  author:@me  review-requested:@me  updated:>2026-01-01\n"
            "  screen reader language:python stars:>50   (repositories)"
        )
        outer.Add(wx.StaticText(self, label=help_text), 0, wx.ALL, 10)
        outer.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        self.SetSizerAndFit(outer)
        self.SetMinSize((520, -1))
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        wx.CallAfter(self.query_ctrl.SetFocus)
        # The last search, selected so typing replaces it; or a start such as
        # "repo:owner/name ", with the cursor after it to go on typing.
        wx.CallAfter(self.query_ctrl.SelectAll if select else self.query_ctrl.SetInsertionPointEnd)

    def _on_ok(self, event: wx.CommandEvent) -> None:
        if self.query_ctrl.GetValue().strip():
            event.Skip()
            return
        wx.MessageBox("Type something to search for.", "Search GitHub",
                      wx.OK | wx.ICON_INFORMATION, self)
        self.query_ctrl.SetFocus()

    def values(self) -> tuple[str, str]:
        return self.KINDS[self.kind_ctrl.GetSelection()][0], self.query_ctrl.GetValue().strip()


# ── Pull request dialogs ────────────────────────────────────────────────


class ReviewDialog(wx.Dialog):
    """Approve, request changes, or comment, with an optional message.

    Labelled as the other dialogs. Ctrl+Enter submits from the message, as
    in New Issue, and Enter in it starts a new line.
    """

    KINDS = [("approve", "Approve"), ("request-changes", "Request changes"),
             ("comment", "Comment")]

    def __init__(self, parent: wx.Window, pr_label: str) -> None:
        super().__init__(parent, title="Review Pull Request",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER, size=(560, 420))
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(wx.StaticText(self, label=f"Review {pr_label}"), 0, wx.ALL, 10)
        self.kind_ctrl = wx.RadioBox(self, label="Your review",
                                     choices=[name for _, name in self.KINDS],
                                     majorDimension=1, style=wx.RA_SPECIFY_COLS)
        outer.Add(self.kind_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        label = "&Message (Markdown; needed to request changes or comment)"
        outer.Add(wx.StaticText(self, label=label), 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.body_ctrl = wx.TextCtrl(self, style=wx.TE_MULTILINE)
        self.body_ctrl.SetName(label.replace("&", ""))
        outer.Add(self.body_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        outer.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        ok = self.FindWindow(wx.ID_OK)
        if ok:
            ok.SetLabel("&Submit Review")
        self.SetSizer(outer)
        submit = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self._on_submit, id=submit)
        self.SetAcceleratorTable(wx.AcceleratorTable([
            (wx.ACCEL_CTRL, wx.WXK_RETURN, submit), (wx.ACCEL_CTRL, wx.WXK_NUMPAD_ENTER, submit),
        ]))
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        wx.CallAfter(self.kind_ctrl.SetFocus)

    def _valid(self) -> bool:
        kind, body = self.values()
        if kind != "approve" and not body:
            wx.MessageBox("Requesting changes or commenting needs a message.",
                          "Review Pull Request", wx.OK | wx.ICON_INFORMATION, self)
            self.body_ctrl.SetFocus()
            return False
        return True

    def _on_submit(self, event) -> None:
        if self._valid():
            self.EndModal(wx.ID_OK)

    def _on_ok(self, event) -> None:
        if self._valid():
            event.Skip()

    def values(self) -> tuple[str, str]:
        return self.KINDS[self.kind_ctrl.GetSelection()][0], self.body_ctrl.GetValue().strip()


class MergeDialog(wx.Dialog):
    """How to merge a pull request, offering only what the repository allows."""

    def __init__(self, parent: wx.Window, pr_label: str, methods: list[str]) -> None:
        super().__init__(parent, title="Merge Pull Request", style=wx.DEFAULT_DIALOG_STYLE)
        self._methods = methods
        names = dict(MERGE_METHODS)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(wx.StaticText(self, label=f"Merge {pr_label}"), 0, wx.ALL, 10)
        self.method_ctrl = wx.RadioBox(self, label="Merge method", choices=[names[m] for m in methods],
                                       majorDimension=1, style=wx.RA_SPECIFY_COLS)
        outer.Add(self.method_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        self.delete_ctrl = wx.CheckBox(self, label="&Delete the branch afterwards")
        outer.Add(self.delete_ctrl, 0, wx.ALL, 10)
        outer.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        ok = self.FindWindow(wx.ID_OK)
        if ok:
            ok.SetLabel("&Merge")
        self.SetSizerAndFit(outer)
        self.SetMinSize((420, -1))
        wx.CallAfter(self.method_ctrl.SetFocus)

    def values(self) -> tuple[str, bool]:
        return self._methods[self.method_ctrl.GetSelection()], self.delete_ctrl.GetValue()


def format_checks(pr_label: str, checks: list) -> str:
    """A pull request's checks as text: a count, then each, failures first."""
    words = {"fail": "failed", "cancel": "cancelled", "pending": "running",
             "pass": "passed", "skipping": "skipped"}
    counts: dict[str, int] = {}
    for c in checks:
        counts[c.bucket] = counts.get(c.bucket, 0) + 1
    order = ["fail", "cancel", "pending", "pass", "skipping"]
    summary = ", ".join(f"{counts[b]} {words[b]}" for b in order if b in counts)
    lines = [f"Checks for {pr_label}", summary or "No checks have run.", ""]
    for c in checks:
        where = f"{c.workflow} / {c.name}" if c.workflow else c.name
        lines.append(f"{words.get(c.bucket, c.state.lower())}: {where}")
        if c.description:
            lines.append(f"    {c.description}")
        if c.link:
            lines.append(f"    {c.link}")
    if counts.get("fail"):
        lines += ["", "For a failed workflow, Workflow Runs (Ctrl+7) and L on its run "
                      "shows what failed."]
    return "\n".join(lines)


# ── New issue dialog ────────────────────────────────────────────────────


class NewIssueDialog(wx.Dialog):
    """Title and body for a new issue.

    Same labelling discipline as the other dialogs: a StaticText before each
    field and a matching SetName. The body is plain multi-line text, written
    in Markdown as on github.com. In it Enter starts a new line, so Ctrl+Enter
    (Cmd+Enter on a Mac) creates the issue from anywhere in the dialog; Tab
    still moves between the fields. Enter in the title moves to the body.
    """

    def __init__(self, parent: wx.Window, repo: str, title: str = "", body: str = "") -> None:
        super().__init__(
            parent,
            title="New Issue",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            size=(620, 480),
        )
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(wx.StaticText(self, label=f"Create an issue in {repo}"), 0, wx.ALL, 10)

        # The & marks Alt+T and Alt+D on Windows; the accessible name is the
        # label without it.
        label = "&Title (required)"
        outer.Add(wx.StaticText(self, label=label), 0, wx.LEFT | wx.RIGHT, 10)
        # Enter in the title goes on to the description, as a person filling
        # in the form expects, rather than filing an issue with no body.
        self.title_ctrl = wx.TextCtrl(self, value=title, style=wx.TE_PROCESS_ENTER)
        self.title_ctrl.SetName(label.replace("&", ""))
        self.title_ctrl.Bind(wx.EVT_TEXT_ENTER, lambda e: self.body_ctrl.SetFocus())
        outer.Add(self.title_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        label = "&Description (Markdown, optional)"
        outer.Add(wx.StaticText(self, label=label), 0, wx.LEFT | wx.RIGHT, 10)
        self.body_ctrl = wx.TextCtrl(self, value=body, style=wx.TE_MULTILINE)
        self.body_ctrl.SetName(label.replace("&", ""))
        outer.Add(self.body_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        ok = self.FindWindow(wx.ID_OK)
        if ok:
            # Not "&Create": the stock Cancel button already has Alt+C.
            ok.SetLabel("C&reate Issue")
        outer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        self.SetSizer(outer)
        self.SetMinSize((420, 320))

        submit = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self._on_submit, id=submit)
        self.SetAcceleratorTable(wx.AcceleratorTable([
            (wx.ACCEL_CTRL, wx.WXK_RETURN, submit),
            (wx.ACCEL_CTRL, wx.WXK_NUMPAD_ENTER, submit),
        ]))
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        # After the dialog is up: focus set during construction can be lost
        # to the dialog's own default-button handling on some platforms.
        wx.CallAfter(self.title_ctrl.SetFocus)
        wx.CallAfter(self.title_ctrl.SetInsertionPointEnd)

    def _on_submit(self, event: wx.CommandEvent) -> None:
        if self._valid():
            self.EndModal(wx.ID_OK)

    def _on_ok(self, event: wx.CommandEvent) -> None:
        if self._valid():
            event.Skip()

    def _valid(self) -> bool:
        if self.title_ctrl.GetValue().strip():
            return True
        wx.MessageBox("An issue needs a title.", "New Issue",
                      wx.OK | wx.ICON_INFORMATION, self)
        self.title_ctrl.SetFocus()
        return False

    def values(self) -> tuple[str, str]:
        """(title, body). The body is kept as typed, apart from trailing space."""
        return self.title_ctrl.GetValue().strip(), self.body_ctrl.GetValue().rstrip()


# ── Main frame ──────────────────────────────────────────────────────────


class GhViewerFrame(wx.Frame):
    """Main application window."""

    def __init__(
        self,
        repo: str | None = None,
        update_service: "updater.UpdateService | None" = None,
    ) -> None:
        super().__init__(
            None,
            title="ghviewer — GitHub Issues & PRs",
            size=(1000, 700),
        )
        self.updater = update_service
        self._pending_update: tuple[str, str] | None = None  # (version, notes url)
        self.repo: str | None = None
        self.items: list[Item] = []
        self._all_repos: list[dict] = []
        self._pinned_repos: list[str] = load_pinned()
        self.favorites: list[FavoriteEntry] = load_favorites()

        # View settings
        self.columns: list[str] = list(DEFAULT_COLUMNS)
        self.sort_order: str = SORT_ORDERS[0]
        self.list_mode: str = "quick"  # "quick" or "full"
        self.state_filter: str = "open"  # "open", "closed", "all"
        self.tab_filter: str = "both"  # "issues", "prs", "both"
        self.page_size: int = 100      # how many items to fetch per page
        self.current_limit: int = 100  # current fetch limit (grows via View More)
        self.view_mode: str = VIEW_ISSUES  # current view: issues, branches, commits, etc.
        self.git_items: list = []   # holds Branch/Commit/Tag/Release/WorkflowRun objects
        self.commit_branch: str = ""  # branch for commits view ("" = default branch)
        self.artifacts_run: WorkflowRun | None = None  # run whose artifacts are shown
        self.jobs_run: WorkflowRun | None = None  # run whose jobs are shown
        self.assets_release: Release | None = None  # release whose assets are shown
        # Pages config for the current repo. Shared by both Pages views — the
        # published-file list is derived from it — so it survives the move
        # between them and is cleared on the way out to anything else.
        self.pages_site: PagesSite | None = None
        self.filter_text: str = ""  # quick filter text (Ctrl+F, empty = no filter)
        # Every list fetch carries a token. Results whose token is no longer the
        # current one are dropped, because by then they belong to a view or a
        # repo the user has already left. See `_begin_fetch`.
        self._fetch_token: int = 0
        # Label the Issues view is restricted to ("" = no restriction). Set by
        # pressing Enter on a label; unlike the quick filter this is applied by
        # `gh`, so it reaches issues past the current page.
        self.label_filter: str = ""
        # Whether GitHub has older activity than the Activity view has loaded;
        # None while a load is under way and the answer isn't known yet.
        self._activity_more: bool | None = False
        # Notifications: whether read ones are listed too, and whether GitHub
        # has more than are loaded (None while a load is under way).
        self._include_read: bool = False
        self._notif_more: bool | None = False
        # What the list on screen was loaded with, and when: Backspace back to
        # it reloads if Include Read changed meanwhile, and Mark All Read marks
        # only what had arrived by then.
        self._notif_loaded_include: bool = False
        self._notif_loaded_at: str = ""
        # Row to put the cursor on when the feed load about to start lands
        # (View More lands you on the first new row, not back at the top).
        # Handed to that one load in _load_items and reset there, so a load
        # that is superseded or fails can't leave it for a later one.
        self._pending_focus_row = 0  # a row, or for Notifications the ids already shown
        # The list you were in when you opened a repository from it — G on an
        # activity event, Enter on a starred or watched repo — so Backspace
        # brings you back to the same item without fetching the list again:
        # (view, items, more, item, limit).
        self._return_to: tuple | None = None
        # Something to select once the view now loading arrives — set when a
        # GitHub address names one thing in a list (an issue, a release, a
        # run): (fetch token, view, kind, ref). Bound to the load it was set
        # for, so it can only ever land on that load; see _take_pending_row.
        self._pending_target: tuple[int, str, str, str] | None = None
        # Unsent new-issue text per repo, (title, body): kept when the dialog
        # is cancelled or creating fails, so nothing typed is lost.
        self._issue_drafts: dict[str, tuple[str, str]] = {}
        # True from Ctrl+N until the issue exists or the form is abandoned, so
        # a second Ctrl+N can't open the same draft and file it twice.
        self._issue_busy: bool = False
        # Bumped on every account switch. Work started as one account checks
        # it when it lands, so a late reply can't touch the next account's
        # counts or lists.
        self._account_gen: int = 0
        # The search on screen, or last run: (kind, query), and how many
        # GitHub said match.
        self._search: tuple[str, str] | None = None
        self._search_total: int = 0
        self.saved_searches: list[SavedSearch] = load_saved_searches()
        # The items in the list control, in row order. With a quick filter on
        # this is a subset of the view's items, and row N is _shown[N], not
        # items[N] — everything that turns a row into an item goes through it.
        self._shown: list = []
        # Repo list loads, like item loads, carry a token so that a slow one
        # can't overwrite a newer one. See _load_repos.
        self._repo_token: int = 0
        self._repos_loaded_once: bool = False
        # How many repositories each counted category holds, once known.
        self._category_counts: dict[str, int] = {}
        # The organizations you belong to, for My Organizations, and the one
        # whose repositories are showing.
        self._orgs: list = []
        self._org: str = ""
        # Whether the Shared With Me entry is in the repo list.
        self._show_shared: bool = False

        self._build_ui()
        self._bind_events()
        self._build_menu()
        self._update_menu_checks()

        if repo:
            self._select_repo(repo)
        # The list on the left loads either way; with --repo it then keeps
        # that repository selected (see _restore_repo_selection).
        self._load_repos()

        self.Show()

        # Check for updates in the background so startup is never blocked.
        # Must come after Show(): a modal raised against an unshown frame
        # returns immediately instead of waiting for the user.
        if self.updater:
            wx.CallLater(2000, self._start_update_check)

    # ── UI construction ─────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Main splitter: repo list (left) | issues+details (right)
        self.main_splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE, name="main_splitter")
        self.main_splitter.SetMinimumPaneSize(200)

        # Left panel: repo list
        repo_panel = wx.Panel(self.main_splitter, name="repo_panel")
        repo_sizer = wx.BoxSizer(wx.VERTICAL)
        repo_sizer.Add(
            wx.StaticText(repo_panel, label="Repositories"),
            flag=wx.LEFT | wx.TOP, border=3,
        )
        self.repo_list = wx.ListBox(
            repo_panel,
            name="repo_list",
            style=wx.LB_SINGLE | wx.BORDER_SUNKEN,
        )
        repo_sizer.Add(self.repo_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=3)
        repo_panel.SetSizer(repo_sizer)

        # Right panel: issue list (top) + details (bottom)
        right_panel = wx.Panel(self.main_splitter, name="right_panel")
        right_sizer = wx.BoxSizer(wx.VERTICAL)

        self.splitter = wx.SplitterWindow(right_panel, style=wx.SP_LIVE_UPDATE)
        self.splitter.SetMinimumPaneSize(120)

        # List panel
        #
        # See ItemList: on macOS this is a native table, on Windows the same
        # wx.ListCtrl as always.
        #
        # The label is not decoration. This list was the one control in the
        # window without a wx.StaticText before it, and its name was
        # "item_list" — an identifier, not something anyone would want read
        # aloud. Under VoiceOver that combination gives the table no accessible
        # name at all, so tabbing onto it announces essentially nothing and it
        # reads as though the list is not there. The repo list and the details
        # box were always reachable precisely because they carry a label; this
        # follows the same convention the generated dialogs above document —
        # a StaticText immediately before the control *and* a matching SetName,
        # so the name is right whether the screen reader takes it from the
        # associated label or from the control itself.
        #
        # Both are refreshed by _update_list_label() when the view changes, so
        # the list is announced as "Issues", "Branches", "Releases" and so on
        # rather than something generic.
        list_panel = wx.Panel(self.splitter, name="list_panel")
        list_sizer = wx.BoxSizer(wx.VERTICAL)
        self.list_label = wx.StaticText(list_panel, label="Issues")
        list_sizer.Add(self.list_label, flag=wx.LEFT | wx.TOP, border=3)
        self.list_ctrl = ItemList(list_panel, name="Issues")
        list_sizer.Add(self.list_ctrl, proportion=1, flag=wx.EXPAND | wx.ALL, border=3)
        list_panel.SetSizer(list_sizer)

        # Details panel
        details_panel = wx.Panel(self.splitter, name="details_panel")
        details_sizer = wx.BoxSizer(wx.VERTICAL)
        self.details_text = wx.TextCtrl(
            details_panel,
            name="details_text",
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH | wx.TE_WORDWRAP | wx.WANTS_CHARS,
        )
        self._comment_positions: list[tuple[int, int]] = []  # (line, length) per comment
        self._current_comment: int = -1
        details_sizer.Add(
            wx.StaticText(details_panel, label="Details"),
            flag=wx.LEFT | wx.TOP, border=3,
        )
        details_sizer.Add(self.details_text, proportion=1, flag=wx.EXPAND | wx.ALL, border=3)
        details_panel.SetSizer(details_sizer)

        self.splitter.SplitHorizontally(list_panel, details_panel, 400)
        self.splitter.SetSashPosition(400)

        right_sizer.Add(self.splitter, proportion=1, flag=wx.EXPAND)
        right_panel.SetSizer(right_sizer)

        self.main_splitter.SplitVertically(repo_panel, right_panel, 300)
        self.main_splitter.SetSashPosition(300)

        # Status bar — part of the F6 loop, see NavStatusBar
        self.status_bar = NavStatusBar(self, on_update=self._on_update_item)
        self.SetStatusBar(self.status_bar)
        # Menu help text would be written to the native field alone, out of
        # step with the focusable item covering it.
        self.SetStatusBarPane(-1)
        self._announce("Ready")
        self._update_mode_status()

        # Layout
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.main_splitter, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)
        self.SetSizer(sizer)

        # Initial columns
        self._rebuild_columns()

    def _rebuild_columns(self) -> None:
        """Rebuild the ListCtrl columns from self.columns."""
        self.list_ctrl.DeleteAllItems()
        self.list_ctrl.DeleteAllColumns()
        widths = {
            # Issues/PRs
            "number": 60, "type": 60, "state": 70, "title": 400,
            "author": 120, "created": 100, "updated": 100, "labels": 150,
            "assignees": 120, "comments": 70, "draft": 50, "review": 100,
            "+/-": 90, "files": 50, "base": 100, "head": 100,
            # Branches
            "branch": 150, "last commit": 400, "date": 100, "protected": 70,
            "ahead": 60, "behind": 60,
            # Commits
            "sha": 80, "message": 400,
            # Tags
            "tag": 150, "commit": 80,
            # Releases
            "tag": 100, "name": 250, "draft": 50, "prerelease": 70,
            # Workflow (runs + definitions) + artifacts
            "name": 150, "status": 100, "result": 100, "event": 100, "#": 50,
            "state": 90, "path": 320, "size": 90, "expired": 70,
            # Labels
            "label": 180, "description": 340, "color": 80, "default": 70,
            # Favorites
            "repo": 180, "subtitle": 250,
        }
        if self.view_mode == VIEW_ACTIVITY:
            # Same column names as other views, different contents: the date
            # carries a time, and the title shares the row with an action.
            widths.update({"actor": 130, "action": 240, "title": 300, "date": 130})
        elif self.view_mode == VIEW_NOTIFICATIONS:
            widths.update({"status": 70, "reason": 130, "type": 80, "title": 420,
                           "repo": 220, "updated": 130})
        elif self.view_mode in (VIEW_MY_WORK, VIEW_SEARCH_ISSUES):
            widths.update({"why": 130, "repo": 200, "title": 380})
        elif self.view_mode == VIEW_ORGS:
            widths.update({"organization": 240, "role": 100, "repositories": 110})
        elif self.view_mode in REPO_LIST_VIEWS or self.view_mode == VIEW_SEARCH_REPOS:
            widths.update({"repo": 240, "description": 380, "language": 100,
                           "stars": 80, "pushed": 100, "owner": 140})
        for i, col in enumerate(self.columns):
            self.list_ctrl.InsertColumn(i, col, width=widths.get(col, 100))

    # ── Menu ────────────────────────────────────────────────────────────

    def _build_menu(self) -> None:
        menu_bar = wx.MenuBar()

        # File menu — the repository and the list itself
        file_menu = wx.Menu()
        file_menu.Append(ID_OPEN_REPO, "Open Repository or Address…\tCtrl+Shift+O")
        file_menu.Append(ID_REMOVE_REPO, "Remove from List…")
        file_menu.AppendSeparator()
        file_menu.Append(ID_SWITCH_ACCOUNT, "Switch GitHub Account…\tCtrl+Shift+K")
        file_menu.AppendSeparator()
        file_menu.Append(ID_REFRESH, "Refresh\tCtrl+R")
        file_menu.Append(ID_VIEW_MORE, "View More\tCtrl++")
        file_menu.AppendSeparator()
        file_menu.Append(ID_SEARCH, "Search GitHub…\tCtrl+Shift+F")
        file_menu.Append(ID_GOTO, "Go To Issue…\tCtrl+G")
        file_menu.Append(ID_FILTER, "Quick Filter…\tCtrl+F")
        file_menu.AppendSeparator()
        file_menu.Append(ID_NEXT_COMMENT, "Next Comment\tAlt+N")
        file_menu.Append(ID_PREV_COMMENT, "Previous Comment\tAlt+P")
        file_menu.AppendSeparator()
        file_menu.Append(wx.ID_EXIT, "Quit\tCtrl+Q")
        menu_bar.Append(file_menu, "File")

        # Actions menu — everything that acts on what the list is showing.
        # One home for them, whichever view they belong to. Items are re-labelled
        # and enabled per view in `_update_actions_menu`, so the menu is a
        # reliable answer to "what can I do here?" rather than a list to sift.
        actions_menu = wx.Menu()
        actions_menu.Append(ID_OPEN_BROWSER, "Open in Browser\tCtrl+O")
        # Copy acts on the item in the list, or on the repository when the
        # repository list has focus. The fourth entry is renamed per view for
        # what it copies there: Copy Number, Copy SHA, Copy Tag…
        copy_menu = wx.Menu()
        self._act_copy_link = copy_menu.Append(ID_COPY_LINK, "Copy Link\tCtrl+Shift+C")
        self._act_copy_markdown = copy_menu.Append(
            ID_COPY_MARKDOWN, "Copy Markdown Link\tCtrl+Shift+L"
        )
        copy_menu.Append(ID_COPY_TITLE, "Copy Title\tCtrl+Shift+T")
        self._act_copy_ident = copy_menu.Append(ID_COPY_IDENT, "Copy Number\tCtrl+Shift+I")
        copy_menu.Append(ID_COPY_DETAILS, "Copy Details\tCtrl+Shift+D")
        actions_menu.AppendSubMenu(copy_menu, "Copy")
        actions_menu.AppendSeparator()
        self._act_close = actions_menu.Append(ID_CLOSE_ITEM, "Close Issue/PR\tCtrl+W")
        self._act_reopen = actions_menu.Append(ID_REOPEN, "Reopen Issue/PR\tCtrl+Shift+W")
        self._act_comment = actions_menu.Append(ID_COMMENT, "Add Comment…\tCtrl+M")
        self._act_new_issue = actions_menu.Append(ID_NEW_ISSUE, "New Issue…\tCtrl+N")
        # Pull requests. K, V and D are the keys in the issues list.
        pr_menu = wx.Menu()
        pr_menu.Append(ID_PR_CHECKS, "&Checks (K)")
        pr_menu.Append(ID_PR_REVIEW, "Re&view… (V)")
        pr_menu.Append(ID_PR_MERGE, "&Merge…")
        pr_menu.Append(ID_PR_DRAFT, "Ready for Review or Back to &Draft (D)")
        pr_menu.Append(ID_PR_REVIEWERS, "Request &Reviewers…")
        pr_menu.Append(ID_PR_UPDATE, "&Update Branch…")
        self._act_pr = actions_menu.AppendSubMenu(pr_menu, "&Pull Request")
        self._act_search_repo = actions_menu.Append(
            ID_SEARCH_REPO, "Search This Repository…\tCtrl+Shift+S")
        self._act_watch = actions_menu.Append(ID_WATCH_SETTINGS, "Watch Settings…\tCtrl+Shift+U")
        self._act_save_search = actions_menu.Append(ID_SAVE_SEARCH, "Save Search…\tCtrl+S")
        actions_menu.AppendSeparator()
        # Ctrl+I and Ctrl+D are safe as accelerators; a bare Delete accelerator
        # would not be, since it would swallow the Delete key inside the list.
        # The bare Insert and Delete keys are handled in `on_char_hook`.
        self._act_new = actions_menu.Append(ID_NEW_LABEL, "New Label…\tCtrl+I")
        self._act_delete = actions_menu.Append(ID_DELETE_ITEM, "Delete\tCtrl+D")
        actions_menu.AppendSeparator()
        self._act_run_workflow = actions_menu.Append(
            ID_ACT_RUN_WORKFLOW, "Run Workflow on Branch…"
        )
        self._act_download = actions_menu.Append(
            ID_ACT_DOWNLOAD_ARTIFACT, "Download Artifact…"
        )
        # Workflow runs. J, L, E and X are the keys in the list.
        self._act_run_jobs = actions_menu.Append(ID_RUN_JOBS, "Show Jobs (J)")
        self._act_run_failed = actions_menu.Append(ID_RUN_FAILED, "Show What Failed (L)")
        self._act_run_rerun = actions_menu.Append(ID_RUN_RERUN, "Rerun… (E)")
        self._act_run_cancel = actions_menu.Append(ID_RUN_CANCEL, "Cancel Run… (X)")
        self._act_open_site = actions_menu.Append(
            ID_OPEN_PAGES_SITE, "Open Published Site"
        )
        actions_menu.AppendSeparator()
        self._act_select_branch = actions_menu.Append(
            ID_SELECT_BRANCH, "Select Branch…\tCtrl+B"
        )
        self._act_compare = actions_menu.Append(
            ID_COMPARE_BRANCHES, "Compare Branches…\tCtrl+Shift+B"
        )
        actions_menu.AppendSeparator()
        # G in Activity and Notifications; here so the command can be found.
        self._act_go_to_repo = actions_menu.Append(
            ID_GO_TO_EVENT_REPO, "Go to Event's Repository\tCtrl+Shift+G"
        )
        actions_menu.AppendSeparator()
        # Notifications. M, U and Delete are the keys in the list; the
        # menu has no accelerators for them, as bare letters can't be.
        self._act_mark_read = actions_menu.Append(ID_MARK_READ, "Mark as Read (M)")
        self._act_unsubscribe = actions_menu.Append(
            ID_UNSUBSCRIBE, "Unsubscribe from Thread (U)"
        )
        self._act_mark_all_read = actions_menu.Append(ID_MARK_ALL_READ, "Mark All as Read…")
        menu_bar.Append(actions_menu, "Actions")
        self._actions_menu = actions_menu

        # View menu
        view_menu = wx.Menu()

        # View Mode submenu — switch between Issues/PRs and Git views.
        # Ctrl+1..Ctrl+0 jump straight to a view; the numbers follow the order
        # of this menu, so the shortcut is readable off the menu itself.
        # Pages goes on the end rather than beside the other repo views, and
        # takes Ctrl+0 as the tenth: inserting it in the middle would renumber
        # every shortcut below it and break the ones already in people's hands.
        show_menu = wx.Menu()
        show_menu.AppendRadioItem(ID_VIEW_ISSUES, "Issues & PRs\tCtrl+1")
        show_menu.AppendRadioItem(ID_VIEW_BRANCHES, "Branches\tCtrl+2")
        show_menu.AppendRadioItem(ID_VIEW_COMMITS, "Commits\tCtrl+3")
        show_menu.AppendRadioItem(ID_VIEW_TAGS, "Tags\tCtrl+4")
        show_menu.AppendRadioItem(ID_VIEW_RELEASES, "Releases\tCtrl+5")
        show_menu.AppendRadioItem(ID_VIEW_WORKFLOWS, "Workflows\tCtrl+6")
        show_menu.AppendRadioItem(ID_VIEW_WORKFLOW, "Workflow Runs\tCtrl+7")
        show_menu.AppendRadioItem(ID_VIEW_LABELS, "Labels\tCtrl+8")
        show_menu.AppendRadioItem(ID_VIEW_FAVORITES, "★ Favorites\tCtrl+9")
        show_menu.AppendRadioItem(ID_VIEW_PAGES, "GitHub Pages\tCtrl+0")
        show_menu.AppendRadioItem(ID_VIEW_NOTIFICATIONS, "Notifications\tCtrl+Shift+N")
        show_menu.AppendRadioItem(ID_VIEW_MY_WORK, "My Work\tCtrl+Shift+M")
        # Checked while search results are showing; choosing it asks for a
        # search, as File ▸ Search GitHub does.
        show_menu.AppendRadioItem(ID_VIEW_SEARCH_RESULTS, "Search Results…")
        show_menu.AppendRadioItem(ID_VIEW_ACTIVITY, "Activity\tCtrl+Shift+A")
        show_menu.AppendRadioItem(ID_VIEW_STARRED, "Starred Repositories")
        show_menu.AppendRadioItem(ID_VIEW_WATCHED, "Watched Repositories")
        show_menu.AppendRadioItem(ID_VIEW_SHARED, "Shared With Me")
        # Checked too while one organization's repositories are showing.
        show_menu.AppendRadioItem(ID_VIEW_ORGS, "My Organizations")
        view_menu.AppendSubMenu(show_menu, "View Mode")

        view_menu.AppendSeparator()

        # List mode submenu
        mode_menu = wx.Menu()
        mode_menu.AppendRadioItem(ID_QUICK_MODE, "Quick Mode (compact)")
        mode_menu.AppendRadioItem(ID_FULL_MODE, "Full Mode (field names for screen reader)")
        view_menu.AppendSubMenu(mode_menu, "List Mode")

        view_menu.AppendSeparator()

        # Sort order submenu
        sort_menu = wx.Menu()
        self._sort_menu_items = {}
        for i, order in enumerate(SORT_ORDERS):
            item_id = wx.NewIdRef()
            self._sort_menu_items[item_id] = order
            sort_menu.AppendRadioItem(item_id, order)
            self.Bind(wx.EVT_MENU, self.on_sort_selected, id=item_id)
        view_menu.AppendSubMenu(sort_menu, "Sort Order")

        view_menu.AppendSeparator()

        # Columns submenu (rebuilt when view mode changes)
        self._col_menu = wx.Menu()
        self._col_menu_items = {}
        self._rebuild_columns_menu()
        view_menu.AppendSubMenu(self._col_menu, "Columns")

        view_menu.AppendSeparator()

        # State filter submenu
        state_menu = wx.Menu()
        state_menu.AppendRadioItem(ID_STATE_OPEN, "Open")
        state_menu.AppendRadioItem(ID_STATE_CLOSED, "Closed")
        state_menu.AppendRadioItem(ID_STATE_ALL, "All")
        view_menu.AppendSubMenu(state_menu, "State")

        # Filter submenu — which item types to show in Issues & PRs view
        tab_menu = wx.Menu()
        tab_menu.AppendRadioItem(ID_TAB_ISSUES, "Issues Only")
        tab_menu.AppendRadioItem(ID_TAB_PRS, "PRs Only")
        tab_menu.AppendRadioItem(ID_TAB_BOTH, "Issues & PRs")
        view_menu.AppendSubMenu(tab_menu, "Filter")

        view_menu.AppendSeparator()
        self._show_read_item = view_menu.AppendCheckItem(
            ID_SHOW_READ, "Include Read Notifications"
        )

        menu_bar.Append(view_menu, "View")

        # Help menu
        help_menu = wx.Menu()
        help_menu.Append(ID_USER_GUIDE, "User Guide\tF1")
        help_menu.AppendSeparator()
        help_menu.Append(ID_CHECK_UPDATES, "Check for Updates…")
        help_menu.Append(wx.ID_ABOUT, "About GHManage")
        menu_bar.Append(help_menu, "Help")

        self.SetMenuBar(menu_bar)

        self.Bind(wx.EVT_MENU, self.on_user_guide, id=ID_USER_GUIDE)
        self.Bind(wx.EVT_MENU, self.on_check_updates, id=ID_CHECK_UPDATES)
        self.Bind(wx.EVT_MENU, self.on_about, id=wx.ID_ABOUT)

        # Bind mode/state/tab menu items
        self.Bind(wx.EVT_MENU, self.on_quick_mode, id=ID_QUICK_MODE)
        self.Bind(wx.EVT_MENU, self.on_full_mode, id=ID_FULL_MODE)
        self.Bind(wx.EVT_MENU, self.on_state_open, id=ID_STATE_OPEN)
        self.Bind(wx.EVT_MENU, self.on_state_closed, id=ID_STATE_CLOSED)
        self.Bind(wx.EVT_MENU, self.on_state_all, id=ID_STATE_ALL)
        self.Bind(wx.EVT_MENU, self.on_tab_issues, id=ID_TAB_ISSUES)
        self.Bind(wx.EVT_MENU, self.on_tab_prs, id=ID_TAB_PRS)
        self.Bind(wx.EVT_MENU, self.on_tab_both, id=ID_TAB_BOTH)
        self.Bind(wx.EVT_MENU, self.on_view_issues, id=ID_VIEW_ISSUES)
        self.Bind(wx.EVT_MENU, self.on_view_branches, id=ID_VIEW_BRANCHES)
        self.Bind(wx.EVT_MENU, self.on_view_commits, id=ID_VIEW_COMMITS)
        self.Bind(wx.EVT_MENU, self.on_view_tags, id=ID_VIEW_TAGS)
        self.Bind(wx.EVT_MENU, self.on_view_releases, id=ID_VIEW_RELEASES)
        self.Bind(wx.EVT_MENU, self.on_view_workflows, id=ID_VIEW_WORKFLOWS)
        self.Bind(wx.EVT_MENU, self.on_view_workflow, id=ID_VIEW_WORKFLOW)
        self.Bind(wx.EVT_MENU, self.on_view_labels, id=ID_VIEW_LABELS)
        self.Bind(wx.EVT_MENU, self.on_view_favorites, id=ID_VIEW_FAVORITES)
        self.Bind(wx.EVT_MENU, self.on_view_pages, id=ID_VIEW_PAGES)
        self.Bind(wx.EVT_MENU, self.on_view_activity, id=ID_VIEW_ACTIVITY)
        self.Bind(wx.EVT_MENU, self.on_view_notifications, id=ID_VIEW_NOTIFICATIONS)
        self.Bind(wx.EVT_MENU, lambda e: self._toggle_include_read(), id=ID_SHOW_READ)
        self.Bind(wx.EVT_MENU, lambda e: self._mark_notification_read(), id=ID_MARK_READ)
        self.Bind(wx.EVT_MENU, lambda e: self._mark_all_read(), id=ID_MARK_ALL_READ)
        self.Bind(wx.EVT_MENU, lambda e: self._unsubscribe_notification(), id=ID_UNSUBSCRIBE)
        self.Bind(wx.EVT_MENU, self.on_view_starred, id=ID_VIEW_STARRED)
        self.Bind(wx.EVT_MENU, self.on_view_watched, id=ID_VIEW_WATCHED)
        self.Bind(wx.EVT_MENU, self.on_view_shared, id=ID_VIEW_SHARED)
        self.Bind(wx.EVT_MENU, self.on_view_orgs, id=ID_VIEW_ORGS)
        self.Bind(wx.EVT_MENU, self.on_go_to_event_repo, id=ID_GO_TO_EVENT_REPO)
        self.Bind(wx.EVT_MENU, lambda e: self._copy("link"), id=ID_COPY_LINK)
        self.Bind(wx.EVT_MENU, lambda e: self._copy("markdown"), id=ID_COPY_MARKDOWN)
        self.Bind(wx.EVT_MENU, lambda e: self._copy("title"), id=ID_COPY_TITLE)
        self.Bind(wx.EVT_MENU, lambda e: self._copy("ident"), id=ID_COPY_IDENT)
        self.Bind(wx.EVT_MENU, lambda e: self._copy("details"), id=ID_COPY_DETAILS)

    # ── Updates ─────────────────────────────────────────────────────────

    def _start_update_check(self) -> None:
        """Background check run once at startup."""
        threading.Thread(
            target=self._check_for_updates, args=(True,), daemon=True
        ).start()

    def on_check_updates(self, event) -> None:
        """Help ▸ Check for Updates — reports the result either way."""
        self._announce("Checking for updates…")
        threading.Thread(
            target=self._check_for_updates, args=(False,), daemon=True
        ).start()

    def _check_for_updates(self, silent: bool = True) -> None:
        """Worker thread. `silent` = the startup check, which never interrupts.

        On startup a found update is only announced in the status bar; it
        installs itself the next time GHManage starts. Stealing focus with a
        modal at launch — and restarting out from under the user — is worse
        than waiting. The Help menu check is user-initiated, so it may prompt.
        """
        if not self.updater:
            if not silent:
                wx.CallAfter(self._show_no_update, portable=True)
            return

        info = self.updater.check_for_update()
        if not info:
            if not silent:
                wx.CallAfter(self._show_no_update, portable=False)
            return

        wx.CallAfter(self._show_update_item, info.version, info.whats_new_url)
        if silent:
            wx.CallAfter(
                self._announce,
                f"GHManage {info.version} downloaded — "
                "it will be installed next time you start GHManage.",
            )
        else:
            wx.CallAfter(self._show_update_dialog, info.version, info.whats_new_url)

    def _show_update_item(self, version: str, url: str) -> None:
        """Keep a found update on the status bar, where pressing it offers a restart.

        The startup announcement is overwritten by the next status message; this
        item stays until GHManage restarts.
        """
        self._pending_update = (version, url)
        self.status_bar.set_item("update", f"GHManage {version} ready to install")

    def _on_update_item(self) -> None:
        if self._pending_update:
            self._show_update_dialog(*self._pending_update)

    def _show_no_update(self, portable: bool) -> None:
        if portable:
            msg = (
                f"GHManage {APP_VERSION} is running as a portable copy, "
                "which cannot update itself.\n\n"
                "Install GHManage to receive automatic updates."
            )
        else:
            msg = f"GHManage {APP_VERSION} is up to date."
        wx.MessageBox(msg, "Check for Updates", wx.OK | wx.ICON_INFORMATION, self)

    def _show_update_dialog(self, version: str, url: str) -> None:
        msg = (
            f"GHManage {version} is available. You are running {APP_VERSION}.\n\n"
            "It is downloading in the background. Choose Restart Now to "
            "install it immediately, or Later to install it the next time "
            "you start GHManage."
        )
        dlg = wx.MessageDialog(
            self, msg, "Update Available", wx.YES_NO | wx.ICON_INFORMATION
        )
        dlg.SetYesNoLabels("&Restart Now", "&Later")
        try:
            restart_now = dlg.ShowModal() == wx.ID_YES
        finally:
            dlg.Destroy()

        if not restart_now:
            return  # already downloaded; bootstrap() applies it on next launch

        if not self.updater.apply_update_and_restart(sys.argv[1:]):
            wx.MessageBox(
                "The update could not be applied. It will be retried the next "
                f"time GHManage starts.\n\nRelease notes:\n{url}",
                "Update Failed",
                wx.OK | wx.ICON_WARNING,
                self,
            )

    def on_user_guide(self, event) -> None:
        """Help ▸ User Guide (F1): the guide on the web, in your browser."""
        if webbrowser.open(USER_GUIDE_URL):
            self._announce("Opened the user guide in your browser.")
        else:
            self._announce(f"Couldn't open a browser. The user guide is at {USER_GUIDE_URL}")

    def on_about(self, event) -> None:
        wx.MessageBox(
            f"GHManage {APP_VERSION}\n\n"
            "A GUI viewer and manager for GitHub issues and pull requests.\n\n"
            f"{updater.REPO_URL}",
            "About GHManage",
            wx.OK | wx.ICON_INFORMATION,
            self,
        )

    def _update_menu_checks(self) -> None:
        """Update checkmarks/radio selections to match current settings."""
        menu_bar = self.GetMenuBar()
        # List mode
        menu_bar.Check(ID_QUICK_MODE, self.list_mode == "quick")
        menu_bar.Check(ID_FULL_MODE, self.list_mode == "full")
        # View mode (Show submenu)
        menu_bar.Check(ID_VIEW_ISSUES, self.view_mode == VIEW_ISSUES)
        menu_bar.Check(ID_VIEW_BRANCHES, self.view_mode == VIEW_BRANCHES)
        menu_bar.Check(ID_VIEW_COMMITS, self.view_mode == VIEW_COMMITS)
        menu_bar.Check(ID_VIEW_TAGS, self.view_mode == VIEW_TAGS)
        menu_bar.Check(ID_VIEW_RELEASES, self.view_mode == VIEW_RELEASES)
        menu_bar.Check(ID_VIEW_WORKFLOWS, self.view_mode == VIEW_WORKFLOWS)
        menu_bar.Check(ID_VIEW_WORKFLOW, self.view_mode == VIEW_WORKFLOW)
        menu_bar.Check(ID_VIEW_LABELS, self.view_mode == VIEW_LABELS)
        menu_bar.Check(ID_VIEW_FAVORITES, self.view_mode == VIEW_FAVORITES)
        menu_bar.Check(ID_VIEW_PAGES, self.view_mode == VIEW_PAGES)
        menu_bar.Check(ID_VIEW_NOTIFICATIONS, self.view_mode == VIEW_NOTIFICATIONS)
        menu_bar.Check(ID_VIEW_MY_WORK, self.view_mode == VIEW_MY_WORK)
        menu_bar.Check(ID_VIEW_SEARCH_RESULTS, self.view_mode in SEARCH_VIEWS)
        menu_bar.Check(ID_VIEW_ACTIVITY, self.view_mode == VIEW_ACTIVITY)
        menu_bar.Check(ID_SHOW_READ, self._include_read)
        menu_bar.Check(ID_VIEW_STARRED, self.view_mode == VIEW_STARRED)
        menu_bar.Check(ID_VIEW_WATCHED, self.view_mode == VIEW_WATCHED)
        menu_bar.Check(ID_VIEW_SHARED, self.view_mode == VIEW_SHARED)
        menu_bar.Check(ID_VIEW_ORGS, self.view_mode in (VIEW_ORGS, VIEW_ORG))
        # State filter
        menu_bar.Check(ID_STATE_OPEN, self.state_filter == "open")
        menu_bar.Check(ID_STATE_CLOSED, self.state_filter == "closed")
        menu_bar.Check(ID_STATE_ALL, self.state_filter == "all")
        # Tab filter
        menu_bar.Check(ID_TAB_ISSUES, self.tab_filter == "issues")
        menu_bar.Check(ID_TAB_PRS, self.tab_filter == "prs")
        menu_bar.Check(ID_TAB_BOTH, self.tab_filter == "both")
        # Columns
        for item_id, col in self._col_menu_items.items():
            menu_bar.Check(item_id, col in self.columns)
        # Sort order
        for item_id, order in self._sort_menu_items.items():
            menu_bar.Check(item_id, order == self.sort_order)
        self._update_actions_menu()

    def _update_actions_menu(self) -> None:
        """Label and enable the Actions items for the current view.

        The Delete entry names what it would delete, so the menu never offers a
        bare "Delete" whose object you have to guess, and is disabled where
        nothing can be deleted — which also parks its Ctrl+D accelerator.
        """
        if not hasattr(self, "_act_delete"):
            return  # called before the menu exists
        issues = self.view_mode == VIEW_ISSUES
        self._act_close.Enable(issues)
        self._act_reopen.Enable(issues)
        self._act_comment.Enable(issues)

        in_repo = bool(self.repo) and self.view_mode not in REPOLESS_VIEWS
        self._act_new.Enable(in_repo)
        # Always on: they act on the repository in front of you (see
        # _repo_in_front) and say so when there is none.
        self._act_new_issue.Enable(True)
        self._act_search_repo.Enable(True)
        self._act_pr.Enable(issues)
        # Always on: it can act on the repo selected in the repo list from any
        # view, and says "Select a repository first" when there is none.
        self._act_watch.Enable(True)
        self._act_save_search.Enable(self.view_mode in SEARCH_VIEWS)
        self._act_go_to_repo.Enable(self.view_mode in GO_TO_REPO_VIEWS)
        self._act_go_to_repo.SetItemLabel(
            "Go to Notification's Repository\tCtrl+Shift+G"
            if self.view_mode == VIEW_NOTIFICATIONS
            else "Go to Event's Repository\tCtrl+Shift+G"
            if self.view_mode == VIEW_ACTIVITY
            else "Go to Repository\tCtrl+Shift+G"
        )
        notifications = self.view_mode == VIEW_NOTIFICATIONS
        for entry in (self._act_mark_read, self._act_unsubscribe, self._act_mark_all_read):
            entry.Enable(notifications)

        if self.view_mode == VIEW_LABELS:
            self._act_delete.SetItemLabel("Delete Label…\tCtrl+D")
            self._act_delete.Enable(True)
        elif self.view_mode == VIEW_WORKFLOW:
            self._act_delete.SetItemLabel("Delete Workflow Run…\tCtrl+D")
            self._act_delete.Enable(True)
        elif self.view_mode == VIEW_NOTIFICATIONS:
            self._act_delete.SetItemLabel("Mark as Done\tCtrl+D")
            self._act_delete.Enable(True)
        else:
            self._act_delete.SetItemLabel("Delete\tCtrl+D")
            self._act_delete.Enable(False)

        self._act_run_workflow.Enable(self.view_mode == VIEW_WORKFLOWS)
        self._act_download.Enable(self.view_mode == VIEW_ARTIFACTS)
        runs = self.view_mode in (VIEW_WORKFLOW, VIEW_JOBS)
        self._act_run_jobs.Enable(self.view_mode == VIEW_WORKFLOW)
        for entry in (self._act_run_failed, self._act_run_rerun, self._act_run_cancel):
            entry.Enable(runs)
        # Only offer the site once we know there is one — the Pages views are
        # reachable on a repo that publishes nothing.
        self._act_open_site.Enable(
            self.view_mode in (VIEW_PAGES, VIEW_PAGEFILES) and self.pages_site is not None
        )
        self._act_select_branch.Enable(self.view_mode == VIEW_COMMITS)
        self._act_compare.Enable(self.view_mode == VIEW_BRANCHES)
        # An artifact has no page of its own on github.com to link to.
        linkable = self.view_mode != VIEW_ARTIFACTS
        self._act_copy_link.Enable(linkable)
        self._act_copy_markdown.Enable(linkable)
        noun = self._COPY_IDENT_NOUNS.get(self.view_mode, "Name")
        self._act_copy_ident.SetItemLabel(f"Copy {noun}\tCtrl+Shift+I")

    def _rebuild_columns_menu(self) -> None:
        """Rebuild the Columns submenu for the current view mode."""
        # Remove old items
        for item_id in list(self._col_menu_items.keys()):
            self.Unbind(wx.EVT_MENU, id=item_id)
            self._col_menu.DestroyItem(self._col_menu.FindItemById(item_id))
        self._col_menu_items = {}
        # Get available columns for current view
        _, all_cols = VIEW_COLUMNS.get(self.view_mode, (DEFAULT_COLUMNS, ALL_COLUMNS))
        for col in all_cols:
            item_id = wx.NewIdRef()
            self._col_menu_items[item_id] = col
            self._col_menu.AppendCheckItem(item_id, col)
            self.Bind(wx.EVT_MENU, self.on_column_toggled, id=item_id)

    def _switch_view(self, mode: str, load: bool = True) -> None:
        """Switch to a different view mode (issues, branches, commits, etc.).

        ``load=False`` sets the view up without fetching, for a caller that
        already has its contents (Backspace back to the Activity feed).
        """
        if self.view_mode == mode:
            return
        # Every view but Favorites and Activity is a view *of a repo*. Refuse rather than
        # switch to an empty list, and put the radio check back where it was —
        # the menu item has already toggled itself by the time we get here.
        if mode not in REPOLESS_VIEWS and not self.repo:
            self._update_menu_checks()
            self._announce("Select a repository first.")
            return
        self.view_mode = mode
        # Reset per-view drill-down context and filter when leaving a view
        if mode != VIEW_COMMITS:
            self.commit_branch = ""
        if mode != VIEW_ARTIFACTS:
            self.artifacts_run = None
        if mode != VIEW_JOBS:
            self.jobs_run = None
        if mode != VIEW_ASSETS:
            self.assets_release = None
        if mode != VIEW_ISSUES:
            self.label_filter = ""
        if mode not in (VIEW_PAGES, VIEW_PAGEFILES):
            self.pages_site = None
        if mode != VIEW_ISSUES:
            # The way back to the feed is from the repo's issues, where G
            # left you; anywhere else Backspace means something of its own.
            self._return_to = None
        self.filter_text = ""  # clear filter on view switch
        # Update columns for the new view
        default_cols, _ = VIEW_COLUMNS.get(mode, (DEFAULT_COLUMNS, ALL_COLUMNS))
        self.columns = list(default_cols)
        self._rebuild_columns()
        self._rebuild_columns_menu()
        self._update_menu_checks()
        self.current_limit = self.page_size
        # Keep the repo list in step with the view however you got there —
        # Ctrl+Shift+A or the View menu as much as the list itself — so Tab
        # back to it lands on the entry for what you are looking at.
        self._restore_repo_selection(None)
        if not load:
            return
        if mode == VIEW_FAVORITES:
            self._load_favorites_view()
        elif self.repo or mode in FEED_VIEWS:
            self._load_items()

    # ── Event binding ───────────────────────────────────────────────────

    def _bind_events(self) -> None:
        self.Bind(wx.EVT_LISTBOX_DCLICK, self.on_repo_activated, self.repo_list)
        self.repo_list.Bind(wx.EVT_CHAR_HOOK, self.on_repo_key_down)
        self.repo_list.Bind(wx.EVT_CONTEXT_MENU, self.on_repo_context_menu)
        # The two widgets emit different event families, so the bindings differ
        # even though the handlers are shared. The handlers below take their
        # row from list_ctrl.GetFirstSelected() rather than off the event, which
        # is what lets one set of handlers serve both.
        if IS_MAC:
            self.Bind(wx.dataview.EVT_DATAVIEW_SELECTION_CHANGED,
                      self.on_item_selected, self.list_ctrl)
            self.Bind(wx.dataview.EVT_DATAVIEW_ITEM_ACTIVATED,
                      self.on_item_activated, self.list_ctrl)
            self.Bind(wx.dataview.EVT_DATAVIEW_ITEM_CONTEXT_MENU,
                      self.on_item_context_menu, self.list_ctrl)
            # DataViewCtrl has no EVT_LIST_KEY_DOWN equivalent. EVT_KEY_DOWN
            # carries the same key codes; on_list_key_down already Skip()s
            # anything it does not claim, so arrow-key navigation still works.
            self.list_ctrl.Bind(wx.EVT_KEY_DOWN, self.on_list_key_down)
        else:
            self.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_item_selected, self.list_ctrl)
            self.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_item_activated, self.list_ctrl)
            # EVT_CONTEXT_MENU, not EVT_LIST_ITEM_RIGHT_CLICK: the latter is the
            # mouse alone, and the Applications key and Shift+F10 must open the
            # menu too. A right-click on a row raises this as well.
            self.list_ctrl.Bind(wx.EVT_CONTEXT_MENU, self.on_item_context_menu)
            self.Bind(wx.EVT_LIST_KEY_DOWN, self.on_list_key_down, self.list_ctrl)
        self.details_text.Bind(wx.EVT_CHAR_HOOK, self.on_details_key_down)
        # Frame-level, so Insert/Delete in the Labels view work wherever focus
        # is — including the details panel, which is where the text describing
        # them is read. EVT_LIST_KEY_DOWN only fires for the list itself, which
        # made that text an instruction you could read but not follow.
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        self.Bind(wx.EVT_MENU, self.on_refresh, id=ID_REFRESH)
        self.Bind(wx.EVT_MENU, self.on_open_repo, id=ID_OPEN_REPO)
        self.Bind(wx.EVT_MENU, self.on_remove_repo, id=ID_REMOVE_REPO)
        self.Bind(wx.EVT_MENU, self.on_open_browser, id=ID_OPEN_BROWSER)
        self.Bind(wx.EVT_MENU, self.on_close_item, id=ID_CLOSE_ITEM)
        self.Bind(wx.EVT_MENU, self.on_reopen, id=ID_REOPEN)
        self.Bind(wx.EVT_MENU, self.on_comment, id=ID_COMMENT)
        self.Bind(wx.EVT_MENU, self.on_new_issue, id=ID_NEW_ISSUE)
        self.Bind(wx.EVT_MENU, lambda e: self._switch_account_flow(), id=ID_SWITCH_ACCOUNT)
        self.Bind(wx.EVT_MENU, lambda e: self._watch_settings_flow(), id=ID_WATCH_SETTINGS)
        self.Bind(wx.EVT_MENU, lambda e: self._search_flow(), id=ID_SEARCH)
        self.Bind(wx.EVT_MENU, lambda e: self.on_item_activated(None), id=ID_CTX_OPEN)
        self.Bind(wx.EVT_MENU, lambda e: self._activate_repo_entry(), id=ID_REPO_OPEN)
        self.Bind(wx.EVT_MENU, lambda e: self._repo_entry_action("browser"), id=ID_REPO_BROWSER)
        self.Bind(wx.EVT_MENU, lambda e: self._search_repo_in_front(), id=ID_SEARCH_REPO)
        self.Bind(wx.EVT_MENU, lambda e: self._search_from_view_menu(), id=ID_VIEW_SEARCH_RESULTS)
        self.Bind(wx.EVT_MENU, lambda e: self._show_run_jobs(), id=ID_RUN_JOBS)
        self.Bind(wx.EVT_MENU, lambda e: self._pr_checks(), id=ID_PR_CHECKS)
        self.Bind(wx.EVT_MENU, lambda e: self._pr_review(), id=ID_PR_REVIEW)
        self.Bind(wx.EVT_MENU, lambda e: self._pr_merge(), id=ID_PR_MERGE)
        self.Bind(wx.EVT_MENU, lambda e: self._pr_toggle_draft(), id=ID_PR_DRAFT)
        self.Bind(wx.EVT_MENU, lambda e: self._pr_request_reviewers(), id=ID_PR_REVIEWERS)
        self.Bind(wx.EVT_MENU, lambda e: self._pr_update_branch(), id=ID_PR_UPDATE)
        self.Bind(wx.EVT_MENU, lambda e: self._show_what_failed(), id=ID_RUN_FAILED)
        self.Bind(wx.EVT_MENU, lambda e: self._rerun_run(), id=ID_RUN_RERUN)
        self.Bind(wx.EVT_MENU, lambda e: self._cancel_run(), id=ID_RUN_CANCEL)
        self.Bind(wx.EVT_MENU, lambda e: self._save_search(), id=ID_SAVE_SEARCH)
        self.Bind(wx.EVT_MENU, lambda e: self._select_category(VIEW_MY_WORK), id=ID_VIEW_MY_WORK)
        self.Bind(wx.EVT_MENU, self.on_goto, id=ID_GOTO)
        self.Bind(wx.EVT_MENU, self.on_filter, id=ID_FILTER)
        self.Bind(wx.EVT_MENU, self.on_new_label, id=ID_NEW_LABEL)
        self.Bind(wx.EVT_MENU, self.on_delete_label, id=ID_DELETE_LABEL)
        self.Bind(wx.EVT_MENU, self.on_delete_item, id=ID_DELETE_ITEM)
        self.Bind(wx.EVT_MENU, self.on_act_run_workflow, id=ID_ACT_RUN_WORKFLOW)
        self.Bind(wx.EVT_MENU, self.on_act_download_artifact, id=ID_ACT_DOWNLOAD_ARTIFACT)
        self.Bind(wx.EVT_MENU, self.on_open_pages_site, id=ID_OPEN_PAGES_SITE)
        self.Bind(wx.EVT_MENU, self.on_select_branch, id=ID_SELECT_BRANCH)
        self.Bind(wx.EVT_MENU, self.on_compare_branches, id=ID_COMPARE_BRANCHES)
        self.Bind(wx.EVT_MENU, self.on_view_more, id=ID_VIEW_MORE)
        self.Bind(wx.EVT_MENU, self.on_next_comment, id=ID_NEXT_COMMENT)
        self.Bind(wx.EVT_MENU, self.on_prev_comment, id=ID_PREV_COMMENT)
        self.Bind(wx.EVT_MENU, self.on_quit, id=wx.ID_EXIT)
        self.Bind(wx.EVT_CLOSE, self.on_quit)

    # ── Repo loading ───────────────────────────────────────────────────

    def _load_repos(self) -> None:
        self._repo_token += 1
        token = self._repo_token
        self._announce("Loading your repositories…")

        def worker() -> None:
            try:
                listing = list_repos(limit=100)
            except GhError as exc:
                wx.CallAfter(self._on_repos_error, str(exc))
                return
            wx.CallAfter(self._on_repos_loaded, listing, token=token)
            # The counts come after the list, one small call each, so the
            # list is never kept waiting for them. A count that can't be had
            # is left off rather than shown wrong.
            counts = {}
            for entry, count in COUNTED_ENTRIES.items():
                try:
                    counts[entry] = count()
                except GhError:
                    continue
            wx.CallAfter(self._on_category_counts, counts, token)

        threading.Thread(target=worker, daemon=True).start()

    def _on_category_counts(self, counts: dict[str, int], token: int | None = None) -> None:
        if token is not None and token != self._repo_token:
            return  # a later load is on its way with newer numbers
        self._category_counts.update(counts)
        self._refresh_category_labels()

    def _category_label(self, entry: str, label: str) -> str:
        """``Starred Repositories (7)`` once the count is known, else the name."""
        n = self._category_counts.get(entry)
        if n is None:
            return label
        # Notifications counts what is waiting, not what there is.
        unit = " unread" if entry == NOTIFICATIONS_ENTRY else ""
        return f"{label} ({n:,}{unit})"

    def _refresh_category_labels(self) -> None:
        """Put the current counts on the category entries, in place.

        SetString rather than a rebuild, as the Favorites count does, so the
        row you are on in the list stays where it is.
        """
        labels = dict(self._category_entries())
        for i in range(self.repo_list.GetCount()):
            entry = self.repo_list.GetClientData(i)
            if entry in labels:
                self._set_repo_list_label(i, self._category_label(entry, labels[entry]))

    def _category_entries(self) -> list:
        """Every entry after ★ Favorites, in order, with its label: the fixed
        categories, then Shared With Me when there is any."""
        entries = list(CATEGORY_ENTRIES)
        if self._show_shared:
            entries.append((SHARED_ENTRY, SHARED_LABEL))
        return entries

    def _set_repo_list_label(self, i: int, label: str) -> None:
        """Change one repo-list entry's text — only if it actually changes.

        On Windows SetString deletes and re-inserts the row, and on the
        selected row that raises a focus event even when the list doesn't
        have focus, which a screen reader may announce. Rewriting a label to
        the text it already has would do that for nothing.
        """
        if self.repo_list.GetString(i) != label:
            self.repo_list.SetString(i, label)

    def _on_repos_loaded(self, repos, token: int | None = None) -> None:
        """Build the repository list: from a fresh ``RepoListing``, or from the
        repos already cached (a plain list) for a rebuild."""
        # A load superseded by a later one must not land on top of it. No
        # token means a rebuild from what is already cached, which is always
        # current.
        if token is not None and token != self._repo_token:
            return
        if isinstance(repos, RepoListing):
            listing, repos = repos, repos.repos
            self._orgs = listing.orgs
            # None is "more than a page", so there is something to show.
            self._show_shared = listing.shared != 0
            counts = {MY_ORGS_ENTRY: len(listing.orgs),
                      SHARED_ENTRY: listing.shared or None}
            for entry, n in counts.items():
                # Unknown now means unknown: not the number from last time.
                if n is None:
                    self._category_counts.pop(entry, None)
                else:
                    self._category_counts[entry] = n
        self._all_repos = repos
        # Remember what was selected so the rebuild puts you back on it,
        # rather than at the top of the list while you are arrowing through.
        old = self.repo_list.GetSelection()
        previous = self.repo_list.GetClientData(old) if old != wx.NOT_FOUND else None
        self.repo_list.Clear()
        # The views that aren't of one repository come first, Favorites
        # leading as it always has.
        n_fav = len(self.favorites)
        fav_label = f"★ Favorites ({n_fav})" if n_fav else "★ Favorites"
        self.repo_list.Append(fav_label, clientData=FAVORITES_ENTRY)
        for entry, label in self._category_entries():
            self.repo_list.Append(self._category_label(entry, label), clientData=entry)
        # Saved searches next: Enter runs one.
        for saved in getattr(self, "saved_searches", []):
            self.repo_list.Append(f"🔍 {saved.name}",
                                  clientData=SEARCH_ENTRY_PREFIX + saved.name)
        # Pinned (added-by-URL) repos next, marked with a pin
        shown = set()
        for name in self._pinned_repos:
            if name in shown:
                continue
            shown.add(name)
            # If it's also in the gh list, reuse its description
            desc = ""
            for r in repos:
                if r.get("nameWithOwner", "") == name:
                    desc = r.get("description") or ""
                    break
            label = f"📌 {name} — {desc}" if desc else f"📌 {name}"
            self.repo_list.Append(label, clientData=name)
        # Then the user's own repos. Organizations' are under My
        # Organizations, so a big one can't bury these.
        for repo in repos:
            name = repo.get("nameWithOwner", "")
            if name in shown:
                continue
            shown.add(name)
            desc = repo.get("description") or ""
            label = f"{name} — {desc}" if desc else name
            self.repo_list.Append(label, clientData=name)
        self._announce(
            f"Loaded {len(shown)} repositories. Select one to view issues and PRs."
        )
        self._restore_repo_selection(previous)
        # Take focus only when the list first appears, or when it already has
        # it. A rebuild (after Open Repository, say) must not pull you out of
        # what you are reading — and not when nothing in the app has focus
        # either, which is also what it sees while it is in the background.
        if not self._repos_loaded_once or self._current_focus() is self.repo_list:
            self.repo_list.SetFocus()
        self._repos_loaded_once = True

    def _current_focus(self):
        return wx.Window.FindFocus()

    def _current_entry(self):
        """The repo-list entry for what the right-hand side shows, or None."""
        entry = self._view_entry(self.view_mode)
        if entry:
            return entry
        if self.view_mode in SEARCH_VIEWS:
            search = getattr(self, "_search", None)
            for saved in getattr(self, "saved_searches", []):
                if search == (saved.kind, saved.query):
                    return SEARCH_ENTRY_PREFIX + saved.name
            return None
        return self.repo

    def _restore_repo_selection(self, previous) -> None:
        """Select the right row after a rebuild of the repo list.

        Whatever was selected before, if it is still there; otherwise the
        entry for what the right-hand side is showing. If that has gone (a
        pinned repo just removed), select nothing rather than something that
        disagrees with the rest of the window.
        """
        wanted = [previous, self._current_entry()]
        for target in wanted:
            if target is None:
                continue
            for i in range(self.repo_list.GetCount()):
                if self.repo_list.GetClientData(i) == target:
                    self.repo_list.SetSelection(i)
                    return
        if previous is None and not self.repo and self.repo_list.GetCount():
            # First load: start at the top. Not on an empty list — before the
            # repos arrive, or after they failed to — where wx asserts.
            self.repo_list.SetSelection(0)
        else:
            self.repo_list.SetSelection(wx.NOT_FOUND)

    def _on_repos_error(self, msg: str) -> None:
        self._announce(f"Error loading repos: {msg}")

    def on_repo_activated(self, event: wx.CommandEvent) -> None:
        """Double-click on repo list — load that repo's items."""
        self._activate_repo_entry()

    def on_repo_key_down(self, event: wx.KeyEvent) -> None:
        """Handle Enter key on repo list — load the selected repo."""
        if event.GetKeyCode() == wx.WXK_RETURN:
            self._activate_repo_entry()
            return  # swallow the key
        event.Skip()

    def _activate_repo_entry(self) -> None:
        """Open whatever is selected in the repo list: a repo or a pseudo-entry."""
        idx = self.repo_list.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        name = self.repo_list.GetClientData(idx)
        if not name:
            return
        if name == FAVORITES_ENTRY:
            self._select_favorites()
        elif name in ENTRY_VIEWS:
            self._select_category(ENTRY_VIEWS[name])
        elif name.startswith(SEARCH_ENTRY_PREFIX):
            saved = self._saved_search(name[len(SEARCH_ENTRY_PREFIX):])
            if saved:
                self._run_search(saved.kind, saved.query)
        else:
            self._select_repo(name)

    def _select_repo(self, repo: str, view: str = VIEW_ISSUES) -> None:
        if " — " in repo:
            repo = repo.split(" — ")[0].strip()
        self.repo = repo
        self._return_to = None
        self._pending_target = None
        self.current_limit = self.page_size  # reset to first page
        self.filter_text = ""  # clear filter on repo switch
        self.label_filter = ""  # a label of the old repo means nothing here
        self._update_actions_menu()  # repo-dependent items (New Label…)
        self._update_title()
        # A new repo opens on its issues, unless asked for another view
        if self.view_mode != view:
            self._switch_view(view)
        else:
            self._load_items()

    def _select_favorites(self) -> None:
        """Switch to the Favorites view — shows all favorited items across repos."""
        self.repo = None
        self._update_title()
        self._update_actions_menu()
        if self.view_mode != VIEW_FAVORITES:
            self._switch_view(VIEW_FAVORITES)
        else:
            self._load_favorites_view()

    def _select_category(self, view: str) -> None:
        """Switch to Activity, Starred or Watched — lists across all repos.

        Unlike Favorites these keep the repository you were in, so Ctrl+1
        after a glance at one takes you straight back to it.
        """
        if self.view_mode != view:
            self._switch_view(view)
        else:
            self.current_limit = self.page_size
            self._load_items()

    def _select_org(self, login: str) -> None:
        """Enter on an organization in My Organizations: its repositories.
        Backspace goes back up to the organizations."""
        if self.view_mode == VIEW_ORG and login != self._org:
            # A filter typed for one organization means nothing in the next.
            self.filter_text = ""
        self._org = login
        self._select_category(VIEW_ORG)

    # ── Item loading ───────────────────────────────────────────────────

    def _begin_fetch(self) -> int:
        """Claim the list for a new load and invalidate any still in flight.

        Fetches run on background threads and come back through `wx.CallAfter`,
        so a slow one can land long after the user has moved on — the issues of
        a big repo arriving into the Labels view, filling it with blank rows
        under the wrong columns and a status bar describing a different view.
        Nothing cancels a `gh` call, so instead every load takes a token and the
        handlers ignore results that are no longer the current one.
        """
        self._fetch_token += 1
        return self._fetch_token

    def _fetch_is_current(self, token: int) -> bool:
        """True if `token` is still the load whose results the list wants."""
        return token == self._fetch_token

    def _load_favorites_view(self) -> None:
        """Populate the list with all favorited items (mixed types, cross-repo)."""
        # Favorites load synchronously from disk, but still take a token — an
        # in-flight repo fetch must not land on top of them.
        self._begin_fetch()
        self._set_view_status("Loading favorites…")
        self.details_text.Clear()
        self.favorites = load_favorites()
        self.git_items = list(self.favorites)  # favorites are stored as git_items for the list
        self.items = []
        filtered = self._populate_filtered_list(self.favorites)
        n = len(self.favorites)
        self._set_view_status(
            f"★ Favorites — {n} item{'s' if n != 1 else ''}.",
            "F=unfavorite  Enter=open in browser  Ctrl+F=filter",
        )
        self._update_title()
        if filtered:
            wx.CallLater(100, self._focus_list)

    def _load_items(self) -> None:
        # Name the view as well as the repo: after a Ctrl+<n> switch this is the
        # first confirmation of where you landed.
        view_label = self._VIEW_LABELS.get(self.view_mode, self.view_mode)
        if self.view_mode == VIEW_ACTIVITY:
            self._set_view_status("Loading your activity feed…")
            self._activity_more = None  # unknown until this load lands
        elif self.view_mode == VIEW_NOTIFICATIONS:
            self._set_view_status("Loading your notifications…")
            self._notif_more = None
        elif self.view_mode == VIEW_MY_WORK:
            self._set_view_status("Finding what needs you — five searches, a few seconds…")
        elif self.view_mode in SEARCH_VIEWS:
            query = self._search[1] if self._search else ""
            self._set_view_status(f"Searching GitHub for {query}…")
        elif self.view_mode == VIEW_ORG:
            self._set_view_status(f"Loading {self._org}'s repositories…")
        elif self.view_mode == VIEW_ORGS:
            self._set_view_status("Loading your organizations…")
        elif self.view_mode in REPO_LIST_VIEWS:
            self._set_view_status(f"Loading {self._view_label(self.view_mode, lower=True)}…")
        else:
            self._set_view_status(f"Loading {view_label} for {self.repo}…")
        self.list_ctrl.DeleteAllItems()
        self._shown = []
        self.details_text.Clear()
        # Read the view and repo once, here on the UI thread, so the worker
        # cannot see them change halfway through and dispatch on a mix of both.
        token = self._begin_fetch()
        view = self.view_mode
        limit = self.current_limit
        include_read = self._include_read
        org = self._org
        org_logins = [o.login for o in self._orgs]
        entry = self._view_entry(view) if view in REPO_LIST_VIEWS else None
        search = self._search
        # View More in a search: what is already listed, to add the next page to
        more_of, self._search_more = getattr(self, "_search_more", None), None
        focus_row, self._pending_focus_row = self._pending_focus_row, 0

        def worker() -> None:
            try:
                if view == VIEW_ISSUES:
                    issues = []
                    prs = []
                    if self.tab_filter in ("issues", "both"):
                        issues = fetch_issues(
                            self.repo, self.state_filter, self.current_limit,
                            self.label_filter,
                        )
                    if self.tab_filter in ("prs", "both"):
                        prs = fetch_prs(
                            self.repo, self.state_filter, self.current_limit,
                            self.label_filter,
                        )
                    combined = sort_items(issues + prs, self.sort_order)
                    wx.CallAfter(
                        self._on_items_loaded, token, combined, len(issues), len(prs)
                    )
                elif view == VIEW_BRANCHES:
                    branches = fetch_branches(self.repo, self.current_limit)
                    wx.CallAfter(self._on_git_items_loaded, token, branches, "branches")
                elif view == VIEW_COMMITS:
                    commits = fetch_commits(self.repo, self.commit_branch, self.current_limit)
                    wx.CallAfter(self._on_git_items_loaded, token, commits, "commits")
                elif view == VIEW_TAGS:
                    tags = fetch_tags(self.repo, self.current_limit)
                    wx.CallAfter(self._on_git_items_loaded, token, tags, "tags")
                elif view == VIEW_RELEASES:
                    releases = fetch_releases(self.repo, self.current_limit)
                    wx.CallAfter(self._on_git_items_loaded, token, releases, "releases")
                elif view == VIEW_WORKFLOWS:
                    workflows = fetch_workflows(self.repo, self.current_limit)
                    wx.CallAfter(self._on_git_items_loaded, token, workflows, "workflows")
                elif view == VIEW_LABELS:
                    labels = fetch_labels(self.repo, self.current_limit)
                    wx.CallAfter(self._on_git_items_loaded, token, labels, "labels")
                elif view == VIEW_WORKFLOW:
                    runs = fetch_workflow_runs(self.repo, self.current_limit)
                    wx.CallAfter(self._on_git_items_loaded, token, runs, "workflow runs")
                elif view == VIEW_ARTIFACTS:
                    if self.artifacts_run:
                        arts = fetch_run_artifacts(
                            self.repo, self.artifacts_run.run_id, self.current_limit
                        )
                        wx.CallAfter(self._on_git_items_loaded, token, arts, "artifacts")
                    else:
                        wx.CallAfter(self._on_git_items_loaded, token, [], "artifacts")
                elif view == VIEW_JOBS:
                    run = self.jobs_run
                    jobs = fetch_run_jobs(self.repo, run.run_id) if run else []
                    # The run as it is now, not as it was when J was pressed:
                    # it may have finished, or been rerun, since.
                    fresh = fetch_workflow_run(self.repo, run.run_id) if run else None
                    wx.CallAfter(self._on_jobs_loaded, token, jobs, fresh)
                elif view == VIEW_ASSETS:
                    if self.assets_release:
                        assets = fetch_release_assets(
                            self.repo,
                            self.assets_release.id,
                            self.assets_release.tag,
                            self.current_limit,
                        )
                        wx.CallAfter(self._on_git_items_loaded, token, assets, "assets")
                    else:
                        wx.CallAfter(self._on_git_items_loaded, token, [], "assets")
                elif view == VIEW_MY_WORK:
                    work, capped, failed = fetch_my_work()
                    wx.CallAfter(self._on_my_work_loaded, token, work, focus_row, capped, failed)
                elif view in SEARCH_VIEWS:
                    if not search:
                        wx.CallAfter(self._on_search_loaded, token, [], 0, 0)
                    else:
                        fetch = search_issues if view == VIEW_SEARCH_ISSUES else search_repos
                        if more_of:
                            offset = (len(more_of) // 100) * 100
                            found, total = fetch(search[1], 100, offset)
                            have = {getattr(x, "url", "") for x in more_of}
                            found = more_of + [x for x in found if getattr(x, "url", "") not in have]
                        else:
                            found, total = fetch(search[1], limit)
                        wx.CallAfter(self._on_search_loaded, token, found, total, focus_row)
                elif view == VIEW_NOTIFICATIONS:
                    notes, more = fetch_notifications(limit, include_read)
                    wx.CallAfter(self._on_notifications_loaded, token, notes, more, focus_row)
                elif view == VIEW_ACTIVITY:
                    events, more = fetch_activity(limit)
                    wx.CallAfter(self._on_activity_loaded, token, events, more, focus_row)
                elif view == VIEW_ORGS:
                    wx.CallAfter(self._on_orgs_loaded, token, fetch_orgs(), focus_row)
                elif view in REPO_LIST_VIEWS:
                    if view == VIEW_ORG:
                        repos = fetch_org_repos(org, limit)
                    elif view == VIEW_SHARED:
                        repos = fetch_shared_repos(limit, org_logins)
                    elif view == VIEW_STARRED:
                        repos = fetch_starred_repos(limit)
                    else:
                        repos = fetch_watched_repos(limit)
                    # A full page may not be all of them; ask for the count
                    # so the entry in the repo list stays true. Organizations
                    # and Shared were counted with the repo list.
                    count = None
                    if len(repos) >= limit and entry in COUNTED_ENTRIES:
                        try:
                            count = COUNTED_ENTRIES[entry]()
                        except GhError:
                            pass
                    wx.CallAfter(self._on_repo_list_loaded, token, repos, focus_row, count)
                elif view == VIEW_PAGES:
                    # The config comes first: with Pages off it is the whole
                    # answer, and when it is on it says where to read the rest.
                    site = fetch_pages_site(self.repo)
                    builds = fetch_pages_builds(self.repo, self.current_limit) if site else []
                    wx.CallAfter(self._on_pages_loaded, token, site, builds)
                elif view == VIEW_PAGEFILES:
                    # Normally arrived at from the Pages view, which has already
                    # fetched the config; re-fetch only when it hasn't.
                    site = self.pages_site or fetch_pages_site(self.repo)
                    files = fetch_pages_files(self.repo, site, self.current_limit) if site else []
                    wx.CallAfter(self._on_pagefiles_loaded, token, site, files)
            except GhError as exc:
                wx.CallAfter(self._on_fetch_error, token, str(exc))
                return

        threading.Thread(target=worker, daemon=True).start()

    def _item_label(self, item, col: str) -> str:
        """Get the display value for a single column, with mode-aware formatting."""
        val = item.to_row(self.columns).get(col, "")
        if self.list_mode == "full":
            return f"{col}: {val}" if val else ""
        return val

    def _favorite_prefix(self, item) -> str:
        """Return '★ ' if the item is in favorites, else empty string."""
        if isinstance(item, ActivityEvent):
            # An event is starred when what it is about is a favorite; many
            # events share the repo's address and must not all light up.
            url = item.subject_url
        else:
            url = getattr(item, "url", "") or ""
        if url and is_favorite(url, self.favorites):
            return "★ "
        return ""

    # View-mode display labels for the window title
    _VIEW_LABELS = {
        VIEW_ISSUES: "Issues",
        VIEW_BRANCHES: "Branches",
        VIEW_COMMITS: "Commits",
        VIEW_TAGS: "Tags",
        VIEW_RELEASES: "Releases",
        VIEW_WORKFLOWS: "Workflows",
        VIEW_WORKFLOW: "Workflow Runs",
        VIEW_ARTIFACTS: "Artifacts",
        VIEW_JOBS: "Jobs",
        VIEW_ASSETS: "Release Assets",
        VIEW_LABELS: "Labels",
        VIEW_FAVORITES: "Favorites",
        VIEW_PAGES: "GitHub Pages",
        VIEW_PAGEFILES: "Published Pages",
        VIEW_ACTIVITY: "Activity",
        VIEW_STARRED: "Starred Repositories",
        VIEW_WATCHED: "Watched Repositories",
        VIEW_NOTIFICATIONS: "Notifications",
        VIEW_MY_WORK: "My Work",
        VIEW_SEARCH_ISSUES: "Search Results",
        VIEW_SEARCH_REPOS: "Repository Search Results",
        VIEW_ORGS: "My Organizations",
        VIEW_ORG: "Organization Repositories",
        VIEW_SHARED: SHARED_LABEL,
    }

    def _view_label(self, view: str, lower: bool = False) -> str:
        """A view's name for titles and messages. An organization's carries
        its name, which keeps its capitals when the rest is lowered."""
        if view == VIEW_ORG and self._org:
            return f"{self._org} {'repositories' if lower else 'Repositories'}"
        if view == VIEW_SHARED and lower:
            return "repositories shared with you"  # "back to shared with me" isn't English
        label = self._VIEW_LABELS.get(view, view.title())
        return label.lower() if lower else label

    def _view_entry(self, view: str):
        """The repo-list entry standing for ``view``, or None. An
        organization's repositories are reached through My Organizations."""
        if view == VIEW_ORG:
            return MY_ORGS_ENTRY
        return VIEW_ENTRIES.get(view)

    def _update_title(self) -> None:
        """Set the window title: <view> [<branch>] — <repo> — ghviewer."""
        view_label = self._view_label(self.view_mode)
        parts: list[str] = [view_label]
        # Include branch where it matters (commits view)
        if self.view_mode == VIEW_COMMITS and self.commit_branch:
            parts.append(self.commit_branch)
        # Include the run being drilled into (artifacts view)
        if self.view_mode == VIEW_ARTIFACTS and self.artifacts_run:
            parts.append(f"run #{self.artifacts_run.run_number} {self.artifacts_run.name}")
        if self.view_mode == VIEW_JOBS and self.jobs_run:
            parts.append(f"run #{self.jobs_run.run_number} {self.jobs_run.name}")
        # Include the release being drilled into (assets view)
        if self.view_mode == VIEW_ASSETS and self.assets_release:
            parts.append(self.assets_release.tag or self.assets_release.name)
        # Include the label the issues list is restricted to
        if self.view_mode == VIEW_ISSUES and self.label_filter:
            parts.append(f"label: {self.label_filter}")
        if self.repo and self.view_mode not in REPOLESS_VIEWS:
            parts.append(self.repo)
        parts.append("ghviewer")
        self.SetTitle(" — ".join(parts))
        self._update_list_label()

    def _update_list_label(self) -> None:
        """Keep the item list's visible label and accessible name in step.

        Called from _update_title, which already runs on every view, repo and
        drill-down change, so the list announces what it is currently showing.
        Both are set: the StaticText is what a sighted user reads and what a
        screen reader may pick up as the associated label, and SetName is the
        control's own accessible name for when it does not.
        """
        label = self._view_label(self.view_mode)
        self.list_label.SetLabel(label)
        self.list_ctrl.SetName(label)

    def _populate_filtered_list(self, source_items: list, use_favorite_prefix: bool = False) -> None:
        """Populate the list ctrl with items that match the current filter.

        ``source_items`` is the full unfiltered list (self.items, self.git_items,
        or self.favorites). Only items matching ``self.filter_text`` are shown.
        """
        self.list_ctrl.DeleteAllItems()
        filtered = [it for it in source_items if self._matches_filter(it)]
        self._shown = filtered
        for i, item in enumerate(filtered):
            prefix = self._favorite_prefix(item) if use_favorite_prefix else ""
            if isinstance(item, FavoriteEntry):
                row = {
                    "type": item.item_type,
                    "repo": item.repo,
                    "title": item.title,
                    "subtitle": item.subtitle,
                }
                for j, col in enumerate(self.columns):
                    label = row.get(col, "")
                    if self.list_mode == "full":
                        label = f"{col}: {label}" if label else ""
                    if j == 0:
                        self.list_ctrl.InsertItem(i, prefix + label)
                    else:
                        self.list_ctrl.SetItem(i, j, label)
            else:
                for j, col in enumerate(self.columns):
                    label = self._item_label(item, col)
                    if j == 0:
                        self.list_ctrl.InsertItem(i, prefix + label)
                    else:
                        self.list_ctrl.SetItem(i, j, label)
        self._update_filter_status()
        return filtered

    def _on_items_loaded(
        self, token: int, items: list[Item], n_issues: int, n_prs: int
    ) -> None:
        if not self._fetch_is_current(token):
            return  # the user has moved on; these belong to a view they left
        self.items = items
        self.git_items = []
        filtered = self._populate_filtered_list(items, use_favorite_prefix=True)
        # Note fork→parent redirection in the status bar
        upstream = parent_repo(self.repo)
        source = f"{self.repo} (issues from upstream {upstream})" if upstream else self.repo
        label_info = f" labelled '{self.label_filter}'" if self.label_filter else ""
        label_hint = "  Backspace=back to labels" if self.label_filter else ""
        if self._return_to:
            back = self._view_label(self._return_to[0], lower=True)
            label_hint = f"  Backspace=back to {back}"
        self._set_view_status(
            f"{source} — {n_issues} issues, {n_prs} PRs ({self.state_filter}){label_info}. "
            f"Showing up to {self.current_limit} newest.",
            "Ctrl++=view more  R=refresh  M=comment  N=new issue  K=checks  V=review  "
            "F=favorite  Ctrl+F=filter"
            f"{label_hint}",
        )
        self._update_title()
        row = self._take_pending_row(items, token)
        if filtered:
            wx.CallLater(100, self._focus_list, row)

    def _on_jobs_loaded(self, token: int, jobs: list, fresh) -> None:
        if not self._fetch_is_current(token):
            return
        if fresh is not None and self.jobs_run and fresh.run_id == self.jobs_run.run_id:
            self.jobs_run = fresh
        self._on_git_items_loaded(token, jobs, "jobs")

    def _on_pages_loaded(self, token: int, site: "PagesSite | None", builds: list) -> None:
        """Pages view: keep the site config, list its publish history."""
        if not self._fetch_is_current(token):
            return  # the user has moved on; these belong to a view they left
        # Whether there is a site to open is only known now, after the fetch —
        # the Actions entry was disabled when the view switched.
        self.pages_site = site
        self._update_actions_menu()
        if site is None:
            self._show_pages_disabled()
            return
        self._on_git_items_loaded(token, builds, "publishes")

    def _on_pagefiles_loaded(self, token: int, site: "PagesSite | None", files: list) -> None:
        """Published-pages view: one row per file the site serves."""
        if not self._fetch_is_current(token):
            return
        self.pages_site = site
        self._update_actions_menu()
        if site is None:
            self._show_pages_disabled()
            return
        self._on_git_items_loaded(token, files, "published files")

    def _show_pages_disabled(self) -> None:
        """Pages is switched off for this repo — say so instead of showing nothing.

        An empty list would read the same as a site that has never published,
        so the details panel carries the explanation.
        """
        self.git_items = []
        self.items = []
        self.list_ctrl.DeleteAllItems()
        self._shown = []
        self.details_text.SetValue(
            "GitHub Pages is not enabled for this repository.\n\n"
            "Turn it on under Settings → Pages on github.com, then press R "
            "here to refresh."
        )
        self._announce(f"{self.repo} — GitHub Pages is not enabled.")
        self._update_title()

    def _on_git_items_loaded(self, token: int, items: list, kind: str) -> None:
        """Handle loaded git items (branches, commits, tags, releases, workflow runs)."""
        if not self._fetch_is_current(token):
            return  # the user has moved on; these belong to a view they left
        self.git_items = items
        self.items = []  # clear issues/PRs
        filtered = self._populate_filtered_list(items, use_favorite_prefix=True)
        # Build status text — include branch name for commits view
        branch_info = ""
        if self.view_mode == VIEW_COMMITS:
            branch_info = f" on {self.commit_branch}" if self.commit_branch else " on default branch"
        compare_hint = "  Ctrl+Shift+B=compare branches" if self.view_mode == VIEW_BRANCHES else ""
        if self.view_mode == VIEW_WORKFLOWS:
            compare_hint = "  Enter=run on branch"
        elif self.view_mode == VIEW_WORKFLOW:
            compare_hint = ("  Enter=list artifacts  J=jobs  L=what failed  E=rerun  X=cancel"
                            "  Delete/Ctrl+D=delete run")
        elif self.view_mode == VIEW_JOBS:
            compare_hint = ("  Enter=read log  L=what failed  E=rerun  X=cancel"
                            "  Backspace=back to runs")
        elif self.view_mode == VIEW_ARTIFACTS:
            compare_hint = "  Enter=download  Backspace=back to runs"
        elif self.view_mode == VIEW_RELEASES:
            compare_hint = "  Enter=list assets"
        elif self.view_mode == VIEW_ASSETS:
            compare_hint = "  Enter=download in browser  Backspace=back to releases"
        elif self.view_mode == VIEW_COMMITS:
            compare_hint = "  Backspace=back to branches"
        elif self.view_mode == VIEW_LABELS:
            compare_hint = (
                "  Enter=browse issues & PRs with it"
                "  Insert/Ctrl+I=new  Delete/Ctrl+D=remove"
            )
        elif self.view_mode == VIEW_PAGES:
            compare_hint = "  Enter=browse published pages  S=open site"
        elif self.view_mode == VIEW_PAGEFILES:
            compare_hint = "  Enter=open page  S=open site  Backspace=back to Pages"
        # Download totals lead the status line where they are the point of the view
        totals = ""
        if self.view_mode == VIEW_RELEASES:
            totals = f" {total_downloads(items):,} downloads across them."
        elif self.view_mode == VIEW_ASSETS:
            totals = f" {sum(a.download_count for a in items):,} downloads in total."
        elif self.view_mode in (VIEW_PAGES, VIEW_PAGEFILES) and self.pages_site:
            # Where the site lives and what it is built from is the thing you
            # came to check, so it leads rather than sitting in the details pane.
            site = self.pages_site
            totals = (
                f" Live at {site.url} — {site.status_display}, "
                f"published from {site.source_branch}{site.source_path}."
            )
        # Ctrl+B only picks a branch in the Commits view — offering it in the
        # tags, releases, or labels list is advertising a key that answers
        # "Select Branch is only available in Commits view."
        branch_hint = "  Ctrl+B=select branch" if self.view_mode == VIEW_COMMITS else ""
        self._set_view_status(
            f"{self.repo} — {len(items)} {kind}{branch_info}.{totals} "
            f"Showing up to {self.current_limit}.",
            f"Ctrl++=view more  R=refresh{branch_hint}  Ctrl+F=filter{compare_hint}",
        )
        self._update_title()
        row = self._take_pending_row(items, token)
        if filtered:
            wx.CallLater(100, self._focus_list, row)

    def _on_activity_loaded(
        self, token: int, events: list, more: bool = False, focus=0,
    ) -> None:
        """Activity view: your feed, newest first.

        ``focus`` is the row to land on, or the event to land on wherever the
        list now shows it (Backspace from a repo reached with G).
        """
        if not self._fetch_is_current(token):
            return  # the user has moved on; these belong to a view they left
        self._activity_more = more
        self.git_items = events
        self.items = []
        filtered = self._populate_filtered_list(events, use_favorite_prefix=True)
        n = len(events)
        if n:
            tail = (
                " Ctrl++ loads older ones." if more
                else " That is all GitHub keeps."
            )
            message = f"Activity — {n} event{'s' if n != 1 else ''}, newest first.{tail}"
        else:
            message = (
                "Activity — nothing yet. The feed shows what happens in "
                "repositories you star or watch and by people you follow."
            )
        self._set_view_status(
            message,
            "Enter=open in browser  G=go to repository  Ctrl++=view more  "
            "R=refresh  F=favorite  Ctrl+F=filter",
        )
        self._update_title()
        row = focus if isinstance(focus, int) else max(self._row_of(focus), 0)
        if filtered:
            wx.CallLater(100, self._focus_list, row)

    def _on_notifications_loaded(
        self, token: int, notes: list, more: bool = False, focus=0, fresh: bool = True,
    ) -> None:
        """Notifications view: newest first, unread only unless asked.

        ``focus`` is the row to land on; or the notification to land on
        wherever the list now shows it (Backspace from one opened here); or,
        after View More, the ids already heard, to land on the first new one.
        """
        if not self._fetch_is_current(token):
            return  # the user has moved on; these belong to a view they left
        self._notif_more = more
        if fresh:
            # What this list is, and how far it reaches: Mark All Read marks
            # read only up to the newest thing in it, so nothing that arrived
            # since — unseen — is marked. Not on a restore from Backspace, whose
            # list is as old as when you left it.
            self._notif_loaded_include = self._include_read
            self._notif_loaded_at = max((n.updated_at for n in notes), default="") or \
                _utc_now_iso()
        self.git_items = notes
        self.items = []
        filtered = self._populate_filtered_list(notes, use_favorite_prefix=True)
        if fresh and not self._include_read and not more:
            # Every unread one is here, so the count is known exactly.
            self._category_counts[NOTIFICATIONS_ENTRY] = sum(1 for x in notes if x.unread)
            self._refresh_category_labels()
        self._set_notifications_status()
        self._update_title()
        if isinstance(focus, frozenset):
            # View More: the first notification not on the list before. Rows
            # read or done meanwhile have gone, so a row number would skip.
            row = next((i for i, x in enumerate(self._shown) if x.id not in focus),
                       max(len(self._shown) - 1, 0))
        elif isinstance(focus, int):
            row = focus
        else:
            row = max(self._row_of_id(focus), 0)
        if filtered:
            wx.CallLater(100, self._focus_list, row)

    def _on_search_loaded(self, token: int, results: list, total: int, focus=0) -> None:
        """Search results: issues and PRs, or repositories, across GitHub."""
        if not self._fetch_is_current(token):
            return
        self._search_total = total
        if self.view_mode == VIEW_SEARCH_ISSUES:
            self.items, self.git_items = results, []
            noun = "issue or pull request" if total == 1 else "issues and pull requests"
        else:
            self.git_items, self.items = results, []
            noun = "repository" if total == 1 else "repositories"
        filtered = self._populate_filtered_list(results, use_favorite_prefix=True)
        query = self._search[1] if self._search else ""
        n = len(results)
        if not n:
            message = f"Search — nothing matches {query}."
        else:
            reach = min(total, SEARCH_MAX)
            if n < reach:
                tail = " Ctrl++ loads more."
            elif total > SEARCH_MAX:
                tail = f" GitHub returns at most the first {SEARCH_MAX:,}; narrow the search for the rest."
            else:
                tail = ""
            verb = "matches" if total == 1 else "match"
            message = f"Search — {total:,} {noun} {verb} {query}, showing {n:,}.{tail}"
        self._set_view_status(
            message,
            "Enter=open here  G=go to repository  Ctrl+O=open on GitHub  F=favorite  "
            "Ctrl+S=save search  Ctrl+Shift+F=new search  Ctrl+F=filter",
        )
        self._update_title()
        self._restore_repo_selection(None)
        row = focus if isinstance(focus, int) else max(self._row_of(focus), 0)
        if filtered:
            wx.CallLater(100, self._focus_list, row)

    def _on_my_work_loaded(self, token: int, items: list, focus=0,
                           capped: set | None = None, failed: list | None = None) -> None:
        """My Work: open issues and PRs that need you, grouped by why."""
        if not self._fetch_is_current(token):
            return
        self.items, self.git_items = items, []
        filtered = self._populate_filtered_list(items, use_favorite_prefix=True)
        if capped is None:  # restored by Backspace: as it was
            capped = getattr(self, "_my_work_capped", set())
            failed = getattr(self, "_my_work_failed", [])
        self._my_work_capped, self._my_work_failed = capped, failed or []
        self._category_counts[MY_WORK_ENTRY] = len(items)
        self._refresh_category_labels()
        if items:
            counts: dict[str, int] = {}
            for it in items:
                counts[it.why] = counts.get(it.why, 0) + 1
            parts = ", ".join(f"{n}{'+' if why in capped else ''} {why}"
                              for why, n in counts.items())
            message = f"My Work — {len(items)} open: {parts}."
            if capped:
                message += " Lists marked + have more than 100; search finds the rest."
        else:
            message = "My Work — nothing open needs you."
        if self._my_work_failed:
            message += (f" Couldn't load: {', '.join(self._my_work_failed)} — "
                        "GitHub allows 30 searches a minute; R tries again shortly.")
        self._set_view_status(
            message,
            "Enter=open here  G=go to repository  Ctrl+O=open on GitHub  F=favorite  "
            "R=refresh  Ctrl+F=filter",
        )
        self._update_title()
        row = focus if isinstance(focus, int) else max(self._row_of(focus), 0)
        if filtered:
            wx.CallLater(100, self._focus_list, row)

    def _set_notifications_status(self) -> None:
        notes = self.git_items
        n = len(notes)
        unread = sum(1 for x in notes if x.unread)
        tail = " Ctrl++ loads more." if self._notif_more else ""
        if not n:
            message = ("Notifications — nothing unread." if not self._include_read
                       else "Notifications — none.")
        elif unread == n and not self._include_read:
            message = f"Notifications — {n:,} unread, newest first.{tail}"
        else:
            message = f"Notifications — {n:,}, {unread:,} unread, newest first.{tail}"
        self._set_view_status(
            message,
            "Enter=open  M=mark read  Delete=done  U=unsubscribe  "
            f"I={'hide' if self._include_read else 'include'} read  G=go to repository  "
            "Ctrl+O=open on GitHub  F=favorite  R=refresh  Ctrl+F=filter",
        )

    def _row_of_id(self, note) -> int:
        """The row showing the notification with ``note``'s id, or -1."""
        nid = getattr(note, "id", None)
        return next((i for i, x in enumerate(self._shown)
                     if isinstance(x, Notification) and x.id == nid), -1)

    def _on_repo_list_loaded(
        self, token: int, repos: list, focus=0, count: int | None = None,
    ) -> None:
        """Starred, Watched, Shared or an organization's: one row per repository.

        ``focus`` is the row to land on, or the repository to land on wherever
        the list now shows it (Backspace from a repo opened from here).
        """
        if not self._fetch_is_current(token):
            return  # the user has moved on; these belong to a view they left
        self.git_items = repos
        self.items = []
        filtered = self._populate_filtered_list(repos, use_favorite_prefix=True)
        n = len(repos)
        label = self._view_label(self.view_mode)
        if n < self.current_limit:
            # The whole list is here, so its length is the count: newer than
            # the one fetched at startup if you have starred something since.
            count = n
        if count is not None and self.view_mode == VIEW_ORG:
            # The count belongs to the organization's row, not an entry.
            for org in self._orgs:
                if org.login == self._org:
                    org.repo_count = count
        elif count is not None:
            self._category_counts[self._view_entry(self.view_mode)] = count
            self._refresh_category_labels()
        if n:
            more = " Ctrl++ loads more." if n >= self.current_limit else ""
            message = f"{label} — {n} repositor{'ies' if n != 1 else 'y'}.{more}"
        elif self.view_mode == VIEW_STARRED:
            message = f"{label} — you haven't starred any repositories."
        elif self.view_mode == VIEW_ORG:
            message = f"{label} — none that you can see."
        elif self.view_mode == VIEW_SHARED:
            message = f"{label} — nobody has shared a repository with you."
        else:
            message = f"{label} — you aren't watching any repositories."
        self._set_view_status(
            message,
            "Enter=open here  Ctrl+O=open on GitHub  F=favorite  Ctrl++=view more  "
            "R=refresh  Ctrl+F=filter",
        )
        self._update_title()
        row = focus if isinstance(focus, int) else max(self._row_of(focus), 0)
        if filtered:
            wx.CallLater(100, self._focus_list, row)

    def _on_orgs_loaded(self, token: int, orgs: list, focus=0) -> None:
        """My Organizations: one row per organization you belong to."""
        if not self._fetch_is_current(token):
            return  # the user has moved on; these belong to a view they left
        self._orgs = orgs
        self.git_items = orgs
        self.items = []
        filtered = self._populate_filtered_list(orgs)
        self._category_counts[MY_ORGS_ENTRY] = len(orgs)
        self._refresh_category_labels()
        n = len(orgs)
        if n:
            message = (f"My Organizations — {n} organization{'s' if n != 1 else ''}, "
                       "the ones you own first.")
        else:
            message = "My Organizations — you don't belong to any organizations."
        self._set_view_status(
            message,
            "Enter=list its repositories  Ctrl+O=open on GitHub  R=refresh  Ctrl+F=filter",
        )
        self._update_title()
        if filtered:
            wx.CallLater(100, self._focus_list, focus if isinstance(focus, int) else 0)

    def _focus_list(self, row: int = 0) -> None:
        """Move keyboard focus to the list and select a row (the first by default)."""
        row = max(0, min(row, self.list_ctrl.GetItemCount() - 1))
        self.list_ctrl.SetFocus()
        self.list_ctrl.Select(row, on=True)
        self.list_ctrl.Focus(row)
        if hasattr(self.list_ctrl, "EnsureVisible"):
            self.list_ctrl.EnsureVisible(row)
        self._show_details(row)

    def _set_pending_target(self, view: str, kind: str, ref: str) -> None:
        """Select ``ref`` when the load just started for ``view`` lands.

        Call right after starting that load (``_select_repo``,
        ``_switch_view``, ``_load_items``), whose token it takes.
        """
        self._pending_target = (self._fetch_token, view, kind, ref)

    def _take_pending_row(self, items: list, token: int) -> int:
        """The row to land on for a pending GitHub address, else the first.

        Only the load the target was set for can take it. Any other load
        that lands means that one was superseded — the user moved on — so the
        target goes with it rather than firing on some later visit. When the
        thing isn't among what loaded, an issue or PR is fetched by number
        (Go To does the same), a commit by SHA; anything else is announced.
        """
        target = self._pending_target
        if not target:
            return 0
        self._pending_target = None
        target_token, view, kind, ref = target
        if target_token != token or view != self.view_mode:
            return 0

        def matches(it) -> bool:
            if kind == "item":
                return isinstance(it, Item) and str(it.number) == ref
            if kind == "commit":
                return isinstance(it, Commit) and it.sha.startswith(ref.lower())
            if kind == "release":
                return isinstance(it, Release) and it.tag == ref
            if kind == "run":
                return isinstance(it, WorkflowRun) and str(it.run_id) == ref
            return False

        found = next((it for it in items if matches(it)), None)
        row = self._row_of(found) if found is not None else -1
        if row >= 0:
            wx.CallLater(150, self._announce, self._describe_landing(found))
            return row
        # After the list has settled on its first row, or that would land on
        # top of the item these select — and only if that list is still the
        # one on screen when they run.
        if kind == "item":
            wx.CallLater(150, self._if_still_current, token, self._goto_issue, int(ref))
        elif kind == "commit":
            wx.CallLater(150, self._if_still_current, token, self._goto_commit, ref)
        elif kind in ("release", "run"):
            what = f"Release {ref}" if kind == "release" else f"Run {ref}"
            plural = "releases" if kind == "release" else "workflow runs"
            if found is not None:
                said = f"{what} is hidden by the quick filter. Escape clears it."
            elif items:
                said = f"{what} isn't among the {len(items)} newest {plural}."
            else:
                said = f"{what} wasn't found: there are no {plural} to show."
            wx.CallLater(150, self._announce, said)
        return 0

    def _if_still_current(self, token: int, fn, *args) -> None:
        if self._fetch_is_current(token):
            fn(*args)

    @staticmethod
    def _describe_landing(item) -> str:
        if isinstance(item, Item):
            return f"Opened #{item.number} — {item.title}"
        if isinstance(item, Commit):
            return f"Opened commit {item.short_sha} — {_first_line(item.message)}"
        if isinstance(item, Release):
            return f"Opened release {item.tag}"
        if isinstance(item, WorkflowRun):
            return f"Opened run #{item.run_number} {item.name}"
        return "Opened"

    def _goto_commit(self, sha: str) -> None:
        """Show a commit that isn't in the list: fetched, and put at the top."""
        if self.view_mode != VIEW_COMMITS or not self.repo:
            return
        self._announce(f"Commit {sha[:7]} isn't among the newest on this branch, fetching…")
        repo, token = self.repo, self._fetch_token

        def worker() -> None:
            try:
                commit = fetch_commit_detail(repo, sha)
            except GhError as exc:
                wx.CallAfter(self._on_fetch_error, token, f"Couldn't fetch commit {sha[:7]}: {exc}")
                return
            wx.CallAfter(self._on_commit_fetched, commit, repo, token)

        threading.Thread(target=worker, daemon=True).start()

    def _on_commit_fetched(self, commit: Commit, repo: str, token: int) -> None:
        # The list it was meant for must still be the one on screen: not
        # another repo, view or branch, nor a refresh of it since.
        if self.view_mode != VIEW_COMMITS or self.repo != repo or token != self._fetch_token:
            return
        self.filter_text = ""
        self.git_items = [commit] + [c for c in self.git_items if c.sha != commit.sha]
        self._populate_filtered_list(self.git_items, use_favorite_prefix=True)
        self._focus_list(0)
        self._announce(
            f"Opened commit {commit.short_sha} — {_first_line(commit.message)}. "
            "It is not on this branch's latest commits, so it is shown first."
        )

    def _on_items_error(self, msg: str) -> None:
        self._announce(f"Error: {msg}")
        self._update_title()

    def _on_fetch_error(self, token: int, msg: str) -> None:
        """Error from a list load — swallowed if that load is no longer current.

        A failure in a view you have already left is not worth replacing the
        status of the view you are now looking at.
        """
        if not self._fetch_is_current(token):
            return
        if self.view_mode == VIEW_ACTIVITY and self._activity_more is None:
            self._activity_more = False  # not loading any more; R tries again
        if self.view_mode == VIEW_NOTIFICATIONS and self._notif_more is None:
            self._notif_more = False
        self._pending_target = None  # its load failed; don't let it fire later
        self._on_items_error(msg)

    # ── Details panel ──────────────────────────────────────────────────

    def _show_details(self, row: int) -> None:
        """Show details for the item in list row ``row`` in the details panel."""
        self._comment_positions = []
        self._current_comment = -1
        item = self._row_item(row)
        source = self._view_source()
        idx = next((i for i, it in enumerate(source) if it is item), -1)
        if self.view_mode in ITEM_VIEWS:
            self._show_issue_details(idx)
        elif self.view_mode == VIEW_FAVORITES:
            self._show_favorite_details(idx)
        else:
            self._show_git_details(idx)

    def _show_favorite_details(self, idx: int) -> None:
        """Show details for a favorited item in the details panel."""
        if idx < 0 or idx >= len(self.favorites):
            self.details_text.Clear()
            return
        fav = self.favorites[idx]
        lines = []
        lines.append(f"★ {fav.title}")
        lines.append(f"Type: {fav.item_type}")
        lines.append(f"Repo: {fav.repo}")
        # Pages files were favourited with their address as the subtitle;
        # it is shown under URL already, so don't read it out twice.
        if fav.subtitle and fav.subtitle != fav.url:
            lines.append(f"Detail: {fav.subtitle}")
        if fav.added_at:
            lines.append(f"Favorited: {fav.added_at[:10]}")
        lines.append("URL:")
        lines.append(fav.url or "(none)")
        lines.append("")
        lines.append("─" * 60)
        lines.append("")
        lines.append("Press Enter to open in browser.")
        lines.append("Press F to remove from favorites.")
        self.details_text.SetValue("\n".join(lines))

    def _show_issue_details(self, idx: int) -> None:
        """Show details for an issue/PR."""
        if idx < 0 or idx >= len(self.items):
            self.details_text.Clear()
            return
        item = self.items[idx]
        lines = []
        lines.append(f"#{item.number} [{item.kind}] {item.title}")
        if item.repo:
            lines.append(f"Repository: {item.repo}")
        if item.why:
            lines.append(f"On My Work because: {item.why}")
        lines.append(f"State: {item.state_display}")
        lines.append(f"Author: {item.author}")
        lines.append(f"Created: {item.created_at}")
        lines.append(f"Updated: {item.updated_at}")
        lines.append("URL:")
        lines.append(item.url or "(none)")
        if item.labels:
            lines.append(f"Labels: {', '.join(item.labels)}")
        if item.assignees:
            lines.append(f"Assignees: {', '.join(item.assignees)}")
        if item.comments and not item.comment_list and item.repo:
            # Search and My Work don't fetch comments; the item's own view does.
            lines.append(f"Comments: {item.comments} — press Enter to open it and read them")
        else:
            lines.append(f"Comments: {item.comments}")
        if item.is_pr:
            lines.append(f"Draft: {'Yes' if item.is_draft else 'No'}")
            lines.append(f"Merged: {'Yes' if item.is_merged else 'No'}")
            if item.review_status:
                lines.append(f"Review: {item.review_status}")
            if item.head_branch or item.base_branch:
                lines.append(f"Branches: {item.head_branch} → {item.base_branch}")
            if item.changed_files or item.additions or item.deletions:
                lines.append(f"Changes: +{item.additions} -{item.deletions} ({item.changed_files} files)")
            if getattr(self, "view_mode", None) == VIEW_ISSUES and item.state == "OPEN":
                lines.append("Keys: K checks, V review, D "
                             + ("ready for review" if item.is_draft else "back to draft")
                             + "; Actions ▸ Pull Request to merge.")
        lines.append("")
        lines.append("─" * 60)
        lines.append("")
        body = item.body or "(no description)"
        # One list entry per text line, so the comment positions recorded
        # below count the same lines _line_to_position does.
        lines.extend(body.splitlines() or [""])
        # Show actual comments if we have them, tracking line positions
        if item.comment_list:
            lines.append("")
            lines.append("─" * 60)
            lines.append(f"Comments ({len(item.comment_list)}):")
            lines.append("─" * 60)
            for i, c in enumerate(item.comment_list):
                lines.append("")
                start_line = len(lines)
                header = f"  Comment {i + 1} of {len(item.comment_list)} — {c['author']} ({c['created_at'][:10] if c['created_at'] else ''}):"
                lines.append(header)
                comment_lines = []
                for body_line in c["body"].splitlines():
                    comment_lines.append(f"    {body_line}")
                lines.extend(comment_lines)
                # Track this comment's position: (line index, number of lines)
                self._comment_positions.append((start_line, len(comment_lines) + 1))
        self.details_text.SetValue("\n".join(lines))

    def _show_git_details(self, idx: int) -> None:
        """Show details for a git item (branch, commit, tag, release, workflow run)."""
        if idx < 0 or idx >= len(self.git_items):
            self.details_text.Clear()
            return
        item = self.git_items[idx]
        lines = []
        if isinstance(item, Branch):
            lines.append(f"Branch: {item.name}")
            lines.append(f"Last commit: {item.commit_sha}")
            lines.append(f"Message: {item.commit_message}")
            lines.append(f"Author: {item.commit_author}")
            lines.append(f"Date: {item.commit_date}")
            lines.append(f"Protected: {'Yes' if item.protected else 'No'}")
            if item.ahead:
                lines.append(f"Ahead: {item.ahead}")
            if item.behind:
                lines.append(f"Behind: {item.behind}")
            lines.append("URL:")
            lines.append(item.url or "(none)")
        elif isinstance(item, Commit):
            lines.append(f"Commit: {item.sha}")
            lines.append(f"Short SHA: {item.short_sha}")
            branch = self.commit_branch if self.commit_branch else "default branch"
            lines.append(f"Branch: {branch}")
            lines.append(f"Author: {item.author}")
            lines.append(f"Date: {item.date}")
            lines.append("URL:")
            lines.append(item.url or "(none)")
            lines.append("")
            lines.append("─" * 60)
            lines.append("")
            lines.append(item.message or "(no message)")
            if item.files:
                lines.append("")
                lines.append("─" * 60)
                lines.append(f"Files changed ({item.files_changed}):")
                lines.append("─" * 60)
                for f in item.files:
                    status = f.get("status", "")
                    fname = f.get("filename", "")
                    adds = f.get("additions", 0)
                    dels = f.get("deletions", 0)
                    lines.append(f"  {status}: {fname} (+{adds} -{dels})")
            if item.additions or item.deletions:
                lines.append("")
                lines.append(f"Total: +{item.additions} -{item.deletions} ({item.files_changed} files)")
        elif isinstance(item, Tag):
            lines.append(f"Tag: {item.name}")
            lines.append(f"Commit: {item.commit_sha}")
            lines.append("URL:")
            lines.append(item.url or "(none)")
        elif isinstance(item, Label):
            lines.append(f"Label: {item.name}")
            lines.append(f"Description: {item.description or '(none)'}")
            lines.append(f"Colour: {'#' + item.color if item.color else '(none)'}")
            lines.append(f"Default label: {'Yes' if item.is_default else 'No'}")
            lines.append("URL:")
            lines.append(item.url or "(none)")
            lines.append("")
            lines.append("─" * 60)
            lines.append("")
            lines.append("Keys, from the list or from here:")
            lines.append("")
            lines.append("  Enter             list the issues and PRs with this label")
            lines.append("  Insert or Ctrl+I  create a new label")
            lines.append(f"  Delete or Ctrl+D  delete '{item.name}' — GHManage asks first")
            lines.append("")
            lines.append("The Actions menu has all three.")
            lines.append("")
            lines.append("Deleting a label strips it from every issue and PR that")
            lines.append("has it, and GitHub offers no way to undo that.")
        elif isinstance(item, Release):
            lines.append(f"Release: {item.name}")
            lines.append(f"Tag: {item.tag}")
            lines.append(f"Date: {item.created_at}")
            lines.append(f"Draft: {'Yes' if item.draft else 'No'}")
            lines.append(f"Prerelease: {'Yes' if item.prerelease else 'No'}")
            lines.append(f"Downloads: {item.downloads:,} across {len(item.assets)} assets")
            lines.append("URL:")
            lines.append(item.url or "(none)")
            if item.assets:
                lines.append("")
                lines.append("─" * 60)
                lines.append("Downloads by asset:")
                lines.append("─" * 60)
                # Most-downloaded first — the number is why you are looking here
                for a in sorted(item.assets, key=lambda x: x.download_count, reverse=True):
                    lines.append(f"  {a.download_count:>7,}  {a.name}  ({a.size_human()})")
                lines.append("")
                lines.append("Press Enter to open these assets as their own list.")
            lines.append("")
            lines.append("─" * 60)
            lines.append("")
            lines.append(item.body or "(no release notes)")
        elif isinstance(item, Workflow):
            lines.append(f"Workflow: {item.name}")
            lines.append(f"State: {item.state}")
            lines.append(f"File: {item.path}")
            lines.append(f"ID: {item.id}")
            lines.append("URL:")
            lines.append(item.url or "(none)")
            lines.append("")
            lines.append("─" * 60)
            lines.append("")
            lines.append("Press Enter to run this workflow on a branch you choose")
            lines.append("(only works if the workflow supports manual runs /")
            lines.append("workflow_dispatch). Right-click for the same option.")
        elif isinstance(item, WorkflowRun):
            lines.append(f"Workflow: {item.name}")
            lines.append(f"Run #: {item.run_number}")
            lines.append(f"Status: {item.status}")
            lines.append(f"Result: {item.conclusion or '(running)'}")
            lines.append(f"Branch: {item.branch}")
            lines.append(f"Event: {item.event}")
            lines.append(f"Date: {item.created_at}")
            lines.append("URL:")
            lines.append(item.url or "(none)")
            lines.append("")
            lines.append("─" * 60)
            lines.append("")
            lines.append("Press Enter to list this run's artifacts, J for its jobs and steps.")
            if item.conclusion in ("failure", "timed_out", "startup_failure"):
                lines.append("L shows what failed: GitHub's errors and the end of each failed step's log.")
            lines.append("E reruns it, X cancels it while it is running.")
            lines.append("Delete or Ctrl+D deletes this run — GHManage asks first.")
        elif isinstance(item, WorkflowJob):
            lines.append(f"Job: {item.name}")
            lines.append(f"Status: {item.status}")
            lines.append(f"Result: {item.conclusion or '(running)'}")
            if item.duration:
                lines.append(f"Took: {item.duration}")
            lines.append(f"ID: {item.id}")
            lines.append("URL:")
            lines.append(item.url or "(none)")
            lines.append("")
            lines.append("─" * 60)
            lines.append(f"Steps ({len(item.steps)}):")
            lines.append("─" * 60)
            for step in item.steps:
                lines.append(f"  Step {step.number}, {step.name}: "
                             f"{step.conclusion or step.status or 'not started'}")
            lines.append("")
            lines.append("Press Enter to read this job's log; it opens at the first error.")
            lines.append("L shows only what failed, across the run.")
            lines.append("Press Backspace to return to the workflow runs.")
        elif isinstance(item, Artifact):
            lines.append(f"Artifact: {item.name}")
            lines.append(f"Size: {item.size_human()}")
            lines.append(f"Expired: {'Yes' if item.expired else 'No'}")
            lines.append(f"Created: {item.created_at}")
            lines.append(f"ID: {item.id}")
            lines.append("")
            lines.append("─" * 60)
            lines.append("")
            if item.expired:
                lines.append("This artifact has expired and can no longer be downloaded.")
            else:
                lines.append("Press Enter to download this artifact into a folder you choose.")
            lines.append("Press Backspace to return to the workflow runs.")
        elif isinstance(item, ReleaseAsset):
            lines.append(f"Asset: {item.name}")
            lines.append(f"Downloads: {item.download_count:,}")
            lines.append(f"Size: {item.size_human()}")
            if item.release_tag:
                lines.append(f"Release: {item.release_tag}")
            lines.append(f"Updated: {item.updated_at}")
            lines.append(f"ID: {item.id}")
            lines.append("URL:")
            lines.append(item.url or "(none)")
            lines.append("")
            lines.append("─" * 60)
            lines.append("")
            lines.append("The download count is a lifetime running total kept by GitHub.")
            lines.append("It is not broken down by date, and no API offers that — to see")
            lines.append("downloads over time you have to record these numbers yourself")
            lines.append("and compare them later.")
            lines.append("")
            lines.append("Press Enter to download this file in your browser.")
            lines.append("Press Backspace to return to the releases.")
        elif isinstance(item, PagesBuild):
            site = self.pages_site
            lines.append(f"Publish: {item.status}")
            lines.append(f"Commit: {item.commit}")
            lines.append(f"By: {item.pusher}")
            lines.append(f"Date: {item.created_at}")
            if item.duration_human():
                lines.append(f"Duration: {item.duration_human()}")
            if item.error:
                lines.append(f"Error: {item.error}")
            lines.append(f"ID: {item.id}")
            if site:
                lines.append("")
                lines.append("Site:")
                lines.append(site.url or "(none)")
                lines.append(f"Source: {site.source_branch}{site.source_path}")
                lines.append(f"Built by: {'Actions' if site.built_by_actions else 'GitHub'}")
                lines.append(f"HTTPS enforced: {'Yes' if site.https_enforced else 'No'}")
                if site.cname:
                    lines.append(f"Custom domain: {site.cname}")
                lines.append(f"Visibility: {'public' if site.public else 'private'}")
                lines.append(f"Custom 404: {'Yes' if site.custom_404 else 'No'}")
            lines.append("")
            lines.append("─" * 60)
            lines.append("")
            if item.kind == "deployment":
                # Worth saying: this row did not come from where the reader
                # probably assumes, and it carries less than a build does.
                lines.append("This site is published by Actions, so its history comes from")
                lines.append("the github-pages deployments rather than the Pages build log.")
                lines.append("Deployments record a state but not a build duration.")
                lines.append("")
            lines.append("Press Enter to browse the pages this site serves.")
            lines.append("Press S to open the site itself in your browser.")
        elif isinstance(item, PagesFile):
            site = self.pages_site
            lines.append(f"Page: {item.path}")
            lines.append("URL:")
            lines.append(item.url or "(none)")
            lines.append(f"Size: {item.size_human()}")
            lines.append("")
            lines.append("─" * 60)
            lines.append("")
            if site and site.built_by_actions:
                # The distinction matters: a workflow can publish a subset of
                # the branch, or something it generated that is not in it at all.
                lines.append("This site is built by Actions, so this list is the source")
                lines.append("branch, not the output. What the workflow actually ships")
                lines.append("may be a subset of these files — or files it generated")
                lines.append("that never appear here.")
            elif item.path.endswith((".md", ".markdown")) and item.url.endswith(".html"):
                lines.append("Jekyll renders Markdown to HTML, so this file is stored as")
                lines.append(f"{item.path} but served at the .html URL above.")
            lines.append("")
            lines.append("Press Enter to open this page in your browser.")
            lines.append("Press Backspace to return to the publish history.")
        elif isinstance(item, RepoEntry):
            lines.append(item.name)
            if item.description:
                lines.append(item.description)
            lines.append("URL:")
            lines.append(item.url or "(none)")
            if item.language:
                lines.append(f"Language: {item.language}")
            lines.append(f"Stars: {item.stars:,}")
            lines.append(f"Forks: {item.forks:,}")
            lines.append(f"Open issues and pull requests: {item.open_issues:,}")
            if item.pushed_at:
                lines.append(f"Last pushed: {item.pushed_at[:10]}")
            notes = [n for n, on in (("Archived (read-only)", item.archived),
                                     ("A fork", item.fork), ("Private", item.private)) if on]
            for note in notes:
                lines.append(note)
            lines.append("")
            lines.append("─" * 60)
            lines.append("")
            lines.append(f"Press Enter to open {item.name} here in GHManage.")
            lines.append("Press Ctrl+O to open it on GitHub.")
        elif isinstance(item, OrgEntry):
            lines.append(item.login)
            lines.append(f"Your role: {item.role}")
            if item.repo_count is not None:
                lines.append(f"Repositories you can see: {item.repo_count:,}")
            lines.append("URL:")
            lines.append(item.url)
            lines.append("")
            lines.append("─" * 60)
            lines.append("")
            lines.append(f"Press Enter to list {item.login}'s repositories.")
            lines.append("Press Ctrl+O to open it on GitHub.")
        elif isinstance(item, Notification):
            lines.append(f"#{item.number} {item.title}" if item.number else item.title)
            lines.append(f"{item.kind} in {item.repo}" if item.kind else item.repo)
            lines.append(f"Why: {item.reason_display}")
            lines.append(f"Status: {'unread' if item.unread else 'read'}")
            lines.append(f"Updated: {item.to_row(['updated'])['updated']}")
            lines.append("URL:")
            lines.append(item.url or "(none)")
            lines.append("")
            lines.append("─" * 60)
            lines.append("")
            if item.is_item:
                lines.append(f"Press Enter to open #{item.number} here in GHManage;")
                lines.append("Backspace from there brings you back.")
            else:
                lines.append("Press Enter to open this in your browser.")
            lines.append("M marks it read, Delete marks it done, U unsubscribes")
            lines.append(f"from the thread, G opens {item.repo} here.")
        elif isinstance(item, ActivityEvent):
            lines.append(item.summary)
            lines.append(f"Who: {item.actor}")
            lines.append(f"What: {item.action}")
            if item.title:
                lines.append(f"About: {item.title}")
            lines.append(f"Repository: {item.repo}")
            lines.append(f"When: {item.to_row(['date'])['date']}")
            lines.append("URL:")
            lines.append(item.url or "(none)")
            lines.append("")
            lines.append("─" * 60)
            lines.append("")
            if item.body:
                lines.extend(item.body.splitlines())
                lines.append("")
                lines.append("─" * 60)
                lines.append("")
            lines.append("Press Enter to open this in your browser.")
            lines.append(f"Press G to open {item.repo} here in GHManage.")
        self.details_text.SetValue("\n".join(lines))

    # ── Helpers ─────────────────────────────────────────────────────────

    def _focused_item(self):
        """Return the currently focused item (issue/PR, git item, or favorite)."""
        return self._row_item(self.list_ctrl.GetFirstSelected())

    def _row_item(self, row: int):
        """The item shown in list row ``row``, or None.

        Not ``items[row]``: with a quick filter on, the rows are a subset of
        the items, and the two only line up when nothing is filtered out.
        """
        if 0 <= row < len(self._shown):
            return self._shown[row]
        return None

    def _row_of(self, item) -> int:
        """The list row showing ``item``, or -1 if it is filtered out."""
        return next((i for i, it in enumerate(self._shown) if it is item), -1)

    def _view_source(self) -> list:
        """The full, unfiltered items behind the current view."""
        if self.view_mode in ITEM_VIEWS:
            return self.items
        if self.view_mode == VIEW_FAVORITES:
            return self.favorites
        return self.git_items

    # What Actions ▸ Copy ▸ Copy <noun> copies in each view. Mirrors the
    # ident_noun copy_values() gives that view's items; Activity mixes
    # numbered events with repository-wide ones, so it says both.
    _COPY_IDENT_NOUNS = {
        VIEW_ISSUES: "Number",
        VIEW_BRANCHES: "Branch Name",
        VIEW_COMMITS: "SHA",
        VIEW_TAGS: "Tag",
        VIEW_RELEASES: "Tag",
        VIEW_WORKFLOWS: "File Path",
        VIEW_WORKFLOW: "Run ID",
        VIEW_ARTIFACTS: "Name",
        VIEW_JOBS: "Job ID",
        VIEW_ASSETS: "File Name",
        VIEW_LABELS: "Label Name",
        VIEW_FAVORITES: "Name",
        VIEW_PAGES: "Commit",
        VIEW_PAGEFILES: "Path",
        VIEW_ACTIVITY: "Number, Tag or Repository",
        VIEW_STARRED: "Repository Name",
        VIEW_WATCHED: "Repository Name",
        VIEW_ORGS: "Organization Name",
        VIEW_ORG: "Repository Name",
        VIEW_SHARED: "Repository Name",
        VIEW_NOTIFICATIONS: "Number or Repository",
        VIEW_MY_WORK: "Number",
        VIEW_SEARCH_ISSUES: "Number",
        VIEW_SEARCH_REPOS: "Repository Name",
    }

    _COPY_WHAT = {
        "link": "link",
        "markdown": "Markdown link",
        "title": "title",
        "details": "details",
    }

    def _copy_target(self) -> CopyValues | None:
        """What Copy acts on: the repository when the repo list has focus,
        else the item selected in the list."""
        if self._pane_index(self._current_focus()) == 0:
            idx = self.repo_list.GetSelection()
            name = self.repo_list.GetClientData(idx) if idx != wx.NOT_FOUND else None
            if is_repo_entry(name):
                return repo_copy_values(name)
            return None
        item = self._focused_item()
        return copy_values(item) if item is not None else None

    def _copy(self, what: str) -> None:
        """Actions ▸ Copy: put one thing about the current item on the clipboard."""
        if what == "details":
            text = self.details_text.GetValue().strip()
            noun = "details"
            if not text:
                self._announce("The details panel is empty — nothing to copy.")
                return
        else:
            values = self._copy_target()
            if values is None:
                if self._pane_index(self._current_focus()) == 0:
                    self._announce("That entry is not a repository — nothing to copy.")
                else:
                    self._announce("Nothing selected to copy.")
                return
            if what == "ident":
                text, noun = values.ident, values.spoken_noun
            elif what == "markdown":
                text, noun = values.markdown, "Markdown link"
            else:
                text, noun = getattr(values, what), self._COPY_WHAT[what]
            if not text:
                self._announce(f"This item has no {noun} to copy.")
                return
        if self._set_clipboard(text):
            # Say what was copied when it is short enough to be worth hearing.
            shown = text if len(text) <= 120 and "\n" not in text else ""
            self._announce(f"Copied {noun}: {shown}" if shown else f"Copied {noun}.")
        else:
            self._announce("Couldn't open the clipboard. Try again.")

    def _set_clipboard(self, text: str) -> bool:
        clip = wx.TheClipboard
        if not clip.Open():
            return False
        try:
            clip.SetData(wx.TextDataObject(text))
            # Leave it on the clipboard after GHManage quits.
            clip.Flush()
        finally:
            clip.Close()
        return True

    def _announce(self, msg: str) -> None:
        """Update status bar (screen reader accessible)."""
        self.status_bar.set_item("message", msg)

    def _set_view_status(self, message: str, keys: str = "") -> None:
        """Describe the view in the status bar: what it shows and its keys.

        A load in progress passes no keys, which takes the last view's keys off
        the bar — they may not work in the view that is on its way.
        """
        self.status_bar.set_item("message", message)
        self.status_bar.set_item("keys", keys)
        self._update_filter_status()

    def _update_mode_status(self) -> None:
        self.status_bar.set_item("mode", f"{self.list_mode.capitalize()} mode")

    # ── List events ─────────────────────────────────────────────────────

    def on_item_selected(self, event) -> None:
        # Read the row from the control, not the event: wx.ListEvent has
        # GetIndex() but the macOS DataViewEvent does not, and this handler
        # serves both. GetFirstSelected() means the same thing on each.
        idx = self.list_ctrl.GetFirstSelected()
        if idx < 0:
            return
        self._show_details(idx)
        if self.list_mode == "full":
            item = self._focused_item()
            if item:
                if isinstance(item, FavoriteEntry):
                    self._announce(
                        f"type: {item.item_type}, repo: {item.repo}, "
                        f"title: {item.title}, subtitle: {item.subtitle}"
                    )
                else:
                    self._announce(item.to_accessible_string(self.columns))

    def on_item_activated(self, event) -> None:  # wx.ListEvent / DataViewEvent
        """Double-click or Enter — context-dependent action."""
        item = self._focused_item()
        if not item:
            return
        # In Branches view, Enter switches to Commits for that branch
        if self.view_mode == VIEW_BRANCHES and isinstance(item, Branch):
            self.commit_branch = item.name
            self._switch_view(VIEW_COMMITS)
            self._announce(f"Showing commits on branch {item.name}")
            return
        # In Labels view, Enter shows the issues and PRs carrying that label
        if self.view_mode == VIEW_LABELS and isinstance(item, Label):
            self._browse_label(item)
            return
        # In Workflows view, Enter offers to run the workflow on a branch
        if self.view_mode == VIEW_WORKFLOWS and isinstance(item, Workflow):
            self._run_workflow_flow(item)
            return
        # In Workflow Runs view, Enter drills into that run's artifacts
        if self.view_mode == VIEW_WORKFLOW and isinstance(item, WorkflowRun):
            self.artifacts_run = item
            self._switch_view(VIEW_ARTIFACTS)
            self._announce(f"Showing artifacts for run #{item.run_number} {item.name}")
            return
        if self.view_mode == VIEW_JOBS and isinstance(item, WorkflowJob):
            self._show_job_log(item)
            return
        # In Artifacts view, Enter downloads the selected artifact
        if self.view_mode == VIEW_ARTIFACTS and isinstance(item, Artifact):
            self._download_artifact_flow(item)
            return
        # In Releases view, Enter drills into that release's assets and their counts
        if self.view_mode == VIEW_RELEASES and isinstance(item, Release):
            if not item.assets:
                self._announce(f"{item.tag} has no assets attached")
                return
            self.assets_release = item
            self._switch_view(VIEW_ASSETS)
            self._announce(
                f"Showing {len(item.assets)} assets for {item.tag}, "
                f"{item.downloads:,} downloads in total"
            )
            return
        # In Pages view, Enter drills into the pages the site serves. Which
        # publish is selected doesn't change that: the file list is the site as
        # it stands now, and GitHub keeps no per-publish snapshot to browse.
        if self.view_mode == VIEW_PAGES and isinstance(item, PagesBuild):
            if not self.pages_site:
                self._announce("No Pages site for this repository")
                return
            self._switch_view(VIEW_PAGEFILES)
            self._announce(f"Browsing the pages published at {self.pages_site.url}")
            return
        # In Published Pages view, Enter opens that page in the browser
        if self.view_mode == VIEW_PAGEFILES and isinstance(item, PagesFile):
            webbrowser.open(item.url)
            self._announce(f"Opened {item.path} in browser")
            return
        # In Favorites view, Enter opens in browser
        if self.view_mode == VIEW_FAVORITES and isinstance(item, FavoriteEntry):
            if item.url:
                webbrowser.open(item.url)
                self._announce(f"Opened {item.title} in browser")
            else:
                self._announce("No URL for this favorite")
            return
        if self.view_mode == VIEW_ORGS and isinstance(item, OrgEntry):
            self._select_org(item.login)
            return
        # In the lists of repositories, Enter opens the repository here
        if self.view_mode in REPO_LIST_VIEWS and isinstance(item, RepoEntry):
            self._open_repo_from_list(item.name, item)
            return
        if self.view_mode == VIEW_NOTIFICATIONS and isinstance(item, Notification):
            self._open_notification(item)
            return
        # Across repositories: open the issue or PR here, Backspace returns
        if self.view_mode in (VIEW_MY_WORK, VIEW_SEARCH_ISSUES) and isinstance(item, Item):
            self._open_item_here(item)
            return
        if self.view_mode == VIEW_SEARCH_REPOS and isinstance(item, RepoEntry):
            self._open_repo_from_list(item.name, item)
            return
        # In Activity view, Enter opens what the event was about
        if self.view_mode == VIEW_ACTIVITY and isinstance(item, ActivityEvent):
            self._open_event(item)
            return
        # All other views: open in browser
        url = getattr(item, "url", "") or ""
        if url:
            webbrowser.open(url)
            label = getattr(item, "number", None) or getattr(item, "name", "") or getattr(item, "short_sha", "")
            self._announce(f"Opened {label} in browser")
        else:
            self._announce("No URL for this item")

    # What Enter does in each view, for the first entry of the list's context
    # menu. None where Enter opens the browser, which the Actions menu's own
    # Open in Browser already offers.
    _OPEN_LABELS = {
        VIEW_BRANCHES: "Show Commits",
        VIEW_WORKFLOWS: "Run on a Branch…",
        VIEW_WORKFLOW: "List Artifacts",
        VIEW_JOBS: "Read Log",
        VIEW_ARTIFACTS: "Download…",
        VIEW_RELEASES: "List Files",
        VIEW_LABELS: "List Issues and PRs with This Label",
        VIEW_PAGES: "Browse Published Pages",
        VIEW_NOTIFICATIONS: "Open",
        VIEW_MY_WORK: "Open Here",
        VIEW_SEARCH_ISSUES: "Open Here",
        VIEW_SEARCH_REPOS: "Open Here",
        VIEW_STARRED: "Open Here",
        VIEW_WATCHED: "Open Here",
        VIEW_ORGS: "List Its Repositories",
        VIEW_ORG: "Open Here",
        VIEW_SHARED: "Open Here",
    }

    def _context_entries(self) -> list:
        """The item list's context menu, as data: Enter's action first, then
        everything the Actions menu offers in this view.

        Built from the Actions menu itself rather than listed again, so the two
        can't drift apart — a new action there is in the context menu too, and
        one greyed out there is left out here. Entries are ("item", id, label),
        ("sub", label, entries) and ("sep",).
        """
        self._update_actions_menu()  # the enables must be this view's, now
        entries: list = []
        item = self._focused_item()
        label = self._OPEN_LABELS.get(self.view_mode)
        if isinstance(item, Artifact) and item.expired:
            label = None  # gone from GitHub; Enter would only say so
        # Actions entries that do what the Enter entry already does.
        same_as_enter = {ID_ACT_RUN_WORKFLOW, ID_ACT_DOWNLOAD_ARTIFACT}
        if label and item is not None:
            entries.append(("item", ID_CTX_OPEN, f"{label}\tEnter"))
            entries.append(("sep",))
        else:
            same_as_enter = set()
        if isinstance(item, Artifact) and item.expired:
            same_as_enter = {ID_ACT_DOWNLOAD_ARTIFACT}

        def walk(menu) -> list:
            out: list = []
            for mi in menu.GetMenuItems():
                if mi.IsSeparator():
                    if out and out[-1] != ("sep",):
                        out.append(("sep",))
                    continue
                if not mi.IsEnabled() or mi.GetId() in same_as_enter:
                    continue
                sub = mi.GetSubMenu()
                if sub is not None:
                    inner = walk(sub)
                    if inner:
                        out.append(("sub", mi.GetItemLabel(), inner))
                else:
                    out.append(("item", mi.GetId(), mi.GetItemLabel()))
            while out and out[-1] == ("sep",):
                out.pop()
            return out

        entries += walk(self._actions_menu)
        while entries and entries[-1] == ("sep",):
            entries.pop()
        return entries

    @staticmethod
    def _menu_from_entries(entries: list) -> wx.Menu:
        menu = wx.Menu()
        for entry in entries:
            if entry[0] == "sep":
                menu.AppendSeparator()
            elif entry[0] == "sub":
                menu.AppendSubMenu(GhViewerFrame._menu_from_entries(entry[2]), entry[1])
            else:
                menu.Append(entry[1], entry[2])
        return menu

    def _popup(self, window: wx.Window, menu: wx.Menu, event=None) -> None:
        """Show ``menu`` by the selection when opened from the keyboard, where
        the mouse is when opened by a click."""
        pos = wx.DefaultPosition
        from_keyboard = event is None or (
            hasattr(event, "GetPosition") and event.GetPosition() == wx.DefaultPosition)
        if from_keyboard and window is self.list_ctrl and not IS_MAC:
            row = self.list_ctrl.GetFirstSelected()
            if row >= 0:
                self.list_ctrl.EnsureVisible(row)
                pos = self.list_ctrl.GetItemRect(row).GetBottomLeft()
        window.PopupMenu(menu, pos)
        menu.Destroy()

    def on_item_context_menu(self, event) -> None:  # ContextMenuEvent / DataViewEvent
        """Applications key, Shift+F10 or right-click in the item list."""
        if IS_MAC and hasattr(event, "GetItem"):
            # A right- or Ctrl-click acts on the row clicked, which on macOS
            # is not selected by the click itself.
            clicked = event.GetItem()
            if clicked and clicked.IsOk():
                row = self.list_ctrl.ItemToRow(clicked)
                if row >= 0 and row != self.list_ctrl.GetFirstSelected():
                    self.list_ctrl.Select(row)
                    self._show_details(row)
        # Copy and Watch Settings act on the pane with focus; a click doesn't
        # always move it, so the menu's commands could otherwise reach the
        # other list.
        self.list_ctrl.SetFocus()
        clicked_off_rows = (
            not IS_MAC and hasattr(event, "GetPosition")
            and event.GetPosition() != wx.DefaultPosition and self._focused_item() is None
        )
        if clicked_off_rows:
            return  # a click on empty space: nothing there to act on
        entries = self._context_entries()
        if not entries:
            self._announce("Nothing to do here.")
            return
        self._popup(self.list_ctrl, self._menu_from_entries(entries), event)

    def _repo_context_entries(self, data) -> list:
        """The repository list's context menu, for the entry ``data``."""
        if is_repo_entry(data):
            entries = [
                ("item", ID_REPO_OPEN, "Open\tEnter"),
                ("item", ID_REPO_BROWSER, "Open on GitHub"),
                ("sep",),
                ("item", ID_NEW_ISSUE, "New Issue…\tCtrl+N"),
                ("item", ID_SEARCH_REPO, "Search This Repository…\tCtrl+Shift+S"),
                ("item", ID_WATCH_SETTINGS, "Watch Settings…\tCtrl+Shift+U"),
                ("sep",),
                ("sub", "Copy", [
                    ("item", ID_COPY_LINK, "Copy Link\tCtrl+Shift+C"),
                    ("item", ID_COPY_MARKDOWN, "Copy Markdown Link\tCtrl+Shift+L"),
                    ("item", ID_COPY_IDENT, "Copy Repository Name\tCtrl+Shift+I"),
                ]),
            ]
            if data in self._pinned_repos:
                entries += [("sep",), ("item", ID_REMOVE_REPO, "Remove from List")]
            return entries
        if isinstance(data, str) and data.startswith(SEARCH_ENTRY_PREFIX):
            return [("item", ID_REPO_OPEN, "Run Search\tEnter"),
                    ("item", ID_REMOVE_REPO, "Remove Saved Search")]
        if data:
            return [("item", ID_REPO_OPEN, "Open\tEnter")]
        return []

    def on_repo_context_menu(self, event: wx.ContextMenuEvent) -> None:
        """Applications key, Shift+F10 or right-click in the repository list."""
        pos = event.GetPosition()
        if pos != wx.DefaultPosition:
            # A click: act on the entry clicked, which a right-click on a list
            # box does not select by itself.
            hit = self.repo_list.HitTest(self.repo_list.ScreenToClient(pos))
            if hit != wx.NOT_FOUND:
                self.repo_list.SetSelection(hit)
        # Copy and Watch Settings act on the pane with focus, and a right-click
        # on a list box doesn't move it there by itself.
        self.repo_list.SetFocus()
        idx = self.repo_list.GetSelection()
        data = self.repo_list.GetClientData(idx) if idx != wx.NOT_FOUND else None
        entries = self._repo_context_entries(data)
        if not entries:
            return
        self._popup(self.repo_list, self._menu_from_entries(entries), event)

    def _search_repo_in_front(self) -> None:
        """Actions ▸ Search This Repository (Ctrl+Shift+S): a search that
        starts repo:owner/name, for the repository in front of you."""
        repo = self._repo_in_front()
        if not repo:
            self._announce("Select a repository first: Search This Repository needs one.")
            return
        self._search_flow(prefill=(KIND_ISSUES, f"repo:{repo} "))

    def _repo_entry_action(self, action: str) -> None:
        """A repository-list context menu action, on the repo selected there."""
        idx = self.repo_list.GetSelection()
        name = self.repo_list.GetClientData(idx) if idx != wx.NOT_FOUND else None
        if not is_repo_entry(name):
            self._announce("Select a repository first.")
            return
        if action == "browser":
            url = f"https://github.com/{name}"
            webbrowser.open(url)
            self._announce(f"Opened {name} on GitHub")

    # ── Run a workflow (workflow_dispatch) ──────────────────────────────

    def _run_workflow_flow(self, wf: "Workflow") -> None:
        """Start the 'run this workflow' flow.

        Branch first, then inputs. That order is deliberate and matches the web
        UI: a workflow's inputs are declared in the workflow file, so a branch
        that adds or changes an input has a different form from the default
        branch. Reading the file before the branch is known would show the
        wrong set of inputs and silently drop the values the user typed.

        Nothing is triggered until the user confirms.
        """
        if not self.repo:
            self._announce("No repository loaded.")
            return
        self._announce(f"Loading branches for {wf.name}…")

        def worker() -> None:
            try:
                names = [b.name for b in fetch_branches(self.repo, 200)]
                wx.CallAfter(self._on_workflow_branches_ready, wf, names)
            except GhError as exc:
                wx.CallAfter(self._on_items_error, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_workflow_branches_ready(self, wf: "Workflow", names: list[str]) -> None:
        """Ask which branch to run on, then read that branch's workflow file."""
        if not names:
            self._announce("No branches found to run against.")
            return
        dlg = wx.SingleChoiceDialog(
            self,
            f"Run '{wf.name}' on which branch?",
            "Run Workflow",
            names,
        )
        dlg.SetSelection(0)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            self._announce("Run cancelled.")
            return
        branch = dlg.GetStringSelection()
        dlg.Destroy()
        if not branch:
            return

        self._announce(f"Checking how {wf.name} can be run on {branch}…")

        def worker() -> None:
            try:
                spec = fetch_dispatch_spec(self.repo, wf.path, branch)
                wx.CallAfter(self._on_workflow_dispatch_ready, wf, branch, spec)
            except GhError as exc:
                wx.CallAfter(self._on_items_error, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_workflow_dispatch_ready(
        self, wf: "Workflow", branch: str, spec: "DispatchSpec"
    ) -> None:
        """Collect inputs if the workflow declares any, then dispatch."""
        if not spec.supports_dispatch:
            msg = (
                f"'{wf.name}' can't be run manually because it doesn't declare a "
                f"workflow_dispatch trigger on {branch}.\n\n"
                "Add `on: workflow_dispatch` to the workflow file to enable "
                "manual runs and branch selection."
            )
            self._announce(f"{wf.name} doesn't support manual runs on {branch}.")
            wx.MessageBox(msg, "Run Workflow", wx.OK | wx.ICON_INFORMATION, self)
            return

        # No inputs declared: nothing to ask, so don't put an empty dialog in
        # the way — this is the original behaviour and stays unchanged.
        if not spec.inputs:
            self._dispatch_workflow(wf, branch, {})
            return

        dlg = WorkflowInputsDialog(self, wf.name, branch, spec.inputs)
        if dlg.ShowModal() == wx.ID_OK:
            values = dlg.values()
            dlg.Destroy()
            self._dispatch_workflow(wf, branch, values)
        else:
            dlg.Destroy()
            self._announce("Run cancelled.")

    def _dispatch_workflow(
        self, wf: "Workflow", branch: str, inputs: dict[str, str]
    ) -> None:
        """Trigger the workflow on ``branch`` in the background."""
        summary = ", ".join(f"{k}={v}" for k, v in inputs.items())
        self._announce(
            f"Starting '{wf.name}' on {branch}"
            + (f" with {summary}…" if summary else "…")
        )

        def worker() -> None:
            try:
                dispatch_workflow(self.repo, wf.id, branch, inputs)
                wx.CallAfter(
                    self._announce,
                    f"Started '{wf.name}' on {branch}"
                    + (f" with {summary}. " if summary else ". ")
                    + "Switch to Workflow Runs and refresh to watch it.",
                )
            except GhError as exc:
                wx.CallAfter(self._on_items_error, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    # ── Download an artifact ────────────────────────────────────────────

    def _download_artifact_flow(self, art: "Artifact") -> None:
        """Prompt for a destination folder, then download the artifact into it."""
        if not self.repo:
            self._announce("No repository loaded.")
            return
        if art.expired:
            self._announce(f"'{art.name}' has expired and can't be downloaded.")
            wx.MessageBox(
                f"'{art.name}' has expired and can no longer be downloaded.",
                "Download Artifact",
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            return
        dlg = wx.DirDialog(
            self,
            f"Choose a folder to download '{art.name}' into",
            style=wx.DD_DEFAULT_STYLE,
        )
        if dlg.ShowModal() == wx.ID_OK:
            dest = dlg.GetPath()
            dlg.Destroy()
            self._do_download_artifact(art, dest)
        else:
            dlg.Destroy()
            self._announce("Download cancelled.")

    def _do_download_artifact(self, art: "Artifact", dest: str) -> None:
        """Download ``art`` into ``dest`` in the background."""
        run_id = art.run_id or (self.artifacts_run.run_id if self.artifacts_run else 0)
        self._announce(f"Downloading '{art.name}'…")

        def worker() -> None:
            try:
                download_artifact(self.repo, run_id, art.name, dest)
                wx.CallAfter(
                    self._announce,
                    f"Downloaded '{art.name}' into {dest}.",
                )
            except GhError as exc:
                wx.CallAfter(self._on_items_error, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def on_char_hook(self, event: wx.KeyEvent) -> None:
        """Frame-wide keys that must not depend on which pane has focus.

        The bare Insert and Delete keys are handled here rather than in
        ``on_list_key_down`` so they work from the details panel too — that panel
        is where the text describing them is read. They cannot be menu
        accelerators: a bare Delete accelerator would swallow the Delete key
        everywhere in the window. Their Ctrl+I / Ctrl+D twins in the Actions menu
        are ordinary accelerators, which is why those need nothing here.

        F6 and Shift+F6 move between panes, see ``_cycle_pane``.

        Everything else is skipped, so the focused control keeps first claim on
        its own keys.
        """
        key = event.GetKeyCode()
        if key == wx.WXK_F6 and event.GetModifiers() in (wx.MOD_NONE, wx.MOD_SHIFT):
            self._cycle_pane(backward=event.ShiftDown())
            return
        # Not from the repository list: Delete there reads as "remove this
        # repo", and acting on the item list from another pane is a surprise.
        # Nor from the status bar, which is not about any item in the list.
        focus = self.FindFocus()
        in_status_bar = focus is not None and self.status_bar.IsDescendant(focus)
        if focus is self.repo_list or in_status_bar:
            event.Skip()
            return
        if key == wx.WXK_INSERT and self.view_mode == VIEW_LABELS:
            self._do_new_label()
            return
        # G here rather than in the list's handler so it also works from the
        # details panel, where "Press G" is read.
        if (key == ord("G") and not event.HasAnyModifiers()
                and self.view_mode in GO_TO_REPO_VIEWS):
            self._go_to_event_repo()
            return
        if self.view_mode == VIEW_ISSUES and not event.HasAnyModifiers():
            # Pull request keys, here so they work from the details panel,
            # where the line naming them is read.
            action = {
                ord("K"): self._pr_checks,
                ord("V"): self._pr_review,
                ord("D"): self._pr_toggle_draft,
            }.get(key)
            if action:
                action()
                return
        if self.view_mode in (VIEW_WORKFLOW, VIEW_JOBS) and not event.HasAnyModifiers():
            action = {
                ord("J"): self._show_run_jobs,
                ord("L"): self._show_what_failed,
                ord("E"): self._rerun_run,
                ord("X"): self._cancel_run,
            }.get(key)
            if action:
                action()
                return
        if self.view_mode == VIEW_NOTIFICATIONS and not event.HasAnyModifiers():
            action = {
                ord("M"): self._mark_notification_read,
                ord("U"): self._unsubscribe_notification,
                ord("I"): self._toggle_include_read,
            }.get(key)
            if action:
                action()
                return
        if key == wx.WXK_DELETE and self.view_mode in (VIEW_LABELS, VIEW_WORKFLOW,
                                                       VIEW_NOTIFICATIONS):
            self._delete_focused_item()
            return
        event.Skip()

    def _focus_panes(self) -> list[wx.Window]:
        """The F6 loop, in order. The status bar is always the last stop."""
        return [self.repo_list, self.list_ctrl, self.details_text, self.status_bar]

    def _pane_index(self, window: wx.Window | None) -> int | None:
        """Which pane `window` belongs to, or None when it is in none of them.

        Walks up the parents: on macOS focus in the item list sits on a child
        of the table, not the table itself.
        """
        panes = self._focus_panes()
        while window is not None and not window.IsTopLevel():
            for index, pane in enumerate(panes):
                if window is pane:
                    return index
            window = window.GetParent()
        return None

    def _cycle_pane(self, backward: bool) -> None:
        """F6 / Shift+F6 — move focus to the next or previous pane, wrapping."""
        panes = self._focus_panes()
        current = self._pane_index(self.FindFocus())
        if current is None:
            target = len(panes) - 1 if backward else 0
        else:
            target = (current + (-1 if backward else 1)) % len(panes)
        if panes[target] is self.status_bar:
            self.status_bar.focus_first()
        else:
            panes[target].SetFocus()

    @staticmethod
    def _modifiers_down(event) -> bool:
        """Whether Ctrl, Alt, Shift or Cmd is held for this key.

        On Windows the list's key event is a wx.ListEvent, which carries no
        modifier state at all; the keyboard is asked directly instead. The
        list handles the key as it arrives, so that is the state it was
        pressed with. On macOS it is an ordinary wx.KeyEvent.
        """
        if isinstance(event, wx.KeyEvent):
            return event.HasAnyModifiers()
        return wx.GetMouseState().HasAnyModifiers()

    def on_list_key_down(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        # The single-letter keys here are bare letters. With a modifier the
        # key belongs to something else — Ctrl+C is copy, not Close — so it is
        # passed on untouched.
        if self._modifiers_down(event):
            event.Skip()
            return
        if key == wx.WXK_ESCAPE:
            self._clear_filter()
        elif key == ord("F"):
            self._toggle_favorite()
        elif key == ord("R"):
            self.on_refresh(None)
        elif key == wx.WXK_BACK and self.view_mode in PARENT_VIEW:
            # Backspace steps back up a drill-down (artifacts -> runs, commits -> branches)
            parent = PARENT_VIEW[self.view_mode]
            if self.view_mode == VIEW_ORG:
                # Back on the organization you came from, not at the top.
                logins = [o.login for o in self._orgs]
                self._pending_focus_row = logins.index(self._org) if self._org in logins else 0
            self._switch_view(parent)
            self._announce(f"Back to {self._VIEW_LABELS.get(parent, parent).lower()}")
        elif key == wx.WXK_BACK and self.view_mode == VIEW_ISSUES and self._return_to:
            self._return_to_list()
        elif key == wx.WXK_BACK and self.view_mode == VIEW_ISSUES and self.label_filter:
            # Issues restricted to a label is a drill-down too, even though the
            # view mode is the same one you reach with Ctrl+1.
            self._switch_view(VIEW_LABELS)
            self._announce("Back to labels")
        elif key == ord("S") and self.view_mode in (VIEW_PAGES, VIEW_PAGEFILES):
            self._open_pages_site()
        elif self.view_mode == VIEW_ISSUES:
            # Issue/PR-specific keys
            if key == ord("C"):
                self._do_close()
            elif key == ord("O"):
                self._do_reopen()
            elif key == ord("M"):
                self._do_comment()
            elif key == ord("N"):
                self._do_new_issue()
            else:
                event.Skip()
        else:
            event.Skip()

    def on_open_pages_site(self, event: wx.CommandEvent) -> None:
        self._open_pages_site()

    def _open_pages_site(self) -> None:
        """Open the site's home page (S key, or Actions ▸ Open Published Site)."""
        if not self.pages_site or not self.pages_site.url:
            self._announce("No Pages site for this repository")
            return
        webbrowser.open(self.pages_site.url)
        self._announce(f"Opened {self.pages_site.url} in browser")

    def _open_event(self, item: ActivityEvent) -> None:
        """Open an activity event's page on github.com."""
        if not item.url:
            self._announce("No URL for this event")
            return
        webbrowser.open(item.url)
        self._announce(f"Opened {item.action} in {item.repo} in browser")

    def on_go_to_event_repo(self, event: wx.CommandEvent) -> None:
        self._go_to_event_repo()

    def _go_to_event_repo(self) -> None:
        """Open the repository an activity event happened in (G key)."""
        item = self._focused_item()
        if isinstance(item, RepoEntry):
            self._open_repo_from_list(item.name, item)
            return
        if not isinstance(item, (ActivityEvent, Notification, Item)) or not item.repo:
            self._announce("No repository for this item.")
            return
        self._open_repo_from_list(item.repo, item)

    def _open_repo_from_list(self, repo: str, item) -> None:
        """Open ``repo`` from a list of many (Activity, Starred, Watched).

        Remembers the list and the item you were on, so Backspace from the
        repo's issues brings you back to it.
        """
        # The item itself, not its row: with a quick filter on, the row
        # number means something else once the filter is gone.
        if self.view_mode == VIEW_ACTIVITY:
            more = self._activity_more
        elif self.view_mode == VIEW_NOTIFICATIONS:
            more = self._notif_more
        else:
            more = False
        saved = (self.view_mode, list(self._view_source()), bool(more),
                 item, self.current_limit)
        self._select_repo(repo)
        # Set after _select_repo, which clears it for an ordinary repo change.
        self._return_to = saved
        # Select it in the repo list too when it is there, so the list on the
        # left agrees with what the right side is showing — and nothing when
        # it isn't, rather than leaving the list you came from selected.
        self.repo_list.SetSelection(wx.NOT_FOUND)
        for i in range(self.repo_list.GetCount()):
            if self.repo_list.GetClientData(i) == repo:
                self.repo_list.SetSelection(i)
                break

    def _return_to_list(self) -> None:
        """Backspace from a repo opened from a list: that list, where you left it."""
        view, items, more, item, limit = self._return_to
        self._return_to = None
        self._pending_target = None
        self._switch_view(view, load=False)
        self.current_limit = limit
        self._restore_repo_selection(None)
        token = self._begin_fetch()
        if view == VIEW_ACTIVITY:
            self._on_activity_loaded(token, items, more, item)
        elif view == VIEW_MY_WORK:
            self._on_my_work_loaded(token, items, item)
        elif view in SEARCH_VIEWS:
            self._on_search_loaded(token, items, self._search_total, item)
        elif view == VIEW_NOTIFICATIONS:
            if self._include_read != self._notif_loaded_include:
                # Include Read was changed while you were away; the list you
                # left no longer matches it.
                self._pending_focus_row = 0
                self._load_items()
            else:
                self._on_notifications_loaded(token, items, more, item, fresh=False)
        else:
            self._on_repo_list_loaded(token, items, item)
        self._announce(f"Back to {self._view_label(view, lower=True)}")

    def _toggle_favorite(self) -> None:
        """Toggle favorite status on the currently focused item (F key)."""
        item = self._focused_item()
        if not item:
            return

        # In the favorites view, F unfavorites the item
        if self.view_mode == VIEW_FAVORITES and isinstance(item, FavoriteEntry):
            self.favorites = [f for f in self.favorites if f.url != item.url]
            save_favorites(self.favorites)
            self._announce(f"Removed '{item.title}' from favorites")
            self._load_favorites_view()
            self._refresh_repo_list_fav_count()
            return

        if isinstance(item, Notification) and not item.own_page:
            self._announce(
                f"This {item.kind or 'notification'} has no page of its own to favorite, "
                "only its repository's list of them."
            )
            return

        if isinstance(item, ActivityEvent) and not item.subject_url:
            self._announce(
                "This event isn't about an issue, pull request, release or "
                "discussion, so there is nothing to favorite."
            )
            return

        # In other views, F toggles favorite on the current item
        url = getattr(item, "url", "") or ""
        if not url:
            self._announce("No URL for this item — can't favorite.")
            return

        entry = self._build_favorite_entry(item)
        if entry is None:
            self._announce("Can't determine item type for favorite.")
            return

        self.favorites, was_added = toggle_favorite(entry, self.favorites)
        if was_added:
            self._announce(f"★ Added '{entry.title}' to favorites")
        else:
            self._announce(f"Removed '{entry.title}' from favorites")
        self._refresh_repo_list_fav_count()
        self._redraw_favorite_marks()

    def _redraw_favorite_marks(self) -> None:
        """Put the ★ on, or take it off, every row whose favorite just changed.

        Every row, not just this one: in Activity several events can be about
        the same issue, and they should all agree.
        """
        if not self.columns:
            return
        for row, item in enumerate(self._shown):
            text = self._item_label(item, self.columns[0])
            self.list_ctrl.SetItem(row, 0, self._favorite_prefix(item) + text)

    def _build_favorite_entry(self, item) -> FavoriteEntry | None:
        """Build a FavoriteEntry from any item type (Item, Branch, Commit, etc.)."""
        url = getattr(item, "url", "") or ""
        repo = self.repo or ""
        if isinstance(item, Item):
            repo = item.repo or repo
            item_type = "PR" if item.is_pr else "issue"
            title = f"#{item.number} — {item.title}"
            subtitle = item.state_display
        elif isinstance(item, Branch):
            item_type = "branch"
            title = item.name
            subtitle = item.commit_message[:60] if item.commit_message else ""
        elif isinstance(item, Commit):
            item_type = "commit"
            title = item.short_sha
            subtitle = item.message[:60] if item.message else ""
        elif isinstance(item, Tag):
            item_type = "tag"
            title = item.name
            subtitle = item.commit_sha
        elif isinstance(item, Label):
            item_type = "label"
            title = item.name
            subtitle = item.description[:60] if item.description else ""
        elif isinstance(item, Release):
            item_type = "release"
            title = item.tag
            subtitle = item.name
        elif isinstance(item, Workflow):
            item_type = "workflow"
            title = item.name
            subtitle = f"{item.state} — {item.path}"
        elif isinstance(item, WorkflowRun):
            item_type = "workflow run"
            title = f"#{item.run_number} {item.name}"
            subtitle = f"{item.conclusion or item.status} on {item.branch}"
        elif isinstance(item, WorkflowJob):
            item_type = "job"
            title = item.name
            subtitle = item.conclusion or item.status
        elif isinstance(item, PagesFile):
            item_type = "page"
            title = item.path
            subtitle = item.url
        elif isinstance(item, RepoEntry):
            item_type = "repository"
            repo = item.name
            title = item.name
            subtitle = item.description[:60] if item.description else ""
        elif isinstance(item, Notification):
            if not item.own_page:
                return None
            repo = item.repo
            item_type = item.kind or "notification"
            title = f"#{item.number} — {item.title}" if item.number else item.title
            subtitle = ""
        elif isinstance(item, ActivityEvent):
            # F on an event favorites what it is about — the issue, pull
            # request, release or discussion — the same entry F makes in that
            # item's own view. Events with no such subject can't be favorited:
            # their address is the repo's, shared by many unrelated events.
            if not item.subject_url:
                return None
            url = item.subject_url
            repo = item.repo
            item_type = item.subject_kind
            if item.number:
                title = f"#{item.number} — {item.title}" if item.title else f"#{item.number}"
            else:
                title = item.title or item.action
            subtitle = ""
        else:
            return None

        from datetime import datetime
        return FavoriteEntry(
            repo=repo,
            item_type=item_type,
            url=url,
            title=title,
            subtitle=subtitle,
            added_at=datetime.now().isoformat(timespec="seconds"),
        )

    def _refresh_repo_list_fav_count(self) -> None:
        """Update the ★ Favorites count in the repo list without full reload."""
        for i in range(self.repo_list.GetCount()):
            data = self.repo_list.GetClientData(i)
            if data == FAVORITES_ENTRY:
                n = len(self.favorites)
                label = f"★ Favorites ({n})" if n else "★ Favorites"
                self._set_repo_list_label(i, label)
                break

    def on_details_key_down(self, event: wx.KeyEvent) -> None:
        """Pass key events through — comment navigation is handled via Alt+N/Alt+P menu accelerators."""
        event.Skip()

    def on_next_comment(self, event: wx.CommandEvent) -> None:
        """Alt+N — jump to the next comment in the details box."""
        self._navigate_comment(1)

    def on_prev_comment(self, event: wx.CommandEvent) -> None:
        """Alt+P — jump to the previous comment in the details box."""
        self._navigate_comment(-1)

    def _navigate_comment(self, direction: int) -> None:
        """Move to the next (1) or previous (-1) comment in the details box."""
        if not self._comment_positions:
            self._announce("No comments to navigate.")
            return
        new_idx = self._current_comment + direction
        if new_idx < 0:
            self._announce("Already at first comment.")
            return
        if new_idx >= len(self._comment_positions):
            self._announce("Already at last comment.")
            return
        self._current_comment = new_idx
        line, length = self._comment_positions[new_idx]
        start_pos = self._line_to_position(line)
        end_pos = self._line_to_position(line + length)
        self.details_text.SetFocus()
        self.details_text.SetSelection(start_pos, end_pos)
        self.details_text.ShowPosition(start_pos)
        total = len(self._comment_positions)
        self._announce(f"Comment {new_idx + 1} of {total}")

    def _line_to_position(self, line: int) -> int:
        """Convert a 0-based line index to a character position in the TextCtrl."""
        text = self.details_text.GetValue()
        pos = 0
        current_line = 0
        for ch in text:
            if current_line >= line:
                break
            if ch == '\n':
                current_line += 1
            pos += 1
        return pos

    # ── Menu actions ────────────────────────────────────────────────────

    def on_refresh(self, event: wx.CommandEvent) -> None:
        if self.view_mode == VIEW_FAVORITES:
            self._load_favorites_view()
        elif self.repo or self.view_mode in FEED_VIEWS:
            self.current_limit = self.page_size  # reset to first page
            self._load_items()

    def on_view_more(self, event: wx.CommandEvent) -> None:
        """Increase the fetch limit and reload to show more items."""
        if self.view_mode == VIEW_ACTIVITY:
            if self._activity_more is None:
                self._announce("Activity is still loading.")
                return
            if not self._activity_more:
                self._announce(
                    "No older activity. GitHub keeps only your latest "
                    f"{ACTIVITY_MAX} events, from the last 90 days."
                )
                return
            # Land on the first of the older events, not back at the top.
            self._pending_focus_row = len(self._shown)
        elif self.view_mode == VIEW_NOTIFICATIONS:
            if self._notif_more is None:
                self._announce("Notifications are still loading.")
                return
            if not self._notif_more:
                self._announce("That is all your notifications.")
                return
            self._pending_focus_row = frozenset(x.id for x in self.git_items)
        elif self.view_mode in SEARCH_VIEWS:
            have = len(self._view_source())
            if have >= min(self._search_total, SEARCH_MAX):
                self._announce("That is every result GitHub gives for this search.")
                return
            # Only the next page, added to what is here.
            self._search_more = list(self._view_source())
            self._pending_focus_row = len(self._shown)
        elif self.view_mode == VIEW_MY_WORK:
            self._announce("My Work shows up to 100 of each kind. Search (Ctrl+Shift+F) "
                           "finds more.")
            return
        elif self.view_mode == VIEW_ORGS:
            self._announce("That is all your organizations.")
            return
        elif self.view_mode in REPO_LIST_VIEWS:
            if len(self.git_items) < self.current_limit:
                label = self._view_label(self.view_mode, lower=True)
                whose = "" if self.view_mode in (VIEW_ORG, VIEW_SHARED) else "your "
                self._announce(f"That is all {whose}{label}.")
                return
            self._pending_focus_row = len(self._shown)
        elif not self.repo:
            return
        self.current_limit += self.page_size
        self._load_items()

    def on_open_browser(self, event: wx.CommandEvent) -> None:
        item = self._focused_item()
        if not item:
            return
        if isinstance(item, ActivityEvent):
            self._open_event(item)
            return
        if isinstance(item, Notification):
            self._open_notification(item, in_browser=True)
            return
        url = getattr(item, "url", "") or ""
        if url:
            webbrowser.open(url)
            if isinstance(item, FavoriteEntry):
                self._announce(f"Opened {item.title} in browser")
            else:
                label = getattr(item, "number", None) or getattr(item, "name", "") or getattr(item, "short_sha", "")
                self._announce(f"Opened {label} in browser")
        else:
            self._announce("No URL for this item")

    def on_close_item(self, event: wx.CommandEvent) -> None:
        self._do_close()

    def on_reopen(self, event: wx.CommandEvent) -> None:
        self._do_reopen()

    def on_comment(self, event: wx.CommandEvent) -> None:
        self._do_comment()

    def on_open_repo(self, event: wx.CommandEvent) -> None:
        """Ctrl+Shift+O — open a repository, or anything in one, by its address.

        Takes OWNER/NAME or any github.com address. An issue, pull request,
        commit, release, workflow run or branch address opens the repository
        on the view that shows it, with it selected. A GitHub address already
        on the clipboard is offered, so pasting from an email is one Enter.
        """
        dlg = wx.TextEntryDialog(
            self,
            "Enter a GitHub address or OWNER/NAME.\n"
            "Repository, issue, pull request, commit, release, workflow run "
            "and branch addresses open in GHManage.",
            "Open Repository or Address",
            self._clipboard_github_url(),
        )
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            value = dlg.GetValue().strip()
        finally:
            dlg.Destroy()
        if value:
            self._open_address(value)

    def _clipboard_github_url(self) -> str:
        """The first github.com address on the clipboard, or "".

        Quiet whatever the clipboard holds: another program may have it open,
        or it may hold a picture, and on Windows wx reports either with an
        error box of its own unless logging is suppressed.
        """
        try:
            with wx.LogNull():
                clip = wx.TheClipboard
                if not clip.Open():
                    return ""
                try:
                    if not clip.IsSupported(wx.DataFormat(wx.DF_UNICODETEXT)) and \
                            not clip.IsSupported(wx.DataFormat(wx.DF_TEXT)):
                        return ""
                    data = wx.TextDataObject()
                    if not clip.GetData(data):
                        return ""
                    text = data.GetText()
                finally:
                    clip.Close()
        except Exception:  # noqa: BLE001 — a convenience; never stop the dialog
            return ""
        return first_github_url(text)

    def _open_address(self, value: str) -> None:
        target = parse_github_url(value)
        if target is None:
            self._announce("Couldn't read that. Use a github.com address or OWNER/NAME.")
            return
        if target.kind == "user":
            self._announce(
                f"{target.ref} is a person or organisation, not a repository. "
                "GHManage can't show profiles yet."
            )
            return
        repo = target.repo
        if target.kind == "inside":
            # A file, the wiki, a discussion: no view of its own here, so the
            # repository opens — without pinning, as for any link opened
            # from an email.
            self._select_repo(repo)
            self._select_in_repo_list(repo)
            wx.CallLater(150, self._announce,
                         f"GHManage has no view for that page, so {repo} is open on its issues.")
            return
        if target.kind == "repo":
            # Pin it so it shows in the left list across sessions. Only a
            # repository's own address does this: links to single issues,
            # opened from email, would otherwise fill the list.
            self._pinned_repos = add_pinned(repo)
            self._refresh_repo_list()
            self._select_repo(repo)
            return
        view = {
            "item": VIEW_ISSUES,
            "commit": VIEW_COMMITS,
            "branch": VIEW_COMMITS,
            "release": VIEW_RELEASES,
            "run": VIEW_WORKFLOW,
        }.get(target.kind, target.ref if target.kind == "view" else VIEW_ISSUES)
        if view == VIEW_COMMITS:
            # Set before the switch, which loads the commits of commit_branch:
            # the branch named, or the default branch for a commit address.
            self.commit_branch = target.ref if target.kind == "branch" else ""
        self._select_repo(repo, view)
        if target.kind in ("item", "commit", "release", "run"):
            self._set_pending_target(view, target.kind, target.ref)
        self._select_in_repo_list(repo)

    def _select_in_repo_list(self, repo: str) -> None:
        """Select ``repo`` in the repository list when it is there, else nothing.

        Not case-sensitive: GitHub isn't, and an address typed or pasted
        need not match the case the list shows.
        """
        self.repo_list.SetSelection(wx.NOT_FOUND)
        wanted = repo.lower()
        for i in range(self.repo_list.GetCount()):
            data = self.repo_list.GetClientData(i)
            if isinstance(data, str) and data.lower() == wanted:
                self.repo_list.SetSelection(i)
                break

    def on_remove_repo(self, event: wx.CommandEvent) -> None:
        """Remove the currently selected repo from the pinned list."""
        idx = self.repo_list.GetSelection()
        if idx == wx.NOT_FOUND:
            self._announce("Select a repository in the list first.")
            return
        name = self.repo_list.GetClientData(idx)
        if not name:
            return
        if name == FAVORITES_ENTRY or name in ENTRY_VIEWS:
            self._announce("That entry is always in the list.")
            return
        if name.startswith(SEARCH_ENTRY_PREFIX):
            label = name[len(SEARCH_ENTRY_PREFIX):]
            self.saved_searches = remove_saved_search(label)
            self._refresh_repo_list()
            self._announce(f"Removed the saved search '{label}'.")
            return
        if name not in self._pinned_repos:
            self._announce(
                f"{name} comes from your GitHub account and can't be removed from here."
            )
            return
        self._pinned_repos = remove_pinned(name)
        self._refresh_repo_list()
        self._announce(f"Removed {name} from the pinned list.")

    def _refresh_repo_list(self) -> None:
        """Rebuild the repo list from cached gh results + current pinned repos."""
        self._on_repos_loaded(self._all_repos)

    def on_goto(self, event: wx.CommandEvent) -> None:
        """Ctrl+G — open a dialog to jump to a specific issue/PR by number."""
        if self.view_mode != VIEW_ISSUES:
            self._announce("Go To is only available in Issues & PRs view.")
            return
        if not self.items:
            self._announce("No items loaded. Load a repository first.")
            return
        dlg = wx.NumberEntryDialog(
            self,
            "Enter the issue or PR number:",
            "Go To Issue #",
            "Go To Issue",
            1,
            1,
            1000000,
        )
        if dlg.ShowModal() == wx.ID_OK:
            number = dlg.GetValue()
            self._goto_issue(number)
        dlg.Destroy()

    def on_filter(self, event: wx.CommandEvent) -> None:
        """Ctrl+F — quick filter the current list by text across all columns."""
        dlg = wx.TextEntryDialog(
            self,
            "Filter the current list (case-insensitive).\n"
            "Matches against all visible columns.\n"
            "Leave empty to clear the filter.",
            "Quick Filter",
            self.filter_text,
        )
        if dlg.ShowModal() == wx.ID_OK:
            self.filter_text = dlg.GetValue().strip()
            self._refresh_list_display()
            if self.filter_text:
                self._announce(f"Filter: '{self.filter_text}' applied")
            else:
                self._announce("Filter cleared")
        dlg.Destroy()

    def _clear_filter(self) -> None:
        """Clear the quick filter and refresh the display."""
        if not self.filter_text:
            self._announce("No filter active.")
            return
        self.filter_text = ""
        self._refresh_list_display()
        self._announce("Filter cleared")

    def _matches_filter(self, item) -> bool:
        """Return True if the item matches the current filter text (or no filter)."""
        if not self.filter_text:
            return True
        needle = self.filter_text.lower()
        if isinstance(item, FavoriteEntry):
            haystack = " ".join([
                item.item_type, item.repo, item.title, item.subtitle,
            ]).lower()
            return needle in haystack
        row = item.to_row(self.columns)
        haystack = " ".join(str(v) for v in row.values()).lower()
        return needle in haystack

    def _filtered_items(self) -> list:
        """Return the filtered list for the current view mode."""
        if self.view_mode in ITEM_VIEWS:
            return [it for it in self.items if self._matches_filter(it)]
        elif self.view_mode == VIEW_FAVORITES:
            return [fav for fav in self.favorites if self._matches_filter(fav)]
        else:
            return [it for it in self.git_items if self._matches_filter(it)]

    def _update_filter_status(self) -> None:
        """Show the filter state in the status bar, or take it off when none."""
        if not self.filter_text:
            self.status_bar.set_item("filter", "")
            return
        total = len(self.items) if self.view_mode in ITEM_VIEWS else (
            len(self.favorites) if self.view_mode == VIEW_FAVORITES else len(self.git_items)
        )
        shown = len(self._filtered_items())
        self.status_bar.set_item("filter", f"Filter: '{self.filter_text}' ({shown}/{total})")

    def _goto_issue(self, number: int) -> None:
        """Select the item with the given number and focus the details box.

        If the item isn't in the currently loaded list (e.g. it's closed, or
        beyond the fetch limit), it's fetched on-demand via ``gh`` and inserted
        into the list so the user can still view it.
        """
        for item in self.items:
            if item.number == number:
                row = self._row_of(item)
                if row < 0:
                    # Hidden by the quick filter: drop it rather than jump
                    # to a row that isn't there.
                    self.filter_text = ""
                    self._populate_filtered_list(self.items, use_favorite_prefix=True)
                    row = self._row_of(item)
                self.list_ctrl.SetFocus()
                self.list_ctrl.Select(row, on=True)
                self.list_ctrl.Focus(row)
                self._show_details(row)
                # Move focus to the details box so user can read/navigate comments
                wx.CallLater(100, self.details_text.SetFocus)
                self._announce(f"Jumped to #{number} — {item.title}")
                return
        if self.view_mode != VIEW_ISSUES or not self.repo:
            return  # left the issues list before this ran (it may be scheduled)
        # Not in the current list — fetch it on-demand in the background
        self._announce(f"#{number} not in current list, fetching…")
        # Read here, on the UI thread: by the time the worker runs, another
        # repository may be open, and its #number is a different item.
        repo = self.repo

        def worker() -> None:
            try:
                item = fetch_item_by_number(number, repo)
            except GhError as exc:
                wx.CallAfter(self._goto_error, number, str(exc))
                return
            except Exception as exc:
                # Anything escaping here kills the thread silently and leaves
                # the status on "fetching…" for good. A bare str() of, say, a
                # KeyError is just "'number'", so name the kind of error too.
                wx.CallAfter(self._goto_error, number,
                             f"Unexpected error ({type(exc).__name__}: {exc})")
                return
            wx.CallAfter(self._on_goto_fetched, item, number, repo)

        threading.Thread(target=worker, daemon=True).start()

    def _goto_error(self, number: int, msg: str) -> None:
        """Show an error dialog when a Go To fetch fails."""
        self._announce(f"Error fetching #{number}: {msg}")
        wx.MessageBox(
            f"Could not fetch #{number}:\n{msg}",
            "Go To Error",
            wx.OK | wx.ICON_WARNING,
            self,
        )

    def _on_goto_fetched(self, item: Optional[Item], number: int,
                         repo: Optional[str] = None) -> None:
        """Called when an on-demand fetch for Go To completes."""
        # Go To inserts into the issues list. If the view or the repository
        # moved on while the fetch was running, that list is not what is on
        # screen any more.
        if self.view_mode != VIEW_ISSUES or (repo is not None and repo != self.repo):
            self._announce(f"Left the issues list before #{number} arrived.")
            return
        if item is None:
            self._announce(f"#{number} not found in {self.repo}.")
            wx.MessageBox(
                f"#{number} does not exist as an issue or PR in {self.repo}.",
                "Not Found",
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            return
        # Insert the fetched item into the list and select it
        self.items.append(item)
        self.items = sort_items(self.items, self.sort_order)
        idx = next((i for i, it in enumerate(self.items) if it.number == number), -1)
        if idx < 0:
            self._announce(f"#{number} could not be added to the list.")
            return
        # Rebuild the list ctrl to reflect the new sorted order. The filter
        # goes: the item asked for by number has to be in the list.
        self.filter_text = ""
        self._populate_filtered_list(self.items, use_favorite_prefix=True)
        row = self._row_of(self.items[idx])
        self.list_ctrl.SetFocus()
        self.list_ctrl.Select(row, on=True)
        self.list_ctrl.Focus(row)
        self._show_details(row)
        wx.CallLater(100, self.details_text.SetFocus)
        self._announce(f"Jumped to #{number} — {item.title}")

    def on_select_branch(self, event: wx.CommandEvent) -> None:
        """Ctrl+B — select which branch to view commits for."""
        if self.view_mode != VIEW_COMMITS:
            self._announce("Select Branch is only available in Commits view.")
            return
        if not self.repo:
            self._announce("No repository loaded.")
            return
        # Fetch branch names in background, then show a selection dialog
        self._announce("Loading branches…")

        def worker() -> None:
            try:
                branches = fetch_branches(self.repo, 200)
                names = [b.name for b in branches]
                wx.CallAfter(self._show_branch_picker, names)
            except GhError as exc:
                wx.CallAfter(self._on_items_error, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _show_branch_picker(self, names: list[str]) -> None:
        """Show a dialog to pick a branch for the commits view."""
        if not names:
            self._announce("No branches found.")
            return
        current = self.commit_branch if self.commit_branch else names[0]
        dlg = wx.SingleChoiceDialog(
            self,
            "Select a branch to view commits:",
            "Select Branch",
            names,
        )
        # Try to pre-select the current branch
        if current in names:
            dlg.SetSelection(names.index(current))
        if dlg.ShowModal() == wx.ID_OK:
            selected = dlg.GetStringSelection()
            dlg.Destroy()
            if selected and selected != self.commit_branch:
                self.commit_branch = selected
                self.current_limit = self.page_size
                self._load_items()
                self._announce(f"Showing commits on branch {selected}")
        else:
            dlg.Destroy()

    def on_compare_branches(self, event: wx.CommandEvent) -> None:
        """Ctrl+Shift+B — compare two branches (ahead/behind, commits, files)."""
        if not self.repo:
            self._announce("No repository loaded.")
            return
        # Fetch branch names in the background, then run the pickers.
        self._announce("Loading branches for comparison…")

        def worker() -> None:
            try:
                branches = fetch_branches(self.repo, 200)
                names = [b.name for b in branches]
                wx.CallAfter(self._show_compare_pickers, names)
            except GhError as exc:
                wx.CallAfter(self._on_items_error, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _show_compare_pickers(self, names: list[str]) -> None:
        """Pick the base and head branches via two accessible dialogs."""
        if not names:
            self._announce("No branches found to compare.")
            return
        if len(names) < 2:
            self._announce("Need at least two branches to compare.")
            return

        # Sensible defaults: head = the branch currently focused (if any),
        # base = the first branch (usually the repo's default branch).
        focused = self._focused_item()
        head_default = focused.name if isinstance(focused, Branch) else names[1]

        # Step 1 — base branch (compare FROM).
        base_dlg = wx.SingleChoiceDialog(
            self,
            "Step 1 of 2 — choose the BASE branch (compare FROM, e.g. main):",
            "Compare Branches — Base",
            names,
        )
        base_dlg.SetSelection(0)
        if base_dlg.ShowModal() != wx.ID_OK:
            base_dlg.Destroy()
            self._announce("Compare cancelled.")
            return
        base = base_dlg.GetStringSelection()
        base_dlg.Destroy()

        # Step 2 — head branch (compare TO).
        head_dlg = wx.SingleChoiceDialog(
            self,
            f"Step 2 of 2 — choose the HEAD branch to compare against '{base}' "
            "(compare TO):",
            "Compare Branches — Head",
            names,
        )
        if head_default in names:
            head_dlg.SetSelection(names.index(head_default))
        if head_dlg.ShowModal() != wx.ID_OK:
            head_dlg.Destroy()
            self._announce("Compare cancelled.")
            return
        head = head_dlg.GetStringSelection()
        head_dlg.Destroy()

        if base == head:
            self._announce("Base and head are the same branch — nothing to compare.")
            wx.MessageBox(
                "Pick two different branches to compare.",
                "Compare Branches",
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            return
        self._run_compare(base, head)

    def _run_compare(self, base: str, head: str) -> None:
        """Fetch the comparison in the background and show the result."""
        self._announce(f"Comparing {base}…{head}…")

        def worker() -> None:
            try:
                result = fetch_compare(self.repo, base, head)
                wx.CallAfter(self._show_compare_result, result)
            except GhError as exc:
                wx.CallAfter(self._on_items_error, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _show_compare_result(self, result: CompareResult) -> None:
        """Display a branch comparison in an accessible, focusable text dialog."""
        text = self._format_compare(result)
        summary = (
            f"identical to '{result.base}'"
            if result.ahead_by == 0 and result.behind_by == 0
            else f"{result.ahead_by} ahead, {result.behind_by} behind '{result.base}'"
        )
        self._announce(f"'{result.head}' is {summary}.")
        self._show_text_dialog(
            f"Compare: {result.base} … {result.head}", text
        )

    def _format_compare(self, r: CompareResult) -> str:
        """Render a CompareResult as readable, screen-reader-friendly text."""
        sep = "─" * 60
        lines = [
            f"Comparing branches in {self.repo or 'this repository'}",
            "",
            f"Base (compare from): {r.base}",
            f"Head (compare to):   {r.head}",
            "",
        ]
        if r.ahead_by == 0 and r.behind_by == 0:
            lines.append(f"'{r.head}' and '{r.base}' are identical — no differences.")
            return "\n".join(lines)
        lines += [
            f"'{r.head}' is {r.ahead_by} commit(s) AHEAD of '{r.base}' "
            f"and {r.behind_by} commit(s) BEHIND.",
            "",
            f"  Ahead {r.ahead_by}: commits on '{r.head}' not on '{r.base}'.",
            f"  Behind {r.behind_by}: commits on '{r.base}' not on '{r.head}'.",
            "",
            sep,
        ]
        shown = len(r.commits)
        if r.ahead_by > shown:
            lines.append(f"Commits added on '{r.head}' (showing {shown} of {r.ahead_by}):")
        else:
            lines.append(f"Commits added on '{r.head}' ({shown}):")
        lines.append(sep)
        if r.commits:
            for c in r.commits:
                sha = (c.get("sha") or "")[:8]
                msg = c.get("message") or ""
                first_line = msg.splitlines()[0] if msg else ""
                lines.append(f"  {sha}  {first_line}")
        else:
            lines.append("  (none)")
        lines += ["", sep]
        total_add = sum(f.get("additions", 0) for f in r.files)
        total_del = sum(f.get("deletions", 0) for f in r.files)
        lines.append(f"Files changed ({len(r.files)}):")
        lines.append(sep)
        if r.files:
            for f in r.files:
                status = f.get("status", "")
                fname = f.get("filename", "")
                adds = f.get("additions", 0)
                dels = f.get("deletions", 0)
                lines.append(f"  {status}: {fname} (+{adds} -{dels})")
            if len(r.files) >= 100:
                lines.append("  … (file list capped at 100)")
            lines += ["", f"Total: +{total_add} -{total_del} across {len(r.files)} file(s)"]
        else:
            lines.append("  (none)")
        return "\n".join(lines)

    def _show_text_dialog(self, title: str, text: str, start_line: int = 0) -> None:
        """Show read-only, focusable, scrollable text in a modal dialog.

        Used for content a screen reader needs to navigate line by line
        (e.g. a branch comparison). The text control receives focus so the
        user lands directly on the content.
        """
        dlg = wx.Dialog(
            self, title=title,
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            size=(680, 500),
        )
        sizer = wx.BoxSizer(wx.VERTICAL)
        txt = wx.TextCtrl(
            dlg, value=text,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
        )
        txt.SetName(title)
        sizer.Add(txt, 1, wx.EXPAND | wx.ALL, 8)
        btn_sizer = dlg.CreateButtonSizer(wx.OK)
        if btn_sizer:
            sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 8)
        dlg.SetSizer(sizer)
        wx.CallAfter(txt.SetFocus)
        # After focus, or some platforms put the caret back at the start. By
        # line, which the control converts in its own units.
        def place() -> None:
            pos = txt.XYToPosition(0, start_line) if start_line else 0
            pos = max(pos, 0)
            txt.SetInsertionPoint(pos)
            txt.ShowPosition(pos)
        wx.CallAfter(place)
        dlg.ShowModal()
        dlg.Destroy()

    def on_quit(self, event: wx.CommandEvent) -> None:
        # A downloaded update is left staged: updater.bootstrap() applies it on
        # the next launch, before any window appears. Applying here instead
        # would mean racing our own shutdown for a lock on the install dir.
        self.Destroy()

    # ── View menu actions ───────────────────────────────────────────────

    def on_quick_mode(self, event: wx.CommandEvent) -> None:
        self.list_mode = "quick"
        self._update_menu_checks()
        self._update_mode_status()
        self._announce("Quick mode: compact display")
        if self.items or self.git_items:
            self._refresh_list_display()

    def on_full_mode(self, event: wx.CommandEvent) -> None:
        self.list_mode = "full"
        self._update_menu_checks()
        self._update_mode_status()
        self._announce("Full mode: field names included for screen reader")
        if self.items or self.git_items:
            self._refresh_list_display()

    def on_sort_selected(self, event: wx.CommandEvent) -> None:
        if self.view_mode == VIEW_MY_WORK:
            self._update_menu_checks()
            self._announce("My Work is grouped by why it needs you, so it isn't sorted.")
            return
        if self.view_mode in SEARCH_VIEWS:
            self._update_menu_checks()
            self._announce("Search results are in GitHub's order, best match first. To sort, "
                           "add a qualifier such as sort:updated-desc to the search.")
            return
        self.sort_order = self._sort_menu_items.get(event.GetId(), SORT_ORDERS[0])
        self._update_menu_checks()
        if self.items:
            self.items = sort_items(self.items, self.sort_order)
            self._refresh_list_display()

    def on_column_toggled(self, event: wx.CommandEvent) -> None:
        col = self._col_menu_items.get(event.GetId())
        if not col:
            return
        if col in self.columns:
            self.columns.remove(col)
        else:
            self.columns.append(col)
        self._update_menu_checks()
        self._rebuild_columns()
        self._refresh_list_display()

    def on_state_open(self, event: wx.CommandEvent) -> None:
        self.state_filter = "open"
        self._update_menu_checks()
        if self.repo:
            self.current_limit = self.page_size
            self._load_items()

    def on_state_closed(self, event: wx.CommandEvent) -> None:
        self.state_filter = "closed"
        self._update_menu_checks()
        if self.repo:
            self.current_limit = self.page_size
            self._load_items()

    def on_state_all(self, event: wx.CommandEvent) -> None:
        self.state_filter = "all"
        self._update_menu_checks()
        if self.repo:
            self.current_limit = self.page_size
            self._load_items()

    def on_tab_issues(self, event: wx.CommandEvent) -> None:
        self.tab_filter = "issues"
        self._update_menu_checks()
        if self.repo:
            self.current_limit = self.page_size
            self._load_items()

    def on_tab_prs(self, event: wx.CommandEvent) -> None:
        self.tab_filter = "prs"
        self._update_menu_checks()
        if self.repo:
            self.current_limit = self.page_size
            self._load_items()

    def on_tab_both(self, event: wx.CommandEvent) -> None:
        self.tab_filter = "both"
        self._update_menu_checks()
        if self.repo:
            self.current_limit = self.page_size
            self._load_items()

    # ── View mode switching (Show submenu) ──────────────────────────────

    def on_view_issues(self, event: wx.CommandEvent) -> None:
        # Asking for Issues & PRs by name means all of them: drop any label
        # drill-down, including when that leaves the view mode unchanged.
        if self.view_mode == VIEW_ISSUES:
            if self.label_filter:
                self.label_filter = ""
                self.current_limit = self.page_size
                self._load_items()
                self._announce("Showing all issues and PRs")
            return
        self.label_filter = ""
        self._switch_view(VIEW_ISSUES)

    def on_view_branches(self, event: wx.CommandEvent) -> None:
        self._switch_view(VIEW_BRANCHES)

    def on_view_commits(self, event: wx.CommandEvent) -> None:
        self._switch_view(VIEW_COMMITS)

    def on_view_tags(self, event: wx.CommandEvent) -> None:
        self._switch_view(VIEW_TAGS)

    def on_view_releases(self, event: wx.CommandEvent) -> None:
        self._switch_view(VIEW_RELEASES)

    def on_view_workflows(self, event: wx.CommandEvent) -> None:
        self._switch_view(VIEW_WORKFLOWS)

    def on_view_workflow(self, event: wx.CommandEvent) -> None:
        self._switch_view(VIEW_WORKFLOW)

    def on_view_labels(self, event: wx.CommandEvent) -> None:
        self._switch_view(VIEW_LABELS)

    def on_view_favorites(self, event: wx.CommandEvent) -> None:
        self._select_favorites()

    def on_view_pages(self, event: wx.CommandEvent) -> None:
        self._switch_view(VIEW_PAGES)

    def on_view_activity(self, event: wx.CommandEvent) -> None:
        self._select_category(VIEW_ACTIVITY)

    def on_view_notifications(self, event: wx.CommandEvent) -> None:
        self._select_category(VIEW_NOTIFICATIONS)

    def on_view_starred(self, event: wx.CommandEvent) -> None:
        self._select_category(VIEW_STARRED)

    def on_view_watched(self, event: wx.CommandEvent) -> None:
        self._select_category(VIEW_WATCHED)

    def on_view_shared(self, event: wx.CommandEvent) -> None:
        self._select_category(VIEW_SHARED)

    def on_view_orgs(self, event: wx.CommandEvent) -> None:
        self._select_category(VIEW_ORGS)

    # ── List display refresh ───────────────────────────────────────────

    def _refresh_list_display(self) -> None:
        """Re-populate the list from current data without re-fetching."""
        if self.view_mode == VIEW_FAVORITES:
            self._load_favorites_view()
            return
        items = self.items if self.view_mode in ITEM_VIEWS else self.git_items
        filtered = self._populate_filtered_list(items, use_favorite_prefix=True)
        if filtered:
            wx.CallLater(100, self._focus_list)

    # ── Actions ─────────────────────────────────────────────────────────

    def _do_close(self) -> None:
        item = self._focused_item()
        if not item:
            return
        kind = "PR" if item.is_pr else "issue"
        confirm = wx.MessageBox(
            f"Close {kind} #{item.number}?\n\n{item.title}",
            "Confirm Close",
            wx.YES_NO | wx.ICON_QUESTION,
            self,
        )
        if confirm != wx.YES:
            return
        self._announce(f"Closing #{item.number}…")

        def worker() -> None:
            try:
                close_item(item, self.repo)
                wx.CallAfter(self._on_action_done, f"Closed #{item.number}")
            except GhError as exc:
                wx.CallAfter(self._on_action_error, f"Error closing #{item.number}: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _do_reopen(self) -> None:
        item = self._focused_item()
        if not item:
            return
        kind = "PR" if item.is_pr else "issue"
        confirm = wx.MessageBox(
            f"Reopen {kind} #{item.number}?\n\n{item.title}",
            "Confirm Reopen",
            wx.YES_NO | wx.ICON_QUESTION,
            self,
        )
        if confirm != wx.YES:
            return
        self._announce(f"Reopening #{item.number}…")

        def worker() -> None:
            try:
                reopen_item(item, self.repo)
                wx.CallAfter(self._on_action_done, f"Reopened #{item.number}")
            except GhError as exc:
                wx.CallAfter(self._on_action_error, f"Error reopening #{item.number}: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _do_comment(self) -> None:
        item = self._focused_item()
        if not item:
            return
        dlg = wx.TextEntryDialog(
            self,
            f"Add a comment to #{item.number}:\n{item.title}",
            "Add Comment",
            "",
            style=wx.TE_MULTILINE | wx.OK | wx.CANCEL,
        )
        if dlg.ShowModal() == wx.ID_OK:
            comment = dlg.GetValue().strip()
            if not comment:
                return
            self._announce(f"Adding comment to #{item.number}…")

            def worker() -> None:
                try:
                    add_comment(item, comment, self.repo)
                    wx.CallAfter(self._on_action_done, f"Comment added to #{item.number}")
                except GhError as exc:
                    wx.CallAfter(self._on_action_error, f"Error commenting #{item.number}: {exc}")

            threading.Thread(target=worker, daemon=True).start()
        dlg.Destroy()

    def on_new_issue(self, event: wx.CommandEvent) -> None:
        self._new_issue_in_front()

    def _new_issue_in_front(self) -> None:
        """Actions ▸ New Issue (Ctrl+N), for the repository in front of you.

        Already on that repository's issues, or in another of its views, the
        issue is created there, as before. Anywhere else the repository is
        opened on its issues first, so the new issue lands in a list you can
        see: from a row of Notifications, My Work, Activity, search results,
        Starred or Watched by the same path as Enter, so Backspace comes back;
        from the repository list or Favorites, as choosing it there would.
        """
        if self._issue_busy:
            # Before any switching: moving away would also cost the issue
            # being created its landing in the list.
            self._announce("Already creating an issue — wait for it to finish.")
            return
        repo, source = self._repo_in_front_from()
        if not repo:
            self._announce("Select a repository first: New Issue needs one.")
            return
        here = repo == self.repo and self.view_mode not in REPOLESS_VIEWS
        if here and (source == "open" or self.view_mode == VIEW_ISSUES):
            self._do_new_issue()
            return
        if source == "row" and self.view_mode != VIEW_FAVORITES:
            self._open_repo_from_list(repo, self._focused_item())
        else:
            self._select_repo(repo)
        self._do_new_issue()

    def _do_new_issue(self) -> None:
        """New Issue (Ctrl+N, or N in the issues list).

        The dialog names the repo the issue will go to, which on a fork is the
        upstream — that takes a gh call, so it is made first, off the UI thread.
        """
        if not self.repo or self.view_mode in REPOLESS_VIEWS:
            self._announce("Select a repository first.")
            return
        if self._issue_busy:
            self._announce("Already creating an issue — wait for it to finish.")
            return
        self._issue_busy = True
        repo = self.repo
        self._announce("Preparing a new issue…")

        def worker() -> None:
            try:
                target = parent_repo(repo) or repo
            except Exception:  # noqa: BLE001 — never leave Ctrl+N stuck "busy"
                target = repo
            wx.CallAfter(self._show_new_issue_dialog, repo, target)

        threading.Thread(target=worker, daemon=True).start()

    def _show_new_issue_dialog(self, repo: str, target: str) -> None:
        if self.repo != repo:
            self._issue_busy = False
            return  # moved to another repository while it was looked up
        title, body = self._issue_drafts.get(repo, ("", ""))
        submitted_from = self.view_mode
        try:
            dlg = NewIssueDialog(self, target, title, body)
            try:
                ok = dlg.ShowModal() == wx.ID_OK
                title, body = dlg.values()
            finally:
                dlg.Destroy()
        except Exception:
            self._issue_busy = False
            raise
        if not ok:
            self._issue_busy = False
            if title or body:
                self._issue_drafts[repo] = (title, body)
                self._announce("New issue cancelled. What you typed is kept for next time.")
            else:
                self._issue_drafts.pop(repo, None)
                self._announce("New issue cancelled.")
            return
        self._issue_drafts[repo] = (title, body)  # until GitHub has it
        self._announce(f"Creating issue in {target}…")

        def worker() -> None:
            try:
                number, _url = create_issue(repo, title, body, effective=target)
            except IssueCreatedUnreadable:
                # It exists; only its number is unknown. Treat as created —
                # keeping the draft would invite filing it a second time.
                wx.CallAfter(self._on_issue_created, repo, 0, title, submitted_from)
                return
            except GhError as exc:
                wx.CallAfter(self._on_issue_error, str(exc))
                return
            except Exception as exc:  # noqa: BLE001 — never leave "Creating…" hanging
                wx.CallAfter(self._on_issue_error, f"{type(exc).__name__}: {exc}")
                return
            wx.CallAfter(self._on_issue_created, repo, number, title, submitted_from)

        threading.Thread(target=worker, daemon=True).start()

    def _on_issue_error(self, msg: str) -> None:
        self._issue_busy = False
        kept = bool(self._issue_drafts)  # gone if the account was switched meanwhile
        tail = " What you typed is kept; Ctrl+N opens it again." if kept else ""
        self._announce(f"Couldn't create the issue: {msg}{tail}")
        wx.MessageBox(
            f"The issue was not created.\n\n{msg}"
            + ("\n\nWhat you typed is kept. Press Ctrl+N to try again." if kept else ""),
            "New Issue", wx.OK | wx.ICON_WARNING, self,
        )

    def _on_issue_created(self, repo: str, number: int, title: str,
                          submitted_from: str = VIEW_ISSUES) -> None:
        self._issue_busy = False
        self._issue_drafts.pop(repo, None)
        said = f"Created issue #{number} — {title}" if number else f"Created issue: {title}"
        # Show it — the issues list, reloaded, landing on the new one — but
        # only if you are where you were when you made it. Having moved on
        # since, you are left there.
        if self.repo != repo or self.view_mode != submitted_from:
            self._announce(said)
            return
        self.filter_text = ""  # the new issue must not be hidden by it
        if self.view_mode != VIEW_ISSUES:
            self._switch_view(VIEW_ISSUES)
        else:
            self.current_limit = self.page_size
            self._load_items()
        if number:
            self._set_pending_target(VIEW_ISSUES, "item", str(number))
        self._announce(said)

    def _on_action_done(self, msg: str) -> None:
        self._announce(f"{msg}. Refreshing…")
        self._load_items()

    def _on_action_error(self, msg: str) -> None:
        self._announce(msg)

    # ── Notifications ───────────────────────────────────────────────────

    def _focused_notification(self) -> Notification | None:
        item = self._focused_item()
        if self.view_mode == VIEW_NOTIFICATIONS and isinstance(item, Notification):
            return item
        self._announce("Select a notification first.")
        return None

    def _open_notification(self, note: Notification, in_browser: bool = False) -> None:
        """Enter: an issue or pull request opens here, anything else on GitHub.

        Either way it is marked read, as reading it on github.com would.
        """
        if note.unread:
            self._run_notification_change(note, "read")
        if note.is_item and not in_browser:
            self._open_item_here(note)
            return
        if note.subject_type == "Release" and note.api_url:
            # Its own page needs its tag, which only GitHub can tell us.
            self._announce(f"Opening {note.title}…")

            def worker() -> None:
                url = release_page(note.api_url) or note.url
                wx.CallAfter(webbrowser.open, url)
                wx.CallAfter(self._announce, f"Opened {note.title} in browser")

            threading.Thread(target=worker, daemon=True).start()
            return
        if note.url:
            webbrowser.open(note.url)
            self._announce(f"Opened {note.title} in browser")
        else:
            self._announce("No address for this notification.")

    def _mark_notification_read(self) -> None:
        note = self._focused_notification()
        if note is None:
            return
        if not note.unread:
            self._announce("Already read.")
            return
        self._run_notification_change(note, "read", announce=True)

    def _mark_notification_done(self) -> None:
        note = self._focused_notification()
        if note is not None:
            self._run_notification_change(note, "done", announce=True)

    def _unsubscribe_notification(self) -> None:
        note = self._focused_notification()
        if note is not None:
            self._run_notification_change(note, "unsubscribe", announce=True)

    # By name, looked up when used: holding the functions themselves here
    # would bind them at import, past the reach of anything that patches them.
    _NOTIFICATION_CHANGES = {
        "read": ("mark_notification_read", "Marked read"),
        "done": ("mark_notification_done", "Done"),
        "unsubscribe": ("unsubscribe_notification",
                        "Unsubscribed — no more notifications for this thread "
                        "unless you comment or are mentioned"),
    }

    def _run_notification_change(self, note: Notification, change: str,
                                 announce: bool = False) -> None:
        """Mark read, done or unsubscribe, in the background, then show it."""
        name, said = self._NOTIFICATION_CHANGES[change]
        call = globals()[name]
        gen = getattr(self, "_account_gen", 0)

        def worker() -> None:
            try:
                call(note.id)
            except Exception as exc:  # noqa: BLE001 — GhError, or anything else
                wx.CallAfter(self._announce, f"Couldn't update the notification: {exc}")
                return
            wx.CallAfter(self._on_notification_changed, note, change,
                         f"{said}: {note.title}" if announce else "", gen)

        threading.Thread(target=worker, daemon=True).start()

    def _on_notification_changed(self, note: Notification, change: str, said: str,
                                 gen: int | None = None) -> None:
        """Show a change GitHub has accepted, wherever that thread is listed.

        Matched by id, not by object: a reload while the request was out
        brings new objects for the same threads, and the list you left to
        open one (kept for Backspace) has its own copy too.
        """
        if gen is not None and gen != getattr(self, "_account_gen", 0):
            return  # made as an account you have since switched away from
        copies = [n for n in self.git_items if isinstance(n, Notification) and n.id == note.id]
        if self._return_to and self._return_to[0] == VIEW_NOTIFICATIONS:
            copies += [n for n in self._return_to[1] if n.id == note.id]
        copies.append(note)
        if change in ("read", "done"):
            was_unread = any(n.unread for n in copies)
            for n in copies:
                n.unread = False
            if was_unread:
                self._adjust_unread_count(-1)
        if change == "done" and self._return_to and self._return_to[0] == VIEW_NOTIFICATIONS:
            view, items, *rest = self._return_to
            self._return_to = (view, [n for n in items if n.id != note.id], *rest)
        if said:
            self._announce(said)
        if self.view_mode != VIEW_NOTIFICATIONS:
            return
        row = self._row_of_id(note)
        if change == "done":
            # Gone from the inbox, so gone from the list; stay at the same place.
            self.git_items = [n for n in self.git_items if n.id != note.id]
            if row >= 0:
                selected = self.list_ctrl.GetFirstSelected()
                keep_focus = self._pane_index(self._current_focus()) != 1
                self._populate_filtered_list(self.git_items, use_favorite_prefix=True)
                if self._shown:
                    # Where you are now, moved up one if the row went from above.
                    target = selected - 1 if 0 <= row < selected else selected
                    target = min(max(target, 0), len(self._shown) - 1)
                    if keep_focus:
                        # Done from the details panel: stay in it.
                        self.list_ctrl.Select(target, on=True)
                        self.list_ctrl.Focus(target)
                        self._show_details(target)
                    else:
                        self._focus_list(target)
                else:
                    self.details_text.Clear()
        elif row >= 0:
            self._redraw_row(row, self._shown[row])
            if row == self.list_ctrl.GetFirstSelected():
                self._show_details(row)
        self._set_notifications_status()
        if said:
            self._announce(said)  # the status line above replaced it

    def _redraw_row(self, row: int, item) -> None:
        for j, col in enumerate(self.columns):
            text = self._item_label(item, col)
            if j == 0:
                text = self._favorite_prefix(item) + text
            self.list_ctrl.SetItem(row, j, text)

    def _adjust_unread_count(self, delta: int) -> None:
        n = self._category_counts.get(NOTIFICATIONS_ENTRY)
        if n is not None:
            self._category_counts[NOTIFICATIONS_ENTRY] = max(0, n + delta)
            self._refresh_category_labels()

    def _mark_all_read(self) -> None:
        if self.view_mode != VIEW_NOTIFICATIONS:
            self._announce("Switch to Notifications first (Ctrl+Shift+N).")
            return
        confirm = wx.MessageBox(
            "Mark every notification as read?\n\n"
            "This covers all of them on GitHub, not just those listed here.",
            "Mark All as Read",
            wx.YES_NO | wx.ICON_QUESTION,
            self,
        )
        if confirm != wx.YES:
            return
        self._announce("Marking all notifications read…")

        since = self._notif_loaded_at
        gen = self._account_gen

        def worker() -> None:
            try:
                mark_all_notifications_read(since)
            except GhError as exc:
                wx.CallAfter(self._announce, f"Couldn't mark them read: {exc}")
                return
            wx.CallAfter(self._on_all_read, gen)

        threading.Thread(target=worker, daemon=True).start()

    def _on_all_read(self, gen: int | None = None) -> None:
        """Show everything read, without asking GitHub again straight away.

        A large inbox is marked in the background (HTTP 202), so a reload
        now could bring back unread ones and contradict what was just said.
        """
        if gen is not None and gen != self._account_gen:
            return
        self._category_counts[NOTIFICATIONS_ENTRY] = 0
        self._refresh_category_labels()
        lists = [self.git_items if self.view_mode == VIEW_NOTIFICATIONS else []]
        if self._return_to and self._return_to[0] == VIEW_NOTIFICATIONS:
            lists.append(self._return_to[1])
        for notes in lists:
            for n in notes:
                if isinstance(n, Notification):
                    n.unread = False
        if self.view_mode == VIEW_NOTIFICATIONS:
            for row, item in enumerate(self._shown):
                self._redraw_row(row, item)
            self._set_notifications_status()
        self._announce("Marked all read. GitHub may take a moment to catch up; "
                       "R refreshes the list.")

    def _toggle_include_read(self) -> None:
        """I, or View ▸ Include Read Notifications."""
        self._include_read = not self._include_read
        self.GetMenuBar().Check(ID_SHOW_READ, self._include_read)
        if self.view_mode == VIEW_NOTIFICATIONS:
            self.current_limit = self.page_size
            self._load_items()
        self._announce("Including read notifications." if self._include_read
                       else "Unread notifications only.")

    # ── Search ──────────────────────────────────────────────────────────

    def _open_item_here(self, item) -> None:
        """An issue or PR from a list across repos, opened in its repo's issues.

        Not when its repository is a fork: the Issues view of a fork shows
        its upstream's issues (forks usually have none of their own), where
        #N is something else entirely. Those open on GitHub instead. Whether
        a repo is a fork costs a gh call, so the answer is kept.
        """
        if not item.repo:
            self._announce("No repository for this item.")
            return
        repo, number = item.repo, item.number
        cache = self.__dict__.setdefault("_fork_parent", {})
        if repo in cache:
            self._open_item_checked(item, cache[repo])
            return
        self._announce(f"Opening #{number} in {repo}…")

        def worker() -> None:
            wx.CallAfter(self._on_fork_checked, item, parent_repo(repo))

        threading.Thread(target=worker, daemon=True).start()

    def _on_fork_checked(self, item, parent) -> None:
        # parent_repo says None for "not a fork" and for "couldn't ask"; only
        # a fork is certain enough to keep for the rest of the session.
        if parent:
            self.__dict__.setdefault("_fork_parent", {})[item.repo] = parent
        self._open_item_checked(item, parent)

    def _open_item_checked(self, item, parent) -> None:
        if parent:
            webbrowser.open(item.url)
            self._announce(f"#{item.number} is in {item.repo}, a fork, whose issues GHManage "
                           f"shows from {parent}; opened it in your browser instead.")
            return
        self._open_repo_from_list(item.repo, item)
        self._set_pending_target(VIEW_ISSUES, "item", str(item.number))

    def _saved_search(self, name: str) -> SavedSearch | None:
        return next((s for s in self.saved_searches if s.name == name), None)

    def _search_flow(self, prefill: tuple[str, str] | None = None) -> None:
        """File ▸ Search GitHub (Ctrl+Shift+F)."""
        kind, query = prefill or self._search or (KIND_ISSUES, "")
        dlg = SearchDialog(self, kind, query, select=prefill is None)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            kind, query = dlg.values()
        finally:
            dlg.Destroy()
        self._run_search(kind, query)

    def _search_from_view_menu(self) -> None:
        # The radio item has checked itself; put it right if the search is
        # cancelled, by re-checking whatever is actually showing.
        self._search_flow()
        self._update_menu_checks()

    def _run_search(self, kind: str, query: str) -> None:
        self._search = (kind, query)
        self._search_total = 0
        self._search_more = None
        self._return_to = None
        if self.view_mode in SEARCH_VIEWS:
            # Nothing from the last search may be acted on while this one loads.
            self.items, self.git_items = [], []
        view = VIEW_SEARCH_REPOS if kind == KIND_REPOS else VIEW_SEARCH_ISSUES
        if self.view_mode == view:
            self.current_limit = self.page_size
            self.filter_text = ""
            self._load_items()
        else:
            self._switch_view(view)
        self._restore_repo_selection(None)

    def _save_search(self) -> None:
        """Actions ▸ Save Search (Ctrl+S): keep this search in the repo list."""
        if self.view_mode not in SEARCH_VIEWS or not self._search:
            self._announce("Run a search first (Ctrl+Shift+F).")
            return
        kind, query = self._search
        dlg = wx.TextEntryDialog(
            self, f"Name this search. It goes in the repository list, where Enter runs it.\n\n"
            f"{query}", "Save Search", query[:60],
        )
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            name = dlg.GetValue().strip()
        finally:
            dlg.Destroy()
        if not name:
            self._announce("A saved search needs a name.")
            return
        self.saved_searches = add_saved_search(SavedSearch(name, query, kind))
        self._refresh_repo_list()
        self._announce(f"Saved '{name}'. It is in the repository list, after My Work; "
                       "Enter there runs it again.")

    # ── Pull requests ───────────────────────────────────────────────────

    def _focused_pr(self) -> Item | None:
        item = self._focused_item()
        if self.view_mode == VIEW_ISSUES and isinstance(item, Item) and item.is_pr:
            return item
        self._announce("Select a pull request in Issues & PRs first.")
        return None

    @staticmethod
    def _pr_label(pr: Item) -> str:
        return f"#{pr.number} {pr.title}"

    def _pr_in_background(self, call, done, error: str) -> None:
        """Run ``call`` off the UI thread, then reload. ``done`` is what to
        say, or a function of ``call``'s result giving it."""
        def worker() -> None:
            try:
                result = call()
            except GhError as exc:
                wx.CallAfter(self._on_action_error, f"{error}: {exc}")
                return
            except Exception as exc:  # noqa: BLE001
                wx.CallAfter(self._on_action_error, f"{error}: {type(exc).__name__}: {exc}")
                return
            wx.CallAfter(self._on_action_done, done(result) if callable(done) else done)

        threading.Thread(target=worker, daemon=True).start()

    def _open_pr(self) -> Item | None:
        """The selected pull request, if it is still open; else say why not."""
        pr = self._focused_pr()
        if pr is not None and pr.state != "OPEN":
            self._announce(f"#{pr.number} is {pr.state_display.lower()}.")
            return None
        return pr

    def _pr_checks(self) -> None:
        """K: the checks on a pull request, failures first."""
        pr = self._focused_pr()
        if pr is None:
            return
        repo, label = self.repo, self._pr_label(pr)
        self._announce(f"Loading the checks on #{pr.number}…")

        def worker() -> None:
            try:
                checks = fetch_pr_checks(pr.url)
            except GhError as exc:
                wx.CallAfter(self._announce, f"Couldn't load the checks: {exc}")
                return
            wx.CallAfter(self._on_checks_ready, repo, label, checks)

        threading.Thread(target=worker, daemon=True).start()

    def _on_checks_ready(self, repo: str, label: str, checks: list) -> None:
        if self.repo != repo:
            return
        text = format_checks(label, checks)
        self._announce(text.splitlines()[1])
        self._show_text_dialog(f"Checks — {label}", text)

    def _pr_review(self) -> None:
        """V: approve, request changes, or comment."""
        pr = self._open_pr()
        if pr is None:
            return
        dlg = ReviewDialog(self, self._pr_label(pr))
        try:
            if dlg.ShowModal() != wx.ID_OK:
                self._announce("Review cancelled.")
                return
            kind, body = dlg.values()
        finally:
            dlg.Destroy()
        said = {"approve": "Approved", "request-changes": "Requested changes on",
                "comment": "Commented on"}[kind]
        self._announce(f"Submitting your review of #{pr.number}…")
        url = pr.url
        self._pr_in_background(lambda: review_pr(url, kind, body),
                               f"{said} #{pr.number}", f"Couldn't review #{pr.number}")

    def _pr_merge(self) -> None:
        """Actions ▸ Pull Request ▸ Merge: how, from what the repo allows."""
        pr = self._open_pr()
        if pr is None:
            return
        if pr.is_draft:
            self._announce(f"#{pr.number} is a draft; mark it ready for review first (D).")
            return
        repo = self.repo
        self._announce("Checking how this repository lets pull requests merge…")

        def worker() -> None:
            try:
                methods = allowed_merge_methods(pr.url)
            except GhError as exc:
                wx.CallAfter(self._announce, f"Couldn't check the merge settings: {exc}")
                return
            wx.CallAfter(self._choose_merge, repo, pr, methods)

        threading.Thread(target=worker, daemon=True).start()

    _MERGE_OUTCOMES = {
        "merged": "Merged #{n}",
        "auto": "#{n} will merge by itself once its required checks pass — "
                "GitHub turned on auto-merge",
        "queued": "GitHub took the merge of #{n} but hasn't merged it yet; it may be "
                  "in a merge queue. Refresh to see",
    }

    def _choose_merge(self, repo: str, pr: Item, methods: list[str]) -> None:
        if self.repo != repo:
            return
        if not methods:
            self._announce("This repository allows no way of merging.")
            return
        dlg = MergeDialog(self, f"{self._pr_label(pr)} into {pr.base_branch or 'its base'}",
                          methods)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                self._announce("Merge cancelled.")
                return
            method, delete = dlg.values()
        finally:
            dlg.Destroy()
        self._announce(f"Merging #{pr.number}…")
        url, n = pr.url, pr.number
        self._pr_in_background(lambda: merge_pr(url, method, delete),
                               lambda outcome: self._MERGE_OUTCOMES[outcome].format(n=n),
                               f"Couldn't merge #{n}")

    def _pr_toggle_draft(self) -> None:
        """D: a draft becomes ready for review; an open PR goes back to draft.

        Asks first: others see the change, and D is one stray key away.
        """
        pr = self._open_pr()
        if pr is None:
            return
        ready = pr.is_draft
        what = "ready for review" if ready else "back to a draft"
        confirm = wx.MessageBox(
            f"Mark {self._pr_label(pr)} {what}?", "Pull Request",
            wx.YES_NO | wx.ICON_QUESTION, self,
        )
        if confirm != wx.YES:
            return
        self._announce(f"Marking #{pr.number} {what}…")
        url = pr.url
        self._pr_in_background(lambda: set_pr_ready(url, ready),
                               f"#{pr.number} is {what}", f"Couldn't change #{pr.number}")

    def _pr_request_reviewers(self) -> None:
        pr = self._open_pr()
        if pr is None:
            return
        dlg = wx.TextEntryDialog(
            self, f"Request reviews on {self._pr_label(pr)} from (GitHub logins, "
            "separated by commas; a team as org/team-name):", "Request Reviewers", "",
        )
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            logins = [x.strip().lstrip("@") for x in dlg.GetValue().split(",") if x.strip()]
        finally:
            dlg.Destroy()
        if not logins:
            self._announce("No reviewers named.")
            return
        self._announce(f"Requesting reviews from {', '.join(logins)}…")
        url = pr.url
        self._pr_in_background(lambda: request_reviewers(url, logins),
                               f"Requested reviews on #{pr.number} from {', '.join(logins)}",
                               f"Couldn't request reviewers on #{pr.number}")

    def _pr_update_branch(self) -> None:
        pr = self._open_pr()
        if pr is None:
            return
        confirm = wx.MessageBox(
            f"Bring {self._pr_label(pr)} up to date with {pr.base_branch or 'its base'}?\n\n"
            "GitHub merges the base branch into the pull request's branch.",
            "Update Branch", wx.YES_NO | wx.ICON_QUESTION, self,
        )
        if confirm != wx.YES:
            return
        self._announce(f"Updating the branch of #{pr.number}…")
        url = pr.url
        self._pr_in_background(lambda: update_pr_branch(url),
                               f"Updated the branch of #{pr.number}",
                               f"Couldn't update the branch of #{pr.number}")

    # ── Workflow runs: jobs, logs, rerun, cancel ────────────────────────

    def _focused_run(self) -> WorkflowRun | None:
        """The run J, L, E and X act on: the selected one, or the one whose
        jobs are listed."""
        if self.view_mode == VIEW_JOBS and self.jobs_run:
            return self.jobs_run
        item = self._focused_item()
        if self.view_mode == VIEW_WORKFLOW and isinstance(item, WorkflowRun):
            return item
        self._announce("Select a workflow run first.")
        return None

    def _show_run_jobs(self) -> None:
        """J: the run's jobs, as a list to drill into (Backspace returns)."""
        if self.view_mode != VIEW_WORKFLOW:
            return
        run = self._focused_run()
        if run is None:
            return
        self.jobs_run = run
        self._switch_view(VIEW_JOBS)
        self._announce(f"Showing jobs for run #{run.run_number} {run.name}")

    def _show_what_failed(self) -> None:
        """L: GitHub's errors and the end of each failed step's log, in one text."""
        run = self._focused_run()
        if run is None or not self.repo:
            return
        if run.status != "completed":
            self._announce(f"Run #{run.run_number} is still {run.status.replace('_', ' ')}.")
            return
        if run.conclusion == "success":
            self._announce(f"Nothing failed in run #{run.run_number} — it succeeded.")
            return
        if getattr(self, "_report_busy", False):
            self._announce("Still putting the last report together.")
            return
        repo = self.repo
        self._report_busy = True
        self._announce(f"Finding what failed in run #{run.run_number}…")

        def worker() -> None:
            from concurrent.futures import ThreadPoolExecutor
            try:
                jobs = fetch_run_jobs(repo, run.run_id)
                failed = [j for j in jobs if j.conclusion in FAILED_CONCLUSIONS]
                with ThreadPoolExecutor(max_workers=6) as pool:
                    found = list(pool.map(lambda j: fetch_job_annotations(repo, j.id), failed))
                annotations = {j.id: a for j, a in zip(failed, found)}
                log = fetch_failed_log(repo, run.run_id) if failed else []
            except GhError as exc:
                wx.CallAfter(self._report_failed, f"Couldn't read run #{run.run_number}: {exc}")
                return
            text = format_failure_report(run, jobs, annotations, log)
            wx.CallAfter(self._on_report_ready, repo,
                         f"What failed — run #{run.run_number} {run.name}", text, 0)

        threading.Thread(target=worker, daemon=True).start()

    def _show_job_log(self, job: WorkflowJob) -> None:
        """Enter on a job: its whole log, opening at the first error."""
        run = self.jobs_run
        if not run or not self.repo:
            return
        if job.conclusion == "skipped":
            self._announce(f"{job.name} was skipped, so it has no log.")
            return
        if job.status != "completed":
            self._announce(f"{job.name} is still {job.status.replace('_', ' ')}; its log "
                           "is ready when it finishes.")
            return
        if getattr(self, "_report_busy", False):
            self._announce("Still putting the last report together.")
            return
        repo = self.repo
        self._report_busy = True
        self._announce(f"Loading the log of {job.name}…")

        def worker() -> None:
            try:
                log = fetch_job_log(repo, run.run_id, job.id)
            except GhError as exc:
                wx.CallAfter(self._report_failed, f"Couldn't load the log of {job.name}: {exc}")
                return
            text, start = format_job_log(job, log)
            wx.CallAfter(self._on_report_ready, repo, f"Log — {job.name}", text, start)

        threading.Thread(target=worker, daemon=True).start()

    def _report_failed(self, msg: str) -> None:
        self._report_busy = False
        self._announce(msg)

    def _on_report_ready(self, repo: str, title: str, text: str, start: int) -> None:
        self._report_busy = False
        if self.repo != repo or self.view_mode not in (VIEW_WORKFLOW, VIEW_JOBS):
            self._announce(f"{title} is ready, but you have moved on; ask again there.")
            return
        self._announce(title + (" — at the first error." if start else "."))
        self._show_text_dialog(title, text, start)

    def _rerun_run(self) -> None:
        """E: run it again — every job, or only those that failed."""
        run = self._focused_run()
        if run is None or not self.repo:
            return
        if run.status != "completed":
            self._announce(f"Run #{run.run_number} hasn't finished; cancel it (X) or wait.")
            return
        choices = ["Rerun all jobs"]
        if run.conclusion in ("failure", "cancelled", "timed_out", "startup_failure"):
            choices.insert(0, "Rerun failed jobs only")
        dlg = wx.SingleChoiceDialog(
            self, f"Rerun #{run.run_number} {run.name} on {run.branch}?", "Rerun", choices,
        )
        dlg.SetSelection(0)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                self._announce("Rerun cancelled.")
                return
            failed_only = dlg.GetStringSelection() == "Rerun failed jobs only"
        finally:
            dlg.Destroy()
        repo = self.repo
        self._run_change(run, lambda: rerun_workflow_run(repo, run.run_id, failed_only),
                         f"Rerunning {'the failed jobs of ' if failed_only else ''}"
                         f"#{run.run_number} {run.name}")

    def _cancel_run(self) -> None:
        """X: stop a run that is queued or in progress."""
        run = self._focused_run()
        if run is None or not self.repo:
            return
        if run.status == "completed":
            self._announce(f"Run #{run.run_number} has already finished.")
            return
        confirm = wx.MessageBox(
            f"Cancel run #{run.run_number} {run.name} on {run.branch}?",
            "Cancel Run", wx.YES_NO | wx.ICON_QUESTION, self,
        )
        if confirm != wx.YES:
            return
        repo = self.repo
        self._run_change(run, lambda: cancel_workflow_run(repo, run.run_id),
                         f"Cancelling #{run.run_number} {run.name}")

    def _run_change(self, run: WorkflowRun, call, said: str) -> None:
        self._announce(f"{said}…")
        repo = self.repo

        def worker() -> None:
            try:
                call()
            except GhError as exc:
                wx.CallAfter(self._announce, f"Couldn't do that to run #{run.run_number}: {exc}")
                return
            wx.CallAfter(self._on_run_changed, repo, said)

        threading.Thread(target=worker, daemon=True).start()

    def _on_run_changed(self, repo: str, said: str) -> None:
        if self.repo == repo and self.view_mode in (VIEW_WORKFLOW, VIEW_JOBS):
            # GitHub takes a moment to show the new state; refresh after it.
            wx.CallLater(3000, self._refresh_if_runs, repo)
        self._announce(f"{said}. The list refreshes in a moment.")

    def _refresh_if_runs(self, repo: str) -> None:
        if self.repo == repo and self.view_mode in (VIEW_WORKFLOW, VIEW_JOBS):
            self._load_items()

    # ── Watching ────────────────────────────────────────────────────────

    _WATCH_CHOICES = [
        (WATCH_PARTICIPATING, "Participating and @mentions — only what you take part in"),
        (WATCH_ALL, "All Activity — every issue, pull request, release and discussion"),
        (WATCH_IGNORE, "Ignore — nothing, not even @mentions"),
    ]

    def _repo_in_front(self) -> str | None:
        """The repository the repository actions (New Issue, Search This
        Repository, Watch Settings) are about — the one in front of you:

        - the repository selected in the repository list, when that has focus;
        - in a list across repositories (Notifications, My Work, Activity,
          search results, Starred, Watched), the selected row's repository;
        - otherwise the repository open.
        """
        return self._repo_in_front_from()[0]

    def _repo_in_front_from(self) -> tuple[str | None, str]:
        """``_repo_in_front`` and where it came from: "list" (the repository
        list), "row" (the selected row of a list across repositories) or
        "open" (the repository open). Opening it differs by source: from a
        row, Backspace should come back to that row."""
        if self._pane_index(self._current_focus()) == 0:
            idx = self.repo_list.GetSelection()
            name = self.repo_list.GetClientData(idx) if idx != wx.NOT_FOUND else None
            if is_repo_entry(name):
                return name, "list"
        item = self._focused_item()
        if self.view_mode in REPOLESS_VIEWS:
            if isinstance(item, RepoEntry):
                return item.name, "row"
            if isinstance(item, FavoriteEntry):
                return (item.repo or None), "row"
            return (getattr(item, "repo", "") or None), "row"
        return self.repo, "open"

    def _watch_target(self) -> str | None:
        return self._repo_in_front()

    def _watch_settings_flow(self) -> None:
        """Actions ▸ Watch Settings (Ctrl+Shift+U): how GitHub notifies you
        about a repository."""
        repo = self._watch_target()
        if not repo:
            self._announce("Select a repository first.")
            return
        self._announce(f"Checking how you watch {repo}…")

        def worker() -> None:
            try:
                level = get_watch_level(repo)
            except GhError as exc:
                wx.CallAfter(self._on_watch_error, repo, exc)
                return
            wx.CallAfter(self._choose_watch_level, repo, level)

        threading.Thread(target=worker, daemon=True).start()

    def _on_watch_error(self, repo: str, exc: GhError) -> None:
        if isinstance(exc, MissingScope):
            self._announce(f"Watch Settings needs gh's \"{exc.scope}\" permission; "
                           "see the message for how to add it.")
            wx.MessageBox(str(exc), "Watch Settings", wx.OK | wx.ICON_INFORMATION, self)
        else:
            self._announce(f"Couldn't check how you watch {repo}: {exc}")

    def _choose_watch_level(self, repo: str, level: str) -> None:
        labels = [label for _, label in self._WATCH_CHOICES]
        current = next(i for i, (lv, _) in enumerate(self._WATCH_CHOICES) if lv == level)
        dlg = wx.SingleChoiceDialog(
            self,
            f"How should GitHub notify you about {repo}?\n"
            f"Now: {labels[current].split(' — ')[0]}.\n"
            "For only some kinds of activity (Custom), use github.com.",
            "Watch Settings",
            labels,
        )
        dlg.SetSelection(current)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                self._announce("Watch settings unchanged.")
                return
            choice = dlg.GetSelection()
        finally:
            dlg.Destroy()
        new_level, label = self._WATCH_CHOICES[choice]
        name = label.split(" — ")[0]
        if new_level == level:
            self._announce(f"Already {name} for {repo}.")
            return
        self._announce(f"Setting {repo} to {name}…")

        def worker() -> None:
            try:
                set_watch_level(repo, new_level)
            except GhError as exc:
                wx.CallAfter(self._on_watch_error, repo, exc)
                return
            wx.CallAfter(self._on_watch_set, repo, name)

        threading.Thread(target=worker, daemon=True).start()

    def _on_watch_set(self, repo: str, name: str) -> None:
        self._announce(f"{repo} is now {name}.")
        # Watching or not changes how many Watched holds; ask again.
        threading.Thread(target=self._recount_watched, args=(self._account_gen,),
                         daemon=True).start()

    def _recount_watched(self, gen: int) -> None:
        try:
            n = COUNTED_ENTRIES[WATCHED_ENTRY]()
        except GhError:
            return
        wx.CallAfter(self._on_watched_recounted, n, gen)

    def _on_watched_recounted(self, n: int, gen: int) -> None:
        if gen == self._account_gen:
            self._on_category_counts({WATCHED_ENTRY: n})

    # ── Accounts ────────────────────────────────────────────────────────

    def _switch_account_flow(self) -> None:
        """File ▸ Switch GitHub Account (Ctrl+Shift+K): another account gh
        is signed in to. gh keeps the accounts; this only chooses."""
        self._announce("Asking gh which accounts it has…")

        def worker() -> None:
            try:
                accounts = list_accounts()
            except GhError as exc:
                wx.CallAfter(self._announce, f"Couldn't list gh's accounts: {exc}")
                return
            wx.CallAfter(self._choose_account, accounts)

        threading.Thread(target=worker, daemon=True).start()

    def _choose_account(self, accounts: list) -> None:
        if not accounts:
            self._announce("gh isn't signed in to github.com. Run gh auth login in a terminal.")
            return
        if len(accounts) == 1:
            msg = (f"gh is signed in to one github.com account, {accounts[0].login}.\n\n"
                   "To add another, run this in a terminal, then come back here:\n\n"
                   "gh auth login")
            self._announce(f"Only one account: {accounts[0].login}.")
            wx.MessageBox(msg, "Switch GitHub Account", wx.OK | wx.ICON_INFORMATION, self)
            return
        labels = [f"{a.login}{' — in use' if a.active else ''}" for a in accounts]
        dlg = wx.SingleChoiceDialog(
            self, "Use which github.com account?\n"
            "gh in your terminal switches to it too.",
            "Switch GitHub Account", labels,
        )
        dlg.SetSelection(0)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                self._announce("Account unchanged.")
                return
            chosen = accounts[dlg.GetSelection()]
        finally:
            dlg.Destroy()
        if chosen.active:
            self._announce(f"Already using {chosen.login}.")
            return
        self._announce(f"Switching to {chosen.login}…")

        def worker() -> None:
            try:
                switch_account(chosen.login, chosen.host)
            except GhError as exc:
                wx.CallAfter(self._announce, f"Couldn't switch account: {exc}")
                return
            wx.CallAfter(self._on_account_switched, chosen.login)

        threading.Thread(target=worker, daemon=True).start()

    def _on_account_switched(self, login: str) -> None:
        """Start again as the new account: its repositories, counts and inbox.

        Favorites and pinned repositories stay — they are this computer's,
        not the account's.
        """
        self._account_gen += 1
        self._search = None
        self._search_total = 0
        self.__dict__.pop("_fork_parent", None)  # the new account may see other repos
        self.repo = None
        self._return_to = None
        self._pending_target = None
        self._issue_drafts.clear()
        self._category_counts.clear()
        self._load_repos()
        if self.view_mode == VIEW_NOTIFICATIONS:
            self.current_limit = self.page_size
            self._load_items()
        else:
            self._switch_view(VIEW_NOTIFICATIONS)
        self._update_title()
        wx.CallLater(200, self._announce, f"Now using {login}. Showing their notifications.")

    # ── Labels ──────────────────────────────────────────────────────────

    def _browse_label(self, label: "Label") -> None:
        """Show the issues and PRs carrying ``label``.

        This reuses the Issues & PRs view rather than inventing a new one, so
        the state filter, columns, sorting, and every issue action still work.
        The restriction is applied by `gh`, not by the quick filter, so it
        finds items that were never on the current page.
        """
        self.label_filter = label.name
        self.current_limit = self.page_size
        if self.view_mode == VIEW_ISSUES:
            self._load_items()
        else:
            self._switch_view(VIEW_ISSUES)
        self._announce(
            f"Showing issues and PRs labelled '{label.name}'. "
            "Backspace returns to the labels."
        )

    def on_new_label(self, event: wx.CommandEvent) -> None:
        self._do_new_label()

    def on_delete_label(self, event: wx.CommandEvent) -> None:
        self._do_delete_label()

    def on_delete_item(self, event: wx.CommandEvent) -> None:
        """Actions ▸ Delete (Ctrl+D) — deletes whatever this view can delete."""
        self._delete_focused_item()

    def on_act_run_workflow(self, event: wx.CommandEvent) -> None:
        item = self._focused_item()
        if isinstance(item, Workflow):
            self._run_workflow_flow(item)
        else:
            self._announce("Select a workflow first.")

    def on_act_download_artifact(self, event: wx.CommandEvent) -> None:
        item = self._focused_item()
        if isinstance(item, Artifact):
            self._download_artifact_flow(item)
        else:
            self._announce("Select an artifact first.")

    def _delete_focused_item(self) -> None:
        """Route Delete/Ctrl+D to the deletion this view supports.

        One entry point for the key and the menu item, so the two can never
        disagree about what Delete means in a given view. Never from the
        repository list, where Delete reads as "remove this repository" —
        the bare key is kept out of it in on_char_hook, Ctrl+D here.
        """
        if self._pane_index(self._current_focus()) == 0:
            self._announce("Move to the list to delete or mark done (F6).")
            return
        if self.view_mode == VIEW_LABELS:
            self._do_delete_label()
        elif self.view_mode == VIEW_WORKFLOW:
            self._do_delete_run()
        elif self.view_mode == VIEW_NOTIFICATIONS:
            self._mark_notification_done()
        else:
            self._announce(
                "Nothing here can be deleted. Labels and workflow runs can."
            )

    def _do_new_label(self) -> None:
        """Create a label (Insert in the Labels view, or the File menu)."""
        if not self.repo:
            self._announce("Select a repository first.")
            return
        dlg = NewLabelDialog(self, self.repo)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            self._announce("New label cancelled.")
            return
        name, color, description = dlg.values()
        dlg.Destroy()
        self._announce(f"Creating label '{name}'…")

        def worker() -> None:
            try:
                create_label(self.repo, name, color, description)
                wx.CallAfter(self._on_label_action_done, f"Created label '{name}'")
            except GhError as exc:
                wx.CallAfter(
                    self._on_action_error, f"Error creating label '{name}': {exc}"
                )

        threading.Thread(target=worker, daemon=True).start()

    def _do_delete_label(self) -> None:
        """Delete the focused label (Delete in the Labels view, or the File menu)."""
        if self.view_mode != VIEW_LABELS:
            self._announce("Switch to the Labels view to delete a label (Ctrl+8).")
            return
        item = self._focused_item()
        if not isinstance(item, Label):
            self._announce("Select a label first.")
            return
        confirm = wx.MessageBox(
            f"Delete the label '{item.name}'?\n\n"
            f"{item.description or '(no description)'}\n\n"
            "It will be removed from every issue and pull request that carries "
            "it. This cannot be undone.",
            "Confirm Delete Label",
            wx.YES_NO | wx.ICON_WARNING,
            self,
        )
        if confirm != wx.YES:
            return
        name = item.name
        self._announce(f"Deleting label '{name}'…")

        def worker() -> None:
            try:
                delete_label(self.repo, name)
                wx.CallAfter(self._on_label_action_done, f"Deleted label '{name}'")
            except GhError as exc:
                wx.CallAfter(
                    self._on_action_error, f"Error deleting label '{name}': {exc}"
                )

        threading.Thread(target=worker, daemon=True).start()

    def _on_label_action_done(self, msg: str) -> None:
        """Refresh the labels list after a create/delete.

        Separate from ``_on_action_done`` because that one refreshes whatever
        view is current, and a label can be created from anywhere via the File
        menu — refreshing the Releases list after creating a label would be a
        surprise, and would hide the label that was just made.
        """
        self._announce(f"{msg}. Refreshing labels…")
        if self.view_mode == VIEW_LABELS:
            self._load_items()
        else:
            self._switch_view(VIEW_LABELS)

    def _do_delete_run(self) -> None:
        """Delete the focused workflow run (Delete key in Workflow view)."""
        item = self._focused_item()
        if not item or not isinstance(item, WorkflowRun):
            return
        confirm = wx.MessageBox(
            f"Delete workflow run #{item.run_number}?\n\n{item.name} "
            f"({item.conclusion or item.status} on {item.branch})\n\n"
            "This cannot be undone.",
            "Confirm Delete Run",
            wx.YES_NO | wx.ICON_WARNING,
            self,
        )
        if confirm != wx.YES:
            return
        self._announce(f"Deleting run #{item.run_number}…")

        run_id = item.run_id
        run_number = item.run_number

        def worker() -> None:
            try:
                delete_workflow_run(self.repo, run_id)
                wx.CallAfter(self._on_action_done, f"Deleted run #{run_number}")
            except GhError as exc:
                wx.CallAfter(self._on_action_error, f"Error deleting run #{run_number}: {exc}")

        threading.Thread(target=worker, daemon=True).start()


# ── Entry point ────────────────────────────────────────────────────────


def main() -> None:
    # Must run before argparse: Velopack relaunches the app with its own hook
    # arguments during install/update/uninstall, and this handles and exits.
    updater.bootstrap()

    parser = argparse.ArgumentParser(
        description="GUI viewer and manager for GitHub issues and pull requests."
    )
    parser.add_argument(
        "--repo",
        metavar="OWNER/NAME",
        default=None,
        help="GitHub repository (owner/name). Skips the repo chooser.",
    )
    parser.add_argument(
        "--update-feed",
        metavar="DIR",
        default=None,
        help="Check this local folder of vpk output for updates instead of "
             "GitHub Releases (for testing the update cycle offline).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"GHManage {APP_VERSION}",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Write verbose update logging to the update log.",
    )
    args = parser.parse_args()

    updater.configure_logging(debug=args.debug)
    service = updater.UpdateService(APP_VERSION, feed=args.update_feed)

    app = wx.App(False)
    GhViewerFrame(repo=args.repo, update_service=service)
    app.MainLoop()


if __name__ == "__main__":
    main()