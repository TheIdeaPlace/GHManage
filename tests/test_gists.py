"""Gists (#90): your gists in the repository list, like Starred, and their
files' text in the details panel, Alt+N and Alt+P between files."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import gh_data
import gistview
from gh_data import GhError, Gist, GistFile

ROW = {
    "id": "abc123", "description": "Build notes", "public": False,
    "html_url": "https://gist.github.com/me/abc123", "comments": 2,
    "created_at": "2026-01-02T10:00:00Z", "updated_at": "2026-10-01T10:00:00Z",
    "owner": {"login": "me"}, "truncated": False,
    "files": {"notes.md": {"filename": "notes.md", "language": "Markdown", "size": 1300,
                           "raw_url": "r1"},
              "run.sh": {"filename": "run.sh", "language": "Shell", "size": 20,
                         "raw_url": "r2"}},
}


def test_your_gists_are_listed_without_their_text(fake_gh):
    fake_gh.route("api gists?", [ROW, dict(ROW, id="", files={})])
    [g] = gh_data.fetch_gists(100)
    assert fake_gh.calls == [["api", "gists?per_page=100&page=1"]]
    assert (g.id, g.title, g.visibility, g.owner, g.comments) == (
        "abc123", "Build notes", "Secret", "me", 2)
    assert [f.name for f in g.files] == ["notes.md", "run.sh"]
    assert g.files[0].content is None and not g.loaded
    assert g.to_row(["title", "files", "visibility", "updated", "comments"]) == {
        "title": "Build notes", "files": "notes.md, run.sh", "visibility": "Secret",
        "updated": "2026-10-01", "comments": "2"}


def test_a_gist_without_a_description_is_named_by_its_first_file():
    g = gh_data._parse_gist(dict(ROW, description=""))
    assert g.title == "notes.md"
    assert gh_data._parse_gist(dict(ROW, description="  ", files={})).title == "abc123"


def test_one_gist_is_read_with_its_files(fake_gh):
    files = {"notes.md": dict(ROW["files"]["notes.md"], content="# A\ntext\n"),
             "big.txt": {"filename": "big.txt", "size": 2_000_000, "truncated": True,
                         "content": "start"}}
    fake_gh.route("gists/abc123", dict(ROW, files=files, truncated=True))
    g = gh_data.fetch_gist("abc123")
    assert g.loaded and g.files_truncated
    assert g.files[0].content == "# A\ntext\n" and g.files[1].truncated


def test_the_count_for_the_entry(fake_gh):
    fake_gh.route("-i gists?per_page=1",
                  'HTTP/2.0 200 OK\nLink: <https://api.github.com/gists?per_page=1&page=7>; '
                  'rel="last"\n\n[]')
    assert gh_data.count_gists() == 7


# ── Reading one ────────────────────────────────────────────────────────


def _loaded(*files, cut=False):
    return Gist("abc", "Notes", public=True, files=list(files), url="https://gist/abc",
                loaded=True, files_truncated=cut, comments=1)


def test_each_file_is_headed_by_its_name_and_alt_n_stops_there():
    g = _loaded(GistFile("a.md", 1300, "Markdown", content="# A\ntext\n"),
                GistFile("b.sh", 5, "Shell", content="ls\n"))
    text, stops = gistview.gist_text(g)
    lines = text.split("\n")
    assert [lines[i] for i in stops] == ["File 1 of 2: a.md — Markdown, 1.3 KB",
                                         "File 2 of 2: b.sh — Shell, 5 bytes"]
    assert lines[stops[0] + 1:stops[0] + 3] == ["# A", "text"]   # a line out per line in
    assert lines[stops[1] + 1] == "ls"
    assert lines[0] == "Gist: Notes" and "Public, 2 files" in lines


def test_before_the_text_comes_it_says_so():
    g = Gist("abc", "Notes", files=[GistFile("a.md")])
    text, stops = gistview.gist_text(g)
    assert text.endswith("Getting the files' text…") and stops == []


@pytest.mark.parametrize("f, said", [
    (GistFile("x", 2, content=""), ["(empty)"]),
    (GistFile("x", 2_000_000), ["Too large to show here."]),
    (GistFile("x", 2, content="\x00\x01"), ["Not text."]),
    (GistFile("x", 2_000_000, content="a\n", truncated=True),
     ["a", "", "GitHub sent only the start of x; the rest is on GitHub."]),
])
def test_files_that_cannot_be_shown_whole_say_so(f, said):
    assert gistview.file_body(f) == said


def test_a_gist_with_more_files_than_github_lists_says_so():
    text, _ = gistview.gist_text(_loaded(GistFile("a", content="x"), cut=True))
    assert text.endswith("GitHub listed only some of this gist's files; "
                         "the rest are on GitHub.")


def test_a_long_description_is_kept_whole():
    g = Gist("abc", "First line\nsecond line", files=[], loaded=True)
    lines = gistview.gist_text(g)[0].split("\n")
    assert lines[:4] == ["Gist: First line", "Description:", "First line", "second line"]


def test_status():
    gists = [Gist("a", public=False), Gist("b")]
    assert gistview.status_message(gists, 100) == "Gists — 2 gists, 1 secret."
    assert gistview.status_message(gists, 2).endswith("Ctrl++ loads more.")
    assert gistview.status_message([], 100) == "Gists — you have no gists."


# ── In the window ──────────────────────────────────────────────────────

if os.environ.get("CI"):
    import wx  # noqa: F401
else:
    pytest.importorskip("wx")

import announce  # noqa: E402
import ghviewer  # noqa: E402

Frame = ghviewer.GhViewerFrame


class FakeText:
    def __init__(self) -> None:
        self.value = ""
        self.insertion = 0

    def SetValue(self, v): self.value = v
    def GetValue(self): return self.value
    def Clear(self): self.value = ""
    def GetInsertionPoint(self): return self.insertion
    def SetInsertionPoint(self, p): self.insertion = p
    def GetLastPosition(self): return len(self.value)


def _frame(**attrs):
    f = SimpleNamespace(
        details_text=FakeText(), items=[], git_items=[], repo=None, current_limit=100,
        view_mode=ghviewer.VIEW_GISTS, status=[], told=[], events=[],
        _detail_gen=1, _category_counts={}, _comment_positions=[], _current_comment=-1,
        _fetch_is_current=lambda token: token == 1,
        _populate_filtered_list=lambda items, use_favorite_prefix=False: list(items),
        _update_title=lambda: None, _focus_list=lambda row: None,
        _refresh_category_labels=lambda: None,
    )
    f._set_view_status = lambda message, keys="": f.status.append((message, keys))
    f._tell = f.told.append
    f._announce = f.events.append
    f._render_gist = lambda item: Frame._render_gist(f, item)
    f._fetch_gist_later = lambda item, gen: f.events.append(("fetch", item.id, gen))
    f._shows = lambda view, item, gen: Frame._shows(f, view, item, gen)
    f._focused = None
    f._focused_item = lambda: f._focused
    f.FindFocus = lambda: None
    for k, v in attrs.items():
        setattr(f, k, v)
    return f


def test_the_view_is_wired_up():
    v = ghviewer.VIEW_GISTS
    assert ghviewer.VIEW_COLUMNS[v] is ghviewer.GIST_SET
    assert v in ghviewer.REPOLESS_VIEWS and v in ghviewer.FEED_VIEWS
    assert ghviewer.VIEW_ENTRIES[v] == ghviewer.GISTS_ENTRY
    assert (ghviewer.GISTS_ENTRY, "Gists") in ghviewer.CATEGORY_ENTRIES
    assert ghviewer.COUNTED_ENTRIES[ghviewer.GISTS_ENTRY] is ghviewer.count_gists
    headings = [c.heading for c in ghviewer.GIST_SET.defs(list(ghviewer.GIST_SET.defaults))]
    assert headings == ["Gist", "Files", "Visibility", "Updated"]
    assert Frame._nav_noun(SimpleNamespace(view_mode=v)) == "file"


def test_loaded_lists_them_and_counts_the_entry(monkeypatch):
    later = []
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda ms, fn, *a: later.append(a))
    f = _frame()
    gists = [Gist("a"), Gist("b", public=False)]
    Frame._on_gists_loaded(f, 2, gists, None)
    assert f.git_items == []  # a load the user moved on from
    Frame._on_gists_loaded(f, 1, gists, None)
    assert f.git_items == gists and later == [(0,)]
    assert f._category_counts == {ghviewer.GISTS_ENTRY: 2}
    assert f.status[-1] == ("Gists — 2 gists, 1 secret.",
                            "Enter=read  Ctrl+O=open on GitHub  Alt+N/Alt+P=next/previous file  "
                            "Ctrl++=view more  R=refresh  Ctrl+F=filter")


def test_a_full_page_keeps_the_fetched_count(monkeypatch):
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda *a: None)
    f = _frame(current_limit=2)
    Frame._on_gists_loaded(f, 1, [Gist("a"), Gist("b")], 40)
    assert f._category_counts == {ghviewer.GISTS_ENTRY: 40}


def test_no_gists_is_said(monkeypatch):
    spoken = []
    monkeypatch.setattr(announce, "announce", lambda text, *a, **k: spoken.append(text))
    f = _frame()
    Frame._on_gists_loaded(f, 1, [], None)
    assert spoken == ["Gists — you have no gists."]
    assert f.details_text.value.startswith("You have no gists.")
    assert f.status[-1][1] == "R=refresh"


def test_selecting_one_shows_it_and_reads_its_files_later():
    g = Gist("abc", "Notes", files=[GistFile("a.md")])
    f = _frame(git_items=[g])
    Frame._show_gist_details(f, 0)
    assert f.details_text.value.endswith("Getting the files' text…")
    assert f.events[-1] == ("fetch", "abc", 1)


def test_a_gist_read_before_is_not_read_again():
    g = _loaded(GistFile("a.md", content="x"))
    f = _frame(git_items=[g])
    Frame._show_gist_details(f, 0)
    assert "File 1 of 1: a.md" in f.details_text.value and not f.events
    assert f._comment_positions and f._comment_positions[0][1] == 1


def _fetched():
    return _loaded(GistFile("a.md", 3, content="# A\n"), GistFile("b", 1, content="b"))


def test_files_that_arrive_are_shown_and_kept():
    g = Gist("abc", "Notes", files=[GistFile("a.md")])
    f = _frame(git_items=[g])
    f._focused = g
    Frame._on_gist_fetched(f, 1, g, _fetched(), "")
    assert g.loaded and [x.content for x in g.files] == ["# A\n", "b"]
    assert "File 2 of 2: b" in f.details_text.value
    assert len(f._comment_positions) == 2


def test_files_that_arrive_after_you_moved_on_are_kept_not_shown():
    g = Gist("abc", "Notes", files=[GistFile("a.md")])
    f = _frame(git_items=[g], _detail_gen=2)
    f._focused = g
    Frame._on_gist_fetched(f, 1, g, _fetched(), "")
    assert g.loaded and f.details_text.value == ""


def test_files_arriving_while_you_read_are_said(monkeypatch):
    spoken = []
    monkeypatch.setattr(announce, "announce", lambda text, *a, **k: spoken.append(text))
    g = Gist("abc", "Notes", files=[GistFile("a.md")])
    f = _frame(git_items=[g])
    f._focused = g
    f.FindFocus = lambda: f.details_text
    Frame._on_gist_fetched(f, 1, g, _fetched(), "")
    assert spoken == ["Files here: 2."]


def test_files_that_could_not_be_read_say_why(monkeypatch):
    spoken = []
    monkeypatch.setattr(announce, "announce", lambda text, *a, **k: spoken.append(text))
    g = Gist("abc", "Notes", files=[GistFile("a.md")])
    f = _frame(git_items=[g])
    f._focused = g
    Frame._render_gist(f, g)
    f.FindFocus = lambda: f.details_text
    Frame._on_gist_fetched(f, 1, g, None, "HTTP 502")
    assert f.details_text.value.endswith("Couldn't get the files of Notes: HTTP 502")
    assert "Getting the files' text" not in f.details_text.value
    assert spoken == ["Couldn't get the files of Notes: HTTP 502"] and not g.loaded


def test_copy_and_favorite():
    g = Gist("abc", "Notes", url="https://gist/abc")
    v = ghviewer.copy_values(g)
    assert (v.link, v.title, v.ident, v.ident_noun) == ("https://gist/abc", "Notes", "abc",
                                                        "Gist ID")
    f = _frame(_focused_item=lambda: g)
    Frame._toggle_favorite(f)
    assert f.told == ["Gists can't be favorites. Ctrl+Shift+C copies its link."]


def test_the_gist_in_front_is_no_repository():
    f = _frame()
    f._pane_index = lambda w: 1
    f._current_focus = lambda: None
    f._focused_item = lambda: Gist("abc")
    assert Frame._repo_in_front(SimpleNamespace(
        _repo_in_front_from=lambda: Frame._repo_in_front_from(f))) is None


def test_a_failed_read_is_on_the_status_bar_while_you_are_in_the_list():
    g = Gist("abc", "Notes", files=[GistFile("a.md")])
    f = _frame(git_items=[g])
    f._focused = g
    Frame._render_gist(f, g)
    Frame._on_gist_fetched(f, 1, g, None, "HTTP 502")
    assert f.events[-1] == "Couldn't get the files of Notes: HTTP 502"


def _more_frame(n, limit):
    f = _frame(current_limit=limit, page_size=100, git_items=[Gist(str(i)) for i in range(n)],
               _activity_more=False, _notif_more=False, _pending_focus_row=0)
    f._shown = list(f.git_items)
    f._load_items = lambda: f.events.append(("load", f.current_limit, f._pending_focus_row))
    return f


def test_view_more_loads_the_next_page_and_lands_on_it():
    f = _more_frame(100, 100)
    Frame.on_view_more(f, None)
    assert f.events == [("load", 200, 100)]


def test_view_more_with_every_gist_listed_says_so():
    f = _more_frame(3, 100)
    Frame.on_view_more(f, None)
    assert f.events == ["That is all your gists."]


def test_a_gist_too_long_to_show_whole_names_the_rest(monkeypatch):
    monkeypatch.setattr(gistview, "MAX_GIST_CHARS", 10)
    g = _loaded(GistFile("a", content="12345678\n"), GistFile("b", content="123456\n"))
    text, stops = gistview.gist_text(g)
    lines = text.split("\n")
    assert len(stops) == 2 and lines[stops[0] + 1] == "12345678"
    assert lines[stops[1] + 1].startswith("Not shown: this gist is too long")


def test_the_context_menu_does_not_offer_to_favorite_a_gist():
    import inspect
    src = inspect.getsource(Frame._context_entries)
    assert "Gist, InsightRow" in src
