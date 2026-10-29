"""Pull request actions: checks, review, merge, draft, reviewers, update branch."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

import gh_data
from gh_data import Check, Item


URL = "https://github.com/up/r/pull/5"


def _checks_output(monkeypatch, rows, code=0, stderr=""):
    seen = []

    def run(args, **k):
        seen.append(args)
        return SimpleNamespace(stdout=json.dumps(rows) if rows is not None else "",
                               stderr=stderr, returncode=code)
    monkeypatch.setattr(gh_data.subprocess, "run", run)
    return seen


def test_pr_parts():
    assert gh_data._pr_parts(URL) == ("up/r", 5)
    with pytest.raises(gh_data.GhError):
        gh_data._pr_parts("https://github.com/up/r/issues/5")


def test_checks_are_read_even_when_gh_exits_non_zero(monkeypatch):
    # gh exits 1 when a check failed, 8 while one runs, and prints them anyway
    seen = _checks_output(monkeypatch, [
        {"name": "lint", "state": "SUCCESS", "bucket": "pass", "workflow": "CI"},
        {"name": "test", "state": "FAILURE", "bucket": "fail", "workflow": "CI"},
        {"name": "build", "state": "PENDING", "bucket": "pending", "workflow": "CI"},
    ], code=1)
    checks = gh_data.fetch_pr_checks(URL)
    assert [c.name for c in checks] == ["test", "build", "lint"]
    assert seen[0][1:4] == ["pr", "checks", URL]


def test_no_checks(monkeypatch):
    _checks_output(monkeypatch, None, code=1, stderr="no checks reported on the 'x' branch")
    assert gh_data.fetch_pr_checks(URL) == []


def test_checks_error(monkeypatch):
    _checks_output(monkeypatch, None, code=1, stderr="HTTP 404")
    with pytest.raises(gh_data.GhError, match="404"):
        gh_data.fetch_pr_checks(URL)


@pytest.mark.parametrize("method, delete, expected", [
    ("squash", False, ["pr", "merge", URL, "--squash"]),
    ("rebase", True, ["pr", "merge", URL, "--rebase", "--delete-branch"]),
])
def test_merge_targets_the_pull_request_by_its_address(fake_gh, method, delete, expected):
    # By address, never number + repo: a failed fork lookup must not be able
    # to send the merge to the fork's own #5.
    fake_gh.route("pr merge", "")
    fake_gh.route("pr view", {"state": "MERGED", "autoMergeRequest": None})
    assert gh_data.merge_pr(URL, method, delete) == "merged"
    assert fake_gh.calls[0] == expected


@pytest.mark.parametrize("view, outcome", [
    ({"state": "MERGED"}, "merged"),
    ({"state": "OPEN", "autoMergeRequest": {"enabledAt": "x"}}, "auto"),
    ({"state": "OPEN", "autoMergeRequest": None}, "queued"),
    (gh_data.GhError("HTTP 502"), "queued"),
])
def test_merge_says_what_actually_happened(fake_gh, view, outcome):
    fake_gh.route("pr merge", "")
    fake_gh.route("pr view", view)
    assert gh_data.merge_pr(URL, "merge") == outcome


def test_merge_rejects_an_unknown_method():
    with pytest.raises(ValueError):
        gh_data.merge_pr(URL, "octopus")


@pytest.mark.parametrize("ready, tail", [(True, []), (False, ["--undo"])])
def test_ready_and_draft(fake_gh, ready, tail):
    fake_gh.route("pr ready", "")
    gh_data.set_pr_ready(URL, ready)
    assert fake_gh.calls == [["pr", "ready", URL, *tail]]


def test_review_sends_the_message_on_stdin(fake_gh):
    fake_gh.route("pr review", "")
    gh_data.review_pr(URL, "request-changes", "Please fix — ünïcode too")
    assert fake_gh.calls == [["pr", "review", URL, "--request-changes", "--body-file", "-"]]
    assert fake_gh.stdin == ["Please fix — ünïcode too"]


def test_approve_without_a_message(fake_gh):
    fake_gh.route("pr review", "")
    gh_data.review_pr(URL, "approve")
    assert fake_gh.calls == [["pr", "review", URL, "--approve"]]
    assert fake_gh.stdin == [None]


def test_request_reviewers(fake_gh):
    fake_gh.route("pr edit", "")
    gh_data.request_reviewers(URL, ["alice", "org/team"])
    assert fake_gh.calls == [["pr", "edit", URL, "--add-reviewer", "alice,org/team"]]


def test_update_branch(fake_gh):
    fake_gh.route("update-branch", "{}")
    gh_data.update_pr_branch(URL)
    assert fake_gh.calls == [["api", "-X", "PUT", "repos/up/r/pulls/5/update-branch"]]


def test_allowed_merge_methods(fake_gh):
    fake_gh.route("repo view up/r", {"mergeCommitAllowed": False, "squashMergeAllowed": True,
                                     "rebaseMergeAllowed": True})
    assert gh_data.allowed_merge_methods(URL) == ["squash", "rebase"]


# ── The window ──────────────────────────────────────────────────────────

if os.environ.get("CI"):
    import wx  # noqa: F401
else:
    pytest.importorskip("wx")

import ghviewer  # noqa: E402

Frame = ghviewer.GhViewerFrame


def test_format_checks():
    text = ghviewer.format_checks("#5 Fix", [
        Check("test", "FAILURE", "fail", "CI", "https://x/1", "3 failed"),
        Check("lint", "SUCCESS", "pass", "CI"),
        Check("lint2", "SUCCESS", "pass", ""),
    ])
    lines = text.splitlines()
    assert lines[:2] == ["Checks for #5 Fix", "1 failed, 2 passed"]
    assert "failed: CI / test" in lines and "    3 failed" in lines and "passed: lint2" in lines
    assert lines[-1] == "passed: lint2"


def test_format_no_checks():
    assert ghviewer.format_checks("#5 Fix", []).splitlines()[1] == "No checks have run."


def _frame(item, view=ghviewer.VIEW_ISSUES):
    f = SimpleNamespace(view_mode=view, repo="o/r", announced=[])
    f._announce = f.announced.append
    f._focused_item = lambda: item
    f._focused_pr = lambda: Frame._focused_pr(f)
    f._open_pr = lambda: Frame._open_pr(f)
    f._pr_label = Frame._pr_label
    return f


def test_pr_actions_need_a_pull_request():
    f = _frame(Item(1, "An issue", "OPEN", "u", False))
    Frame._pr_checks(f)
    assert f.announced == ["Select a pull request in Issues & PRs first."]


def test_a_draft_cannot_be_merged():
    f = _frame(Item(2, "Draft", "OPEN", "u", True, is_draft=True))
    Frame._pr_merge(f)
    assert f.announced == ["#2 is a draft; mark it ready for review first (D)."]


def test_a_merged_pr_cannot_be_merged_again():
    f = _frame(Item(3, "Done", "MERGED", "u", True, is_merged=True))
    Frame._pr_merge(f)
    assert f.announced == ["#3 is merged."]


@pytest.mark.parametrize("action", ["_pr_review", "_pr_update_branch", "_pr_request_reviewers"])
def test_actions_on_a_closed_pr_say_so(action):
    f = _frame(Item(6, "Old", "CLOSED", "u", True))
    getattr(Frame, action)(f)
    assert f.announced == ["#6 is closed."]


@pytest.mark.parametrize("draft, ready", [(True, True), (False, False)])
def test_d_flips_draft_after_asking(monkeypatch, draft, ready):
    asked = []
    monkeypatch.setattr(ghviewer.wx, "MessageBox", lambda msg, *a, **k: asked.append(msg) or ghviewer.wx.YES)
    f = _frame(Item(4, "T", "OPEN", "u", True, is_draft=draft))
    calls = []
    f._pr_in_background = lambda call, done, error: calls.append(done)
    Frame._pr_toggle_draft(f)
    assert len(asked) == 1
    assert calls == ["#4 is ready for review" if ready else "#4 is back to a draft"]


def test_d_answered_no_changes_nothing(monkeypatch):
    monkeypatch.setattr(ghviewer.wx, "MessageBox", lambda *a, **k: ghviewer.wx.NO)
    f = _frame(Item(4, "T", "OPEN", "u", True))
    f._pr_in_background = lambda *a: pytest.fail("not after No")
    Frame._pr_toggle_draft(f)


def test_merge_outcomes_are_worded():
    for outcome in ("merged", "auto", "queued"):
        assert "#7" in Frame._MERGE_OUTCOMES[outcome].format(n=7)
