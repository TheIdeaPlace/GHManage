# GHManage 0.9.2

GHManage is a desktop app for reading and managing your GitHub repositories from
a fast, keyboard-driven list.

This release puts your own repositories back on their own. It also gives your
organizations an entry of their own and makes favorites easier to use.

## My Organizations

In 0.9.1 the repository list mixed in up to 100 repositories from every
organization you belong to. An organization may have hundreds or thousands of
repositories, so if you belong to a big one, your own disappeared among them.
The list is now your own repositories again, and your organizations have an
entry of their own.

**My Organizations** comes after My Work at the top of the repository list,
with how many you belong to, for example "My Organizations (3)". It's also on
View ▸ View Mode. Each row gives the organization's name, your role in it
(owner or member), and how many of its repositories you can see. The ones you
own come first.

| Key | Action |
|-----|--------|
| `Enter` | List the organization's repositories, most recently pushed first |
| `Backspace` | From those, come back to My Organizations, on the same organization |
| `Ctrl+O` | Open the organization on GitHub |

An organization's repositories work like Starred and Watched: `Enter` opens one
here, `Backspace` brings you back to it, and `Ctrl++` loads more.

## Shared With Me

**Shared With Me** lists other people's repositories that you've been made a
collaborator on. Ones owned by your organizations are left out, because they're
already under My Organizations. The entry is only in the list when there's at
least one repository in it.

## Favorites

- **Favorite a repository from the repository list.** Press `F` on one to add
  it to favorites, or again to remove it.
- **A favorite repository opens here.** `Enter` on a repository in ★ Favorites
  opens it in GHManage rather than on GitHub, and `Backspace` brings you back to
  the same row. `Ctrl+O` still opens it on GitHub.
- **A menu command.** Actions ▸ Add or Remove Favorite (F). The context menus
  say which it will do: "Add to Favorites" or "Remove from Favorites".
- The status bar confirms with "Added to favorites" or "Removed from favorites".

## Also fixed

- Pressing a letter key in the list that does something, such as `F`, `R` or
  `C`, no longer makes Windows beep.
- If the GitHub CLI's sign-in can't read your organizations, your own
  repositories still load.

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
