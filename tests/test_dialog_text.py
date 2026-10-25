"""Dialogs read only their title and the focused control when they open (#60).

A StaticText that labels nothing is "dialog text": screen readers read it
with the focused control as the dialog opens. These build the real dialogs
and check that every StaticText is the label of the control made just
after it, and that help text sits last in tab order.
"""

from __future__ import annotations

import os

import pytest

if os.environ.get("CI"):
    import wx
else:
    wx = pytest.importorskip("wx")

import ghviewer  # noqa: E402
import search_help  # noqa: E402


@pytest.fixture(scope="module")
def frame():
    app = wx.App(False)
    f = wx.Frame(None)
    yield f
    f.Destroy()
    app.Destroy()


def _unlabelled_text(dlg: wx.Dialog) -> list[str]:
    """StaticTexts not followed (in tab order) by a control they label."""
    kids = list(dlg.GetChildren())
    stray = []
    for i, w in enumerate(kids):
        if isinstance(w, wx.StaticText):
            nxt = kids[i + 1] if i + 1 < len(kids) else None
            if nxt is None or isinstance(nxt, wx.StaticText) or not nxt.AcceptsFocusFromKeyboard():
                stray.append(w.GetLabel())
    return stray


def _button(dlg: wx.Dialog, wid: int) -> wx.Button:
    # dlg.FindWindowById can find a dialog destroyed earlier in the session.
    return next(w for w in dlg.GetChildren() if w.GetId() == wid)


def _named(dlg: wx.Dialog, name: str) -> wx.TextCtrl:
    found = [w for w in dlg.GetChildren() if isinstance(w, wx.TextCtrl) and w.GetName() == name]
    assert len(found) == 1, name
    return found[0]


def test_search_dialog_has_no_dialog_text(frame):
    dlg = ghviewer.SearchDialog(frame)
    try:
        assert _unlabelled_text(dlg) == []
        box = _named(dlg, "Examples")
        assert box.GetValue() == ghviewer.SearchDialog.EXAMPLES
        assert not box.IsEditable()
        # Last in tab order: after OK and Cancel, so Tab from the Search box
        # reaches Insert Qualifier first, as before.
        kids = list(dlg.GetChildren())
        assert kids[-1] is box
        assert kids.index(_button(dlg, wx.ID_CANCEL)) < kids.index(box)
        # On screen it is still just under the Search box.
        dlg.Layout()
        assert dlg.query_ctrl.GetPosition().y < box.GetPosition().y < dlg.qualifiers_btn.GetPosition().y
    finally:
        dlg.Destroy()


def _fits(box: wx.TextCtrl) -> bool:
    """Every wrapped line of the box shows without scrolling."""
    return box.GetNumberOfLines() * box.GetCharHeight() <= box.GetClientSize().height


def test_search_dialog_is_wide_enough_to_show_the_examples(frame):
    dlg = ghviewer.SearchDialog(frame)
    try:
        dlg.Layout()
        box = _named(dlg, "Examples")
        assert dlg.GetSize().width >= 520
        assert _fits(box)
    finally:
        dlg.Destroy()


def test_qualifiers_notes_show_in_full(frame):
    dlg = ghviewer.SearchQualifiersDialog(frame, ghviewer.KIND_ISSUES)
    try:
        dlg.Layout()
        assert _fits(_named(dlg, "Notes"))
    finally:
        dlg.Destroy()


def test_enter_in_a_reading_box_presses_the_default_button(frame):
    dlg = ghviewer.SearchQualifiersDialog(frame, ghviewer.KIND_ISSUES)
    pressed = []
    dlg.Bind(wx.EVT_BUTTON, lambda e: pressed.append(e.GetId()), id=wx.ID_OK)
    try:
        box = _named(dlg, "Notes")
        for code, mods, expected in ((wx.WXK_RETURN, False, [wx.ID_OK]),
                                     (ord("A"), False, []),
                                     (wx.WXK_RETURN, True, [])):
            pressed.clear()
            key = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
            key.SetKeyCode(code)
            key.SetControlDown(mods)
            key.SetEventObject(box)
            box.GetEventHandler().ProcessEvent(key)
            assert pressed == expected
        # Not a disabled one.
        pressed.clear()
        _button(dlg, wx.ID_OK).Disable()
        key = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
        key.SetKeyCode(wx.WXK_RETURN)
        box.GetEventHandler().ProcessEvent(key)
        assert pressed == []
    finally:
        dlg.Destroy()


@pytest.mark.parametrize("kind", [ghviewer.KIND_ISSUES, ghviewer.KIND_REPOS])
def test_qualifiers_dialog_has_no_dialog_text(frame, kind):
    dlg = ghviewer.SearchQualifiersDialog(frame, kind)
    try:
        assert _unlabelled_text(dlg) == []
        box = _named(dlg, "Notes")
        assert box.GetValue() == search_help.GENERAL_NOTE
        assert not box.IsEditable()
        assert list(dlg.GetChildren())[-1] is box
        dlg.Layout()
        assert dlg.list.GetPosition().y < box.GetPosition().y < _button(dlg, wx.ID_OK).GetPosition().y
    finally:
        dlg.Destroy()
