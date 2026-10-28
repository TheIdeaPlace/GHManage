"""Insights (#89): a repository's last 14 days of traffic, and its
contributors, as one list whose rows are the figures."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import gh_data
import insightview
from gh_data import GhError, InsightRow, Insights

VIEWS = {"count": 68, "uniques": 38, "views": [
    {"timestamp": "2026-10-14T00:00:00Z", "count": 1, "uniques": 1},
    {"timestamp": "2026-10-27T00:00:00Z", "count": 2, "uniques": 2}]}
CLONES = {"count": 1, "uniques": 1, "clones": [
    {"timestamp": "2026-10-20T00:00:00Z", "count": 1, "uniques": 1}]}
REFERRERS = [{"referrer": "github.com", "count": 9, "uniques": 9}]
PATHS = [{"path": "/o/r/issues", "title": "/issues", "count": 9, "uniques": 3}]
PEOPLE = [{"login": "kelly", "contributions": 312, "html_url": "https://github.com/kelly"},
          {"login": "bot", "contributions": 1}]


def _traffic(fake_gh):
    fake_gh.route("traffic/views", VIEWS)
    fake_gh.route("traffic/clones", CLONES)
    fake_gh.route("popular/referrers", REFERRERS)
    fake_gh.route("popular/paths", PATHS)


def _said(r: InsightRow) -> list[str]:
    return [r.section, r.name, r.count_display, r.uniques_display]


def test_every_figure_is_a_row_in_order(fake_gh):
    _traffic(fake_gh)
    fake_gh.route("contributors", PEOPLE)
    got = gh_data.fetch_insights("o/r", 100)
    assert [_said(r) for r in got.rows] == [
        ["Views", "Last 14 days", "68 views", "38 unique visitors"],
        ["Views", "2026-10-27", "2 views", "2 unique visitors"],      # newest day first
        ["Views", "2026-10-14", "1 view", "1 unique visitor"],
        ["Clones", "Last 14 days", "1 clone", "1 unique cloner"],
        ["Clones", "2026-10-20", "1 clone", "1 unique cloner"],
        ["Referrer", "github.com", "9 views", "9 unique visitors"],
        ["Page", "/issues", "9 views", "3 unique visitors"],
        ["Contributor", "kelly", "312 commits", ""],
        ["Contributor", "bot", "1 commit", ""],
    ]
    assert got.rows[0].detail == "2026-10-14 to 2026-10-27"
    assert got.rows[0].url == "https://github.com/o/r/graphs/traffic"
    assert got.rows[6].url == "https://github.com/o/r/issues"
    assert got.rows[8].url == "https://github.com/bot"
    assert (got.traffic_error, got.contributors_error, got.contributors_pending) == ("", "", False)
    assert any("contributors?per_page=100&page=1" in " ".join(c) for c in fake_gh.calls)


def test_without_push_access_contributors_are_still_shown(fake_gh):
    fake_gh.route("traffic", GhError("gh: Must have push access to repository (HTTP 403)"))
    fake_gh.route("contributors", PEOPLE)
    got = gh_data.fetch_insights("o/r")
    assert got.traffic_error == "Traffic needs push access to o/r, which you don't have."
    assert [r.section for r in got.rows] == ["Contributor", "Contributor"]


def test_another_traffic_failure_says_what_github_said(fake_gh):
    fake_gh.route("traffic", GhError("HTTP 502"))
    fake_gh.route("contributors", [])
    assert gh_data.fetch_insights("o/r").traffic_error == "Couldn't read the traffic: HTTP 502"


def test_a_repository_too_large_for_contributors(fake_gh):
    _traffic(fake_gh)
    fake_gh.route("contributors", GhError(
        "The history or contributor list is too large to list contributors (HTTP 403)"))
    got = gh_data.fetch_insights("o/r")
    assert got.contributors_error == ("GitHub won't list the contributors of a "
                                      "repository this large.")
    assert got.rows and not got.section("Contributor")


def test_contributors_still_being_counted_are_asked_again(fake_gh, monkeypatch):
    monkeypatch.setattr(gh_data, "CONTRIBUTOR_WAIT", 0)
    _traffic(fake_gh)
    replies = iter(["{}", "{}", PEOPLE])
    fake_gh.route("contributors", lambda args: next(replies))
    got = gh_data.fetch_insights("o/r")
    assert not got.contributors_pending and len(got.section("Contributor")) == 2


def test_contributors_still_counted_after_the_retries(fake_gh, monkeypatch):
    monkeypatch.setattr(gh_data, "CONTRIBUTOR_WAIT", 0)
    _traffic(fake_gh)
    fake_gh.route("contributors", "{}")
    got = gh_data.fetch_insights("o/r")
    assert got.contributors_pending
    assert len(fake_gh.called_with("contributors")) == gh_data.CONTRIBUTOR_RETRIES + 1
    assert "GitHub is still counting the contributors; press R in a moment." in \
        insightview.status_message("o/r", got)


def test_contributors_are_paged_to_the_limit(fake_gh):
    _traffic(fake_gh)
    page = [{"login": f"u{i}", "contributions": 1} for i in range(100)]
    fake_gh.route("&page=1", page).route("&page=2", page[:3])
    got = gh_data.fetch_insights("o/r", 150)
    assert len(got.section("Contributor")) == 103


def test_status_says_the_totals_and_what_is_missing():
    rows = [InsightRow("Views", "Last 14 days", 1234, 210),
            InsightRow("Clones", "Last 14 days", 5, 1),
            InsightRow("Contributor", "a", 3)]
    assert insightview.status_message("o/r", Insights(rows)) == (
        "o/r — 1,234 views (210 unique) and 5 clones (1 unique) in the last 14 days, "
        "1 contributor.")
    no_traffic = Insights(rows[2:], traffic_error="Traffic needs push access to o/r, "
                                                  "which you don't have.")
    assert insightview.status_message("o/r", no_traffic) == (
        "o/r — 1 contributor. Traffic needs push access to o/r, which you don't have.")
    assert insightview.status_message("o/r", Insights(contributors_error="Too large.")) == (
        "o/r — no insights to show. Too large.")
    assert insightview.status_message("o/r", Insights()) == "o/r — 0 contributors."


@pytest.mark.parametrize("row, first, second", [
    (InsightRow("Views", "Last 14 days", 68, 38, detail="2026-10-14 to 2026-10-27"),
     "Views, last 14 days (2026-10-14 to 2026-10-27)", "68 views, 38 unique visitors."),
    (InsightRow("Clones", "2026-10-20", 1, 1), "Clones on 2026-10-20", "1 clone, 1 unique cloner."),
    (InsightRow("Referrer", "github.com", 9, 9), "Referring site: github.com",
     "9 views, 9 unique visitors, in the last 14 days."),
    (InsightRow("Page", "/issues", 9, 3, detail="/o/r/issues"), "Popular page: /issues",
     "Path: /o/r/issues"),
    (InsightRow("Contributor", "kelly", 312), "Contributor: kelly",
     "312 commits on the default branch."),
])
def test_details_say_the_row_in_full(row, first, second):
    lines = insightview.insight_details(row).split("\n")
    assert lines[:2] == [first, second]
    assert lines[-1] == "Backspace goes back to the list; Ctrl+O opens it on GitHub."


def test_a_row_reads_whole():
    r = InsightRow("Views", "Last 14 days", 1234, 210)
    assert r.to_row(["section", "name", "count", "uniques"]) == {
        "section": "Views", "name": "Last 14 days", "count": "1,234 views",
        "uniques": "210 unique visitors"}


# ── In the window ──────────────────────────────────────────────────────

if os.environ.get("CI"):
    import wx
else:
    wx = pytest.importorskip("wx")

import announce  # noqa: E402
import ghviewer  # noqa: E402

Frame = ghviewer.GhViewerFrame


class FakeText:
    def __init__(self) -> None:
        self.value = ""

    def SetValue(self, v): self.value = v
    def Clear(self): self.value = ""


def _frame(**attrs):
    f = SimpleNamespace(
        _focus_list=lambda row: None,
        details_text=FakeText(), items=[], git_items=[], repo="o/r", current_limit=100,
        view_mode=ghviewer.VIEW_INSIGHTS, status=[], told=[], announced=[],
        _fetch_is_current=lambda token: token == 1,
        _populate_filtered_list=lambda items, use_favorite_prefix=False: list(items),
        _update_title=lambda: None,
    )
    f._set_view_status = lambda message, keys="": f.status.append((message, keys))
    f._tell = f.told.append
    f._announce = f.announced.append
    for k, v in attrs.items():
        setattr(f, k, v)
    return f


def test_the_view_is_wired_up():
    v = ghviewer.VIEW_INSIGHTS
    assert ghviewer.VIEW_COLUMNS[v] is ghviewer.INSIGHT_SET
    assert Frame._VIEW_LABELS[v] == "Insights"
    assert (v, "Insights") in ghviewer.REPO_GO_TO
    assert v in ghviewer.NO_MORE_VIEWS
    headings = [c.heading for c in ghviewer.INSIGHT_SET.defs(list(ghviewer.INSIGHT_SET.defaults))]
    assert headings == ["Section", "Name", "Count", "Unique"]


ROWS = [InsightRow("Views", "Last 14 days", 3, 2, url="u"), InsightRow("Contributor", "k", 1)]


def test_loaded_lands_on_the_first_row(monkeypatch):
    later, spoken, focused = [], [], []
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda ms, fn, *a: later.append(fn))
    monkeypatch.setattr(announce, "announce", lambda text, *a, **k: spoken.append(text))
    f = _frame(_focus_list=focused.append)
    Frame._on_insights_loaded(f, 2, Insights(ROWS))
    assert f.git_items == []  # a load the user moved on from
    Frame._on_insights_loaded(f, 1, Insights(ROWS))
    later[-1]()
    assert f.git_items == ROWS and focused == [0] and spoken == []
    message, keys = f.status[-1]
    assert keys.startswith("Enter=read  Ctrl+O=open on GitHub")


def test_what_is_missing_is_said_after_the_first_row(monkeypatch):
    events, later = [], []
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda ms, fn, *a: later.append(fn))
    monkeypatch.setattr(announce, "announce", lambda text, *a, **k: events.append(text))
    f = _frame(_focus_list=lambda row: events.append(("focus", row)))
    Frame._on_insights_loaded(f, 1, Insights(ROWS[1:], traffic_error="Traffic needs push."))
    assert events == []          # nothing before focus moves
    later[-1]()
    assert events == [("focus", 0), "Traffic needs push."]


def test_a_view_left_before_focus_moves_is_not_focused(monkeypatch):
    later, events = [], []
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda ms, fn, *a: later.append(fn))
    f = _frame(_focus_list=events.append)
    Frame._on_insights_loaded(f, 1, Insights(ROWS))
    f._fetch_is_current = lambda token: False
    later[-1]()
    assert events == []


def test_nothing_to_show_is_said(monkeypatch):
    spoken = []
    monkeypatch.setattr(announce, "announce", lambda text, *a, **k: spoken.append(text))
    f = _frame()
    Frame._on_insights_loaded(f, 1, Insights(traffic_error="Traffic needs push.",
                                              contributors_error="Too large."))
    assert spoken == ["o/r — no insights to show. Traffic needs push. Too large."]
    assert f.details_text.value == spoken[0]
    assert f.status[-1][1] == "R=refresh  Ctrl+F=filter"


def test_many_contributors_says_only_the_top_are_listed(monkeypatch):
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda *a: None)
    monkeypatch.setattr(ghviewer, "INSIGHT_CONTRIBUTORS", 2)
    f = _frame()
    Frame._on_insights_loaded(f, 1, Insights([InsightRow("Contributor", "a", 2),
                                              InsightRow("Contributor", "b", 1)]))
    assert f.status[-1][0] == "o/r — 2 contributors. These are the 2 with most commits."


def test_full_mode_does_not_name_cells_that_say_what_they_count():
    from columns import row_text
    cols = ghviewer.INSIGHT_SET.defs(list(ghviewer.INSIGHT_SET.defaults))
    values = InsightRow("Views", "Last 14 days", 1234, 210).to_row([c.id for c in cols])
    assert row_text(values, cols, True) == (
        "Views, Name: Last 14 days, 1,234 views, 210 unique visitors")


def test_selecting_a_row_shows_it():
    f = _frame(git_items=ROWS)
    Frame._show_insight_details(f, 0)
    assert f.details_text.value == insightview.insight_details(ROWS[0])
    Frame._show_insight_details(f, 5)
    assert f.details_text.value == ""


def test_copy_favorite_and_sort():
    v = ghviewer.copy_values(ROWS[0])
    assert (v.link, v.ident, v.ident_noun, v.text) == (
        "u", "Last 14 days", "Name", "Views, Last 14 days, 3 views, 2 unique visitors")
    f = _frame(_focused_item=lambda: ROWS[0], _update_menu_checks=lambda: None)
    Frame._toggle_favorite(f)
    assert f.told == ["Insights can't be favorites. F on the repository in the "
                      "repository list favorites it."]
    Frame.on_sort_selected(f, SimpleNamespace(GetId=lambda: 0))
    assert f.told[-1] == ("Insights are listed by section, most first within each, "
                          "so they aren't sorted.")
