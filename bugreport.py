"""Help ▸ Report a Bug…: what the form collects, the text it sends, how it's
sent, and the crash log and quit check that a report can carry.

The report goes to The Idea Place's shared bug-report relay (TheIdeaPlace/
app-kit, relay/), a Cloudflare Worker that files it as a GitHub issue in this
repo under a bot account, so nobody needs a GitHub account to report a bug.
When the relay can't be reached, or this copy was built without a relay key
(any build but a release), the whole report goes on the clipboard and GitHub's
new issue page can be opened with it filled in.

Built to the baseline in The-Idea-Place-Projects/baseline/bug-reports.md, after
My Photo Library Described's BugReport.cs. Nothing here knows about wx, and the
network is a function, so all of it is tested without sending anything; the
form is ``BugReportDialog`` in ghviewer.

What a report may say about the computer is a fixed list (``system_lines``),
and all of it is in the preview, so the person reads everything that is sent.
"""

from __future__ import annotations

import json
import locale
import logging
import logging.handlers
import os
import platform
import re
import ssl
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import quote

from favorites import _app_data_dir as app_data_dir
from updater import REPO_URL
from version import __version__ as APP_VERSION

# Written by the release workflow from the APPKIT_RELAY_URL variable and the
# APPKIT_RELAY_KEY secret, and never committed. A build without it (from
# source, a fork, a pull request) has no key and uses the GitHub page instead.
try:
    import _relay_config  # type: ignore[import-not-found]
except ImportError:
    _relay_config = None

APP_NAME = "GHManage"
APP_ID = "ghmanage"  # the relay's APPS key, which picks this repo
ISSUES_NEW_URL = f"{REPO_URL}/issues/new"

BUG = "bug"
SUGGESTION = "suggestion"
KINDS = (BUG, SUGGESTION)
KIND_NAMES = {BUG: "Bug", SUGGESTION: "Suggestion"}

# The form's three boxes, by kind: (label, heading in the issue). The first is
# required. A suggestion has two; its third box is hidden.
FIELDS = {
    BUG: (
        ("What &happened (required)", "What happened"),
        ("What you &expected", "What you expected"),
        ("Steps to &reproduce", "Steps to reproduce"),
    ),
    SUGGESTION: (
        ("Your s&uggestion (required)", "Suggestion"),
        ("How it would &help", "How it would help"),
    ),
}

# The relay cuts a body at 8,000 characters, which would lose the end of a
# crash log, the part that matters. So the body is kept under this, attached
# lines go oldest first, and the preview stays exactly what is filed.
LONGEST_BODY = 7800
# What the person types is held to these, so their words and the system
# information always fit in LONGEST_BODY with room for attachments: three
# answers of LONGEST_ANSWER come to 6,000. The relay cuts a title at 200 and a
# contact at 200; cutting them here keeps the preview what is filed.
LONGEST_TITLE = 190  # with "[Windows] " in front, under the relay's 200
LONGEST_ANSWER = 2000
LONGEST_CONTACT = 200
LINES_LEFT_OUT = "(Earlier lines left out.)"
DIDNT_FIT = "(Left out: the report is too long to include it.)"

# The longest address GitHub's new issue page is given; longer ones risk the
# browser or GitHub refusing it. The encoded length is what counts.
LONGEST_PAGE_ADDRESS = 6000

# The relay gives up at 12 seconds, so a report it is still filing can't be
# filed again by hand; the app waits a little longer.
TIMEOUT = 15


def platform_tag() -> str:
    return "Mac" if sys.platform == "darwin" else "Windows"


# ── Privacy ──────────────────────────────────────────────────────────────


def redact(text: str, home: Optional[str] = None) -> str:
    """``text`` with the home folder written as ``~``, so a path in a crash
    doesn't name the person. Either slash, any case on Windows."""
    home = (home if home is not None else os.path.expanduser("~")).rstrip("\\/")
    if len(home) < 3:  # "~" or "/" unexpanded: nothing safe to replace
        return text
    pattern = r"[\\/]".join(re.escape(part) for part in re.split(r"[\\/]", home))
    flags = re.IGNORECASE if sys.platform == "win32" or re.match(r"^[A-Za-z]:", home) else 0
    return re.sub(pattern + r"(?=$|[\\/\s'\"),:;])", "~", text, flags=flags)


# ── The report ───────────────────────────────────────────────────────────


@dataclass
class Attachment:
    """What came with a report from elsewhere: the crash, the log. Redacted
    already. ``name`` is how the form's check box says it ("the crash")."""

    name: str
    heading: str
    text: str


@dataclass
class Report:
    kind: str = BUG
    title: str = ""
    answers: list[str] = field(default_factory=lambda: ["", "", ""])
    contact: str = ""
    include_system: bool = True
    system_text: str = ""
    attachments: list[Attachment] = field(default_factory=list)
    include_attachments: bool = True
    tag: str = field(default_factory=platform_tag)

    @property
    def full_title(self) -> str:
        """Every title starts "[Windows] " or "[Mac] ", so the platform can be
        told at a glance; GitHub's page gives labels only to triagers."""
        title = self.title.strip()[:LONGEST_TITLE].strip()
        title = title or ("Bug report" if self.kind == BUG else "Suggestion")
        return f"[{self.tag}] {title}"

    @property
    def labels(self) -> str:
        """For GitHub's page. The relay applies its own from ``kind``."""
        first = "bug" if self.kind == BUG else "enhancement"
        return f"{first},user-reported,{self.tag.lower()}"

    @property
    def contact_text(self) -> str:
        return self.contact.strip()[:LONGEST_CONTACT].strip()

    def missing(self) -> Optional[str]:
        """What must be filled in and isn't: "title", "first", or None."""
        if not self.title.strip():
            return "title"
        if not self.answers[0].strip():
            return "first"
        return None

    @property
    def attachments_label(self) -> str:
        """The form's check box for what came with the report."""
        names = list(dict.fromkeys(a.name for a in self.attachments))
        joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        return f"Include {joined}"

    @property
    def body(self) -> str:
        """The issue's text: the answers, the system information, then
        anything attached, within LONGEST_BODY. An empty answer is left out
        rather than sent as an empty heading."""
        sections: list[str] = []
        for (_, heading), answer in zip(FIELDS[self.kind], self.answers):
            answer = answer.strip()[:LONGEST_ANSWER].strip()
            if answer:
                sections.append(f"**{heading}**\n{answer}")
        if self.include_system and self.system_text:
            sections.append(f"**System**\n```\n{self.system_text}\n```")
        if self.include_attachments:
            room = LONGEST_BODY - sum(len(s) + 2 for s in sections)
            for a in self.attachments:
                if not a.text:
                    continue
                frame = len(f"**{a.heading}**\n```\n\n```") + 2
                text = _fitted(a.text, room - frame)
                section = (f"**{a.heading}**\n```\n{text}\n```" if text is not None
                           else f"**{a.heading}**\n{DIDNT_FIT}")
                # Even the note saying it was left out must fit, or the relay
                # would cut the end.
                if len(section) + 2 > room:
                    continue
                sections.append(section)
                room -= len(section) + 2
        return "\n\n".join(sections) if sections else "(No details given.)"

    @property
    def preview(self) -> str:
        """Exactly what Send sends: the title, the kind, the contact if there
        is one, and the body."""
        lines = [f"Title: {self.full_title}", f"Kind: {KIND_NAMES[self.kind]}"]
        if self.contact_text:
            lines.append(f"Contact: {self.contact_text}")
        return "\n".join(lines) + "\n\n" + self.body

    @property
    def clipboard_text(self) -> str:
        """The whole report, for pasting into GitHub's page."""
        text = self.full_title + "\n\n" + self.body
        if self.contact_text:
            text += f"\n\n**Contact**\n{self.contact_text}"
        return text

    def relay_payload(self) -> dict:
        """The relay's JSON: {title, body, kind, contact?}."""
        payload = {"title": self.full_title, "body": self.body, "kind": self.kind}
        if self.contact_text:
            payload["contact"] = self.contact_text
        return payload

    def issue_page_url(self) -> str:
        """GitHub's new issue page with the report filled in, cut short to fit
        the address when it must; the whole report is on the clipboard."""
        whole = self.body
        if self.contact_text:
            whole += f"\n\n**Contact**\n{self.contact_text}"

        def address(body: str) -> str:
            return (f"{ISSUES_NEW_URL}?title={quote(self.full_title, safe='')}"
                    f"&body={quote(body, safe='')}&labels={quote(self.labels, safe='')}")

        url = address(whole)
        length = len(whole)
        while len(url) > LONGEST_PAGE_ADDRESS and length > 0:
            length = length * 9 // 10
            url = address(whole[:length] + "\n\n(Cut short here: paste the rest from the clipboard.)")
        return url


def _fitted(text: str, room: int) -> Optional[str]:
    """``text``, or its last lines within ``room`` after LINES_LEFT_OUT;
    None when not even a line fits."""
    if len(text) <= room:
        return text
    kept: list[str] = []
    used = len(LINES_LEFT_OUT)
    for line in reversed(text.split("\n")):
        if used + len(line) + 1 > room:
            break
        kept.insert(0, line)
        used += len(line) + 1
    return LINES_LEFT_OUT + "\n" + "\n".join(kept) if kept else None


# ── What a report says about the computer ───────────────────────────────


def system_lines(channel: str, os_name: str, arch: str, screen_reader: str,
                 language: str, gh_version: str) -> str:
    """The allowed list, and nothing else: no log, no paths, no account."""
    return "\n".join([
        f"App: {APP_NAME} {APP_VERSION} ({channel})",
        f"OS: {os_name}",
        f"Architecture: {arch}",
        f"Screen reader: {screen_reader}",
        f"Language: {language}",
        f"GitHub CLI: {gh_version}",
    ])


def collect_system_text(gh_exe: str = "gh") -> str:
    """Gathers the allowed list. Slow parts (gh --version) are bounded; call
    it off the UI thread."""
    return system_lines(_channel(), _os_name(), platform.machine() or "unknown",
                        screen_reader(), _language(), _gh_version(gh_exe))


def _channel() -> str:
    if not getattr(sys, "frozen", False):
        return "from source"
    if sys.platform == "darwin":
        return "app"
    # Velopack puts Update.exe one folder above the app's current/ folder; a
    # portable copy has no installer beside it.
    exe_dir = Path(sys.executable).resolve().parent
    return "installed" if (exe_dir.parent / "Update.exe").exists() else "portable"


def _os_name() -> str:
    if sys.platform == "darwin":
        return f"macOS {platform.mac_ver()[0] or platform.release()}"
    if sys.platform == "win32":
        version = sys.getwindowsversion()
        name = "Windows 11" if version.build >= 22000 else f"Windows {platform.release()}"
        return f"{name} ({version.major}.{version.minor}.{version.build})"
    return f"{platform.system()} {platform.release()}"


def _language() -> str:
    if sys.platform == "win32":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, 85):
                return buf.value
        except Exception:
            pass
    try:
        lang = locale.getlocale()[0]
    except ValueError:
        lang = None
    return lang or os.environ.get("LANG", "").split(".")[0] or "unknown"


def _gh_version(gh_exe: str) -> str:
    try:
        out = subprocess.run(
            [gh_exe, "--version"], capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return "not found"
    match = re.search(r"gh version (\S+)", out)
    return match.group(1) if match else "unknown"


# The process names of the Windows screen readers, as the person would name them.
_WINDOWS_READERS = {
    "nvda.exe": "NVDA",
    "jfw.exe": "JAWS",
    "narrator.exe": "Narrator",
    "zoomtext.exe": "ZoomText",
    "fusion.exe": "Fusion",
    "dolphin.exe": "Dolphin",
}


def readers_in(process_names: list[str]) -> str:
    found = sorted({_WINDOWS_READERS[n.lower()] for n in process_names
                    if n.lower() in _WINDOWS_READERS})
    return ", ".join(found) if found else "none detected"


def screen_reader() -> str:
    try:
        if sys.platform == "win32":
            return readers_in(_windows_processes())
        if sys.platform == "darwin":
            import speech
            return "VoiceOver" if speech.voiceover_running() else "none detected"
    except Exception:
        pass
    return "unknown"


def _windows_processes() -> list[str]:
    """The names of running processes, from a toolhelp snapshot."""
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if snapshot in (None, wintypes.HANDLE(-1).value):
        return []
    names: list[str] = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            names.append(entry.szExeFile)
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return names


# ── Sending ──────────────────────────────────────────────────────────────


@dataclass
class Result:
    """Filed, with the issue's number and address; or not. ``no_key`` when
    this copy has no relay key, so nothing was tried."""

    number: int = 0
    issue_url: str = ""
    no_key: bool = False

    @property
    def filed(self) -> bool:
        return bool(self.issue_url)


def relay_config() -> tuple[str, str]:
    """(url, key) this copy sends with, or empty strings. GHMANAGE_RELAY_URL
    and GHMANAGE_RELAY_KEY, both set, stand in for a release build's."""
    url = os.environ.get("GHMANAGE_RELAY_URL", "")
    key = os.environ.get("GHMANAGE_RELAY_KEY", "")
    if url and key:
        return url, key
    if _relay_config is not None:
        return (getattr(_relay_config, "RELAY_URL", "") or "",
                getattr(_relay_config, "RELAY_KEY", "") or "")
    return "", ""


# transport(url, data, headers, timeout) -> (status, body)
Transport = Callable[[str, bytes, dict, float], "tuple[int, str]"]


def _ssl_context() -> ssl.SSLContext:
    # A packaged Mac app may have no certificate bundle of its own.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _urllib_transport(url: str, data: bytes, headers: dict, timeout: float) -> tuple[int, str]:
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def parse_reply(status: int, body: str) -> Optional[Result]:
    """The relay's {issueUrl, number}, or None for anything else."""
    if not 200 <= status <= 299:
        return None
    try:
        reply = json.loads(body)
    except ValueError:
        return None
    if not isinstance(reply, dict):
        return None
    number, url = reply.get("number"), reply.get("issueUrl")
    if (isinstance(number, int) and not isinstance(number, bool) and number > 0
            and isinstance(url, str) and url.startswith("https://")):
        return Result(number, url)
    return None


def send(report: Report, url: str, key: str,
         transport: Optional[Transport] = None) -> Result:
    """POST the report to the relay with this app's id and key; the key goes
    in a header and nowhere else. Never raises: anything but a filed issue is
    an unfiled Result, and the form falls back to GitHub's page."""
    if not url or not key:
        return Result(no_key=True)
    headers = {
        "Content-Type": "application/json",
        "X-AppKit-App": APP_ID,
        "X-AppKit-Key": key,
        # Required: Cloudflare turns away urllib's own "Python-urllib/3.x"
        # with a 403 (error 1010) before the relay ever sees the report.
        "User-Agent": f"{APP_NAME}/{APP_VERSION}",
    }
    try:
        data = json.dumps(report.relay_payload()).encode("utf-8")
        status, body = (transport or _urllib_transport)(url, data, headers, TIMEOUT)
    except Exception as exc:  # no network, timeout, TLS: all the same here
        log.info("The bug-report relay couldn't be reached (%s)", type(exc).__name__)
        return Result()
    filed = parse_reply(status, body)
    if filed:
        log.info("Report filed as issue #%d", filed.number)
        return filed
    log.info("The bug-report relay answered %d", status)
    return Result()


# ── The log and crashes ─────────────────────────────────────────────────

log = logging.getLogger("ghmanage")
LOG_NAME = "ghmanage.log"
LOG_BYTES = 512 * 1024
LOG_BACKUPS = 3
LOG_LINES_SENT = 40
LONGEST_LOG_LINE = 1500

# This session's last unhandled exception, redacted, for the form to offer.
last_error: Optional[str] = None


def log_folder() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / APP_NAME
    # Under %APPDATA%, not %LOCALAPPDATA%: Velopack installs into the latter
    # and replaces it on every update.
    return app_data_dir() / "logs"


CRASH_NAME = "crash.txt"
_crash_file = None  # held open for the whole run, for faulthandler


def configure_log() -> None:
    """A rotated log, always on, so a crash is recorded whatever else is set.

    A crash in native code (wx, ctypes) never reaches Python's handlers, so
    faulthandler writes the Python stack of every thread to crash.txt when
    one happens. The file is emptied at each start, so read it first
    (crash_attachment)."""
    global _crash_file
    try:
        folder = log_folder()
        folder.mkdir(parents=True, exist_ok=True)
        import faulthandler
        _crash_file = open(folder / CRASH_NAME, "w", encoding="utf-8")
        faulthandler.enable(file=_crash_file, all_threads=True)
    except Exception:
        pass
    try:
        folder = log_folder()
        folder.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            folder / LOG_NAME, maxBytes=LOG_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        log.propagate = False
    except Exception:  # logging must never stop the app starting
        pass


def record_exception(exc_type, exc, tb, where: str = "") -> None:
    """Log an unhandled exception with its stack, and keep it for a report."""
    global last_error
    if exc_type is None or issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        return
    text = "".join(traceback.format_exception(exc_type, exc, tb)).rstrip()
    last_error = redact(text)
    try:
        log.error("Unhandled exception%s:\n%s", f" in {where}" if where else "", text)
    except Exception:
        pass


def install_handlers() -> None:
    """Catch what nothing else does: on the UI thread (wxPython hands an
    exception in an event handler to sys.excepthook, and carries on) and on
    background threads."""
    previous = sys.excepthook
    previous_thread = threading.excepthook

    def on_exception(exc_type, exc, tb):
        record_exception(exc_type, exc, tb)
        previous(exc_type, exc, tb)

    def on_thread_exception(args):
        name = args.thread.name if args.thread else "a thread"
        record_exception(args.exc_type, args.exc_value, args.exc_traceback, name)
        previous_thread(args)

    sys.excepthook = on_exception
    threading.excepthook = on_thread_exception


def flag_path() -> Path:
    return app_data_dir() / "running.flag"


def begin_run(pid: Optional[int] = None,
              is_running: Optional[Callable[[int], bool]] = None,
              boot_time: Optional[float] = None) -> Optional[datetime]:
    """At start: when the last run didn't quit cleanly, when it started;
    otherwise None. Then marks this run.

    Not a crash: the flag's process is still running (a second copy was
    opened), or the computer has started since (it was shut down or lost
    power with GHManage open)."""
    pid = os.getpid() if pid is None else pid
    is_running = is_running or _is_running
    path = flag_path()
    previous = None
    try:
        if path.exists():
            owner = path.read_text(encoding="utf-8").strip()
            started = path.stat().st_mtime
            booted = _boot_time() if boot_time is None else boot_time
            if owner.isdigit() and int(owner) != pid and is_running(int(owner)):
                return None
            if not (booted and started < booted):
                previous = datetime.fromtimestamp(started)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(pid), encoding="utf-8")
    except Exception:  # unreadable, or a number no process could have
        try:
            path.write_text(str(pid), encoding="utf-8")
        except Exception:
            pass
        return None  # can't tell; nothing to offer, and never stop the start
    return previous


def end_run(pid: Optional[int] = None) -> None:
    """On a clean quit, and before an update restarts the app. Only the copy
    that wrote the flag removes it, so a second copy quitting doesn't hide the
    first one's crash."""
    pid = os.getpid() if pid is None else pid
    path = flag_path()
    try:
        if path.exists() and path.read_text(encoding="utf-8").strip() == str(pid):
            path.unlink()
    except OSError:
        pass  # left; offered next time


def _is_running(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _boot_time() -> Optional[float]:
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
            return time.time() - ctypes.windll.kernel32.GetTickCount64() / 1000
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True,
                                 text=True, timeout=3).stdout
            match = re.search(r"sec = (\d+)", out)
            return float(match.group(1)) if match else None
    except Exception:
        pass
    return None


def log_attachment(folder: Optional[Path] = None) -> list[Attachment]:
    """The last lines of the log, which end with the crash when there was one.
    Read at start, before this run writes, so they are the last run's."""
    path = (folder or log_folder()) / LOG_NAME
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-LOG_LINES_SENT:]
    except OSError:
        return []
    if not lines:
        return []
    lines = [line if len(line) <= LONGEST_LOG_LINE else line[:LONGEST_LOG_LINE] + " …"
             for line in lines]
    return [Attachment("the log", f"Log, last {len(lines)} lines", redact("\n".join(lines)))]


def crash_attachment(folder: Optional[Path] = None) -> list[Attachment]:
    """What faulthandler wrote when the last run crashed in native code, if
    it did. Read at start, before configure_log empties the file."""
    path = (folder or log_folder()) / CRASH_NAME
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return []
    if not text:
        return []
    lines = [line[:LONGEST_LOG_LINE] for line in text.splitlines()[-LOG_LINES_SENT:]]
    return [Attachment("the crash", "Crash", redact("\n".join(lines)))]


def error_attachment() -> list[Attachment]:
    """This session's last unhandled exception, if there was one."""
    if not last_error:
        return []
    return [Attachment("the error", "Last error", last_error)]
