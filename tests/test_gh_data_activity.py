"""Starred and watched repositories, and the activity feed."""

from __future__ import annotations

import re

import pytest

import gh_data
from columns import row_text
from gh_columns import ACTIVITY_SET, REPO_SET
from gh_data import GhError, parse_event


@pytest.fixture(autouse=True)
def _fresh_login(monkeypatch):
    # current_login caches; each test starts from not knowing who is signed in.
    monkeypatch.setattr(gh_data, "_login", None)


def _repos(n, start=0):
    return [{"full_name": f"o/r{i}", "description": f"d{i}"} for i in range(start, start + n)]


# ── Paging ─────────────────────────────────────────────────────────────


def test_api_pages_stops_at_a_short_page(fake_gh):
    fake_gh.route("&page=1", _repos(100))
    fake_gh.route("&page=2", _repos(30, 100))
    rows = gh_data._api_pages("user/starred", 500)
    assert len(rows) == 130
    assert len(fake_gh.calls) == 2


def test_api_pages_stops_at_the_limit(fake_gh):
    fake_gh.route("&page=1", _repos(100))
    fake_gh.route("&page=2", _repos(100, 100))
    rows = gh_data._api_pages("user/starred", 200)
    assert len(rows) == 200
    # Not asked for a third page, though the second was full
    assert not fake_gh.called_with("&page=3")


def test_api_pages_small_limit_asks_for_a_small_page(fake_gh):
    fake_gh.route("api", _repos(5))
    assert len(gh_data._api_pages("user/starred", 5)) == 5
    assert fake_gh.calls == [["api", "user/starred?per_page=5&page=1"]]


def test_api_pages_appends_to_an_existing_query(fake_gh):
    fake_gh.route("api", [])
    gh_data._api_pages("x?sort=updated", 10)
    assert fake_gh.calls[0][1] == "x?sort=updated&per_page=10&page=1"


def test_api_pages_empty_and_non_list_replies(fake_gh):
    fake_gh.route("api", "  ")
    assert gh_data._api_pages("x", 100) == []
    fake_gh.routes.clear()
    fake_gh.route("api", {"message": "odd"})
    assert gh_data._api_pages("x", 100) == []


def test_api_pages_error_propagates(fake_gh):
    fake_gh.route("api", GhError("HTTP 401"))
    with pytest.raises(GhError):
        gh_data._api_pages("x", 100)


# ── Starred / watched ──────────────────────────────────────────────────


def test_starred_repos_become_entries(fake_gh):
    fake_gh.route("user/starred", [
        {"full_name": "a/one", "description": None, "fork": True, "archived": True,
         "html_url": "https://github.com/a/one", "language": "Python",
         "stargazers_count": 1234, "forks_count": 5, "open_issues_count": 7,
         "pushed_at": "2026-10-01T10:00:00Z", "private": False},
        {"full_name": "b/two", "description": "Two"},
        {"description": "no name, dropped"},
    ])
    one, two = gh_data.fetch_starred_repos()
    assert (one.name, one.owner, one.url, one.language, one.stars, one.forks,
            one.open_issues, one.archived, one.fork) == (
        "a/one", "a", "https://github.com/a/one", "Python", 1234, 5, 7, True, True)
    # No address in the reply: built from the name
    assert two.url == "https://github.com/b/two" and two.description == "Two"
    row = one.to_row(["repo", "description", "language", "stars", "pushed", "owner"])
    assert row == {"repo": "a/one", "description": "archived; fork", "language": "Python",
                   "stars": "1,234", "pushed": "2026-10-01", "owner": "a"}
    assert two.to_row(["description"]) == {"description": "Two"}
    cols = ["repo", "language"]
    assert row_text(one.to_row(cols), REPO_SET.defs(cols)) == "a/one, Language: Python"


def test_watched_repos_use_subscriptions(fake_gh):
    fake_gh.route("user/subscriptions", [{"full_name": "c/three"}])
    assert [r.name for r in gh_data.fetch_watched_repos()] == ["c/three"]


def test_repo_lists_ask_for_the_limit(fake_gh):
    fake_gh.route("user/starred", [])
    gh_data.fetch_starred_repos(250)
    assert fake_gh.calls[0] == ["api", "user/starred?per_page=100&page=1"]


# ── Who is signed in ───────────────────────────────────────────────────


def test_current_login_is_looked_up_once(fake_gh):
    fake_gh.route("api user", "octo\n")
    assert gh_data.current_login() == "octo"
    assert gh_data.current_login() == "octo"
    assert len(fake_gh.calls) == 1


def test_current_login_empty_is_an_error(fake_gh):
    fake_gh.route("api user", "")
    with pytest.raises(GhError, match="gh auth login"):
        gh_data.current_login()


# ── Activity feed ──────────────────────────────────────────────────────


def _stars(n):
    return [{"type": "WatchEvent", "actor": {"login": "a"}, "repo": {"name": "o/r"}}] * n


def test_fetch_activity_reads_received_events(fake_gh):
    fake_gh.route("api user -q", "octo")
    fake_gh.route("received_events", _stars(1))
    events, more = gh_data.fetch_activity(100)
    assert fake_gh.called_with("users/octo/received_events?per_page=100&page=1")
    assert events[0].summary == "a starred o/r"
    # A page came back, and two more pages exist to ask for
    assert more is True


def test_fetch_activity_does_not_stop_at_a_short_page(fake_gh):
    # Seen on the real API: pages of 96, 100 and 81 events
    fake_gh.route("api user -q", "octo")
    fake_gh.route("&page=1", _stars(96))
    fake_gh.route("&page=2", _stars(100))
    events, more = gh_data.fetch_activity(200)
    assert len(events) == 196 and more is True


def test_fetch_activity_never_asks_past_what_github_keeps(fake_gh):
    # A fourth page is an HTTP 422, not an empty list
    fake_gh.route("api user -q", "octo")
    fake_gh.route("&page=4", GhError("HTTP 422: pagination is limited"))
    fake_gh.route("received_events", lambda args: _stars(100))
    events, more = gh_data.fetch_activity(1000)
    assert len(events) == gh_data.ACTIVITY_MAX
    assert more is False
    assert not fake_gh.called_with("&page=4")


def test_fetch_activity_is_newest_first_whatever_order_github_sends(fake_gh):
    # Seen on the real API: a 04:39 event listed above an 08:22 one
    fake_gh.route("api user -q", "octo")
    fake_gh.route("received_events", [
        {"type": "WatchEvent", "repo": {"name": "o/a"}, "created_at": "2026-10-05T08:29:00Z"},
        {"type": "WatchEvent", "repo": {"name": "o/b"}, "created_at": "2026-10-05T04:39:00Z"},
        {"type": "WatchEvent", "repo": {"name": "o/c"}, "created_at": "2026-10-05T08:22:00Z"},
    ])
    events, _ = gh_data.fetch_activity(100)
    assert [e.repo for e in events] == ["o/a", "o/c", "o/b"]


def test_fetch_activity_empty_page_means_no_more(fake_gh):
    fake_gh.route("api user -q", "octo")
    fake_gh.route("&page=1", _stars(40))
    fake_gh.route("&page=2", [])
    events, more = gh_data.fetch_activity(200)
    assert len(events) == 40 and more is False


# ── Pull request titles, which events no longer carry ──────────────────


def _pr_event(repo, number, verb="opened", title=""):
    return gh_data.ActivityEvent(
        "PullRequestEvent", "a", repo, f"{verb} pull request #{number}",
        title=title, verb=verb, subject_kind="PR", number=number,
    )


@pytest.fixture
def graphql(monkeypatch):
    """Stand-in for gh_data._graphql: replies in turn, records each query."""
    class Fake:
        def __init__(self):
            self.queries: list[str] = []
            self.replies: list = []

        def __call__(self, query):
            self.queries.append(query)
            reply = self.replies.pop(0) if self.replies else {"data": {}}
            if isinstance(reply, BaseException):
                raise reply
            return reply
    fake = Fake()
    monkeypatch.setattr(gh_data, "_graphql", fake)
    return fake


def test_pr_titles_come_from_one_graphql_query(graphql):
    graphql.replies.append({"data": {
        "r0": {"p3": {"title": "Three", "body": "Body 3"}, "p4": {"title": "Four", "body": "x"}},
        "r1": {"p9": None},
    }})
    events = [_pr_event("o/a", 3), _pr_event("o/a", 4, "closed"), _pr_event("o/b", 9),
              _pr_event("o/a", 3, title="Kept")]
    gh_data._fill_pr_titles(events)
    assert [e.title for e in events] == ["Three", "Four", "", "Kept"]
    # Only an opened PR takes its description
    assert events[0].body == "Body 3" and events[1].body == ""
    assert len(graphql.queries) == 1
    q = graphql.queries[0]
    assert 'r0: repository(owner: "o", name: "a")' in q and "p3: pullRequest(number: 3)" in q


def test_partial_reply_keeps_what_did_resolve(graphql):
    # What gh really returns when one repo or PR can't be read: the data it
    # got, nulls where it couldn't, and an errors list. No per-repo retries.
    graphql.replies.append({
        "data": {"r0": None, "r1": {"p1": {"title": "One"}, "p2": None}},
        "errors": [{"type": "NOT_FOUND"}],
    })
    events = [_pr_event("o/gone", 5), _pr_event("o/ok", 1), _pr_event("o/ok", 2)]
    gh_data._fill_pr_titles(events)
    assert [e.title for e in events] == ["", "One", ""]
    assert len(graphql.queries) == 1


def test_many_repos_are_split_across_queries(graphql):
    events = [_pr_event(f"o/r{i}", 1) for i in range(gh_data._TITLE_QUERY_REPOS + 5)]
    gh_data._fill_pr_titles(events)
    assert len(graphql.queries) == 2


@pytest.mark.parametrize("failure", [
    GhError("HTTP 502"), OSError("too long"), ValueError("bad"), {"data": "not a dict"},
])
def test_title_lookup_failure_is_never_fatal(graphql, failure):
    graphql.replies.append(failure)
    events = [_pr_event("o/a", 1)]
    gh_data._fill_pr_titles(events)
    assert events[0].title == ""


def test_no_lookup_when_nothing_needs_a_title(graphql):
    gh_data._fill_pr_titles([_pr_event("o/a", 1, title="Has one"),
                            gh_data.ActivityEvent("WatchEvent", "a", "o/a", "starred")])
    assert graphql.queries == []


def test_graphql_returns_partial_data_from_a_failed_gh(monkeypatch, real_graphql):
    import subprocess

    class Done:
        returncode = 1
        stdout = '{"data": {"r0": null}, "errors": [{"type": "NOT_FOUND"}]}'
        stderr = "gh: Could not resolve to a Repository"
    seen = {}

    def run(args, **kw):
        seen["args"], seen["input"] = args, kw.get("input")
        return Done()
    monkeypatch.setattr(subprocess, "run", run)
    reply = real_graphql("{ x }")
    assert reply["data"] == {"r0": None}
    # The query goes on stdin, not the command line
    assert seen["args"][-3:] == ["graphql", "--input", "-"]
    assert '"query": "{ x }"' in seen["input"]


def test_graphql_with_no_json_is_an_error(monkeypatch, real_graphql):
    import subprocess

    class Done:
        returncode = 1
        stdout = ""
        stderr = "gh: not logged in"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())
    with pytest.raises(GhError, match="not logged in"):
        real_graphql("{ x }")


def test_parse_event_records_what_it_is_about():
    pr = _ev("PullRequestEvent", {"action": "opened", "number": 5})
    assert (pr.subject_kind, pr.number, pr.pr_number) == ("PR", 5, 5)
    assert pr.subject_url == "https://github.com/o/r/pull/5"
    assert _ev("PullRequestReviewEvent", {"pull_request": {"number": 6}}).pr_number == 6
    issue = _ev("IssuesEvent", {"action": "opened", "issue": {"number": 7}})
    assert (issue.subject_kind, issue.pr_number) == ("issue", 0)
    # A comment's subject is the issue, not the comment anchor
    comment = _ev("IssueCommentEvent", {
        "issue": {"number": 8, "html_url": "https://github.com/o/r/issues/8"},
        "comment": {"html_url": "https://github.com/o/r/issues/8#issuecomment-1"}})
    assert comment.url.endswith("#issuecomment-1")
    assert comment.subject_url == "https://github.com/o/r/issues/8"
    rel = _ev("ReleaseEvent", {"release": {"tag_name": "v1", "html_url": "https://rel"}})
    assert (rel.subject_kind, rel.subject_url) == ("release", "https://rel")
    # Events about a branch, a push or the repo itself have no subject
    for etype in ("WatchEvent", "PushEvent", "DeleteEvent", "CreateEvent", "PublicEvent"):
        assert _ev(etype).subject_url == ""


def test_fetch_activity_fills_titles(fake_gh, graphql):
    fake_gh.route("api user -q", "octo")
    fake_gh.route("received_events", [{
        "type": "PullRequestEvent", "repo": {"name": "o/r"},
        "payload": {"action": "opened", "number": 3, "pull_request": {"number": 3}},
    }])
    graphql.replies.append({"data": {"r0": {"p3": {"title": "Filled", "body": ""}}}})
    events, _ = gh_data.fetch_activity(100)
    assert events[0].title == "Filled"


def test_a_failing_later_page_keeps_the_pages_already_read(fake_gh):
    fake_gh.route("api user -q", "octo")
    fake_gh.route("&page=2", GhError("HTTP 502"))
    fake_gh.route("&page=1", [{"id": str(i), "type": "WatchEvent"} for i in range(100)])
    events, more = gh_data.fetch_activity(300)
    # Kept, and not taken as the end of the feed: View More tries again
    assert len(events) == 100 and more is True


def test_a_failing_first_page_is_an_error(fake_gh):
    fake_gh.route("api user -q", "octo")
    fake_gh.route("received_events", GhError("HTTP 401"))
    with pytest.raises(GhError):
        gh_data.fetch_activity(100)


def test_an_event_on_two_pages_is_listed_once(fake_gh):
    # A new event between requests shifts the last of page 1 onto page 2
    fake_gh.route("api user -q", "octo")
    fake_gh.route("&page=1", [{"id": str(i), "type": "WatchEvent"} for i in range(100)])
    fake_gh.route("&page=2", [{"id": "99", "type": "WatchEvent"}, {"id": "100", "type": "WatchEvent"}])
    events, _ = gh_data.fetch_activity(200)
    assert len(events) == 101
    assert len({e.event_id for e in events}) == 101


def _ev(etype, payload=None, **extra):
    raw = {
        "type": etype,
        "actor": {"login": "alice", "display_login": "alice"},
        "repo": {"name": "o/r"},
        "created_at": "2026-10-05T14:32:00Z",
        "payload": payload or {},
    }
    raw.update(extra)
    return parse_event(raw)


@pytest.mark.parametrize("etype, payload, action, title, url", [
    ("WatchEvent", {}, "starred", "", "https://github.com/o/r"),
    ("ForkEvent", {"forkee": {"full_name": "alice/r", "html_url": "https://github.com/alice/r"}},
     "forked", "to alice/r", "https://github.com/alice/r"),
    ("CreateEvent", {"ref_type": "repository", "ref": None}, "created repository", "",
     "https://github.com/o/r"),
    ("CreateEvent", {"ref_type": "branch", "ref": "dev"}, "created branch dev", "",
     "https://github.com/o/r/tree/dev"),
    ("CreateEvent", {"ref_type": "tag", "ref": "v1"}, "created tag v1", "",
     "https://github.com/o/r/releases/tag/v1"),
    ("DeleteEvent", {"ref_type": "branch", "ref": "old"}, "deleted branch old", "",
     "https://github.com/o/r"),
    ("IssuesEvent", {"action": "opened", "issue": {"number": 7, "title": "Bug",
                                                   "html_url": "https://github.com/o/r/issues/7"}},
     "opened issue #7", "Bug", "https://github.com/o/r/issues/7"),
    ("PullRequestEvent", {"action": "closed", "number": 3,
                          "pull_request": {"merged": True, "title": "Feat"}},
     "merged pull request #3", "Feat", "https://github.com/o/r/pull/3"),
    ("PullRequestEvent", {"action": "closed", "number": 4, "pull_request": {"merged": False}},
     "closed pull request #4", "", "https://github.com/o/r/pull/4"),
    ("IssueCommentEvent", {"issue": {"number": 9, "title": "Q", "pull_request": {}},
                           "comment": {"html_url": "https://c", "body": "hi"}},
     "commented on pull request #9", "Q", "https://c"),
    ("IssueCommentEvent", {"issue": {"number": 9, "title": "Q"}, "comment": {}},
     "commented on issue #9", "Q", "https://github.com/o/r"),
    ("PullRequestReviewEvent", {"review": {"state": "approved", "html_url": "https://rv"},
                                "pull_request": {"number": 2, "title": "T"}},
     "approved pull request #2", "T", "https://rv"),
    ("PullRequestReviewEvent", {"review": {"state": "CHANGES_REQUESTED"},
                                "pull_request": {"number": 2}},
     "requested changes on pull request #2", "", "https://github.com/o/r"),
    ("PullRequestReviewCommentEvent", {"comment": {"html_url": "https://rc"},
                                       "pull_request": {"number": 2}},
     "commented on the review of pull request #2", "", "https://rc"),
    ("ReleaseEvent", {"action": "published",
                      "release": {"tag_name": "v1.0", "name": "Big one", "html_url": "https://rel"}},
     "published release v1.0", "Big one", "https://rel"),
    ("ReleaseEvent", {"release": {"tag_name": "v2", "name": "v2"}},
     "published release v2", "", "https://github.com/o/r"),
    ("CommitCommentEvent", {"comment": {"commit_id": "abcdef1234", "html_url": "https://cc"}},
     "commented on commit abcdef1", "", "https://cc"),
    ("PublicEvent", {}, "made the repository public", "", "https://github.com/o/r"),
    ("MemberEvent", {"action": "added", "member": {"login": "bob"}},
     "added bob as a collaborator", "", "https://github.com/o/r"),
    ("GollumEvent", {"pages": [{"title": "Home", "html_url": "https://wiki"}]},
     "edited the wiki", "Home", "https://wiki"),
    ("DiscussionEvent", {"action": "created",
                         "discussion": {"number": 5, "title": "Idea", "html_url": "https://d"}},
     "created discussion #5", "Idea", "https://d"),
    ("SponsorshipEvent", {}, "sponsored", "", "https://github.com/o/r"),
    ("BrandNewThingEvent", {}, "brand new thing", "", "https://github.com/o/r"),
    # Who or what a verb applies to, so rows that would read alike don't
    ("PullRequestEvent", {"action": "labeled", "number": 3, "label": {"name": "dependencies"}},
     'labeled pull request #3 "dependencies"', "", "https://github.com/o/r/pull/3"),
    ("IssuesEvent", {"action": "unlabeled", "issue": {"number": 4}, "label": None},
     "unlabeled issue #4", "", "https://github.com/o/r/issues/4"),
    ("IssuesEvent", {"action": "assigned", "issue": {"number": 4}, "assignee": {"login": "bob"}},
     "assigned bob to issue #4", "", "https://github.com/o/r/issues/4"),
    ("IssuesEvent", {"action": "unassigned", "issue": {"number": 4}, "assignee": {"login": "bob"}},
     "unassigned bob from issue #4", "", "https://github.com/o/r/issues/4"),
    ("PullRequestEvent", {"action": "review_requested", "number": 3,
                          "requested_reviewer": {"login": "cat"}},
     "requested a review from cat on pull request #3", "", "https://github.com/o/r/pull/3"),
])
def test_parse_event_types(etype, payload, action, title, url):
    ev = _ev(etype, payload)
    assert (ev.action, ev.title, ev.url) == (action, title, url)
    assert ev.actor == "alice" and ev.repo == "o/r" and ev.event_type == etype


def test_push_with_commits_counts_them_and_compares():
    ev = _ev("PushEvent", {
        "ref": "refs/heads/main", "size": 2, "distinct_size": 2,
        "before": "1" * 40, "head": "2" * 40,
        "commits": [
            {"sha": "aaaaaaa111", "message": "First\n\nmore"},
            {"sha": "bbbbbbb222", "message": "Second"},
        ],
    })
    assert ev.action == "pushed 2 commits to main"
    assert ev.title == "Second"
    assert ev.body == "aaaaaaa First\nbbbbbbb Second"
    assert ev.url == "https://github.com/o/r/compare/111111111111...222222222222"


def test_push_without_commits_still_reads():
    # GitHub's trimmed push payload: a ref and head, no commit list or size
    ev = _ev("PushEvent", {"ref": "refs/heads/dev", "head": "2" * 40, "before": "0" * 40})
    assert ev.action == "pushed to dev"
    assert ev.url == "https://github.com/o/r/commits/dev"


def test_one_commit_is_singular():
    ev = _ev("PushEvent", {"ref": "refs/heads/main", "size": 1})
    assert ev.action == "pushed 1 commit to main"


def test_opened_issue_keeps_its_body_but_a_close_does_not():
    opened = _ev("IssuesEvent", {"action": "opened", "issue": {"number": 1, "body": "Steps"}})
    closed = _ev("IssuesEvent", {"action": "closed", "issue": {"number": 1, "body": "Steps"}})
    assert opened.body == "Steps" and closed.body == ""


def test_event_with_nothing_in_it_does_not_crash():
    ev = parse_event({})
    assert ev.action == "did something"
    assert ev.actor == "" and ev.repo == "" and ev.url == ""


def test_null_payload_fields_do_not_crash():
    ev = parse_event({"type": "IssuesEvent", "actor": None, "repo": None, "payload": None})
    assert ev.action == "updated issue"


def test_summary_and_rows():
    ev = _ev("IssuesEvent", {"action": "opened", "issue": {"number": 7, "title": "Bug"}})
    assert ev.summary == "alice opened issue #7 in o/r: Bug"
    row = ev.to_row(["actor", "action", "repo", "title", "date", "nope"])
    assert row["actor"] == "alice" and row["nope"] == ""
    assert re.fullmatch(r"2026-10-0[456] \d\d:\d\d", row["date"])
    cols = ["actor", "title"]
    assert row_text(ev.to_row(cols), ACTIVITY_SET.defs(cols)) == "alice, Title: Bug"


@pytest.mark.parametrize("iso, shown", [
    ("", ""),
    ("not a date at all", "not a date at all"[:16]),
    ("2026-10-05T14:32:00", "2026-10-05 14:32"),   # no zone: shown as given
])
def test_local_time_edge_cases(iso, shown):
    assert gh_data._local_time(iso) == shown


@pytest.mark.parametrize("etype, payload, summary", [
    ("WatchEvent", {}, "alice starred o/r"),
    ("ForkEvent", {"forkee": {"full_name": "alice/r"}}, "alice forked o/r to alice/r"),
    ("PublicEvent", {}, "alice made o/r public"),
    ("IssuesEvent", {"action": "closed", "issue": {"number": 1, "title": "T"}},
     "alice closed issue #1 in o/r: T"),
])
def test_summaries_read_as_sentences(etype, payload, summary):
    assert _ev(etype, payload).summary == summary


def test_event_id_is_kept():
    assert parse_event({"id": 123, "type": "WatchEvent"}).event_id == "123"


# ── Counting without fetching ──────────────────────────────────────────


HEAD = "HTTP/2.0 200 OK\r\nContent-Type: application/json\r\n"


@pytest.mark.parametrize("reply, count", [
    # Seen on the real API: 7 starred, one per page, so the last page is 7
    (HEAD + 'Link: <https://api.github.com/user/starred?per_page=1&page=2>; rel="next", '
     '<https://api.github.com/user/starred?per_page=1&page=7>; rel="last"\r\n\r\n[{"id": 1}]', 7),
    (HEAD + '\r\n[{"id": 1}]', 1),     # one page only: no Link header
    (HEAD + "\r\n[]", 0),              # nothing starred
])
def test_count_reads_the_last_page(fake_gh, reply, count):
    fake_gh.route("api -i user/starred?per_page=1", reply)
    assert gh_data.count_starred_repos() == count


def test_count_watched_uses_subscriptions(fake_gh):
    fake_gh.route("api -i user/subscriptions?per_page=1", HEAD + "\r\n[{}, {}]")
    assert gh_data.count_watched_repos() == 2


def test_count_with_a_garbled_reply_is_an_error(fake_gh):
    fake_gh.route("api -i", HEAD + "\r\nnot json")
    with pytest.raises(GhError):
        gh_data.count_starred_repos()


@pytest.mark.parametrize("link, count", [
    # page before per_page: read by name, not position
    ('<https://api.github.com/user/starred?page=2&per_page=1>; rel="next", '
     '<https://api.github.com/user/starred?page=12&per_page=1>; rel="last"', 12),
    ('<https://api.github.com/user/starred?per_page=1&page=3>; rel="last"', 3),
])
def test_count_reads_page_by_name(fake_gh, link, count):
    fake_gh.route("api -i", HEAD + f"Link: {link}\r\n\r\n[{{}}]")
    assert gh_data.count_starred_repos() == count


@pytest.mark.parametrize("reply", [
    # A Link header with no last page: unknown, not "1"
    HEAD + 'Link: <https://api.github.com/user/starred?page=2>; rel="next"\r\n\r\n[{}]',
    # Headers that never end: unknown, not "0"
    HEAD,
])
def test_count_that_cannot_be_read_is_an_error(fake_gh, reply):
    fake_gh.route("api -i", reply)
    with pytest.raises(GhError):
        gh_data.count_starred_repos()


def test_count_appends_to_an_existing_query(fake_gh):
    fake_gh.route("api -i", HEAD + "\r\n[]")
    gh_data._count_items("x?sort=updated")
    assert fake_gh.calls[0] == ["api", "-i", "x?sort=updated&per_page=1"]
