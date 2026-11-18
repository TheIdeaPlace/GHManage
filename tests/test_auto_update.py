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


@pytest.fixture(autouse=True)
def _no_leftover_log_handlers(monkeypatch):
    """main() now opens the update log; close it so tmp folders can go. And
    a startup failure recorded here isn't another test's "last error"."""
    monkeypatch.setattr(ghviewer.bugreport, "last_error", None)
    yield
    for logger in (updater.logger, ghviewer.bugreport.log):
        for h in list(logger.handlers):
            logger.removeHandler(h)
            h.close()


class PanicException(BaseException):
    """What pyo3 raises when Rust code in velopack panics: a BaseException."""


@pytest.mark.parametrize("raised", [PanicException("panicked"), RuntimeError("bad")])
def test_a_failure_in_velopack_is_logged_not_fatal(frozen_velopack, monkeypatch, caplog, raised):
    def boom(self):
        raise raised
    monkeypatch.setattr(FakeApp, "run", boom)
    with caplog.at_level("ERROR", logger="ghmanage.updater"):
        updater.bootstrap()   # no exception: GHManage goes on starting (#142)
    assert "Velopack bootstrap failed" in caplog.text
    assert type(raised).__name__ in caplog.text   # with the traceback


def test_velopacks_own_exit_still_exits(frozen_velopack, monkeypatch):
    def leave(self):
        raise SystemExit(0)
    monkeypatch.setattr(FakeApp, "run", leave)
    with pytest.raises(SystemExit):
        updater.bootstrap()


@pytest.fixture
def quiet_start(monkeypatch):
    """main() up to the window, without what would outlive the test: the
    excepthooks, faulthandler on a tmp crash.txt, a real wx.App."""
    bugreport = ghviewer.bugreport
    monkeypatch.setattr(updater, "bootstrap", lambda auto_apply=True: None)
    monkeypatch.setattr(sys, "argv", ["ghmanage"])
    monkeypatch.setattr(bugreport, "configure_log", bugreport._add_log_handler)
    monkeypatch.setattr(bugreport, "install_handlers", lambda: None)
    monkeypatch.setattr(bugreport, "begin_run", lambda: None)
    monkeypatch.setattr(ghviewer.wx, "App", lambda redirect=False: SimpleNamespace(
        MainLoop=lambda: None))


def _log_text() -> str:
    for h in ghviewer.bugreport.log.handlers:
        h.flush()
    return (ghviewer.bugreport.log_folder() / ghviewer.bugreport.LOG_NAME).read_text(
        encoding="utf-8")


def test_a_failure_starting_is_written_to_the_log(quiet_start, monkeypatch):
    # #142: the packaged build's "Unhandled exception in script" box was the
    # only record; the log said nothing.
    def broken(*a, **k):
        raise KeyError("nav_mode")
    monkeypatch.setattr(ghviewer, "GhViewerFrame", broken)
    with pytest.raises(KeyError) as caught:
        ghviewer.main()
    text = _log_text()
    assert "Unhandled exception in starting GHManage" in text
    assert text.count("KeyError: 'nav_mode'") == 1
    assert caught.value._ghmanage_logged   # so launch.py doesn't log it again


def test_a_failure_once_running_says_running(quiet_start, monkeypatch):
    def loop():
        raise RuntimeError("closing")
    monkeypatch.setattr(ghviewer, "GhViewerFrame", lambda **k: SimpleNamespace())
    monkeypatch.setattr(ghviewer.wx, "App", lambda redirect=False: SimpleNamespace(
        MainLoop=loop))
    with pytest.raises(RuntimeError):
        ghviewer.main()
    text = _log_text()
    assert "Unhandled exception in running GHManage" in text
    assert "in starting GHManage" not in text


def test_debug_is_only_the_whole_word(monkeypatch):
    # main() reads --debug before argparse; a shortened --deb would be read
    # differently by each, so the parser refuses shortened options.
    levels = []
    monkeypatch.setattr(updater, "configure_logging", lambda debug=False: levels.append(debug))
    monkeypatch.setattr(updater, "bootstrap", lambda auto_apply=True: None)
    monkeypatch.setattr(sys, "argv", ["ghmanage", "--deb"])
    with pytest.raises(SystemExit):   # argparse: unrecognized arguments
        ghviewer.main()
    assert levels == [False]


def test_a_failure_in_velopack_reaches_the_update_log(frozen_velopack, monkeypatch):
    # The update log is opened before the hooks run, so their failure is in it.
    def boom(self):
        raise PanicException("panicked")
    monkeypatch.setattr(FakeApp, "run", boom)
    monkeypatch.setattr(sys, "argv", ["ghmanage"])
    monkeypatch.setattr(ghviewer, "_start", lambda: updater.bootstrap() or SimpleNamespace(
        MainLoop=lambda: None))
    ghviewer.main()
    for h in updater.logger.handlers:
        h.flush()
    with open(updater._log_path(), encoding="utf-8") as f:
        text = f.read()
    assert "Velopack bootstrap failed" in text and "PanicException: panicked" in text


def test_exit_while_starting_is_not_logged_as_a_failure(monkeypatch):
    monkeypatch.setattr(updater, "bootstrap",
                        lambda auto_apply=True: (_ for _ in ()).throw(SystemExit))
    with pytest.raises(SystemExit):
        ghviewer.main()
    assert ghviewer.bugreport.last_error is None


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
