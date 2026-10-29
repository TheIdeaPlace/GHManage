"""No key instructions in content (Kelly's rule).

The details panel, a file's or a diff's text, and the reports GHManage
writes describe the item only. Keys belong on the menus (with the key in the
label), in the status bar's key hints, in Keyboard Shortcuts and in the user
guide, not in the middle of the text being read: "Press Enter to…",
"Ctrl+O opens it on GitHub" and "Backspace goes back…" were all over it once.

Two guards: every details formatter is run on sample items of each kind and
its text scanned; and the source of the formatters is scanned for a line of
text with a key in it, so a new one can't creep in. An empty or error state
may still say what would help; those are allowed by name below.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import alertview
import codeview
import diffview
import discussionview
import gistview
import insightview
import milestoneview
from gh_data import (
    ALERT_CODE, ALERT_DEPENDABOT, ALERT_SECRET, ActivityEvent, Artifact, Branch, ChangedFile, Check,
    Commit, Discussion, DiscussionComment, Gist, GistFile, InsightRow, Insights, Item, JobStep,
    Label, Milestone, Notification, OrgEntry, PagesBuild, PagesFile, PagesSite, Release,
    ReleaseAsset, RepoEntry, RepoFile, SecurityAlert, Tag, Workflow, WorkflowJob, WorkflowRun,
)

if os.environ.get("CI"):
    import wx  # noqa: F401
else:
    pytest.importorskip("wx")

import ghviewer  # noqa: E402
from favorites import FavoriteEntry  # noqa: E402

Frame = ghviewer.GhViewerFrame
ROOT = Path(__file__).resolve().parent.parent

# A key named in text: "Press Enter", "Ctrl+O", "Backspace", "Alt+N", and
# Enter said as what it does ("Enter opens", "Enter to list").
FORBIDDEN = re.compile(
    r"\bpress\b|Ctrl\+|Backspace|Alt\+[NP]\b|\bEnter (to|opens|goes|lists|reads|runs|"
    r"downloads|shows)\b|\bKeys:",
    re.IGNORECASE)

# Empty and error states, which may say what would help.
ALLOWED = {
    "GitHub is still counting the contributors; press R in a moment.",
}


def _clean(text: str) -> str:
    for allowed in ALLOWED:
        text = text.replace(allowed, "")
    return text


def _assert_no_keys(text: str, where: str) -> None:
    hits = [ln for ln in _clean(text).splitlines() if FORBIDDEN.search(ln)]
    assert not hits, f"{where}: key instructions in content: {hits}"


# ── The formatters, run on samples of every kind ──────────────────────

URL = "https://github.com/o/r/issues/4"
SITE = PagesSite(url="https://o.github.io/r/", source_branch="main")
ACTIONS_SITE = PagesSite(url="https://o.github.io/r/", source_branch="main",
                         build_type="workflow")

GIT_ITEMS = [
    Branch("main", "abc", "msg", "me", "2026-01-01", ahead=1, behind=2, url=URL),
    Commit("c" * 40, "ccccccc", "msg", "me", "2026-01-01", url=URL, additions=1,
           deletions=1, files_changed=1, files=[{"filename": "a.py", "status": "modified"}],
           branches=["main"]),
    Tag("v1", "abc", url=URL),
    Label("bug", "d73a4a", "Something is wrong", url=URL),
    Release("v1", "One", False, False, "2026-01-01", url=URL, body="Notes",
            assets=[ReleaseAsset(1, "a.exe", 100, 5, "2026-01-01", url=URL)]),
    Release("v2", "Two", True, True, "2026-01-01", url=URL),
    Workflow(1, "CI", ".github/workflows/ci.yml", "active", url=URL),
    WorkflowRun("CI", "completed", "failure", "main", "push", "2026-01-01", url=URL),
    WorkflowRun("CI", "in_progress", "", "main", "push", "2026-01-01", url=URL),
    WorkflowJob(5, "build", "completed", "failure", url=URL,
                steps=[JobStep(1, "Set up", "completed", "success"),
                       JobStep(2, "Test", "completed", "failure")]),
    Artifact(1, "build", 10, False, "2026-01-01"),
    Artifact(2, "old", 10, True, "2026-01-01"),
    ReleaseAsset(1, "a.exe", 100, 5, "2026-01-01", url=URL, release_tag="v1"),
    PagesBuild(1, "built", "abc", "me", "2026-01-01", duration_ms=3000, url=URL),
    PagesBuild(2, "success", "abc", "me", "2026-01-01", kind="deployment", url=URL),
    PagesFile("index.md", "https://o.github.io/r/index.html"),
    PagesFile("style.css", "https://o.github.io/r/style.css"),
    RepoEntry("o/r", "A repo", url="https://github.com/o/r", language="Python",
              archived=True, fork=True, private=True, pushed_at="2026-01-01"),
    OrgEntry("o", repo_count=3),
    Notification("1", "Fix it", "o/r", "mention", "Issue", url=URL, number=4),
    Notification("2", "v1", "o/r", "subscribed", "Release",
                 url="https://github.com/o/r/releases/tag/v1"),
    Notification("3", "Something", "o/r", "subscribed", "CheckSuite",
                 url="https://github.com/o/r/compare/a...b"),
    ActivityEvent("IssueCommentEvent", "alice", "o/r", "commented on issue #4",
                  title="Crash", url=URL + "#c1", body="Same here.", subject_kind="issue",
                  number=4, subject_url=URL),
    ActivityEvent("PushEvent", "bob", "o/r", "pushed to main",
                  url="https://github.com/o/r/compare/a...b"),
]


def _frame(**attrs):
    text = SimpleNamespace(value="")
    text.SetValue = lambda v: setattr(text, "value", v)
    text.GetValue = lambda: text.value
    text.Clear = lambda: setattr(text, "value", "")
    f = SimpleNamespace(details_text=text, items=[], git_items=[], favorites=[],
                        commit_branch="", pages_site=None, repo="o/r", view_mode="",
                        _comment_positions=[], _current_comment=-1)
    for k, v in attrs.items():
        setattr(f, k, v)
    return f


@pytest.mark.parametrize("site", [None, SITE, ACTIONS_SITE])
@pytest.mark.parametrize("item", GIT_ITEMS, ids=lambda i: type(i).__name__)
def test_git_details_name_no_keys(item, site):
    for view in ghviewer.VIEW_COLUMNS:
        f = _frame(git_items=[item], pages_site=site, view_mode=view)
        Frame._show_git_details(f, 0)
        assert f.details_text.value
        _assert_no_keys(f.details_text.value, f"{type(item).__name__} in {view}")


def test_git_details_do_not_end_on_an_empty_rule():
    for item in GIT_ITEMS:
        for site in (None, SITE, ACTIONS_SITE):
            f = _frame(git_items=[item], pages_site=site)
            Frame._show_git_details(f, 0)
            last = f.details_text.value.split("\n")[-1]
            assert last.strip() and set(last) != {"─"}, type(item).__name__


ISSUES = [
    Item(4, "Fix", "OPEN", URL, False, body="Text", comments=2,
         comment_list=[{"author": "a", "created_at": "2026-01-01", "body": "hi"}]),
    Item(5, "PR", "OPEN", URL, True, is_draft=True, review_status="APPROVED", additions=1,
         deletions=1, changed_files=1, head_branch="f", base_branch="main", comments=3),
    Item(6, "PR", "OPEN", URL, True, comments=3, repo="o/r", why="review requested"),
    Item(7, "Done", "CLOSED", URL, False, repo="o/fork"),
]


@pytest.mark.parametrize("item", ISSUES, ids=lambda i: f"#{i.number}")
@pytest.mark.parametrize("view", [ghviewer.VIEW_ISSUES, ghviewer.VIEW_MY_WORK,
                                  ghviewer.VIEW_SEARCH_ISSUES])
def test_issue_details_name_no_keys(item, view):
    f = _frame(items=[item], view_mode=view)
    f.__dict__["_fork_parent"] = {"o/fork": "up/r"}
    Frame._show_issue_details(f, 0)
    text = f.details_text.value
    assert text.startswith(f"#{item.number} ")
    _assert_no_keys(text, f"#{item.number} in {view}")
    assert f"Comments: {item.comments}" in text.split("\n")


@pytest.mark.parametrize("fav", [
    FavoriteEntry("o/r", "issue", URL, "#4 — Fix"),
    FavoriteEntry("o/r", "repository", "https://github.com/o/r", "o/r"),
    FavoriteEntry("o/r", "page", "https://o.github.io/r/a.html", "a.html",
                  subtitle="https://o.github.io/r/a.html"),
    FavoriteEntry("o/r", "compare", "https://github.com/o/r/compare/a...b", "a...b"),
])
def test_favorite_details_name_no_keys(fav):
    f = _frame(favorites=[fav])
    Frame._show_favorite_details(f, 0)
    text = f.details_text.value
    assert text.split("\n")[-1] == fav.url
    _assert_no_keys(text, f"favorite {fav.title}")


ALERTS = [
    SecurityAlert(ALERT_DEPENDABOT, 1, "open", "high", "lodash", "Prototype pollution",
                  url=URL, info={"advisory_url": "https://github.com/advisories/x",
                                 "description": "\n".join(f"l{i}" for i in range(200))}),
    SecurityAlert(ALERT_CODE, 2, "dismissed", "", "py/sql", "SQL", url=URL,
                  info={"dismissed_at": "2026-01-01", "dismissed_reason": "false positive"}),
    SecurityAlert(ALERT_SECRET, 3, "resolved", "", "token", "A token", url=URL),
]


@pytest.mark.parametrize("alert", ALERTS, ids=lambda a: a.kind)
def test_alert_details_name_no_keys(alert):
    _assert_no_keys(alertview.alert_details(alert), alert.kind)


def test_a_cut_description_says_where_the_rest_is_without_a_key():
    cut = alertview.trim_text("\n".join(f"l{i}" for i in range(100)), max_lines=3)
    assert cut.split("\n")[-1] == "(More on GitHub.)"


def test_discussion_details_name_no_keys():
    reply = DiscussionComment("c", "reply")
    d = Discussion(3, "Q", url=URL, category="Q&A", author="a", body="Body", comment_count=9,
                   comments=[DiscussionComment("b", "x", is_answer=True, replies=[reply],
                                               reply_count=4)],
                   comments_cut=True)
    for item in (d, Discussion(4, "Q", url=URL, comment_count=2)):
        text, _ = discussionview.discussion_details(item)
        _assert_no_keys(text, f"discussion {item.number}")


def test_gist_text_names_no_keys():
    g = Gist("abc", "Notes", url=URL, loaded=True, files_truncated=True, files=[
        GistFile("a.md", 10, content="# a\n"),
        GistFile("big", 2_000_000),
        GistFile("bin", 2, content="\x00\x01"),
        GistFile("cut", 10, content="x\n", truncated=True),
        GistFile("huge", 10, content="y" * (gistview.MAX_GIST_CHARS + 1)),
    ])
    for item in (g, Gist("def", "Other", url=URL)):
        text, _ = gistview.gist_text(item)
        _assert_no_keys(text, f"gist {item.id}")


@pytest.mark.parametrize("row", [
    InsightRow("Views", "Last 14 days", 5, 2, url=URL),
    InsightRow("Clones", "2026-10-20", 1, 1, url=URL),
    InsightRow("Referrer", "github.com", 9, 9, url=URL),
    InsightRow("Page", "/issues", 9, 3, detail="/o/r/issues", url=URL),
    InsightRow("Contributor", "kelly", 312, url=URL),
], ids=lambda r: r.section)
def test_insight_details_name_no_keys(row):
    _assert_no_keys(insightview.insight_details(row), row.section)


def test_milestone_details_name_no_keys():
    for m in (Milestone(3, "v1", description="Plan", url=URL, creator="k", closed_at="x"),
              Milestone(4, "v2", url=URL)):
        text = milestoneview.milestone_details(m)
        assert text.split("\n")[-1] in ("Plan", "(no description)")
        _assert_no_keys(text, m.title)


def test_file_and_diff_text_name_no_keys():
    big = RepoFile("big.json", size=10_000_000)
    for f in (RepoFile("src", "dir"), RepoFile("lib", "submodule", sha="abcdef123"),
              RepoFile("l", "link"), big):
        _assert_no_keys(codeview.entry_text(f), f.path)
    _assert_no_keys(codeview.file_text(RepoFile("b.bin", size=2), "\x00\x01")[0], "binary")
    for kw in (dict(patch=None, additions=4000), dict(patch=None),
               dict(patch="", status="renamed", previous_filename="old.py"),
               dict(patch="@@ -1 +1 @@\n-a\n+b", additions=1, deletions=1)):
        for style in diffview.STYLES:
            _assert_no_keys(diffview.file_text(ChangedFile("a.py", **kw), style)[0], str(kw))


def test_reports_name_no_keys():
    run = WorkflowRun("CI", "completed", "failure", "main", "push", "", run_number=4, run_id=7)
    job = WorkflowJob(1, "build", "completed", "failure",
                      steps=[JobStep(1, "Test", "completed", "failure")])
    report = ghviewer.format_failure_report(run, [job], {}, [("build", "Test", ["boom"])])
    _assert_no_keys(report, "what failed")
    check = Check("test", "FAILURE", "fail", "CI", "https://x/1", "3 failed")
    _assert_no_keys(ghviewer.format_checks("#5 Fix", [check]), "checks")


def test_empty_states_may_say_what_helps():
    # Allowed, and only because they are empty or error states.
    said = insightview.notes(Insights(rows=[], contributors_pending=True))
    assert said == ["GitHub is still counting the contributors; press R in a moment."]
    _assert_no_keys(" ".join(said), "contributors pending")


# ── The source: no line of text with a key in it ──────────────────────

FORMATTERS = {
    "ghviewer.py": ("_show_git_details", "_show_issue_details", "_show_favorite_details",
                    "format_failure_report", "format_checks", "format_job_log"),
    "alertview.py": None, "codeview.py": None, "diffview.py": None,
    "discussionview.py": None, "gistview.py": None, "insightview.py": None,
    "milestoneview.py": None,
}
# Functions in those modules that write the status bar, not content.
STATUS_LINE_FUNCTIONS = {"status_message", "notes"}


def _strings(node: ast.AST) -> list[str]:
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append(n.value)
    return out


def _docstrings(fn: ast.AST) -> set[int]:
    ids = set()
    for n in ast.walk(fn):
        if isinstance(n, (ast.FunctionDef, ast.Module, ast.ClassDef)) and n.body:
            first = n.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
    return ids


@pytest.mark.parametrize("name", sorted(FORMATTERS))
def test_formatter_source_has_no_key_instructions(name):
    tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
    wanted = FORMATTERS[name]
    hits = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef) or fn.name in STATUS_LINE_FUNCTIONS:
            continue
        if wanted is not None and fn.name not in wanted:
            continue
        docs = _docstrings(fn)
        for n in ast.walk(fn):
            if (isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and id(n) not in docs and FORBIDDEN.search(_clean(n.value))):
                hits.append(f"{fn.name}: {n.value!r}")
    assert not hits, hits


def test_the_read_keys_line_is_gone():
    import commands
    assert not hasattr(commands, "READ_KEYS")
    for name in FORMATTERS:
        assert "READ_KEYS" not in (ROOT / name).read_text(encoding="utf-8"), name
