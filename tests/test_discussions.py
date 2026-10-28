"""Discussions (#86): a repository's discussions, read with their comments
and replies, and commented on with M. GraphQL only, through _graphql."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import discussionview
import gh_data
from gh_data import Discussion, DiscussionComment, Discussions, GhError


def _node(number=7, **over):
    node = {
        "id": f"D_{number}", "number": number, "title": f"Topic {number}",
        "url": f"https://github.com/o/r/discussions/{number}",
        "createdAt": "2026-10-01T10:00:00Z", "updatedAt": "2026-10-02T10:00:00Z",
        "body": "First line\r\nSecond line", "closed": False, "locked": False,
        "upvoteCount": 2, "author": {"login": "alice"},
        "category": {"name": "Q&A", "isAnswerable": True},
        "isAnswered": True, "answerChosenAt": "2026-10-03T10:00:00Z",
        "answer": {"author": {"login": "bob"}}, "comments": {"totalCount": 3},
    }
    node.update(over)
    return node


def _page(nodes, more=False, cursor="c1", enabled=True, total=None):
    return {"data": {"repository": {
        "hasDiscussionsEnabled": enabled,
        "discussions": {"totalCount": total if total is not None else len(nodes),
                        "pageInfo": {"hasNextPage": more, "endCursor": cursor},
                        "nodes": nodes}}}}


@pytest.fixture
def graphql(monkeypatch):
    """Stand-in for gh_data._graphql: replies in turn, records each call."""
    fake = SimpleNamespace(replies=[], calls=[])

    def run(query, variables=None):
        fake.calls.append((query, variables))
        return fake.replies.pop(0)
    monkeypatch.setattr(gh_data, "_graphql", run)
    return fake


# ── Data ───────────────────────────────────────────────────────────────

def test_discussions_are_parsed(graphql):
    graphql.replies = [_page([_node(7), _node(8, author=None, category=None,
                                              isAnswered=None, answer=None)])]
    result = gh_data.fetch_discussions("o/r", "open", 30)
    assert result.enabled and not result.more
    d, ghost = result.items
    assert (d.number, d.title, d.node_id, d.repo, d.category, d.author) == (
        7, "Topic 7", "D_7", "o/r", "Q&A", "alice")
    assert d.answerable and d.answered and d.answer_author == "bob"
    assert (d.comment_count, d.upvotes) == (3, 2)
    assert d.comments is None  # read when selected
    assert ghost.author == "ghost" and not ghost.answerable and ghost.category == ""
    query, variables = graphql.calls[0]
    assert variables == {"owner": "o", "name": "r", "first": 30, "after": None,
                         "states": ["OPEN"]}
    assert "UPDATED_AT" in query and "DESC" in query


@pytest.mark.parametrize("state,states", [("open", ["OPEN"]), ("closed", ["CLOSED"]),
                                          ("all", None)])
def test_view_state_chooses_the_discussions(graphql, state, states):
    graphql.replies = [_page([])]
    gh_data.fetch_discussions("o/r", state, 10)
    assert graphql.calls[0][1]["states"] == states


def test_more_than_a_page_is_read_by_cursor(graphql):
    graphql.replies = [_page([_node(n) for n in range(100)], more=True, cursor="A",
                             total=250),
                       _page([_node(n) for n in range(100, 150)], more=True, cursor="B",
                             total=250)]
    result = gh_data.fetch_discussions("o/r", "all", 150)
    assert len(result.items) == 150 and result.more and result.total == 250
    assert [c[1]["first"] for c in graphql.calls] == [100, 50]
    assert graphql.calls[1][1]["after"] == "A"


def test_discussions_turned_off_is_an_answer_not_an_error(graphql):
    graphql.replies = [{"data": {"repository": {"hasDiscussionsEnabled": False,
                                                "discussions": None}}}]
    result = gh_data.fetch_discussions("o/r")
    assert not result.enabled and result.items == []


def test_a_missing_repository_is_an_error(graphql):
    graphql.replies = [{"data": {"repository": None}, "errors": [
        {"message": "Could not resolve to a Repository with the name 'o/r'."}]}]
    with pytest.raises(GhError, match="Could not resolve"):
        gh_data.fetch_discussions("o/r")


def _comment(author="carol", body="Hi", answer=False, replies=(), total=None, **over):
    node = {"author": {"login": author}, "body": body, "createdAt": "2026-10-04T10:00:00Z",
            "url": "u", "isAnswer": answer, "upvoteCount": 0, "isMinimized": False,
            "replies": {"totalCount": len(replies) if total is None else total,
                        "nodes": list(replies)}}
    node.update(over)
    return node


def _comments_page(nodes, more=False, cursor="c"):
    return {"data": {"repository": {"discussion": {"comments": {
        "totalCount": len(nodes), "pageInfo": {"hasNextPage": more, "endCursor": cursor},
        "nodes": nodes}}}}}


def test_comments_come_with_their_replies(graphql):
    reply = _comment("dan", "Me too", answer=True)
    graphql.replies = [_comments_page([_comment(replies=[reply], total=3)])]
    comments, cut = gh_data.fetch_discussion_comments("o/r", 7)
    assert not cut
    (c,) = comments
    assert c.author == "carol" and c.reply_count == 3
    assert c.replies[0].author == "dan" and c.replies[0].is_answer
    assert graphql.calls[0][1]["number"] == 7


def test_comments_page_by_cursor_and_say_when_cut(graphql, monkeypatch):
    monkeypatch.setattr(gh_data, "DISCUSSION_COMMENT_PAGES", 2)
    graphql.replies = [_comments_page([_comment()], True, "A"),
                       _comments_page([_comment()], True, "B")]
    comments, cut = gh_data.fetch_discussion_comments("o/r", 7)
    assert len(comments) == 2 and cut
    assert graphql.calls[1][1]["after"] == "A"


def test_comments_of_a_missing_discussion(graphql):
    graphql.replies = [{"data": {"repository": {"discussion": None}}}]
    with pytest.raises(GhError, match="#7 wasn't found"):
        gh_data.fetch_discussion_comments("o/r", 7)


def test_a_comment_is_posted_with_variables(graphql):
    graphql.replies = [{"data": {"addDiscussionComment": {"comment": {"url": "new"}}}}]
    body = 'Says "quotes", \\ and émoji 🎉\nover lines'
    url = gh_data.add_discussion_comment(Discussion(7, "T", node_id="D_7"), body)
    assert url == "new"
    query, variables = graphql.calls[0]
    assert "addDiscussionComment" in query and body not in query
    assert variables == {"id": "D_7", "body": body}


def test_a_refused_comment_says_why(graphql):
    graphql.replies = [{"data": {"addDiscussionComment": None}, "errors": [
        {"message": "Discussion is locked"}]}]
    with pytest.raises(GhError, match="locked"):
        gh_data.add_discussion_comment(Discussion(7, "T", node_id="D_7"), "x")
    with pytest.raises(GhError):
        gh_data.add_discussion_comment(Discussion(7, "T"), "x")  # no id


def test_graphql_sends_variables_on_stdin(monkeypatch, real_graphql):
    import subprocess
    seen = {}

    class Done:
        returncode = 0
        stdout = '{"data": {}}'
        stderr = ""

    def run(args, **kw):
        seen["input"] = kw.get("input")
        return Done()
    monkeypatch.setattr(subprocess, "run", run)
    real_graphql("query($a: Int!) { x }", {"a": 1})
    assert json.loads(seen["input"]) == {"query": "query($a: Int!) { x }",
                                         "variables": {"a": 1}}
    real_graphql("{ x }")
    assert json.loads(seen["input"]) == {"query": "{ x }"}


def test_rows():
    d = Discussion(7, "T", category="Ideas", author="a", comment_count=2,
                   updated_at="2026-10-02T10:00:00Z", upvotes=5)
    row = d.to_row(["number", "category", "title", "answered", "comments", "updated",
                    "state", "upvotes"])
    assert row == {"number": "7", "category": "Ideas", "title": "T", "answered": "",
                   "comments": "2", "updated": "2026-10-02", "state": "Open",
                   "upvotes": "5"}
    d.answerable = True
    assert d.to_row(["answered"])["answered"] == "Unanswered"
    d.answered, d.closed = True, True
    assert d.to_row(["answered", "state"]) == {"answered": "Answered", "state": "Closed"}


# ── The details text (discussionview) ─────────────────────────────────

def _discussion(**over) -> Discussion:
    d = Discussion(7, "Why?", url="https://github.com/o/r/discussions/7", category="Q&A",
                   author="alice", created_at="2026-10-01T10:00:00Z",
                   updated_at="2026-10-02T10:00:00Z", body="Line one\r\nLine two",
                   answerable=True, answered=True, answer_author="bob", comment_count=2)
    for k, v in over.items():
        setattr(d, k, v)
    return d


def test_details_before_the_comments_are_read():
    text, positions = discussionview.discussion_details(_discussion())
    lines = text.split("\n")
    assert lines[0] == "#7 [Q&A] Why?"
    assert "Answered: Yes by bob" in lines
    i = lines.index("URL:")
    assert lines[i + 1] == "https://github.com/o/r/discussions/7"
    assert "Line one" in lines and "Line two" in lines
    assert lines[-1] == "Getting the 2 comments…"
    assert positions == []


def test_details_with_comments_replies_and_the_answer():
    comments = [
        DiscussionComment("carol", "Try this\nand that", "2026-10-04T10:00:00Z",
                          replies=[DiscussionComment("bob", "This works",
                                                     "2026-10-05T10:00:00Z", is_answer=True),
                                   DiscussionComment("x", "spam", "2026-10-05T10:00:00Z",
                                                     minimized=True)],
                          reply_count=4),
        DiscussionComment("dan", "", "2026-10-06T10:00:00Z"),
    ]
    d = _discussion(comments=comments, answer_chosen_at="2026-10-07T00:00:00Z")
    text, positions = discussionview.discussion_details(d)
    lines = text.split("\n")
    assert "Answered: Yes by bob in reply 1 to comment 1 (chosen 2026-10-07)" in lines
    assert "Comments (2, with 2 replies):" in lines
    assert [k for *_, k in positions] == ["comment", "reply", "reply", "comment"]
    heads = [lines[line] for line, _, _ in positions]
    assert heads == [
        "  Comment 1 of 2 — carol (2026-10-04):",
        "      Reply 1 of 4 to comment 1 — bob (2026-10-05), the answer:",
        "      Reply 2 of 4 to comment 1 — x (2026-10-05), hidden on GitHub:",
        "  Comment 2 of 2 — dan (2026-10-06):",
    ]
    # Each stop covers its heading and its own text, not the replies under it.
    line, n, _ = positions[0]
    assert lines[line + 1:line + n] == ["    Try this", "    and that"]
    assert lines[positions[2][0] + 1] == "        (hidden on GitHub)"
    assert "spam" not in text
    assert "      2 more replies on GitHub." in lines


def test_an_answered_comment_and_a_cut_list():
    d = _discussion(comments=[DiscussionComment("a", "x", is_answer=True)],
                    comments_cut=True)
    text, _ = discussionview.discussion_details(d)
    assert "Answered: Yes by bob in comment 1" in text
    assert "1 of 1 — a (), the answer:" in text
    assert text.endswith("More comments on GitHub: press Enter to open the discussion there.")


def test_answer_line_by_category():
    assert discussionview.answer_line(_discussion(answerable=False)) == ""
    assert discussionview.answer_line(_discussion(answered=False)) == "Answered: No"


def test_no_comments_and_no_body():
    text, positions = discussionview.discussion_details(
        _discussion(body="", comment_count=0, answerable=False))
    assert text.split("\n")[-1] == "(no description)"
    assert positions == [] and "Answered" not in text and "Getting" not in text


def test_status_and_empty_text():
    off = Discussions(items=[], enabled=False)
    assert discussionview.status_message(off, "o/r", "open", 100) == (
        "o/r has discussions turned off.")
    assert discussionview.empty_text(off, "o/r", "open") == "o/r has discussions turned off."
    none = Discussions(items=[])
    assert discussionview.empty_text(none, "o/r", "closed") == "o/r has no closed discussions."
    assert discussionview.status_message(none, "o/r", "all", 100) == "o/r — 0 discussions."
    some = Discussions(items=[_discussion(), _discussion()], more=True, total=9)
    assert discussionview.status_message(some, "o/r", "open", 2) == (
        "o/r — 2 open discussions of 9, most recently active first. Ctrl++ shows more.")


# ── The view ───────────────────────────────────────────────────────────

wx = None
try:  # the frame tests need wx; the rest of this file doesn't
    import wx  # noqa: F811
except ImportError:  # pragma: no cover
    pass
needs_wx = pytest.mark.skipif(wx is None, reason="wxPython not installed")

if wx is not None:
    import announce
    import ghviewer
    Frame = ghviewer.GhViewerFrame


class FakeText:
    def __init__(self, value="") -> None:
        self.value = value
        self.point = 0

    def SetValue(self, v):
        self.value, self.point = v, 0

    def GetValue(self):
        return self.value

    def Clear(self):
        self.value = ""

    def GetInsertionPoint(self):
        return self.point

    def SetInsertionPoint(self, p):
        self.point = p


def _frame(**attrs):
    frame = SimpleNamespace(
        details_text=FakeText(), items=[], git_items=[], repo="o/r", current_limit=100,
        view_mode=ghviewer.VIEW_DISCUSSIONS, status=[], told=[], announced=[],
        _detail_gen=1, _comment_positions=[], _current_comment=-1,
        _fetch_is_current=lambda token: token == 1,
        _populate_filtered_list=lambda items, use_favorite_prefix=False: list(items),
        _update_title=lambda: None,
        _take_pending_row=lambda items, token: 0,
    )
    frame._set_view_status = lambda message, keys="": frame.status.append((message, keys))
    frame._tell = frame.told.append
    frame._announce = frame.announced.append
    frame._line_to_position = lambda line: Frame._line_to_position(frame, line)
    frame._render_discussion = lambda item, keep_place=False: Frame._render_discussion(
        frame, item, keep_place)
    for k, v in attrs.items():
        setattr(frame, k, v)
    return frame


@needs_wx
def test_the_view_is_wired_up():
    v = ghviewer.VIEW_DISCUSSIONS
    assert ghviewer.VIEW_COLUMNS[v] is ghviewer.DISCUSSION_SET
    assert Frame._VIEW_LABELS[v] == "Discussions"
    assert (v, "Discussions") in ghviewer.REPO_GO_TO
    assert v not in ghviewer.REPOLESS_VIEWS and v not in ghviewer.NO_MORE_VIEWS
    assert ghviewer.ADDRESS_VIEWS["discussion"] == v and "discussion" in ghviewer.PENDING_KINDS
    headings = [c.heading for c in ghviewer.DISCUSSION_SET.defs(
        list(ghviewer.DISCUSSION_SET.defaults))]
    assert headings == ["Number", "Category", "Title", "Author", "Answered", "Comments",
                        "Updated"]


@needs_wx
def test_discussions_land_in_the_list_and_a_stale_load_is_dropped(monkeypatch):
    calls = []
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda ms, fn, *a: calls.append((fn, a)))
    frame = _frame(_focus_list=lambda row: None)
    result = Discussions(items=[_discussion()])
    Frame._on_discussions_loaded(frame, 2, result, "open")
    assert frame.git_items == [] and frame.status == []
    Frame._on_discussions_loaded(frame, 1, result, "open")
    assert frame.git_items == result.items and calls[0][1] == (0,)
    message, keys = frame.status[-1]
    assert message == "o/r — 1 open discussion." and "M=comment" in keys


@needs_wx
def test_discussions_turned_off_are_said_aloud(monkeypatch):
    spoken = []
    monkeypatch.setattr(announce, "announce", lambda text, cat=None, force=False:
                        spoken.append((text, cat)))
    frame = _frame()
    Frame._on_discussions_loaded(frame, 1, Discussions(items=[], enabled=False), "open")
    assert frame.details_text.value == "o/r has discussions turned off."
    assert spoken == [("o/r has discussions turned off.", announce.STATUS)]
    assert frame.status[-1][1] == "R=refresh  Ctrl+F=filter"
    # M then says so too, rather than "select one".
    frame._focused_item = lambda: None
    Frame._comment_on_discussion(frame)
    assert frame.told == ["o/r has discussions turned off."]


@needs_wx
def test_selecting_one_shows_it_and_reads_its_comments_after_a_pause(monkeypatch):
    later = []
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda ms, fn, *a: later.append((ms, fn)))
    d = _discussion()
    frame = _frame(git_items=[d])
    frame._fetch_discussion_comments_later = lambda item, gen: later.append(("fetch", item))
    Frame._show_discussion_details(frame, 0)
    assert frame.details_text.value.startswith("#7 [Q&A] Why?")
    assert later == [("fetch", d)]
    # Read already, or none to read: no fetch.
    later.clear()
    d.comments = []
    Frame._show_discussion_details(frame, 0)
    assert later == []
    Frame._show_discussion_details(frame, 4)
    assert frame.details_text.value == ""


@needs_wx
def test_the_fetch_waits_and_is_dropped_when_the_selection_moved(monkeypatch):
    later, started = [], []
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda ms, fn, *a: later.append((ms, fn)))
    monkeypatch.setattr(ghviewer.threading, "Thread",
                        lambda target, daemon: SimpleNamespace(start=lambda: started.append(1)))
    frame = _frame()
    Frame._fetch_discussion_comments_later(frame, _discussion(), 1)
    ms, start = later[0]
    assert ms == 250 and started == []
    frame._detail_gen = 2  # moved on
    start()
    assert started == []
    frame._detail_gen = 1
    start()
    assert started == [1]


@needs_wx
def test_comments_arriving_keep_the_caret_where_it_was():
    d = _discussion()
    frame = _frame(git_items=[d], FindFocus=lambda: None)
    frame._shows = lambda view, item, gen: gen == 1 and item is d
    Frame._render_discussion(frame, d)
    frame.FindFocus = lambda: frame.details_text  # reading the body
    text = frame.details_text.value
    caret = text.index("Line two") + 3
    frame.details_text.point = caret
    comments = [DiscussionComment("carol", "Hi", "2026-10-04T10:00:00Z", is_answer=True)]
    Frame._on_discussion_comments(frame, 1, d, comments, False, "")
    assert d.comments == comments
    # The Answered line grew; the caret is still in "Line two", 3 in.
    new = frame.details_text.value
    assert new.index("Line two") + 3 == frame.details_text.point
    assert "in comment 1" in new
    assert frame._comment_positions and frame._current_comment == -1


@needs_wx
def test_comments_for_a_row_left_are_kept_but_not_shown():
    d = _discussion()
    frame = _frame(details_text=FakeText("other"))
    frame._shows = lambda view, item, gen: False
    Frame._on_discussion_comments(frame, 1, d, [], False, "")
    assert d.comments == [] and frame.details_text.value == "other"


@needs_wx
def test_comments_that_fail_say_so_in_place_of_getting():
    d = _discussion()
    frame = _frame(FindFocus=lambda: None)
    frame._shows = lambda view, item, gen: True
    Frame._render_discussion(frame, d)
    Frame._on_discussion_comments(frame, 1, d, None, False, "HTTP 502")
    assert frame.details_text.value.endswith("\nCouldn't read the comments: HTTP 502")
    assert "Getting" not in frame.details_text.value
    assert d.comments is None


@needs_wx
def test_m_refuses_a_locked_discussion_and_a_second_post():
    d = _discussion(locked=True)
    frame = _frame(_focused_item=lambda: d)
    Frame._comment_on_discussion(frame)
    assert frame.told[-1] == "Discussion #7 is locked, so it can't take comments."
    d.locked = False
    frame._discussion_comment_busy = True
    Frame._comment_on_discussion(frame)
    assert frame.told[-1] == "Still adding the last comment."


class _Dialog:
    value = "My comment"
    result = None  # set to wx.ID_OK in the test

    def __init__(self, parent, message, caption, value="", style=0):
        _Dialog.message = message

    def ShowModal(self):
        return _Dialog.result

    def GetValue(self):
        return _Dialog.value

    def Destroy(self):
        pass


@needs_wx
def test_m_posts_then_reads_the_comments_again(monkeypatch):
    posted, after = [], []
    _Dialog.result = wx.ID_OK
    monkeypatch.setattr(ghviewer.wx, "TextEntryDialog", _Dialog)
    monkeypatch.setattr(ghviewer, "add_discussion_comment",
                        lambda d, body: posted.append((d.number, body)) or "u")
    fresh = [DiscussionComment("me", "My comment")]
    monkeypatch.setattr(ghviewer, "fetch_discussion_comments", lambda repo, n: (fresh, False))
    monkeypatch.setattr(ghviewer.wx, "CallAfter", lambda fn, *a: after.append((fn, a)))
    monkeypatch.setattr(ghviewer.threading, "Thread",
                        lambda target, daemon: SimpleNamespace(start=target))
    d = _discussion()
    frame = _frame(_focused_item=lambda: d)
    frame._on_discussion_comment_done = lambda *a: after.append(("done", a))
    Frame._comment_on_discussion(frame)
    assert "discussion #7" in _Dialog.message and "Why?" in _Dialog.message
    assert posted == [(7, "My comment")] and frame._discussion_comment_busy
    fn, args = after[-1]
    assert args == (d, True, fresh, False, "")


@needs_wx
def test_m_with_nothing_typed_posts_nothing(monkeypatch):
    _Dialog.result, _Dialog.value = wx.ID_OK, "   "
    monkeypatch.setattr(ghviewer.wx, "TextEntryDialog", _Dialog)
    monkeypatch.setattr(ghviewer, "add_discussion_comment",
                        lambda d, body: pytest.fail("posted"))
    frame = _frame(_focused_item=lambda: _discussion())
    Frame._comment_on_discussion(frame)
    assert not getattr(frame, "_discussion_comment_busy", False)
    _Dialog.value = "My comment"


@needs_wx
def test_after_posting_the_comments_and_row_are_brought_up_to_date():
    d = _discussion()
    redrawn = []
    frame = _frame(_focused_item=lambda: d, _row_of=lambda item: 3,
                   _redraw_row=lambda row, item: redrawn.append(row),
                   _discussion_comment_busy=True)
    fresh = [DiscussionComment("a", "x"), DiscussionComment("b", "y"),
             DiscussionComment("me", "new")]
    Frame._on_discussion_comment_done(frame, d, True, fresh, False, "")
    assert d.comments == fresh and d.comment_count == 3 and redrawn == [3]
    assert "Comment 3 of 3 — me" in frame.details_text.value
    assert frame.told == ["Comment added to discussion #7."]
    assert not frame._discussion_comment_busy


@needs_wx
def test_a_failed_post_is_said():
    frame = _frame(_discussion_comment_busy=True)
    Frame._on_discussion_comment_done(frame, _discussion(), False, None, False, "locked")
    assert frame.told == ["Couldn't add the comment. locked"]
    assert not frame._discussion_comment_busy


@needs_wx
def test_sorting_is_refused_aloud():
    frame = _frame(_update_menu_checks=lambda: None)
    Frame.on_sort_selected(frame, SimpleNamespace(GetId=lambda: 0))
    assert frame.told == ["Discussions are listed most recently active first, "
                          "so they aren't sorted."]


@needs_wx
def test_copy_and_favorite():
    d = _discussion()
    v = ghviewer.copy_values(d)
    assert (v.ident, v.title, v.link) == ("#7", "Why?", d.url)
    assert v.markdown == f"[#7 Why?]({d.url})"
    frame = SimpleNamespace(repo="o/r", view_mode=ghviewer.VIEW_DISCUSSIONS)
    fav = Frame._build_favorite_entry(frame, d)
    assert (fav.item_type, fav.title, fav.url) == ("discussion", "#7 — Why?", d.url)


@needs_wx
def test_a_discussion_address_opens_here():
    t = ghviewer.parse_github_url("https://github.com/o/r/discussions/12")
    assert (t.repo, t.kind, t.ref) == ("o/r", "discussion", "12")


@needs_wx
def test_a_discussion_notification_opens_here_on_it():
    calls = []
    frame = SimpleNamespace(
        _open_repo_from_list=lambda repo, item, view: calls.append((repo, view)),
        _set_pending_target=lambda view, kind, ref: calls.append((view, kind, ref)))
    v = ghviewer.VIEW_DISCUSSIONS
    numbered = gh_data.parse_notification({
        "id": "1", "unread": False, "reason": "comment",
        "repository": {"full_name": "o/r"},
        "subject": {"title": "Why?", "type": "Discussion",
                    "url": "https://api.github.com/repos/o/r/discussions/12"}})
    Frame._open_discussion_here(frame, numbered)
    assert calls == [("o/r", v), (v, "discussion", "12")]
    # GitHub often gives no address for a discussion: found by its title.
    calls.clear()
    bare = gh_data.parse_notification({
        "id": "2", "unread": False, "reason": "comment",
        "repository": {"full_name": "o/r"},
        "subject": {"title": "Why?", "type": "Discussion", "url": None}})
    Frame._open_discussion_here(frame, bare)
    assert calls == [("o/r", v), (v, "discussion_title", "Why?")]


@needs_wx
def test_enter_on_a_discussion_notification_comes_here_ctrl_o_goes_to_github(monkeypatch):
    opened, here = [], []
    monkeypatch.setattr(ghviewer.webbrowser, "open", opened.append)
    note = gh_data.Notification("1", "Why?", "o/r", subject_type="Discussion", unread=False,
                                url="https://github.com/o/r/discussions")
    frame = SimpleNamespace(_open_discussion_here=here.append, _announce=lambda m: None)
    Frame._open_notification(frame, note)
    assert here == [note] and opened == []
    Frame._open_notification(frame, note, in_browser=True)
    assert opened == ["https://github.com/o/r/discussions"]


@needs_wx
def test_landing_on_a_discussion_by_number_or_title(monkeypatch):
    later = []
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda ms, fn, *a: later.append(a))
    items = [_discussion(number=3, title="A"), _discussion(number=9, title="B")]
    v = ghviewer.VIEW_DISCUSSIONS

    def frame(kind, ref):
        return SimpleNamespace(_pending_target=(1, v, kind, ref), view_mode=v,
                               _row_of=lambda it: items.index(it),
                               _describe_landing=Frame._describe_landing,
                               _announce=lambda m: None)
    assert Frame._take_pending_row(frame("discussion", "9"), items, 1) == 1
    assert later[-1] == ("Opened discussion #9 — B",)
    assert Frame._take_pending_row(frame("discussion_title", "A"), items, 1) == 0
    assert Frame._take_pending_row(frame("discussion", "44"), items, 1) == 0
    assert later[-1] == ("Discussion #44 isn't among the 2 most recently active "
                         "discussions.",)
    Frame._take_pending_row(frame("discussion_title", "Gone"), [], 1)
    assert later[-1] == ("The discussion “Gone” wasn't found: there are no discussions "
                         "to show.",)
