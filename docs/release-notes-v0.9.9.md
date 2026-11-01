# GHManage 0.9.9

GHManage is a desktop app for reading and managing your GitHub repositories from
a fast, keyboard-driven list.

This release brings the people on GitHub into GHManage: the people you follow,
your followers, anyone's profile, and who starred, watches or forked a
repository.

On a Mac, use `Cmd` where these notes say `Ctrl`, and `Option` where they say `Alt`.

## People

Two new entries in the repository list, after Gists, list **People I Follow**
and **My Followers**, with how many. They are on **View → View Mode** too. Each
row reads a person's user name, name, bio, followers, following and public
repositories; **View → Columns…** adds how you are connected ("you follow each
other"), company, location and when they joined. Selecting a person shows their
whole profile in the details panel (#25).

From a person, `Enter` lists their repositories, `O` their followers, `W` the
people they follow, `S` the repositories they have starred, and `A` what they
have done in public lately. Each of these works the same way, so you can go as
deep as you like, and `Backspace` comes back a step at a time, to the row you
left. `Insert` follows someone and `Delete` unfollows them. Following needs a
permission `gh` doesn't ask for when you sign in; the first time, GHManage shows
the command that adds it. A Mac keyboard has no `Insert` key, so on a Mac use
**Actions → Follow** and **Actions → Unfollow**.

## View User

**Actions → View User…** (`Ctrl+U`) opens anyone's profile from wherever you
are. It offers the people the selected item names, such as an issue's author,
assignees and commenters, an Activity event's actor or a repository's owner, or
you can type any user name. The profile opens with focus at its top, and
`Backspace` takes you back to where you were, on the same item. An
organization's profile shows its description, website and repositories, and `A`
lists what has happened in it lately.

## Stargazers, Watchers and Forks

**Actions → Stargazers**, **Watchers** and **Forks**, also on a repository's
context menu in the repository list, list who starred the repository in front of
you, who watches it, and its forks, newest first (#31). Stargazers and watchers
are people, with everything above; `Enter` on a fork opens it here.

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
