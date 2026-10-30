"""Help ▸ Report a Bug: the report, what it says about the computer, sending
it through the relay and falling back, the crash flag and the log; then the
real form, run without showing it. Nothing is sent anywhere."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit

import pytest

import bugreport
from bugreport import BUG, SUGGESTION, Attachment, Report, Result


def _report(**kw) -> Report:
    base = dict(kind=BUG, title="Crash on load", answers=["It closed", "", ""], tag="Windows")
    base.update(kw)
    return Report(**base)


# ── The report ───────────────────────────────────────────────────────────


def test_title_carries_the_platform_and_a_default():
    assert _report().full_title == "[Windows] Crash on load"
    assert _report(title="  ", tag="Mac").full_title == "[Mac] Bug report"
    assert _report(title="", kind=SUGGESTION).full_title == "[Windows] Suggestion"


def test_body_leaves_out_empty_answers_and_uses_the_kinds_headings():
    body = _report(answers=["It closed", "", "Open a repo"], include_system=False).body
    assert body == "**What happened**\nIt closed\n\n**Steps to reproduce**\nOpen a repo"
    body = _report(kind=SUGGESTION, answers=["Dark mode", "Night use", "ignored"],
                   include_system=False).body
    assert body == "**Suggestion**\nDark mode\n\n**How it would help**\nNight use"
    assert _report(answers=["", "", ""], include_system=False).body == "(No details given.)"


def test_system_information_is_included_only_when_checked():
    r = _report(system_text="App: GHManage 1.0 (installed)")
    assert "**System**\n```\nApp: GHManage 1.0 (installed)\n```" in r.body
    r.include_system = False
    assert "System" not in r.body


def test_required_fields():
    assert _report(title=" ").missing() == "title"
    assert _report(answers=[" ", "x", "y"]).missing() == "first"
    assert _report().missing() is None


def test_preview_is_exactly_what_is_sent():
    r = _report(contact="me@example.com", system_text="App: x")
    payload = r.relay_payload()
    assert r.preview == (f"Title: {payload['title']}\nKind: Bug\nContact: me@example.com\n\n"
                         f"{payload['body']}")
    assert payload == {"title": "[Windows] Crash on load", "body": r.body, "kind": "bug",
                       "contact": "me@example.com"}
    assert "contact" not in _report().relay_payload()
    assert _report(kind=SUGGESTION).relay_payload()["kind"] == "suggestion"


def test_attachments_are_offered_and_can_be_left_out():
    r = _report(include_system=False, attachments=[Attachment("the log", "Log", "a\nb")])
    assert r.attachments_label == "Include the log"
    assert r.body.endswith("**Log**\n```\na\nb\n```")
    r.include_attachments = False
    assert "Log" not in r.body
    two = _report(attachments=[Attachment("the error", "E", "x"), Attachment("the log", "L", "y")])
    assert two.attachments_label == "Include the error and the log"


def test_a_long_attachment_keeps_its_last_lines_within_the_limit():
    lines = [f"line {i:05d} " + "x" * 60 for i in range(400)]
    r = _report(attachments=[Attachment("the log", "Log", "\n".join(lines))])
    body = r.body
    assert len(body) <= bugreport.LONGEST_BODY
    assert bugreport.LINES_LEFT_OUT in body
    assert lines[-1] in body and lines[0] not in body
    assert body.rstrip().endswith("```")


def test_an_attachment_with_no_room_says_it_was_left_out():
    # One line far longer than the room: not even a line of it fits.
    r = _report(include_system=False,
                attachments=[Attachment("the log", "Log", "y" * (bugreport.LONGEST_BODY + 1))])
    assert r.body.endswith(bugreport.DIDNT_FIT)
    assert len(r.body) <= bugreport.LONGEST_BODY


def test_issue_page_is_prefilled_and_cut_to_fit():
    r = _report(contact="me")
    url = r.issue_page_url()
    assert url.startswith("https://github.com/TheIdeaPlace/GHManage/issues/new?")
    q = parse_qs(urlsplit(url).query)
    assert q["title"] == ["[Windows] Crash on load"]
    assert q["labels"] == ["bug,user-reported,windows"]
    assert q["body"][0].startswith("**What happened**\nIt closed")
    assert q["body"][0].endswith("**Contact**\nme")
    long = _report(answers=["é" * 5000, "", ""])
    url = long.issue_page_url()
    assert len(url) <= bugreport.LONGEST_PAGE_ADDRESS
    assert parse_qs(urlsplit(url).query)["body"][0].endswith("paste the rest from the clipboard.)")
    assert _report(kind=SUGGESTION, tag="Mac").labels == "enhancement,user-reported,mac"


def test_clipboard_has_the_title_body_and_contact():
    assert _report(contact="me").clipboard_text == (
        "[Windows] Crash on load\n\n" + _report().body + "\n\n**Contact**\nme")


# ── Privacy ──────────────────────────────────────────────────────────────


def test_redact_replaces_the_home_folder_either_slash_any_case():
    home = r"C:\Users\kelly"
    text = ('File "C:\\Users\\kelly\\GitHub\\x.py", line 3\n'
            "c:/users/KELLY/AppData/y\nC:\\Users\\kellyford\\z")
    out = bugreport.redact(text, home)
    assert 'File "~\\GitHub\\x.py"' in out
    assert "~/AppData/y" in out
    assert "C:\\Users\\kellyford\\z" in out  # another person's folder isn't this one
    assert bugreport.redact("/Users/kelly/x and /Users/kelly", "/Users/kelly") == "~/x and ~"
    assert bugreport.redact("anything", "/") == "anything"


def test_system_lines_are_the_allowed_list():
    text = bugreport.system_lines("installed", "Windows 11 (10.0.26100)", "AMD64", "NVDA",
                                  "en-US", "2.80.0")
    assert [line.split(":")[0] for line in text.splitlines()] == [
        "App", "OS", "Architecture", "Screen reader", "Language", "GitHub CLI"]
    assert text.startswith(f"App: GHManage {bugreport.APP_VERSION} (installed)")


def test_screen_readers_named_from_process_names():
    assert bugreport.readers_in(["explorer.exe", "NVDA.exe", "jfw.exe"]) == "JAWS, NVDA"
    assert bugreport.readers_in(["explorer.exe"]) == "none detected"


def test_collect_system_text_runs_here(monkeypatch):
    monkeypatch.setattr(bugreport, "_gh_version", lambda exe: "2.0.0")
    text = bugreport.collect_system_text()
    assert "GitHub CLI: 2.0.0" in text
    assert "App: GHManage" in text
    assert os.path.expanduser("~") not in text


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process list")
def test_windows_process_list_includes_this_python():
    names = [n.lower() for n in bugreport._windows_processes()]
    assert os.path.basename(sys.executable).lower() in names


def test_gh_version_when_gh_is_missing():
    assert bugreport._gh_version(os.path.join("no", "such", "gh-xyz")) == "not found"


# ── Sending ──────────────────────────────────────────────────────────────


def test_no_key_sends_nothing():
    called = []
    result = bugreport.send(_report(), "https://relay/report", "", lambda *a: called.append(a))
    assert result.no_key and not result.filed and called == []
    assert bugreport.send(_report(), "", "k", lambda *a: called.append(a)).no_key


def test_sends_the_app_id_and_key_in_headers_only():
    seen = {}

    def transport(url, data, headers, timeout):
        seen.update(url=url, data=data, headers=headers, timeout=timeout)
        return 200, json.dumps({"issueUrl": "https://github.com/TheIdeaPlace/GHManage/issues/7",
                                "number": 7})

    result = bugreport.send(_report(), "https://relay/report", "secret", transport)
    assert result == Result(7, "https://github.com/TheIdeaPlace/GHManage/issues/7")
    assert seen["headers"]["X-AppKit-App"] == "ghmanage"
    assert seen["headers"]["X-AppKit-Key"] == "secret"
    assert seen["timeout"] == bugreport.TIMEOUT
    # Cloudflare refuses urllib's default agent before the relay sees it.
    assert seen["headers"]["User-Agent"].startswith("GHManage/")
    assert b"secret" not in seen["data"]
    assert json.loads(seen["data"]) == _report().relay_payload()


@pytest.mark.parametrize("status,body", [
    (401, "Unauthorized."),
    (502, "Could not create the issue."),
    (200, "not json"),
    (200, "[]"),
    (200, json.dumps({"issueUrl": "http://insecure", "number": 3})),
    (200, json.dumps({"issueUrl": "https://x", "number": 0})),
    (200, json.dumps({"issueUrl": "https://x", "number": True})),
])
def test_anything_but_a_filed_issue_falls_back(status, body):
    result = bugreport.send(_report(), "https://r", "k", lambda *a: (status, body))
    assert not result.filed and not result.no_key


def test_a_network_failure_falls_back():
    def transport(*a):
        raise TimeoutError("slow")
    assert not bugreport.send(_report(), "https://r", "k", transport).filed


def test_the_real_transport_against_a_local_server():
    """urllib end to end, against a server on this machine standing in for
    the relay: the headers arrive, a 401 is an answer and not an exception."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    got = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            got["key"] = self.headers["X-AppKit-Key"]
            got["body"] = self.rfile.read(int(self.headers["Content-Length"]))
            ok = got["key"] == "right"
            reply = (json.dumps({"issueUrl": "https://github.com/x/y/issues/5", "number": 5})
                     if ok else "Unauthorized.").encode()
            self.send_response(200 if ok else 401)
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/report"
        assert bugreport.send(_report(), url, "right").number == 5
        assert json.loads(got["body"])["title"] == "[Windows] Crash on load"
        wrong = bugreport.send(_report(), url, "wrong")
        assert not wrong.filed and not wrong.no_key
    finally:
        server.shutdown()


def test_relay_config_from_the_environment_or_the_build(monkeypatch):
    monkeypatch.delenv("GHMANAGE_RELAY_URL", raising=False)
    monkeypatch.delenv("GHMANAGE_RELAY_KEY", raising=False)
    monkeypatch.setattr(bugreport, "_relay_config", None)
    assert bugreport.relay_config() == ("", "")
    from types import SimpleNamespace
    monkeypatch.setattr(bugreport, "_relay_config", SimpleNamespace(RELAY_URL="https://a", RELAY_KEY="k"))
    assert bugreport.relay_config() == ("https://a", "k")
    monkeypatch.setenv("GHMANAGE_RELAY_URL", "https://b")
    assert bugreport.relay_config() == ("https://a", "k")  # both or neither
    monkeypatch.setenv("GHMANAGE_RELAY_KEY", "k2")
    assert bugreport.relay_config() == ("https://b", "k2")


def test_write_relay_config(tmp_path, monkeypatch):
    sys.path.insert(0, str(bugreport.Path(__file__).resolve().parent.parent / "scripts"))
    try:
        import write_relay_config as w
    finally:
        sys.path.pop(0)
    out = tmp_path / "_relay_config.py"
    monkeypatch.delenv("APPKIT_RELAY_URL", raising=False)
    monkeypatch.setenv("APPKIT_RELAY_KEY", "k'\"x")
    assert w.main(["w", str(out)]) == 1 and not out.exists()
    monkeypatch.setenv("APPKIT_RELAY_URL", "http://plain")
    assert w.main(["w", str(out)]) == 1
    monkeypatch.setenv("APPKIT_RELAY_URL", "https://relay/report")
    assert w.main(["w", str(out)]) == 0
    ns: dict = {}
    exec(out.read_text(encoding="utf-8"), ns)
    assert (ns["RELAY_URL"], ns["RELAY_KEY"]) == ("https://relay/report", "k'\"x")


def test_relay_config_is_never_committed():
    root = bugreport.Path(__file__).resolve().parent.parent
    assert "/_relay_config.py" in (root / ".gitignore").read_text(encoding="utf-8").splitlines()


# ── The quit flag ────────────────────────────────────────────────────────


def test_a_clean_quit_offers_nothing():
    assert bugreport.begin_run(pid=10, is_running=lambda p: False, boot_time=0) is None
    bugreport.end_run(pid=10)
    assert not bugreport.flag_path().exists()
    assert bugreport.begin_run(pid=11, is_running=lambda p: False, boot_time=0) is None


def test_a_run_that_did_not_quit_is_offered_once():
    bugreport.begin_run(pid=10, is_running=lambda p: False, boot_time=0)
    crashed = bugreport.begin_run(pid=11, is_running=lambda p: False, boot_time=0)
    assert crashed is not None
    assert bugreport.flag_path().read_text() == "11"
    bugreport.end_run(pid=11)
    assert bugreport.begin_run(pid=12, is_running=lambda p: False, boot_time=0) is None


def test_a_second_copy_is_not_a_crash_and_does_not_hide_one():
    bugreport.begin_run(pid=10, is_running=lambda p: False, boot_time=0)
    assert bugreport.begin_run(pid=11, is_running=lambda p: p == 10, boot_time=0) is None
    # The second copy quitting leaves the first one's flag.
    bugreport.end_run(pid=11)
    assert bugreport.flag_path().read_text() == "10"


def test_a_restart_since_is_not_a_crash():
    bugreport.begin_run(pid=10, is_running=lambda p: False, boot_time=0)
    assert bugreport.begin_run(pid=11, is_running=lambda p: False,
                               boot_time=time.time() + 60) is None


def test_is_running_knows_this_process():
    assert bugreport._is_running(os.getpid())


# ── The log and unhandled exceptions ────────────────────────────────────


@pytest.fixture
def fresh_log(monkeypatch, tmp_path):
    monkeypatch.setattr(bugreport, "log_folder", lambda: tmp_path)
    monkeypatch.setattr(bugreport, "last_error", None)
    yield tmp_path
    for h in list(bugreport.log.handlers):
        bugreport.log.removeHandler(h)
        h.close()


def test_log_attachment_is_the_last_lines_redacted(fresh_log):
    home = os.path.expanduser("~")
    lines = [f"line {i}" for i in range(100)] + [f"error in {home}{os.sep}x.py", "z" * 2000]
    (fresh_log / bugreport.LOG_NAME).write_text("\n".join(lines), encoding="utf-8")
    [a] = bugreport.log_attachment()
    out = a.text.splitlines()
    assert len(out) == bugreport.LOG_LINES_SENT
    assert out[-2] == f"error in ~{os.sep}x.py"
    assert out[-1].endswith(" …") and len(out[-1]) == bugreport.LONGEST_LOG_LINE + 2
    assert a.name == "the log"
    assert bugreport.log_attachment(fresh_log / "none") == []


def test_unhandled_exceptions_are_logged_and_kept(fresh_log, monkeypatch):
    monkeypatch.setattr(sys, "excepthook", lambda *a: None)
    monkeypatch.setattr(threading, "excepthook", lambda args: None)
    bugreport.configure_log()
    bugreport.install_handlers()
    try:
        raise ValueError("boom")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    assert "ValueError: boom" in bugreport.last_error
    [a] = bugreport.error_attachment()
    assert a.heading == "Last error"

    t = threading.Thread(target=lambda: 1 / 0, name="worker")
    t.start()
    t.join()
    assert "ZeroDivisionError" in bugreport.last_error
    for h in bugreport.log.handlers:
        h.flush()
    text = (fresh_log / bugreport.LOG_NAME).read_text(encoding="utf-8")
    assert "Unhandled exception:\nTraceback" in text
    assert "Unhandled exception in worker" in text


def test_exit_and_interrupt_are_not_errors(fresh_log):
    bugreport.record_exception(SystemExit, SystemExit(0), None)
    bugreport.record_exception(KeyboardInterrupt, KeyboardInterrupt(), None)
    assert bugreport.last_error is None
    assert bugreport.error_attachment() == []


# ── The form ─────────────────────────────────────────────────────────────

if os.environ.get("CI"):
    import wx
else:
    wx = pytest.importorskip("wx")

import announce  # noqa: E402
import ghviewer  # noqa: E402


@pytest.fixture(scope="module")
def frame():
    app = wx.App(False)
    f = wx.Frame(None)
    yield f
    f.Destroy()
    app.Destroy()


@pytest.fixture
def form(frame, monkeypatch):
    """A real form, not shown, whose sends finish at once."""
    monkeypatch.setattr(ghviewer.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda ms, fn, *a, **k: fn(*a, **k))

    class Thread:
        def __init__(self, target, daemon=True):
            self.target = target

        def start(self):
            self.target()
    monkeypatch.setattr(ghviewer.threading, "Thread", Thread)
    said: list[tuple[str, str]] = []
    observer = lambda text, cat: said.append((text, cat))  # noqa: E731
    announce.announcer.observers.append(observer)
    copied: list[str] = []
    monkeypatch.setattr(ghviewer.BugReportDialog, "_copy", staticmethod(lambda t: copied.append(t) or True))
    opened: list[str] = []
    monkeypatch.setattr(ghviewer.webbrowser, "open", lambda u: opened.append(u) or True)
    sends: list = []

    def make(result=None, **kw):
        def send(report, url, key):
            sends.append((report, url, key))
            return result or Result()
        dlg = ghviewer.BugReportDialog(frame, "App: GHManage", relay=("https://r", "k"), send=send, **kw)
        dlg.ended = []
        dlg.EndModal = dlg.ended.append
        dlg.said, dlg.copied, dlg.opened, dlg.sends = said, copied, opened, sends
        return dlg

    yield make
    announce.announcer.observers.remove(observer)


def _fill(dlg, title="Crash", first="It closed"):
    dlg.title_ctrl.SetValue(title)
    dlg.field_ctrls[0].SetValue(first)


def test_form_controls_are_named_and_in_order(form):
    dlg = form()
    try:
        names = [w.GetName() for w in dlg.GetChildren()
                 if isinstance(w, (wx.TextCtrl, wx.Choice))]
        assert names == ["Kind", "Title (required)", "What happened (required)",
                         "What you expected", "Steps to reproduce",
                         "Contact, optional and public: an email address or GitHub name",
                         "Preview: exactly what will be sent, publicly"]
        assert dlg.preview_ctrl.GetValue() == dlg.report().preview
        assert not dlg.preview_ctrl.IsEditable()
        assert dlg.attach_check is None
    finally:
        dlg.Destroy()


def test_preview_follows_typing_and_checkboxes(form):
    dlg = form(attachments=[Attachment("the log", "Log", "last line")])
    try:
        _fill(dlg)
        assert "**What happened**\nIt closed" in dlg.preview_ctrl.GetValue()
        assert "last line" in dlg.preview_ctrl.GetValue()
        assert dlg.attach_check.GetLabel() == "&Include the log"
        dlg.attach_check.SetValue(False)
        dlg.attach_check.ProcessEvent(wx.CommandEvent(wx.wxEVT_CHECKBOX, dlg.attach_check.GetId()))
        assert "last line" not in dlg.preview_ctrl.GetValue()
        dlg.system_check.SetValue(False)
        dlg.system_check.ProcessEvent(wx.CommandEvent(wx.wxEVT_CHECKBOX, dlg.system_check.GetId()))
        assert "App: GHManage" not in dlg.preview_ctrl.GetValue()
    finally:
        dlg.Destroy()


def test_suggestion_relabels_and_hides_steps(form):
    dlg = form()
    try:
        dlg.field_ctrls[2].SetValue("steps typed as a bug")
        dlg.kind_ctrl.SetSelection(1)
        dlg._on_kind()
        assert dlg.field_ctrls[0].GetName() == "Your suggestion (required)"
        assert dlg.field_labels[1].GetLabel() == "How it would &help"
        assert not dlg.field_ctrls[2].IsShown()
        assert "steps typed" not in dlg.preview_ctrl.GetValue()
        assert "Kind: Suggestion" in dlg.preview_ctrl.GetValue()
        dlg.kind_ctrl.SetSelection(0)
        dlg._on_kind()
        assert dlg.field_ctrls[2].IsShown()
    finally:
        dlg.Destroy()


def test_send_with_a_required_field_empty_says_so(form):
    dlg = form()
    try:
        dlg.on_send()
        assert dlg.message.GetLabel() == "Title is required."
        assert ("Title is required.", "result") in dlg.said
        dlg.title_ctrl.SetValue("Crash")
        dlg.on_send()
        assert dlg.message.GetLabel() == "What happened is required."
        assert dlg.sends == []
    finally:
        dlg.Destroy()


def test_filed_moves_to_open_issue_and_says_the_number(form):
    dlg = form(Result(42, "https://github.com/TheIdeaPlace/GHManage/issues/42"))
    try:
        _fill(dlg)
        dlg.on_send()
        report, url, key = dlg.sends[0]
        assert (url, key) == ("https://r", "k")
        assert report.preview == dlg.preview_ctrl.GetValue()
        assert dlg.sent and not dlg.sending
        assert dlg.open_issue_button.IsShown() and not dlg.send_button.IsShown()
        assert not dlg.page_button.IsShown()
        assert dlg.message.GetLabel() == (
            "Report sent as issue #42. https://github.com/TheIdeaPlace/GHManage/issues/42")
        assert ("Report sent as issue #42.", "result") in dlg.said
        assert dlg.cancel_button.GetLabel() == "Close"
        dlg.open_issue_button.ProcessEvent(
            wx.CommandEvent(wx.wxEVT_BUTTON, dlg.open_issue_button.GetId()))
        assert dlg.opened == ["https://github.com/TheIdeaPlace/GHManage/issues/42"]
        # Sending again does nothing, and closing doesn't ask.
        dlg.on_send()
        assert len(dlg.sends) == 1
        assert dlg.on_cancel() and dlg.ended == [wx.ID_CLOSE]
    finally:
        dlg.Destroy()


def test_not_filed_copies_and_offers_the_page(form):
    dlg = form(Result())
    try:
        _fill(dlg)
        dlg.on_send()
        assert dlg.message.GetLabel() == "Couldn't send. The report is on the clipboard."
        assert dlg.copied == [dlg.report().clipboard_text]
        assert dlg.page_button.IsShown() and dlg.send_button.IsShown()
        assert dlg.opened == []  # the browser waits to be asked
        dlg.page_button.ProcessEvent(wx.CommandEvent(wx.wxEVT_BUTTON, dlg.page_button.GetId()))
        assert dlg.opened == [dlg.report().issue_page_url()]
        assert len(dlg.copied) == 2
    finally:
        dlg.Destroy()


def test_no_key_says_this_copy_cannot_send(form):
    dlg = form(Result(no_key=True))
    try:
        _fill(dlg)
        dlg.on_send()
        assert dlg.message.GetLabel() == (
            "This copy of GHManage can't send reports itself. The report is on the clipboard.")
    finally:
        dlg.Destroy()


def test_while_sending_close_waits_and_send_is_ignored(form):
    dlg = form()
    try:
        _fill(dlg)
        dlg.sending = True
        dlg.on_send()
        assert dlg.sends == []
        assert not dlg.on_cancel() and dlg.ended == []
        assert ("Still sending.", "result") in dlg.said
    finally:
        dlg.Destroy()


def test_cancel_asks_only_when_something_was_typed(form, monkeypatch):
    dlg = form()
    try:
        assert dlg.on_cancel() and dlg.ended == [wx.ID_CANCEL]
    finally:
        dlg.Destroy()

    answers = []

    class Ask:
        def __init__(self, *a, **k):
            pass

        def SetYesNoLabels(self, *a):
            pass

        def ShowModal(self):
            return answers.pop(0)

        def Destroy(self):
            pass

    monkeypatch.setattr(ghviewer.wx, "MessageDialog", Ask)
    dlg = form()
    try:
        dlg.contact_ctrl.SetValue("me")
        answers[:] = [wx.ID_NO, wx.ID_YES]
        assert not dlg.on_cancel() and dlg.ended == []
        assert dlg.on_cancel() and dlg.ended == [wx.ID_CANCEL]
    finally:
        dlg.Destroy()


def test_a_crash_report_starts_with_its_title_and_is_not_typed(form):
    dlg = form(title="Quit unexpectedly", attachments=[Attachment("the log", "Log", "x")])
    try:
        assert dlg.title_ctrl.GetValue() == "Quit unexpectedly"
        assert not dlg.typed()
        assert dlg.attach_check.GetValue()
    finally:
        dlg.Destroy()


def test_help_menu_has_report_a_bug_and_the_log_folder():
    import inspect
    src = inspect.getsource(ghviewer.GhViewerFrame)
    assert 'help_menu.Append(ID_REPORT_BUG, "Report a Bug…")' in src
    assert 'help_menu.Append(ID_OPEN_LOG_FOLDER, "Open Log Folder")' in src


# ── After review ─────────────────────────────────────────────────────────


def test_long_answers_are_held_so_the_body_and_attachments_fit():
    r = _report(answers=["a" * 9000, "b" * 9000, "c" * 9000], title="t" * 500,
                contact="x" * 500, system_text="App: x\n" * 6,
                attachments=[Attachment("the log", "Log", "last line")])
    assert len(r.body) <= bugreport.LONGEST_BODY
    assert "last line" in r.body  # the attachment still fits
    assert len(r.full_title) <= 200
    assert len(r.contact_text) == bugreport.LONGEST_CONTACT
    assert len(r.issue_page_url()) <= bugreport.LONGEST_PAGE_ADDRESS


def test_a_send_that_raises_still_frees_the_form(form, frame):
    def boom(report, url, key):
        raise RuntimeError("no")
    dlg = ghviewer.BugReportDialog(frame, "App", relay=("https://r", "k"), send=boom)
    try:
        dlg.title_ctrl.SetValue("t")
        dlg.field_ctrls[0].SetValue("x")
        dlg.on_send()
        assert not dlg.sending
        assert dlg.page_button.IsShown()
    finally:
        dlg.Destroy()


def test_a_retry_that_files_hides_the_page_button(form):
    dlg = form(Result())
    try:
        _fill(dlg)
        dlg.on_send()
        assert dlg.page_button.IsShown()
        dlg._send = lambda r, u, k: Result(9, "https://github.com/x/y/issues/9")
        dlg.on_send()
        assert dlg.open_issue_button.IsShown()
        assert not dlg.page_button.IsShown() and not dlg.send_button.IsShown()
    finally:
        dlg.Destroy()


def test_form_boxes_are_held_to_the_limits(form):
    dlg = form()
    try:
        dlg.title_ctrl.SetValue("t" * 500)
        dlg.title_ctrl.AppendText("more")  # typing past the limit is refused
        assert len(dlg.report().full_title) <= 200
    finally:
        dlg.Destroy()


@pytest.mark.parametrize("content", [b"99999999999999999999999", b"\xff\xfe\x00junk", b"-3"])
def test_a_damaged_flag_never_stops_the_start(content):
    path = bugreport.flag_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    bugreport.begin_run(pid=10, boot_time=0)  # no exception
    assert path.read_text() == "10"


def test_crash_attachment_reads_what_faulthandler_left(fresh_log):
    home = os.path.expanduser("~")
    (fresh_log / bugreport.CRASH_NAME).write_text(
        f"Fatal Python error: Segmentation fault\n  File \"{home}{os.sep}x.py\", line 1",
        encoding="utf-8")
    [a] = bugreport.crash_attachment()
    assert a.name == "the crash" and "Segmentation fault" in a.text
    assert home not in a.text
    (fresh_log / bugreport.CRASH_NAME).write_text("", encoding="utf-8")
    assert bugreport.crash_attachment() == []


def test_configure_log_empties_the_crash_file_for_this_run(fresh_log):
    import faulthandler
    (fresh_log / bugreport.CRASH_NAME).write_text("old crash", encoding="utf-8")
    try:
        bugreport.configure_log()
        assert faulthandler.is_enabled()
        assert (fresh_log / bugreport.CRASH_NAME).read_text(encoding="utf-8") == ""
    finally:
        faulthandler.disable()
        if bugreport._crash_file:
            bugreport._crash_file.close()
            bugreport._crash_file = None


def test_thread_exceptions_still_reach_the_previous_hook(fresh_log, monkeypatch):
    seen = []
    monkeypatch.setattr(sys, "excepthook", lambda *a: None)
    monkeypatch.setattr(threading, "excepthook", lambda args: seen.append(args.exc_type))
    bugreport.install_handlers()
    t = threading.Thread(target=lambda: 1 / 0)
    t.start()
    t.join()
    assert seen == [ZeroDivisionError]


def test_report_bug_gathers_off_the_ui_thread_and_opens_once(monkeypatch):
    from types import SimpleNamespace
    calls, shown = [], []
    monkeypatch.setattr(bugreport, "collect_system_text", lambda exe: "SYS")
    started = []

    class Thread:
        def __init__(self, target, daemon=True):
            self.target = target

        def start(self):
            started.append(self.target)
    monkeypatch.setattr(ghviewer.threading, "Thread", Thread)
    monkeypatch.setattr(ghviewer.wx, "CallAfter", lambda fn, *a: calls.append((fn, a)))
    f = SimpleNamespace(_announce=lambda m: None)
    f._show_bug_report = lambda *a: shown.append(a)
    ghviewer.GhViewerFrame.on_report_bug(f)
    ghviewer.GhViewerFrame.on_report_bug(f)  # a second press while gathering
    assert len(started) == 1
    started[0]()
    fn, args = calls[0]
    assert args == ("SYS", [], "")
