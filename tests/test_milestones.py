"""Milestones (#87): a repository's milestones with their progress, and
Enter on one for its issues and pull requests in Issues & PRs."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import gh_data
import milestoneview
from gh_data import GhError, Milestone

ROW = {
    "number": 91, "title": "2027.1", "state": "open", "description": "Next release.\n\nMore.",
    "due_on": "2026-12-01T08:00:00Z", "open_issues": 16, "closed_issues": 76,
    "created_at": "2025-11-08T06:42:46Z", "updated_at": "2026-10-28T01:39:23Z",
    "closed_at": None, "creator": {"login": "seanbudd"},
    "html_url": "https://github.com/o/r/milestone/91",
}


def test_milestones_are_read_with_the_state(fake_gh):
    fake_gh.route("milestones", [ROW, dict(ROW, number=2, title="Later", open_issues=0,
                                            closed_issues=0, due_on=None, creator=None)])
    ms = gh_data.fetch_milestones("o/r", "closed", 100)
    (call,) = fake_gh.called_with("milestones")
    assert "repos/o/r/milestones?state=closed&per_page=100&page=1" in " ".join(call)
    m, empty = ms
    assert (m.number, m.title, m.creator, m.url, m.repo) == (
        91, "2027.1", "seanbudd", "https://github.com/o/r/milestone/91", "o/r")
    assert (m.total, m.percent_done, m.done_display) == (92, 82, "82%")
    assert empty.percent_done is None and empty.done_display == "" and empty.creator == ""


def test_an_unknown_state_is_open(fake_gh):
    fake_gh.route("milestones", [])
    gh_data.fetch_milestones("o/r", "bogus")
    assert "state=open" in " ".join(fake_gh.called_with("milestones")[0])


def test_a_fork_shows_its_upstream_milestones(fake_gh):
    fake_gh.route("isFork,parent", {"isFork": True,
                                    "parent": {"owner": {"login": "up"}, "name": "r"}})
    fake_gh.route("milestones", [])
    gh_data.fetch_milestones("me/r")
    assert "repos/up/r/milestones" in " ".join(fake_gh.called_with("milestones")[0])


def test_rows():
    m = gh_data._parse_milestone(ROW, "o/r")
    assert m.to_row(["title", "due", "open", "closed", "done", "state", "description",
                     "updated"]) == {
        "title": "2027.1", "due": "2026-12-01", "open": "16", "closed": "76",
        "done": "82%", "state": "Open", "description": "Next release.",
        "updated": "2026-10-28"}


def test_issues_of_a_milestone_go_by_number(fake_gh):
    fake_gh.route("issue list", [])
    gh_data.fetch_issues("o/r", "open", 30, milestone=Milestone(2, "1"))
    args = fake_gh.called_with("issue list")[0]
    assert args[args.index("--milestone") + 1] == "2"


def test_prs_of_a_milestone_go_by_search(fake_gh):
    fake_gh.route("pr list", [])
    gh_data.fetch_prs("o/r", "all", 30, milestone=Milestone(2, 'Say "hi"'))
    args = fake_gh.called_with("pr list")[0]
    assert args[args.index("--search") + 1] == 'milestone:"Say hi"'
    assert "--milestone" not in args


def test_without_a_milestone_nothing_is_added(fake_gh):
    fake_gh.route("issue list", [])
    fake_gh.route("pr list", [])
    gh_data.fetch_issues("o/r")
    gh_data.fetch_prs("o/r")
    joined = " ".join(" ".join(c) for c in fake_gh.calls)
    assert "--milestone" not in joined and "--search" not in joined


def test_prs_too_large_to_size_in_time_come_without_their_sizes(monkeypatch):
    calls = []
    pr = {"number": 5, "title": "Big", "state": "MERGED", "url": "u", "mergedAt": "x"}

    def run(args, stdin=None):
        if "isFork,parent" in " ".join(args):
            return json.dumps({"isFork": False})
        calls.append(args)
        if gh_data.PR_FIELDS in args:
            raise GhError("HTTP 502: 502 Bad Gateway (https://api.github.com/graphql)")
        return json.dumps([pr])
    monkeypatch.setattr(gh_data, "_run_gh", run)
    (item,) = gh_data.fetch_prs("o/r", "all", 100)
    assert len(calls) == 2 and gh_data.PR_LIGHT_FIELDS in calls[1]
    assert "additions" not in gh_data.PR_LIGHT_FIELDS and "headRefName" in gh_data.PR_LIGHT_FIELDS
    assert not item.has_stats
    assert item.to_row(["+/-", "files"]) == {"+/-": "", "files": ""}


def test_other_pr_failures_are_not_retried(monkeypatch):
    calls = []

    def run(args, stdin=None):
        if "isFork,parent" in " ".join(args):
            return json.dumps({"isFork": False})
        calls.append(args)
        raise GhError("HTTP 404: Not Found")
    monkeypatch.setattr(gh_data, "_run_gh", run)
    with pytest.raises(GhError, match="404"):
        gh_data.fetch_prs("o/r")
    assert len(calls) == 1


def test_prs_with_sizes_show_them(fake_gh):
    fake_gh.route("pr list", [{"number": 5, "title": "T", "state": "OPEN", "url": "u",
                               "additions": 0, "deletions": 0, "changedFiles": 0}])
    (item,) = gh_data.fetch_prs("o/r")
    assert item.has_stats and item.to_row(["+/-", "files"]) == {"+/-": "+0/-0", "files": "0"}


# ── The details text ──────────────────────────────────────────────────

def test_details():
    text = milestoneview.milestone_details(gh_data._parse_milestone(ROW, "o/r"))
    lines = text.split("\n")
    assert lines[0] == "Milestone: 2027.1"
    assert "Due: 2026-12-01" in lines
    assert "Progress: 76 of 92 closed, 82% done" in lines
    assert "Created by: seanbudd" in lines
    i = lines.index("URL:")
    assert lines[i + 1] == "https://github.com/o/r/milestone/91"
    assert "Next release." in lines and "More." in lines
    assert not any(line.startswith("Closed on") for line in lines)


def test_details_of_an_empty_closed_milestone():
    m = Milestone(3, "Old", state="closed", closed_at="2026-01-01T00:00:00Z")
    text = milestoneview.milestone_details(m)
    assert "State: Closed" in text and "Due: no due date" in text
    assert "Progress: Nothing in it yet" in text and "Closed on: " in text
    assert "(no description)" in text


def test_status():
    ms = [Milestone(1, "a"), Milestone(2, "b")]
    assert milestoneview.status_message("o/r", ms, "open") == "o/r — 2 open milestones."
    assert milestoneview.status_message("o/r", ms[:1], "all") == "o/r — 1 milestone."


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
    def __init__(self) -> None:
        self.value = ""

    def SetValue(self, v): self.value = v
    def Clear(self): self.value = ""


def _frame(**attrs):
    frame = SimpleNamespace(
        details_text=FakeText(), items=[], git_items=[], repo="o/r", current_limit=100,
        view_mode=ghviewer.VIEW_MILESTONES, status=[], told=[], announced=[],
        page_size=100,
        _fetch_is_current=lambda token: token == 1,
        _populate_filtered_list=lambda items, use_favorite_prefix=False: list(items),
        _update_title=lambda: None,
        _take_pending_row=lambda items, token: 0,
    )
    frame._set_view_status = lambda message, keys="": frame.status.append((message, keys))
    frame._tell = frame.told.append
    frame._announce = frame.announced.append
    for k, v in attrs.items():
        setattr(frame, k, v)
    return frame


@needs_wx
def test_the_view_is_wired_up():
    v = ghviewer.VIEW_MILESTONES
    assert ghviewer.VIEW_COLUMNS[v] is ghviewer.MILESTONE_SET
    assert Frame._VIEW_LABELS[v] == "Milestones"
    assert (v, "Milestones") in ghviewer.REPO_GO_TO
    assert Frame._OPEN_LABELS[v] == "List Its Issues and PRs"
    headings = [c.heading for c in ghviewer.MILESTONE_SET.defs(
        list(ghviewer.MILESTONE_SET.defaults))]
    assert headings == ["Title", "Due", "Open", "Closed", "Done", "State"]
    t = ghviewer.parse_github_url("https://github.com/o/r/milestone/4")
    assert (t.kind, t.ref) == ("milestone", "4")
    assert ghviewer.parse_github_url("https://github.com/o/r/milestones").ref == "milestones"


@needs_wx
def test_milestones_land_in_the_list(monkeypatch):
    calls = []
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda ms, fn, *a: calls.append(a))
    frame = _frame(_focus_list=lambda row: None)
    ms = [gh_data._parse_milestone(ROW, "o/r")]
    Frame._on_milestones_loaded(frame, 2, ms, "open")
    assert frame.git_items == []
    Frame._on_milestones_loaded(frame, 1, ms, "open")
    assert frame.git_items == ms and calls == [(0,)]
    message, keys = frame.status[-1]
    assert message == "o/r — 1 open milestone." and keys.startswith("Enter=issues and PRs")


@needs_wx
def test_no_milestones_is_said(monkeypatch):
    spoken = []
    monkeypatch.setattr(announce, "announce", lambda text, cat=None, force=False:
                        spoken.append(text))
    frame = _frame()
    Frame._on_milestones_loaded(frame, 1, [], "closed")
    assert frame.details_text.value == "o/r has no closed milestones."
    assert spoken == ["o/r — 0 closed milestones."]
    assert frame.status[-1][1] == "R=refresh  Ctrl+F=filter"


@needs_wx
def test_selecting_one_shows_it():
    m = gh_data._parse_milestone(ROW, "o/r")
    frame = _frame(git_items=[m])
    Frame._show_milestone_details(frame, 0)
    assert frame.details_text.value == milestoneview.milestone_details(m)
    Frame._show_milestone_details(frame, 3)
    assert frame.details_text.value == ""


@needs_wx
def test_enter_lists_its_issues_and_backspace_comes_back_to_it():
    m = gh_data._parse_milestone(ROW, "o/r")
    log = []
    frame = _frame(label_filter="bug", milestone_filter=None, current_limit=500)

    def switch(view, load=True):
        log.append(("switch", view, load))
        frame.view_mode = view
        if view != ghviewer.VIEW_ISSUES:
            frame.milestone_filter = None
    frame._switch_view = switch
    frame._load_items = lambda: log.append(("load", frame.milestone_filter))
    frame._set_pending_target = lambda view, kind, ref: log.append(("pending", kind, ref))
    Frame._browse_milestone(frame, m)
    assert frame.view_mode == ghviewer.VIEW_ISSUES and frame.milestone_filter is m
    assert frame.label_filter == "" and frame.current_limit == 100
    assert log == [("switch", ghviewer.VIEW_ISSUES, False), ("load", m)]
    assert "2027.1" in frame.announced[-1] and "Backspace" in frame.announced[-1]
    log.clear()
    Frame._back_to_milestones(frame)
    assert frame.milestone_filter is None
    assert log == [("switch", ghviewer.VIEW_MILESTONES, True), ("pending", "milestone", "91")]
    assert frame.announced[-1] == "Back to milestones"


@needs_wx
def test_a_label_drops_the_milestone():
    frame = _frame(milestone_filter=Milestone(1, "a"), view_mode=ghviewer.VIEW_LABELS,
                   label_filter="")
    frame._switch_view = lambda view, load=True: setattr(frame, "view_mode", view)
    Frame._browse_label(frame, gh_data.Label("bug"))
    assert frame.milestone_filter is None and frame.label_filter == "bug"


@needs_wx
def test_landing_back_on_the_milestone(monkeypatch):
    later = []
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda ms, fn, *a: later.append(a))
    items = [Milestone(1, "a"), Milestone(91, "2027.1")]
    v = ghviewer.VIEW_MILESTONES
    frame = SimpleNamespace(_pending_target=(1, v, "milestone", "91"), view_mode=v,
                            _row_of=lambda it: items.index(it),
                            _describe_landing=Frame._describe_landing,
                            _announce=lambda m: None)
    assert Frame._take_pending_row(frame, items, 1) == 1
    assert later[-1] == ("Milestone 2027.1",)
    frame._pending_target = (1, v, "milestone", "5")
    assert Frame._take_pending_row(frame, items, 1) == 0
    assert later[-1] == ("Milestone 5 isn't among the 2 milestones listed.",)


@needs_wx
def test_sorting_is_refused_aloud():
    frame = _frame(_update_menu_checks=lambda: None)
    Frame.on_sort_selected(frame, SimpleNamespace(GetId=lambda: 0))
    assert frame.told == ["Milestones are listed in GitHub's order, nearest due date first, "
                          "so they aren't sorted."]


@needs_wx
def test_copy_and_favorite():
    m = gh_data._parse_milestone(ROW, "o/r")
    v = ghviewer.copy_values(m)
    assert (v.ident, v.ident_noun, v.link) == ("2027.1", "Milestone Title", m.url)
    fav = Frame._build_favorite_entry(SimpleNamespace(repo="o/r", view_mode="milestones"), m)
    assert (fav.item_type, fav.title, fav.subtitle) == (
        "milestone", "2027.1", "76 of 92 closed, 82% done")
