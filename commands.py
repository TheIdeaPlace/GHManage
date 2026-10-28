"""Commands and keys, for Help ▸ Keyboard Shortcuts (#3) and the command
palette (#27).

The menus already name every command, its shortcut and whether it applies
right now, so both are built by walking the menu bar (in ``ghviewer``) into
``Command`` rows rather than from a second list that could drift from them.
What the menus can't carry are the bare keys in a list, F, R, C, Delete and
the rest, since a bare-letter accelerator would fire while typing anywhere.
Those are in ``LIST_KEYS`` below, and must be kept in step with the key
handlers in ``ghviewer`` (``on_repo_key_down``, ``_on_list_key`` and
``on_char_hook``).
"""

from __future__ import annotations

from dataclasses import dataclass


# Between a menu and its submenu in "where": "View > View Mode". Plain ">"
# rather than a typographic arrow, which screen readers read out by its
# Unicode name ("black right-pointing small triangle").
MENU_SEP = " > "


@dataclass(frozen=True)
class Command:
    name: str          # "Refresh (R)", as on the menu without its mnemonic
    keys: str = ""     # "Ctrl+R", or "" when it has no shortcut
    where: str = ""    # "File", "Actions > Copy", or for a list key "Issues list"
    id: int = 0        # the menu id the palette posts; 0 for a list key
    checked: bool = False  # a check or radio item that is on


def split_label(label: str) -> tuple[str, str]:
    """A menu label's name and shortcut: "&Refresh (R)\\tCtrl+R" is
    ("Refresh (R)", "Ctrl+R"). "&&" is a literal ampersand."""
    name, _, keys = label.partition("\t")
    name = name.replace("&&", "\0").replace("&", "").replace("\0", "&")
    return name.strip(), keys.strip()


def matching(commands: list[Command], text: str) -> list[Command]:
    """The commands with every word of ``text`` in their name, shortcut or
    menu. Ones whose name starts with what was typed come first; otherwise
    menu order is kept, so related commands stay together."""
    words = text.lower().split()
    if not words:
        return list(commands)
    hits = [c for c in commands
            if all(w in f"{c.name} {c.keys} {c.where}".lower() for w in words)]
    typed = text.strip().lower()
    return sorted(hits, key=lambda c: not c.name.lower().startswith(typed))


REPO_LIST = "Repository list"
ANY_LIST = "Any list"
ISSUES = "Issues & PRs list"
LABELS = "Labels list"
RUNS = "Workflow runs and jobs"
NOTIFICATIONS = "Notifications list"
FEEDS = "Activity, Notifications, My Work and search results"
PAGES = "GitHub Pages"
CHANGES = "Issues & PRs list and Commits list"
FILES = "Changed Files"
CODE = "Files"
HISTORY = "File History"
COMMITS = "Commits list"
WINDOW = "Anywhere in the window"

LIST_KEYS: list[Command] = [
    Command("Move to the next pane", "F6", WINDOW),
    Command("Move to the previous pane", "Shift+F6", WINDOW),
    Command("Context menu", "Applications or Shift+F10", WINDOW),
    Command("Open the selected entry", "Enter", REPO_LIST),
    Command("Add the repository to favorites, or remove it", "F", REPO_LIST),
    Command("Remove from the list", "Delete", REPO_LIST),
    Command("Open the item, or go into it", "Enter", ANY_LIST),
    Command("Add to favorites, or remove", "F", ANY_LIST),
    Command("Refresh", "R", ANY_LIST),
    Command("Clear the quick filter", "Escape", ANY_LIST),
    Command("Back to where you came from", "Backspace", ANY_LIST),
    Command("Close the issue or pull request", "C", ISSUES),
    Command("Reopen it", "O", ISSUES),
    Command("Add a comment", "M", ISSUES),
    Command("New issue", "N", ISSUES),
    Command("Pull request checks", "K", ISSUES),
    Command("Review the pull request", "V", ISSUES),
    Command("Ready for review, or back to draft", "D", ISSUES),
    Command("The pull request's or commit's changed files", "H", CHANGES),
    Command("The commit's changed files", "Enter", COMMITS),
    Command("Read the file's changes", "Enter", FILES),
    Command("Back to the pull request or commit", "Backspace", FILES),
    Command("Open the file whole, in Files", "W", FILES),
    Command("Comment on the pull request's line the caret is on, in its lines", "M", FILES),
    Command("Open the folder, or read the file", "Enter", CODE),
    Command("Up a folder", "Backspace", CODE),
    Command("The file's history", "H", CODE),
    Command("Blame: who last changed each line, or the file again", "B", CODE),
    Command("Next or previous Markdown heading, or blame run", "Alt+N, Alt+P", CODE),
    Command("The commit's changed files", "Enter or H", HISTORY),
    Command("Back to the file", "Backspace", HISTORY),
    Command("New label", "Insert", LABELS),
    Command("Delete the label", "Delete", LABELS),
    Command("Show jobs", "J", RUNS),
    Command("Show what failed", "L", RUNS),
    Command("Rerun", "E", RUNS),
    Command("Cancel the run", "X", RUNS),
    Command("Delete the run", "Delete", RUNS),
    Command("Mark as read", "M", NOTIFICATIONS),
    Command("Mark as done", "Delete", NOTIFICATIONS),
    Command("Unsubscribe from the thread", "U", NOTIFICATIONS),
    Command("Include read notifications, or unread only", "I", NOTIFICATIONS),
    Command("Go to the repository", "G", FEEDS),
    Command("Open the published site", "S", PAGES),
]


def shortcut_rows(menu_commands: list[Command]) -> list[Command]:
    """Every shortcut: the list keys, then each menu command that has one."""
    return LIST_KEYS + [c for c in menu_commands if c.keys]


def summary(shown: list[Command], palette: bool) -> str:
    """What the filter has found, said after each pause in typing: how many
    match and, in the palette, what Enter would run."""
    if not shown:
        return "No commands match." if palette else "No shortcuts match."
    n = len(shown)
    if not palette:
        return f"{n} shortcut{'s' if n != 1 else ''}."
    first = shown[0]
    name = first.name.rstrip("…")  # "Enter runs Merge.", not "Merge…."
    runs = f"{name}, {first.keys}" if first.keys else name
    return f"{n} command{'s' if n != 1 else ''}. Enter runs {runs}."
