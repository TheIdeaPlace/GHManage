"""Read README (#88): the README of the repository in front of you, opened
in Files on its default branch and read from the top in the details panel."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import gh_data
from gh_data import GhError, RepoFile

# ── Finding it ─────────────────────────────────────────────────────────


def test_the_readme_is_where_github_says(fake_gh):
    fake_gh.route("repos/o/r/readme", {"path": "docs/README.md", "sha": "s"})
    assert gh_data.fetch_readme_path("o/r") == "docs/README.md"
    assert fake_gh.calls == [["api", "repos/o/r/readme"]]


def test_a_repository_without_one(fake_gh):
    fake_gh.route("readme", GhError("gh: Not Found (HTTP 404)"))
    assert gh_data.fetch_readme_path("o/r") is None


def test_other_failures_are_raised(fake_gh):
    fake_gh.route("readme", GhError("HTTP 500"))
    with pytest.raises(GhError):
        gh_data.fetch_readme_path("o/r")


# ── In the window ──────────────────────────────────────────────────────

if os.environ.get("CI"):
    import wx  # noqa: F401
else:
    pytest.importorskip("wx")

import ghviewer  # noqa: E402

Frame = ghviewer.GhViewerFrame
CODE = ghviewer.VIEW_CODE


class FakeText:
    def __init__(self) -> None:
        self.value = ""
        self.focused = False
        self.insertion = None

    def SetValue(self, v): self.value = v
    def GetValue(self): return self.value
    def Clear(self): self.value = ""
    def SetFocus(self): self.focused = True
    def SetInsertionPoint(self, p): self.insertion = p


class RepoList:
    def __init__(self, data):
        self.data = data

    def GetSelection(self): return 0
    def GetClientData(self, i): return self.data


def _frame(view=CODE, pane=1, item=None, listed="o/listed"):
    f = SimpleNamespace(view_mode=view, repo="o/r", repo_list=RepoList(listed),
                        details_text=FakeText(), git_items=[], items=[], told=[],
                        events=[], _blob_cache={}, _detail_gen=0, _fetch_token=0,
                        _comment_positions=[], _current_comment=-1, filter_text="")
    Frame._reset_code(f)
    f._pane_index = lambda w: pane
    f._current_focus = lambda: None
    f._focused_item = lambda: item
    f._repo_in_front_from = lambda: Frame._repo_in_front_from(f)
    f._tell = f.told.append
    f._announce = lambda msg: f.events.append(("status", msg))
    f._select_repo = lambda r, v: f.events.append(("open", r, v))
    f._select_in_repo_list = lambda r: f.events.append(("listed", r))
    f._open_repo_from_list = lambda r, it, v: f.events.append(("open from list", r, v))
    f._code_where = lambda: Frame._code_where(f)
    return f


def test_read_readme_opens_files_on_the_repo_in_front():
    f = _frame(ghviewer.VIEW_BRANCHES)
    Frame._read_readme(f)
    assert f._code_readme == "o/r"
    assert f.events[-2:] == [("open", "o/r", CODE), ("listed", "o/r")]


def test_from_the_repository_list_it_is_the_one_selected_there():
    f = _frame(ghviewer.VIEW_ISSUES, pane=0)
    Frame._read_readme(f)
    assert f._code_readme == "o/listed"
    assert ("open", "o/listed", CODE) in f.events


def test_from_a_row_of_starred_backspace_comes_back_to_it():
    row = gh_data.RepoEntry("s/r")
    f = _frame(ghviewer.VIEW_STARRED, item=row)
    Frame._read_readme(f)
    assert f.events[-1] == ("open from list", "s/r", CODE)


def test_with_no_repository_it_says_so():
    f = _frame(ghviewer.VIEW_NOTIFICATIONS, listed=None)
    Frame._read_readme(f)
    assert f.told == ["Select a repository first: Read README needs one."]
    assert getattr(f, "_code_readme", None) is None


README = RepoFile("docs/README.md", size=20, sha="r1")
ENTRIES = [RepoFile("docs/img", "dir"), RepoFile("docs/guide.md", size=5, sha="g1"), README]


def _arrive(f, monkeypatch, readme="docs/README.md", note=""):
    later = []
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda ms, fn: later.append(fn))
    monkeypatch.setattr(ghviewer.announce, "announce",
                        lambda *a: f.events.append(("said",) + a))
    f._set_view_status = lambda msg, keys="": None
    f._update_title = f._update_actions_menu = lambda: None
    f._shown = []

    def populate(items, use_favorite_prefix=False):
        f._shown = list(items)
        return f._shown
    f._populate_filtered_list = populate
    f._focus_list = lambda row: f.events.append(("focus", row))
    f._fetch_is_current = lambda token: True
    f._read_readme_text = lambda item: Frame._read_readme_text(f, item)
    f._read_from_top = lambda: Frame._read_from_top(f)
    Frame._on_code_loaded(f, 1, "main", "docs", ENTRIES, False, note, readme)
    later[0]()


def test_it_lands_on_the_readme_and_reads_it_when_the_text_arrives(monkeypatch):
    f = _frame()
    _arrive(f, monkeypatch)
    assert ("focus", 2) in f.events
    assert f._readme_focus is README and not f.details_text.focused
    # No folder count read over the README's first line.
    assert not [e for e in f.events if e[0] == "said"]
    f._shows = lambda view, item, gen: True
    f._keep_blob = lambda sha, text: f._blob_cache.__setitem__(sha, text)
    f.FindFocus = lambda: None
    f._render_code = lambda item: f.details_text.SetValue("docs/README.md: 1 line.\n# Hi")
    Frame._on_blob_fetched(f, 0, README, "# Hi\n", "")
    assert f.details_text.focused and f.details_text.insertion == 0
    assert f._readme_focus is None


def test_a_readme_already_read_is_read_at_once(monkeypatch):
    f = _frame()
    f._blob_cache = {"r1": "# Hi\n"}
    _arrive(f, monkeypatch)
    assert f.details_text.focused and f.details_text.insertion == 0


def test_no_readme_says_so_at_the_top(monkeypatch):
    f = _frame()
    _arrive(f, monkeypatch, readme="", note="o/r has no README.")
    assert f.told == ["o/r has no README."]
    assert not f.details_text.focused


def _worker_frame(monkeypatch, readme_reply):
    """Run _load_items' Files branch on this thread with a fake gh."""
    calls = []
    monkeypatch.setattr(ghviewer, "fetch_default_branch", lambda repo: "main")
    monkeypatch.setattr(ghviewer, "fetch_readme_path", readme_reply)

    def folder(repo, ref, path):
        calls.append(("folder", ref, path))
        return ENTRIES, False
    monkeypatch.setattr(ghviewer, "fetch_repo_folder", folder)
    monkeypatch.setattr(ghviewer.wx, "CallAfter", lambda fn, *a: calls.append(("after",) + a))

    class Thread:
        def __init__(self, target, daemon=True): self.target = target
        def start(self): self.target()
    monkeypatch.setattr(ghviewer.threading, "Thread", Thread)
    return calls


def test_the_load_opens_the_readmes_folder(monkeypatch):
    calls = _worker_frame(monkeypatch, lambda repo: "docs/README.md")
    f = _load_frame()
    f._code_readme = "o/r"
    Frame._load_items(f)
    assert ("folder", "main", "docs") in calls
    after = [c for c in calls if c[0] == "after"][0]
    assert after[3] == "docs" and after[-2:] == ("", "docs/README.md")
    assert f._code_readme is None  # one load only


def test_the_load_without_a_readme_opens_the_top_and_says_why(monkeypatch):
    calls = _worker_frame(monkeypatch, lambda repo: None)
    f = _load_frame()
    f._code_readme = "o/r"
    Frame._load_items(f)
    after = [c for c in calls if c[0] == "after"][0]
    assert after[3] == "" and after[-2:] == ("o/r has no README.", "")


def test_an_ordinary_load_of_files_does_not_look_for_it(monkeypatch):
    def boom(repo):
        raise AssertionError("asked for the README")
    calls = _worker_frame(monkeypatch, boom)
    f = _load_frame()
    Frame._load_items(f)
    assert ("folder", "main", "") in calls


def _load_frame():
    f = _frame()
    f.view_mode = CODE
    f.list_ctrl = SimpleNamespace(DeleteAllItems=lambda: None)
    f.details_text = FakeText()
    f.state_filter = "open"
    f._include_read = False
    f._org = None
    f._orgs = []
    f._search = None
    f._pending_focus_row = 0
    f.current_limit = 100
    f.commit_branch = ""
    f.tab_filter = "both"
    f.label_filter = ""
    f._set_view_status = lambda *a, **k: None
    f._view_label = lambda v, lower=False: "Files"
    f._begin_fetch = lambda: 1
    f._view_entry = lambda v: None
    f._VIEW_LABELS = Frame._VIEW_LABELS
    f._on_code_loaded = lambda *a: None  # CallAfter is caught before it runs
    f._on_fetch_error = lambda t, m: f.told.append(m)
    f._on_items_error = lambda m: f.told.append(m)
    return f
