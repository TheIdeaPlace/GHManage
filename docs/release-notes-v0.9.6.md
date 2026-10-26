# GHManage 0.9.6

GHManage is a desktop app for reading and managing your GitHub repositories from
a fast, keyboard-driven list.

This release can archive and delete repositories on GitHub. Deleting needs a
one-time step first, described in the next section. GHManage also tells your
screen reader what an action in the Columns dialog did, and screen readers on
a Mac now read the labels in GHManage's dialogs.

On a Mac, use `Cmd` where these notes say `Ctrl`, and `Option` where they say `Alt`.

## Before you delete a repository: one step in a terminal

This release can delete a repository on GitHub. Before the first time you do,
gh needs one more permission. GitHub doesn't give it when you sign in to gh,
because deleting can't be undone. Do this once:

1. Open a terminal: Command Prompt or PowerShell on Windows, or Terminal on a
   Mac.
2. Type this command and press `Enter`:

   `gh auth refresh -h github.com -s delete_repo`

3. gh shows a one-time code, such as `ABCD-1234`, and asks you to press `Enter`.
   Note the code, then press `Enter`, and your browser opens on GitHub.
4. In the browser, type the code and approve. gh then says it is done, and you
   can close the terminal.

If you skip this, GHManage doesn't delete anything. It shows you the same
command when you try. You only need to do this once for each GitHub account.

You also need admin rights on the repository. You have them on your own
repositories. For one that belongs to someone else or to an organization,
GHManage tells you if you don't have them.

## Archive or delete a repository on GitHub

Select a repository in the list, then choose **File → Archive or Unarchive
Repository…** or **File → Delete Repository from GitHub…**. Both are on the
repository's context menu too. Neither has a shortcut key, so a slip of the
finger can't reach them. (#68)

- **Archive** is the safe choice if you just want a repository left alone. It
  becomes read-only on GitHub: no new issues, pull requests, comments or
  pushes, but nothing is lost and you can still read everything. Undo it with
  **Unarchive**. Archiving needs no extra permission.
- **Delete** removes the repository from GitHub for good, with its code,
  issues, pull requests, releases, wiki and Actions history. This can't be
  undone. To confirm, you type the repository's name, for example
  `owner/name`, as you would on github.com. **Delete** stays unavailable until
  the name matches, and GHManage says when it becomes available. **Cancel** is
  the default, and pressing `Enter` never deletes on its own. Afterwards the
  repository is gone from the list, your pinned repositories and your
  favorites.

**Remove from List** (`Delete` in the repository list) hasn't changed. It only
takes a repository off GHManage's list and never touches GitHub.

## GHManage tells your screen reader what an action did

In **View → Columns…**, every action is now said, not just shown: "Author
moved above Message", "Author moved to the top", "Branches added at the end,
5 of 5", "Author removed, 3 columns shown", "Columns reset to the default".
When there is nothing to do, you hear why, such as "Commit is already at the
top", rather than only a beep. A move names the column it is now next to, so
you know what changed without counting positions. (#65)

It is shown under the lists too. On Windows it is sent as a UI Automation
notification, the standard way for an app to give a screen reader something to
say, so your screen reader speaks it in your own voice and settings, with
nothing extra installed. **View → Speak Results** turns it off and on.

## Fixed

- **The Search GitHub dialog no longer reads its examples when it opens.**
  Screen readers read the examples under the Search box along with the box
  itself. They are now in an **Examples** box you go to when you want them
  (`Alt+X`, or `Shift+Tab` from Search for), so opening the dialog says its
  title and "Search". The Search Qualifiers table's note about numbers,
  dates and ranges works the same way, under **Notes** (`Alt+N`). (#60)
- **On a Mac, screen readers now read the labels of lists, choices and text
  boxes in dialogs.** Before, they could read what was in a box without what
  the box was for, such as the two lists in **View → Columns…** without
  "Available columns" and "Shown columns". Lists, choices and text boxes now
  have their labels on a Mac, in the dialogs and in the main window's
  repository list, item list and details panel. (#69)
- **On a Mac, Help → Keyboard Shortcuts and the Command Palette open
  again.** They failed to open there; Windows was not affected.

## Before you start

GHManage drives the [GitHub CLI](https://cli.github.com/), so install it and sign
in first:

```
gh auth login
```

GHManage never asks for or stores credentials of its own — every request goes
through `gh`.

## Updating

If you already have GHManage installed you do not need to download anything; this
version will arrive on its own.

## Downloads

| File | Use it if |
|------|-----------|
| `GHManage-win-Setup.exe` | Windows, installed and updating itself |
| `GHManage-win-Portable.zip` | Windows, a folder to run from anywhere, no install, no updates |
| `GHManage-osx.dmg` | macOS, drag to Applications |
| `GHManage-osx-Portable.zip` | macOS, unzip it yourself |

The remaining files (`*.nupkg`, `RELEASES`, `releases.win.json`,
`assets.win.json`, `releases.osx.json`, `assets.osx.json`) are the update feed
the installed app reads. Leave them alone.

## Requirements

- Windows 10 or 11, 64-bit — or an Apple Silicon Mac on macOS 11 or newer
- The [GitHub CLI](https://cli.github.com/), installed and authenticated with
  `gh auth login`
