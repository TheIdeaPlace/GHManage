"""GitHub-wide search, My Work, and saved searches."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

import gh_data
import saved_searches as ss


def _issue(n, repo="o/r", pr=False, merged=False, title="T"):
    raw = {
        "number": n, "title": title, "state": "open",
        "html_url": f"https://github.com/{repo}/{'pull' if pr else 'issues'}/{n}",
        "repository_url": f"https://api.github.com/repos/{repo}",
        "user": {"login": "alice"}, "labels": [{"name": "bug"}], "comments": 3,
        "created_at": "2026-10-01T00:00:00Z", "updated_at": f"2026-10-0{n % 9 + 1}T00:00:00Z",
        "body": "Body",
    }
    if pr:
        raw["pull_request"] = {"merged_at": "2026-10-02T00:00:00Z" if merged else None}
    return raw


def test_the_query_goes_to_github_exactly_as_typed(fake_gh):
    fake_gh.route("search/issues", {"total_count": 1, "items": [_issue(1)]})
    gh_data.search_issues('review-requested:@me label:"good first issue"', 30)
    call = fake_gh.calls[0]
    assert call[:4] == ["api", "-X", "GET", "search/issues"]
    assert 'q=review-requested:@me label:"good first issue"' in call


def test_search_item_fields():
    item = gh_data.parse_search_item(_issue(7, repo="nvaccess/nvda", pr=True, merged=True))
    assert (item.number, item.repo, item.is_pr, item.is_merged) == (7, "nvaccess/nvda", True, True)
    assert item.state_display == "MERGED"
    assert item.author == "alice" and item.labels == ["bug"] and item.comments == 3
    row = item.to_row(gh_data.SEARCH_ITEM_DEFAULT_COLUMNS)
    assert row["repo"] == "nvaccess/nvda" and row["type"] == "PR"


def test_search_pages_up_to_the_limit(fake_gh):
    pages = {1: [_issue(i) for i in range(100)], 2: [_issue(i) for i in range(100, 150)]}
    fake_gh.route("search/issues", lambda args: {
        "total_count": 150,
        "items": pages[int(next(a for a in args if a.startswith("page=")).split("=")[1])],
    })
    items, total = gh_data.search_issues("x", 300)
    assert (len(items), total) == (150, 150)
    assert len(fake_gh.calls) == 2


def test_search_stops_at_what_github_will_give(fake_gh):
    fake_gh.route("search/issues", {"total_count": 5000, "items": [_issue(i) for i in range(100)]})
    items, total = gh_data.search_issues("x", 100)
    assert len(items) == 100 and total == 5000 and len(fake_gh.calls) == 1


def test_search_repos(fake_gh):
    fake_gh.route("search/repositories", {"total_count": 1, "items": [
        {"full_name": "nvaccess/nvda", "stargazers_count": 2653, "language": "Python",
         "html_url": "https://github.com/nvaccess/nvda"}]})
    repos, total = gh_data.search_repos("screen reader", 10)
    assert [r.name for r in repos] == ["nvaccess/nvda"] and repos[0].stars == 2653


def test_my_work_lists_each_item_once_under_its_first_reason(fake_gh):
    replies = {
        "review-requested": [_issue(1, pr=True), _issue(2, pr=True)],
        "assignee": [_issue(2, pr=True), _issue(3)],
        "author:@me archived:false sort": [],
        "mentions": [_issue(4)],
    }

    def reply(args):
        q = next(a for a in args if a.startswith("q="))
        for key, items in replies.items():
            if key in q:
                return {"total_count": len(items) + (50 if key == "mentions" else 0),
                        "items": items}
        return {"total_count": 0, "items": []}
    fake_gh.route("search/issues", reply)
    items, capped, failed = gh_data.fetch_my_work(100)
    assert failed == []
    # Grouped by why, most recently updated first within each group
    assert [(i.number, i.why) for i in items] == [
        (2, "review requested"), (1, "review requested"), (3, "assigned"), (4, "mentioned")]
    assert capped == {"mentioned"}


# ── Saved searches ──────────────────────────────────────────────────────


def test_saved_searches_round_trip(app_data):
    assert ss.load_saved_searches() == []
    ss.add_saved_search(ss.SavedSearch("Bugs", "is:open label:bug"))
    ss.add_saved_search(ss.SavedSearch("Py", "language:python", ss.KIND_REPOS))
    ss.add_saved_search(ss.SavedSearch("bugs", "is:open label:bug repo:o/r"))  # same name, replaced
    loaded = ss.load_saved_searches()
    assert [(s.name, s.kind) for s in loaded] == [("Py", ss.KIND_REPOS), ("bugs", ss.KIND_ISSUES)]
    ss.remove_saved_search("Py")
    assert [s.name for s in ss.load_saved_searches()] == ["bugs"]


def test_unreadable_saved_searches_are_empty(app_data):
    ss._file().write_text("not json", encoding="utf-8")
    assert ss.load_saved_searches() == []
    ss._file().write_text(json.dumps([{"name": "", "query": "x"}, {"name": "ok", "query": "q", "kind": "weird"}]),
                          encoding="utf-8")
    assert [(s.name, s.kind) for s in ss.load_saved_searches()] == [("ok", ss.KIND_ISSUES)]


# ── The window ──────────────────────────────────────────────────────────

if os.environ.get("CI"):
    import wx  # noqa: F401
else:
    pytest.importorskip("wx")

import ghviewer  # noqa: E402

Frame = ghviewer.GhViewerFrame


def test_is_repo_entry():
    assert ghviewer.is_repo_entry("o/r")
    for data in (None, "", ghviewer.FAVORITES_ENTRY, ghviewer.MY_WORK_ENTRY,
                 ghviewer.SEARCH_ENTRY_PREFIX + "Bugs"):
        assert not ghviewer.is_repo_entry(data)


def _frame(view=ghviewer.VIEW_SEARCH_ISSUES, search=(ss.KIND_ISSUES, "q")):
    f = SimpleNamespace(
        view_mode=view, _search=search, _search_total=0, items=[], git_items=[],
        _shown=[], saved_searches=[], repo="o/r", announced=[], statuses=[],
        _category_counts={}, current_limit=100, page_size=100, filter_text="x",
        _return_to=None, events=[],
    )
    f._fetch_is_current = lambda t: True
    f._announce = f.announced.append
    f._set_view_status = lambda m, k="": f.statuses.append(m)
    f._update_title = lambda: None
    f._restore_repo_selection = lambda p: None
    f._refresh_category_labels = lambda: None
    f._row_of = lambda it: Frame._row_of(f, it)
    f._focus_list = lambda row=0: None

    def populate(items, use_favorite_prefix=False):
        f._shown = list(items)
        return f._shown
    f._populate_filtered_list = populate
    return f


def test_search_results_status(monkeypatch):
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda *a: None)
    f = _frame()
    items = [gh_data.parse_search_item(_issue(i)) for i in range(3)]
    Frame._on_search_loaded(f, 1, items, 512)
    assert f.items == items and f.git_items == []
    assert f.statuses == ["Search — 512 issues and pull requests match q, showing 3. Ctrl++ loads more."]


def test_search_beyond_github_limit_says_so(monkeypatch):
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda *a: None)
    f = _frame()
    items = [gh_data.parse_search_item(_issue(i)) for i in range(3)]
    f._search_total = 0
    Frame._on_search_loaded(f, 1, items * 334, 5000)   # 1002 rows, more than GitHub gives
    assert "at most the first 1,000" in f.statuses[-1]


def test_repo_search_results_go_in_git_items(monkeypatch):
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda *a: None)
    f = _frame(ghviewer.VIEW_SEARCH_REPOS, (ss.KIND_REPOS, "q"))
    repos = [gh_data.RepoEntry("o/r")]
    Frame._on_search_loaded(f, 1, repos, 1)
    assert f.git_items == repos and f.items == []
    assert f.statuses == ["Search — 1 repository matches q, showing 1."]


def test_my_work_status_counts_reasons_and_marks_capped(monkeypatch):
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda *a: None)
    f = _frame(ghviewer.VIEW_MY_WORK)
    a = gh_data.Item(1, "A", "OPEN", "u1", True, why="review requested")
    b = gh_data.Item(2, "B", "OPEN", "u2", False, why="your issue")
    Frame._on_my_work_loaded(f, 1, [a, b], 0, {"your issue"})
    assert f.statuses == ["My Work — 2 open: 1 review requested, 1+ your issue. "
                          "Lists marked + have more than 100; search finds the rest."]
    assert f._category_counts[ghviewer.MY_WORK_ENTRY] == 2


@pytest.mark.parametrize("kind, view", [
    (ss.KIND_ISSUES, ghviewer.VIEW_SEARCH_ISSUES), (ss.KIND_REPOS, ghviewer.VIEW_SEARCH_REPOS),
])
def test_run_search_switches_to_its_view(kind, view):
    f = _frame(ghviewer.VIEW_BRANCHES, None)
    f._switch_view = lambda v: f.events.append(("switch", v))
    Frame._run_search(f, kind, "q")
    assert f._search == (kind, "q") and f.events == [("switch", view)]


def test_run_search_again_in_the_same_view_reloads():
    f = _frame()
    f._load_items = lambda: f.events.append("load")
    Frame._run_search(f, ss.KIND_ISSUES, "new")
    assert f.events == ["load"] and f.filter_text == "" and f._search == (ss.KIND_ISSUES, "new")


def test_current_entry_is_the_saved_search_on_screen():
    f = _frame(search=(ss.KIND_ISSUES, "is:open label:bug"))
    f.saved_searches = [ss.SavedSearch("Bugs", "is:open label:bug")]
    f._view_entry = lambda view: Frame._view_entry(f, view)
    assert Frame._current_entry(f) == ghviewer.SEARCH_ENTRY_PREFIX + "Bugs"
    f._search = (ss.KIND_ISSUES, "something else")
    assert Frame._current_entry(f) is None


def test_enter_on_a_search_result_opens_it_in_its_repo():
    item = gh_data.parse_search_item(_issue(9, repo="nvaccess/nvda"))
    f = _frame()
    f._fetch_token = 4
    f._open_repo_from_list = lambda repo, it: f.events.append((repo, it.number))
    f._set_pending_target = lambda *a: Frame._set_pending_target(f, *a)
    f._open_item_checked = lambda it, parent, *a: Frame._open_item_checked(f, it, parent, *a)
    f._fork_parent = {"nvaccess/nvda": None}   # known not to be a fork
    Frame._open_item_here(f, item)
    assert f.events == [("nvaccess/nvda", 9)]
    assert f._pending_target == (4, ghviewer.VIEW_ISSUES, "item", "9")


def test_an_item_in_a_fork_says_why_it_can_t_open_here(monkeypatch):
    # The Issues view of a fork shows its upstream's issues; #9 there is
    # something else, so it must not be "found" there. Nor does Enter open
    # the browser: it says why, and that Ctrl+O does.
    opened = []
    monkeypatch.setattr(ghviewer.webbrowser, "open", opened.append)
    item = gh_data.parse_search_item(_issue(9, repo="me/fork"))
    f = _frame()
    told = []
    f._tell = lambda msg, *a, **k: told.append(msg)
    f._open_repo_from_list = lambda *a: pytest.fail("not in the fork's issues")
    f._open_item_checked = lambda it, parent, *a: Frame._open_item_checked(f, it, parent, *a)
    f._fork_parent = {"me/fork": "up/r"}
    Frame._open_item_here(f, item)
    assert opened == []
    assert told == ["#9 is in me/fork, a fork; GHManage shows that repository's issues "
                    "from up/r. Ctrl+O opens it on GitHub."]


def test_my_work_keeps_what_loaded_when_one_search_fails(fake_gh):
    def reply(args):
        q = next(a for a in args if a.startswith("q="))
        if "mentions" in q:
            raise gh_data.GhError("API rate limit exceeded")
        if "review-requested" in q:
            return {"total_count": 1, "items": [_issue(1, pr=True)]}
        return {"total_count": 0, "items": []}
    fake_gh.route("search/issues", reply)
    items, capped, failed = gh_data.fetch_my_work()
    assert [i.number for i in items] == [1] and failed == ["mentioned"]


def test_my_work_all_failing_is_an_error(fake_gh):
    fake_gh.route("search/issues", gh_data.GhError("API rate limit exceeded"))
    with pytest.raises(gh_data.GhError):
        gh_data.fetch_my_work()


def test_view_more_asks_only_for_the_next_page(fake_gh):
    fake_gh.route("search/issues", {"total_count": 500, "items": [_issue(i) for i in range(100, 200)]})
    items, total = gh_data.search_issues("x", 100, offset=100)
    assert len(fake_gh.calls) == 1
    assert "page=2" in fake_gh.calls[0] and "per_page=100" in fake_gh.calls[0]
    assert items[0].number == 100


def test_view_more_stops_at_the_end_of_the_results():
    f = _frame()
    f.items = [object()] * 30
    f._search_total = 30
    f._load_items = lambda: pytest.fail("nothing more to load")
    f._view_source = lambda: Frame._view_source(f)
    Frame.on_view_more(f, None)
    assert f.announced == ["That is every result GitHub gives for this search."]
