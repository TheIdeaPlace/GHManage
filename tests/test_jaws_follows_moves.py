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
    monkeypatch.setattr(ghviewer.announce, "announce",
                        lambda text, category=None, force=False, queued=False:
                        said.append((text, category, force)))
    return said


def test_with_jaws_the_comment_moved_to_is_spoken(monkeypatch, said):
    monkeypatch.setattr(speech, "jaws_running", lambda: True)
    f = _frame()
    Frame._navigate_comment(f, 1)
    Frame._navigate_comment(f, 1)
    texts = [t for t, _c, _f in said]
    assert texts[0].startswith("  Comment 1 of 2 — ann")
    assert texts[1].startswith("  Comment 2 of 2 — bob") and texts[1].endswith("second")
    # Spoken whatever the feedback settings: it is the text, not feedback.
    assert all(c == ghviewer.announce.RESULT and force for _t, c, force in said)


def test_what_jaws_hears_is_what_is_selected(monkeypatch, said):
    monkeypatch.setattr(speech, "jaws_running", lambda: True)
    f = _frame()
    Frame._navigate_comment(f, 1)
    assert said[0][0] == f.details_text.GetStringSelection()


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
