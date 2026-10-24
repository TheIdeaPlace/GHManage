"""Choices that last between sessions: the list mode, and the columns each
kind of list shows and the order they're read in.

Kept in ``settings.json`` in the per-user app data folder
(``%APPDATA%\ghmanage`` on Windows). A file that can't be read is set aside
as ``settings.json.bak-<time>`` and the defaults used, so one bad write never
stops the app starting.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from columns import ColumnSet, reconcile

LIST_MODES = ("quick", "full")


def app_data_dir() -> Path:
    """The per-user app data directory for ghmanage, created if needed."""
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    path = Path(base) / "ghmanage"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _settings_file() -> Path:
    return app_data_dir() / "settings.json"


def load_settings() -> dict:
    f = _settings_file()
    if not f.exists():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        pass
    try:
        f.replace(f.with_name(f"{f.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}"))
    except OSError:
        pass
    return {}


def save_settings(data: dict) -> None:
    """Write every setting at once: to a temporary file first, then over the
    old one, so a crash part-way leaves the old file whole."""
    f = _settings_file()
    tmp = f.with_name(f.name + ".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, f)
    except OSError:
        pass  # a setting not kept is no reason to interrupt what you're doing


def _update(key: str, value) -> None:
    data = load_settings()
    data[key] = value
    save_settings(data)


def load_list_mode() -> str:
    mode = load_settings().get("list_mode")
    return mode if mode in LIST_MODES else "quick"


def save_list_mode(mode: str) -> None:
    if mode in LIST_MODES:
        _update("list_mode", mode)


def load_columns(column_set: ColumnSet) -> list[str]:
    """The columns a kind of list shows, in order: as last chosen, or its defaults."""
    layouts = load_settings().get("column_layouts")
    saved = layouts.get(column_set.id) if isinstance(layouts, dict) else None
    return reconcile(saved, column_set)


def save_columns(column_set: ColumnSet, columns: list[str]) -> None:
    data = load_settings()
    layouts = data.get("column_layouts")
    if not isinstance(layouts, dict):
        layouts = {}
    layouts[column_set.id] = reconcile(columns, column_set)
    data["column_layouts"] = layouts
    save_settings(data)


def reset_columns(column_set: ColumnSet) -> list[str]:
    """Forget a list's chosen columns; returns its defaults."""
    data = load_settings()
    layouts = data.get("column_layouts")
    if isinstance(layouts, dict) and column_set.id in layouts:
        del layouts[column_set.id]
        save_settings(data)
    return list(column_set.defaults)
