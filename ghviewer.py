#!/usr/bin/env python3
"""ghviewer — a wxPython GUI for browsing and managing GitHub issues & PRs.

Requires the `gh` CLI (https://cli.github.com/) and wxPython.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import tempfile
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
from pinned_repos import (
    add_pinned, hide_repo, load_hidden, load_pinned, remove_pinned, unhide_repos,
)
import announce
import alertview
import codeview
import commands
import diffview
import discussionview
import milestoneview
import settings
import search_help
import speech
from favorites import FavoriteEntry, load_favorites, save_favorites, is_favorite, toggle_favorite
from saved_searches import (
    KIND_ISSUES, KIND_REPOS, SavedSearch, add_saved_search, load_saved_searches,
    remove_saved_search,
)

from columns import ColumnSet, LayoutEditor, cell_text, names_cell, row_text
from gh_columns import (
    COLUMN_SETS, ACTIVITY_SET, ARTIFACT_SET, ASSET_SET, BRANCH_SET, CHANGED_FILE_SET, COMMIT_SET,
    FAVORITES_SET,
    ISSUE_SET, JOB_SET, LABEL_SET, MY_WORK_SET, NOTIFICATION_SET, ORG_SET,
    PAGEFILE_SET, PAGES_SET, RELEASE_SET, REPO_FILE_SET, REPO_SET, SEARCH_ITEM_SET, TAG_SET,
    SECURITY_SET, WORKFLOW_RUN_SET, WORKFLOW_SET, DISCUSSION_SET, MILESTONE_SET,
)
from gh_data import (
    ACTIVITY_MAX,
    ActivityEvent,
    Notification,
    RepoEntry,
    RepoFile,
    ALERT_DEPENDABOT,
    ALERT_KIND_LABELS,
    ALERT_KINDS,
    SecurityAlert,
    fetch_security_alerts,
    Discussion,
    add_discussion_comment,
    fetch_discussion,
    fetch_discussion_comments,
    fetch_discussions,
    Milestone,
    fetch_milestones,
    ALL_BRANCHES,
    ALL_BRANCHES_PER_BRANCH_MAX,
    GhError,
    Item,
    SORT_ORDERS,
    Artifact,
    Branch,
    ChangedFile,
    Commit,
    MAX_CHANGED_FILES,
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
    WorkflowJob,
    cancel_workflow_run,
    fetch_failed_log,
    fetch_job_annotations,
    fetch_job_log,
    fetch_run_jobs,
    fetch_workflow_run,
    rerun_workflow_run,
    SEARCH_MAX,
    fetch_my_work,
    search_issues,
    search_repos,
    MissingScope,
    WATCH_ALL,
    WATCH_IGNORE,
    WATCH_PARTICIPATING,
    get_watch_level,
    repo_admin,
    delete_repo,
    set_archived,
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
    fetch_all_branch_commits,
    fetch_commits,
    fetch_commit_detail,
    fetch_commit_diff,
    fetch_commit_files,
    fetch_pr_diff,
    fetch_pr_files,
    fetch_pr_head_sha,
    fetch_pr_review_comments,
    add_review_comment,
    comments_by_path,
    fetch_blame,
    fetch_blob_text,
    fetch_commit_file,
    fetch_default_branch,
    fetch_file_history,
    fetch_ref_names,
    fetch_repo_folder,
    file_diff,
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
               the wiki); it opens the repository
      item     an issue or pull request; ``ref`` is its number
      discussion  a discussion; ``ref`` is its number
      milestone   a milestone; ``ref`` is its number
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
    "discussions": "discussions",
    "milestones": "milestones",
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
    if section == "discussions" and arg.isdigit():
        return GitHubTarget(repo, "discussion", arg)
    if section == "milestone" and arg.isdigit():
        return GitHubTarget(repo, "milestone", arg)
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


def clone_url(repo: str, kind: str = "https") -> str:
    """The address ``git clone`` takes for OWNER/NAME, over HTTPS or SSH."""
    if kind == "ssh":
        return f"git@github.com:{repo}.git"
    return f"https://github.com/{repo}.git"


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


# What Select Branch lists for ALL_BRANCHES.
ALL_BRANCHES_CHOICE = "All branches"


def _commit_branch_label(branch: str) -> str:
    """``commit_branch`` as words: ALL_BRANCHES reads "all branches"."""
    return "all branches" if branch == ALL_BRANCHES else branch


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
    if isinstance(item, ChangedFile):
        return CopyValues(item.url, item.filename, item.filename, "Path", item.filename)
    if isinstance(item, RepoFile):
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
    if isinstance(item, Milestone):
        return CopyValues(item.url, item.title, item.title, "Milestone Title", item.title)
    if isinstance(item, Discussion):
        number = f"#{item.number}"
        return CopyValues(item.url, item.title, number, "Number", f"{number} {item.title}")
    if isinstance(item, SecurityAlert):
        text = f"{item.ident} {item.summary}".strip()
        return CopyValues(item.url, item.summary, item.ident, item.ident_noun, text)
    if isinstance(item, FavoriteEntry):
        # A favorite keeps no number or SHA of its own, only how it was
        # titled, so Copy Name and Copy Title give the same thing.
        return CopyValues(item.url, item.title, item.title, "Name", item.title)
    return None


def security_status(repo: str, report, state: str, limit: int) -> str:
    """The Security Alerts status message: how many of each kind, then why
    any kind is missing, then whether there may be more."""
    alerts = report.alerts
    n = len(alerts)
    which = {"open": "open ", "closed": "closed "}.get(state, "")
    head = f"{repo} — {n} {which}security alert{'s' if n != 1 else ''}"
    counts = []
    for kind in ALERT_KINDS:
        k = sum(1 for a in alerts if a.kind == kind)
        if k:
            label = ALERT_KIND_LABELS[kind]
            counts.append(f"{k} {label if kind == ALERT_DEPENDABOT else label.lower()}")
    parts = [head + (": " + ", ".join(counts) if counts else "") + "."]
    parts += report.notes()
    if report.full:
        parts.append(f"Showing up to {limit} of each kind; Ctrl++ shows more.")
    return " ".join(parts)


def write_diff_file(stem: str, text: str) -> str:
    """Save a diff where Open Diff can hand it to another app: GHManage's
    folder in the temp folder, one file per diff, written over each time."""
    folder = os.path.join(tempfile.gettempdir(), "GHManage")
    os.makedirs(folder, exist_ok=True)
    safe = re.sub(r"[^\w.-]+", "-", stem).strip("-.") or "changes"
    path = os.path.join(folder, f"{safe}.diff")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return path


def open_in_default_app(path: str) -> bool:
    """Open a file in whatever app the system opens it with. On Windows,
    Notepad when nothing is set to open .diff files."""
    try:
        if sys.platform == "win32":
            try:
                os.startfile(path)  # type: ignore[attr-defined]
            except OSError:
                subprocess.Popen(["notepad.exe", path])
        elif sys.platform == "darwin":
            # TextEdit (-t) when no app claims .diff files.
            if subprocess.call(["open", path]) != 0:
                subprocess.Popen(["open", "-t", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError:
        return False
    return True


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
ID_CHOOSE_COLUMNS = wx.NewIdRef()
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
ID_FAVORITE = wx.NewIdRef()
ID_VIEW_NOTIFICATIONS = wx.NewIdRef()
ID_MARK_READ = wx.NewIdRef()
ID_MARK_ALL_READ = wx.NewIdRef()
ID_UNSUBSCRIBE = wx.NewIdRef()
ID_SHOW_READ = wx.NewIdRef()
ID_SPEAK_RESULTS = wx.NewIdRef()
ID_USER_GUIDE = wx.NewIdRef()
ID_SHORTCUTS = wx.NewIdRef()
ID_COMMAND_PALETTE = wx.NewIdRef()
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
ID_HIDDEN_REPOS = wx.NewIdRef()
ID_ARCHIVE_REPO = wx.NewIdRef()
ID_DELETE_REPO = wx.NewIdRef()
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
ID_COPY_CLONE_HTTPS = wx.NewIdRef()
ID_COPY_CLONE_SSH = wx.NewIdRef()
ID_COPY_DETAILS = wx.NewIdRef()
ID_COPY_DIFF = wx.NewIdRef()
ID_CHANGED_FILES = wx.NewIdRef()
ID_OPEN_DIFF = wx.NewIdRef()
ID_VIEW_CODE = wx.NewIdRef()
ID_FILE_HISTORY = wx.NewIdRef()
ID_BLAME = wx.NewIdRef()
ID_WHOLE_FILE = wx.NewIdRef()
ID_COMMENT_LINE = wx.NewIdRef()
ID_VIEW_SECURITY = wx.NewIdRef()
ID_VIEW_DISCUSSIONS = wx.NewIdRef()
ID_VIEW_MILESTONES = wx.NewIdRef()


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
VIEW_FILES = "files"           # files a pull request or commit changed (drill-down)
VIEW_CODE = "code"             # a repository's files and folders (Files)
VIEW_HISTORY = "history"       # the commits that changed one file (drill-down)
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
VIEW_SECURITY = "security"     # Dependabot, code scanning and secret scanning alerts
VIEW_DISCUSSIONS = "discussions"  # a repository's discussions (GraphQL)
VIEW_MILESTONES = "milestones"   # a repository's milestones and their progress

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
# A repository's views, as its context menu's Go To lists them (#51).
REPO_GO_TO = [
    (VIEW_ISSUES, "Issues & PRs"),
    (VIEW_BRANCHES, "Branches"),
    (VIEW_COMMITS, "Commits"),
    (VIEW_TAGS, "Tags"),
    (VIEW_RELEASES, "Releases"),
    (VIEW_WORKFLOWS, "Workflows"),
    (VIEW_WORKFLOW, "Workflow Runs"),
    (VIEW_LABELS, "Labels"),
    (VIEW_PAGES, "GitHub Pages"),
    (VIEW_CODE, "Files"),
    (VIEW_SECURITY, "Security Alerts"),
    (VIEW_DISCUSSIONS, "Discussions"),
    (VIEW_MILESTONES, "Milestones"),
]
ID_GO_TO_VIEW = {view: wx.NewIdRef() for view, _ in REPO_GO_TO}


def go_to_submenu() -> tuple:
    """The Go To submenu of a repository's context menu: each of its views."""
    return ("sub", "Go To", [("item", ID_GO_TO_VIEW[view], label) for view, label in REPO_GO_TO])


# The view a GitHub address of each kind opens in here, for Open Address
# and Activity alike; and the kinds whose own row is then selected.
ADDRESS_VIEWS = {
    "item": VIEW_ISSUES,
    "commit": VIEW_COMMITS,
    "branch": VIEW_COMMITS,
    "release": VIEW_RELEASES,
    "run": VIEW_WORKFLOW,
    "discussion": VIEW_DISCUSSIONS,
    "milestone": VIEW_MILESTONES,
}
PENDING_KINDS = ("item", "commit", "release", "run", "discussion", "milestone")
# Views that load everything at once, where View More has nothing to add.
NO_MORE_VIEWS = (VIEW_FAVORITES, VIEW_MY_WORK, VIEW_ORGS, VIEW_JOBS, VIEW_ARTIFACTS,
                 VIEW_PAGES, VIEW_PAGEFILES, VIEW_FILES, VIEW_CODE)
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

# The Actions menu item for F. Context menus name what it will do instead.
FAVORITE_LABEL = "Add or Remove Favorite (F)"

USER_GUIDE_URL = "https://theideaplace.github.io/GHManage/"
# The guide's site has a page per section (scripts/build_user_guide.py,
# page_slug); this one is the Searching GitHub section's.
SEARCH_HELP_URL = USER_GUIDE_URL + "searching-github.html"

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

# The columns each view can show (gh_columns). Views listing the same kind
# of thing share a set: every list of repositories has the same columns.
VIEW_COLUMNS = {
    VIEW_ISSUES: ISSUE_SET,
    VIEW_BRANCHES: BRANCH_SET,
    VIEW_COMMITS: COMMIT_SET,
    VIEW_TAGS: TAG_SET,
    VIEW_RELEASES: RELEASE_SET,
    VIEW_WORKFLOWS: WORKFLOW_SET,
    VIEW_WORKFLOW: WORKFLOW_RUN_SET,
    VIEW_ARTIFACTS: ARTIFACT_SET,
    VIEW_JOBS: JOB_SET,
    VIEW_ASSETS: ASSET_SET,
    VIEW_FILES: CHANGED_FILE_SET,
    VIEW_CODE: REPO_FILE_SET,
    VIEW_HISTORY: COMMIT_SET,
    VIEW_LABELS: LABEL_SET,
    VIEW_FAVORITES: FAVORITES_SET,
    VIEW_PAGES: PAGES_SET,
    VIEW_PAGEFILES: PAGEFILE_SET,
    VIEW_ACTIVITY: ACTIVITY_SET,
    VIEW_STARRED: REPO_SET,
    VIEW_WATCHED: REPO_SET,
    VIEW_NOTIFICATIONS: NOTIFICATION_SET,
    VIEW_MY_WORK: MY_WORK_SET,
    VIEW_SEARCH_ISSUES: SEARCH_ITEM_SET,
    VIEW_SEARCH_REPOS: REPO_SET,
    VIEW_ORGS: ORG_SET,
    VIEW_ORG: REPO_SET,
    VIEW_SHARED: REPO_SET,
    VIEW_SECURITY: SECURITY_SET,
    VIEW_DISCUSSIONS: DISCUSSION_SET,
    VIEW_MILESTONES: MILESTONE_SET,
}


def _view_columns(view_mode: str) -> ColumnSet:
    """The columns a view can show."""
    return VIEW_COLUMNS.get(view_mode, ISSUE_SET)


def _row_values(item, columns: list[str]) -> dict[str, str]:
    """Each column's value for an item, by column id."""
    if isinstance(item, FavoriteEntry):
        return {"type": item.item_type, "repo": item.repo,
                "title": item.title, "subtitle": item.subtitle}
    return item.to_row(columns)


def is_repo_entry(data) -> bool:
    """Whether a repo-list entry's client data names a repository, rather
    than Favorites, a category or a saved search."""
    return (
        isinstance(data, str) and bool(data) and data != FAVORITES_ENTRY
        and data not in ENTRY_VIEWS and not data.startswith(SEARCH_ENTRY_PREFIX)
    )


def _name(ctrl: wx.Window, label: str) -> None:
    """Name a control for screen readers. Use this, not SetName alone.

    On Windows this is SetName and nothing else. On a Mac SetName reaches
    nothing native, so VoiceOver read text boxes, lists and choices without
    their labels; speech.set_label puts the name on the native view (#69).
    """
    ctrl.SetName(label)
    speech.set_label(ctrl, label)


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
            _name(self, name)
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
                _name(ctrl, label)
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
                _name(ctrl, label)
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

        def add_field(label: str) -> wx.TextCtrl:
            text = wx.StaticText(self, label=label)
            fields.Add(text, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
            ctrl = wx.TextCtrl(self)
            _name(ctrl, label)
            fields.Add(ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
            return ctrl

        self.name_ctrl = add_field("Name (required)")
        self.desc_ctrl = add_field("Description")
        self.color_ctrl = add_field(
            "Colour, 6-digit hex such as d73a4a (optional — GitHub picks one if blank)",
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


def _reading_box(parent: wx.Window, label: str, text: str, max_width: int = 640) -> wx.BoxSizer:
    """Help text you hear only if you go to it: a labelled, read-only box.

    A StaticText in a dialog that labels nothing is "dialog text", which
    screen readers read along with the focused control when the dialog
    opens. In a box it is read only when you Tab to it. Call this after
    the dialog's buttons are made, so the box is last in tab order, and
    Insert the sizer where it should appear on screen. The label stays
    the box's label because it is made just before it.

    It is as wide as its longest line, up to max_width, and tall enough
    for the text wrapped to that width. Enter presses the dialog's default
    button, as it does in the dialog's other fields; a multi-line box
    would otherwise keep it.
    """
    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(wx.StaticText(parent, label=label))
    box = wx.TextCtrl(parent, value=text,
                      style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP)
    _name(box, label.replace("&", ""))
    margin = 24  # the edit's borders and inner padding, with room to spare
    widths = [box.GetTextExtent(line).width for line in text.split("\n")]
    width = min(max(widths) + margin, max_width)
    lines = sum(-(-w // (width - margin)) or 1 for w in widths)  # each wraps to ceil(w / room)
    box.SetMinSize((width, box.GetCharHeight() * lines + margin))

    def on_key(event: wx.KeyEvent) -> None:
        button = wx.GetTopLevelParent(box).GetDefaultItem()
        if (event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
                and not event.HasAnyModifiers() and isinstance(button, wx.Button)
                and button.IsEnabled()):
            press = wx.CommandEvent(wx.wxEVT_BUTTON, button.GetId())
            press.SetEventObject(button)
            button.GetEventHandler().ProcessEvent(press)
            return
        event.Skip()

    box.Bind(wx.EVT_KEY_DOWN, on_key)
    sizer.Add(box, 0, wx.EXPAND)
    return sizer


class SearchDialog(wx.Dialog):
    """What to search GitHub for, and how.

    The query is GitHub's own search syntax, passed through untouched, so
    every qualifier github.com accepts works here. Labelled as the other
    dialogs: a StaticText before each control and a matching SetName.
    """

    KINDS = [(KIND_ISSUES, "Issues and pull requests"), (KIND_REPOS, "Repositories")]

    EXAMPLES = (
        "Words and GitHub's qualifiers, for example:\n"
        "is:open is:issue label:bug repo:nvaccess/nvda\n"
        "author:@me review-requested:@me updated:>2026-01-01\n"
        "screen reader language:python stars:>50 (repositories)"
    )

    def __init__(self, parent: wx.Window, kind: str = KIND_ISSUES, query: str = "",
                 select: bool = True) -> None:
        super().__init__(parent, title="Search GitHub",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        outer = wx.BoxSizer(wx.VERTICAL)

        label = "Search &for"
        outer.Add(wx.StaticText(self, label=label), 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.kind_ctrl = wx.Choice(self, choices=[name for _, name in self.KINDS])
        _name(self.kind_ctrl, label.replace("&", ""))
        keys = [k for k, _ in self.KINDS]
        self.kind_ctrl.SetSelection(keys.index(kind) if kind in keys else 0)
        outer.Add(self.kind_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # A short label, and no hint text: both are said every time you
        # land on the field. Examples are in the Examples box (Alt+X) and
        # under Insert Qualifier (Alt+Q).
        label = "&Search"
        outer.Add(wx.StaticText(self, label=label), 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.query_ctrl = wx.TextCtrl(self, value=query)
        _name(self.query_ctrl, label.replace("&", ""))
        outer.Add(self.query_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # Alt+Q, from its label. F1 is help, as everywhere: the guide's
        # section on searching (see _on_char_hook).
        self.qualifiers_btn = wx.Button(self, label="Insert &Qualifier…")
        outer.Add(self.qualifiers_btn, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        outer.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        # Under the Search box on screen, but last in tab order: as plain
        # text it was read with the Search box when the dialog opened (#60).
        examples = _reading_box(self, "E&xamples", self.EXAMPLES)
        outer.Insert(4, examples, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        outer.SetMinSize((520, -1))  # on the dialog, Fit would replace it
        self.SetSizerAndFit(outer)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self.qualifiers_btn.Bind(wx.EVT_BUTTON, lambda e: self._show_qualifiers())
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
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

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        """F1 is help: the guide's section on searching."""
        if event.GetKeyCode() == wx.WXK_F1 and not event.HasAnyModifiers():
            if not webbrowser.open(SEARCH_HELP_URL):
                wx.MessageBox(f"Couldn't open a browser. Help on searching is at {SEARCH_HELP_URL}",
                              "Search GitHub", wx.OK | wx.ICON_INFORMATION, self)
            return
        event.Skip()

    def _show_qualifiers(self) -> None:
        """The qualifiers for what is being searched; the one chosen goes into
        the query where the cursor was."""
        kind = self.KINDS[self.kind_ctrl.GetSelection()][0]
        at = self.query_ctrl.GetInsertionPoint()
        dlg = SearchQualifiersDialog(self, kind)
        try:
            chosen = dlg.chosen if dlg.ShowModal() == wx.ID_OK else None
        finally:
            dlg.Destroy()
        if chosen is not None:
            text, at = search_help.insert_qualifier(self.query_ctrl.GetValue(), at, chosen)
            self.query_ctrl.SetValue(text)
            self.query_ctrl.SetInsertionPoint(at)
        self.query_ctrl.SetFocus()


class SearchQualifiersDialog(wx.Dialog):
    """Search ▸ Insert Qualifier (Alt+Q): GitHub's qualifiers for what is being
    searched, as a table of qualifier, meaning and example, with a filter.
    Enter puts the selected one into the query."""

    def __init__(self, parent: wx.Window, kind: str) -> None:
        what = "repositories" if kind == KIND_REPOS else "issues and pull requests"
        super().__init__(parent, title=f"Search Qualifiers for {what}",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.kind = kind
        self.chosen: search_help.Qualifier | None = None
        self.qualifiers = search_help.qualifiers_for(kind)
        self._shown: list = []
        outer = wx.BoxSizer(wx.VERTICAL)

        label = "&Filter"
        outer.Add(wx.StaticText(self, label=label), 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.filter_ctrl = wx.TextCtrl(self)
        _name(self.filter_ctrl, label.replace("&", ""))
        outer.Add(self.filter_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        label = "&Qualifiers"
        outer.Add(wx.StaticText(self, label=label), 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL, size=(640, 300))
        _name(self.list, label.replace("&", ""))
        for i, (heading, width) in enumerate((("Qualifier", 170), ("Meaning", 300), ("Example", 220))):
            self.list.InsertColumn(i, heading, width=width)
        outer.Add(self.list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        insert = wx.Button(self, wx.ID_OK, "&Insert into Search")
        insert.SetDefault()
        docs = wx.Button(self, label="Open GitHub Search &Documentation")
        close = wx.Button(self, wx.ID_CANCEL, "Close")
        for b in (insert, docs, close):
            buttons.Add(b, 0, wx.LEFT, 6)
        outer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        # Under the list on screen, last in tab order, for the same reason
        # as the Search dialog's examples (#60).
        notes = _reading_box(self, "&Notes", search_help.GENERAL_NOTE)
        outer.Insert(outer.GetItemCount() - 1, notes, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.SetSizerAndFit(outer)

        self.filter_ctrl.Bind(wx.EVT_TEXT, lambda e: self._fill())
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self._choose())
        self.Bind(wx.EVT_BUTTON, lambda e: self._choose(), id=wx.ID_OK)
        docs.Bind(wx.EVT_BUTTON, lambda e: webbrowser.open(search_help.DOCS[kind]))
        self._fill()
        wx.CallAfter(self.list.SetFocus)

    def _fill(self) -> None:
        self._shown = search_help.matching(self.qualifiers, self.filter_ctrl.GetValue())
        self.list.DeleteAllItems()
        for i, o in enumerate(self._shown):
            self.list.InsertItem(i, o.op)
            self.list.SetItem(i, 1, o.meaning)
            self.list.SetItem(i, 2, o.example)
        if self._shown:
            self.list.Select(0)
            self.list.Focus(0)

    def _choose(self) -> None:
        if not self.IsModal():
            return  # Enter on the list and the default button both ask
        row = self.list.GetFirstSelected()
        if row < 0 or row >= len(self._shown):
            wx.Bell()
            return
        self.chosen = self._shown[row]
        self.EndModal(wx.ID_OK)


class _DescribedAccessible(getattr(wx, "Accessible", object)):
    """Gives a control an accessible description that can change, for the
    screen reader to read when told it has (see CommandListDialog._notify).
    Everything else is left to the control's own accessibility."""

    def __init__(self, window: wx.Window) -> None:
        super().__init__(window)
        self.description = ""

    def GetDescription(self, childId):
        if childId == 0 and self.description:
            return (wx.ACC_OK, self.description)
        return (wx.ACC_NOT_IMPLEMENTED, "")


class CommandListDialog(wx.Dialog):
    """A filterable table of commands: Help ▸ Keyboard Shortcuts (#3), and
    the command palette (#27), where Enter runs the chosen command.

    The palette starts in the filter so you can type straight away, and Down
    moves into the list; the shortcuts table starts in the list, to read.
    """

    def __init__(self, parent: wx.Window, title: str, rows: list,
                 headings: tuple, cells, palette: bool = False) -> None:
        super().__init__(parent, title=title,
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.rows = rows
        self.cells = cells  # Command -> the row's cells, in heading order
        self.palette = palette
        self.chosen: commands.Command | None = None
        self._shown: list = []
        outer = wx.BoxSizer(wx.VERTICAL)

        label = "&Find a command" if palette else "&Filter"
        outer.Add(wx.StaticText(self, label=label), 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.filter_ctrl = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        _name(self.filter_ctrl, label.replace("&", ""))
        outer.Add(self.filter_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        # What the filter has found: on screen under it, and as the filter's
        # accessible description, which the screen reader reads when you
        # land on it and again after each pause in typing.
        self.summary = wx.StaticText(self, label="")
        outer.Add(self.summary, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self._described = None
        # Windows only; VoiceOver waits for #54. A Mac's wx has wx.Accessible
        # too, but making one raises NotImplementedError, which stopped this
        # dialog opening there.
        if wx.Platform == "__WXMSW__":
            self._described = _DescribedAccessible(self.filter_ctrl)
            self.filter_ctrl.SetAccessible(self._described)
        self._notify_timer: wx.CallLater | None = None

        self._what = "Commands" if palette else "Shortcuts"
        self.list_label = wx.StaticText(self, label=f"&{self._what}")
        outer.Add(self.list_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL, size=(720, 380))
        for i, (heading, width) in enumerate(headings):
            self.list.InsertColumn(i, heading, width=width)
        outer.Add(self.list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        if palette:
            run = wx.Button(self, wx.ID_OK, "&Run")
            run.SetDefault()
            buttons.Add(run, 0, wx.LEFT, 6)
        close = wx.Button(self, wx.ID_CANCEL, "Close")
        buttons.Add(close, 0, wx.LEFT, 6)
        outer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        self.SetSizerAndFit(outer)

        self.filter_ctrl.Bind(wx.EVT_TEXT, lambda e: self._on_text())
        self.filter_ctrl.Bind(wx.EVT_KEY_DOWN, self._on_filter_key)
        self.list.Bind(wx.EVT_KEY_DOWN, self._on_list_key)
        if palette:
            # The first match, whichever row the list is on: that is what
            # the summary says Enter runs.
            self.filter_ctrl.Bind(wx.EVT_TEXT_ENTER, lambda e: self._choose(first=True))
            self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self._choose())
            self.Bind(wx.EVT_BUTTON, lambda e: self._choose(), id=wx.ID_OK)
        self._fill()
        wx.CallAfter((self.filter_ctrl if palette else self.list).SetFocus)

    def _on_text(self) -> None:
        self._fill()
        # Said once typing pauses, not on every key, so it doesn't talk
        # over the letters being echoed.
        if self._notify_timer is not None:
            self._notify_timer.Stop()
        self._notify_timer = wx.CallLater(self.NOTIFY_DELAY_MS, self._notify)

    NOTIFY_DELAY_MS = 350

    def _summary_text(self) -> str:
        """Nothing until something is typed: on opening, the dialog would
        otherwise read it twice, and "Enter runs" would name whatever
        happens to be first."""
        if not self.filter_ctrl.GetValue().strip():
            return ""
        return commands.summary(self._shown, self.palette)

    def _notify(self) -> None:
        """Typing has paused: show what the filter found, and tell the screen
        reader the filter's description has changed. NVDA reads a change to
        the focused control's description. It is only sent while the filter
        has focus, where it is about what you typed."""
        if not self.filter_ctrl:
            return  # typed, then Enter before the pause: the dialog is gone
        found = self._summary_text()
        # Here rather than on every key: a changing label can be read out.
        self.summary.SetLabel(found)
        if self._described is None:
            return
        self._described.description = found
        if wx.Window.FindFocus() is not self.filter_ctrl:
            return
        wx.Accessible.NotifyEvent(wx.ACC_EVENT_OBJECT_DESCRIPTIONCHANGE,
                                  self.filter_ctrl, wx.OBJID_CLIENT, wx.ACC_SELF)

    def _on_filter_key(self, event: wx.KeyEvent) -> None:
        """Down from the filter goes into the list, onto its first row."""
        if event.GetKeyCode() == wx.WXK_DOWN:
            if self._shown:
                self.list.SetFocus()
            else:
                wx.Bell()  # nothing matches; otherwise silent
            return
        event.Skip()

    def _on_list_key(self, event: wx.KeyEvent) -> None:
        """Up from the first row goes back to the filter."""
        if event.GetKeyCode() == wx.WXK_UP and self.list.GetFirstSelected() <= 0:
            self.filter_ctrl.SetFocus()
            return
        event.Skip()

    def _fill(self) -> None:
        self._shown = commands.matching(self.rows, self.filter_ctrl.GetValue())
        # How many match, in the list's name too: typing in the filter is
        # otherwise silent, and with none matching Down does nothing.
        n = len(self._shown)
        label = f"{self._what}, {n} matching" if n else f"{self._what}, none matching"
        self.list_label.SetLabel("&" + label)
        _name(self.list, label)
        self.list.DeleteAllItems()
        for i, c in enumerate(self._shown):
            for col, cell in enumerate(self.cells(c)):
                if col == 0:
                    self.list.InsertItem(i, cell)
                else:
                    self.list.SetItem(i, col, cell)
        if self._shown:
            self.list.Select(0)
            self.list.Focus(0)

    def _choose(self, first: bool = False) -> None:
        if not self.IsModal():
            return  # Enter on the list and the default button both ask
        row = 0 if first else self.list.GetFirstSelected()
        if row < 0 or row >= len(self._shown):
            wx.Bell()
            return
        self.chosen = self._shown[row]
        self.EndModal(wx.ID_OK)


class HiddenReposDialog(wx.Dialog):
    """File ▸ Hidden Repositories: the repositories removed from the list.
    Enter or Show Again puts the selected one back and stays open for the
    next; it closes itself when none are left."""

    def __init__(self, parent: wx.Window, names: list[str], show_again) -> None:
        super().__init__(parent, title="Hidden Repositories",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.show_again = show_again  # name -> None
        self._busy = False
        outer = wx.BoxSizer(wx.VERTICAL)
        label = "&Hidden repositories"
        outer.Add(wx.StaticText(self, label=label), 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.list = wx.ListBox(self, choices=names, style=wx.LB_SINGLE, size=(420, 260))
        _name(self.list, label.replace("&", ""))
        self.list.SetSelection(0)
        outer.Add(self.list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        show = wx.Button(self, label="&Show Again")
        show.SetDefault()
        close = wx.Button(self, wx.ID_CANCEL, "Close")
        for b in (show, close):
            buttons.Add(b, 0, wx.LEFT, 6)
        outer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        self.SetSizerAndFit(outer)
        show.Bind(wx.EVT_BUTTON, lambda e: self._show())
        self.list.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._show())
        wx.CallAfter(self.list.SetFocus)

    def _show(self) -> None:
        # Enter can arrive as both the default button and the list's
        # double-click on some platforms; one keypress, one repository.
        if self._busy:
            return
        self._busy = True
        wx.CallAfter(setattr, self, "_busy", False)
        row = self.list.GetSelection()
        if row == wx.NOT_FOUND:
            wx.Bell()
            return
        self.show_again(self.list.GetString(row))
        self.list.Delete(row)
        if not self.list.GetCount():
            self.EndModal(wx.ID_OK)
            return
        self.list.SetSelection(min(row, self.list.GetCount() - 1))
        self.list.SetFocus()


class ColumnsDialog(wx.Dialog):
    """View ▸ Columns: which columns each kind of list shows, the
    order a screen reader reads them in, and whether their names are read
    too. Modelled on The Chat Place's Session List Columns and QuickMail's
    Message List Fields: the columns not shown, the ones shown in reading
    order, Add, Remove, Move Up, Move Down, Move to Top, Move to Bottom and
    Reset to Default, and a preview of a row. OK keeps every change; Cancel
    or Escape leaves them all.

    Keys as well as the buttons: Enter in Available adds, Delete (or
    Backspace, a Mac's Delete) in Shown removes, and Alt+Up, Alt+Down,
    Alt+Home and Alt+End in Shown move (Option on a Mac). Focus stays on
    the column that moved. Each action is said through ``say`` in
    ``LayoutEditor``'s words ("Author moved above Message") and shown under
    the lists; when there is nothing to do it beeps and says why. The rules
    are ``columns.LayoutEditor``'s."""

    def __init__(self, parent: wx.Window, column_sets: list[ColumnSet], current_id: str,
                 layouts: dict[str, list[str]], speak_labels: bool,
                 sample: dict[str, str] | None,
                 say: Callable[[str], bool] | None = None) -> None:
        """``layouts``: each set's columns as they are now. ``sample``: the
        values of a row in the current list, for the preview, or None.
        ``say``: tells the user what an action did; True if it was spoken."""
        super().__init__(parent, title="Columns",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._sets = column_sets
        self._layouts = layouts
        self._editors: dict[str, LayoutEditor] = {}
        self._current_id = current_id
        self._sample = sample
        self._say = say or (lambda text: False)
        outer = wx.BoxSizer(wx.VERTICAL)

        label = "&List to change"
        outer.Add(wx.StaticText(self, label=label), 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.set_ctrl = wx.Choice(self, choices=[cs.name for cs in column_sets])
        _name(self.set_ctrl, label.replace("&", ""))
        ids = [cs.id for cs in column_sets]
        self.set_ctrl.SetSelection(ids.index(current_id) if current_id in ids else 0)
        outer.Add(self.set_ctrl, 0, wx.LEFT | wx.RIGHT, 10)

        lists = wx.BoxSizer(wx.HORIZONTAL)
        self.available = self._list_box(lists, "A&vailable columns")
        self.shown = self._list_box(lists, "&Shown columns, in the order they're read")
        outer.Add(lists, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 4)

        # What the last action did, on screen under the lists, as well as
        # said: it is the only place a refusal's reason shows when it isn't
        # spoken. Empty when the dialog opens, so nothing extra is read then.
        self.result = wx.StaticText(self, label="")
        outer.Add(self.result, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # One line, next to what it describes: a screen reader reads a
        # one-line box whole on reaching it, a multi-line one a line at a time.
        label = "&Preview"
        outer.Add(wx.StaticText(self, label=label), 0, wx.LEFT | wx.RIGHT, 10)
        self.preview = wx.TextCtrl(self, style=wx.TE_READONLY, size=(560, -1))
        _name(self.preview, label.replace("&", ""))
        outer.Add(self.preview, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        row = wx.WrapSizer(wx.HORIZONTAL)
        actions = [
            ("&Add", self.add), ("&Remove", self.remove),
            ("Move &Up", lambda: self.move(-1)), ("Move &Down", lambda: self.move(1)),
            ("Move to &Top", lambda: self.move_to_end(top=True)),
            ("Move to &Bottom", lambda: self.move_to_end(top=False)),
            ("R&eset to Default", self.reset),
        ]
        # Always enabled, so the Tab order never changes; each beeps when
        # there is nothing it can do.
        for text, action in actions:
            button = wx.Button(self, label=text)
            button.Bind(wx.EVT_BUTTON, lambda e, act=action: act())
            row.Add(button, 0, wx.RIGHT | wx.BOTTOM, 6)
        outer.Add(row, 0, wx.LEFT | wx.RIGHT, 10)

        self.labels_ctrl = wx.CheckBox(self, label="Speak column &names (Full mode)")
        self.labels_ctrl.SetValue(speak_labels)
        outer.Add(self.labels_ctrl, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        buttons = wx.StdDialogButtonSizer()
        ok = wx.Button(self, wx.ID_OK, "OK")
        ok.SetDefault()
        buttons.AddButton(ok)
        buttons.AddButton(wx.Button(self, wx.ID_CANCEL, "Cancel"))
        buttons.Realize()
        outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizerAndFit(outer)
        self.SetEscapeId(wx.ID_CANCEL)

        self.set_ctrl.Bind(wx.EVT_CHOICE, lambda e: self._fill(0, 0))
        self.labels_ctrl.Bind(wx.EVT_CHECKBOX, lambda e: self._show_preview())
        self.available.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.add())
        self.shown.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.remove())
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self._fill(0, 0)
        self.CentreOnParent()
        wx.CallAfter(self.shown.SetFocus)

    def _list_box(self, sizer: wx.BoxSizer, label: str) -> wx.ListBox:
        column = wx.BoxSizer(wx.VERTICAL)
        column.Add(wx.StaticText(self, label=label), 0, wx.BOTTOM, 4)
        box = wx.ListBox(self, style=wx.LB_SINGLE, size=(260, 240))
        _name(box, label.replace("&", ""))
        column.Add(box, 1, wx.EXPAND)
        sizer.Add(column, 1, wx.EXPAND | wx.ALL, 6)
        return box

    # ── State ────────────────────────────────────────────────────────

    @property
    def _set(self) -> ColumnSet:
        return self._sets[max(self.set_ctrl.GetSelection(), 0)]

    @property
    def _editor(self) -> LayoutEditor:
        cs = self._set
        if cs.id not in self._editors:
            self._editors[cs.id] = LayoutEditor(cs, self._layouts.get(cs.id))
        return self._editors[cs.id]

    def layouts(self) -> dict[str, list[str]]:
        """The lists whose columns changed, and their columns now."""
        return {set_id: list(ed.shown) for set_id, ed in self._editors.items()
                if ed.changed_from(self._layouts.get(set_id))}

    def speak_labels(self) -> bool:
        return self.labels_ctrl.GetValue()

    def _heading(self, col_id: str) -> str:
        return self._set.column(col_id).heading

    def _fill(self, shown_index: int | None = None, available_index: int | None = None) -> None:
        """Both lists again, each keeping its place or going to the given row."""
        if shown_index is None:
            shown_index = self.shown.GetSelection()
        if available_index is None:
            available_index = self.available.GetSelection()
        ed = self._editor
        self.shown.Set([self._heading(c) for c in ed.shown])
        self.shown.SetSelection(min(max(shown_index, 0), len(ed.shown) - 1))
        rest = ed.available()
        # An empty list reads as nothing at all to a screen reader.
        self.available.Set([self._heading(c) for c in rest] or ["Every column is shown"])
        self.available.SetSelection(min(max(available_index, 0), max(len(rest), 1) - 1))
        self._show_preview()
        # Refilled, the focused row is often the same row number as before,
        # which NVDA takes for no change; say its name has changed. Windows
        # only: on a Mac wx.Accessible exists but raises NotImplementedError.
        focus = wx.Window.FindFocus()
        if focus in (self.shown, self.available) and wx.Platform == "__WXMSW__":
            wx.Accessible.NotifyEvent(wx.ACC_EVENT_OBJECT_NAMECHANGE, focus,
                                      wx.OBJID_CLIENT, focus.GetSelection() + 1)

    def _show_preview(self) -> None:
        ed = self._editor
        text = ""
        if self._sample is not None and self._set.id == self._current_id:
            text = row_text(self._sample, self._set.defs(ed.shown), self.speak_labels())
            if not text:
                text = "This row has nothing in the columns shown."
        if not text:
            text = "Read in this order: " + ", ".join(self._heading(c) for c in ed.shown) + "."
        self.preview.ChangeValue(text)

    # ── Actions ──────────────────────────────────────────────────────

    def add(self) -> None:
        """Show the selected available column, at the end of the row; stay in
        Available for the next, or go to Shown when that was the last."""
        index = self.available.GetSelection()
        if not self._editor.add(index):
            self._refused()
            return
        self._fill(len(self._editor.shown) - 1, index)
        (self.available if self._editor.available() else self.shown).SetFocus()
        self._report()

    def remove(self) -> None:
        index = self.shown.GetSelection()
        self.shown.SetFocus()
        if not self._editor.remove(index):
            self._refused()
            return
        self._fill(index)
        self._report()

    def move(self, step: int) -> None:
        index = self.shown.GetSelection()
        self._move_to(index, index + step)

    def move_to_end(self, top: bool) -> None:
        self._move_to(self.shown.GetSelection(), 0 if top else len(self._editor.shown) - 1)

    def _move_to(self, index: int, target: int) -> None:
        self.shown.SetFocus()
        if not self._editor.move(index, target):
            self._refused()
            return
        # The one row taken out and put back: on Windows SetString deletes
        # and reinserts each row it touches, and the screen reader would hear
        # the column pushed aside before the one that moved.
        heading = self.shown.GetString(index)
        self.shown.Delete(index)
        self.shown.Insert(heading, target)
        self.shown.SetSelection(target)
        self._show_preview()
        self._report()

    def reset(self) -> None:
        self._editor.reset()
        self._fill(0, 0)
        self.shown.SetFocus()
        self._report()

    def _report(self) -> None:
        """What the last action did: shown under the lists, and said."""
        self.result.SetLabel(self._editor.said)
        self._say(self._editor.said)

    def _refused(self) -> None:
        """Nothing to do: a beep, and why."""
        wx.Bell()
        self._report()

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        focus = wx.Window.FindFocus()
        plain = not (event.ControlDown() or event.ShiftDown() or event.AltDown())
        if focus is self.available and plain and key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.add()  # Enter in Available adds, rather than pressing OK
            return
        if focus is self.shown:
            if plain and key in (wx.WXK_DELETE, wx.WXK_NUMPAD_DELETE, wx.WXK_BACK):
                self.remove()
                return
            if event.AltDown() and not (event.ControlDown() or event.ShiftDown()):
                moves = {wx.WXK_UP: lambda: self.move(-1), wx.WXK_DOWN: lambda: self.move(1),
                         wx.WXK_HOME: lambda: self.move_to_end(True),
                         wx.WXK_END: lambda: self.move_to_end(False)}
                if key in moves:
                    moves[key]()
                    return
        event.Skip()


# ── Delete Repository dialog ────────────────────────────────────────────


class DeleteRepoDialog(wx.Dialog):
    """Confirm deleting a repository by typing its name, as github.com does.

    The warning is the dialog's text, read with its title when it opens.
    Delete stays unavailable until the box holds the repository's name;
    Cancel is the default, so Enter never deletes on its own: in the box,
    Enter goes to Delete once the name is right, and does nothing before.
    Tab passes over Delete while it is unavailable, so the moment it becomes
    available is said.
    """

    def __init__(self, parent: wx.Window, repo: str, archived: bool = False) -> None:
        super().__init__(parent, title="Delete Repository from GitHub")
        self.repo = repo
        outer = wx.BoxSizer(wx.VERTICAL)
        warning = (
            f"Delete {repo} from GitHub? This cannot be undone.\n\n"
            "Everything in it goes: its code, issues, pull requests, releases, wiki "
            "and Actions history. Its stars go too, and forks are no longer linked to it."
        )
        if not archived:
            warning += ("\n\nTo keep it but stop changes to it, cancel and choose "
                        "Archive Repository instead, which can be undone.")
        text = wx.StaticText(self, label=warning)
        text.Wrap(460)
        outer.Add(text, 0, wx.ALL, 10)

        label = f"&Type {repo} to confirm"
        outer.Add(wx.StaticText(self, label=label), 0, wx.LEFT | wx.RIGHT, 10)
        self.name_ctrl = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        _name(self.name_ctrl, label.replace("&", ""))
        outer.Add(self.name_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.delete_btn = wx.Button(self, wx.ID_OK, "&Delete")
        cancel = wx.Button(self, wx.ID_CANCEL, "Cancel")
        cancel.SetDefault()
        buttons.Add(self.delete_btn, 0, wx.RIGHT, 6)
        buttons.Add(cancel)
        outer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        self.SetSizerAndFit(outer)
        self.SetEscapeId(wx.ID_CANCEL)
        self.delete_btn.Disable()

        self.name_ctrl.Bind(wx.EVT_TEXT, lambda e: self._update())
        self.name_ctrl.Bind(wx.EVT_TEXT_ENTER, lambda e: self._on_enter())
        self.CentreOnParent()
        wx.CallAfter(self.name_ctrl.SetFocus)

    def matches(self) -> bool:
        return self.name_ctrl.GetValue().strip().lower() == self.repo.lower()

    def _update(self) -> None:
        was = self.delete_btn.IsEnabled()
        now = self.matches()
        self.delete_btn.Enable(now)
        # Tab passes over an unavailable button, so nothing else says
        # when Delete becomes available.
        if now and not was:
            announce.announce("The name matches. Delete is available.", announce.HINT)

    def _on_enter(self) -> None:
        if self.matches():
            self.delete_btn.SetFocus()
        else:
            wx.Bell()
            announce.announce(f"That doesn't match {self.repo} yet.", announce.RESULT)


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
        _name(self.body_ctrl, label.replace("&", ""))
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
        _name(self.title_ctrl, label.replace("&", ""))
        self.title_ctrl.Bind(wx.EVT_TEXT_ENTER, lambda e: self.body_ctrl.SetFocus())
        outer.Add(self.title_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        label = "&Description (Markdown, optional)"
        outer.Add(wx.StaticText(self, label=label), 0, wx.LEFT | wx.RIGHT, 10)
        self.body_ctrl = wx.TextCtrl(self, value=body, style=wx.TE_MULTILINE)
        _name(self.body_ctrl, label.replace("&", ""))
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
        # Repositories from your account you removed from the list (#2).
        self._hidden_repos: list[str] = load_hidden()
        self._repos_known: bool = False
        self._repos_failed: bool = False
        self.favorites: list[FavoriteEntry] = load_favorites()

        # View settings
        # The columns and the list mode are as last chosen (settings.py).
        self.columns: list[str] = settings.load_columns(ISSUE_SET)
        self.sort_order: str = SORT_ORDERS[0]
        self.list_mode: str = settings.load_list_mode()  # "quick" or "full"
        announce.announcer.configure(*settings.load_announcements())
        self.state_filter: str = "open"  # "open", "closed", "all"
        self.tab_filter: str = "both"  # "issues", "prs", "both"
        self.page_size: int = 100      # how many items to fetch per page
        self.current_limit: int = 100  # current fetch limit (grows via View More)
        self.view_mode: str = VIEW_ISSUES  # current view: issues, branches, commits, etc.
        self.git_items: list = []   # holds Branch/Commit/Tag/Release/WorkflowRun objects
        # branch for commits view ("" = default branch, ALL_BRANCHES = every one)
        self.commit_branch: str = ""
        self._branches_unread: int = 0  # all-branches commits: branches that failed to load
        self.artifacts_run: WorkflowRun | None = None  # run whose artifacts are shown
        self.jobs_run: WorkflowRun | None = None  # run whose jobs are shown
        # Changed Files: the pull request (Item) or Commit whose files are
        # shown, and the list it was opened from, for Backspace.
        self._files_of: Item | Commit | None = None
        self._files_back: dict | None = None
        self._diff_style: str = settings.load_diff_style()
        self._diff_busy = False
        # Files: see _reset_code. History: the file whose commits are shown
        # (ref, path, where-phrase) and the Files view to go back to.
        self._reset_code()
        self._history_of: tuple[str, str, str] | None = None
        self._history_back: dict | None = None
        # Fetched text, blame and per-commit changes, kept for the session:
        # blobs and commits never change, so neither does what they say.
        self._blob_cache: dict[str, str] = {}
        self._patch_cache: dict[tuple[str, str], ChangedFile | None] = {}
        self._detail_gen = 0  # bumped whenever the details panel moves on
        self._whole_file_busy = False
        self._line_comment_busy = False
        self._files_head = ""  # the PR's commit Changed Files' lines are of
        self._file_view: diffview.FileView | None = None  # the changed file shown
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
        # Issues & PRs restricted to a milestone (Enter in Milestones).
        self.milestone_filter: Milestone | None = None
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
        # The view a repository opened from a list landed in: Backspace there
        # goes back to the list (Issues & PRs, or a release or commit from
        # Activity).
        self._return_view: str = VIEW_ISSUES
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
        # Spoken messages are raised from a hidden window of their own (see
        # speech.UiaNotifier); a child of a panel, so no sizer or frame
        # layout ever counts it.
        self._speech_window = wx.Window(self.main_splitter.GetWindow1(), size=(1, 1),
                                        name="speech")
        self._speech_window.Hide()
        self._speech_window.Disable()
        announce.announcer.speaker = speech.speaker_for_platform(self._speech_window.GetHandle())
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
        # Its label for VoiceOver, which wx's name never reaches (#69). The
        # name stays "repo_list"; Windows reads the StaticText above.
        speech.set_label(self.repo_list, "Repositories")
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
        speech.set_label(self.details_text, "Details")  # as the repo list's
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
        for i, col in enumerate(_view_columns(self.view_mode).defs(self.columns)):
            self.list_ctrl.InsertColumn(i, col.heading, width=col.width)

    # ── Menu ────────────────────────────────────────────────────────────

    def _build_menu(self) -> None:
        menu_bar = wx.MenuBar()

        # File menu — the repository and the list itself
        file_menu = wx.Menu()
        file_menu.Append(ID_OPEN_REPO, "Open Repository or Address…\tCtrl+Shift+O")
        # Delete is the key in the repository list; not an accelerator, which
        # would swallow Delete in every other control.
        file_menu.Append(ID_REMOVE_REPO, "Remove from List (Delete)")
        file_menu.Append(ID_HIDDEN_REPOS, "Hidden Repositories…")
        # On GitHub itself, so no shortcut keys: one slip can't reach them.
        file_menu.Append(ID_ARCHIVE_REPO, "Archive or Unarchive Repository…")
        file_menu.Append(ID_DELETE_REPO, "Delete Repository from GitHub…")
        file_menu.AppendSeparator()
        file_menu.Append(ID_SWITCH_ACCOUNT, "Switch GitHub Account…\tCtrl+Shift+K")
        file_menu.AppendSeparator()
        file_menu.Append(ID_REFRESH, "Refresh (R)\tCtrl+R")
        file_menu.Append(ID_VIEW_MORE, "View More\tCtrl++")
        file_menu.AppendSeparator()
        file_menu.Append(ID_SEARCH, "Search GitHub…\tCtrl+Shift+F")
        file_menu.Append(ID_GOTO, "Go To Issue…\tCtrl+G")
        file_menu.Append(ID_FILTER, "Quick Filter…\tCtrl+F")
        file_menu.AppendSeparator()
        # Between comments, or between changes in Changed Files.
        self._act_next_comment = file_menu.Append(ID_NEXT_COMMENT, "Next Comment\tAlt+N")
        self._act_prev_comment = file_menu.Append(ID_PREV_COMMENT, "Previous Comment\tAlt+P")
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
        # A pull request's or commit's whole diff; in Changed Files, the file's.
        self._act_copy_diff = copy_menu.Append(ID_COPY_DIFF, "Copy Diff")
        # The repository in front of you, from any view: for a terminal or
        # another tool, where an address on its own won't clone.
        copy_menu.AppendSeparator()
        copy_menu.Append(ID_COPY_CLONE_HTTPS, "Copy HTTPS Clone URL")
        copy_menu.Append(ID_COPY_CLONE_SSH, "Copy SSH Clone URL")
        actions_menu.AppendSubMenu(copy_menu, "Copy")
        # F is the key, in the list and in the repository list. It acts on the
        # repository when the repository list has focus, as Copy does.
        actions_menu.Append(ID_FAVORITE, FAVORITE_LABEL)
        actions_menu.AppendSeparator()
        # C, O, M and N are the keys in the issues list, like K, V and D below.
        self._act_close = actions_menu.Append(ID_CLOSE_ITEM, "Close Issue/PR (C)\tCtrl+W")
        self._act_reopen = actions_menu.Append(ID_REOPEN, "Reopen Issue/PR (O)\tCtrl+Shift+W")
        self._act_comment = actions_menu.Append(ID_COMMENT, "Add Comment… (M)\tCtrl+M")
        self._act_new_issue = actions_menu.Append(ID_NEW_ISSUE, "New Issue… (N)\tCtrl+N")
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
            ID_OPEN_PAGES_SITE, "Open Published Site (S)"
        )
        actions_menu.AppendSeparator()
        self._act_select_branch = actions_menu.Append(
            ID_SELECT_BRANCH, "Select Branch…\tCtrl+B"
        )
        self._act_compare = actions_menu.Append(
            ID_COMPARE_BRANCHES, "Compare Branches…\tCtrl+Shift+B"
        )
        # A pull request's or a commit's changes. H is the key in the list.
        self._act_changed_files = actions_menu.Append(
            ID_CHANGED_FILES, "Changed Files (H)\tCtrl+Shift+H"
        )
        self._act_open_diff = actions_menu.Append(ID_OPEN_DIFF, "Open Diff in Default App")
        # A repository's files. H, B and W are the keys in the list.
        self._act_file_history = actions_menu.Append(ID_FILE_HISTORY, "File History (H)")
        self._act_blame = actions_menu.Append(ID_BLAME, "Blame (B)")
        self._act_whole_file = actions_menu.Append(ID_WHOLE_FILE, "Open Whole File (W)")
        # A pull request's line, in Changed Files: M in the file's lines.
        self._act_comment_line = actions_menu.Append(ID_COMMENT_LINE, "Comment on This Line… (M)")
        actions_menu.AppendSeparator()
        # G in Activity and Notifications; here so the command can be found.
        self._act_go_to_repo = actions_menu.Append(
            ID_GO_TO_EVENT_REPO, "Go to Event's Repository (G)\tCtrl+Shift+G"
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
        # A repository's code. No Ctrl+number is left; checked in File History too.
        show_menu.AppendRadioItem(ID_VIEW_CODE, "Files")
        show_menu.AppendRadioItem(ID_VIEW_SECURITY, "Security Alerts")
        show_menu.AppendRadioItem(ID_VIEW_DISCUSSIONS, "Discussions")
        show_menu.AppendRadioItem(ID_VIEW_MILESTONES, "Milestones")
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
        view_menu.Append(ID_CHOOSE_COLUMNS, "Columns…")

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

        # How Changed Files marks each line; the same choices as The Chat Place.
        marks_menu = wx.Menu()
        self._diff_style_items: dict[int, str] = {}
        for style in diffview.STYLES:
            item_id = wx.NewIdRef()
            self._diff_style_items[int(item_id)] = style
            marks_menu.AppendRadioItem(item_id, diffview.LABELS[style])
            self.Bind(wx.EVT_MENU, lambda e, st=style: self._set_diff_style(st), id=item_id)
        view_menu.AppendSubMenu(marks_menu, "Mark Changed Lines With")

        view_menu.AppendSeparator()
        self._show_read_item = view_menu.AppendCheckItem(
            ID_SHOW_READ, "Include Read Notifications (I)"
        )
        view_menu.AppendSeparator()
        # What an action did, said as well as shown in the status bar. For
        # now the Columns dialog's actions; more as #54 moves them over.
        view_menu.AppendCheckItem(ID_SPEAK_RESULTS, "Speak Results")

        menu_bar.Append(view_menu, "View")

        # Help menu
        help_menu = wx.Menu()
        help_menu.Append(ID_USER_GUIDE, "User Guide\tF1")
        help_menu.Append(ID_SHORTCUTS, "Keyboard Shortcuts\tCtrl+F1")
        help_menu.Append(ID_COMMAND_PALETTE, "Command Palette…\tCtrl+Shift+P")
        help_menu.AppendSeparator()
        help_menu.Append(ID_CHECK_UPDATES, "Check for Updates…")
        help_menu.Append(wx.ID_ABOUT, "About GHManage")
        menu_bar.Append(help_menu, "Help")

        self.SetMenuBar(menu_bar)

        self.Bind(wx.EVT_MENU, self.on_user_guide, id=ID_USER_GUIDE)
        self.Bind(wx.EVT_MENU, self.on_shortcuts, id=ID_SHORTCUTS)
        self.Bind(wx.EVT_MENU, self.on_command_palette, id=ID_COMMAND_PALETTE)
        self.Bind(wx.EVT_MENU, self.on_check_updates, id=ID_CHECK_UPDATES)
        self.Bind(wx.EVT_MENU, self.on_about, id=wx.ID_ABOUT)

        # Bind mode/state/tab menu items
        self.Bind(wx.EVT_MENU, self.on_quick_mode, id=ID_QUICK_MODE)
        self.Bind(wx.EVT_MENU, self.on_full_mode, id=ID_FULL_MODE)
        self.Bind(wx.EVT_MENU, self.on_choose_columns, id=ID_CHOOSE_COLUMNS)
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
        self.Bind(wx.EVT_MENU, self.on_view_security, id=ID_VIEW_SECURITY)
        self.Bind(wx.EVT_MENU, self.on_view_discussions, id=ID_VIEW_DISCUSSIONS)
        self.Bind(wx.EVT_MENU, self.on_view_milestones, id=ID_VIEW_MILESTONES)
        self.Bind(wx.EVT_MENU, self.on_view_activity, id=ID_VIEW_ACTIVITY)
        self.Bind(wx.EVT_MENU, self.on_view_notifications, id=ID_VIEW_NOTIFICATIONS)
        self.Bind(wx.EVT_MENU, lambda e: self._toggle_include_read(), id=ID_SHOW_READ)
        self.Bind(wx.EVT_MENU, lambda e: self._toggle_speak_results(), id=ID_SPEAK_RESULTS)
        self.Bind(wx.EVT_MENU, lambda e: self._mark_notification_read(), id=ID_MARK_READ)
        self.Bind(wx.EVT_MENU, lambda e: self._mark_all_read(), id=ID_MARK_ALL_READ)
        self.Bind(wx.EVT_MENU, lambda e: self._unsubscribe_notification(), id=ID_UNSUBSCRIBE)
        self.Bind(wx.EVT_MENU, self.on_view_starred, id=ID_VIEW_STARRED)
        self.Bind(wx.EVT_MENU, self.on_view_watched, id=ID_VIEW_WATCHED)
        self.Bind(wx.EVT_MENU, self.on_view_shared, id=ID_VIEW_SHARED)
        self.Bind(wx.EVT_MENU, self.on_view_orgs, id=ID_VIEW_ORGS)
        self.Bind(wx.EVT_MENU, self.on_favorite, id=ID_FAVORITE)
        for view, menu_id in ID_GO_TO_VIEW.items():
            self.Bind(wx.EVT_MENU, lambda e, v=view: self._go_to_repo_view(v), id=menu_id)
        self.Bind(wx.EVT_MENU, self.on_go_to_event_repo, id=ID_GO_TO_EVENT_REPO)
        self.Bind(wx.EVT_MENU, lambda e: self._copy("link"), id=ID_COPY_LINK)
        self.Bind(wx.EVT_MENU, lambda e: self._copy("markdown"), id=ID_COPY_MARKDOWN)
        self.Bind(wx.EVT_MENU, lambda e: self._copy("title"), id=ID_COPY_TITLE)
        self.Bind(wx.EVT_MENU, lambda e: self._copy("ident"), id=ID_COPY_IDENT)
        self.Bind(wx.EVT_MENU, lambda e: self._copy("details"), id=ID_COPY_DETAILS)
        self.Bind(wx.EVT_MENU, lambda e: self._diff_action("copy"), id=ID_COPY_DIFF)
        self.Bind(wx.EVT_MENU, lambda e: self._diff_action("open"), id=ID_OPEN_DIFF)
        self.Bind(wx.EVT_MENU, lambda e: self._show_changed_files(), id=ID_CHANGED_FILES)
        self.Bind(wx.EVT_MENU, lambda e: self._switch_view(VIEW_CODE), id=ID_VIEW_CODE)
        self.Bind(wx.EVT_MENU, lambda e: self._show_file_history(), id=ID_FILE_HISTORY)
        self.Bind(wx.EVT_MENU, lambda e: self._toggle_blame(), id=ID_BLAME)
        self.Bind(wx.EVT_MENU, lambda e: self._open_whole_file(), id=ID_WHOLE_FILE)
        self.Bind(wx.EVT_MENU, lambda e: self._comment_on_line(), id=ID_COMMENT_LINE)
        self.Bind(wx.EVT_MENU, lambda e: self._copy_clone_url("https"), id=ID_COPY_CLONE_HTTPS)
        self.Bind(wx.EVT_MENU, lambda e: self._copy_clone_url("ssh"), id=ID_COPY_CLONE_SSH)

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

    def _menu_commands(self, enabled_only: bool) -> list:
        """Every command on the menu bar as a ``commands.Command``, in menu
        order, with the menu it is on. The Actions menu is brought up to date
        first, so what is enabled is what applies right now."""
        self._update_actions_menu()
        menu_bar = self.GetMenuBar()
        out: list = []

        def walk(menu, where: str) -> None:
            for mi in menu.GetMenuItems():
                if mi.IsSeparator():
                    continue
                if enabled_only and not mi.IsEnabled():
                    continue
                name, keys = commands.split_label(mi.GetItemLabel())
                if sys.platform == "darwin":
                    keys = keys.replace("Ctrl+", "Cmd+")
                sub = mi.GetSubMenu()
                if sub is not None:
                    walk(sub, f"{where}{commands.MENU_SEP}{name}")
                    continue
                checked = mi.IsCheckable() and mi.IsChecked()
                out.append(commands.Command(name, keys, where, mi.GetId(), checked))

        for i in range(menu_bar.GetMenuCount()):
            walk(menu_bar.GetMenu(i), menu_bar.GetMenuLabelText(i))
        return out

    def on_shortcuts(self, event) -> None:
        """Help ▸ Keyboard Shortcuts (Ctrl+F1): every key, filterable (#3)."""
        rows = commands.shortcut_rows(self._menu_commands(enabled_only=False))
        dlg = CommandListDialog(
            self, "Keyboard Shortcuts", rows,
            (("Key", 190), ("Command", 330), ("Where", 200)),
            lambda c: (c.keys, c.name, c.where))
        dlg.ShowModal()
        dlg.Destroy()

    def on_command_palette(self, event) -> None:
        """Help ▸ Command Palette (Ctrl+Shift+P): find any command that
        applies here by name, and run it (#27)."""
        rows = [c for c in self._menu_commands(enabled_only=True)
                if c.id != ID_COMMAND_PALETTE]
        dlg = CommandListDialog(
            self, "Command Palette", rows,
            (("Command", 330), ("Shortcut", 150), ("Menu", 240)),
            lambda c: (c.name + (", checked" if c.checked else ""), c.keys, c.where),
            palette=True)
        # Copy, Favorite, New Issue and others act on the pane with focus.
        before = self._current_focus()
        try:
            chosen = dlg.chosen if dlg.ShowModal() == wx.ID_OK else None
        finally:
            dlg.Destroy()
        if chosen is not None:
            # After the palette has gone, so a command that opens a dialog of
            # its own opens it over the main window, and focus is back where
            # the command expects it.
            wx.CallAfter(self._run_menu_command, chosen.id, before)

    def _run_menu_command(self, command_id: int, focus=None) -> None:
        """Do what choosing the menu item does, from the pane that had focus."""
        if focus:  # a destroyed window is falsy
            focus.SetFocus()
        event = wx.CommandEvent(wx.wxEVT_MENU, command_id)
        self.GetEventHandler().ProcessEvent(event)

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
        menu_bar.Check(ID_VIEW_CODE, self.view_mode in (VIEW_CODE, VIEW_HISTORY))
        menu_bar.Check(ID_VIEW_SECURITY, self.view_mode == VIEW_SECURITY)
        menu_bar.Check(ID_VIEW_DISCUSSIONS, self.view_mode == VIEW_DISCUSSIONS)
        menu_bar.Check(ID_VIEW_MILESTONES, self.view_mode == VIEW_MILESTONES)
        menu_bar.Check(ID_VIEW_NOTIFICATIONS, self.view_mode == VIEW_NOTIFICATIONS)
        menu_bar.Check(ID_VIEW_MY_WORK, self.view_mode == VIEW_MY_WORK)
        menu_bar.Check(ID_VIEW_SEARCH_RESULTS, self.view_mode in SEARCH_VIEWS)
        menu_bar.Check(ID_VIEW_ACTIVITY, self.view_mode == VIEW_ACTIVITY)
        menu_bar.Check(ID_SHOW_READ, self._include_read)
        menu_bar.Check(ID_SPEAK_RESULTS, announce.announcer.categories[announce.RESULT])
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
        # Sort order
        for item_id, order in self._sort_menu_items.items():
            menu_bar.Check(item_id, order == self.sort_order)
        for item_id, style in self._diff_style_items.items():
            menu_bar.Check(item_id, style == self._diff_style)
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
        self._act_comment.Enable(issues or self.view_mode == VIEW_DISCUSSIONS)

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
            "Go to Notification's Repository (G)\tCtrl+Shift+G"
            if self.view_mode == VIEW_NOTIFICATIONS
            else "Go to Event's Repository (G)\tCtrl+Shift+G"
            if self.view_mode == VIEW_ACTIVITY
            else "Go to Repository (G)\tCtrl+Shift+G"
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
        self._act_select_branch.Enable(self.view_mode in (VIEW_COMMITS, VIEW_CODE))
        self._act_select_branch.SetItemLabel(
            "Select Branch or Tag…\tCtrl+B" if self.view_mode == VIEW_CODE
            else "Select Branch…\tCtrl+B")
        self._act_compare.Enable(self.view_mode == VIEW_BRANCHES)
        changes = self.view_mode in (VIEW_ISSUES, VIEW_COMMITS, VIEW_HISTORY)
        self._act_changed_files.Enable(changes)
        self._act_copy_diff.Enable(changes or self.view_mode == VIEW_FILES)
        self._act_open_diff.Enable(changes or self.view_mode == VIEW_FILES)
        self._act_file_history.Enable(self.view_mode == VIEW_CODE)
        self._act_blame.Enable(self.view_mode == VIEW_CODE)
        self._act_whole_file.Enable(self.view_mode == VIEW_FILES)
        self._act_comment_line.Enable(
            self.view_mode == VIEW_FILES and isinstance(self._files_of, Item))
        noun = " ".join(w if w == "or" else w.capitalize()
                        for w in GhViewerFrame._nav_noun(self).split())
        self._act_next_comment.SetItemLabel(f"Next {noun}\tAlt+N")
        self._act_prev_comment.SetItemLabel(f"Previous {noun}\tAlt+P")
        # An artifact has no page of its own on github.com to link to.
        linkable = self.view_mode != VIEW_ARTIFACTS
        self._act_copy_link.Enable(linkable)
        self._act_copy_markdown.Enable(linkable)
        noun = self._COPY_IDENT_NOUNS.get(self.view_mode, "Name")
        self._act_copy_ident.SetItemLabel(f"Copy {noun}\tCtrl+Shift+I")

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
        if mode != VIEW_FILES:
            self._files_of = None
            self._files_back = None
        if mode != VIEW_CODE:
            GhViewerFrame._reset_code(self)
        if mode != VIEW_HISTORY:
            self._history_of = None
            self._history_back = None
        if mode != VIEW_ISSUES:
            self.label_filter = ""
            self.milestone_filter = None
        if mode not in (VIEW_PAGES, VIEW_PAGEFILES):
            self.pages_site = None
        if mode != getattr(self, "_return_view", VIEW_ISSUES):
            # The way back to the list is from the view it opened in, where G
            # or Enter left you; anywhere else Backspace means something of
            # its own.
            self._return_to = None
        self.filter_text = ""  # clear filter on view switch
        # Update columns for the new view
        self.columns = settings.load_columns(_view_columns(mode))
        self._rebuild_columns()
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
            self.list_ctrl.Bind(wx.EVT_CHAR, self.on_list_char)
        self.details_text.Bind(wx.EVT_CHAR_HOOK, self.on_details_key_down)
        # Frame-level, so Insert/Delete in the Labels view work wherever focus
        # is — including the details panel, which is where the text describing
        # them is read. EVT_LIST_KEY_DOWN only fires for the list itself, which
        # made that text an instruction you could read but not follow.
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        self.Bind(wx.EVT_MENU, self.on_refresh, id=ID_REFRESH)
        self.Bind(wx.EVT_MENU, self.on_open_repo, id=ID_OPEN_REPO)
        self.Bind(wx.EVT_MENU, self.on_remove_repo, id=ID_REMOVE_REPO)
        self.Bind(wx.EVT_MENU, self.on_hidden_repos, id=ID_HIDDEN_REPOS)
        self.Bind(wx.EVT_MENU, lambda e: self.on_archive_repo(), id=ID_ARCHIVE_REPO)
        self.Bind(wx.EVT_MENU, lambda e: self.on_delete_repo(), id=ID_DELETE_REPO)
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
        # Another account's repositories, or none yet: see on_remove_repo.
        self._repos_known = False
        self._repos_failed = False
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
            # Your own repositories are known now, so removing one can tell
            # whether it is yours (see on_remove_repo).
            self._repos_known = True
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
        # Lower case: GitHub names aren't case-sensitive, and a pin typed as
        # Owner/Repo is the same repository as owner/repo from your account.
        shown = set()
        for name in self._pinned_repos:
            if name.lower() in shown:
                continue
            shown.add(name.lower())
            # If it's also in the gh list, reuse its description
            desc = ""
            for r in repos:
                if r.get("nameWithOwner", "").lower() == name.lower():
                    desc = r.get("description") or ""
                    break
            label = f"📌 {name} — {desc}" if desc else f"📌 {name}"
            self.repo_list.Append(label, clientData=name)
        # Then the user's own repos. Organizations' are under My
        # Organizations, so a big one can't bury these. Not the ones you
        # removed: GitHub still lists them, so they are left out here.
        hidden = {h.lower() for h in self._hidden_repos}
        n_hidden = 0
        for repo in repos:
            name = repo.get("nameWithOwner", "")
            if name.lower() in shown:
                continue
            if name.lower() in hidden:
                n_hidden += 1
                continue
            shown.add(name.lower())
            desc = repo.get("description") or ""
            label = f"{name} — {desc}" if desc else name
            self.repo_list.Append(label, clientData=name)
        hidden_note = f" ({n_hidden} hidden)" if n_hidden else ""
        self._announce(
            f"Loaded {len(shown)} repositories{hidden_note}. "
            "Select one to view issues and PRs."
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
        self._repos_failed = True
        self._announce(f"Error loading repos: {msg}")

    def on_repo_activated(self, event: wx.CommandEvent) -> None:
        """Double-click on repo list — load that repo's items."""
        self._activate_repo_entry()

    def on_repo_key_down(self, event: wx.KeyEvent) -> None:
        """Enter opens the selected entry; F favorites the selected repository."""
        if event.GetKeyCode() == wx.WXK_RETURN:
            self._activate_repo_entry()
            return  # swallow the key
        if event.GetKeyCode() == ord("F") and not self._modifiers_down(event):
            self._favorite_selected_repo()
            return
        if event.GetKeyCode() == wx.WXK_DELETE and not self._modifiers_down(event):
            self.on_remove_repo(None)
            return
        event.Skip()

    def _selected_repo_entry(self) -> RepoEntry | None:
        """The repository selected in the repository list, if it is one."""
        idx = self.repo_list.GetSelection()
        name = self.repo_list.GetClientData(idx) if idx != wx.NOT_FOUND else None
        if not is_repo_entry(name):
            return None
        desc = next((r.get("description") or "" for r in self._all_repos
                     if r.get("nameWithOwner") == name), "")
        return RepoEntry(name, desc, f"https://github.com/{name}")

    def _favorite_selected_repo(self) -> None:
        """F in the repository list: favorite the repository, or unfavorite it."""
        repo = self._selected_repo_entry()
        if repo is None:
            self._announce("Select a repository to favorite.")
            return
        entry = self._build_favorite_entry(repo)
        self.favorites, was_added = toggle_favorite(entry, self.favorites)
        if was_added:
            self._announce("Added to favorites")
        else:
            self._announce("Removed from favorites")
        self._refresh_repo_list_fav_count()
        if self.view_mode == VIEW_FAVORITES:
            self._load_favorites_view()
        else:
            self._redraw_favorite_marks()

    def on_favorite(self, event: wx.CommandEvent) -> None:
        """Actions ▸ Add or Remove Favorite: the repository when the
        repository list has focus, else the row in the list."""
        if self._pane_index(self._current_focus()) == 0:
            self._favorite_selected_repo()
        else:
            self._toggle_favorite()

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
        self.milestone_filter = None  # nor a milestone
        GhViewerFrame._reset_code(self)  # nor a folder or branch of it
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

    def _load_favorites_view(self, focus=None) -> None:
        """Populate the list with all favorited items (mixed types, cross-repo).

        ``focus`` is a favorite to land on (Backspace from a repository
        opened from here), found by its address since the list is reread.
        """
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
            "F=unfavorite  Enter=open (a repository here, the rest in the browser)  "
            "Ctrl+O=open on GitHub  Ctrl+F=filter",
        )
        self._update_title()
        url = getattr(focus, "url", None)
        row = next((i for i, f in enumerate(self._shown) if url and f.url == url), 0)
        if filtered:
            wx.CallLater(100, self._focus_list, row)

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
        commit_branch = self.commit_branch
        files_of = getattr(self, "_files_of", None)
        code_ref, code_path = getattr(self, "_code_ref", ""), getattr(self, "_code_path", "")
        history_of = getattr(self, "_history_of", None)
        repo = self.repo
        state = self.state_filter
        include_read = self._include_read
        milestone = getattr(self, "milestone_filter", None)
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
                            self.label_filter, milestone,
                        )
                    if self.tab_filter in ("prs", "both"):
                        prs = fetch_prs(
                            self.repo, self.state_filter, self.current_limit,
                            self.label_filter, milestone,
                        )
                    combined = sort_items(issues + prs, self.sort_order)
                    wx.CallAfter(
                        self._on_items_loaded, token, combined, len(issues), len(prs)
                    )
                elif view == VIEW_BRANCHES:
                    branches = fetch_branches(self.repo, self.current_limit)
                    wx.CallAfter(self._on_git_items_loaded, token, branches, "branches")
                elif view == VIEW_COMMITS and commit_branch == ALL_BRANCHES:
                    commits, unread = fetch_all_branch_commits(self.repo, limit)
                    wx.CallAfter(self._on_all_branch_commits_loaded, token, commits, unread)
                elif view == VIEW_COMMITS:
                    commits = fetch_commits(self.repo, commit_branch, limit)
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
                elif view == VIEW_FILES:
                    note, head = "", ""
                    if isinstance(files_of, Item):
                        # The commit these lines are of, read first: a line
                        # comment is refused if the pull request has moved on
                        # from it (see _comment_on_line).
                        try:
                            head = fetch_pr_head_sha(files_of.url)
                        except GhError:
                            head = ""
                        files = fetch_pr_files(files_of.url)
                        # The files still show if their comments can't be read.
                        try:
                            GhViewerFrame._attach_comments(
                                files, fetch_pr_review_comments(files_of.url))
                        except GhError as exc:
                            note = f"Couldn't read the review comments: {exc}"
                    elif isinstance(files_of, Commit):
                        files = fetch_commit_files(self.repo, files_of.sha)
                    else:
                        files = []
                    wx.CallAfter(self._on_files_loaded, token, files, note, head)
                elif view == VIEW_CODE:
                    ref = code_ref or fetch_default_branch(repo) or "HEAD"
                    path, note = code_path, ""
                    try:
                        entries, cut = fetch_repo_folder(repo, ref, path)
                    except GhError as exc:
                        if not path or "404" not in str(exc):
                            raise
                        # Not on this branch or tag: its top instead.
                        note = f"{path} isn't on {ref}, so this is the top."
                        path = ""
                        entries, cut = fetch_repo_folder(repo, ref, path)
                    wx.CallAfter(self._on_code_loaded, token, ref, path, entries, cut, note)
                elif view == VIEW_HISTORY:
                    commits = (fetch_file_history(repo, history_of[1], history_of[0], limit)
                               if history_of else [])
                    wx.CallAfter(self._on_history_loaded, token, commits)
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
                elif view == VIEW_SECURITY:
                    report = fetch_security_alerts(repo, state, limit)
                    wx.CallAfter(self._on_security_loaded, token, report, state)
                elif view == VIEW_MILESTONES:
                    milestones = fetch_milestones(repo, state, limit)
                    wx.CallAfter(self._on_milestones_loaded, token, milestones, state)
                elif view == VIEW_DISCUSSIONS:
                    result = fetch_discussions(repo, state, limit)
                    wx.CallAfter(self._on_discussions_loaded, token, result, state)
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
        val = _row_values(item, self.columns).get(col, "")
        column = _view_columns(self.view_mode).column(col)
        position = self.columns.index(col) if col in self.columns else 0
        return cell_text(column, val, self.list_mode == "full" and names_cell(position))

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
        VIEW_FILES: "Changed Files",
        VIEW_CODE: "Files",
        VIEW_HISTORY: "File History",
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
        VIEW_SECURITY: "Security Alerts",
        VIEW_DISCUSSIONS: "Discussions",
        VIEW_MILESTONES: "Milestones",
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
            parts.append(_commit_branch_label(self.commit_branch))
        # Include the run being drilled into (artifacts view)
        if self.view_mode == VIEW_ARTIFACTS and self.artifacts_run:
            parts.append(f"run #{self.artifacts_run.run_number} {self.artifacts_run.name}")
        if self.view_mode == VIEW_JOBS and self.jobs_run:
            parts.append(f"run #{self.jobs_run.run_number} {self.jobs_run.name}")
        # Include the release being drilled into (assets view)
        if self.view_mode == VIEW_ASSETS and self.assets_release:
            parts.append(self.assets_release.tag or self.assets_release.name)
        if self.view_mode == VIEW_FILES and self._files_of is not None:
            parts.append(self._files_of_label())
        if self.view_mode == VIEW_CODE:
            parts.append(self._code_where())
        if self.view_mode == VIEW_HISTORY and self._history_of:
            parts.append(f"{self._history_of[1]} {self._history_of[2]}".strip())
        # Include the label the issues list is restricted to
        if self.view_mode == VIEW_ISSUES and self.label_filter:
            parts.append(f"label: {self.label_filter}")
        milestone = getattr(self, "milestone_filter", None)
        if self.view_mode == VIEW_ISSUES and milestone is not None:
            parts.append(f"milestone: {milestone.title}")
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
        if self.view_mode == VIEW_CODE:
            # Where you are, as the issue asked: "Files: src/ on main".
            label = f"{label}: {self._code_where()}"
        elif self.view_mode == VIEW_HISTORY and self._history_of:
            label = f"{label}: {self._history_of[1]} {self._history_of[2]}".strip()
        self.list_label.SetLabel(label)
        _name(self.list_ctrl, label)

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
        milestone = getattr(self, "milestone_filter", None)
        if milestone is not None:
            label_info = f" in milestone '{milestone.title}'"
            label_hint = "  Backspace=back to milestones"
        if self._return_to:
            back = self._view_label(self._return_to[0], lower=True)
            label_hint = f"  Backspace=back to {back}"
        unsized = ""
        if any(it.is_pr and not getattr(it, "has_stats", True) for it in items):
            unsized = (" GitHub took too long to measure these pull requests, so Changes "
                       "and Files are blank.")
        self._set_view_status(
            f"{source} — {n_issues} issues, {n_prs} PRs ({self.state_filter}){label_info}. "
            f"Showing up to {self.current_limit} newest.{unsized}",
            "Ctrl++=view more  R=refresh  M=comment  N=new issue  K=checks  V=review  "
            "H=changed files  "
            "F=favorite  Ctrl+F=filter"
            f"{label_hint}",
        )
        self._update_title()
        row = self._take_pending_row(items, token)
        if not items and label_info:
            # Enter on a milestone or label that has nothing in this state:
            # focus stays put, so say so rather than leave silence.
            which = "" if self.state_filter == "all" else f"{self.state_filter} "
            said = f"No {which}issues or PRs{label_info}."
            if self.state_filter != "all":
                said += " View, State, All shows every one."
            self.details_text.SetValue(said)
            announce.announce(said, announce.STATUS)
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

    def _on_security_loaded(self, token: int, report, state: str) -> None:
        """Security Alerts: the alerts GitHub would show, most severe first,
        and a sentence for each kind it wouldn't (not set up, no rights, or
        gh lacking the security_events permission)."""
        if not self._fetch_is_current(token):
            return  # the user has moved on; these belong to a view they left
        alerts = report.alerts
        self.git_items = alerts
        self.items = []
        filtered = self._populate_filtered_list(alerts, use_favorite_prefix=True)
        message = security_status(self.repo, report, state, self.current_limit)
        keys = "R=refresh  Ctrl+F=filter"
        if alerts:  # nothing to open, or more to show, in an empty list
            keys = ("Enter or Ctrl+O=open on GitHub  F=favorite  Ctrl++=view more  "
                    + keys)
        self._set_view_status(message, keys)
        self._update_title()
        if not alerts:
            # Nothing in the list to read, so say why here and out loud.
            self.details_text.SetValue(alertview.empty_text(report, state))
            announce.announce(message, announce.STATUS)
            return
        row = self._take_pending_row(alerts, token)
        if filtered:
            wx.CallLater(100, self._focus_list, row)

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

    def _on_all_branch_commits_loaded(self, token: int, commits: list, unread: int) -> None:
        """Commits on all branches, and how many branches couldn't be read."""
        if not self._fetch_is_current(token):
            return
        self._branches_unread = unread
        self._on_git_items_loaded(token, commits, "commits")
        if unread:
            # The status bar says so too, but a list with gaps is worth hearing
            self._announce(
                f"{unread} branch{'es' if unread != 1 else ''} couldn't be read, "
                "so their commits may be missing."
            )

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
            branch_info = (f" on {_commit_branch_label(self.commit_branch)}"
                           if self.commit_branch else " on default branch")
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
            compare_hint = "  Enter=changed files  Backspace=back to branches"
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
        elif (self.view_mode == VIEW_COMMITS and self.commit_branch == ALL_BRANCHES
              and self._branches_unread):
            n = self._branches_unread
            totals = (f" {n} branch{'es' if n != 1 else ''} couldn't be read, "
                      "so their commits may be missing.")
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
            "Enter=open  G=go to repository  Ctrl++=view more  "
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
            if kind == "same":
                return it is ref
            if kind == "item":
                return isinstance(it, Item) and str(it.number) == ref
            if kind == "commit":
                return isinstance(it, Commit) and it.sha.startswith(ref.lower())
            if kind == "release":
                return isinstance(it, Release) and it.tag == ref
            if kind == "run":
                return isinstance(it, WorkflowRun) and str(it.run_id) == ref
            if kind == "discussion":
                return isinstance(it, Discussion) and str(it.number) == ref
            if kind == "discussion_title":
                return isinstance(it, Discussion) and it.title == ref
            if kind == "milestone":
                return isinstance(it, Milestone) and str(it.number) == ref
            return False

        found = next((it for it in items if matches(it)), None)
        row = self._row_of(found) if found is not None else -1
        if row >= 0:
            if kind != "same":
                wx.CallLater(150, self._announce, self._describe_landing(found))
            return row
        if kind == "same":
            return 0
        # After the list has settled on its first row, or that would land on
        # top of the item these select — and only if that list is still the
        # one on screen when they run.
        if kind == "item":
            wx.CallLater(150, self._if_still_current, token, self._goto_issue, int(ref))
        elif kind == "discussion" and found is None:
            wx.CallLater(150, self._if_still_current, token, self._goto_discussion, int(ref))
        elif kind == "commit":
            wx.CallLater(150, self._if_still_current, token, self._goto_commit, ref)
        elif kind in ("release", "run", "discussion", "discussion_title", "milestone"):
            # (what it is, the newest of its kind, its kind)
            what, newest, plural = {
                "release": (f"Release {ref}", "newest releases", "releases"),
                "run": (f"Run {ref}", "newest workflow runs", "workflow runs"),
                "discussion": (f"Discussion #{ref}", "most recently active discussions",
                               "discussions"),
                "discussion_title": (f"The discussion “{ref}”",
                                     "most recently active discussions", "discussions"),
                "milestone": ("That milestone", "milestones listed", "milestones"),
            }[kind]
            if found is not None:
                said = f"{what} is hidden by the quick filter. Escape clears it."
            elif items:
                said = f"{what} isn't among the {len(items)} {newest}."
            else:
                said = f"{what} wasn't found: there are no {plural} to show."
            if kind in ("discussion_title", "milestone"):
                # Enter was pressed to land on it: say aloud that it didn't.
                if getattr(self, "state_filter", "all") != "all":
                    said += " A closed one shows with View, State, All."
                wx.CallLater(150, self._tell, said)
            else:
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
        if isinstance(item, Discussion):
            return f"Opened discussion #{item.number} — {item.title}"
        if isinstance(item, Milestone):
            return f"Milestone {item.title}"
        return "Opened"

    def _goto_discussion(self, number: int) -> None:
        """Show a discussion that isn't in the list (closed, or not among the
        most recently active): fetched, and put at the top."""
        if self.view_mode != VIEW_DISCUSSIONS or not self.repo:
            return
        self._announce(f"Discussion #{number} isn't in this list, fetching…")
        repo, token = self.repo, self._fetch_token

        def worker() -> None:
            try:
                found = fetch_discussion(repo, number)
            except GhError as exc:
                wx.CallAfter(self._on_discussion_fetched, None, repo, token, str(exc), number)
                return
            wx.CallAfter(self._on_discussion_fetched, found, repo, token, "", number)

        threading.Thread(target=worker, daemon=True).start()

    def _on_discussion_fetched(self, found, repo: str, token: int, err: str,
                               number: int) -> None:
        if (self.view_mode != VIEW_DISCUSSIONS or self.repo != repo
                or token != self._fetch_token):
            return  # moved on, or the list was read again since
        if found is None:
            self._tell(f"Couldn't open discussion #{number}: {err}")
            return
        self.filter_text = ""
        self.git_items = [found] + [d for d in self.git_items
                                    if getattr(d, "number", None) != found.number]
        self._populate_filtered_list(self.git_items, use_favorite_prefix=True)
        self._focus_list(0)
        where = "closed, so" if found.closed else "not among the most recently active, so"
        said = (f"Opened discussion #{found.number} — {found.title}. It is {where} "
                "it is shown first.")
        self._announce(said)
        announce.announce(said, announce.STATUS)

    def _goto_commit(self, sha: str) -> None:
        """Show a commit that isn't in the list: fetched, and put at the top."""
        if self.view_mode != VIEW_COMMITS or not self.repo:
            return
        where = "any branch" if self.commit_branch == ALL_BRANCHES else "this branch"
        self._announce(f"Commit {sha[:7]} isn't among the newest on {where}, fetching…")
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
            "It is not among the latest commits listed, so it is shown first."
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
        # Text still on its way for the last row is not for this one.
        self._detail_gen = getattr(self, "_detail_gen", 0) + 1
        item = self._row_item(row)
        source = self._view_source()
        idx = next((i for i, it in enumerate(source) if it is item), -1)
        if self.view_mode in ITEM_VIEWS:
            self._show_issue_details(idx)
        elif self.view_mode == VIEW_FILES:
            self._show_file_details(idx)
        elif self.view_mode == VIEW_CODE:
            self._show_code_details(idx)
        elif self.view_mode == VIEW_HISTORY:
            self._show_history_details(idx)
        elif self.view_mode == VIEW_FAVORITES:
            self._show_favorite_details(idx)
        elif self.view_mode == VIEW_SECURITY:
            self._show_security_details(idx)
        elif self.view_mode == VIEW_DISCUSSIONS:
            self._show_discussion_details(idx)
        elif self.view_mode == VIEW_MILESTONES:
            self._show_milestone_details(idx)
        else:
            self._show_git_details(idx)

    # ── Discussions ─────────────────────────────────────────────────────

    def _on_discussions_loaded(self, token: int, result, state: str) -> None:
        """Discussions: most recently active first; with discussions turned
        off, or none to show, the details panel and speech say so."""
        if not self._fetch_is_current(token):
            return  # the user has moved on; these belong to a view they left
        items = result.items
        self.git_items = items
        self.items = []
        self._discussions_off = not result.enabled
        filtered = self._populate_filtered_list(items, use_favorite_prefix=True)
        message = discussionview.status_message(result, self.repo, state,
                                                self.current_limit)
        keys = "R=refresh  Ctrl+F=filter"
        if items:
            keys = ("Enter or Ctrl+O=open on GitHub  M=comment  Alt+N/Alt+P=comments  "
                    "F=favorite  Ctrl++=view more  " + keys)
        self._set_view_status(message, keys)
        self._update_title()
        if not items:
            self.details_text.SetValue(discussionview.empty_text(result, self.repo, state))
            announce.announce(message, announce.STATUS)
            if result.enabled:
                # A notification or event about a discussion was on its way
                # here: a closed one is still fetched by its number.
                self._take_pending_row(items, token)
            else:
                self._pending_target = None  # turned off says it all
            return
        row = self._take_pending_row(items, token)
        if filtered:
            wx.CallLater(100, self._focus_list, row)

    def _on_milestones_loaded(self, token: int, milestones: list, state: str) -> None:
        """Milestones: GitHub's order, nearest due date first, then those
        without one."""
        if not self._fetch_is_current(token):
            return  # the user has moved on; these belong to a view they left
        self.git_items = milestones
        self.items = []
        filtered = self._populate_filtered_list(milestones, use_favorite_prefix=True)
        source = self.repo
        if milestones and milestones[0].repo and milestones[0].repo != self.repo:
            source = f"{self.repo} (milestones from upstream {milestones[0].repo})"
        message = milestoneview.status_message(source, milestones, state)
        keys = "R=refresh  Ctrl+F=filter"
        if milestones:
            keys = ("Enter=issues and PRs  Ctrl+O=open on GitHub  F=favorite  "
                    "Ctrl++=view more  " + keys)
        self._set_view_status(message, keys)
        self._update_title()
        row = self._take_pending_row(milestones, token)
        if not milestones:
            which = {"open": "open ", "closed": "closed "}.get(state, "")
            self.details_text.SetValue(f"{source} has no {which}milestones.")
            announce.announce(message, announce.STATUS)
            return
        if filtered:
            wx.CallLater(100, self._focus_list, row)

    def _show_milestone_details(self, idx: int) -> None:
        if idx < 0 or idx >= len(self.git_items):
            self.details_text.Clear()
            return
        item = self.git_items[idx]
        if not isinstance(item, Milestone):
            self.details_text.Clear()
            return
        self.details_text.SetValue(milestoneview.milestone_details(item))

    def _show_discussion_details(self, idx: int) -> None:
        """A discussion: its fields and body now, its comments once read
        (fetched when the selection has rested on it a moment)."""
        if idx < 0 or idx >= len(self.git_items):
            self.details_text.Clear()
            return
        item = self.git_items[idx]
        if not isinstance(item, Discussion):
            self.details_text.Clear()
            return
        self._render_discussion(item)
        if item.comments is None and item.comment_count:
            self._fetch_discussion_comments_later(item, self._detail_gen)

    def _render_discussion(self, item: Discussion, keep_place: bool = False) -> None:
        """Put ``item`` in the details panel. With ``keep_place``, the caret
        stays on the line and column it was on, so text arriving under what
        is being read doesn't move it."""
        line = col = 0
        if keep_place:
            caret = self.details_text.GetInsertionPoint()
            old = self.details_text.GetValue()
            line = old.count("\n", 0, caret)
            col = caret - (old.rfind("\n", 0, caret) + 1)
        text, positions = discussionview.discussion_details(item)
        self.details_text.SetValue(text)
        self._comment_positions = list(positions)
        self._current_comment = -1
        if keep_place and (line or col):
            start = self._line_to_position(line)
            end = self._line_to_position(line + 1)
            self.details_text.SetInsertionPoint(min(start + col, max(start, end - 1)))
            # Alt+N from here goes on to the next comment after the caret.
            self._current_comment = sum(1 for p in positions if p[0] <= line) - 1

    def _fetch_discussion_comments_later(self, item: Discussion, gen: int) -> None:
        """Read a discussion's comments once the selection has rested on it,
        so arrowing down the list doesn't read every discussion passed."""
        repo = self.repo
        version = item.comments_version

        def worker() -> None:
            try:
                comments, cut = fetch_discussion_comments(repo, item.number)
                err = ""
            except GhError as exc:
                comments, cut, err = None, False, str(exc)
            wx.CallAfter(self._on_discussion_comments, gen, item, comments, cut, err, version)

        def start() -> None:
            if gen == self._detail_gen:
                threading.Thread(target=worker, daemon=True).start()

        wx.CallLater(250, start)

    def _on_discussion_comments(self, gen: int, item: Discussion, comments, cut: bool,
                                err: str, version: int = 0) -> None:
        if version != item.comments_version:
            return  # read again since (after M posted); that reading is newer
        if comments is not None:
            item.comments, item.comments_cut = comments, cut
        if not self._shows(VIEW_DISCUSSIONS, item, gen):
            return
        reading = self.FindFocus() is self.details_text
        if comments is None:
            caret = self.details_text.GetInsertionPoint()
            text = self.details_text.GetValue()
            said = f"Couldn't read the comments: {err}"
            self.details_text.SetValue(text.rsplit("\n", 1)[0] + "\n" + said)
            self.details_text.SetInsertionPoint(caret)
        else:
            self._render_discussion(item, keep_place=reading)
            n = len(comments)
            said = f"{n} comment{'' if n == 1 else 's'} read." if n else ""
        if reading and said:
            # A focused text box's new value isn't read: say it arrived.
            announce.announce(said, announce.STATUS)

    def _comment_on_discussion(self) -> None:
        """M, or Actions > Add Comment, in Discussions: a comment on the
        selected discussion, then its comments read again."""
        if self.view_mode != VIEW_DISCUSSIONS:
            return
        item = self._focused_item()
        if not isinstance(item, Discussion):
            self._tell(f"{self.repo} has discussions turned off."
                       if getattr(self, "_discussions_off", False)
                       else "Select a discussion first.")
            return
        if item.locked:
            self._tell(f"Discussion #{item.number} is locked, so it can't take comments.")
            return
        if getattr(self, "_discussion_comment_busy", False):
            self._tell("Still adding the last comment.")
            return
        dlg = wx.TextEntryDialog(
            self, f"Add a comment to discussion #{item.number}:\n{item.title}",
            "Add Comment", "", style=wx.TE_MULTILINE | wx.OK | wx.CANCEL)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            body = dlg.GetValue().strip()
        finally:
            dlg.Destroy()
        if not body:
            return
        self._discussion_comment_busy = True
        self._announce(f"Adding a comment to discussion #{item.number}…")
        repo = self.repo
        # Any read of the comments still on its way is older than the one
        # after this post.
        item.comments_version += 1

        def worker() -> None:
            # Any failure, not only gh's, comes back to clear the busy flag.
            try:
                add_discussion_comment(item, body)
            except Exception as exc:  # noqa: BLE001
                wx.CallAfter(self._on_discussion_comment_done, item, False, None, False,
                             str(exc))
                return
            try:
                comments, cut = fetch_discussion_comments(repo, item.number)
                err = ""
            except Exception as exc:  # noqa: BLE001
                comments, cut, err = None, False, str(exc)
            wx.CallAfter(self._on_discussion_comment_done, item, True, comments, cut, err)

        threading.Thread(target=worker, daemon=True).start()

    def _on_discussion_comment_done(self, item: Discussion, posted: bool, comments,
                                    cut: bool, err: str) -> None:
        """The comment is in (or isn't): the discussion read again with it,
        the caret kept where it was, and its Comments column brought up to date."""
        self._discussion_comment_busy = False
        if not posted:
            self._tell(f"Couldn't add the comment. {err}".strip())
            return
        msg = f"Comment added to discussion #{item.number}."
        if comments is None:
            item.comment_count += 1
            # What was read is out of date: read it again when next shown.
            item.comments = None
            msg += f" Couldn't read the comments again: {err}"
        else:
            item.comments, item.comments_cut = comments, cut
            item.comment_count = (max(item.comment_count + 1, len(comments)) if cut
                                  else len(comments))
        if self.view_mode == VIEW_DISCUSSIONS:
            row = self._row_of(item)
            if row >= 0:
                self._redraw_row(row, item)
            if self._focused_item() is item:
                self._render_discussion(item, keep_place=True)
                if item.comments is None:
                    self._fetch_discussion_comments_later(item, self._detail_gen)
        self._tell(msg)

    def _show_security_details(self, idx: int) -> None:
        """A security alert: everything GitHub says about it (alertview)."""
        if idx < 0 or idx >= len(self.git_items):
            self.details_text.Clear()
            return
        item = self.git_items[idx]
        if not isinstance(item, SecurityAlert):
            self.details_text.Clear()
            return
        self.details_text.SetValue(alertview.alert_details(item))

    def _open_alert(self, alert: SecurityAlert) -> None:
        """Enter or Ctrl+O on a security alert: its page on GitHub."""
        name = f"{alert.kind_display} alert {alert.number}".strip()
        if not alert.url:
            self._tell(f"{name} has no page to open.")
            return
        webbrowser.open(alert.url)
        self._announce(f"Opened {name} in browser")

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
        if fav.item_type == "repository":
            lines.append("Press Enter to open it here in GHManage, Ctrl+O to open it on GitHub.")
        else:
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
            if getattr(self, "view_mode", None) == VIEW_ISSUES:
                lines.append("Press H to read the changed files.")
            if getattr(self, "view_mode", None) == VIEW_ISSUES and item.state == "OPEN":
                lines.append("Keys: K checks, V review, D "
                             + ("ready for review" if item.is_draft else "back to draft")
                             + "; Actions > Pull Request to merge.")
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
            if len(item.branches) > 1:
                lines.append(f"Branches: {', '.join(item.branches)}")
            elif item.branches:
                lines.append(f"Branch: {item.branches[0]}")
            elif self.commit_branch != ALL_BRANCHES:
                # Opened on its own (Go To, an address): the list's branch.
                # On all branches there is no telling which, so nothing.
                lines.append(f"Branch: {self.commit_branch or 'default branch'}")
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
            if getattr(self, "view_mode", None) == VIEW_COMMITS:
                lines.append("")
                # H, not Enter: Enter only works in the list, and this is read
                # in the details panel.
                lines.append("Press H to read the changed files, "
                             "Ctrl+O to open the commit on GitHub.")
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
        VIEW_FILES: "Path",
        VIEW_CODE: "Path",
        VIEW_HISTORY: "SHA",
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
        # CVE or GHSA ID, rule ID, or secret type, by the kind of alert.
        VIEW_SECURITY: "Advisory, Rule or Secret Type",
        VIEW_DISCUSSIONS: "Number",
        VIEW_MILESTONES: "Milestone Title",
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

    def _copy_clone_url(self, kind: str) -> None:
        """Copy ▸ Copy HTTPS / SSH Clone URL, for the repository in front of you."""
        repo = self._repo_in_front()
        if not repo:
            self._announce("Select a repository first: there is nothing to clone.")
            return
        url = clone_url(repo, kind)
        noun = "SSH clone URL" if kind == "ssh" else "HTTPS clone URL"
        if self._set_clipboard(url):
            self._announce(f"Copied {noun}: {url}")
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
        if (keys and getattr(self, "_return_to", None)
                and self.view_mode == getattr(self, "_return_view", VIEW_ISSUES)):
            # Backspace goes back to the list this was opened from, whatever
            # it would do in this view otherwise (Commits > Branches).
            back = f"Backspace=back to {self._view_label(self._return_to[0], lower=True)}"
            keys = "  ".join([k for k in keys.split("  ") if k and not k.startswith("Backspace=")]
                             + [back])
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
                self._announce(row_text(_row_values(item, self.columns),
                                        _view_columns(self.view_mode).defs(self.columns)))

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
        if self.view_mode == VIEW_MILESTONES and isinstance(item, Milestone):
            self._browse_milestone(item)
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
        if self.view_mode == VIEW_FILES and isinstance(item, ChangedFile):
            self._read_changes()
            return
        if self.view_mode == VIEW_CODE and isinstance(item, RepoFile):
            if item.is_dir:
                self._code_open_folder(item)
            else:
                self._read_changes()
            return
        if self.view_mode == VIEW_HISTORY and isinstance(item, Commit):
            self._show_changed_files()
            return
        # In Commits, Enter steps into the commit's changed files, as Enter on
        # a branch steps into its commits; Ctrl+O opens it on GitHub.
        if self.view_mode == VIEW_COMMITS and isinstance(item, Commit):
            self._show_changed_files()
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
        # In Favorites view, Enter opens a repository here and the rest in
        # the browser
        if self.view_mode == VIEW_FAVORITES and isinstance(item, FavoriteEntry):
            if item.item_type == "repository" and item.repo:
                self._open_repo_from_list(item.repo, item)
                return
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
        if isinstance(item, SecurityAlert):
            self._open_alert(item)
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
        VIEW_COMMITS: "Changed Files",
        VIEW_WORKFLOWS: "Run on a Branch…",
        VIEW_WORKFLOW: "List Artifacts",
        VIEW_JOBS: "Read Log",
        VIEW_FILES: "Read the Changes",
        VIEW_HISTORY: "Changed Files",
        VIEW_CODE: "Open",
        VIEW_ARTIFACTS: "Download…",
        VIEW_RELEASES: "List Files",
        VIEW_LABELS: "List Issues and PRs with This Label",
        VIEW_MILESTONES: "List Its Issues and PRs",
        VIEW_PAGES: "Browse Published Pages",
        VIEW_NOTIFICATIONS: "Open",
        VIEW_ACTIVITY: "Open",
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
        if self.view_mode in (VIEW_COMMITS, VIEW_HISTORY):
            same_as_enter.add(ID_CHANGED_FILES)
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
        if isinstance(item, RepoEntry):
            # After Enter's entry.
            at = 1 if entries[:1] and entries[0][1] == ID_CTX_OPEN else 0
            entries[at:at] = [("sep",), go_to_submenu(), ("sep",)]
        # View More lives on the File menu, so it was missing here, where
        # people look for "what else can I do in this list" (#52).
        if self.view_mode not in NO_MORE_VIEWS:
            entries += ([("sep",)] if entries else []) + [
                ("item", ID_VIEW_MORE, "View More\tCtrl++")]
        # Say which way F goes for this row, or leave it off where there is
        # nothing it could favorite.
        if self.view_mode == VIEW_FAVORITES:
            fav_label = "Remove from Favorites (F)"
        elif (item is None or isinstance(item, (OrgEntry, ChangedFile))
              or not getattr(item, "url", "")):
            fav_label = None
        elif self._favorite_prefix(item):
            fav_label = "Remove from Favorites (F)"
        else:
            fav_label = "Add to Favorites (F)"
        out = []
        for entry in entries:
            if entry[0] == "item" and entry[1] == ID_FAVORITE:
                if fav_label:
                    out.append(("item", ID_FAVORITE, fav_label))
            elif entry == ("sep",) and (not out or out[-1] == ("sep",)):
                continue
            else:
                out.append(entry)
        while out and out[-1] == ("sep",):
            out.pop()
        return out

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
                go_to_submenu(),
                ("sep",),
                ("item", ID_NEW_ISSUE, "New Issue…\tCtrl+N"),
                ("item", ID_SEARCH_REPO, "Search This Repository…\tCtrl+Shift+S"),
                ("item", ID_WATCH_SETTINGS, "Watch Settings…\tCtrl+Shift+U"),
                ("item", ID_FAVORITE,
                 "Remove from Favorites (F)" if is_favorite(f"https://github.com/{data}",
                                                            self.favorites)
                 else "Add to Favorites (F)"),
                ("sep",),
                ("sub", "Copy", [
                    ("item", ID_COPY_LINK, "Copy Link\tCtrl+Shift+C"),
                    ("item", ID_COPY_MARKDOWN, "Copy Markdown Link\tCtrl+Shift+L"),
                    ("item", ID_COPY_IDENT, "Copy Repository Name\tCtrl+Shift+I"),
                    ("sep",),
                    ("item", ID_COPY_CLONE_HTTPS, "Copy HTTPS Clone URL"),
                    ("item", ID_COPY_CLONE_SSH, "Copy SSH Clone URL"),
                ]),
            ]
            archived = self._known_archived(data)
            entries += [("sep",), ("item", ID_REMOVE_REPO, "Remove from List\tDelete"),
                        ("item", ID_ARCHIVE_REPO,
                         "Unarchive Repository…" if archived else "Archive Repository…"),
                        ("item", ID_DELETE_REPO, "Delete Repository from GitHub…")]
            return entries
        if isinstance(data, str) and data.startswith(SEARCH_ENTRY_PREFIX):
            return [("item", ID_REPO_OPEN, "Run Search\tEnter"),
                    ("item", ID_REMOVE_REPO, "Remove Saved Search…\tDelete")]
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

    def _go_to_repo_view(self, view: str) -> None:
        """Go To ▸ <view> on a repository's context menu: open the repository
        in front of you on that view. From a row in a list of repositories,
        Backspace comes back to the row."""
        repo, source = self._repo_in_front_from()
        if not repo:
            self._announce("Select a repository first.")
            return
        if source == "row":
            self._open_repo_from_list(repo, self._focused_item(), view)
        else:
            if view == VIEW_COMMITS:
                self.commit_branch = ""  # its default branch, not one picked elsewhere
            self._select_repo(repo, view)
            self._select_in_repo_list(repo)

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
        if (key == wx.WXK_BACK and not event.HasAnyModifiers()
                and self.view_mode in (VIEW_FILES, VIEW_CODE, VIEW_HISTORY)
                and focus is self.details_text):
            # Out of the lines to the file they belong to; Backspace again
            # goes back to the pull request or commit.
            self._focus_list(max(0, self.list_ctrl.GetFirstSelected()))
            return
        if (key == ord("H") and not event.HasAnyModifiers()
                and self.view_mode in (VIEW_ISSUES, VIEW_COMMITS, VIEW_HISTORY)):
            # Here so it works from the details panel, where "Press H" is read.
            self._show_changed_files()
            return
        if self.view_mode == VIEW_CODE and not event.HasAnyModifiers():
            # From the list or from the file's text.
            action = {ord("H"): self._show_file_history, ord("B"): self._toggle_blame}.get(key)
            if action:
                action()
                return
        if (key == ord("W") and not event.HasAnyModifiers()
                and self.view_mode == VIEW_FILES):
            self._open_whole_file()
            return
        if (key == ord("M") and not event.HasAnyModifiers()
                and self.view_mode == VIEW_FILES):
            # In the file's lines, where the caret says which line.
            if focus is not self.details_text and isinstance(self._files_of, Item):
                self._tell("Comment on This Line works in the file's lines: "
                           "press Enter, move to the line, then press M.")
                return
            self._comment_on_line()
            return
        if (key == ord("M") and not event.HasAnyModifiers()
                and self.view_mode == VIEW_DISCUSSIONS):
            # Here so it works from the details panel too, where the
            # discussion being commented on is read.
            self._comment_on_discussion()
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
        GhViewerFrame._on_list_key(self, event)
        # A key acted on here still reaches the list as a character, and on
        # Windows the list looks for a row starting with it: F, R, C and the
        # rest beeped wherever none did. Remember to swallow that character.
        self._eat_list_char = not event.GetSkipped()

    def on_list_char(self, event: wx.KeyEvent) -> None:
        """The character after a key on_list_key_down acted on goes no
        further; any other goes on to the list's find-as-you-type."""
        if getattr(self, "_eat_list_char", False):
            self._eat_list_char = False
            return
        event.Skip()

    def _on_list_key(self, event: wx.KeyEvent) -> None:
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
        elif key == wx.WXK_BACK and self.view_mode == VIEW_FILES:
            self._back_from_files()
        elif key == wx.WXK_BACK and self.view_mode == VIEW_CODE:
            self._code_up()
        elif key == wx.WXK_BACK and self.view_mode == VIEW_HISTORY:
            self._back_from_history()
        elif (key == wx.WXK_BACK and self._return_to
              and self.view_mode == getattr(self, "_return_view", VIEW_ISSUES)):
            self._return_to_list()
        elif key == wx.WXK_BACK and self.view_mode in PARENT_VIEW:
            # Backspace steps back up a drill-down (artifacts -> runs, commits -> branches)
            parent = PARENT_VIEW[self.view_mode]
            if self.view_mode == VIEW_ORG:
                # Back on the organization you came from, not at the top.
                logins = [o.login for o in self._orgs]
                self._pending_focus_row = logins.index(self._org) if self._org in logins else 0
            self._switch_view(parent)
            self._announce(f"Back to {self._VIEW_LABELS.get(parent, parent).lower()}")
        elif (key == wx.WXK_BACK and self.view_mode == VIEW_ISSUES
              and getattr(self, "milestone_filter", None) is not None):
            self._back_to_milestones()
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

    def _open_event(self, item: ActivityEvent, in_browser: bool = False) -> None:
        """Enter in Activity: what the event is about, here when GHManage has
        a view for it, with Backspace back to the event; otherwise, and for
        Open in Browser (Ctrl+O), on GitHub."""
        if not in_browser and item.subject_kind in ("issue", "PR") and item.number and item.repo:
            self._open_item_here(item)
            return
        target = parse_github_url(item.url) if item.url and not in_browser else None
        view = ADDRESS_VIEWS.get(target.kind) if target else None
        if view and target.repo and target.kind != "item":
            branch = target.ref if target.kind == "branch" else ""
            self._open_repo_from_list(target.repo, item, view, branch=branch)
            if target.kind in PENDING_KINDS:
                self._set_pending_target(view, target.kind, target.ref)
            return
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

    def _open_repo_from_list(self, repo: str, item, view: str = VIEW_ISSUES,
                             branch: str = "") -> None:
        """Open ``repo`` from a list of many (Activity, Starred, Watched), in
        ``view``; for Commits, on ``branch`` or else the default branch.

        Remembers the list and the item you were on, so Backspace from that
        view brings you back to it.
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
        if view == VIEW_COMMITS:
            self.commit_branch = branch
        self._select_repo(repo, view)
        # Set after _select_repo, which clears it for an ordinary repo change.
        self._return_to = saved
        self._return_view = view
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
        elif view == VIEW_FAVORITES:
            self._load_favorites_view(focus=item)
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
            self._announce("Removed from favorites")
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

        if isinstance(item, ChangedFile):
            self._announce("A changed file can't be a favorite. Backspace, then F "
                           "favorites the pull request or commit.")
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
            self._announce("Added to favorites")
        else:
            self._announce("Removed from favorites")
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
        elif isinstance(item, RepoFile):
            item_type = item.kind_display.lower()
            title = item.path
            subtitle = self._code_where() if self.view_mode == VIEW_CODE else ""
        elif isinstance(item, Milestone):
            item_type = "milestone"
            title = item.title
            subtitle = milestoneview.progress(item)
        elif isinstance(item, Discussion):
            # As F on a discussion's Activity event makes it.
            item_type = "discussion"
            title = f"#{item.number} — {item.title}"
            subtitle = item.category
        elif isinstance(item, SecurityAlert):
            item_type = "security alert"
            title = f"{item.kind_display} #{item.number} — {item.summary}"
            subtitle = " — ".join(x for x in (item.severity, item.package) if x)
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
        noun = GhViewerFrame._nav_noun(self)
        nouns = "changes or comments" if noun == "change or comment" else f"{noun}s"
        positions = self._comment_positions
        if not positions:
            self._announce(f"No {nouns} to navigate.")
            return
        new_idx = self._current_comment + direction
        if new_idx < 0:
            self._announce(f"Already at first {noun}.")
            return
        if new_idx >= len(positions):
            self._announce(f"Already at last {noun}.")
            return
        self._current_comment = new_idx
        line, length = positions[new_idx][:2]
        # Changed Files names what each stop is, a change or a comment, and
        # counts each kind on its own: "Comment 1 of 3".
        kind = positions[new_idx][2] if len(positions[new_idx]) > 2 else None
        start_pos = self._line_to_position(line)
        end_pos = self._line_to_position(line + length)
        if noun != "comment" or kind:
            # Up to the end of its last line, not the newline after it (the
            # last line of all has none).
            text = self.details_text.GetValue()
            if end_pos > start_pos and text[end_pos - 1:end_pos] == "\n":
                end_pos -= 1
        self.details_text.SetFocus()
        self.details_text.SetSelection(start_pos, end_pos)
        self.details_text.ShowPosition(start_pos)
        if kind:
            kinds = [p[2] if len(p) > 2 else kind for p in positions]
            number = kinds[:new_idx + 1].count(kind)
            self._announce(f"{kind.capitalize()} {number} of {kinds.count(kind)}")
            return
        total = len(positions)
        self._announce(f"{noun.capitalize()} {new_idx + 1} of {total}")

    def _line_to_position(self, line: int) -> int:
        """Convert a 0-based line index to a character position in the TextCtrl."""
        text = self.details_text.GetValue()
        pos = 0
        for _ in range(max(0, line)):
            nl = text.find("\n", pos)
            if nl < 0:
                return len(text)
            pos = nl + 1
        return pos

    # ── Menu actions ────────────────────────────────────────────────────

    def on_refresh(self, event: wx.CommandEvent) -> None:
        if self.view_mode == VIEW_CODE:
            item = self._focused_item()
            self._code_land = item.path if isinstance(item, RepoFile) else ""
            # A branch moves: read its folders and blame afresh.
            self._code_folders.clear()
            self._blame_cache.clear()
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
        elif self.view_mode in (VIEW_CODE, VIEW_FILES):
            self._announce(f"{self._view_label(self.view_mode)} lists everything at once.")
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
        elif (self.view_mode == VIEW_COMMITS and self.commit_branch == ALL_BRANCHES
              and len(self.git_items) < self.current_limit):
            self._announce(
                f"That is every commit All branches reads: the newest "
                f"{ALL_BRANCHES_PER_BRANCH_MAX} of each branch. To go further back, "
                "pick one branch with Ctrl+B."
            )
            return
        self.current_limit += self.page_size
        self._load_items()

    def on_open_browser(self, event: wx.CommandEvent) -> None:
        item = self._focused_item()
        if not item:
            return
        if isinstance(item, ActivityEvent):
            self._open_event(item, in_browser=True)
            return
        if isinstance(item, Notification):
            self._open_notification(item, in_browser=True)
            return
        if isinstance(item, SecurityAlert):
            self._open_alert(item)
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
        if self.view_mode == VIEW_DISCUSSIONS:
            self._comment_on_discussion()
            return
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
            if repo.lower() in (h.lower() for h in self._hidden_repos):
                # Opening it by name says you want it back.
                self._hidden_repos = unhide_repos([repo])
            self._refresh_repo_list()
            self._select_repo(repo)
            return
        view = ADDRESS_VIEWS.get(target.kind, target.ref if target.kind == "view" else VIEW_ISSUES)
        if view == VIEW_COMMITS:
            # Set before the switch, which loads the commits of commit_branch:
            # the branch named, or the default branch for a commit address.
            self.commit_branch = target.ref if target.kind == "branch" else ""
        self._select_repo(repo, view)
        if target.kind in PENDING_KINDS:
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
        """Delete or File ▸ Remove from List: take the selected repository or
        saved search out of the list."""
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
            # Asked first: unlike a repository, a saved search can't be
            # brought back, and Delete is one stray keypress.
            if wx.MessageBox(f"Remove the saved search '{label}'?\n\n"
                             "It can't be brought back.", "Remove Saved Search",
                             wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
                return
            self.saved_searches = remove_saved_search(label)
            self._refresh_repo_list()
            self._select_repo_row(idx)
            self._announce(f"Removed the saved search '{label}'.")
            return
        if not self._repos_known:
            # Until your repositories are in, there's no telling whether this
            # one is yours, and unpinning one that is would not last.
            if self._repos_failed:
                # Nothing else reloads the list short of switching account,
                # so try again now rather than send you looking.
                self._load_repos()
                self._announce("Your repositories couldn't be loaded, so nothing can be "
                               "removed yet. Loading them again; try once they are in.")
            else:
                self._announce("The repository list is still loading. "
                               "Try again when it has loaded.")
            return
        self._pinned_repos = remove_pinned(name)
        # One from your GitHub account would come straight back on the next
        # load, so it is hidden instead. A pinned one that is also yours
        # needs both, or it would only lose its pin.
        from_account = any(r.get("nameWithOwner", "").lower() == name.lower()
                           for r in self._all_repos)
        if from_account:
            self._hidden_repos = hide_repo(name)
        self._refresh_repo_list()
        self._select_repo_row(idx)
        if from_account:
            self._announce(f"Removed {name} from the list. "
                           "File, Hidden Repositories brings it back.")
        else:
            self._announce(f"Removed {name} from the list.")

    # ── Archiving and deleting on GitHub (#68) ──────────────────────────

    def _known_archived(self, repo: str) -> bool:
        """Whether one of your repositories is archived, as last loaded.
        False for a repository that isn't yours: it is checked when asked."""
        return any(r.get("nameWithOwner", "").lower() == repo.lower() and r.get("isArchived")
                   for r in self._all_repos)

    def _selected_repository(self) -> tuple[int, str] | None:
        """The repository row selected in the list, or None, said why. Not
        Favorites, the views, or a saved search: they aren't on GitHub."""
        idx = self.repo_list.GetSelection()
        if idx == wx.NOT_FOUND:
            self._announce("Select a repository in the list first.")
            return None
        name = self.repo_list.GetClientData(idx)
        if (not isinstance(name, str) or not name or name == FAVORITES_ENTRY
                or name in ENTRY_VIEWS or name.startswith(SEARCH_ENTRY_PREFIX)):
            self._announce("Select a repository in the list first.")
            return None
        return idx, name

    def _with_admin(self, repo: str, doing: str, then) -> None:
        """Check, off the UI thread, that you can ``doing`` ``repo`` (admin
        rights), then call ``then(admin_info)`` on the UI thread. One at a
        time: a second while one is under way would stack its question on
        top of the first."""
        if getattr(self, "_admin_pending", None):
            self._tell(f"Still working on {self._admin_pending}.")
            return
        self._admin_pending = repo
        self._announce(f"Checking your rights on {repo}…")

        def done(call, *args) -> None:
            self._admin_pending = None
            call(*args)

        def worker() -> None:
            try:
                info = repo_admin(repo)
            except GhError as exc:
                wx.CallAfter(done, self._tell, f"Couldn't check {repo}: {exc}")
                return
            if not info.admin:
                wx.CallAfter(done, self._tell, f"You need admin rights on {repo} to {doing} it.")
                return
            wx.CallAfter(done, then, info)

        threading.Thread(target=worker, daemon=True).start()

    def on_archive_repo(self) -> None:
        """File ▸ Archive or Unarchive Repository: read-only on GitHub, or
        back again. It can be undone, so a plain Yes or No is enough."""
        chosen = self._selected_repository()
        if chosen is None:
            return
        repo = chosen[1]

        def ask(info) -> None:
            archive = not info.archived
            if archive:
                question = (f"Archive {repo}?\n\nIt becomes read-only on GitHub: no new "
                            "issues, pull requests, comments or pushes. You can unarchive "
                            "it later.")
            else:
                question = (f"{repo} is archived. Unarchive it?\n\nIssues, pull requests, "
                            "comments and pushes are allowed again.")
            title = "Archive Repository" if archive else "Unarchive Repository"
            if wx.MessageBox(question, title, wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
                             self) != wx.YES:
                return
            self._announce(f"{'Archiving' if archive else 'Unarchiving'} {repo}…")

            def worker() -> None:
                try:
                    set_archived(repo, archive)
                except GhError as exc:
                    wx.CallAfter(self._tell,
                                 f"Couldn't {'archive' if archive else 'unarchive'} {repo}: {exc}")
                    return
                wx.CallAfter(self._on_archived, repo, archive)

            threading.Thread(target=worker, daemon=True).start()

        self._with_admin(repo, "archive or unarchive", ask)

    # Lists of repositories, whose rows can say "archived" or be the one deleted.
    _REPO_LIST_VIEWS = (VIEW_STARRED, VIEW_WATCHED, VIEW_ORG, VIEW_SHARED, VIEW_SEARCH_REPOS)

    def _shows_repo(self, repo: str) -> bool:
        """Whether the right-hand list is ``repo``'s, or a list of repositories."""
        return ((self.repo or "").lower() == repo.lower()
                or self.view_mode in self._REPO_LIST_VIEWS)

    def _on_archived(self, repo: str, archived: bool) -> None:
        for r in self._all_repos:
            if r.get("nameWithOwner", "").lower() == repo.lower():
                r["isArchived"] = archived
        self._tell(f"Archived {repo}. It is read-only on GitHub now." if archived
                   else f"Unarchived {repo}.")
        if self._shows_repo(repo):
            self._load_items()  # so "Archived (read-only)" shows or goes

    def on_delete_repo(self) -> None:
        """File ▸ Delete Repository from GitHub: gone for good, with
        everything in it, once you have typed its name back."""
        chosen = self._selected_repository()
        if chosen is None:
            return
        row, repo = chosen

        def ask(info) -> None:
            dlg = DeleteRepoDialog(self, repo, info.archived)
            try:
                if dlg.ShowModal() != wx.ID_OK:
                    self._announce(f"{repo} was not deleted.")
                    return
            finally:
                dlg.Destroy()
            self._announce(f"Deleting {repo}…")

            def worker() -> None:
                try:
                    delete_repo(repo)
                except MissingScope as exc:
                    wx.CallAfter(self._on_delete_scope, exc)
                    return
                except GhError as exc:
                    wx.CallAfter(self._tell, f"Couldn't delete {repo}: {exc}")
                    return
                wx.CallAfter(self._on_repo_deleted, repo, row)

            threading.Thread(target=worker, daemon=True).start()

        self._with_admin(repo, "delete", ask)

    def _on_delete_scope(self, exc: MissingScope) -> None:
        self._announce(f"Deleting a repository needs gh's \"{exc.scope}\" permission; "
                       "see the message for how to add it.")
        wx.MessageBox(str(exc), "Delete Repository from GitHub",
                      wx.OK | wx.ICON_INFORMATION, self)

    def _on_repo_deleted(self, repo: str, row: int) -> None:
        """Take every trace of it out of GHManage. The list isn't fetched from
        GitHub again: for a few seconds GitHub can still list a repository
        it has just deleted."""
        key = repo.lower()
        self._all_repos = [r for r in self._all_repos
                           if r.get("nameWithOwner", "").lower() != key]
        if any(p.lower() == key for p in self._pinned_repos):
            self._pinned_repos = remove_pinned(repo)
        kept = [f for f in self.favorites if (f.repo or "").lower() != key]
        favorites_changed = len(kept) != len(self.favorites)
        if favorites_changed:
            self.favorites = kept
            save_favorites(kept)
        # Where you are now, unless that is the row deleted: you may have
        # moved on while gh was working, and the old row number may be
        # another entry by now.
        idx = self.repo_list.GetSelection()
        current = self.repo_list.GetClientData(idx) if idx != wx.NOT_FOUND else None
        self._refresh_repo_list()
        if not isinstance(current, str) or current.lower() == key:
            self._select_repo_row(row)
        self._tell(f"Deleted {repo} from GitHub.")
        if (self.repo or "").lower() == key:
            # Everything on the right would now fail against a repository
            # that isn't there: show your notifications instead, as after
            # switching account.
            self.repo = None
            self._return_to = None
            self._switch_view(VIEW_NOTIFICATIONS)
            self._update_title()
        elif self.view_mode == VIEW_FAVORITES and favorites_changed:
            self._load_favorites_view()
        elif self.view_mode in self._REPO_LIST_VIEWS:
            self._load_items()

    def _select_repo_row(self, row: int) -> None:
        """After a removal: the row that took the removed one's place, or the
        last, so you are where you were rather than somewhere else."""
        count = self.repo_list.GetCount()
        if count:
            self.repo_list.SetSelection(min(row, count - 1))

    def on_hidden_repos(self, event) -> None:
        """File ▸ Hidden Repositories: put removed repositories back."""
        if not self._hidden_repos:
            self._announce("No repositories are hidden.")
            return
        names = sorted(self._hidden_repos, key=str.lower)
        shown: list[str] = []

        def show_again(name: str) -> None:
            self._unhide([name])
            shown.append(name)

        dlg = HiddenReposDialog(self, names, show_again)
        try:
            dlg.ShowModal()
        finally:
            dlg.Destroy()
        if shown:
            n = len(shown)
            self._announce(f"Showing {n} {'repository' if n == 1 else 'repositories'} again.")

    def _unhide(self, names: list[str]) -> None:
        self._hidden_repos = unhide_repos(names)
        self._refresh_repo_list()

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
        """Ctrl+B — select which branch to view commits for; in Files, which
        branch or tag to look at."""
        if self.view_mode == VIEW_CODE and self.repo:
            self._choose_code_ref()
            return
        if self.view_mode != VIEW_COMMITS:
            self._tell("Select Branch is for the Commits and Files views.")
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
        if current == ALL_BRANCHES:
            current = ALL_BRANCHES_CHOICE
        # Every branch at once comes first. Git allows no spaces in a branch
        # name, so "All branches" can't be one.
        names = [ALL_BRANCHES_CHOICE] + names
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
            if selected == ALL_BRANCHES_CHOICE:
                selected = ALL_BRANCHES
            if selected and selected != self.commit_branch:
                self.commit_branch = selected
                self.current_limit = self.page_size
                self._load_items()
                if selected == ALL_BRANCHES:
                    self._announce("Showing commits on all branches")
                else:
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
        _name(txt, title)
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
        settings.flush()  # a choice a busy file kept from being written
        self.Destroy()

    # ── View menu actions ───────────────────────────────────────────────

    def on_quick_mode(self, event: wx.CommandEvent) -> None:
        self.list_mode = "quick"
        settings.save_list_mode(self.list_mode)
        self._update_menu_checks()
        self._update_mode_status()
        self._announce("Quick mode: compact display")
        if self.items or self.git_items:
            self._refresh_list_display(focus=self._focused_item())

    def on_full_mode(self, event: wx.CommandEvent) -> None:
        self.list_mode = "full"
        settings.save_list_mode(self.list_mode)
        self._update_menu_checks()
        self._update_mode_status()
        self._announce("Full mode: field names included for screen reader")
        if self.items or self.git_items:
            self._refresh_list_display(focus=self._focused_item())

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
        if self.view_mode == VIEW_SECURITY:
            self._update_menu_checks()
            self._tell("Security alerts are listed most severe first, then newest, "
                       "so they aren't sorted.")
            return
        if self.view_mode == VIEW_DISCUSSIONS:
            self._update_menu_checks()
            self._tell("Discussions are listed most recently active first, "
                       "so they aren't sorted.")
            return
        if self.view_mode == VIEW_MILESTONES:
            self._update_menu_checks()
            self._tell("Milestones are listed in GitHub's order, nearest due date "
                       "first, so they aren't sorted.")
            return
        self.sort_order = self._sort_menu_items.get(event.GetId(), SORT_ORDERS[0])
        self._update_menu_checks()
        back = self._files_back if self.view_mode == VIEW_FILES else None
        if back and back["view"] == VIEW_ISSUES and back["items"]:
            back["items"] = sort_items(back["items"], self.sort_order)
        if self.items:
            self.items = sort_items(self.items, self.sort_order)
            self._refresh_list_display()

    def on_choose_columns(self, event: wx.CommandEvent) -> None:
        """View ▸ Columns: every list's columns, their order, and
        whether their names are read, in one dialog (ColumnsDialog)."""
        current = _view_columns(self.view_mode)
        sets = COLUMN_SETS
        layouts = {cs.id: settings.load_columns(cs) for cs in sets}
        layouts[current.id] = list(self.columns)
        # The selected row, or the first, for the preview.
        item = self._focused_item() or self._row_item(0)
        sample = _row_values(item, current.ids) if item is not None else None
        dlg = ColumnsDialog(self, sets, current.id, layouts, self.list_mode == "full", sample,
                            say=self._tell)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            changed, speak = dlg.layouts(), dlg.speak_labels()
        finally:
            dlg.Destroy()
        self._apply_column_choices(changed, speak)

    def _apply_column_choices(self, changed: dict[str, list[str]], speak: bool) -> None:
        sets = {cs.id: cs for cs in COLUMN_SETS}
        # Before the columns are rebuilt, which empties the list.
        item = self._focused_item()
        for set_id, cols in changed.items():
            settings.save_columns(sets[set_id], cols)
        mode = "full" if speak else "quick"
        redraw = mode != self.list_mode
        if redraw:
            self.list_mode = mode
            settings.save_list_mode(mode)
            self._update_mode_status()
        current = _view_columns(self.view_mode)
        if current.id in changed:
            self.columns = list(changed[current.id])
            self._rebuild_columns()
            redraw = True
        self._update_menu_checks()
        if redraw and (self.items or self.git_items or self.view_mode == VIEW_FAVORITES):
            self._refresh_list_display(focus=item)
        if changed:
            self._announce("Columns saved.")
        elif redraw:
            self._announce("Column names on." if speak else "Column names off.")
        else:
            self._announce("No changes to the columns.")

    def on_state_open(self, event: wx.CommandEvent) -> None:
        self.state_filter = "open"
        self._update_menu_checks()
        self._reload_after_filter()

    def on_state_closed(self, event: wx.CommandEvent) -> None:
        self.state_filter = "closed"
        self._update_menu_checks()
        self._reload_after_filter()

    def on_state_all(self, event: wx.CommandEvent) -> None:
        self.state_filter = "all"
        self._update_menu_checks()
        self._reload_after_filter()

    def on_tab_issues(self, event: wx.CommandEvent) -> None:
        self.tab_filter = "issues"
        self._update_menu_checks()
        self._reload_after_filter()

    def on_tab_prs(self, event: wx.CommandEvent) -> None:
        self.tab_filter = "prs"
        self._update_menu_checks()
        self._reload_after_filter()

    def on_tab_both(self, event: wx.CommandEvent) -> None:
        self.tab_filter = "both"
        self._update_menu_checks()
        self._reload_after_filter()

    def _reload_after_filter(self) -> None:
        """After View ▸ State or Filter: the list again, with it. In Changed
        Files, the issues and pull requests are read again on the way back
        instead, rather than the files now."""
        if self.view_mode == VIEW_FILES:
            back = self._files_back
            if back and back["view"] == VIEW_ISSUES:
                back["items"] = None
            self._tell("Issues & PRs will show this when you go back to them.")
            return
        if self.repo:
            self.current_limit = self.page_size
            self._load_items()

    # ── View mode switching (Show submenu) ──────────────────────────────

    def on_view_issues(self, event: wx.CommandEvent) -> None:
        # Asking for Issues & PRs by name means all of them: drop any label
        # drill-down, including when that leaves the view mode unchanged.
        if self.view_mode == VIEW_ISSUES:
            if self.label_filter or self.milestone_filter is not None:
                self.label_filter = ""
                self.milestone_filter = None
                self.current_limit = self.page_size
                self._load_items()
                self._announce("Showing all issues and PRs")
            return
        self.label_filter = ""
        self.milestone_filter = None
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

    def on_view_security(self, event: wx.CommandEvent) -> None:
        self._switch_view(VIEW_SECURITY)

    def on_view_discussions(self, event: wx.CommandEvent) -> None:
        self._switch_view(VIEW_DISCUSSIONS)

    def on_view_milestones(self, event: wx.CommandEvent) -> None:
        self._switch_view(VIEW_MILESTONES)

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

    def _refresh_list_display(self, focus=None) -> None:
        """Re-populate the list from current data without re-fetching.

        ``focus`` is the item to land on, so a change to how rows read (the
        columns, Quick or Full mode) leaves you where you were; the first
        row otherwise.
        """
        if self.view_mode == VIEW_FAVORITES:
            self._load_favorites_view(focus=focus)
            return
        items = self.items if self.view_mode in ITEM_VIEWS else self.git_items
        filtered = self._populate_filtered_list(items, use_favorite_prefix=True)
        if filtered:
            row = self._row_of(focus) if focus is not None else 0
            wx.CallLater(100, self._focus_list, max(row, 0))

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
        if note.subject_type == "Discussion" and note.repo and not in_browser:
            self._open_discussion_here(note)
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

    def _open_discussion_here(self, note: Notification) -> None:
        """A discussion's notification: its repository's Discussions, on it,
        with Backspace back to the notifications. GitHub doesn't always give
        a discussion's number here; then it is found by its title."""
        target = parse_github_url(note.url) if note.own_page else None
        self._open_repo_from_list(note.repo, note, VIEW_DISCUSSIONS)
        if target is not None and target.kind == "discussion":
            self._set_pending_target(VIEW_DISCUSSIONS, "discussion", target.ref)
        elif note.title:
            self._set_pending_target(VIEW_DISCUSSIONS, "discussion_title", note.title)

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

    def _toggle_speak_results(self) -> None:
        """View ▸ Speak Results."""
        a = announce.announcer
        a.categories[announce.RESULT] = not a.categories[announce.RESULT]
        settings.save_announcements(a.enabled, a.categories)
        self.GetMenuBar().Check(ID_SPEAK_RESULTS, a.categories[announce.RESULT])
        # Said whatever the setting, or turning it off would be silent.
        self._tell("Results will be spoken." if a.categories[announce.RESULT]
                   else "Results won't be spoken.", force=True)

    def _tell(self, msg: str, category: str = announce.RESULT, force: bool = False) -> bool:
        """The status bar, and the screen reader if this kind of message is
        spoken. True if it was handed to a screen reader. From a worker
        thread it is passed to the UI thread, and returns False."""
        if not wx.IsMainThread():
            wx.CallAfter(self._tell, msg, category, force)
            return False
        self._announce(msg)
        return announce.announce(msg, category, force)

    # ── Changed files ───────────────────────────────────────────────────
    #
    # A pull request's or a commit's files, one row each, and the selected
    # file's changed lines in the details panel, marked as chosen under
    # View ▸ Mark Changed Lines With (app-kit's difftext, via diffview).

    def _show_changed_files(self) -> None:
        """H, or Actions ▸ Changed Files: the files the selected pull
        request or commit changed. Backspace comes back to it."""
        item = self._focused_item()
        if self.view_mode == VIEW_ISSUES and isinstance(item, Item):
            if not item.is_pr:
                self._tell(f"#{item.number} is an issue. Only pull requests "
                           "and commits have changed files.")
                return
        elif not (self.view_mode in (VIEW_COMMITS, VIEW_HISTORY) and isinstance(item, Commit)):
            self._tell("Select a pull request or a commit first.")
            return
        back = {
            "view": self.view_mode,
            "items": list(self._view_source()),
            "item": item,
            "limit": self.current_limit,
            "filter_text": self.filter_text,
            "label_filter": self.label_filter,
            "milestone_filter": getattr(self, "milestone_filter", None),
            "commit_branch": self.commit_branch,
            "branches_unread": self._branches_unread,
            "return_to": self._return_to,
            "return_view": getattr(self, "_return_view", VIEW_ISSUES),
            # From File History: the file, and the Files view behind it.
            "history_of": getattr(self, "_history_of", None),
            "history_back": getattr(self, "_history_back", None),
        }
        self._switch_view(VIEW_FILES, load=False)
        # Set after the switch, which clears them on the way in to anything else.
        self._files_of = item
        self._files_back = back
        self._update_title()
        self._load_items()

    def _files_of_label(self) -> str:
        """What the Changed Files view is showing the files of."""
        src = self._files_of
        if isinstance(src, Item):
            return f"PR #{src.number} {src.title}"
        if isinstance(src, Commit):
            return f"commit {src.short_sha} {_first_line(src.message)}".strip()
        return ""

    @staticmethod
    def _attach_comments(files: list, comments: list) -> None:
        """Give each of a pull request's files its review comments."""
        by_path = comments_by_path(comments)
        for f in files:
            f.comments = by_path.get(f.filename, [])

    def _on_files_loaded(self, token: int, files: list, note: str = "",
                         head: str | None = None) -> None:
        if not self._fetch_is_current(token):
            return  # the user has moved on; these belong to a view they left
        if head is not None:
            # None when the files come back from Files (W) as they were.
            self._files_head = head
        self.git_items = files
        self.items = []
        filtered = self._populate_filtered_list(files)
        # Back from Files (W): on the file you opened whole.
        row = self._take_pending_row(files, token)
        totals = diffview.totals_message(files)
        if len(files) >= MAX_CHANGED_FILES:
            totals += f" GitHub lists only the first {MAX_CHANGED_FILES:,}."
        pr = isinstance(self._files_of, Item)
        if pr and files and not note:
            n = sum(len(f.comments or []) for f in files)
            if n:
                totals += f" {diffview.comment_count(n).capitalize()}."
        if note:
            totals += f" {note}"
        back = self._files_back["view"] if self._files_back else VIEW_ISSUES
        nav = ("Alt+N/Alt+P=next/previous change or comment  M=comment on the line  " if pr
               else "Alt+N/Alt+P=next/previous change  ")
        self._set_view_status(
            f"{self._files_of_label()} — {totals}",
            f"Enter=read the changes  {nav}W=whole file  "
            f"Ctrl+F=filter  Backspace=back to {self._view_label(back, lower=True)}",
        )
        self._update_title()

        def land() -> None:
            if not self._fetch_is_current(token):
                return
            if filtered:
                self._focus_list(row)
            # A status, so it waits for the row focus lands on to be read.
            announce.announce(totals, announce.STATUS)

        wx.CallLater(100, land)

    def _show_file_details(self, idx: int) -> None:
        """A changed file's lines, marked in the chosen style."""
        if idx < 0 or idx >= len(self.git_items):
            self._file_view = None
            self.details_text.Clear()
            return
        f = self.git_items[idx]
        view = diffview.file_view(f, self._diff_style, f.comments)
        self._file_view = view
        self.details_text.SetValue(view.text)
        # Alt+N and Alt+P move between runs of changes the way they move
        # between comments: each is its "Lines 10 to 15:" line. A pull
        # request's review comments are stops too, each counted on its own.
        self._comment_positions = list(view.stops)
        self._current_comment = -1

    def _read_changes(self) -> None:
        """Enter on a changed file: into its lines, from the top."""
        self.details_text.SetFocus()
        self.details_text.SetInsertionPoint(0)

    def _back_from_files(self) -> None:
        """Backspace in Changed Files: the list it was opened from, as it
        was, on the pull request or commit it was opened on."""
        back = self._files_back
        if not back:
            self._switch_view(VIEW_ISSUES)
            return
        view = back["view"]
        # The switch keeps these only in their own views; set them first.
        self.commit_branch = back["commit_branch"]
        self.label_filter = back["label_filter"]
        self.milestone_filter = back.get("milestone_filter")
        self._switch_view(view, load=False)
        self.filter_text = back["filter_text"]
        self.current_limit = back["limit"]
        self._branches_unread = back["branches_unread"]
        self._return_to = back["return_to"]
        self._return_view = back["return_view"]
        if view == VIEW_HISTORY:
            self._history_of = back.get("history_of")
            self._history_back = back.get("history_back")
        items = back["items"]
        if items is None:
            # A filter changed while you were away: read the list again,
            # and land on the pull request again if it is still in it.
            self._load_items()
            self._set_pending_target(view, "item", str(back["item"].number))
            return
        token = self._begin_fetch()
        self._pending_target = (token, view, "same", back["item"])
        if view == VIEW_ISSUES:
            prs = sum(1 for it in items if isinstance(it, Item) and it.is_pr)
            self._on_items_loaded(token, items, len(items) - prs, prs)
        elif view == VIEW_HISTORY:
            self._on_history_loaded(token, items)
        else:
            self._on_git_items_loaded(token, items, "commits")
        self._announce(f"Back to {self._view_label(view, lower=True)}")

    def _set_diff_style(self, style: str) -> None:
        """View ▸ Mark Changed Lines With."""
        was = self._diff_style
        self._diff_style = style
        settings.save_diff_style(style)
        self._update_menu_checks()
        if self.view_mode in (VIEW_FILES, VIEW_HISTORY):
            row = self.list_ctrl.GetFirstSelected()
            if row >= 0:
                # Every style gives one line for each line of the diff, so
                # the caret's line and the change Alt+N is on still match.
                caret = self.details_text.GetInsertionPoint()
                line = self.details_text.GetValue().count("\n", 0, caret)
                current = self._current_comment
                self._show_details(row)
                self.details_text.SetInsertionPoint(self._line_to_position(line))
                self._current_comment = current
        msg = f"Changed lines marked with {diffview.LABELS[style]}."
        # Once, on the way from words to symbols, not between the two
        # symbol styles: as The Chat Place does.
        if diffview.is_symbol_style(style) and not diffview.is_symbol_style(was):
            msg += " " + diffview.SYMBOLS_NOTE
        self._tell(msg)

    def _diff_action(self, action: str) -> None:
        """Copy ▸ Copy Diff ("copy") and Actions ▸ Open Diff in Default App
        ("open"): the selected pull request's or commit's whole diff, or in
        Changed Files the selected file's."""
        item = self._focused_item()
        if self.view_mode == VIEW_FILES and isinstance(item, ChangedFile):
            text = file_diff(item)
            if not text:
                self._tell(f"GitHub doesn't show the lines of {item.filename}, "
                           "so there is no diff.")
                return
            stem = f"{self._diff_stem(self._files_of)}-{item.filename.rsplit('/', 1)[-1]}"
            self._diff_ready(action, text, item.filename, stem)
            return
        if self.view_mode == VIEW_ISSUES and isinstance(item, Item) and item.is_pr:
            what = f"pull request #{item.number}"
            fetch = lambda url=item.url: fetch_pr_diff(url)  # noqa: E731
        elif self.view_mode in (VIEW_COMMITS, VIEW_HISTORY) and isinstance(item, Commit):
            what = f"commit {item.short_sha}"
            fetch = lambda repo=self.repo, sha=item.sha: fetch_commit_diff(repo, sha)  # noqa: E731
        elif isinstance(item, Item) and not item.is_pr:
            self._tell(f"#{item.number} is an issue. Only pull requests and commits have a diff.")
            return
        else:
            self._tell("Select a pull request or a commit first.")
            return
        if self._diff_busy:
            self._tell("Still getting the last diff.")
            return
        self._diff_busy = True
        self._announce(f"Getting the diff of {what}…")
        stem = self._diff_stem(item)

        def worker() -> None:
            try:
                text = fetch()
            except Exception as exc:  # noqa: BLE001 — never leave _diff_busy set
                wx.CallAfter(self._diff_failed, str(exc))
                return
            wx.CallAfter(self._diff_ready, action, text, what, stem)

        threading.Thread(target=worker, daemon=True).start()

    def _diff_stem(self, item) -> str:
        """A file name, without .diff, for an item's diff."""
        repo = (self.repo or "").replace("/", "-")
        if isinstance(item, Item):
            return f"{repo}-pr-{item.number}"
        if isinstance(item, Commit):
            return f"{repo}-{item.short_sha}"
        return repo or "changes"

    def _diff_failed(self, msg: str) -> None:
        self._diff_busy = False
        self._tell(f"Couldn't get the diff: {msg}")

    def _diff_ready(self, action: str, text: str, what: str, stem: str) -> None:
        self._diff_busy = False
        if not text.strip():
            self._tell(f"{what} has no changes to show.")
            return
        n = text.count("\n") + (0 if text.endswith("\n") else 1)
        if action == "copy":
            if self._set_clipboard(text):
                self._tell(f"Copied the diff of {what}, {n:,} line{'s' if n != 1 else ''}.")
            else:
                self._tell("Couldn't open the clipboard. Try again.")
            return
        try:
            path = write_diff_file(stem, text)
        except OSError as exc:
            self._tell(f"Couldn't save the diff: {exc}")
            return
        opened = open_in_default_app(path)
        self._tell(f"Opened the diff of {what}." if opened
                   else f"Saved the diff of {what} as {path}, but couldn't open it.")

    # ── Files: a repository's code ──────────────────────────────────────
    #
    # The repository's folders and files at a branch, tag or commit; the
    # selected file's text in the details panel, or its blame (B); and a
    # file's history (H), each commit read the way Changed Files reads it.
    # W in Changed Files opens a changed file here, whole.

    def _reset_code(self) -> None:
        """Files as it starts: the top of the default branch, nowhere to
        go back to."""
        self._code_ref = ""          # branch, tag or SHA; "" until the default is known
        self._code_at = ""           # "on main", "at tag v1.0", "at commit abc12345"
        self._code_path = ""         # the folder showing; "" for the top
        self._code_stack: list[str] = []  # the folders Enter went in from
        self._code_land = ""         # the path to select when the folder arrives
        self._code_back: dict | None = None  # Changed Files, when W opened this
        self._code_blame: RepoFile | None = None  # the file whose blame is showing
        self._code_folders: dict = {}  # (repo, ref, path) -> (entries, cut), this visit
        self._blame_cache: dict = {}   # (repo, ref, path) -> ranges

    def _code_where(self) -> str:
        """``src/ on main``: the folder and the branch, tag or commit."""
        folder = codeview.folder_label(self.repo or "", getattr(self, "_code_path", ""))
        return f"{folder} {getattr(self, '_code_at', '')}".strip()

    def _nav_noun(self) -> str:
        """What Alt+N and Alt+P move between in the details panel here."""
        view = getattr(self, "view_mode", None)
        if view == VIEW_FILES and isinstance(getattr(self, "_files_of", None), Item):
            return "change or comment"  # a pull request's review comments too
        if view in (VIEW_FILES, VIEW_HISTORY):
            return "change"
        if view == VIEW_CODE:
            return "run" if getattr(self, "_code_blame", None) is not None else "heading"
        return "comment"

    def _load_code(self) -> None:
        """The folder ``_code_path`` at ``_code_ref``: from what this visit
        has read already, or from GitHub."""
        cached = self._code_folders.get((self.repo, self._code_ref, self._code_path))
        if cached is None or not self._code_ref:
            self._load_items()
            return
        token = self._begin_fetch()
        self._on_code_loaded(token, self._code_ref, self._code_path, *cached, "")

    def _on_code_loaded(self, token: int, ref: str, path: str, entries: list,
                        cut: bool, note: str) -> None:
        if not self._fetch_is_current(token):
            return  # the user has moved on; these belong to a view they left
        self._code_ref = ref
        if not self._code_at:
            self._code_at = f"on {ref}"
        if path != self._code_path:
            # The folder isn't on this branch or tag: the top instead.
            self._code_path, self._code_stack = path, []
        self._code_folders[(self.repo, ref, path)] = (entries, cut)
        self._code_blame = None
        self.git_items = entries
        self.items = []
        filtered = self._populate_filtered_list(entries, use_favorite_prefix=True)
        summary = codeview.folder_summary(entries, cut)
        where = self._code_where()
        if self._code_stack or (self._code_path and not self._code_back):
            back = "  Backspace=up a folder"
        elif self._code_back:
            back = "  Backspace=back to changed files"
        elif getattr(self, "_return_to", None) and self._return_view == VIEW_CODE:
            back = "  Backspace=back"  # _set_view_status names the list
        else:
            back = ""
        self._set_view_status(
            f"{where} — {summary}{' ' + note if note else ''}",
            "Enter=open  H=history  B=blame  Alt+N/Alt+P=next/previous heading  "
            f"Ctrl+B=branch or tag  Ctrl+O=open on GitHub  Ctrl+F=filter{back}",
        )
        self._update_title()
        self._update_actions_menu()
        land, self._code_land = self._code_land, ""
        row = next((i for i, f in enumerate(self._shown) if land and f.path == land), 0)

        def arrive() -> None:
            if not self._fetch_is_current(token):
                return
            if filtered:
                self._focus_list(row)
            if note:
                self._tell(note)
            # A status, so it waits for the row focus lands on to be read.
            announce.announce(f"{codeview.folder_label(self.repo or '', path)} {summary}",
                              announce.STATUS)

        wx.CallLater(100, arrive)

    def _code_open_folder(self, item: RepoFile) -> None:
        """Enter on a folder: into it. Backspace comes back out to it."""
        self._code_stack.append(self._code_path)
        self._code_path = item.path
        self._code_land = ""
        self.filter_text = ""
        self._load_code()

    def _code_up(self) -> None:
        """Backspace in Files: up a folder, onto the one you were in; or back
        to Changed Files, when W opened this folder from there."""
        if self._code_stack:
            left = self._code_path
            self._code_path = self._code_stack.pop()
        elif self._code_back:
            self._back_from_code()
            return
        elif self._code_path:
            left = self._code_path
            self._code_path = left.rpartition("/")[0]
        elif (getattr(self, "_return_to", None)
              and getattr(self, "_return_view", None) == VIEW_CODE):
            # Opened here from a list of repositories (Go To ▸ Files).
            self._return_to_list()
            return
        else:
            self._tell("This is the top of the repository.")
            return
        self.filter_text = ""  # a filter typed for one folder means nothing in the next
        self._code_land = left
        self._load_code()

    def _back_from_code(self) -> None:
        """Backspace from the folder W opened: Changed Files as it was, on
        the file."""
        snap = self._code_back
        self._switch_view(VIEW_FILES, load=False)
        # Set after the switch, which clears them on the way in to anything else.
        self._files_of = snap["files_of"]
        self._files_back = snap["files_back"]
        self.filter_text = snap["filter_text"]
        token = self._begin_fetch()
        self._pending_target = (token, VIEW_FILES, "same", snap["item"])
        self._on_files_loaded(token, snap["items"])
        self._announce("Back to changed files")

    def _code_snapshot(self, item) -> dict:
        """Files as it is, to come back to from File History."""
        return {
            "ref": self._code_ref, "at": self._code_at, "path": self._code_path,
            "stack": list(self._code_stack), "back": self._code_back,
            "folders": self._code_folders, "blames": self._blame_cache,
            "items": list(self.git_items), "item": item, "filter_text": self.filter_text,
            # Go To ▸ Files from a list of repositories: Backspace at the top
            # goes back to it, after History as before.
            "return_to": getattr(self, "_return_to", None),
            "return_view": getattr(self, "_return_view", VIEW_ISSUES),
        }

    def _restore_code(self, snap: dict) -> None:
        self._switch_view(VIEW_CODE, load=False)
        self._return_to = snap.get("return_to")
        self._return_view = snap.get("return_view", VIEW_ISSUES)
        self._code_ref, self._code_at = snap["ref"], snap["at"]
        self._code_path, self._code_stack = snap["path"], snap["stack"]
        self._code_back = snap["back"]
        self._code_folders, self._blame_cache = snap["folders"], snap["blames"]
        self.filter_text = snap["filter_text"]
        self._code_land = snap["item"].path if snap["item"] is not None else ""
        cut = self._code_folders.get((self.repo, self._code_ref, self._code_path), ([], False))[1]
        token = self._begin_fetch()
        self._on_code_loaded(token, self._code_ref, self._code_path, snap["items"], cut, "")

    def _show_code_details(self, idx: int) -> None:
        """A row of Files in the details panel: a file's text (fetched when
        it is first selected), its blame when B asked for it, or what a
        folder, link or submodule is."""
        if idx < 0 or idx >= len(self.git_items):
            self.details_text.Clear()
            return
        item = self.git_items[idx]
        if self._code_blame is not None and self._code_blame is not item:
            self._code_blame = None
            self._update_actions_menu()  # Alt+N is "Next Heading" again
        self._render_code(item)

    def _render_code(self, item: RepoFile) -> None:
        positions: list[int] = []
        if item.kind in ("dir", "submodule") or codeview.too_big(item):
            text = codeview.entry_text(item)
        elif item.sha not in self._blob_cache:
            text = f"{item.path}: getting the text…"
            self._fetch_later(item, self._detail_gen)
        elif item.kind == "link":
            text = codeview.entry_text(item, self._blob_cache[item.sha])
        elif self._code_blame is item:
            key = (self.repo, self._code_ref, item.path, item.sha)
            text, positions = codeview.blame_text(item.path, self._blob_cache[item.sha],
                                                  self._blame_cache.get(key, []))
        else:
            text, positions = codeview.file_text(item, self._blob_cache[item.sha])
        self.details_text.SetValue(text)
        self._comment_positions = [(line, 1) for line in positions]
        self._current_comment = -1

    def _fetch_later(self, item: RepoFile, gen: int) -> None:
        """Fetch a file's text once the selection has rested on it a moment,
        so arrowing down a folder doesn't fetch every file passed."""
        repo = self.repo

        def worker() -> None:
            try:
                text, err = fetch_blob_text(repo, item.sha), ""
            except GhError as exc:
                text, err = None, str(exc)
            wx.CallAfter(self._on_blob_fetched, gen, item, text, err)

        def start() -> None:
            if gen == self._detail_gen:
                threading.Thread(target=worker, daemon=True).start()

        wx.CallLater(250, start)

    def _shows(self, view: str, item, gen: int) -> bool:
        """Whether the details panel is still for ``item`` in ``view``."""
        return (gen == self._detail_gen and self.view_mode == view
                and self._focused_item() is item)

    def _keep_blob(self, sha: str, text: str) -> None:
        if len(self._blob_cache) >= 200 or sum(map(len, self._blob_cache.values())) > 20_000_000:
            self._blob_cache.clear()  # a long session's worth; start again
        self._blob_cache[sha] = text

    def _on_blob_fetched(self, gen: int, item: RepoFile, text: str | None, err: str) -> None:
        if text is not None:
            self._keep_blob(item.sha, text)
        if not self._shows(VIEW_CODE, item, gen):
            return
        if text is None:
            self.details_text.SetValue(f"{item.path}: couldn't get the text. {err}")
            return
        reading = self.FindFocus() is self.details_text
        self._render_code(item)
        if reading:
            # Enter went into the panel while it was on its way: the top,
            # and say it is here, as a focused text box's new value isn't read.
            self.details_text.SetInsertionPoint(0)
            first = self.details_text.GetValue().split("\n", 1)[0]
            announce.announce(first, announce.STATUS)

    def _code_file(self, doing: str) -> RepoFile | None:
        """The file selected in Files, or None having said why not."""
        item = self._focused_item()
        if self.view_mode != VIEW_CODE:
            self._tell(f"{doing} is for a file in the Files view.")
            return None
        if not isinstance(item, RepoFile):
            self._tell("Select a file first.")
            return None
        if item.kind != "file":
            self._tell(f"{doing} is for a file. {item.name} is a {item.kind_display.lower()}.")
            return None
        return item

    def _toggle_blame(self) -> None:
        """B, or Actions ▸ Blame: who last changed each line of the
        selected file, in the details panel. B again shows the file."""
        item = self._code_file("Blame")
        if item is None:
            return
        if self._code_blame is item:
            self._code_blame = None
            self._render_code(item)
            self._update_actions_menu()
            self._tell(f"Showing {item.name} again.")
            return
        text = self._blob_cache.get(item.sha)
        if codeview.too_big(item) or (text is not None and codeview.is_binary(text)):
            self._tell(f"{item.name} isn't text to blame line by line.")
            return
        key = (self.repo, self._code_ref, item.path, item.sha)
        gen = self._detail_gen
        if key in self._blame_cache and text is not None:
            self._on_blame_fetched(gen, item, key, self._blame_cache[key], text, "")
            return
        if getattr(self, "_blame_busy", False):
            self._tell("Still getting the blame.")
            return
        self._blame_busy = True
        said = f"Getting the blame of {item.name}. A big file takes a few seconds…"
        self._announce(said)
        announce.announce(said, announce.STATUS)
        repo = self.repo

        def worker() -> None:
            try:
                ranges = fetch_blame(repo, key[1], item.path)
                body = text if text is not None else fetch_blob_text(repo, item.sha)
            except GhError as exc:
                wx.CallAfter(self._on_blame_fetched, gen, item, key, None, None, str(exc))
                return
            wx.CallAfter(self._on_blame_fetched, gen, item, key, ranges, body, "")

        threading.Thread(target=worker, daemon=True).start()

    def _on_blame_fetched(self, gen: int, item: RepoFile, key: tuple, ranges, text, err) -> None:
        self._blame_busy = False
        if ranges is not None:
            self._blame_cache[key] = ranges
            self._keep_blob(item.sha, text)
        if not self._shows(VIEW_CODE, item, gen):
            return
        if ranges is None:
            self._tell(f"Couldn't get the blame of {item.name}: {err}")
            return
        if codeview.is_binary(text):
            self._tell(f"{item.name} isn't text to blame line by line.")
            return
        self._code_blame = item
        self._render_code(item)
        self._update_actions_menu()
        runs = len(self._comment_positions)
        self._tell(f"Blame of {item.name}: {runs} run{'s' if runs != 1 else ''} of lines. "
                   "Alt+N and Alt+P move between them.")

    def _choose_code_ref(self) -> None:
        """Ctrl+B in Files: which branch or tag to look at."""
        self._announce("Getting the branches and tags…")
        repo = self.repo

        def worker() -> None:
            try:
                branches, tags = fetch_ref_names(repo)
            except GhError as exc:
                wx.CallAfter(self._tell, f"Couldn't get the branches: {exc}")
                return
            wx.CallAfter(self._show_code_ref_picker, repo, branches, tags)

        threading.Thread(target=worker, daemon=True).start()

    def _show_code_ref_picker(self, repo: str, branches: list, tags: list) -> None:
        if repo != self.repo or self.view_mode != VIEW_CODE:
            return
        refs = [(b, "branch") for b in branches] + [(t, "tag") for t in tags]
        if not refs:
            self._tell("No branches or tags found.")
            return
        names = [name if kind == "branch" else f"{name} (tag)" for name, kind in refs]
        dlg = wx.SingleChoiceDialog(self, "Choose a branch or tag to look at:",
                                    "Select Branch or Tag", names)
        current = next((i for i, (name, _) in enumerate(refs) if name == self._code_ref), -1)
        if current >= 0:
            dlg.SetSelection(current)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            name, kind = refs[dlg.GetSelection()]
        finally:
            dlg.Destroy()
        if name == self._code_ref:
            return
        self._set_code_ref(name, f"on {name}" if kind == "branch" else f"at tag {name}")

    def _set_code_ref(self, ref: str, at: str) -> None:
        """Look at another branch or tag: the same folder there, on the same
        entry, or the top when it has no such folder."""
        item = self._focused_item()
        self._code_ref, self._code_at = ref, at
        self._code_land = item.path if isinstance(item, RepoFile) else ""
        self._load_items()
        self._tell(f"Files {at}.")

    def _show_file_history(self) -> None:
        """H, or Actions ▸ File History: the commits that changed the
        selected file. Backspace comes back to it."""
        item = self._code_file("File History")
        if item is None:
            return
        snap = self._code_snapshot(item)
        ref, at = self._code_ref, self._code_at
        self._switch_view(VIEW_HISTORY, load=False)
        # Set after the switch, which clears them on the way in to anything else.
        self._history_of = (ref, item.path, at)
        self._history_back = snap
        self._update_title()
        self._load_items()

    def _on_history_loaded(self, token: int, commits: list) -> None:
        if not self._fetch_is_current(token):
            return  # the user has moved on; these belong to a view they left
        self.git_items = commits
        self.items = []
        filtered = self._populate_filtered_list(commits, use_favorite_prefix=True)
        _, path, at = self._history_of or ("", "", "")
        n = len(commits)
        said = (f"{n} commit{'s' if n != 1 else ''} changed {path}." if n
                else f"No commits changed {path} {at}.")
        self._set_view_status(
            f"History of {path} {at} — {n} commit{'s' if n != 1 else ''}. "
            f"Showing up to {self.current_limit}.",
            "Enter=changed files  Alt+N/Alt+P=next/previous change  Ctrl++=view more  "
            "Ctrl+O=open on GitHub  Ctrl+F=filter  Backspace=back to files",
        )
        self._update_title()
        row = self._take_pending_row(commits, token)

        def arrive() -> None:
            if not self._fetch_is_current(token):
                return
            if filtered:
                self._focus_list(row)
            announce.announce(said, announce.STATUS)

        wx.CallLater(100, arrive)

    def _show_history_details(self, idx: int) -> None:
        """One commit of a file's history: what it did to the file."""
        if idx < 0 or idx >= len(self.git_items) or not self._history_of:
            self.details_text.Clear()
            return
        self._render_history(self.git_items[idx])

    def _render_history(self, commit: Commit) -> None:
        path = self._history_of[1]
        key = (commit.sha, path)
        loading = key not in self._patch_cache
        text, starts = codeview.history_text(commit, path, self._patch_cache.get(key),
                                             self._diff_style, loading=loading)
        self.details_text.SetValue(text)
        self._comment_positions = [(line, 1) for line in starts]
        self._current_comment = -1
        if not loading:
            return
        gen, repo = self._detail_gen, self.repo

        def worker() -> None:
            try:
                f, err = fetch_commit_file(repo, commit.sha, path), ""
            except GhError as exc:
                f, err = None, str(exc)
            wx.CallAfter(self._on_patch_fetched, gen, commit, key, f, err)

        def start() -> None:
            if gen == self._detail_gen:
                threading.Thread(target=worker, daemon=True).start()

        wx.CallLater(250, start)

    def _on_patch_fetched(self, gen: int, commit: Commit, key: tuple, f, err: str) -> None:
        if not err:
            if len(self._patch_cache) >= 500:
                self._patch_cache.clear()
            self._patch_cache[key] = f
        if not self._shows(VIEW_HISTORY, commit, gen):
            return
        if err:
            self.details_text.SetValue(
                f"{codeview.commit_heading(commit)}\n\nCouldn't get the changes. {err}")
            return
        self._render_history(commit)

    def _back_from_history(self) -> None:
        """Backspace in File History: Files as it was, on the file."""
        snap = self._history_back
        if not snap:
            self._switch_view(VIEW_CODE)
            return
        self._restore_code(snap)
        self._announce("Back to files")

    def _open_whole_file(self) -> None:
        """W in Changed Files: the selected file, whole, in Files, at the
        pull request's latest commit or at the commit. Backspace comes back."""
        item = self._focused_item()
        if self.view_mode != VIEW_FILES:
            self._tell("Open Whole File is for a file in Changed Files.")
            return
        if not isinstance(item, ChangedFile):
            self._tell("Select a file first.")
            return
        if item.status == "removed":
            self._tell(f"{item.filename} is deleted by this change, so there is "
                       "no whole file to open.")
            return
        src = self._files_of
        if isinstance(src, Commit):
            self._open_code_at(item, src.sha, f"at commit {src.short_sha}")
            return
        if not isinstance(src, Item):
            self._tell("Select a file first.")
            return
        if self._whole_file_busy:
            self._tell("Still finding the pull request's latest commit.")
            return
        self._whole_file_busy = True
        self._announce(f"Finding the latest commit of PR #{src.number}…")

        def worker() -> None:
            try:
                sha, err = fetch_pr_head_sha(src.url), ""
            except GhError as exc:
                sha, err = "", str(exc)
            wx.CallAfter(self._on_head_sha, item, src, sha, err)

        threading.Thread(target=worker, daemon=True).start()

    def _on_head_sha(self, item: ChangedFile, pr: Item, sha: str, err: str) -> None:
        self._whole_file_busy = False
        if (self.view_mode != VIEW_FILES or self._files_of is not pr
                or self._focused_item() is not item):
            return  # moved on meanwhile
        if not sha:
            self._tell(f"Couldn't find the pull request's latest commit. {err}".strip())
            return
        self._open_code_at(item, sha, f"at PR #{pr.number}, {sha[:8]}")

    def _caret_line(self) -> int:
        """The line (from 0) of the details panel the caret is on."""
        caret = self.details_text.GetInsertionPoint()
        return self.details_text.GetValue().count("\n", 0, caret)

    def _comment_on_line(self) -> None:
        """M in a pull request's changed file, or Actions ▸ Comment on This
        Line: a review comment on the line the caret is on, posted on the
        pull request's latest commit."""
        src = self._files_of if self.view_mode == VIEW_FILES else None
        if not isinstance(src, Item):
            self._tell("Line comments are for a pull request's changed files, "
                       "not a commit's." if isinstance(src, Commit) else
                       "Comment on This Line is for a pull request's file in Changed Files.")
            return
        item = self._focused_item()
        view = getattr(self, "_file_view", None)
        if not isinstance(item, ChangedFile) or view is None:
            self._tell("Select a file first.")
            return
        if self._line_comment_busy:
            self._tell("Still adding the last comment.")
            return
        line = self._caret_line()
        target = view.target(line)
        if isinstance(target, str):
            self._tell(target)
            return
        side, number = target
        where = f"line {number}" if side == "RIGHT" else f"removed line {number}"
        shown = view.text.split("\n")[line]
        if len(shown) > 200:
            shown = shown[:200] + "…"  # the prompt names the box: keep it short
        dlg = wx.TextEntryDialog(
            self, f"Comment on {where} of {item.filename}:\n{shown}",
            "Comment on This Line", "", style=wx.TE_MULTILINE | wx.OK | wx.CANCEL)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            body = dlg.GetValue().strip()
        finally:
            dlg.Destroy()
        if not body:
            return
        self._line_comment_busy = True
        self._announce(f"Adding a comment on {where}…")
        path = item.filename
        shown_head = getattr(self, "_files_head", "")

        def worker() -> None:
            # Any failure, not only gh's, comes back to clear the busy flag.
            try:
                sha = fetch_pr_head_sha(src.url)
                if shown_head and sha != shown_head:
                    # GitHub would read the line number in the new diff,
                    # where it may be another line, or none.
                    raise GhError("The pull request has new commits since these lines "
                                  "were read. Press R in the list of files to read them "
                                  "again, then comment.")
                add_review_comment(src.url, sha, path, number, side, body)
            except Exception as exc:  # noqa: BLE001
                wx.CallAfter(self._on_line_comment_done, src, item, line, where,
                             False, None, str(exc))
                return
            try:
                comments, err = fetch_pr_review_comments(src.url), ""
            except Exception as exc:  # noqa: BLE001
                comments, err = None, str(exc)
            wx.CallAfter(self._on_line_comment_done, src, item, line, where,
                         True, comments, err)

        threading.Thread(target=worker, daemon=True).start()

    def _on_line_comment_done(self, pr: Item, item: ChangedFile, line: int, where: str,
                              posted: bool, comments: list | None, err: str) -> None:
        """The comment is in (or isn't): the file's lines read again with it,
        the caret kept on the line, and the Comments column brought up to date."""
        self._line_comment_busy = False
        if not posted:
            self._tell(f"Couldn't add the comment. {err}".strip())
            return
        msg = f"Comment added on {where}."
        if comments is None:
            msg += f" Couldn't read the comments again: {err}"
        elif self.view_mode == VIEW_FILES and self._files_of is pr:
            GhViewerFrame._attach_comments(self.git_items, comments)
            for row, shown in enumerate(self._shown):
                self._redraw_row(row, shown)
            shown = self._focused_item()
            if isinstance(shown, ChangedFile) and shown.filename == item.filename:
                self._show_details(self.list_ctrl.GetFirstSelected())
                self.details_text.SetInsertionPoint(self._line_to_position(line))
                # Alt+N from here goes on to the comments on the line.
                self._current_comment = sum(
                    1 for p in self._comment_positions if p[0] <= line) - 1
        self._tell(msg)

    def _open_code_at(self, item: ChangedFile, ref: str, at: str) -> None:
        """Files at ``ref``, in the folder of ``item``, on it."""
        snap = {
            "files_of": self._files_of, "files_back": self._files_back,
            "items": list(self.git_items), "item": item, "filter_text": self.filter_text,
        }
        self._switch_view(VIEW_CODE, load=False)
        self._code_ref, self._code_at = ref, at
        self._code_path = item.filename.rpartition("/")[0]
        self._code_stack = []
        self._code_land = item.filename
        self._code_back = snap
        self._update_title()
        self._load_items()

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

    def _browse_milestone(self, milestone: Milestone) -> None:
        """Enter in Milestones: the issues and PRs in ``milestone``, in
        Issues & PRs, as Enter on a label does; Backspace comes back."""
        self.label_filter = ""
        self.current_limit = self.page_size
        # The way back from Milestones to a list it was opened from (Starred,
        # Activity), which the switch to Issues & PRs would otherwise drop.
        self._milestone_return = (getattr(self, "_return_to", None),
                                  getattr(self, "_return_view", VIEW_ISSUES))
        self._switch_view(VIEW_ISSUES, load=False)
        # Set after the switch, which clears it everywhere but Issues & PRs.
        self.milestone_filter = milestone
        self._update_title()
        self._load_items()
        said = (f"Showing issues and PRs in milestone '{milestone.title}'. "
                "Backspace returns to the milestones.")
        self._announce(said)
        # Queued behind the first row, which focus reads.
        announce.announce(f"Milestone {milestone.title}", announce.STATUS)

    def _back_to_milestones(self) -> None:
        """Backspace from a milestone's issues: the milestones, on it."""
        milestone = self.milestone_filter
        self.milestone_filter = None
        self._switch_view(VIEW_MILESTONES)
        if milestone is not None:
            self._set_pending_target(VIEW_MILESTONES, "milestone", str(milestone.number))
        saved = getattr(self, "_milestone_return", None)
        self._milestone_return = None
        if saved and saved[0] and saved[1] == VIEW_MILESTONES:
            self._return_to, self._return_view = saved
        self._announce("Back to milestones")

    def _browse_label(self, label: "Label") -> None:
        """Show the issues and PRs carrying ``label``.

        This reuses the Issues & PRs view rather than inventing a new one, so
        the state filter, columns, sorting, and every issue action still work.
        The restriction is applied by `gh`, not by the quick filter, so it
        finds items that were never on the current page.
        """
        self.label_filter = label.name
        self.milestone_filter = None
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