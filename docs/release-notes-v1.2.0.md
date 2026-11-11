# GHManage 1.2.0

GHManage is a desktop app for reading and managing your GitHub repositories from
a fast, keyboard-driven list.

On a Mac, use `Cmd` where these notes say `Ctrl`, and `Option` where they say `Alt`.

This release adds Categories mode. Until now you picked a repository and then
looked at its issues, releases or runs, so checking the same thing in several
projects meant opening each one in turn. Now you can pick the kind of thing
instead, and see it from all the repositories you've chosen in one list (#130).

## Categories mode

**View → Navigate By → Categories** (`Ctrl+Shift+2`) turns the list on the left into
categories. **Navigate By → Repositories** (`Ctrl+Shift+1`) turns it back.
GHManage remembers which one you use.

The categories are Issues & PRs, Releases, Workflow Runs, Commits, Tags,
Milestones, Discussions and Security Alerts. In Categories mode, `Ctrl+1` to
`Ctrl+8` pick them. Each lists its kind from every repository you've chosen,
newest first, and every row starts with its repository.

- **Choose Repositories…**, the first entry, is a checklist of your repositories
  and your organizations'. **Add Repository…** takes any other repository by name
  or address. Only the ones you check are read.
- **Releases** starts with **View → Latest Release Only** checked: one row per
  repository, its latest release. That's the quickest way to see where every
  project stands.
- **Group by Repository**, at the bottom of **View → Sort Order**, lists all of
  one repository's items, then the next's. The other sort orders work too.
- **`]` and `[`** jump to the next or previous repository's items, from the list
  or the details panel.
- **Enter** opens the item in its own repository, on it, and **Backspace** comes
  back to the same row. **G** opens its repository.
- A repository that can't be read is named, with the reason, for example "not
  found, or no access". It's never left out without a word.
- In Issues & PRs, the edit keys work as in My Work: `I` milestone, `L` labels,
  `A` assignees, `P` projects and `E` title and description.

## Fixed

- With JAWS, pressing `Space` in Set Labels, Set Assignees, Set Projects or Choose
  Repositories read the row twice. It now reads once.

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
