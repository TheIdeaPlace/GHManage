"""Help ▸ Keyboard Shortcuts (#3) and the command palette (#27)."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import commands
from commands import Command

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("label, expected", [
    ("Refresh (R)\tCtrl+R", ("Refresh (R)", "Ctrl+R")),
    ("Re&view… (V)", ("Review… (V)", "")),
    ("Issues && PRs\tCtrl+1", ("Issues & PRs", "Ctrl+1")),
    ("&Checks (K)", ("Checks (K)", "")),
])
def test_split_label(label, expected):
    assert commands.split_label(label) == expected


CMDS = [
    Command("Open on GitHub", "Ctrl+O", "Actions"),
    Command("Copy Link", "Ctrl+Shift+C", "Actions > Copy"),
    Command("Refresh (R)", "Ctrl+R", "File"),
    Command("Issues & PRs", "Ctrl+1", "View > View Mode", checked=True),
]


def test_empty_filter_keeps_menu_order():
    assert commands.matching(CMDS, "  ") == CMDS


def test_every_word_must_match_somewhere():
    assert commands.matching(CMDS, "copy link") == [CMDS[1]]
    assert commands.matching(CMDS, "view mode") == [CMDS[3]]   # the menu path counts
    assert commands.matching(CMDS, "ctrl+r") == [CMDS[2]]       # and the shortcut
    assert commands.matching(CMDS, "copy refresh") == []


def test_names_that_start_with_the_text_come_first():
    rows = [Command("Search This Repository"), Command("Reopen"), Command("Close")]
    assert [c.name for c in commands.matching(rows, "re")] == ["Reopen", "Search This Repository"]


def test_shortcut_rows_are_list_keys_then_menu_commands_with_keys():
    rows = commands.shortcut_rows([Command("Merge…", "", "Actions"), CMDS[0]])
    assert rows[:len(commands.LIST_KEYS)] == commands.LIST_KEYS
    assert rows[len(commands.LIST_KEYS):] == [CMDS[0]]


def test_every_list_key_has_a_key_a_name_and_a_place():
    for c in commands.LIST_KEYS:
        assert c.name and c.keys and c.where and c.id == 0


def test_list_letters_are_the_ones_the_handlers_act_on():
    # LIST_KEYS is kept by hand; catch a letter added to a handler and not here.
    src = (ROOT / "ghviewer.py").read_text(encoding="utf-8")
    handled = set(re.findall(r'ord\("([A-Z])"\)', src))
    listed = {c.keys for c in commands.LIST_KEYS if len(c.keys) == 1}
    assert handled <= listed, handled - listed


# ── The frame's side: walking the menu bar ──────────────────────────────

if os.environ.get("CI"):
    import wx  # noqa: F401
else:
    pytest.importorskip("wx")

import ghviewer  # noqa: E402

Frame = ghviewer.GhViewerFrame


class FakeItem:
    def __init__(self, id=0, label="", enabled=True, sep=False, sub=None,
                 checkable=False, checked=False):
        self.id, self.label, self.enabled, self.sep, self.sub = id, label, enabled, sep, sub
        self.checkable, self.checked = checkable, checked

    def IsSeparator(self): return self.sep
    def IsEnabled(self): return self.enabled
    def GetSubMenu(self): return self.sub
    def GetItemLabel(self): return self.label
    def GetId(self): return self.id
    def IsCheckable(self): return self.checkable
    def IsChecked(self): return self.checked


class FakeMenu:
    def __init__(self, *items): self.items = list(items)
    def GetMenuItems(self): return self.items


class FakeMenuBar:
    def __init__(self, *menus): self.menus = list(menus)
    def GetMenuCount(self): return len(self.menus)
    def GetMenu(self, i): return self.menus[i][1]
    def GetMenuLabelText(self, i): return self.menus[i][0]


def _frame():
    bar = FakeMenuBar(
        ("File", FakeMenu(FakeItem(1, "&Refresh (R)\tCtrl+R"), FakeItem(sep=True),
                          FakeItem(2, "Quit\tCtrl+Q"))),
        ("Actions", FakeMenu(
            FakeItem(3, "Close Issue/PR (C)\tCtrl+W", enabled=False),
            FakeItem(4, "Copy", sub=FakeMenu(FakeItem(5, "Copy Link\tCtrl+Shift+C"))))),
        ("View", FakeMenu(FakeItem(6, "View Mode", sub=FakeMenu(
            FakeItem(7, "Issues && PRs\tCtrl+1", checkable=True, checked=True),
            FakeItem(8, "Branches\tCtrl+2", checkable=True))))),
    )
    f = SimpleNamespace(updated=0, _current_focus=lambda: None)
    f._update_actions_menu = lambda: setattr(f, "updated", f.updated + 1)
    f.GetMenuBar = lambda: bar
    return f


def test_menu_walk_gives_every_command_with_its_menu():
    f = _frame()
    got = Frame._menu_commands(f, enabled_only=False)
    assert f.updated == 1   # enables brought up to date first
    ctrl = "Cmd" if sys.platform == "darwin" else "Ctrl"  # as a Mac's menus show it
    assert got == [
        Command("Refresh (R)", f"{ctrl}+R", "File", 1),
        Command("Quit", f"{ctrl}+Q", "File", 2),
        Command("Close Issue/PR (C)", f"{ctrl}+W", "Actions", 3),
        Command("Copy Link", f"{ctrl}+Shift+C", "Actions > Copy", 5),
        Command("Issues & PRs", f"{ctrl}+1", "View > View Mode", 7, checked=True),
        Command("Branches", f"{ctrl}+2", "View > View Mode", 8),
    ]


def test_the_palette_leaves_out_what_does_not_apply():
    ids = [c.id for c in Frame._menu_commands(_frame(), enabled_only=True)]
    assert 3 not in ids and ids == [1, 2, 5, 7, 8]


def test_real_menu_shortcuts_are_not_used_twice():
    # Ctrl+F1 and Ctrl+Shift+P are new; no accelerator may be on two commands.
    src = (ROOT / "ghviewer.py").read_text(encoding="utf-8")
    accels = re.findall(r'\.Append\w*\(\s*\w+,\s*"[^"\n]*\\t([^"\n]+)"', src)
    dupes = {a for a in accels if accels.count(a) > 1}
    assert not dupes, dupes


def test_a_palette_command_runs_from_the_pane_that_had_focus():
    order = []
    focus = SimpleNamespace(SetFocus=lambda: order.append("focus"))
    handler = SimpleNamespace(ProcessEvent=lambda e: order.append(("run", e.GetId())))
    f = SimpleNamespace(GetEventHandler=lambda: handler)
    Frame._run_menu_command(f, int(ghviewer.ID_COPY_LINK), focus)
    assert order == ["focus", ("run", int(ghviewer.ID_COPY_LINK))]


def test_the_palette_runs_nothing_when_closed(monkeypatch):
    class Dlg:
        chosen = Command("Copy Link", "", "Actions", 5)
        def __init__(self, *a, **k): pass
        def ShowModal(self): return ghviewer.wx.ID_CANCEL
        def Destroy(self): pass
    later = []
    monkeypatch.setattr(ghviewer, "CommandListDialog", Dlg)
    monkeypatch.setattr(ghviewer.wx, "CallAfter", lambda *a: later.append(a))
    f = _frame()
    f._menu_commands = lambda enabled_only: Frame._menu_commands(f, enabled_only)
    Frame.on_command_palette(f, None)
    assert later == []


def test_the_palette_leaves_itself_out(monkeypatch):
    seen = {}

    class Dlg:
        chosen = None
        def __init__(self, parent, title, rows, *a, **k): seen["rows"] = rows
        def ShowModal(self): return ghviewer.wx.ID_CANCEL
        def Destroy(self): pass
    monkeypatch.setattr(ghviewer, "CommandListDialog", Dlg)
    f = _frame()
    f.GetMenuBar().menus.append(("Help", FakeMenu(
        FakeItem(int(ghviewer.ID_COMMAND_PALETTE), "Command Palette…\tCtrl+Shift+P"))))
    f._menu_commands = lambda enabled_only: Frame._menu_commands(f, enabled_only)
    Frame.on_command_palette(f, None)
    assert int(ghviewer.ID_COMMAND_PALETTE) not in [c.id for c in seen["rows"]]


def test_the_menu_separator_is_plain_text():
    # "▸" is read as "black right-pointing small triangle".
    assert commands.MENU_SEP == " > "
    src = (ROOT / "ghviewer.py").read_text(encoding="utf-8")
    spoken = [line for line in src.splitlines()
              if "▸" in line and '"""' not in line and not line.strip().startswith("#")
              and re.search(r"[\"'][^\"']*▸", line)]
    assert not spoken, spoken


@pytest.mark.parametrize("shown, palette, said", [
    ([], True, "No commands match."),
    ([], False, "No shortcuts match."),
    ([Command("Branches", "Ctrl+2")], True, "1 command. Enter runs Branches, Ctrl+2."),
    ([Command("Merge…"), Command("Close")], True, "2 commands. Enter runs Merge."),
    ([Command("R", "R")] * 3, False, "3 shortcuts."),
])
def test_summary_says_how_many_and_what_enter_runs(shown, palette, said):
    assert commands.summary(shown, palette) == said


# ── The dialog: what the summary says is what Enter runs ───────────────

Dialog = ghviewer.CommandListDialog


class FakeLabel:
    def __init__(self): self.label = ""
    def SetLabel(self, text): self.label = text


def _dialog(text, shown, selected=0, focus_on_filter=True):
    d = SimpleNamespace(palette=True, _shown=shown, summary=FakeLabel(), ended=None)
    d.filter_ctrl = SimpleNamespace(GetValue=lambda: text)
    d.list = SimpleNamespace(GetFirstSelected=lambda: selected)
    d._described = SimpleNamespace(description="")
    d.IsModal = lambda: True
    d.EndModal = lambda code: setattr(d, "ended", code)
    d._summary_text = lambda: Dialog._summary_text(d)
    return d


SHOWN = [Command("Copy Link", "Ctrl+Shift+C"), Command("Copy Title"), Command("Copy SHA")]


def test_enter_in_the_box_runs_the_first_match_even_after_moving_in_the_list():
    # Review: Shift+Tab back from row 3 left Enter running row 3 while the
    # summary said "Enter runs Copy Link".
    d = _dialog("copy", SHOWN, selected=2)
    Dialog._choose(d, first=True)
    assert d.chosen is SHOWN[0]
    d = _dialog("copy", SHOWN, selected=2)
    Dialog._choose(d)          # Enter on the list runs the row you are on
    assert d.chosen is SHOWN[2]


def test_enter_in_the_box_with_nothing_matching_runs_nothing(monkeypatch):
    bells = []
    monkeypatch.setattr(ghviewer.wx, "Bell", lambda: bells.append(1))
    d = _dialog("zzz", [])
    Dialog._choose(d, first=True)
    assert d.ended is None and bells == [1]


def test_nothing_is_summarised_until_something_is_typed():
    assert Dialog._summary_text(_dialog("  ", SHOWN)) == ""
    assert Dialog._summary_text(_dialog("copy", SHOWN)) == (
        "3 commands. Enter runs Copy Link, Ctrl+Shift+C.")


def test_a_pause_updates_the_label_and_description_and_tells_the_screen_reader(monkeypatch):
    sent = []
    monkeypatch.setattr(ghviewer.wx.Accessible, "NotifyEvent", lambda *a: sent.append(a))
    d = _dialog("copy", SHOWN)
    monkeypatch.setattr(ghviewer.wx.Window, "FindFocus", lambda: d.filter_ctrl)
    Dialog._notify(d)
    said = "3 commands. Enter runs Copy Link, Ctrl+Shift+C."
    assert d.summary.label == said and d._described.description == said
    assert len(sent) == 1 and sent[0][0] == ghviewer.wx.ACC_EVENT_OBJECT_DESCRIPTIONCHANGE


def test_no_event_when_the_box_does_not_have_focus(monkeypatch):
    sent = []
    monkeypatch.setattr(ghviewer.wx.Accessible, "NotifyEvent", lambda *a: sent.append(a))
    monkeypatch.setattr(ghviewer.wx.Window, "FindFocus", lambda: None)
    d = _dialog("copy", SHOWN)
    Dialog._notify(d)
    assert sent == [] and d._described.description.startswith("3 commands")


def test_a_pause_after_the_dialog_has_gone_does_nothing(monkeypatch):
    # Typing then Enter inside the pause: the timer fires on a deleted box.
    sent = []
    monkeypatch.setattr(ghviewer.wx.Accessible, "NotifyEvent", lambda *a: sent.append(a))
    d = _dialog("copy", SHOWN)
    d.filter_ctrl = None   # a deleted wx window is falsy
    Dialog._notify(d)
    assert sent == [] and d.summary.label == ""
