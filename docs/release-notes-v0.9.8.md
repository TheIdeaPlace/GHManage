# GHManage 0.9.8

GHManage is a desktop app for reading and managing your GitHub repositories from
a fast, keyboard-driven list.

This release lets you read a repository's code: browse its folders, read any
file a line at a time, see who last changed each line, and read every change a
file has had. In a pull request's changed files you can read reviewers'
comments on its lines, and add your own.

On a Mac, use `Cmd` where these notes say `Ctrl`, and `Option` where they say `Alt`.

## Files: browse a repository's code

Choose **View → View Mode → Files**, or **Go To → Files** on a repository in the
repository list. The list shows the repository's folders and then its files, at
the default branch. `Enter` goes into a folder and `Backspace` comes back out,
onto the folder you left. The list's name and the status bar say where you are,
for example "src/ on main".

Select a file and the details panel shows its text. The first line names the
file and how many lines it has; after that, line 1 of the file is the next line
of the panel, and so on, so your screen reader's line keys move through it as in
an editor. `Enter` moves into the text. In a Markdown file, `Alt+N` and `Alt+P`
move from heading to heading, so a README reads by section.

**Actions → Select Branch or Tag…** (`Ctrl+B`) looks at another branch or a tag,
staying in the same folder when it is there. A file over 1 MB, or one that isn't
text, says so, and `Ctrl+O` opens it on GitHub. **Copy → Copy Path** copies a
file's path; **Copy Details** copies its text.

## Blame: who last changed each line

`B` on a file (**Actions → Blame**) shows it in runs of lines, each headed by
who last changed them, when, and in which commit, such as "Lines 10 to 14:
Kelly Ford, 2026-09-01, abc1234 Fix the parser". `Alt+N` and `Alt+P` move
between the runs. `B` again shows the file.

## A file's history

`H` on a file (**Actions → File History**) lists the commits that changed it,
newest first. Select one and the details panel shows what it did to the file,
marked in the style you chose under **View → Mark Changed Lines With**, as
Changed Files shows it. `Enter` opens the commit in Changed Files with all its
files; `Backspace` comes back each step of the way. GitHub lists a file's history
by its path, so the list stops at the commit that gave the file its present name.

## The whole file, from Changed Files

In Changed Files, `W` (**Actions → Open Whole File**) opens the selected file in
Files, as it is at that commit or at the pull request's latest commit, so you
can read the code around a change. `Backspace` takes you back to Changed Files.

## Review comments in Changed Files

In a pull request's Changed Files, the comments reviewers left on its lines now
come straight after the line they are on: "Comment by alice: …", with replies
after it, indented. Comments on lines changed since are listed at the end of the
file under "Earlier comments". `Alt+N` and `Alt+P` stop at comments as well as
at runs of changes, and say which: "Change 2 of 7", "Comment 1 of 3". A new
Comments column says how many comments each file has. If you chose Changed
Files' columns before, add it under **View → Columns…**.

To comment on a line, move into the file's lines, put the caret on the line and
press `M` (**Actions → Comment on This Line…**). Type the comment and choose OK.
It appears after the line, and the caret stays where it was. A removed line
takes a comment on the file as it was before the change.

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
