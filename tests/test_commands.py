"""Help ▸ Keyboard Shortcuts (#3) and the command palette (#27)."""

from __future__ import annotations

import os
import re
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
    Command("Open in Browser", "Ctrl+O", "Actions"),
    Command("Copy Link", "Ctrl+Shift+C", "Actions ▸ Copy"),
    Command("Refresh (R)", "Ctrl+R", "File"),
    Command("Issues & PRs", "Ctrl+1", "View ▸ View Mode", checked=True),
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


def test_palette_text_says_checked_and_the_shortcut():
    assert CMDS[3].text == "Issues & PRs, checked (Ctrl+1)"
    assert Command("Merge…").text == "Merge…"


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
    f = SimpleNamespace(updated=0)
    f._update_actions_menu = lambda: setattr(f, "updated", f.updated + 1)
    f.GetMenuBar = lambda: bar
    return f


def test_menu_walk_gives_every_command_with_its_menu():
    f = _frame()
    got = Frame._menu_commands(f, enabled_only=False)
    assert f.updated == 1   # enables brought up to date first
    assert got == [
        Command("Refresh (R)", "Ctrl+R", "File", 1),
        Command("Quit", "Ctrl+Q", "File", 2),
        Command("Close Issue/PR (C)", "Ctrl+W", "Actions", 3),
        Command("Copy Link", "Ctrl+Shift+C", "Actions ▸ Copy", 5),
        Command("Issues & PRs", "Ctrl+1", "View ▸ View Mode", 7, checked=True),
        Command("Branches", "Ctrl+2", "View ▸ View Mode", 8),
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
