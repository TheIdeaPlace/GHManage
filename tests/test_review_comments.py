"""Review comments in Changed Files (#84): a pull request's comments read
after the lines they are on, the Comments column, Alt+N/Alt+P stopping at
comments as well as changes, and M commenting on the caret's line."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest
from theideaplace_appkit import difftext

import diffview
import gh_data
from gh_data import ChangedFile, GhError, ReviewComment

PR_URL = "https://github.com/o/r/pull/7"

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


def _c(id, line=None, side="RIGHT", body="Looks off", author="alice", **kw) -> ReviewComment:
    return ReviewComment(id=id, path="src/app.py", body=body, author=author, line=line,
                         side=side, **kw)


# ── Fetching and posting ───────────────────────────────────────────────


def _api_comment(id, **kw):
    row = {"id": id, "path": "a.py", "body": "Hi", "user": {"login": "alice"},
           "line": 3, "side": "RIGHT", "start_line": None, "original_line": 3,
           "in_reply_to_id": None, "subject_type": "line",
           "html_url": f"https://github.com/o/r/pull/7#discussion_r{id}"}
    row.update(kw)
    return row


def test_review_comments_are_read_with_their_place_and_thread(fake_gh):
    fake_gh.route("repos/o/r/pulls/7/comments", [
        _api_comment(1),
        _api_comment(2, in_reply_to_id=1, user=None),
        _api_comment(3, line=None, original_line=9),
        _api_comment(4, line=None, subject_type="file", side=None),
        _api_comment(5, start_line=2, side="LEFT"),
    ])
    first, reply, outdated, on_file, ranged = gh_data.fetch_pr_review_comments(PR_URL)
    assert (first.id, first.path, first.line, first.side, first.author) == (1, "a.py", 3, "RIGHT", "alice")
    assert reply.in_reply_to == 1 and reply.author == "ghost"
    assert outdated.line is None and outdated.original_line == 9
    assert on_file.on_file and on_file.side == "RIGHT"
    assert ranged.start_line == 2 and ranged.side == "LEFT"
    assert fake_gh.calls[0][:2] == ["api", "repos/o/r/pulls/7/comments?per_page=100&page=1"]


def test_review_comments_refuse_an_address_that_is_not_a_pull_request(fake_gh):
    with pytest.raises(GhError):
        gh_data.fetch_pr_review_comments("https://github.com/o/r/issues/7")
    assert fake_gh.calls == []


def test_a_line_comment_is_posted_with_its_body_on_stdin(fake_gh, monkeypatch):
    sent = {}

    def run(args, stdin=None):
        sent["args"], sent["stdin"] = args, stdin
        return "{}"

    monkeypatch.setattr(gh_data, "_run_gh", run)
    gh_data.add_review_comment(PR_URL, "f" * 40, "src/app.py", 12, "LEFT", "--body is not an option")
    assert sent["args"] == ["api", "-X", "POST", "repos/o/r/pulls/7/comments", "--input", "-"]
    assert json.loads(sent["stdin"]) == {
        "body": "--body is not an option", "commit_id": "f" * 40, "path": "src/app.py",
        "line": 12, "side": "LEFT"}


def test_a_line_comment_needs_a_side_and_a_pull_request(fake_gh):
    with pytest.raises(ValueError):
        gh_data.add_review_comment(PR_URL, "f", "a.py", 1, "BOTH", "x")
    with pytest.raises(GhError):
        gh_data.add_review_comment("https://github.com/o/r/issues/7", "f", "a.py", 1, "RIGHT", "x")
    assert fake_gh.calls == []


def test_the_comments_column_counts_a_pull_requests_and_is_blank_for_a_commit():
    assert _file().to_row(["path", "comments"]) == {"path": "src/app.py", "comments": ""}
    assert _file(comments=[]).to_row(["comments"]) == {"comments": "0"}
    assert _file(comments=[_c(1), _c(2)]).to_row(["comments"]) == {"comments": "2"}
    assert "comments" in gh_data.CHANGED_FILE_DEFAULT_COLUMNS


# ── The file's text ────────────────────────────────────────────────────


def _lines(view):
    return view.text.split("\n")


def test_without_comments_the_text_is_as_before():
    text, starts = diffview.file_text(_file())
    view = diffview.file_view(_file())
    assert view.text == text
    assert [(line, 1, "change") for line in starts] == view.stops
    assert _lines(view)[starts[0]] == "Lines 1 to 3:"


def test_comments_follow_their_line_on_either_side_with_replies():
    comments = [
        _c(1, line=2, body="Why 2?"),                               # the added line
        _c(2, line=2, side="LEFT", body="Was 1 right?", author="bob"),  # the removed one
        _c(3, line=2, body="Because.\n\nIt is.", author="carol", in_reply_to=1),
        _c(4, line=10, side="LEFT", body="Old a"),                    # unchanged, old side
    ]
    view = diffview.file_view(_file(), comments=comments)
    lines = _lines(view)
    assert lines[1:13] == [
        "", "Lines 1 to 3:",
        "Unchanged: def foo():",
        "Removed:     return 1",
        "Comment by bob: Was 1 right?",
        "Added:     return 2",
        "Comment by alice: Why 2?",
        "  Reply by carol: Because.",
        "",
        "    It is.",
        "Unchanged: blank line",
        "",
    ]
    assert lines[13:16] == ["Lines 10 to 12:", "Unchanged: a", "Comment by alice: Old a"]
    # The runs of changes still start where their "Lines…" line is.
    assert view.stops == [(2, 1, "change"), (5, 1, "comment"), (7, 1, "comment"),
                          (8, 3, "comment"), (13, 1, "change"), (15, 1, "comment")]


def test_where_a_comment_would_go_for_each_line():
    view = diffview.file_view(_file(), comments=[_c(1, line=2)])
    lines = _lines(view)
    by_text = dict(zip(lines, view.targets))
    assert view.target(0) == diffview.ON_SUMMARY
    assert by_text["Lines 1 to 3:"] == diffview.ON_WHERE
    assert by_text["Unchanged: def foo():"] == ("RIGHT", 1)
    assert by_text["Removed:     return 1"] == ("LEFT", 2)
    assert by_text["Added:     return 2"] == ("RIGHT", 2)
    assert by_text["Comment by alice: Looks off"] == diffview.ON_COMMENT
    assert by_text["Added: b"] == ("RIGHT", 11)
    assert by_text["Unchanged: c"] == ("RIGHT", 12)
    assert view.target(1) == diffview.ON_OTHER and view.target(999) == diffview.ON_OTHER
    assert len(view.targets) == len(lines)


def test_a_note_line_cannot_take_a_comment():
    f = _file(patch="@@ -1 +1 @@\n-a\n+b\n\\ No newline at end of file")
    view = diffview.file_view(f)
    assert _lines(view)[-1].startswith("Note:") and view.targets[-1] == diffview.ON_NOTE


def test_a_file_without_lines_says_there_is_none_to_comment_on_and_lists_its_comments():
    view = diffview.file_view(_file(patch=None), comments=[_c(1, line=5, original_line=5)])
    assert view.target(2) == diffview.NO_LINES
    # Current comments, not earlier ones: their lines just aren't shown.
    assert _lines(view)[-2:] == [diffview.NOT_SHOWN_HEADING,
                                 "Comment by alice on line 5: Looks off"]


def test_outdated_and_whole_file_comments_go_at_the_end():
    comments = [
        _c(1, line=None, original_line=4, body="Gone now"),
        _c(2, line=None, on_file=True, body="About the file"),
        _c(3, line=None, in_reply_to=1, body="Agreed", author="bob"),
        _c(4, line=99, original_line=99, body="Not in the diff"),
    ]
    view = diffview.file_view(_file(), comments=comments)
    assert _lines(view)[-10:] == [
        "", diffview.FILE_HEADING, "Comment by alice: About the file",
        "", diffview.NOT_SHOWN_HEADING, "Comment by alice on line 99: Not in the diff",
        "", diffview.EARLIER_HEADING,
        "Comment by alice on line 4 as it was: Gone now",
        "  Reply by bob: Agreed",
    ]
    assert [k for _, _, k in view.stops].count("comment") == 4
    assert all(t == diffview.ON_COMMENT for t in view.targets[-2:])


def test_a_reply_to_a_reply_joins_the_thread():
    comments = [_c(1, line=11, body="A"), _c(2, line=11, body="B", in_reply_to=1),
                _c(3, line=11, body="C", in_reply_to=2)]
    lines = _lines(diffview.file_view(_file(), comments=comments))
    i = lines.index("Comment by alice: A")
    assert lines[i + 1:i + 3] == ["  Reply by alice: B", "  Reply by alice: C"]


def test_in_the_changed_style_a_comment_follows_its_line_inside_a_pair():
    comments = [_c(1, line=2, side="LEFT", body="old"), _c(2, line=2, body="new")]
    lines = _lines(diffview.file_view(_file(), "changed", comments))
    i = lines.index("!-     return 1")
    assert lines[i:i + 4] == ["!-     return 1", "Comment by alice: old",
                              "!+     return 2", "Comment by alice: new"]


def test_a_comment_on_several_lines_says_which():
    view = diffview.file_view(_file(), comments=[_c(1, line=12, start_line=10)])
    assert "Comment by alice on lines 10 to 12: Looks off" in _lines(view)


def test_a_reply_whose_comment_is_gone_reads_as_a_comment():
    view = diffview.file_view(_file(), comments=[_c(5, line=11, in_reply_to=4)])
    assert "Comment by alice: Looks off" in _lines(view)


@pytest.mark.parametrize("style", diffview.STYLES)
def test_every_style_finds_the_same_lines(style):
    patch = ("@@ -1,4 +1,4 @@\n-a\n-b\n+A\n+B\n+C\n c\n"
             "@@ -20,3 +21,2 @@\n x\n-y\n\\ No newline at end of file\n-z\n+Z")
    f = _file(patch=patch)
    view = diffview.file_view(f, style)
    lines = _lines(view)
    # The order lines come in is difftext's own, for every style.
    for hunk in difftext.parse_unified(patch):
        marked = difftext._marked(hunk.lines, style)
        order = diffview._order(hunk.lines, style)
        assert [hunk.lines[i] for i in order] == [line for _, line in marked]
    want = {"a": ("LEFT", 1), "b": ("LEFT", 2), "A": ("RIGHT", 1), "B": ("RIGHT", 2),
            "C": ("RIGHT", 3), "c": ("RIGHT", 4), "x": ("RIGHT", 21), "y": ("LEFT", 21),
            "z": ("LEFT", 22), "Z": ("RIGHT", 22)}
    got = {line.rsplit(" ", 1)[-1]: t for line, t in zip(lines, view.targets)
           if isinstance(t, tuple)}
    assert got == want


# ── In the window ──────────────────────────────────────────────────────

if os.environ.get("CI"):
    import wx  # noqa: F401
else:
    wx = pytest.importorskip("wx")

import ghviewer  # noqa: E402
from gh_data import Commit, Item  # noqa: E402

Frame = ghviewer.GhViewerFrame
PR = Item(7, "Fix it", "OPEN", PR_URL, is_pr=True)
COMMIT = Commit("a" * 40, "aaaaaaaa", "Tidy", "me", "")


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
        repo="o/r", _comment_positions=[], _current_comment=-1, _shown=[],
        _diff_style="words", _files_of=PR, _line_comment_busy=False, _file_view=None,
        _announce=announced.append, announced=announced, told=told, redrawn=[],
    )
    f._tell = lambda msg, *a, **k: told.append(msg)
    f._line_to_position = lambda line: Frame._line_to_position(f, line)
    f._caret_line = lambda: Frame._caret_line(f)
    f._redraw_row = lambda row, item: f.redrawn.append((row, item))
    f._on_line_comment_done = lambda *a: Frame._on_line_comment_done(f, *a)
    f._focused_item = lambda: f.git_items[0] if f.git_items else None
    f.list_ctrl = SimpleNamespace(GetFirstSelected=lambda: 0)
    f._show_details = lambda row: Frame._show_file_details(f, row)
    for k, v in attrs.items():
        setattr(f, k, v)
    return f


def _shown(comments):
    changed = _file(comments=comments)
    f = _frame(git_items=[changed], _shown=[changed])
    Frame._show_file_details(f, 0)
    return f


def _caret_on(f, text):
    line = f.details_text.value.split("\n").index(text)
    f.details_text.insertion = Frame._line_to_position(f, line)
    return line


def test_alt_n_names_changes_and_comments_and_counts_each():
    f = _shown([_c(1, line=2, body="One"), _c(2, line=12, body="Two")])
    said = []
    for _ in range(5):
        Frame._navigate_comment(f, 1)
        a, b = f.details_text.selection
        said.append((f.announced[-1], f.details_text.value[a:b]))
    assert said == [
        ("Change 1 of 2", "Lines 1 to 3:"),
        ("Comment 1 of 2", "Comment by alice: One"),
        ("Change 2 of 2", "Lines 10 to 12:"),
        ("Comment 2 of 2", "Comment by alice: Two"),
        ("Already at last change or comment.", "Comment by alice: Two"),
    ]
    Frame._navigate_comment(f, -1)
    assert f.announced[-1] == "Change 2 of 2"


def test_a_comment_of_several_lines_is_selected_whole():
    f = _shown([_c(1, line=2, body="One\ntwo")])
    Frame._navigate_comment(f, 1)
    Frame._navigate_comment(f, 1)
    a, b = f.details_text.selection
    assert f.details_text.value[a:b] == "Comment by alice: One\n  two"


def test_a_commits_files_still_say_change():
    f = _frame(_files_of=COMMIT, git_items=[_file()])
    Frame._show_file_details(f, 0)
    Frame._navigate_comment(f, -1)
    assert f.announced[-1] == "Already at first change."
    assert Frame._nav_noun(f) == "change"
    assert Frame._nav_noun(_frame()) == "change or comment"
    f = _frame(git_items=[_file(patch=None)])
    Frame._show_file_details(f, 0)
    Frame._navigate_comment(f, 1)
    assert f.announced[-1] == "No changes or comments to navigate."


def test_comments_are_given_to_their_files():
    a, b = ChangedFile("a.py"), ChangedFile("b.py")
    Frame._attach_comments([a, b], [ReviewComment(1, "a.py"), ReviewComment(2, "a.py")])
    assert len(a.comments) == 2 and b.comments == []


@pytest.mark.parametrize("text, said", [
    ("src/app.py: modified, 2 lines added, 1 removed.", diffview.ON_SUMMARY),
    ("Lines 1 to 3:", diffview.ON_WHERE),
    ("Comment by alice: Looks off", diffview.ON_COMMENT),
    (diffview.EARLIER_HEADING, diffview.ON_OTHER),
])
def test_m_refuses_a_line_that_is_not_one_of_the_changes(text, said, monkeypatch):
    monkeypatch.setattr(ghviewer.wx, "TextEntryDialog",
                        lambda *a, **k: pytest.fail("no dialog for a refusal"))
    f = _shown([_c(1, line=2), _c(2, line=None)])
    _caret_on(f, text)
    Frame._comment_on_line(f)
    assert f.told == [said]


def test_m_refuses_a_commit_and_another_view():
    f = _frame(_files_of=COMMIT)
    Frame._comment_on_line(f)
    assert f.told == ["Line comments are for a pull request's changed files, not a commit's."]
    f = _frame(view_mode=ghviewer.VIEW_ISSUES)
    Frame._comment_on_line(f)
    assert f.told == ["Comment on This Line is for a pull request's file in Changed Files."]


def test_m_waits_for_the_last_comment():
    f = _shown([])
    f._line_comment_busy = True
    _caret_on(f, "Added: b")
    Frame._comment_on_line(f)
    assert f.told == ["Still adding the last comment."]


class Dialog:
    shown: list = []

    def __init__(self, parent, message, title, value, style=0):
        Dialog.shown.append((message, title))
        self.destroyed = False

    def ShowModal(self): return Dialog.answer[0]
    def GetValue(self): return Dialog.answer[1]
    def Destroy(self): pass


def _post(monkeypatch, fake_gh, f, answer=None):
    Dialog.shown, Dialog.answer = [], answer or (wx.ID_OK, "  Why?  ")
    monkeypatch.setattr(ghviewer.wx, "TextEntryDialog", Dialog)
    started = []
    monkeypatch.setattr(ghviewer.threading, "Thread",
                        lambda target, daemon: SimpleNamespace(start=lambda: started.append(target)))
    monkeypatch.setattr(ghviewer.wx, "CallAfter", lambda fn, *a: fn(*a))
    Frame._comment_on_line(f)
    for target in started:
        target()
    return started


def test_m_comments_on_the_caret_line_and_reads_the_file_again(monkeypatch, fake_gh):
    f = _shown([_c(1, line=2, body="Old")])
    line = _caret_on(f, "Removed:     return 1")
    posted = {}

    def post(args):
        posted["args"] = args
        return "{}"

    fake_gh.route("pr view", "f" * 40 + "\n")
    fake_gh.route("-X POST", post)
    fake_gh.route("pulls/7/comments?per_page", [
        _api_comment(1, path="src/app.py", line=2, body="Old"),
        _api_comment(9, path="src/app.py", line=2, side="LEFT", body="Was it?",
                     user={"login": "me"}),
    ])
    started = _post(monkeypatch, fake_gh, f)
    assert len(started) == 1
    assert Dialog.shown == [("Comment on removed line 2 of src/app.py:\nRemoved:     return 1",
                             "Comment on This Line")]
    assert posted["args"][:4] == ["api", "-X", "POST", "repos/o/r/pulls/7/comments"]
    assert f.told == ["Comment added on removed line 2."]
    lines = f.details_text.value.split("\n")
    assert lines[line + 1] == "Comment by me: Was it?"
    # The caret stays on the line, and Alt+N goes on to the new comment.
    assert f.details_text.insertion == Frame._line_to_position(f, line)
    Frame._navigate_comment(f, 1)
    assert f.announced[-1] == "Comment 1 of 2"
    assert len(f.git_items[0].comments) == 2 and f.redrawn == [(0, f.git_items[0])]
    assert not f._line_comment_busy


def test_an_unchanged_line_is_commented_on_its_new_side(monkeypatch, fake_gh):
    f = _shown([])
    _caret_on(f, "Unchanged: c")
    bodies = []
    fake_gh.route("pr view", "abc")
    fake_gh.route("-X POST", lambda args: bodies.append(args) or "{}")
    fake_gh.route("pulls/7/comments?per_page", [])
    sent = []
    monkeypatch.setattr(ghviewer, "add_review_comment",
                        lambda *a: sent.append(a))
    _post(monkeypatch, fake_gh, f)
    assert sent == [(PR_URL, "abc", "src/app.py", 12, "RIGHT", "Why?")]
    assert Dialog.shown[0][0].startswith("Comment on line 12 of src/app.py:")


def test_cancel_or_nothing_typed_posts_nothing(monkeypatch, fake_gh):
    for answer in ((wx.ID_CANCEL, "x"), (wx.ID_OK, "   ")):
        f = _shown([])
        _caret_on(f, "Added: b")
        assert _post(monkeypatch, fake_gh, f, answer) == []
        assert f.told == [] and not f._line_comment_busy
    assert fake_gh.calls == []


def test_a_failed_post_says_why_and_frees_the_next(monkeypatch, fake_gh):
    f = _shown([])
    _caret_on(f, "Added: b")
    fake_gh.route("pr view", "abc")
    fake_gh.route("-X POST", GhError("Validation Failed"))
    _post(monkeypatch, fake_gh, f)
    assert f.told == ["Couldn't add the comment. Validation Failed"]
    assert not f._line_comment_busy and f.git_items[0].comments == []


def test_posted_but_not_read_again_still_says_it_was_added(monkeypatch, fake_gh):
    f = _shown([])
    _caret_on(f, "Added: b")
    fake_gh.route("pr view", "abc")
    fake_gh.route("-X POST", "{}")
    fake_gh.route("pulls/7/comments?per_page", GhError("timeout"))
    _post(monkeypatch, fake_gh, f)
    assert f.told == ["Comment added on line 11. Couldn't read the comments again: timeout"]


def test_a_comment_posted_after_you_left_only_says_so():
    f = _frame(view_mode=ghviewer.VIEW_ISSUES, _line_comment_busy=True)
    Frame._on_line_comment_done(f, PR, _file(), 3, "line 2", True, [], "")
    assert f.told == ["Comment added on line 2."] and f.redrawn == []
    assert not f._line_comment_busy


def _loaded_frame(files_of):
    f = _frame(_fetch_token=4, _files_of=files_of, _files_back={"view": ghviewer.VIEW_ISSUES})
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


def test_loaded_files_count_the_comments_and_name_m(monkeypatch):
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda *a: None)
    f = _loaded_frame(PR)
    Frame._on_files_loaded(f, 4, [_file(comments=[_c(1), _c(2)]), _file(comments=[])])
    msg, keys = f.status[-1]
    assert msg.endswith("removed. 2 comments.")
    assert "next/previous change or comment  M=comment on the line" in keys
    f = _loaded_frame(PR)
    Frame._on_files_loaded(f, 4, [_file()], "Couldn't read the review comments: boom")
    assert f.status[-1][0].endswith("removed. Couldn't read the review comments: boom")
    f = _loaded_frame(COMMIT)
    Frame._on_files_loaded(f, 4, [_file()])
    assert "M=" not in f.status[-1][1] and "comment" not in f.status[-1][0]


class Key:
    def __init__(self, code): self.code, self.skipped = code, False
    def GetKeyCode(self): return self.code
    def GetModifiers(self): return 0
    def HasAnyModifiers(self): return False
    def Skip(self): self.skipped = True


def _hook_frame(focus_details, files_of=PR):
    f = _frame(_files_of=files_of)
    f.repo_list, f.list_ctrl = object(), object()
    f.status_bar = SimpleNamespace(IsDescendant=lambda w: False)
    f.FindFocus = lambda: f.details_text if focus_details else f.list_ctrl
    f.calls = []
    f._comment_on_line = lambda: f.calls.append("comment")
    return f


def test_m_from_the_list_says_to_go_into_the_lines():
    f = _hook_frame(False)
    Frame.on_char_hook(f, Key(ord("M")))
    assert f.calls == [] and f.told == [
        "Comment on This Line works in the file's lines: press Enter, move to the line, "
        "then press M."]
    f = _hook_frame(True)
    Frame.on_char_hook(f, Key(ord("M")))
    assert f.calls == ["comment"]
    f = _hook_frame(False, COMMIT)
    Frame.on_char_hook(f, Key(ord("M")))
    assert f.calls == ["comment"]  # which says a commit's lines can't take them


def test_a_pull_request_that_moved_on_is_not_commented_on(monkeypatch, fake_gh):
    f = _shown([])
    f._files_head = "old"
    _caret_on(f, "Added: b")
    fake_gh.route("pr view", "new")
    _post(monkeypatch, fake_gh, f)
    assert f.told == ["Couldn't add the comment. The pull request has new commits since "
                      "these lines were read. Press R in the list of files to read them "
                      "again, then comment."]
    assert not any("POST" in c for c in fake_gh.calls)


def test_the_shown_head_is_posted_on(monkeypatch, fake_gh):
    f = _shown([])
    f._files_head = "same"
    _caret_on(f, "Added: b")
    fake_gh.route("pr view", "same")
    sent = []
    monkeypatch.setattr(ghviewer, "add_review_comment", lambda *a: sent.append(a))
    fake_gh.route("pulls/7/comments?per_page", [])
    _post(monkeypatch, fake_gh, f)
    assert sent[0][1] == "same" and f.told == ["Comment added on line 11."]


def test_any_failure_frees_the_next_comment(monkeypatch, fake_gh):
    f = _shown([])
    _caret_on(f, "Added: b")
    fake_gh.route("pr view", "abc")

    def boom(*a):
        raise ValueError("bad JSON")

    monkeypatch.setattr(ghviewer, "add_review_comment", boom)
    _post(monkeypatch, fake_gh, f)
    assert f.told == ["Couldn't add the comment. bad JSON"] and not f._line_comment_busy


def test_a_list_read_again_meanwhile_still_shows_the_new_comment():
    f = _shown([])
    again = _file(comments=[])
    f.git_items, f._shown = [again], [again]
    Frame._on_line_comment_done(f, PR, _file(), 13, "line 11", True,
                                [_c(9, line=11, body="Mine", author="me")], "")
    assert "Comment by me: Mine" in f.details_text.value


def test_the_head_the_lines_are_of_is_kept_and_survives_a_return_from_files(monkeypatch):
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda *a: None)
    f = _loaded_frame(PR)
    Frame._on_files_loaded(f, 4, [_file()], "", "abc")
    assert f._files_head == "abc"
    Frame._on_files_loaded(f, 4, [_file()])
    assert f._files_head == "abc"
