"""Choices that last between sessions: the list mode, the columns each
kind of list shows and the order they're read in, and what is spoken.

Kept in ``settings.json`` in the per-user app data folder
(``%APPDATA%\\ghmanage`` on Windows). What is chosen is also kept in memory
for the session, so a write that fails — the file held open for a moment by
antivirus or a backup — never undoes a choice; the next save, or quitting,
tries again.
A file that can be read but not understood is set aside as
``settings.json.bak-<time>`` and the defaults used, so one bad write never
stops the app starting. A file that can't be read just now is left alone.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from announce import CATEGORIES
from columns import ColumnSet, reconcile
from favorites import _app_data_dir as app_data_dir

LIST_MODES = ("quick", "full")
_LAYOUTS = "column_layouts"

# This session's choices, laid over what is on disk.
_session: dict = {}


def _settings_file() -> Path:
    return app_data_dir() / "settings.json"


def _read_disk() -> dict | None:
    """The saved settings; {} when there are none or they were unreadable
    rubbish (now set aside); None when the file can't be read just now."""
    f = _settings_file()
    if not f.exists():
        return {}
    try:
        raw = f.read_bytes()
    except OSError:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    # Rubbish that can't be moved aside just now is left for next time,
    # rather than written over without a backup.
    return {} if _set_aside(f) else None


def _set_aside(f: Path) -> bool:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup, n = f.with_name(f"{f.name}.bak-{stamp}"), 1
    while backup.exists():
        n += 1
        backup = f.with_name(f"{f.name}.bak-{stamp}-{n}")
    try:
        f.replace(backup)
        return True
    except OSError:
        return False


def _merged(disk: dict) -> dict:
    data = dict(disk)
    for key, value in _session.items():
        if key == _LAYOUTS:
            layouts = data.get(_LAYOUTS)
            data[_LAYOUTS] = {**(layouts if isinstance(layouts, dict) else {}), **value}
        else:
            data[key] = value
    return data


def load_settings() -> dict:
    return _merged(_read_disk() or {})


def _save() -> None:
    """Write the session's choices over what is on disk: to a temporary file
    first, then in place of the old one, so a crash part-way leaves the old
    file whole. Not written while the file can't be read, so nothing saved
    by an earlier session is lost; the choices stay in memory meanwhile."""
    disk = _read_disk()
    if disk is None:
        return
    f = _settings_file()
    tmp = f.with_name(f.name + ".tmp")
    try:
        tmp.write_text(json.dumps(_merged(disk), indent=2), encoding="utf-8")
        for tries_left in (2, 1, 0):
            try:
                os.replace(tmp, f)
                return
            except OSError:
                if tries_left:
                    time.sleep(0.05)  # antivirus or OneDrive holding it a moment
    except OSError:
        pass
    try:
        tmp.unlink()
    except OSError:
        pass


def flush() -> None:
    """Try once more to write this session's choices; for quitting, in case
    the file was busy each time one was made."""
    if _session:
        _save()


def load_list_mode() -> str:
    mode = load_settings().get("list_mode")
    return mode if mode in LIST_MODES else "quick"


def save_list_mode(mode: str) -> None:
    if mode in LIST_MODES:
        _session["list_mode"] = mode
        _save()


def load_columns(column_set: ColumnSet) -> list[str]:
    """The columns a kind of list shows, in order: as last chosen, or its defaults."""
    layouts = load_settings().get(_LAYOUTS)
    saved = layouts.get(column_set.id) if isinstance(layouts, dict) else None
    return reconcile(saved, column_set)


def save_columns(column_set: ColumnSet, columns: list[str]) -> None:
    _session.setdefault(_LAYOUTS, {})[column_set.id] = reconcile(columns, column_set)
    _save()


def load_announcements() -> tuple[bool, dict[str, bool]]:
    """Whether GHManage speaks at all, and which kinds of message
    (``announce.CATEGORIES``). Everything is on until turned off."""
    saved = load_settings().get("announcements")
    saved = saved if isinstance(saved, dict) else {}
    on = saved.get("enabled")
    return (on if isinstance(on, bool) else True,
            {c: saved[c] if isinstance(saved.get(c), bool) else True for c in CATEGORIES})


def save_announcements(enabled: bool, categories: dict[str, bool]) -> None:
    _session["announcements"] = {"enabled": bool(enabled),
                                 **{c: bool(categories.get(c, True)) for c in CATEGORIES}}
    _save()
