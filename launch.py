"""The packaged app's entry point: GHManage, with any failure to start logged.

PyInstaller builds from this file, not ghviewer.py, so that an exception while
ghviewer and its modules are still being imported (a wx library that won't
load, a module that fails on something in this computer) is written to the log
too. A packaged build shows such an exception only in its "Unhandled exception
in script" box, which can't always be copied (#142).

Only the standard library is used before ghviewer is imported, since anything
else could be what failed. From source, ``python ghviewer.py`` is the same app.
"""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime


def log_file() -> str:
    """ghmanage.log in the folder bugreport.log_folder uses."""
    if sys.platform == "darwin":
        folder = os.path.join(os.path.expanduser("~"), "Library", "Logs", "GHManage")
    else:
        base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
        folder = os.path.join(base, "ghmanage", "logs")
    return os.path.join(folder, "ghmanage.log")


def write_failure(exc: BaseException, path: str | None = None) -> None:
    """The exception and its stack at the end of the log, in its format. Never
    raises: the box the packaged build shows next must still appear."""
    try:
        path = path or log_file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip()
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{stamp} ERROR ghmanage: Unhandled exception in starting GHManage:\n"
                    f"{text}\n")
    except Exception:
        pass


def run() -> None:
    try:
        import ghviewer
        ghviewer.main()
    except (SystemExit, KeyboardInterrupt):
        raise
    except BaseException as exc:
        # main() logs what goes wrong once it is running; this is the rest.
        if not getattr(exc, "_ghmanage_logged", False):
            write_failure(exc)
        raise


if __name__ == "__main__":
    run()
