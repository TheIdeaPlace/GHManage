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


@pytest.mark.parametrize("updater_there, on, checks", [
    (True, True, True), (True, False, False), (False, True, False),
])
def test_the_startup_check_only_when_on_and_installed(updater_there, on, checks):
    settings.save_auto_update(on)
    f = SimpleNamespace(updater=object() if updater_there else None)
    assert Frame._should_check_at_startup(f) is checks


def test_main_still_runs_velopacks_hooks_when_the_setting_cant_be_read(monkeypatch):
    # An APPDATA that can't be written must not stop install or uninstall.
    def broken():
        raise OSError("Access is denied")
    monkeypatch.setattr(settings, "load_auto_update", broken)
    seen = []
    monkeypatch.setattr(updater, "bootstrap", lambda auto_apply=True: seen.append(auto_apply)
                        or (_ for _ in ()).throw(SystemExit))
    with pytest.raises(SystemExit):
        ghviewer.main()
    assert seen == [True]


def test_toggling_saves_checks_the_menu_and_always_says_so():
    checked, said = [], []
    f = SimpleNamespace(_tell=lambda msg, *a, **k: said.append((msg, k.get("force"))))
    f.GetMenuBar = lambda: SimpleNamespace(Check=lambda i, v: checked.append((i, v)))
    Frame._toggle_auto_update(f)
    assert settings.load_auto_update() is False
    assert checked == [(ghviewer.ID_AUTO_UPDATE, False)]
    assert said[0] == ("Automatic updates off. Updates are installed only when you choose.",
                       True)   # spoken even with Speak Results off
    Frame._toggle_auto_update(f)
    assert settings.load_auto_update() is True and said[1] == ("Automatic updates on.", True)


@pytest.mark.parametrize("on, says", [
    (True, "It will be retried the next time GHManage starts."),
    (False, "won't be retried by itself"),
])
def test_a_failed_install_doesnt_promise_a_retry_off_wont_make(monkeypatch, on, says):
    monkeypatch.setattr(ghviewer.wx, "MessageDialog", YesDialog)
    boxes = []
    monkeypatch.setattr(ghviewer.wx, "MessageBox", lambda msg, *a, **k: boxes.append(msg))
    monkeypatch.setattr(ghviewer.bugreport, "end_run", lambda: None)
    monkeypatch.setattr(ghviewer.bugreport, "begin_run", lambda: None)
    settings.save_auto_update(on)
    f = SimpleNamespace(updater=SimpleNamespace(apply_update_and_restart=lambda args: False))
    Frame._show_update_dialog(f, "9.9.9", "u")
    assert says in boxes[0]


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


class YesDialog(FakeDialog):
    """Restart Now."""
    def ShowModal(self):
        return ghviewer.wx.ID_YES


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
