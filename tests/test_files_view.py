"""Files (#81), File History (#82) and Blame (#83): a repository's code,
read in the details panel one line out per line in."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import codeview
import gh_data
from gh_data import BlameRange, ChangedFile, Commit, GhError, Item, RepoFile

# ── Fetching ───────────────────────────────────────────────────────────


def test_a_folder_lists_folders_first_with_each_kind(fake_gh):
    fake_gh.route("git/trees/", {"truncated": False, "tree": [
        {"path": "zeta.py", "type": "blob", "mode": "100644", "size": 12, "sha": "b1"},
        {"path": "Alpha", "type": "tree", "mode": "040000", "sha": "t1"},
        {"path": "beta.md", "type": "blob", "mode": "100644", "size": 3, "sha": "b2"},
        {"path": "link", "type": "blob", "mode": "120000", "size": 9, "sha": "b3"},
        {"path": "lib", "type": "commit", "mode": "160000", "sha": "c1"},
    ]})
    files, cut = gh_data.fetch_repo_folder("o/r", "main", "src")
    assert [(f.name, f.kind) for f in files] == [
        ("Alpha", "dir"), ("beta.md", "file"), ("lib", "submodule"),
        ("link", "link"), ("zeta.py", "file")]
    assert files[0].path == "src/Alpha" and not cut
    # GitHub has no page at a submodule's path; its folder links to it.
    assert files[2].url == "https://github.com/o/r/tree/main/src"
    assert files[0].url == "https://github.com/o/r/tree/main/src/Alpha"
    assert files[1].url == "https://github.com/o/r/blob/main/src/beta.md"
    assert fake_gh.calls[0] == ["api", "repos/o/r/git/trees/main%3Asrc"]


def test_the_top_of_a_branch_with_a_slash_in_its_name(fake_gh):
    fake_gh.route("git/trees/", {"truncated": True, "tree": [
        {"path": "a b.txt", "type": "blob", "size": 1, "sha": "x"}]})
    files, cut = gh_data.fetch_repo_folder("o/r", "feature/x", "")
    assert fake_gh.calls[0] == ["api", "repos/o/r/git/trees/feature%2Fx%3A"]
    assert files[0].path == "a b.txt" and cut
    assert files[0].url == "https://github.com/o/r/blob/feature/x/a%20b.txt"


def test_a_folder_that_is_not_there_raises(fake_gh):
    fake_gh.route("git/trees/", GhError("gh: Not Found (HTTP 404)"))
    with pytest.raises(GhError, match="404"):
        gh_data.fetch_repo_folder("o/r", "main", "gone")


def test_a_file_is_read_as_raw_text_by_its_blob(fake_gh):
    fake_gh.route("git/blobs/abc", "﻿hello\n")
    assert gh_data.fetch_blob_text("o/r", "abc") == "hello\n"
    assert fake_gh.calls[0] == ["api", "-H", "Accept: application/vnd.github.raw",
                                "repos/o/r/git/blobs/abc"]


def test_file_history_asks_for_the_path_on_the_ref(fake_gh):
    fake_gh.route("commits?path=", [
        {"sha": "a" * 40, "html_url": "u", "author": {"login": "kel"},
         "commit": {"message": "Fix it\n\nmore", "author": {"name": "Kelly", "date": "2026-09-01T00:00:00Z"}}},
        {"sha": "b" * 40, "author": {"login": "bob"}, "commit": {"message": "", "author": {}}},
    ])
    commits = gh_data.fetch_file_history("o/r", "docs/a b.md", "feature/x", 50)
    assert fake_gh.calls[0][1] == (
        "repos/o/r/commits?path=docs/a%20b.md&sha=feature%2Fx&per_page=50&page=1")
    assert (commits[0].short_sha, commits[0].message, commits[0].author) == (
        "aaaaaaaa", "Fix it", "Kelly")
    assert commits[0].date.startswith("2026-09-01") and commits[0].url == "u"
    assert commits[1].author == "bob"


def test_one_files_changes_in_a_commit(fake_gh):
    fake_gh.route("commits/abc?per_page=100&page=1", [
        {"filename": "a.py", "status": "modified", "patch": "@@ -1 +1 @@\n-a\n+b"},
        {"filename": "b.py", "status": "added"}])
    assert gh_data.fetch_commit_file("o/r", "abc", "a.py").patch.startswith("@@")
    assert gh_data.fetch_commit_file("o/r", "abc", "c.py") is None


@pytest.fixture
def graphql(monkeypatch):
    class Fake:
        def __init__(self):
            self.queries: list[str] = []
            self.replies: list = []

        def __call__(self, query):
            self.queries.append(query)
            return self.replies.pop(0) if self.replies else {"data": {}}
    fake = Fake()
    monkeypatch.setattr(gh_data, "_graphql", fake)
    return fake


def _range(start, end, oid, name="Kelly", date="2026-09-01T10:00:00-05:00", head="Fix"):
    return {"startingLine": start, "endingLine": end,
            "commit": {"oid": oid, "abbreviatedOid": oid[:7], "messageHeadline": head,
                       "author": {"name": name, "date": date, "user": {"login": "kel"}}}}


def test_blame_comes_from_graphql_in_line_order(graphql):
    graphql.replies.append({"data": {"repository": {"object": {"blame": {"ranges": [
        _range(3, 4, "b" * 40), _range(1, 2, "a" * 40, name=""),
    ]}}}}})
    ranges = gh_data.fetch_blame("o/r", 'we"ird', 'src/"q".py')
    assert [r.start for r in ranges] == [1, 3]
    assert ranges[0].author == "kel" and ranges[1].author == "Kelly"
    assert ranges[1].short_sha == "bbbbbbb" and ranges[1].headline == "Fix"
    # In UTC, as every other date in GHManage.
    assert ranges[0].date == "2026-09-01T15:00:00Z"
    q = graphql.queries[0]
    # Every value is quoted for GraphQL, so a quote in a name can't break out.
    assert 'owner: "o"' in q and 'name: "r"' in q
    assert r'expression: "we\"ird"' in q and r'path: "src/\"q\".py"' in q


def test_blame_of_a_ref_that_is_not_there(graphql):
    graphql.replies.append({"data": {"repository": {"object": None}}})
    with pytest.raises(GhError, match="isn't a branch"):
        gh_data.fetch_blame("o/r", "nope", "a.py")
    graphql.replies.append({"data": {"repository": None},
                            "errors": [{"message": "Could not resolve"}]})
    with pytest.raises(GhError, match="Could not resolve"):
        gh_data.fetch_blame("o/r", "main", "a.py")


def test_branch_and_tag_names(fake_gh):
    fake_gh.route("repos/o/r/branches", [{"name": "main"}, {"name": "dev"}])
    fake_gh.route("repos/o/r/tags", [{"name": "v1"}])
    assert gh_data.fetch_ref_names("o/r") == (["main", "dev"], ["v1"])


def test_a_pull_requests_head(fake_gh):
    fake_gh.route("headRefOid", "abc123\n")
    assert gh_data.fetch_pr_head_sha("https://github.com/o/r/pull/7") == "abc123"
    assert fake_gh.calls[0] == ["pr", "view", "https://github.com/o/r/pull/7", "--json",
                                "headRefOid", "-q", ".headRefOid"]
    with pytest.raises(GhError):
        gh_data.fetch_pr_head_sha("https://github.com/o/r/issues/7")


def test_a_files_row():
    f = RepoFile("src/app.py", "file", 2048)
    assert f.to_row(["name", "type", "size", "path"]) == {
        "name": "app.py", "type": "File", "size": "2.0 KB", "path": "src/app.py"}
    assert RepoFile("src", "dir").to_row(["type", "size"]) == {"type": "Folder", "size": ""}
    assert RepoFile("lib", "submodule").kind_display == "Submodule"


# ── As text to read ────────────────────────────────────────────────────


def test_lines_split_only_at_line_breaks():
    assert codeview.file_lines("a\r\nb\rc\n") == ["a", "b", "c"]
    # A form feed is part of its line, as the text box shows it.
    assert codeview.file_lines("a\x0cb\nc") == ["a\x0cb", "c"]
    assert codeview.file_lines("") == []
    assert codeview.file_lines("\n") == [""]


def test_binary_is_told_from_text():
    assert codeview.is_binary("PNG\x00\x01")
    assert codeview.is_binary("�" * 50 + "ab")
    assert not codeview.is_binary("héllo — wörld\n")
    assert not codeview.is_binary("")


def test_markdown_headings_skip_fenced_code():
    lines = ["# Title", "text", "```sh", "# a shell comment", "```", "## Next",
             "    # indented code", "####### seven", "#nospace", "~~~", "# x", "~~~", "### Last"]
    assert codeview.markdown_headings(lines) == [0, 5, 12]


def test_a_file_reads_one_line_out_per_line_in():
    f = RepoFile("README.md", size=40)
    text, starts = codeview.file_text(f, "# One\nbody\n## Two\n")
    lines = text.split("\n")
    assert lines == ["README.md: 3 lines.", "# One", "body", "## Two"]
    # Line N of the file is line N of the panel.
    assert [lines[i] for i in starts] == ["# One", "## Two"]


def test_only_markdown_has_headings_to_move_between():
    assert codeview.file_text(RepoFile("run.sh"), "# comment\n")[1] == []
    assert codeview.file_text(RepoFile("A.MARKDOWN"), "# h\n")[1] == [1]


@pytest.mark.parametrize("text, said", [
    ("", "f.txt: empty."),
    ("one line", "f.txt: 1 line."),
    ("\x00\x01", "f.txt: a binary file, 2 B."),
])
def test_what_a_file_says_first(text, said):
    assert codeview.file_text(RepoFile("f.txt", size=2), text)[0].split("\n")[0] == said


def test_what_rows_that_are_not_text_say():
    assert codeview.entry_text(RepoFile("src", "dir")) == (
        "src/: a folder.")
    assert codeview.entry_text(RepoFile("lib", "submodule", sha="abcdef123")) == (
        "lib: a submodule, another repository, at commit abcdef1.")
    assert codeview.entry_text(RepoFile("l", "link"), "../target\n") == "l: a link to ../target."
    big = RepoFile("big.json", size=gh_data.MAX_FILE_BYTES + 1)
    assert codeview.too_big(big) and not codeview.too_big(RepoFile("s", size=10))
    assert codeview.entry_text(big) == "big.json: 1.0 MB, too large to show here."


def test_folder_names_and_counts():
    assert codeview.folder_label("o/GHManage", "") == "GHManage/"
    assert codeview.folder_label("o/r", "src/a") == "src/a/"
    files = [RepoFile("a", "dir"), RepoFile("b", "dir"), RepoFile("c"), RepoFile("d", "link")]
    assert codeview.folder_summary(files) == "2 folders, 1 file, 1 link."
    assert codeview.folder_summary([]) == "Empty folder."
    assert codeview.folder_summary(files[:1], truncated=True) == (
        "1 folder. GitHub cut this folder's list short.")


def _blame(start, end, sha, author="Kelly", headline="Fix"):
    return BlameRange(start, end, sha, sha[:7], headline, author, "2026-09-01T10:00:00-05:00")


def test_blame_reads_in_runs_headed_by_who_and_when():
    text, starts = codeview.blame_text("a.py", "l1\nl2\nl3\nl4\n", [
        _blame(1, 2, "a" * 40), _blame(3, 3, "a" * 40), _blame(4, 4, "b" * 40, "Bob", "Add")])
    lines = text.split("\n")
    assert lines[0] == "a.py: who last changed each line, in 2 runs."
    assert [lines[i] for i in starts] == [
        "Lines 1 to 3: Kelly, 2026-09-01, aaaaaaa Fix", "Line 4: Bob, 2026-09-01, bbbbbbb Add"]
    assert lines[2:5] == ["l1", "l2", "l3"] and lines[-1] == "l4"


def test_blame_with_no_runs_says_so():
    assert codeview.blame_text("a.py", "x", []) == ("a.py: GitHub has no blame for this file.", [])


def test_a_history_commit_reads_like_changed_files():
    c = Commit("a" * 40, "aaaaaaaa", "Fix it", "Kelly", "2026-09-01T00:00:00Z")
    f = ChangedFile("a.py", additions=1, deletions=1, patch="@@ -1 +1 @@\n-a\n+b")
    text, starts = codeview.history_text(c, "a.py", f, "words")
    lines = text.split("\n")
    assert lines[0] == "Commit aaaaaaaa, Kelly, 2026-09-01: Fix it"
    assert lines[2] == "a.py: modified, 1 line added, 1 removed."
    assert [lines[i] for i in starts] == ["At line 1:"]
    assert "Removed: a" in lines and "Added: b" in lines
    assert codeview.history_text(c, "a.py", None)[0].endswith(
        "GitHub doesn't list a.py among this commit's files.")
    assert codeview.history_text(c, "a.py", None, loading=True) == (
        "Commit aaaaaaaa, Kelly, 2026-09-01: Fix it\n\n" + codeview.LOADING, [])
    assert codeview.commit_heading(Commit("b" * 40, "bbbbbbbb", "", "", "")) == "Commit bbbbbbbb"


# ── In the window ──────────────────────────────────────────────────────

if os.environ.get("CI"):
    import wx  # noqa: F401
else:
    wx = pytest.importorskip("wx")

import ghviewer  # noqa: E402

Frame = ghviewer.GhViewerFrame
CODE, HISTORY, FILES = ghviewer.VIEW_CODE, ghviewer.VIEW_HISTORY, ghviewer.VIEW_FILES


class FakeText:
    def __init__(self) -> None:
        self.value, self.selection, self.insertion = "", None, None

    def SetValue(self, v): self.value = v
    def GetValue(self): return self.value
    def Clear(self): self.value = ""
    def SetFocus(self): pass
    def SetSelection(self, a, b): self.selection = (a, b)
    def SetInsertionPoint(self, p): self.insertion = p
    def ShowPosition(self, p): pass


@pytest.fixture(autouse=True)
def _no_timers(monkeypatch):
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda *a, **k: None)


def _frame(**attrs):
    told: list[str] = []
    announced: list[str] = []
    f = SimpleNamespace(
        details_text=FakeText(), items=[], git_items=[], view_mode=CODE, repo="o/r",
        _comment_positions=[], _current_comment=-1, _diff_style="words",
        _detail_gen=0, _blob_cache={}, _patch_cache={}, filter_text="", current_limit=100,
        _files_of=None, _files_back=None, _history_of=None, _history_back=None,
        _whole_file_busy=False, _fetch_token=0, _pending_target=None,
        told=told, announced=announced, _announce=announced.append,
    )
    Frame._reset_code(f)
    f._tell = lambda msg, *a, **k: told.append(msg)
    f.calls = []
    f._load_items = lambda: f.calls.append(("load", f.view_mode, f._code_path))
    f._update_title = lambda: None
    f._update_actions_menu = lambda: None
    f._begin_fetch = lambda: Frame._begin_fetch(f)
    f._fetch_is_current = lambda token: Frame._fetch_is_current(f, token)
    f._line_to_position = lambda line: Frame._line_to_position(f, line)
    for name in ("_render_code", "_load_code", "_code_where", "_code_snapshot", "_restore_code",
                 "_on_code_loaded", "_back_from_code", "_open_code_at", "_code_file",
                 "_shows", "_keep_blob", "_render_history", "_on_blame_fetched",
                 "_set_code_ref"):
        setattr(f, name, getattr(Frame, name).__get__(f))
    f._fetch_later = lambda item, gen: f.calls.append(("fetch", item.path, gen))
    f._focused = None
    f._focused_item = lambda: f._focused
    f.FindFocus = lambda: None

    def switch(mode, load=True):
        f.calls.append(("switch", mode, load))
        if mode != CODE:
            Frame._reset_code(f)
        if mode != HISTORY:
            f._history_of = f._history_back = None
        if mode != FILES:
            f._files_of = f._files_back = None
        f.view_mode = mode
        f.filter_text = ""
    f._switch_view = switch
    for k, v in attrs.items():
        setattr(f, k, v)
    return f


def _loaded(f, entries, path="", ref="main"):
    """Files as if ``entries`` had just arrived, list and all."""
    f.status = []
    f._set_view_status = lambda msg, keys="": f.status.append((msg, keys))
    f._shown = []

    def populate(items, use_favorite_prefix=False):
        f._shown = list(items)
        return f._shown
    f._populate_filtered_list = populate
    token = f._begin_fetch()
    Frame._on_code_loaded(f, token, ref, path, entries, False, "")


SRC = [RepoFile("src/a", "dir"), RepoFile("src/x.py", size=10, sha="s1"),
       RepoFile("src/README.md", size=10, sha="s2")]


def test_a_folder_arrives_named_with_its_keys():
    f = _frame(_code_path="src", _code_stack=[""])
    _loaded(f, SRC, path="src")
    msg, keys = f.status[-1]
    assert msg == "src/ on main — 1 folder, 2 files."
    assert "H=history  B=blame" in keys and keys.endswith("Backspace=up a folder")
    assert f._code_ref == "main" and f._code_at == "on main"
    assert f._code_folders[("o/r", "main", "src")] == (SRC, False)


def test_at_the_top_backspace_is_not_offered():
    f = _frame()
    _loaded(f, SRC[:1])
    assert "Backspace" not in f.status[-1][1]


def test_a_late_folder_is_dropped():
    f = _frame()
    f._set_view_status = lambda *a: pytest.fail("should be dropped")
    Frame._on_code_loaded(f, 99, "main", "", SRC, False, "")
    assert f.git_items == []


def test_a_missing_folder_becomes_the_top_and_forgets_the_way_up():
    f = _frame(_code_path="gone", _code_stack=["", "x"])
    _loaded(f, SRC, path="")
    assert f._code_path == "" and f._code_stack == []


def test_enter_on_a_folder_goes_in_and_backspace_lands_on_it():
    f = _frame(_code_ref="main")
    Frame._code_open_folder(f, RepoFile("src", "dir"))
    assert f._code_path == "src" and f._code_stack == [""]
    assert f.calls[-1] == ("load", CODE, "src")
    Frame._code_up(f)
    assert f._code_path == "" and f._code_land == "src"


def test_up_from_a_folder_reached_another_way_goes_to_its_parent():
    f = _frame(_code_path="a/b/c")
    Frame._code_up(f)
    assert (f._code_path, f._code_land) == ("a/b", "a/b/c")


def test_backspace_at_the_top_says_so():
    f = _frame()
    Frame._code_up(f)
    assert f.told == ["This is the top of the repository."] and f.calls == []


def test_backspace_at_the_top_goes_back_to_the_list_files_was_opened_from():
    f = _frame(_return_to=("starred", [], False, None, 100), _return_view=CODE)
    f._return_to_list = lambda: f.calls.append("returned")
    Frame._code_up(f)
    assert f.calls == ["returned"] and f.told == []


def test_a_filter_is_for_one_folder():
    f = _frame(filter_text="py", _code_path="src", _code_stack=[""])
    Frame._code_up(f)
    assert f.filter_text == ""
    f.filter_text = "md"
    Frame._code_open_folder(f, RepoFile("docs", "dir"))
    assert f.filter_text == ""


def test_a_folder_read_this_visit_is_not_read_again():
    f = _frame(_code_ref="main", _code_path="src", _code_stack=[""])
    _loaded(f, SRC, path="src")
    f.calls.clear()
    Frame._code_up(f)                       # the top, not read yet
    assert f.calls == [("load", CODE, "")]
    _loaded(f, [RepoFile("src", "dir")], path="")
    Frame._code_open_folder(f, RepoFile("src", "dir"))
    assert f.git_items == SRC and ("load", CODE, "src") not in f.calls[1:]


def test_the_folder_lands_on_the_entry_asked_for(monkeypatch):
    later = []
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda ms, fn: later.append(fn))
    monkeypatch.setattr(ghviewer.announce, "announce", lambda *a: f.calls.append(("said",) + a))
    f = _frame(_code_land="src/x.py", _code_path="src", _code_stack=[""])
    f._focus_list = lambda row: f.calls.append(("focus", row))
    _loaded(f, SRC, path="src")
    later[0]()
    assert ("focus", 1) in f.calls
    assert ("said", "src/ 1 folder, 2 files.", "status") in f.calls


def test_a_markdown_file_shows_its_text_and_headings():
    f = _frame(git_items=SRC, _blob_cache={"s2": "# A\ntext\n## B\n"})
    Frame._show_code_details(f, 2)
    assert f.details_text.value.split("\n")[0] == "src/README.md: 3 lines."
    assert f._comment_positions == [(1, 1), (3, 1)]
    Frame._navigate_comment(f, 1)
    a, b = f.details_text.selection
    assert f.details_text.value[a:b] == "# A" and f.announced[-1] == "Heading 1 of 2"


def test_a_file_not_read_yet_is_fetched():
    f = _frame(git_items=SRC, _detail_gen=4)
    Frame._show_code_details(f, 1)
    assert f.details_text.value == "src/x.py: getting the text…"
    assert f.calls[-1] == ("fetch", "src/x.py", 4)


def test_text_that_arrives_after_you_moved_on_is_kept_but_not_shown():
    f = _frame(git_items=SRC, _detail_gen=5)
    f._focused = SRC[1]
    Frame._on_blob_fetched(f, 4, SRC[1], "print()\n", "")
    assert f._blob_cache["s1"] == "print()\n" and f.details_text.value == ""
    Frame._on_blob_fetched(f, 5, SRC[1], "print()\n", "")
    assert f.details_text.value == "src/x.py: 1 line.\nprint()"


def test_text_that_could_not_be_had_says_why():
    f = _frame(git_items=SRC, _detail_gen=1)
    f._focused = SRC[1]
    Frame._on_blob_fetched(f, 1, SRC[1], None, "HTTP 500")
    assert f.details_text.value == "src/x.py: couldn't get the text. HTTP 500"


def test_folders_and_big_files_are_not_fetched():
    big = RepoFile("big.bin", size=gh_data.MAX_FILE_BYTES + 1, sha="z")
    f = _frame(git_items=[SRC[0], big])
    Frame._show_code_details(f, 0)
    Frame._show_code_details(f, 1)
    assert "too large" in f.details_text.value and not [c for c in f.calls if c[0] == "fetch"]


@pytest.mark.parametrize("item, said", [
    (None, "Select a file first."),
    (RepoFile("src", "dir"), "Blame is for a file. src is a folder."),
    (RepoFile("l", "link"), "Blame is for a file. l is a link."),
])
def test_blame_needs_a_file(item, said):
    f = _frame()
    f._focused = item
    Frame._toggle_blame(f)
    assert f.told == [said]


def test_blame_is_only_for_text():
    f = _frame(_blob_cache={"s1": "\x00\x00"})
    f._focused = SRC[1]
    Frame._toggle_blame(f)
    assert f.told == ["x.py isn't text to blame line by line."]


def test_blame_shows_in_runs_and_b_again_shows_the_file():
    f = _frame(git_items=SRC, _code_ref="main", _blob_cache={"s1": "a\nb\n"})
    f._focused = SRC[1]
    f._blame_cache[("o/r", "main", "src/x.py", "s1")] = [_blame(1, 2, "c" * 40)]
    Frame._toggle_blame(f)
    assert f.details_text.value.split("\n")[1] == "Lines 1 to 2: Kelly, 2026-09-01, ccccccc Fix"
    assert f._code_blame is SRC[1] and Frame._nav_noun(f) == "run"
    assert f.told[-1] == "Blame of x.py: 1 run of lines."
    Frame._show_code_details(f, 1)         # the same row again keeps the blame
    assert f.details_text.value.startswith("src/x.py: who last changed")
    Frame._toggle_blame(f)
    assert f.details_text.value == "src/x.py: 2 lines.\na\nb"
    assert f._code_blame is None and f.told[-1] == "Showing x.py again."


def test_another_row_leaves_the_blame():
    f = _frame(git_items=SRC, _blob_cache={"s1": "a\n", "s2": "b\n"})
    f._code_blame = SRC[1]
    Frame._show_code_details(f, 2)
    assert f._code_blame is None and Frame._nav_noun(f) == "heading"


def test_a_failed_blame_is_said():
    f = _frame(_detail_gen=2)
    f._focused = SRC[1]
    Frame._on_blame_fetched(f, 2, SRC[1], ("o/r", "main", "src/x.py"), None, None, "boom")
    assert f.told == ["Couldn't get the blame of x.py: boom"]


@pytest.mark.parametrize("view, noun", [
    (FILES, "change"), (HISTORY, "change"), (CODE, "heading"), (ghviewer.VIEW_ISSUES, "comment")])
def test_what_alt_n_moves_between(view, noun):
    assert Frame._nav_noun(_frame(view_mode=view)) == noun


# ── History ────────────────────────────────────────────────────────────

C1 = Commit("a" * 40, "aaaaaaaa", "Fix it", "Kelly", "2026-09-01T00:00:00Z", url="u")


def test_history_is_for_a_file():
    f = _frame()
    f._focused = SRC[0]
    Frame._show_file_history(f)
    assert f.told == ["File History is for a file. a is a folder."]


def test_history_and_back_to_the_file():
    f = _frame(_code_ref="main", _code_at="on main", _code_path="src", _code_stack=[""],
               git_items=list(SRC), filter_text="x")
    f._focused = SRC[1]
    Frame._show_file_history(f)
    assert f.view_mode == HISTORY and f._history_of == ("main", "src/x.py", "on main")
    assert f.calls[-1] == ("load", HISTORY, "")
    snap = f._history_back
    assert snap["items"] == SRC and snap["item"] is SRC[1] and snap["stack"] == [""]

    restored = []
    f._on_code_loaded = lambda token, ref, path, items, cut, note: restored.append(
        (ref, path, items, f._code_land, f._code_stack, f.filter_text))
    Frame._back_from_history(f)
    assert f.view_mode == CODE and f._history_of is None
    assert restored == [("main", "src", SRC, "src/x.py", [""], "x")]
    assert f.announced[-1] == "Back to files"


def test_a_history_commit_is_fetched_once_and_shown_when_it_arrives():
    f = _frame(view_mode=HISTORY, git_items=[C1], _history_of=("main", "a.py", "on main"),
               _detail_gen=3)
    f._focused = C1
    Frame._show_history_details(f, 0)
    assert f.details_text.value.endswith(codeview.LOADING)
    changed = ChangedFile("a.py", additions=1, patch="@@ -0,0 +1 @@\n+x")
    Frame._on_patch_fetched(f, 3, C1, (C1.sha, "a.py"), changed, "")
    assert "Added: x" in f.details_text.value and f._comment_positions == [(4, 1)]
    assert f._patch_cache[(C1.sha, "a.py")] is changed


def test_a_history_commit_that_could_not_be_had():
    f = _frame(view_mode=HISTORY, _history_of=("main", "a.py", "on main"), _detail_gen=1)
    f._focused = C1
    Frame._on_patch_fetched(f, 1, C1, (C1.sha, "a.py"), None, "HTTP 502")
    assert f.details_text.value.endswith("Couldn't get the changes. HTTP 502")
    assert (C1.sha, "a.py") not in f._patch_cache


def test_history_loads_say_how_many(monkeypatch):
    f = _frame(view_mode=HISTORY, _history_of=("main", "a.py", "on main"))
    f.status = []
    f._set_view_status = lambda msg, keys="": f.status.append((msg, keys))
    f._populate_filtered_list = lambda items, use_favorite_prefix=False: list(items)
    f._take_pending_row = lambda items, token: 0
    token = f._begin_fetch()
    Frame._on_history_loaded(f, token, [C1])
    msg, keys = f.status[-1]
    assert msg == "History of a.py on main — 1 commit. Showing up to 100."
    assert keys.startswith("Enter=changed files") and keys.endswith("Backspace=back to files")


def test_changed_files_from_history_comes_back_to_it():
    f = _frame(view_mode=HISTORY, git_items=[C1], _history_of=("main", "a.py", "on main"),
               _history_back={"files": True}, label_filter="", commit_branch="",
               _branches_unread=0, _return_to=None, _return_view=ghviewer.VIEW_ISSUES)
    f._focused = C1
    f._view_source = lambda: f.git_items
    Frame._show_changed_files(f)
    assert f.view_mode == FILES and f._files_of is C1
    assert f._files_back["history_of"] == ("main", "a.py", "on main")

    loaded = []
    f._set_pending_target = lambda *a: None
    f._on_history_loaded = lambda token, items: loaded.append(items)
    f._view_label = lambda v, lower=False: Frame._view_label(f, v, lower)
    f._VIEW_LABELS, f._org = Frame._VIEW_LABELS, ""
    Frame._back_from_files(f)
    assert f.view_mode == HISTORY and loaded == [[C1]]
    assert f._history_of == ("main", "a.py", "on main") and f._history_back == {"files": True}
    assert f._pending_target[2:] == ("same", C1)


# ── Whole file from Changed Files ──────────────────────────────────────

PR = Item(7, "Fix", "OPEN", "https://github.com/o/r/pull/7", is_pr=True)


def test_a_deleted_file_cannot_be_opened_whole():
    f = _frame(view_mode=FILES, _files_of=C1)
    f._focused = ChangedFile("gone.py", status="removed")
    Frame._open_whole_file(f)
    assert f.told == ["gone.py is deleted by this change, so there is no whole file to open."]


def test_whole_file_needs_changed_files():
    f = _frame(view_mode=CODE)
    Frame._open_whole_file(f)
    assert f.told == ["Open Whole File is for a file in Changed Files."]


def test_whole_file_of_a_commit_opens_its_folder_on_it_and_comes_back():
    changed = ChangedFile("src/x.py")
    f = _frame(view_mode=FILES, _files_of=C1, _files_back={"view": "commits"},
               git_items=[changed], filter_text="x")
    f._focused = changed
    Frame._open_whole_file(f)
    assert f.view_mode == CODE and f.calls[-1] == ("load", CODE, "src")
    assert (f._code_ref, f._code_at, f._code_land) == (C1.sha, "at commit aaaaaaaa", "src/x.py")

    loaded = []
    f._on_files_loaded = lambda token, items: loaded.append(items)
    Frame._code_up(f)
    assert f.view_mode == FILES and loaded == [[changed]]
    assert f._files_of is C1 and f._files_back == {"view": "commits"} and f.filter_text == "x"
    assert f._pending_target[1:] == (FILES, "same", changed)


def test_whole_file_of_a_pull_request_finds_its_head_first(monkeypatch):
    started = []
    monkeypatch.setattr(ghviewer.threading, "Thread",
                        lambda target, daemon: SimpleNamespace(start=lambda: started.append(target)))
    changed = ChangedFile("x.py")
    f = _frame(view_mode=FILES, _files_of=PR, git_items=[changed])
    f._focused = changed
    Frame._open_whole_file(f)
    Frame._open_whole_file(f)
    assert len(started) == 1 and f.told == ["Still finding the pull request's latest commit."]
    Frame._on_head_sha(f, changed, PR, "f" * 40, "")
    assert f.view_mode == CODE and f._code_at == "at PR #7, ffffffff" and f._code_path == ""


def test_a_head_that_arrives_after_you_left_is_ignored():
    f = _frame(view_mode=ghviewer.VIEW_ISSUES, _whole_file_busy=True)
    Frame._on_head_sha(f, ChangedFile("x.py"), PR, "f" * 40, "")
    assert f.view_mode == ghviewer.VIEW_ISSUES and not f._whole_file_busy


# ── Branch or tag ──────────────────────────────────────────────────────


def test_another_branch_keeps_the_folder_and_the_entry():
    f = _frame(_code_ref="main", _code_path="src")
    f._focused = SRC[1]
    Frame._set_code_ref(f, "v1", "at tag v1")
    assert (f._code_ref, f._code_at, f._code_path, f._code_land) == (
        "v1", "at tag v1", "src", "src/x.py")
    assert f.calls[-1] == ("load", CODE, "src") and f.told == ["Files at tag v1."]


def test_the_picker_offers_branches_then_tags(monkeypatch):
    shown = {}

    class Dlg:
        def __init__(self, parent, msg, title, names):
            shown["names"] = names
        def SetSelection(self, i): shown["sel"] = i
        def ShowModal(self): return ghviewer.wx.ID_OK
        def GetSelection(self): return 2
        def Destroy(self): pass

    monkeypatch.setattr(ghviewer.wx, "SingleChoiceDialog", Dlg)
    f = _frame(_code_ref="dev")
    chosen = []
    f._set_code_ref = lambda ref, at: chosen.append((ref, at))
    Frame._show_code_ref_picker(f, "o/r", ["main", "dev"], ["v1"])
    assert shown == {"names": ["main", "dev", "v1 (tag)"], "sel": 1}
    assert chosen == [("v1", "at tag v1")]


def test_the_picker_for_a_repository_you_have_left_does_not_open(monkeypatch):
    monkeypatch.setattr(ghviewer.wx, "SingleChoiceDialog", lambda *a: pytest.fail("opened"))
    Frame._show_code_ref_picker(_frame(), "x/y", ["main"], [])


def test_select_branch_elsewhere_says_where_it_works():
    f = _frame(view_mode=ghviewer.VIEW_TAGS)
    Frame.on_select_branch(f, None)
    assert f.told == ["Select Branch is for the Commits and Files views."]


def test_copy_and_favorite_of_a_file():
    v = ghviewer.copy_values(RepoFile("src/x.py", url="https://github.com/o/r/blob/main/src/x.py"))
    assert (v.ident, v.ident_noun, v.title) == ("src/x.py", "Path", "src/x.py")
    f = _frame(_code_at="on main")
    f._code_where = lambda: "src/ on main"
    entry = Frame._build_favorite_entry(f, RepoFile("src/x.py", url="u"))
    assert (entry.item_type, entry.title, entry.subtitle) == ("file", "src/x.py", "src/ on main")


def test_history_and_back_keeps_the_way_back_to_a_repository_list():
    back_to = ("starred", [], False, None, 100)
    f = _frame(_code_ref="main", _code_at="on main", git_items=list(SRC),
               _return_to=back_to, _return_view=CODE)
    f._focused = SRC[1]
    snap = Frame._code_snapshot(f, SRC[1])
    f._return_to = None                  # what _switch_view does on the way to History
    f._on_code_loaded = lambda *a: None
    Frame._restore_code(f, snap)
    assert f._return_to == back_to and f._return_view == CODE


def test_a_second_b_while_blame_is_on_its_way(monkeypatch):
    started = []
    monkeypatch.setattr(ghviewer.threading, "Thread",
                        lambda target, daemon: SimpleNamespace(start=lambda: started.append(target)))
    monkeypatch.setattr(ghviewer.announce, "announce", lambda *a: None)
    f = _frame(_code_ref="main")
    f._focused = SRC[1]
    Frame._toggle_blame(f)
    Frame._toggle_blame(f)
    assert len(started) == 1 and f.told == ["Still getting the blame."]
    Frame._on_blame_fetched(f, 99, SRC[1], ("o/r", "main", "src/x.py", "s1"), [], "x", "")
    assert f._blame_busy is False


def test_refresh_reads_folders_and_blame_afresh():
    f = _frame(_code_ref="main")
    f._code_folders[("o/r", "main", "")] = ([], False)
    f._blame_cache[("o/r", "main", "a", "s")] = []
    f.page_size = 100
    Frame.on_refresh(f, None)
    assert f._code_folders == {} and f._blame_cache == {}
    assert f.calls[-1] == ("load", CODE, "")


def test_a_head_for_a_file_you_moved_off_is_not_opened():
    first, second = ChangedFile("a.py"), ChangedFile("b.py")
    f = _frame(view_mode=FILES, _files_of=PR, _whole_file_busy=True)
    f._focused = second
    Frame._on_head_sha(f, first, PR, "f" * 40, "")
    assert f.view_mode == FILES


def test_line_positions():
    f = _frame()
    f.details_text.value = "ab\ncd\n\nef"
    assert [Frame._line_to_position(f, n) for n in range(5)] == [0, 3, 6, 7, 9]
