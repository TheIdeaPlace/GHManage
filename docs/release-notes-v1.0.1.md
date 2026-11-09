# GHManage 1.0.1

GHManage is a desktop app for reading and managing your GitHub repositories from
a fast, keyboard-driven list.

On a Mac, use `Cmd` where these notes say `Ctrl`, and `Option` where they say `Alt`.

## Setting the milestone

You could list milestones and browse their issues, but not put anything in one.
Now `I` in Issues & PRs, or **Actions → Set Milestone…**, puts the selected issue
or pull request in one of the repository's open milestones, or takes it out (#120).

The box lists "No milestone" first, then the open milestones with their due dates,
with the item's current one selected. GHManage says where it went, "#12 is in
milestone 2027.1.", and the row changes in place, so you keep your place in the list.

An issue's or pull request's milestone is now on a "Milestone:" line in the details
panel, and there is a **Milestone** column to add under **View → Columns…**.

## Labels, assignees, projects, title and description

The rest of an issue or pull request can be changed from the list as well (#122):

- `L` sets its labels, `A` its assignees and `P` the projects it is in, the
  repository's and its owner's. Each is a list where every row says whether it is
  checked ("bug, checked"). `Space` changes a row and `Enter` saves. GHManage then
  says what changed: "#12: added bug, removed docs. Labels now: bug, ui."
- `E` edits the title and description, in the same form as New Issue.

These are also on the **Actions** menu, and they work from the details panel too.

## Filtering by people and milestone

**View → Filter** now has **Assigned to Me**, **Assigned To…**, **Opened by Me**,
**Opened By…**, **No Assignee** and **No Milestone**, and they combine. Together,
Assigned to Me and No Milestone list your work that isn't planned yet. **Clear These
Filters** turns them off. The status bar and window title say which are on.

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
