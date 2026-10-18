# GHManage 0.9.3

GHManage is a desktop app for reading and managing your GitHub repositories from
a fast, keyboard-driven list.

This release keeps you in GHManage more often. Activity opens what an event is
about right here, and a repository's right-click menu goes straight to any of
its views. The search dialog can now tell you GitHub's search terms.

On a Mac, use `Cmd` where these notes say `Ctrl`, and `fn+F1` for `F1` unless
your function keys are set to work as standard keys.

## Activity opens things here

Enter on an Activity event now opens what it's about inside GHManage, not on
GitHub:

- an issue or pull request opens in its repository's Issues & PRs, selected;
- a release opens in Releases;
- a commit opens in Commits, and a branch in that branch's commits.

`Backspace` brings you back to the same event. Anything GHManage has no view
for, such as a push's comparison or a discussion, still opens on GitHub, and
`Ctrl+O` always opens the event on GitHub.

Wherever a list sends you, the status bar now says where `Backspace` goes, for
example "Backspace=back to activity".

## Search operators

You don't have to remember GitHub's search terms. In the Search GitHub dialog
(`Ctrl+Shift+F`), press `F1` or choose **Search Operators…** for a table of them,
each with what it means and an example, such as `review-requested:@me` or
`label:bug`. The table matches what you're searching: issues and pull requests,
or repositories.

- Type in **Filter** to narrow the table, for example "review" or "date".
- `Enter` puts the selected term into your query where the cursor was.
- **Open GitHub Search Documentation** opens GitHub's full reference.

## Go To a repository's views

A repository's right-click menu (the Applications key or `Shift+F10`; on a Mac,
`VO+Shift+M` with VoiceOver, or `Ctrl`-click) has a new
**Go To** submenu: Issues & PRs, Branches, Commits, Tags, Releases, Workflows,
Workflow Runs, Labels and GitHub Pages. It's there in the repository list, and
on repositories in Starred, Watched, Shared With Me, an organization's
repositories and repository search results. From one of those lists,
`Backspace` comes back to the same row.

## Copy clone URLs

**Actions ▸ Copy** has **Copy HTTPS Clone URL** and **Copy SSH Clone URL**, the
addresses `git clone` takes, for the repository in front of you. They're also
on a repository's right-click Copy menu.

## Smaller changes

- **View More** is on the right-click menu of every list that loads in pages,
  not only on the File menu.
- Menu items with a single-letter key in the list now show it next to their
  `Ctrl` shortcut, for example "Refresh (R)" and "Close Issue/PR (C)".
- Activity's right-click menu starts with **Open**, like Notifications'.

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
