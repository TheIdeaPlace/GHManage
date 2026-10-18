"""Issues, pull requests, labels and the actions on them."""

from __future__ import annotations

import json

import pytest

import gh_data
from gh_data import GhError, Item


def _issue_row(number=1, **extra):
    row = {
        "number": number,
        "title": f"Issue {number}",
        "state": "OPEN",
        "url": f"https://github.com/o/r/issues/{number}",
        "author": {"login": "alice"},
        "createdAt": "2026-01-02T03:04:05Z",
        "updatedAt": "2026-01-03T00:00:00Z",
        "body": "Body text",
        "labels": [{"name": "bug"}, {"name": "ui"}],
        "assignees": [{"login": "bob"}],
        "comments": [
            {"author": {"login": "carol"}, "body": "First", "createdAt": "2026-01-04"},
            {"author": {"login": "dave"}, "body": None, "createdAt": "2026-01-05"},
        ],
    }
    row.update(extra)
    return row


# ── Parsing ────────────────────────────────────────────────────────────


def test_parse_issues_reads_every_field():
    [item] = gh_data._parse_issues(json.dumps([_issue_row(7)]))
    assert item.number == 7
    assert item.is_pr is False
    assert item.author == "alice"
    assert item.labels == ["bug", "ui"]
    assert item.assignees == ["bob"]
    assert item.comments == 2
    assert item.comment_list[0] == {"author": "carol", "body": "First", "created_at": "2026-01-04"}
    # A null comment body becomes an empty string, not None
    assert item.comment_list[1]["body"] == ""


@pytest.mark.parametrize("raw", ["", "   ", "\n"])
def test_parse_empty_output_is_empty_list(raw):
    assert gh_data._parse_issues(raw) == []
    assert gh_data._parse_prs(raw) == []
    assert gh_data._parse_labels(raw) == []


def test_parse_issue_tolerates_missing_and_null_fields():
    [item] = gh_data._parse_issues(json.dumps([{"number": 3, "body": None, "author": None}]))
    assert item.title == ""
    assert item.body == ""
    assert item.author == "unknown"
    assert item.labels == [] and item.comments == 0


def test_parse_author_variants():
    assert gh_data._parse_author({"author": {"login": "x"}}) == "x"
    assert gh_data._parse_author({"author": "plain"}) == "plain"
    assert gh_data._parse_author({}) == "unknown"


def test_parse_comments_accepts_a_bare_count():
    assert gh_data._parse_comments({"comments": 5}) == (5, [])
    assert gh_data._parse_comments({"comments": None}) == (0, [])


def test_parse_prs_reads_pr_fields():
    row = _issue_row(9, isDraft=True, mergedAt="2026-02-01", reviewDecision=None,
                     additions=10, deletions=2, changedFiles=3,
                     baseRefName="main", headRefName="feature")
    [pr] = gh_data._parse_prs(json.dumps([row]))
    assert pr.is_pr and pr.is_draft and pr.is_merged
    assert pr.review_status == ""
    assert (pr.additions, pr.deletions, pr.changed_files) == (10, 2, 3)
    assert (pr.base_branch, pr.head_branch) == ("main", "feature")


# ── Item display ───────────────────────────────────────────────────────


def test_item_kind_and_state_display():
    issue = Item(1, "t", "open", "u", is_pr=False)
    merged = Item(2, "t", "closed", "u", is_pr=True, is_merged=True)
    assert issue.kind == "ISSUE" and issue.state_display == "OPEN"
    assert merged.kind == "PR" and merged.state_display == "MERGED"


def test_item_to_row_blanks_pr_columns_for_issues():
    issue = Item(1, "t", "open", "u", is_pr=False, created_at="2026-01-02T03:04:05Z")
    row = issue.to_row(["number", "created", "+/-", "files", "base", "nonsense"])
    assert row == {"number": "1", "created": "2026-01-02", "+/-": "", "files": "",
                   "base": "", "nonsense": ""}


def test_accessible_string_names_fields_and_skips_blanks():
    item = Item(4, "Crash on start", "open", "u", is_pr=False, author="")
    assert item.to_accessible_string(["number", "title", "author"]) == (
        "number: 4, title: Crash on start"
    )


def test_every_column_is_known_to_to_row():
    item = Item(1, "t", "open", "u", is_pr=True, additions=1, changed_files=1,
                base_branch="b", head_branch="h", created_at="x", updated_at="y")
    row = item.to_row(gh_data.ALL_COLUMNS)
    assert set(row) == set(gh_data.ALL_COLUMNS)


# ── Sorting ────────────────────────────────────────────────────────────


@pytest.fixture
def three_items():
    return [
        Item(2, "banana", "open", "", False, created_at="2026-02", updated_at="2026-09", comments=1),
        Item(10, "Apple", "open", "", False, created_at="2026-01", updated_at="2026-03", comments=7),
        Item(5, "cherry", "open", "", False, created_at="2026-03", updated_at="2026-05", comments=0),
    ]


@pytest.mark.parametrize("order, expected", [
    ("Number (newest first)", [10, 5, 2]),
    ("Number (oldest first)", [2, 5, 10]),
    ("Title (A-Z)", [10, 2, 5]),          # case-insensitive: Apple, banana, cherry
    ("Title (Z-A)", [5, 2, 10]),
    ("Created (newest first)", [5, 2, 10]),
    ("Created (oldest first)", [10, 2, 5]),
    ("Updated (newest first)", [2, 5, 10]),
    ("Updated (oldest first)", [10, 5, 2]),
    ("Comments (most first)", [10, 2, 5]),
])
def test_sort_items(three_items, order, expected):
    assert [i.number for i in gh_data.sort_items(three_items, order)] == expected


def test_every_offered_sort_order_is_handled(three_items):
    for order in gh_data.SORT_ORDERS:
        result = gh_data.sort_items(three_items, order)
        assert result is not three_items, f"{order!r} fell through unsorted"


def test_unknown_sort_order_leaves_items_alone(three_items):
    assert gh_data.sort_items(three_items, "whatever") is three_items


# ── Fetching ───────────────────────────────────────────────────────────


def test_fetch_issues_builds_command(fake_gh):
    fake_gh.route("issue list", [_issue_row(1)])
    items = gh_data.fetch_issues("o/r", state="closed", limit=50, label="bug")
    assert [i.number for i in items] == [1]
    [call] = fake_gh.called_with("issue list")
    assert call[call.index("--state") + 1] == "closed"
    assert call[call.index("--limit") + 1] == "50"
    assert call[call.index("--label") + 1] == "bug"
    assert call[call.index("--repo") + 1] == "o/r"


def test_fetch_issues_without_label_or_repo(fake_gh):
    fake_gh.route("issue list", [])
    assert gh_data.fetch_issues(None) == []
    [call] = fake_gh.called_with("issue list")
    assert "--label" not in call and "--repo" not in call


def test_fork_issues_come_from_the_parent(fake_gh):
    fake_gh.route("repo view me/fork", {"isFork": True,
                                        "parent": {"owner": {"login": "up"}, "name": "stream"}})
    fake_gh.route("pr list", [])
    gh_data.fetch_prs("me/fork")
    [call] = fake_gh.called_with("pr list")
    assert call[call.index("--repo") + 1] == "up/stream"


@pytest.mark.parametrize("reply", [
    GhError("boom"),
    "not json",
    {"isFork": True, "parent": None},
    {"isFork": True, "parent": {"owner": {}, "name": "x"}},
    {"isFork": False},
])
def test_parent_repo_falls_back_to_none(fake_gh, reply):
    fake_gh.route("repo view", reply)
    assert gh_data.parent_repo("o/r") is None
    assert gh_data.resolve_issue_repo("o/r") == "o/r"


def test_parent_repo_of_nothing_makes_no_call(fake_gh):
    assert gh_data.parent_repo(None) is None
    assert gh_data.parent_repo("") is None
    assert fake_gh.calls == []


def test_parse_accepts_the_single_object_view_returns():
    # `gh issue view --json` prints one object, not an array
    [item] = gh_data._parse_issues(json.dumps(_issue_row(8)))
    assert item.number == 8
    [pr] = gh_data._parse_prs(json.dumps(_issue_row(9)))
    assert pr.number == 9 and pr.is_pr


def test_parse_non_list_non_object_is_empty():
    assert gh_data._parse_issues("42") == []


def test_fetch_item_by_number_finds_a_pr_as_a_pr(fake_gh):
    # gh issue view would also answer for a PR number, minus the PR fields,
    # so the PR lookup has to come first.
    fake_gh.route("pr view", _issue_row(12, headRefName="feature"))
    fake_gh.route("issue view", _issue_row(12))
    item = gh_data.fetch_item_by_number(12, "o/r")
    assert item.is_pr and item.head_branch == "feature"
    assert fake_gh.called_with("issue view") == []


def test_fetch_item_by_number_falls_back_to_issue(fake_gh):
    fake_gh.route("pr view", GhError("Could not resolve to a PullRequest"))
    fake_gh.route("issue view", _issue_row(2))
    item = gh_data.fetch_item_by_number(2, "o/r")
    assert item is not None and not item.is_pr and item.number == 2


def test_fetch_item_by_number_missing_returns_none(fake_gh):
    fake_gh.route("pr view", GhError(
        "GraphQL: Could not resolve to a PullRequest with the number of 99. (repository.pullRequest)"))
    fake_gh.route("issue view", GhError(
        "GraphQL: Could not resolve to an issue or pull request with the number of 99. (repository.issue)"))
    assert gh_data.fetch_item_by_number(99, "o/r") is None


@pytest.mark.parametrize("error", [
    "error connecting to api.github.com",
    "HTTP 401: Bad credentials",
    "API rate limit exceeded",
    "GraphQL: Could not resolve to a Repository with the name 'o/gone'. (repository)",
])
def test_fetch_item_by_number_real_failures_are_not_not_found(fake_gh, error):
    # Reporting these as "does not exist" would tell the user something false
    fake_gh.route("pr view", GhError(error))
    with pytest.raises(GhError, match=error[:20]):
        gh_data.fetch_item_by_number(5, "o/r")
    assert fake_gh.called_with("issue view") == []


def test_fetch_item_by_number_issue_lookup_failure_propagates(fake_gh):
    fake_gh.route("pr view", GhError("Could not resolve to a PullRequest with the number of 3"))
    fake_gh.route("issue view", GhError("HTTP 502"))
    with pytest.raises(GhError, match="502"):
        gh_data.fetch_item_by_number(3, "o/r")


@pytest.mark.parametrize("func, verb", [
    (gh_data.close_item, "close"),
    (gh_data.reopen_item, "reopen"),
])
def test_close_and_reopen(fake_gh, func, verb):
    fake_gh.route(verb, "")
    func(Item(3, "t", "open", "", is_pr=True), "o/r")
    [call] = fake_gh.called_with(verb)
    assert call[:3] == ["pr", verb, "3"] and call[-2:] == ["--repo", "o/r"]


def test_add_comment_passes_body_as_one_argument(fake_gh):
    fake_gh.route("comment", "")
    gh_data.add_comment(Item(3, "t", "open", "", is_pr=False), "two\nlines; rm -rf", "o/r")
    [call] = fake_gh.called_with("comment")
    assert call[call.index("--body") + 1] == "two\nlines; rm -rf"


def test_detect_repo(fake_gh):
    fake_gh.route("nameWithOwner", {"nameWithOwner": "o/r"})
    assert gh_data.detect_repo() == "o/r"


@pytest.mark.parametrize("reply", [GhError("not a repo"), "garbage"])
def test_detect_repo_failure_is_none(fake_gh, reply):
    fake_gh.route("nameWithOwner", reply)
    assert gh_data.detect_repo() is None


def _repos_reply(own, orgs=(), shared=()):
    return {"data": {"viewer": {"own": {"nodes": list(own)},
                                "organizations": {"nodes": list(orgs)},
                                "shared": {"nodes": list(shared)}}}}


def _org(login, admin=False, count=3):
    return {"login": login, "viewerCanAdminister": admin,
            "repositories": {"totalCount": count}}


def test_list_repos_lists_your_own_and_names_your_organizations(monkeypatch):
    queries = []
    own = [{"nameWithOwner": "me/a", "pushedAt": "2026-01-01T00:00:00Z"}]
    monkeypatch.setattr(gh_data, "_graphql", lambda q: queries.append(q) or _repos_reply(
        own, [_org("w3c", count=1108), _org("mine", admin=True, count=13)]))
    listing = gh_data.list_repos(5)
    # Only your own repos: an organization's are under an entry of its own,
    # so a big one (#40) can't bury them
    assert listing.repos == own
    # The organizations you run first, then by name
    assert listing.orgs == [gh_data.OrgEntry("mine", True, 13),
                            gh_data.OrgEntry("w3c", False, 1108)]
    [query] = queries
    assert "ownerAffiliations: [OWNER]" in query
    assert "ORGANIZATION_MEMBER" not in query
    assert "first: 5," in query and "PUSHED_AT" in query


@pytest.mark.parametrize("limit, first", [(0, 1), (250, 100)])
def test_list_repos_keeps_to_one_page(monkeypatch, limit, first):
    queries = []
    monkeypatch.setattr(gh_data, "_graphql",
                        lambda q: queries.append(q) or _repos_reply([]))
    assert gh_data.list_repos(limit).repos == []
    assert f"first: {first}, ownerAffiliations: [OWNER]" in queries[0]


def test_shared_leaves_out_your_organizations_repos(monkeypatch):
    # You stay a collaborator on a repo you move into an organization; it is
    # already under that organization's entry
    shared = [{"owner": {"login": "Mine"}}, {"owner": {"login": "friend"}}, None]
    monkeypatch.setattr(gh_data, "_graphql",
                        lambda q: _repos_reply([], [_org("mine")], shared))
    assert gh_data.list_repos().shared == 1


def test_shared_past_one_page_is_uncounted(monkeypatch):
    shared = [{"owner": {"login": "friend"}}] * 100
    monkeypatch.setattr(gh_data, "_graphql", lambda q: _repos_reply([], [], shared))
    assert gh_data.list_repos().shared is None


def test_list_repos_drops_organizations_it_was_refused(monkeypatch):
    # An organization that blocks the app comes back as null, with an error
    reply = _repos_reply([{"nameWithOwner": "me/a"}, None], [None, _org("ok")])
    reply["errors"] = [{"message": "OAuth App access restrictions"}]
    monkeypatch.setattr(gh_data, "_graphql", lambda q: reply)
    listing = gh_data.list_repos()
    assert listing.repos == [{"nameWithOwner": "me/a"}]
    assert [o.login for o in listing.orgs] == ["ok"]


def test_list_repos_without_organizations_still_lists_yours(monkeypatch):
    reply = {"data": {"viewer": {"own": {"nodes": [{"nameWithOwner": "me/a"}]},
                                 "organizations": None, "shared": None}},
             "errors": [{"message": "Something went wrong"}]}
    monkeypatch.setattr(gh_data, "_graphql", lambda q: reply)
    listing = gh_data.list_repos()
    assert listing.repos == [{"nameWithOwner": "me/a"}]
    assert listing.orgs == [] and listing.shared == 0


def test_fetch_org_repos_most_recently_pushed_first(fake_gh):
    fake_gh.route("orgs/w3c/repos?sort=pushed", [{"full_name": "w3c/a"}, {"name": "x"}])
    assert [r.name for r in gh_data.fetch_org_repos("w3c", 10)] == ["w3c/a"]


def test_fetch_shared_repos_skips_your_organizations(fake_gh):
    fake_gh.route("affiliation=collaborator", [
        {"full_name": "Mine/a", "owner": {"login": "Mine"}},
        {"full_name": "friend/b", "owner": {"login": "friend"}},
    ])
    assert [r.name for r in gh_data.fetch_shared_repos(10, ["mine"])] == ["friend/b"]


@pytest.mark.parametrize("reply, message", [
    ({"data": None, "errors": [{"message": "Bad credentials"}]}, "Bad credentials"),
    # An expired token gets a REST-style 401 body, with no data or errors
    ({"message": "Bad credentials", "status": "401"},
     "Bad credentials. Run gh auth login to sign in again."),
    ({"data": {}}, "Couldn't list your repositories"),
    ({"errors": ["not a dict"]}, "Couldn't list your repositories"),
])
def test_list_repos_with_nothing_back_is_an_error(monkeypatch, reply, message):
    monkeypatch.setattr(gh_data, "_graphql", lambda q: reply)
    with pytest.raises(GhError, match=message):
        gh_data.list_repos()


# ── Labels ─────────────────────────────────────────────────────────────


def test_parse_labels():
    raw = json.dumps([{"name": "bug", "color": "#d73a4a", "description": None, "isDefault": 1}])
    [label] = gh_data._parse_labels(raw)
    assert label.color == "d73a4a"
    assert label.description == ""
    assert label.is_default is True
    assert label.to_row(["color", "default"]) == {"color": "#d73a4a", "default": "Yes"}


def test_parse_labels_rejects_non_list():
    assert gh_data._parse_labels('{"name": "x"}') == []


def test_fetch_labels_sorted_by_name(fake_gh):
    fake_gh.route("label list", [{"name": "a"}])
    gh_data.fetch_labels("o/r")
    [call] = fake_gh.called_with("label list")
    assert call[call.index("--sort") + 1] == "name"


def test_fetch_labels_no_labels_is_empty(fake_gh):
    fake_gh.route("label list", GhError("no labels found in o/r"))
    assert gh_data.fetch_labels("o/r") == []


def test_fetch_labels_other_errors_propagate(fake_gh):
    fake_gh.route("label list", GhError("HTTP 500"))
    with pytest.raises(GhError):
        gh_data.fetch_labels("o/r")


def test_create_label_strips_hash_and_omits_blanks(fake_gh):
    fake_gh.route("label create", "")
    gh_data.create_label("o/r", "needs info", color="#FFAA00")
    [call] = fake_gh.called_with("label create")
    assert call[2] == "needs info"
    assert call[call.index("--color") + 1] == "FFAA00"
    assert "--description" not in call


def test_delete_label_does_not_prompt(fake_gh):
    fake_gh.route("label delete", "")
    gh_data.delete_label("o/r", "bug")
    [call] = fake_gh.called_with("label delete")
    assert "--yes" in call


# ── The gh runner itself ───────────────────────────────────────────────


def test_run_gh_missing_cli_explains_install(monkeypatch, real_run_gh):
    def missing(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(gh_data.subprocess, "run", missing)
    with pytest.raises(GhError, match="cli.github.com"):
        real_run_gh(["status"])


def test_run_gh_failure_carries_stderr(monkeypatch, real_run_gh):
    def fail(cmd, **k):
        raise gh_data.subprocess.CalledProcessError(1, cmd, stderr="  HTTP 404  \n")

    monkeypatch.setattr(gh_data.subprocess, "run", fail)
    with pytest.raises(GhError, match="^HTTP 404$"):
        real_run_gh(["api", "x"])


def test_run_gh_failure_without_stderr_names_command(monkeypatch, real_run_gh):
    def fail(cmd, **k):
        raise gh_data.subprocess.CalledProcessError(1, cmd, stderr="")

    monkeypatch.setattr(gh_data.subprocess, "run", fail)
    with pytest.raises(GhError, match="`gh api x` failed"):
        real_run_gh(["api", "x"])


def test_find_gh_honours_override(monkeypatch):
    monkeypatch.setenv("GHMANAGE_GH_PATH", r"C:\tools\gh.exe")
    assert gh_data._find_gh() == r"C:\tools\gh.exe"


def test_find_gh_falls_back_to_bare_name(monkeypatch):
    monkeypatch.setattr(gh_data.shutil, "which", lambda *a, **k: None)
    assert gh_data._find_gh() == "gh"


# ── New issue ───────────────────────────────────────────────────────────


def test_create_issue_sends_the_body_on_stdin(fake_gh, monkeypatch):
    monkeypatch.setattr(gh_data, "parent_repo", lambda r: None)
    fake_gh.route("issue create", "Creating issue in o/r\n\nhttps://github.com/o/r/issues/42\n")
    number, url = gh_data.create_issue("o/r", "Title", "Body\nline two")
    assert (number, url) == (42, "https://github.com/o/r/issues/42")
    call = fake_gh.called_with("issue create")[0]
    assert call[call.index("--title") + 1] == "Title"
    assert "--body-file" in call and call[call.index("--body-file") + 1] == "-"
    assert call[call.index("--repo") + 1] == "o/r"
    assert fake_gh.stdin[-1] == "Body\nline two"


def test_create_issue_on_a_fork_goes_upstream(fake_gh, monkeypatch):
    monkeypatch.setattr(gh_data, "parent_repo", lambda r: "up/r")
    fake_gh.route("issue create", "https://github.com/up/r/issues/7\n")
    assert gh_data.create_issue("me/r", "T", "")[0] == 7
    call = fake_gh.called_with("issue create")[0]
    assert call[call.index("--repo") + 1] == "up/r"


def test_create_issue_without_an_address_is_an_error(fake_gh, monkeypatch):
    monkeypatch.setattr(gh_data, "parent_repo", lambda r: None)
    fake_gh.route("issue create", "something odd\n")
    with pytest.raises(gh_data.GhError):
        gh_data.create_issue("o/r", "T", "")
