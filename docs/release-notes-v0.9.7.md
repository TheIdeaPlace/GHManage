# GHManage 0.9.7

GHManage is a desktop app for reading and managing your GitHub repositories from
a fast, keyboard-driven list.

This release lets you read what a pull request or a commit changed, line by line,
with each line marked as added, removed or unchanged in the way you choose. It
can also copy a whole diff to the clipboard, or open it in another app, without
a terminal.

On a Mac, use `Cmd` where these notes say `Ctrl`, and `Option` where they say `Alt`.

## Changed Files

Press `Enter` on a commit in Commits, or `H` on a pull request in Issues & PRs
(**Actions → Changed Files**, `Ctrl+Shift+H`, does the same for either).
GHManage lists the files it changed and says how many lines were added and
removed. `Backspace` goes back to where you were.

`Enter` on a commit used to open it on GitHub. It now shows its changed files,
as `Enter` on a branch shows its commits. To open a commit on GitHub, press
`Ctrl+O`, which opens whatever is selected in any list.

Select a file, and the details panel shows its changes. Each run of changes
starts with where it is, such as "Lines 10 to 15:". `Enter` moves into the
lines, and `Alt+N` and `Alt+P` move from one run of changes to the next.

## Choose how changed lines are marked

**View → Mark Changed Lines With** has four styles:

- Words: `Added:`, `Removed:` and `Unchanged:`. This is the default.
- Short words: `Add`, `Del` and `Same`.
- Diff symbols: `+`, `-` and `=`.
- Diff symbols with changed lines: as Diff symbols, but a changed line shows its
  old version marked `!-` and then its new version marked `!+`.

The mark always comes first. These are the same styles The Chat Place uses, so
a change reads the same in both apps. Your screen reader reads symbols only at
a punctuation level that includes them, and GHManage reminds you of this when
you choose a symbol style.

## Copy or open a diff

**Actions → Copy → Copy Diff** puts a pull request's or commit's whole diff on
the clipboard, as `gh pr diff 123 | clip` does. In Changed Files it copies the
selected file's diff. **Actions → Open Diff in Default App** opens the diff in
whatever app opens `.diff` files on your computer, such as Visual Studio Code.

Thanks to George Kerscher for asking for this (#78).
