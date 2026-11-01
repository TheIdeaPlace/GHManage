"""Actions ▸ Copy: what each kind of item puts on the clipboard."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

if os.environ.get("CI"):
    import wx  # noqa: F401
else:
    pytest.importorskip("wx")

import ghviewer  # noqa: E402
from favorites import FavoriteEntry  # noqa: E402
from gh_data import (  # noqa: E402
    ActivityEvent, Artifact, Branch, ChangedFile, Commit, Item, Label, PagesBuild, PagesFile,
    Release, ReleaseAsset, RepoEntry, Tag, Workflow, WorkflowRun,
)

Frame = ghviewer.GhViewerFrame
copy_values = ghviewer.copy_values
URL = "https://github.com/o/r/issues/12"


def test_issue_values():
    v = copy_values(Item(12, "Fix the thing", "open", URL, False))
    assert v.link == URL
    assert v.ident == "#12"
    assert v.ident_noun == "Number"
    assert v.title == "Fix the thing"
    assert v.markdown == f"[#12 Fix the thing]({URL})"


def test_markdown_escapes_brackets_in_the_title():
    v = copy_values(Item(3, r"Crash in [parser] \ lexer", "open", URL, False))
    assert v.markdown == rf"[#3 Crash in \[parser\] \\ lexer]({URL})"


def test_commit_copies_the_full_sha_and_first_line():
    c = Commit("a" * 40, "aaaaaaa", "Fix it\n\nLong body", "me", "", url="u")
    v = copy_values(c)
    assert v.ident == "a" * 40
    assert v.ident_noun == "SHA"
    assert v.title == "Fix it"
    assert v.markdown == "[aaaaaaa Fix it](u)"


def test_release_text_names_tag_and_title_once_each():
    assert copy_values(Release("v1", "One", False, False, "", url="u")).markdown == "[v1 One](u)"
    assert copy_values(Release("v1", "v1", False, False, "", url="u")).markdown == "[v1](u)"
    assert copy_values(Release("v1", "", False, False, "", url="u")).title == "v1"


def test_artifact_has_no_link_so_no_markdown():
    v = copy_values(Artifact(1, "build", 10, False, "", 9))
    assert v.link == ""
    assert v.markdown == ""
    assert v.ident == "build"


@pytest.mark.parametrize("item, ident, noun", [
    (Branch("main", "s", "m", "a", "d", url="u"), "main", "Branch Name"),
    (Tag("v2", "s", url="u"), "v2", "Tag"),
    (ReleaseAsset(1, "a.exe", 1, 1, "", url="u"), "a.exe", "File Name"),
    (Workflow(1, "CI", ".github/workflows/ci.yml", "active", url="u"),
     ".github/workflows/ci.yml", "File Path"),
    (WorkflowRun("CI", "completed", "success", "main", "push", "", url="u",
                 run_number=4, run_id=99), "99", "Run ID"),
    (Label("bug", url="u"), "bug", "Label Name"),
    (PagesBuild(1, "built", "abc123", "me", "", url="u"), "abc123", "Commit"),
    (PagesFile("docs/index.md", "u"), "docs/index.md", "Path"),
    (RepoEntry("o/r", url="u"), "o/r", "Repository Name"),
    (FavoriteEntry("o/r", "issue", "u", "#4 — T"), "#4 — T", "Name"),
], ids=lambda x: type(x).__name__ if not isinstance(x, str) else "")
def test_ident_per_kind(item, ident, noun):
    v = copy_values(item)
    assert (v.ident, v.ident_noun) == (ident, noun)
    assert v.link == "u"


# One item of the kind each view lists.
VIEW_SAMPLES = {
    ghviewer.VIEW_ISSUES: Item(1, "T", "open", "u", False),
    ghviewer.VIEW_BRANCHES: Branch("main", "s", "m", "a", "d", url="u"),
    ghviewer.VIEW_COMMITS: Commit("a" * 40, "aaaaaaa", "m", "me", "", url="u"),
    ghviewer.VIEW_TAGS: Tag("v1", "s", url="u"),
    ghviewer.VIEW_RELEASES: Release("v1", "One", False, False, "", url="u"),
    ghviewer.VIEW_WORKFLOWS: Workflow(1, "CI", "ci.yml", "active", url="u"),
    ghviewer.VIEW_WORKFLOW: WorkflowRun("CI", "", "", "", "", "", url="u", run_id=3),
    ghviewer.VIEW_ARTIFACTS: Artifact(1, "build", 10, False, "", 9),
    ghviewer.VIEW_ASSETS: ReleaseAsset(1, "a.exe", 1, 1, "", url="u"),
    ghviewer.VIEW_FILES: ChangedFile("docs/a.md", url="u"),
    ghviewer.VIEW_CODE: ghviewer.RepoFile("docs/a.md", url="u"),
    ghviewer.VIEW_HISTORY: Commit("a" * 40, "aaaaaaa", "m", "me", "", url="u"),
    ghviewer.VIEW_LABELS: Label("bug", url="u"),
    ghviewer.VIEW_FAVORITES: FavoriteEntry("o/r", "issue", "u", "#4 — T"),
    ghviewer.VIEW_PAGES: PagesBuild(1, "built", "abc", "me", "", url="u"),
    ghviewer.VIEW_PAGEFILES: PagesFile("index.md", "u"),
    ghviewer.VIEW_STARRED: RepoEntry("o/r", url="u"),
    ghviewer.VIEW_WATCHED: RepoEntry("o/r", url="u"),
    ghviewer.VIEW_ORGS: ghviewer.OrgEntry("o"),
    ghviewer.VIEW_ORG: RepoEntry("o/r", url="u"),
    ghviewer.VIEW_SHARED: RepoEntry("o/r", url="u"),
    ghviewer.VIEW_JOBS: ghviewer.WorkflowJob(5, "build", url="u"),
    ghviewer.VIEW_MY_WORK: Item(1, "T", "open", "u", False, repo="o/r", why="assigned"),
    ghviewer.VIEW_SEARCH_ISSUES: Item(1, "T", "open", "u", False, repo="o/r"),
    ghviewer.VIEW_SEARCH_REPOS: RepoEntry("o/r", url="u"),
    ghviewer.VIEW_DISCUSSIONS: ghviewer.Discussion(3, "T", url="u"),
    ghviewer.VIEW_MILESTONES: ghviewer.Milestone(3, "v1", url="u"),
    ghviewer.VIEW_INSIGHTS: ghviewer.InsightRow("Contributor", "kelly", 3, url="u"),
    ghviewer.VIEW_GISTS: ghviewer.Gist("abc", "Notes", url="u"),
    ghviewer.VIEW_PEOPLE: ghviewer.Person("alice", name="Alice", url="u"),
    ghviewer.VIEW_USER_REPOS: RepoEntry("o/r", url="u"),
}


def test_every_view_has_a_noun():
    assert set(Frame._COPY_IDENT_NOUNS) == set(ghviewer.VIEW_COLUMNS)
    # These three mix kinds of thing, each with its own noun; the menu names them all.
    mixed = {ghviewer.VIEW_ACTIVITY, ghviewer.VIEW_NOTIFICATIONS, ghviewer.VIEW_SECURITY}
    assert set(VIEW_SAMPLES) | mixed == set(ghviewer.VIEW_COLUMNS)


@pytest.mark.parametrize("view", sorted(VIEW_SAMPLES))
def test_menu_noun_matches_what_the_view_copies(view):
    # The menu label is chosen by view, the copied value by item; they
    # must name the same thing.
    assert Frame._COPY_IDENT_NOUNS[view] == copy_values(VIEW_SAMPLES[view]).ident_noun


def test_activity_noun_covers_every_kind_of_event():
    label = Frame._COPY_IDENT_NOUNS[ghviewer.VIEW_ACTIVITY]
    for noun in ("Number", "Tag", "Repository"):
        assert noun in label


def test_spoken_noun_keeps_acronyms():
    assert ghviewer.CopyValues(ident_noun="SHA").spoken_noun == "SHA"
    assert ghviewer.CopyValues(ident_noun="Run ID").spoken_noun == "run ID"
    assert ghviewer.CopyValues(ident_noun="Branch Name").spoken_noun == "branch name"


def test_run_without_an_id_has_nothing_to_copy():
    assert copy_values(WorkflowRun("CI", "", "", "", "", "")).ident == ""


def test_pages_build_text_names_the_commit():
    v = copy_values(PagesBuild(1, "built", "abcdef123", "me", "", url="u"))
    assert v.markdown == "[abcdef1 built](u)"


def test_activity_release_event_copies_the_tag():
    ev = ActivityEvent("ReleaseEvent", "bob", "o/r", "published release v2.0", title="Big",
                       url="https://github.com/o/r/releases/tag/v2.0", subject_kind="release",
                       subject_url="https://github.com/o/r/releases/tag/v2.0")
    v = copy_values(ev)
    assert (v.ident, v.ident_noun) == ("v2.0", "Tag")
    assert v.markdown == "[v2.0 Big](https://github.com/o/r/releases/tag/v2.0)"


def test_activity_event_about_an_issue_copies_the_issue():
    ev = ActivityEvent("IssuesEvent", "bob", "o/r", "opened issue #7", title="Bug",
                       url="https://github.com/o/r/issues/7#c", subject_kind="issue",
                       number=7, subject_url="https://github.com/o/r/issues/7")
    v = copy_values(ev)
    assert v.link == "https://github.com/o/r/issues/7"
    assert v.ident == "#7"
    assert v.markdown == "[#7 Bug](https://github.com/o/r/issues/7)"


def test_activity_event_about_a_repo_copies_the_repo():
    ev = ActivityEvent("WatchEvent", "bob", "o/r", "starred", url="https://github.com/o/r")
    v = copy_values(ev)
    assert v.ident == "o/r"
    assert v.ident_noun == "Repository Name"
    assert v.markdown == "[bob starred o/r](https://github.com/o/r)"


def test_unknown_item_gives_none():
    assert copy_values(object()) is None


def test_repo_copy_values():
    v = ghviewer.repo_copy_values("o/r")
    assert v.link == "https://github.com/o/r"
    assert v.markdown == "[o/r](https://github.com/o/r)"


# ── The command itself ────────────────────────────────────────────────


class FakeText:
    def __init__(self, value=""):
        self.value = value

    def GetValue(self):
        return self.value


def _frame(item=None, details="", focus=None):
    announced: list[str] = []
    clipboard: list[str] = []
    frame = SimpleNamespace(
        details_text=FakeText(details),
        repo_list=object(),
        _announce=announced.append,
        announced=announced,
        clipboard=clipboard,
        _focused_item=lambda: item,
        _current_focus=lambda: focus,
        _set_clipboard=lambda text: clipboard.append(text) or True,
        _COPY_WHAT=Frame._COPY_WHAT,
    )
    frame._copy_target = lambda: Frame._copy_target(frame)
    frame._pane_index = lambda w: 0 if w is not None and w is frame.repo_list else None
    return frame


@pytest.mark.parametrize("what, expected", [
    ("link", URL),
    ("markdown", f"[#12 Fix]({URL})"),
    ("title", "Fix"),
    ("ident", "#12"),
])
def test_copy_puts_the_value_on_the_clipboard(what, expected):
    f = _frame(Item(12, "Fix", "open", URL, False))
    Frame._copy(f, what)
    assert f.clipboard == [expected]
    assert expected in f.announced[-1]


def test_copy_details_copies_the_panel():
    f = _frame(details="All of it\nline two")
    Frame._copy(f, "details")
    assert f.clipboard == ["All of it\nline two"]
    assert f.announced[-1] == "Copied details."


def test_copy_with_nothing_selected_says_so():
    f = _frame(None)
    Frame._copy(f, "link")
    assert f.clipboard == []
    assert f.announced == ["Nothing selected to copy."]


def test_copy_link_of_an_artifact_says_there_is_none():
    f = _frame(Artifact(1, "build", 10, False, "", 9))
    Frame._copy(f, "link")
    assert f.clipboard == []
    assert f.announced == ["This item has no link to copy."]


def test_copy_from_the_repo_list_copies_the_repository():
    class RepoList:
        def GetSelection(self): return 2
        def GetClientData(self, i): return "o/r"
    rl = RepoList()
    f = _frame(Item(12, "Fix", "open", URL, False), focus=rl)
    f.repo_list = rl
    Frame._copy(f, "link")
    assert f.clipboard == ["https://github.com/o/r"]


def test_copy_from_a_category_entry_copies_nothing():
    class RepoList:
        def GetSelection(self): return 0
        def GetClientData(self, i): return ghviewer.FAVORITES_ENTRY
    rl = RepoList()
    f = _frame(focus=rl)
    f.repo_list = rl
    Frame._copy(f, "link")
    assert f.clipboard == []


def test_copy_sha_is_announced_as_an_acronym():
    f = _frame(Commit("a" * 40, "aaaaaaa", "m", "me", ""))
    Frame._copy(f, "ident")
    assert f.announced[-1].startswith("Copied SHA: ")


def test_category_entry_explains_why_nothing_was_copied():
    class RepoList:
        def GetSelection(self): return 0
        def GetClientData(self, i): return ghviewer.ACTIVITY_ENTRY
    rl = RepoList()
    f = _frame(focus=rl)
    f.repo_list = rl
    Frame._copy(f, "title")
    assert f.announced == ["That entry is not a repository — nothing to copy."]


@pytest.mark.skipif(not ghviewer.IS_MAC, reason="the macOS table only")
def test_mac_item_list_accepts_row_numbers():
    import wx
    app = wx.App(False)  # noqa: F841
    frame = wx.Frame(None)
    try:
        lst = ghviewer.ItemList(frame)
        lst.InsertColumn(0, "a")
        for i in range(3):
            lst.InsertItem(i, str(i))
        lst.EnsureVisible(2)          # a row number, as wx.ListCtrl takes
        lst.EnsureVisible(99)         # out of range: ignored, not an error
        lst.EnsureVisible(lst.RowToItem(1))  # an item still works
    finally:
        frame.Destroy()


# ── Clone URLs (#50) ───────────────────────────────────────────────────


def test_clone_urls():
    assert ghviewer.clone_url("o/r") == "https://github.com/o/r.git"
    assert ghviewer.clone_url("o/r", "ssh") == "git@github.com:o/r.git"


@pytest.mark.parametrize("kind, expected, noun", [
    ("https", "https://github.com/nvaccess/nvda.git", "HTTPS clone URL"),
    ("ssh", "git@github.com:nvaccess/nvda.git", "SSH clone URL"),
])
def test_copy_clone_url_of_the_repository_in_front(kind, expected, noun):
    f = _frame()
    f._repo_in_front = lambda: "nvaccess/nvda"
    Frame._copy_clone_url(f, kind)
    assert f.clipboard == [expected]
    assert f.announced == [f"Copied {noun}: {expected}"]


def test_copy_clone_url_with_no_repository_says_so():
    f = _frame()
    f._repo_in_front = lambda: None
    Frame._copy_clone_url(f, "https")
    assert f.clipboard == [] and "Select a repository first" in f.announced[0]
