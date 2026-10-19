# GHManage 0.9.4

GHManage is a desktop app for reading and managing your GitHub repositories from
a fast, keyboard-driven list.

This release lets you take any repository out of the list, and adds two ways
to find your way round GHManage: a list of every keyboard shortcut, and a
command palette. The Search GitHub dialog is also quieter and easier to use
with a screen reader.

On a Mac, use `Cmd` where these notes say `Ctrl`.

## Take any repository out of the list

`Delete` in the repository list, or **File → Remove from List**, now works for
your own repositories, not only ones you opened by address (#2). Before, it
said they couldn't be removed, and only on the status bar.

- GitHub lists your own repositories every time, so GHManage hides the ones
  you remove. Nothing changes on GitHub.
- **File → Hidden Repositories…** lists them. `Enter` puts the selected one back.
- After a removal you stay where you were, on the next repository.
- Removing a saved search now asks first, since it can't be brought back.

## Keyboard Shortcuts

**Help → Keyboard Shortcuts** (`Ctrl+F1`) lists every key in GHManage: the
single letters in the lists and every menu shortcut. It shows the key, the
command and where it works, and you can type to filter it (#3).

## Command Palette

**Help → Command Palette** (`Ctrl+Shift+P`) finds a command by name and runs
it (#27). Type a few letters, press `Down Arrow` to move into the list, then
`Enter`. It lists only the commands that work where you are, with each one's
shortcut and menu.

When you pause typing, it says how many commands match and which one `Enter`
will run, for example "2 commands. Enter runs Branches, Ctrl+2." NVDA reads
this as you go. Menus are separated with ">", for example "View > View Mode".

## Search GitHub

- The search box is now labelled just **Search**, and no longer has example
  text inside it. When you move back to the box, your screen reader reads
  "Search, edit" and nothing more. When the dialog first opens, JAWS and NVDA
  still read the explanation of how to search, with its examples, because it
  is part of the dialog. A future version will improve this.
- GitHub calls `is:open`, `label:bug` and the rest **qualifiers**, so the
  table of them is now **Search Qualifiers**. **It has moved from `F1` to
  `Alt+Q`** (**Insert Qualifier…**).
- `F1` in the search dialog is help now: it opens the guide's page on
  searching GitHub.

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
