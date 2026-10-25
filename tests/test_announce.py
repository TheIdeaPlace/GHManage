"""What GHManage says (#65): the Columns dialog's wording, which messages
pass the user's settings, and that the dialog says each action."""

from __future__ import annotations

import os
import types

import pytest

import announce
import settings
from announce import HINT, RESULT, SILENT, STATUS, Announcer
from columns import LayoutEditor
from gh_columns import COMMIT_SET


# ── The wording ─────────────────────────────────────────────────────────

def _editor(shown=("sha", "message", "author", "date")):
    return LayoutEditor(COMMIT_SET, list(shown))


@pytest.mark.parametrize("index, target, said", [
    (2, 1, "Author moved above Message."),
    (1, 2, "Message moved below Author."),
    (2, 0, "Author moved to the top."),
    (1, 3, "Message moved to the bottom."),
    (3, 1, "Date moved above Message."),
    (0, 2, "Commit moved below Author."),
])
def test_a_move_names_the_column_it_is_now_next_to(index, target, said):
    ed = _editor()
    assert ed.move(index, target)
    assert ed.said == said


@pytest.mark.parametrize("index, target, said", [
    (0, -1, "Commit is already at the top."),
    (0, 0, "Commit is already at the top."),     # Move to Top on the first
    (3, 4, "Date is already at the bottom."),
    (3, 3, "Date is already at the bottom."),    # Move to Bottom on the last
    (-1, 0, "No column is selected."),
])
def test_a_move_that_cannot_happen_says_why(index, target, said):
    ed = _editor()
    assert not ed.move(index, target)
    assert ed.said == said
    assert ed.shown == ["sha", "message", "author", "date"]


def test_add_remove_and_reset_say_what_happened():
    ed = _editor()
    assert ed.add(0)  # branch
    assert ed.said == "Branches added at the end, 5 of 5."
    assert ed.remove(1)
    assert ed.said == "Message removed, 4 columns shown."
    ed.reset()
    assert ed.said == "Columns reset to the default."


def test_add_and_remove_refusals():
    ed = _editor(["sha", "message"])
    assert ed.remove(0) and ed.said == "Commit removed, 1 column shown."
    assert not ed.remove(0) and ed.said == "At least one column has to be shown."
    assert not ed.add(99) and ed.said == "No column is selected."
    every = _editor(COMMIT_SET.ids)
    assert not every.add(0) and every.said == "Every column is shown."


@pytest.mark.parametrize("target", [-1, 0, 1])
def test_a_lone_column_says_it_is_the_only_one(target):
    ed = _editor(["sha"])
    assert not ed.move(0, target)
    assert ed.said == "Commit is the only column shown."


# ── Which messages are spoken ───────────────────────────────────────────

class _Rec:
    def __init__(self):
        self.spoken: list[tuple[str, bool]] = []
        self.seen: list[tuple[str, str]] = []
        self.categories: list[str] = []

    def speaker(self, text, interrupt, category):
        self.spoken.append((text, interrupt))
        self.categories.append(category)
        return True


def _announcer():
    a, rec = Announcer(), _Rec()
    a.speaker = rec.speaker
    a.observers.append(lambda t, c: rec.seen.append((t, c)))
    return a, rec


def test_results_interrupt_and_the_rest_wait_their_turn():
    a, rec = _announcer()
    assert a.announce("Author moved above Message.", RESULT)
    assert a.announce("Loading…", STATUS)
    assert a.announce("Press F1 for help.", HINT)
    assert rec.spoken == [("Author moved above Message.", True),
                          ("Loading…", False), ("Press F1 for help.", False)]
    # The speaker is told the category, for a notification activity of its own.
    assert rec.categories == [RESULT, STATUS, HINT]


def test_silent_and_empty_are_never_spoken():
    a, rec = _announcer()
    assert not a.announce("Shown already", SILENT)
    assert not a.announce("  ", RESULT)
    assert not a.announce("x", "no-such-category")
    assert rec.spoken == [] and rec.seen == []


def test_settings_filter_by_category_and_altogether():
    a, rec = _announcer()
    a.configure(True, {RESULT: False})
    assert not a.announce("moved", RESULT)
    assert a.announce("loading", STATUS)
    a.configure(False, {RESULT: True})
    assert not a.announce("moved", RESULT)
    assert not a.announce("loading", STATUS)
    assert rec.seen == [("loading", STATUS)]


def test_force_is_heard_whatever_the_settings_and_interrupts():
    a, rec = _announcer()
    a.configure(False, {RESULT: False, STATUS: False, HINT: False})
    assert a.announce("Results won't be spoken.", RESULT, force=True)
    assert a.announce("hint", HINT, force=True)
    assert rec.spoken == [("Results won't be spoken.", True), ("hint", True)]
    assert not a.announce("never", SILENT, force=True)


def test_nothing_to_speak_with_still_lets_observers_see_it():
    a = Announcer()
    seen = []
    a.observers.append(lambda t, c: seen.append(t))
    assert not a.announce("moved", RESULT)
    assert seen == ["moved"]


def test_a_failing_speaker_never_raises():
    a = Announcer()
    a.speaker = lambda t, i, c: 1 / 0
    assert not a.announce("moved", RESULT)


def test_settings_default_on_and_round_trip():
    assert settings.load_announcements() == (True, {RESULT: True, STATUS: True, HINT: True})
    settings.save_announcements(True, {RESULT: False, STATUS: True, HINT: True})
    assert settings.load_announcements() == (True, {RESULT: False, STATUS: True, HINT: True})
    settings.save_announcements(False, {})
    assert settings.load_announcements() == (False, {RESULT: True, STATUS: True, HINT: True})


def test_settings_ignore_rubbish():
    settings._session["announcements"] = {"enabled": "yes", RESULT: 0, HINT: False}
    assert settings.load_announcements() == (True, {RESULT: True, STATUS: True, HINT: False})
    settings._session["announcements"] = ["not", "a", "dict"]
    assert settings.load_announcements() == (True, {RESULT: True, STATUS: True, HINT: True})


# ── The dialog says each action ─────────────────────────────────────────

if os.environ.get("CI"):
    import wx
else:
    wx = pytest.importorskip("wx")

import ghviewer  # noqa: E402


@pytest.fixture(scope="module")
def frame():
    app = wx.App(False)
    f = wx.Frame(None)
    yield f
    f.Destroy()
    app.Destroy()


def _dialog(frame, said, spoken=True, shown=("sha", "message", "author", "date")):
    def say(text):
        said.append(text)
        return spoken
    return ghviewer.ColumnsDialog(frame, [COMMIT_SET], COMMIT_SET.id,
                                  {COMMIT_SET.id: list(shown)}, False, None, say=say)


def test_the_dialog_says_each_action(frame, monkeypatch):
    monkeypatch.setattr(wx, "Bell", lambda: None)
    said: list[str] = []
    dlg = _dialog(frame, said)
    try:
        dlg.shown.SetSelection(2)
        dlg.move(-1)
        dlg.move_to_end(top=True)
        dlg.move_to_end(top=True)        # already there
        dlg.available.SetSelection(0)
        dlg.add()
        dlg.shown.SetSelection(1)
        dlg.remove()
        dlg.reset()
        assert said == ["Author moved above Message.", "Author moved to the top.",
                        "Author is already at the top.", "Branches added at the end, 5 of 5.",
                        "Commit removed, 4 columns shown.", "Columns reset to the default."]
        # Focus stays on the column that moved, and the list shows the change.
        assert dlg.shown.GetStrings() == ["Commit", "Message", "Author", "Date"]
    finally:
        dlg.Destroy()


def test_what_an_action_did_is_shown_in_the_dialog_too(frame, monkeypatch):
    # Even when it isn't spoken, a refusal's reason is in the dialog: the
    # status bar is behind it, and a beep alone doesn't say why.
    bells = []
    monkeypatch.setattr(wx, "Bell", lambda: bells.append(1))
    said: list[str] = []
    dlg = _dialog(frame, said, spoken=False, shown=("sha",))
    try:
        assert dlg.result.GetLabel() == ""  # nothing extra read as the dialog opens
        dlg.shown.SetSelection(0)
        dlg.remove()
        assert said == ["At least one column has to be shown."]
        assert dlg.result.GetLabel() == "At least one column has to be shown."
        assert bells == [1]
        dlg.available.SetSelection(0)
        dlg.add()
        assert dlg.result.GetLabel() == "Message added at the end, 2 of 2."
    finally:
        dlg.Destroy()


def test_speak_results_turns_off_and_on_and_is_kept(monkeypatch):
    told, checks = [], []
    stub = types.SimpleNamespace(
        GetMenuBar=lambda: types.SimpleNamespace(Check=lambda i, on: checks.append(on)),
        _tell=lambda msg, force=False: told.append((msg, force)))
    monkeypatch.setattr(announce, "announcer", Announcer())
    ghviewer.GhViewerFrame._toggle_speak_results(stub)
    assert announce.announcer.categories[RESULT] is False
    assert settings.load_announcements()[1][RESULT] is False
    assert checks == [False] and told == [("Results won't be spoken.", True)]
    ghviewer.GhViewerFrame._toggle_speak_results(stub)
    assert settings.load_announcements()[1][RESULT] is True
    assert told[-1] == ("Results will be spoken.", True)


def test_tell_writes_the_status_bar_and_says_whether_it_spoke(frame, monkeypatch):
    a, rec = _announcer()
    monkeypatch.setattr(announce, "announcer", a)
    shown = []
    stub = types.SimpleNamespace(_announce=shown.append)
    assert ghviewer.GhViewerFrame._tell(stub, "Columns saved.")
    assert shown == ["Columns saved."] and rec.spoken == [("Columns saved.", True)]
    a.configure(True, {RESULT: False})
    assert not ghviewer.GhViewerFrame._tell(stub, "Quiet.")
    assert shown[-1] == "Quiet."


def test_the_module_announcer_is_what_the_frame_configures():
    assert isinstance(announce.announcer, Announcer)
