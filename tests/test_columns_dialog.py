"""View > Columns: the rules (columns.LayoutEditor) and what OK does
(GhViewerFrame._apply_column_choices), without windows."""

from __future__ import annotations

import os
import types

import pytest

import settings
from columns import LayoutEditor
from gh_columns import COMMIT_SET, TAG_SET

if os.environ.get("CI"):
    import wx  # noqa: F401
else:
    pytest.importorskip("wx")

import ghviewer  # noqa: E402

COMMITS = ghviewer.VIEW_COMMITS


def _editor(shown=("sha", "message", "author", "date")):
    return LayoutEditor(COMMIT_SET, list(shown))


def test_available_is_the_rest_in_set_order():
    assert _editor().available() == ["branch", "files", "+/-"]


def test_add_goes_to_the_end():
    ed = _editor()
    assert ed.add(1)  # files
    assert ed.shown == ["sha", "message", "author", "date", "files"]
    assert not ed.add(9)


def test_remove_but_never_the_last():
    ed = _editor(["sha", "message"])
    assert ed.remove(0) and ed.shown == ["message"]
    assert not ed.remove(0) and ed.shown == ["message"]
    assert not ed.remove(-1)


def test_move_up_down_top_bottom():
    ed = _editor()
    assert ed.move(2, 1) and ed.shown == ["sha", "author", "message", "date"]
    assert ed.move(3, 0) and ed.shown == ["date", "sha", "author", "message"]
    assert not ed.move(0, -1)   # already at the top
    assert not ed.move(3, 4)    # already at the bottom
    assert not ed.move(1, 1)


def test_reset_and_changed():
    ed = _editor(["message", "sha"])
    assert not ed.changed_from(["message", "sha"])
    ed.reset()
    assert ed.shown == list(COMMIT_SET.defaults)
    assert ed.changed_from(["message", "sha"])


def test_starts_from_a_cleaned_layout():
    assert LayoutEditor(COMMIT_SET, ["nope", "sha", "sha"]).shown == ["sha"]


# ── OK in the dialog ────────────────────────────────────────────────────


def _frame(view_mode, columns, list_mode="quick"):
    calls = []
    f = types.SimpleNamespace(
        view_mode=view_mode, columns=list(columns), list_mode=list_mode,
        items=[], git_items=[object()], _focused_item=lambda: None,
        _update_mode_status=lambda: calls.append("mode"),
        _rebuild_columns=lambda: calls.append("columns"),
        _update_menu_checks=lambda: None,
        _refresh_list_display=lambda focus=None: calls.append("refresh"),
        _announce=lambda text: calls.append(text))
    return f, calls


def test_ok_saves_every_list_changed_and_redraws_this_one():
    f, calls = _frame(COMMITS, ["sha", "message"])
    ghviewer.GhViewerFrame._apply_column_choices(
        f, {"commits": ["message", "sha"], "tags": ["commit", "tag"]}, False)
    assert f.columns == ["message", "sha"]
    assert settings.load_columns(COMMIT_SET) == ["message", "sha"]
    assert settings.load_columns(TAG_SET) == ["commit", "tag"]
    assert calls == ["columns", "refresh", "Columns saved."]


def test_ok_with_names_turned_on_switches_to_full_mode():
    f, calls = _frame(COMMITS, ["sha"])
    ghviewer.GhViewerFrame._apply_column_choices(f, {}, True)
    assert f.list_mode == "full" and settings.load_list_mode() == "full"
    assert calls == ["mode", "refresh", "Column names on."]


def test_ok_with_another_list_changed_leaves_this_one_alone():
    f, calls = _frame(COMMITS, ["sha"])
    ghviewer.GhViewerFrame._apply_column_choices(f, {"tags": ["tag"]}, False)
    assert f.columns == ["sha"]
    assert calls == ["Columns saved."]


def test_ok_with_nothing_changed():
    f, calls = _frame(COMMITS, ["sha"])
    ghviewer.GhViewerFrame._apply_column_choices(f, {}, False)
    assert calls == ["No changes to the columns."]


def test_ok_lands_back_on_the_row_you_were_on():
    item = object()
    landed = []
    f, calls = _frame(COMMITS, ["sha", "message"])
    f._focused_item = lambda: item
    f._refresh_list_display = lambda focus=None: landed.append(focus)
    ghviewer.GhViewerFrame._apply_column_choices(f, {"commits": ["message", "sha"]}, False)
    assert landed == [item]
