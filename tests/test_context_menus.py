"""Context menus: the item list's mirrors the Actions menu; the repo list has its own."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

if os.environ.get("CI"):
    import wx  # noqa: F401
else:
    pytest.importorskip("wx")

import ghviewer  # noqa: E402
from favorites import FavoriteEntry  # noqa: E402
from gh_data import Branch, Item, OrgEntry  # noqa: E402

Frame = ghviewer.GhViewerFrame


class FakeItem:
    def __init__(self, id=0, label="", enabled=True, sep=False, sub=None):
        self.id, self.label, self.enabled, self.sep, self.sub = id, label, enabled, sep, sub

    def IsSeparator(self): return self.sep
    def IsEnabled(self): return self.enabled
    def GetSubMenu(self): return self.sub
    def GetItemLabel(self): return self.label
    def GetId(self): return self.id


class FakeMenu:
    def __init__(self, *items):
        self.items = list(items)

    def GetMenuItems(self): return self.items


SEP = FakeItem(sep=True)
# The last entry wherever a list can load more (#52).
MORE = ("item", ghviewer.ID_VIEW_MORE, "View More\tCtrl++")


def _frame(view, item, actions):
    f = SimpleNamespace(view_mode=view, _actions_menu=actions, announced=[], favorites=[])
    f._favorite_prefix = lambda it: Frame._favorite_prefix(f, it)
    f._update_actions_menu = lambda: None
    f._focused_item = lambda: item
    f._OPEN_LABELS = Frame._OPEN_LABELS
    f._announce = f.announced.append
    return f


def test_entries_mirror_the_enabled_actions():
    actions = FakeMenu(
        FakeItem(1, "Open in Browser\tCtrl+O"),
        FakeItem(2, "Copy", sub=FakeMenu(FakeItem(3, "Copy Link"), FakeItem(4, "Copy X", enabled=False))),
        SEP,
        FakeItem(5, "Close Issue/PR", enabled=False),
        SEP,
        SEP,
        FakeItem(6, "New Issue…"),
        SEP,
        FakeItem(7, "Run Workflow", enabled=False),
    )
    f = _frame(ghviewer.VIEW_ISSUES, Item(1, "T", "OPEN", "u", False), actions)
    assert Frame._context_entries(f) == [
        ("item", 1, "Open in Browser\tCtrl+O"),
        ("sub", "Copy", [("item", 3, "Copy Link")]),
        ("sep",),
        ("item", 6, "New Issue…"),
        ("sep",),
        MORE,
    ]


def test_enter_s_action_comes_first_where_it_is_not_the_browser():
    actions = FakeMenu(FakeItem(1, "Open in Browser"))
    f = _frame(ghviewer.VIEW_BRANCHES, Branch("main", "s", "m", "a", "d"), actions)
    entries = Frame._context_entries(f)
    assert entries[0] == ("item", ghviewer.ID_CTX_OPEN, "Show Commits\tEnter")
    assert entries[1] == ("sep",)


def test_no_open_entry_without_a_selection():
    f = _frame(ghviewer.VIEW_BRANCHES, None, FakeMenu(FakeItem(1, "Compare")))
    assert Frame._context_entries(f) == [("item", 1, "Compare"), ("sep",), MORE]


def test_an_empty_submenu_is_left_out():
    actions = FakeMenu(FakeItem(2, "Pull Request", sub=FakeMenu(FakeItem(3, "Merge", enabled=False))))
    f = _frame(ghviewer.VIEW_ISSUES, None, actions)
    assert Frame._context_entries(f) == [MORE]


def test_every_open_label_is_for_a_real_view():
    assert set(Frame._OPEN_LABELS) <= set(ghviewer.VIEW_COLUMNS)


def test_the_real_actions_menu_offers_new_issue_in_a_repo():
    # The thing asked for: New Issue on the context menu of a repo's lists.
    labels = []

    def flatten(entries):
        for e in entries:
            if e[0] == "item":
                labels.append(e[2])
            elif e[0] == "sub":
                flatten(e[2])
    f = _frame(ghviewer.VIEW_BRANCHES, Branch("main", "s", "m", "a", "d"),
               FakeMenu(FakeItem(ghviewer.ID_NEW_ISSUE, "New Issue…\tCtrl+N")))
    flatten(Frame._context_entries(f))
    assert "New Issue…\tCtrl+N" in labels


# ── The repository list ─────────────────────────────────────────────────


def _repo_frame(pinned=(), favorites=()):
    return SimpleNamespace(_pinned_repos=list(pinned), favorites=list(favorites))


def _ids(entries):
    out = []
    for e in entries:
        if e[0] == "item":
            out.append(e[1])
        elif e[0] == "sub":
            out += _ids(e[2])
    return out


def test_a_repository_s_menu():
    ids = _ids(Frame._repo_context_entries(_repo_frame(), "o/r"))
    for wanted in (ghviewer.ID_REPO_OPEN, ghviewer.ID_REPO_BROWSER, ghviewer.ID_NEW_ISSUE,
                   ghviewer.ID_SEARCH_REPO, ghviewer.ID_WATCH_SETTINGS, ghviewer.ID_COPY_LINK):
        assert wanted in ids
    # One of your own too: removing it hides it (#2).
    assert ghviewer.ID_REMOVE_REPO in ids


FAV = FakeItem(ghviewer.ID_FAVORITE, ghviewer.FAVORITE_LABEL)


@pytest.mark.parametrize("view, item, favorites, label", [
    (ghviewer.VIEW_ISSUES, Item(1, "T", "OPEN", "u1", False), [], "Add to Favorites (F)"),
    (ghviewer.VIEW_ISSUES, Item(1, "T", "OPEN", "u1", False),
     [FavoriteEntry("o/r", "issue", "u1", "#1")], "Remove from Favorites (F)"),
    (ghviewer.VIEW_FAVORITES, FavoriteEntry("o/r", "issue", "u1", "#1"), [],
     "Remove from Favorites (F)"),
    # Nothing to favorite: no entry at all
    (ghviewer.VIEW_ORGS, OrgEntry("bigorg"), [], None),
])
def test_the_favorite_entry_says_which_way_it_goes(view, item, favorites, label):
    f = _frame(view, item, FakeMenu(FAV))
    f.favorites = favorites
    favs = [e for e in Frame._context_entries(f) if e[0] == "item" and e[1] == ghviewer.ID_FAVORITE]
    assert favs == ([("item", ghviewer.ID_FAVORITE, label)] if label else [])


@pytest.mark.parametrize("favorites, label", [
    ([], "Add to Favorites (F)"),
    ([FavoriteEntry("o/r", "repository", "https://github.com/o/r", "o/r")],
     "Remove from Favorites (F)"),
])
def test_a_repository_s_menu_can_favorite_it(favorites, label):
    entries = Frame._repo_context_entries(_repo_frame(favorites=favorites), "o/r")
    assert ("item", ghviewer.ID_FAVORITE, label) in entries


def test_a_pinned_repository_can_be_removed():
    assert ghviewer.ID_REMOVE_REPO in _ids(Frame._repo_context_entries(_repo_frame(["o/r"]), "o/r"))


def test_a_saved_search_s_menu():
    entries = Frame._repo_context_entries(_repo_frame(), ghviewer.SEARCH_ENTRY_PREFIX + "Bugs")
    assert [e[2] for e in entries] == ["Run Search\tEnter", "Remove Saved Search…\tDelete"]


def test_a_category_just_opens():
    assert Frame._repo_context_entries(_repo_frame(), ghviewer.ACTIVITY_ENTRY) == [
        ("item", ghviewer.ID_REPO_OPEN, "Open\tEnter")]


class RepoList:
    def __init__(self, data):
        self.data = data

    def GetSelection(self): return 0
    def GetClientData(self, i): return self.data


def test_repo_actions_on_a_category_entry_say_so():
    f = SimpleNamespace(repo_list=RepoList(ghviewer.MY_WORK_ENTRY), announced=[])
    f._announce = f.announced.append
    Frame._repo_entry_action(f, "browser")
    assert f.announced == ["Select a repository first."]


def test_no_duplicate_of_enter_from_the_actions_menu():
    from gh_data import Workflow
    actions = FakeMenu(FakeItem(ghviewer.ID_ACT_RUN_WORKFLOW, "Run Workflow on Branch…"),
                       FakeItem(9, "Open in Browser"))
    f = _frame(ghviewer.VIEW_WORKFLOWS, Workflow(1, "CI", "ci.yml", "active"), actions)
    labels = [e[2] for e in Frame._context_entries(f) if e[0] == "item"]
    assert labels == ["Run on a Branch…\tEnter", "Open in Browser", "View More\tCtrl++"]


def test_an_expired_artifact_offers_no_download():
    from gh_data import Artifact
    actions = FakeMenu(FakeItem(ghviewer.ID_ACT_DOWNLOAD_ARTIFACT, "Download Artifact…"),
                       FakeItem(9, "Copy"))
    f = _frame(ghviewer.VIEW_ARTIFACTS, Artifact(1, "build", 10, True, "", 9), actions)
    assert Frame._context_entries(f) == [("item", 9, "Copy")]   # all there is: no View More


@pytest.mark.parametrize("view", [ghviewer.VIEW_FAVORITES, ghviewer.VIEW_MY_WORK, ghviewer.VIEW_ORGS])
def test_no_view_more_where_everything_is_already_loaded(view):
    f = _frame(view, None, FakeMenu(FakeItem(1, "Copy")))
    assert MORE not in Frame._context_entries(f)


# ── Go To on a repository's context menu (#51) ─────────────────────────


def _go_to(entries):
    return next((e for e in entries if e[0] == "sub" and e[1] == "Go To"), None)


def test_a_repository_s_menu_goes_to_each_of_its_views():
    sub = _go_to(Frame._repo_context_entries(_repo_frame(), "o/r"))
    assert [e[2] for e in sub[2]] == [label for _, label in ghviewer.REPO_GO_TO]
    assert [e[1] for e in sub[2]] == [ghviewer.ID_GO_TO_VIEW[v] for v, _ in ghviewer.REPO_GO_TO]


def test_a_repository_row_s_menu_has_go_to_too():
    from gh_data import RepoEntry
    f = _frame(ghviewer.VIEW_STARRED, RepoEntry("o/r", url="u"), FakeMenu(FakeItem(9, "Copy")))
    assert _go_to(Frame._context_entries(f)) is not None
    # Not on a row that isn't a repository
    f = _frame(ghviewer.VIEW_ISSUES, Item(1, "T", "OPEN", "u", False), FakeMenu(FakeItem(9, "Copy")))
    assert _go_to(Frame._context_entries(f)) is None


@pytest.mark.parametrize("source, expected", [
    ("row", [("from list", "o/r", ghviewer.VIEW_RELEASES)]),
    ("list", [("select", "o/r", ghviewer.VIEW_RELEASES), ("in list", "o/r")]),
])
def test_go_to_opens_the_repository_on_that_view(source, expected):
    events = []
    f = SimpleNamespace(announced=[], commit_branch="old")
    f._announce = f.announced.append
    f._repo_in_front_from = lambda: ("o/r", source)
    f._focused_item = lambda: "row item"
    f._open_repo_from_list = lambda repo, item, view: events.append(("from list", repo, view))
    f._select_repo = lambda repo, view: events.append(("select", repo, view))
    f._select_in_repo_list = lambda repo: events.append(("in list", repo))
    Frame._go_to_repo_view(f, ghviewer.VIEW_RELEASES)
    assert events == expected


def test_go_to_commits_starts_on_the_default_branch():
    f = SimpleNamespace(announced=[], commit_branch="feature")
    f._repo_in_front_from = lambda: ("o/r", "list")
    f._select_repo = lambda repo, view: None
    f._select_in_repo_list = lambda repo: None
    Frame._go_to_repo_view(f, ghviewer.VIEW_COMMITS)
    assert f.commit_branch == ""


def test_never_two_separators_together_or_at_either_end():
    from gh_data import RepoEntry
    # Every action greyed out: Enter's entry, Go To and View More
    actions = FakeMenu(SEP, FakeItem(5, "Close", enabled=False), SEP)
    f = _frame(ghviewer.VIEW_STARRED, RepoEntry("o/r", url="u"), actions)
    entries = Frame._context_entries(f)
    kinds = [e[0] for e in entries]
    assert kinds[0] != "sep" and kinds[-1] != "sep"
    assert all(not (a == b == "sep") for a, b in zip(kinds, kinds[1:]))
