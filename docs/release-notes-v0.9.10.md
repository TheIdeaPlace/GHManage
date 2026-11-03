# GHManage 0.9.10

GHManage is a desktop app for reading and managing your GitHub repositories from
a fast, keyboard-driven list.

This release makes comparing branches something you can go into, rather than a
box of text to read. It also lists how far every branch is from the default
branch, and lets you create a pull request.

On a Mac, use `Cmd` where these notes say `Ctrl`, and `Option` where they say `Alt`.

## Comparing

A comparison now opens in lists, and says how the two stand as it arrives: "dev
and main have diverged: dev is 3 commits ahead and 1 behind. 12 files changed, 240
lines added, 18 removed. Pull request #40 is open: Add search."

`L` moves between its lists:

- **Changed files** works as it does for a pull request or a commit: `Enter` reads
  a file's lines, `Alt+N` moves between its changes and `W` opens it whole.
- **Commits ahead** and **Commits behind** list the commits each has that the other
  lacks. The ones behind were counted before, but never listed. `Enter` opens a
  commit's changed files.

`S` swaps base and head, `I` says the summary again, `F` in Changed files adds the
comparison to favorites and `Backspace` goes back to where you started.

## Quicker to start

- `C` on a row goes straight to a comparison: a branch with the default branch, a
  tag or release with the one before it, a commit with the latest on its branch.
- `Ctrl+Shift+B` now works from any view of a repository, and is one dialog rather
  than two. It starts on the default branch and the row you were on, and you can
  type a commit's SHA or another owner's `OWNER:BRANCH` as well as choose a branch
  or tag.
- A comparison's address opens the comparison, from **Open Repository or Address…**
  (`Ctrl+Shift+O`), from Favorites, and from a push in Activity.

## Ahead and behind on Branches

Each branch's row says how many commits it is ahead of the default branch and how
many behind. If you chose your own columns for Branches before this, add them under
**View → Columns…**.

## Creating a pull request

`P` in a comparison opens its pull request or, if it has none, creates one, with a
title, a description and **Create as a draft**.

## Fixes

- The base branch started on whichever branch came first alphabetically, not the
  default branch.
- A long comparison's commits were an arbitrary hundred of GitHub's newest 250. They
  are now all 250, newest first, and say so when there are more.
- File totals counted only the first hundred files as though they were all of them.
  GitHub gives 300, and GHManage now says when it stopped there.
- A renamed file lost its old name in a comparison.
- `Ctrl+Shift+B` did nothing outside Branches, and said nothing.
- A branch's last commit in the list could run on past its first line.
