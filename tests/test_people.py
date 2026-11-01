"""People (#25): People I Follow and My Followers in the repository list,
anyone's profile with View User, and from a person their repositories,
stars, followers, who they follow and what they've done lately; Follow and
Unfollow."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

import gh_data
import peopleview
from gh_data import GhError, MissingScope, Person


def _user(login="alice", **extra):
    node = {
        "__typename": "User", "login": login, "url": f"https://github.com/{login}",
        "name": "Alice Smith", "createdAt": "2018-10-09T17:47:39Z", "bio": "Builds\nthings",
        "company": "Acme", "location": "Madison", "websiteUrl": "https://a.example",
        "twitterUsername": "al", "pronouns": "she/her", "isViewer": False,
        "viewerIsFollowing": True, "isFollowingViewer": False,
        "status": {"message": "Away"}, "followers": {"totalCount": 1238},
        "following": {"totalCount": 94}, "publicRepos": {"totalCount": 12},
    }
    node.update(extra)
    return node


class FakeGraphql:
    """Stands in for gh_data._graphql: replies in turn, and keeps what was asked."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, query, variables=None):
        self.calls.append((query, variables))
        return self.replies.pop(0)


def _page(kind, nodes, next_cursor=None, owner="viewer"):
    return {"data": {owner: {kind: {
        "pageInfo": {"hasNextPage": bool(next_cursor), "endCursor": next_cursor},
        "nodes": nodes}}}}


# ── Reading people ──────────────────────────────────────────────────────


def test_your_people_are_read_a_page_at_a_time(monkeypatch):
    first = [_user(f"u{i}") for i in range(100)]
    fake = FakeGraphql(_page("following", first, "c1"),
                       _page("following", [_user("b")]))
    monkeypatch.setattr(gh_data, "_graphql", fake)
    people = gh_data.fetch_people("following", limit=150)
    assert len(people) == 101 and people[-1].login == "b"
    (q1, v1), (q2, v2) = fake.calls
    assert "viewer { following(first: $first, after: $after)" in q1
    assert v1 == {"first": 100, "after": None} and v2 == {"first": 50, "after": "c1"}
    # A list asks no costly per-person counts: stars wait for the profile.
    assert "starredRepositories" not in q1


def test_someones_followers_pass_the_login_as_a_variable(monkeypatch):
    fake = FakeGraphql(_page("followers", [_user("b")], owner="user"))
    monkeypatch.setattr(gh_data, "_graphql", fake)
    gh_data.fetch_people("followers", "o'brien", 5)
    query, variables = fake.calls[0]
    assert "o'brien" not in query and variables["login"] == "o'brien"
    assert "user(login: $login) { followers(" in query


def test_no_such_user_is_said_plainly(monkeypatch):
    reply = {"data": {"user": None}, "errors": [
        {"type": "NOT_FOUND", "message": "Could not resolve to a User with the login of 'zz'."}]}
    monkeypatch.setattr(gh_data, "_graphql", FakeGraphql(reply))
    with pytest.raises(GhError, match="There's no GitHub user called zz."):
        gh_data.fetch_people("followers", "zz")


def test_other_failures_keep_githubs_words(monkeypatch):
    reply = {"errors": [{"message": "API rate limit exceeded"}]}
    monkeypatch.setattr(gh_data, "_graphql", FakeGraphql(reply))
    with pytest.raises(GhError, match="rate limit"):
        gh_data.fetch_people("following")


def test_a_row_reads_whole():
    p = gh_data._parse_person(_user())
    assert p.title == "alice (Alice Smith)" and p.connection == "you follow them"
    assert p.to_row(gh_data.PEOPLE_COLUMNS) == {
        "login": "alice", "name": "Alice Smith", "bio": "Builds things",
        "followers": "1,238", "following": "94", "repositories": "12",
        "connection": "you follow them", "company": "Acme", "location": "Madison",
        "joined": "2018-10-09"}
    assert not p.full and p.starred is None and p.repos_public


@pytest.mark.parametrize("you, they, said", [
    (True, True, "you follow each other"), (True, False, "you follow them"),
    (False, True, "follows you"), (False, False, ""),
])
def test_connection(you, they, said):
    p = gh_data._parse_person(_user(viewerIsFollowing=you, isFollowingViewer=they))
    assert p.connection == said


def test_a_profile_has_the_costlier_counts(monkeypatch):
    node = _user(isViewer=True, starredRepositories={"totalCount": 6},
                 allRepos={"totalCount": 20})
    fake = FakeGraphql({"data": {"repositoryOwner": node}})
    monkeypatch.setattr(gh_data, "_graphql", fake)
    p = gh_data.fetch_person("alice")
    assert p.full and p.starred == 6 and p.is_viewer and p.connection == "you"
    assert p.repos == 20 and not p.repos_public   # yours, private ones counted
    assert fake.calls[0][1] == {"login": "alice"}


def test_an_organization_is_a_profile_without_followers(monkeypatch):
    org = {"__typename": "Organization", "login": "nvaccess", "url": "u", "name": "NV Access",
           "description": "Empowering lives", "location": "Australia",
           "email": "info@nvaccess.org", "publicRepos": {"totalCount": 36}}
    monkeypatch.setattr(gh_data, "_graphql", FakeGraphql({"data": {"repositoryOwner": org}}))
    p = gh_data.fetch_person("nvaccess")
    assert p.is_org and p.bio == "Empowering lives" and p.repos == 36
    assert p.followers is None and p.you_follow is None and p.connection == ""


def test_nobody_by_that_name_is_none(monkeypatch):
    monkeypatch.setattr(gh_data, "_graphql",
                        FakeGraphql({"data": {"repositoryOwner": None}}))
    assert gh_data.fetch_person("zz") is None


def test_counts_for_the_entries(monkeypatch):
    monkeypatch.setattr(gh_data, "_graphql", FakeGraphql(
        {"data": {"viewer": {"following": {"totalCount": 4}}}},
        {"data": {"viewer": {"followers": {"totalCount": 28}}}}))
    assert gh_data.count_following() == 4 and gh_data.count_followers() == 28


def test_repositories_and_stars(fake_gh):
    repo = {"full_name": "alice/x", "html_url": "u"}
    fake_gh.route("users/alice/repos", [repo])
    fake_gh.route("user/repos", [repo, repo])
    fake_gh.route("users/alice/starred", [repo])
    assert len(gh_data.fetch_user_repos("alice")) == 1
    assert len(gh_data.fetch_user_repos("alice", viewer=True)) == 2
    assert gh_data.fetch_user_starred("alice")[0].name == "alice/x"
    assert fake_gh.calls[0][1].startswith("users/alice/repos?type=owner&sort=pushed")
    assert fake_gh.calls[1][1].startswith("user/repos?affiliation=owner&sort=pushed")


def test_someones_activity_is_their_public_events(fake_gh):
    fake_gh.route("users/alice/events/public", [])
    fake_gh.route("orgs/alice/events", GhError("HTTP 404"))
    events, more = gh_data.fetch_activity(100, of="alice")
    assert fake_gh.calls[0] == ["api", "users/alice/events/public?per_page=100&page=1"]
    assert events == [] and not more


def test_an_organizations_activity_is_its_own_events(fake_gh):
    event = {"id": "1", "type": "WatchEvent", "actor": {"login": "bob"},
             "repo": {"name": "nvaccess/nvda"}, "payload": {"action": "started"},
             "created_at": "2026-10-01T00:00:00Z"}
    fake_gh.route("users/nvaccess/events/public", [])
    fake_gh.route("orgs/nvaccess/events?per_page=100&page=1", [event])
    fake_gh.route("orgs/nvaccess/events?per_page=100&page=2", [])
    events, more = gh_data.fetch_activity(200, of="nvaccess")
    assert [e.actor for e in events] == ["bob"] and not more
    assert fake_gh.calls[-1] == ["api", "orgs/nvaccess/events?per_page=100&page=2"]


# ── Following ──────────────────────────────────────────────────────────


def test_follow_and_unfollow(fake_gh):
    fake_gh.route("user/following/alice", "")
    gh_data.follow_user("alice")
    gh_data.unfollow_user("alice")
    assert fake_gh.calls == [["api", "-X", "PUT", "user/following/alice"],
                             ["api", "-X", "DELETE", "user/following/alice"]]


@pytest.mark.parametrize("text", [
    "gh: Not Found (HTTP 404)",
    'This API operation needs the "user:follow" scope. To request it, run: gh auth refresh',
])
def test_without_the_permission_it_says_how_to_add_it(monkeypatch, text):
    def boom(args, **kw):
        raise GhError(text)
    monkeypatch.setattr(gh_data, "_run_gh", boom)
    with pytest.raises(MissingScope) as info:
        gh_data.follow_user("alice")
    assert info.value.scope == "user:follow"
    assert "gh auth refresh -h github.com -s user:follow" in str(info.value)


def test_other_follow_failures_pass_through(monkeypatch):
    def boom(args, **kw):
        raise GhError("HTTP 502")
    monkeypatch.setattr(gh_data, "_run_gh", boom)
    with pytest.raises(GhError, match="502") as info:
        gh_data.unfollow_user("alice")
    assert not isinstance(info.value, MissingScope)


# ── As text ────────────────────────────────────────────────────────────


def test_a_profile_reads_line_by_line():
    p = gh_data._parse_person(_user(starredRepositories={"totalCount": 6}))
    p.starred = 6
    lines = peopleview.person_details(p).split("\n")
    assert lines[:4] == ["User: alice (Alice Smith)", "Pronouns: she/her", "Status: Away",
                         "You follow them."]
    for line in ("Company: Acme", "Followers: 1,238", "Following: 94",
                 "Repositories: 12 public", "Starred: 6", "Joined: 2018-10-09",
                 "X (Twitter): @al"):
        assert line in lines
    assert lines[lines.index("URL:") + 1] == "https://github.com/alice"
    assert lines[-2:] == ["Builds", "things"]


def test_an_organization_reads_as_one():
    p = Person("nvaccess", name="NV Access", is_org=True, repos=36, url="u")
    text = peopleview.person_details(p)
    assert text.startswith("Organization: nvaccess (NV Access)")
    assert "Followers" not in text and "follow" not in text.lower()
    assert text.endswith("(no description)")


@pytest.mark.parametrize("kind, login, lower, said", [
    ("following", "", False, "People I Follow"),
    ("followers", "", False, "My Followers"),
    ("following", "", True, "people you follow"),
    ("followers", "", True, "your followers"),
    ("followers", "alice", False, "alice's Followers"),
    ("followers", "james", True, "james' followers"),
    ("following", "alice", False, "People alice Follows"),
    ("user", "Alice", True, "Alice"),
])
def test_list_names(kind, login, lower, said):
    assert peopleview.people_label(kind, login, lower=lower) == said


def test_other_names():
    assert peopleview.repos_label("starred", "alice") == "alice's Starred Repositories"
    assert peopleview.repos_label("repos", "alice", lower=True) == "alice's repositories"
    assert peopleview.activity_label("Bob") == "Bob's Activity"


def test_status_lines():
    two = [Person("a"), Person("b")]
    assert peopleview.status_message("following", "", two, 100) == "People I Follow — 2 people."
    assert peopleview.status_message("followers", "x", two, 2).endswith("Ctrl++ loads more.")
    assert peopleview.status_message("followers", "", [], 100) == (
        "My Followers — Nobody follows you yet.")
    assert peopleview.status_message("user", "zz", [], 100) == (
        "There's no GitHub user called zz.")
    assert peopleview.status_message("user", "a", [Person("a", name="A")], 100) == "User a (A)."


# ── Who View User offers ───────────────────────────────────────────────


def test_an_issue_offers_its_author_then_assignees_then_commenters():
    item = gh_data.Item(1, "T", "open", "u", False, author="alice", assignees=["bob", "Alice"],
                        comment_list=[{"author": "carol"}, {"author": "ghost"},
                                      {"author": "bob"}], repo="org/r")
    assert peopleview.people_of(item) == [
        ("alice", "author"), ("bob", "assigned"), ("carol", "commented"), ("org", "owner")]


def test_display_names_are_not_offered_and_the_repository_owner_is():
    commit = gh_data.Commit("a" * 40, "aaaaaaa", "m", "Kelly Ford", "")
    assert peopleview.people_of(commit, "kellylford/GHManage") == [("kellylford", "owner")]


def test_events_repositories_discussions_and_contributors():
    ev = gh_data.ActivityEvent("WatchEvent", "dave", "o/r", "starred")
    assert peopleview.people_of(ev)[0] == ("dave", "")
    assert peopleview.people_of(gh_data.RepoEntry("nvaccess/nvda")) == [("nvaccess", "owner")]
    reply = gh_data.DiscussionComment("frank", "b")
    comment = gh_data.DiscussionComment("erin", "b", replies=[reply])
    disc = gh_data.Discussion(3, "T", author="zed", comments=[comment])
    assert peopleview.people_of(disc) == [
        ("zed", "author"), ("erin", "commented"), ("frank", "replied")]
    row = gh_data.InsightRow("Contributor", "kelly", 3)
    assert ("kelly", "contributor") in peopleview.people_of(row)


@pytest.mark.parametrize("text, ok", [
    ("alice", True), ("a-b-c", True), ("a" * 39, True), ("-a", False), ("a--b", False),
    ("a b", False), ("", False), ("a" * 40, False), ("Kelly Ford", False),
])
def test_is_login(text, ok):
    assert peopleview.is_login(text) is ok


# ── In the window ──────────────────────────────────────────────────────

if os.environ.get("CI"):
    import wx  # noqa: F401
else:
    pytest.importorskip("wx")

import announce  # noqa: E402
import ghviewer  # noqa: E402

Frame = ghviewer.GhViewerFrame
V = ghviewer


def test_the_views_are_wired_up():
    for view in (V.VIEW_PEOPLE, V.VIEW_USER_REPOS):
        assert view in V.REPOLESS_VIEWS and view in V.FEED_VIEWS
        assert view in Frame._VIEW_LABELS and view in Frame._COPY_IDENT_NOUNS
    assert V.VIEW_COLUMNS[V.VIEW_PEOPLE] is V.PEOPLE_SET
    assert V.VIEW_USER_REPOS in V.REPO_LIST_VIEWS
    assert V.enter_label(V.VIEW_PEOPLE) == "List Repositories"
    assert (V.FOLLOWING_ENTRY, "People I Follow") in V.CATEGORY_ENTRIES
    assert (V.FOLLOWERS_ENTRY, "My Followers") in V.CATEGORY_ENTRIES
    assert V.COUNTED_ENTRIES[V.FOLLOWING_ENTRY] is V.count_following
    assert V.ENTRY_VIEWS[V.FOLLOWERS_ENTRY] == V.VIEW_PEOPLE
    headings = [c.heading for c in V.PEOPLE_SET.defs(list(V.PEOPLE_SET.defaults))]
    assert headings == ["User", "Name", "Bio", "Followers", "Following", "Repositories"]


def test_login_from_choice():
    assert V.login_from_choice("alice — author") == "alice"
    assert V.login_from_choice(" @bob ") == "bob"


@pytest.mark.parametrize("attrs, view, label, entry", [
    ({"_people": ("following", "")}, V.VIEW_PEOPLE, "People I Follow", V.FOLLOWING_ENTRY),
    ({"_people": ("followers", "")}, V.VIEW_PEOPLE, "My Followers", V.FOLLOWERS_ENTRY),
    ({"_people": ("followers", "bob")}, V.VIEW_PEOPLE, "bob's Followers", None),
    ({"_user_repos": ("starred", "bob")}, V.VIEW_USER_REPOS, "bob's Starred Repositories",
     None),
    ({"_activity_of": "bob"}, V.VIEW_ACTIVITY, "bob's Activity", None),
    ({"_activity_of": ""}, V.VIEW_ACTIVITY, "Activity", V.ACTIVITY_ENTRY),
])
def test_names_and_entries(attrs, view, label, entry):
    f = SimpleNamespace(view_mode=view, **attrs)
    assert Frame._view_label(f, view) == label
    assert Frame._view_entry(f, view) == entry


class FakeText:
    def __init__(self) -> None:
        self.value = ""
        self.insertion = 0

    def SetValue(self, v): self.value = v
    def GetValue(self): return self.value
    def Clear(self): self.value = ""
    def GetInsertionPoint(self): return self.insertion
    def SetInsertionPoint(self, p): self.insertion = p
    def GetLastPosition(self): return len(self.value)


def _frame(**attrs):
    f = SimpleNamespace(
        details_text=FakeText(), items=[], git_items=[], repo=None, current_limit=100,
        page_size=100, view_mode=V.VIEW_PEOPLE, status=[], told=[], events=[],
        _people=("following", ""), _user_repos=("repos", ""), _activity_of="",
        _people_trail=[], _detail_gen=1, _category_counts={}, _comment_positions=[],
        _current_comment=-1, filter_text="", _read_profile=False,
        _follow_count={}, _follow_pending=set(), _fetch_token=1, _landed_token=1,
        _fetch_is_current=lambda token: token == 1,
        _populate_filtered_list=lambda items, use_favorite_prefix=False: list(items),
        _update_title=lambda: None, _focus_list=lambda row: None,
        _refresh_category_labels=lambda: None, _update_actions_menu=lambda: None,
        _update_menu_checks=lambda: None, _restore_repo_selection=lambda prev: None,
    )
    f._set_view_status = lambda message, keys="": f.status.append((message, keys))
    f._tell = f.told.append
    f._announce = f.events.append
    f._view_entry = lambda view: Frame._view_entry(f, view)
    f._view_label = lambda view, lower=False: Frame._view_label(f, view, lower)
    f._shown = []
    f._row_of = lambda item: Frame._row_of(f, item)
    f._focused = None
    f._focused_item = lambda: f._focused
    f._fetch_person_later = lambda person, gen: f.events.append(("fetch", person.login))
    f._in_people = lambda: Frame._in_people(f)
    f._redraw_profile = lambda person: Frame._redraw_profile(f, person)
    f.FindFocus = lambda: None
    for k, v in attrs.items():
        setattr(f, k, v)
    return f


def test_your_people_are_listed_and_counted(monkeypatch):
    later = []
    monkeypatch.setattr(V.wx, "CallLater", lambda ms, fn, *a: later.append((fn, a)))
    f = _frame()
    people = [Person("a"), Person("b")]
    Frame._on_people_loaded(f, 2, people)
    assert f.git_items == []   # a load the user moved on from
    Frame._on_people_loaded(f, 1, people)
    assert f.git_items == people and f._category_counts == {V.FOLLOWING_ENTRY: 2}
    assert f.status[-1] == (
        "People I Follow — 2 people.",
        "Enter=list repositories  Ctrl+O=open on GitHub  O=followers  W=following  "
        "S=starred  A=activity  Insert=follow  Delete=unfollow  Ctrl++=view more  "
        "R=refresh  Ctrl+F=filter")


def test_someone_elses_list_counts_no_entry(monkeypatch):
    monkeypatch.setattr(V.wx, "CallLater", lambda *a: None)
    f = _frame(_people=("followers", "bob"))
    Frame._on_people_loaded(f, 1, [Person("a")])
    assert f._category_counts == {}


def test_nobody_is_said(monkeypatch):
    spoken = []
    monkeypatch.setattr(announce, "announce", lambda text, *a, **k: spoken.append(text))
    f = _frame(_people=("followers", ""))
    Frame._on_people_loaded(f, 1, [])
    assert spoken == ["My Followers — Nobody follows you yet."]
    assert f.details_text.value == "Nobody follows you yet."
    assert f.status[-1][1] == "R=refresh  Ctrl+F=filter"


def test_view_user_goes_into_the_profile(monkeypatch):
    later = []
    monkeypatch.setattr(V.wx, "CallLater", lambda ms, fn, *a: later.append((fn, a)))
    f = _frame(_people=("user", "alice"), _read_profile=True)
    f._if_still_current = object()
    f._read_item = object()
    Frame._on_people_loaded(f, 1, [Person("alice", full=True)])
    assert (f._if_still_current, (1, f._read_item)) in later
    assert f._read_profile is False
    assert f.status[-1][0] == "User alice."
    assert "view more" not in f.status[-1][1]


def test_selecting_a_row_reads_the_rest_of_the_profile_later():
    p = Person("alice", url="u")
    f = _frame(git_items=[p])
    Frame._show_person_details(f, 0)
    assert f.details_text.value.startswith("User: alice")
    assert f.events == [("fetch", "alice")]
    p.full = True
    f.events.clear()
    Frame._show_person_details(f, 0)
    assert f.events == []


def test_the_rest_arrives_and_is_kept():
    p = Person("alice", url="u", repos=3)
    got = Person("alice", url="u", repos=3, starred=9, full=True, follows_you=True)
    f = _frame(git_items=[p])
    f._shows = lambda view, item, gen: True
    Frame._on_person_fetched(f, 1, p, got)
    assert p.full and p.starred == 9 and p.follows_you
    assert "Starred: 9" in f.details_text.value


# ── Going in and coming back ────────────────────────────────────────────


class FakeList:
    def __init__(self, row=0):
        self.row = row

    def GetFirstSelected(self):
        return self.row


def _trail_frame(**attrs):
    f = _frame(list_ctrl=FakeList(1), _return_to=None, _return_view=V.VIEW_ISSUES,
               _activity_more=None, **attrs)
    f._view_source = lambda: f.git_items
    f._push_people = lambda: Frame._push_people(f)
    f._people_snapshot = lambda: Frame._people_snapshot(f)
    f._selected_person = lambda: Frame._selected_person(f)
    f._PEOPLE_TRAIL_MAX = 50
    f._VIEW_CONTEXT = Frame._VIEW_CONTEXT
    f.loads = []
    f._load_items = lambda: f.loads.append(f._people)
    f.switched = []
    f._switch_view = lambda view, load=True: (f.switched.append(view),
                                              setattr(f, "view_mode", view))
    f._show_people_view = lambda view: Frame._show_people_view(f, view)
    return f


def test_o_lists_their_followers_and_backspace_comes_back(monkeypatch):
    monkeypatch.setattr(V.wx, "CallLater", lambda *a: None)
    alice, bob = Person("alice"), Person("bob")
    f = _trail_frame(git_items=[alice, bob])
    f._shown = [alice, bob]
    f._focused = bob
    Frame._person_people(f, "followers")
    assert f._people == ("followers", "bob") and f.loads == [("followers", "bob")]
    assert len(f._people_trail) == 1
    assert Frame._back_label(f) == "Back to People I Follow"
    assert Frame._back_label(f, lower=True) == "back to people you follow"
    # Back: the list as it was, drawn again without a fetch, on bob.
    landed = []
    f._begin_fetch = lambda: 1
    f._on_people_loaded = lambda token, items, count, focus: landed.append((items, focus))
    f._on_repo_list_loaded = f._on_activity_loaded = None
    f._snapshot_label = lambda snap, lower=False: Frame._snapshot_label(f, snap, lower)
    Frame._people_back(f)
    assert landed == [([alice, bob], bob)] and f._people == ("following", "")
    assert f._people_trail == [] and f.events[-1] == "Back to people you follow"


def test_enter_lists_their_repositories_and_a_their_activity():
    bob = Person("bob")
    f = _trail_frame(git_items=[bob])
    f._focused = bob
    Frame._person_repos(f, "repos")
    assert f._user_repos == ("repos", "bob") and f.switched == [V.VIEW_USER_REPOS]
    f.view_mode = V.VIEW_PEOPLE
    Frame._person_activity(f)
    assert f._activity_of == "bob" and f.switched[-1] == V.VIEW_ACTIVITY
    assert len(f._people_trail) == 2
    assert Frame._back_label(f) == "Back to People I Follow"


def test_organizations_are_refused_what_they_dont_have():
    org = Person("nvaccess", is_org=True)
    f = _trail_frame(git_items=[org])
    f._focused = org
    Frame._person_people(f, "following")
    Frame._person_repos(f, "starred")
    assert f._people_trail == [] and len(f.told) == 2
    assert "organization" in f.told[0]


def test_the_trail_is_kept_to_a_bounded_length_keeping_the_way_out():
    f = _trail_frame()
    Frame._push_people(f)
    first = f._people_trail[0]
    for _ in range(60):
        Frame._push_people(f)
    assert len(f._people_trail) == 50 and f._people_trail[0] is first


def test_backspace_from_your_own_list_goes_nowhere():
    f = _trail_frame()
    assert Frame._back_label(f) is None


def test_view_user_from_issues_returns_to_the_issue(monkeypatch):
    issue = gh_data.Item(7, "T", "open", "https://github.com/o/r/issues/7", False)
    f = _trail_frame(view_mode=V.VIEW_ISSUES, repo="o/r", items=[issue], label_filter="bug",
                     commit_branch="", artifacts_run=None, jobs_run=None, assets_release=None,
                     _files_of=None, _files_back=None, _history_of=None, _history_back=None,
                     milestone_filter=None, pages_site=None, _org="")
    f._view_source = lambda: f.items
    f._focused = issue
    Frame._view_user(f, "alice")
    assert f._people == ("user", "alice") and f._read_profile
    assert f.switched == [V.VIEW_PEOPLE]
    # Back: Issues again, still filtered by its label, landing on #7.
    f.label_filter = ""
    pending = []
    f._set_pending_target = lambda view, kind, ref: pending.append((view, kind, ref))
    f._begin_fetch = lambda: 1
    f.loads.clear()
    f._load_items = lambda: f.loads.append(f.view_mode)
    f._load_favorites_view = None
    f._restore_view = lambda snap: Frame._restore_view(f, snap)
    f._snapshot_label = lambda snap, lower=False: Frame._snapshot_label(f, snap, lower)
    Frame._people_back(f)
    assert f.view_mode == V.VIEW_ISSUES and f.repo == "o/r" and f.label_filter == "bug"
    assert f.loads == [V.VIEW_ISSUES] and f._url_fallback_row == 1
    assert pending == [(V.VIEW_ISSUES, "url", issue.url)]
    assert f.events[-1] == "Back to issues"


def test_a_url_target_lands_silently():
    issue = gh_data.Item(7, "T", "open", "https://x/7", False)
    f = SimpleNamespace(_pending_target=(3, V.VIEW_ISSUES, "url", "https://x/7"),
                        view_mode=V.VIEW_ISSUES, _shown=[gh_data.Item(1, "", "", "u", False),
                                                         issue])
    f._row_of = lambda item: Frame._row_of(f, item)
    assert Frame._take_pending_row(f, f._shown, 3) == 1


# ── Follow and Unfollow ────────────────────────────────────────────────


def test_follow_refuses_what_it_cant_do():
    f = _trail_frame()
    for person, said in [
        (Person("me", is_viewer=True), "That's you."),
        (Person("org", is_org=True), "org is an organization; GHManage follows people, "
                                     "not organizations."),
        (Person("a", you_follow=True), "You already follow a."),
    ]:
        f._focused = person
        Frame._follow_person(f, True)
        assert f.told[-1] == said
    f._focused = Person("b", you_follow=False)
    Frame._follow_person(f, False)
    assert f.told[-1] == "You don't follow b."


def test_following_updates_the_row_and_the_count():
    bob = Person("bob", you_follow=False, followers=10)
    f = _trail_frame(git_items=[bob], _category_counts={V.FOLLOWING_ENTRY: 4})
    f._shown = [bob]
    redrawn = []
    f._redraw_row = lambda row, item: redrawn.append((row, item))
    f._redraw_profile = lambda person: redrawn.append(("details", person.login))
    f.list_ctrl = FakeList(0)
    Frame._on_follow_done(f, bob, True, None)
    assert bob.you_follow and bob.followers == 11
    assert f._category_counts[V.FOLLOWING_ENTRY] == 5
    assert redrawn == [(0, bob), ("details", "bob")]
    assert f.told[-1] == "Now following bob."
    Frame._on_follow_done(f, bob, False, None)
    assert not bob.you_follow and bob.followers == 10 and f.told[-1] == "Unfollowed bob."


def test_missing_permission_is_shown_with_the_command(monkeypatch):
    shown = []
    monkeypatch.setattr(V.wx, "MessageBox", lambda text, *a, **k: shown.append(text))
    f = _trail_frame()
    Frame._on_follow_done(f, Person("bob"), True, MissingScope("user:follow"))
    assert "gh auth refresh -h github.com -s user:follow" in shown[0]
    assert 'needs gh\'s "user:follow" permission' in f.events[-1]


@pytest.mark.parametrize("people, keys", [
    ([], ""),
    ([Person("org", is_org=True)], "A=activity"),
    ([Person("me", is_viewer=True)], "O=followers  W=following  S=starred  A=activity"),
    ([Person("a")], "O=followers  W=following  S=starred  A=activity  Insert=follow  "
                    "Delete=unfollow"),
])
def test_the_status_bar_names_only_keys_that_work(people, keys):
    assert peopleview.person_keys(people) == keys


def test_drilled_in_the_repo_list_keeps_the_entry_you_started_from():
    root = {"view": V.VIEW_PEOPLE, "people": ("followers", ""), "user_repos": ("repos", ""),
            "activity_of": "", "repo": None}
    f = SimpleNamespace(view_mode=V.VIEW_USER_REPOS, _user_repos=("repos", "bob"),
                        _people=("followers", ""), _activity_of="", _people_trail=[root],
                        repo=None)
    f._view_entry = lambda view: Frame._view_entry(f, view)
    assert Frame._current_entry(f) == V.FOLLOWERS_ENTRY
    f._people_trail = [dict(root, view=V.VIEW_ISSUES, people=("following", ""), repo="o/r")]
    assert Frame._current_entry(f) == "o/r"


# ── A repository's stargazers, watchers and forks (#31) ────────────────


def test_a_repositorys_stargazers_pass_owner_and_name(monkeypatch):
    fake = FakeGraphql(_page("stargazers", [_user("s")], owner="repository"))
    monkeypatch.setattr(gh_data, "_graphql", fake)
    [p] = gh_data.fetch_people("stargazers", "nvaccess/nvda", 5)
    query, variables = fake.calls[0]
    assert "repository(owner: $owner, name: $name) { stargazers(" in query
    assert (variables["owner"], variables["name"]) == ("nvaccess", "nvda") and p.login == "s"


def test_no_such_repository_is_said_plainly(monkeypatch):
    reply = {"data": {"repository": None}, "errors": [{"type": "NOT_FOUND", "message": "x"}]}
    monkeypatch.setattr(gh_data, "_graphql", FakeGraphql(reply))
    with pytest.raises(GhError, match="There's no repository called o/zz that you can see."):
        gh_data.fetch_people("watchers", "o/zz")


def test_forks_newest_first(fake_gh):
    fake_gh.route("repos/o/r/forks", [{"full_name": "x/r", "fork": True}])
    [fork] = gh_data.fetch_repo_forks("o/r")
    assert fork.name == "x/r" and fork.fork
    assert fake_gh.calls[0][1].startswith("repos/o/r/forks?sort=newest")


def test_repository_people_names():
    assert peopleview.people_label("stargazers", "o/r") == "Stargazers of o/r"
    assert peopleview.people_label("watchers", "o/r", lower=True) == "watchers of o/r"
    assert peopleview.repos_label("forks", "o/r") == "Forks of o/r"
    assert peopleview.empty_text("stargazers", "o/r") == "Nobody has starred o/r."
    assert peopleview.empty_text("watchers", "o/r") == "Nobody watches o/r."


def test_stargazers_and_forks_of_the_repository_in_front(monkeypatch):
    f = _trail_frame(view_mode=V.VIEW_ISSUES, repo="o/r")
    f._repo_in_front = lambda: "o/r"
    Frame._repo_people(f, "stargazers")
    assert f._people == ("stargazers", "o/r") and f.switched == [V.VIEW_PEOPLE]
    assert Frame._back_label(f) == "Back to Issues"
    Frame._repo_people(f, "forks")
    assert f._user_repos == ("forks", "o/r") and f.switched[-1] == V.VIEW_USER_REPOS
    assert Frame._back_label(f) == "Back to Stargazers of o/r"
    assert Frame._view_label(f, V.VIEW_USER_REPOS) == "Forks of o/r"


def test_stargazers_without_a_repository_say_so():
    f = _trail_frame()
    f._repo_in_front = lambda: None
    Frame._repo_people(f, "watchers")
    assert f.told == ["Select a repository first."] and f._people_trail == []


def test_in_a_repositorys_stargazers_that_repository_is_in_front():
    f = SimpleNamespace(view_mode=V.VIEW_PEOPLE, _people=("stargazers", "o/r"), repo=None)
    f._pane_index = lambda window: 1
    f._current_focus = lambda: None
    f._focused_item = lambda: Person("alice")
    assert Frame._repo_in_front_from(f) == ("o/r", "row")
    f._people = ("followers", "")
    assert Frame._repo_in_front_from(f) == (None, "row")



# ── From the review ────────────────────────────────────────────────────


def test_a_step_saved_while_loading_is_reloaded_not_redrawn():
    f = _trail_frame(git_items=[gh_data.RepoEntry("o/r")], _fetch_token=5, _landed_token=4)
    snap = Frame._people_snapshot(f)
    assert snap["items"] is None
    f._landed_token = 5
    assert Frame._people_snapshot(f)["items"] == f.git_items


def test_a_people_step_saved_while_loading_reloads_on_backspace():
    f = _trail_frame()
    f._people_trail = [dict(Frame._people_snapshot(f), items=None, row=3)]
    f.view_mode = V.VIEW_PEOPLE
    f._people = ("user", "bob")
    restored = []
    f._restore_view = restored.append
    f._snapshot_label = lambda snap, lower=False: "people you follow"
    Frame._people_back(f)
    assert restored and restored[0]["row"] == 3 and f._people == ("following", "")


def test_from_outside_people_a_new_trail_starts():
    f = _trail_frame(view_mode=V.VIEW_STARRED)
    f._people_trail = [{"view": V.VIEW_PEOPLE, "stale": True}]
    Frame._push_people(f)
    assert len(f._people_trail) == 1 and "stale" not in f._people_trail[0]


def test_a_repository_opened_from_someones_repositories_keeps_the_trail():
    f = _trail_frame(view_mode=V.VIEW_ISSUES)
    f._return_to = (V.VIEW_USER_REPOS, [], False, None, 100)
    f._people_trail = [{"view": V.VIEW_PEOPLE}]
    Frame._push_people(f)
    assert len(f._people_trail) == 2


def test_empty_starred_forks_and_activity_are_spoken(monkeypatch):
    spoken = []
    monkeypatch.setattr(announce, "announce", lambda text, *a, **k: spoken.append(text))
    for kind, said in [("starred", "bob hasn't starred any repositories."),
                       ("forks", "o/r has no forks.")]:
        f = _frame(view_mode=V.VIEW_USER_REPOS, _user_repos=(kind, "o/r" if kind == "forks"
                                                              else "bob"))
        f._orgs = []
        Frame._on_repo_list_loaded(f, 1, [])
        assert spoken[-1].endswith(said)
    f = _frame(view_mode=V.VIEW_ACTIVITY, _activity_of="bob", _activity_more=None)
    Frame._on_activity_loaded(f, 1, [])
    assert spoken[-1] == "bob's Activity — nothing public in the last 90 days."


def test_a_one_word_commit_author_is_not_offered():
    commit = gh_data.Commit("a" * 40, "aaaaaaa", "m", "Kelly", "")
    assert peopleview.people_of(commit, "kellylford/GHManage") == [("kellylford", "owner")]


def test_insert_twice_sends_one_follow(monkeypatch):
    started = []
    monkeypatch.setattr(V.threading, "Thread",
                        lambda target, daemon: SimpleNamespace(start=lambda: started.append(1)))
    bob = Person("bob", you_follow=False)
    f = _trail_frame()
    f._focused = bob
    Frame._follow_person(f, True)
    Frame._follow_person(f, True)
    assert started == [1] and f.told[-1] == "Still following bob…"
    assert f._follow_count == {"bob": 1}


def test_a_profile_read_begun_before_a_follow_does_not_undo_it():
    bob = Person("bob", you_follow=True, followers=11)
    stale = Person("bob", you_follow=False, followers=10, starred=3, full=True)
    f = _frame(git_items=[bob], _follow_count={"bob": 1})
    f._shows = lambda view, item, gen: False
    Frame._on_person_fetched(f, 1, bob, stale, 0)
    assert bob.you_follow and bob.followers == 11 and bob.starred == 3


def test_a_url_target_that_misses_lands_on_the_saved_row():
    f = SimpleNamespace(_pending_target=(3, V.VIEW_ISSUES, "url", "https://x/7"),
                        view_mode=V.VIEW_ISSUES, _shown=[], _url_fallback_row=4)
    f._row_of = lambda item: -1
    assert Frame._take_pending_row(f, [], 3) == 4


def test_not_found_names_the_account_and_the_permission(monkeypatch):
    def boom(args, **kw):
        raise GhError("gh: Not Found (HTTP 404)")
    monkeypatch.setattr(gh_data, "_run_gh", boom)
    with pytest.raises(MissingScope) as info:
        gh_data.follow_user("gone")
    text = str(info.value)
    assert text.startswith("GitHub said Not Found for gone. If the account still exists, this")
    assert "gh auth refresh -h github.com -s user:follow" in text


def test_account_switch_forgets_the_old_accounts_people(monkeypatch):
    monkeypatch.setattr(V.wx, "CallLater", lambda *a: None)
    f = SimpleNamespace(_update_title=lambda: None, _announce=lambda m: None, _account_gen=0, _search=None, _search_total=0, repo="o/r",
                        _return_to=None, _pending_target=None, _issue_drafts={},
                        _category_counts={}, _people_trail=[{}], _people=("followers", "x"),
                        _user_repos=("starred", "x"), _activity_of="x",
                        view_mode=V.VIEW_NOTIFICATIONS, page_size=100, current_limit=100)
    f._load_repos = f._load_items = lambda: None
    Frame._on_account_switched(f, "other")
    assert f._people_trail == [] and f._people == ("following", "") and f._activity_of == ""
