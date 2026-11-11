"""The checklist's rows on Windows: a real virtual list in a real, unshown box.

What a screen reader says of them can't be tested here; this is that the list
behaves as the list box it stands in for.
"""

import sys

import pytest

wx = pytest.importorskip("wx")

import ghviewer  # noqa: E402
from checklist import Checklist  # noqa: E402

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the rows are Windows-only")


@pytest.fixture(scope="module")
def frame():
    app = wx.App(False)
    f = wx.Frame(None)
    yield f
    f.Destroy()
    app.Destroy()


@pytest.fixture
def rows(frame):
    r = ghviewer.ChecklistRows(frame, ["bug, checked", "docs, not checked"], (300, 200))
    yield r
    r.Destroy()


def test_an_empty_list_has_no_selection(frame):
    r = ghviewer.ChecklistRows(frame, [], (300, 200))
    try:
        assert r.GetItemCount() == 0 and r.GetSelection() == wx.NOT_FOUND
    finally:
        r.Destroy()


def test_selecting_a_row_is_what_comes_back(rows):
    rows.SetSelection(1)
    assert rows.GetSelection() == 1
    assert rows.GetFocusedItem() == 1


def test_changing_a_row_keeps_it_selected_and_shows_the_new_text(rows):
    rows.SetSelection(1)
    rows.SetString(1, "docs, checked")
    assert rows.GetSelection() == 1
    assert rows.GetItemText(1) == "docs, checked"


def test_a_row_added_can_be_selected(rows):
    rows.SetSelection(0)
    rows.Set(["bug, checked", "docs, not checked", "triage, checked, new"])
    rows.SetSelection(2)
    assert rows.GetItemCount() == 3 and rows.GetSelection() == 2
    assert rows.GetSelectedItemCount() == 1


def test_a_cleared_selection_falls_back_to_the_focused_row(rows):
    rows.SetSelection(1)
    rows.Select(1, False)
    assert rows.GetFirstSelected() == wx.NOT_FOUND
    assert rows.GetSelection() == 1


def _box(frame, note=""):
    return ghviewer.ChecklistDialog(frame, "Set Labels", "Labels", Checklist(["bug", "docs"], []),
                                    new_label="&New Label…", new_prompt="Name:", note=note)


def test_the_column_fills_the_list(frame):
    dlg = _box(frame)
    try:
        assert dlg.list.GetColumnWidth(0) == dlg.list.GetClientSize().width
    finally:
        dlg.Destroy()


def test_the_list_is_named_by_its_prompt_even_with_a_note(frame):
    # Windows names a list from the text made just before it.
    dlg = _box(frame, note="No labels were found.")
    try:
        children = list(dlg.GetChildren())
        before = children[children.index(dlg.list) - 1]
        assert before.GetLabel().replace("&", "") == "Labels"
    finally:
        dlg.Destroy()
