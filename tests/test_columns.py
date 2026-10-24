from __future__ import annotations

import types

import pytest

import gh_columns
from columns import STATE, TEXT, ColumnDef, cell_text, row_text

TITLE = ColumnDef("title", "Title")
STATE_COL = ColumnDef("state", "State", kind=STATE)
SHA = ColumnDef("sha", "Commit")


def test_cell_names_a_text_column_but_not_a_state():
    assert cell_text(TITLE, "Fix crash", True) == "Title: Fix crash"
    assert cell_text(STATE_COL, "open", True) == "open"


def test_cell_without_names_is_the_value_as_is():
    assert cell_text(TITLE, "Fix crash", False) == "Fix crash"
    assert cell_text(STATE_COL, "open", False) == "open"


def test_empty_cell_says_nothing_even_with_names():
    assert cell_text(TITLE, "", True) == ""
    assert cell_text(TITLE, "  ", True) == ""


def test_spoken_label_can_differ_from_heading():
    col = ColumnDef("+/-", "+/-", spoken_label="Changes")
    assert cell_text(col, "+3/-1", True) == "Changes: +3/-1"


def test_row_reads_in_column_order_skipping_blanks():
    values = {"sha": "a1b2c3d", "state": "open", "title": ""}
    assert row_text(values, [SHA, STATE_COL, TITLE]) == "a1b2c3d, open"
    assert row_text(values, [STATE_COL, SHA]) == "open, Commit: a1b2c3d"


def test_row_without_names():
    values = {"sha": "a1b2c3d", "title": "Fix crash"}
    assert row_text(values, [SHA, TITLE], speak_labels=False) == "a1b2c3d, Fix crash"


def test_row_after_a_finished_phrase_takes_only_a_space():
    values = {"title": "Why?", "sha": "a1b2c3d"}
    assert row_text(values, [TITLE, SHA], speak_labels=False) == "Why? a1b2c3d"


def test_row_of_nothing_is_empty():
    assert row_text({}, [SHA, TITLE]) == ""


def test_every_column_in_every_set_is_described():
    for column_set in gh_columns.COLUMN_SETS:
        for col_id in column_set.ids:
            assert col_id in gh_columns.CATALOG, (column_set.id, col_id)
        assert set(column_set.defaults) <= set(column_set.ids), column_set.id


@pytest.mark.parametrize("column_set", gh_columns.COLUMN_SETS, ids=lambda s: s.id)
def test_headings_are_words_not_keys(column_set):
    for col in column_set.columns:
        assert col.heading[0].isupper(), (column_set.id, col.id, col.heading)
        assert col.heading not in ("sha", "#", "+/-"), (column_set.id, col.id)
        assert col.kind in (TEXT, STATE)


def test_headings_people_hear():
    assert gh_columns.COMMIT_SET.column("sha").heading == "Commit"
    assert gh_columns.COMMIT_SET.column("+/-").heading == "Changes"
    assert gh_columns.COMMIT_SET.column("branch").heading == "Branches"
    assert gh_columns.WORKFLOW_RUN_SET.column("#").heading == "Run"
    assert gh_columns.ASSET_SET.column("#").heading == "ID"


def test_set_ids_are_unique():
    ids = [s.id for s in gh_columns.COLUMN_SETS]
    assert len(ids) == len(set(ids))


def test_unknown_column_still_has_a_heading():
    assert gh_columns.ISSUE_SET.column("nonsense").heading == "nonsense"


def test_list_widths_kept_from_before():
    assert gh_columns.ISSUE_SET.column("title").width == 400
    assert gh_columns.NOTIFICATION_SET.column("title").width == 420
    assert gh_columns.REPO_SET.column("repo").width == 240
    assert gh_columns.ACTIVITY_SET.column("date").width == 130


def test_full_mode_cells_use_headings_and_leave_states_bare():
    import ghviewer
    from gh_data import Item

    item = Item(4, "Crash", "open", "u", is_pr=True, additions=3, deletions=1)
    f = types.SimpleNamespace(view_mode=ghviewer.VIEW_ISSUES, list_mode="full",
                              columns=["state", "number", "+/-"])
    label = lambda col: ghviewer.GhViewerFrame._item_label(f, item, col)
    assert label("number") == "Number: 4"
    assert label("+/-") == "Changes: +3/-1"
    assert label("state") == item.state_display
    f.columns = ["number", "state"]
    assert label("number") == "4"  # the first column is never named
    f.list_mode = "quick"
    assert label("number") == "4"


def _favorite_frame(list_mode):
    import ghviewer
    from favorites import FavoriteEntry

    fav = FavoriteEntry("o/r", "issue", "https://github.com/o/r/issues/4",
                        "#4 — Crash", "open")
    said = []
    f = types.SimpleNamespace(
        view_mode=ghviewer.VIEW_FAVORITES, list_mode=list_mode,
        columns=list(ghviewer.FAVORITES_SET.defaults),
        list_ctrl=types.SimpleNamespace(GetFirstSelected=lambda: 0),
        _show_details=lambda idx: None, _focused_item=lambda: fav,
        _announce=said.append)
    return ghviewer, fav, f, said


def test_favorites_cells_and_full_mode_announcement():
    ghviewer, fav, f, said = _favorite_frame("full")
    Frame = ghviewer.GhViewerFrame
    assert Frame._item_label(f, fav, "repo") == "Repository: o/r"
    assert Frame._item_label(f, fav, "type") == "issue"
    f.columns = ["repo", "title"]
    assert Frame._item_label(f, fav, "repo") == "o/r"
    f.columns = list(ghviewer.FAVORITES_SET.defaults)
    Frame.on_item_selected(f, None)
    assert said == ["issue, Repository: o/r, Title: #4 — Crash, Subtitle: open"]


def test_quick_mode_announces_nothing_on_selection():
    ghviewer, fav, f, said = _favorite_frame("quick")
    ghviewer.GhViewerFrame.on_item_selected(f, None)
    assert said == []
    assert ghviewer.GhViewerFrame._item_label(f, fav, "repo") == "o/r"
