"""Checks against the real GitHub API, for what fakes can't settle.

Skipped unless GHMANAGE_LIVE_GITHUB=1, and then gh must be signed in (in CI,
GH_TOKEN set to the workflow's token). The live-github workflow runs these.
They only read public repositories.

Every other test fakes gh, so a query GitHub would reject, or a field it
fills differently from what the fakes assume, passes there. These ask
GitHub itself.
"""

from __future__ import annotations

import os
import time

import pytest

import gh_data

pytestmark = pytest.mark.skipif(
    os.environ.get("GHMANAGE_LIVE_GITHUB") != "1",
    reason="talks to GitHub; set GHMANAGE_LIVE_GITHUB=1 to run",
)

# Busy, public, and with plenty of branches.
BUSY_REPO = os.environ.get("GHMANAGE_LIVE_REPO", "cli/cli")


@pytest.fixture(autouse=True)
def real_gh(monkeypatch, real_run_gh, real_graphql):
    """Undo conftest's fakes: these tests are about the real thing."""
    monkeypatch.setattr(gh_data, "_run_gh", real_run_gh)
    monkeypatch.setattr(gh_data, "_graphql", real_graphql)


def _graphql_default_branch(repo: str) -> str:
    owner, name = repo.split("/", 1)
    node = gh_data._graphql_repository(gh_data._graphql(
        f'{{ repository(owner: "{owner}", name: "{name}") {{ defaultBranchRef {{ name }} }} }}'
    ))
    return node["defaultBranchRef"]["name"]


def test_default_branch_matches_graphql():
    rest = gh_data.fetch_default_branch(BUSY_REPO)
    assert rest and rest == _graphql_default_branch(BUSY_REPO)


def test_one_branch_commits_name_the_default_branch():
    commits = gh_data.fetch_commits(BUSY_REPO, limit=5)
    assert len(commits) == 5
    default = gh_data.fetch_default_branch(BUSY_REPO)
    assert all(c.branches == [default] for c in commits)


def test_tag_commit_date_does_not_order_branches():
    """Why fetch_all_branch_commits sorts branches itself: ordering refs by
    TAG_COMMIT_DATE, documented only for tags, leaves branches unsorted.
    Reported, not asserted: whether a page happens to come out sorted
    depends on the repository, and a GitHub fix shouldn't turn a PR red."""
    owner, name = "cli", "cli"   # where it was seen, whatever repo is being checked
    node = gh_data._graphql_repository(gh_data._graphql(
        f'{{ repository(owner: "{owner}", name: "{name}") {{ '
        'refs(refPrefix: "refs/heads/", first: 30, '
        "orderBy: {field: TAG_COMMIT_DATE, direction: DESC}) "
        "{ nodes { name target { ... on Commit { committedDate } } } } } }"
    ))
    dates = [r["target"]["committedDate"] for r in node["refs"]["nodes"]]
    assert len(dates) > 1
    if dates == sorted(dates, reverse=True):
        print("\nTAG_COMMIT_DATE now sorts branches: GitHub could order them for us")
    else:
        print("\nTAG_COMMIT_DATE still leaves branches unsorted")


def test_all_branches_reaches_the_newest_work():
    """The newest commit on any branch is at least as new as the default
    branch's, and the list draws on recently active branches."""
    commits, _ = gh_data.fetch_all_branch_commits(BUSY_REPO, limit=100)
    newest_default = gh_data.fetch_commits(BUSY_REPO, limit=1)[0].date
    assert commits[0].date >= newest_default
    print(f"\nnewest anywhere {commits[0].date} on {commits[0].branches}, "
          f"newest on the default branch {newest_default}")


def test_all_branches_against_github():
    started = time.monotonic()
    commits, unread = gh_data.fetch_all_branch_commits(BUSY_REPO, limit=100)
    took = time.monotonic() - started
    branches = {b for c in commits for b in c.branches}
    print(f"\n{len(commits)} commits from {len(branches)} branches in {took:.1f}s, "
          f"{unread} branches unread")
    assert unread == 0
    assert len(commits) == 100
    assert [c.date for c in commits] == sorted((c.date for c in commits), reverse=True)
    assert all(c.date.endswith("Z") and len(c.date) == 20 for c in commits)
    assert all(c.message and c.author and c.url and len(c.sha) == 40 for c in commits)
    assert all(c.branches for c in commits)
    assert len(commits) == len({c.sha for c in commits})
    default = gh_data.fetch_default_branch(BUSY_REPO)
    # The default branch leads any commit's list it is in
    assert all(c.branches[0] == default for c in commits if default in c.branches)
    assert len(branches) > 1
    assert took < 60


def test_all_branches_reads_a_second_page():
    commits, unread = gh_data.fetch_all_branch_commits(BUSY_REPO, limit=200)
    print(f"\nView More: {len(commits)} commits, {unread} branches unread")
    assert unread == 0 and len(commits) == 200


def test_how_many_one_branch_returns_past_100():
    """Not a pass/fail on this change: records whether View More on a single
    branch can get past 100, which REST's per_page may cap."""
    commits = gh_data.fetch_commits(BUSY_REPO, limit=200)
    print(f"\nOne branch, asked for 200: got {len(commits)}")
    assert commits
