"""Categories mode in the window (#130): Navigate By, Choose Repositories,
the category lists, Enter, Backspace, ] and [, Ctrl+1 to Ctrl+8."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import across
import settings
from across import Row
from gh_data import Commit, Discussion, Item, Milestone, Release, SecurityAlert, Tag, WorkflowRun

if os.environ.get("CI"):
    import wx  # noqa: F401
else:
    pytest.importorskip("wx")

import ghviewer as V  # noqa: E402

Frame = V.GhViewerFrame


# ── The left-hand list ──────────────────────────────────────────────────


class FakeListBox:
    def __init__(self):
        self.rows, self.sel, self.focused = [], -1, False
    def Clear(self): self.rows = []
    def Append(self, text, clientData=None): self.rows.append((text, clientData))
    def GetCount(self): return len(self.rows)
    def GetSelection(self): return self.sel
    def SetSelection(self, i): self.sel = i
    def GetClientData(self, i): return self.rows[i][1]
    def GetString(self, i): return self.rows[i][0]
    def SetFocus(self): self.focused = True


def _left_frame(**kw):
    state = dict(repo_list=FakeListBox(), _repos_loaded_once=False, repo=None,
                 view_mode=V.VIEW_ISSUES, said=[], _nav_mode=settings.NAV_CATEGORIES,
                 _all_repos=[])
    state.update(kw)
    f = SimpleNamespace(**state)
    f._current_focus = lambda: None
    f._current_entry = lambda: Frame._current_entry(f)
    f._view_entry = lambda v: Frame._view_entry(f, v)
    f._restore_repo_selection = lambda prev: Frame._restore_repo_selection(f, prev)
    f._tell = lambda m, *a, **k: f.said.append(m)
    return f


def test_categories_mode_lists_choose_repositories_then_each_category():
    settings.save_across_repos(["o/a", "o/b"])
    f = _left_frame()
    Frame._fill_categories(f)
    texts = [t for t, _ in f.repo_list.rows]
    assert texts == ["Choose Repositories… (2 chosen)", "Issues & PRs", "Releases",
                     "Workflow Runs", "Commits", "Tags", "Milestones", "Discussions",
                     "Security Alerts"]
    assert f.repo_list.rows[2][1] == V.ACROSS_ENTRY_PREFIX + "releases"
    assert f.repo_list.focused and f.repo_list.sel == 0


def test_with_none_chosen_the_first_entry_says_so():
    f = _left_frame()
    Frame._fill_categories(f)
    assert f.repo_list.rows[0][0] == "Choose Repositories… (none chosen yet)"


def test_category_entries_are_not_repositories():
    assert not V.is_repo_entry(V.CHOOSE_REPOS_ENTRY)
    assert not V.is_repo_entry(V.ACROSS_ENTRY_PREFIX + "releases")
    assert V.is_repo_entry("o/r")


def test_a_category_view_is_selected_in_the_left_list():
    f = _left_frame(view_mode=V.ACROSS_VIEW_OF["tags"])
    Frame._fill_categories(f)
    f.repo_list.sel = -1
    Frame._restore_repo_selection(f, None)
    assert f.repo_list.GetClientData(f.repo_list.sel) == V.ACROSS_ENTRY_PREFIX + "tags"


def test_the_mode_is_remembered_and_said(monkeypatch):
    monkeypatch.setattr(V.speech, "set_label", lambda *a: None)
    rebuilt = []
    f = _left_frame(_nav_mode=settings.NAV_REPOSITORIES)
    f._repo_list_title = SimpleNamespace(SetLabel=lambda t: rebuilt.append(("title", t)))
    f._update_menu_checks = lambda: None
    f._nav_title = lambda: Frame._nav_title(f)
    f._on_repos_loaded = lambda repos: Frame._fill_categories(f)
    Frame._set_nav_mode(f, settings.NAV_CATEGORIES)
    assert settings.load_nav_mode() == settings.NAV_CATEGORIES
    assert ("title", "Categories") in rebuilt
    assert f.said == ["Categories, 9 entries."]


# ── Choosing repositories ───────────────────────────────────────────────


@pytest.mark.parametrize("typed, name", [
    ("o/r", "o/r"), (" o/r/ ", "o/r"), ("https://github.com/TheIdeaPlace/GHManage", "TheIdeaPlace/GHManage"),
    ("github.com/TheIdeaPlace/AIChat/issues/5", "TheIdeaPlace/AIChat"),
    ("not a repo", ""), ("a/b/c", ""), ("o/", ""),
])
def test_names_typed_or_pasted(typed, name):
    assert Frame.across_repo_name(typed) == name


class FakeChooser:
    answer = None
    add, toggle = [], []
    seen = None

    def __init__(self, parent, title, prompt, model, say=None, new_label="", new_prompt="",
                 note="", same_as=None):
        FakeChooser.seen = (title, prompt, model.rows(), new_label, note)
        for n in FakeChooser.add:
            model.add(n)
        for n in FakeChooser.toggle:
            model.toggle(model.names.index(n))
    def ShowModal(self): return FakeChooser.answer
    def Destroy(self): pass


@pytest.fixture
def chooser(monkeypatch):
    monkeypatch.setattr(V, "ChecklistDialog", FakeChooser)
    FakeChooser.add, FakeChooser.toggle = [], []
    FakeChooser.answer = V.wx.ID_OK
    f = _left_frame(view_mode=V.VIEW_ISSUES)
    f._tell_after_box = f.said.append
    f._fill_categories = lambda: None
    f._select_across = lambda kind: f.said.append(f"open {kind}")
    f.across_repo_name = Frame.across_repo_name
    return f


def test_choosing_saves_the_checked_repositories(chooser):
    settings.save_across_repos(["o/b"])
    FakeChooser.toggle = ["o/a"]
    Frame._ask_across_repos(chooser, ["o/b", "o/a", "O/A", ""], "")
    title, prompt, rows, new_label, note = FakeChooser.seen
    # As the box opened: duplicates by case listed once, A to Z, the chosen one checked.
    assert rows == ["o/a, not checked", "o/b, checked"]
    assert set(settings.load_across_repos()) == {"o/a", "o/b"}
    assert chooser.said == ["2 repositories chosen."]
    assert new_label == "&Add Repository…"


def test_an_added_address_becomes_its_repository_and_junk_is_left_out(chooser):
    FakeChooser.add = ["https://github.com/x/y", "nonsense"]
    Frame._ask_across_repos(chooser, ["o/a"], "")
    assert settings.load_across_repos() == ["x/y"]
    assert chooser.said == ["1 repository chosen. Not repository names, so left out: nonsense."]


def test_cancel_changes_nothing(chooser):
    settings.save_across_repos(["o/b"])
    FakeChooser.answer = V.wx.ID_CANCEL
    FakeChooser.toggle = ["o/b"]
    Frame._ask_across_repos(chooser, ["o/b"], "releases")
    assert settings.load_across_repos() == ["o/b"]
    assert chooser.said == ["Repositories unchanged."]


def test_choosing_from_a_category_then_opens_it(chooser):
    FakeChooser.toggle = ["o/a"]
    Frame._ask_across_repos(chooser, ["o/a"], "releases")
    assert chooser.said[-1] == "open releases"


def test_a_category_with_none_chosen_asks_first():
    opened = []
    f = SimpleNamespace(_choose_across_repos=lambda then="": opened.append(then))
    Frame._select_across(f, "runs")
    assert opened == ["runs"]


# ── Ctrl+1 to Ctrl+8 ────────────────────────────────────────────────────


def test_ctrl_numbers_pick_categories_only_in_categories_mode():
    picked = []
    f = _left_frame()
    Frame._fill_categories(f)
    f._update_menu_checks = lambda: None
    f._select_across = picked.append
    assert Frame._across_shortcut(f, 2) is True and picked == ["releases"]
    assert f.repo_list.GetClientData(f.repo_list.sel) == V.ACROSS_ENTRY_PREFIX + "releases"
    f._nav_mode = settings.NAV_REPOSITORIES
    assert Frame._across_shortcut(f, 2) is False and picked == ["releases"]


# ── A category's list ───────────────────────────────────────────────────


ROWS = [Row("o/a", Release("v2", "Two", False, False, "2026-11-02", url="ua2"), "2026-11-02"),
        Row("o/b", Release("v9", "Nine", False, False, "2026-11-05", url="ub9"), "2026-11-05")]


def _list_frame(view):
    f = SimpleNamespace(view_mode=view, items=[], git_items=[], sort_order=V.SORT_ORDERS[0],
                        status=[], focused=[], details_text=SimpleNamespace(
                            SetValue=lambda v: f.status.append(("details", v))),
                        _across_result=None)
    f._fetch_is_current = lambda t: t == 1
    f._across_ordered = lambda r: Frame._across_ordered(f, r)
    f._populate_filtered_list = lambda rows, use_favorite_prefix=False: list(rows)
    f._set_view_status = lambda m, k="": f.status.append((m, k))
    f._update_title = lambda: None
    f._row_of = lambda it: 0
    f._focus_list = lambda row: f.focused.append(row)
    return f


def test_a_loaded_list_is_newest_first_with_its_status(monkeypatch):
    later = []
    monkeypatch.setattr(V.wx, "CallLater", lambda ms, fn, *a: later.append((fn, a)))
    f = _list_frame(V.ACROSS_VIEW_OF["releases"])
    result = across.Result("releases", rows=list(ROWS), repos=["o/a", "o/b"])
    Frame._on_across_loaded(f, 1, result)
    assert [r.repo for r in f.git_items] == ["o/b", "o/a"] and f.items == []
    message, keys = f.status[0]
    assert message == "Releases from 2 repositories: 2 releases. Latest release of each."
    assert "]=next repository" in keys and "Enter=open in its repository" in keys


def test_issues_go_in_items_so_they_behave_as_in_my_work(monkeypatch):
    monkeypatch.setattr(V.wx, "CallLater", lambda *a: None)
    f = _list_frame(V.VIEW_ACROSS_ISSUES)
    issue = Item(1, "T", "OPEN", "u", False, repo="o/a", updated_at="2026-11-01")
    Frame._on_across_loaded(f, 1, across.Result("issues", rows=[issue], repos=["o/a"]))
    assert f.items == [issue] and f.git_items == []
    assert "I=milestone" in f.status[0][1]
    assert V.VIEW_ACROSS_ISSUES in V.ITEM_VIEWS


def test_an_empty_list_says_why_in_the_details_and_aloud(monkeypatch):
    spoken = []
    monkeypatch.setattr(V.announce, "announce", lambda m, c=None, *a: spoken.append(m))
    f = _list_frame(V.ACROSS_VIEW_OF["discussions"])
    f._populate_filtered_list = lambda rows, use_favorite_prefix=False: []
    r = across.Result("discussions", rows=[], repos=["o/a"], notes={"o/a": "Discussions are off"})
    Frame._on_across_loaded(f, 1, r)
    assert spoken == ["Discussions from 1 repository: 0 discussions. o/a: Discussions are off."]


def test_a_superseded_load_is_dropped():
    f = _list_frame(V.ACROSS_VIEW_OF["releases"])
    Frame._on_across_loaded(f, 2, across.Result("releases", rows=list(ROWS)))
    assert f.status == [] and f._across_result is None


def test_grouping_and_sort_order(monkeypatch):
    settings.save_flag("group_by_repo", True)
    f = _list_frame(V.ACROSS_VIEW_OF["releases"])
    r = across.Result("releases", rows=list(ROWS), repos=["o/a", "o/b"])
    assert [x.repo for x in Frame._across_ordered(f, r)] == ["o/a", "o/b"]
    settings.save_flag("group_by_repo", False)
    f.sort_order = "Created (oldest first)"
    assert [x.repo for x in Frame._across_ordered(f, r)] == ["o/a", "o/b"]
    f.sort_order = "Title (Z-A)"
    assert [x.item.name for x in Frame._across_ordered(f, r)] == ["Two", "Nine"]


def test_latest_release_only_reloads_releases():
    loads, said = [], []
    f = SimpleNamespace(view_mode=V.ACROSS_VIEW_OF["releases"], _tell=said.append,
                        _update_menu_checks=lambda: None, _load_items=lambda: loads.append(1))
    Frame._toggle_across_flag(f, "latest_release_only")
    assert settings.load_flag("latest_release_only", True) is False
    assert said == ["Every release."] and loads == [1]


# ── Details, Enter, G, favorites ────────────────────────────────────────


def test_details_start_with_the_repository():
    out = []
    f = SimpleNamespace(details_text=SimpleNamespace(SetValue=out.append, Clear=lambda: None),
                        commit_branch="")
    Frame._show_across_details(f, ROWS[0])
    assert out[0].splitlines()[0] == "Repository: o/a"
    assert "v2" in out[0]
    Frame._show_across_details(f, Row("o/m", Milestone(3, "1.0", url="u")))
    assert out[1].startswith("Repository: o/m\nMilestone: 1.0")


@pytest.mark.parametrize("item, kind, ref", [
    (Release("v2", "Two", False, False, ""), "release", "v2"),
    (WorkflowRun("CI", "", "", "", "", "", run_id=7), "run", "7"),
    (Commit("a" * 40, "aaaaaaa", "m", "me", ""), "commit", "a" * 40),
    (Milestone(3, "1.0"), "milestone", "3"),
    (Discussion(4, "T"), "discussion", "4"),
])
def test_enter_opens_it_in_its_repository(item, kind, ref):
    opened = []
    f = SimpleNamespace(_open_address_here=lambda t, it: opened.append((t.repo, t.kind, t.ref)) or True,
                        _tell=lambda m: opened.append(m))
    Frame._open_across_row(f, Row("o/r", item))
    assert opened == [("o/r", kind, ref)]


@pytest.mark.parametrize("item, view, kind, ref", [
    (Tag("v1", "abc"), V.VIEW_TAGS, "tag", "v1"),
    (SecurityAlert("dependabot", 2, "open", "high", "p", "s", "w", url="ua"),
     V.VIEW_SECURITY, "alert", "ua"),
])
def test_enter_on_a_tag_or_alert_lands_on_it(item, view, kind, ref):
    calls = []
    f = SimpleNamespace(_open_repo_from_list=lambda r, it, v: calls.append(("open", r, v)),
                        _set_pending_target=lambda v, k, rf: calls.append(("pending", v, k, rf)))
    Frame._open_across_row(f, Row("o/r", item))
    assert calls == [("open", "o/r", view), ("pending", view, kind, ref)]
    assert f._speak_landing is True


def test_g_opens_the_rows_repository():
    opened = []
    f = SimpleNamespace(_focused_item=lambda: ROWS[0],
                        _open_repo_from_list=lambda r, it: opened.append(r))
    Frame._go_to_event_repo(f)
    assert opened == ["o/a"]


def test_a_row_is_favorited_as_its_item_in_its_repository():
    f = SimpleNamespace(repo=None)
    entry = Frame._build_favorite_entry(f, ROWS[0])
    assert entry.repo == "o/a" and entry.item_type == "release" and entry.url == "ua2"


def test_copy_reads_the_item():
    assert V.copy_values(ROWS[0]).ident == "v2"


# ── ] and [ ─────────────────────────────────────────────────────────────


class FakeList:
    def __init__(self, sel):
        self.sel = sel
    def GetFirstSelected(self): return self.sel
    def Select(self, i, on=True):
        if on:
            self.sel = i
    def Focus(self, i): pass


def _jump_frame(rows, sel, in_details=False):
    f = SimpleNamespace(_shown=rows, list_ctrl=FakeList(sel), said=[], focused=[],
                        details_text=object(), columns=["repo", "tag", "name"], shown=[])
    f._current_focus = lambda: f.details_text if in_details else None
    f._focus_list = lambda i: f.focused.append(i)
    f._show_details = f.shown.append
    f.details_text = SimpleNamespace(SetInsertionPoint=lambda p: None)
    f._current_focus = lambda: f.details_text if in_details else None
    f._tell = f.said.append
    f._row_item = lambda i: rows[i]
    f._row_said = lambda i: Frame._row_said(f, i)
    return f


ROWS3 = [Row("o/a", Release("a2", "A2", False, False, "")), Row("o/a", Release("a1", "A1", False, False, "")),
         Row("o/b", Release("b1", "B1", False, False, ""))]


def test_bracket_moves_to_the_next_repository_in_the_list(monkeypatch):
    monkeypatch.setattr(V.speech, "jaws_running", lambda: False)
    f = _jump_frame(ROWS3, 0)
    Frame._across_jump(f, 1)
    assert f.focused == [2] and f.said == []   # NVDA reads the row it lands on


def test_with_jaws_the_move_is_said(monkeypatch):
    monkeypatch.setattr(V.speech, "jaws_running", lambda: True)
    f = _jump_frame(ROWS3, 0)
    Frame._across_jump(f, 1)
    assert f.said == ["o/b: b1, B1"]


def test_from_the_details_panel_it_stays_there_and_says_where(monkeypatch):
    f = _jump_frame(ROWS3, 2, in_details=True)
    Frame._across_jump(f, -1)
    assert f.list_ctrl.sel == 0 and f.shown == [0] and f.focused == []
    assert f.said == ["o/a: a2, A2"]


def test_at_the_end_it_says_so():
    f = _jump_frame(ROWS3, 2)
    Frame._across_jump(f, 1)
    assert f.said == ["No more repositories after this one."]
    f = _jump_frame(ROWS3, 0)
    Frame._across_jump(f, -1)
    assert f.said == ["No repositories before this one."]


def test_brackets_reach_the_jump_from_the_key_handler():
    from test_consistent_keys import Key, _hook_frame
    f = _hook_frame(V.ACROSS_VIEW_OF["releases"])
    f._across_jump = lambda step: f.calls.append(("jump", step))

    class Bracket(Key):
        def __init__(self, ch):
            super().__init__(ord(ch))
            self.ch = ch
        def GetUnicodeKey(self): return ord(self.ch)
    Frame.on_char_hook(f, Bracket("]"))
    Frame.on_char_hook(f, Bracket("["))
    assert f.calls == [("jump", 1), ("jump", -1)]


def test_keys_and_views_are_registered():
    for view in V.ACROSS_VIEWS:
        assert view in V.REPOLESS_VIEWS and view in V.FEED_VIEWS and view in V.GO_TO_REPO_VIEWS
        assert V._view_columns(view).columns[0].id == "repo"
