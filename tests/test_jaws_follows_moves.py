"""Alt+N and Alt+P select the comment, change or heading moved to. NVDA and
Narrator read that selection; JAWS reads a selection only when a key it
knows made it, so it said nothing. With JAWS running the selection is spoken
for it, and with any other screen reader it isn't, or it would be heard
twice."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

if os.environ.get("CI"):
    import wx  # noqa: F401
else:
    pytest.importorskip("wx")

import ghviewer  # noqa: E402
import speech  # noqa: E402

Frame = ghviewer.GhViewerFrame
# Kept before conftest's stand-in replaces it for each test.
_REAL_JAWS_RUNNING = speech.jaws_running


class FakeText:
    def __init__(self, value: str) -> None:
        self.value, self.selection = value, None

    def GetValue(self): return self.value
    def SetFocus(self): pass
    def SetSelection(self, a, b): self.selection = (a, b)
    def ShowPosition(self, p): pass

    def GetStringSelection(self):
        a, b = self.selection
        return self.value[a:b]


TEXT = ("Body\n"
        "  Comment 1 of 2 — ann (2026-01-01):\n    first\n"
        "  Comment 2 of 2 — bob (2026-01-02):\n    second")


def _frame():
    f = SimpleNamespace(details_text=FakeText(TEXT), _comment_positions=[(1, 2), (3, 2)],
                        _current_comment=-1, announced=[], view_mode=ghviewer.VIEW_ISSUES)
    f._announce = f.announced.append
    f._line_to_position = lambda line: Frame._line_to_position(f, line)
    return f


@pytest.fixture
def said(monkeypatch):
    said = []

    def record(text, category=None, force=False, queued=False):
        said.append((text, category, force, queued))

    monkeypatch.setattr(ghviewer.announce, "announce", record)
    # A move from the list speaks after the focus change: run it at once.
    monkeypatch.setattr(ghviewer.wx, "CallLater", lambda ms, fn, *a, **k: fn(*a, **k))
    return said


@pytest.fixture
def focus(monkeypatch):
    """Where focus is: None (the list) until a test puts it in the details."""
    where = SimpleNamespace(window=None)
    monkeypatch.setattr(ghviewer.wx.Window, "FindFocus", staticmethod(lambda: where.window))
    return where


def test_with_jaws_the_comment_moved_to_is_spoken(monkeypatch, said, focus):
    monkeypatch.setattr(speech, "jaws_running", lambda: True)
    f = _frame()
    Frame._navigate_comment(f, 1)
    focus.window = f.details_text
    Frame._navigate_comment(f, 1)
    texts = [s[0] for s in said]
    assert texts[0].startswith("  Comment 1 of 2 — ann")
    assert texts[1].startswith("  Comment 2 of 2 — bob") and texts[1].endswith("second")
    # Spoken whatever the feedback settings: it is the text, not feedback.
    assert all(s[1] == ghviewer.announce.RESULT and s[2] for s in said)


def test_from_the_list_it_follows_what_jaws_says_about_focus(monkeypatch, said, focus):
    # Interrupting would cut off, or be cut off by, JAWS reading the details
    # box focus moved to; queued after it, both are heard.
    monkeypatch.setattr(speech, "jaws_running", lambda: True)
    f = _frame()
    Frame._navigate_comment(f, 1)
    assert said[0][3] is True
    focus.window = f.details_text
    Frame._navigate_comment(f, 1)
    assert said[1][3] is False  # within the details box it interrupts


def test_what_jaws_hears_is_what_is_selected(monkeypatch, said, focus):
    monkeypatch.setattr(speech, "jaws_running", lambda: True)
    f = _frame()
    Frame._navigate_comment(f, 1)
    assert said[0][0] == f.details_text.GetStringSelection()


def test_an_emoji_before_it_doesnt_shift_the_selection(monkeypatch, said, focus):
    # The text box counts an emoji as two; each one before the comment
    # moved the selection, and what JAWS was told, one character along.
    monkeypatch.setattr(ghviewer, "_UTF16_POSITIONS", True)
    monkeypatch.setattr(speech, "jaws_running", lambda: True)
    f = _frame()
    f.details_text = Utf16Text("Body 🎉🎉🎉\n  Comment 1 of 1 — ann:\n    first")
    f._comment_positions = [(1, 2)]
    Frame._navigate_comment(f, 1)
    assert f.details_text.GetStringSelection() == "  Comment 1 of 1 — ann:\n    first"
    assert said[0][0] == "  Comment 1 of 1 — ann:\n    first"


def test_positions_convert_both_ways():
    text = "a🎉b\nc"
    for platform_units in (True, False):
        ghviewer._UTF16_POSITIONS, saved = platform_units, ghviewer._UTF16_POSITIONS
        try:
            for i in range(len(text) + 1):
                assert ghviewer._text_index(text, ghviewer._ctrl_pos(text, i)) == i
        finally:
            ghviewer._UTF16_POSITIONS = saved
    assert ghviewer._ctrl_pos(text, 3) in (3, 4)


class Utf16Text(FakeText):
    """Counts positions as the Windows text box does, in UTF-16 units."""

    def GetStringSelection(self):
        a, b = self.selection
        units = self.value.encode("utf-16-le")
        return units[a * 2:b * 2].decode("utf-16-le")


def test_without_jaws_nothing_extra_is_spoken(monkeypatch, said):
    # NVDA and Narrator read the selection themselves.
    monkeypatch.setattr(speech, "jaws_running", lambda: False)
    f = _frame()
    Frame._navigate_comment(f, 1)
    assert said == []
    assert f.details_text.selection is not None


def test_at_the_end_nothing_is_spoken_for_jaws_either(monkeypatch, said):
    monkeypatch.setattr(speech, "jaws_running", lambda: True)
    f = _frame()
    f._current_comment = 1
    Frame._navigate_comment(f, 1)
    assert said == []
    assert f.announced == ["Already at last comment."]


def test_jaws_running_is_false_off_windows(monkeypatch):
    monkeypatch.setattr(speech, "IS_WINDOWS", False)
    assert _REAL_JAWS_RUNNING() is False


def test_jaws_running_looks_for_its_window(monkeypatch):
    if not speech.IS_WINDOWS:
        pytest.skip("Windows only")
    import ctypes
    asked = []

    class User32:
        def FindWindowW(self, cls, title):
            asked.append(cls)
            return 0

    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=User32()))
    assert _REAL_JAWS_RUNNING() is False
    assert asked == ["JFWUI2"]


def test_jaws_running_is_false_if_it_cant_look(monkeypatch):
    if not speech.IS_WINDOWS:
        pytest.skip("Windows only")
    import ctypes

    class User32:
        def FindWindowW(self, cls, title):
            raise OSError("no user32")

    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=User32()))
    assert _REAL_JAWS_RUNNING() is False
