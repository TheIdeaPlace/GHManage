"""Help > Automatic Updates: on by default; off, GHManage neither looks for
updates when it starts nor installs one downloaded earlier."""

from __future__ import annotations

import os
import sys
import types
from types import SimpleNamespace

import pytest

import settings
import updater

if os.environ.get("CI"):
    import wx  # noqa: F401
else:
    pytest.importorskip("wx")

import ghviewer  # noqa: E402

Frame = ghviewer.GhViewerFrame


def test_on_until_turned_off():
    assert settings.load_auto_update() is True
    settings.save_auto_update(False)
    assert settings.load_auto_update() is False
    settings.save_auto_update(True)
    assert settings.load_auto_update() is True


def test_kept_across_runs():
    settings.save_auto_update(False)
    settings._session.clear()   # a new run reads the file
    assert settings.load_auto_update() is False


def test_something_odd_in_the_file_means_on(monkeypatch):
    monkeypatch.setattr(settings, "load_settings", lambda: {"auto_update": "no"})
    assert settings.load_auto_update() is True


class FakeApp:
    made: list = []

    def __init__(self):
        self.auto = None
        self.ran = False
        FakeApp.made.append(self)

    def set_auto_apply_on_startup(self, on):
        self.auto = on
        return self

    def run(self):
        self.ran = True


@pytest.fixture
def frozen_velopack(monkeypatch):
    FakeApp.made = []
    monkeypatch.setitem(sys.modules, "velopack", types.SimpleNamespace(App=FakeApp))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    return FakeApp


@pytest.mark.parametrize("on", [True, False])
def test_startup_installs_a_downloaded_update_only_when_on(frozen_velopack, on):
    updater.bootstrap(auto_apply=on)
    (app,) = frozen_velopack.made
    assert app.auto is on and app.ran   # the install/uninstall hooks run either way


def test_main_passes_the_setting_to_bootstrap(monkeypatch):
    seen = []
    monkeypatch.setattr(updater, "bootstrap", lambda auto_apply=True: seen.append(auto_apply)
                        or (_ for _ in ()).throw(SystemExit))
    settings.save_auto_update(False)
    with pytest.raises(SystemExit):
        ghviewer.main()
    assert seen == [False]


def test_the_startup_check_is_skipped_when_off():
    src = open(ghviewer.__file__, encoding="utf-8").read()
    assert ("if self.updater and settings.load_auto_update():\n"
            "            wx.CallLater(2000, self._start_update_check)") in src


def test_toggling_saves_checks_the_menu_and_says_so():
    checked, said = [], []
    f = SimpleNamespace(_tell=said.append)
    f.GetMenuBar = lambda: SimpleNamespace(Check=lambda i, v: checked.append((i, v)))
    Frame._toggle_auto_update(f)
    assert settings.load_auto_update() is False
    assert checked == [(ghviewer.ID_AUTO_UPDATE, False)]
    assert said[0].startswith("Automatic updates off.")
    Frame._toggle_auto_update(f)
    assert settings.load_auto_update() is True and said[1].startswith("Automatic updates on.")


class FakeDialog:
    shown = []

    def __init__(self, parent, msg, title, style):
        self.msg = msg
        FakeDialog.shown.append(self)

    def SetYesNoLabels(self, yes, no):
        self.labels = (yes, no)

    def ShowModal(self):
        return ghviewer.wx.ID_NO

    def Destroy(self):
        pass


@pytest.mark.parametrize("on, later, says", [
    (True, "&Later", "the next time you start GHManage"),
    (False, "&Not Now", "won't be installed by itself"),
])
def test_the_update_box_doesnt_promise_what_off_wont_do(monkeypatch, on, later, says):
    FakeDialog.shown = []
    monkeypatch.setattr(ghviewer.wx, "MessageDialog", FakeDialog)
    settings.save_auto_update(on)
    Frame._show_update_dialog(SimpleNamespace(updater=None), "9.9.9", "u")
    (box,) = FakeDialog.shown
    assert box.labels == ("&Restart Now", later) and says in box.msg
