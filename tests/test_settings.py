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


def test_list_mode_is_remembered():
    import ghviewer

    f = types.SimpleNamespace(
        list_mode="quick", items=[], git_items=[], _update_menu_checks=lambda: None,
        _update_mode_status=lambda: None, _announce=lambda text: None)
    ghviewer.GhViewerFrame.on_full_mode(f, None)
    assert settings.load_list_mode() == "full"
    ghviewer.GhViewerFrame.on_quick_mode(f, None)
    assert settings.load_list_mode() == "quick"


def test_quitting_writes_what_a_busy_file_kept_back(monkeypatch):
    real = settings.os.replace
    monkeypatch.setattr(settings.os, "replace", lambda a, b: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(settings.time, "sleep", lambda s: None)
    settings.save_list_mode("full")
    assert not _file().exists()
    monkeypatch.setattr(settings.os, "replace", real)
    settings.flush()
    settings._session.clear()
    assert settings.load_list_mode() == "full"


def test_rubbish_that_cannot_be_moved_aside_is_not_written_over(monkeypatch):
    _file().write_text("{bad", encoding="utf-8")
    monkeypatch.setattr(settings.Path, "replace", lambda self, target: (_ for _ in ()).throw(OSError()))
    settings.save_list_mode("full")
    assert _file().read_text(encoding="utf-8") == "{bad"
    assert settings.load_list_mode() == "full"  # kept for the session
