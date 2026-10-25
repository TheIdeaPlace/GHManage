# GHManage 0.9.6

GHManage is a desktop app for reading and managing your GitHub repositories from
a fast, keyboard-driven list.

On a Mac, use `Cmd` where these notes say `Ctrl`, and `Option` where they say `Alt`.

## Fixed

- **The Search GitHub dialog no longer reads its examples when it opens.**
  Screen readers read the examples under the Search box along with the box
  itself. They are now in an **Examples** box you go to when you want them
  (`Alt+X`, or `Shift+Tab` from Search for), so opening the dialog says its
  title and "Search". The Search Qualifiers table's note about numbers,
  dates and ranges works the same way, under **Notes** (`Alt+N`). (#60)

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
