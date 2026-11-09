"""Changing an issue or pull request (#122): labels, assignees, projects,
title and description; and View > Filter by people and milestone."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

import gh_data
from checklist import Checklist, change_said
from gh_data import GhError, Item, ItemFilter, ItemNow, ItemProjects, MissingScope, Project

if os.environ.get("CI"):
    import wx  # noqa: F401
else:
    pytest.importorskip("wx")

import ghviewer  # noqa: E402
from test_set_milestone import fake_frame, run_now  # noqa: E402
from test_consistent_keys import Key, _hook_frame  # noqa: E402

Frame = ghviewer.GhViewerFrame


# ── The checklist ───────────────────────────────────────────────────────


def test_rows_say_their_state():
    c = Checklist(["bug", "docs", "ui"], ["docs"])
    assert c.rows() == ["bug, not checked", "docs, checked", "ui, not checked"]
    assert c.summary() == "1 checked: docs"


def test_toggle_says_what_it_now_is():
    c = Checklist(["bug", "docs"], ["docs"])
    assert c.toggle(0) == "bug checked"
    assert c.toggle(1) == "docs not checked"
    assert c.row(0) == "bug, checked" and c.chosen() == ["bug"]
    assert (c.added(), c.removed(), c.changed) == (["bug"], ["docs"], True)


def test_toggling_back_is_no_change():
    c = Checklist(["bug"], [])
    c.toggle(0)
    c.toggle(0)
    assert not c.changed and c.summary() == "None checked"


def test_something_checked_but_not_offered_is_kept_at_the_end():
    c = Checklist(["alice"], ["zed", "alice"])
    assert c.names == ["alice", "zed"] and c.chosen() == ["alice", "zed"]


def test_duplicates_in_the_options_are_listed_once():
    assert Checklist(["a", "a", "b"], []).names == ["a", "b"]


@pytest.mark.parametrize("added, removed, now, said", [
    (["bug"], [], ["bug", "ui"], "#5: added bug. Labels now: bug, ui."),
    (["bug"], ["docs"], ["bug"], "#5: added bug, removed docs. Labels now: bug."),
    ([], ["docs"], [], "#5: removed docs. No labels now."),
    ([], [], [], "#5 has no labels."),
])
def test_change_said(added, removed, now, said):
    assert change_said(5, "Labels", added, removed, now) == said


# ── gh calls ────────────────────────────────────────────────────────────


ISSUE = Item(7, "T", "OPEN", "u", False, labels=["docs"], assignees=["bob"], body="Old")


def test_only_the_label_changes_are_sent(fake_gh):
    fake_gh.route("labels", "")
    gh_data.change_item_labels(ISSUE, "o/r", ["bug", "ui"], ["needs info/triage"])
    add, remove = fake_gh.calls
    assert add[:4] == ["api", "-X", "POST", "repos/o/r/issues/7/labels"]
    assert json.loads(fake_gh.stdin[0]) == {"labels": ["bug", "ui"]}
    assert remove[:4] == ["api", "-X", "DELETE",
                          "repos/o/r/issues/7/labels/needs%20info%2Ftriage"]


def test_removing_a_label_already_gone_is_no_error(fake_gh):
    fake_gh.route("DELETE", GhError("HTTP 404: Label does not exist"))
    gh_data.change_item_labels(ISSUE, "o/r", [], ["docs"])


def test_other_label_failures_are_errors(fake_gh):
    fake_gh.route("DELETE", GhError("HTTP 403: Forbidden"))
    with pytest.raises(GhError, match="403"):
        gh_data.change_item_labels(ISSUE, "o/r", [], ["docs"])


def test_nothing_to_change_sends_nothing(fake_gh):
    gh_data.change_item_labels(ISSUE, "o/r", [], [])
    gh_data.change_item_assignees(ISSUE, "o/r", [], [])
    gh_data.edit_item(ISSUE, "o/r")
    assert fake_gh.calls == []


def test_only_the_assignee_changes_are_sent(fake_gh):
    fake_gh.route("assignees", "")
    gh_data.change_item_assignees(ISSUE, "o/r", ["alice"], ["bob"])
    add, remove = fake_gh.calls
    assert add[:4] == ["api", "-X", "POST", "repos/o/r/issues/7/assignees"]
    assert remove[:4] == ["api", "-X", "DELETE", "repos/o/r/issues/7/assignees"]
    assert [json.loads(x) for x in fake_gh.stdin] == [{"assignees": ["alice"]},
                                                      {"assignees": ["bob"]}]


def test_title_and_body_go_on_stdin_not_the_command_line(fake_gh):
    fake_gh.route("PATCH", "")
    gh_data.edit_item(ISSUE, "o/r", "New -title", "Body\n--flag")
    assert json.loads(fake_gh.stdin[0]) == {"title": "New -title", "body": "Body\n--flag"}
    assert "New -title" not in " ".join(fake_gh.calls[0])


def test_a_title_alone_leaves_the_description(fake_gh):
    fake_gh.route("PATCH", "")
    gh_data.edit_item(ISSUE, "o/r", title="Only this")
    assert json.loads(fake_gh.stdin[0]) == {"title": "Only this"}


def test_the_item_is_read_afresh_with_text_box_line_endings(fake_gh):
    fake_gh.route("repos/o/r/issues/7", {"title": "T", "body": "a\r\nb",
                                         "labels": [{"name": "bug"}],
                                         "assignees": [{"login": "bob"}]})
    now = gh_data.fetch_item_now(ISSUE, "o/r")
    assert (now.title, now.body, now.labels, now.assignees) == ("T", "a\nb", ["bug"], ["bob"])
    assert gh_data.fetch_item_now(ISSUE, "o/r").body == "a\nb"
    fake_gh.routes.clear()
    fake_gh.route("repos/o/r/issues/7", {"title": "T", "body": None})
    assert gh_data.fetch_item_now(ISSUE, "o/r").body == ""


def test_no_repository_is_an_error_and_sends_nothing(fake_gh):
    with pytest.raises(GhError):
        gh_data.change_item_labels(ISSUE, "", ["bug"], [])
    with pytest.raises(GhError):
        gh_data.fetch_item_now(ISSUE, "")
    assert fake_gh.calls == []


def test_assignable_users_and_label_names_are_sorted(fake_gh):
    fake_gh.route("assignees", [{"login": "zed"}, {"login": "Alice"}, {}])
    fake_gh.route("/labels", [{"name": "ui"}, {"name": "Bug"}])
    assert gh_data.fetch_assignable_users("o/r") == ["Alice", "zed"]
    assert gh_data.fetch_label_names("o/r") == ["Bug", "ui"]
    assert "repos/o/r/assignees?per_page=100&page=1" in fake_gh.calls[0][1]
    assert not fake_gh.called_with("isFork")


def _projects_reply(repo_projects, owner_projects, items, content_id="I_1"):
    return {"data": {"repository": {
        "projectsV2": {"nodes": repo_projects},
        "owner": {"projectsV2": {"nodes": owner_projects}},
        "issueOrPullRequest": {"id": content_id, "projectItems": {"nodes": items}},
    }}}


def test_projects_of_the_repository_and_its_owner(monkeypatch):
    seen = []
    p1 = {"id": "P1", "title": "Roadmap", "number": 1, "closed": False}
    p2 = {"id": "P2", "title": "Bugs", "number": 2, "closed": False}
    old = {"id": "P3", "title": "Old", "number": 3, "closed": True}
    monkeypatch.setattr(gh_data, "_graphql", lambda q, v=None: seen.append(v) or _projects_reply(
        [p1], [p1, p2, old], [{"id": "ITEM1", "project": old}]))
    got = gh_data.fetch_item_projects(ISSUE, "o/r")
    assert seen == [{"owner": "o", "name": "r", "number": 7}]
    assert got.content_id == "I_1"
    assert [p.title for p in got.available] == ["Bugs", "Roadmap"]   # closed left out
    assert [(p.title, p.item_id, p.closed) for p in got.current] == [("Old", "ITEM1", True)]


def test_projects_without_the_permission_say_which(monkeypatch):
    monkeypatch.setattr(gh_data, "_graphql", lambda q, v=None: {"data": {"repository": None},
        "errors": [{"message": "Your token has not been granted the required scopes to "
                    "execute this query. The 'projectsV2' field requires one of the "
                    "following scopes: ['read:project']"}]})
    with pytest.raises(MissingScope) as caught:
        gh_data.fetch_item_projects(ISSUE, "o/r")
    assert caught.value.scope == "project"


def test_a_missing_permission_is_said_even_with_the_item_found(monkeypatch):
    reply = _projects_reply([], [], [])
    reply["data"]["repository"]["projectsV2"] = None
    reply["errors"] = [{"type": "INSUFFICIENT_SCOPES", "message": "Your token has not been "
                        "granted the required scopes ... requires one of the following "
                        "scopes: ['read:project']"}]
    monkeypatch.setattr(gh_data, "_graphql", lambda q, v=None: reply)
    with pytest.raises(MissingScope):
        gh_data.fetch_item_projects(ISSUE, "o/r")


def test_projects_carry_their_owner(monkeypatch):
    p = {"id": "P1", "title": "R", "number": 1, "closed": False, "owner": {"login": "org"}}
    monkeypatch.setattr(gh_data, "_graphql", lambda q, v=None: _projects_reply([p], [], []))
    assert gh_data.fetch_item_projects(ISSUE, "o/r").available[0].owner == "org"


def test_projects_of_a_missing_item(monkeypatch):
    monkeypatch.setattr(gh_data, "_graphql", lambda q, v=None: {"data": {"repository": {
        "issueOrPullRequest": None}}})
    with pytest.raises(GhError, match="Couldn't find #7 in o/r"):
        gh_data.fetch_item_projects(ISSUE, "o/r")


def test_adding_and_removing_from_a_project(monkeypatch):
    seen = []
    monkeypatch.setattr(gh_data, "_graphql", lambda q, v=None: seen.append((q, v)) or {"data": {}})
    gh_data.add_to_project("P1", "I_1")
    gh_data.remove_from_project("P1", "ITEM1")
    assert "addProjectV2ItemById" in seen[0][0] and seen[0][1] == {"p": "P1", "c": "I_1"}
    assert "deleteProjectV2Item" in seen[1][0] and seen[1][1] == {"p": "P1", "i": "ITEM1"}


def test_a_failed_project_change_is_an_error(monkeypatch):
    monkeypatch.setattr(gh_data, "_graphql",
                        lambda q, v=None: {"errors": [{"message": "Resource not accessible"}]})
    with pytest.raises(GhError, match="Resource not accessible"):
        gh_data.add_to_project("P1", "I_1")


# ── Filters ─────────────────────────────────────────────────────────────


def test_filter_describe_and_args():
    f = ItemFilter(assignee="@me", author="bob", no_milestone=True, no_assignee=False)
    assert f.active and f.describe() == "assigned to me, opened by bob, no milestone"
    assert f.args() == ["--assignee", "@me", "--author", "bob"]
    assert f.search_terms() == ["no:milestone"]
    assert not ItemFilter().active and ItemFilter().describe() == ""


def test_issues_are_fetched_with_the_filter(fake_gh):
    fake_gh.route("issue list", [])
    gh_data.fetch_issues("o/r", item_filter=ItemFilter(assignee="alice", no_assignee=True))
    args = fake_gh.called_with("issue list")[0]
    assert args[args.index("--assignee") + 1] == "alice"
    assert args[args.index("--search") + 1] == "no:assignee"


def test_prs_combine_the_milestone_search_with_the_filter(fake_gh):
    fake_gh.route("pr list", [])
    gh_data.fetch_prs("o/r", milestone=gh_data.Milestone(2, "1.1"),
                      item_filter=ItemFilter(author="@me", no_assignee=True))
    args = fake_gh.called_with("pr list")[0]
    assert args.count("--search") == 1
    assert args[args.index("--search") + 1] == 'milestone:"1.1" no:assignee'
    assert args[args.index("--author") + 1] == "@me"


def test_no_filter_adds_nothing(fake_gh):
    fake_gh.route("issue list", [])
    gh_data.fetch_issues("o/r", item_filter=ItemFilter())
    args = fake_gh.called_with("issue list")[0]
    assert "--search" not in args and "--assignee" not in args


def _filter_frame(view=ghviewer.VIEW_ISSUES):
    f = SimpleNamespace(view_mode=view, item_filter=ItemFilter(), said=[], reloads=0)
    f._update_menu_checks = lambda: None
    f._tell = f.said.append
    f._reload_after_filter = lambda: setattr(f, "reloads", f.reloads + 1)
    f._set_item_filter = lambda new: Frame._set_item_filter(f, new)
    f._FILTER_PROMPTS = Frame._FILTER_PROMPTS
    return f


def test_assigned_to_me_turns_on_and_off():
    f = _filter_frame()
    Frame._filter_mine(f)
    assert f.item_filter.assignee == "@me" and f.reloads == 1
    Frame._filter_mine(f)
    assert f.item_filter.assignee == "" and f.reloads == 2


def test_opened_by_me_and_the_no_filters():
    f = _filter_frame()
    Frame._filter_my_own(f)
    Frame._filter_toggle(f, "no_milestone")
    Frame._filter_toggle(f, "no_assignee")
    assert f.item_filter == ItemFilter(author="@me", no_milestone=True, no_assignee=True)
    Frame._filter_clear(f)
    assert f.item_filter == ItemFilter()


class FakeTextEntry:
    answer = (None, "")

    def __init__(self, parent, prompt, title, value):
        self.value = value
        FakeTextEntry.seen = (prompt, title, value)
    def ShowModal(self): return FakeTextEntry.answer[0]
    def GetValue(self): return FakeTextEntry.answer[1]
    def Destroy(self): pass


def test_assigned_to_someone(monkeypatch):
    monkeypatch.setattr(ghviewer.wx, "TextEntryDialog", FakeTextEntry)
    FakeTextEntry.answer = (ghviewer.wx.ID_OK, " @alice ")
    f = _filter_frame()
    Frame._filter_ask(f, "assignee")
    assert f.item_filter.assignee == "alice"
    assert FakeTextEntry.seen[1] == "Assigned To"


@pytest.mark.parametrize("typed", ["@me", "me", "ME"])
def test_typing_me_means_you(monkeypatch, typed):
    monkeypatch.setattr(ghviewer.wx, "TextEntryDialog", FakeTextEntry)
    FakeTextEntry.answer = (ghviewer.wx.ID_OK, typed)
    f = _filter_frame()
    Frame._filter_ask(f, "author")
    assert f.item_filter.author == "@me"


def test_no_assignee_and_an_assignee_exclude_each_other(monkeypatch):
    f = _filter_frame()
    Frame._filter_mine(f)
    Frame._filter_toggle(f, "no_assignee")
    assert f.item_filter == ItemFilter(no_assignee=True)
    Frame._filter_mine(f)
    assert f.item_filter == ItemFilter(assignee="@me")
    monkeypatch.setattr(ghviewer.wx, "TextEntryDialog", FakeTextEntry)
    FakeTextEntry.answer = (ghviewer.wx.ID_OK, "bob")
    Frame._filter_toggle(f, "no_assignee")
    Frame._filter_ask(f, "assignee")
    assert f.item_filter == ItemFilter(assignee="bob")


def test_cancelling_a_people_filter_changes_nothing(monkeypatch):
    monkeypatch.setattr(ghviewer.wx, "TextEntryDialog", FakeTextEntry)
    FakeTextEntry.answer = (ghviewer.wx.ID_CANCEL, "x")
    f = _filter_frame()
    Frame._filter_ask(f, "author")
    assert f.item_filter == ItemFilter() and f.reloads == 0


def test_a_filter_set_elsewhere_says_it_waits_for_issues():
    f = _filter_frame(view=ghviewer.VIEW_BRANCHES)
    Frame._filter_mine(f)
    assert f.reloads == 0
    assert f.said == ["Issues & PRs will be filtered: assigned to me."]


# ── The flows ───────────────────────────────────────────────────────────


class FakeChecklistDialog:
    """Checks or unchecks the rows named in ``toggle``, then OK or Cancel."""
    toggle: list = []
    answer = None
    shown: list = []

    def __init__(self, parent, title, prompt, model, say=None):
        self.model = model
        FakeChecklistDialog.shown.append((title, prompt, model.rows()))
    def ShowModal(self):
        for name in FakeChecklistDialog.toggle:
            self.model.toggle(self.model.names.index(name))
        return FakeChecklistDialog.answer
    def Destroy(self): pass


@pytest.fixture
def edits(monkeypatch):
    run_now(monkeypatch)
    monkeypatch.setattr(ghviewer, "ChecklistDialog", FakeChecklistDialog)
    FakeChecklistDialog.shown, FakeChecklistDialog.toggle = [], []
    FakeChecklistDialog.answer = ghviewer.wx.ID_OK
    sent = []
    monkeypatch.setattr(ghviewer, "fetch_label_names", lambda repo: ["bug", "docs", "ui"])
    monkeypatch.setattr(ghviewer, "fetch_assignable_users", lambda repo: ["alice", "bob"])
    monkeypatch.setattr(ghviewer, "change_item_labels",
                        lambda item, repo, add, rem: sent.append(("labels", repo, add, rem)))
    monkeypatch.setattr(ghviewer, "change_item_assignees",
                        lambda item, repo, add, rem: sent.append(("assignees", repo, add, rem)))
    monkeypatch.setattr(ghviewer, "add_to_project",
                        lambda pid, cid: sent.append(("add", pid, cid)))
    monkeypatch.setattr(ghviewer, "remove_from_project",
                        lambda pid, iid: sent.append(("remove", pid, iid)))
    monkeypatch.setattr(ghviewer, "edit_item",
                        lambda item, repo, t, b: sent.append(("edit", repo, t, b)))
    # GitHub now: what a test puts in NOW, else the item as listed.
    NOW.clear()
    monkeypatch.setattr(ghviewer, "fetch_item_now", lambda item, repo: NOW.get(item.number) or
                        ItemNow(item.title, item.body, list(item.labels), list(item.assignees)))
    return sent


NOW: dict = {}


def _item(**kw):
    return Item(5, "Bug", "OPEN", "u", False, **kw)


def test_setting_labels(edits):
    item = _item(labels=["docs"])
    f = fake_frame(item)
    FakeChecklistDialog.toggle = ["bug", "docs"]
    Frame._set_labels_flow(f)
    title, prompt, rows = FakeChecklistDialog.shown[0]
    assert (title, prompt) == ("Set Labels", "Labels for #5 Bug")
    assert rows == ["bug, not checked", "docs, checked", "ui, not checked"]
    assert edits == [("labels", "o/r", ["bug"], ["docs"])]
    assert item.labels == ["bug"] and f.redrawn and f.details == [0]
    assert f.said == ["#5: added bug, removed docs. Labels now: bug."]
    assert f._item_edit_busy is False


def test_labels_cancelled_or_unchanged_send_nothing(edits):
    for answer, toggle in ((ghviewer.wx.ID_CANCEL, ["bug"]), (ghviewer.wx.ID_OK, [])):
        f = fake_frame(_item())
        FakeChecklistDialog.answer, FakeChecklistDialog.toggle = answer, toggle
        Frame._set_labels_flow(f)
        assert f.said == ["Labels unchanged."] and f._item_edit_busy is False
    assert edits == []


def test_a_repository_with_no_labels_says_so(edits, monkeypatch):
    monkeypatch.setattr(ghviewer, "fetch_label_names", lambda repo: [])
    f = fake_frame(_item())
    Frame._set_labels_flow(f)
    assert FakeChecklistDialog.shown == [] and f.said == ["o/r has no labels."]


def test_labels_on_a_fork_go_upstream(edits):
    f = fake_frame(_item(), repo="me/fork")
    FakeChecklistDialog.toggle = ["ui"]
    Frame._set_labels_flow(f)
    assert edits == [("labels", "up/r", ["ui"], [])]


def test_setting_assignees_keeps_one_who_cant_be_assigned_now(edits):
    item = _item(assignees=["zed"])
    f = fake_frame(item)
    FakeChecklistDialog.toggle = ["alice"]
    Frame._set_assignees_flow(f)
    assert FakeChecklistDialog.shown[0][2][-1] == "zed, checked"
    assert edits == [("assignees", "o/r", ["alice"], [])]
    assert item.assignees == ["alice", "zed"]
    assert f.said == ["#5: added alice. Assignees now: alice, zed."]


def test_a_failed_save_is_said_and_changes_nothing(edits, monkeypatch):
    def boom(*a):
        raise GhError("HTTP 422: too many assignees")
    monkeypatch.setattr(ghviewer, "change_item_assignees", boom)
    item = _item()
    f = fake_frame(item)
    FakeChecklistDialog.toggle = ["alice"]
    Frame._set_assignees_flow(f)
    assert item.assignees == [] and f.redrawn == []
    assert f.said == ["Couldn't change #5: HTTP 422: too many assignees"]
    assert f._item_edit_busy is False


PROJECTS = ItemProjects(
    "I_5",
    [Project("P1", "Roadmap", 1), Project("P2", "Bugs", 2), Project("P4", "Bugs", 4)],
    [Project("P2", "Bugs", 2, item_id="E2"), Project("P9", "Old", 9, True, item_id="E9")])


def test_projects_add_and_remove(edits, monkeypatch):
    monkeypatch.setattr(ghviewer, "fetch_item_projects", lambda item, repo: PROJECTS)
    f = fake_frame(_item())
    FakeChecklistDialog.toggle = ["Roadmap", "Bugs (#2)", "Old (closed)"]
    Frame._set_projects_flow(f)
    rows = FakeChecklistDialog.shown[0][2]
    assert rows == ["Roadmap, not checked", "Bugs (#2), checked", "Bugs (#4), not checked",
                    "Old (closed), checked"]
    assert edits == [("add", "P1", "I_5"), ("remove", "P2", "E2"), ("remove", "P9", "E9")]
    assert f.said == ["#5: added Roadmap, removed Bugs (#2), Old (closed). Projects now: Roadmap."]


def test_projects_without_permission_explain_it(edits, monkeypatch):
    def boom(item, repo):
        raise MissingScope("project")
    monkeypatch.setattr(ghviewer, "fetch_item_projects", boom)
    boxes = []
    monkeypatch.setattr(ghviewer.wx, "MessageBox", lambda msg, *a, **k: boxes.append(msg))
    f = fake_frame(_item())
    Frame._set_projects_flow(f)
    assert f.said == ["Couldn't get the projects of o/r: it needs gh's \"project\" permission."]
    assert "gh auth refresh -h github.com -s project" in boxes[0]
    assert f._item_edit_busy is False


def test_no_projects_says_so(edits, monkeypatch):
    monkeypatch.setattr(ghviewer, "fetch_item_projects",
                        lambda item, repo: ItemProjects("I_5", [], []))
    f = fake_frame(_item())
    Frame._set_projects_flow(f)
    assert f.said == ["o/r and its owner have no open projects."]


class FakeEditDialog:
    answer = (None, ("", ""))

    def __init__(self, parent, repo, item, title, body):
        FakeEditDialog.seen = (repo, title, body)
    def ShowModal(self): return FakeEditDialog.answer[0]
    def values(self): return FakeEditDialog.answer[1]
    def Destroy(self): pass


def test_editing_the_title_and_description(edits, monkeypatch):
    monkeypatch.setattr(ghviewer, "EditItemDialog", FakeEditDialog)
    FakeEditDialog.answer = (ghviewer.wx.ID_OK, ("Better title", "New body"))
    item = _item(body="Old body")
    f = fake_frame(item)
    Frame._edit_item_flow(f)
    assert FakeEditDialog.seen == ("o/r", "Bug", "Old body")
    assert edits == [("edit", "o/r", "Better title", "New body")]
    assert (item.title, item.body) == ("Better title", "New body")
    assert f.said == ["#5 saved."]


def test_the_form_starts_from_github_now_and_sends_only_the_title(edits, monkeypatch):
    # Someone changed the description on the web after the list loaded.
    monkeypatch.setattr(ghviewer, "EditItemDialog", FakeEditDialog)
    NOW[5] = ItemNow("Bug", "Their new body", [], [])
    FakeEditDialog.answer = (ghviewer.wx.ID_OK, ("Bug, fixed typo", "Their new body"))
    item = _item(body="Stale body")
    f = fake_frame(item)
    Frame._edit_item_flow(f)
    assert FakeEditDialog.seen == ("o/r", "Bug", "Their new body")
    assert edits == [("edit", "o/r", "Bug, fixed typo", None)]


def test_editing_with_no_change_sends_nothing(edits, monkeypatch):
    monkeypatch.setattr(ghviewer, "EditItemDialog", FakeEditDialog)
    FakeEditDialog.answer = (ghviewer.wx.ID_OK, ("Bug", "Body"))
    f = fake_frame(_item(body="Body\n\n"))
    Frame._edit_item_flow(f)
    assert edits == [] and f.said == ["Not changed."]


def test_labels_start_from_github_now(edits):
    # A bot added needs-info after the list loaded: shown checked, and kept.
    NOW[5] = ItemNow("Bug", "", ["needs-info"], [])
    item = _item()
    f = fake_frame(item)
    FakeChecklistDialog.toggle = ["bug"]
    Frame._set_labels_flow(f)
    assert "needs-info, checked" in FakeChecklistDialog.shown[0][2]
    assert edits == [("labels", "o/r", ["bug"], [])]
    assert item.labels == ["bug", "needs-info"]


def test_projects_the_item_is_in_elsewhere_keep_their_own_row(edits, monkeypatch):
    # In the user's own "Roadmap" while the repository's owner has one too.
    data = ItemProjects("I_5", [Project("ORG", "Roadmap", 1, owner="org")],
                        [Project("MINE", "Roadmap", 3, owner="me", item_id="E3")])
    monkeypatch.setattr(ghviewer, "fetch_item_projects", lambda item, repo: data)
    f = fake_frame(_item())
    FakeChecklistDialog.toggle = ["Roadmap (me, #3)"]
    Frame._set_projects_flow(f)
    assert FakeChecklistDialog.shown[0][2] == ["Roadmap (org, #1), not checked",
                                               "Roadmap (me, #3), checked"]
    assert edits == [("remove", "MINE", "E3")]
    assert f._item_edit_busy is False


def test_project_rows_are_unique_even_for_twins():
    twins = [Project("A", "Old", 2, True, owner="o", item_id="x"),
             Project("B", "Old", 2, True, owner="o", item_id="y")]
    names = [n for n, _ in Frame.project_rows([], twins)]
    assert len(set(names)) == 2


def test_an_unexpected_error_frees_the_next_change(edits, monkeypatch):
    def broken(repo):
        raise ValueError("bad JSON")
    monkeypatch.setattr(ghviewer, "fetch_label_names", broken)
    f = fake_frame(_item())
    Frame._set_labels_flow(f)
    assert f._item_edit_busy is False
    assert f.said == ["Couldn't get the labels of o/r: ValueError: bad JSON"]


def test_a_box_due_after_leaving_issues_is_dropped(edits, monkeypatch):
    f = fake_frame(_item())
    orig = ghviewer.fetch_label_names

    def leave(repo):
        f.view_mode = ghviewer.VIEW_BRANCHES
        return orig(repo)
    monkeypatch.setattr(ghviewer, "fetch_label_names", leave)
    Frame._set_labels_flow(f)
    assert FakeChecklistDialog.shown == [] and f._item_edit_busy is False


def test_a_reloaded_list_gets_the_change_too(edits):
    old = _item()
    f = fake_frame(old)
    fresh = _item()
    f._shown = [fresh]      # R pressed while the box was open
    FakeChecklistDialog.toggle = ["bug"]
    Frame._set_labels_flow(f)
    assert fresh.labels == ["bug"] and f.redrawn == [(0, "")]


def test_one_change_at_a_time(edits):
    f = fake_frame(_item())
    f._item_edit_busy = True
    for flow in (Frame._set_labels_flow, Frame._set_assignees_flow, Frame._set_projects_flow,
                 Frame._edit_item_flow, Frame._set_milestone_flow):
        flow(f)
    assert f.said == ["Still saving the last change."] * 5
    assert FakeChecklistDialog.shown == []


# ── Keys ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("key, action", [
    ("L", "_set_labels_flow"), ("A", "_set_assignees_flow"),
    ("P", "_set_projects_flow"), ("E", "_edit_item_flow"),
])
@pytest.mark.parametrize("focus", ["list", "details"])
def test_keys_in_issues_and_prs(key, action, focus):
    f = _hook_frame(ghviewer.VIEW_ISSUES, focus=focus, item=_item())
    Frame.on_char_hook(f, Key(ord(key)))
    assert f.calls == [action]


def test_e_in_workflow_runs_is_still_rerun():
    f = _hook_frame(ghviewer.VIEW_WORKFLOW)
    Frame.on_char_hook(f, Key(ord("E")))
    assert f.calls == ["_rerun_run"]


def test_keys_are_listed_in_keyboard_shortcuts():
    import commands
    keys = {(c.keys, c.where) for c in commands.LIST_KEYS}
    for k in "ILAPE":
        assert (k, commands.ISSUES) in keys
