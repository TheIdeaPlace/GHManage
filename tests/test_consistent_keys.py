"""One contract for the keys: Enter goes in, inside GHManage; Ctrl+O goes out
to GitHub; Backspace comes back; every key a handler acts on is on a menu."""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import commands
import gh_data

if os.environ.get("CI"):
    import wx  # noqa: F401
else:
    pytest.importorskip("wx")

import ghviewer  # noqa: E402
from favorites import FavoriteEntry  # noqa: E402
from gh_data import (  # noqa: E402
    Artifact, Branch, Commit, Discussion, Gist, InsightRow, Item, PagesBuild,
    PagesFile, Release, ReleaseAsset, SecurityAlert, Tag, WorkflowRun,
)

Frame = ghviewer.GhViewerFrame
ROOT = Path(__file__).resolve().parent.parent
V = ghviewer


# ── Names: one for each key, the same on the menu and the status bar ────


@pytest.mark.parametrize("label, said", [
    ("Show Commits", "show commits"),
    ("Run on a Branch…", "run on a branch"),
    ("List Issues and PRs with This Label", "list issues and PRs with this label"),
    ("Open on GitHub", "open on GitHub"),
    ("Read", "read"),
])
def test_hint_words(label, said):
    assert commands.hint_words(label) == said


def test_every_view_says_what_enter_does():
    assert set(ghviewer.OPEN_LABELS) == set(ghviewer.VIEW_COLUMNS)
    for view in ghviewer.VIEW_COLUMNS:
        assert ghviewer.enter_hint(view).startswith("Enter=")
        assert "browser" not in ghviewer.enter_label(view).lower()


@pytest.mark.parametrize("view, hint", [
    (V.VIEW_ISSUES, "Ctrl+O=open on GitHub"),
    (V.VIEW_PAGES, "Ctrl+O=open its commit on GitHub"),
    (V.VIEW_PAGEFILES, "Ctrl+O=open on the web"),
    (V.VIEW_ASSETS, "Ctrl+O=open its release on GitHub"),
    (V.VIEW_ARTIFACTS, ""),
])
def test_ctrl_o_hint_names_what_it_opens(view, hint):
    assert ghviewer.ctrl_o_hint(view) == hint


def test_read_views_read_on_enter():
    for view in ghviewer.READ_VIEWS:
        assert ghviewer.OPEN_LABELS[view].startswith("Read")


# ── Every key the handlers act on is on a menu ──────────────────────────

KEY_NAMES = {"RETURN": "Enter", "BACK": "Backspace", "ESCAPE": "Escape",
             "INSERT": "Insert", "DELETE": "Delete", "F6": "F6"}


def _label_strings(src: str) -> list[str]:
    """Every string in ghviewer.py that isn't a docstring, f-strings' text included."""
    tree = ast.parse(src)
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Module, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docs.add(id(body[0].value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


MENU_CALLS = {"Append", "AppendCheckItem", "AppendRadioItem", "AppendSubMenu", "SetItemLabel"}


def _menu_labels(src: str) -> list[str]:
    """The text of every label given to a menu: the string arguments of
    Append…/SetItemLabel calls (f-strings' text parts included), the labels
    of the context menu entries ("item", id, label), and FAVORITE_LABEL."""
    tree = ast.parse(src)
    out: list[str] = []

    def texts(node) -> list[str]:
        return [n.value for n in ast.walk(node)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]

    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in MENU_CALLS):
            for arg in node.args:
                out += texts(arg)
        if (isinstance(node, ast.Tuple) and node.elts and isinstance(node.elts[0], ast.Constant)
                and node.elts[0].value == "item"):
            out += texts(node)
    out.append(ghviewer.FAVORITE_LABEL)
    return out


def test_every_key_the_handlers_act_on_is_on_a_menu():
    src = (ROOT / "ghviewer.py").read_text(encoding="utf-8")
    keys = set(re.findall(r'ord\("([A-Z])"\)', src))
    keys |= {KEY_NAMES[k] for k in re.findall(r"wx\.WXK_([A-Z0-9]+)", src) if k in KEY_NAMES}
    strings = _menu_labels(src)
    missing = [k for k in sorted(keys)
               if not any(f"({k})" in s or f"\t{k}" in s or f"(Shift+{k})" in s
                          for s in strings)]
    assert not missing, missing


def test_the_new_menu_items_carry_their_keys():
    src = (ROOT / "ghviewer.py").read_text(encoding="utf-8")
    for label in ("Back (Backspace)", "Clear Quick Filter (Escape)", "Next Pane (F6)",
                  "Previous Pane (Shift+F6)", "New Label… (Insert)\\tCtrl+I",
                  "Delete Label… (Delete)\\tCtrl+D", "Delete Workflow Run… (Delete)\\tCtrl+D",
                  "Mark as Done (Delete)\\tCtrl+D", "Open on GitHub\\tCtrl+O"):
        assert label in src, label
    assert "Open in Browser" not in src


# ── The Actions menu: Enter first, named for the view ───────────────────


class MenuItem:
    def __init__(self): self.label, self.enabled = "", True
    def SetItemLabel(self, label): self.label = label
    def Enable(self, on=True): self.enabled = bool(on)


def _menu_frame(view, item=None, **attrs):
    src = (ROOT / "ghviewer.py").read_text(encoding="utf-8")
    f = SimpleNamespace(view_mode=view, repo="o/r", pages_site=None, filter_text="",
                        _files_of=None, _files_back=None, _return_to=None,
                        _code_stack=[], _code_path="", _code_back=None, _org="",
                        label_filter="", milestone_filter=None)
    for name in set(re.findall(r"self\.(_act_\w+) = ", src)):
        setattr(f, name, MenuItem())
    f._focused_item = lambda: item
    f._current_focus = lambda: None
    f._focus_panes = lambda: []
    f._COPY_IDENT_NOUNS = Frame._COPY_IDENT_NOUNS
    f._back_label = lambda lower=False: Frame._back_label(f, lower)
    f._view_label = lambda v, lower=False: Frame._view_label(f, v, lower)
    for k, v in attrs.items():
        setattr(f, k, v)
    Frame._update_actions_menu(f)
    return f


@pytest.mark.parametrize("view, item, label", [
    (V.VIEW_ISSUES, Item(1, "T", "OPEN", "u", False), "Read (Enter)"),
    (V.VIEW_BRANCHES, Branch("main", "s", "m", "a", "d"), "Show Commits (Enter)"),
    (V.VIEW_TAGS, Tag("v1", "abc"), "Files at This Tag (Enter)"),
    (V.VIEW_ASSETS, ReleaseAsset(1, "a.zip", 1, 1, ""), "Download… (Enter)"),
    (V.VIEW_CODE, None, "Open Folder or File (Enter)"),
])
def test_the_first_action_is_enter_s(view, item, label):
    f = _menu_frame(view, item)
    assert f._act_enter.label == label
    assert f._act_enter.enabled is (item is not None)


def test_enter_is_greyed_on_an_expired_artifact_and_ctrl_o_on_any_artifact():
    f = _menu_frame(V.VIEW_ARTIFACTS, Artifact(1, "build", 10, True, "", 9))
    assert not f._act_enter.enabled
    assert f._act_open_web.label == "Open on GitHub\tCtrl+O" and not f._act_open_web.enabled
    f = _menu_frame(V.VIEW_ARTIFACTS, Artifact(1, "build", 10, False, "", 9))
    assert f._act_enter.enabled and f._act_enter.label == "Download… (Enter)"


def test_ctrl_o_s_item_stays_on_in_artifacts_for_the_repository_list():
    # From the repository list, Ctrl+O opens the repository in any view.
    repo_list = SimpleNamespace(IsTopLevel=lambda: False, GetParent=lambda: None)
    f = _menu_frame(V.VIEW_ARTIFACTS, Artifact(1, "build", 10, False, "", 9),
                    _current_focus=lambda: repo_list, _focus_panes=lambda: [repo_list])
    Frame._update_actions_menu(f)
    assert f._act_open_web.enabled


@pytest.mark.parametrize("view, label", [
    (V.VIEW_PAGES, "Open Its Commit on GitHub\tCtrl+O"),
    (V.VIEW_PAGEFILES, "Open on the Web\tCtrl+O"),
    (V.VIEW_ASSETS, "Open Its Release on GitHub\tCtrl+O"),
    (V.VIEW_GISTS, "Open on GitHub\tCtrl+O"),
])
def test_ctrl_o_s_item_names_what_it_opens(view, label):
    f = _menu_frame(view)
    assert f._act_open_web.label == label and f._act_open_web.enabled


@pytest.mark.parametrize("view, attrs, label", [
    (V.VIEW_ISSUES, {}, None),
    (V.VIEW_COMMITS, {}, "Back to Branches (Backspace)"),
    (V.VIEW_ISSUES, {"label_filter": "bug"}, "Back to Labels (Backspace)"),
    (V.VIEW_ISSUES, {"milestone_filter": object()}, "Back to Milestones (Backspace)"),
    (V.VIEW_FILES, {"_files_back": {"view": V.VIEW_COMMITS}}, "Back to Commits (Backspace)"),
    (V.VIEW_CODE, {"_code_path": "src"}, "Up a Folder (Backspace)"),
    (V.VIEW_CODE, {"_code_back": {"view": V.VIEW_TAGS}}, "Back to Tags (Backspace)"),
    (V.VIEW_CODE, {}, None),
    (V.VIEW_HISTORY, {}, "Back to Files (Backspace)"),
    (V.VIEW_COMMITS, {"_return_to": (V.VIEW_FAVORITES,), "_return_view": V.VIEW_COMMITS},
     "Back to Favorites (Backspace)"),
])
def test_back_is_named_for_where_it_goes_and_greyed_where_nowhere(view, attrs, label):
    f = _menu_frame(view, **attrs)
    assert f._act_back.enabled is (label is not None)
    assert f._act_back.label == (label or "Back (Backspace)")


def test_back_to_issues_and_prs_escapes_the_ampersand():
    f = _menu_frame(V.VIEW_FILES)
    assert f._act_back.label == "Back to Issues (Backspace)"
    assert Frame._back_label(f, lower=True) == "back to issues"


def test_clear_filter_is_greyed_without_a_filter():
    assert not _menu_frame(V.VIEW_ISSUES)._act_clear_filter.enabled
    assert _menu_frame(V.VIEW_ISSUES, filter_text="x")._act_clear_filter.enabled


@pytest.mark.parametrize("view, label", [
    (V.VIEW_LABELS, "Delete Label… (Delete)\tCtrl+D"),
    (V.VIEW_WORKFLOW, "Delete Workflow Run… (Delete)\tCtrl+D"),
    (V.VIEW_NOTIFICATIONS, "Mark as Done (Delete)\tCtrl+D"),
])
def test_delete_names_the_key(view, label):
    assert _menu_frame(view)._act_delete.label == label


# ── Enter: in, never the browser ────────────────────────────────────────


@pytest.fixture
def no_browser(monkeypatch):
    monkeypatch.setattr(ghviewer.webbrowser, "open",
                        lambda url: pytest.fail(f"Enter opened the browser: {url}"))


def _enter_frame(view, item):
    f = SimpleNamespace(view_mode=view, repo="o/r", calls=[], told=[])
    f._focused_item = lambda: item
    f._tell = lambda msg, *a, **k: f.told.append(msg)
    for name in ("_read_item", "_open_tag_files", "_download_asset_flow", "_open_favorite",
                 "_open_notification", "_open_event", "_open_item_here", "_show_changed_files"):
        setattr(f, name, (lambda n: lambda *a: f.calls.append(n))(name))
    return f


@pytest.mark.parametrize("view, item, call", [
    (V.VIEW_ISSUES, Item(1, "T", "OPEN", "u", False), "_read_item"),
    (V.VIEW_DISCUSSIONS, Discussion(7, "Q", url="u"), "_read_item"),
    (V.VIEW_SECURITY, SecurityAlert(gh_data.ALERT_CODE, 1, "open", url="u"), "_read_item"),
    (V.VIEW_INSIGHTS, InsightRow("Views", "today", url="u"), "_read_item"),
    (V.VIEW_GISTS, Gist("1", "g", url="u"), "_read_item"),
    (V.VIEW_PAGEFILES, PagesFile("index.md", "https://o.github.io/r/"), "_read_item"),
    (V.VIEW_TAGS, Tag("v1", "abc"), "_open_tag_files"),
    (V.VIEW_ASSETS, ReleaseAsset(1, "a.zip", 1, 1, "", release_tag="v1"),
     "_download_asset_flow"),
    (V.VIEW_FAVORITES, FavoriteEntry("o/r", "issue", "https://github.com/o/r/issues/1", "#1"),
     "_open_favorite"),
    (V.VIEW_COMMITS, Commit("a" * 40, "aaaaaaaa", "m", "me", ""), "_show_changed_files"),
])
def test_enter_goes_in(no_browser, view, item, call):
    f = _enter_frame(view, item)
    Frame.on_item_activated(f, None)
    assert f.calls == [call]


def test_enter_on_anything_else_reads_it_rather_than_open_the_browser(no_browser):
    # Should a view ever reach the end with no case of its own.
    f = _enter_frame("someday", Item(1, "T", "OPEN", "u", False))
    Frame.on_item_activated(f, None)
    assert f.calls == ["_read_item"]


# ── Tags: Enter is Files at the tag, Backspace comes back ───────────────


def test_a_tag_opens_its_files_and_backspace_comes_back_to_it():
    tag = Tag("v1.2", "abc")
    tags = [Tag("v1.3", "def"), tag]
    f = SimpleNamespace(view_mode=V.VIEW_TAGS, git_items=list(tags), filter_text="",
                        current_limit=30, _return_to=None, _return_view=V.VIEW_ISSUES,
                        calls=[], announced=[], _fetch_token=0)
    Frame._reset_code(f)

    def switch(mode, load=True):
        f.view_mode = mode
        if mode != V.VIEW_CODE:
            Frame._reset_code(f)
    f._switch_view = switch
    f._update_title = lambda: None
    f._load_items = lambda: f.calls.append(("load", f.view_mode, f._code_ref))
    Frame._open_tag_files(f, tag)
    assert f.calls == [("load", V.VIEW_CODE, "v1.2")]
    assert f._code_at == "at tag v1.2" and f._code_back["view"] == V.VIEW_TAGS
    assert Frame._back_label(SimpleNamespace(**{**vars(f), "_org": ""})) == "Back to Tags"
    # Backspace at the top: Tags, on the tag
    f._begin_fetch = lambda: 5
    f._announce = f.announced.append
    f._on_git_items_loaded = lambda token, items, kind: f.calls.append(("tags", items, kind))
    Frame._back_from_code(f)
    assert f.view_mode == V.VIEW_TAGS
    assert f.calls[-1] == ("tags", tags, "tags")
    assert f._pending_target == (5, V.VIEW_TAGS, "same", tag)
    assert f.announced == ["Back to tags"]


# ── Release files: Enter downloads here ─────────────────────────────────


def test_a_release_file_downloads_with_gh(fake_gh):
    fake_gh.route("release download", "")
    gh_data.download_release_asset("o/r", "v1", "app*[x].zip", "C:/dl")
    assert fake_gh.calls[-1] == ["release", "download", "v1", "-p", "app[*][[]x].zip",
                                 "-D", "C:/dl", "--repo", "o/r"]
    gh_data.download_release_asset("o/r", "v1", "a.zip", "C:/dl", replace=True)
    assert "--clobber" in fake_gh.calls[-1]


def test_the_download_says_how_it_went(monkeypatch):
    monkeypatch.setattr(ghviewer.wx, "CallAfter", lambda fn, *a: fn(*a))

    class Thread:
        def __init__(self, target, daemon=True): self.target = target
        def start(self): self.target()
    monkeypatch.setattr(ghviewer.threading, "Thread", Thread)
    got = []
    monkeypatch.setattr(ghviewer, "download_release_asset",
                        lambda *a: got.append(a))
    told = []
    f = SimpleNamespace(repo="o/r", _tell=lambda m, *a, **k: told.append(m))
    asset = ReleaseAsset(1, "a.zip", 1, 1, "", release_tag="v1")
    Frame._do_download_asset(f, asset, "C:/dl", False)
    assert got == [("o/r", "v1", "a.zip", "C:/dl", False)]
    assert told == ["Downloading a.zip…", "Downloaded a.zip into C:/dl."]

    def fail(*a):
        raise gh_data.GhError("no such asset")
    monkeypatch.setattr(ghviewer, "download_release_asset", fail)
    Frame._do_download_asset(f, asset, "C:/dl", False)
    assert told[-1] == "Couldn't download a.zip: no such asset"


# ── Ctrl+O: the selected thing on GitHub, from the pane with focus ──────


def _web_frame(item, pane=1, view=V.VIEW_ISSUES, release=None):
    f = SimpleNamespace(repo="o/r", view_mode=view, told=[], announced=[], repos=[],
                        assets_release=release)
    f._pane_index = lambda w: pane
    f._current_focus = lambda: None
    f._focused_item = lambda: item
    f._tell = lambda m, *a, **k: f.told.append(m)
    f._announce = f.announced.append
    f._web_target = lambda it: Frame._web_target(f, it)
    f._repo_entry_action = lambda action: f.repos.append(action)
    return f


@pytest.fixture
def browsed(monkeypatch):
    opened = []
    monkeypatch.setattr(ghviewer.webbrowser, "open", opened.append)
    return opened


def test_ctrl_o_in_the_repository_list_opens_the_repository(browsed):
    f = _web_frame(Item(1, "T", "OPEN", "u", False), pane=0)
    Frame.on_open_browser(f, None)
    assert f.repos == ["browser"] and browsed == []


def test_ctrl_o_on_an_artifact_says_there_is_no_page(browsed):
    f = _web_frame(Artifact(1, "build", 10, False, "", 9), view=V.VIEW_ARTIFACTS)
    Frame.on_open_browser(f, None)
    assert browsed == [] and f.told == ["An artifact has no page on GitHub. Enter downloads it."]


def test_ctrl_o_with_nothing_selected_says_so(browsed):
    f = _web_frame(None)
    Frame.on_open_browser(f, None)
    assert browsed == [] and f.told


@pytest.mark.parametrize("item, release, url, said", [
    (ReleaseAsset(1, "a.zip", 1, 1, "", url="https://github.com/o/r/releases/download/v1/a.zip",
                  release_tag="v1"),
     Release("v1", "One", False, False, "", url="https://github.com/o/r/releases/tag/v1"),
     "https://github.com/o/r/releases/tag/v1", "Opened release v1 on GitHub"),
    (ReleaseAsset(1, "a.zip", 1, 1, "", release_tag="v 2"), None,
     "https://github.com/o/r/releases/tag/v%202", "Opened release v 2 on GitHub"),
    (PagesBuild(1, "built", "abcdef123456", "me", "", url="https://github.com/o/r/commit/abc"), None,
     "https://github.com/o/r/commit/abc", "Opened commit abcdef12 on GitHub"),
    (PagesFile("index.md", "https://o.github.io/r/index.html"), None,
     "https://o.github.io/r/index.html", "Opened index.md on the web"),
    (Item(4, "T", "OPEN", "https://github.com/o/r/issues/4", False), None,
     "https://github.com/o/r/issues/4", "Opened #4 on GitHub"),
])
def test_ctrl_o_opens_the_right_page(browsed, item, release, url, said):
    f = _web_frame(item, release=release)
    Frame.on_open_browser(f, None)
    assert browsed == [url] and f.announced == [said]


# ── Keys: modifiers, J in Jobs, Ctrl+O, the details panel ───────────────


class Key:
    def __init__(self, code, mods=0):
        self.code, self.mods, self.skipped = code, mods, False
    def GetKeyCode(self): return self.code
    def GetModifiers(self): return self.mods
    def HasAnyModifiers(self): return self.mods != 0
    def ShiftDown(self): return bool(self.mods & ghviewer.wx.MOD_SHIFT)
    def Skip(self): self.skipped = True


def _hook_frame(view, focus="list", item=None):
    f = SimpleNamespace(view_mode=view, calls=[], _files_of=None)
    f.repo_list, f.list_ctrl, f.details_text = object(), object(), object()
    f.status_bar = SimpleNamespace(IsDescendant=lambda w: False)
    f.FindFocus = lambda: {"list": f.list_ctrl, "details": f.details_text,
                           "repos": f.repo_list}[focus]
    f._focused_item = lambda: item
    for name in ("_do_new_label", "_delete_focused_item", "_show_run_jobs", "on_open_browser",
                 "_back_to_row", "on_item_activated", "_show_what_failed", "_rerun_run",
                 "_cancel_run", "_pr_checks", "_pr_review", "_pr_toggle_draft",
                 "_show_file_history", "_toggle_blame", "_show_changed_files",
                 "_open_whole_file", "_go_to_event_repo"):
        setattr(f, name, (lambda n: lambda *a: f.calls.append(n))(name))
    f._enter_from_details = lambda: Frame._enter_from_details(f)
    return f


@pytest.mark.parametrize("key, mods", [
    (ghviewer.wx.WXK_INSERT, ghviewer.wx.MOD_CONTROL),   # Ctrl+Insert copies
    (ghviewer.wx.WXK_INSERT, ghviewer.wx.MOD_SHIFT),     # Shift+Insert pastes
    (ghviewer.wx.WXK_DELETE, ghviewer.wx.MOD_SHIFT),     # Shift+Delete cuts
    (ghviewer.wx.WXK_DELETE, ghviewer.wx.MOD_CONTROL),
])
def test_insert_and_delete_with_a_modifier_do_nothing_of_ours(key, mods):
    f = _hook_frame(V.VIEW_LABELS, focus="details")
    ev = Key(key, mods)
    Frame.on_char_hook(f, ev)
    assert f.calls == [] and ev.skipped


def test_bare_insert_and_delete_still_work():
    f = _hook_frame(V.VIEW_LABELS)
    Frame.on_char_hook(f, Key(ghviewer.wx.WXK_INSERT))
    Frame.on_char_hook(f, Key(ghviewer.wx.WXK_DELETE))
    assert f.calls == ["_do_new_label", "_delete_focused_item"]


def test_j_is_jobs_in_workflow_runs_only():
    f = _hook_frame(V.VIEW_WORKFLOW)
    Frame.on_char_hook(f, Key(ord("J")))
    assert f.calls == ["_show_run_jobs"]
    f = _hook_frame(V.VIEW_JOBS)
    ev = Key(ord("J"))
    Frame.on_char_hook(f, ev)
    assert f.calls == [] and ev.skipped
    Frame.on_char_hook(f, Key(ord("L")))   # the rest of the run keys still work
    assert f.calls == ["_show_what_failed"]


@pytest.mark.parametrize("focus", ["list", "details", "repos"])
def test_ctrl_o_works_from_every_pane(focus):
    f = _hook_frame(V.VIEW_ARTIFACTS, focus=focus)
    Frame.on_char_hook(f, Key(ord("O"), ghviewer.wx.MOD_CONTROL))
    assert f.calls == ["on_open_browser"]


def test_bare_o_is_not_ctrl_o():
    f = _hook_frame(V.VIEW_ISSUES)
    ev = Key(ord("O"))
    Frame.on_char_hook(f, ev)
    assert f.calls == [] and ev.skipped


@pytest.mark.parametrize("view", [V.VIEW_ISSUES, V.VIEW_BRANCHES, V.VIEW_DISCUSSIONS])
def test_backspace_in_the_details_panel_goes_back_to_the_row(view):
    f = _hook_frame(view, focus="details")
    Frame.on_char_hook(f, Key(ghviewer.wx.WXK_BACK))
    assert f.calls == ["_back_to_row"]


def test_backspace_in_the_list_is_not_taken_here():
    f = _hook_frame(V.VIEW_ISSUES)
    ev = Key(ghviewer.wx.WXK_BACK)
    Frame.on_char_hook(f, ev)
    assert f.calls == [] and ev.skipped


@pytest.mark.parametrize("view, item, acts", [
    (V.VIEW_BRANCHES, Branch("main", "s", "m", "a", "d"), True),
    (V.VIEW_WORKFLOW, WorkflowRun("CI", "completed", "success", "main", "push", ""), True),
    (V.VIEW_ISSUES, Item(1, "T", "OPEN", "u", False), False),   # reading it already
    (V.VIEW_DISCUSSIONS, Discussion(7, "Q"), False),
    (V.VIEW_CODE, gh_data.RepoFile("a.py", "file"), False),
    (V.VIEW_CODE, gh_data.RepoFile("src", "dir"), True),
    (V.VIEW_BRANCHES, None, False),
])
def test_enter_in_the_details_panel_does_what_it_does_in_the_list(view, item, acts):
    f = _hook_frame(view, focus="details", item=item)
    ev = Key(ghviewer.wx.WXK_RETURN)
    Frame.on_char_hook(f, ev)
    assert f.calls == (["on_item_activated"] if acts else [])
    assert ev.skipped is (not acts)


def test_backspace_from_the_details_panel_lands_on_the_row():
    focused = []
    f = SimpleNamespace(list_ctrl=SimpleNamespace(GetItemCount=lambda: 3,
                                                  GetFirstSelected=lambda: 2,
                                                  SetFocus=lambda: focused.append("list")))
    f._focus_list = lambda row: focused.append(row)
    Frame._back_to_row(f)
    assert focused == [2]
    f.list_ctrl.GetItemCount = lambda: 0
    Frame._back_to_row(f)
    assert focused == [2, "list"]


# ── Favorites, Activity, forks: here, or said why not ───────────────────


def _fav_frame():
    f = SimpleNamespace(opened=[], told=[], _fetch_token=3)
    f._tell = lambda m, *a, **k: f.told.append(m)
    f._open_repo_from_list = lambda repo, item, view=V.VIEW_ISSUES, branch="": (
        f.opened.append(("repo", repo, view) + ((branch,) if branch else ())))
    f._set_pending_target = lambda view, kind, ref: f.opened.append(("target", kind, ref))
    f._open_item_here = lambda item, repo="", number=0: f.opened.append(("item", repo, number))
    f._open_address_here = lambda t, it: Frame._open_address_here(f, t, it)
    return f


@pytest.mark.parametrize("fav, opened", [
    (FavoriteEntry("o/r", "repository", "https://github.com/o/r", "o/r"),
     [("repo", "o/r", V.VIEW_ISSUES)]),
    (FavoriteEntry("o/r", "PR", "https://github.com/o/r/pull/5", "#5 — x"),
     [("item", "o/r", 5)]),
    (FavoriteEntry("o/r", "commit", "https://github.com/o/r/commit/abc1234", "abc1234"),
     [("repo", "o/r", V.VIEW_COMMITS), ("target", "commit", "abc1234")]),
    (FavoriteEntry("o/r", "release", "https://github.com/o/r/releases/tag/v1", "v1"),
     [("repo", "o/r", V.VIEW_RELEASES), ("target", "release", "v1")]),
    (FavoriteEntry("o/r", "workflow run", "https://github.com/o/r/actions/runs/9", "#3 CI"),
     [("repo", "o/r", V.VIEW_WORKFLOW), ("target", "run", "9")]),
    (FavoriteEntry("o/r", "milestone", "https://github.com/o/r/milestone/2", "1.0"),
     [("repo", "o/r", V.VIEW_MILESTONES), ("target", "milestone", "2")]),
    (FavoriteEntry("o/r", "discussion", "https://github.com/o/r/discussions/4", "#4 — q"),
     [("repo", "o/r", V.VIEW_DISCUSSIONS), ("target", "discussion", "4")]),
    (FavoriteEntry("o/r", "branch", "https://github.com/o/r/tree/dev", "dev"),
     [("repo", "o/r", V.VIEW_COMMITS, "dev")]),
    (FavoriteEntry("o/r", "tag", "https://github.com/o/r/releases/tag/v1", "v1"),
     [("repo", "o/r", V.VIEW_TAGS), ("target", "tag", "v1")]),
    (FavoriteEntry("o/r", "label", "https://github.com/o/r/labels/bug", "bug"),
     [("repo", "o/r", V.VIEW_LABELS), ("target", "label", "bug")]),
])
def test_enter_on_a_favorite_opens_it_here(no_browser, fav, opened):
    f = _fav_frame()
    Frame._open_favorite(f, fav)
    assert f.opened == opened and f.told == []


@pytest.mark.parametrize("fav, said", [
    (FavoriteEntry("o/r", "file", "https://github.com/o/r/blob/main/a.py", "a.py"),
     "GHManage has no view for that; Ctrl+O opens it on GitHub."),
    (FavoriteEntry("o/r", "page", "https://o.github.io/r/", "index.md"),
     "GHManage has no view for that; Ctrl+O opens it on the web."),
])
def test_a_favorite_with_no_view_here_says_so(no_browser, fav, said):
    f = _fav_frame()
    Frame._open_favorite(f, fav)
    assert f.opened == [] and f.told == [said]


def test_favorites_found_by_name_land_on_them(monkeypatch):
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda ms, fn, *a: fn(*a))
    f = SimpleNamespace(_pending_target=(1, V.VIEW_TAGS, "tag", "v1"), view_mode=V.VIEW_TAGS,
                        _shown=[], _speak_landing=False)
    tags = [Tag("v2", "a"), Tag("v1", "b")]
    f._shown = tags
    f._row_of = lambda it: Frame._row_of(f, it)
    f._describe_landing = Frame._describe_landing
    said = []
    f._say_landing = said.append
    assert Frame._take_pending_row(f, tags, 1) == 1
    assert said == ["Tag v1"]


def test_an_event_s_repository_opens_here():
    f = _fav_frame()
    event = ghviewer.ActivityEvent(event_type="WatchEvent", actor="a", repo="o/r",
                                   action="starred o/r", url="https://github.com/o/r")
    Frame._open_event(f, event)
    assert f.opened == [("repo", "o/r", V.VIEW_ISSUES)]


@pytest.mark.parametrize("url, view", [
    ("https://github.com/o/r", V.VIEW_ISSUES),
    ("https://github.com/o/r/issues/3", V.VIEW_ISSUES),
    ("https://github.com/o/r/actions", V.VIEW_WORKFLOW),
    ("https://github.com/o/r/compare/a...b", None),
    ("https://github.com/someone", None),
    ("https://o.github.io/r/", None),
])
def test_address_view(url, view):
    assert ghviewer.address_view(ghviewer.parse_github_url(url)) == view


def test_on_the_web():
    assert ghviewer.on_the_web("https://github.com/o/r") == "on GitHub"
    assert ghviewer.on_the_web("https://gist.github.com/x") == "on GitHub"
    assert ghviewer.on_the_web("https://o.github.io/r/") == "on the web"


# ── Details text: no browser behind Enter ───────────────────────────


def test_no_details_text_sends_you_to_the_browser_with_enter():
    src = (ROOT / "ghviewer.py").read_text(encoding="utf-8")
    for name in ("alertview", "discussionview", "gistview", "insightview", "milestoneview",
                 "codeview"):
        src += (ROOT / f"{name}.py").read_text(encoding="utf-8")
    assert "Enter to open in browser" not in src
    assert "Enter to open this in your browser" not in src
    assert "Enter to download this file in your browser" not in src


def test_the_view_keys_hint_puts_enter_and_ctrl_o_first():
    assert ghviewer.keys_hint(ghviewer.enter_hint(V.VIEW_TAGS), ghviewer.ctrl_o_hint(V.VIEW_TAGS),
                              "", "R=refresh") == (
        "Enter=files at this tag  Ctrl+O=open on GitHub  R=refresh")


def test_list_keys_name_the_new_places():
    keys = {(c.keys, c.where) for c in commands.LIST_KEYS}
    assert ("Backspace", commands.DETAILS) in keys
    assert ("Delete", commands.REPO_LIST) in keys
    assert ("Enter", commands.TAGS) in keys and ("Enter", commands.ASSETS) in keys
    assert ("J", commands.RUN_LIST) in keys


def test_a_favorite_security_alert_lands_in_security_alerts():
    fav = FavoriteEntry("o/r", "security alert",
                        "https://github.com/o/r/security/dependabot/3", "Dependabot #3")
    f = _fav_frame()
    Frame._open_favorite(f, fav)
    assert f.opened == [("repo", "o/r", V.VIEW_SECURITY),
                        ("target", "alert", "https://github.com/o/r/security/dependabot/3")]


def test_a_landing_refused_aloud_stops_speaking_landings(monkeypatch):
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda ms, fn, *a: fn(*a))
    told = []
    f = SimpleNamespace(_pending_target=(1, V.VIEW_TAGS, "tag", "v9"), view_mode=V.VIEW_TAGS,
                        _shown=[Tag("v1", "a")], _speak_landing=True,
                        _tell=lambda m, *a, **k: told.append(m))
    f._row_of = lambda it: Frame._row_of(f, it)
    assert Frame._take_pending_row(f, f._shown, 1) == 0
    assert told == ["Tag v9 isn't among the 1 newest tags."] and f._speak_landing is False


def _fork_frame():
    f = SimpleNamespace(view_mode=V.VIEW_FAVORITES, _fetch_token=4, told=[], opened=[])
    f._tell = lambda m, *a, **k: f.told.append(m)
    f._open_item_checked = lambda item, parent, repo, number: f.opened.append((repo, number))
    return f


def test_a_second_enter_while_github_is_asked_asks_nothing_more(monkeypatch):
    started = []

    class Thread:
        def __init__(self, target, daemon=True): started.append(target)
        def start(self): pass
    monkeypatch.setattr(ghviewer.threading, "Thread", Thread)
    f = _fork_frame()
    item = FavoriteEntry("o/r", "issue", "https://github.com/o/r/issues/1", "#1")
    Frame._open_item_here(f, item, "o/r", 1)
    Frame._open_item_here(f, item, "o/r", 1)
    assert len(started) == 1 and f.told == ["Opening #1 in o/r…"]


def test_the_fork_answer_opens_nothing_once_you_have_moved_on():
    f = _fork_frame()
    item = FavoriteEntry("o/r", "issue", "https://github.com/o/r/issues/1", "#1")
    where = (4, V.VIEW_FAVORITES, "o/r", 1)
    f._fork_asking = where
    f._focused_item = lambda: item
    f.view_mode = V.VIEW_ISSUES          # opened something else meanwhile
    Frame._on_fork_checked(f, item, None, "o/r", 1, where)
    assert f.opened == [] and f._fork_asking is None
    f.view_mode = V.VIEW_FAVORITES       # still there, on it
    Frame._on_fork_checked(f, item, None, "o/r", 1, where)
    assert f.opened == [("o/r", 1)]
    f._focused_item = lambda: None       # moved to another row
    Frame._on_fork_checked(f, item, None, "o/r", 1, where)
    assert f.opened == [("o/r", 1)]
