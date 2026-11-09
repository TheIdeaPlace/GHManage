"""Set Milestone (#120): put an issue or pull request in a milestone, or take
it out, and see its milestone in the details and the Milestone column."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import gh_data
from gh_data import GhError, Item, Milestone

if os.environ.get("CI"):
    import wx  # noqa: F401
else:
    pytest.importorskip("wx")

import ghviewer  # noqa: E402

Frame = ghviewer.GhViewerFrame


# ── Data ────────────────────────────────────────────────────────────────


def test_issues_and_prs_are_read_with_their_milestone(fake_gh):
    fake_gh.route("issue list", [
        {"number": 1, "title": "A", "state": "OPEN", "url": "u",
         "milestone": {"number": 3, "title": "1.1"}},
        {"number": 2, "title": "B", "state": "OPEN", "url": "u", "milestone": None},
    ])
    fake_gh.route("pr list", [{"number": 5, "title": "P", "state": "OPEN", "url": "u",
                               "milestone": {"number": 4, "title": "2.0"}}])
    a, b = gh_data.fetch_issues("o/r")
    (p,) = gh_data.fetch_prs("o/r")
    assert (a.milestone, b.milestone, p.milestone) == ("1.1", "", "2.0")
    assert "milestone" in gh_data.ISSUE_FIELDS.split(",")
    assert gh_data.ISSUE_FIELDS in fake_gh.called_with("issue list")[0]
    assert "milestone" in gh_data.PR_LIGHT_FIELDS.split(",")


def test_search_results_carry_the_milestone():
    item = gh_data.parse_search_item({"number": 9, "title": "T", "milestone": {"title": "Q4"},
                                      "repository_url": "https://api.github.com/repos/o/r"})
    assert item.milestone == "Q4"
    assert gh_data.parse_search_item({"number": 9, "milestone": None}).milestone == ""


def test_milestone_is_a_column():
    assert "milestone" in gh_data.ALL_COLUMNS
    assert Item(1, "T", "OPEN", "u", False, milestone="1.1").to_row(["milestone"]) == {
        "milestone": "1.1"}
    from gh_columns import CATALOG
    assert CATALOG["milestone"].heading == "Milestone"


def test_setting_goes_by_number_through_the_issues_endpoint(fake_gh):
    fake_gh.route("PATCH", "")
    gh_data.set_item_milestone(Item(7, "T", "OPEN", "u", True), "o/r", Milestone(2, "1"))
    (call,) = fake_gh.called_with("PATCH")
    assert call[:4] == ["api", "-X", "PATCH", "repos/o/r/issues/7"]
    assert call[call.index("-F") + 1] == "milestone=2"


def test_clearing_sends_null(fake_gh):
    fake_gh.route("PATCH", "")
    gh_data.set_item_milestone(Item(7, "T", "OPEN", "u", False), "o/r", None)
    call = fake_gh.called_with("PATCH")[0]
    assert call[call.index("-F") + 1] == "milestone=null"


def test_the_repository_is_used_as_given(fake_gh):
    # The caller resolved it once, for the milestones too; no second lookup.
    fake_gh.route("PATCH", "")
    gh_data.set_item_milestone(Item(7, "T", "OPEN", "u", False, repo="x/y"), "up/r",
                               Milestone(1, "A"))
    assert "repos/up/r/issues/7" in fake_gh.called_with("PATCH")[0]
    assert not fake_gh.called_with("isFork")


def test_no_repository_is_an_error(fake_gh):
    with pytest.raises(GhError):
        gh_data.set_item_milestone(Item(7, "T", "OPEN", "u", False), "", None)
    assert fake_gh.calls == []


def test_resolved_milestones_are_not_looked_up_again(fake_gh):
    fake_gh.route("milestones", [])
    gh_data.fetch_milestones("up/r", "open", resolved=True)
    assert not fake_gh.called_with("isFork")
    assert "repos/up/r/milestones" in " ".join(fake_gh.called_with("milestones")[0])


# ── Choices ─────────────────────────────────────────────────────────────


MS = [Milestone(3, "1.1", due_on="2026-12-01T08:00:00Z"), Milestone(4, "Later")]


def test_choices_start_with_none_and_show_due_dates():
    labels, sel = Frame.milestone_choices("", MS)
    assert labels == ["No milestone", "1.1, due 2026-12-01", "Later"]
    assert sel == 0


def test_the_current_milestone_is_selected():
    assert Frame.milestone_choices("Later", MS)[1] == 2


def test_a_closed_current_milestone_is_listed_and_selected():
    labels, sel = Frame.milestone_choices("0.9", MS)
    assert labels[-1] == "0.9, closed" and sel == len(labels) - 1


# ── The flow ────────────────────────────────────────────────────────────


class FakeDialog:
    answer = None   # (wx.ID_OK or wx.ID_CANCEL, selection)
    shown: list = []

    def __init__(self, parent, message, caption, choices):
        FakeDialog.shown.append((message, caption, list(choices)))
        self.sel = 0

    def SetSelection(self, i): self.sel = i
    def ShowModal(self):
        code, sel = FakeDialog.answer
        if sel is not None:
            self.sel = sel
        return code
    def GetSelection(self): return self.sel
    def Destroy(self): pass


class NowThread:
    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args
    def start(self): self.target(*self.args)


@pytest.fixture
def flow(monkeypatch):
    monkeypatch.setattr(ghviewer.threading, "Thread", NowThread)
    monkeypatch.setattr(ghviewer.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    monkeypatch.setattr(ghviewer.wx, "SingleChoiceDialog", FakeDialog)
    FakeDialog.shown = []
    set_calls = []
    fetched = []
    # A fork: its issues and milestones are its upstream's.
    monkeypatch.setattr(ghviewer, "resolve_issue_repo",
                        lambda repo: "up/r" if repo == "me/fork" else repo)
    monkeypatch.setattr(ghviewer, "fetch_milestones",
                        lambda repo, state, resolved=False:
                        fetched.append((repo, resolved)) or list(MS))
    monkeypatch.setattr(ghviewer, "set_item_milestone",
                        lambda item, repo, m: set_calls.append((item.number, repo, m)))

    def make(item, view=ghviewer.VIEW_ISSUES, selected=0, repo="o/r"):
        f = SimpleNamespace(view_mode=view, repo=repo, said=[], announced=[],
                            redrawn=[], details=[], set_calls=set_calls, fetched=fetched,
                            _milestone_busy=False)
        f.details_text = object()
        f._current_focus = lambda: None
        f._announce = f.announced.append
        f._tell = lambda msg, *a, **k: f.said.append(msg)
        f._focused_item = lambda: item
        f._shown = [item]
        f._row_of = lambda it: 0 if it is item else -1
        f._redraw_row = lambda row, it: f.redrawn.append((row, it.milestone))
        f._show_details = f.details.append
        f.list_ctrl = SimpleNamespace(GetFirstSelected=lambda: selected)
        f.milestone_choices = Frame.milestone_choices
        f.NO_MILESTONE = Frame.NO_MILESTONE
        for name in ("_choose_milestone", "_on_milestone_set", "_milestone_done",
                     "_refresh_details_keeping_caret"):
            setattr(f, name, (lambda n: lambda *a: getattr(Frame, n)(f, *a))(name))
        return f
    return make


def test_putting_an_issue_in_a_milestone(flow):
    item = Item(5, "Bug", "OPEN", "u", False)
    f = flow(item)
    FakeDialog.answer = (ghviewer.wx.ID_OK, 1)
    Frame._set_milestone_flow(f)
    message, caption, choices = FakeDialog.shown[0]
    assert caption == "Set Milestone" and message == "Milestone for #5 Bug:"
    assert f.set_calls == [(5, "o/r", MS[0])]
    assert item.milestone == "1.1"
    assert f.redrawn == [(0, "1.1")] and f.details == [0]
    assert f.said == ["#5 is in milestone 1.1."]


def test_taking_a_pull_request_out_of_its_milestone(flow):
    item = Item(6, "PR", "OPEN", "u", True, milestone="Later")
    f = flow(item)
    FakeDialog.answer = (ghviewer.wx.ID_OK, 0)
    Frame._set_milestone_flow(f)
    assert f.set_calls == [(6, "o/r", None)]
    assert item.milestone == ""
    assert f.said == ["#6 has no milestone."]


def test_a_search_result_uses_its_own_repository(flow):
    item = Item(6, "PR", "OPEN", "u", True, repo="x/y")
    f = flow(item)
    FakeDialog.answer = (ghviewer.wx.ID_OK, 2)
    Frame._set_milestone_flow(f)
    assert f.set_calls == [(6, "x/y", MS[1])]


def test_cancel_changes_nothing(flow):
    item = Item(5, "Bug", "OPEN", "u", False, milestone="1.1")
    f = flow(item)
    FakeDialog.answer = (ghviewer.wx.ID_CANCEL, None)
    Frame._set_milestone_flow(f)
    assert f.set_calls == [] and item.milestone == "1.1"
    assert f.said == ["Milestone unchanged."]


def test_choosing_the_same_one_says_so_and_sends_nothing(flow):
    item = Item(5, "Bug", "OPEN", "u", False, milestone="Later")
    f = flow(item)
    FakeDialog.answer = (ghviewer.wx.ID_OK, None)  # OK on the preselected one
    Frame._set_milestone_flow(f)
    assert f.set_calls == []
    assert f.said == ["#5 is already in milestone Later."]


def test_keeping_a_closed_milestone_sends_nothing(flow):
    item = Item(5, "Bug", "OPEN", "u", False, milestone="0.9")
    f = flow(item)
    FakeDialog.answer = (ghviewer.wx.ID_OK, None)
    Frame._set_milestone_flow(f)
    assert f.set_calls == []
    assert FakeDialog.shown[0][2][-1] == "0.9, closed"


def test_no_open_milestones_says_so(flow, monkeypatch):
    monkeypatch.setattr(ghviewer, "fetch_milestones", lambda repo, state, resolved=False: [])
    f = flow(Item(5, "Bug", "OPEN", "u", False))
    Frame._set_milestone_flow(f)
    assert FakeDialog.shown == []
    assert f.said == ["o/r has no open milestones."]


def test_no_open_milestones_still_lets_you_clear_one(flow, monkeypatch):
    monkeypatch.setattr(ghviewer, "fetch_milestones", lambda repo, state, resolved=False: [])
    item = Item(5, "Bug", "OPEN", "u", False, milestone="0.9")
    f = flow(item)
    FakeDialog.answer = (ghviewer.wx.ID_OK, 0)
    Frame._set_milestone_flow(f)
    assert FakeDialog.shown[0][2] == ["No milestone", "0.9, closed"]
    assert f.set_calls == [(5, "o/r", None)]


def test_a_failed_fetch_is_said(flow, monkeypatch):
    def boom(repo, state, resolved=False):
        raise GhError("HTTP 404")
    monkeypatch.setattr(ghviewer, "fetch_milestones", boom)
    f = flow(Item(5, "Bug", "OPEN", "u", False))
    Frame._set_milestone_flow(f)
    assert f.said == ["Couldn't get the milestones of o/r: HTTP 404"]


def test_a_failed_set_is_said_and_nothing_changes(flow, monkeypatch):
    def boom(item, repo, m):
        raise GhError("HTTP 403: Must have push access")
    monkeypatch.setattr(ghviewer, "set_item_milestone", boom)
    item = Item(5, "Bug", "OPEN", "u", False)
    f = flow(item)
    FakeDialog.answer = (ghviewer.wx.ID_OK, 1)
    Frame._set_milestone_flow(f)
    assert item.milestone == "" and f.redrawn == []
    assert f.said == ["Couldn't set the milestone of #5: HTTP 403: Must have push access"]


def test_only_in_issues_and_prs(flow):
    f = flow(Item(5, "Bug", "OPEN", "u", False), view=ghviewer.VIEW_COMMITS)
    Frame._set_milestone_flow(f)
    assert f.said == ["Select an issue or pull request in Issues & PRs first."]
    f = flow(None)
    Frame._set_milestone_flow(f)
    assert f.said == ["Select an issue or pull request in Issues & PRs first."]


def test_details_name_the_milestone():
    item = Item(5, "Bug", "OPEN", "u", False, milestone="1.1")
    text = SimpleNamespace(value="")
    f = SimpleNamespace(items=[item], details_text=SimpleNamespace(
        SetValue=lambda v: setattr(text, "value", v), Clear=lambda: None))
    Frame._show_issue_details(f, 0)
    assert "Milestone: 1.1" in text.value.splitlines()


def test_a_fork_fetches_and_sets_in_the_same_repository(flow):
    item = Item(5, "Bug", "OPEN", "u", False)
    f = flow(item, repo="me/fork")
    FakeDialog.answer = (ghviewer.wx.ID_OK, 1)
    Frame._set_milestone_flow(f)
    assert f.fetched == [("up/r", True)]
    assert f.set_calls == [(5, "up/r", MS[0])]


def test_a_second_press_while_one_is_open_says_so(flow):
    f = flow(Item(5, "Bug", "OPEN", "u", False))
    f._milestone_busy = True
    Frame._set_milestone_flow(f)
    assert FakeDialog.shown == [] and f.fetched == []
    assert f.said == ["Still setting the last milestone."]


@pytest.mark.parametrize("answer", [(ghviewer.wx.ID_OK, 1), (ghviewer.wx.ID_CANCEL, None),
                                    (ghviewer.wx.ID_OK, None)])
def test_every_ending_lets_it_be_used_again(flow, answer):
    f = flow(Item(5, "Bug", "OPEN", "u", False))
    FakeDialog.answer = answer
    Frame._set_milestone_flow(f)
    assert f._milestone_busy is False


@pytest.mark.parametrize("where", ["fetch", "set"])
def test_a_failure_lets_it_be_used_again(flow, monkeypatch, where):
    def boom(*a, **k):
        raise GhError("HTTP 500")
    monkeypatch.setattr(ghviewer, "fetch_milestones" if where == "fetch" else
                        "set_item_milestone", boom)
    f = flow(Item(5, "Bug", "OPEN", "u", False))
    FakeDialog.answer = (ghviewer.wx.ID_OK, 1)
    Frame._set_milestone_flow(f)
    assert f._milestone_busy is False


# ── The details panel keeps its place ───────────────────────────────────


@pytest.mark.parametrize("old, new, caret, expected", [
    ("abc\nComments: 3\nbody", "abc\nMilestone: A\nComments: 3\nbody", 18, 31),  # after it
    ("abc\nComments: 3\nbody", "abc\nMilestone: A\nComments: 3\nbody", 2, 2),    # before it
    ("abc\nMilestone: A\nComments", "abc\nComments", 25, 12),                   # removed
    ("Milestone: 1.1\nx", "Milestone: 1.2\nx", 15, 15),                        # changed
    ("abc\nMilestone: Long\nx", "abc\nx", 10, 4),                    # inside what went
])
def test_moved_caret(old, new, caret, expected):
    assert ghviewer.moved_caret(old, new, caret) == expected


class FakeText:
    def __init__(self):
        self.value, self.caret = "", 0
    def GetValue(self): return self.value
    def SetValue(self, v): self.value = v
    def GetInsertionPoint(self): return self.caret
    def SetInsertionPoint(self, p): self.caret = p
    def Clear(self): self.value = ""


def test_set_from_the_details_panel_keeps_the_caret(flow):
    item = Item(5, "Bug", "OPEN", "u", False, body="Line one\nLine two")
    f = flow(item)
    f.items = [item]
    f.details_text = FakeText()
    Frame._show_issue_details(f, 0)
    f.details_text.caret = f.details_text.value.index("Line two")
    f._current_focus = lambda: f.details_text
    f._show_details = lambda row: Frame._show_issue_details(f, row)
    FakeDialog.answer = (ghviewer.wx.ID_OK, 1)
    Frame._set_milestone_flow(f)
    text = f.details_text.value
    assert "Milestone: 1.1" in text
    assert text[f.details_text.caret:].startswith("Line two")


def test_set_from_the_list_just_shows_it(flow):
    f = flow(Item(5, "Bug", "OPEN", "u", False))
    FakeDialog.answer = (ghviewer.wx.ID_OK, 1)
    Frame._set_milestone_flow(f)
    assert f.details == [0]


# ── The I key ───────────────────────────────────────────────────────────


from test_consistent_keys import Key, _hook_frame  # noqa: E402


@pytest.mark.parametrize("focus", ["list", "details"])
def test_i_sets_the_milestone_in_issues_and_prs(focus):
    f = _hook_frame(ghviewer.VIEW_ISSUES, focus=focus, item=Item(5, "Bug", "OPEN", "u", False))
    Frame.on_char_hook(f, Key(ord("I")))
    assert f.calls == ["_set_milestone_flow"]


def test_ctrl_i_is_not_set_milestone():
    f = _hook_frame(ghviewer.VIEW_ISSUES, item=Item(5, "Bug", "OPEN", "u", False))
    Frame.on_char_hook(f, Key(ord("I"), ghviewer.wx.MOD_CONTROL))
    assert "_set_milestone_flow" not in f.calls


def test_i_in_notifications_is_still_include_read():
    f = _hook_frame(ghviewer.VIEW_NOTIFICATIONS)
    f._toggle_include_read = lambda: f.calls.append("_toggle_include_read")
    f._mark_notification_read = f._unsubscribe_notification = lambda: None
    Frame.on_char_hook(f, Key(ord("I")))
    assert f.calls == ["_toggle_include_read"]
