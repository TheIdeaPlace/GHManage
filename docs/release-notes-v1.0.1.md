# GHManage 1.0.1

GHManage is a desktop app for reading and managing your GitHub repositories from
a fast, keyboard-driven list.

On a Mac, use `Cmd` where these notes say `Ctrl`, and `Option` where they say `Alt`.

This release lets you organize issues and pull requests without leaving GHManage.
Until now you could read them, comment on them, and close or reopen them, but
anything else meant a trip to github.com. Now you can set their milestone, labels,
assignees and projects, and edit their title and description, all from the list.
You can also narrow the list by those same things (#120, #122).

## Change an issue or pull request where you find it

Select an issue or pull request and press a key:

| Key | What it sets |
|-----|--------------|
| `I` | Its milestone |
| `L` | Its labels |
| `A` | Who it's assigned to |
| `P` | The projects it's in, the repository's and its owner's |
| `E` | Its title and description |

Each one is also on the **Actions** menu. They work in Issues & PRs, in **My
Work** and in search results, from the list or while you're reading the item in
the details panel.

They all work the same way:

- **One box, starting from what's there now.** Milestone is a list to choose
  one from. Labels, assignees and projects are lists where every row says
  whether it is checked, for example "bug, checked": press `Space` to change a
  row and `Enter` to save. Title and description open in the same form as New
  Issue.
- **You hear what changed,** for example "#12: added bug, removed docs. Labels
  now: bug, ui." The row and the details panel change where you are, so you keep
  your place in the list.
- **What you need doesn't have to exist yet.** **New milestone…**, **New
  Label…** and **New Project…** create one and use it straight away, so a
  repository's first milestone or label can be made right here.
- **Nothing is claimed that didn't happen.** Before offering a list, GHManage
  checks that you're allowed to make the change: GitHub ignores milestones,
  labels and assignees from people without access, and still reports success.
  If you can't make the change, or something goes wrong, a message box says so.
  Someone else's change made since your list loaded is kept, not undone.

Whatever you can set, you can also see. The details panel now shows an item's
milestone and its projects, each with its status, and **View → Columns…** has a
column for each: Labels, Assignees, Milestone and Projects. My Work and search
results gain Assignees and Milestone columns too.

## Give gh the permissions these need, all at once

Some of these features, and a few older ones, need GitHub permissions that `gh`
doesn't ask for when you sign in:
- **project:** projects.
- **notifications:** Watch Settings.
- **user:follow:** following people.
- **delete_repo:** deleting a repository. It's optional.

Until now you found out one feature at a time, from a message saying which permission
was missing (#129).

**Help → GitHub Permissions…** now lists them all, what each is for and whether
`gh` has it. It gives one command that adds every one that's missing, for example:

```
gh auth refresh -h github.com -s project,notifications,user:follow
```

**Copy Command** puts it on the clipboard, and **Run in a Terminal** runs it for
you. In the terminal, `gh` shows a one-time code and asks you to press `Enter`. Your
browser then opens on GitHub, where you type the code and approve. The permissions
`gh` already has are kept. **Check Again** shows what has changed. The command
changes the account `gh` is using now, which the box names. If `gh` uses a token
from the `GH_TOKEN` environment variable, the box says to change the token on
GitHub instead.

If you meet a missing permission anyway, the message now has a **Copy Command**
button, and an **All Permissions…** button that opens the same list.

## Narrow the list by the same things

**View → Filter** now has **Assigned to Me**, **Assigned To…**, **Opened by
Me**, **Opened By…**, **No Assignee** and **No Milestone**. They combine:
Assigned to Me and No Milestone together list your work that isn't planned yet.
**Clear These Filters** turns them off, and the status bar and window title say
which filters are on.

## Choose whether GHManage updates itself

**Help → Automatic Updates** is on unless you turn it off. Turned off, GHManage
doesn't look for updates when it starts, and doesn't install one it downloaded
earlier, so you keep the version you have. **Help → Check for Updates…** still
works whenever you want it.

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
