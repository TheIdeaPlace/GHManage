"""Persistence for user-pinned (added-by-URL) repositories.

Pinned repos are stored as a JSON file in the user's per-app data directory
(`%APPDATA%\\ghmanage\\pinned_repos.json` on Windows) so they survive across
sessions. Each entry is just ``OWNER/NAME``; the description is fetched live
when the repo list is built.

Hidden repos live beside them in ``hidden_repos.json``: repositories from your
GitHub account that you have removed from the list. GitHub still lists them,
so they are kept out of the list here rather than deleted anywhere.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def _app_data_dir() -> Path:
    """Return the per-user app data directory for ghmanage, creating it if needed."""
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    path = Path(base) / "ghmanage"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pinned_file() -> Path:
    return _app_data_dir() / "pinned_repos.json"


def _hidden_file() -> Path:
    return _app_data_dir() / "hidden_repos.json"


def load_pinned() -> list[str]:
    """Load the list of pinned repo names (OWNER/NAME). Returns [] if missing/invalid."""
    return _load_names(_pinned_file())


def _load_names(f: Path) -> list[str]:
    """A JSON list of repo names, or [] when the file is missing or unreadable."""
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, list):
        return [str(r) for r in data if isinstance(r, str) and r]
    return []


def save_pinned(repos: list[str]) -> None:
    """Persist the list of pinned repo names."""
    _save_names(_pinned_file(), repos)


def _save_names(f: Path, repos: list[str]) -> None:
    f.write_text(json.dumps(repos, indent=2), encoding="utf-8")


def add_pinned(repo: str) -> list[str]:
    """Add a repo to the pinned list (dedup, case-insensitive). Returns the new list."""
    repos = load_pinned()
    lower = [r.lower() for r in repos]
    if repo.lower() not in lower:
        repos.append(repo)
        save_pinned(repos)
    return repos


def remove_pinned(repo: str) -> list[str]:
    """Remove a repo from the pinned list (case-insensitive). Returns the new list."""
    repos = [r for r in load_pinned() if r.lower() != repo.lower()]
    save_pinned(repos)
    return repos


def load_hidden() -> list[str]:
    """The repos removed from the list (OWNER/NAME). [] if missing/invalid."""
    return _load_names(_hidden_file())


def hide_repo(repo: str) -> list[str]:
    """Keep a repo out of the list (dedup, case-insensitive). Returns the new list."""
    repos = load_hidden()
    if repo.lower() not in (r.lower() for r in repos):
        repos.append(repo)
        _save_names(_hidden_file(), repos)
    return repos


def unhide_repos(names: list[str]) -> list[str]:
    """Put repos back in the list (case-insensitive). Returns the new hidden list."""
    gone = {n.lower() for n in names}
    repos = [r for r in load_hidden() if r.lower() not in gone]
    _save_names(_hidden_file(), repos)
    return repos
