"""The window's text-building logic, exercised without opening a window.

The details panel, comment navigation and favorites are methods on the frame,
but they only touch a few attributes. Each test calls the method on a small
stand-in object carrying just those, so no wx.App or display is needed — only
an importable wx.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

if os.environ.get("CI"):
    import wx  # noqa: F401  — in CI a missing wx must fail, not quietly skip 60 tests
else:
    pytest.importorskip("wx")

import ghviewer  # noqa: E402
from favorites import FavoriteEntry  # noqa: E402
from gh_data import (  # noqa: E402
    Artifact, Branch, Commit, Item, Label, OrgEntry, PagesBuild, PagesFile, PagesSite,
    Release, ReleaseAsset, Tag, Workflow, WorkflowRun,
)

Frame = ghviewer.GhViewerFrame
URL = "https://github.com/o/r/thing"


class FakeText:
    """Just enough of the details wx.TextCtrl."""

    def __init__(self) -> None:
        self.value = ""
        self.selection = None

    def SetValue(self, v): self.value = v
    def GetValue(self): return self.value
    def Clear(self): self.value = ""
    def SetFocus(self): pass
    def SetSelection(self, a, b): self.selection = (a, b)
    def ShowPosition(self, p): pass

    @property
    def lines(self) -> list[str]:
        return self.value.split("\n")

    def selected(self) -> str:
        a, b = self.selection
        return self.value[a:b]


def _frame(**attrs):
    announced: list[str] = []
    frame = SimpleNamespace(
        details_text=FakeText(), items=[], git_items=[], favorites=[],
        commit_branch="", pages_site=None, repo="o/r",
        _comment_positions=[], _current_comment=-1,
        _announce=announced.append, announced=announced,
    )
    frame._line_to_position = lambda line: Frame._line_to_position(frame, line)
    frame._open_repo_from_list = lambda repo, item: Frame._open_repo_from_list(frame, repo, item)
    frame._VIEW_LABELS = Frame._VIEW_LABELS
    frame._view_source = lambda: Frame._view_source(frame)
    frame._orgs, frame._org, frame._show_shared = [], "", False
    for name in ("_view_label", "_view_entry", "_category_entries"):
        setattr(frame, name, getattr(Frame, name).__get__(frame))
    for k, v in attrs.items():
        setattr(frame, k, v)
    return frame


SITE = PagesSite(url="https://o.github.io/r/", source_branch="main")

GIT_ITEMS = [
    Branch("main", "abc", "msg", "me", "2026-01-01", url=URL),
    Commit("c" * 40, "cccccccc", "msg", "me", "2026-01-01", url=URL),
    Tag("v1", "abc", url=URL),
    Label("bug", url=URL),
    Release("v1", "One", False, False, "2026-01-01", url=URL),
    Workflow(1, "CI", ".github/workflows/ci.yml", "active", url=URL),
    WorkflowRun("CI", "completed", "success", "main", "push", "2026-01-01", url=URL),
    ReleaseAsset(1, "a.exe", 100, 5, "2026-01-01", url=URL),
    PagesFile("index.md", URL),
]


def _address_after(lines: list[str], label: str) -> str:
    i = lines.index(label)
    return lines[i + 1]


# ── Addresses sit on their own line ────────────────────────────────────


@pytest.mark.parametrize("item", GIT_ITEMS, ids=lambda i: type(i).__name__)
def test_git_details_put_url_on_its_own_line(item):
    f = _frame(git_items=[item], pages_site=SITE)
    Frame._show_git_details(f, 0)
    lines = f.details_text.lines
    assert _address_after(lines, "URL:") == URL
    # The label is never followed by the address on the same line
    assert not any(l.startswith("URL: ") for l in lines)


def test_pages_build_shows_site_address_on_its_own_line():
    f = _frame(git_items=[PagesBuild(1, "built", "abc", "me", "2026-01-01")], pages_site=SITE)
    Frame._show_git_details(f, 0)
    assert _address_after(f.details_text.lines, "Site:") == SITE.url


def test_issue_details_url_on_its_own_line():
    f = _frame(items=[Item(1, "t", "open", URL, is_pr=True)])
    Frame._show_issue_details(f, 0)
    assert _address_after(f.details_text.lines, "URL:") == URL


@pytest.mark.parametrize("item", [Tag("v1", "abc"), Item(1, "t", "open", "", is_pr=False)],
                         ids=["tag", "issue"])
def test_missing_address_reads_none(item):
    if isinstance(item, Item):
        f = _frame(items=[item])
        Frame._show_issue_details(f, 0)
    else:
        f = _frame(git_items=[item])
        Frame._show_git_details(f, 0)
    assert _address_after(f.details_text.lines, "URL:") == "(none)"


def test_artifact_has_no_address_line():
    f = _frame(git_items=[Artifact(1, "dist", 10, False, "2026-01-01")])
    Frame._show_git_details(f, 0)
    assert "URL:" not in f.details_text.lines


@pytest.mark.parametrize("show, attr", [
    (Frame._show_git_details, "git_items"),
    (Frame._show_issue_details, "items"),
    (Frame._show_favorite_details, "favorites"),
])
@pytest.mark.parametrize("idx", [-1, 0, 5])
def test_out_of_range_clears_details(show, attr, idx):
    f = _frame()
    f.details_text.value = "stale"
    show(f, idx)
    assert f.details_text.value == ""


# ── Favorites ──────────────────────────────────────────────────────────


def test_favorite_details():
    fav = FavoriteEntry("o/r", "issue", URL, "#1 — Bug", subtitle="OPEN", added_at="2026-01-02T03:04:05")
    f = _frame(favorites=[fav])
    Frame._show_favorite_details(f, 0)
    lines = f.details_text.lines
    assert lines[0] == "★ #1 — Bug"
    assert "Detail: OPEN" in lines and "Favorited: 2026-01-02" in lines
    assert _address_after(lines, "URL:") == URL


def test_favorited_page_does_not_repeat_its_address():
    fav = FavoriteEntry("o/r", "page", URL, "index.md", subtitle=URL)
    f = _frame(favorites=[fav])
    Frame._show_favorite_details(f, 0)
    assert f.details_text.value.count(URL) == 1


@pytest.mark.parametrize("item, item_type, title", [
    (Item(4, "Bug", "open", URL, is_pr=False), "issue", "#4 — Bug"),
    (Item(5, "Fix", "open", URL, is_pr=True), "PR", "#5 — Fix"),
    (GIT_ITEMS[0], "branch", "main"),
    (GIT_ITEMS[1], "commit", "cccccccc"),
    (GIT_ITEMS[2], "tag", "v1"),
    (GIT_ITEMS[3], "label", "bug"),
    (GIT_ITEMS[4], "release", "v1"),
    (GIT_ITEMS[5], "workflow", "CI"),
    (GIT_ITEMS[6], "workflow run", "#0 CI"),
    (GIT_ITEMS[8], "page", "index.md"),
])
def test_build_favorite_entry(item, item_type, title):
    entry = Frame._build_favorite_entry(_frame(), item)
    assert (entry.repo, entry.item_type, entry.title, entry.url) == ("o/r", item_type, title, URL)
    assert entry.added_at


def test_unfavoritable_item_is_none():
    assert Frame._build_favorite_entry(_frame(), GIT_ITEMS[7]) is None   # a release asset


# ── Comment navigation ─────────────────────────────────────────────────


def _issue_with_comments(body: str) -> Item:
    return Item(1, "t", "open", URL, is_pr=False, body=body, comment_list=[
        {"author": "ann", "created_at": "2026-01-01T00:00:00Z", "body": "first\nsecond line"},
        {"author": "ben", "created_at": "", "body": "only line"},
    ])


@pytest.mark.parametrize("body", [
    "",
    "one line",
    "para one\n\npara two\nmore",
    "windows\r\nline endings\r\n",
])
def test_comment_navigation_selects_each_comment(body):
    f = _frame(items=[_issue_with_comments(body)])
    Frame._show_issue_details(f, 0)

    Frame._navigate_comment(f, 1)
    assert f.details_text.selected() == (
        "  Comment 1 of 2 — ann (2026-01-01):\n    first\n    second line\n")
    assert f.announced[-1] == "Comment 1 of 2"

    Frame._navigate_comment(f, 1)
    assert f.details_text.selected() == "  Comment 2 of 2 — ben ():\n    only line"

    Frame._navigate_comment(f, 1)
    assert f.announced[-1] == "Already at last comment."
    Frame._navigate_comment(f, -1)
    assert f.details_text.selected().startswith("  Comment 1 of 2")
    Frame._navigate_comment(f, -1)
    assert f.announced[-1] == "Already at first comment."


def test_no_comments_to_navigate():
    f = _frame(items=[Item(1, "t", "open", URL, is_pr=False)])
    Frame._show_issue_details(f, 0)
    Frame._navigate_comment(f, 1)
    assert f.announced == ["No comments to navigate."]


def test_line_to_position():
    f = _frame()
    f.details_text.value = "ab\ncde\n\nf"
    assert [Frame._line_to_position(f, n) for n in range(5)] == [0, 3, 7, 8, 9]


# ── Repo spec parsing ──────────────────────────────────────────────────


@pytest.mark.parametrize("text, repo", [
    ("owner/name", "owner/name"),
    ("  owner/name  ", "owner/name"),
    ("https://github.com/owner/name", "owner/name"),
    ("https://github.com/owner/name.git", "owner/name"),
    ("https://github.com/owner/name/", "owner/name"),
    ("https://github.com/owner/name/issues/12", "owner/name"),
    ("https://github.com/owner/name?tab=readme", "owner/name"),
    ("https://github.com/owner/name#readme", "owner/name"),
    ("git@github.com:owner/name.git", "owner/name"),
    ("github.com/Community-Access/quill", "Community-Access/quill"),
])
def test_parse_repo_spec(text, repo):
    assert ghviewer._parse_repo_spec(text) == repo


@pytest.mark.parametrize("text", ["", "   ", "owner", "owner/", "/name", "https://github.com/owner"])
def test_parse_repo_spec_rejects(text):
    assert ghviewer._parse_repo_spec(text) is None


# ── Go to Number for an item not in the list ───────────────────────────


@pytest.fixture
def inline_worker(monkeypatch):
    """Run the background fetch inline and deliver CallAfter at once."""
    class InlineThread:
        def __init__(self, target, daemon=None): self.target = target
        def start(self): self.target()

    boxes: list[str] = []
    monkeypatch.setattr(ghviewer.threading, "Thread", InlineThread)
    monkeypatch.setattr(ghviewer.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    monkeypatch.setattr(ghviewer.wx, "MessageBox", lambda msg, *a, **k: boxes.append(msg))
    return boxes


def _goto_frame():
    f = _frame(view_mode=ghviewer.VIEW_ISSUES)
    f._say_landing = lambda m, final=True: Frame._say_landing(f, m, final)
    f._goto_error = lambda n, m: Frame._goto_error(f, n, m)
    f._on_goto_fetched = lambda item, n, repo=None: Frame._on_goto_fetched(f, item, n, repo)
    return f


@pytest.mark.parametrize("error, spoken", [
    (ghviewer.GhError("HTTP 401: Bad credentials"), "Error fetching #5: HTTP 401: Bad credentials"),
    (KeyError("number"), "Error fetching #5: Unexpected error (KeyError: 'number')"),
])
def test_goto_fetch_failure_is_reported(monkeypatch, inline_worker, error, spoken):
    def fail(number, repo):
        raise error

    monkeypatch.setattr(ghviewer, "fetch_item_by_number", fail)
    f = _goto_frame()
    Frame._goto_issue(f, 5)
    assert f.announced == ["#5 not in current list, fetching…", spoken]
    assert len(inline_worker) == 1 and inline_worker[0].startswith("Could not fetch #5:")


def test_goto_missing_number_says_not_found(monkeypatch, inline_worker):
    monkeypatch.setattr(ghviewer, "fetch_item_by_number", lambda n, r: None)
    f = _goto_frame()
    Frame._goto_issue(f, 9999)
    assert f.announced[-1] == "#9999 not found in o/r."
    assert "does not exist" in inline_worker[0]


# ── The repository list: categories first, then repositories ──────────


class FakeListBox:
    """Just enough of the repo wx.ListBox."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, object]] = []
        self.selection = -1
        self.focused = 0

    def Clear(self):
        self.rows = []
        self.selection = -1

    def Append(self, label, clientData=None): self.rows.append((label, clientData))
    def GetCount(self): return len(self.rows)
    def GetClientData(self, i): return self.rows[i][1]
    def SetSelection(self, i): self.selection = i
    def GetSelection(self): return self.selection
    def SetFocus(self): self.focused += 1
    def SetString(self, i, label):
        self.set_strings = getattr(self, "set_strings", 0) + 1
        self.rows[i] = (label, self.rows[i][1])

    def GetString(self, i): return self.rows[i][0]

    @property
    def labels(self) -> list[str]:
        return [label for label, _ in self.rows]


def _repo_frame(pinned=(), repo=None, view=ghviewer.VIEW_ISSUES, focus=None, loaded_once=False):
    f = _frame(
        repo=repo, view_mode=view, repo_list=FakeListBox(),
        _pinned_repos=list(pinned), _hidden_repos=[], _all_repos=[], _repos_known=True, _repos_failed=False,
        _repo_token=0, _repos_loaded_once=loaded_once, _category_counts={},
    )
    for name in ("_restore_repo_selection", "_category_label", "_refresh_category_labels",
                 "_set_repo_list_label", "_current_entry", "_select_repo_row"):
        setattr(f, name, getattr(Frame, name).__get__(f))
    f._current_focus = lambda: focus
    return f


def _row(name, desc=""):
    return {"nameWithOwner": name, "description": desc}


CATEGORIES = ["★ Favorites", "Activity", "Starred Repositories", "Watched Repositories",
              "Notifications", "My Work", "My Organizations", "Gists"]


def test_categories_come_first_then_pinned_then_your_own():
    f = _repo_frame(pinned=["p/pin"])
    Frame._on_repos_loaded(f, [_row("me/a", "Mine"), _row("p/pin", "Pinned one")])
    assert f.repo_list.labels == CATEGORIES + ["📌 p/pin — Pinned one", "me/a — Mine"]
    assert [d for _, d in f.repo_list.rows] == [
        ghviewer.FAVORITES_ENTRY, ghviewer.ACTIVITY_ENTRY, ghviewer.STARRED_ENTRY,
        ghviewer.WATCHED_ENTRY, ghviewer.NOTIFICATIONS_ENTRY, ghviewer.MY_WORK_ENTRY,
        ghviewer.MY_ORGS_ENTRY, ghviewer.GISTS_ENTRY, "p/pin", "me/a"]
    assert f.repo_list.selection == 0
    assert f.announced[-1] == "Loaded 2 repositories. Select one to view issues and PRs."


def test_every_category_entry_has_a_view_and_back():
    for entry, _ in ghviewer.CATEGORY_ENTRIES:
        view = ghviewer.ENTRY_VIEWS[entry]
        assert ghviewer.VIEW_ENTRIES[view] == entry
        assert view in ghviewer.REPOLESS_VIEWS and view in ghviewer.FEED_VIEWS
        assert view in ghviewer.VIEW_COLUMNS and view in Frame._VIEW_LABELS


@pytest.mark.parametrize("entry, view", [
    (ghviewer.ACTIVITY_ENTRY, ghviewer.VIEW_ACTIVITY),
    (ghviewer.STARRED_ENTRY, ghviewer.VIEW_STARRED),
    (ghviewer.WATCHED_ENTRY, ghviewer.VIEW_WATCHED),
])
def test_enter_on_a_category_opens_its_view(entry, view):
    f = _repo_frame()
    f.repo_list.Append("x", entry)
    f.repo_list.SetSelection(0)
    opened = []
    f._select_category = opened.append
    Frame._activate_repo_entry(f)
    assert opened == [view]


def test_a_superseded_repo_load_is_dropped():
    f = _repo_frame()
    f._repo_token = 2
    Frame._on_repos_loaded(f, [_row("me/a")], token=1)
    assert f.repo_list.rows == []


def test_rebuilt_list_keeps_the_current_repo_selected():
    f = _repo_frame(repo="me/b")
    Frame._on_repos_loaded(f, [_row("me/a"), _row("me/b")])
    assert f.repo_list.GetClientData(f.repo_list.selection) == "me/b"


def test_rebuilt_list_keeps_the_row_you_were_on():
    f = _repo_frame()
    Frame._on_repos_loaded(f, [_row("me/a"), _row("me/b")])
    f.repo_list.SetSelection(9)  # me/b, after the eight fixed entries and me/a
    Frame._on_repos_loaded(f, [_row("me/a"), _row("me/b")])
    assert f.repo_list.GetClientData(f.repo_list.selection) == "me/b"


def test_rebuilt_list_selects_nothing_when_the_shown_repo_is_gone():
    # Viewing a pinned repo, then removing it from the list
    f = _repo_frame(repo="p/gone")
    Frame._on_repos_loaded(f, [_row("me/a")])
    assert f.repo_list.selection == ghviewer.wx.NOT_FOUND


@pytest.mark.parametrize("view, row", [
    (ghviewer.VIEW_ACTIVITY, 1), (ghviewer.VIEW_STARRED, 2), (ghviewer.VIEW_WATCHED, 3),
    (ghviewer.VIEW_NOTIFICATIONS, 4), (ghviewer.VIEW_MY_WORK, 5),
])
def test_rebuilt_list_keeps_the_category_selected(view, row):
    f = _repo_frame(view=view, repo="me/a")
    Frame._on_repos_loaded(f, [_row("me/a")])
    assert f.repo_list.selection == row


def test_first_load_takes_focus():
    f = _repo_frame(focus=object())
    Frame._on_repos_loaded(f, [_row("me/a")])
    assert f.repo_list.focused == 1 and f._repos_loaded_once


def test_a_later_load_leaves_focus_alone_while_the_app_is_in_the_background():
    # No focused window: what the app sees after Enter opened the browser
    f = _repo_frame(focus=None, loaded_once=True)
    Frame._on_repos_loaded(f, [_row("me/a")])
    assert f.repo_list.focused == 0


def test_a_later_load_leaves_focus_where_you_are():
    f = _repo_frame(focus=object(), loaded_once=True)
    Frame._on_repos_loaded(f, [_row("me/a")])
    assert f.repo_list.focused == 0


def test_a_later_load_keeps_focus_in_the_repo_list():
    f = _repo_frame(loaded_once=True)
    f._current_focus = lambda: f.repo_list
    Frame._on_repos_loaded(f, [_row("me/a")])
    assert f.repo_list.focused == 1


@pytest.mark.parametrize("name, spoken", [
    (ghviewer.ACTIVITY_ENTRY, "That entry is always in the list."),
    (ghviewer.STARRED_ENTRY, "That entry is always in the list."),
    (ghviewer.FAVORITES_ENTRY, "That entry is always in the list."),
])
def test_remove_from_list_explains_what_it_cannot_remove(name, spoken):
    f = _repo_frame()
    f._all_repos = [_row("me/a")]
    f.repo_list.Append("row", name)
    f.repo_list.SetSelection(0)
    Frame.on_remove_repo(f, None)
    assert f.announced[-1].startswith(spoken)


def _remove(f, name):
    f._refresh_repo_list = lambda: Frame._on_repos_loaded(f, f._all_repos)
    f.repo_list.Clear()
    Frame._on_repos_loaded(f, f._all_repos)
    f.repo_list.SetSelection([d for _, d in f.repo_list.rows].index(name))
    Frame.on_remove_repo(f, None)


def test_removing_one_of_your_own_hides_it_and_says_how_to_get_it_back():
    # #2: it used to say it couldn't be removed, and only on the status bar.
    import pinned_repos
    f = _repo_frame()
    f._all_repos = [_row("me/a"), _row("me/b")]
    _remove(f, "me/a")
    assert "me/a" not in [d for _, d in f.repo_list.rows]
    assert "me/b" in [d for _, d in f.repo_list.rows]
    assert f._hidden_repos == ["me/a"] == pinned_repos.load_hidden()
    assert f.announced[-1] == ("Removed me/a from the list. "
                               "File, Hidden Repositories brings it back.")


def test_a_hidden_repo_stays_out_of_later_loads_and_is_counted():
    f = _repo_frame()
    f._hidden_repos = ["ME/A"]  # case doesn't matter
    Frame._on_repos_loaded(f, [_row("me/a"), _row("me/b")])
    assert "me/a" not in [d for _, d in f.repo_list.rows]
    assert f.announced[-1].startswith("Loaded 1 repositories (1 hidden).")


def test_removing_a_pinned_repo_that_is_also_yours_takes_it_out_entirely():
    # Unpinning alone left it in the list, under your own repos.
    f = _repo_frame(pinned=["me/a"])
    f._all_repos = [_row("me/a")]
    _remove(f, "me/a")
    assert "me/a" not in [d for _, d in f.repo_list.rows]
    assert f._pinned_repos == [] and f._hidden_repos == ["me/a"]


def test_removing_a_pinned_repo_from_elsewhere_just_unpins_it():
    f = _repo_frame(pinned=["o/other"])
    f._all_repos = [_row("me/a")]
    _remove(f, "o/other")
    assert "o/other" not in [d for _, d in f.repo_list.rows]
    assert f._hidden_repos == []
    assert f.announced[-1] == "Removed o/other from the list."


def test_delete_in_the_repo_list_removes():
    f = _repo_frame()
    removed = []
    f.on_remove_repo = removed.append
    f._modifiers_down = lambda e: False
    event = SimpleNamespace(GetKeyCode=lambda: ghviewer.wx.WXK_DELETE, Skip=lambda: None)
    Frame.on_repo_key_down(f, event)
    assert removed == [None]


def test_hidden_repositories_with_none_hidden_says_so():
    f = _repo_frame()
    Frame.on_hidden_repos(f, None)
    assert f.announced[-1] == "No repositories are hidden."


def test_unhiding_puts_it_back(monkeypatch):
    import pinned_repos
    f = _repo_frame()
    f._all_repos = [_row("me/a"), _row("me/b")]
    _remove(f, "me/a")
    _remove(f, "me/b")
    f._unhide = lambda names: Frame._unhide(f, names)

    class Dlg:
        """Show Again on me/a, then Close."""
        def __init__(self, parent, names, show_again):
            assert names == ["me/a", "me/b"]
            self.show_again = show_again
        def ShowModal(self):
            self.show_again("me/a")
            return ghviewer.wx.ID_CANCEL
        def Destroy(self): pass
    monkeypatch.setattr(ghviewer, "HiddenReposDialog", Dlg)
    Frame.on_hidden_repos(f, None)
    assert "me/a" in [d for _, d in f.repo_list.rows]
    assert "me/b" not in [d for _, d in f.repo_list.rows]
    assert pinned_repos.load_hidden() == ["me/b"]
    assert f.announced[-1] == "Showing 1 repository again."


def test_closing_hidden_repositories_without_choosing_says_nothing(monkeypatch):
    f = _repo_frame()
    f._hidden_repos = ["me/a"]

    class Dlg:
        def __init__(self, *a): pass
        def ShowModal(self): return ghviewer.wx.ID_CANCEL
        def Destroy(self): pass
    monkeypatch.setattr(ghviewer, "HiddenReposDialog", Dlg)
    before = list(f.announced)
    Frame.on_hidden_repos(f, None)
    assert f.announced == before and f._hidden_repos == ["me/a"]


def test_after_a_removal_you_are_on_the_row_that_took_its_place():
    # Review of #2: the rebuild used to leave nothing selected, or jump to
    # the repository open on the right.
    f = _repo_frame(repo="me/c")
    f._all_repos = [_row("me/a"), _row("me/b"), _row("me/c")]
    _remove(f, "me/b")
    assert f.repo_list.GetClientData(f.repo_list.GetSelection()) == "me/c"
    _remove(f, "me/c")   # the last one: you land on the new last
    assert f.repo_list.GetClientData(f.repo_list.GetSelection()) == "me/a"


def test_removing_waits_for_the_list_to_load():
    f = _repo_frame(pinned=["me/a"])
    f._repos_known = False
    f._all_repos = []
    f._refresh_repo_list = lambda: None
    Frame._on_repos_loaded(f, [])
    f.repo_list.SetSelection([d for _, d in f.repo_list.rows].index("me/a"))
    Frame.on_remove_repo(f, None)
    assert f._pinned_repos == ["me/a"]
    assert f.announced[-1].startswith("The repository list is still loading.")


def test_removing_after_the_list_failed_to_load_says_so():
    f = _repo_frame(pinned=["me/a"])
    f._repos_known = False
    f._refresh_repo_list = lambda: None
    Frame._on_repos_error(f, "boom")
    Frame._on_repos_loaded(f, [])
    f.repo_list.SetSelection([d for _, d in f.repo_list.rows].index("me/a"))
    reloads = []
    f._load_repos = lambda: reloads.append(1)
    Frame.on_remove_repo(f, None)
    assert f._pinned_repos == ["me/a"] and reloads == [1]
    assert "couldn't be loaded" in f.announced[-1]


def test_a_pin_in_other_case_is_one_row_and_one_removal():
    f = _repo_frame(pinned=["Me/A"])
    f._all_repos = [_row("me/a")]
    Frame._on_repos_loaded(f, f._all_repos)
    assert [d for _, d in f.repo_list.rows].count("Me/A") == 1
    assert "me/a" not in [d for _, d in f.repo_list.rows]
    _remove(f, "Me/A")
    assert not any(isinstance(d, str) and d.lower() == "me/a" for _, d in f.repo_list.rows)
    assert f._pinned_repos == [] and f._hidden_repos == ["Me/A"]


@pytest.mark.parametrize("answer, removed", [(ghviewer.wx.YES, True), (ghviewer.wx.NO, False)])
def test_removing_a_saved_search_asks_first(monkeypatch, answer, removed):
    import saved_searches
    saved_searches.add_saved_search(
        saved_searches.SavedSearch("Bugs", "is:open label:bug"))
    f = _repo_frame()
    f.saved_searches = saved_searches.load_saved_searches()
    asked = []
    monkeypatch.setattr(ghviewer.wx, "MessageBox", lambda *a: asked.append(a[0]) or answer)
    _remove(f, ghviewer.SEARCH_ENTRY_PREFIX + "Bugs")
    assert asked and "can't be brought back" in asked[0]
    assert (saved_searches.load_saved_searches() == []) == removed


def test_opening_a_hidden_repo_by_address_brings_it_back():
    import pinned_repos
    pinned_repos.hide_repo("me/a")
    f = _repo_frame()
    f._hidden_repos = ["me/a"]
    f._all_repos = [_row("me/a")]
    f._refresh_repo_list = lambda: Frame._on_repos_loaded(f, f._all_repos)
    f._select_repo = lambda repo, view=None: None
    Frame._open_address(f, "https://github.com/ME/A")
    assert pinned_repos.load_hidden() == [] and f._hidden_repos == []
    assert any(d.lower() == "me/a" for _, d in f.repo_list.rows if isinstance(d, str))


def test_user_guide_opens_in_the_browser(monkeypatch):
    opened = []
    monkeypatch.setattr(ghviewer.webbrowser, "open", lambda url: opened.append(url) or True)
    f = _frame()
    Frame.on_user_guide(f, None)
    assert opened == ["https://theideaplace.github.io/GHManage/"]
    assert f.announced[-1] == "Opened the user guide in your browser."


def test_user_guide_without_a_browser_says_where_it_is(monkeypatch):
    monkeypatch.setattr(ghviewer.webbrowser, "open", lambda url: False)
    f = _frame()
    Frame.on_user_guide(f, None)
    assert f.announced[-1].endswith("https://theideaplace.github.io/GHManage/")


class StrictListBox(FakeListBox):
    """Asserts on a bad index, as the real wx.ListBox does."""

    def SetSelection(self, i):
        if i != ghviewer.wx.NOT_FOUND and not 0 <= i < len(self.rows):
            raise AssertionError("invalid index in wxListBox::SetSelection")
        super().SetSelection(i)


@pytest.mark.parametrize("view", [ghviewer.VIEW_FAVORITES, ghviewer.VIEW_ACTIVITY,
                                  ghviewer.VIEW_STARRED])
def test_switching_view_before_the_repo_list_loads(view):
    # Ctrl+9 at startup, or after `gh` failed: the repo list is empty
    f = _repo_frame()
    f.repo_list = StrictListBox()
    f.page_size, f.current_limit, f._return_to = 100, 100, None
    loads = []
    for name in ("_rebuild_columns", "_rebuild_columns_menu", "_update_menu_checks"):
        setattr(f, name, lambda: None)
    f._load_items = lambda: loads.append("items")
    f._load_favorites_view = lambda: loads.append("favorites")
    Frame._switch_view(f, view)
    assert f.view_mode == view and len(loads) == 1


@pytest.mark.parametrize("n, spoken", [(7, "That is all your starred repositories."), (100, None)])
def test_view_more_in_a_repo_list_stops_when_there_is_no_more(n, spoken):
    f = _list_frame()
    f.git_items = f._shown = [STAR] * n
    loads = []
    f._load_items = lambda: loads.append(f.current_limit)
    Frame.on_view_more(f, None)
    if spoken:
        assert loads == [] and f.announced[-1] == spoken
    else:
        assert loads == [200]


def test_f_puts_the_star_on_every_row_about_it(app_data):
    class Rows:
        def __init__(self): self.cells = {}
        def SetItem(self, row, col, text): self.cells[(row, col)] = text
    a, b = _event("o/r", 4), _event("o/r", 4)   # two events about issue #4
    c = ghviewer.ActivityEvent("WatchEvent", "x", "o/r", "starred")
    f = _frame(view_mode=ghviewer.VIEW_ACTIVITY, columns=["actor"], list_mode="quick",
               _shown=[a, b, c], list_ctrl=Rows())
    for name in ("_item_label", "_favorite_prefix", "_redraw_favorite_marks",
                 "_build_favorite_entry"):
        setattr(f, name, getattr(Frame, name).__get__(f))
    f._refresh_repo_list_fav_count = lambda: None
    f._focused_item = lambda: a
    Frame._toggle_favorite(f)
    assert f.list_ctrl.cells == {(0, 0): "★ a", (1, 0): "★ a", (2, 0): "x"}


# ── Starred and Watched repositories ───────────────────────────────────


STAR = ghviewer.RepoEntry(
    "nvaccess/nvda", "NVDA, the free screen reader", url="https://github.com/nvaccess/nvda",
    language="Python", stars=2345, forks=600, open_issues=2500,
    pushed_at="2026-10-04T12:00:00Z")


def test_repo_details():
    f = _frame(git_items=[STAR])
    Frame._show_git_details(f, 0)
    lines = f.details_text.lines
    assert lines[:2] == ["nvaccess/nvda", "NVDA, the free screen reader"]
    assert _address_after(lines, "URL:") == STAR.url
    for line in ("Language: Python", "Stars: 2,345", "Forks: 600",
                 "Open issues and pull requests: 2,500", "Last pushed: 2026-10-04"):
        assert line in lines
    assert lines[-1] == "Press Ctrl+O to open it on GitHub."
    assert not any(line.startswith("Archived") for line in lines)


def test_repo_details_name_its_flags():
    repo = ghviewer.RepoEntry("o/r", archived=True, fork=True, private=True)
    f = _frame(git_items=[repo])
    Frame._show_git_details(f, 0)
    assert {"Archived (read-only)", "A fork", "Private"} <= set(f.details_text.lines)


def test_repo_favorite():
    entry = Frame._build_favorite_entry(_frame(repo=None), STAR)
    assert (entry.repo, entry.item_type, entry.title, entry.subtitle, entry.url) == (
        "nvaccess/nvda", "repository", "nvaccess/nvda", "NVDA, the free screen reader",
        STAR.url)


def _list_frame(view=ghviewer.VIEW_STARRED, limit=100):
    f = _activity_frame(limit)
    f.view_mode = view
    f._category_counts = {}
    f._refresh_category_labels = lambda: None
    f._VIEW_LABELS = Frame._VIEW_LABELS
    f._row_of = lambda item: Frame._row_of(f, item)
    return f


@pytest.mark.parametrize("view, n, limit, message", [
    (ghviewer.VIEW_STARRED, 3, 100, "Starred Repositories — 3 repositories."),
    (ghviewer.VIEW_STARRED, 1, 100, "Starred Repositories — 1 repository."),
    (ghviewer.VIEW_WATCHED, 100, 100, "Watched Repositories — 100 repositories. Ctrl++ loads more."),
    (ghviewer.VIEW_STARRED, 0, 100, "Starred Repositories — you haven't starred any repositories."),
    (ghviewer.VIEW_WATCHED, 0, 100, "Watched Repositories — you aren't watching any repositories."),
])
def test_repo_list_status(call_later, view, n, limit, message):
    f = _list_frame(view, limit)
    Frame._on_repo_list_loaded(f, 1, [STAR] * n)
    msg, keys = f.statuses[-1]
    assert msg == message
    assert "Enter=open here" in keys and "Ctrl+O=open on GitHub" in keys


def test_stale_repo_list_is_dropped():
    f = _list_frame()
    Frame._on_repo_list_loaded(f, 0, [STAR])
    assert f.statuses == [] and f.git_items == []


def test_load_items_fetches_the_list_for_the_view(monkeypatch, inline_worker):
    calls = []
    monkeypatch.setattr(ghviewer, "fetch_starred_repos", lambda limit: calls.append(("s", limit)) or [STAR])
    monkeypatch.setattr(ghviewer, "fetch_watched_repos", lambda limit: calls.append(("w", limit)) or [])
    for view in (ghviewer.VIEW_STARRED, ghviewer.VIEW_WATCHED):
        f, _ = _load_frame(view)
        landed = []
        f._on_repo_list_loaded = lambda *a: landed.append(a)
        f._pending_focus_row = 7
        Frame._load_items(f)
        assert landed[-1][2] == 7   # (token, repos, focus row, count)
    assert calls == [("s", 100), ("w", 100)]


def test_enter_on_a_starred_repo_opens_it_and_remembers_the_way_back():
    f = _repo_frame(view=ghviewer.VIEW_STARRED)
    f.repo_list.Append("nvaccess/nvda", "nvaccess/nvda")
    f.list_ctrl = FakeItemList(0)
    f.git_items, f._activity_more, f.current_limit = [STAR], False, 200
    f._focused_item = lambda: STAR
    opened = []
    f._select_repo = lambda repo, view=ghviewer.VIEW_ISSUES: opened.append(repo)
    f._open_repo_from_list = lambda repo, item: Frame._open_repo_from_list(f, repo, item)
    Frame.on_item_activated(f, None)
    assert opened == ["nvaccess/nvda"] and f.repo_list.selection == 0
    assert f._return_to == (ghviewer.VIEW_STARRED, [STAR], False, STAR, 200)


def test_backspace_returns_to_the_starred_list_on_the_same_repo(call_later):
    other = ghviewer.RepoEntry("o/other")
    f = _list_frame()
    f.view_mode, f.repo, f.repo_list = ghviewer.VIEW_ISSUES, "nvaccess/nvda", FakeListBox()
    f._return_to = (ghviewer.VIEW_STARRED, [other, STAR], False, STAR, 200)
    f._switch_view = lambda mode, load=True: setattr(f, "view_mode", mode)
    f._begin_fetch = lambda: 1
    f._restore_repo_selection = lambda prev: None
    f._on_repo_list_loaded = lambda *a: Frame._on_repo_list_loaded(f, *a)
    Frame._return_to_list(f)
    assert f.view_mode == ghviewer.VIEW_STARRED and f.git_items == [other, STAR]
    assert f.current_limit == 200
    assert call_later[-1][1] == (1,)
    assert f.announced[-1] == "Back to starred repositories"


def test_view_more_in_a_repo_list_lands_on_the_first_new_row():
    f = _list_frame()
    f.git_items = f._shown = [STAR] * 100
    loads = []
    f._load_items = lambda: loads.append(f.current_limit)
    Frame.on_view_more(f, None)
    assert loads == [200] and f._pending_focus_row == 100


@pytest.mark.parametrize("view", [ghviewer.VIEW_STARRED, ghviewer.VIEW_WATCHED])
def test_category_views_keep_the_current_repo(view):
    f = _frame(view_mode=ghviewer.VIEW_ISSUES, repo="o/r")
    f._switch_view = lambda mode: setattr(f, "view_mode", mode)
    Frame._select_category(f, view)
    assert f.view_mode == view and f.repo == "o/r"


# ── Rows and items with a quick filter on ──────────────────────────────


class FakeItemList:
    def __init__(self, selected=-1):
        self.selected = selected

    def GetFirstSelected(self): return self.selected


def _filtered_frame(items, shown, selected):
    f = _frame(view_mode=ghviewer.VIEW_ACTIVITY, git_items=items, _shown=shown,
               list_ctrl=FakeItemList(selected))
    for name in ("_row_item", "_row_of", "_view_source", "_show_git_details",
                 "_show_issue_details", "_show_favorite_details"):
        setattr(f, name, getattr(Frame, name).__get__(f))
    return f


def _event(repo, n=0):
    return ghviewer.ActivityEvent("IssuesEvent", "a", repo, f"opened issue #{n}", title=f"T{n}",
                                  subject_kind="issue", number=n,
                                  subject_url=f"https://github.com/{repo}/issues/{n}",
                                  url=f"https://github.com/{repo}/issues/{n}")


def test_filtered_row_is_the_item_it_shows():
    a, b, c = _event("o/a", 1), _event("o/b", 2), _event("o/c", 3)
    # A filter hides a and b, so c is row 0
    f = _filtered_frame([a, b, c], [c], 0)
    assert Frame._focused_item(f) is c
    Frame._show_details(f, 0)
    assert f.details_text.lines[0].startswith("a opened issue #3 in o/c")


def test_g_with_a_filter_goes_to_the_repo_you_heard():
    a, c = _event("o/a", 1), _event("o/c", 3)
    f = _filtered_frame([a, c], [c], 0)
    f.repo_list = FakeListBox()
    f.git_items = [a, c]
    f._activity_more, f.current_limit = True, 100
    f._focused_item = lambda: Frame._focused_item(f)
    opened = []
    f._select_repo = lambda repo, view=ghviewer.VIEW_ISSUES: opened.append(repo)
    Frame._go_to_event_repo(f)
    assert opened == ["o/c"]


def test_nothing_selected_is_no_item():
    f = _filtered_frame([_event("o/a")], [_event("o/a")], -1)
    assert Frame._focused_item(f) is None


# ── Favorites from the Activity view ───────────────────────────────────


def test_activity_favorite_is_what_the_event_is_about():
    ev = _event("x/proj", 9)
    entry = Frame._build_favorite_entry(_frame(repo=None), ev)
    assert (entry.repo, entry.item_type, entry.title, entry.url) == (
        "x/proj", "issue", "#9 — T9", "https://github.com/x/proj/issues/9")


def test_events_without_a_subject_cannot_be_favorited():
    star = ghviewer.ActivityEvent("WatchEvent", "a", "o/r", "starred", url="https://github.com/o/r")
    f = _frame(view_mode=ghviewer.VIEW_ACTIVITY)
    f._focused_item = lambda: star
    Frame._toggle_favorite(f)
    assert "nothing to favorite" in f.announced[-1]
    assert f.favorites == []


def test_two_events_sharing_an_address_do_not_unfavorite_each_other(app_data):
    # Before: both used the repo address, so F on the second removed the first
    star = ghviewer.ActivityEvent("WatchEvent", "a", "o/r", "starred", url="https://github.com/o/r")
    issue = _event("o/r", 4)
    f = _frame(view_mode=ghviewer.VIEW_ACTIVITY, repo=None)
    f._refresh_repo_list_fav_count = lambda: None
    f._build_favorite_entry = lambda item: Frame._build_favorite_entry(f, item)
    f._redraw_favorite_marks = lambda: None
    f._focused_item = lambda: issue
    Frame._toggle_favorite(f)
    assert [fav.url for fav in f.favorites] == [issue.subject_url]
    f._focused_item = lambda: star
    Frame._toggle_favorite(f)
    assert [fav.url for fav in f.favorites] == [issue.subject_url]


def test_star_prefix_follows_the_subject_not_the_repo():
    fav = FavoriteEntry("o/r", "issue", "https://github.com/o/r/issues/4", "#4")
    f = _frame(favorites=[fav])
    star = ghviewer.ActivityEvent("WatchEvent", "a", "o/r", "starred", url="https://github.com/o/r")
    comment = ghviewer.ActivityEvent(
        "IssueCommentEvent", "a", "o/r", "commented on issue #4",
        url="https://github.com/o/r/issues/4#issuecomment-1",
        subject_kind="issue", number=4, subject_url="https://github.com/o/r/issues/4")
    assert Frame._favorite_prefix(f, comment) == "★ "
    assert Frame._favorite_prefix(f, star) == ""


# ── Activity view ──────────────────────────────────────────────────────


EVENT = ghviewer.ActivityEvent(
    event_type="IssueCommentEvent", actor="alice", repo="x/proj",
    action="commented on issue #9", created_at="2026-10-05T14:32:00Z",
    title="Crash on start", url="https://github.com/x/proj/issues/9#c1",
    body="Same here.\nSecond line.",
)


def test_activity_details_read_as_a_sentence_then_fields():
    f = _frame(git_items=[EVENT])
    Frame._show_git_details(f, 0)
    lines = f.details_text.lines
    assert lines[0] == "alice commented on issue #9 in x/proj: Crash on start"
    assert "About: Crash on start" in lines and "Repository: x/proj" in lines
    assert _address_after(lines, "URL:") == EVENT.url
    assert "Same here." in lines and "Second line." in lines
    assert lines[-1] == "Press G to open x/proj here in GHManage."


def test_activity_details_without_title_or_body():
    ev = ghviewer.ActivityEvent("WatchEvent", "bob", "x/p", "starred", url="https://github.com/x/p")
    f = _frame(git_items=[ev])
    Frame._show_git_details(f, 0)
    lines = f.details_text.lines
    assert lines[0] == "bob starred x/p"
    assert not any(line.startswith("About:") for line in lines)


def _activity_frame(limit=100):
    f = _frame(
        view_mode=ghviewer.VIEW_ACTIVITY, repo=None, current_limit=limit,
        page_size=100, _fetch_token=1, filter_text="", _pending_focus_row=0,
        _activity_more=False, _shown=[], _notif_more=False, _include_read=False,
        _search=None,
    )
    f._fetch_is_current = lambda t: t == f._fetch_token
    def populate(items, use_favorite_prefix=False):
        f._shown = list(items)
        return f._shown
    f._populate_filtered_list = populate
    f._focus_list = lambda row=0: None
    f._update_title = lambda: None
    statuses = []
    f._set_view_status = lambda msg, keys="": statuses.append((msg, keys))
    f.statuses = statuses
    return f


@pytest.fixture
def call_later(monkeypatch):
    calls = []
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda ms, fn, *a: calls.append((fn, a)))
    return calls


def test_activity_loaded_status(call_later):
    f = _activity_frame()
    Frame._on_activity_loaded(f, 1, [EVENT] * 100, True)
    msg, keys = f.statuses[-1]
    assert msg == "Activity — 100 events, newest first. Ctrl++ loads older ones."
    assert "G=go to repository" in keys and "Enter=open  " in keys
    assert f._activity_more is True
    assert f.git_items == [EVENT] * 100
    assert call_later[-1][1] == (0,)  # focus on the newest


def test_activity_short_feed_says_that_is_everything(call_later):
    f = _activity_frame()
    Frame._on_activity_loaded(f, 1, [EVENT])
    assert f.statuses[-1][0] == "Activity — 1 event, newest first. That is all GitHub keeps."


def test_empty_activity_explains_where_events_come_from(call_later):
    f = _activity_frame()
    Frame._on_activity_loaded(f, 1, [])
    assert "repositories you star or watch" in f.statuses[-1][0]


def test_stale_activity_results_are_dropped():
    f = _activity_frame()
    Frame._on_activity_loaded(f, 0, [EVENT])
    assert f.statuses == [] and f.git_items == []


def test_view_more_stops_at_what_github_keeps():
    f = _activity_frame(limit=ghviewer.ACTIVITY_MAX)
    f._activity_more = False
    f._load_items = lambda: pytest.fail("should not reload")
    Frame.on_view_more(f, None)
    assert f.announced[-1] == (
        "No older activity. GitHub keeps only your latest 300 events, "
        "from the last 90 days.")


def test_view_more_while_loading_says_so():
    f = _activity_frame()
    f._activity_more = None
    f._load_items = lambda: pytest.fail("should not reload")
    Frame.on_view_more(f, None)
    assert f.announced[-1] == "Activity is still loading."


def test_view_more_lands_on_the_first_older_event(call_later):
    f = _activity_frame()
    f._activity_more = True
    f._shown = [EVENT] * 96
    loads = []
    f._load_items = lambda: loads.append(f.current_limit)
    Frame.on_view_more(f, None)
    assert loads == [200] and f._pending_focus_row == 96
    Frame._on_activity_loaded(f, 1, [EVENT] * 196, True, 96)
    assert call_later[-1][1] == (96,)


def _load_frame(view=ghviewer.VIEW_ACTIVITY):
    """Enough of the frame for _load_items, with the worker run inline."""
    f = _activity_frame()
    f.view_mode = view
    f.repo, f.tab_filter, f.state_filter, f.label_filter = None, "both", "open", ""
    f.list_ctrl = SimpleNamespace(DeleteAllItems=lambda: None)
    f._VIEW_LABELS = Frame._VIEW_LABELS
    f._begin_fetch = lambda: 1
    landed = []
    f._on_activity_loaded = lambda *a: landed.append(a)
    f._on_fetch_error = lambda t, m: Frame._on_fetch_error(f, t, m)
    f._on_items_error = lambda m: f._announce(f"Error: {m}")
    return f, landed


def test_the_focus_row_goes_to_one_load_only(monkeypatch, inline_worker):
    # View More's row is handed to that load and cleared at once, so a load
    # that never lands can't leave it for the next one.
    monkeypatch.setattr(ghviewer, "fetch_activity", lambda limit: ([EVENT], True))
    f, landed = _load_frame()
    f._pending_focus_row = 96
    Frame._load_items(f)
    assert landed[-1][-1] == 96 and f._pending_focus_row == 0
    Frame._load_items(f)
    assert landed[-1][-1] == 0


def test_a_failed_activity_load_does_not_stay_loading(monkeypatch, inline_worker):
    def boom(limit):
        raise ghviewer.GhError("HTTP 401")
    monkeypatch.setattr(ghviewer, "fetch_activity", boom)
    f, _ = _load_frame()
    f._fetch_is_current = lambda t: True
    Frame._load_items(f)
    assert f._activity_more is False
    assert f.announced[-1] == "Error: HTTP 401"


def test_go_to_event_repo_opens_it_and_selects_it_in_the_list():
    f = _repo_frame(view=ghviewer.VIEW_ACTIVITY)
    f.repo_list.Append("x/proj (starred)", "x/proj")
    f.list_ctrl = FakeItemList(4)
    f.git_items, f._activity_more, f.current_limit = [EVENT], True, 200
    f._focused_item = lambda: EVENT
    opened = []
    f._select_repo = lambda repo, view=ghviewer.VIEW_ISSUES: opened.append(repo)
    Frame._go_to_event_repo(f)
    assert opened == ["x/proj"] and f.repo_list.selection == 0
    # Remembered for Backspace: the events, whether there are more, the event
    assert f._return_to == (ghviewer.VIEW_ACTIVITY, [EVENT], True, EVENT, 200)


def test_go_to_a_repo_not_in_the_list_deselects_activity():
    f = _repo_frame(view=ghviewer.VIEW_ACTIVITY)
    f.repo_list.Append("Activity", ghviewer.ACTIVITY_ENTRY)
    f.repo_list.SetSelection(0)
    f.list_ctrl = FakeItemList(0)
    f.git_items, f._activity_more, f.current_limit = [EVENT], False, 100
    f._focused_item = lambda: EVENT
    f._select_repo = lambda r, view=None: None
    Frame._go_to_event_repo(f)
    assert f.repo_list.selection == ghviewer.wx.NOT_FOUND


def test_backspace_returns_to_the_feed_without_fetching(call_later):
    f = _activity_frame()
    f.view_mode = ghviewer.VIEW_ISSUES
    f.repo, f.repo_list = "x/proj", FakeListBox()
    other = ghviewer.ActivityEvent("WatchEvent", "b", "o/r", "starred")
    f._return_to = (ghviewer.VIEW_ACTIVITY, [EVENT, other], True, other, 200)
    switched = []
    f._switch_view = lambda mode, load=True: (switched.append((mode, load)),
                                               setattr(f, "view_mode", mode))
    f._begin_fetch = lambda: 1
    f._restore_repo_selection = lambda prev: None
    f._row_of = lambda item: Frame._row_of(f, item)
    f._on_activity_loaded = lambda *a: Frame._on_activity_loaded(f, *a)
    Frame._return_to_list(f)
    assert switched == [(ghviewer.VIEW_ACTIVITY, False)]
    assert f.git_items == [EVENT, other] and f.current_limit == 200
    assert call_later[-1][1] == (1,)  # back on the event you left
    assert f._return_to is None
    assert f.announced[-1] == "Back to activity"


@pytest.mark.parametrize("mode, repo, loads", [
    (ghviewer.VIEW_ACTIVITY, None, ["items"]),       # needs no repo, and loads
    (ghviewer.VIEW_FAVORITES, None, ["favorites"]),
    (ghviewer.VIEW_BRANCHES, None, []),              # refused: no repo
    (ghviewer.VIEW_BRANCHES, "o/r", ["items"]),
])
def test_switch_view_loads_activity_without_a_repo(mode, repo, loads):
    loaded = []
    f = _frame(view_mode=ghviewer.VIEW_ISSUES, repo=repo, page_size=100, current_limit=100,
               _return_to=None)
    for name in ("_rebuild_columns", "_rebuild_columns_menu", "_update_menu_checks"):
        setattr(f, name, lambda: None)
    f._restore_repo_selection = lambda previous: None
    f._load_items = lambda: loaded.append("items")
    f._load_favorites_view = lambda: loaded.append("favorites")
    Frame._switch_view(f, mode)
    assert loaded == loads


def test_switch_view_without_load():
    f = _frame(view_mode=ghviewer.VIEW_ISSUES, repo="o/r", page_size=100, current_limit=100,
               _return_to=("kept",))
    for name in ("_rebuild_columns", "_rebuild_columns_menu", "_update_menu_checks"):
        setattr(f, name, lambda: None)
    f._restore_repo_selection = lambda previous: None
    f._load_items = lambda: pytest.fail("should not load")
    Frame._switch_view(f, ghviewer.VIEW_ACTIVITY, load=False)
    assert f.view_mode == ghviewer.VIEW_ACTIVITY
    # Leaving the issues list for anything else forgets the way back
    assert f._return_to is None


def test_activity_keeps_the_current_repo():
    # Ctrl+Shift+A for a glance, then Ctrl+1 goes straight back
    f = _frame(view_mode=ghviewer.VIEW_ISSUES, repo="o/r")
    f._switch_view = lambda mode: setattr(f, "view_mode", mode)
    Frame._select_category(f, ghviewer.VIEW_ACTIVITY)
    assert f.view_mode == ghviewer.VIEW_ACTIVITY and f.repo == "o/r"


def test_refresh_in_favorites_reloads_favorites():
    loads = []
    f = _frame(view_mode=ghviewer.VIEW_FAVORITES, repo="o/r")
    f._load_favorites_view = lambda: loads.append("favorites")
    f._load_items = lambda: loads.append("items")
    Frame.on_refresh(f, None)
    assert loads == ["favorites"]


def test_activity_view_is_allowed_without_a_repo():
    assert ghviewer.VIEW_ACTIVITY in ghviewer.REPOLESS_VIEWS
    assert ghviewer.VIEW_ACTIVITY in ghviewer.VIEW_COLUMNS


def test_backspace_after_g_with_a_filter_lands_on_that_event(call_later):
    # G pressed on row 0 of a filtered list showing the third event; the
    # filter is gone on the way back, so row 0 would be the wrong event.
    a, b, c = _event("o/a", 1), _event("o/b", 2), _event("o/c", 3)
    f = _activity_frame()
    f.view_mode, f.repo, f.repo_list = ghviewer.VIEW_ACTIVITY, None, FakeListBox()
    f.git_items, f._shown, f.list_ctrl = [a, b, c], [c], FakeItemList(0)
    f._activity_more, f.filter_text = True, "o/c"
    f._focused_item = lambda: Frame._focused_item(f)
    f._row_item = lambda row: Frame._row_item(f, row)
    f._select_repo = lambda repo, view=ghviewer.VIEW_ISSUES: setattr(f, "view_mode", view)
    Frame._go_to_event_repo(f)

    f._switch_view = lambda mode, load=True: (setattr(f, "view_mode", mode),
                                               setattr(f, "filter_text", ""))
    f._begin_fetch = lambda: 1
    f._restore_repo_selection = lambda prev: None
    f._row_of = lambda item: Frame._row_of(f, item)
    f._on_activity_loaded = lambda *args: Frame._on_activity_loaded(f, *args)
    Frame._return_to_list(f)
    assert call_later[-1][1] == (2,)  # c's row in the unfiltered feed


@pytest.mark.parametrize("view, row", [
    (ghviewer.VIEW_WATCHED, 3), (ghviewer.VIEW_ACTIVITY, 1), (ghviewer.VIEW_ISSUES, 8), (ghviewer.VIEW_GISTS, 7),
    (ghviewer.VIEW_NOTIFICATIONS, 4), (ghviewer.VIEW_MY_WORK, 5),
])
def test_switching_view_moves_the_repo_list_selection_with_it(view, row):
    # Watched from the View menu while Starred was selected in the list
    f = _repo_frame(view=ghviewer.VIEW_STARRED, repo="me/a")
    Frame._on_repos_loaded(f, [_row("me/a")])
    f.repo_list.SetSelection(2)
    f.page_size, f.current_limit, f._return_to = 100, 100, None
    for name in ("_rebuild_columns", "_rebuild_columns_menu", "_update_menu_checks",
                 "_load_items", "_load_favorites_view"):
        setattr(f, name, lambda: None)
    Frame._switch_view(f, view)
    assert f.repo_list.selection == row


class FakeListKey(ghviewer.wx.ListEvent):
    """A real wx.ListEvent — what the list sends on Windows — with a key code.

    Real, so that the handler can only use what a ListEvent really has: it has
    no modifier state, which is exactly what broke every list key once.
    """

    def __init__(self, key):
        super().__init__()
        self.key, self.skipped = key, False

    def GetKeyCode(self): return self.key
    def Skip(self, skip=True): self.skipped = True


class MouseState:
    def __init__(self, modifiers): self.modifiers = modifiers
    def HasAnyModifiers(self): return self.modifiers


def _key_frame(monkeypatch, modifiers):
    monkeypatch.setattr(ghviewer.wx, "GetMouseState", lambda: MouseState(modifiers))
    f = _frame(view_mode=ghviewer.VIEW_ISSUES, label_filter="", _return_to=None)
    f._modifiers_down = Frame._modifiers_down
    acted = []
    for name in ("_do_close", "_do_reopen", "_do_comment", "_toggle_favorite", "_load_items",
                 "_clear_filter"):
        setattr(f, name, lambda name=name: acted.append(name))
    f.on_refresh = lambda event: acted.append("refresh")
    return f, acted


@pytest.mark.parametrize("letter", ["C", "O", "M", "F", "R"])
def test_letter_keys_with_a_modifier_are_left_alone(monkeypatch, letter):
    # Ctrl+C in the issues list is copy; it must not start closing the issue
    f, acted = _key_frame(monkeypatch, modifiers=True)
    key = FakeListKey(ord(letter))
    Frame.on_list_key_down(f, key)
    assert acted == [] and key.skipped


@pytest.mark.parametrize("key, action", [
    (ord("C"), "_do_close"), (ord("O"), "_do_reopen"), (ord("M"), "_do_comment"),
    (ord("F"), "_toggle_favorite"), (ord("R"), "refresh"),
    (ghviewer.wx.WXK_ESCAPE, "_clear_filter"),
])
def test_bare_keys_work_from_a_real_list_event(monkeypatch, key, action):
    # The Windows path: a wx.ListEvent, not a wx.KeyEvent
    f, acted = _key_frame(monkeypatch, modifiers=False)
    Frame.on_list_key_down(f, FakeListKey(key))
    assert acted == [action]


def test_modifiers_from_a_key_event_come_from_the_event():
    # The macOS path: an ordinary wx.KeyEvent knows its own modifiers
    event = ghviewer.wx.KeyEvent(ghviewer.wx.wxEVT_KEY_DOWN)
    event.SetControlDown(True)
    assert Frame._modifiers_down(event) is True
    assert Frame._modifiers_down(ghviewer.wx.KeyEvent(ghviewer.wx.wxEVT_KEY_DOWN)) is False




# ── Counts on the category entries ─────────────────────────────────────


def test_category_entries_show_their_counts_once_known():
    f = _repo_frame()
    Frame._on_repos_loaded(f, [_row("me/a")])
    assert f.repo_list.labels[:8] == CATEGORIES   # not known yet: just the name
    f.repo_list.SetSelection(8)
    Frame._on_category_counts(f, {ghviewer.STARRED_ENTRY: 7, ghviewer.WATCHED_ENTRY: 0,
                                  ghviewer.GISTS_ENTRY: 3})
    assert f.repo_list.labels[:9] == [
        "★ Favorites", "Activity", "Starred Repositories (7)", "Watched Repositories (0)",
        "Notifications", "My Work", "My Organizations", "Gists (3)", "me/a"]
    assert f.repo_list.selection == 8   # updated in place: you stay where you were
    # A rebuild keeps them
    Frame._on_repos_loaded(f, [_row("me/a")])
    assert f.repo_list.labels[2] == "Starred Repositories (7)"


def test_counts_from_a_superseded_load_are_dropped():
    f = _repo_frame()
    Frame._on_repos_loaded(f, [_row("me/a")])
    f._repo_token = 2
    Frame._on_category_counts(f, {ghviewer.STARRED_ENTRY: 7}, 1)
    assert f.repo_list.labels[2] == "Starred Repositories"


def test_load_repos_fetches_the_counts_after_the_list(monkeypatch, inline_worker):
    order = []
    monkeypatch.setattr(ghviewer, "list_repos", lambda limit: order.append("list") or [_row("me/a")])

    def watched():
        raise ghviewer.GhError("HTTP 403")
    monkeypatch.setitem(ghviewer.COUNTED_ENTRIES, ghviewer.STARRED_ENTRY,
                        lambda: order.append("starred") or 7)
    monkeypatch.setitem(ghviewer.COUNTED_ENTRIES, ghviewer.WATCHED_ENTRY, watched)
    monkeypatch.setitem(ghviewer.COUNTED_ENTRIES, ghviewer.NOTIFICATIONS_ENTRY, watched)
    monkeypatch.setitem(ghviewer.COUNTED_ENTRIES, ghviewer.GISTS_ENTRY, watched)
    f = _repo_frame()
    f._on_repos_loaded = lambda *a, **k: (order.append("shown"), Frame._on_repos_loaded(f, *a, **k))
    f._on_category_counts = lambda *a: Frame._on_category_counts(f, *a)
    Frame._load_repos(f)
    assert order[:3] == ["list", "shown", "starred"]
    # A count that failed is left off, not shown as 0
    assert f.repo_list.labels[2:4] == ["Starred Repositories (7)", "Watched Repositories"]


def test_a_complete_list_corrects_its_count(call_later):
    f = _list_frame()
    counted = []
    f._refresh_category_labels = lambda: counted.append(dict(f._category_counts))
    Frame._on_repo_list_loaded(f, 1, [STAR] * 8)
    assert counted == [{ghviewer.STARRED_ENTRY: 8}]


def test_a_full_page_does_not_claim_a_count(call_later):
    # 100 of maybe more: the startup count stands
    f = _list_frame()
    f._category_counts = {ghviewer.STARRED_ENTRY: 250}
    Frame._on_repo_list_loaded(f, 1, [STAR] * 100)   # no count fetched
    assert f._category_counts == {ghviewer.STARRED_ENTRY: 250}


def test_an_unchanged_count_does_not_rewrite_the_entry():
    # On Windows a rewrite of the selected entry raises a focus event a
    # screen reader may announce, so the same text is never written again.
    f = _repo_frame()
    Frame._on_repos_loaded(f, [_row("me/a")])
    Frame._on_category_counts(f, {ghviewer.STARRED_ENTRY: 7})
    assert f.repo_list.set_strings == 1
    Frame._on_category_counts(f, {ghviewer.STARRED_ENTRY: 7})
    Frame._refresh_category_labels(f)
    assert f.repo_list.set_strings == 1
    Frame._on_category_counts(f, {ghviewer.STARRED_ENTRY: 8})
    assert f.repo_list.set_strings == 2 and f.repo_list.labels[2] == "Starred Repositories (8)"


@pytest.mark.parametrize("view, entry", [
    (ghviewer.VIEW_STARRED, ghviewer.STARRED_ENTRY),
    (ghviewer.VIEW_WATCHED, ghviewer.WATCHED_ENTRY),
])
def test_a_full_page_takes_the_fetched_count(call_later, view, entry):
    f = _list_frame(view)
    Frame._on_repo_list_loaded(f, 1, [STAR] * 100, 0, 250)
    assert f._category_counts == {entry: 250}


def test_a_full_page_fetches_the_count_in_the_worker(monkeypatch, inline_worker):
    monkeypatch.setattr(ghviewer, "fetch_starred_repos", lambda limit: [STAR] * limit)
    monkeypatch.setitem(ghviewer.COUNTED_ENTRIES, ghviewer.STARRED_ENTRY, lambda: 250)
    f, _ = _load_frame(ghviewer.VIEW_STARRED)
    landed = []
    f._on_repo_list_loaded = lambda *a: landed.append(a)
    Frame._load_items(f)
    assert landed[-1][-1] == 250


def test_a_short_list_needs_no_count_call(monkeypatch, inline_worker):
    monkeypatch.setattr(ghviewer, "fetch_starred_repos", lambda limit: [STAR] * 3)
    monkeypatch.setitem(ghviewer.COUNTED_ENTRIES, ghviewer.STARRED_ENTRY,
                        lambda: pytest.fail("no count needed"))
    f, _ = _load_frame(ghviewer.VIEW_STARRED)
    landed = []
    f._on_repo_list_loaded = lambda *a: landed.append(a)
    Frame._load_items(f)
    assert landed[-1][-1] is None


# ── My Organizations and Shared With Me (#40) ──────────────────────────


def _listing(repos=(), orgs=(), shared=0):
    return ghviewer.RepoListing(list(repos), list(orgs), shared)


ORGS = [OrgEntry("mine", True, 13), OrgEntry("bigorg", False, 1108)]


def test_my_organizations_is_one_entry_and_your_own_repos_stay_yours():
    f = _repo_frame(pinned=["p/pin"])
    Frame._on_repos_loaded(f, _listing([_row("me/a")], ORGS, shared=2))
    # One entry for all of them, with no emoji, then Shared With Me
    assert f.repo_list.labels == CATEGORIES[:6] + [
        "My Organizations (2)", "Gists", "Shared With Me (2)", "📌 p/pin", "me/a"]
    assert [d for _, d in f.repo_list.rows][6:9] == [
        ghviewer.MY_ORGS_ENTRY, ghviewer.GISTS_ENTRY, ghviewer.SHARED_ENTRY]
    # Only pinned and your own count as repositories
    assert f.announced[-1] == "Loaded 2 repositories. Select one to view issues and PRs."
    # A rebuild from the cache keeps them
    Frame._on_repos_loaded(f, f._all_repos)
    assert f.repo_list.labels[6:9] == ["My Organizations (2)", "Gists", "Shared With Me (2)"]


@pytest.mark.parametrize("shared, label", [(0, None), (None, "Shared With Me")])
def test_shared_with_me_is_there_only_when_something_is(shared, label):
    f = _repo_frame()
    Frame._on_repos_loaded(f, _listing([_row("me/a")], shared=shared))
    assert f.repo_list.labels[8] == (label or "me/a")


def test_enter_on_my_organizations_lists_them():
    f = _repo_frame()
    f.repo_list.Append("My Organizations", ghviewer.MY_ORGS_ENTRY)
    f.repo_list.SetSelection(0)
    opened = []
    f._select_category = opened.append
    Frame._activate_repo_entry(f)
    assert opened == [ghviewer.VIEW_ORGS]
    assert not ghviewer.is_repo_entry(ghviewer.MY_ORGS_ENTRY)
    assert not ghviewer.is_repo_entry(ghviewer.SHARED_ENTRY)


def test_organizations_list_names_role_and_count(call_later):
    f = _list_frame(ghviewer.VIEW_ORGS)
    Frame._on_orgs_loaded(f, 1, list(ORGS))
    assert f.statuses[-1][0] == "My Organizations — 2 organizations, the ones you own first."
    assert f._category_counts == {ghviewer.MY_ORGS_ENTRY: 2}
    assert ORGS[0].to_row(ghviewer.ORG_SET.ids) == {
        "organization": "mine", "role": "owner", "repositories": "13"}
    assert ORGS[1].to_row(["role", "repositories"]) == {"role": "member", "repositories": "1,108"}


def test_enter_on_an_organization_lists_its_repositories():
    f = _frame(view_mode=ghviewer.VIEW_ORGS)
    f._focused_item = lambda: ORGS[1]
    opened = []
    f._select_org = opened.append
    Frame.on_item_activated(f, None)
    assert opened == ["bigorg"]


def test_backspace_from_an_organization_goes_up_to_it_in_the_list():
    assert ghviewer.PARENT_VIEW[ghviewer.VIEW_ORG] == ghviewer.VIEW_ORGS


def test_an_organizations_repositories_select_my_organizations():
    f = _repo_frame(view=ghviewer.VIEW_ORG)
    f._org = "bigorg"
    f._view_entry = lambda view: Frame._view_entry(f, view)
    assert Frame._current_entry(f) == ghviewer.MY_ORGS_ENTRY


def test_load_items_fetches_the_organizations_their_repos_or_shared(monkeypatch, inline_worker):
    calls = []
    monkeypatch.setattr(ghviewer, "fetch_orgs", lambda: calls.append("orgs") or list(ORGS))
    monkeypatch.setattr(ghviewer, "fetch_org_repos",
                        lambda org, limit: calls.append(("org", org, limit)) or [STAR])
    monkeypatch.setattr(ghviewer, "fetch_shared_repos",
                        lambda limit, orgs: calls.append(("shared", tuple(orgs))) or [])
    f, _ = _load_frame(ghviewer.VIEW_ORGS)
    landed = []
    f._on_orgs_loaded = lambda *a: landed.append(a)
    Frame._load_items(f)
    assert landed[-1][1] == ORGS
    for view in (ghviewer.VIEW_ORG, ghviewer.VIEW_SHARED):
        f, _ = _load_frame(view)
        f._org, f._orgs = "bigorg", [OrgEntry("bigorg")]
        landed = []
        f._on_repo_list_loaded = lambda *a: landed.append(a)
        Frame._load_items(f)
        assert landed[-1][-1] is None   # counted with the repo list, not again
    assert calls == ["orgs", ("org", "bigorg", 100), ("shared", ("bigorg",))]
    assert f.statuses[0][0] == "Loading repositories shared with you…"


def test_an_organizations_list_names_it_and_corrects_its_row_count(call_later):
    f = _list_frame(ghviewer.VIEW_ORG)
    f._org, f._orgs = "bigorg", [OrgEntry("bigorg", False, 1108)]
    Frame._on_repo_list_loaded(f, 1, [STAR] * 3)
    assert f.statuses[-1][0] == "bigorg Repositories — 3 repositories."
    assert f._orgs[0].repo_count == 3 and f._category_counts == {}
    assert Frame._view_label(f, ghviewer.VIEW_ORG, lower=True) == "bigorg repositories"


def test_another_organization_starts_without_the_last_ones_filter():
    f = _frame(view_mode=ghviewer.VIEW_ORG, filter_text="docs", _org="bigorg")
    f._select_category = lambda view: None
    Frame._select_org(f, "TheIdeaPlace")
    assert f.filter_text == "" and f._org == "TheIdeaPlace"
    # The same one again keeps it
    f.filter_text = "quill"
    Frame._select_org(f, "TheIdeaPlace")
    assert f.filter_text == "quill"


def test_a_count_no_longer_known_is_not_kept():
    f = _repo_frame()
    Frame._on_repos_loaded(f, _listing(orgs=ORGS, shared=40))
    assert f._category_counts[ghviewer.SHARED_ENTRY] == 40
    Frame._on_repos_loaded(f, _listing(orgs=ORGS, shared=None))
    assert f.repo_list.labels[8] == "Shared With Me"


# ── Favoriting repositories ─────────────────────────────────────────────


def test_f_in_the_repository_list_favorites_the_repository(monkeypatch):
    f = _repo_frame()
    Frame._on_repos_loaded(f, [_row("me/a", "Mine")])
    f.repo_list.SetSelection(8)   # me/a, after the eight fixed entries
    f.favorites = []
    f._build_favorite_entry = lambda item: Frame._build_favorite_entry(f, item)
    f._selected_repo_entry = lambda: Frame._selected_repo_entry(f)
    f._refresh_repo_list_fav_count = lambda: None
    f._redraw_favorite_marks = lambda: None
    monkeypatch.setattr(ghviewer, "toggle_favorite",
                        lambda e, favs: ([e], True) if not favs else ([], False))
    Frame._favorite_selected_repo(f)
    [fav] = f.favorites
    assert (fav.item_type, fav.repo, fav.url) == ("repository", "me/a", "https://github.com/me/a")
    assert f.announced[-1] == "Added to favorites"
    Frame._favorite_selected_repo(f)
    assert f.favorites == [] and f.announced[-1] == "Removed from favorites"


def test_f_on_a_category_entry_says_so():
    f = _repo_frame()
    Frame._on_repos_loaded(f, [_row("me/a")])
    f.repo_list.SetSelection(1)   # Activity
    f._selected_repo_entry = lambda: Frame._selected_repo_entry(f)
    Frame._favorite_selected_repo(f)
    assert f.announced[-1] == "Select a repository to favorite."


def test_enter_on_a_favorite_repository_opens_it_here_and_backspace_returns():
    fav = FavoriteEntry("nvaccess/nvda", "repository", "https://github.com/nvaccess/nvda",
                        "nvaccess/nvda")
    f = _repo_frame(view=ghviewer.VIEW_FAVORITES)
    f.repo_list.Append("nvaccess/nvda", "nvaccess/nvda")
    f.list_ctrl = FakeItemList(0)
    f.favorites, f.git_items, f._activity_more, f.current_limit = [fav], [fav], False, 100
    f._focused_item = lambda: fav
    opened = []
    f._select_repo = lambda repo, view=ghviewer.VIEW_ISSUES: opened.append(repo)
    Frame.on_item_activated(f, None)
    assert opened == ["nvaccess/nvda"]
    assert f._return_to[0] == ghviewer.VIEW_FAVORITES and f._return_to[3] is fav
    # Backspace: Favorites again, on that favorite
    loaded = []
    f._switch_view = lambda view, load=True: None
    f._restore_repo_selection = lambda prev: None
    f._begin_fetch = lambda: 1
    f._load_favorites_view = lambda focus=None: loaded.append(focus)
    f._pending_target = None
    Frame._return_to_list(f)
    assert loaded == [fav]


# ── No beep after a letter key that did something ──────────────────────


class CharEvent(ghviewer.wx.KeyEvent):
    def __init__(self):
        super().__init__(ghviewer.wx.wxEVT_CHAR)
        self.passed_on = False

    def Skip(self, skip=True):
        self.passed_on = True


@pytest.mark.parametrize("claimed", [True, False])
def test_the_character_after_a_claimed_key_goes_no_further(monkeypatch, claimed):
    # On Windows the list's find-as-you-type beeps at a letter no row starts
    # with, so F (and R, C…) beeped even though they worked
    monkeypatch.setattr(Frame, "_on_list_key",
                        lambda self, ev: None if claimed else ev.Skip())
    f = _frame()
    key = ghviewer.wx.ListEvent()
    Frame.on_list_key_down(f, key)
    char = CharEvent()
    Frame.on_list_char(f, char)
    assert char.passed_on is (not claimed)
    # Only that one character: the next goes on as usual
    later = CharEvent()
    Frame.on_list_char(f, later)
    assert later.passed_on


# ── Enter in Activity opens the event's subject here (#42) ─────────────


def _subject_event(**kw):
    base = dict(event_type="IssueCommentEvent", actor="alice", repo="o/r",
                action="commented on issue #12")
    base.update(kw)
    return ghviewer.ActivityEvent(**base)


def _event_frame():
    f = _frame(view_mode=ghviewer.VIEW_ACTIVITY)
    f.opened, f.browsed = [], []
    f._open_item_here = lambda item: f.opened.append(("item", item.repo, item.number))
    f._open_repo_from_list = lambda repo, item, view=ghviewer.VIEW_ISSUES, branch="": (
        f.opened.append(("repo", repo, view) + ((branch,) if branch else ())))
    f._set_pending_target = lambda view, kind, ref: f.opened.append(("target", kind, ref))
    return f


def test_enter_on_an_issue_event_opens_the_issue_here():
    f = _event_frame()
    Frame._open_event(f, _subject_event(subject_kind="issue", number=12,
                                url="https://github.com/o/r/issues/12#issuecomment-1"))
    assert f.opened == [("item", "o/r", 12)]


@pytest.mark.parametrize("url, view, kind, ref", [
    ("https://github.com/o/r/releases/tag/v1.2", ghviewer.VIEW_RELEASES, "release", "v1.2"),
    ("https://github.com/o/r/commit/abc1234#commitcomment-9", ghviewer.VIEW_COMMITS,
     "commit", "abc1234"),
])
def test_enter_on_a_release_or_commit_event_opens_its_view_here(url, view, kind, ref):
    f = _event_frame()
    Frame._open_event(f, _subject_event(event_type="ReleaseEvent", url=url))
    assert f.opened == [("repo", "o/r", view), ("target", kind, ref)]


def test_enter_on_an_event_with_no_view_here_opens_github(monkeypatch):
    opened = []
    monkeypatch.setattr(ghviewer.webbrowser, "open", opened.append)
    f = _event_frame()
    url = "https://github.com/o/r/compare/aaa...bbb"
    Frame._open_event(f, _subject_event(event_type="PushEvent", action="pushed 2 commits", url=url))
    assert f.opened == [] and opened == [url]


def test_backspace_returns_from_the_view_an_event_opened_in():
    f = _frame(view_mode=ghviewer.VIEW_COMMITS, _return_to=("x",),
               _return_view=ghviewer.VIEW_COMMITS, label_filter="")
    went = []
    f._return_to_list = lambda: went.append("back")
    f._switch_view = lambda view: went.append(("parent", view))
    f._modifiers_down = lambda ev: False
    Frame._on_list_key(f, FakeListKey(ghviewer.wx.WXK_BACK))
    # Back to Activity, not up to Branches, Commits' usual parent
    assert went == ["back"]


def test_enter_on_a_branch_address_opens_its_commits():
    f = _event_frame()
    Frame._open_event(f, _subject_event(event_type="CreateEvent",
                                        url="https://github.com/o/r/tree/fix-focus"))
    # On that branch, with nothing to select in it
    assert f.opened == [("repo", "o/r", ghviewer.VIEW_COMMITS, "fix-focus")]


def test_open_in_browser_on_an_event_opens_github(monkeypatch):
    opened = []
    monkeypatch.setattr(ghviewer.webbrowser, "open", opened.append)
    f = _event_frame()
    url = "https://github.com/o/r/issues/12#issuecomment-1"
    Frame._open_event(f, _subject_event(subject_kind="issue", number=12, url=url),
                      in_browser=True)
    assert f.opened == [] and opened == [url]


@pytest.mark.parametrize("view, return_view, keys, expected", [
    # Commits reached from Activity: back to Activity, not to Branches
    (ghviewer.VIEW_COMMITS, ghviewer.VIEW_COMMITS, "R=refresh  Backspace=back to branches",
     "R=refresh  Backspace=back to activity"),
    (ghviewer.VIEW_RELEASES, ghviewer.VIEW_RELEASES, "R=refresh  Enter=list assets",
     "R=refresh  Enter=list assets  Backspace=back to activity"),
    # Somewhere else: as it was
    (ghviewer.VIEW_COMMITS, ghviewer.VIEW_ISSUES, "Backspace=back to branches",
     "Backspace=back to branches"),
])
def test_the_status_bar_names_the_way_back(view, return_view, keys, expected):
    set_items = {}
    f = _frame(view_mode=view, _return_to=(ghviewer.VIEW_ACTIVITY, [], False, None, 100),
               _return_view=return_view)
    f.status_bar = SimpleNamespace(set_item=lambda k, v: set_items.__setitem__(k, v))
    f._update_filter_status = lambda: None
    Frame._set_view_status(f, "msg", keys)
    assert set_items["keys"] == expected


# ── Commits on all branches ────────────────────────────────────────────


def _commit(branches):
    return Commit("c" * 40, "cccccccc", "msg", "me", "2026-01-01", url=URL, branches=branches)


@pytest.mark.parametrize("branches, commit_branch, line", [
    (["main", "dev"], ghviewer.ALL_BRANCHES, "Branches: main, dev"),
    (["main"], "", "Branch: main"),
    # A commit opened on its own carries no branch: say what the list is of
    ([], "dev", "Branch: dev"),
    ([], "", "Branch: default branch"),
])
def test_commit_details_name_its_branches(branches, commit_branch, line):
    f = _frame(git_items=[_commit(branches)], commit_branch=commit_branch)
    Frame._show_git_details(f, 0)
    assert line in f.details_text.lines


def test_commit_opened_on_its_own_on_all_branches_names_no_branch():
    f = _frame(git_items=[_commit([])], commit_branch=ghviewer.ALL_BRANCHES)
    Frame._show_git_details(f, 0)
    assert not any(l.startswith("Branch") for l in f.details_text.lines)


def _commits_frame(branch, limit):
    loads: list[int] = []
    f = _frame(view_mode=ghviewer.VIEW_COMMITS, commit_branch=branch,
               current_limit=limit, page_size=100)
    f._load_items = lambda: loads.append(f.current_limit)
    return f, loads


def test_view_more_on_all_branches_stops_when_there_is_no_more():
    f, loads = _commits_frame(ghviewer.ALL_BRANCHES, 200)
    f.git_items = [_commit(["main"])] * 150
    Frame.on_view_more(f, None)
    assert loads == []
    assert "pick one branch with Ctrl+B" in f.announced[-1]


def test_view_more_on_all_branches_loads_while_the_list_is_full():
    f, loads = _commits_frame(ghviewer.ALL_BRANCHES, 100)
    f.git_items = [_commit(["main"])] * 100
    Frame.on_view_more(f, None)
    assert loads == [200]


def test_view_more_on_one_branch_still_loads():
    f, loads = _commits_frame("dev", 100)
    Frame.on_view_more(f, None)
    assert loads == [200]


def test_commit_branch_label():
    assert ghviewer._commit_branch_label(ghviewer.ALL_BRANCHES) == "all branches"
    assert ghviewer._commit_branch_label("dev") == "dev"


class FakeChoiceDialog:
    """Stands in for wx.SingleChoiceDialog; picks ``choose`` on ShowModal."""
    choose = None
    last = None

    def __init__(self, parent, message, caption, choices):
        self.choices, self.selection = choices, None
        FakeChoiceDialog.last = self

    def SetSelection(self, i): self.selection = i
    def ShowModal(self): return ghviewer.wx.ID_OK
    def GetStringSelection(self): return self.choose
    def Destroy(self): pass


@pytest.fixture
def choice_dialog(monkeypatch):
    monkeypatch.setattr(ghviewer.wx, "SingleChoiceDialog", FakeChoiceDialog)
    return FakeChoiceDialog


@pytest.mark.parametrize("current, preselected", [
    (ghviewer.ALL_BRANCHES, 0),
    ("dev", 2),
])
def test_branch_picker_offers_all_branches_first(choice_dialog, current, preselected):
    f, loads = _commits_frame(current, 100)
    choice_dialog.choose = "main" if current != "main" else "dev"
    Frame._show_branch_picker(f, ["main", "dev"])
    assert choice_dialog.last.choices == ["All branches", "main", "dev"]
    assert choice_dialog.last.selection == preselected


def test_picking_all_branches_loads_every_branch(choice_dialog):
    f, loads = _commits_frame("dev", 300)
    choice_dialog.choose = "All branches"
    Frame._show_branch_picker(f, ["main", "dev"])
    assert f.commit_branch == ghviewer.ALL_BRANCHES
    assert loads == [100]   # back to the first page
    assert f.announced[-1] == "Showing commits on all branches"


def _loaded_frame(branch, unread=0):
    statuses: list = []
    f = _frame(view_mode=ghviewer.VIEW_COMMITS, commit_branch=branch, current_limit=100,
               _branches_unread=unread, _fetch_token=1)
    f._fetch_is_current = lambda t: t == 1
    f._populate_filtered_list = lambda items, use_favorite_prefix=False: []
    f._set_view_status = lambda msg, keys="": statuses.append(msg)
    f._update_title = lambda: None
    f._take_pending_row = lambda items, token: 0
    f._on_git_items_loaded = lambda t, items, kind: Frame._on_git_items_loaded(f, t, items, kind)
    f.statuses = statuses
    return f


def test_all_branches_status_says_so():
    f = _loaded_frame(ghviewer.ALL_BRANCHES)
    Frame._on_all_branch_commits_loaded(f, 1, [_commit(["main"])], 0)
    assert f.statuses[-1].startswith("o/r — 1 commits on all branches.")
    assert "couldn't be read" not in f.statuses[-1]
    assert f.announced == []


@pytest.mark.parametrize("unread, words", [(1, "1 branch couldn't"), (3, "3 branches couldn't")])
def test_all_branches_status_says_when_branches_are_missing(unread, words):
    f = _loaded_frame(ghviewer.ALL_BRANCHES)
    Frame._on_all_branch_commits_loaded(f, 1, [_commit(["main"])], unread)
    assert words in f.statuses[-1]
    assert words in f.announced[-1]


def test_stale_all_branches_results_are_dropped():
    f = _loaded_frame(ghviewer.ALL_BRANCHES, unread=0)
    Frame._on_all_branch_commits_loaded(f, 0, [_commit(["main"])], 5)
    assert f.statuses == [] and f._branches_unread == 0


def test_switch_view_brings_back_the_columns_last_chosen():
    import settings
    settings.save_columns(ghviewer.COMMIT_SET, ["message", "sha"])
    f = _frame(view_mode=ghviewer.VIEW_ISSUES, repo="o/r", page_size=100, current_limit=100,
               _return_to=None)
    for name in ("_rebuild_columns", "_rebuild_columns_menu", "_update_menu_checks"):
        setattr(f, name, lambda: None)
    f._restore_repo_selection = lambda previous: None
    Frame._switch_view(f, ghviewer.VIEW_COMMITS, load=False)
    assert f.columns == ["message", "sha"]
    Frame._switch_view(f, ghviewer.VIEW_TAGS, load=False)
    assert f.columns == list(ghviewer.TAG_SET.defaults)
