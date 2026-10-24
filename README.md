# ghmanage

A **wxPython GUI** for viewing and managing GitHub issues, pull requests, and git metadata.

Built with [wxPython](https://www.wxpython.org/) and the [GitHub CLI (`gh`)](https://cli.github.com/).

**The full user guide is at <https://theideaplace.github.io/GHManage/>**, and Help ▸
User Guide (`F1`) opens it from the app. This README is a summary.

## Features

- **Repo chooser** — list shows your GitHub repositories; arrow through and press Enter to load.
  Above them sit **★ Favorites**, **Activity**, **Starred Repositories**, **Watched Repositories**,
  **Notifications**, **My Work** and your saved searches, the counted ones with how many they hold,
  e.g. "Notifications (12 unread)"
- **Notifications** — your GitHub inbox: why you were told, what it is, mark read, mark done,
  unsubscribe; Enter opens an issue or PR right here, and Backspace comes back
- **Search GitHub** — Ctrl+Shift+F searches issues and PRs, or repositories, across all of GitHub
  with GitHub's own qualifiers (`is:open label:bug author:@me …`); save a search and it sits in the
  repo list, one Enter away
- **My Work** — open issues and PRs that need you, everywhere: review requests, assigned, your
  own, mentions
- **Open any GitHub address** — paste a link to an issue, PR, commit, release, workflow run or
  branch into Ctrl+Shift+O and it opens in its own view with that item selected
- **New issue** — Ctrl+N, a title and a Markdown description
- **Pull requests** — checks (K), review (V), draft/ready (D), merge, request reviewers, update branch
- **Copy** — the link, a Markdown link, the title, the number/SHA/tag, or the details, for anything
- **Watch settings and account switching** — Participating, All Activity or Ignore for a
  repository; switch between the github.com accounts gh is signed in to
- **Activity** — your GitHub feed: what happens in the repositories you star or watch and
  what the people you follow do, newest first, across every repository
- **Issues & PRs view** — issues and PRs in one list, like an email inbox
- **Git views** — browse branches, commits, tags, releases, workflows (run them on a branch), and workflow runs (drill into a run's artifacts and download them)
- **GitHub Pages** — if a repo publishes a site, see every publish and whether it worked, then browse the pages it serves and open any of them in your browser
- **Release download counts** — the Releases view shows how many times each release was downloaded, with a repo total in the status bar; press Enter on a release for a per-file breakdown
- **Labels view** — browse the repo's labels, press Enter on one to list the issues and PRs carrying it, and create or delete labels with Ctrl+I / Ctrl+D (or Insert / Delete)
- **Branch-specific commits** — press Enter on a branch to see its commits, or press Ctrl+B in Commits view to pick a branch
- **Details panel** — full body, metadata, comments, file changes, and release notes shown below the list
- **Comment navigation** — press Alt+N/Alt+P in the details box to jump between comments
- **View More** — press Ctrl++ to load more items (100 at a time)
- **View menu** with:
  - **View Mode** — switch between Issues & PRs, Branches, Commits, Tags, Releases, Workflows, Workflow Runs, Labels, GitHub Pages, Notifications, Activity, Starred Repositories and Watched Repositories
  - **Quick / Full list mode** — Quick shows compact rows; Full includes field names (e.g. "208, PR, OPEN, Title: …") for screen readers
  - **Sort order** — by number, title, created date, updated date, or comments
  - **Column selection** — toggle columns on/off (columns change per view mode)
  - **State filter** — open, closed, or all (issues/PRs view)
  - **Show filter** — issues only, PRs only, or both (issues/PRs view)
- **Actions menu** — one home for everything that acts on what the list is
  showing: close, reopen, comment, new issue, copy, watch settings, create and
  delete labels, delete a workflow run, run a workflow, download an artifact,
  mark notifications read or done, open in browser. Each item names
  what it would act on in the current view and is greyed out where it does not
  apply, so the menu answers "what can I do here?" without trial and error

## Prerequisites

- Python 3.9+
- The `gh` CLI installed and authenticated (`gh auth login`)
- wxPython

## Install

### Windows

Download **GHManage-win-Setup.exe** from the
[latest release](https://github.com/TheIdeaPlace/GHManage/releases) and run it. It
installs per-user, with no administrator prompt, and keeps itself up to date:
new versions download in the background and install the next time you start
GHManage. Help ▸ Check for Updates checks on demand.

**GHManage-win-Portable.zip** is also published for anyone who would rather not
install. It does not update itself.

Releases are code-signed. See [docs/INSTALLER.md](docs/INSTALLER.md) for how.

### macOS

Apple Silicon (M1 or later), macOS 11 Big Sur or newer.

Download **GHManage-osx.dmg** from the
[latest release](https://github.com/TheIdeaPlace/GHManage/releases), open it, and
drag GHManage to Applications. **GHManage-osx-Portable.zip** contains the same
app if you prefer to unzip it yourself.

Both update themselves — a macOS app bundle carries its own updater, so it
keeps working wherever you put it. New versions download in the background and
install the next time you start GHManage; Help ▸ Check for Updates checks on
demand.

Install and sign in to the GitHub CLI first:

```bash
brew install gh
```

then `gh auth login`. GHManage looks for `gh` in the usual Homebrew and MacPorts
locations, because an app launched from Finder does not inherit the PATH from
your shell profile. If you keep it somewhere else, set `GHMANAGE_GH_PATH` to its
full path.

There is no Intel build. wxPython and Velopack both publish per-architecture
wheels with no universal2 build, so an Intel release would be a separate build
rather than a fat binary.

### From source

```bash
pip install -r requirements.txt
```

Or install as a package:

```bash
pip install .
```

## Run

```bash
python ghviewer.py
```

Or for a specific repository (skips the repo chooser):

```bash
python ghviewer.py --repo owner/repo-name
```

## Keybindings

### Global

| Key | Action |
|-----|--------|
| `R` or `Ctrl+R` | Refresh the list (resets to first page) |
| `Ctrl++` | View More — load the next page of items |
| `Ctrl+O` | Open the selected item on GitHub in your browser |
| `Ctrl+Shift+O` | Open a repository, or an issue, PR, commit, release, run or branch, by its address |
| `Ctrl+Shift+C` / `Ctrl+Shift+L` | Copy the selected item's link / a Markdown link to it |
| `Ctrl+Shift+T` / `Ctrl+Shift+I` / `Ctrl+Shift+D` | Copy its title / number, SHA or name / details |
| `Ctrl+N` | New issue — in the open repository, or the one selected in the repo list or the current list |
| `Ctrl+Shift+S` | Search the repository in front of you |
| `Ctrl+Shift+F` | Search GitHub; `Ctrl+S` in the results saves the search |
| `Ctrl+Shift+U` | Watch settings for the repository |
| `Ctrl+Shift+K` | Switch GitHub account |
| `Ctrl+G` | Go to a specific issue/PR by number (issues view only) |
| `Ctrl+B` | Select a branch for the Commits view (commits view only) |
| `Ctrl+I` | Create — a new label (Labels view) |
| `Ctrl+D` | Delete — the selected label or workflow run; mark a notification done |
| `Ctrl+1` … `Ctrl+0` | Switch view — see below |
| `Alt+N` | Jump to the next comment in the details box |
| `Alt+P` | Jump to the previous comment in the details box |
| `Tab` | Move focus between the repo list, item list, and details panel |
| `F6` / `Shift+F6` | Move focus to the next / previous pane: repo list, item list, details panel, status bar |
| `F1` | Open the user guide in your browser |
| `Ctrl+Q` | Quit |

### In the status bar

`F6` stops on the status bar as well as the three panes. The bar is split into
items — the latest message, the keys that work in the current view, the filter
when one is set, the list mode, and a found update — and `Left` / `Right` move
from one to the next, wrapping at either end. Items with nothing to say are not
on the bar. Press `Enter` or `Space` on the update item to install the update
and restart.

### Switching views

Once a repository is loaded, `Ctrl+<number>` jumps straight to a view — the
numbers follow the order of the View ▸ View Mode menu, so you can read them off
the menu. They work from anywhere in the window (repo list, item list, or
details panel).

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

Every view except Favorites, Activity, Starred and Watched Repositories, Shared With Me,
an organization's repositories, Notifications, My Work and search results needs a
repository, so with none selected
the status bar says "Select a repository first" and the view is left alone. Those don't change
the repository you are in, so `Ctrl+1` takes you back to it.

### Starred and watched repositories

The repository list starts with seven entries that aren't single repositories:
**★ Favorites**, **Activity**, **Starred Repositories**, **Watched Repositories**,
**Notifications**, **My Work** and **My Organizations** (Enter on an organization
lists its repositories). After them come **Shared With Me** (other people's
repositories you collaborate on, when there are any), your saved searches, any
repositories you opened by address, then your own repositories. Starred and Watched are also on View ▸ View Mode.

- **Starred Repositories** — the repositories you have starred, most recently
  starred first.
- **Watched Repositories** — the repositories you are watching. GitHub watches
  your own repositories for you, so they are in this list as well.

Each row reads repository, description, language, stars and when it was last
pushed; an archived repository or a fork says so at the start of its
description. The details panel adds forks and open issues.

| Key | Action |
|-----|--------|
| `Enter` | Open the repository here in GHManage; `Backspace` from its issues comes back to the same row |
| `Ctrl+O` | Open the repository on GitHub |
| `F` | Favorite the repository |
| `Ctrl++` | Load 100 more |

### In the Notifications view

| Key | Action |
|-----|--------|
| `Enter` (or double-click) | Open an issue or PR here in GHManage (`Backspace` comes back); anything else on GitHub. Marks it read |
| `M` | Mark read |
| `Delete` or `Ctrl+D` | Mark done |
| `U` | Unsubscribe from the thread |
| `I` | Include read notifications, or not |
| `G` or `Ctrl+Shift+G` | Open its repository here |
| `Ctrl++` | Load more |

Choose **Notifications** in the repository list, press
`Ctrl+Shift+N`, or use View ▸ View Mode ▸ Notifications. Each row reads why
GitHub told you, what it is, its title, the repository, when it changed, and
whether it is read. **Actions ▸ Mark All as Read** asks first.

### In the Activity view

| Key | Action |
|-----|--------|
| `Enter` (or double-click) | Open what the event is about here in GHManage (an issue, pull request, release or commit), with `Backspace` back to the event; anything else on GitHub |
| `G` or `Ctrl+Shift+G` | Open the event's repository here in GHManage; `Backspace` there brings you back to the same event |
| `F` | Favorite what the event is about: its issue, pull request, release or discussion |
| `Ctrl++` | Load older events |

Choose **Activity** at the top of the repository list, press `Ctrl+Shift+A`, or
use View ▸ View Mode ▸ Activity. The repository you were in stays selected, so
`Ctrl+1` takes you straight back to it. It is the feed github.com shows on your
dashboard: pushes, pull requests, issues, comments, reviews, releases, stars
and forks in the repositories you star or watch, and by the people you follow.
Each row reads who, what, which repository, what it was about, and when (in
your local time), for example "alice, merged pull request #42,
nvaccess/nvda, Fix the braille cursor, 2026-10-05 14:32". The details panel
gives the whole event as one sentence, then the comment, review or description
text when there is one.

GitHub keeps only the latest 300 events from the last 90 days. The first 100 are
loaded, `Ctrl++` loads the next 100 and puts you on the first of them, and the
status bar says when there are no more. The quick filter (`Ctrl+F`) works here
like in every other view.

`F` favorites the issue, pull request, release or discussion an event is about,
the same favorite you would make from that item's own view. Events about a
push, a branch or the repository as a whole have nothing of their own to keep,
and the status bar says so. `G` and Actions ▸ Go to Event's Repository work
from the details panel as well as the list.

### In the issue/PR list only

| Key | Action |
|-----|--------|
| `Enter` (or double-click) | Open the selected item on GitHub in your browser |
| `C` | Close the selected issue/PR |
| `O` | Reopen the selected issue/PR |
| `M` or `Ctrl+M` | Add a comment to the selected item |
| `N` or `Ctrl+N` | New issue |
| `K` | Checks on the selected pull request |
| `V` | Review it: approve, request changes, comment |
| `D` | Draft ⇄ ready for review |
| `Backspace` | Return to the labels list (only when the list is restricted to a label) |

### In the branches view

| Key | Action |
|-----|--------|
| `Enter` | Switch to Commits view for the selected branch |

### In the commits view

| Key | Action |
|-----|--------|
| `Backspace` | Return to the branches list |

### In the releases view

| Key | Action |
|-----|--------|
| `Enter` | Drill into the selected release's assets and their download counts |

The **downloads** column totals every file attached to a release, and the status
bar totals every release currently loaded — press `Ctrl++` to load more and the
total grows with them. The details panel breaks a release down file by file,
most-downloaded first.

From a release's **Assets** list, `Enter` downloads the selected file in your
browser and `Backspace` returns to the releases.

A download count is a **lifetime running total** kept by GitHub. It is not
broken down by date, and no API offers that — to see downloads over time you
have to record the numbers and compare them later. Counts include automated
traffic, so a sharp spike on one release is worth reading with suspicion.

### In the workflows view

| Key | Action |
|-----|--------|
| `Enter` (or right-click → Run on branch…) | Run the selected workflow on a branch you pick |

Manual runs only work when the workflow declares an `on: workflow_dispatch`
trigger; if it doesn't, the app tells you so instead of triggering anything.
After a run starts, switch to **Workflow Runs** and refresh to watch it.

### In the workflow runs view

| Key | Action |
|-----|--------|
| `Enter` | Drill into the selected run's artifacts (shown in the same list) |
| `Ctrl+D` or `Delete` | Delete the selected run (asks first) |
| `J` | List the run's jobs and steps; `Enter` on a job reads its log, opening at the first error |
| `L` | Show what failed: GitHub's errors and the end of each failed step's log |
| `E` | Rerun: all jobs, or only the failed ones |
| `X` | Cancel a queued or running run |

From a run's **Artifacts** list, press `Enter` (or right-click → Download…) on an
artifact to download it into a folder you choose, and `Backspace` to return to the
runs list. Expired artifacts can't be downloaded and are marked as such.

### In the labels view

| Key | Action |
|-----|--------|
| `Enter` | List the issues and PRs carrying the selected label |
| `Ctrl+I` or `Insert` | Create a label |
| `Ctrl+D` or `Delete` | Delete the selected label (asks first) |

These keys work from the labels list *and* from the details panel below it, so
you can read what a label is and act on it without moving focus back. Right-click
offers the same three actions, and so does the **Actions** menu — where the
Delete entry names the label it would delete.

`Enter` reloads the **Issues & PRs** view restricted to that label, so the state
filter, columns, sorting, and every issue action still work there — the window
title and status bar name the label, and `Backspace` returns to the labels list.
The restriction is applied by `gh`, not by the quick filter, so it finds items
that were never on the current page. `Ctrl+1` clears it and shows everything again.

A new label needs a name; the description and colour are optional, and GitHub
picks a colour when the field is left blank. **Deleting a label strips it from
every issue and pull request that carries it, and GitHub offers no undo**, so the
app confirms first.

On a fork, labels come from the same upstream repo the issues do.

### In the GitHub Pages view

| Key | Action |
|-----|--------|
| `Enter` | Browse the pages the site serves |
| `S` | Open the site itself in your browser |

`Ctrl+0` shows the publish history of a repository's Pages site — one row per
publish, with whether it succeeded, the commit it came from, who pushed it, and
how long it took. The status bar carries the site's address, its state, and the
branch and folder it publishes from; the details panel adds the rest of the
configuration, including any custom domain.

If the repository has no site, the app says so plainly rather than showing you an
empty list.

From there, `Enter` opens the site's **Published Pages** — every file the site
serves, each with the address it is served at. `Enter` on one opens it in your
default browser, `S` opens the site's home page, and `Backspace` returns to the
publish history. The **Actions** menu carries Open Published Site too, enabled
once a site is found. `F` favorites a page like anything else, so a page you
check often is one keystroke away from any repository.

Two things are worth knowing about that list, and the details panel says so on
the pages it applies to:

- **Jekyll sites serve Markdown as HTML.** A file stored as `guide/setup.md` is
  served at `guide/setup.html`. The listed address is the one that works. A site
  with a `.nojekyll` file skips this and is served exactly as committed.
- **A site built by Actions is listed from its source, not its output.** GitHub
  publishes those through a workflow, and the workflow decides what actually
  ships — possibly a subset of these files, possibly something it generated that
  is not in the repository at all. For sites GitHub builds itself, the list is
  what is served.

The publish history has the same split. Sites GitHub builds report a full build
log with durations and error messages; sites built by Actions have no build log
at all, so their history is read from their deployments instead, which record a
state but not a duration.

### Actions menu

Everything that acts on what the list is showing lives in one menu, whichever
view it belongs to: open in browser, close/reopen/comment on an issue, create
and delete labels, delete a workflow run, run a workflow, download an artifact,
open a published Pages site, pick or compare branches.

Items are re-labelled and enabled for the current view, so **Delete** reads
"Delete Label…" in the Labels view and "Delete Workflow Run…" in Workflow Runs,
and is greyed out where nothing can be deleted. `Ctrl+D` follows the same rule;
so does the bare `Delete` key, which additionally works from the details panel.

### View menu → View Mode

Switch between **Issues & PRs**, **Branches**, **Commits**, **Tags**, **Releases**
(with download counts), **Workflows** (the workflow definitions, which you can run
on a branch), **Workflow Runs** (recent run history), **Labels**,
**GitHub Pages** (a published site and the pages it serves), **Notifications**
(your GitHub inbox) and **Activity** (your GitHub feed, across all repositories).
Each view has its own set of columns and detail formatting.

## Building

```bash
build.bat
```

Builds the app folder into `dist\ghmanage\`. Add `clean` to wipe artifacts first.

```bash
build.bat installer
```

Also packs the Velopack installer and update feed into `installer\Releases\`.
That step needs `vpk`, a .NET global tool: `dotnet tool install -g vpk`.

The build is `--onedir`, not `--onefile`, and that is not optional — see
[docs/INSTALLER.md](docs/INSTALLER.md) for why, along with the update flow, how to
test an upgrade locally, and the code-signing setup.

Tests run with `python -m pytest` (install it with `pip install pytest`). They
fake the `gh` CLI, so they need no network and no sign-in.

`assets\` holds the icon stamped into the app, the Start menu shortcut, and
Setup.exe, plus the two scripts that generate it and the exe's version resource.
`make_icon.py` only needs re-running if the artwork changes.