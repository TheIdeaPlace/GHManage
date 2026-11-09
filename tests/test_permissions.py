"""GitHub permissions (#129): what GHManage can use beyond gh's sign-in, one
command for the missing ones, Help > GitHub Permissions, and Permission
Needed boxes that copy the command or show them all."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import gh_data
import permissions
from gh_data import MissingScope

if os.environ.get("CI"):
    import wx  # noqa: F401
else:
    pytest.importorskip("wx")

import ghviewer  # noqa: E402

Frame = ghviewer.GhViewerFrame

HEADERS = ("HTTP/2.0 200 OK\r\nContent-Type: application/json\r\n"
           "X-Oauth-Scopes: delete_repo, gist, project, read:org, repo, workflow\r\n"
           "\r\n{\"login\": \"kellylford\"}")


# ── Which permissions ───────────────────────────────────────────────────


def test_scopes_are_read_from_githubs_header():
    assert permissions.parse_scopes(HEADERS) == {
        "delete_repo", "gist", "project", "read:org", "repo", "workflow"}


def test_a_token_that_doesnt_list_its_scopes_is_unknown():
    assert permissions.parse_scopes("HTTP/2.0 200 OK\r\n\r\n{\"x\": \"X-Oauth-Scopes: a\"}") is None


def test_fetch_asks_github_with_headers(fake_gh):
    fake_gh.route("api -i user", HEADERS)
    assert "project" in permissions.fetch_scopes()


def test_fetch_failing_is_unknown(fake_gh):
    fake_gh.route("api -i user", gh_data.GhError("HTTP 401"))
    assert permissions.fetch_scopes() is None


def test_kellys_sign_in_misses_notifications_and_follow():
    have = permissions.parse_scopes(HEADERS)
    assert [p.scope for p in permissions.missing(have)] == ["notifications", "user:follow"]


def test_broader_scopes_cover_narrower_ones():
    assert not [p for p in permissions.missing({"repo", "user", "project", "notifications"})]


def test_deleting_repositories_only_when_asked():
    assert "delete_repo" not in [p.scope for p in permissions.missing(set())]
    assert "delete_repo" in [p.scope for p in permissions.missing(set(), include_optional=True)]


def test_unknown_scopes_ask_for_everything():
    assert len(permissions.missing(None)) == len(
        [p for p in permissions.PERMISSIONS if not p.optional])


def test_one_command_for_all_of_them():
    assert permissions.command(["notifications", "user:follow"]) == (
        "gh auth refresh -h github.com -s notifications,user:follow")
    assert permissions.command([]) == ""


def test_summary_names_each_with_what_it_is_for():
    text = permissions.summary(permissions.parse_scopes(HEADERS), False)
    lines = text.splitlines()
    assert "user:follow: missing. Follow and unfollow people." in lines
    assert "project: has it. Set an issue's or pull request's projects, and show them in the list." in lines
    assert lines[-1] == "Missing: notifications, user:follow."
    full = permissions.summary({"repo", "user", "project", "notifications", "delete_repo"}, True)
    assert full.splitlines()[-1] == "gh has every permission GHManage uses."
    assert "doesn't say" in permissions.summary(None, False)


def test_every_scope_the_app_asks_for_is_listed():
    # The scopes GHManage's own messages name must all be in the box.
    for scope in ("project", "notifications", gh_data.FOLLOW_SCOPE, gh_data.SECURITY_SCOPE,
                  "delete_repo"):
        assert scope in permissions.BY_SCOPE


# ── Permission Needed box ───────────────────────────────────────────────


def _frame():
    f = SimpleNamespace(announced=[], said=[], opened=[])
    f._announce = f.announced.append
    f._tell_after_box = f.said.append
    f._show_permissions = lambda: f.opened.append("permissions")
    f.PERMISSION_COPY, f.PERMISSION_ALL = Frame.PERMISSION_COPY, Frame.PERMISSION_ALL
    return f


def test_the_box_names_it_and_gives_the_command(message_dialog):
    f = _frame()
    Frame._permission_needed(f, "Watch Settings", "Couldn't check how you watch o/r",
                             MissingScope("notifications"))
    (box,) = message_dialog.shown
    assert box.caption == "Watch Settings"
    assert box.message.splitlines()[0] == ("Couldn't check how you watch o/r. That needs gh's "
                                           "\"notifications\" permission, which gh doesn't ask "
                                           "for when you sign in.")
    assert "gh auth refresh -h github.com -s notifications" in box.message.splitlines()
    assert box.labels == ("&Copy Command", "&All Permissions…", "Close")
    assert f.announced == ["Couldn't check how you watch o/r: it needs gh's "
                           "\"notifications\" permission."]
    assert f.said == [] and f.opened == []


def test_copy_command_copies_it(message_dialog, monkeypatch):
    copied = []
    monkeypatch.setattr(ghviewer, "copy_text", lambda t: copied.append(t) or True)
    message_dialog.answer = ghviewer.wx.ID_YES
    f = _frame()
    Frame._permission_needed(f, "Follow", "Couldn't follow bob", MissingScope("user:follow"))
    assert copied == ["gh auth refresh -h github.com -s user:follow"]
    assert f.said == ["Command copied."]


def test_all_permissions_opens_the_list(message_dialog):
    message_dialog.answer = ghviewer.wx.ID_NO
    f = _frame()
    Frame._permission_needed(f, "Follow", "Couldn't follow bob", MissingScope("user:follow"))
    assert f.opened == ["permissions"]


def test_help_menu_has_github_permissions():
    src = open(ghviewer.__file__, encoding="utf-8").read()
    assert 'help_menu.Append(ID_PERMISSIONS, "GitHub Permissions…")' in src


# ── Running the command ─────────────────────────────────────────────────


def test_windows_runs_it_in_a_new_console_that_stays(monkeypatch):
    seen = []
    monkeypatch.setattr(ghviewer.sys, "platform", "win32")
    monkeypatch.setattr(ghviewer.subprocess, "Popen", lambda args, **k: seen.append((args, k)))
    assert ghviewer.run_in_terminal(["gh", "auth", "refresh", "-s", "a,b"])
    args, kwargs = seen[0]
    assert args == ["cmd.exe", "/k", "gh", "auth", "refresh", "-s", "a,b"]


def test_a_mac_runs_it_in_terminal(monkeypatch):
    seen = []
    monkeypatch.setattr(ghviewer.sys, "platform", "darwin")
    monkeypatch.setattr(ghviewer.subprocess, "Popen", lambda args, **k: seen.append(args))
    assert ghviewer.run_in_terminal(["/opt/homebrew/bin/gh", "auth", "refresh", "-s", "a"])
    osa, flag, script = seen[0]
    assert (osa, flag) == ("osascript", "-e")
    assert 'tell application "Terminal"' in script
    assert "do script \"/opt/homebrew/bin/gh auth refresh -s a\"" in script


def test_no_terminal_says_so(monkeypatch):
    def fail(*a, **k):
        raise OSError("no")
    monkeypatch.setattr(ghviewer.sys, "platform", "win32")
    monkeypatch.setattr(ghviewer.subprocess, "Popen", fail)
    assert ghviewer.run_in_terminal(["gh"]) is False
