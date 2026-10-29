"""Changed Files (#78): a pull request's or commit's files, each file's lines
marked by app-kit's difftext, the marking style setting, and Copy and Open
Diff."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import diffview
import gh_data
import settings
from gh_data import ChangedFile, GhError

PR = "https://github.com/o/r/pull/7"

PATCH = (
    "@@ -1,3 +1,3 @@\n"
    " def foo():\n"
    "-    return 1\n"
    "+    return 2\n"
    " \n"
    "@@ -10,2 +10,3 @@ class X:\n"
    " a\n"
    "+b\n"
    " c"
)


def _file(**kw) -> ChangedFile:
    base = dict(filename="src/app.py", status="modified", additions=2, deletions=1, patch=PATCH)
    base.update(kw)
    return ChangedFile(**base)


# ── Fetching ───────────────────────────────────────────────────────────


def _api_file(name, **kw):
    row = {"filename": name, "status": "modified", "additions": 1, "deletions": 0,
           "patch": "@@ -1 +1 @@\n-a\n+b", "blob_url": f"https://github.com/o/r/blob/x/{name}"}
    row.update(kw)
    return row


def test_pr_files_are_read_page_by_page(fake_gh):
    first = [_api_file(f"f{i}") for i in range(100)]
    fake_gh.route("pulls/7/files?per_page=100&page=1", first)
    fake_gh.route("pulls/7/files?per_page=100&page=2", [_api_file("last")])
    files = gh_data.fetch_pr_files(PR)
    assert len(files) == 101 and files[-1].filename == "last"
    assert files[0].url.endswith("/f0") and files[0].patch.startswith("@@")
    # The repository comes from the pull request's address, not the one open.
    assert all("repos/o/r/pulls/7/files" in " ".join(c) for c in fake_gh.calls)


def test_pr_files_without_a_patch_or_with_a_rename(fake_gh):
    fake_gh.route("pulls/7/files", [
        {"filename": "logo.png", "status": "added", "additions": 0, "deletions": 0},
        _api_file("new.md", status="renamed", previous_filename="old.md"),
    ])
    logo, renamed = gh_data.fetch_pr_files(PR)
    assert logo.patch is None and logo.status_display == "Added"
    assert renamed.previous_filename == "old.md" and renamed.status_display == "Renamed"


def test_pr_files_refuse_an_address_that_is_not_a_pull_request(fake_gh):
    with pytest.raises(GhError):
        gh_data.fetch_pr_files("https://github.com/o/r/issues/7")
    assert fake_gh.calls == []


def test_commit_files_page_past_the_first_hundred(fake_gh):
    fake_gh.route("commits/abc?per_page=100&page=1", [_api_file(f"f{i}") for i in range(100)])
    fake_gh.route("commits/abc?per_page=100&page=2", [_api_file("z", status="removed")])
    files = gh_data.fetch_commit_files("o/r", "abc")
    assert len(files) == 101 and files[-1].status_display == "Deleted"
    assert fake_gh.calls[0][:2] == ["api", "repos/o/r/commits/abc?per_page=100&page=1"]


def test_commit_files_of_a_commit_with_none(fake_gh):
    fake_gh.route("commits/abc", "")
    assert gh_data.fetch_commit_files("o/r", "abc") == []


def test_whole_diffs(fake_gh):
    fake_gh.route("pr diff", "diff --git a/x b/x\n")
    fake_gh.route("commits/abc", "diff --git a/y b/y\n")
    assert gh_data.fetch_pr_diff(PR).startswith("diff --git a/x")
    assert fake_gh.calls[-1] == ["pr", "diff", PR, "--color=never"]
    assert gh_data.fetch_commit_diff("o/r", "abc").startswith("diff --git a/y")
    assert fake_gh.calls[-1] == ["api", "-H", "Accept: application/vnd.github.diff",
                                 "repos/o/r/commits/abc"]


def test_a_failed_diff_raises(fake_gh):
    fake_gh.route("pr diff", GhError("diff too large"))
    with pytest.raises(GhError, match="too large"):
        gh_data.fetch_pr_diff(PR)


@pytest.mark.parametrize("status, old, header", [
    ("modified", "", ["--- a/src/app.py", "+++ b/src/app.py"]),
    ("added", "", ["--- /dev/null", "+++ b/src/app.py"]),
    ("removed", "", ["--- a/src/app.py", "+++ /dev/null"]),
    ("renamed", "src/old.py", ["rename from src/old.py", "rename to src/app.py",
                               "--- a/src/old.py", "+++ b/src/app.py"]),
])
def test_file_diff_has_the_header_an_editor_expects(status, old, header):
    text = gh_data.file_diff(_file(status=status, previous_filename=old))
    lines = text.split("\n")
    assert lines[0] == f"diff --git a/{old or 'src/app.py'} b/src/app.py"
    assert lines[1:1 + len(header)] == header
    assert lines[1 + len(header)].startswith("@@ -1,3") and text.endswith("\n")


@pytest.mark.parametrize("patch", [None, ""])
def test_file_diff_without_lines_is_empty(patch):
    assert gh_data.file_diff(_file(patch=patch)) == ""


@pytest.mark.parametrize("patch", [None, ""])
def test_a_rename_without_line_changes_is_still_a_diff(patch):
    f = _file(status="renamed", previous_filename="old.md", filename="new.md",
              patch=patch, additions=0, deletions=0)
    assert gh_data.file_diff(f) == (
        "diff --git a/old.md b/new.md\nrename from old.md\nrename to new.md\n")


def test_changed_file_row():
    row = _file(status="removed").to_row(["path", "status", "added", "removed"])
    assert row == {"path": "src/app.py", "status": "Deleted", "added": "2", "removed": "1"}


# ── As text to read ────────────────────────────────────────────────────


def test_file_text_in_words_with_where_each_change_starts():
    text, starts = diffview.file_text(_file(), "words")
    lines = text.split("\n")
    assert lines[0] == "src/app.py: modified, 2 lines added, 1 removed."
    assert [lines[i] for i in starts] == ["Lines 1 to 3:", "Lines 10 to 12:"]
    assert lines[starts[0] + 1:starts[0] + 4] == [
        "Unchanged: def foo():", "Removed:     return 1", "Added:     return 2"]
    assert "Added: b" in lines


@pytest.mark.parametrize("style, removed, added", [
    ("short", "Del     return 1", "Add     return 2"),
    ("symbols", "-     return 1", "+     return 2"),
    ("changed", "!-     return 1", "!+     return 2"),
])
def test_file_text_in_each_style(style, removed, added):
    lines = diffview.file_text(_file(), style)[0].split("\n")
    assert removed in lines and added in lines


def test_an_unknown_style_reads_as_words():
    assert "Added: b" in diffview.file_text(_file(), "nonsense")[0]


def test_no_newline_note_is_kept():
    f = _file(patch="@@ -1 +1 @@\n-a\n+b\n\\ No newline at end of file")
    assert "Note: No newline at end of file" in diffview.file_text(f)[0]


@pytest.mark.parametrize("kw, said", [
    (dict(patch=None, additions=0, deletions=0, status="added"),
     "No lines to show: a binary file, or one with no text."),
    (dict(patch=None, additions=4000, deletions=0),
     "GitHub doesn't show the lines of a change this large."),
    (dict(patch="", additions=0, deletions=0, status="renamed", previous_filename="a/old.py"),
     "No lines changed, only the name."),
])
def test_files_without_lines_say_why(kw, said):
    text, starts = diffview.file_text(_file(**kw))
    assert text.split("\n")[-1] == said and starts == []


def test_summary_names_a_rename_and_counts_one_line():
    f = _file(status="renamed", previous_filename="src/old.py", additions=1, deletions=0)
    assert diffview.file_summary(f) == (
        "src/app.py: renamed from src/old.py, 1 line added, 0 removed.")


def test_totals():
    assert diffview.totals_message([]) == "No files changed."
    assert diffview.totals_message([_file(additions=1, deletions=0)]) == (
        "1 file changed, 1 line added, 0 removed.")
    assert diffview.totals_message([_file(), _file(additions=10, deletions=4)]) == (
        "2 files changed, 12 lines added, 5 removed.")


def test_styles_are_app_kits():
    from theideaplace_appkit import difftext
    assert diffview.STYLES == difftext.STYLES and diffview.LABELS == difftext.LABELS
    assert [s for s in diffview.STYLES if diffview.is_symbol_style(s)] == ["symbols", "changed"]


# ── The setting ────────────────────────────────────────────────────────


def test_diff_style_defaults_to_words_and_round_trips():
    assert settings.load_diff_style() == "words"
    settings.save_diff_style("symbols")
    settings._session.clear()
    assert settings.load_diff_style() == "symbols"


def test_an_unknown_diff_style_is_not_kept():
    settings.save_diff_style("rainbow")
    assert settings.load_diff_style() == "words"
    (settings.app_data_dir() / "settings.json").write_text(
        '{"diff_style": "rainbow"}', encoding="utf-8")
    assert settings.load_diff_style() == "words"


# ── In the window ──────────────────────────────────────────────────────

if os.environ.get("CI"):
    import wx  # noqa: F401
else:
    wx = pytest.importorskip("wx")

import ghviewer  # noqa: E402
from gh_data import Commit, Item  # noqa: E402

Frame = ghviewer.GhViewerFrame


class FakeText:
    def __init__(self) -> None:
        self.value, self.selection, self.focused, self.insertion = "", None, 0, None

    def SetValue(self, v): self.value = v
    def GetValue(self): return self.value
    def Clear(self): self.value = ""
    def SetFocus(self): self.focused += 1
    def SetSelection(self, a, b): self.selection = (a, b)
    def SetInsertionPoint(self, p): self.insertion = p
    def GetInsertionPoint(self): return self.insertion or 0
    def ShowPosition(self, p): pass


def _frame(**attrs):
    announced: list[str] = []
    told: list[str] = []
    f = SimpleNamespace(
        details_text=FakeText(), items=[], git_items=[], view_mode=ghviewer.VIEW_FILES,
        repo="o/r", _comment_positions=[], _current_comment=-1,
        _diff_style="words", _files_of=None, _diff_busy=False,
        _announce=announced.append, announced=announced, told=told,
    )
    f._tell = lambda msg, *a, **k: told.append(msg)
    f._line_to_position = lambda line: Frame._line_to_position(f, line)
    for k, v in attrs.items():
        setattr(f, k, v)
    return f


def test_details_show_the_file_and_alt_n_moves_between_changes():
    f = _frame(git_items=[_file()])
    Frame._show_file_details(f, 0)
    assert f.details_text.value.startswith("src/app.py: modified")
    Frame._navigate_comment(f, 1)
    a, b = f.details_text.selection
    assert f.details_text.value[a:b] == "Lines 1 to 3:"
    assert f.announced[-1] == "Change 1 of 2"
    Frame._navigate_comment(f, 1)
    Frame._navigate_comment(f, 1)
    assert f.announced[-1] == "Already at last change."


def test_a_file_without_lines_has_no_changes_to_move_between():
    f = _frame(git_items=[_file(patch=None)])
    Frame._show_file_details(f, 0)
    Frame._navigate_comment(f, 1)
    assert f.announced[-1] == "No changes to navigate."


def test_enter_goes_into_the_lines_from_the_top():
    f = _frame()
    Frame._read_changes(f)
    assert f.details_text.focused == 1 and f.details_text.insertion == 0


def test_the_view_is_titled_by_what_it_shows():
    pr = Item(7, "Fix it", "OPEN", PR, is_pr=True)
    commit = Commit("a" * 40, "aaaaaaaa", "Tidy\n\nmore", "me", "")
    assert Frame._files_of_label(_frame(_files_of=pr)) == "PR #7 Fix it"
    assert Frame._files_of_label(_frame(_files_of=commit)) == "commit aaaaaaaa Tidy"


def _opener(view, item):
    f = _frame(view_mode=view)
    f._focused_item = lambda: item
    f.switched = []
    f._switch_view = lambda mode, load=True: f.switched.append(mode)
    return f


def test_an_issue_has_no_changed_files():
    issue = Item(3, "Bug", "OPEN", "https://github.com/o/r/issues/3", is_pr=False)
    f = _opener(ghviewer.VIEW_ISSUES, issue)
    Frame._show_changed_files(f)
    assert f.switched == [] and "is an issue" in f.told[-1]


def test_changed_files_need_a_pull_request_or_commit():
    f = _opener(ghviewer.VIEW_TAGS, None)
    Frame._show_changed_files(f)
    assert f.switched == [] and f.told[-1] == "Select a pull request or a commit first."


def test_style_change_redraws_and_speaks_the_symbols_note_once():
    f = _frame(git_items=[_file()])
    f._update_menu_checks = lambda: None
    f.list_ctrl = SimpleNamespace(GetFirstSelected=lambda: 0)
    f._show_details = lambda row: Frame._show_file_details(f, row)
    Frame._set_diff_style(f, "symbols")
    assert "+     return 2" in f.details_text.value
    assert diffview.SYMBOLS_NOTE in f.told[-1]
    Frame._set_diff_style(f, "changed")
    assert diffview.SYMBOLS_NOTE not in f.told[-1]
    assert "!+     return 2" in f.details_text.value
    Frame._set_diff_style(f, "short")
    assert f.told[-1] == f"Changed lines marked with {diffview.LABELS['short']}."
    assert settings.load_diff_style() == "short"


def test_style_change_keeps_your_place():
    f = _frame(git_items=[_file()])
    f._update_menu_checks = lambda: None
    f.list_ctrl = SimpleNamespace(GetFirstSelected=lambda: 0)
    f._show_details = lambda row: Frame._show_file_details(f, row)
    Frame._show_file_details(f, 0)
    Frame._navigate_comment(f, 1)
    Frame._navigate_comment(f, 1)
    line = f.details_text.value.count("\n", 0, f.details_text.selection[1])
    f.details_text.insertion = f.details_text.selection[1]
    Frame._set_diff_style(f, "symbols")
    assert f.details_text.value.count("\n", 0, f.details_text.insertion) == line
    assert f._current_comment == 1


def test_copy_diff_of_a_file_puts_its_diff_on_the_clipboard():
    f = _frame(git_items=[_file()], _files_of=Item(7, "Fix", "OPEN", PR, is_pr=True))
    f._focused_item = lambda: f.git_items[0]
    f._diff_stem = lambda item: Frame._diff_stem(f, item)
    f._diff_ready = lambda *a: Frame._diff_ready(f, *a)
    clip: list[str] = []
    f._set_clipboard = lambda text: clip.append(text) or True
    Frame._diff_action(f, "copy")
    assert clip[0].startswith("diff --git a/src/app.py b/src/app.py\n")
    assert f.told[-1] == "Copied the diff of src/app.py, 12 lines."


def test_copy_diff_of_a_file_without_lines_says_so():
    f = _frame(git_items=[_file(patch=None)])
    f._focused_item = lambda: f.git_items[0]
    Frame._diff_action(f, "copy")
    assert "no diff" in f.told[-1]


def test_diff_ready_writes_and_opens_the_file(monkeypatch, tmp_path):
    monkeypatch.setattr(ghviewer.tempfile, "gettempdir", lambda: str(tmp_path))
    opened: list[str] = []
    monkeypatch.setattr(ghviewer, "open_in_default_app", lambda p: opened.append(p) or True)
    f = _frame()
    Frame._diff_ready(f, "open", "diff --git a/x b/x\n", "pull request #7", "o-r-pr-7")
    assert opened == [str(tmp_path / "GHManage" / "o-r-pr-7.diff")]
    assert (tmp_path / "GHManage" / "o-r-pr-7.diff").read_bytes() == b"diff --git a/x b/x\n"
    assert f.told[-1] == "Opened the diff of pull request #7."


def test_an_empty_diff_is_not_copied():
    f = _frame()
    Frame._diff_ready(f, "copy", "", "commit abc", "x")
    assert f.told[-1] == "commit abc has no changes to show."


def test_diff_file_names_are_safe(monkeypatch, tmp_path):
    monkeypatch.setattr(ghviewer.tempfile, "gettempdir", lambda: str(tmp_path))
    path = ghviewer.write_diff_file("o-r-pr-7-../../evil name?.md", "x")
    assert os.path.dirname(path) == str(tmp_path / "GHManage")
    assert os.path.basename(path) == "o-r-pr-7-..-..-evil-name-.md.diff"


# ── Going in and coming back ───────────────────────────────────────────


class FakeList:
    def __init__(self) -> None:
        self.selected = -1

    def GetFirstSelected(self): return self.selected


def _round_trip_frame(view, items, item, **state):
    """A frame whose list shows ``items`` in ``view``, with ``item``
    selected, and the methods the trip in and out of Changed Files calls
    recording what they were asked to do."""
    f = _frame(view_mode=view, items=list(items) if view == ghviewer.VIEW_ISSUES else [],
               git_items=[] if view == ghviewer.VIEW_ISSUES else list(items),
               current_limit=100, filter_text="", label_filter="", commit_branch="",
               _branches_unread=0, _return_to=None, _return_view=ghviewer.VIEW_ISSUES,
               _fetch_token=0, _pending_target=None, _files_back=None)
    for k, v in state.items():
        setattr(f, k, v)
    f._focused_item = lambda: item
    f._view_source = lambda: f.items if f.view_mode == ghviewer.VIEW_ISSUES else f.git_items
    f.calls = []

    def switch(mode, load=True):
        # What _switch_view does to the state this feature keeps.
        f.calls.append(("switch", mode, load))
        f.view_mode = mode
        if mode != ghviewer.VIEW_COMMITS:
            f.commit_branch = ""
        if mode != ghviewer.VIEW_ISSUES:
            f.label_filter = ""
        if mode != ghviewer.VIEW_FILES:
            f._files_of = None
            f._files_back = None
        if mode != f._return_view:
            f._return_to = None
        f.filter_text = ""
        f.current_limit = 30
    f._switch_view = switch
    f._update_title = lambda: None
    f._load_items = lambda: f.calls.append(("load", f.view_mode))
    f._begin_fetch = lambda: Frame._begin_fetch(f)
    f._set_pending_target = lambda *a: Frame._set_pending_target(f, *a)
    f._view_label = lambda v, lower=False: Frame._view_label(f, v, lower)
    f._VIEW_LABELS = Frame._VIEW_LABELS
    f._org = ""
    f._on_items_loaded = lambda token, its, ni, np: f.calls.append(("issues", token, its, ni, np))
    f._on_git_items_loaded = lambda token, its, kind: f.calls.append(("git", token, its, kind))
    return f


PRS = [Item(7, "Fix", "OPEN", PR, is_pr=True), Item(3, "Bug", "OPEN", "u3", is_pr=False)]


def test_open_from_issues_and_come_back_to_the_list_as_it_was():
    back_to = ("activity", [], False, None, 30)
    f = _round_trip_frame(ghviewer.VIEW_ISSUES, PRS, PRS[0], label_filter="bug",
                          filter_text="fix", current_limit=200, _return_to=back_to)
    Frame._show_changed_files(f)
    assert f.calls == [("switch", ghviewer.VIEW_FILES, False), ("load", ghviewer.VIEW_FILES)]
    # Set after the switch, which clears them.
    assert f._files_of is PRS[0] and f._files_back["item"] is PRS[0]

    f.calls.clear()
    Frame._back_from_files(f)
    assert f.calls[0] == ("switch", ghviewer.VIEW_ISSUES, False)
    kind, token, items, n_issues, n_prs = f.calls[1]
    assert (kind, items, n_issues, n_prs) == ("issues", PRS, 1, 1)
    assert (f.label_filter, f.filter_text, f.current_limit) == ("bug", "fix", 200)
    assert f._return_to == back_to
    assert f._pending_target == (token, ghviewer.VIEW_ISSUES, "same", PRS[0])
    assert f.announced[-1] == "Back to issues"


def test_open_from_commits_on_all_branches_and_come_back():
    commits = [Commit("a" * 40, "aaaaaaaa", "One", "me", ""), Commit("b" * 40, "bbbbbbbb", "Two", "me", "")]
    f = _round_trip_frame(ghviewer.VIEW_COMMITS, commits, commits[1],
                          commit_branch=gh_data.ALL_BRANCHES, _branches_unread=2)
    Frame._show_changed_files(f)
    assert f.commit_branch == ""      # gone while in Changed Files…
    Frame._back_from_files(f)
    assert f.commit_branch == gh_data.ALL_BRANCHES and f._branches_unread == 2   # …and back
    assert f.calls[-1][0] == "git" and f.calls[-1][2] == commits
    assert f._pending_target[2:] == ("same", commits[1])


def test_a_filter_changed_meanwhile_reads_the_list_again():
    f = _round_trip_frame(ghviewer.VIEW_ISSUES, PRS, PRS[0])
    Frame._show_changed_files(f)
    Frame._reload_after_filter(f)
    assert "when you go back" in f.told[-1]
    assert ("load", ghviewer.VIEW_FILES) == f.calls[-1]   # the files aren't read again
    f.calls.clear()
    Frame._back_from_files(f)
    assert f.calls == [("switch", ghviewer.VIEW_ISSUES, False), ("load", ghviewer.VIEW_ISSUES)]
    assert f._pending_target[1:] == (ghviewer.VIEW_ISSUES, "item", "7")


def _pending_frame(shown, target):
    f = SimpleNamespace(_pending_target=target, view_mode=ghviewer.VIEW_ISSUES, _shown=shown,
                        announced=[])
    f._row_of = lambda it: Frame._row_of(f, it)
    return f


def test_the_same_item_is_found_by_identity_and_not_announced(monkeypatch):
    later: list = []
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda *a: later.append(a))
    twin = Item(7, "Fix", "OPEN", PR, is_pr=True)     # equal, but not the one
    f = _pending_frame([twin, PRS[0]], (5, ghviewer.VIEW_ISSUES, "same", PRS[0]))
    assert Frame._take_pending_row(f, [twin, PRS[0]], 5) == 1
    assert later == []


def test_the_same_item_filtered_out_lands_on_the_first_row_quietly(monkeypatch):
    later: list = []
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda *a: later.append(a))
    f = _pending_frame([PRS[1]], (5, ghviewer.VIEW_ISSUES, "same", PRS[0]))
    assert Frame._take_pending_row(f, PRS, 5) == 0
    assert later == []


def _loaded_frame(files):
    f = _frame(_fetch_token=4, _files_of=PRS[0],
               _files_back={"view": ghviewer.VIEW_ISSUES})
    f._fetch_is_current = lambda token: token == f._fetch_token
    f._populate_filtered_list = lambda items: list(items)
    f._take_pending_row = lambda items, token: 0
    f.status = []
    f._set_view_status = lambda msg, keys="": f.status.append((msg, keys))
    f._update_title = lambda: None
    f._files_of_label = lambda: Frame._files_of_label(f)
    f._view_label = lambda v, lower=False: Frame._view_label(f, v, lower)
    f._VIEW_LABELS = Frame._VIEW_LABELS
    f._org = ""
    return f


def test_files_that_arrive_late_are_dropped():
    f = _loaded_frame([])
    Frame._on_files_loaded(f, 3, [_file()])
    assert f.git_items == [] and f.status == []


def test_loaded_files_say_their_totals_and_the_way_back(monkeypatch):
    later: list = []
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda ms, fn: later.append(fn))
    spoken: list = []
    monkeypatch.setattr(ghviewer.announce, "announce", lambda msg, cat: spoken.append((msg, cat)))
    f = _loaded_frame([])
    f._focus_list = lambda row: spoken.append(("focus", row))
    Frame._on_files_loaded(f, 4, [_file()])
    msg, keys = f.status[-1]
    assert msg == "PR #7 Fix — 1 file changed, 2 lines added, 1 removed."
    assert "Backspace=back to issues" in keys
    later[0]()
    # Focus first, then the totals, waiting their turn behind the row.
    assert spoken == [("focus", 0), ("1 file changed, 2 lines added, 1 removed.", "status")]


def test_three_thousand_files_say_github_stops_there(monkeypatch):
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda *a: None)
    f = _loaded_frame([])
    Frame._on_files_loaded(f, 4, [_file(additions=0, deletions=0)] * gh_data.MAX_CHANGED_FILES)
    assert f.status[-1][0].endswith("GitHub lists only the first 3,000.")


def test_a_failed_diff_frees_the_next_try():
    f = _frame(_diff_busy=True)
    Frame._diff_failed(f, "diff too large")
    assert f._diff_busy is False and f.told[-1] == "Couldn't get the diff: diff too large"


def test_enter_on_a_commit_opens_its_changed_files():
    commit = Commit("a" * 40, "aaaaaaaa", "One", "me", "", url="u")
    f = _frame(view_mode=ghviewer.VIEW_COMMITS)
    f._focused_item = lambda: commit
    opened = []
    f._show_changed_files = lambda: opened.append(True)
    Frame.on_item_activated(f, None)
    assert opened == [True]
