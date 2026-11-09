"""GitHub permissions (#129): what GHManage can use beyond gh's sign-in, one
command for the missing ones, Help > GitHub Permissions, and Permission
Needed boxes that copy the command or show them all."""

from __future__ import annotations

import os
import subprocess
from types import SimpleNamespace

import pytest

import gh_data
import permissions
from gh_data import MissingScope
from permissions import State

if os.environ.get("CI"):
    import wx  # noqa: F401
else:
    pytest.importorskip("wx")

import ghviewer  # noqa: E402

Frame = ghviewer.GhViewerFrame

HEADERS = ("HTTP/2.0 200 OK\r\nContent-Type: application/json\r\n"
           "X-Oauth-Scopes: delete_repo, gist, project, read:org, repo, workflow\r\n"
           "\r\n{\"login\": \"kellylford\"}")
KELLY = permissions.parse_scopes(HEADERS)


@pytest.fixture(autouse=True)
def _no_token_env(monkeypatch):
    for var in permissions.TOKEN_VARS:
        monkeypatch.delenv(var, raising=False)


# ── Which permissions ───────────────────────────────────────────────────


def test_scopes_and_login_are_read_from_githubs_reply():
    assert permissions.parse_reply(HEADERS) == (
        {"delete_repo", "gist", "project", "read:org", "repo", "workflow"}, "kellylford")


def test_a_token_that_doesnt_list_its_scopes_is_unknown():
    assert permissions.parse_scopes(
        "HTTP/2.0 200 OK\r\n\r\n{\"login\": \"X-Oauth-Scopes: a\"}") is None


def test_state_from_github(fake_gh):
    fake_gh.route("api -i user", HEADERS)
    state = permissions.fetch_state()
    assert (state.login, state.error, state.can_refresh) == ("kellylford", "", True)
    assert "project" in state.scopes


def test_gh_failing_is_said_not_taken_for_unknown(fake_gh):
    fake_gh.route("api -i user", gh_data.GhError(
        "You are not logged into any GitHub hosts. To log in, run: gh auth login"))
    state = permissions.fetch_state()
    assert state.error.startswith("You are not logged into any GitHub hosts")
    assert not state.can_refresh
    text = permissions.summary(state, False)
    assert "Couldn't ask GitHub" in text and "gh auth login" in text
    assert permissions.refresh_command(state, False) == ""


def test_a_token_in_the_environment_cant_be_refreshed(fake_gh, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "ghp_x")
    fake_gh.route("api -i user", HEADERS)
    state = permissions.fetch_state()
    assert state.token_var == "GH_TOKEN" and not state.can_refresh
    text = permissions.summary(state, False)
    assert "GH_TOKEN" in text and permissions.TOKEN_SETTINGS in text
    assert permissions.refresh_command(state, False) == ""


def test_kellys_sign_in_misses_notifications_and_follow():
    assert [p.scope for p in permissions.missing(KELLY)] == ["notifications", "user:follow"]
    assert permissions.refresh_command(State(scopes=KELLY), False) == (
        "gh auth refresh -h github.com -s notifications,user:follow")


def test_broader_scopes_cover_narrower_ones():
    assert not permissions.missing({"repo", "user", "project", "notifications"})


def test_deleting_repositories_only_when_asked():
    assert "delete_repo" not in [p.scope for p in permissions.missing(set())]
    assert "delete_repo" in [p.scope for p in permissions.missing(set(), include_optional=True)]


def test_unknown_scopes_ask_for_everything_and_say_why():
    state = State(scopes=None, login="me")
    assert len(permissions.missing(None)) == len(
        [p for p in permissions.PERMISSIONS if not p.optional])
    text = permissions.summary(state, False)
    assert "doesn't say" in text and "unknown" in text


def test_summary_names_the_account_and_each_permission():
    lines = permissions.summary(State(scopes=KELLY, login="kellylford"), False).splitlines()
    assert lines[0] == "Account: kellylford, the one gh is using now."
    assert "user:follow: missing. Follow and unfollow people." in lines
    assert lines[-1] == "Missing: notifications, user:follow."
    full = permissions.summary(State(scopes={"repo", "user", "project", "notifications",
                                             "delete_repo"}), True)
    assert full.splitlines()[-1] == "gh has every permission GHManage uses."


def test_every_scope_the_app_asks_for_is_listed():
    for scope in ("project", "notifications", gh_data.FOLLOW_SCOPE, gh_data.SECURITY_SCOPE,
                  "delete_repo"):
        assert scope in permissions.BY_SCOPE


# ── Permission Needed box ───────────────────────────────────────────────


def _frame():
    f = SimpleNamespace(announced=[], said=[], opened=[])
    f._announce = f.announced.append
    f._tell_after_box = f.said.append
    f._show_permissions = lambda: f.opened.append("permissions")
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
    assert box.labels == (ghviewer.PERMISSION_COPY, ghviewer.PERMISSION_ALL,
                          ghviewer.PERMISSION_CLOSE)
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


def test_a_404_on_following_keeps_what_github_said(message_dialog):
    # The account may be gone; the box mustn't flatly blame the permission.
    exc = gh_data._follow_error(gh_data.GhError("gh: Not Found (HTTP 404)"), "ghost")
    f = _frame()
    Frame._permission_needed(f, "Follow", "Couldn't follow ghost", exc)
    first = message_dialog.shown[0].message.splitlines()[0]
    assert first.startswith("GitHub said Not Found for ghost. If the account still exists")


def test_with_a_token_in_the_environment_no_command_is_offered(message_dialog, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    message_dialog.answer = ghviewer.wx.ID_YES
    f = _frame()
    Frame._permission_needed(f, "Follow", "Couldn't follow bob", MissingScope("user:follow"))
    (box,) = message_dialog.shown
    assert "gh auth refresh" not in box.message and "GITHUB_TOKEN" in box.message
    assert f.opened == ["permissions"]   # Yes is All Permissions there


def test_mac_keeps_escape_on_the_last_button():
    assert ghviewer.PERMISSION_CLOSE in ("Close", "Cancel")


# ── The Permissions box ─────────────────────────────────────────────────


class FakeCtrl:
    def __init__(self, value=False):
        self.value = value
    def GetValue(self): return self.value
    def ChangeValue(self, v): self.value = v
    def SetInsertionPoint(self, p): pass


def _dialog(state, recheck=None):
    d = SimpleNamespace(_state=state, _recheck=recheck, _checking=False, said=[],
                        optional=FakeCtrl(False), text=FakeCtrl(""), command=FakeCtrl(""))
    d._say = d.said.append
    for name in ("_command", "_cant", "_fill", "copy", "run", "check_again", "_checked"):
        setattr(d, name, (lambda n: lambda *a: getattr(ghviewer.PermissionsDialog, n)(d, *a))(name))
    d.__bool__ = lambda: True
    return d


def test_box_shows_the_command_and_the_checkbox_adds_delete(monkeypatch):
    d = _dialog(State(scopes={"repo", "project"}, login="me"))
    d._fill()
    assert d.command.value == "gh auth refresh -h github.com -s notifications,user:follow"
    d.optional.value = True
    d._fill()
    assert d.command.value.endswith("notifications,user:follow,delete_repo")


@pytest.mark.parametrize("state, why", [
    (State(scopes={"repo", "user", "project", "notifications"}), "nothing to add"),
    (State(error="gh not found"), "can't be asked"),
    (State(scopes={"repo"}, token_var="GH_TOKEN"), "changed on GitHub"),
])
def test_copy_and_run_say_why_there_is_nothing(monkeypatch, state, why):
    monkeypatch.setattr(ghviewer, "run_in_terminal", lambda a: pytest.fail("ran"))
    monkeypatch.setattr(ghviewer, "copy_text", lambda t: pytest.fail("copied"))
    d = _dialog(state)
    d._fill()
    d.copy()
    d.run()
    assert len(d.said) == 2 and all(why in s for s in d.said)


def test_run_opens_a_terminal_with_the_missing_scopes(monkeypatch):
    seen = []
    monkeypatch.setattr(ghviewer, "run_in_terminal", lambda a: seen.append(a) or True)
    monkeypatch.setattr(gh_data, "_find_gh", lambda: "gh")
    d = _dialog(State(scopes={"repo", "project"}))
    d.run()
    assert seen == [["gh", "auth", "refresh", "-h", "github.com", "-s",
                     "notifications,user:follow"]]
    assert "Check Again" in d.said[0]


def test_check_again_asks_off_the_ui_thread_and_says_the_result(monkeypatch):
    from test_set_milestone import NowThread
    monkeypatch.setattr(ghviewer.threading, "Thread", NowThread)
    monkeypatch.setattr(ghviewer.wx, "CallAfter", lambda fn, *a: fn(*a))
    d = _dialog(State(scopes={"repo"}),
                recheck=lambda: State(scopes={"repo", "user", "project", "notifications"}))
    d.check_again()
    assert d.said == ["Checking…", "gh has every permission GHManage uses."]
    assert d._checking is False and d.command.value == "None needed."


# ── Running the command ─────────────────────────────────────────────────


def test_windows_quotes_the_whole_command_for_cmd(monkeypatch):
    seen = []
    monkeypatch.setattr(ghviewer.sys, "platform", "win32")
    monkeypatch.setattr(ghviewer.subprocess, "Popen", lambda cmd, **k: seen.append(cmd))
    assert ghviewer.run_in_terminal([r"C:\Users\R&D\gh.exe", "auth", "refresh", "-s", "a,b"])
    # The path always quoted, & or not; "a,b" too, since cmd splits on commas.
    assert seen == ['cmd.exe /s /k ""C:\\Users\\R&D\\gh.exe" auth refresh -s "a,b""']


@pytest.mark.skipif(os.name != "nt", reason="cmd.exe")
def test_cmd_really_runs_a_path_with_an_ampersand(tmp_path):
    # The reviewer's failing case, run for real: a folder named "R&D" (no
    # space, so nothing but the rule for the program path quotes it). The
    # script hands its arguments to Python, which reads them as gh.exe does.
    import json
    import sys
    folder = tmp_path / "R&D"
    folder.mkdir()
    script = folder / "gh.cmd"
    script.write_text(f'@"{sys.executable}" -c "import sys,json;print(json.dumps(sys.argv[1:]))" %*\n',
                      encoding="utf-8")
    cmd = ghviewer.terminal_command([str(script), "auth", "refresh", "-s", "a,b"]).replace(
        " /k ", " /c ")
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    assert json.loads(out.strip().splitlines()[-1]) == ["auth", "refresh", "-s", "a,b"]


def test_a_mac_opens_a_command_file_in_terminal(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(ghviewer.sys, "platform", "darwin")
    monkeypatch.setattr(ghviewer.tempfile, "mkstemp",
                        lambda **k: (os.open(tmp_path / "x.command", os.O_CREAT | os.O_WRONLY),
                                     str(tmp_path / "x.command")))
    monkeypatch.setattr(ghviewer.subprocess, "run",
                        lambda args, **k: seen.append(args) or SimpleNamespace(returncode=0))
    assert ghviewer.run_in_terminal(["/opt/home brew/gh", "auth", "refresh", "-s", "a"])
    assert seen == [["open", "-a", "Terminal", str(tmp_path / "x.command")]]
    body = (tmp_path / "x.command").read_text(encoding="utf-8")
    assert body == "#!/bin/sh\n'/opt/home brew/gh' auth refresh -s a\n"


def test_a_mac_that_cant_open_terminal_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(ghviewer.sys, "platform", "darwin")
    monkeypatch.setattr(ghviewer.tempfile, "mkstemp",
                        lambda **k: (os.open(tmp_path / "y.command", os.O_CREAT | os.O_WRONLY),
                                     str(tmp_path / "y.command")))
    monkeypatch.setattr(ghviewer.subprocess, "run", lambda a, **k: SimpleNamespace(returncode=1))
    assert ghviewer.run_in_terminal(["gh"]) is False


def test_help_menu_has_github_permissions():
    src = open(ghviewer.__file__, encoding="utf-8").read()
    assert 'help_menu.Append(ID_PERMISSIONS, "GitHub Permissions…")' in src
