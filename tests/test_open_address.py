"""Open Repository or Address: GitHub addresses and where they land."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

if os.environ.get("CI"):
    import wx  # noqa: F401
else:
    pytest.importorskip("wx")

import ghviewer  # noqa: E402
from gh_data import Commit, Item, Release, WorkflowRun  # noqa: E402

Frame = ghviewer.GhViewerFrame
parse = ghviewer.parse_github_url
T = ghviewer.GitHubTarget


@pytest.mark.parametrize("text, target", [
    ("owner/name", T("owner/name")),
    ("https://github.com/owner/name", T("owner/name")),
    ("https://github.com/owner/name.git", T("owner/name")),
    ("git@github.com:owner/name.git", T("owner/name")),
    ("github.com/owner/name/", T("owner/name")),
    ("https://github.com/nvaccess/nvda/issues/11538", T("nvaccess/nvda", "item", "11538")),
    ("https://github.com/o/r/pull/12", T("o/r", "item", "12")),
    ("https://github.com/o/r/pull/12/files", T("o/r", "item", "12")),
    ("https://github.com/o/r/issues/12#issuecomment-99", T("o/r", "item", "12")),
    ("https://github.com/o/r/commit/abc1234", T("o/r", "commit", "abc1234")),
    ("https://github.com/o/r/releases/tag/v1.2.0", T("o/r", "release", "v1.2.0")),
    ("https://github.com/o/r/releases/tag/app/v1", T("o/r", "release", "app/v1")),
    ("https://github.com/o/r/actions/runs/123456", T("o/r", "run", "123456")),
    ("https://github.com/o/r/actions/runs/123456/job/9", T("o/r", "run", "123456")),
    ("https://github.com/o/r/tree/dev", T("o/r", "branch", "dev")),
    ("https://github.com/o/r/tree/main/docs", T("o/r", "inside")),
    ("https://github.com/o/r/blob/main/README.md", T("o/r", "inside")),
    ("https://github.com/o/r/releases", T("o/r", "view", "releases")),
    ("https://github.com/o/r/pulls", T("o/r", "view", "issues")),
    ("https://github.com/o/r/actions", T("o/r", "view", "workflow")),
    ("https://github.com/o/r/labels", T("o/r", "view", "labels")),
    ("https://github.com/o/r/wiki", T("o/r", "inside")),
    ("https://github.com/o/r/discussions/5", T("o/r", "discussion", "5")),
    ("https://github.com/o/r/discussions", T("o/r", "view", "discussions")),
    ("https://github.com/o/r/discussions/categories/q-a", T("o/r", "inside")),
    ("https://github.com/o/r/compare/a...b", T("o/r", "inside")),
    # Pasted from email, chat and Markdown
    ("<https://github.com/o/r>", T("o/r")),
    ("https://github.com/o/r.", T("o/r")),
    ("(https://github.com/o/r/pull/3)", T("o/r", "item", "3")),
    ("https://github.com/o/r/issues/12,", T("o/r", "item", "12")),
    ("github.com/o/r\u200b", T("o/r")),
    ("HTTPS://GitHub.com/o/r/issues/3", T("o/r", "item", "3")),
    ("https://www.github.com/o/r", T("o/r")),
    ("http://github.com/o/r", T("o/r")),
    # Encoded and decorated refs
    ("https://github.com/o/r/releases/tag/v1.0%2Bb", T("o/r", "release", "v1.0+b")),
    ("https://github.com/o/r/tree/feature%2Fx", T("o/r", "branch", "feature/x")),
    ("https://github.com/o/r/commit/abc1234.patch", T("o/r", "commit", "abc1234")),
    ("https://github.com/o/r/commit/zzz", T("o/r", "inside")),
    ("https://github.com/o/r/commits/dev", T("o/r", "branch", "dev")),
    ("https://github.com/o/r/actions/workflows/ci.yml", T("o/r", "view", "workflows")),
    ("https://github.com/o/r?tab=readme", T("o/r")),
    ("https://github.com/someone", T("", "user", "someone")),
    ("https://github.com/orgs/nvaccess/repositories", T("", "user", "nvaccess")),
])
def test_parse(text, target):
    assert parse(text) == target


@pytest.mark.parametrize("text", [
    "", "   ", "owner", "https://github.com/", "https://github.com/settings/profile",
    "https://github.com/notifications", "https://github.com/issues/assigned",
    "https://github.example.com/o/r", "https://raw.githubusercontent.com/o/r/main/x",
    "https://api.github.com/repos/o/r/issues/1", "https://gist.github.com/kelly/abc123",
    "git@ghe.corp:o/r.git", "https://github.com/stars/kelly",
    "https://github.com/advisories/GHSA-1234", "ftp://github.com/o/r",
    "https://github.com/o/../x", "https://github.com/-bad-/r",
])
def test_parse_rejects(text):
    assert parse(text) is None


def test_view_targets_are_real_views():
    for view in ghviewer._URL_VIEWS.values():
        assert view in ghviewer.VIEW_COLUMNS


# ── Landing on the item ─────────────────────────────────────────────────


class Later:
    """Collects wx.CallLater calls instead of running them on a timer."""

    def __init__(self):
        self.calls = []

    def __call__(self, ms, fn, *args):
        self.calls.append((fn, args))


@pytest.fixture
def later(monkeypatch):
    rec = Later()
    monkeypatch.setattr(ghviewer.wx, "CallLater", rec)
    return rec


def _frame(view, target, items, token=1):
    frame = SimpleNamespace(
        view_mode=view, _pending_target=(token, *target) if target else None,
        _shown=list(items), _announce=lambda m: None, _tell=lambda *a: None,
        _goto_issue=lambda n: None,
        _goto_commit=lambda sha: None,
    )
    frame._if_still_current = "if_still_current"
    frame._row_of = lambda it: Frame._row_of(frame, it)
    frame._describe_landing = Frame._describe_landing
    frame._say_landing = lambda m, final=True: Frame._say_landing(frame, m, final)
    return frame


ISSUES = [Item(n, f"T{n}", "open", f"u{n}", False) for n in (5, 4, 3)]


def test_lands_on_the_issue(later):
    f = _frame(ghviewer.VIEW_ISSUES, (ghviewer.VIEW_ISSUES, "item", "4"), ISSUES)
    assert Frame._take_pending_row(f, ISSUES, 1) == 1
    assert f._pending_target is None
    # Said, queued after the row: a big repository loads for seconds, and
    # the status bar alone left you hearing just a list.
    fn, args = later.calls[-1]
    assert fn == f._say_landing and args == ("Opened #4 — T4",)


@pytest.mark.parametrize("kind, ref, said", [
    ("item", "14845", "#14845"),
    ("commit", "abcdef0123456", "commit abcdef0"),
    ("release", "v1.2", "release v1.2"),
    ("run", "42", "run 42"),
])
def test_opening_label(kind, ref, said):
    assert ghviewer.opening_label(kind, ref) == said


def _address_frame():
    calls = []
    f = SimpleNamespace(_hidden_repos=[], _tell="tell", calls=calls)
    f._select_repo = lambda repo, view=None: calls.append(("select", repo, view))
    f._set_pending_target = lambda *a: calls.append(("pending",) + a)
    f._select_in_repo_list = lambda repo: calls.append(("list", repo))
    return f


def test_opening_an_item_address_says_what_is_coming(later):
    f = _address_frame()
    Frame._open_address(f, "https://github.com/cli/cli/pull/14845")
    assert f.calls == [("select", "cli/cli", ghviewer.VIEW_ISSUES),
                       ("pending", ghviewer.VIEW_ISSUES, "item", "14845"),
                       ("list", "cli/cli")]
    # Said a moment later, after the dialog's focus has gone back, which
    # would otherwise cut it off; and the landing will be said too.
    assert later.calls == [("tell", ("Opening #14845 in cli/cli…",))]
    assert f._speak_landing is True


def test_a_branch_address_has_nothing_to_land_on(later):
    f = _address_frame()
    Frame._open_address(f, "https://github.com/cli/cli/tree/trunk")
    assert later.calls == [] and not getattr(f, "_speak_landing", False)


def _landing_frame(speak):
    f = SimpleNamespace(_speak_landing=speak, announced=[], told=[])
    f._announce = f.announced.append
    f._tell = lambda m, cat=None: f.told.append((m, cat))
    return f


def test_a_landing_from_an_address_is_said_once():
    f = _landing_frame(True)
    Frame._say_landing(f, "#5 not in current list, fetching…", final=False)
    Frame._say_landing(f, "Jumped to #5 — T")
    Frame._say_landing(f, "Something later")
    assert f.told == [("#5 not in current list, fetching…", ghviewer.announce.STATUS),
                      ("Jumped to #5 — T", ghviewer.announce.STATUS)]
    assert f.announced == ["Something later"]


def test_any_other_landing_stays_in_the_status_bar():
    # Backspace back to a list, a new issue, Go To: the row focus says it.
    f = _landing_frame(False)
    Frame._say_landing(f, "Opened #12 — T")
    assert f.told == [] and f.announced == ["Opened #12 — T"]


def test_a_new_load_forgets_the_landing():
    f = SimpleNamespace(_fetch_token=1, _speak_landing=True)
    Frame._begin_fetch(f)
    assert f._speak_landing is False


def test_a_failed_load_after_opening_says_why():
    f = _landing_frame(True)
    f._fetch_is_current = lambda t: True
    f.view_mode = ghviewer.VIEW_ISSUES
    f._pending_target = (1, ghviewer.VIEW_ISSUES, "item", "5")
    f._on_items_error = lambda msg: f.announced.append(f"Error: {msg}")
    f._say_landing = lambda m, final=True: Frame._say_landing(f, m, final)
    Frame._on_fetch_error(f, 1, "Could not resolve to a Repository")
    assert f.told == [("Error: Could not resolve to a Repository", ghviewer.announce.STATUS)]
    assert f._pending_target is None


def test_missing_issue_is_fetched_by_number(later):
    f = _frame(ghviewer.VIEW_ISSUES, (ghviewer.VIEW_ISSUES, "item", "99"), ISSUES)
    assert Frame._take_pending_row(f, ISSUES, 1) == 0
    assert ("if_still_current", (1, f._goto_issue, 99)) in later.calls


def test_issue_hidden_by_the_filter_is_fetched_by_number(later):
    # Go To drops the filter, so it is the way to reach a filtered-out item
    f = _frame(ghviewer.VIEW_ISSUES, (ghviewer.VIEW_ISSUES, "item", "4"), ISSUES)
    f._shown = [ISSUES[0]]
    assert Frame._take_pending_row(f, ISSUES, 1) == 0
    assert ("if_still_current", (1, f._goto_issue, 4)) in later.calls


def test_a_target_only_lands_on_its_own_load(later):
    # The load it was set for was superseded (the user switched view, or
    # the load failed and they came back later): it must not fire now.
    f = _frame(ghviewer.VIEW_ISSUES, (ghviewer.VIEW_ISSUES, "item", "4"), ISSUES, token=1)
    assert Frame._take_pending_row(f, ISSUES, 2) == 0
    assert f._pending_target is None
    assert later.calls == []


def test_a_target_for_another_view_is_dropped(later):
    f = _frame(ghviewer.VIEW_ISSUES, (ghviewer.VIEW_RELEASES, "release", "v1"), ISSUES)
    assert Frame._take_pending_row(f, ISSUES, 1) == 0
    assert f._pending_target is None


def test_set_pending_target_takes_the_current_token():
    f = SimpleNamespace(_fetch_token=5, _pending_target=None)
    Frame._set_pending_target(f, ghviewer.VIEW_ISSUES, "item", "3")
    assert f._pending_target == (5, ghviewer.VIEW_ISSUES, "item", "3")


def test_commit_matches_an_abbreviated_sha(later):
    commits = [Commit("a" * 40, "aaaaaaa", "m", "me", ""), Commit("b" * 40, "bbbbbbb", "m", "me", "")]
    f = _frame(ghviewer.VIEW_COMMITS, (ghviewer.VIEW_COMMITS, "commit", "BBBBBBB"), commits)
    assert Frame._take_pending_row(f, commits, 1) == 1


def test_missing_commit_is_fetched(later):
    commits = [Commit("a" * 40, "aaaaaaa", "m", "me", "")]
    f = _frame(ghviewer.VIEW_COMMITS, (ghviewer.VIEW_COMMITS, "commit", "c0ffee"), commits)
    assert Frame._take_pending_row(f, commits, 1) == 0
    assert ("if_still_current", (1, f._goto_commit, "c0ffee")) in later.calls


def test_release_and_run(later):
    rels = [Release("v2", "", False, False, ""), Release("v1", "", False, False, "")]
    f = _frame(ghviewer.VIEW_RELEASES, (ghviewer.VIEW_RELEASES, "release", "v1"), rels)
    assert Frame._take_pending_row(f, rels, 1) == 1
    runs = [WorkflowRun("CI", "", "", "", "", "", run_id=7), WorkflowRun("CI", "", "", "", "", "", run_id=8)]
    f = _frame(ghviewer.VIEW_WORKFLOW, (ghviewer.VIEW_WORKFLOW, "run", "8"), runs)
    assert Frame._take_pending_row(f, runs, 1) == 1


def test_missing_release_in_an_empty_list_says_so(later):
    said = []
    f = _frame(ghviewer.VIEW_RELEASES, (ghviewer.VIEW_RELEASES, "release", "v9"), [])
    f._announce = said.append
    Frame._take_pending_row(f, [], 1)
    fn, args = later.calls[0]
    assert "no releases" in args[0]


def test_no_target_lands_on_the_first_row(later):
    f = _frame(ghviewer.VIEW_ISSUES, None, ISSUES)
    assert Frame._take_pending_row(f, ISSUES, 1) == 0
    assert later.calls == []


# ── A fetched commit, and the list it was for ─────────────────────────


def _commit_frame():
    f = SimpleNamespace(
        view_mode=ghviewer.VIEW_COMMITS, repo="o/r", _fetch_token=3, filter_text="x",
        git_items=[Commit("a" * 40, "aaaaaaa", "m", "me", "")], announced=[], focused=[],
    )
    f._announce = f.announced.append
    f._populate_filtered_list = lambda items, use_favorite_prefix=False: list(items)
    f._focus_list = lambda row=0: f.focused.append(row)
    f._say_landing = lambda m, final=True: Frame._say_landing(f, m, final)
    return f


def test_fetched_commit_goes_first_and_clears_the_filter():
    f = _commit_frame()
    far = Commit("c" * 40, "ccccccc", "Far\n\nbody", "me", "")
    Frame._on_commit_fetched(f, far, "o/r", 3)
    assert f.git_items[0] is far and f.filter_text == ""
    assert f.focused == [0]


@pytest.mark.parametrize("change", ["repo", "view", "token"])
def test_fetched_commit_for_a_list_since_left_is_dropped(change):
    f = _commit_frame()
    if change == "repo":
        f.repo = "o/other"
    elif change == "view":
        f.view_mode = ghviewer.VIEW_BRANCHES
    else:
        f._fetch_token = 4   # refreshed, or another branch chosen, meanwhile
    before = list(f.git_items)
    Frame._on_commit_fetched(f, Commit("c" * 40, "ccccccc", "m", "me", ""), "o/r", 3)
    assert f.git_items == before and f.focused == []


def test_a_commit_row_reads_only_the_first_line():
    c = Commit("c" * 40, "ccccccc", "Subject\n\nLong body", "me", "")
    assert c.to_row(["message"])["message"] == "Subject"


# ── The clipboard offer ─────────────────────────────────────────────────


@pytest.mark.parametrize("text, url", [
    ("https://github.com/o/r/issues/1", "https://github.com/o/r/issues/1"),
    ("See https://github.com/o/r/issues/1 for details.", "https://github.com/o/r/issues/1"),
    ("first line\n<https://github.com/o/r/pull/2>.", "https://github.com/o/r/pull/2"),
    ("https://github.com/settings then https://github.com/o/r", "https://github.com/o/r"),
    ("nothing here", ""),
    ("https://gist.github.com/a/b", ""),
])
def test_first_github_url(text, url):
    assert ghviewer.first_github_url(text) == url


def test_a_scheduled_fallback_runs_only_for_the_list_it_was_for():
    ran = []
    f = SimpleNamespace(_fetch_token=2)
    f._fetch_is_current = lambda t: t == f._fetch_token
    Frame._if_still_current(f, 1, ran.append, "stale")
    Frame._if_still_current(f, 2, ran.append, "current")
    assert ran == ["current"]
