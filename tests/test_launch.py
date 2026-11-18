"""launch.py, the packaged app's entry point: a failure while ghviewer is
still being imported is written to the log too (#142)."""

from __future__ import annotations

import os
import sys
import types

import pytest

import launch


def _log() -> str:
    with open(launch.log_file(), encoding="utf-8") as f:
        return f.read()


def test_the_log_is_the_one_bugreport_writes():
    import bugreport
    assert os.path.abspath(launch.log_file()) == os.path.abspath(
        bugreport.log_folder() / bugreport.LOG_NAME)


def test_a_failure_importing_is_logged_then_raised(monkeypatch):
    monkeypatch.setitem(sys.modules, "ghviewer", None)   # import raises ImportError
    with pytest.raises(ImportError):
        launch.run()
    text = _log()
    assert "ERROR ghmanage: Unhandled exception in starting GHManage:" in text
    assert "import of ghviewer halted" in text


def test_what_main_logged_already_isnt_logged_again(monkeypatch):
    def main():
        exc = RuntimeError("logged by main")
        exc._ghmanage_logged = True
        raise exc
    monkeypatch.setitem(sys.modules, "ghviewer", types.SimpleNamespace(main=main))
    with pytest.raises(RuntimeError):
        launch.run()
    assert not os.path.exists(launch.log_file())


def test_what_main_didnt_log_is_logged(monkeypatch):
    class Panic(BaseException):
        pass

    def main():
        raise Panic("from Rust")
    monkeypatch.setitem(sys.modules, "ghviewer", types.SimpleNamespace(main=main))
    with pytest.raises(Panic):
        launch.run()
    assert "Panic: from Rust" in _log()


def test_exit_passes_straight_through(monkeypatch):
    monkeypatch.setitem(sys.modules, "ghviewer", types.SimpleNamespace(
        main=lambda: (_ for _ in ()).throw(SystemExit(0))))
    with pytest.raises(SystemExit):
        launch.run()
    assert not os.path.exists(launch.log_file())


def test_a_log_that_cant_be_written_still_lets_the_error_through(tmp_path):
    blocked = tmp_path / "a file, not a folder"
    blocked.write_text("x", encoding="utf-8")
    launch.write_failure(ValueError("boom"), str(blocked / "logs" / "ghmanage.log"))  # no raise
