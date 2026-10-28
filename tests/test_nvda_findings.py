"""Fixes for what the NVDA run of 28 October 2026 found: a long comment read
as "592 characters selected", the milestone said before its issues, the view
named only after a palette command, and "Gists (0)" read twice."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

if os.environ.get("CI"):
    import wx  # noqa: F401
else:
    pytest.importorskip("wx")

import ghviewer  # noqa: E402
from gh_data import Milestone  # noqa: E402

Frame = ghviewer.GhViewerFrame


class FakeText:
    def __init__(self, value: str) -> None:
        self.value, self.selection = value, None

    def GetValue(self): return self.value
    def SetFocus(self): pass
    def SetSelection(self, a, b): self.selection = (a, b)
    def ShowPosition(self, p): pass

    def selected(self) -> str:
        a, b = self.selection
        return self.value[a:b]


def _nav_frame(text: str, positions):
    f = SimpleNamespace(details_text=FakeText(text), _comment_positions=positions,
                        _current_comment=-1, announced=[], view_mode=ghviewer.VIEW_ISSUES)
    f._announce = f.announced.append
    f._line_to_position = lambda line: Frame._line_to_position(f, line)
    return f


def test_a_short_comment_is_selected_whole():
    text = "Body\n  Comment 1 of 1 — ann (2026-01-01):\n    short"
    f = _nav_frame(text, [(1, 2)])
    Frame._navigate_comment(f, 1)
    assert f.details_text.selected().startswith("  Comment 1 of 1 — ann")
    assert f.details_text.selected().rstrip().endswith("short")


def test_a_long_comment_selects_its_heading_so_it_is_read():
    # NVDA reads a selection only up to 512 characters, past that "592
    # characters selected": who wrote it was lost.
    body = "\n".join("    " + "word " * 20 for _ in range(10))
    text = "Body\n  Comment 1 of 1 — ann (2026-01-01):\n" + body
    f = _nav_frame(text, [(1, 11)])
    Frame._navigate_comment(f, 1)
    assert f.details_text.selected() == "  Comment 1 of 1 — ann (2026-01-01):"


def test_a_long_first_line_is_cut_at_the_limit():
    text = "Body\n" + "x" * 2000
    f = _nav_frame(text, [(1, 1)])
    Frame._navigate_comment(f, 1)
    a, b = f.details_text.selection
    assert b - a == ghviewer.SELECTION_READ_MAX


def test_the_milestone_is_said_after_its_issues_arrive(monkeypatch):
    later = []
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda ms, fn, *a: later.append((fn, a)))
    said = []
    monkeypatch.setattr(ghviewer.announce, "announce", lambda m, c=None: said.append(m))
    f = SimpleNamespace(
        label_filter="", page_size=100, current_limit=100, view_mode=ghviewer.VIEW_MILESTONES,
        _return_to=None, _return_view=ghviewer.VIEW_ISSUES,
    )
    f._switch_view = lambda mode, load=True: setattr(f, "view_mode", mode)
    f._update_title = lambda: None
    f._load_items = lambda: None
    f._announce = lambda m: None
    Frame._browse_milestone(f, Milestone(91, "2027.1"))
    # Nothing said yet: the list is still loading.
    assert said == [] and f._say_milestone is True


def test_gists_entry_is_not_relabelled_when_its_count_is_unchanged(monkeypatch):
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda *a: None)
    monkeypatch.setattr(ghviewer.announce, "announce", lambda *a: None)
    relabelled = []
    f = SimpleNamespace(
        current_limit=100, git_items=[], items=[], details_text=SimpleNamespace(SetValue=lambda v: None),
        _category_counts={ghviewer.GISTS_ENTRY: 0},
    )
    f._fetch_is_current = lambda t: True
    f._populate_filtered_list = lambda items, use_favorite_prefix=False: list(items)
    f._refresh_category_labels = lambda: relabelled.append(True)
    f._set_view_status = lambda *a: None
    f._update_title = lambda: None
    Frame._on_gists_loaded(f, 1, [], 0)
    assert relabelled == []
    f._category_counts[ghviewer.GISTS_ENTRY] = 3
    Frame._on_gists_loaded(f, 1, [], 0)
    assert relabelled == [True]


def _items_frame(monkeypatch, said, later):
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda ms, fn, *a: later.append((fn, a)))
    monkeypatch.setattr(ghviewer, "parent_repo", lambda repo: None)
    f = SimpleNamespace(
        repo="o/r", label_filter="", milestone_filter=Milestone(91, "2027.1"), _return_to=None,
        state_filter="open", current_limit=100, items=[], git_items=[],
        details_text=SimpleNamespace(SetValue=lambda v: None), _say_milestone=True,
    )
    f._fetch_is_current = lambda t: True
    f._populate_filtered_list = lambda items, use_favorite_prefix=False: list(items)
    f._set_view_status = lambda *a: None
    f._view_label = lambda v, lower=False: v
    f._update_title = lambda: None
    f._take_pending_row = lambda items, token: 0
    f._focus_list = "focus"
    return f


def test_the_milestone_is_said_once_when_its_issues_land(monkeypatch):
    said, later = [], []
    f = _items_frame(monkeypatch, said, later)
    item = ghviewer.Item(1, "T", "OPEN", "u", False)
    Frame._on_items_loaded(f, 1, [item], 1, 0)
    assert later[-1] == (ghviewer.announce.announce, ("Milestone 2027.1", ghviewer.announce.STATUS))
    assert f._say_milestone is False
    later.clear()
    Frame._on_items_loaded(f, 1, [item], 1, 0)       # R: not said again
    assert all(fn != ghviewer.announce.announce for fn, _ in later)


def test_an_empty_milestone_clears_the_flag(monkeypatch):
    monkeypatch.setattr(ghviewer.announce, "announce", lambda *a: None)
    said, later = [], []
    f = _items_frame(monkeypatch, said, later)
    Frame._on_items_loaded(f, 1, [], 0, 0)
    assert f._say_milestone is False


def test_a_palette_command_that_switches_view_names_the_new_list(monkeypatch):
    said = []
    monkeypatch.setattr(ghviewer.announce, "announce", lambda m, c=None: said.append((m, c)))
    f = SimpleNamespace(view_mode=ghviewer.VIEW_ISSUES)
    f.list_label = SimpleNamespace(GetLabel=lambda: "Files: GHManage/ on main")
    f._update_list_label = lambda: None
    switch = SimpleNamespace(ProcessEvent=lambda e: setattr(f, "view_mode", ghviewer.VIEW_CODE))
    f.GetEventHandler = lambda: switch
    Frame._run_menu_command(f, 1)
    assert said == [("Files: GHManage/ on main", ghviewer.announce.RESULT)]
    said.clear()
    stay = SimpleNamespace(ProcessEvent=lambda e: None)
    f.GetEventHandler = lambda: stay
    Frame._run_menu_command(f, 1)
    assert said == []


def test_a_long_comment_in_changed_files_selects_its_first_line():
    body = "\n".join("  " + "word " * 20 for _ in range(10))
    text = "file.py: modified\nComment by ann: first line\n" + body
    f = _nav_frame(text, [(1, 11, "comment")])
    f.view_mode = ghviewer.VIEW_FILES
    f._files_of = ghviewer.Item(7, "T", "OPEN", "https://github.com/o/r/pull/7", True)
    f._nav_noun = lambda: "change or comment"
    Frame._navigate_comment(f, 1)
    assert f.details_text.selected() == "Comment by ann: first line"
