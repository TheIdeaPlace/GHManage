"""Across Repositories (#130): one kind of thing from many repositories."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

import across
import gh_data
from across import Row
from gh_data import GhError, Item, Release


def rel(tag, when, draft=False, pre=False):
    return Release(tag=tag, name=tag, draft=draft, prerelease=pre, created_at=when, url=f"u/{tag}")


# ── Fetching ────────────────────────────────────────────────────────────


@pytest.fixture
def fake(monkeypatch):
    calls = []

    def releases(repo, limit=30):
        calls.append(("releases", repo, limit))
        if repo == "o/gone":
            raise GhError("gh: Not Found (HTTP 404)")
        return {"o/a": [rel("v2", "2026-11-02"), rel("v1", "2026-10-01")],
                "o/b": [rel("v9", "2026-11-05")], "o/none": []}[repo]
    monkeypatch.setattr(gh_data, "fetch_releases", releases)
    return calls


def test_each_repository_is_read_and_failures_are_named(fake):
    r = across.fetch("releases", ["o/a", "o/gone", "o/b", "o/none"], limit=10)
    assert [across.repo_of(x) for x in r.rows] == ["o/a", "o/a", "o/b"]   # chosen order
    assert r.failed == {"o/gone": "not found, or no access"}
    assert r.empty_repos() == ["o/none"]
    assert {c[1] for c in fake} == {"o/a", "o/gone", "o/b", "o/none"} and fake[0][2] == 10


def test_latest_release_only_takes_githubs_latest(fake):
    r = across.fetch("releases", ["o/a", "o/b"], latest_only=True)
    assert [x.item.tag for x in r.rows] == ["v2", "v9"]


def test_latest_skips_drafts_and_prereleases():
    assert across.latest_release([rel("v3", "3", draft=True), rel("v2", "2", pre=True),
                                  rel("v1", "1")])[0].tag == "v1"
    assert across.latest_release([rel("v2", "2", pre=True)])[0].tag == "v2"
    assert across.latest_release([rel("v1", "1", draft=True)]) == []


def test_progress_is_called_as_each_repository_answers(fake):
    seen = []
    across.fetch("releases", ["o/a", "o/b", "o/gone"], progress=lambda d, n: seen.append((d, n)))
    assert sorted(seen) == [(1, 3), (2, 3), (3, 3)]


def test_reads_happen_side_by_side(monkeypatch):
    # Every repository waits for the others: only side by side does it finish.
    barrier = threading.Barrier(3, timeout=5)

    def runs(repo, limit=30):
        barrier.wait()
        return []
    monkeypatch.setattr(gh_data, "fetch_workflow_runs", runs)
    r = across.fetch("runs", ["a/1", "a/2", "a/3"])
    assert not r.failed


def test_issues_say_their_repository_and_a_fork_means_its_upstream(monkeypatch):
    monkeypatch.setattr(gh_data, "resolve_issue_repo", lambda r: "up/r" if r == "me/fork" else r)
    monkeypatch.setattr(gh_data, "fetch_issues",
                        lambda repo, state, limit, item_filter=None: [Item(1, "I", "OPEN", "u", False)])
    monkeypatch.setattr(gh_data, "fetch_prs",
                        lambda repo, state, limit, item_filter=None: [Item(2, "P", "OPEN", "u", True)])
    r = across.fetch("issues", ["o/a", "me/fork"])
    assert sorted((i.repo, i.number) for i in r.rows) == [("o/a", 1), ("o/a", 2),
                                                          ("up/r", 1), ("up/r", 2)]


def test_discussions_off_is_a_note_not_a_failure(monkeypatch):
    monkeypatch.setattr(gh_data, "fetch_discussions",
                        lambda repo, state, limit: SimpleNamespace(enabled=False, items=[]))
    r = across.fetch("discussions", ["o/a"])
    assert r.notes == {"o/a": "Discussions are off"} and not r.failed


@pytest.mark.parametrize("text, said", [
    ("GraphQL: Could not resolve to a Repository with the name 'x/y'. (repository)",
     "not found, or no access"),
    ("gh: Not Found (HTTP 404)", "not found, or no access"),
    ("HTTP 403: Resource not accessible", "no access"),
    ("HTTP 502: Bad Gateway", "GitHub didn't answer in time"),
    ("gh: something else went wrong..", "something else went wrong"),
])
def test_why_failed_is_short(text, said):
    assert across.why_failed(GhError(text)) == said


# ── Order and moving between repositories ──────────────────────────────


ROWS = [Row("o/a", rel("a2", "x"), "2026-11-02"), Row("o/a", rel("a1", "x"), "2026-10-01"),
        Row("o/b", rel("b1", "x"), "2026-11-05"), Row("o/c", rel("c1", "x"), "")]


def test_newest_first_across_repositories_undated_last():
    assert [r.item.tag for r in across.order(ROWS, ["o/a", "o/b", "o/c"])] == [
        "b1", "a2", "a1", "c1"]


def test_oldest_first_and_by_name():
    assert [r.item.tag for r in across.order(ROWS, [], newest=False)] == ["a1", "a2", "b1", "c1"]
    assert [r.item.tag for r in across.order(ROWS, [], by_name=True)] == ["a1", "a2", "b1", "c1"]


def test_grouped_follows_the_chosen_repository_order():
    out = across.order(ROWS, ["o/b", "o/a", "o/c"], grouped=True)
    assert [(r.repo, r.item.tag) for r in out] == [("o/b", "b1"), ("o/a", "a2"), ("o/a", "a1"),
                                                   ("o/c", "c1")]


def test_next_and_previous_repository():
    rows = across.order(ROWS, ["o/a", "o/b", "o/c"], grouped=True)   # a2 a1 b1 c1
    assert across.next_repo(rows, 0, 1) == 2       # a → b
    assert across.next_repo(rows, 2, 1) == 3       # b → c
    assert across.next_repo(rows, 3, 1) == -1      # none after c
    assert across.next_repo(rows, 3, -1) == 2      # c → b
    assert across.next_repo(rows, 2, -1) == 0      # b → the first of a's run
    assert across.next_repo(rows, 1, -1) == -1     # nothing before a


def test_next_repository_in_mixed_order_skips_the_same_repository():
    mixed = [Row("o/a", None), Row("o/a", None), Row("o/b", None), Row("o/a", None)]
    assert across.next_repo(mixed, 0, 1) == 2
    assert across.next_repo(mixed, 2, 1) == 3


def test_a_row_reads_with_its_repository():
    row = Row("o/a", rel("v2", "2026-11-02T10:00:00Z"))
    assert row.to_row(["repo", "tag"]) == {"repo": "o/a", "tag": "v2"}
    assert row.url == "u/v2"


def test_status_says_what_came_back_and_from_where():
    r = across.Result("releases", rows=ROWS[:2], repos=["o/a", "o/b", "o/x"],
                      failed={"o/x": "no access"})
    assert across.status(r, 2) == ("Releases from 3 repositories: 2 releases. 1 has none. "
                                   "Couldn't read o/x: no access.")
    one = across.Result("releases", rows=ROWS[:1], repos=["o/a"])
    assert across.status(one, 1) == "Releases from 1 repository: 1 release."
