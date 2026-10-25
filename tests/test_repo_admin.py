"""Archiving and deleting a repository on GitHub from the repository list (#68)."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import gh_data
from gh_data import GhError, MissingScope

if os.environ.get("CI"):
    import wx
else:
    wx = pytest.importorskip("wx")

import ghviewer  # noqa: E402
from favorites import FavoriteEntry  # noqa: E402

Frame = ghviewer.GhViewerFrame

# What gh says when its sign-in lacks the permission.
NO_DELETE_SCOPE = ('HTTP 403: Must have admin rights to Repository. '
                   '(https://api.github.com/repos/me/old)\n'
                   'This API operation needs the "delete_repo" scope. To request it, run:  '
                   'gh auth refresh -h github.com -s delete_repo')


# ── gh_data ─────────────────────────────────────────────────────────────

def test_delete_repo_asks_gh_once_confirmed(fake_gh):
    fake_gh.route("repo delete", "")
    gh_data.delete_repo("me/old")
    assert fake_gh.calls[-1] == ["repo", "delete", "me/old", "--yes"]


def test_delete_without_the_permission_says_how_to_add_it(fake_gh):
    fake_gh.route("repo delete", GhError(NO_DELETE_SCOPE))
    with pytest.raises(MissingScope) as caught:
        gh_data.delete_repo("me/old")
    assert caught.value.scope == "delete_repo"
    assert "gh auth refresh -h github.com -s delete_repo" in str(caught.value)


def test_other_delete_errors_pass_through(fake_gh):
    fake_gh.route("repo delete", GhError("HTTP 404: Not Found"))
    with pytest.raises(GhError) as caught:
        gh_data.delete_repo("me/old")
    assert not isinstance(caught.value, MissingScope)


@pytest.mark.parametrize("archived, verb", [(True, "archive"), (False, "unarchive")])
def test_set_archived(fake_gh, archived, verb):
    fake_gh.route(f"repo {verb}", "")
    gh_data.set_archived("me/old", archived)
    assert fake_gh.calls[-1] == ["repo", verb, "me/old", "--yes"]


@pytest.mark.parametrize("reply, admin, archived", [
    ({"viewerPermission": "ADMIN", "isArchived": False}, True, False),
    ({"viewerPermission": "ADMIN", "isArchived": True}, True, True),
    ({"viewerPermission": "WRITE", "isArchived": False}, False, False),
    ({"viewerPermission": "MAINTAIN"}, False, False),
    ({}, False, False),
])
def test_repo_admin(fake_gh, reply, admin, archived):
    fake_gh.route("repo view me/old", reply)
    info = gh_data.repo_admin("me/old")
    assert (info.admin, info.archived) == (admin, archived)
    assert fake_gh.calls[-1] == ["repo", "view", "me/old", "--json", "viewerPermission,isArchived"]


def test_your_repositories_say_whether_they_are_archived():
    # The repository list asks GitHub for it, so the menu can say Unarchive.
    import inspect
    assert "isArchived" in inspect.getsource(gh_data.list_repos)


# ── The menus ───────────────────────────────────────────────────────────

def _menu_frame(repos=()):
    frame = SimpleNamespace(_pinned_repos=[], favorites=[], _all_repos=list(repos))
    frame._known_archived = lambda repo: Frame._known_archived(frame, repo)
    return frame


def _items(entries):
    out = {}
    for e in entries:
        if e[0] == "item":
            out[e[1]] = e[2]
        elif e[0] == "sub":
            out.update(_items(e[2]))
    return out


def test_a_repository_s_menu_archives_and_deletes():
    items = _items(Frame._repo_context_entries(_menu_frame(), "me/old"))
    assert items[ghviewer.ID_ARCHIVE_REPO] == "Archive Repository…"
    assert items[ghviewer.ID_DELETE_REPO] == "Delete Repository from GitHub…"
    # No shortcut key on either: one slip mustn't reach them.
    assert "\t" not in items[ghviewer.ID_ARCHIVE_REPO] + items[ghviewer.ID_DELETE_REPO]


def test_an_archived_repository_s_menu_unarchives():
    frame = _menu_frame([{"nameWithOwner": "Me/Old", "isArchived": True}])
    items = _items(Frame._repo_context_entries(frame, "me/old"))
    assert items[ghviewer.ID_ARCHIVE_REPO] == "Unarchive Repository…"


def test_saved_searches_and_fixed_entries_offer_neither():
    frame = _menu_frame()
    for data in (ghviewer.SEARCH_ENTRY_PREFIX + "bugs", ghviewer.FAVORITES_ENTRY,
                 *list(ghviewer.ENTRY_VIEWS)[:2]):
        items = _items(Frame._repo_context_entries(frame, data))
        assert ghviewer.ID_DELETE_REPO not in items and ghviewer.ID_ARCHIVE_REPO not in items


def test_the_file_menu_has_both_without_shortcuts():
    import inspect
    src = inspect.getsource(Frame._build_menu)
    assert 'file_menu.Append(ID_ARCHIVE_REPO, "Archive or Unarchive Repository…")' in src
    assert 'file_menu.Append(ID_DELETE_REPO, "Delete Repository from GitHub…")' in src


# ── The handlers ────────────────────────────────────────────────────────

class _List:
    def __init__(self, rows, selected):
        self.rows, self.selected = list(rows), selected

    def GetSelection(self):
        return self.selected

    def GetClientData(self, i):
        return self.rows[i]

    def GetCount(self):
        return len(self.rows)

    def SetSelection(self, i):
        self.selected = i


@pytest.fixture
def now(monkeypatch):
    """Workers and CallAfter run at once, in order."""
    class Thread:
        def __init__(self, target, daemon=None):
            self.target = target

        def start(self):
            self.target()
    monkeypatch.setattr(ghviewer.threading, "Thread", Thread)
    monkeypatch.setattr(ghviewer.wx, "CallAfter", lambda f, *a, **k: f(*a, **k))


def _frame(rows, selected, repos=(), pinned=(), favorites=(), open_repo=None,
           view=ghviewer.VIEW_ISSUES):
    f = SimpleNamespace(repo_list=_List(rows, selected), _all_repos=list(repos),
                        _pinned_repos=list(pinned), favorites=list(favorites),
                        repo=open_repo, view_mode=view, _return_to=None,
                        said=[], told=[], refreshed=0, loads=[], switched=[], titled=0,
                        _REPO_LIST_VIEWS=Frame._REPO_LIST_VIEWS)
    f._announce = f.said.append
    f._tell = lambda msg, *a, **k: f.told.append(msg)
    f._on_action_error = f.said.append
    f._load_items = lambda: f.loads.append("items")
    f._load_favorites_view = lambda: f.loads.append("favorites")
    f._switch_view = f.switched.append

    def title():
        f.titled += 1
    f._update_title = title

    yours = {r["nameWithOwner"].lower() for r in repos}

    def refresh():
        # As _on_repos_loaded does: rebuilt without the repositories of yours
        # that are gone, the selection put back on its entry if it is there.
        rows = f.repo_list.rows
        current = rows[f.repo_list.selected] if f.repo_list.selected >= 0 else None
        gone = yours - {r["nameWithOwner"].lower() for r in f._all_repos}
        f.refreshed += 1
        f.repo_list.rows = [r for r in rows if r.lower() not in gone]
        f.repo_list.selected = (f.repo_list.rows.index(current)
                                if current in f.repo_list.rows else 0)
    f._refresh_repo_list = refresh
    for name in ("_selected_repository", "_with_admin", "_on_archived", "_on_repo_deleted",
                 "_on_delete_scope", "_select_repo_row", "_known_archived", "_shows_repo"):
        setattr(f, name, getattr(Frame, name).__get__(f))
    return f



@pytest.mark.parametrize("rows, selected", [
    (["me/old"], wx.NOT_FOUND),
    ([ghviewer.FAVORITES_ENTRY], 0),
    ([ghviewer.SEARCH_ENTRY_PREFIX + "bugs"], 0),
    ([next(iter(ghviewer.ENTRY_VIEWS))], 0),
])
def test_only_a_repository_can_be_archived_or_deleted(fake_gh, now, rows, selected):
    for action in (Frame.on_delete_repo, Frame.on_archive_repo):
        f = _frame(rows, selected)
        action(f)
        assert f.said == ["Select a repository in the list first."]
    assert fake_gh.calls == []


def test_without_admin_rights_nothing_is_asked(fake_gh, now, monkeypatch):
    fake_gh.route("repo view me/theirs", {"viewerPermission": "WRITE", "isArchived": False})
    monkeypatch.setattr(ghviewer, "DeleteRepoDialog", lambda *a, **k: pytest.fail("asked"))
    monkeypatch.setattr(ghviewer.wx, "MessageBox", lambda *a, **k: pytest.fail("asked"))
    f = _frame(["me/theirs"], 0)
    Frame.on_delete_repo(f)
    assert f.told == ["You need admin rights on me/theirs to delete it."]
    Frame.on_archive_repo(f)
    assert f.told[-1] == "You need admin rights on me/theirs to archive or unarchive it."
    assert not any(c[:2] in (["repo", "delete"], ["repo", "archive"]) for c in fake_gh.calls)


class _Dialog:
    answer = wx.ID_OK

    def __init__(self, parent, repo, archived=False):
        self.repo = repo

    def ShowModal(self):
        return self.answer

    def Destroy(self):
        pass


def test_delete_cleans_up_after_itself(fake_gh, now, monkeypatch):
    fake_gh.route("repo view me/old", {"viewerPermission": "ADMIN", "isArchived": False})
    fake_gh.route("repo delete", "")
    monkeypatch.setattr(ghviewer, "DeleteRepoDialog", _Dialog)
    removed_pins = []
    monkeypatch.setattr(ghviewer, "remove_pinned",
                        lambda name: removed_pins.append(name) or [])
    saved = []
    monkeypatch.setattr(ghviewer, "save_favorites", lambda favs: saved.append(list(favs)))
    favs = [FavoriteEntry(repo="me/old", item_type="issue", url="https://github.com/me/old/issues/1",
                          title="x"),
            FavoriteEntry(repo="me/keep", item_type="repo", url="https://github.com/me/keep",
                          title="y")]
    f = _frame(["me/keep", "me/old", "me/next"], 1,
               repos=[{"nameWithOwner": "me/old"}, {"nameWithOwner": "me/keep"}],
               pinned=["Me/Old"], favorites=favs)
    Frame.on_delete_repo(f)
    assert ["repo", "delete", "me/old", "--yes"] in fake_gh.calls
    assert [r["nameWithOwner"] for r in f._all_repos] == ["me/keep"]
    assert removed_pins == ["me/old"]
    assert [x.repo for x in f.favorites] == ["me/keep"] and saved == [f.favorites]
    assert f.refreshed == 1
    assert f.told[-1] == "Deleted me/old from GitHub."
    assert f.said[:2] == ["Checking your rights on me/old…", "Deleting me/old…"]


def test_cancelling_deletes_nothing(fake_gh, now, monkeypatch):
    fake_gh.route("repo view me/old", {"viewerPermission": "ADMIN"})

    class No(_Dialog):
        answer = wx.ID_CANCEL
    monkeypatch.setattr(ghviewer, "DeleteRepoDialog", No)
    f = _frame(["me/old"], 0, repos=[{"nameWithOwner": "me/old"}])
    Frame.on_delete_repo(f)
    assert not any(c[:2] == ["repo", "delete"] for c in fake_gh.calls)
    assert f.said[-1] == "me/old was not deleted." and f._all_repos


def test_delete_without_the_permission_shows_the_command(fake_gh, now, monkeypatch):
    fake_gh.route("repo view me/old", {"viewerPermission": "ADMIN"})
    fake_gh.route("repo delete", GhError(NO_DELETE_SCOPE))
    monkeypatch.setattr(ghviewer, "DeleteRepoDialog", _Dialog)
    boxes = []
    monkeypatch.setattr(ghviewer.wx, "MessageBox", lambda msg, *a, **k: boxes.append(msg))
    f = _frame(["me/old"], 0, repos=[{"nameWithOwner": "me/old"}])
    Frame.on_delete_repo(f)
    assert "gh auth refresh -h github.com -s delete_repo" in boxes[0]
    assert f._all_repos  # still there
    assert "delete_repo" in f.said[-1]


@pytest.mark.parametrize("archived_before, verb, told", [
    (False, "archive", "Archived me/old. It is read-only on GitHub now."),
    (True, "unarchive", "Unarchived me/old."),
])
def test_archive_and_unarchive(fake_gh, now, monkeypatch, archived_before, verb, told):
    fake_gh.route("repo view me/old", {"viewerPermission": "ADMIN", "isArchived": archived_before})
    fake_gh.route(f"repo {verb}", "")
    asked = []

    def box(msg, title, style, parent):
        asked.append((title, style))
        return wx.YES
    monkeypatch.setattr(ghviewer.wx, "MessageBox", box)
    f = _frame(["me/old"], 0, repos=[{"nameWithOwner": "me/old", "isArchived": archived_before}])
    Frame.on_archive_repo(f)
    assert ["repo", verb, "me/old", "--yes"] in fake_gh.calls
    assert f._all_repos[0]["isArchived"] is (not archived_before)
    assert f.told[-1] == told
    # No is the default answer.
    assert asked[0][1] & wx.NO_DEFAULT


def test_archive_answered_no_changes_nothing(fake_gh, now, monkeypatch):
    fake_gh.route("repo view me/old", {"viewerPermission": "ADMIN", "isArchived": False})
    monkeypatch.setattr(ghviewer.wx, "MessageBox", lambda *a, **k: wx.NO)
    f = _frame(["me/old"], 0)
    Frame.on_archive_repo(f)
    assert not any(c[:2] == ["repo", "archive"] for c in fake_gh.calls)


# ── The dialog ──────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def frame():
    app = wx.App(False)
    f = wx.Frame(None)
    yield f
    f.Destroy()
    app.Destroy()


def test_delete_is_unavailable_until_the_name_is_typed(frame):
    dlg = ghviewer.DeleteRepoDialog(frame, "me/old")
    try:
        assert not dlg.delete_btn.IsEnabled()
        for typed, ok in (("me/ol", False), ("me/old2", False), ("ME/Old", True),
                          ("  me/old ", True), ("", False)):
            dlg.name_ctrl.SetValue(typed)
            assert dlg.delete_btn.IsEnabled() is ok, typed
        # Cancel is the default and Escape's button.
        assert dlg.GetDefaultItem().GetId() == wx.ID_CANCEL
        assert dlg.GetEscapeId() == wx.ID_CANCEL
        assert dlg.name_ctrl.GetName() == "Type me/old to confirm"
    finally:
        dlg.Destroy()


def test_delete_becoming_available_is_said_once(frame, monkeypatch):
    import announce
    heard = []
    a = announce.Announcer()
    a.observers.append(lambda text, category: heard.append((text, category)))
    monkeypatch.setattr(announce, "announcer", a)
    dlg = ghviewer.DeleteRepoDialog(frame, "me/old")
    try:
        for typed in ("me/ol", "me/old", "me/old ", "me/o", "me/old"):
            dlg.name_ctrl.SetValue(typed)
        assert heard == [("The name matches. Delete is available.", announce.HINT)] * 2
    finally:
        dlg.Destroy()


def test_enter_in_the_box_never_deletes(frame, monkeypatch):
    bells = []
    monkeypatch.setattr(wx, "Bell", lambda: bells.append(1))
    dlg = ghviewer.DeleteRepoDialog(frame, "me/old")
    ended = []
    dlg.EndModal = lambda code: ended.append(code)
    try:
        dlg.name_ctrl.SetValue("me/o")
        dlg._on_enter()
        assert bells == [1] and ended == []
        dlg.name_ctrl.SetValue("me/old")
        dlg._on_enter()
        assert ended == []  # it only moves to Delete
    finally:
        dlg.Destroy()


def test_the_warning_suggests_archiving_unless_already_archived(frame):
    for archived, mentioned in ((False, True), (True, False)):
        dlg = ghviewer.DeleteRepoDialog(frame, "me/old", archived)
        try:
            text = " ".join(w.GetLabel() for w in dlg.GetChildren() if isinstance(w, wx.StaticText))
            assert "cannot be undone" in text
            assert ("Archive Repository" in text) is mentioned
        finally:
            dlg.Destroy()


# ── After the review ────────────────────────────────────────────────────

def _admin_ok(fake_gh, repo="me/old", archived=False):
    fake_gh.route(f"repo view {repo}", {"viewerPermission": "ADMIN", "isArchived": archived})


def test_deleting_the_open_repository_leaves_it(fake_gh, now, monkeypatch):
    _admin_ok(fake_gh)
    fake_gh.route("repo delete", "")
    monkeypatch.setattr(ghviewer, "DeleteRepoDialog", _Dialog)
    f = _frame(["me/keep", "me/old"], 1, repos=[{"nameWithOwner": "me/old"}],
               open_repo="Me/Old")
    Frame.on_delete_repo(f)
    assert f.repo is None
    assert f.switched == [ghviewer.VIEW_NOTIFICATIONS] and f.titled == 1


def test_deleting_another_repository_leaves_the_open_one_alone(fake_gh, now, monkeypatch):
    _admin_ok(fake_gh)
    fake_gh.route("repo delete", "")
    monkeypatch.setattr(ghviewer, "DeleteRepoDialog", _Dialog)
    f = _frame(["me/keep", "me/old"], 1, repos=[{"nameWithOwner": "me/old"}],
               open_repo="me/keep")
    Frame.on_delete_repo(f)
    assert f.repo == "me/keep" and f.switched == [] and f.loads == []


def test_after_a_delete_you_are_where_you_moved_to(fake_gh, now, monkeypatch):
    _admin_ok(fake_gh)
    monkeypatch.setattr(ghviewer, "DeleteRepoDialog", _Dialog)
    f = _frame(["me/keep", "me/old", "me/next", "me/other"], 1,
               repos=[{"nameWithOwner": "me/old"}])

    def moved_meanwhile(args):
        f.repo_list.selected = 3  # arrowed to me/other while gh worked
        return ""
    fake_gh.route("repo delete", moved_meanwhile)
    Frame.on_delete_repo(f)
    assert f.repo_list.rows[f.repo_list.selected] == "me/other"


def test_after_a_delete_you_are_on_the_row_that_took_its_place(fake_gh, now, monkeypatch):
    _admin_ok(fake_gh)
    fake_gh.route("repo delete", "")
    monkeypatch.setattr(ghviewer, "DeleteRepoDialog", _Dialog)
    f = _frame(["me/keep", "me/old", "me/next"], 1, repos=[{"nameWithOwner": "me/old"}])
    Frame.on_delete_repo(f)
    assert f.repo_list.rows[f.repo_list.selected] == "me/next"


def test_an_open_favorites_view_loses_the_deleted_repository(fake_gh, now, monkeypatch):
    _admin_ok(fake_gh)
    fake_gh.route("repo delete", "")
    monkeypatch.setattr(ghviewer, "DeleteRepoDialog", _Dialog)
    monkeypatch.setattr(ghviewer, "save_favorites", lambda favs: None)
    favs = [FavoriteEntry(repo="me/old", item_type="repo", url="https://github.com/me/old",
                          title="x")]
    f = _frame(["me/old"], 0, repos=[{"nameWithOwner": "me/old"}], favorites=favs,
               view=ghviewer.VIEW_FAVORITES)
    Frame.on_delete_repo(f)
    assert f.loads == ["favorites"] and f.favorites == []


@pytest.mark.parametrize("call, reply, heard", [
    ("repo view", GhError("HTTP 502"), "Couldn't check me/old: HTTP 502"),
    ("repo delete", GhError("HTTP 500"), "Couldn't delete me/old: HTTP 500"),
])
def test_failures_are_spoken_not_only_shown(fake_gh, now, monkeypatch, call, reply, heard):
    if call != "repo view":
        _admin_ok(fake_gh)
    fake_gh.route(call, reply)
    monkeypatch.setattr(ghviewer, "DeleteRepoDialog", _Dialog)
    f = _frame(["me/old"], 0, repos=[{"nameWithOwner": "me/old"}])
    Frame.on_delete_repo(f)
    assert f.told[-1] == heard
    assert f._all_repos  # nothing removed


def test_a_failed_archive_is_spoken(fake_gh, now, monkeypatch):
    _admin_ok(fake_gh)
    fake_gh.route("repo archive", GhError("HTTP 403"))
    monkeypatch.setattr(ghviewer.wx, "MessageBox", lambda *a, **k: wx.YES)
    f = _frame(["me/old"], 0, repos=[{"nameWithOwner": "me/old", "isArchived": False}])
    Frame.on_archive_repo(f)
    assert f.told[-1] == "Couldn't archive me/old: HTTP 403"
    assert f._all_repos[0]["isArchived"] is False


def test_archiving_reloads_what_shows_it(fake_gh, now, monkeypatch):
    _admin_ok(fake_gh)
    fake_gh.route("repo archive", "")
    monkeypatch.setattr(ghviewer.wx, "MessageBox", lambda *a, **k: wx.YES)
    for open_repo, view, loads in (("me/old", ghviewer.VIEW_ISSUES, ["items"]),
                                   (None, ghviewer.VIEW_STARRED, ["items"]),
                                   ("me/keep", ghviewer.VIEW_ISSUES, [])):
        f = _frame(["me/old"], 0, open_repo=open_repo, view=view)
        Frame.on_archive_repo(f)
        assert f.loads == loads, (open_repo, view)


def test_one_check_at_a_time(fake_gh, monkeypatch):
    # The worker is held back, as a slow network would.
    started = []

    class Thread:
        def __init__(self, target, daemon=None):
            self.target = target

        def start(self):
            started.append(self.target)
    monkeypatch.setattr(ghviewer.threading, "Thread", Thread)
    monkeypatch.setattr(ghviewer.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    _admin_ok(fake_gh)
    monkeypatch.setattr(ghviewer, "DeleteRepoDialog", lambda *a, **k: _Dialog(*a))
    f = _frame(["me/old"], 0, repos=[{"nameWithOwner": "me/old"}])
    Frame.on_delete_repo(f)
    Frame.on_delete_repo(f)
    assert len(started) == 1 and f.told == ["Still working on me/old."]
    started[0]()  # the check finishes; the next one may go ahead
    assert f._admin_pending is None


def test_a_token_without_the_right_gets_a_hint(fake_gh):
    fake_gh.route("repo delete", GhError("HTTP 403: Must have admin rights to Repository. "
                                         "(https://api.github.com/repos/me/old)"))
    with pytest.raises(GhError) as caught:
        gh_data.delete_repo("me/old")
    assert not isinstance(caught.value, MissingScope)
    assert "Administration" in str(caught.value) and "delete_repo" in str(caught.value)


def test_enter_on_a_wrong_name_says_why(frame, monkeypatch):
    import announce
    heard = []
    a = announce.Announcer()
    a.observers.append(lambda text, category: heard.append((text, category)))
    monkeypatch.setattr(announce, "announcer", a)
    monkeypatch.setattr(wx, "Bell", lambda: None)
    dlg = ghviewer.DeleteRepoDialog(frame, "me/old")
    try:
        dlg.name_ctrl.SetValue("me/ol")
        dlg._on_enter()
        assert heard == [("That doesn't match me/old yet.", announce.RESULT)]
    finally:
        dlg.Destroy()
