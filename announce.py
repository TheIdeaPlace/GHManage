"""Things GHManage says to the screen reader, as well as showing them.

Every message has a category, after QuickMail's ``AnnouncementCategory``:

- ``RESULT``: the outcome of something you just did ("Author moved above
  Message"). It interrupts, since it answers the key you pressed.
- ``STATUS``: background progress. It waits its turn.
- ``HINT``: a tip you can silence once you know the app. It waits behind
  whatever is being read, so it never cuts off the row you landed on.
- ``SILENT``: never spoken; the outcome is already evident.

The user turns spoken feedback off altogether, or one category at a time
(``settings.load_announcements``). Nothing here knows about wx or a platform:
the ``speaker`` that does the speaking is set by the app at startup (UI
Automation notifications on Windows, a VoiceOver announcement on a Mac), so
the wording and the filtering can be tested anywhere, and the module can move
to app-kit for the other apps.

Call it from the UI thread only: the speakers post to the window system.
"""

from __future__ import annotations

from typing import Callable

RESULT = "result"
STATUS = "status"
HINT = "hint"
SILENT = "silent"

# The categories the user can switch, in the order they're offered.
CATEGORIES = (RESULT, STATUS, HINT)

# speaker(text, interrupt, category) -> whether it was handed to a screen reader.
Speaker = Callable[[str, bool, str], bool]
# observer(text, category): sees every message that passes the filters.
Observer = Callable[[str, str], None]


class Announcer:
    def __init__(self) -> None:
        self.enabled = True
        self.categories: dict[str, bool] = {c: True for c in CATEGORIES}
        self.speaker: Speaker | None = None
        self.observers: list[Observer] = []

    def configure(self, enabled: bool, categories: dict[str, bool]) -> None:
        self.enabled = bool(enabled)
        for c in CATEGORIES:
            if c in categories:
                self.categories[c] = bool(categories[c])

    def would_speak(self, category: str, force: bool = False) -> bool:
        if category == SILENT or category not in CATEGORIES:
            return False
        return force or (self.enabled and self.categories[category])

    def announce(self, text: str, category: str = RESULT, force: bool = False,
                 queued: bool = False) -> bool:
        """Say ``text`` if the user wants this category spoken. ``force``
        is for the few things that must be heard whatever the settings, such
        as "Spoken feedback off" itself. True when a screen reader was given
        it; False when filtered out, or when there is nothing to speak with,
        in which case the status bar, written by the caller, is all there is.
        ``queued`` lets a result follow what is being read instead of cutting
        it off: for an action that moved focus, said after the focus change.
        """
        text = (text or "").strip()
        if not text or not self.would_speak(category, force):
            return False
        for observe in list(self.observers):
            observe(text, category)
        if self.speaker is None:
            return False
        try:
            interrupt = not queued and (force or category == RESULT)
            return bool(self.speaker(text, interrupt, category))
        except Exception:  # speech must never take the app down with it
            return False


# The app's one announcer.
announcer = Announcer()


def announce(text: str, category: str = RESULT, force: bool = False,
             queued: bool = False) -> bool:
    return announcer.announce(text, category, force, queued)
