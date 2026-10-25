"""Controls are named for screen readers on a Mac too (#69).

wx's SetName reaches nothing native on a Mac, so ghviewer names controls
through ``_name``, which also has ``speech.set_label`` put the name on the
native view. The first tests run anywhere; the rest build hidden controls
and real dialogs and read each name back from AppKit, so they run on macOS
only (CI's build-macos job runs them).
"""

from __future__ import annotations

import ctypes
import os
import sys

import pytest

if os.environ.get("CI"):
    import wx
else:
    wx = pytest.importorskip("wx")

import ghviewer  # noqa: E402
import speech  # noqa: E402
from commands import Command  # noqa: E402
from gh_columns import COMMIT_SET, TAG_SET  # noqa: E402
from gh_data import WorkflowInput  # noqa: E402

mac = pytest.mark.skipif(sys.platform != "darwin", reason="AppKit labels are macOS only")
not_mac = pytest.mark.skipif(sys.platform == "darwin", reason="checks the other platforms")


class _Named:
    """Stands in for a control: records SetName and has no native view."""

    def __init__(self) -> None:
        self.names: list[str] = []

    def SetName(self, name: str) -> None:
        self.names.append(name)

    def GetHandle(self) -> int:
        return 0


# ── Anywhere ────────────────────────────────────────────────────────────


def test_name_sets_the_name_and_the_mac_label(monkeypatch):
    labelled = []
    monkeypatch.setattr(speech, "set_label", lambda ctrl, label: labelled.append((ctrl, label)))
    ctrl = _Named()
    ghviewer._name(ctrl, "Search for")
    assert ctrl.names == ["Search for"]
    assert labelled == [(ctrl, "Search for")]


def test_name_is_set_whatever_set_label_manages():
    ctrl = _Named()  # no native view, so set_label can do nothing with it
    ghviewer._name(ctrl, "Preview")
    assert ctrl.names == ["Preview"]


@not_mac
def test_set_label_is_a_quiet_false_off_macos():
    ctrl = _Named()
    assert speech.set_label(ctrl, "Preview") is False
    assert speech.set_label(object(), "Preview") is False  # no GetHandle at all
    assert speech.get_label(ctrl) is None


def test_set_label_refuses_an_empty_label_or_no_view():
    assert speech.set_label(_Named(), "") is False
    assert speech.set_label(_Named(), "Preview") is False
    assert speech.get_label(_Named()) is None


# ── On a Mac ────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def frame():
    app = wx.App(False)
    f = wx.Frame(None)  # never shown
    yield f
    f.Destroy()
    app.Destroy()


def _labelled_controls(window: wx.Window) -> list[wx.Window]:
    """Every text box, list box and choice in ``window``, at any depth:
    the controls whose names VoiceOver couldn't read before #69."""
    found = []
    for child in window.GetChildren():
        if isinstance(child, (wx.TextCtrl, wx.ListBox, wx.Choice)):
            found.append(child)
        found += _labelled_controls(child)
    return found


def _is_kind_of(view, class_name: str) -> bool:
    return bool(speech._send(view, "isKindOfClass:", ctypes.c_void_p(speech._class(class_name)),
                             restype=ctypes.c_bool, argtypes=(ctypes.c_void_p,)))


# The AppKit view each control's label has to be on: the one VoiceOver lands
# on. get_label reads back through the same _target_view as set_label, so
# without this a change in what wx's GetHandle() returns would put the label
# on a scroll view VoiceOver never focuses and still pass.
VIEW_CLASSES = {
    "Search": "NSTextField",
    "Description": "NSTextView",
    "Hidden repositories": "NSTableView",
    "List to change": "NSPopUpButton",
    "Issues": "NSTableView",  # an NSOutlineView, which is one
}


@mac
def test_each_kind_of_control_reads_its_name(frame):
    controls = {
        "Search": wx.TextCtrl(frame),
        "Description": wx.TextCtrl(frame, style=wx.TE_MULTILINE),
        "Hidden repositories": wx.ListBox(frame, choices=["a/b", "c/d"]),
        "List to change": wx.Choice(frame, choices=["Commits", "Tags"]),
        "Issues": ghviewer.ItemList(frame),
    }
    for label, ctrl in controls.items():
        ghviewer._name(ctrl, label)
    try:
        for label, ctrl in controls.items():
            assert speech.get_label(ctrl) == label, type(ctrl).__name__
            assert _is_kind_of(speech._target_view(ctrl), VIEW_CLASSES[label]), label
        # Renaming, as the item list is on every view change, replaces it.
        ghviewer._name(controls["Issues"], "Branches")
        assert speech.get_label(controls["Issues"]) == "Branches"
    finally:
        for ctrl in controls.values():
            ctrl.Destroy()


@mac
def test_the_item_list_is_labelled_when_made(frame):
    ctrl = ghviewer.ItemList(frame, name="Issues")
    try:
        assert speech.get_label(ctrl) == "Issues"
    finally:
        ctrl.Destroy()


def _dialogs(frame):
    sets = [COMMIT_SET, TAG_SET]
    return {
        "Search": lambda: ghviewer.SearchDialog(frame),
        "Search Qualifiers": lambda: ghviewer.SearchQualifiersDialog(frame, ghviewer.KIND_ISSUES),
        "Columns": lambda: ghviewer.ColumnsDialog(
            frame, sets, COMMIT_SET.id, {s.id: list(s.defaults) for s in sets}, False, None),
        "Hidden Repositories": lambda: ghviewer.HiddenReposDialog(frame, ["a/b"], lambda n: None),
        "New Issue": lambda: ghviewer.NewIssueDialog(frame, "owner/name"),
        "New Label": lambda: ghviewer.NewLabelDialog(frame, "owner/name"),
        "Review": lambda: ghviewer.ReviewDialog(frame, "PR #1"),
        "Command Palette": lambda: ghviewer.CommandListDialog(
            frame, "Command Palette", [Command("Quit", "Ctrl+Q", "File", 1)],
            (("Command", 330), ("Shortcut", 150)), lambda c: (c.name, c.keys), palette=True),
        "Delete Repository": lambda: ghviewer.DeleteRepoDialog(frame, "owner/name"),
        "Run workflow": lambda: ghviewer.WorkflowInputsDialog(frame, "CI", "main", [
            WorkflowInput("level", "choice", "Log level", "info", True, ["info", "debug"]),
            WorkflowInput("note", "string", "A note"),
        ]),
    }


@pytest.mark.parametrize("which", list(_dialogs(None)))
def test_every_text_box_list_and_choice_in_a_dialog_is_named(frame, which):
    """Anywhere: none is left with wx's default name ("text", "listBox",
    "choice", "listCtrl"), which is what a control made without _name has."""
    dlg = _dialogs(frame)[which]()
    try:
        controls = _labelled_controls(dlg) + [
            w for w in dlg.GetChildren() if isinstance(w, wx.ListCtrl)]
        assert controls
        defaults = {wx.TextCtrlNameStr, wx.ListBoxNameStr, wx.ChoiceNameStr,
                    wx.ListCtrlNameStr}
        assert [c.GetName() for c in controls if c.GetName() in defaults] == []
    finally:
        dlg.Destroy()


@mac
@pytest.mark.parametrize("which", list(_dialogs(None)))
def test_every_named_control_in_a_dialog_reads_its_name(frame, which):
    dlg = _dialogs(frame)[which]()
    try:
        controls = _labelled_controls(dlg)
        assert controls
        for ctrl in controls:
            assert speech.get_label(ctrl) == ctrl.GetName(), (which, ctrl.GetName())
    finally:
        dlg.Destroy()
