"""Security Alerts (#85): a repository's Dependabot, code scanning and secret
scanning alerts in one list, most severe first, each kind failing on its own."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import alertview
import gh_data
from gh_data import (
    ALERT_CODE, ALERT_DEPENDABOT, ALERT_SECRET, GhError, SecurityAlert, SecurityAlerts,
)

# Shapes as GitHub returns them (trimmed). The code scanning one is a real
# alert's, from TheIdeaPlace/AIChat.

DEPENDABOT = {
    "number": 4,
    "state": "open",
    "dependency": {
        "package": {"ecosystem": "pip", "name": "requests"},
        "manifest_path": "requirements.txt",
        "scope": "runtime",
        "relationship": "direct",
    },
    "security_advisory": {
        "ghsa_id": "GHSA-j8r2-6x86-q33q",
        "cve_id": "CVE-2023-32681",
        "summary": "Unintended leak of Proxy-Authorization header in requests",
        "description": "Requests is a HTTP library.\n\nSince 2.3.0 it has leaked headers.",
        "severity": "medium",
        "cvss": {"score": 6.1, "vector_string": "CVSS:3.1/AV:N"},
    },
    "security_vulnerability": {
        "package": {"ecosystem": "pip", "name": "requests"},
        "severity": "medium",
        "vulnerable_version_range": ">= 2.3.0, < 2.31.0",
        "first_patched_version": {"identifier": "2.31.0"},
    },
    "url": "https://api.github.com/repos/o/r/dependabot/alerts/4",
    "html_url": "https://github.com/o/r/security/dependabot/4",
    "created_at": "2026-05-01T10:00:00Z",
    "updated_at": "2026-05-02T10:00:00Z",
    "dismissed_at": None, "dismissed_by": None, "dismissed_reason": None,
    "dismissed_comment": None, "fixed_at": None, "auto_dismissed_at": None,
}

CODE = {
    "number": 1,
    "created_at": "2026-10-15T23:34:24Z",
    "updated_at": "2026-10-15T23:36:58Z",
    "html_url": "https://github.com/o/r/security/code-scanning/1",
    "state": "dismissed",
    "fixed_at": None,
    "dismissed_by": {"login": "kellylford"},
    "dismissed_at": "2026-10-15T23:36:58Z",
    "dismissed_reason": "used in tests",
    "dismissed_comment": "In a test file, not app code.",
    "rule": {
        "id": "py/incomplete-url-substring-sanitization",
        "severity": "warning",
        "description": "Incomplete URL substring sanitization",
        "name": "py/incomplete-url-substring-sanitization",
        "tags": ["correctness", "external/cwe/cwe-020", "security"],
        "full_description": "Security checks on the substrings of an unparsed URL are "
                            "often vulnerable to bypassing.",
        "help": "# Long help\n" * 50,
        "security_severity_level": "high",
    },
    "tool": {"name": "CodeQL", "guid": None, "version": "2.27.3"},
    "most_recent_instance": {
        "ref": "refs/heads/main",
        "state": "dismissed",
        "message": {"text": "The string cli.github.com may be at an arbitrary position."},
        "location": {"path": "tests/test_ui_hidden.py", "start_line": 8178,
                     "end_line": 8178},
        "classifications": ["test"],
    },
}

SECRET = {
    "number": 2,
    "created_at": "2026-03-01T08:00:00Z",
    "updated_at": "2026-03-02T08:00:00Z",
    "html_url": "https://github.com/o/r/security/secret-scanning/2",
    "state": "resolved",
    "secret_type": "github_personal_access_token",
    "secret_type_display_name": "GitHub Personal Access Token",
    "validity": "inactive",
    "resolution": "revoked",
    "resolved_by": {"login": "kellylford"},
    "resolved_at": "2026-03-02T08:00:00Z",
    "resolution_comment": "Rotated.",
    "push_protection_bypassed": True,
    "push_protection_bypassed_by": {"login": "someone"},
    "push_protection_bypassed_at": "2026-03-01T07:59:00Z",
    "first_location_detected": {"path": "config/settings.py", "start_line": 12},
    "has_more_locations": True,
}

DEP_403 = GhError('{"message":"Dependabot alerts are disabled for this repository.",'
                  '"status":"403"}gh: Dependabot alerts are disabled for this repository. '
                  '(HTTP 403)\ngh: This API operation needs the "admin:repo_hook" scope. '
                  'To request it, run:  gh auth refresh -h github.com -s admin:repo_hook')
CODE_404 = GhError("gh: no analysis found (HTTP 404)\n"
                   'gh: This API operation needs the "admin:repo_hook" scope.')
SECRET_404 = GhError("gh: Secret scanning is disabled on this repository. (HTTP 404)")
HINT = ('gh: This API operation needs the "admin:repo_hook" scope. To request it, run:  '
        "gh auth refresh -h github.com -s admin:repo_hook")
NOT_ACCESSIBLE = GhError("gh: Resource not accessible by personal access token (HTTP 403)\n"
                         + HINT)
# What a repository you don't administer answers (cli/cli, as gh prints it).
DEP_NOT_AUTHORIZED = GhError("gh: You are not authorized to perform this operation. "
                             "(HTTP 403)\n" + HINT)
CODE_NOT_AUTHORIZED = GhError("gh: You are not authorized to read code scanning alerts. "
                              "(HTTP 403)\n" + HINT)
SECRET_NOT_FOUND = GhError("gh: Not Found (HTTP 404)")


def _headers(body, next_url=""):
    """A ``gh api -i`` reply: the headers, a blank line, the body."""
    import json
    link = f'Link: <{next_url}>; rel="next"\r\n' if next_url else ""
    return f"HTTP/2.0 200 OK\r\nContent-Type: application/json\r\n{link}\r\n{json.dumps(body)}"


def _all_routes(fake_gh, dependabot=(), code=(), secret=()):
    fake_gh.route("dependabot/alerts", dependabot if isinstance(dependabot, BaseException)
                  else _headers(list(dependabot)))
    fake_gh.route("code-scanning/alerts", code if isinstance(code, BaseException)
                  else list(code))
    fake_gh.route("secret-scanning/alerts", secret if isinstance(secret, BaseException)
                  else list(secret))


# ── Reading the alerts ─────────────────────────────────────────────────


def test_a_dependabot_alert_is_read_into_columns_and_details():
    a = gh_data._dependabot_alert(DEPENDABOT)
    assert a.to_row(gh_data.SECURITY_DEFAULT_COLUMNS) == {
        "kind": "Dependabot", "severity": "medium", "package": "requests (pip)",
        "summary": "Unintended leak of Proxy-Authorization header in requests",
        "where": "requirements.txt", "state": "open", "created": "2026-05-01"}
    assert (a.ident, a.ident_noun) == ("CVE-2023-32681", "CVE")
    assert a.info["patched"] == "2.31.0" and a.info["cvss"] == 6.1


def test_a_dependabot_alert_without_a_cve_is_known_by_its_ghsa_and_newer_cvss():
    raw = dict(DEPENDABOT, security_advisory=dict(
        DEPENDABOT["security_advisory"], cve_id=None, cvss={"score": 0},
        cvss_severities={"cvss_v3": {"score": 7.5}, "cvss_v4": {"score": 0}}))
    a = gh_data._dependabot_alert(raw)
    assert (a.ident, a.ident_noun) == ("GHSA-j8r2-6x86-q33q", "GHSA ID")
    assert a.info["cvss"] == 7.5


def test_a_code_scanning_alert_takes_the_security_severity():
    a = gh_data._code_alert(CODE)
    assert a.severity == "high" and a.info["tool_severity"] == "warning"
    assert a.package == "py/incomplete-url-substring-sanitization"
    assert a.where == "tests/test_ui_hidden.py:8178"
    assert a.summary == "Incomplete URL substring sanitization"
    assert a.state_display == "dismissed" and a.info["dismissed_by"] == "kellylford"


def test_a_code_scanning_alert_that_is_not_about_security_keeps_the_tool_severity():
    rule = dict(CODE["rule"], security_severity_level=None)
    assert gh_data._code_alert(dict(CODE, rule=rule)).severity == "warning"


def test_a_secret_scanning_alert_has_no_severity_and_no_secret():
    a = gh_data._secret_alert(dict(SECRET, secret="ghp_shouldneverbeshown"))
    assert a.severity == "" and a.ident == "github_personal_access_token"
    assert a.summary == "GitHub Personal Access Token"
    assert a.where == "config/settings.py:12"
    assert "ghp_" not in alertview.alert_details(a)


def test_auto_dismissed_reads_with_a_hyphen():
    assert gh_data._dependabot_alert(dict(DEPENDABOT, state="auto_dismissed")
                                     ).state_display == "auto-dismissed"


def test_most_severe_first_then_newest():
    def alert(sev, day):
        return SecurityAlert(ALERT_CODE, 1, "open", severity=sev,
                             created_at=f"2026-01-{day:02d}T00:00:00Z")
    alerts = [alert("", 9), alert("low", 1), alert("note", 2), alert("critical", 1),
              alert("high", 3), alert("high", 7), alert("moderate", 4), alert("warning", 5),
              alert("error", 1)]
    got = [(a.severity, a.created_at[8:10]) for a in gh_data.sort_alerts(alerts)]
    assert got == [("critical", "01"), ("high", "07"), ("high", "03"), ("moderate", "04"),
                   ("low", "01"), ("error", "01"), ("warning", "05"), ("note", "02"),
                   ("", "09")]


@pytest.mark.parametrize("state, dep, code, secret", [
    ("open", "state=open", "state=open", "state=open&hide_secret=true"),
    ("closed", "state=dismissed,fixed,auto_dismissed", "state=closed",
     "state=resolved&hide_secret=true"),
    # Secret scanning refuses state=all, so All asks for no state at all.
    ("all", None, None, "hide_secret=true"),
])
def test_view_state_maps_onto_each_kinds_states(fake_gh, state, dep, code, secret):
    _all_routes(fake_gh)
    gh_data.fetch_security_alerts("o/r", state, 50)
    calls = {c[-1].split("/")[3]: c[-1] for c in fake_gh.calls}
    assert calls["dependabot"] == (f"repos/o/r/dependabot/alerts?{dep}&per_page=50" if dep
                                   else "repos/o/r/dependabot/alerts?per_page=50")
    assert calls["code-scanning"].startswith(
        f"repos/o/r/code-scanning/alerts?{code}&per_page=50" if code
        else "repos/o/r/code-scanning/alerts?per_page=50")
    assert calls["secret-scanning"].startswith(
        f"repos/o/r/secret-scanning/alerts?{secret}&per_page=50")
    # Dependabot is read with its headers, for the cursor to the next page.
    assert fake_gh.called_with("dependabot")[0][:2] == ["api", "-i"]


def test_dependabot_follows_the_cursor_not_page_numbers(fake_gh):
    nxt = "https://api.github.com/repositories/9/dependabot/alerts?per_page=100&after=XYZ"
    pages = {
        "repos/o/r/dependabot/alerts?state=open&per_page=100":
            _headers([dict(DEPENDABOT, number=i) for i in range(100)], nxt),
        "repositories/9/dependabot/alerts?per_page=100&after=XYZ":
            _headers([dict(DEPENDABOT, number=100)]),
    }
    fake_gh.route("dependabot/alerts", lambda args: pages[args[-1]])
    fake_gh.route("code-scanning/alerts", [])
    fake_gh.route("secret-scanning/alerts", [])
    report = gh_data.fetch_security_alerts("o/r", "open", 150)
    assert len(report.alerts) == 101 and not report.full
    assert not any("&page=" in c[-1] or "?page=" in c[-1]
                   for c in fake_gh.called_with("dependabot"))


def test_a_full_kind_is_said_to_have_more(fake_gh):
    _all_routes(fake_gh, code=[dict(CODE, number=i) for i in range(5)])
    report = gh_data.fetch_security_alerts("o/r", "open", 5)
    assert report.full == [ALERT_CODE]


def test_each_kind_fails_on_its_own(fake_gh):
    _all_routes(fake_gh, dependabot=DEP_403, code=CODE_404, secret=[SECRET])
    report = gh_data.fetch_security_alerts("o/r", "all", 100)
    assert [a.kind for a in report.alerts] == [ALERT_SECRET]
    assert report.notes() == [
        "Dependabot alerts aren't turned on for this repository.",
        "Code scanning isn't set up on this repository.",
    ]
    # gh's admin:repo_hook hint on those is wrong, and isn't repeated.
    assert report.missing_scope == []


def test_code_scanning_not_enabled_and_secret_scanning_off(fake_gh):
    _all_routes(fake_gh, dependabot=[DEPENDABOT], secret=SECRET_404,
                code=GhError("gh: Code scanning is not enabled for this repository. "
                             "Please enable code scanning in the repository settings. "
                             "(HTTP 403)"))
    report = gh_data.fetch_security_alerts("o/r", "open", 100)
    assert len(report.alerts) == 1
    assert report.notes() == ["Code scanning isn't set up on this repository.",
                              "Secret scanning isn't turned on for this repository."]


def test_a_missing_permission_names_the_scope_and_the_command_once(fake_gh):
    _all_routes(fake_gh, dependabot=NOT_ACCESSIBLE, code=NOT_ACCESSIBLE, secret=[])
    report = gh_data.fetch_security_alerts("o/r", "open", 100)
    assert report.missing_scope == [ALERT_DEPENDABOT, ALERT_CODE]
    assert report.notes() == [
        "Dependabot and code scanning alerts need gh's security_events permission. "
        "Run gh auth refresh -h github.com -s security_events in a terminal, then press R."]


def test_a_reply_that_is_not_json_loses_only_its_own_kind(fake_gh):
    fake_gh.route("dependabot/alerts", _headers([DEPENDABOT]))
    fake_gh.route("code-scanning/alerts", "<html>oops</html>")
    fake_gh.route("secret-scanning/alerts", [SECRET])
    report = gh_data.fetch_security_alerts("o/r", "all", 100)
    assert len(report.alerts) == 2
    assert report.notes()[0].startswith("Couldn't read code scanning alerts: Unexpected reply")


def test_a_live_or_leaked_open_secret_goes_with_the_high_ones():
    live = gh_data._secret_alert(dict(SECRET, state="open", validity="active"))
    leaked = gh_data._secret_alert(dict(SECRET, state="open", validity="unknown",
                                        publicly_leaked=True))
    old = gh_data._secret_alert(dict(SECRET, state="open", validity="inactive"))
    gone = gh_data._secret_alert(dict(SECRET, validity="active"))  # resolved
    assert live.severity_rank == leaked.severity_rank == gh_data.SEVERITY_RANK["high"]
    assert old.severity_rank == gone.severity_rank == gh_data.UNKNOWN_SEVERITY_RANK


def test_three_kinds_needing_the_scope_read_as_a_list():
    assert gh_data.scope_sentence(list(gh_data.ALERT_KINDS)).startswith(
        "Dependabot, code scanning and secret scanning alerts need")


def test_a_repository_you_dont_administer_says_rights_not_permission(fake_gh):
    _all_routes(fake_gh, dependabot=DEP_NOT_AUTHORIZED, code=CODE_NOT_AUTHORIZED,
                secret=SECRET_NOT_FOUND)
    report = gh_data.fetch_security_alerts("o/r", "open", 100)
    assert report.missing_scope == []
    assert report.notes() == [
        "Dependabot alerts need admin or security manager rights on this repository.",
        "Code scanning alerts need admin or security manager rights on this repository.",
        "Secret scanning alerts can't be read here: either it isn't turned on, or it needs "
        "admin or security manager rights on this repository."]


def test_no_rights_and_other_failures_are_said_plainly():
    why, said = gh_data.classify_alert_error(
        ALERT_SECRET, GhError("gh: Must have admin rights to Repository. (HTTP 403)"))
    assert why == "rights"
    assert said == "Secret scanning alerts need admin or security manager rights on this repository."
    # Any other 403 is GitHub's own words, without gh's scope hint.
    why, said = gh_data.classify_alert_error(
        ALERT_DEPENDABOT, GhError("gh: API rate limit exceeded for user. (HTTP 403)\n" + HINT))
    assert (why, said) == ("error", "Couldn't read dependabot alerts: "
                                    "API rate limit exceeded for user. (HTTP 403)")
    why, said = gh_data.classify_alert_error(
        ALERT_CODE, GhError("gh: error connecting to api.github.com\ncheck your connection"))
    assert why == "error"
    assert said == "Couldn't read code scanning alerts: error connecting to api.github.com"


# ── The details panel ──────────────────────────────────────────────────


def test_dependabot_details_name_everything_useful():
    lines = alertview.alert_details(gh_data._dependabot_alert(DEPENDABOT)).split("\n")
    assert lines[0] == ("Dependabot alert #4: Unintended leak of Proxy-Authorization "
                        "header in requests")
    for want in ("Severity: medium", "State: open", "Package: requests (pip)",
                 "Manifest: requirements.txt", "Dependency: runtime direct",
                 "Affected versions: >= 2.3.0, < 2.31.0", "First patched version: 2.31.0",
                 "GHSA: GHSA-j8r2-6x86-q33q", "CVE: CVE-2023-32681", "CVSS score: 6.1",
                 "Created: 2026-05-01", "Updated: 2026-05-02",
                 "Requests is a HTTP library."):
        assert want in lines
    # Addresses stand alone on the line after their label.
    assert lines[lines.index("URL:") + 1] == "https://github.com/o/r/security/dependabot/4"
    assert lines[lines.index("Advisory URL:") + 1] == (
        "https://github.com/advisories/GHSA-j8r2-6x86-q33q")


def test_an_unpatched_dependency_says_so():
    raw = dict(DEPENDABOT, security_vulnerability=dict(
        DEPENDABOT["security_vulnerability"], first_patched_version=None))
    assert "First patched version: none yet" in alertview.alert_details(
        gh_data._dependabot_alert(raw)).split("\n")


def test_code_scanning_details_give_the_place_and_why_it_was_dismissed():
    lines = alertview.alert_details(gh_data._code_alert(CODE)).split("\n")
    for want in ("Severity: high", "Tool severity: warning", "State: dismissed",
                 "Rule: py/incomplete-url-substring-sanitization", "Tool: CodeQL 2.27.3",
                 "Location: tests/test_ui_hidden.py, line 8178", "Branch: main",
                 "Classified as: test", "CWE: CWE-020",
                 "Dismissed: 2026-10-15 by kellylford", "Dismissed because: used in tests",
                 "Dismissal comment: In a test file, not app code.",
                 "Security checks on the substrings of an unparsed URL are often "
                 "vulnerable to bypassing."):
        assert want in lines
    assert "# Long help" not in "\n".join(lines)  # the rule's help page stays on GitHub


def test_secret_details_say_how_it_was_resolved():
    lines = alertview.alert_details(gh_data._secret_alert(SECRET)).split("\n")
    for want in ("Secret scanning alert #2: GitHub Personal Access Token",
                 "State: resolved", "Secret type: github_personal_access_token",
                 "Validity: inactive", "Found in: config/settings.py, line 12 (and elsewhere)",
                 "Push protection bypassed by someone on 2026-03-01",
                 "Resolved: 2026-03-02 by kellylford", "Resolved as: revoked",
                 "Resolution comment: Rotated."):
        assert want in lines
    assert not any(ln.startswith("Severity") for ln in lines)


def test_a_long_description_is_cut_at_a_line():
    text = "\n".join(f"line {i}" for i in range(100))
    cut = alertview.trim_text(text, max_lines=5)
    assert cut.split("\n") == ["line 0", "line 1", "line 2", "line 3", "line 4",
                               "(More on GitHub.)"]
    one_line = alertview.trim_text("x" * 50, max_chars=10)
    assert one_line.split("\n")[0] == "x" * 10
    assert alertview.trim_text("short\n\n\n\nend") == "short\n\nend"


def test_the_empty_list_says_why_kind_by_kind():
    report = SecurityAlerts(alerts=[], unavailable={
        ALERT_CODE: "Code scanning isn't set up on this repository."},
        missing_scope=[ALERT_SECRET])
    text = alertview.empty_text(report, "open")
    assert text.split("\n") == [
        "No open security alerts.", "",
        "Code scanning isn't set up on this repository.",
        "Secret scanning alerts need gh's security_events permission. Run gh auth refresh "
        "-h github.com -s security_events in a terminal, then press R."]
    assert alertview.empty_text(SecurityAlerts(alerts=[]), "all") == "No security alerts."


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


@needs_wx
def test_status_counts_each_kind_and_says_what_is_missing():
    report = SecurityAlerts(
        alerts=[gh_data._code_alert(CODE), gh_data._code_alert(CODE),
                gh_data._dependabot_alert(DEPENDABOT)],
        unavailable={ALERT_SECRET: "Secret scanning isn't turned on for this repository."},
        full=[ALERT_CODE])
    assert ghviewer.security_status("o/r", report, "open", 2) == (
        "o/r — 3 open security alerts: 1 Dependabot, 2 code scanning. "
        "Secret scanning isn't turned on for this repository. "
        "Showing up to 2 of each kind; Ctrl++ shows more.")
    one = SecurityAlerts(alerts=[gh_data._secret_alert(SECRET)])
    assert ghviewer.security_status("o/r", one, "all", 100) == (
        "o/r — 1 security alert: 1 secret scanning.")


@needs_wx
def test_copy_gives_the_advisory_rule_or_secret_type():
    dep = ghviewer.copy_values(gh_data._dependabot_alert(DEPENDABOT))
    assert (dep.ident, dep.spoken_noun) == ("CVE-2023-32681", "CVE")
    assert dep.link == "https://github.com/o/r/security/dependabot/4"
    assert dep.markdown == ("[CVE-2023-32681 Unintended leak of Proxy-Authorization header "
                            "in requests](https://github.com/o/r/security/dependabot/4)")
    code = ghviewer.copy_values(gh_data._code_alert(CODE))
    assert (code.ident, code.spoken_noun, code.title) == (
        "py/incomplete-url-substring-sanitization", "rule ID",
        "Incomplete URL substring sanitization")
    secret = ghviewer.copy_values(gh_data._secret_alert(SECRET))
    assert (secret.ident, secret.spoken_noun) == ("github_personal_access_token", "secret type")
    # The menu names all three.
    noun = Frame._COPY_IDENT_NOUNS[ghviewer.VIEW_SECURITY]
    assert all(w in noun for w in ("Advisory", "Rule", "Secret Type"))


@needs_wx
def test_the_view_is_wired_up():
    v = ghviewer.VIEW_SECURITY
    assert ghviewer.VIEW_COLUMNS[v] is ghviewer.SECURITY_SET
    assert Frame._VIEW_LABELS[v] == "Security Alerts"
    assert (v, "Security Alerts") in ghviewer.REPO_GO_TO
    assert v not in ghviewer.REPOLESS_VIEWS and v not in ghviewer.NO_MORE_VIEWS
    headings = [c.heading for c in ghviewer.SECURITY_SET.defs(
        list(ghviewer.SECURITY_SET.defaults))]
    assert headings == ["Kind", "Severity", "Package or rule", "Summary", "Where", "State",
                        "Created"]


class FakeText:
    def __init__(self) -> None:
        self.value = ""

    def SetValue(self, v): self.value = v
    def Clear(self): self.value = ""


def _frame(**attrs):
    said: list[str] = []
    frame = SimpleNamespace(
        details_text=FakeText(), items=[], git_items=[], repo="o/r", current_limit=100,
        view_mode=ghviewer.VIEW_SECURITY, said=said, status=[], focused=[],
        _fetch_is_current=lambda token: token == 1,
        _populate_filtered_list=lambda items, use_favorite_prefix=False: list(items),
        _update_title=lambda: None,
        _take_pending_row=lambda items, token: 0,
    )
    frame._set_view_status = lambda message, keys="": frame.status.append((message, keys))
    for k, v in attrs.items():
        setattr(frame, k, v)
    return frame


@needs_wx
def test_an_empty_list_says_why_in_the_details_and_aloud(monkeypatch):
    spoken = []
    monkeypatch.setattr(announce, "announce", lambda text, cat=None, force=False:
                        spoken.append((text, cat)))
    frame = _frame()
    report = SecurityAlerts(alerts=[], unavailable={
        ALERT_DEPENDABOT: "Dependabot alerts aren't turned on for this repository."})
    Frame._on_security_loaded(frame, 1, report, "open")
    assert frame.details_text.value.startswith("No open security alerts.\n\nDependabot")
    message, keys = frame.status[-1]
    assert message == ("o/r — 0 open security alerts. "
                       "Dependabot alerts aren't turned on for this repository.")
    assert keys == "R=refresh  Ctrl+F=filter"
    assert spoken == [(message, announce.STATUS)]


@needs_wx
def test_alerts_land_in_the_list_and_a_stale_load_is_dropped(monkeypatch):
    calls = []
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda ms, fn, *a: calls.append((fn, a)))
    frame = _frame(_focus_list=lambda row: None)
    alerts = [gh_data._code_alert(CODE)]
    Frame._on_security_loaded(frame, 2, SecurityAlerts(alerts=alerts), "open")
    assert frame.git_items == [] and frame.status == []  # token 2 isn't current
    Frame._on_security_loaded(frame, 1, SecurityAlerts(alerts=alerts), "open")
    assert frame.git_items == alerts and calls[0][1] == (0,)


@needs_wx
def test_selecting_an_alert_shows_its_details():
    alert = gh_data._secret_alert(SECRET)
    frame = _frame(git_items=[alert])
    Frame._show_security_details(frame, 0)
    assert frame.details_text.value == alertview.alert_details(alert)
    Frame._show_security_details(frame, 5)
    assert frame.details_text.value == ""


@needs_wx
def test_ctrl_o_opens_the_alert_on_github(monkeypatch):
    opened = []
    monkeypatch.setattr(ghviewer.webbrowser, "open", opened.append)
    announced, told = [], []
    alert = gh_data._code_alert(CODE)
    frame = SimpleNamespace(_announce=announced.append, _tell=told.append, repo="o/r",
                            _pane_index=lambda w: 1, _current_focus=lambda: None)
    frame._focused_item = lambda: alert
    frame._web_target = lambda it: Frame._web_target(frame, it)
    Frame.on_open_browser(frame, None)
    assert opened == ["https://github.com/o/r/security/code-scanning/1"]
    assert announced == ["Opened Code scanning alert 1 on GitHub"]
    alert = SecurityAlert(ALERT_CODE, 3, "open")
    Frame.on_open_browser(frame, None)
    assert told == ["Code scanning alert 3 has no page to open."]


@needs_wx
def test_an_alert_can_be_a_favorite():
    frame = SimpleNamespace(repo="o/r", view_mode=ghviewer.VIEW_SECURITY)
    fav = Frame._build_favorite_entry(frame, gh_data._dependabot_alert(DEPENDABOT))
    assert fav.item_type == "security alert" and fav.repo == "o/r"
    assert fav.title == ("Dependabot #4 — Unintended leak of Proxy-Authorization header "
                         "in requests")
    assert fav.subtitle == "medium — requests (pip)"


@needs_wx
def test_sort_order_is_refused_here():
    told = []
    frame = SimpleNamespace(view_mode=ghviewer.VIEW_SECURITY, _update_menu_checks=lambda: None,
                            _tell=told.append, sort_order="Number (newest first)")
    Frame.on_sort_selected(frame, None)
    assert frame.sort_order == "Number (newest first)"
    assert told == ["Security alerts are listed most severe first, then newest, "
                    "so they aren't sorted."]
