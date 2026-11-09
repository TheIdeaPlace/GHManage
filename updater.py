"""Automatic updates via Velopack.

Two things have to happen for updates to work:

1. `bootstrap()` runs at the very top of `main()`, before anything else parses
   argv or creates a wx.App. Velopack's Update.exe re-launches the app with
   hook arguments (install, update, uninstall, first-run); `bootstrap()` handles
   those and exits the process. Skip it and installs/updates silently misbehave.
2. `UpdateService` checks GitHub Releases, downloads in the background, and
   applies on restart. On Windows that happens only from a Velopack-installed
   copy — a portable ghmanage.exe has nothing to update and is left alone. On
   macOS every GHManage.app can update itself, whether it came from the .pkg,
   the DMG, or the portable zip, because the bundle carries its own updater.

Local testing without publishing a release: pass `--update-feed <dir>` pointing
at a `vpk pack` output folder. See docs/INSTALLER.md.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("ghmanage.updater")

REPO_URL = "https://github.com/TheIdeaPlace/GHManage"
RELEASES_URL = f"{REPO_URL}/releases"


def _log_path() -> str:
    if sys.platform == "darwin":
        # ~/Library/Logs is where macOS expects an app's logs, and it is what
        # Console.app shows under "Log Reports" — the equivalent of telling a
        # Windows user to open %APPDATA%.
        return os.path.join(
            os.path.expanduser("~"), "Library", "Logs", "GHManage",
            "ghmanage-update.log",
        )

    # %APPDATA%, not %LOCALAPPDATA% — the latter is where Velopack installs the
    # app and manages its contents; nothing of ours belongs in there.
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "GHManage", "ghmanage-update.log")


def configure_logging(debug: bool = False) -> None:
    """Log update activity to the platform's per-user log location.

    %APPDATA%\\GHManage\\ghmanage-update.log on Windows,
    ~/Library/Logs/GHManage/ghmanage-update.log on macOS.

    A silently broken updater cannot fix itself in the field — every failure
    path below logs, so a stranded install can be diagnosed from this file.
    """
    try:
        path = _log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG if debug else logging.INFO)
        logger.propagate = False
    except Exception:  # logging must never stop the app starting
        pass


def bootstrap(auto_apply: bool = True) -> None:
    """Run the Velopack app hooks. Call first thing in main().

    ``auto_apply`` False (Help > Automatic Updates off): an update downloaded
    earlier is left uninstalled at startup; Help > Check for Updates can
    still install one when asked."""
    # Only a packaged build is ever launched by Update.exe. Running the hooks
    # from a source checkout does nothing except print a confusing
    # "NotInstalled" error from the native layer.
    if not getattr(sys, "frozen", False):
        logger.debug("not a packaged build; skipping Velopack bootstrap")
        return

    try:
        import velopack
    except ImportError:
        logger.debug("velopack not installed; skipping bootstrap")
        return

    try:
        # auto_apply_on_startup: a package downloaded during a previous session
        # is installed here, before any window appears, and the app relaunches
        # on the new version. This is what makes updates automatic — the user
        # never has to act. Set explicitly rather than relying on the default.
        velopack.App().set_auto_apply_on_startup(bool(auto_apply)).run()
    except Exception as exc:
        logger.error("Velopack bootstrap failed: %s", exc)


@dataclass
class UpdateInfo:
    version: str
    whats_new_url: str


class UpdateService:
    """Checks for, downloads, and applies updates."""

    def __init__(self, current_version: str, feed: Optional[str] = None) -> None:
        self.current_version = current_version
        self._feed = feed
        self._manager = None
        self._pending = None
        self._download_thread: Optional[threading.Thread] = None
        self._downloaded = False
        self._resolved = False

    # ── internals ────────────────────────────────────────────────────────

    def _get_manager(self):
        """Return an UpdateManager, or None if this copy can't self-update."""
        if self._resolved:
            return self._manager
        self._resolved = True

        try:
            import velopack
        except ImportError:
            logger.info("velopack not installed; updates disabled")
            return None

        try:
            # A local folder of `vpk pack` output overrides the GitHub feed.
            source = self._feed if self._feed else velopack.GithubSource(REPO_URL)
            mgr = velopack.UpdateManager(source)

            # Velopack only manages copies it installed. A portable exe (or a
            # `python ghviewer.py` run) reports portable and is left alone.
            #
            # Windows only. Velopack's macOS locator hardcodes IsPortable: true
            # for every .app it can locate — a Mac bundle carries its own
            # UpdateMac and update feed wherever it sits, so Velopack draws no
            # installed/portable distinction there. Applying this guard on macOS
            # would therefore disable updates for every Mac user, including
            # .pkg installs, and do it silently: the log line below is the only
            # symptom, and "no update available" never appears because the
            # check returns before it. The .app is updatable from /Applications,
            # ~/Applications, or wherever the user dragged it.
            if sys.platform == "win32" and mgr.get_is_portable():
                logger.info("running portable; updates disabled")
                return None

            logger.info(
                "update manager ready (installed version %s)",
                mgr.get_current_version(),
            )
            self._manager = mgr
            return mgr
        except Exception as exc:
            logger.info("update manager unavailable: %s", exc)
            return None

    # ── public API ───────────────────────────────────────────────────────

    def check_for_update(self) -> Optional[UpdateInfo]:
        """Check the feed. On a hit, start downloading in the background.

        Safe to call from a worker thread. Returns None when up to date or
        when this copy can't self-update.
        """
        mgr = self._get_manager()
        if not mgr:
            return None

        try:
            update = mgr.check_for_updates()
        except Exception as exc:
            logger.error("update check failed: %s", exc)
            return None

        if not update:
            logger.info("no update available")
            return None

        version = update.TargetFullRelease.Version
        logger.info("update %s available; downloading in background", version)
        self._pending = update
        self._start_background_download(mgr, update)

        return UpdateInfo(
            version=version,
            whats_new_url=f"{RELEASES_URL}/tag/v{version}",
        )

    def _start_background_download(self, mgr, update) -> None:
        def download() -> None:
            try:
                mgr.download_updates(update)
                self._downloaded = True
                logger.info(
                    "update %s downloaded; will be applied on restart",
                    update.TargetFullRelease.Version,
                )
            except Exception as exc:
                logger.error("background download failed: %s", exc)

        self._download_thread = threading.Thread(target=download, daemon=True)
        self._download_thread.start()

    def apply_update_and_restart(self, args: Optional[list[str]] = None) -> bool:
        """Apply the pending update and relaunch. Returns False if not ready."""
        mgr = self._get_manager()
        update = self._pending
        if not mgr or not update:
            return False

        # The download runs in the background; wait for it before applying.
        if self._download_thread and self._download_thread.is_alive():
            logger.info("waiting for download to finish before applying")
            self._download_thread.join(timeout=120.0)

        if not self._downloaded:
            logger.error("download incomplete; not applying")
            return False

        try:
            restart_args = list(args) if args else []
            mgr.apply_updates_and_restart_with_args(update, restart_args)
            return True
        except Exception as exc:
            logger.error("apply and restart failed: %s", exc)
            return False

    @property
    def is_download_complete(self) -> bool:
        return self._downloaded

    @property
    def is_update_pending(self) -> bool:
        return self._pending is not None
