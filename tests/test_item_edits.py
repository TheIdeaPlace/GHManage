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
from test_set_milestone import BOXES, fake_frame, run_now  # noqa: E402
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


def test_adding_a_new_one_checks_it_and_marks_it_new():
    c = Checklist(["bug"], [])
    assert c.add(" triage ") == (1, "triage added, checked")
    assert c.row(1) == "triage, checked, new" and c.to_create() == ["triage"]
    c.toggle(1)
    assert c.row(1) == "triage, not checked, new" and c.to_create() == []


def test_adding_one_already_listed_checks_it_instead():
    c = Checklist(["Bug"], [])
    assert c.add("bug") == (0, "Bug is already listed, now checked")
    assert c.names == ["Bug"] and c.chosen() == ["Bug"] and c.to_create() == []


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


def test_a_new_label_is_posted_light_grey(fake_gh):
    fake_gh.route("labels", "")
    gh_data.create_label_in("o/r", "needs info")
    assert fake_gh.calls[0][:4] == ["api", "-X", "POST", "repos/o/r/labels"]
    assert json.loads(fake_gh.stdin[0]) == {"name": "needs info", "color": "ededed"}


def test_a_label_that_already_exists_is_no_error(fake_gh):
    # GitHub's 422 doesn't say why; the label being there says it.
    fake_gh.route("-X POST", GhError("gh: Validation Failed (HTTP 422)"))
    fake_gh.route("repos/o/r/labels/needs%20info", {"name": "needs info"})
    gh_data.create_label_in("o/r", "needs info")


def test_a_422_for_another_reason_is_an_error(fake_gh):
    fake_gh.route("-X POST", GhError("gh: Validation Failed (HTTP 422)"))
    fake_gh.route("repos/o/r/labels/bad", GhError("HTTP 404"))
    with pytest.raises(GhError, match="422"):
        gh_data.create_label_in("o/r", "bad")


def test_a_new_milestone_is_posted_and_read_back(fake_gh):
    fake_gh.route("milestones", {"number": 3, "title": "0.6", "state": "open",
                                 "html_url": "https://github.com/o/r/milestone/3"})
    m = gh_data.create_milestone("o/r", "0.6")
    assert (m.number, m.title, m.repo) == (3, "0.6", "o/r")
    assert json.loads(fake_gh.stdin[0]) == {"title": "0.6"}
    assert "0.6" not in " ".join(fake_gh.calls[0])


def test_a_milestone_github_didnt_make_is_an_error(fake_gh):
    fake_gh.route("milestones", {})
    with pytest.raises(GhError, match="didn't create"):
        gh_data.create_milestone("o/r", "0.6")


def test_a_new_project_is_made_for_the_owner_linked_to_the_repository(monkeypatch):
    seen = []
    monkeypatch.setattr(gh_data, "_graphql", lambda q, v=None: seen.append((q, v)) or {
        "data": {"createProjectV2": {"projectV2": {"id": "PVT_new"}}}})
    assert gh_data.create_project("O_1", "R_1", "Board") == "PVT_new"
    assert "createProjectV2" in seen[0][0] and seen[0][1] == {"o": "O_1", "r": "R_1", "t": "Board"}


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
    add: list = []   # names New Label/Project adds before the toggles
    answer = None
    shown: list = []

    def __init__(self, parent, title, prompt, model, say=None, new_label="", new_prompt="",
                 note="", same_as=None):
        FakeChecklistDialog.note = note
        same_as = same_as or (lambda typed: [])
        FakeChecklistDialog.new = (new_label, new_prompt)
        for name in FakeChecklistDialog.add:   # as ChecklistDialog.add_new does
            same = same_as(name)
            if len(same) <= 1:
                model.add(same[0] if same else name)
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
    FakeChecklistDialog.add = []
    FakeChecklistDialog.answer = ghviewer.wx.ID_OK
    sent = []
    monkeypatch.setattr(ghviewer, "fetch_label_names", lambda repo, limit=100: ["bug", "docs", "ui"])
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


def test_a_repository_with_no_labels_still_opens_the_box(edits, monkeypatch):
    monkeypatch.setattr(ghviewer, "fetch_label_names", lambda repo, limit=100: [])
    f = fake_frame(_item())
    FakeChecklistDialog.answer = ghviewer.wx.ID_CANCEL
    Frame._set_labels_flow(f)
    title, prompt, rows = FakeChecklistDialog.shown[0]
    assert prompt == "Labels for #5 Bug" and rows == []
    assert FakeChecklistDialog.note == "o/r has no labels yet."
    assert FakeChecklistDialog.new == ("&New Label…", "Name of the new label in o/r:")


def test_a_new_label_is_created_then_added(edits, monkeypatch):
    created = []
    monkeypatch.setattr(ghviewer, "create_label_in",
                        lambda repo, name: created.append((repo, name)))
    item = _item()
    f = fake_frame(item)
    FakeChecklistDialog.add = ["triage"]
    Frame._set_labels_flow(f)
    assert created == [("o/r", "triage")]
    assert edits == [("labels", "o/r", ["triage"], [])]
    assert item.labels == ["triage"]
    assert f.said == ["Created triage. #5: added triage. Labels now: triage."]


def test_a_new_label_unchecked_again_is_not_created(edits, monkeypatch):
    monkeypatch.setattr(ghviewer, "create_label_in", lambda repo, name: pytest.fail("created"))
    f = fake_frame(_item())
    FakeChecklistDialog.add = ["triage"]
    FakeChecklistDialog.toggle = ["triage"]
    Frame._set_labels_flow(f)
    assert edits == [] and f.said == ["Labels unchanged."]




def test_no_one_to_assign_is_shown_in_a_box(edits, monkeypatch):
    monkeypatch.setattr(ghviewer, "fetch_assignable_users", lambda repo: [])
    f = fake_frame(_item())
    Frame._set_assignees_flow(f)
    assert BOXES == [("Set Assignees", "No one can be assigned in o/r.")]
    assert FakeChecklistDialog.shown == [] and f._item_edit_busy is False


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
    assert BOXES == [("Couldn't Do It", "Couldn't change #5.\n\nHTTP 422: too many assignees")]
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
    f = fake_frame(_item())
    Frame._set_projects_flow(f)
    assert f.announced[-1] == ("Couldn't get the projects of o/r: it needs gh's "
                               "\"project\" permission.")
    title, message = BOXES[0]
    assert title == "Permission Needed"
    assert "gh auth refresh -h github.com -s project" in message
    assert f._item_edit_busy is False


def test_no_projects_still_opens_the_box(edits, monkeypatch):
    monkeypatch.setattr(ghviewer, "fetch_item_projects",
                        lambda item, repo: ItemProjects("I_5", [], [], owner="org"))
    f = fake_frame(_item())
    FakeChecklistDialog.answer = ghviewer.wx.ID_CANCEL
    Frame._set_projects_flow(f)
    assert FakeChecklistDialog.note == "o/r and org have no open projects."
    assert FakeChecklistDialog.new == ("&New Project…", "Title of the new project, for org:")


def test_a_new_project_is_created_for_the_owner_and_the_item_added(edits, monkeypatch):
    made = []
    monkeypatch.setattr(ghviewer, "create_project",
                        lambda owner, repo_id, title: made.append((owner, repo_id, title)) or "NEW")
    monkeypatch.setattr(ghviewer, "fetch_item_projects", lambda item, repo: ItemProjects(
        "I_5", [Project("P1", "Roadmap", 1)], [], repo_id="R_1", owner_id="O_1", owner="org"))
    f = fake_frame(_item())
    FakeChecklistDialog.add = ["Triage board"]
    Frame._set_projects_flow(f)
    assert made == [("O_1", "R_1", "Triage board")]
    assert edits == [("add", "NEW", "I_5")]
    assert f.said == ["Created Triage board. #5: added Triage board. Projects now: Triage board."]


def test_adding_a_name_already_listed_checks_it_instead(edits, monkeypatch):
    monkeypatch.setattr(ghviewer, "create_project", lambda *a: pytest.fail("created"))
    monkeypatch.setattr(ghviewer, "fetch_item_projects", lambda item, repo: ItemProjects(
        "I_5", [Project("P1", "Roadmap", 1)], []))
    f = fake_frame(_item())
    FakeChecklistDialog.add = ["roadmap"]
    Frame._set_projects_flow(f)
    assert edits == [("add", "P1", "I_5")]


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
    def broken(repo, limit=100):
        raise ValueError("bad JSON")
    monkeypatch.setattr(ghviewer, "fetch_label_names", broken)
    f = fake_frame(_item())
    Frame._set_labels_flow(f)
    assert f._item_edit_busy is False
    assert BOXES[0][1] == "Couldn't get the labels of o/r.\n\nValueError: bad JSON"


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


@pytest.mark.parametrize("view", [ghviewer.VIEW_MY_WORK, ghviewer.VIEW_SEARCH_ISSUES])
@pytest.mark.parametrize("key, action", [
    ("I", "_set_milestone_flow"), ("L", "_set_labels_flow"), ("E", "_edit_item_flow"),
])
def test_keys_in_my_work_and_search_results(view, key, action):
    f = _hook_frame(view, item=_item())
    f._go_to_event_repo = lambda: f.calls.append("_go_to_event_repo")
    Frame.on_char_hook(f, Key(ord(key)))
    assert f.calls == [action]


def test_g_in_my_work_still_goes_to_the_repository():
    f = _hook_frame(ghviewer.VIEW_MY_WORK, item=_item())
    Frame.on_char_hook(f, Key(ord("G")))
    assert f.calls == ["_go_to_event_repo"]


def test_e_in_workflow_runs_is_still_rerun():
    f = _hook_frame(ghviewer.VIEW_WORKFLOW)
    Frame.on_char_hook(f, Key(ord("E")))
    assert f.calls == ["_rerun_run"]


def test_keys_are_listed_in_keyboard_shortcuts():
    import commands
    keys = {(c.keys, c.where) for c in commands.LIST_KEYS}
    for k in "ILAPE":
        assert (k, commands.ITEM_LISTS) in keys


# ── Second review ───────────────────────────────────────────────────────

from test_set_milestone import ACCESS  # noqa: E402


@pytest.mark.parametrize("view", [ghviewer.VIEW_MY_WORK, ghviewer.VIEW_SEARCH_ISSUES])
def test_an_item_in_a_fork_is_changed_in_the_fork_itself(edits, view):
    # From My Work or a search, the item's repository is exact; swapping a
    # fork for its upstream would change a different issue with that number.
    f = fake_frame(_item(repo="me/fork"), view=view)
    FakeChecklistDialog.toggle = ["bug"]
    Frame._set_labels_flow(f)
    assert edits == [("labels", "me/fork", ["bug"], [])]


def test_in_issues_and_prs_a_fork_still_means_its_upstream(edits):
    f = fake_frame(_item(), repo="me/fork")
    FakeChecklistDialog.toggle = ["bug"]
    Frame._set_labels_flow(f)
    assert edits == [("labels", "up/r", ["bug"], [])]


@pytest.mark.parametrize("flow, what", [
    (Frame._set_labels_flow, "the labels"), (Frame._set_assignees_flow, "the assignees"),
    (Frame._set_milestone_flow, "the milestone"),
])
def test_without_access_a_box_says_so_before_any_choices(edits, monkeypatch, flow, what):
    monkeypatch.setattr(ghviewer, "fetch_milestones", lambda *a, **k: [])
    monkeypatch.setattr(ghviewer.wx, "SingleChoiceDialog",
                        lambda *a, **k: pytest.fail("no choices without access"))
    ACCESS.add("o/r")
    f = fake_frame(_item())
    flow(f)
    assert BOXES == [("Can't Change It", f"You can't change {what} of #5: that needs "
                      "write or triage access to o/r.")]
    assert FakeChecklistDialog.shown == [] and edits == [] and f._item_edit_busy is False


def test_projects_and_edit_dont_ask_for_repository_access(edits, monkeypatch):
    # Projects have their own permissions, and an author may edit their own issue.
    monkeypatch.setattr(ghviewer, "fetch_item_projects",
                        lambda item, repo: ItemProjects("I_5", [Project("P1", "R", 1)], []))
    ACCESS.add("o/r")
    f = fake_frame(_item())
    FakeChecklistDialog.answer = ghviewer.wx.ID_CANCEL
    Frame._set_projects_flow(f)
    assert FakeChecklistDialog.shown and BOXES == []


def test_typing_an_existing_project_title_checks_it(edits, monkeypatch):
    monkeypatch.setattr(ghviewer, "create_project", lambda *a: pytest.fail("duplicate made"))
    data = ItemProjects("I_5", [Project("A", "Roadmap", 1, owner="org"),
                                Project("B", "Board", 2, owner="org")], [])
    monkeypatch.setattr(ghviewer, "fetch_item_projects", lambda item, repo: data)
    f = fake_frame(_item())
    FakeChecklistDialog.add = ["ROADMAP"]
    Frame._set_projects_flow(f)
    assert edits == [("add", "A", "I_5")]


def test_typing_a_title_two_projects_share_adds_nothing(edits, monkeypatch):
    monkeypatch.setattr(ghviewer, "create_project", lambda *a: pytest.fail("duplicate made"))
    data = ItemProjects("I_5", [Project("A", "Roadmap", 1, owner="org"),
                                Project("B", "Roadmap", 2, owner="me")], [])
    monkeypatch.setattr(ghviewer, "fetch_item_projects", lambda item, repo: data)
    f = fake_frame(_item())
    FakeChecklistDialog.add = ["Roadmap"]
    Frame._set_projects_flow(f)
    assert edits == [] and f.said == ["Projects unchanged."]


def test_a_failure_after_making_a_project_says_it_was_made(edits, monkeypatch):
    monkeypatch.setattr(ghviewer, "create_project", lambda *a: "NEW")

    def refuse(pid, cid):
        raise GhError("Resource not accessible")
    monkeypatch.setattr(ghviewer, "add_to_project", refuse)
    monkeypatch.setattr(ghviewer, "fetch_item_projects", lambda item, repo: ItemProjects(
        "I_5", [], [], repo_id="R", owner_id="O", owner="org"))
    f = fake_frame(_item())
    FakeChecklistDialog.add = ["Board"]
    Frame._set_projects_flow(f)
    assert BOXES[0][1] == ("Couldn't change #5.\n\nCreated Board, then: "
                           "Resource not accessible")


def test_a_dropped_milestone_change_is_an_error(fake_gh):
    # No write access: GitHub answers 200 with the issue unchanged.
    fake_gh.route("PATCH", {"number": 7, "milestone": None})
    with pytest.raises(gh_data.NotChanged, match="write access to o/r"):
        gh_data.set_item_milestone(ISSUE, "o/r", gh_data.Milestone(2, "1.0"))


def test_a_milestone_change_github_made_is_fine(fake_gh):
    fake_gh.route("PATCH", {"number": 7, "milestone": {"number": 2}})
    gh_data.set_item_milestone(ISSUE, "o/r", gh_data.Milestone(2, "1.0"))
    fake_gh.routes.clear()
    fake_gh.route("PATCH", {"number": 7, "milestone": None})
    gh_data.set_item_milestone(ISSUE, "o/r", None)


def test_assignees_github_ignored_are_an_error(fake_gh):
    fake_gh.route("assignees", {"number": 7, "assignees": [{"login": "bob"}]})
    with pytest.raises(gh_data.NotChanged):
        gh_data.change_item_assignees(ISSUE, "o/r", ["alice"], [])
    with pytest.raises(gh_data.NotChanged):
        gh_data.change_item_assignees(ISSUE, "o/r", [], ["bob"])


def test_assignees_github_took_are_fine(fake_gh):
    fake_gh.route("POST", {"number": 7, "assignees": [{"login": "Alice"}]})
    fake_gh.route("DELETE", {"number": 7, "assignees": [{"login": "Alice"}]})
    gh_data.change_item_assignees(ISSUE, "o/r", ["alice"], ["bob"])


@pytest.mark.parametrize("perms, ok", [
    ({"admin": False, "maintain": False, "push": False, "triage": True, "pull": True}, True),
    ({"admin": False, "maintain": False, "push": False, "triage": False, "pull": True}, False),
    (None, True),
])
def test_who_can_change_items(fake_gh, perms, ok):
    fake_gh.route("repos/o/r", perms if perms is not None else "")
    assert gh_data.can_change_items("o/r") is ok


def test_access_unknown_when_github_wont_say(fake_gh):
    fake_gh.route("repos/o/r", GhError("HTTP 500"))
    assert gh_data.can_change_items("o/r") is True
