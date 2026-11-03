"""Comparing two branches, tags or commits: what GitHub is asked, what is said,
and getting in and back out. The windows are in test_new_issue's style: no real
frame, the frame's methods run on a stand-in."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import compareview
import gh_data
from gh_data import Branch, ChangedFile, Commit, ComparePull, CompareResult, GhError, Tag

wx = pytest.importorskip("wx")

import ghviewer  # noqa: E402

Frame = ghviewer.GhViewerFrame


def _commit(sha: str, message: str = "m") -> Commit:
    return Commit(sha * 40, (sha * 40)[:8], message, "me", "2026-11-01", url=f"u/{sha}")


def _result(**kw) -> CompareResult:
    fields = dict(base="main", head="dev", loaded=True, url="https://github.com/o/r/compare/main...dev")
    fields.update(kw)
    return CompareResult(**fields)


FILE = ChangedFile("a.py", additions=3, deletions=1, patch="@@ -1 +1 @@\n-a\n+b")


# ── Asking GitHub ───────────────────────────────────────────────────────


def _rows(*shas):
    return [{"sha": s * 40, "message": f"c{s}", "author": "me", "date": "d", "url": f"u/{s}"}
            for s in shas]


def test_commits_come_newest_first_with_what_a_commit_row_needs(fake_gh):
    fake_gh.route("pulls?", [])
    # GitHub lists them oldest first.
    fake_gh.route("compare/main...dev", {"ahead": 2, "behind": 0, "url": "U",
                                         "commits": _rows("a", "b"), "files": []})
    r = gh_data.fetch_compare("o/r", "main", "dev")
    assert [c.message for c in r.commits] == ["cb", "ca"]
    assert r.commits[0].short_sha == "b" * 8 and r.commits[0].branches == ["dev"]
    assert (r.ahead_by, r.behind_by, r.url, r.loaded) == (2, 0, "U", True)


def test_behind_commits_are_read_the_other_way_round_only_when_there_are_any(fake_gh):
    fake_gh.route("pulls?", [])
    fake_gh.route("compare/dev...main", _rows("c", "d"))
    fake_gh.route("compare/main...dev", {"ahead": 0, "behind": 2, "commits": [], "files": []})
    r = gh_data.fetch_compare("o/r", "main", "dev")
    assert [c.message for c in r.behind_commits] == ["cd", "cc"]
    assert r.behind_commits[0].branches == ["main"]

    fake_gh.routes.clear()
    fake_gh.calls.clear()
    fake_gh.route("pulls?", [])
    fake_gh.route("compare/main...dev", {"ahead": 1, "behind": 0, "commits": [], "files": []})
    gh_data.fetch_compare("o/r", "main", "dev")
    assert not fake_gh.called_with("compare/dev...main")


def test_files_keep_their_lines_and_a_rename_its_old_name(fake_gh):
    fake_gh.route("pulls?", [])
    fake_gh.route("compare/", {"ahead": 1, "behind": 0, "commits": [], "files": [
        {"filename": "new.py", "status": "renamed", "additions": 1, "deletions": 0,
         "patch": "@@ -1 +1 @@", "previous_filename": "old.py", "blob_url": "B"}]})
    f = gh_data.fetch_compare("o/r", "a", "b").files[0]
    assert (f.filename, f.previous_filename, f.patch, f.url) == (
        "new.py", "old.py", "@@ -1 +1 @@", "B")


def test_a_ref_is_escaped_but_keeps_its_slashes_and_owner(fake_gh):
    fake_gh.route("pulls?", [])
    fake_gh.route("compare/", {"ahead": 0, "behind": 0, "commits": [], "files": []})
    gh_data.fetch_compare("o/r", "rel#1", "fork:feat/x y")
    assert fake_gh.calls[0][1] == "repos/o/r/compare/rel%231...fork:feat/x%20y"


def test_the_comparison_survives_not_being_able_to_read_its_pull(fake_gh):
    fake_gh.route("pulls?", GhError("nope"))
    fake_gh.route("compare/", {"ahead": 1, "behind": 0, "commits": [], "files": []})
    r = gh_data.fetch_compare("o/r", "main", "dev")
    assert r.loaded and r.pull is None


def test_the_open_pull_is_looked_up_by_owner_and_branch(fake_gh):
    fake_gh.route("pulls?", [{"number": 7, "title": "T", "html_url": "P"}])
    assert gh_data.fetch_open_pull("o/r", "main", "feat/x") == ComparePull(7, "T", "P")
    called = fake_gh.calls[-1][1]
    assert "state=open" in called and "base=main" in called and "head=o:feat%2Fx" in called
    gh_data.fetch_open_pull("o/r", "main", "fork:feat")
    assert "head=fork:feat" in fake_gh.calls[-1][1]


def test_creating_a_pull_request(fake_gh):
    fake_gh.route("pr create", "https://github.com/o/r/pull/12\n")
    assert gh_data.create_pull_request("o/r", "main", "dev", "T", "B", draft=True) == (
        12, "https://github.com/o/r/pull/12")
    args = fake_gh.calls[-1]
    assert args[args.index("--base") + 1] == "main" and args[args.index("--head") + 1] == "dev"
    assert "--draft" in args and fake_gh.stdin[-1] == "B"
    gh_data.create_pull_request("o/r", "main", "dev", "T", "B")
    assert "--draft" not in fake_gh.calls[-1]


def test_a_pull_request_gh_doesnt_say_the_address_of(fake_gh):
    fake_gh.route("pr create", "Created!")
    with pytest.raises(gh_data.IssueCreatedUnreadable):
        gh_data.create_pull_request("o/r", "main", "dev", "T", "")


def test_branch_counts_turn_github_s_direction_round_and_read_every_page(monkeypatch):
    pages = [
        {"data": {"repository": {"refs": {
            "pageInfo": {"hasNextPage": True, "endCursor": "X"},
            # compare(headRef: main) on dev: main is 5 ahead of dev, so dev is 5 behind.
            "nodes": [{"name": "dev", "compare": {"aheadBy": 5, "behindBy": 2}},
                      {"name": "gone", "compare": None}]}}}},
        {"data": {"repository": {"refs": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": [{"name": "fix", "compare": {"aheadBy": 0, "behindBy": 1}}]}}}},
    ]
    seen = []

    def graphql(query, variables=None):
        seen.append(variables)
        return pages[len(seen) - 1]

    monkeypatch.setattr(gh_data, "_graphql", graphql)
    assert gh_data.fetch_branch_counts("o/r", "main") == {"dev": (2, 5), "fix": (1, 0)}
    assert seen[0] == {"owner": "o", "name": "r", "head": "main", "after": None}
    assert seen[1]["after"] == "X"


def test_branch_counts_say_why_not(monkeypatch):
    monkeypatch.setattr(gh_data, "_graphql",
                        lambda q, v=None: {"errors": [{"message": "too big"}]})
    with pytest.raises(GhError, match="too big"):
        gh_data.fetch_branch_counts("o/r", "main")


def test_a_branch_row_tells_zero_from_not_known():
    b = Branch("dev", "s", "m", "a", "d")
    assert b.to_row(["ahead", "behind"]) == {"ahead": "", "behind": ""}
    b.ahead, b.behind = 0, 3
    assert b.to_row(["ahead", "behind"]) == {"ahead": "0", "behind": "3"}


# ── What is said ────────────────────────────────────────────────────────


@pytest.mark.parametrize("ahead, behind, said", [
    (0, 0, "dev and main are identical."),
    (1, 0, "dev is 1 commit ahead of main."),
    (3, 0, "dev is 3 commits ahead of main."),
    (0, 1, "dev is 1 commit behind main."),
    (2, 1, "dev and main have diverged: dev is 2 commits ahead and 1 behind."),
    (1000, 2500, "dev and main have diverged: dev is 1,000 commits ahead and 2,500 behind."),
])
def test_relation(ahead, behind, said):
    assert compareview.relation(_result(ahead_by=ahead, behind_by=behind)) == said


def test_a_branch_compared_with_itself():
    assert "compared with itself" in compareview.relation(_result(base="main", head="main"))


def test_summary_has_how_they_stand_their_files_and_their_pull():
    r = _result(ahead_by=1, files=[FILE], pull=ComparePull(7, "Fix it"))
    assert compareview.summary(r) == (
        "dev is 1 commit ahead of main. 1 file changed, 3 lines added, 1 removed. "
        "Pull request #7 is open: Fix it.")


def test_the_file_cap_is_said_only_when_github_stopped():
    assert "first 300" not in compareview.files_note(_result(files=[FILE] * 299))
    assert "first 300" in compareview.files_note(_result(files=[FILE] * 300))


def test_a_list_of_only_the_newest_commits_says_so():
    commits = [_commit("a")] * 250
    r = _result(ahead_by=8454, commits=commits)
    assert compareview.list_said(r, compareview.AHEAD) == "Commits ahead: the newest 250 of 8,454."
    r = _result(behind_by=2, behind_commits=[_commit("a")] * 2)
    assert compareview.list_said(r, compareview.BEHIND) == "Commits behind: 2."


def test_lists_only_those_with_something_in_them_in_order():
    a, b = [_commit("a")], [_commit("b")]
    full = _result(files=[FILE], commits=a, behind_commits=b)
    assert compareview.lists_of(full) == ["files", "ahead", "behind"]
    assert compareview.next_list(full, "files") == "ahead"
    assert compareview.next_list(full, "ahead") == "behind"
    assert compareview.next_list(full, "behind") == "files"

    behind_only = _result(behind_commits=b)
    assert compareview.first_list(behind_only) == "behind"
    assert compareview.next_list(behind_only, "behind") == "behind"

    identical = _result()
    assert compareview.first_list(identical) == "files"
    assert compareview.next_list(identical, "files") == "files"


def test_a_pull_request_starts_from_one_commits_message_or_the_branch_name():
    one = _result(commits=[_commit("a", "Fix focus\n\nThe list lost it.\n")])
    assert compareview.pull_prefill(one) == ("Fix focus", "The list lost it.")
    two = _result(head="feature/fix-the_focus", commits=[_commit("a"), _commit("b")])
    assert compareview.pull_prefill(two) == ("Fix the focus", "")


# ── Addresses and choices ───────────────────────────────────────────────


@pytest.mark.parametrize("url, ref", [
    ("https://github.com/o/r/compare/a...b", "a...b"),
    ("https://github.com/o/r/compare/main...feat/x?expand=1", "main...feat/x"),
    ("https://github.com/o/r/compare/feat", "feat"),
    ("https://github.com/o/r/compare/a...b.diff", "a...b"),
])
def test_a_compare_address_is_read(url, ref):
    target = ghviewer.parse_github_url(url)
    assert (target.repo, target.kind, target.ref) == ("o/r", "compare", ref)
    assert ghviewer.address_view(target) == ghviewer.VIEW_BRANCHES


def test_the_github_compare_page_with_nothing_chosen_has_no_view():
    assert ghviewer.parse_github_url("https://github.com/o/r/compare").kind == "inside"


@pytest.mark.parametrize("ref, refs", [
    ("main...dev", ("main", "dev")),
    ("main..dev", ("main", "dev")),
    ("main...fork:feat/x", ("main", "fork:feat/x")),
    ("dev", ("", "dev")),
])
def test_compare_refs(ref, refs):
    assert ghviewer.compare_refs(ref) == refs


@pytest.mark.parametrize("base, head, word", [
    ("", "dev", "base"), ("main", "", "head"), ("main", "main", "both main"), ("main", "dev", ""),
])
def test_what_is_wrong_with_a_choice(base, head, word):
    problem = ghviewer.compare_choice_problem(base, head)
    assert word in problem if word else problem == ""


# ── The frame ───────────────────────────────────────────────────────────


def _frame(view, **attrs):
    told: list[str] = []
    f = SimpleNamespace(
        view_mode=view, repo="o/r", _files_of=None, _files_back=None, git_items=[], items=[],
        _compare_list=compareview.FILES, _compare_summary_due=False, current_limit=30,
        filter_text="", label_filter="", milestone_filter=None, commit_branch="",
        _branches_unread=0, _return_to=None, _return_view=ghviewer.VIEW_ISSUES,
        _fetch_token=0, _pending_target=None, told=told, calls=[], _history_of=None,
        _history_back=None, _org="",
    )
    f._tell = lambda msg, *a, **k: told.append(msg)
    f._announce = told.append
    f._comparison = lambda: Frame._comparison(f)
    f._loaded_comparison = lambda: Frame._loaded_comparison(f)
    f._focused_item = lambda: None
    f._view_source = lambda: f.items if f.view_mode == ghviewer.VIEW_ISSUES else f.git_items
    f._begin_fetch = lambda: Frame._begin_fetch(f)
    f._fetch_is_current = lambda token: token == f._fetch_token
    f._update_title = lambda: None
    f._load_items = lambda: f.calls.append(("load", f.view_mode, f._files_of))
    f._compare_back = lambda: Frame._compare_back(f)
    f._show_compare_list = lambda which, token=None: Frame._show_compare_list(f, which, token)
    f._on_files_loaded = lambda token, files, *a: f.calls.append(("files", files))
    f._on_compare_commits_loaded = lambda token, commits: f.calls.append(("commits", commits))
    f._on_git_items_loaded = lambda token, items, kind: f.calls.append(("git", items, kind))
    f._view_label = lambda v, lower=False: Frame._view_label(f, v, lower)
    f._VIEW_LABELS = Frame._VIEW_LABELS
    f._set_pending_target = lambda *a: Frame._set_pending_target(f, *a)
    f._ref_name = Frame._ref_name
    f._previous_ref = lambda item: Frame._previous_ref(f, item)
    f._commits_branch = lambda: Frame._commits_branch(f)
    f._open_compare = lambda *a, **k: Frame._open_compare(f, *a, **k)

    def switch(mode, load=True):
        f.calls.append(("switch", mode))
        if f.view_mode == mode:
            return
        f.view_mode = mode
        if mode not in (ghviewer.VIEW_FILES, ghviewer.VIEW_COMPARE):
            f._files_of = None
            f._files_back = None
        f.filter_text = ""
    f._switch_view = switch
    for k, v in attrs.items():
        setattr(f, k, v)
    return f


def _in_comparison(result, which=compareview.FILES, back=None, **attrs):
    view = ghviewer.VIEW_FILES if which == compareview.FILES else ghviewer.VIEW_COMPARE
    return _frame(view, _files_of=result, _compare_list=which,
                  _files_back=back or {"view": ghviewer.VIEW_BRANCHES}, **attrs)


def test_only_a_comparison_is_a_comparison():
    r = _result()
    assert Frame._comparison(_frame(ghviewer.VIEW_FILES, _files_of=r)) is r
    assert Frame._comparison(_frame(ghviewer.VIEW_COMPARE, _files_of=r)) is r
    assert Frame._comparison(_frame(ghviewer.VIEW_FILES, _files_of=_commit("a"))) is None
    # Coming back to a list: what is left in the attribute isn't showing.
    assert Frame._comparison(_frame(ghviewer.VIEW_BRANCHES, _files_of=r)) is None


def test_a_load_keeps_its_token_filter_and_the_row_waiting_for_it():
    commits = [_commit("a"), _commit("b")]
    r = _result(commits=commits, ahead_by=2)
    f = _in_comparison(r, compareview.AHEAD, filter_text="x")
    token = Frame._begin_fetch(f)
    f._pending_target = (token, ghviewer.VIEW_COMPARE, "url", "u/b")
    seen = []
    f._on_compare_commits_loaded = lambda t, c: seen.append((t, f.filter_text, f._pending_target))
    Frame._on_compare_loaded(f, token, _result(commits=commits, ahead_by=2))
    assert seen == [(token, "x", (token, ghviewer.VIEW_COMPARE, "url", "u/b"))]
    assert f._compare_summary_due is False   # coming back to a row isn't news


def test_refresh_keeps_the_filter_and_says_the_summary():
    r = _result(files=[FILE])
    f = _in_comparison(r, filter_text="a")
    token = Frame._begin_fetch(f)
    Frame._on_compare_loaded(f, token, _result(files=[FILE]))
    assert f.filter_text == "a" and f._compare_summary_due is True


def test_l_is_a_new_list_so_the_filter_goes():
    r = _result(files=[FILE], commits=[_commit("a")], ahead_by=1)
    f = _in_comparison(r, filter_text="a")
    Frame._compare_next_list(f)
    assert f.filter_text == ""


def test_a_new_comparison_leaves_nothing_of_the_last_view_to_draw():
    branch = Branch("dev", "s", "m", "a", "d")
    f = _frame(ghviewer.VIEW_BRANCHES, git_items=[branch], _landed_token=0)
    Frame._open_compare(f, "main", "nope")
    assert f.git_items == [] and f._files_back["items"] == [branch]


def test_a_list_still_loading_is_read_again_on_the_way_back():
    branch = Branch("dev", "s", "m", "a", "d")
    f = _frame(ghviewer.VIEW_BRANCHES, git_items=[branch], _landed_token=0, _fetch_token=5)
    assert Frame._compare_back(f)["items"] is None


@pytest.mark.parametrize("view", [ghviewer.VIEW_FILES, ghviewer.VIEW_COMPARE])
def test_state_and_filter_wait_for_the_way_back(view):
    back = {"view": ghviewer.VIEW_ISSUES, "items": ["x"]}
    f = _frame(view, _files_of=_result(), _files_back=back)
    Frame._reload_after_filter(f)
    assert back["items"] is None and f.calls == [] and "go back" in f.told[-1]


def test_a_pull_gh_didnt_say_the_address_of_is_not_offered_again_as_a_draft():
    key = ("o/r", "main", "dev")
    f = _in_comparison(_result(), _pull_busy=True, _pull_drafts={key: ("t", "b", False)})
    Frame._on_pull_unreadable(f, key)
    assert f._pull_drafts == {} and f._pull_busy is False and "was created" in f.told[-1]


def test_p_says_what_isnt_a_branch_instead_of_offering_the_form():
    r = _result(ahead_by=1, head="v1.2")
    f = _in_comparison(r, _pull_busy=False)
    Frame._show_pull_dialog(f, r, "v1.2")
    assert "isn't a branch" in f.told[-1]


def test_is_branch(fake_gh):
    fake_gh.route("heads/yes", "refs/heads/yes")
    fake_gh.route("heads/tag", GhError("gh: Not Found (HTTP 404)"))
    fake_gh.route("heads/down", GhError("gh: server error (HTTP 502)"))
    assert gh_data.is_branch("o/r", "yes") is True
    assert gh_data.is_branch("o/r", "tag") is False
    assert gh_data.is_branch("o/r", "down") is None


def test_whole_file_of_another_owners_head_says_so():
    item = ChangedFile("a.py")
    f = _in_comparison(_result(head="them:feat"), _whole_file_busy=False)
    f._focused_item = lambda: item
    Frame._open_whole_file(f)
    assert "them's" in f.told[-1]


def test_previous_skips_a_draft():
    rel = [SimpleNamespace(tag="v3", draft=False), SimpleNamespace(tag="v2", draft=True),
           SimpleNamespace(tag="v1", draft=False)]
    f = _frame(ghviewer.VIEW_RELEASES, git_items=rel)
    f._ref_name = lambda it: it.tag
    assert Frame._previous_ref(f, rel[0]) == "v1"


def test_keys_of_a_comparison_that_failed_to_load_say_so():
    f = _in_comparison(_result(loaded=False))
    assert Frame._loaded_comparison(f) is None
    assert "hasn't loaded" in f.told[-1]


def test_c_on_a_branch_compares_with_the_default_branch_keeping_the_way_back():
    branch = Branch("dev", "s", "m", "a", "d")
    rows = [branch]
    f = _frame(ghviewer.VIEW_BRANCHES, git_items=rows, filter_text="de", current_limit=60,
               _landed_token=0)
    f._focused_item = lambda: branch
    Frame._compare_with(f)
    assert f.view_mode == ghviewer.VIEW_FILES
    assert isinstance(f._files_of, CompareResult)
    assert (f._files_of.base, f._files_of.head, f._files_of.loaded) == ("", "dev", False)
    back = f._files_back
    assert (back["view"], back["items"], back["item"], back["filter_text"], back["limit"]) == (
        ghviewer.VIEW_BRANCHES, rows, branch, "de", 60)
    assert f.calls[-1][0] == "load"
    assert f.told[-1] == "Comparing dev with the default branch…"


def test_c_on_a_tag_compares_with_the_one_before_it():
    tags = [Tag("v3", "s"), Tag("v2", "s"), Tag("v1", "s")]
    f = _frame(ghviewer.VIEW_TAGS, git_items=tags)
    f._focused_item = lambda: tags[0]
    Frame._compare_with(f)
    assert (f._files_of.base, f._files_of.head) == ("v2", "v3")


def test_c_on_the_last_tag_says_there_is_nothing_before_it():
    tags = [Tag("v2", "s"), Tag("v1", "s")]
    f = _frame(ghviewer.VIEW_TAGS, git_items=tags)
    f._focused_item = lambda: tags[1]
    Frame._compare_with(f)
    assert f.view_mode == ghviewer.VIEW_TAGS and "last one listed" in f.told[-1]


@pytest.mark.parametrize("branch, head", [("dev", "dev"), ("", ""), (ghviewer.ALL_BRANCHES, "")])
def test_c_on_a_commit_compares_it_with_the_latest(branch, head):
    commit = _commit("a")
    f = _frame(ghviewer.VIEW_COMMITS, git_items=[commit], commit_branch=branch)
    f._focused_item = lambda: commit
    Frame._compare_with(f)
    assert (f._files_of.base, f._files_of.head) == (commit.short_sha, head)


def test_a_view_that_cant_be_put_back_goes_back_to_branches():
    f = _frame(ghviewer.VIEW_ARTIFACTS, filter_text="x")
    back = Frame._compare_back(f)
    assert (back["view"], back["items"], back["filter_text"]) == (ghviewer.VIEW_BRANCHES, None, "")


def test_a_comparison_from_a_comparison_goes_back_where_the_first_did():
    origin = {"view": ghviewer.VIEW_TAGS}
    f = _in_comparison(_result(), back=origin)
    assert Frame._compare_back(f) is origin


def test_swap_asks_again_the_other_way_round_with_the_same_way_back():
    origin = {"view": ghviewer.VIEW_TAGS}
    f = _in_comparison(_result(), back=origin)
    Frame._compare_swap(f)
    assert (f._files_of.base, f._files_of.head, f._files_of.loaded) == ("dev", "main", False)
    assert f._files_back is origin and f.calls[-1][0] == "load"


def test_loaded_opens_on_the_first_list_with_something_in_it():
    origin = {"view": ghviewer.VIEW_BRANCHES}
    f = _in_comparison(_result(loaded=False, base="", head="dev"), back=origin)
    token = Frame._begin_fetch(f)
    behind = [_commit("b")]
    got = _result(behind_by=1, behind_commits=behind)
    Frame._on_compare_loaded(f, token, got)
    assert f.view_mode == ghviewer.VIEW_COMPARE and f._compare_list == compareview.BEHIND
    assert f._files_of is got and f._files_back is origin
    assert f.calls[-1] == ("commits", behind)
    assert f._compare_summary_due is True


def test_refresh_stays_on_the_list_it_was_on():
    commits = [_commit("a")]
    f = _in_comparison(_result(files=[FILE], commits=commits), compareview.AHEAD)
    token = Frame._begin_fetch(f)
    Frame._on_compare_loaded(f, token, _result(files=[FILE], commits=commits))
    assert f._compare_list == compareview.AHEAD and f.calls[-1] == ("commits", commits)


def test_a_stale_load_is_dropped():
    f = _in_comparison(_result(loaded=False))
    stale = Frame._begin_fetch(f)
    Frame._begin_fetch(f)
    Frame._on_compare_loaded(f, stale, _result())
    assert f.calls == [] and f._files_of.loaded is False


def test_l_goes_round_the_lists_and_a_lone_list_says_so():
    a, b = [_commit("a")], [_commit("b")]
    r = _result(files=[FILE], commits=a, behind_commits=b, ahead_by=1, behind_by=1)
    f = _in_comparison(r)
    Frame._compare_next_list(f)
    assert (f.view_mode, f._compare_list, f.calls[-1]) == (
        ghviewer.VIEW_COMPARE, compareview.AHEAD, ("commits", a))
    Frame._compare_next_list(f)
    assert (f.view_mode, f._compare_list, f.calls[-1]) == (
        ghviewer.VIEW_COMPARE, compareview.BEHIND, ("commits", b))
    Frame._compare_next_list(f)
    assert (f.view_mode, f._compare_list, f.calls[-1]) == (
        ghviewer.VIEW_FILES, compareview.FILES, ("files", [FILE]))
    # Through it all, the comparison and its way back are kept.
    assert f._files_of is r and f._files_back == {"view": ghviewer.VIEW_BRANCHES}

    alone = _in_comparison(_result(ahead_by=0, behind_by=0))
    Frame._compare_next_list(alone)
    assert "only list" in alone.told[-1] and alone.calls == []


def test_backspace_label_in_each_list_of_a_comparison():
    for which in (compareview.FILES, compareview.AHEAD):
        f = _in_comparison(_result(), which, back={"view": ghviewer.VIEW_TAGS})
        assert Frame._back_label(f) == "Back to Tags"


def _full_back(view, items, item):
    return {"view": view, "items": items, "item": item, "limit": 60, "filter_text": "x",
            "label_filter": "", "milestone_filter": None, "commit_branch": "",
            "branches_unread": 0, "return_to": None, "return_view": ghviewer.VIEW_ISSUES}


@pytest.mark.parametrize("view, kind", sorted(ghviewer.COMPARE_BACK_KINDS.items()))
def test_back_from_a_comparison_is_the_list_as_it_was(view, kind):
    rows = [Tag("v1", "s")]
    f = _in_comparison(_result(), back=_full_back(view, rows, rows[0]))
    Frame._back_from_files(f)
    assert f.view_mode == view and f.calls[-1] == ("git", rows, kind)
    assert (f.filter_text, f.current_limit) == ("x", 60)
    assert f._pending_target[2:] == ("same", rows[0])


def test_back_from_a_comparison_opened_from_an_address_reads_branches():
    f = _in_comparison(_result(), back=_full_back(ghviewer.VIEW_BRANCHES, None, None))
    Frame._back_from_files(f)
    assert f.view_mode == ghviewer.VIEW_BRANCHES and f.calls[-1][0] == "load"


def test_a_commit_of_a_comparison_and_back_to_it():
    commits = [_commit("a"), _commit("b")]
    r = _result(commits=commits, ahead_by=2)
    origin = _full_back(ghviewer.VIEW_BRANCHES, [], None)
    f = _in_comparison(r, compareview.AHEAD, back=origin, git_items=commits)
    f._focused_item = lambda: commits[1]
    Frame._show_changed_files(f)
    assert f.view_mode == ghviewer.VIEW_FILES and f._files_of is commits[1]
    assert Frame._comparison(f) is None   # in here it is the commit's files

    Frame._back_from_files(f)
    assert f.view_mode == ghviewer.VIEW_COMPARE and f._files_of is r
    assert f._files_back is origin and f._compare_list == compareview.AHEAD
    assert f.calls[-1] == ("commits", commits)
    assert f._pending_target[2:] == ("same", commits[1])


def test_the_pull_key_refuses_when_there_is_nothing_to_bring_in():
    f = _in_comparison(_result(ahead_by=0, behind_by=2))
    Frame._compare_pull(f)
    assert "nothing" in f.told[-1]


def test_a_new_pull_is_remembered_and_said():
    r = _result(ahead_by=1)
    f = _in_comparison(r, _pull_busy=True, _pull_drafts={("o/r", "main", "dev"): ("t", "b", False)})
    f._set_compare_status = lambda: f.calls.append(("status",))
    pull = ComparePull(12, "t", "u")
    Frame._on_pull_created(f, ("o/r", "main", "dev"), r, pull)
    assert r.pull is pull and f._pull_busy is False and f._pull_drafts == {}
    assert f.calls == [("status",)]
    assert f.told[-1] == "Created pull request #12 from dev into main."


def test_a_failed_pull_keeps_what_was_typed():
    drafts = {("o/r", "main", "dev"): ("t", "b", True)}
    f = _in_comparison(_result(), _pull_busy=True, _pull_drafts=drafts)
    Frame._on_pull_failed(f, "no")
    assert f._pull_busy is False and f._pull_drafts == drafts and "no" in f.told[-1]


def test_going_to_the_pull_and_back_returns_to_the_same_list():
    r = _result(pull=ComparePull(12))
    origin = {"view": ghviewer.VIEW_BRANCHES}
    commits = [_commit("a")]
    f = _in_comparison(r, compareview.AHEAD, back=origin, git_items=commits)
    opened = []
    def open_repo(repo, item):
        opened.append(repo)
        f.view_mode = ghviewer.VIEW_ISSUES
        f._files_of = None
        f._files_back = None
        f._return_view = ghviewer.VIEW_ISSUES
    f._open_repo_from_list = open_repo
    Frame._on_comparison_pull_checked(f, r, "o/r", 12, None)
    assert opened == ["o/r"] and f._pending_target[1:] == (ghviewer.VIEW_ISSUES, "item", "12")

    f._restore_repo_selection = lambda *_: None
    Frame._return_to_list(f)
    assert f.view_mode == ghviewer.VIEW_COMPARE and f._files_of is r and f._files_back is origin
    assert f._compare_list == compareview.AHEAD and f.calls[-1] == ("commits", commits)
    # On the row it left, with the filter it had.
    assert f._pending_target[2:] == ("same", None)


def test_a_pull_on_a_fork_is_said_not_opened():
    r = _result(pull=ComparePull(12))
    f = _in_comparison(r)
    Frame._on_comparison_pull_checked(f, r, "o/r", 12, "up/r")
    assert f.view_mode == ghviewer.VIEW_FILES and "up/r" in f.told[-1]


def test_branch_counts_fill_every_branch_but_the_default():
    main, dev, new = (Branch(n, "s", "m", "a", "d") for n in ("main", "dev", "new"))
    f = _frame(ghviewer.VIEW_ARTIFACTS)  # moved on: the rows still get them, for Backspace
    token = Frame._begin_fetch(f)
    Frame._on_branch_counts(f, token, [main, dev, new], "main", {"main": (0, 0), "dev": (2, 1)})
    assert (main.ahead, main.behind) == (None, None)
    assert (dev.ahead, dev.behind, dev.compared_with) == (2, 1, "main")
    assert (new.ahead, new.behind) == (None, None)


def test_branch_counts_read_with_the_list_say_nothing_if_github_wont(monkeypatch):
    monkeypatch.setattr(ghviewer, "fetch_default_branch", lambda repo: "main")
    monkeypatch.setattr(ghviewer, "fetch_branch_counts", lambda *a: {"dev": (1, 2)})
    assert ghviewer.read_branch_counts("o/r", 30) == ("main", {"dev": (1, 2)})

    def refuse(*a):
        raise GhError("no")
    monkeypatch.setattr(ghviewer, "fetch_branch_counts", refuse)
    assert ghviewer.read_branch_counts("o/r", 30) == ("", {})


def test_a_comparison_favorite_opens_again(tmp_path):
    from favorites import FavoriteEntry
    f = _in_comparison(_result(ahead_by=1), favorites=[])
    f._refresh_repo_list_fav_count = lambda: None
    Frame._favorite_comparison(f, f._files_of)
    entry = f.favorites[0]
    assert isinstance(entry, FavoriteEntry) and entry.item_type == "compare"
    assert ghviewer.parse_github_url(entry.url).kind == "compare"
    Frame._favorite_comparison(f, f._files_of)
    assert f.favorites == [] and "removed" in f.told[-1]


def test_a_comparison_not_yet_loaded_has_nothing_to_favorite():
    f = _in_comparison(_result(url="", loaded=False), favorites=[])
    Frame._favorite_comparison(f, f._files_of)
    assert f.favorites == [] and "address" in f.told[-1]
