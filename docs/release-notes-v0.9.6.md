# GHManage 0.9.6

GHManage is a desktop app for reading and managing your GitHub repositories from
a fast, keyboard-driven list.

On a Mac, use `Cmd` where these notes say `Ctrl`, and `Option` where they say `Alt`.

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
  "Available columns" and "Shown columns". Every labelled list, choice and
  text box now has its label on a Mac, in every dialog and in the main
  window's repository list, item list and details panel. (#69)

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
