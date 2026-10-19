"""Favorites and pinned repos, which persist between sessions."""

from __future__ import annotations

import json

import pytest

import favorites
import pinned_repos
from favorites import FavoriteEntry


def _fav(url="https://github.com/o/r/issues/1", **kw):
    return FavoriteEntry(repo="o/r", item_type="issue", url=url, title="#1", **kw)


def test_tests_cannot_reach_real_gh():
    # Guard for the autouse fixture in conftest: no fake_gh here, so any gh
    # call must fail rather than run the real, signed-in CLI.
    import gh_data
    import pytest
    with pytest.raises(AssertionError, match="real gh CLI"):
        gh_data.fetch_tags("o/r")


# ── Favorites ──────────────────────────────────────────────────────────


def test_no_file_means_no_favorites(app_data):
    assert favorites.load_favorites() == []


def test_favorites_round_trip(app_data):
    entries = [_fav(subtitle="open", added_at="2026-01-01T00:00:00"), _fav("https://x/2")]
    favorites.save_favorites(entries)
    assert favorites.load_favorites() == entries


def test_favorites_keep_non_ascii(app_data):
    favorites.save_favorites([_fav(subtitle="café — ★")])
    assert favorites.load_favorites()[0].subtitle == "café — ★"


def test_corrupt_favorites_file_is_ignored(app_data):
    (app_data / "favorites.json").write_text("{not json", encoding="utf-8")
    assert favorites.load_favorites() == []
    (app_data / "favorites.json").write_text('{"a": 1}', encoding="utf-8")
    assert favorites.load_favorites() == []


def test_bad_entries_are_skipped_and_missing_fields_default(app_data):
    (app_data / "favorites.json").write_text(
        json.dumps(["junk", 3, {"url": "https://x", "title": "T"}]), encoding="utf-8")
    [fav] = favorites.load_favorites()
    assert (fav.url, fav.title, fav.repo, fav.subtitle) == ("https://x", "T", "", "")


def test_toggle_adds_then_removes_and_saves(app_data):
    favs, added = favorites.toggle_favorite(_fav(), [])
    assert added and len(favs) == 1
    assert len(favorites.load_favorites()) == 1
    favs, added = favorites.toggle_favorite(_fav(), favs)
    assert not added and favs == []
    assert favorites.load_favorites() == []


def test_add_dedups_by_url(app_data):
    favs = favorites.add_favorite(_fav(), [])
    favs = favorites.add_favorite(_fav(subtitle="different"), favs)
    assert len(favs) == 1


def test_key_combines_repo_type_and_url():
    assert _fav().key == "o/r|issue|https://github.com/o/r/issues/1"


# ── Pinned repos ───────────────────────────────────────────────────────


def test_pinned_round_trip_case_insensitive(app_data):
    assert pinned_repos.load_pinned() == []
    assert pinned_repos.add_pinned("Owner/Repo") == ["Owner/Repo"]
    assert pinned_repos.add_pinned("owner/repo") == ["Owner/Repo"]
    assert pinned_repos.add_pinned("o/other") == ["Owner/Repo", "o/other"]
    assert pinned_repos.remove_pinned("OWNER/REPO") == ["o/other"]
    assert pinned_repos.load_pinned() == ["o/other"]


def test_pinned_ignores_junk(app_data):
    (app_data / "pinned_repos.json").write_text(json.dumps(["o/r", "", 5, None]), encoding="utf-8")
    assert pinned_repos.load_pinned() == ["o/r"]
    (app_data / "pinned_repos.json").write_text("nope", encoding="utf-8")
    assert pinned_repos.load_pinned() == []



def test_hidden_round_trip_case_insensitive(app_data):
    assert pinned_repos.load_hidden() == []
    assert pinned_repos.hide_repo("Me/A") == ["Me/A"]
    assert pinned_repos.hide_repo("me/a") == ["Me/A"]
    assert pinned_repos.hide_repo("me/b") == ["Me/A", "me/b"]
    assert pinned_repos.unhide_repos(["ME/A", "not/there"]) == ["me/b"]
    assert pinned_repos.load_hidden() == ["me/b"]
    (app_data / "hidden_repos.json").write_text("nope", encoding="utf-8")
    assert pinned_repos.load_hidden() == []
