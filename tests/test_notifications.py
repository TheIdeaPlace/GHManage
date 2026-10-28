"""Notifications: parsing GitHub's threads, and what the view does with them."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

import gh_data
from gh_data import Notification, parse_notification


def _raw(n=1, kind="PullRequest", path="pulls/12", unread=True, reason="review_requested",
         repo="o/r", title="Fix it"):
    return {
        "id": str(n), "unread": unread, "reason": reason,
        "updated_at": "2026-10-05T12:00:00Z",
        "subject": {"title": title, "type": kind,
                    "url": f"https://api.github.com/repos/{repo}/{path}" if path else None},
        "repository": {"full_name": repo},
    }


@pytest.mark.parametrize("kind, path, url, number, own", [
    ("PullRequest", "pulls/12", "https://github.com/o/r/pull/12", 12, True),
    ("Issue", "issues/7", "https://github.com/o/r/issues/7", 7, True),
    ("Commit", "commits/abc", "https://github.com/o/r/commit/abc", 0, True),
    ("Discussion", "discussions/11422", "https://github.com/o/r/discussions/11422", 0, True),
    ("RepositoryAdvisory", "security-advisories/GHSA-x", "https://github.com/o/r/security/advisories/GHSA-x", 0, True),
    ("Release", "releases/123", "https://github.com/o/r/releases", 0, False),
    ("CheckSuite", None, "https://github.com/o/r/actions", 0, False),
    ("RepositoryInvitation", None, "https://github.com/o/r/invitations", 0, False),
])
def test_subject_addresses_become_pages(kind, path, url, number, own):
    n = parse_notification(_raw(kind=kind, path=path))
    assert (n.url, n.number, n.own_page) == (url, number, own)
    assert n.is_item == (kind in ("Issue", "PullRequest"))


def test_row_and_words():
    n = parse_notification(_raw())
    row = n.to_row(gh_data.NOTIFICATION_COLUMNS)
    assert row["status"] == "unread"
    assert row["reason"] == "review requested"
    assert row["type"] == "PR"
    assert row["title"] == "#12 Fix it"
    assert row["repo"] == "o/r"
    read = parse_notification(_raw(unread=False, reason="ci_activity", kind="CheckSuite", path=None))
    row = read.to_row(gh_data.NOTIFICATION_COLUMNS)
    assert (row["status"], row["reason"], row["type"], row["title"]) == ("read", "CI activity", "CI run", "Fix it")


def test_status_column_comes_last():
    assert gh_data.NOTIFICATION_DEFAULT_COLUMNS[-1] == "status"


def test_unknown_reason_reads_as_words():
    assert parse_notification(_raw(reason="some_new_thing")).reason_display == "some new thing"


def _page(rows, has_next):
    link = 'Link: <https://api.github.com/notifications?page=9>; rel="next"\n' if has_next else ""
    return f"HTTP/2.0 200 OK\n{link}Content-Type: application/json\n\n" + json.dumps(rows)


def test_fetch_follows_the_next_link(fake_gh):
    pages = {1: (_raw_range(0, 50), True), 2: (_raw_range(50, 70), False)}
    fake_gh.route("notifications?all=false",
                  lambda args: _page(*pages[int(args[-1].rsplit("=", 1)[1])]))
    notes, more = gh_data.fetch_notifications(100)
    assert len(notes) == 70 and more is False
    assert all("-i" in c and "per_page=50" in c[-1] for c in fake_gh.calls)


def test_a_full_last_page_is_not_more(fake_gh):
    # Exactly 50: a full page, but GitHub gives no next link.
    fake_gh.route("notifications", _page(_raw_range(0, 50), False))
    notes, more = gh_data.fetch_notifications(50)
    assert len(notes) == 50 and more is False


def test_fetch_stops_at_the_limit_and_says_there_is_more(fake_gh):
    fake_gh.route("notifications", _page(_raw_range(0, 50), True))
    notes, more = gh_data.fetch_notifications(30)
    assert len(notes) == 30 and more is True
    assert len(fake_gh.calls) == 1


def test_a_thread_on_two_pages_is_listed_once(fake_gh):
    pages = {1: (_raw_range(0, 50), True), 2: (_raw_range(49, 60), False)}
    fake_gh.route("notifications",
                  lambda args: _page(*pages[int(args[-1].rsplit("=", 1)[1])]))
    notes, _ = gh_data.fetch_notifications(100)
    assert len(notes) == 60 and len({n.id for n in notes}) == 60


def test_include_read_asks_for_all(fake_gh):
    fake_gh.route("notifications?all=true", _page([], False))
    assert gh_data.fetch_notifications(50, include_read=True) == ([], False)


def _raw_range(a, b):
    return [_raw(i) for i in range(a, b)]


@pytest.mark.parametrize("fn, args, expected", [
    (gh_data.mark_notification_read, ("9",), ["api", "-X", "PATCH", "notifications/threads/9"]),
    (gh_data.mark_notification_done, ("9",), ["api", "-X", "DELETE", "notifications/threads/9"]),
    (gh_data.unsubscribe_notification, ("9",),
     ["api", "-X", "DELETE", "notifications/threads/9/subscription"]),
    (gh_data.mark_all_notifications_read, (), ["api", "-X", "PUT", "notifications", "-F", "read=true"]),
    (gh_data.mark_all_notifications_read, ("2026-10-06T10:00:00Z",),
     ["api", "-X", "PUT", "notifications", "-F", "read=true",
      "-f", "last_read_at=2026-10-06T10:00:00Z"]),
])
def test_changes_call_the_right_endpoint(fake_gh, fn, args, expected):
    fake_gh.route("notifications", "")
    fn(*args)
    assert fake_gh.calls == [expected]


def test_release_page_asks_for_the_release(fake_gh):
    fake_gh.route("repos/o/r/releases/5", {"html_url": "https://github.com/o/r/releases/tag/v1"})
    assert gh_data.release_page("https://api.github.com/repos/o/r/releases/5") == \
        "https://github.com/o/r/releases/tag/v1"


# ── The view ────────────────────────────────────────────────────────────

if os.environ.get("CI"):
    import wx  # noqa: F401
else:
    pytest.importorskip("wx")

import ghviewer  # noqa: E402

Frame = ghviewer.GhViewerFrame


def _note(n, unread=True, number=0):
    return Notification(str(n), f"T{n}", "o/r", unread=unread, number=number,
                        subject_type="Issue" if number else "Release",
                        url=f"https://github.com/o/r/issues/{number}" if number else "u",
                        own_page=bool(number))


class FakeList:
    def __init__(self):
        self.cells = {}
        self.selected = 0

    def SetItem(self, row, col, text): self.cells[(row, col)] = text
    def GetFirstSelected(self): return self.selected
    def Select(self, row, on=True): self.selected = row
    def Focus(self, row): pass


def _frame(notes, focus_pane=1):
    announced = []
    f = SimpleNamespace(
        view_mode=ghviewer.VIEW_NOTIFICATIONS, git_items=list(notes), _shown=list(notes),
        columns=["reason", "title", "status"], list_mode="quick", favorites=[],
        _category_counts={ghviewer.NOTIFICATIONS_ENTRY: 10}, _return_to=None,
        list_ctrl=FakeList(), _announce=announced.append, announced=announced,
        focused=[], details_text=SimpleNamespace(Clear=lambda: None),
        _include_read=False, _notif_more=False, statuses=[],
    )
    f._row_of = lambda it: Frame._row_of(f, it)
    f._row_of_id = lambda it: Frame._row_of_id(f, it)
    f._item_label = lambda it, col: Frame._item_label(f, it, col)
    f._favorite_prefix = lambda it: ""
    f._redraw_row = lambda row, it: Frame._redraw_row(f, row, it)
    f._refresh_category_labels = lambda: None
    f._adjust_unread_count = lambda d: Frame._adjust_unread_count(f, d)
    f._show_details = lambda row: None
    f._focus_list = lambda row=0: f.focused.append(row)
    f._current_focus = lambda: None
    f._pane_index = lambda w: focus_pane
    f._set_notifications_status = lambda: f.statuses.append(
        sum(1 for n in f.git_items if n.unread))

    def populate(items, use_favorite_prefix=False):
        f._shown = list(items)
        return f._shown
    f._populate_filtered_list = populate
    return f


def test_read_updates_the_row_the_count_and_the_status():
    notes = [_note(1), _note(2)]
    f = _frame(notes)
    Frame._on_notification_changed(f, notes[1], "read", "Marked read: T2")
    assert notes[1].unread is False
    assert f.list_ctrl.cells[(1, 2)] == "read"
    assert f._category_counts[ghviewer.NOTIFICATIONS_ENTRY] == 9
    assert f.statuses == [1]
    assert f.announced[-1] == "Marked read: T2"


def test_a_reply_after_a_reload_finds_the_new_copy_by_id():
    old = _note(2)
    reloaded = [_note(1), _note(2)]
    f = _frame(reloaded)
    Frame._on_notification_changed(f, old, "read", "")
    assert reloaded[1].unread is False
    assert f.list_ctrl.cells[(1, 2)] == "read"
    assert f._category_counts[ghviewer.NOTIFICATIONS_ENTRY] == 9


def test_reading_twice_counts_once():
    notes = [_note(1)]
    f = _frame(notes)
    Frame._on_notification_changed(f, notes[0], "read", "")
    Frame._on_notification_changed(f, notes[0], "read", "")
    assert f._category_counts[ghviewer.NOTIFICATIONS_ENTRY] == 9


def test_done_removes_it_and_stays_in_place():
    notes = [_note(1), _note(2), _note(3)]
    f = _frame(notes)
    f.list_ctrl.selected = 1
    Frame._on_notification_changed(f, notes[1], "done", "Done: T2")
    assert [n.id for n in f.git_items] == ["1", "3"]
    assert f.focused == [1]   # the row that was below it
    assert f._category_counts[ghviewer.NOTIFICATIONS_ENTRY] == 9


def test_done_above_where_you_are_keeps_you_on_your_row():
    notes = [_note(1), _note(2), _note(3)]
    f = _frame(notes)
    f.list_ctrl.selected = 2          # you moved on to T3 while it was sent
    Frame._on_notification_changed(f, notes[0], "done", "")
    assert f.focused == [1]           # T3, now one row up


def test_done_on_the_last_row_lands_on_the_new_last():
    notes = [_note(1), _note(2)]
    f = _frame(notes)
    f.list_ctrl.selected = 1
    Frame._on_notification_changed(f, notes[1], "done", "")
    assert f.focused == [0]


def test_done_from_the_details_panel_leaves_focus_there():
    notes = [_note(1), _note(2)]
    f = _frame(notes, focus_pane=2)
    Frame._on_notification_changed(f, notes[0], "done", "")
    assert f.focused == [] and f.list_ctrl.selected == 0


def test_done_on_a_read_one_leaves_the_count():
    notes = [_note(1, unread=False)]
    f = _frame(notes)
    Frame._on_notification_changed(f, notes[0], "done", "")
    assert f._category_counts[ghviewer.NOTIFICATIONS_ENTRY] == 10


def test_unsubscribe_leaves_it_unread():
    notes = [_note(1)]
    f = _frame(notes)
    Frame._on_notification_changed(f, notes[0], "unsubscribe", "Unsubscribed")
    assert notes[0].unread is True
    assert f._category_counts[ghviewer.NOTIFICATIONS_ENTRY] == 10


def test_done_while_away_comes_off_the_list_you_return_to():
    notes = [_note(1, number=4), _note(2)]
    f = _frame([])
    f.view_mode = ghviewer.VIEW_ISSUES
    f._return_to = (ghviewer.VIEW_NOTIFICATIONS, list(notes), False, notes[0], 100)
    Frame._on_notification_changed(f, notes[0], "done", "")
    assert [n.id for n in f._return_to[1]] == ["2"]
    assert f.list_ctrl.cells == {}


def test_enter_on_an_issue_opens_it_here_and_marks_it_read():
    note = _note(1, number=42)
    f = _frame([note])
    changes, opened = [], []
    f._run_notification_change = lambda n, c, announce=False: changes.append(c)
    f._open_item_here = lambda n: opened.append(n)
    Frame._open_notification(f, note)
    assert changes == ["read"]
    assert opened == [note]


def _opening_frame(note):
    """A Notifications frame that records where Enter opens things here."""
    f = _frame([note])
    f.opened = []
    f._tell = lambda msg, *a, **k: f.announced.append(msg)
    f._open_repo_from_list = lambda repo, item, view=ghviewer.VIEW_ISSUES, branch="": (
        f.opened.append(("repo", repo, view)))
    f._set_pending_target = lambda view, kind, ref: f.opened.append(("target", kind, ref))
    f._open_item_here = lambda item, repo="", number=0: f.opened.append(("item", item))
    f._open_address_here = lambda target, item: Frame._open_address_here(f, target, item)
    f._focused_item = lambda: note
    return f


def test_enter_on_a_ci_run_opens_its_runs_here_never_the_browser(monkeypatch):
    note = Notification("1", "CI failed", "o/r", unread=False, subject_type="CheckSuite",
                        url="https://github.com/o/r/actions")
    f = _opening_frame(note)
    opened = []
    monkeypatch.setattr(ghviewer.webbrowser, "open", opened.append)
    f._run_notification_change = lambda *a, **k: pytest.fail("already read")
    Frame._open_notification(f, note)
    assert opened == []
    assert f.opened == [("repo", "o/r", ghviewer.VIEW_WORKFLOW)]


def test_enter_on_a_security_alert_opens_the_repository_s_alerts_here():
    note = Notification("1", "Alert", "o/r", unread=False,
                        subject_type="RepositoryDependabotAlertsThread",
                        url="https://github.com/o/r/security/dependabot")
    f = _opening_frame(note)
    Frame._open_notification(f, note)
    assert f.opened == [("repo", "o/r", ghviewer.VIEW_SECURITY)]


def test_enter_on_something_with_no_view_says_so_aloud(monkeypatch):
    note = Notification("1", "Invite", "o/r", unread=False, subject_type="RepositoryInvitation",
                        url="https://github.com/o/r/invitations")
    f = _opening_frame(note)
    opened = []
    monkeypatch.setattr(ghviewer.webbrowser, "open", opened.append)
    Frame._open_notification(f, note)
    assert opened == [] and f.opened == []
    assert f.announced[-1] == ghviewer.NO_VIEW_SAID


def _sync_threads(monkeypatch):
    monkeypatch.setattr(ghviewer.wx, "CallAfter", lambda fn, *a: fn(*a))

    class Thread:
        def __init__(self, target, daemon=True): self.target = target
        def start(self): self.target()
    monkeypatch.setattr(ghviewer.threading, "Thread", Thread)


RELEASE_NOTE = dict(id="1", title="v2", repo="o/r", unread=False, subject_type="Release",
                    api_url="https://api.github.com/repos/o/r/releases/5",
                    url="https://github.com/o/r/releases")


def test_enter_on_a_release_opens_it_in_releases_here(monkeypatch):
    note = Notification(**RELEASE_NOTE)
    f = _opening_frame(note)
    f._on_release_page = lambda n, url, b: Frame._on_release_page(f, n, url, b)
    opened = []
    monkeypatch.setattr(ghviewer.webbrowser, "open", opened.append)
    monkeypatch.setattr(ghviewer, "release_page", lambda u: "https://github.com/o/r/releases/tag/v2")
    _sync_threads(monkeypatch)
    Frame._open_notification(f, note)
    assert opened == []
    assert f.opened == [("repo", "o/r", ghviewer.VIEW_RELEASES), ("target", "release", "v2")]
    assert f.announced[0] == "Opening v2…"


def test_a_release_whose_page_github_won_t_give_opens_the_releases(monkeypatch):
    note = Notification(**RELEASE_NOTE)
    f = _opening_frame(note)
    f._on_release_page = lambda n, url, b: Frame._on_release_page(f, n, url, b)
    monkeypatch.setattr(ghviewer, "release_page", lambda u: "")
    _sync_threads(monkeypatch)
    Frame._open_notification(f, note)
    assert f.opened == [("repo", "o/r", ghviewer.VIEW_RELEASES)]


def test_a_release_page_that_arrives_after_you_moved_on_opens_nothing(monkeypatch):
    note = Notification(**RELEASE_NOTE)
    f = _opening_frame(note)
    f._on_release_page = lambda n, url, b: Frame._on_release_page(f, n, url, b)
    f._focused_item = lambda: Notification("2", "other", "o/r")
    monkeypatch.setattr(ghviewer, "release_page", lambda u: "https://github.com/o/r/releases/tag/v2")
    _sync_threads(monkeypatch)
    Frame._open_notification(f, note)
    assert f.opened == []


def test_ctrl_o_on_a_release_opens_its_page_on_github(monkeypatch):
    note = Notification(**RELEASE_NOTE)
    f = _opening_frame(note)
    f._on_release_page = lambda n, url, b: Frame._on_release_page(f, n, url, b)
    opened = []
    monkeypatch.setattr(ghviewer.webbrowser, "open", opened.append)
    monkeypatch.setattr(ghviewer, "release_page", lambda u: "https://github.com/o/r/releases/tag/v2")
    _sync_threads(monkeypatch)
    Frame._open_notification(f, note, in_browser=True)
    assert opened == ["https://github.com/o/r/releases/tag/v2"] and f.opened == []
    assert f.announced[-1] == "Opened v2 on GitHub"


def test_changes_go_through_a_patchable_function(monkeypatch):
    # The regression behind looking these up by name: a stub of the module's
    # function must be what runs, or a test can change real notifications.
    called = []
    monkeypatch.setattr(ghviewer, "mark_notification_read", lambda tid: called.append(tid))
    monkeypatch.setattr(ghviewer.wx, "CallAfter", lambda fn, *a: None)

    class Thread:
        def __init__(self, target, daemon=True): self.target = target
        def start(self): self.target()
    monkeypatch.setattr(ghviewer.threading, "Thread", Thread)
    f = _frame([])
    f._NOTIFICATION_CHANGES = Frame._NOTIFICATION_CHANGES
    f._on_notification_changed = lambda *a: None
    Frame._run_notification_change(f, _note(9), "read")
    assert called == ["9"]


def test_favoriting_a_shared_page_is_refused():
    f = _frame([])
    entry = Frame._build_favorite_entry(SimpleNamespace(repo=None), _note(1))
    assert entry is None
    good = Frame._build_favorite_entry(SimpleNamespace(repo=None), _note(1, number=5))
    assert good.url == "https://github.com/o/r/issues/5" and good.title == "#5 — T1"
    del f


def test_view_more_lands_on_the_first_new_one(monkeypatch):
    calls = []
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda ms, fn, *a: calls.append(a))
    f = _frame([])
    f._fetch_is_current = lambda t: True
    f._update_title = lambda: None
    f._notif_loaded_include = False
    # Before: 1..3 shown; 2 was marked done meanwhile, so the reload has
    # 1, 3, then new ones 4, 5.
    seen = frozenset({"1", "2", "3"})
    Frame._on_notifications_loaded(f, 1, [_note(1), _note(3), _note(4), _note(5)], False, seen)
    assert calls[-1] == (2,)


def test_a_complete_unread_list_sets_the_count(monkeypatch):
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda *a: None)
    f = _frame([])
    f._fetch_is_current = lambda t: True
    f._update_title = lambda: None
    Frame._on_notifications_loaded(f, 1, [_note(1), _note(2)], False)
    assert f._category_counts[ghviewer.NOTIFICATIONS_ENTRY] == 2
    Frame._on_notifications_loaded(f, 1, [_note(1)], True)   # more to come: leave it
    assert f._category_counts[ghviewer.NOTIFICATIONS_ENTRY] == 2


def test_mark_all_read_updates_the_list_without_reloading():
    notes = [_note(1), _note(2)]
    f = _frame(notes)
    Frame._on_all_read(f)
    assert not any(n.unread for n in notes)
    assert f._category_counts[ghviewer.NOTIFICATIONS_ENTRY] == 0
    assert f.list_ctrl.cells[(0, 2)] == "read"


@pytest.mark.parametrize("include", [False, True])
def test_status_line_counts_unread(include):
    notes = [_note(1), _note(2, unread=False)]
    f = _frame(notes)
    f._include_read = include
    said = []
    f._set_view_status = lambda m, k="": said.append(m)
    Frame._set_notifications_status(f)
    assert said == ["Notifications — 2, 1 unread, newest first."]


def test_ctrl_d_from_the_repo_list_does_nothing():
    f = _frame([_note(1)], focus_pane=0)
    f._mark_notification_done = lambda: pytest.fail("not from the repo list")
    Frame._delete_focused_item(f)
    assert f.announced == ["Move to the list to delete or mark done (F6)."]


def test_a_restore_from_backspace_keeps_what_the_list_was_loaded_with(monkeypatch):
    # Mark All Read must reach only as far as the list you saw, not to the
    # moment you came back to it.
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda *a: None)
    f = _frame([])
    f._fetch_is_current = lambda t: True
    f._update_title = lambda: None
    old = _note(1)
    old.updated_at = "2026-10-06T10:00:00Z"
    Frame._on_notifications_loaded(f, 1, [old], False)
    assert f._notif_loaded_at == "2026-10-06T10:00:00Z"
    f._category_counts[ghviewer.NOTIFICATIONS_ENTRY] = 7
    Frame._on_notifications_loaded(f, 2, [old], False, old, fresh=False)
    assert f._notif_loaded_at == "2026-10-06T10:00:00Z"
    assert f._category_counts[ghviewer.NOTIFICATIONS_ENTRY] == 7


def test_a_reply_from_the_previous_account_is_ignored():
    notes = [_note(1)]
    f = _frame(notes)
    f._account_gen = 2
    Frame._on_notification_changed(f, notes[0], "read", "", gen=1)
    assert notes[0].unread is True
    assert f._category_counts[ghviewer.NOTIFICATIONS_ENTRY] == 10
