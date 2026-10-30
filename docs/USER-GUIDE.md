# GHManage User Guide

GHManage is a keyboard-driven desktop app for your GitHub repositories, built for screen reader users. It shows issues, pull requests, branches, commits, tags, releases, workflows, labels, GitHub Pages sites and your GitHub activity feed as fast lists you can arrow through, with the details of whatever you are on in a panel below. It runs on Windows and on Apple Silicon Macs, and does all of its work through the GitHub CLI.

---

## Contents

- [System Requirements](#system-requirements)
- [Installing and Updating](#installing-and-updating)
- [Signing In with the GitHub CLI](#signing-in-with-the-github-cli)
- [The Main Window](#the-main-window)
- [Enter, Ctrl+O and Backspace](#enter-ctrlo-and-backspace)
- [The Repository List](#the-repository-list)
- [Issues and Pull Requests](#issues-and-pull-requests)
- [Labels](#labels)
- [Milestones](#milestones)
- [Insights](#insights)
- [Branches and Commits](#branches-and-commits)
- [Changed Files](#changed-files)
- [Files](#files)
- [Reading a README](#reading-a-readme)
- [Security Alerts](#security-alerts)
- [Discussions](#discussions)
- [Tags and Releases](#tags-and-releases)
- [Workflows and Workflow Runs](#workflows-and-workflow-runs)
- [GitHub Pages](#github-pages)
- [Notifications](#notifications)
- [My Work](#my-work)
- [Searching GitHub](#searching-github)
- [Activity](#activity)
- [Starred and Watched Repositories](#starred-and-watched-repositories)
- [My Organizations and Shared With Me](#my-organizations-and-shared-with-me)
- [Gists](#gists)
- [Favorites](#favorites)
- [Quick Filter](#quick-filter)
- [Copying](#copying)
- [List Mode, Sorting and Columns](#list-mode-sorting-and-columns)
- [Spoken Results](#spoken-results)
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

**Files**, a repository's code, **Security Alerts**, **Discussions**, **Milestones** and **Insights** are on the same menu after GitHub Pages, without a number; see [Files](#files), [Security Alerts](#security-alerts), [Discussions](#discussions), [Milestones](#milestones) and [Insights](#insights). **Starred Repositories** and **Watched Repositories** are on the same menu, after Activity.

Favorites, Notifications, My Work, Activity, Starred Repositories, Watched Repositories, Shared With Me, an organization's repositories and search results are not about one repository, so they work at any time. Every other view needs a repository: with none chosen, the status bar says "Select a repository first." and the view stays as it was.

Several views lead into others. `Enter` on a branch shows its commits, on a release its files, on a workflow run its artifacts, on a label the issues that carry it. `Backspace` steps back up to where you came from. See [Enter, Ctrl+O and Backspace](#enter-ctrlo-and-backspace).

When a view loads, the status bar names it and the repository, for example "Loading Branches for owner/name…", and then says what arrived.

### The status bar

The status bar is split into items:

- **The message**: what the view is showing, or the last thing GHManage told you.
- **Keys**: the keys that work in the current view, `Enter` and `Ctrl+O` first, then the view's own, and last where `Backspace` goes, for example "Enter=list files  Ctrl+O=open on GitHub  Ctrl++=view more  R=refresh  Ctrl+F=filter". `Enter` and `Backspace` are named as File and Actions name them.
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
| **File** | Open Repository or Address, Remove from List, Hidden Repositories, Archive or Unarchive Repository, Delete Repository from GitHub, Switch GitHub Account, Refresh, Back, View More, Search GitHub, Go To Issue, Quick Filter, Clear Quick Filter, Next and Previous Comment, Quit |
| **Actions** | Everything that acts on the item you are on, starting with what `Enter` does. See [The Actions Menu](#the-actions-menu). |
| **View** | View Mode, List Mode, Sort Order, Columns, State, Filter, Mark Changed Lines With, Next Pane, Previous Pane, Include Read Notifications, Speak Results |
| **Help** | User Guide, Keyboard Shortcuts, Command Palette, Report a Bug, Open Log Folder, Check for Updates, About GHManage |

**Help → User Guide** (`F1`, or `fn+F1` on a Mac) opens this guide in your web browser.

Every key that does something is on a menu with the key in its name, the single-letter keys too: **Refresh (R)**, **Back to Branches (Backspace)**, **Clear Quick Filter (Escape)**, **Next Pane (F6)**, **New Label… (Insert)**. So the menus, the Command Palette and Keyboard Shortcuts tell you every key.

### Keyboard Shortcuts and the Command Palette

**Help → Keyboard Shortcuts** (`Ctrl+F1`) lists every key in GHManage in a table of key, command and where it works: the single-letter keys in the lists as well as every menu shortcut. Type in **Filter** to narrow it, for example "delete" or "ctrl+shift"; the list's name says how many match, for example "Shortcuts, 4 matching". What it found is shown under **Filter** when you pause typing, for example "4 shortcuts.", and NVDA reads it. `Escape` closes it.

**Help → Command Palette…** (`Ctrl+Shift+P`) finds a command by name and runs it, so you don't need to know which menu it is on or what its shortcut is. Type a few letters of the command, for example "branches" or "copy link", then `Down Arrow` to move into the list, and `Enter` to run the one you are on. `Enter` in the box runs the first match, and `Up Arrow` on the first command goes back to the box. As you type, GHManage says how many commands match and which one `Enter` would run, for example "2 commands. Enter runs Branches, Ctrl+2." It is said when you pause, so it doesn't talk over your typing, and it is also shown under the box. NVDA reads it as the box's description; on a Mac it is only on screen for now. The list's name says how many match too. The command runs as if you had chosen it from its menu, on whatever you were on before you opened the palette. It lists only the commands that apply where you are, each with its shortcut and the menu it is on, so it also teaches you the shortcut for next time.

---

## Enter, Ctrl+O and Backspace

Three keys work the same way in every view.

**`Enter` goes in, inside GHManage.** Where the selected item has a deeper list, `Enter` shows it: a branch's commits, a tag's files, a release's files, a run's artifacts, a folder. Otherwise `Enter` goes into the item itself: focus moves into the details panel, at the top, where its text, comments or lines are, and `Alt+N` and `Alt+P` move through them. Where the thing to do is an action here, `Enter` does it: run a workflow, download an artifact or a release's file. In Favorites, Notifications, Activity, My Work and search results, `Enter` opens the thing in its own view here. An issue, pull request, commit or discussion opens into it, as `Enter` on its row would: its text and comments, or a commit's changed files; `Backspace` goes to its row, and again back to where you were. Anything else lands on its row. `Enter` never opens the web browser. Where GHManage has no view for something, `Enter` says so: "GHManage has no view for that; Ctrl+O opens it on GitHub."

**`Ctrl+O` opens the selected thing on GitHub**, in every view (**Actions → Open on GitHub**). It acts on the pane with focus, as Copy and `F` do: in the repository list, the repository. A few views open something else, and the menu item is named for it: a release's file opens its release (**Open Its Release on GitHub**), a publish in GitHub Pages opens its commit (**Open Its Commit on GitHub**), and a published page opens on the web (**Open on the Web**). An artifact has no page of its own, so there the item is greyed out and `Ctrl+O` says so.

**`Backspace` goes back out**, the opposite of `Enter`. In the details panel it goes back to the item's row in the list. In a list, it goes back to the list you came from, on the item you left: from a branch's commits to Branches, from Files at a tag to Tags, from what `Enter` opened in Favorites back to Favorites. **File → Back** is named for where it goes, for example **Back to Branches (Backspace)**, and is greyed out where `Backspace` has nowhere to go.

The first item on the **Actions** menu, and on the list's context menu, is what `Enter` does in the view you are in, for example **Show Commits (Enter)**, **Read (Enter)** or **Download… (Enter)**. The status bar says it the same way: "Enter=show commits".

| View | `Enter` | `Ctrl+O` | `Backspace` in the list |
|------|---------|----------|-------------------------|
| Issues & PRs | Read it, in the details panel | Open it on GitHub | Back to the label, milestone or list you came from |
| Branches | Show its commits | Open it on GitHub | |
| Commits | Its changed files | Open it on GitHub | Back to Branches |
| Tags | Its files, in Files at that tag | Open it on GitHub | |
| Releases | List its files | Open it on GitHub | |
| A release's files | Download it into a folder you choose | Open its release on GitHub | Back to Releases |
| Workflows | Run it on a branch | Open it on GitHub | |
| Workflow Runs | List its artifacts | Open it on GitHub | |
| Jobs | Read its log | Open it on GitHub | Back to Workflow Runs |
| Artifacts | Download it into a folder you choose | Nothing: no page | Back to Workflow Runs |
| Changed Files | Read its changes | Open the file on GitHub | Back to the pull request or commit |
| Files | Open the folder, or read the file | Open it on GitHub | Up a folder; at the top, back to Tags or Changed Files |
| File History | The commit's changed files | Open the commit on GitHub | Back to Files |
| Labels | List its issues and pull requests | Open it on GitHub | |
| Milestones | List its issues and pull requests | Open it on GitHub | |
| Discussions, Security Alerts, Insights, Gists | Read it, in the details panel | Open it on GitHub | |
| GitHub Pages | Browse the published pages | Open the publish's commit on GitHub | |
| Published Pages | Read it, in the details panel | Open the page on the web | Back to GitHub Pages |
| Favorites | Open it here, in its own view | Open it on GitHub | From there, back to Favorites |
| Notifications | Open it here, in its own view, and mark it read | Open it on GitHub, and mark it read | From there, back to Notifications |
| Activity | Open what it is about here | Open it on GitHub | From there, back to Activity |
| My Work, issue search results | Open it in its repository here | Open it on GitHub | From there, back to the list |
| Starred, Watched, Shared With Me, an organization, repository search | Open the repository here | Open it on GitHub | From there, back to the list |
| My Organizations | List its repositories | Open it on GitHub | |

An issue or pull request in a fork can't open here, because a fork's Issues & PRs shows its upstream's issues. `Enter` says so, for example "#9 is in me/fork, a fork; GHManage shows that repository's issues from up/r. Ctrl+O opens it on GitHub."

---

## The Repository List

The list on the left is where you choose what to look at. Arrow to an entry and press `Enter`, or double-click it. Typing a letter jumps to the next entry starting with it, except `F`, which adds the selected repository to favorites or removes it (see [Favorites](#favorites)).

It is in this order:

1. **★ Favorites**, with how many you have, for example "★ Favorites (12)". See [Favorites](#favorites).
2. **Activity**: your GitHub feed. See [Activity](#activity).
3. **Starred Repositories**: the repositories you have starred, with how many, for example "Starred Repositories (7)". See [Starred and Watched Repositories](#starred-and-watched-repositories).
4. **Watched Repositories**: the repositories you watch, with how many.
5. **Notifications**, with how many are unread, for example "Notifications (12 unread)". See [Notifications](#notifications).
6. **My Work**: open issues and pull requests that need you, with how many once it has loaded. See [My Work](#my-work).
7. **My Organizations**: the organizations you belong to, with how many, for example "My Organizations (3)". See [My Organizations and Shared With Me](#my-organizations-and-shared-with-me).
8. **Gists**: your gists, with how many, for example "Gists (4)". See [Gists](#gists).
9. **Shared With Me**: other people's repositories you have been made a collaborator on, with how many. It is only there when there is at least one.
10. **Your saved searches**, each marked with a magnifying glass, for example "🔍 NVDA braille bugs". See [Saved searches](#saved-searches).
11. **Repositories you opened by address**, each marked with a pin, for example "📌 nvaccess/nvda — NVDA, the free and open source screen reader".
12. **Your own repositories**, most recently pushed first, each followed by its description, up to 100.

The first eight are always there, so the same keystrokes from the top of the list always reach them. The first four are where they were before Notifications, My Work and My Organizations arrived. When the list first loads, the status bar says how many repositories it found: "Loaded 42 repositories. Select one to view issues and PRs."

The notification, starred, watched and gist counts are asked for once the list is up, so they appear a moment after the names, without moving you from the entry you are on. If GitHub can't be asked, the entry shows just its name rather than a number that might be wrong. Opening Starred, Watched or Gists, or pressing `R` in it, brings its count up to date, so a repository you starred on the web since GHManage started is counted then.

Opening a repository shows its **Issues & PRs**. Use `Ctrl+2` through `Ctrl+0` to reach its other views.

### Opening a repository or a GitHub address

**File → Open Repository or Address…** (`Ctrl+Shift+O`) opens any repository on GitHub, yours or not, without cloning it, and goes straight to most things inside one. Type or paste:

- `owner/name`, `https://github.com/owner/name` or `git@github.com:owner/name.git` to open the repository on its issues and pull requests. It is added to the repository list with a pin, where it stays between sessions until you remove it.
- The address of an issue or pull request (`…/issues/12`, `…/pull/12`) to open it: its text and comments, in the details panel, as `Enter` on its row would. A pull request's changes (`…/pull/12/files`, `…/pull/12.diff`) open its [Changed Files](#changed-files) instead, as `H` on it would. `Backspace` takes you to its row in the repository's issues and pull requests. When it is not among those loaded, closed say, it is fetched and added, as Go To Issue does.
- A commit (`…/commit/<sha>`) to open its changed files, as `Enter` on it in Commits would. A commit that isn't among the default branch's latest is fetched and shown first.
- A release (`…/releases/tag/v1.2`) or a workflow run (`…/actions/runs/<id>`) to open Releases or Workflow Runs on it, with its details in the details panel. A branch (`…/tree/<branch>`) opens that branch's commits.
- A list (`…/releases`, `…/pulls`, `…/actions`, `…/labels`, `…/branches`, `…/tags`, `…/commits`) to open that view.

- A branch's history (`…/commits/<branch>`) opens that branch's commits; a workflow file (`…/actions/workflows/ci.yml`) opens Workflows.

A discussion's address opens it, in the repository's Discussions. Each address says what it is opening, for example "Opening #14845 in cli/cli…", and then where it got to, "Opened pull request #14845 — …": a big repository can take several seconds to load. Any other address inside a repository, a file or the wiki say, opens the repository on its issues, and the status bar says GHManage has no view for that page. A branch whose name has a `/` in it can't be told apart from a folder in a `…/tree/` address, so that opens the repository too. Only a repository's own address pins it: a link from an email to an issue, a file or anything else in a repository opens without adding to your list.

Addresses can be pasted as they come: wrapped in `<…>` or brackets, followed by a full stop or comma, in any mix of upper and lower case. Only github.com is read; addresses on other GitHub hosts, gists, raw files and the API get the "Couldn't read that" message.

When the clipboard already holds a GitHub address, the box starts with it filled in, so opening a link you have copied is `Ctrl+Shift+O` and `Enter`. If you copied a whole sentence or paragraph, the first GitHub address in it is the one offered.

A person's or organisation's address says so on the status bar; GHManage has no profile view. An address it cannot read at all gets "Couldn't read that. Use a github.com address or OWNER/NAME."

### Removing a repository from the list

`Delete` in the repository list, or **File → Remove from List**, takes the selected repository out of the list. It never deletes anything on GitHub. The status bar confirms it, for example "Removed owner/name from the list."

That works for every repository in the list: ones you opened by address, and your own. GitHub still lists your own repositories each time the list loads, so GHManage keeps a note of the ones you removed and leaves them out. When some are left out, the status bar says how many when the list loads, for example "Loaded 20 repositories (3 hidden)."

After a removal you are on the row that took its place, so you can go on down the list.

To put one back, choose **File → Hidden Repositories…**. It lists the repositories you have removed: move to one and press `Enter` (the **Show Again** button) to put it back in the list. The window stays open for the next one, and closes on its own when none are left; `Escape` closes it. Opening a hidden repository by its address with **File → Open Repository or Address…** brings it back too.

The entries at the top, organizations included, are always there. A saved search is removed the same way, but it can't be brought back, so GHManage asks first.

### Archiving or deleting a repository on GitHub

Removing a repository from the list leaves it on GitHub. To change the repository on GitHub itself, select it in the list and choose one of these from the **File** menu or the repository's context menu. Neither has a shortcut key, so a slip of the finger can't reach them. Both need admin rights on the repository; without them, GHManage says so and stops.

**Before you delete a repository for the first time**, gh needs one more permission, which it doesn't ask for when you sign in because deleting can't be undone. Do this once for each GitHub account: open a terminal (Command Prompt or PowerShell on Windows, Terminal on a Mac), type the command below and press `Enter`. gh shows a one-time code and asks you to press `Enter`; your browser opens on GitHub, where you type the code and approve.

```
gh auth refresh -h github.com -s delete_repo
```

If you haven't done this, GHManage deletes nothing and shows you the same command. Archiving needs no extra permission.

- **Archive Repository…** makes it read-only on GitHub: no new issues, pull requests, comments or pushes, but everything stays and you can still read it. GHManage asks first, with **No** as the answer if you just press `Enter`. An archived repository's entry reads **Unarchive Repository…**, which undoes it. On the File menu the entry is **Archive or Unarchive Repository…**, and the question says which it will do.
- **Delete Repository from GitHub…** deletes it for good, with its code, issues, pull requests, releases, wiki and Actions history. This can't be undone. The window that opens says so, and asks you to type the repository's name, for example `owner/name`. **Delete** stays unavailable until what you have typed matches. When what you type matches, GHManage says "The name matches. Delete is available." **Cancel** is the default, and `Enter` in the box moves to **Delete** once the name matches rather than deleting, so pressing `Enter` never deletes on its own; before it matches, `Enter` says "That doesn't match owner/name yet." Afterwards the repository is gone from the list, from your pinned repositories and from your favorites, and you are on the row that took its place. If it was the repository open on the right, GHManage shows your notifications instead.

### Forks

GitHub turns issues off on a fork by default, and the issues and pull requests that matter live on the repository it was forked from. So when you open a fork, its **Issues & PRs** and **Labels** come from that upstream repository, and the status bar says so, for example "you/nvda (issues from upstream nvaccess/nvda)". Pull requests opened only within the fork itself are not shown. Branches, commits, releases, workflows and the rest are the fork's own.

---

## Issues and Pull Requests

**Issues & PRs** (`Ctrl+1`) lists a repository's issues and pull requests together, newest first, like an inbox. It is what you see when you open a repository.

Each row shows the number, whether it is an issue or a PR, its state (OPEN, CLOSED or MERGED) and its title. Other columns are available under **View → Columns…**; see [List Mode, Sorting and Columns](#list-mode-sorting-and-columns). The status bar counts what loaded: "owner/name — 23 issues, 7 PRs (open). Showing up to 100 newest."

The details panel shows the item in full: state, author, dates, address, labels, assignees and comment count; for a pull request whether it is a draft, whether it is merged, its review status, its branches and the size of its changes; then the description and every comment. `Alt+N` and `Alt+P` move between the comments. See [The Details Panel and Comment Navigation](#the-details-panel-and-comment-navigation).

### Choosing what is listed

- **View → State** shows **Open**, **Closed** or **All**. Open is the default.
- **View → Filter** shows **Issues Only**, **PRs Only**, or **Issues & PRs**.

Both reload the list from GitHub, so they reach items that were never in the list you had.

### Keys in the issues list

| Key | Action |
|-----|--------|
| `Enter` | Read it: focus moves into the details panel, at the top, with its comments after its description. `Backspace` there comes back to the row |
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
| `H` | Its changed files, and each file's changed lines; see [Changed Files](#changed-files) |
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

## Milestones

**View → View Mode → Milestones**, or **Go To → Milestones** on a repository in the repository list, lists the repository's milestones in GitHub's order: the nearest due date first, then those without one. The columns are Title, Due, Open, Closed, Done and State; Description and Updated can be added under **View → Columns…**. Open and Closed count the milestone's issues and pull requests together, as GitHub does, and Done is the closed ones as a percentage, such as "82%". **View → Sort Order** doesn't apply here.

**View → State** chooses what is listed: **Open** (the default), **Closed** or **All**.

Selecting a milestone shows it in the details panel: its title, state, due date, progress ("76 of 92 closed, 82% done"), the open and closed counts, who created it, when it was created, updated and closed, its address on the line after "URL:", and its description.

| Key | Action |
|-----|--------|
| `Enter` | List the milestone's issues and pull requests |
| `Ctrl+O` | Open the milestone on GitHub |

### Browsing by milestone

`Enter` on a milestone shows **Issues & PRs** restricted to it, as `Enter` on a label does. The window title and the status bar name it, for example "owner/name — 16 issues, 0 PRs (open) in milestone '2027.1'". Everything in Issues & PRs still works there, including the state filter, sorting and columns. `Backspace` returns to the milestones, on the one you came from. `Ctrl+1` drops the restriction.

**View → State** is shared: choose **All** in a milestone's issues to see the closed ones as well, and the milestones list shows all of its milestones too when you go back.

On a fork, milestones come from the upstream repository, the same one the issues come from.

A list of very large pull requests can take GitHub too long to measure. Then GHManage lists them without their sizes, and the Changes and Files columns are blank, rather than showing nothing at all.

---

## Insights

**View → View Mode → Insights**, or **Go To → Insights** on a repository in the repository list, shows who visits the repository and who has built it: one list whose rows are the figures themselves. The Section column says what each row is, and each count says what it counts, so a row reads whole on its own:

- **Views**: first the total for the last 14 days, "Views, Last 14 days, 1,234 views, 210 unique visitors", then a row for each day, newest first.
- **Clones**: the same for clones and unique cloners.
- **Referrer**: the sites people came from, most first.
- **Page**: the repository's most visited pages, most first.
- **Contributor**: each contributor with their commits on the default branch, most first, up to 500; the status bar says when there are that many.

The status bar sums it up, for example "owner/name — 1,234 views (210 unique) and 56 clones (12 unique) in the last 14 days, 30 contributors." Selecting a row shows it in full in the details panel. `Enter` moves into it in the details panel, and `Backspace` comes back. `Ctrl+O` opens it on GitHub: the repository's traffic page for views, clones and referrers, the page itself for a popular page, and the person's profile for a contributor. The quick filter (`Ctrl+F`) finds rows by section or name, for example "contributor". **Copy Details** copies what the details panel shows; **Copy Markdown Link** gives the row as it reads, linked.

GitHub keeps traffic for 14 days only, and shows it only to people who can push to the repository. Without that access the Views, Clones, Referrer and Page rows are left out, and GHManage says "Traffic needs push access to owner/name, which you don't have." after the first row. GitHub won't list the contributors of a very large repository, and says so; and when it is still counting them, GHManage says "GitHub is still counting the contributors; press R in a moment."

**View → Sort Order** doesn't apply here, and `F` doesn't make a row a favorite: favorite the repository from the repository list instead.

---

## Branches and Commits

### Branches

**Branches** (`Ctrl+2`) lists each branch with its last commit, who made it and when. **View → Columns…** adds whether the branch is protected and how far it is ahead of and behind the default branch.

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

**All branches**, first in that list, shows recent commits from every branch together, newest first. A commit on several branches appears once, naming each of them. **View More** (`Ctrl++`) adds older commits, up to the newest 100 of each of the default branch and the 99 most recently changed branches (on a repository with more than 1,000 branches, of the first 1,000 by name); that makes it a view of recent work across branches rather than of older history, for which you pick one branch. For an older commit, the branches named are the ones it is still among the newest commits of, which may not be every branch that has it. If some branches couldn't be read, the status bar says how many.

Each commit shows its short SHA, message, author and date; **View → Columns…** adds the branch (on All branches, the first few branches it is on and how many more), how many files changed and the lines added and removed. The details panel has the full SHA, the branch or every branch it is on, the whole message, and the files changed when GitHub reports them. `Enter` on a commit lists its changed files, with their lines; see [Changed Files](#changed-files). `H` does the same, and `Ctrl+O` opens the commit on GitHub.

---

## Changed Files

**Changed Files** lists the files a pull request or a commit changed, and lets you read each file's changed lines, a line at a time, with every line saying whether it was added, removed or left as it was.

To open it, press `Enter` on a commit in Commits, or `H` on a pull request in Issues & PRs or on a commit. **Actions → Changed Files** (`Ctrl+Shift+H`) and the context menu do the same, and so does opening a pull request's changes address, such as `…/pull/12/files` or `…/pull/12.diff`, with **File → Open Repository or Address…**. When the files have loaded, GHManage says how many there are and how many lines were added and removed, for example "3 files changed, 40 lines added, 12 removed." `Backspace` takes you back to the pull request or commit, in the list as you left it.

Each file has a row with its path, what happened to it (Added, Modified, Deleted or Renamed), how many lines were added and removed and, for a pull request, how many review comments it has. The quick filter (`Ctrl+F`) finds a file by part of its name.

### Reading a file's changes

The details panel shows the selected file. Its first line sums the file up, for example "src/app.py: modified, 2 lines added, 1 removed." For a renamed file, it also says the name the file had before. Then come the changes: each run of changed lines begins with where it is in the file, such as "Lines 10 to 15:", followed by its lines. A few unchanged lines either side of the changes are included so you know where you are.

`Enter` on a file moves into its lines, at the top. Read them with your screen reader's reading keys, as in any text. `Alt+N` and `Alt+P` move to the next and previous run of changes, selecting its "Lines…" line; the status bar says "Change 2 of 5". On a Mac, use `Option+N` and `Option+P`. In this view, the **File** menu's Next Comment and Previous Comment read Next Change and Previous Change.

GitHub doesn't give the lines of a binary file, such as an image, or of a file whose changes are very large. Such a file still has its row, and the details panel says why there are no lines to show. `Ctrl+O` opens the file on GitHub.

### Review comments on a pull request's lines

For a pull request, the comments reviewers left on its lines are part of each file's text. A comment comes straight after the line it is on, starting "Comment by alice:", and the rest of a long comment follows it, indented. Replies come after it, starting "Reply by bob:", indented a little further. A comment on several lines says so: "Comment by alice on lines 10 to 12:", after the last of them.

Comments on lines that later commits changed are no longer on any line shown, so they are listed at the end of the file under "Earlier comments, on lines changed since:", each saying the line it was on, for example "Comment by alice on line 12 as it was:". Comments on the file as a whole come under "Comments on the whole file:", and comments on lines this view doesn't show, such as the lines of a file too large for GitHub to show, under "Comments on lines not shown here:", each saying its line.

`Alt+N` and `Alt+P` stop at each comment and reply as well as at each run of changes, selecting the whole comment (or, for a comment over about 500 characters, its first line: see below). The status bar counts each kind on its own: "Change 2 of 7", then "Comment 1 of 3". In this view the **File** menu's items read Next Change or Comment and Previous Change or Comment. When the files load, GHManage also says how many comments there are, for example "9 files changed, 251 lines added, 28 removed. 2 comments."

A commit's changed files have no review comments, so its rows leave the Comments column empty.

### Commenting on a line

To comment on a line of a pull request, move into the file's lines, put the caret on the line and press `M`, or choose **Actions → Comment on This Line…**. A box asks for the comment, naming the line and showing it, for example "Comment on line 12 of src/app.py:". Type the comment and press `Tab` to the OK button, or press `Escape` to leave without commenting. The comment goes on the pull request's latest commit, and GHManage says "Comment added on line 12." Your comment then appears after the line, after any comments already on it, with the caret still on the line, so `Alt+N` reads the comments on it in turn. If the pull request has had new commits since you opened its files, GHManage doesn't post the comment, since the line numbers may have moved; it asks you to press `R` in the list of files to read them again first. The file's Comments column counts it too.

An added or unchanged line takes a comment on the file as it is after the change. A removed line takes one on the file as it was, and the box says "removed line 12" to show which. The summary line, a "Lines…" line, a comment, and the "No newline at end of file" notes can't take a comment; `M` on one of them says why. `M` in the list of files asks you to move into the lines first, and a commit's lines can't take comments here.

### How lines are marked

**View → Mark Changed Lines With** chooses how each line starts. Here is the same change in each style:

Words (Added, Removed, Unchanged), the default:

```
Lines 1 to 3:
Unchanged: def foo():
Removed:     return 1
Added:     return 2
```

Short words (Add, Del, Same):

```
Lines 1 to 3:
Same def foo():
Del     return 1
Add     return 2
```

Diff symbols (+, -, =):

```
Lines 1 to 3:
= def foo():
-     return 1
+     return 2
```

Diff symbols with changed lines (!-, !+, +, -, =). A line that was changed, rather than only added or only removed, is shown as its old version marked `!-` and then its new version marked `!+`. When several lines were changed together, each old line is followed by its new one, so you can compare them as you go:

```
Lines 1 to 3:
= def foo():
!-     return 1
!+     return 2
```

The mark always comes first and the line's own indentation is kept after it. A blank line reads "blank line", for example "Unchanged: blank line".

Your screen reader speaks symbols only if its punctuation level reads them, so GHManage reminds you of this when you choose a symbol style. If you don't hear the marks, raise your screen reader's punctuation level, or use one of the words styles, which read at any level.

The choice is remembered, and the details panel changes straight away. The Chat Place uses the same four styles, so a change reads the same in both.

### Copying a diff or opening it in another app

**Actions → Copy → Copy Diff** (`Ctrl+Shift+X`) puts a diff on the clipboard, the way `gh pr diff 123 | clip` does:

- on a pull request in Issues & PRs, or a commit in Commits, the whole diff;
- in Changed Files, the selected file's diff.

**Actions → Open Diff in Default App** (`Ctrl+Shift+E`) saves the same diff as a `.diff` file and opens it in whatever app your computer opens `.diff` files with, such as Visual Studio Code. If no app is set for `.diff` files, Windows asks which app to use, and Notepad is one of the choices. The files are kept in a GHManage folder in your temporary folder.

---

## Files

**Files** shows a repository's code: its folders and files, at its default branch or any branch or tag you choose. Selecting a file shows its text in the details panel, a line of the file to a line of the panel, so your screen reader's line keys move through it as they would in an editor.

Choose **View → View Mode → Files**, or **Go To → Files** on a repository's context menu in the repository list. The list starts at the top of the repository, folders first, then files, each in name order. Each row has the entry's name, its type (Folder, File, Link or Submodule) and a file's size; **View → Columns…** adds its full path.

The list is named for where you are, for example "Files: src/ on main", and the status bar says the same with how many folders and files there are. When a folder loads, GHManage says its name and what is in it.

### Moving around

- `Enter` on a folder goes into it. `Backspace` comes back out, onto the folder you were in. At the top of the repository, `Backspace` only says so.
- **Actions → Select Branch or Tag…** (`Ctrl+B`) chooses which branch or tag to look at: the branches come first, then the tags, each marked "(tag)". You stay in the same folder, on the same file, when the branch or tag has them; otherwise you are taken to the top, and GHManage says why.
- `R` reads the folder again from GitHub. A folder you have already been in this visit opens straight away, without asking GitHub again.
- The quick filter (`Ctrl+F`) finds an entry in the folder by part of its name.
- `H` and `B` are taken by File History and Blame here, so typing them doesn't jump to an entry starting with that letter; the other letters do.

### Reading a file

The details panel shows the selected file. Its first line names the file and says how many lines it has, for example "README.md: 120 lines." Line 1 of the file is the panel's second line, line 2 its third, and so on.

`Enter` on a file moves into its text, at the top. In a Markdown file (one ending `.md` or `.markdown`), `Alt+N` and `Alt+P` move to the next and previous heading, so a README reads by section; the status bar says "Heading 2 of 9". Lines starting `#` inside a fenced code block are not headings.

A file larger than 1 MB, or one that isn't text, such as an image, is not shown: the details panel says so, and `Ctrl+O` opens it on GitHub. A link says where it points. A submodule is another repository; the panel says which commit of it this one uses, and `Ctrl+O` opens the folder it is in on GitHub, which links to it.

`Ctrl+O` opens the selected file or folder on GitHub. **Copy → Copy Path** (`Ctrl+Shift+I`) copies the file's path from the top of the repository, and **Copy Details** (`Ctrl+Shift+D`) copies everything in the details panel, which for a file is its text with the line naming it first. `F` adds the file or folder to your favorites.

### Blame: who last changed each line

`B` on a file, or **Actions → Blame**, shows in the details panel who last changed each line and in which commit. The file is shown in runs of lines, each headed like this:

```
Lines 10 to 14: Kelly Ford, 2026-09-01, abc1234 Fix the parser
```

followed by those lines of the file. A run of one line starts "Line 7:". `Alt+N` and `Alt+P` move between the runs, and GHManage says how many there are. `B` again shows the file's text again, and so does moving to another row.

Blame takes a few seconds on a big file; the status bar says it is getting it. Blame is for text files: a binary file, a link or a folder has none.

### A file's history

`H` on a file, or **Actions → File History**, lists the commits that changed it on the branch or tag you are looking at, newest first, with each commit's SHA, message, author and date. `Ctrl++` loads more. `Backspace` comes back to Files, on the file.

Selecting a commit shows, in the details panel, what that commit did to the file: a line naming the commit, then the file's changed lines marked in the style chosen under **View → Mark Changed Lines With**, exactly as in [Changed Files](#changed-files). `Alt+N` and `Alt+P` move between the runs of changes.

`Enter` (or `H`) on a commit opens it in Changed Files, with all the files it changed; `Backspace` from there comes back to the history. `Ctrl+O` opens the commit on GitHub, and Copy Diff and Open Diff in Default App work on the whole commit, as in Commits.

GitHub lists a file's history by its path, so it stops where the file was renamed: commits from before it had its present name are not listed.

### The whole file, from Changed Files

In [Changed Files](#changed-files), `W` on a file, or **Actions → Open Whole File**, opens it in Files: the folder it is in, on the file, as it is at the commit, or at the pull request's latest commit. Use it to read the code around a change. `Backspace` from that folder goes back to Changed Files, on the file. A file the change deleted has no whole file to open, and GHManage says so.

---

## Reading a README

**Actions → Read README** (`Ctrl+Shift+R`) reads the README of the repository in front of you: the one selected in the repository list when that has focus, the selected row's repository in a list of many (Starred, Notifications, search results and the like), and otherwise the repository open. It is also on a repository's context menu in the repository list.

The README opens in [Files](#files), on the default branch, in the folder GitHub found it in (usually the top; sometimes `docs` or `.github`), with the README selected and focus in its text at the first line, which names the file and says how many lines it has. Everything Files does works on it: in a Markdown README, `Alt+N` and `Alt+P` move from heading to heading; `B` shows its blame and `H` its history; `Ctrl+B` reads it on another branch or tag. `Backspace` moves out of the text to the list of files around it. From a row of a list of many, `Backspace` from the top of the repository goes back to that row.

A repository without a README opens at the top of its files, and GHManage says it has none.

---

## Security Alerts

**View → View Mode → Security Alerts**, or **Go To → Security Alerts** on a repository in the repository list, lists the repository's security alerts from GitHub: Dependabot alerts about the packages it depends on, code scanning alerts about its code, and secret scanning alerts about passwords and keys committed to it, all in one list. The Kind column says which each one is. GHManage only reads alerts; to dismiss or reopen one, open it on GitHub.

The columns are Kind, Severity, Package or rule, Summary, Where, State and Created. Where is the manifest file for a Dependabot alert (such as `requirements.txt`), the file and line for code scanning, and where a secret was found. The most severe come first, critical, high, medium and low, and newest first within each. Code scanning rules that aren't about security have only the scanning tool's own error, warning or note, which come after low; secret scanning alerts have no severity, so an open secret that still works, or has leaked publicly, comes with the high ones and the rest come last. **View → Sort Order** doesn't apply here.

**View → State** chooses what is listed: **Open** (the default), **Closed** (dismissed, fixed or, for secrets, resolved) or **All**. `Ctrl++` loads more of each kind when there are more than one page.

Selecting an alert shows everything GitHub says about it in the details panel:

- **Dependabot**: the advisory's summary, the package, the manifest, whether it is a direct or indirect dependency and for runtime or development, the affected versions, the first patched version, the GHSA and CVE ids, the CVSS score, and the advisory's description.
- **Code scanning**: the rule, the tool, the file and line, the branch, the tool's message about this place, the CWE, and the rule's description.
- **Secret scanning**: the kind of secret, whether it is still valid, where it was found, and whether someone pushed it past push protection. The secret itself is never fetched or shown.

A closed alert also says who dismissed or resolved it, when and why. The alert's address is on the line after "URL:", and a Dependabot advisory's after "Advisory URL:".

`Enter` moves into the alert in the details panel, at the top, and `Backspace` comes back to the row. `Ctrl+O` opens the alert on GitHub. **Copy** works as everywhere else; Copy Advisory, Rule or Secret Type (`Ctrl+Shift+I`) copies the CVE id (or the GHSA id when there is no CVE), the code scanning rule id, or the secret's type.

### When a kind of alert can't be shown

Each kind of alert is turned on separately on GitHub, and each needs its own rights, so GHManage shows what it can and says plainly what it can't, in the status bar and, when the list is empty, in the details panel. For example:

- "Dependabot alerts aren't turned on for this repository."
- "Code scanning isn't set up on this repository."
- "Secret scanning isn't turned on for this repository."
- "Code scanning alerts need admin or security manager rights on this repository."

On a repository you don't administer, the last is the usual answer: GitHub shows security alerts only to admins and security managers. Secret scanning doesn't say which of the two it is, so for it the message names both.

Rarely, the way `gh` signs in isn't allowed to read security alerts at all, and GitHub says so. Then the status bar gives the command that adds `gh`'s "security_events" permission:

```
gh auth refresh -h github.com -s security_events
```

Run it in a terminal, approve it in your browser, then press `R`.

## Discussions

**View → View Mode → Discussions**, or **Go To → Discussions** on a repository in the repository list, lists the repository's discussions, the most recently active first. The columns are Number, Category, Title, Author, Answered, Comments and Updated; Created, State and Upvotes can be added under **View → Columns…**. Answered says "Answered" or "Unanswered" for a discussion in a category that takes an answer, such as Q&A, and is blank in the others. **View → Sort Order** doesn't apply here.

**View → State** chooses what is listed: **Open** (the default), **Closed** or **All**. `Ctrl++` loads more when the status bar says there are more.

Selecting a discussion shows it in the details panel: its number, category and title, then its state, author, when it was started and last active, whether it is answered and by whom, its upvotes and how many comments it has, its address on the line after "URL:", and its text. Its comments follow, read when the selection rests on it a moment (the panel says "Getting the comments…" until then), each under a heading such as "Comment 2 of 5 — alice (2026-10-01):", with its replies indented under it, such as "Reply 1 of 2 to comment 2 — bob (2026-10-02):". The comment or reply chosen as the answer has ", the answer" at the end of its heading, and the Answered line says which it is: "Answered: Yes by bob in reply 1 to comment 2". A comment hidden on GitHub shows its heading only. `Alt+N` and `Alt+P` move from comment to comment and reply to reply.

`M`, or **Actions → Add Comment…** (`Ctrl+M`), comments on the selected discussion. Type the comment and choose OK. The comments are read again with yours among them, and the caret stays where it was. A locked discussion can't take comments, and GHManage says so.

`Enter` moves into the discussion in the details panel, at the top, where `Alt+N` and `Alt+P` move between its comments, and `Backspace` comes back to the row. `Ctrl+O` opens the discussion on GitHub. **Copy** works as everywhere else; Copy Number copies `#7`. `F` adds it to your favorites.

A repository with discussions turned off says so, in the details panel and aloud.

---

## Tags and Releases

### Tags

**Tags** (`Ctrl+4`) lists the repository's tags and the commit each points at. `Enter` on a tag opens its files in [Files](#files), as they are at that tag, from the top of the repository; everything in Files works there. `Backspace` at the top comes back to Tags, on the tag. `Ctrl+O` opens the tag on GitHub.

### Releases

**Releases** (`Ctrl+5`) lists releases with their tag, name, date and **downloads**: how many times the files attached to each were downloaded, added together. **View → Columns…** adds the number of files and whether a release is a draft or a pre-release.

The status bar totals the downloads of every release currently loaded, for example "owner/name — 30 releases. 12,408 downloads across them." `Ctrl++` loads more releases, and the total grows with them.

The details panel shows a release's downloads file by file, most downloaded first, followed by its release notes.

### A release's files

`Enter` on a release lists its files, each with its download count and size, and the status bar gives the total: "Showing 6 assets for v1.2.0, 3,204 downloads in total". A release with no files says so instead.

In that list, `Enter` downloads the selected file: GHManage asks which folder to save it in, and asks before replacing a file of the same name there. The status bar says "Downloaded app.zip into C:\Users\you\Downloads." when it is done, and your screen reader says it too. `Ctrl+O` opens the release on GitHub, and `Backspace` returns to the releases.

### Reading download counts

A download count is a running total kept by GitHub for the life of the file. It is not broken down by date, and GitHub offers no way to get it by date, so to see downloads over time you have to note the numbers and compare them later. Counts include automated downloads, such as other software checking for updates, so a sudden spike on one release deserves some suspicion.

---

## Workflows and Workflow Runs

### Workflows

**Workflows** (`Ctrl+6`) lists the repository's GitHub Actions workflows: each one's name, whether it is active, and its file.

`Enter` runs the selected workflow on a branch you choose. So does **Actions → Run on a Branch… (Enter)**, the first item on the Actions menu and the context menu here. It goes like this:

1. GHManage asks which branch to run on.
2. It reads the workflow file *on that branch* to find out whether it can be run by hand, and what inputs it takes. The branch comes first because a branch can add or change inputs, and the form has to match the branch that will run.
3. If the workflow takes inputs, a form asks for them, laid out as GitHub's own **Run workflow** form is: a list to choose from, a checkbox, or a box to type in, each labelled with the input's description and with its default filled in. Required inputs say "(required)", and **OK** will not go ahead while one is empty; it says which one and puts you in it. A workflow with no inputs skips this step.
4. The run starts, and the status bar says so: "Started 'Build' on main. Switch to Workflow Runs and refresh to watch it."

A workflow can only be run by hand if its file has an `on: workflow_dispatch` trigger. If it does not, GHManage tells you so and runs nothing.

### Workflow runs

**Workflow Runs** (`Ctrl+7`) lists recent runs: the workflow's name, its status (queued, in progress or completed), its result, the branch and the date. **View → Columns…** adds the event that started it and the run number.

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

A run's **Artifacts** list shows each file the run saved, with its size, whether it has expired, and when it was made. `Enter`, or **Actions → Download… (Enter)**, asks which folder to save it in and downloads it there. An artifact has no page of its own on GitHub, so **Open on GitHub** is greyed out here and `Ctrl+O` says so. The status bar says "Downloaded 'build' into C:\Users\you\Downloads." when it is done.

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
| `Enter` | Read the page's details: its address, size, and how it is served |
| `Ctrl+O` | Open the page on the web (**Actions → Open on the Web**) |
| `S` | Open the site's home page in your browser (also in the publish history) |
| `F` | Add the page to favorites, so one you check often is a keystroke away |
| `Backspace` | Return to the publish history |

**Actions → Open Published Site** does what `S` does, once GHManage knows there is a site. In the publish history, `Ctrl+O` (**Open Its Commit on GitHub**) opens the commit a publish came from.

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
| `Enter` | Open it here in GHManage, on it: an issue or pull request in its repository's Issues & PRs, a discussion in Discussions (found by its title when GitHub doesn't give its number), a release in Releases, a commit in Commits. A workflow run, which notifications don't identify, opens the repository's Workflow Runs; a security alert its Security Alerts. Anything else says GHManage has no view for it, and that `Ctrl+O` opens it on GitHub. Either way it is marked read. An issue, pull request, commit or discussion opens into it, as `Enter` on its row would: its text and comments, or a commit's changed files; `Backspace` goes to its row, and again back to where you were. Anything else lands on its row. |
| `Backspace` | From what `Enter` opened, come back to the same notification |
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

**File → Search GitHub…** (`Ctrl+Shift+F`) searches all of GitHub, not just one repository. Choose what to search for, **Issues and pull requests** or **Repositories**, and type in the **Search** box.

The query is GitHub's own search language, exactly as on github.com, so every qualifier works:

- `is:open is:issue label:bug repo:nvaccess/nvda`
- `author:@me`, `review-requested:@me`, `mentions:@me`, `involves:@me`
- `updated:>2026-01-01`, `created:2026-09-01..2026-09-30`
- `org:nvaccess braille in:title`
- for repositories: `screen reader language:python stars:>50`, `topic:accessibility archived:false`

The dialog has some of these under **Examples**, just below the **Search** box. You hear them only when you go to them: press `Alt+X`, or `Shift+Tab` from **Search for**.

### Search qualifiers

GitHub calls the parts such as `is:open`, `label:bug` and `author:@me` **qualifiers**. You don't have to remember them. In the search dialog, press `Alt+Q` or choose **Insert Qualifier…** for a table of them, each with what it means and an example. The table matches what you are searching for: issues and pull requests (reviews, checks, draft, branches, merged), or repositories (stars, language, topics, license). Type in **Filter** to narrow it, for example "review" or "date".

**Notes**, under the table (`Alt+N`), says how to write numbers, dates and ranges, how to leave something out, and how to keep words together.

`Enter`, or **Insert into Search**, puts the selected qualifier into the **Search** box where the cursor was. One that needs a value, such as `label:`, is left for you to type it; one that is complete, such as `is:open`, gets a space after it. **Open GitHub Search Documentation** opens GitHub's full reference in your browser.

`F1` in the search dialog opens this part of the guide.

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

**Actions → Save Search…** (`Ctrl+S`, `Cmd+S` on a Mac) asks for a name and adds the search to the repository list, after My Work, marked with 🔍. `Enter` there runs it again, for fresh results. Saving under a name you have used replaces that search. **File → Remove from List** (`Delete`) with a saved search selected removes it.

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
| `Enter` | Open what the event is about here in GHManage: an issue or pull request in its repository's Issues & PRs, a release in Releases, a commit in Commits, a branch's commits, a discussion in Discussions, a repository at its Issues & PRs. For anything GHManage has no view for (a push's comparison, a wiki page, a person) it says so, and that `Ctrl+O` opens it on GitHub |
| `Ctrl+O` | Open it on GitHub |
| `G` or `Ctrl+Shift+G` | Open the event's repository here in GHManage |
| `Backspace` | From what `Enter` or `G` opened, come back to the same event |
| `F` | Add what the event is about to favorites, or remove it |
| `Ctrl++` | Load older events |
| `R` | Reload the feed |

### Going to an event's repository

`G`, or **Actions → Go to Event's Repository** (`Ctrl+Shift+G`), opens the repository the event happened in, here in GHManage, at its **Issues & PRs**. The repository is selected in the list on the left too, when it is there. `Backspace` from those issues brings you back to the feed, on the event you left, without loading it again. The status bar says "Back to activity".

`G` works from the details panel as well as the list, so you can read an event and go to its repository without moving back. The context menu on an event offers the same, as **Go to owner/name**.

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

Each row shows the repository's name, description, main language, stars, and when it was last pushed to. A repository that is archived, a fork or private says so at the start of its description. The details panel adds its address, forks and open issues. **View → Columns…** can also show the owner.

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

## My Organizations and Shared With Me

**My Organizations**, after My Work in the repository list, lists the organizations you belong to, the ones you are an owner of first and then the rest by name. It is also on **View → View Mode → My Organizations**. Each row reads the organization's name, your role in it (owner or member) and how many of its repositories you can see.

| Key | Action |
|-----|--------|
| `Enter` | List the organization's repositories, most recently pushed first |
| `Backspace` | From those repositories, come back to My Organizations, on the same organization |
| `Ctrl+O` | Open the organization on GitHub |
| `Ctrl+F` | Filter the list |
| `R` | Reload the list |

An organization's repositories work like Starred and Watched: the same columns, details and keys, and `Enter` on one opens it here, with `Backspace` bringing you back to it.

An organization's repositories are kept out of the list of your own, so belonging to a big organization, which may have hundreds or thousands of repositories, doesn't bury yours. To keep one you use often a keystroke away, favorite it with `F`.

**Shared With Me** lists other people's repositories you have been made a collaborator on. It leaves out repositories owned by your organizations, which are already under My Organizations. It is only in the repository list when there is at least one, and works like Starred and Watched.

These keep the repository you were in, so `Ctrl+1` takes you back to it.

---

## Gists

**Gists** lists your gists, public and secret, most recently updated first. Open it from its entry in the repository list, after My Organizations, or from **View → View Mode → Gists**. Like Starred, it isn't about one repository, so it works at any time.

Each row shows the gist's description (or, without one, its first file's name, as GitHub names it), its files, whether it is Public or Secret, and when it was last updated; **View → Columns…** adds its comments and when it was created.

Selecting a gist shows it in the details panel: its description, whether it is public or secret, how many files it has, when it was updated and created, how many comments it has, and its address. A moment after the selection rests on it, its files' text follows, each file headed by its name, language and size, for example "File 2 of 3: notes.md — Markdown, 1.2 KB", then the file a line of the file to a line of the panel. `Alt+N` and `Alt+P` move from file to file. If you are already reading the panel when the files arrive, GHManage says how many there are. A gist too long to show in full (over about 2 MB of text) shows its first files and names the rest.

GitHub sends up to a megabyte of each file. A larger one shows its start and says GitHub sent only the start of it; a very large one, or one that isn't text, says so instead of showing it; and a gist with more files than GitHub lists says that too. In each case `Ctrl+O` opens the gist on GitHub, with all of it.

| Key | Action |
|-----|--------|
| `Enter` | Read it: focus moves into the details panel, at the top; `Backspace` comes back to the row |
| `Ctrl+O` | Open the gist on GitHub |
| `Alt+N` / `Alt+P` | Next / previous file in the details panel |
| `Ctrl++` | Load 100 more |
| `Ctrl+F` | Filter the list |
| `R` | Reload the list |

**Copy Link** (`Ctrl+Shift+C`) copies the gist's address, **Copy Gist ID** (`Ctrl+Shift+I`) its ID, and **Copy Details** (`Ctrl+Shift+D`) everything in the details panel, files and all. Gists are read-only here, and can't be favorites.

---

## Favorites

Favorites gather the things you come back to, from any repository, into one list. Press `F` on almost anything to add it: an issue or pull request, a branch, a commit, a tag, a release, a label, a workflow, a workflow run, a published page, the subject of an Activity event, or a repository, whether in the repository list or in Starred, Watched, Shared With Me, an organization's repositories or search results. Press `F` again to remove it.

The same command is **Actions → Add or Remove Favorite (F)**, and it is on the context menus (the Applications key or `Shift+F10`), where it says which it will do: "Add to Favorites" or "Remove from Favorites". With the repository list focused, it acts on the selected repository.

The status bar confirms each change: "Added to favorites" or "Removed from favorites". A favorited item has a ★ at the start of its row, so you hear it as you arrow past, and pressing `F` puts the ★ on or takes it off straight away.

### The Favorites view

Choose **★ Favorites** at the top of the repository list, or press `Ctrl+9`. The entry in the repository list shows how many favorites you have.

Each row shows the kind of item, its repository, its title and a short description. The details panel adds when you favorited it and its address.

| Key | Action |
|-----|--------|
| `Enter` | Open it here in GHManage, in its own view, on it: a repository at its Issues & PRs, an issue or pull request, a commit, a branch's commits, a tag, a release, a label, a workflow, a run, a discussion, a milestone or a security alert. A file, a published page or a job has no view to land on, and GHManage says so. An issue, pull request, commit or discussion opens into it, as `Enter` on its row would: its text and comments, or a commit's changed files; `Backspace` goes to its row, and again back to where you were. Anything else lands on its row. |
| `Backspace` | From what `Enter` opened, come back to Favorites, on the same row |
| `Ctrl+O` | Open the favorite on GitHub |
| `F` | Remove it from favorites |
| `Ctrl+F` | Filter the list |

A favorite repository is the quickest way back to one you use often, an organization's say: ★ Favorites, then `Enter`.

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
| Copy Diff | `Ctrl+Shift+X` | A pull request's or commit's whole diff, as `gh pr diff` prints it; in Changed Files, the selected file's. See [Changed Files](#changed-files) |
| Copy Path | `Ctrl+Shift+I` | In Files, the file's or folder's path from the top of the repository; in Changed Files, the changed file's. Copy Details copies a file's text |
| Copy HTTPS Clone URL | | The repository's address for `git clone`, such as `https://github.com/nvaccess/nvda.git` |
| Copy SSH Clone URL | | The same over SSH, such as `git@github.com:nvaccess/nvda.git` |

The two clone URLs are for the repository in front of you: the one selected in the repository list when that has focus, the repository of the selected row in a list across repositories, or else the repository open.

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
| Milestones | Copy Milestone Title | the milestone's title |
| GitHub Pages | Copy Commit | the commit the publish was built from |
| Published Pages | Copy Path | the page's path in the repository |
| Favorites | Copy Name | the favorite's title, the same as Copy Title |
| My Work, search results | Copy Number, or Copy Repository Name for repositories | `owner/name#208`, since the list mixes repositories; or `owner/name` |
| Notifications | Copy Number or Repository | the issue or pull request number, or the repository for anything else |
| Activity | Copy Number, Tag or Repository | the issue or pull request number, the release's tag, or the repository for events about a whole repository |
| Starred, Watched, Shared With Me, an organization's repositories | Copy Repository Name | `owner/name` |
| My Organizations | Copy Organization Name | the organization's name |
| Discussions | Copy Number | `#7` |
| Security Alerts | Copy Advisory, Rule or Secret Type | a Dependabot alert's CVE id (its GHSA id when it has no CVE), a code scanning alert's rule id, or a secret's type |

In Activity, Copy Link and Copy Markdown Link copy what the event is about (the issue, pull request or release) rather than the event itself, the same thing `F` favorites.

Artifacts have no page of their own on github.com, so in a run's artifacts Copy Link and Copy Markdown Link are greyed out.

With focus in the repository list, Copy Link, Copy Markdown Link, Copy Title and the fourth item copy that repository: its address, a Markdown link to it, or `owner/name`, whatever the fourth item is called at the time. Copy Details always copies the details panel.

---

## List Mode, Sorting and Columns

### Quick and Full mode

**View → List Mode** decides how much each row says:

- **Quick Mode (compact)** shows just the values: "208  PR  OPEN  Fix the braille cursor". It is the default and the fastest to arrow through.
- **Full Mode (field names for screen reader)** puts each column's name before its value: "208, PR, OPEN, Title: Fix the braille cursor". The first column is never named: it's the row's name, and typing a letter in the list still jumps to the rows starting with it. Columns whose value already says what it is (Type, State, Status and Result) are left without a name too, so you hear "OPEN" rather than "State: OPEN". In Full mode the status bar message also repeats the row as you move to it.

The current mode is shown on the status bar, and the status bar says "Quick mode: compact display" or "Full mode: field names included for screen reader" when you switch. The mode you choose is kept for next time.

### Sort order

**View → Sort Order** sorts **Issues & PRs** by number, title, created date, updated date, either way round, or by most comments. Sorting rearranges what is loaded without asking GitHub again.

### Columns

A screen reader reads a row's columns from left to right, so the order of the columns is the order you hear them. **View → Columns…** lets you decide that order, which columns are shown and whether their names are read, for every kind of list in one place. Each kind of list has its own columns, and its own defaults.

- **List to change** starts on the list you're in. Choose another to change its columns too.
- **Available columns** are the ones not shown. `Enter` or **Add** puts the selected one at the end of the row.
- **Shown columns, in the order they're read** lists what each row says, first to last. `Delete` (or `Backspace`) or **Remove** takes one off; at least one always stays. `Alt+Up` and `Alt+Down` (or **Move Up** and **Move Down**) move the selected column one place, and `Alt+Home` and `Alt+End` (**Move to Top** and **Move to Bottom**) move it to the start or the end; on a Mac, use `Option` for `Alt`. The column stays selected as it moves, and GHManage says where it went in terms of its neighbours, and shows it under the lists: "Author moved above Message", "Author moved to the top". When there is nothing to do, it beeps and says why, for example "Commit is already at the top".
- **Reset to Default** puts back the list's original columns.
- Adding, removing and resetting are said too: "Branches added at the end, 5 of 5", "Author removed, 3 columns shown", "Columns reset to the default". See [Spoken Results](#spoken-results).
- **Speak column names (Full mode)** is the same choice as **View → List Mode**.
- **Preview**, just after the lists, shows how the selected row (or the first row) will read, without the ★ a favorite starts with. For a list other than the one you're in, or when the list is empty, it shows the order the columns will be read in.

**OK** keeps every change, for every list you changed, and leaves you on the row you were on; **Cancel** or `Escape` leaves them all as they were.

| View | Shown by default | Also available |
|------|------------------|----------------|
| Issues & PRs | Number, Type, State, Title | Author, Created, Updated, Labels, Assignees, Comments, Draft, Review, Changes, Files, Base branch, Head branch |
| Branches | Branch, Last commit, Author, Date | Protected, Ahead, Behind |
| Commits | Commit, Message, Author, Date | Branches, Files, Changes |
| Tags | Tag, Commit | |
| Releases | Tag, Name, Date, Downloads | Assets, Draft, Pre-release |
| Release files | Name, Downloads, Size, Date | ID |
| Workflows | Name, State, Path | ID |
| Workflow Runs | Name, Status, Result, Branch, Date | Event, Run |
| A run's jobs | Name, Status, Result, Duration, Failed step | |
| Artifacts | Name, Size, Expired, Date | ID |
| Labels | Label, Description, Color | Default |
| GitHub Pages | Status, Commit, Pushed by, Date, Duration | Kind, Error, ID |
| Published Pages | Page, Address | Size |
| Favorites | Type, Repository, Title, Subtitle | |
| Notifications | Reason, Type, Title, Repository, Updated, Status | |
| My Work | Why, Type, Number, Title, Repository, Updated | Author, Labels |
| Search results: issues and pull requests | Type, Number, State, Title, Repository, Updated | Author, Labels, Comments |
| My Organizations | Organization, Role, Repositories | |
| Activity | Actor, Action, Repository, Title, Date | |
| Changed Files | File, Status, Added, Removed, Comments | |
| Every list of repositories: Starred, Watched, Shared With Me, an organization's, and repository search | Repository, Description, Language, Stars, Pushed | Owner |

The pull-request columns (Changes, Files, Base branch, Head branch) are empty on issues.

GHManage remembers the columns you choose for each kind of list, including after you close it. Every list of repositories shares one choice, since they all show the same columns. At least one column always stays on.

---

## Spoken Results

When you do something whose result isn't obvious from where your focus lands, GHManage tells your screen reader what happened, as well as showing it in the status bar. For now that is the actions in **View → Columns…**; more of GHManage will follow.

On Windows, GHManage sends these as UI Automation notifications, the standard way an app gives a screen reader something to say, so there is nothing to install or set up, and your screen reader speaks them in its own voice and at its own rate. Your screen reader needs to support UI Automation notifications; current versions of the common Windows screen readers do. On a Mac, they are sent as accessibility announcements.

**View → Speak Results** turns this off and on. It is on until you turn it off, and your choice is kept for next time. Turning it off says "Results won't be spoken." so you know it took effect; the status bar, and the Columns dialog itself, still show every result.

---

## The Details Panel and Comment Navigation

The details panel shows everything about the item you are on in the list, and changes as you move. It is ordinary read-only text, so your screen reader's reading keys work in it: arrow line by line, read by word, select and copy.

Web addresses always have a line of their own, under a line reading "URL:", so you can arrow to one and read or copy it on its own.

The panel describes the item and nothing else: it doesn't list keys. The keys for the item are on the **Actions** menu and the context menu, with each key in its label, and the status bar's key hints name the main ones for the view. The keys that act on the item work from the details panel as well as from the list: `Enter` in the details panel does what it does in the list, except where `Enter` is what brought you into the panel to read. `Backspace` in the details panel goes back to the item's row in the list.

### Moving between comments

An issue or pull request's comments come after its description, each beginning with a heading such as "Comment 2 of 5 — alice (2026-10-01):".

| Key | Action |
|-----|--------|
| `Alt+N` | Next comment |
| `Alt+P` | Previous comment |

On a Mac, use `Option+N` and `Option+P`. Both are also on the **File** menu as **Next Comment** and **Previous Comment**.

Each press moves focus to the details panel and selects the whole comment, from its heading to its last line, so your screen reader reads it and you can copy it. A comment over about 500 characters selects only its first line, the heading that says whose it is: NVDA reads a longer selection only as "592 characters selected". `Down Arrow` reads on, and `Shift+Down Arrow` selects more to copy. The status bar says "Comment 2 of 5". At either end it says "Already at last comment." or "Already at first comment.", and an item with none says "No comments to navigate."

---

## The Actions Menu

Everything that acts on what the list is showing is on the **Actions** menu, whichever view it belongs to. Its items are relabelled for the view you are in and greyed out where they do not apply, so the menu answers "what can I do here?" without trial and error.

| Item | Key | Works in |
|------|-----|----------|
| What `Enter` does, named for the view: **Read (Enter)**, **Show Commits (Enter)**, **Download… (Enter)** | `Enter` in the list | Every view, with an item selected |
| Open on GitHub | `Ctrl+O` | Every view; **Open Its Release on GitHub** on a release's file, **Open Its Commit on GitHub** in GitHub Pages, **Open on the Web** on a published page; greyed out in Artifacts |
| Copy → Link, Markdown Link, Title, Number, Details | `Ctrl+Shift+C`, `L`, `T`, `I`, `D` | Every view; see [Copying](#copying) |
| Close Issue/PR | `Ctrl+W` | Issues & PRs |
| Reopen Issue/PR | `Ctrl+Shift+W` | Issues & PRs |
| Add Comment… | `Ctrl+M`, or `M` in the list | Issues & PRs; Discussions |
| New Issue… | `Ctrl+N` | Everywhere, for the repository in front of you; shows the new issue in its Issues & PRs |
| Search This Repository… | `Ctrl+Shift+S` | Everywhere, for the repository in front of you: a search starting `repo:owner/name` |
| Read README | `Ctrl+Shift+R` | Everywhere, for the repository in front of you: its README, in Files |
| Pull Request → Checks, Review…, Merge…, Ready for Review or Back to Draft, Request Reviewers…, Update Branch… | `K`, `V`, `D` in the list | Issues & PRs, on a pull request |
| Watch Settings… | `Ctrl+Shift+U` | Everywhere, for the repository in front of you |
| Save Search… | `Ctrl+S` | Search results |
| New Label… (Insert) | `Ctrl+I`, or `Insert` in Labels | Any view of a repository; switches to Labels to show the new one |
| Delete | `Ctrl+D`, or `Delete` in the list | Labels (reads **Delete Label… (Delete)**), Workflow Runs (reads **Delete Workflow Run… (Delete)**) and Notifications (reads **Mark as Done (Delete)**) |
| Open Published Site | | GitHub Pages, once a site is found |
| Select Branch… | `Ctrl+B` | Commits; in Files it reads **Select Branch or Tag…** |
| Compare Branches… | `Ctrl+Shift+B` | Branches |
| Changed Files | `Ctrl+Shift+H`, or `H` in the list | Issues & PRs, on a pull request; Commits; File History |
| Open Diff in Default App | `Ctrl+Shift+E` | Issues & PRs, on a pull request; Commits; Changed Files; File History |
| File History | `H` in the list | Files, on a file |
| Blame | `B` in the list | Files, on a file |
| Open Whole File | `W` in the list | Changed Files |
| Comment on This Line… | `M` in the file's lines | Changed Files, for a pull request |
| Go to Event's Repository | `Ctrl+Shift+G` | Activity, and Notifications where it reads **Go to Notification's Repository** |
| Mark as Read, Unsubscribe from Thread | `M`, `U` in the list | Notifications |
| Mark All as Read… | | Notifications |

On a Mac, use `Cmd` for `Ctrl`.

`Ctrl+D` follows the same rule as the menu item, and so does the bare `Delete` key, which also works from the details panel. In other views neither does anything. `Delete` never acts from the repository list. `Insert` and `Delete` act only on their own: `Ctrl+Insert`, `Shift+Insert`, `Shift+Delete` and `Ctrl+Delete` are left to copy, paste and cut.

The **File** menu has **Back (Backspace)**, named for where it goes, and **Clear Quick Filter (Escape)**; the **View** menu has **Next Pane (F6)** and **Previous Pane (Shift+F6)**. Each is greyed out where its key does nothing.

### Context menus

The **Applications** key, `Shift+F10`, or a right-click opens a context menu (on a Mac, `VO+Shift+M` with VoiceOver, or `Ctrl`-click).

In the item list it starts with what `Enter` does in that view, for example **Show Commits (Enter)** on a branch or **Open Here (Enter)** on a search result, as the Actions menu does, and then offers everything the Actions menu offers in that view, with Copy and Pull Request as submenus. It is built from the Actions menu each time, so the two always agree. It ends with **View More** (`Ctrl++`) in every list that loads in pages. On a repository in Starred, Watched, Shared With Me, an organization's repositories or repository search results, it also has **Go To** (see below), and `Backspace` from where it takes you comes back to that row.

In the repository list, a repository's menu has **Open**, **Open on GitHub** (`Ctrl+O`), **Go To**, **New Issue…**, **Search This Repository…** (a search starting `repo:owner/name`), **Read README**, **Watch Settings…**, **Add to Favorites** or **Remove from Favorites**, Copy, and **Remove from List**. **Go To** opens the repository straight on one of its views: Issues & PRs, Branches, Commits, Tags, Releases, Workflows, Workflow Runs, Labels, GitHub Pages, Files, Security Alerts, Discussions, Milestones or Insights. Copy includes **Copy HTTPS Clone URL** and **Copy SSH Clone URL**, the addresses `git clone` takes. These are the same commands as on the Actions menu, for the repository selected. A saved search's menu has **Run Search** and **Remove Saved Search**; Favorites and the other entries at the top have **Open**.

---

## Keyboard Shortcuts

On a Mac, use `Cmd` in place of `Ctrl` for every shortcut that has one, `Option` in place of `Alt`, and `fn` with the function keys (`fn+F1`, `fn+F6`) unless your function keys are set to work as standard keys. Single-letter keys, `Enter`, `Backspace` and `Escape` are the same. The Mac's delete key is `Backspace`; for `Delete` use `fn+delete`, or `Cmd+D`.

### Anywhere in the window

| Key | Action |
|-----|--------|
| `F6` / `Shift+F6` | Next / previous pane: repository list, item list, details panel, status bar |
| `Tab` / `Shift+Tab` | Move between the repository list, item list and details panel |
| `F1` | Open this guide in your browser |
| `Ctrl+F1` | Keyboard shortcuts: this list, in GHManage |
| `Ctrl+Shift+P` | Command palette: find a command and run it |
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
| `Ctrl+Shift+R` | Read the README of the repository in front of you |
| `Ctrl+O` | Open the selected item on GitHub; in the repository list, the repository |
| `Ctrl+Shift+C` | Copy the selected item's link |
| `Ctrl+Shift+L` | Copy a Markdown link to it |
| `Ctrl+Shift+T` / `Ctrl+Shift+I` / `Ctrl+Shift+D` | Copy its title / number, SHA or name / details |
| `Ctrl+Shift+O` | Open a repository, or an issue, pull request, commit, release or run, by its address |
| `Alt+N` / `Alt+P` | Next / previous comment in the details panel; change in File History, and change or review comment in Changed Files; Markdown heading, or blame run, in Files; file in Gists |
| `Ctrl+Shift+H` | The changed files of the selected pull request or commit |
| `Ctrl+Shift+X` | Copy the pull request's or commit's diff (in Changed Files, the file's) |
| `Ctrl+Shift+E` | Open that diff in your default app for `.diff` files |
| `Ctrl+Shift+U` | Watch settings for the repository |
| `Ctrl+Shift+K` | Switch GitHub account |
| Applications key or `Shift+F10` | Context menu for the selected item or repository |
| `Ctrl+Q` | Quit |

### In the item list

| Key | Action |
|-----|--------|
| `Enter` | Go in: a deeper list, the item in the details panel, or an action here; never the browser. The Actions menu's first item names it |
| `Backspace` | Back to the list you came from (**File → Back**) |
| `F` | Add to favorites, or remove |
| `R` | Refresh |
| `Escape` | Clear the quick filter (**File → Clear Quick Filter**) |

### In the details panel

| Key | Action |
|-----|--------|
| `Backspace` | Back to the item's row in the list |
| `Enter` | What `Enter` does in the list, where that isn't reading what you are already reading |

### In Issues & PRs

| Key | Action |
|-----|--------|
| `Enter` | Read it, in the details panel |
| `Ctrl+O` | Open it on GitHub |
| `C` or `Ctrl+W` | Close |
| `O` or `Ctrl+Shift+W` | Reopen |
| `M` or `Ctrl+M` | Add a comment |
| `N` or `Ctrl+N` | New issue |
| `K` / `V` / `D` | On a pull request: checks / review / ready or draft |
| `H` | On a pull request: its changed files |
| `Backspace` | Back to the labels, Notifications, My Work, search results, the Activity feed, or the Starred or Watched list, when you came from one |

### In Branches and Commits

| Key | Action |
|-----|--------|
| `Enter` on a branch | Show its commits |
| `Enter` on a commit | Show its changed files |
| `Ctrl+Shift+B` | Compare two branches (Branches view) |
| `Ctrl+B` | Choose the branch (Commits view) |
| `H` | The selected commit's changed files, as `Enter` does |
| `Backspace` | Commits back to branches |

### In Changed Files

| Key | Action |
|-----|--------|
| `Enter` | Into the file's changed lines |
| `Alt+N` / `Alt+P` | Next / previous change or review comment in the details panel |
| `M` | In a pull request's file's lines: comment on the line the caret is on |
| `Backspace` | Back to the pull request or commit |
| `W` | Open the file whole, in Files |

### In Files

| Key | Action |
|-----|--------|
| `Enter` | Into a folder; into a file's text |
| `Backspace` | Up a folder, onto the one you were in; at the top, back to Tags when `Enter` on a tag opened it, or to Changed Files when `W` did |
| `H` | The file's history |
| `B` | Blame: who last changed each line; `B` again shows the file |
| `Alt+N` / `Alt+P` | Next / previous Markdown heading, or blame run |
| `Ctrl+B` | Choose the branch or tag |
| `Ctrl+O` | Open the file or folder on GitHub |

### In File History

| Key | Action |
|-----|--------|
| `Enter` or `H` | The commit's changed files |
| `Alt+N` / `Alt+P` | Next / previous change to the file in the details panel |
| `Backspace` | Back to the file in Files |

### In Tags and Releases

| Key | Action |
|-----|--------|
| `Enter` on a tag | Its files, in Files at that tag |
| `Enter` on a release | List its files and their download counts |
| `Enter` on a file | Download it into a folder you choose |
| `Ctrl+O` on a file | Open its release on GitHub |
| `Backspace` | Files back to releases; from Files at a tag, back to Tags |

### In Workflows and Workflow Runs

| Key | Action |
|-----|--------|
| `Enter` on a workflow | Run it on a branch |
| `Enter` on a run | List its artifacts |
| `J` | The run's jobs, in Workflow Runs; `Enter` on a job reads its log |
| `L` | What failed |
| `E` / `X` | Rerun / cancel |
| `Ctrl+D` or `Delete` | Delete the run |
| `Enter` on an artifact | Download it into a folder you choose |
| `Backspace` | Artifacts or jobs back to runs |

### In Gists

| Key | Action |
|-----|--------|
| `Enter` | Read it, in the details panel |
| `Ctrl+O` | Open it on GitHub |
| `Alt+N` / `Alt+P` | Next / previous file, in the details panel |

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

### In Milestones

| Key | Action |
|-----|--------|
| `Enter` | List the milestone's issues and pull requests |
| `Backspace` | From those, back to the milestones |

### In Insights

| Key | Action |
|-----|--------|
| `Enter` | Read the row, in the details panel |
| `Ctrl+O` | Open the row on GitHub: the traffic page, the popular page, or the contributor's profile |
| `R` | Read the figures again |

### In GitHub Pages

| Key | Action |
|-----|--------|
| `Enter` in the publish history | List the pages the site serves |
| `Ctrl+O` in the publish history | Open the publish's commit on GitHub |
| `Enter` on a page | Read it, in the details panel |
| `Ctrl+O` on a page | Open it on the web |
| `S` | Open the site's home page |
| `Backspace` | Pages back to the publish history |

### In Security Alerts

| Key | Action |
|-----|--------|
| `Enter` | Read the alert, in the details panel |
| `Ctrl+O` | Open the alert on GitHub |
| `R` | Read the alerts again |

### In Discussions

| Key | Action |
|-----|--------|
| `Enter` | Read the discussion, in the details panel |
| `Ctrl+O` | Open the discussion on GitHub |
| `M` | Add a comment |
| `Alt+N` / `Alt+P` | Next or previous comment or reply in the details panel |
| `R` | Read the discussions again |

### In Notifications

| Key | Action |
|-----|--------|
| `Enter` | Open it here, in its own view; or say GHManage has no view for it |
| `Ctrl+O` | Open it on GitHub |
| `M` | Mark read |
| `Delete` or `Ctrl+D` | Mark done |
| `U` | Unsubscribe from the thread |
| `I` | Include read notifications, or not |
| `G` or `Ctrl+Shift+G` | Open its repository in GHManage |

### In Activity

| Key | Action |
|-----|--------|
| `Enter` | Open what the event is about here; or say GHManage has no view for it |
| `Ctrl+O` | Open it on GitHub |
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
| `Enter` | Open it here, in its own view; or say GHManage has no view for it |
| `Ctrl+O` | Open it on GitHub |
| `F` | Remove from favorites |

### In the repository list

| Key | Action |
|-----|--------|
| `Enter` | Open the selected entry |
| `Ctrl+O` | Open the selected repository on GitHub |
| `F` | Add the selected repository to favorites, or remove it |
| `Delete` | Remove the selected repository or saved search from the list |

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

Found a bug, or have an idea? **Help → Report a Bug…** sends it from inside GHManage, and you don't need a GitHub account. It is filed as an issue at [github.com/TheIdeaPlace/GHManage/issues](https://github.com/TheIdeaPlace/GHManage/issues) by The Idea Place's bug-report bot. Everything in it is public.

### The form

- **Kind**: Bug or Suggestion. The boxes below change to match.
- **Title**, required.
- For a bug, **What happened** (required), **What you expected** and **Steps to reproduce**. For a suggestion, **Your suggestion** (required) and **How it would help**. Say what you did key by key if you can, and what your screen reader and the status bar said.
- **Contact**, optional: an email address or GitHub name, if you would like a reply. It is public like the rest.
- **Include system information**, checked to start with. See below for exactly what it adds.
- **Preview**: exactly what will be sent, kept up to date as you type. It is a read-only box you can Tab to and read; nothing is spoken while you type.

`Send` (or `Ctrl+Enter` from anywhere in the form, `Cmd+Enter` on a Mac) files it. If the title or the first box is empty, the form says which, and puts you in it.

When the report is filed, the form says "Report sent as issue #" and the number, shows its address, and you are on **Open Issue**, which opens it on GitHub. If it can't be sent (no internet, or the service didn't answer), the whole report is put on the clipboard, the form says so, and you are on **Open GitHub's New Issue Page**. That opens the page with the report filled in, to file under your own GitHub account; a very long report is cut short there, and the rest is on the clipboard to paste. A copy of GHManage built from source sends nothing and always offers the page.

Closing the form with `Escape` or **Cancel** asks first if you have typed anything. While a report is sending, **Cancel** says "Still sending…" and waits.

### What a report says about your computer

With **Include system information** checked, and nothing more:

- GHManage's version, and whether it is installed, portable or run from source.
- Windows or macOS, and its version.
- The processor type.
- The screen reader running, if GHManage can tell: NVDA, JAWS, Narrator, ZoomText, Fusion or Dolphin on Windows, VoiceOver on a Mac.
- Your language setting.
- The version of `gh`.

Never your GitHub account, your repositories, your files, or anything from your settings.

### After something goes wrong

GHManage keeps a log of anything that goes wrong: `%APPDATA%\ghmanage\logs\ghmanage.log` on Windows and `~/Library/Logs/GHManage/ghmanage.log` on the Mac. **Help → Open Log Folder** opens its folder. It never grows past half a megabyte, and the three before it are kept. Nothing reads it but you and a report you choose to send.

If GHManage quit unexpectedly last time, it asks once when it next starts, "GHManage quit unexpectedly last time. Report it?" **Report** opens the form with the title "Quit unexpectedly" and the end of that run checked to include: the last 40 lines of the log, and, if GHManage crashed rather than being closed, what it was doing when it crashed (`crash.txt`, beside the log). Your home folder is written as `~`, and all of it is shown in the preview. Uncheck it to leave them out. If something went wrong in this session without GHManage closing, the form offers **Include the error** the same way.

### Other ways

You can also open an issue yourself at [github.com/TheIdeaPlace/GHManage/issues](https://github.com/TheIdeaPlace/GHManage/issues), or from GHManage: open the repository with `Ctrl+Shift+O` and `TheIdeaPlace/GHManage`, and create one from Issues. For a problem with updating, attach the update log described in [Where your settings live](#where-your-settings-live).