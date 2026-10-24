# GHManage 0.9.5

GHManage is a desktop app for reading and managing your GitHub repositories from
a fast, keyboard-driven list.

This release lets you decide what every list says and the order it says it in.
A new **Columns** dialog lets you choose each list's columns and their reading
order, and whether their names are read. GHManage now remembers your choices.
Column names are now plain words, and Full mode no longer reads names that add
nothing. Commits can also show every branch at once.

On a Mac, use `Cmd` where these notes say `Ctrl`, and `Option` where they say `Alt`.

## Choose your columns, and the order they're read in

A screen reader reads a row's columns from left to right, so the order of the
columns is the order you hear them. **View → Columns…** sets that for every
kind of list in one place. It replaces the old Columns submenu, which could only
turn a column on or off.

- **List to change** starts on the list you're in. Pick another to change its
  columns too.
- **Available columns** are the ones not shown. `Enter` or **Add** puts one at
  the end of the row.
- **Shown columns, in the order they're read** lists what each row says, first
  to last.
  - `Alt+Up` and `Alt+Down` move the selected column one place. `Alt+Home` and
    `Alt+End` move it to the start or the end.
  - `Delete` removes it. At least one column always stays.
  - On Windows your screen reader reads the column's new place, for example
    "Author, 2 of 4".
- **Reset to Default** puts back the list's original columns.
- **Speak column names** turns Full mode on or off.
- **Preview** shows how a row will read with your choices.
- **OK** keeps every change and leaves you on the row you were on.

## Your columns and list mode are remembered

Before, columns went back to their defaults whenever you changed views, and
Quick or Full mode reset each time GHManage started. Now each kind of list keeps
the columns you chose, and the mode is kept too, including after you close
GHManage. Every list of repositories shares one choice, since they all show the
same columns.

## Plain-word column names

Column headings are words now: "Commit" instead of "sha", "Changes" instead of
"+/-", "Run" for a workflow run's number, and "Repository" instead of "repo".
Screen readers that read column headings hear these too.

## Full mode says less, and only what helps

Full mode puts each column's name before its value, and now it leaves out names
that add nothing:

- **The first column is never named.** It's the row's name, so typing a letter
  in the list still jumps to the rows that start with it.
- **Type, State, Status and Result are read without a name.** Their value
  already says what it is, so you hear "OPEN" rather than "State: OPEN".

A row now reads "208, PR, OPEN, Title: Fix the braille cursor" instead of
"number: 208, type: PR, state: OPEN, title: Fix the braille cursor".

## All branches in Commits

**All branches** is first in **Select Branch** (`Ctrl+B`). It shows recent
commits from the default branch and the 99 most recently changed branches
together, newest first (#61).

- A commit on several branches appears once.
- The new **Branches** column shows where a commit is: "main, dev, fix and 4
  more". Turn it on in **View → Columns…**.
- The details panel lists every branch the commit is on.
- **View More** (`Ctrl++`) adds older commits, up to the newest 100 from each
  branch. For older history than that, pick one branch.
- If some branches can't be read, the status bar says how many.

On a single branch, the Branches column shows that branch's name, including the
default branch's real name.

## Known limits

- **Moving a column isn't announced in words yet.** It says its new position,
  not "moved above Message" (#65).
- **On a Mac, VoiceOver may not read a column's new place after a move.**
- **Columns are chosen per kind of list, not per repository** (#66).

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
