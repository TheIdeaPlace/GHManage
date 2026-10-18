# GHManage User Guide

GHManage is a keyboard-driven desktop app for your GitHub repositories, built for screen reader users. It shows issues, pull requests, branches, commits, tags, releases, workflows, labels, GitHub Pages sites and your GitHub activity feed as fast lists you can arrow through, with the details of whatever you are on in a panel below. It runs on Windows and on Apple Silicon Macs, and does all of its work through the GitHub CLI.

---

## Contents

- [System Requirements](#system-requirements)
- [Installing and Updating](#installing-and-updating)
- [Signing In with the GitHub CLI](#signing-in-with-the-github-cli)
- [The Main Window](#the-main-window)
- [The Repository List](#the-repository-list)
- [Issues and Pull Requests](#issues-and-pull-requests)
- [Labels](#labels)
- [Branches and Commits](#branches-and-commits)
- [Tags and Releases](#tags-and-releases)
- [Workflows and Workflow Runs](#workflows-and-workflow-runs)
- [GitHub Pages](#github-pages)
- [Notifications](#notifications)
- [My Work](#my-work)
- [Searching GitHub](#searching-github)
- [Activity](#activity)
- [Starred and Watched Repositories](#starred-and-watched-repositories)
- [Organizations and Shared With Me](#organizations-and-shared-with-me)
- [Favorites](#favorites)
- [Quick Filter](#quick-filter)
- [Copying](#copying)
- [List Mode, Sorting and Columns](#list-mode-sorting-and-columns)
- [The Details Panel and Comment Navigation](#the-details-panel-and-comment-navigation)
- [The Actions Menu](#the-actions-menu)
- [Keyboard Shortcuts](#keyboard-shortcuts)
- [Release History](#release-history)
- [Reporting Issues](#reporting-issues)

---

## System Requirements

- **Windows:** Windows 10 or Windows 11, 64-bit.
- **Mac:** an Apple Silicon Mac (M1 or later) on macOS 11 Big Sur or newer.
- **The GitHub CLI (`gh`)**, installed and signed in. GHManage has no sign-in of its own; see [Signing In with the GitHub CLI](#signing-in-with-the-github-cli).
- **A screen reader is optional.** GHManage is tested with JAWS and NVDA on Windows and VoiceOver on the Mac, but works the same with no screen reader in use.

---

## Installing and Updating

### Which download do you want?

Every release is published on the [GHManage releases page](https://github.com/TheIdeaPlace/GHManage/releases). Take the first file listed for your computer unless you have a reason not to.

| File | Use it if |
|------|-----------|
| `GHManage-win-Setup.exe` | Windows. Installs GHManage and keeps it up to date. |
| `GHManage-win-Portable.zip` | Windows, when you want a folder you can run from anywhere. Nothing is installed, and it never updates itself. |
| `GHManage-osx.dmg` | Mac. Open it and drag GHManage to Applications. |
| `GHManage-osx-Portable.zip` | Mac, when you would rather unzip the app yourself. It contains the same app as the DMG. |

The other files on the release page (`*.nupkg`, `RELEASES`, `releases.win.json`, `assets.win.json`, `releases.osx.json`, `assets.osx.json`) are the update feed the installed app reads. You never need to download them.

### Installing on Windows

Run **GHManage-win-Setup.exe**. It installs for your user account only, into `%LocalAppData%\GHManage`, so there is no administrator prompt. A Start menu shortcut is added, and GHManage starts when setup finishes.

Releases are signed, so Windows knows who published them and SmartScreen does not warn about an unknown publisher.

### Installing on a Mac

Open **GHManage-osx.dmg** and move **GHManage** to **Applications**. The app is signed and notarized by Apple, so Gatekeeper opens it without complaint.

You can keep the app anywhere, not just in Applications: a Mac app carries its own updater inside it, so it keeps updating wherever it lives.

### How updating works

Installed copies of GHManage, on Windows and on the Mac, keep themselves up to date. A couple of seconds after GHManage starts it checks for a newer release in the background. If it finds one, it downloads it quietly and the status bar says:

"GHManage 1.2.3 downloaded — it will be installed next time you start GHManage."

Nothing interrupts you and nothing restarts on its own. The next time you start GHManage, the new version is the one that opens.

That message is replaced by the next thing GHManage tells you, so the update also gets an item of its own on the status bar, **GHManage 1.2.3 ready to install**, which stays there until you restart. Press `F6` until you reach the status bar, arrow to that item, and press `Enter` or `Space`. The **Update Available** dialog offers **Restart Now** to install immediately, and **Later** to leave it for your next start. See [The status bar](#the-status-bar) for moving around the bar.

To check by hand, choose **Help → Check for Updates…**. It always answers: either "GHManage 1.2.3 is up to date", or the **Update Available** dialog.

An update never touches your favorites, the repositories you opened by address, or anything else you have set up.

### The portable versions

The portable zips are complete copies of GHManage that run from any folder and write nothing outside it except your settings. They cannot update themselves. **Help → Check for Updates…** in a portable copy says so: "GHManage is running as a portable copy, which cannot update itself." To update a portable copy, download the new zip and replace the old folder.

### Where your settings live

Favorites, the repositories you opened by address, and your other settings are small files in a `ghmanage` folder: `%APPDATA%\ghmanage` on Windows and `~/.config/ghmanage` on the Mac. Installed and portable copies share them. GHManage never stores GitHub credentials; those belong to `gh`.

If updates ever misbehave, the update log is `%APPDATA%\GHManage\ghmanage-update.log` on Windows and `~/Library/Logs/GHManage/ghmanage-update.log` on the Mac. Attaching it to a bug report helps.

### Running from source

If you would rather run the Python source, you need Python 3.9 or later. From a copy of the repository:

```
pip install -r requirements.txt
python ghviewer.py
```

Three command-line options work in every copy, installed or not:

| Option | What it does |
|--------|--------------|
| `--repo OWNER/NAME` | Opens that repository straight away instead of starting on the repository list. |
| `--version` | Prints the version and exits. |
| `--debug` | Writes more detail to the update log. |

For example, to start GHManage on the issues of NVDA's repository, `nvaccess/nvda`:

- **Windows, installed:** in the Run box (`Windows+R`) or a terminal, type

  ```
  %LocalAppData%\GHManage\current\ghmanage.exe --repo nvaccess/nvda
  ```

- **Mac, installed:** in Terminal, type

  ```
  /Applications/GHManage.app/Contents/MacOS/GHManage --repo nvaccess/nvda
  ```

- **From source:** in the repository's folder, type

  ```
  python ghviewer.py --repo nvaccess/nvda
  ```

Options can be combined, so `--repo nvaccess/nvda --debug` does both.

---

## Signing In with the GitHub CLI

GHManage does not sign in to GitHub itself. Every request it makes goes through the GitHub CLI, `gh`, using the account `gh` is signed in to. That is a deliberate choice: GHManage never asks for a password or token and has nothing of yours to store or lose, and whatever `gh` can see, GHManage can see.

### Installing gh

- **Windows:** download the installer from [cli.github.com](https://cli.github.com/), or run `winget install GitHub.cli`.
- **Mac:** run `brew install gh`, or use the installer from [cli.github.com](https://cli.github.com/).

### Signing in

In a terminal, run:

```
gh auth login
```

and follow its prompts. Choose **GitHub.com**, and sign in through the browser when it offers to. Run `gh auth status` at any time to see which account is signed in.

You only do this once. GHManage picks up the sign-in the next time it starts.

### More than one account

`gh` can be signed in to several github.com accounts at once, a personal one and a work one say: run `gh auth login` again for each. **File → Switch GitHub Account…** (`Ctrl+Shift+K`) then lists them, the one in use first, and switching starts GHManage again as that account: its repositories, its counts and its Notifications, which is where you land. Favorites and repositories you opened by address stay, since they belong to this computer rather than to an account.

Switching changes the account `gh` uses in your terminal too, exactly as `gh auth switch` does. With only one account signed in, the command says so and how to add another. Only github.com accounts are offered; GHManage does not work with GitHub Enterprise servers.

### Permissions gh does not ask for

When you sign in, `gh` asks GitHub for the permissions most commands need. A few GHManage features need one more, and say so when you use them, with the command that adds it. For example, **Watch Settings** needs the "notifications" permission:

```
gh auth refresh -h github.com -s notifications
```

`gh` opens your browser to approve it, once.

### When GHManage cannot find gh

If `gh` is missing, the status bar says that the `gh` CLI was not found, with where to get it. On the Mac, an app started from Finder or the Dock does not see the `PATH` your terminal uses, so GHManage looks in the usual Homebrew and MacPorts folders itself (`/opt/homebrew/bin`, `/usr/local/bin`, `/opt/local/bin`) as well as `~/.local/bin`. If you keep `gh` somewhere else, set the environment variable `GHMANAGE_GH_PATH` to its full path.

If `gh` is installed but signed out, or its sign-in has expired, the error `gh` gives is shown in the status bar as it is, because that is the message that says what to fix.

---

## The Main Window

The window has three panes and a status bar:

1. **Repositories**, on the left: the repository list, with Favorites, Activity, Starred Repositories, Watched Repositories, Notifications, My Work and your saved searches at the top. See [The Repository List](#the-repository-list).
2. **The item list**, top right: whatever the current view shows, such as issues and pull requests, branches, or releases. Its label, and the name your screen reader announces for it, is the name of the view, for example "Issues", "Branches" or "Release Assets", so you hear where you are as you move into it.
3. **Details**, bottom right: everything about the item you are on in the list, as read-only text you can move through line by line. See [The Details Panel and Comment Navigation](#the-details-panel-and-comment-navigation).
4. **The status bar**, at the bottom: what the view is showing, the keys that work in it, and anything GHManage has just done.

The window title names the view and the repository, and the branch, release, run or label when you have drilled into one, for example "Commits — main — owner/name".

### Moving between panes

`F6` moves to the next pane: repository list, item list, details panel, status bar, and round to the repository list again. `Shift+F6` goes the other way. On a Mac keyboard press `fn+F6` and `fn+Shift+F6`, unless you have set the function keys to work as standard keys.

`Tab` and `Shift+Tab` move between the repository list, the item list and the details panel, as they always have. They never stop on the status bar, so the three panes stay one keystroke apart.

### Views

Each repository has several views. `Ctrl` and a number jumps straight to one from anywhere in the window, and the numbers follow the order of **View → View Mode**, so you can read them off the menu. On a Mac use `Cmd` instead of `Ctrl`, here and in every other menu shortcut.

| Key | View |
|-----|------|
| `Ctrl+1` | Issues & PRs |
| `Ctrl+2` | Branches |
| `Ctrl+3` | Commits |
| `Ctrl+4` | Tags |
| `Ctrl+5` | Releases |
| `Ctrl+6` | Workflows |
| `Ctrl+7` | Workflow Runs |
| `Ctrl+8` | Labels |
| `Ctrl+9` | ★ Favorites |
| `Ctrl+0` | GitHub Pages |
| `Ctrl+Shift+N` | Notifications |
| `Ctrl+Shift+M` | My Work |
| `Ctrl+Shift+A` | Activity |

**Starred Repositories** and **Watched Repositories** are on the same menu, after Activity.

Favorites, Notifications, My Work, Activity, Starred Repositories, Watched Repositories, Shared With Me, an organization's repositories and search results are not about one repository, so they work at any time. Every other view needs a repository: with none chosen, the status bar says "Select a repository first." and the view stays as it was.

Several views lead into others. `Enter` on a branch shows its commits, on a release its files, on a workflow run its artifacts, on a label the issues that carry it. `Backspace` steps back up to where you came from.

When a view loads, the status bar names it and the repository, for example "Loading Branches for owner/name…", and then says what arrived.

### The status bar

The status bar is split into items:

- **The message**: what the view is showing, or the last thing GHManage told you.
- **Keys**: the keys that work in the current view, for example "Ctrl++=view more  R=refresh  Ctrl+F=filter  Enter=list assets".
- **Filter**: the quick filter and how many rows it matches, while one is set.
- **Mode**: Quick mode or Full mode.
- **Update**: an update ready to install, when one has been found.

`F6` puts you on the first item. `Left` and `Right` then move from one item to the next, wrapping round at either end. Items with nothing to say are not on the bar, so every stop has something on it. Your screen reader's own command for reading the status bar (`Insert+Page Down` in JAWS, `Insert+End` in NVDA) still reads the whole bar.

The message is where GHManage announces things: what loaded, what was opened, what failed and why. It is worth reading whenever a key seems not to have done anything.

### Loading more

Lists load 100 items to begin with. `Ctrl++` (**File → View More**) loads the next 100, and the status bar says how many are showing. `R` in the list, or `Ctrl+R` from anywhere (**File → Refresh**), reloads the view from GitHub and goes back to the first 100.

### Menus

| Menu | What is on it |
|------|---------------|
| **File** | Open Repository or Address, Remove from List, Switch GitHub Account, Refresh, Search GitHub, View More, Go To Issue, Quick Filter, Next and Previous Comment, Quit |
| **Actions** | Everything that acts on the item you are on. See [The Actions Menu](#the-actions-menu). |
| **View** | View Mode, List Mode, Sort Order, Columns, State, Filter |
| **Help** | User Guide, Check for Updates, About GHManage |

**Help → User Guide** (`F1`, or `fn+F1` on a Mac) opens this guide in your web browser.

---

## The Repository List

The list on the left is where you choose what to look at. Arrow to an entry and press `Enter`, or double-click it. Typing a letter jumps to the next entry starting with it.

It is in this order:

1. **★ Favorites**, with how many you have, for example "★ Favorites (12)". See [Favorites](#favorites).
2. **Activity**: your GitHub feed. See [Activity](#activity).
3. **Starred Repositories**: the repositories you have starred, with how many, for example "Starred Repositories (7)". See [Starred and Watched Repositories](#starred-and-watched-repositories).
4. **Watched Repositories**: the repositories you watch, with how many.
5. **Notifications**, with how many are unread, for example "Notifications (12 unread)". See [Notifications](#notifications).
6. **My Work**: open issues and pull requests that need you, with how many once it has loaded. See [My Work](#my-work).
7. **Shared With Me**: other people's repositories you have been made a collaborator on, with how many. It is only there when there is at least one. See [Organizations and Shared With Me](#organizations-and-shared-with-me).
8. **Each organization you belong to**, marked with a building, with how many of its repositories you can see, for example "🏢 TheIdeaPlace (13)". The ones you are an owner of come first.
9. **Your saved searches**, each marked with a magnifying glass, for example "🔍 NVDA braille bugs". See [Saved searches](#saved-searches).
10. **Repositories you opened by address**, each marked with a pin, for example "📌 nvaccess/nvda — NVDA, the free and open source screen reader".
11. **Your own repositories**, most recently pushed first, each followed by its description, up to 100.

The first six are always there, so the same keystrokes from the top of the list always reach them. The first four are where they were before Notifications and My Work arrived. When the list first loads, the status bar says how many repositories it found: "Loaded 42 repositories. Select one to view issues and PRs."

The notification, starred and watched counts are asked for once the list is up, so they appear a moment after the names, without moving you from the entry you are on. If GitHub can't be asked, the entry shows just its name rather than a number that might be wrong. Opening Starred or Watched, or pressing `R` in it, brings its count up to date, so a repository you starred on the web since GHManage started is counted then.

Opening a repository shows its **Issues & PRs**. Use `Ctrl+2` through `Ctrl+0` to reach its other views.

### Opening a repository or a GitHub address

**File → Open Repository or Address…** (`Ctrl+Shift+O`) opens any repository on GitHub, yours or not, without cloning it, and goes straight to most things inside one. Type or paste:

- `owner/name`, `https://github.com/owner/name` or `git@github.com:owner/name.git` to open the repository on its issues and pull requests. It is added to the repository list with a pin, where it stays between sessions until you remove it.
- The address of an issue or pull request (`…/issues/12`, `…/pull/12`, `…/pull/12/files`) to open the repository's issues with that one selected. When it is not among those loaded, closed say, it is fetched and added, as Go To Issue does.
- A commit (`…/commit/<sha>`) to open the commits with it selected. A commit that isn't among the default branch's latest is fetched and shown first.
- A release (`…/releases/tag/v1.2`), a workflow run (`…/actions/runs/<id>`) or a branch (`…/tree/<branch>`) to open the releases, the workflow runs or that branch's commits.
- A list (`…/releases`, `…/pulls`, `…/actions`, `…/labels`, `…/branches`, `…/tags`, `…/commits`) to open that view.

- A branch's history (`…/commits/<branch>`) opens that branch's commits; a workflow file (`…/actions/workflows/ci.yml`) opens Workflows.

Any other address inside a repository, a file, the wiki or a discussion say, opens the repository on its issues, and the status bar says GHManage has no view for that page. A branch whose name has a `/` in it can't be told apart from a folder in a `…/tree/` address, so that opens the repository too. Only a repository's own address pins it: a link from an email to an issue, a file or anything else in a repository opens without adding to your list.

Addresses can be pasted as they come: wrapped in `<…>` or brackets, followed by a full stop or comma, in any mix of upper and lower case. Only github.com is read; addresses on other GitHub hosts, gists, raw files and the API get the "Couldn't read that" message.

When the clipboard already holds a GitHub address, the box starts with it filled in, so opening a link you have copied is `Ctrl+Shift+O` and `Enter`. If you copied a whole sentence or paragraph, the first GitHub address in it is the one offered.

A person's or organisation's address says so on the status bar; GHManage has no profile view. An address it cannot read at all gets "Couldn't read that. Use a github.com address or OWNER/NAME."

### Removing a repository from the list

**File → Remove from List…** removes the selected repository from the list. It applies to repositories you opened by address; the status bar confirms with "Removed owner/name from the pinned list." It does not delete anything on GitHub.

Your own repositories are always listed, so asking to remove one says it "comes from your GitHub account and can't be removed from here". The entries at the top, organizations included, are always there too. A saved search can be removed the same way.

### Forks

GitHub turns issues off on a fork by default, and the issues and pull requests that matter live on the repository it was forked from. So when you open a fork, its **Issues & PRs** and **Labels** come from that upstream repository, and the status bar says so, for example "you/nvda (issues from upstream nvaccess/nvda)". Pull requests opened only within the fork itself are not shown. Branches, commits, releases, workflows and the rest are the fork's own.

---

## Issues and Pull Requests

**Issues & PRs** (`Ctrl+1`) lists a repository's issues and pull requests together, newest first, like an inbox. It is what you see when you open a repository.

Each row shows the number, whether it is an issue or a PR, its state (OPEN, CLOSED or MERGED) and its title. Other columns are available under **View → Columns**; see [List Mode, Sorting and Columns](#list-mode-sorting-and-columns). The status bar counts what loaded: "owner/name — 23 issues, 7 PRs (open). Showing up to 100 newest."

The details panel shows the item in full: state, author, dates, address, labels, assignees and comment count; for a pull request whether it is a draft, whether it is merged, its review status, its branches and the size of its changes; then the description and every comment. `Alt+N` and `Alt+P` move between the comments. See [The Details Panel and Comment Navigation](#the-details-panel-and-comment-navigation).

### Choosing what is listed

- **View → State** shows **Open**, **Closed** or **All**. Open is the default.
- **View → Filter** shows **Issues Only**, **PRs Only**, or **Issues & PRs**.

Both reload the list from GitHub, so they reach items that were never in the list you had.

### Keys in the issues list

| Key | Action |
|-----|--------|
| `Enter` | Open the issue or pull request on GitHub in your browser |
| `C` or `Ctrl+W` | Close it |
| `O` or `Ctrl+Shift+W` | Reopen it |
| `M` or `Ctrl+M` | Add a comment |
| `N` or `Ctrl+N` | New issue |
| `F` | Add it to favorites, or remove it |
| `Ctrl+G` | Go to an issue or pull request by number |
| `Ctrl+O` | Open it on GitHub |

Closing and reopening ask first, naming the item: "Close issue #12?" with its title. A comment is typed into the **Add Comment** box, which takes several lines. When the change has gone through, the status bar says so, for example "Closed #12. Refreshing…", and the list reloads.

### Creating an issue

**Actions → New Issue…** (`Ctrl+N`, or `N` in the issues list) opens a form with a title and a description. Write the description in Markdown, as on github.com. `Enter` in the title moves on to the description. In the description `Enter` starts a new line, so `Ctrl+Enter` (`Cmd+Enter` on a Mac) creates the issue from anywhere in the form, as does the **Create Issue** button; `Tab` moves between the fields, and on Windows `Alt+T` and `Alt+D` jump to them.

New Issue works wherever you are, for the repository in front of you:

- in a view of the open repository, that repository;
- with focus in the repository list, the repository selected there;
- in Notifications, My Work, Activity, search results, Starred, Watched or Favorites, the selected row's repository.

When that isn't the repository open, GHManage opens it on its issues first, so the new issue shows in its list; from Notifications, My Work, Activity, search results, Starred or Watched, `Backspace` afterwards comes back to where you were. With no repository in front of you, the status bar says so.

The form names the repository the issue goes to. On a fork that is the upstream repository, since that is where the issues you see in the list live.

Once GitHub has it, the issues list reloads with the new issue selected, unless you have moved to another view or repository in the meantime; then the status bar just says it was created. While one issue is being created, `Ctrl+N` waits for it, so the same text can't be filed twice. If you cancel the form with something typed, or GitHub refuses the issue, what you typed is kept and `Ctrl+N` brings it back, until you quit GHManage.

### Pull requests

On a pull request in the issues list:

| Key | Action |
|-----|--------|
| `K` | Its checks: how many passed, failed or are still running, then each one, failures first, with its link |
| `V` | Review it: approve, request changes, or comment, with a message |
| `D` | Mark a draft ready for review, or an open pull request back to a draft, after asking |

**Actions → Pull Request** has those three, and:

- **Merge…** offers the ways the repository allows (a merge commit, squash, rebase) and whether to delete the branch afterwards. A draft has to be marked ready first. The status bar then says what happened: merged; or, when required checks are still running, that GitHub turned on auto-merge and will merge it when they pass; or that it accepted the merge but hasn't done it yet, as with a merge queue. If GitHub won't merge it at all, because a required review is missing say, the status bar gives GitHub's reason.
- **Request Reviewers…** takes GitHub logins separated by commas, or a team as `org/team-name`.
- **Update Branch…** merges the base branch into the pull request's branch, as the button on github.com does, after asking.

`K`, `V` and `D` work from the details panel too. The review form works like New Issue: `Ctrl+Enter` submits it from the message. Requesting changes or commenting needs a message; approving doesn't. After a review, merge or change, the list reloads.

When a check failed in a GitHub Actions workflow, Workflow Runs (`Ctrl+7`) and `L` on its run shows what failed.

### Go to an issue by number

**File → Go To Issue…** (`Ctrl+G`) asks for a number and puts you on that issue or pull request, with focus in the details panel so you can start reading. It works in **Issues & PRs** only.

If the number is not in the list, because it is closed while you are viewing open items or older than the list reaches, GHManage fetches it from GitHub, adds it to the list and selects it. If it is in the list but hidden by the quick filter, the filter is cleared so you can see it. If the number is neither an issue nor a pull request, GHManage says "#123 does not exist as an issue or PR in owner/name"; if GitHub could not be reached at all, it gives the real reason instead, so a dropped connection is never mistaken for a missing issue.

---

## Labels

**Labels** (`Ctrl+8`) lists the repository's labels with their descriptions and colours. The details panel adds whether a label is one of GitHub's defaults, and its address.

| Key | Action |
|-----|--------|
| `Enter` | List the issues and pull requests carrying the label |
| `Ctrl+I` or `Insert` | Create a label |
| `Ctrl+D` or `Delete` | Delete the selected label, after asking |

These keys work from the details panel as well as the list, so you can read what a label is and act on it without moving back. The context menu and the **Actions** menu have the same three. On a Mac keyboard, which has no `Insert` key, use `Cmd+I`; `Cmd+D` deletes.

### Browsing by label

`Enter` on a label shows **Issues & PRs** restricted to that label. The window title and the status bar name it, for example "owner/name — 4 issues, 1 PRs (open) labelled 'bug'". Everything in Issues & PRs still works there, including the state filter, sorting, columns, and closing, reopening and commenting.

The restriction is applied by GitHub, not by the quick filter, so it finds every item with the label, not only those that happened to be in the list. `Backspace` returns to the labels. `Ctrl+1` drops the restriction and shows all issues and pull requests again.

### Creating and deleting labels

The **New Label** dialog has three fields: **Name**, which is required; **Description**; and **Colour**, six hexadecimal digits such as `d73a4a`. Leave the colour blank and GitHub picks one. If the colour is not six hex digits, GHManage says so and puts you back in the field before anything is sent.

Deleting a label removes it from every issue and pull request that carries it, and GitHub has no undo for that, so GHManage asks first and the question says so. The **Delete** item on the Actions menu reads **Delete Label…** in this view, so you know what it would delete.

After either change the labels list reloads, so you can see the result.

On a fork, labels come from the upstream repository, the same one the issues come from.

---

## Branches and Commits

### Branches

**Branches** (`Ctrl+2`) lists each branch with its last commit, who made it and when. **View → Columns** adds whether the branch is protected and how far it is ahead of and behind the default branch.

| Key | Action |
|-----|--------|
| `Enter` | Show the branch's commits |
| `Ctrl+Shift+B` | Compare two branches |
| `F` | Add the branch to favorites, or remove it |

### Comparing branches

**Actions → Compare Branches…** (`Ctrl+Shift+B`, in the Branches view) asks two questions, one after the other. "Step 1 of 2" asks for the **base** branch, the one to compare from, usually `main`. "Step 2 of 2" asks for the **head** branch to compare against it, and starts on the branch you were on in the list.

The result opens in a text window you can read line by line: how many commits the head branch is ahead and behind, the commits it adds, and the files changed with their additions and deletions. The status bar gives the short version, for example "'feature' is 3 ahead, 0 behind 'main'." Press `Escape` or **OK** to close it.

### Commits

**Commits** (`Ctrl+3`) lists the commits on the default branch. `Enter` on a branch in the Branches view lists that branch's commits instead, and `Backspace` takes you back to the branches.

To switch branch without going back, use **Actions → Select Branch…** (`Ctrl+B`), which works in the Commits view and starts on the branch you are viewing.

Each commit shows its short SHA, message, author and date; **View → Columns** adds how many files changed and the lines added and removed. The details panel has the full SHA, the branch, the whole message, and the files changed when GitHub reports them. `Enter` on a commit opens it on GitHub.

---

## Tags and Releases

### Tags

**Tags** (`Ctrl+4`) lists the repository's tags and the commit each points at. `Enter` opens a tag on GitHub.

### Releases

**Releases** (`Ctrl+5`) lists releases with their tag, name, date and **downloads**: how many times the files attached to each were downloaded, added together. **View → Columns** adds the number of files and whether a release is a draft or a prerelease.

The status bar totals the downloads of every release currently loaded, for example "owner/name — 30 releases. 12,408 downloads across them." `Ctrl++` loads more releases, and the total grows with them.

The details panel shows a release's downloads file by file, most downloaded first, followed by its release notes.

### A release's files

`Enter` on a release lists its files, each with its download count and size, and the status bar gives the total: "Showing 6 assets for v1.2.0, 3,204 downloads in total". A release with no files says so instead.

In that list, `Enter` downloads the selected file through your browser, and `Backspace` returns to the releases.

### Reading download counts

A download count is a running total kept by GitHub for the life of the file. It is not broken down by date, and GitHub offers no way to get it by date, so to see downloads over time you have to note the numbers and compare them later. Counts include automated downloads, such as other software checking for updates, so a sudden spike on one release deserves some suspicion.

---

## Workflows and Workflow Runs

### Workflows

**Workflows** (`Ctrl+6`) lists the repository's GitHub Actions workflows: each one's name, whether it is active, and its file.

`Enter` runs the selected workflow on a branch you choose. So does **Actions → Run Workflow on Branch…**, and **Run on branch…** on the context menu. It goes like this:

1. GHManage asks which branch to run on.
2. It reads the workflow file *on that branch* to find out whether it can be run by hand, and what inputs it takes. The branch comes first because a branch can add or change inputs, and the form has to match the branch that will run.
3. If the workflow takes inputs, a form asks for them, laid out as GitHub's own **Run workflow** form is: a list to choose from, a checkbox, or a box to type in, each labelled with the input's description and with its default filled in. Required inputs say "(required)", and **OK** will not go ahead while one is empty; it says which one and puts you in it. A workflow with no inputs skips this step.
4. The run starts, and the status bar says so: "Started 'Build' on main. Switch to Workflow Runs and refresh to watch it."

A workflow can only be run by hand if its file has an `on: workflow_dispatch` trigger. If it does not, GHManage tells you so and runs nothing.

### Workflow runs

**Workflow Runs** (`Ctrl+7`) lists recent runs: the workflow's name, its status (queued, in progress or completed), its result, the branch and the date. **View → Columns** adds the event that started it and the run number.

| Key | Action |
|-----|--------|
| `Enter` | List the run's artifacts |
| `J` | List the run's jobs, with their steps |
| `L` | Show what failed |
| `E` | Rerun it: every job, or only the ones that failed |
| `X` | Cancel it, while it is queued or running |
| `Ctrl+D` or `Delete` | Delete the run, after asking |
| `Ctrl+O` | Open the run on GitHub |

Deleting a run cannot be undone, and the question says so. On a Mac keyboard, use `Cmd+D`. `J`, `L`, `E` and `X` work from the details panel too, and are on the **Actions** menu as Show Jobs, Show What Failed, Rerun… and Cancel Run….

### What failed

`L` on a failed run gathers what you would otherwise hunt for across the run's page and its logs, into one text to read from the top:

- which jobs failed, at which step, after how long; jobs that were cancelled, usually because another failed first, are named on one line rather than reported as failures;
- what GitHub flagged in each: the errors shown as annotations on the run's page, such as "Process completed with exit code 1.", or a failing test's file and line;
- the last 40 lines of each failed step's log, where the error usually is. Some repositories' logs don't say where one step ends and the next begins; then it is the end of the job's log, and the report says so.

A run that failed before any job started, because of a mistake in the workflow file or because it is waiting for someone to approve it, says that instead.

Logs are tidied for reading: no colour codes or other terminal control codes, no timestamp on every line, GitHub's error and warning markers read as "ERROR:" and "WARNING:", and the commands it ran as "Command:". Warnings that are not failures are left out. On a run that succeeded, `L` just says so.

### Jobs

`J` on a run lists its jobs: each job's name, status, result, how long it took and the step that failed, if one did. The details panel lists every step with its result, "Step 4, Run tests: failure". `Enter` on a job opens its whole log, with the cursor on the first error when there is one; a very long log keeps its last 20,000 lines. A skipped job has no log, and a running one's log is ready when it finishes; GHManage says so rather than opening an empty window. `L`, `E` and `X` work here on the run the jobs belong to. `Backspace` returns to the runs.

### Rerun and cancel

`E` asks how to rerun a finished run: **Rerun failed jobs only**, offered when something failed, or **Rerun all jobs**. `X` cancels a run that is queued or in progress, after asking. Either way the list refreshes itself a few seconds later, once GitHub shows the change.

### Artifacts

A run's **Artifacts** list shows each file the run saved, with its size, whether it has expired, and when it was made. `Enter`, **Actions → Download Artifact…**, or **Download…** on the context menu asks which folder to save it in and downloads it there. The status bar says "Downloaded 'build' into C:\Users\you\Downloads." when it is done.

GitHub deletes artifacts after a while. An expired one is marked in the list, and GHManage says it can no longer be downloaded rather than trying.

`Backspace` returns to the runs.

---

## GitHub Pages

**GitHub Pages** (`Ctrl+0`) shows the site a repository publishes, if it has one: one row per publish, with whether it worked, the commit it came from, who pushed it, and how long it took.

The status bar leads with what you most likely came to check, for example "Live at https://owner.github.io/name/ — built, published from main/docs." The details panel adds the rest of the site's settings: who builds it, whether HTTPS is enforced, any custom domain, whether it is public, and whether it has its own 404 page.

If the repository has no site, the details panel says "GitHub Pages is not enabled for this repository." rather than leaving you with an empty list, which would look the same as a site that has never published.

### The pages a site serves

`Enter` in the publish history lists **Published Pages**: every file the site serves, each with the address it is served at.

| Key | Action |
|-----|--------|
| `Enter` | Open the page in your browser |
| `S` | Open the site's home page in your browser (also in the publish history) |
| `F` | Add the page to favorites, so one you check often is a keystroke away |
| `Backspace` | Return to the publish history |

**Actions → Open Published Site** does what `S` does, once GHManage knows there is a site.

Two things about this list are worth knowing, and the details panel points them out on the pages they apply to:

- **Jekyll sites serve Markdown as HTML.** A file stored as `guide/setup.md` is served at `guide/setup.html`, and the address listed is the one that works. A site with a `.nojekyll` file skips Jekyll and is served exactly as committed.
- **A site built by Actions is listed from its source, not its output.** GitHub publishes those sites through a workflow, and the workflow decides what actually ships, which may be only some of these files, or files it generated that are not in the repository at all. For sites GitHub builds itself, the list is what is served.

The publish history has the same split. Sites GitHub builds itself keep a full build log with durations and error messages. Sites built by Actions have no build log, so their history comes from their deployments instead, which record whether each publish worked but not how long it took.

---

## Notifications

**Notifications** is your GitHub inbox: the issues, pull requests, releases, discussions and workflow runs GitHub has told you about, across every repository, most recently updated first. It lists the unread ones, as github.com does.

Open it by choosing **Notifications** in the repository list, after Watched Repositories, with `Ctrl+Shift+N` (`Cmd+Shift+N` on a Mac), or from **View → View Mode → Notifications**. Like Activity, it keeps the repository you were in.

Each row reads why you were told, what kind of thing it is, its title, the repository, when it last changed, and whether it is read:

"review requested, PR, #1587 Bump huggingface-hub, Community-Access/quill, 2026-10-05 18:41, unread"

Why you were told is GitHub's reason in words: review requested, mention, team mention, assigned, author, comment, state change, CI activity, security alert, or watching, when it comes from a repository you watch. The details panel has the same, with the address on a line of its own.

### Keys in the Notifications view

| Key | Action |
|-----|--------|
| `Enter` | An issue or pull request opens here in GHManage, selected in its repository's list. A discussion, commit, release or security advisory opens on its own page on GitHub (a discussion GitHub doesn't give an address for opens the repository's discussions); a workflow run, which notifications don't identify, opens the repository's Actions page. Either way it is marked read |
| `Backspace` | From the issue or pull request, come back to the same notification |
| `M` | Mark it read |
| `Delete` or `Ctrl+D` | Mark it done: it leaves your inbox, as the Done button on github.com does. GHManage can't bring it back; github.com's **Done** tab can |
| `U` | Unsubscribe from the thread: no more notifications about it unless you comment or are mentioned |
| `I` | Include read notifications, or go back to unread only |
| `G` or `Ctrl+Shift+G` | Open its repository here in GHManage |
| `Ctrl+O` | Open it on GitHub, and mark it read |
| `F` | Add it to favorites, or remove it. Only something with a page of its own can be a favorite: not a workflow run, a release or an invitation, whose address is their repository's list of them |
| `Ctrl++` | Load more, landing on the first one not listed before |

`M`, `U`, `I`, `G` and `Delete` work from the details panel as well as the list, and leave you in the panel. GitHub has no way to mark a notification unread again, from GHManage or anywhere else, so `M` and `Enter` are for good.

The **Actions** menu has Mark as Read, Mark as Done, Unsubscribe from Thread and **Mark All as Read…**, which asks first and then marks every notification read, not only those loaded, up to the moment the list was loaded: anything that has come in since stays unread for you to see. A large inbox is marked in the background on GitHub, so the list shows them read straight away but a refresh in the first few seconds may still bring some back. **View → Include Read Notifications** is the same as `I`.

A read notification stays in the list until you refresh, its row now ending "read", so marking several in a row doesn't move you about. Marking one done takes it out at once, and you land on the one that was below it.

To see only some, use the quick filter (`Ctrl+F`): it matches the reason and the repository as well as the title, so "review requested" or "nvaccess/nvda" narrows the list to those.

The count beside **Notifications** in the repository list goes down as you read, and is brought up to date whenever the whole of your unread list has loaded.

---

## My Work

**My Work** answers "what on GitHub needs me?": the open issues and pull requests, in every repository, where:

- your review is requested,
- you are assigned,
- you opened the pull request,
- you opened the issue,
- you are mentioned.

They come in that order, most recently updated first within each, and each is listed once, under the first reason that applies: a pull request you are asked to review and also mentioned in is a review request. Archived repositories are left out.

Open it by choosing **My Work** in the repository list, after Notifications, with `Ctrl+Shift+M` (`Cmd+Shift+M` on a Mac), or from **View → View Mode → My Work**. It takes five searches, so a few seconds; `R` asks again. GitHub allows 30 searches a minute, so if you refresh a lot, one kind may fail to load; the status bar names it and the rest still show. The status bar adds it up, for example "My Work — 36 open: 14 review requested, 15 assigned, 7 your pull request". Each kind lists up to 100; a kind with more is marked with a +, and a search (`Ctrl+Shift+F`) with the same terms finds the rest.

Each row reads why it is on the list, whether it is an issue or a pull request, its number, title, repository and when it last changed. The details panel adds the description.

| Key | Action |
|-----|--------|
| `Enter` | Open it here in GHManage, selected in its repository's issues; `Backspace` comes back |
| `G` or `Ctrl+Shift+G` | Open its repository here |
| `Ctrl+O` | Open it on GitHub |
| `F` | Add it to favorites, or remove it |

---

## Searching GitHub

**File → Search GitHub…** (`Ctrl+Shift+F`) searches all of GitHub, not just one repository. Choose what to search for, **Issues and pull requests** or **Repositories**, and type the query.

The query is GitHub's own search language, exactly as on github.com, so every qualifier works:

- `is:open is:issue label:bug repo:nvaccess/nvda`
- `author:@me`, `review-requested:@me`, `mentions:@me`, `involves:@me`
- `updated:>2026-01-01`, `created:2026-09-01..2026-09-30`
- `org:nvaccess braille in:title`
- for repositories: `screen reader language:python stars:>50`, `topic:accessibility archived:false`

The results replace the list, best match first. Issue and pull request results read type, number, state, title, repository and when last updated; repository results read the same as Starred and Watched Repositories. The status bar says how many match: "Search — 512 issues and pull requests match repo:nvaccess/nvda braille is:open, showing 100."

| Key | Action |
|-----|--------|
| `Enter` | Open the issue, pull request or repository here in GHManage; `Backspace` comes back to the results |
| `G` or `Ctrl+Shift+G` | Open the result's repository here |
| `Ctrl+O` | Open it on GitHub |
| `F` | Add it to favorites, or remove it |
| `Ctrl++` | Load the next 100, added to these |
| `Ctrl+S` | Save this search |
| `Ctrl+Shift+F` | A new search, starting from this one |

GitHub returns at most the first 1,000 results of any search, and allows about 30 searches a minute. A search that matches more than 1,000 says so; narrow it to reach the rest.

Results stay in GitHub's order, best match first; **View → Sort Order** doesn't apply here. To sort, say so in the query: `sort:updated-desc`, `sort:created-asc`, `sort:comments-desc`, or for repositories `sort:stars-desc`.

An issue or pull request in a fork opens on GitHub rather than here: GHManage shows a fork's issues from its upstream, where the same number is something else.

### Saved searches

**Actions → Save Search…** (`Ctrl+S`, `Cmd+S` on a Mac) asks for a name and adds the search to the repository list, after My Work, marked with 🔍. `Enter` there runs it again, for fresh results. Saving under a name you have used replaces that search. **File → Remove from List…** with a saved search selected removes it.

Saved searches are kept on this computer, beside your favorites.

---

## Activity

**Activity** is your GitHub feed, the one github.com shows on your dashboard: what happens in the repositories you star or watch, and what the people you follow do. That covers pushes, pull requests, issues, comments, reviews, releases, stars and forks, newest first, across every repository.

Open it by choosing **Activity** near the top of the repository list, with `Ctrl+Shift+A` (`Cmd+Shift+A` on a Mac), or from **View → View Mode → Activity**. GHManage keeps the repository you were in, so `Ctrl+1` takes you straight back to its issues.

Each row reads who, what, which repository, what it was about, and when, in your local time:

"alice, merged pull request #42, nvaccess/nvda, Fix the braille cursor, 2026-10-05 14:32"

The details panel gives the whole event as one sentence, then who, what, the repository and the time on lines of their own, then the comment, review or description when there is one.

### Keys in the Activity view

| Key | Action |
|-----|--------|
| `Enter` | Open what the event is about on GitHub: the issue, pull request, comment, release or commits |
| `G` or `Ctrl+Shift+G` | Open the event's repository here in GHManage |
| `Backspace` | From that repository's issues, come back to the same event |
| `F` | Add what the event is about to favorites, or remove it |
| `Ctrl++` | Load older events |
| `R` | Reload the feed |

### Going to an event's repository

`G`, or **Actions → Go to Event's Repository** (`Ctrl+Shift+G`), opens the repository the event happened in, here in GHManage, at its **Issues & PRs**. The repository is selected in the list on the left too, when it is there. `Backspace` from those issues brings you back to the feed, on the event you left, without loading it again. The status bar says "Back to activity".

`G` works from the details panel as well as the list, since that is where "Press G to open owner/name here in GHManage" is read. The context menu on an event offers the same, as **Go to owner/name**.

### Favoriting from the feed

`F` favorites the issue, pull request, release or discussion an event is about. It is the same favorite you would make from that item's own view, so an issue favorited from the feed is starred in the repository's issues list too, and every event about a favorited item shows the ★.

Some events are about a push, a branch, or the repository as a whole, and have nothing of their own to keep. For those the status bar says "This event isn't about an issue, pull request, release or discussion, so there is nothing to favorite."

### How far back it goes

GitHub keeps only your latest 300 events, from the last 90 days. The first 100 load when you open the feed. `Ctrl++` loads the next 100 and puts you on the first of them, so you carry on reading where the list used to end. When there are no more, the status bar says "That is all GitHub keeps.", and `Ctrl++` says "No older activity. GitHub keeps only your latest 300 events, from the last 90 days."

An empty feed says what would fill it: "Activity — nothing yet. The feed shows what happens in repositories you star or watch and by people you follow."

The quick filter (`Ctrl+F`) works here as in every other view.

---

## Starred and Watched Repositories

**Starred Repositories** lists the repositories you have starred on GitHub, most recently starred first. **Watched Repositories** lists the ones you watch. Open either from its entry near the top of the repository list, or from **View → View Mode → Starred Repositories** or **Watched Repositories**.

GitHub watches your own repositories for you automatically, so they appear in Watched Repositories as well as other people's.

Each row shows the repository's name, description, main language, stars, and when it was last pushed to. A repository that is archived, a fork or private says so at the start of its description. The details panel adds its address, forks and open issues. **View → Columns** can also show the owner.

| Key | Action |
|-----|--------|
| `Enter` | Open the repository here in GHManage, at its Issues & PRs |
| `Backspace` | From that repository's issues, come back to the list, on the same row |
| `Ctrl+O` | Open the repository on GitHub |
| `F` | Add the repository to favorites, or remove it |
| `Ctrl++` | Load 100 more |
| `Ctrl+F` | Filter the list |
| `R` | Reload the list |

### Watch settings

**Actions → Watch Settings…** (`Ctrl+Shift+U`) sets how GitHub notifies you about a repository: **Participating and @mentions** (only what you take part in, GitHub's default), **All Activity** (watching: every issue, pull request, release and discussion), or **Ignore** (nothing, not even mentions). The current setting is selected when the list opens.

It acts on the repository in front of you, the same one New Issue uses: the open repository, the one selected in the repository list when that has focus, or the selected row's repository in Notifications, My Work, Activity, search results, Starred, Watched or Favorites. GitHub's **Custom** setting, to be told about only some kinds of activity, isn't available to programs, so for that use the repository's Watch button on github.com.

The first time, it will most likely tell you it needs `gh`'s "notifications" permission; see [Permissions gh does not ask for](#permissions-gh-does-not-ask-for).

These lists keep other people's repositories out of the main repository list, which stays short: just your own and the ones you opened by address. To keep a starred repository one keystroke away, favorite it with `F`, or open it by address with `Ctrl+Shift+O` to pin it in the repository list.

---

## Organizations and Shared With Me

Each organization you belong to has its own entry in the repository list, after My Work, for example "🏢 TheIdeaPlace (13)". The number is how many of its repositories you can see. Organizations you are an owner of come first, then the rest by name. `Enter` on one lists its repositories, most recently pushed first.

An organization's repositories are kept out of the list of your own, so belonging to a big organization (W3C has over a thousand repositories) doesn't bury yours. To keep one you use often a keystroke away, favorite it with `F`.

**Shared With Me** lists other people's repositories you have been made a collaborator on. It leaves out repositories owned by your organizations, which are already under those organizations' entries. It is only in the repository list when there is at least one.

Both work like Starred and Watched: the same columns and details, and the same keys (`Enter`, `Backspace`, `Ctrl+O`, `F`, `Ctrl++`, `Ctrl+F` and `R`). They keep the repository you were in, so `Ctrl+1` takes you back to it.

---

## Favorites

Favorites gather the things you come back to, from any repository, into one list. Press `F` on almost anything to add it: an issue or pull request, a branch, a commit, a tag, a release, a label, a workflow, a workflow run, a published page, a repository in Starred or Watched Repositories, or the subject of an Activity event. Press `F` again to remove it.

The status bar confirms each change: "★ Added '#12 — Crash on startup' to favorites", or "Removed … from favorites". A favorited item has a ★ at the start of its row, so you hear it as you arrow past, and pressing `F` puts the ★ on or takes it off straight away.

### The Favorites view

Choose **★ Favorites** at the top of the repository list, or press `Ctrl+9`. The entry in the repository list shows how many favorites you have.

Each row shows the kind of item, its repository, its title and a short description. The details panel adds when you favorited it and its address.

| Key | Action |
|-----|--------|
| `Enter` | Open the favorite on GitHub |
| `F` | Remove it from favorites |
| `Ctrl+F` | Filter the list |

Favorites are kept on your computer, in `favorites.json` in your settings folder, so they last between sessions and survive updates.

---

## Quick Filter

**File → Quick Filter…** (`Ctrl+F`) narrows the current list to the rows containing some text. It is not case-sensitive, and it matches anything in the columns you can see. Leave the box empty to clear the filter.

While a filter is on, the status bar has a filter item saying what it is and how many rows match, for example "Filter: 'braille' (4/100)". `Escape` in the list clears it, and the status bar says "Filter cleared". Switching to another view or repository clears it too, since a filter for issues means nothing in the branches list.

The filter only looks at what has already loaded. To search further back, load more with `Ctrl++`, or for issues and pull requests use **View → State** or a label, which ask GitHub.

With a filter on, every key acts on the row you are on: `Enter`, `F`, `C`, `O`, `G`, `Delete` and the rest, and the details panel always shows that same row.

---

## Copying

**Actions → Copy** puts something about the item you are on onto the clipboard, ready to paste into an email, a document or a chat. The status bar says what was copied, and reads it out when it is short.

| Item | Key | Copies |
|------|-----|--------|
| Copy Link | `Ctrl+Shift+C` | The item's address on github.com |
| Copy Markdown Link | `Ctrl+Shift+L` | A Markdown link, for example `[#11538 Improve diagnostics](https://github.com/nvaccess/nvda/issues/11538)` |
| Copy Title | `Ctrl+Shift+T` | The title: an issue's title, a commit's first line, a release's name |
| Copy Number, Copy SHA, … | `Ctrl+Shift+I` | The short thing that names the item; see below |
| Copy Details | `Ctrl+Shift+D` | Everything in the details panel |

The fourth item is named for what it copies in the view you are in:

| View | Item reads | Copies |
|------|------------|--------|
| Issues & PRs | Copy Number | `#208` |
| Branches | Copy Branch Name | the branch name |
| Commits | Copy SHA | the full 40-character SHA |
| Tags, Releases | Copy Tag | the tag |
| A release's files | Copy File Name | the file's name |
| Workflows | Copy File Path | the workflow file, such as `.github/workflows/ci.yml` |
| Workflow Runs | Copy Run ID | the run's id, as `gh run view` takes it |
| A run's jobs | Copy Job ID | the job's id |
| A run's artifacts | Copy Name | the artifact's name |
| Labels | Copy Label Name | the label |
| GitHub Pages | Copy Commit | the commit the publish was built from |
| Published Pages | Copy Path | the page's path in the repository |
| Favorites | Copy Name | the favorite's title, the same as Copy Title |
| My Work, search results | Copy Number, or Copy Repository Name for repositories | `owner/name#208`, since the list mixes repositories; or `owner/name` |
| Notifications | Copy Number or Repository | the issue or pull request number, or the repository for anything else |
| Activity | Copy Number, Tag or Repository | the issue or pull request number, the release's tag, or the repository for events about a whole repository |
| Starred, Watched | Copy Repository Name | `owner/name` |

In Activity, Copy Link and Copy Markdown Link copy what the event is about (the issue, pull request or release) rather than the event itself, the same thing `F` favorites.

Artifacts have no page of their own on github.com, so in a run's artifacts Copy Link and Copy Markdown Link are greyed out.

With focus in the repository list, Copy Link, Copy Markdown Link, Copy Title and the fourth item copy that repository: its address, a Markdown link to it, or `owner/name`, whatever the fourth item is called at the time. Copy Details always copies the details panel.

---

## List Mode, Sorting and Columns

### Quick and Full mode

**View → List Mode** decides how much each row says:

- **Quick Mode (compact)** shows just the values: "208  PR  OPEN  Fix the braille cursor". It is the default and the fastest to arrow through.
- **Full Mode (field names for screen reader)** puts each column's name before its value: "number: 208, type: PR, state: OPEN, title: Fix the braille cursor". In Full mode the status bar message also repeats the row as you move to it.

The current mode is shown on the status bar, and the status bar says "Quick mode: compact display" or "Full mode: field names included for screen reader" when you switch.

### Sort order

**View → Sort Order** sorts **Issues & PRs** by number, title, created date, updated date, either way round, or by most comments. Sorting rearranges what is loaded without asking GitHub again.

### Columns

**View → Columns** lists the columns the current view can show, each with a checkmark when it is on. Choose one to turn it on or off. Each view has its own columns, and its own defaults.

| View | Shown by default | Also available |
|------|------------------|----------------|
| Issues & PRs | number, type, state, title | author, created, updated, labels, assignees, comments, draft, review, +/-, files, base, head |
| Branches | branch, last commit, author, date | protected, ahead, behind |
| Commits | sha, message, author, date | files, +/- |
| Tags | tag, commit | |
| Releases | tag, name, date, downloads | assets, draft, prerelease |
| Release files | name, downloads, size, date | # |
| Workflows | name, state, path | # |
| Workflow Runs | name, status, result, branch, date | event, # |
| A run's jobs | name, status, result, duration, failed step | |
| Artifacts | name, size, expired, date | # |
| Labels | label, description, color | default |
| GitHub Pages | status, commit, pusher, date, duration | kind, error, # |
| Published Pages | page, url | size |
| Favorites | type, repo, title, subtitle | |
| Notifications | reason, type, title, repo, updated, status | |
| My Work | why, type, number, title, repo, updated | author, labels |
| Search results: issues and pull requests | type, number, state, title, repo, updated | author, labels, comments |
| Search results: repositories | repo, description, language, stars, pushed | owner |
| Activity | actor, action, repo, title, date | |
| Starred and Watched Repositories | repo, description, language, stars, pushed | owner |

The pull-request columns (+/-, files, base, head) are empty on issues. Columns go back to the view's defaults when you leave it.

---

## The Details Panel and Comment Navigation

The details panel shows everything about the item you are on in the list, and changes as you move. It is ordinary read-only text, so your screen reader's reading keys work in it: arrow line by line, read by word, select and copy.

Web addresses always have a line of their own, under a line reading "URL:", so you can arrow to one and read or copy it on its own.

Many items end with the keys that act on them, for example "Press Enter to list this run's artifacts." Those keys work from the details panel too, where they are read, as well as from the list.

### Moving between comments

An issue or pull request's comments come after its description, each beginning with a heading such as "Comment 2 of 5 — alice (2026-10-01):".

| Key | Action |
|-----|--------|
| `Alt+N` | Next comment |
| `Alt+P` | Previous comment |

On a Mac, use `Option+N` and `Option+P`. Both are also on the **File** menu as **Next Comment** and **Previous Comment**.

Each press moves focus to the details panel and selects the whole comment, from its heading to its last line, so your screen reader reads it and you can copy it. The status bar says "Comment 2 of 5". At either end it says "Already at last comment." or "Already at first comment.", and an item with none says "No comments to navigate."

---

## The Actions Menu

Everything that acts on what the list is showing is on the **Actions** menu, whichever view it belongs to. Its items are relabelled for the view you are in and greyed out where they do not apply, so the menu answers "what can I do here?" without trial and error.

| Item | Key | Works in |
|------|-----|----------|
| Open in Browser | `Ctrl+O` | Every view |
| Copy ▸ Link, Markdown Link, Title, Number, Details | `Ctrl+Shift+C`, `L`, `T`, `I`, `D` | Every view; see [Copying](#copying) |
| Close Issue/PR | `Ctrl+W` | Issues & PRs |
| Reopen Issue/PR | `Ctrl+Shift+W` | Issues & PRs |
| Add Comment… | `Ctrl+M` | Issues & PRs |
| New Issue… | `Ctrl+N` | Everywhere, for the repository in front of you; shows the new issue in its Issues & PRs |
| Search This Repository… | `Ctrl+Shift+S` | Everywhere, for the repository in front of you: a search starting `repo:owner/name` |
| Pull Request ▸ Checks, Review…, Merge…, Ready for Review or Back to Draft, Request Reviewers…, Update Branch… | `K`, `V`, `D` in the list | Issues & PRs, on a pull request |
| Watch Settings… | `Ctrl+Shift+U` | Everywhere, for the repository in front of you |
| Save Search… | `Ctrl+S` | Search results |
| New Label… | `Ctrl+I` | Any view of a repository; switches to Labels to show the new one |
| Delete | `Ctrl+D` | Labels (reads **Delete Label…**), Workflow Runs (reads **Delete Workflow Run…**) and Notifications (reads **Mark as Done**) |
| Run Workflow on Branch… | | Workflows |
| Download Artifact… | | A run's artifacts |
| Open Published Site | | GitHub Pages, once a site is found |
| Select Branch… | `Ctrl+B` | Commits |
| Compare Branches… | `Ctrl+Shift+B` | Branches |
| Go to Event's Repository | `Ctrl+Shift+G` | Activity, and Notifications where it reads **Go to Notification's Repository** |
| Mark as Read, Unsubscribe from Thread | `M`, `U` in the list | Notifications |
| Mark All as Read… | | Notifications |

On a Mac, use `Cmd` for `Ctrl`.

`Ctrl+D` follows the same rule as the menu item, and so does the bare `Delete` key, which also works from the details panel. In other views neither does anything. `Delete` never acts from the repository list.

### Context menus

The **Applications** key, `Shift+F10`, or a right-click opens a context menu (on a Mac, `VO+Shift+M` with VoiceOver, or `Ctrl`-click).

In the item list it starts with what `Enter` does in that view, for example **Show Commits** on a branch or **Open Here** on a search result, and then offers everything the Actions menu offers in that view, with Copy and Pull Request as submenus. It is built from the Actions menu each time, so the two always agree.

In the repository list, a repository's menu has **Open**, **Open on GitHub**, **New Issue…**, **Search This Repository…** (a search starting `repo:owner/name`), **Watch Settings…**, Copy, and **Remove from List…** for a repository you opened by address. These are the same commands as on the Actions menu, for the repository selected. A saved search's menu has **Run Search** and **Remove Saved Search**; Favorites and the other entries at the top have **Open**.

---

## Keyboard Shortcuts

On a Mac, use `Cmd` in place of `Ctrl` for every shortcut that has one, `Option` in place of `Alt`, and `fn` with the function keys (`fn+F1`, `fn+F6`) unless your function keys are set to work as standard keys. Single-letter keys, `Enter`, `Backspace` and `Escape` are the same. The Mac's delete key is `Backspace`; for `Delete` use `fn+delete`, or `Cmd+D`.

### Anywhere in the window

| Key | Action |
|-----|--------|
| `F6` / `Shift+F6` | Next / previous pane: repository list, item list, details panel, status bar |
| `Tab` / `Shift+Tab` | Move between the repository list, item list and details panel |
| `F1` | Open this guide in your browser |
| `Ctrl+1` … `Ctrl+0` | Switch view; see [Views](#views) |
| `Ctrl+Shift+N` | Notifications |
| `Ctrl+Shift+M` | My Work |
| `Ctrl+Shift+A` | Activity |
| `Ctrl+Shift+F` | Search GitHub |
| `Ctrl+R` | Refresh the list |
| `Ctrl++` | Load more |
| `Ctrl+F` | Quick filter |
| `Ctrl+G` | Go to an issue or pull request by number |
| `Ctrl+N` | New issue in the repository in front of you |
| `Ctrl+Shift+S` | Search the repository in front of you |
| `Ctrl+O` | Open the selected item on GitHub |
| `Ctrl+Shift+C` | Copy the selected item's link |
| `Ctrl+Shift+L` | Copy a Markdown link to it |
| `Ctrl+Shift+T` / `Ctrl+Shift+I` / `Ctrl+Shift+D` | Copy its title / number, SHA or name / details |
| `Ctrl+Shift+O` | Open a repository, or an issue, pull request, commit, release or run, by its address |
| `Alt+N` / `Alt+P` | Next / previous comment in the details panel |
| `Ctrl+Shift+U` | Watch settings for the repository |
| `Ctrl+Shift+K` | Switch GitHub account |
| Applications key or `Shift+F10` | Context menu for the selected item or repository |
| `Ctrl+Q` | Quit |

### In the item list

| Key | Action |
|-----|--------|
| `Enter` | Open, or step into, the selected item; what it does depends on the view |
| `Backspace` | Step back up to the view you came from |
| `F` | Add to favorites, or remove |
| `R` | Refresh |
| `Escape` | Clear the quick filter |

### In Issues & PRs

| Key | Action |
|-----|--------|
| `Enter` | Open on GitHub |
| `C` or `Ctrl+W` | Close |
| `O` or `Ctrl+Shift+W` | Reopen |
| `M` or `Ctrl+M` | Add a comment |
| `N` or `Ctrl+N` | New issue |
| `K` / `V` / `D` | On a pull request: checks / review / ready or draft |
| `Backspace` | Back to the labels, Notifications, My Work, search results, the Activity feed, or the Starred or Watched list, when you came from one |

### In Branches and Commits

| Key | Action |
|-----|--------|
| `Enter` on a branch | Show its commits |
| `Ctrl+Shift+B` | Compare two branches (Branches view) |
| `Ctrl+B` | Choose the branch (Commits view) |
| `Backspace` | Commits back to branches |

### In Releases

| Key | Action |
|-----|--------|
| `Enter` on a release | List its files and their download counts |
| `Enter` on a file | Download it in your browser |
| `Backspace` | Files back to releases |

### In Workflows and Workflow Runs

| Key | Action |
|-----|--------|
| `Enter` on a workflow | Run it on a branch |
| `Enter` on a run | List its artifacts |
| `J` | The run's jobs; `Enter` on a job reads its log |
| `L` | What failed |
| `E` / `X` | Rerun / cancel |
| `Ctrl+D` or `Delete` | Delete the run |
| `Enter` on an artifact | Download it into a folder you choose |
| `Backspace` | Artifacts or jobs back to runs |

### In My Work and search results

| Key | Action |
|-----|--------|
| `Enter` | Open the issue, pull request or repository here; `Backspace` comes back |
| `G` or `Ctrl+Shift+G` | Open its repository here |
| `Ctrl+S` | Save the search (search results) |
| `Ctrl+Shift+F` | A new search |

### In Labels

| Key | Action |
|-----|--------|
| `Enter` | List the issues and pull requests with the label |
| `Ctrl+I` or `Insert` | New label |
| `Ctrl+D` or `Delete` | Delete the label |

### In GitHub Pages

| Key | Action |
|-----|--------|
| `Enter` in the publish history | List the pages the site serves |
| `Enter` on a page | Open it in your browser |
| `S` | Open the site's home page |
| `Backspace` | Pages back to the publish history |

### In Notifications

| Key | Action |
|-----|--------|
| `Enter` | Open it: an issue or pull request here, anything else on GitHub |
| `M` | Mark read |
| `Delete` or `Ctrl+D` | Mark done |
| `U` | Unsubscribe from the thread |
| `I` | Include read notifications, or not |
| `G` or `Ctrl+Shift+G` | Open its repository in GHManage |

### In Activity

| Key | Action |
|-----|--------|
| `Enter` | Open what the event is about on GitHub |
| `G` or `Ctrl+Shift+G` | Open the event's repository in GHManage |
| `F` | Favorite what the event is about |

### In Starred, Watched, Shared With Me and an organization

| Key | Action |
|-----|--------|
| `Enter` | Open the repository in GHManage |
| `Ctrl+O` | Open it on GitHub |
| `F` | Favorite the repository |

### In Favorites

| Key | Action |
|-----|--------|
| `Enter` | Open on GitHub |
| `F` | Remove from favorites |

### In the status bar

| Key | Action |
|-----|--------|
| `Left` / `Right` | Previous / next item, wrapping |
| `Enter` or `Space` on the update item | Offer to restart and install the update |

---

## Release History

Every version of GHManage has release notes saying what was added, changed and fixed in it. They are all on the web, newest first, at [GHManage Release History](https://theideaplace.github.io/GHManage/releases.html), starting with version 0.1.0 in July 2026.

Each version has its own page there, and every page links to the versions either side of it, so you can read back as far as you like.

To find out which version you are running, open **Help → About GHManage**. If you installed GHManage rather than using a portable copy, it updates itself, so you are normally on the newest version already.

The same notes are on each version's own page on GitHub, alongside its downloads, at [github.com/TheIdeaPlace/GHManage/releases](https://github.com/TheIdeaPlace/GHManage/releases).

---

## Reporting Issues

Found a bug, or have an idea? Open an issue at [github.com/TheIdeaPlace/GHManage/issues](https://github.com/TheIdeaPlace/GHManage/issues). You can do it from GHManage itself: open the repository with `Ctrl+Shift+O` and `TheIdeaPlace/GHManage`, then **Open in Browser** (`Ctrl+O`) on any issue to reach the site.

A good report says:

- What you did, key by key if you can.
- What you expected, and what happened instead, including what your screen reader said and what the status bar said.
- Your version (**Help → About GHManage**), whether you are on Windows or a Mac, and which screen reader you use, if any.
- For a problem with updating, the update log described in [Where your settings live](#where-your-settings-live).
