from __future__ import annotations

import json
import types

import settings
from columns import reconcile
from gh_columns import COMMIT_SET, ISSUE_SET


def _file():
    return settings.app_data_dir() / "settings.json"


def test_defaults_with_no_file():
    assert settings.load_list_mode() == "quick"
    assert settings.load_columns(COMMIT_SET) == list(COMMIT_SET.defaults)


def test_columns_and_mode_round_trip():
    settings.save_columns(COMMIT_SET, ["message", "sha", "branch"])
    settings.save_list_mode("full")
    assert settings.load_columns(COMMIT_SET) == ["message", "sha", "branch"]
    assert settings.load_list_mode() == "full"
    # Each list keeps its own.
    assert settings.load_columns(ISSUE_SET) == list(ISSUE_SET.defaults)


def test_a_choice_that_cannot_be_written_is_kept_for_the_session(monkeypatch):
    def locked(src, dst):
        raise PermissionError("held open")
    monkeypatch.setattr(settings.os, "replace", locked)
    monkeypatch.setattr(settings.time, "sleep", lambda s: None)
    settings.save_columns(COMMIT_SET, ["message", "sha"])
    assert settings.load_columns(COMMIT_SET) == ["message", "sha"]
    assert not _file().exists()
    assert not list(settings.app_data_dir().glob("*.tmp"))


def test_a_file_that_cannot_be_read_is_left_alone(monkeypatch):
    settings.save_columns(ISSUE_SET, ["title"])
    settings._session.clear()  # a new session
    real = settings.Path.read_bytes

    def locked(self):
        if self.name == "settings.json":
            raise PermissionError("held open")
        return real(self)
    monkeypatch.setattr(settings.Path, "read_bytes", locked)
    settings.save_list_mode("full")
    assert settings.load_list_mode() == "full"
    monkeypatch.setattr(settings.Path, "read_bytes", real)
    assert not list(settings.app_data_dir().glob("settings.json.bak-*"))
    # Nothing the earlier session saved was written over.
    assert settings.load_columns(ISSUE_SET) == ["title"]


def test_two_bad_files_in_the_same_second_both_kept():
    for text in ("{bad", "{worse"):
        _file().write_text(text, encoding="utf-8")
        settings.load_settings()
    backups = sorted(p.read_text(encoding="utf-8")
                     for p in settings.app_data_dir().glob("settings.json.bak-*"))
    assert backups == ["{bad", "{worse"]


def test_unknown_mode_is_not_kept():
    settings.save_list_mode("loud")
    assert settings.load_list_mode() == "quick"


def test_corrupt_file_is_set_aside_and_defaults_used():
    _file().write_text("{not json", encoding="utf-8")
    assert settings.load_list_mode() == "quick"
    assert not _file().exists()
    backups = list(settings.app_data_dir().glob("settings.json.bak-*"))
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == "{not json"


def test_file_that_is_not_an_object_is_set_aside():
    _file().write_text("[1, 2]", encoding="utf-8")
    assert settings.load_columns(COMMIT_SET) == list(COMMIT_SET.defaults)
    assert list(settings.app_data_dir().glob("settings.json.bak-*"))


def test_saves_from_two_sessions_combine():
    settings.save_columns(ISSUE_SET, ["title"])
    settings._session.clear()
    settings.save_columns(COMMIT_SET, ["sha"])
    settings._session.clear()
    assert settings.load_columns(ISSUE_SET) == ["title"]
    assert settings.load_columns(COMMIT_SET) == ["sha"]


def test_other_settings_survive_a_save():
    _file().write_text(json.dumps({"something_later": 1}), encoding="utf-8")
    settings.save_list_mode("full")
    assert json.loads(_file().read_text(encoding="utf-8"))["something_later"] == 1


def test_reconcile_drops_unknown_and_repeats_and_keeps_order():
    assert reconcile(["author", "nope", "sha", "author"], COMMIT_SET) == ["author", "sha"]


def test_reconcile_falls_back_to_defaults():
    assert reconcile([], COMMIT_SET) == list(COMMIT_SET.defaults)
    assert reconcile(["nope"], COMMIT_SET) == list(COMMIT_SET.defaults)
    assert reconcile("sha", COMMIT_SET) == list(COMMIT_SET.defaults)
    assert reconcile(None, COMMIT_SET) == list(COMMIT_SET.defaults)


# ── The main window ─────────────────────────────────────────────────────


def _toggle_frame(columns):
    import ghviewer

    said = []
    item_id = object()
    f = types.SimpleNamespace(
        view_mode=ghviewer.VIEW_COMMITS, columns=list(columns),
        _col_menu_items={item_id: None}, _announce=said.append,
        _update_menu_checks=lambda: None, _rebuild_columns=lambda: None,
        _refresh_list_display=lambda: None)
    event = types.SimpleNamespace(GetId=lambda: item_id)

    def toggle(col):
        f._col_menu_items[item_id] = col
        ghviewer.GhViewerFrame.on_column_toggled(f, event)
    return f, said, toggle


def test_turning_a_column_on_or_off_is_remembered():
    f, said, toggle = _toggle_frame(["sha", "message"])
    toggle("author")
    assert settings.load_columns(COMMIT_SET) == ["sha", "message", "author"]
    toggle("sha")
    assert settings.load_columns(COMMIT_SET) == ["message", "author"]


def test_the_last_column_stays():
    f, said, toggle = _toggle_frame(["message"])
    toggle("message")
    assert f.columns == ["message"]
    assert said == ["At least one column has to be shown."]


def test_list_mode_is_remembered():
    import ghviewer

    f = types.SimpleNamespace(
        list_mode="quick", items=[], git_items=[], _update_menu_checks=lambda: None,
        _update_mode_status=lambda: None, _announce=lambda text: None)
    ghviewer.GhViewerFrame.on_full_mode(f, None)
    assert settings.load_list_mode() == "full"
    ghviewer.GhViewerFrame.on_quick_mode(f, None)
    assert settings.load_list_mode() == "quick"
