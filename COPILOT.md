# GHManage — Project Knowledge

> This file is the authoritative reference for anyone (human or AI) working on this project.
> Keep it updated whenever the architecture, conventions, or features change.

## What This Project Is

**GHManage** (package name `ghviewer`) is a **wxPython desktop GUI** for viewing and managing
GitHub issues, pull requests, and git metadata — branches, commits, tags, releases,
and CI workflow runs. It is designed specifically to be **screen-reader-friendly** without being
patronizing: keyboard-first navigation, a "Full mode" that includes field names in list rows,
status-bar announcements, and comment navigation via Alt+N/Alt+P.

The app shells out to the **`gh` CLI** for all GitHub operations (issues, PRs, repos) and uses
the **GitHub REST API** (via `gh api`) for git metadata that `gh` doesn't have first-class commands
for (branches, commits, tags, compare, workflow runs).

## Architecture

```
ghviewer.py   — UI layer (wxPython). All event handlers, menus, dialogs, list population.
gh_data.py    — Data layer. All `gh` CLI and `gh api` calls, data classes, parsing.
diffview.py   — A changed file as text to read (no wx). Lines are marked by app-kit's
                `theideaplace_appkit.difftext`, shared with The Chat Place.
codeview.py   — A repository's files as text to read (no wx): a file one line out per line
                in, Markdown headings, blame runs, one commit of a file's history.
alertview.py  — A security alert as text to read (no wx): alert_details, empty_text.
milestoneview.py — A milestone as text to read (no wx): milestone_details, progress, status_message.
gistview.py   — A gist as text to read (no wx): gist_text (text and a stop per file heading),
                file_heading, file_body, status_message.
insightview.py — Insights as text to read (no wx): insight_details, notes, status_message.
peopleview.py — People as text (no wx): person_details, the lists' names (people_label,
                repos_label, activity_label), person_keys, status_message, and people_of
                (who View User offers for an item) with is_login.
discussionview.py — A discussion as text to read (no wx): discussion_details (text and
                Alt+N/Alt+P stops per comment and reply), answer_line, status_message.
```

**Rule:** `ghviewer.py` never calls `gh` or the API directly. `gh_data.py` never imports wx.
This separation is critical — keep it.

### Data flow

1. User selects a repo → `ghviewer` calls `gh_data.fetch_*` in a background thread
2. `gh_data` shells out to `gh` (or `gh api`), parses JSON, returns `Item` / `Branch` / `Commit` objects
3. `ghviewer` receives results via `wx.CallAfter` and populates the ListCtrl + details panel

### Threading model

All network calls happen in `threading.Thread(daemon=True)`. Results are marshaled back to the
UI thread via `wx.CallAfter`. Never touch wx widgets from a worker thread.

## Key Classes & Functions

### gh_data.py

- `Item` — dataclass for issues/PRs. Has `to_row(columns)`, a dict of column id to value.
- `_run_gh(args)` — runs `gh` subprocess, returns stdout, raises `GhError` on failure.
- `fetch_issues(repo, state, limit)` / `fetch_prs(repo, state, limit)` — list issues/PRs.
- `fetch_branches(repo, limit)` — list branches via REST API.
- `fetch_commits(repo, branch, limit)` — list commits, optionally for a specific branch.
- `fetch_commit_detail(repo, sha)` — full commit with file changes.
- `ChangedFile`, `fetch_pr_files(pr_url)`, `fetch_commit_files(repo, sha)` — the Changed Files
  view (`VIEW_FILES`, H on a PR or commit): each file with its `patch`, which GitHub leaves out
  for binary and very large files. `fetch_pr_diff` / `fetch_commit_diff` give the whole diff for
  Copy Diff and Open Diff; `file_diff(f)` one file's, with its header. The marking style
  (`settings.load_diff_style`) is app-kit's difftext style id. app-kit is pinned to a commit
  archive in `requirements.txt` and `pyproject.toml`; bump both together.
- `ReviewComment`, `fetch_pr_review_comments(pr_url)`, `add_review_comment(pr_url, commit_id,
  path, line, side, body)` — a PR's line comments (#84). `line`/`side` (RIGHT new file, LEFT old)
  place a comment; `line` is null once outdated. A reply's `in_reply_to` is its thread's first
  comment. The post sends JSON on stdin (`gh api --input -`). For a PR the files worker attaches
  each file's comments to `ChangedFile.comments` (`_attach_comments`); None for a commit's file
  or when reading them failed, which leaves the Comments column blank.
- `RepoFile`, `fetch_repo_folder(repo, ref, path)` — the Files view (`VIEW_CODE`). A folder is
  read with the git trees API (`git/trees/{ref}:{path}`, URL-quoted whole so a ref with a
  slash works), not the contents API: trees say which entries are links (mode 120000) and
  submodules (type commit), which contents lists as files, and have no 1,000-entry cap.
  `fetch_blob_text(repo, sha)` reads a file by blob SHA with `Accept: application/vnd.github.raw`
  (UTF-8 with replacement, via `_run_gh`); `MAX_FILE_BYTES` (1 MB) is the most shown.
  `fetch_readme_path(repo)` (`repos/{r}/readme`: the path GitHub picks, None on 404) is Read
  README's (#88). `fetch_file_history(repo, path, ref, limit)` (`commits?path=&sha=`, doesn't follow renames),
  `fetch_commit_file(repo, sha, path)` (one file of `fetch_commit_files`), `fetch_blame(repo,
  ref, path)` (GraphQL `object(expression:).blame(path:)`, values quoted with json.dumps),
  `fetch_ref_names(repo)` (branch and tag names only, for Ctrl+B in Files), and
  `fetch_pr_head_sha(pr_url)` (W on a pull request's file).
- `SecurityAlert`, `SecurityAlerts`, `fetch_security_alerts(repo, state, limit)` — the Security
  Alerts view (`VIEW_SECURITY`, #85, read-only). Reads `repos/{r}/dependabot|code-scanning|
  secret-scanning/alerts` in parallel (ThreadPoolExecutor); each kind fails on its own and
  `classify_alert_error` turns its failure into "off" (disabled / not enabled / no analysis),
  "rights" ("You are not authorized…" 403 from Dependabot and code scanning on a repo you don't
  administer; secret scanning's bare "Not Found" 404, which names both causes), "scope"
  ("Resource not accessible by…": said once by `scope_sentence`, naming `security_events` and
  the `gh auth refresh` command) or "error" (GitHub's own text: rate limits, SSO). **gh adds a
  bogus "needs the admin:repo_hook scope" hint to every one of these failures**; it is
  dropped before classifying and never repeated. Dependabot rejects `page=` (HTTP 400): it
  pages by cursor through `_api_cursor_pages` (`gh api -i`, Link rel="next"). Secret scanning
  rejects `state=all`, so View > State > All sends no state; `hide_secret=true` always, so the
  secret is never fetched. `sort_alerts`: `SEVERITY_RANK` (critical..low, then code scanning's
  tool error/warning/note, then none), newest first within. `ghviewer.security_status` is
  the status line; `_on_security_loaded` speaks it (STATUS) only when the list is empty.
- `Discussion`, `DiscussionComment`, `Discussions`, `fetch_discussions(repo, state, limit)`,
  `fetch_discussion_comments(repo, number)`, `add_discussion_comment(discussion, body)` — the
  Discussions view (`VIEW_DISCUSSIONS`, #86). GraphQL only, through `_graphql(query,
  variables)`: values (and a typed comment) go as GraphQL variables, never into the query
  text. The list (UPDATED_AT desc, `states:` from View > State, cursor paging) carries each
  body; `hasDiscussionsEnabled` false gives `Discussions(enabled=False)`, said plainly, not
  an error. Comments (100 a page, up to `DISCUSSION_COMMENT_PAGES`, replies up to 100 each)
  are read when a row rests 250 ms (`_fetch_discussion_comments_later`, `_detail_gen`) and
  kept on the Discussion (`comments` None until read). `_render_discussion(keep_place=True)`
  keeps the caret's line and column when comments arrive or after M posts. Notifications
  for a discussion open here (`_open_discussion_here`): by number from its address, else by
  title (pending kind `discussion_title`; GitHub often gives discussions no subject URL);
  Activity and Open Address reach it through `parse_github_url` kind "discussion" in
  `ADDRESS_VIEWS`/`PENDING_KINDS`.
  One not in the list (closed, or older) is fetched by number (`fetch_discussion`,
  `_goto_discussion`) and put first, like `_goto_commit`. `Discussion.comments_version`
  stops a comment read begun before M posted from replacing the read after it. A field
  GitHub refuses in a partial reply (`discussions: null` with `errors`) raises, never
  reads as an empty list.
- `Milestone`, `fetch_milestones(repo, state, limit)` — the Milestones view (`VIEW_MILESTONES`,
  #87): REST `repos/{r}/milestones?state=` through `_api_pages`, GitHub's order (due_on asc),
  on a fork the upstream's (`resolve_issue_repo`, like labels). Enter (`_browse_milestone`)
  sets `milestone_filter` (a Milestone) on Issues & PRs, which `fetch_issues` passes as
  `--milestone <number>` (a numeric title would be read as a number) and `fetch_prs` as
  `--search 'milestone:"title"'` (gh pr list has no --milestone; quotes can't be escaped in
  search, so they are dropped). Cleared like `label_filter` (switching view, repo, Ctrl+1,
  a label); Backspace (`_back_to_milestones`) lands on the milestone via pending kind
  "milestone". `fetch_prs` retries an HTTP 502/504 without `PR_STAT_FIELDS`
  (additions, deletions, changedFiles), which GitHub times out on for very large PRs
  (nvaccess/nvda); those Items have `has_stats` False and blank Changes/Files cells.
- `Gist`, `GistFile`, `fetch_gists(limit)` (`gists`, paged, no text), `fetch_gist(id)` (files
  with `content`, `truncated` past ~1 MB, no content at all when very large; `Gist.files_truncated`
  when GitHub lists only some files), `count_gists()` — the Gists view (`VIEW_GISTS`, #90,
  read-only). A repoless category entry (`GISTS_ENTRY`, last of `CATEGORY_ENTRIES`, counted in
  `COUNTED_ENTRIES`), in `REPOLESS_VIEWS` and `FEED_VIEWS`. A gist's files are read 250 ms after
  its row rests (`_fetch_gist_later`, `_detail_gen`, `_shows`) and kept on the row's own Gist
  (`loaded`), so coming back needs no fetch; Alt+N's noun is "file". F is refused aloud.
- `InsightRow`, `Insights`, `fetch_insights(repo, limit)` — the Insights view (`VIEW_INSIGHTS`,
  #89, read-only). One list whose rows are the figures (`section`: Views, Clones, Referrer,
  Page, Contributor); `count_display`/`uniques_display` name what they count ("1,234 views",
  "210 unique visitors", `INSIGHT_NOUNS`) so a row reads on its own in Quick mode. The four
  `traffic/*` calls run side by side; they need push access, and their 403 becomes
  `traffic_error` (`traffic_sentence`) while contributors still show. `repos/{r}/contributors`
  is paged by hand (`_fetch_contributors`): a non-list reply (202, still counting) is retried
  `CONTRIBUTOR_RETRIES` times `CONTRIBUTOR_WAIT` apart, then `contributors_pending`; a too-large
  repository's 403 is `contributors_error`. ghviewer lists up to `INSIGHT_CONTRIBUTORS` (500);
  Insights is in `NO_MORE_VIEWS`; F and sorting are refused aloud; the notes are spoken
  (STATUS) after the first row.
- `Person`, `fetch_people(kind, login, limit)`, `fetch_person(login)`, `count_following` /
  `count_followers`, `fetch_user_repos(login, limit, viewer)`, `fetch_user_starred`,
  `fetch_repo_forks(repo, limit)`, `follow_user` / `unfollow_user` — People (#25) and a
  repository's Stargazers, Watchers and Forks (#31). Lists are GraphQL (`_USER_FIELDS`, cursor
  paging, login/owner/name as variables): kinds followers/following (of `viewer` or
  `user(login:)`) and stargazers/watchers (`repository(owner:,name:)`, `REPO_PEOPLE`). **A list
  row asks no `starredRepositories` and no unrestricted repo count**: they made a page of 100 take
  most of a minute; `fetch_person` (`_PERSON_FIELDS`, `repositoryOwner`, User or Organization)
  asks them and sets `full`, and ghviewer reads it 250 ms after a row rests
  (`_fetch_person_later`). User `email` needs `user:email`, so it's asked of organizations only.
  Follow/unfollow (`PUT`/`DELETE user/following/{login}`) need `user:follow`; a 404, 403 or gh's
  scope hint becomes `MissingScope("user:follow")`. `fetch_activity(limit, of=login)` reads
  `users/{login}/events/public`.
- `fetch_tags(repo, limit)` / `fetch_releases(repo, limit)` / `fetch_workflow_runs(repo, limit)`.
- `fetch_release_assets(repo, release_id, release_tag, limit)` — a release's files with their
  download counts. The releases endpoint already returns assets inline, so the Releases list
  costs no extra call; this exists so the drill-down view can refresh on its own (R key).
- `total_downloads(releases)` — sum across every asset of every release given.
- `ReleaseAsset` — dataclass for a release file. `Release.downloads` is a computed property
  summing its assets. **Download counts are lifetime running totals** — GitHub exposes no
  date breakdown, so any over-time view would require snapshotting and diffing ourselves.
- `fetch_labels(repo, limit)` / `create_label(repo, name, color, description)` /
  `delete_label(repo, name)` — the Labels view. All three go through
  `resolve_issue_repo`, like the issue calls do: on a fork you browse the upstream
  issues, so a label list from the fork itself would not match them. `gh label list`
  exits non-zero on a repo with no labels at all; `fetch_labels` translates that
  into an empty list rather than an error.
- `Label` — dataclass for a label: name, color, description, url, is_default.
- `fetch_issues` / `fetch_prs` take an optional `label` and pass it to `gh` as
  `--label`. Filtering server-side is the point — an unfiltered page of 100 may
  not contain a single issue with the label you picked.
- `fetch_compare(repo, base, head)` — compare two refs.
- `fetch_item_detail(item, repo)` — re-fetch a single issue/PR with full detail.
- `close_item` / `reopen_item` / `add_comment` — actions on issues/PRs.
- `fetch_pages_site(repo)` → `PagesSite | None` — the repo's Pages config. **None means Pages
  is off**, not that the call failed: every Pages endpoint 404s on a repo without a site, and
  `_is_not_found` turns that into a normal answer.
- `fetch_pages_builds(repo, limit)` — publish history. Two endpoints hide behind this. A site
  GitHub builds itself (`build_type: legacy`) reports on `pages/builds`; a site published by
  Actions (`build_type: workflow`) returns an **empty list** there and its history lives in the
  `github-pages` deployments instead. Legacy sites have deployments *as well*, so the two are
  never merged — it falls back rather than combining, or every publish would appear twice.
- `PagesBuild.kind` says which endpoint a row came from. Builds carry a duration and an error
  message; deployments carry only a state, and their state costs one extra call each (fetched
  concurrently, same as branch commit info).
- `_build_id_from_url(url)` — `pages/builds` rows have **no `id` field**, unlike every other
  list endpoint here. The id has to be read off the end of `.url`.
- `fetch_pages_files(repo, site, limit)` → `list[PagesFile]` — the pages a site serves.
  **There is no API for this.** It reads the git tree of the source branch and maps each file
  onto its live URL, which is more than concatenation: a source path of `/docs` publishes only
  that subtree with the prefix stripped, and without a `.nojekyll` marker a legacy site runs
  through Jekyll, which renders `.md` to `.html` and withholds its `_`-prefixed directories.
  For an **Actions-built site the tree is the source, not the output** — the workflow decides
  what ships. The UI states that caveat; don't drop it.
- `list_repos(limit)` — list user's GitHub repos.
- `detect_repo()` — detect repo from current git directory.
- `sort_items(items, sort_order)` — sort by named order string.
- `fetch_dispatch_spec(repo, path, ref)` → `DispatchSpec` — whether a workflow can be run
  manually and which inputs it declares. **There is no API that returns a workflow's inputs.**
  GitHub's own "Run workflow" form is built by parsing the workflow file, and so is this.
  `ref` matters: a branch that adds an input has a different form from the default branch.
- `_parse_dispatch_spec(raw)` — the YAML parsing half, split out so it is testable without
  network access. Note the `on:` key: YAML 1.1 reads a bare `on` as boolean `True`, so the
  lookup checks both. Falls back to the old substring check if the file will not parse.
- `WorkflowInput` — one declared input: name, type, description, default, required, options.
- `fetch_environments(repo)` — environment names, used to fill the choices for an
  `environment`-typed input (the workflow file declares those without options).
- `dispatch_workflow(repo, workflow_id, ref, inputs)` — trigger a manual run. Inputs go over
  as `gh api -f "inputs[key]=value"`; `gh` turns the bracket syntax into nested JSON.
- `workflow_supports_dispatch(repo, path)` — thin wrapper kept for callers that only need the
  yes/no.

### ghviewer.py

- `GhViewerFrame` — main window. Owns all state: `repo`, `items`, `git_items`, `columns`,
  `sort_order`, `list_mode`, `state_filter`, `tab_filter`, `page_size`, `current_limit`,
  `view_mode`, `commit_branch`, `label_filter`.
- `_build_ui` / `_build_menu` / `_bind_events` — construction.
- `_load_items` — background fetch + populate list (dispatches by `view_mode`).
- **Every list load carries a token** from `_begin_fetch`, and the `wx.CallAfter`
  handlers drop results when `_fetch_is_current` says otherwise. Nothing cancels a
  `gh` call, so a slow fetch will still come back after the user has switched views —
  without the token, a big repo's issues land in whatever view is now on screen, filling
  it with blank rows under the wrong columns and a status bar describing a view you left.
  `_load_items` also snapshots `view_mode` on the UI thread and dispatches on that copy,
  so a switch mid-fetch cannot make the worker choose one branch and report another.
  **Any new async path that writes to the list needs the same treatment**;
  `_on_goto_fetched` is the other one, guarded on the view instead.
- `_switch_view(mode)` — switch between Issues/PRs, Branches, Commits, Tags, Releases,
  Workflow, Labels, Pages. Each drill-down view clears its context here when you leave it
  (`commit_branch`, `artifacts_run`, `assets_release`, `label_filter`) — add a reset for
  any new one. `pages_site` is the exception: it is shared by *both* Pages views, so it
  survives the move between them and clears only on the way out to anything else.
- Drill-down views are registered in `PARENT_VIEW`, which is what makes Backspace step back up.
  A new drill-down needs an entry there, in `VIEW_COLUMNS`, and in `_VIEW_LABELS`.
- `_show_details(idx)` — dispatches to `_show_issue_details` or `_show_git_details`.
- `_navigate_comment(direction)` — Alt+N/Alt+P comment jumping.
- `_refresh_list_display` — re-populate list from `self.items` or `self.git_items` without re-fetching.
- **The key contract** (Kelly's request after #78–#90): **Enter goes in, inside GHManage;
  Ctrl+O goes to GitHub; Backspace comes back; every key is on a menu.**
  - `on_item_activated` never opens the browser. `OPEN_LABELS` (module level; the class's
    `_OPEN_LABELS` is the same dict) names Enter per view for every view in `VIEW_COLUMNS`;
    `enter_label`/`enter_hint` give the menu name and the status bar's "Enter=…" from it
    (`commands.hint_words` lowercases Title-case words, keeps PRs/GitHub). `READ_VIEWS`
    (Issues, Discussions, Security, Insights, Gists, Published Pages, Changed Files): Enter
    is `_read_item` — focus into the details panel at the top. Tags: `_open_tag_files`
    (Files at the tag; `_code_back = {"view": VIEW_TAGS, …}`, which `_back_from_code`
    restores). Release files: `_download_asset_flow` → `gh_data.download_release_asset`
    (`gh release download TAG -p <glob-escaped name> -D dir [--clobber]`).
  - Cross-repo lists open things here: `address_view(target)` is the view a
    `parse_github_url` target opens in (None: no view, `NO_VIEW_SAID` spoken);
    `_open_address_here(target, row)` lands on it via `_open_repo_from_list` + pending
    target, so Backspace returns to the row. Favorites (`_open_favorite`; tags, labels and
    workflows found by name via `FAVORITE_BY_NAME` and pending kinds tag/label/workflow),
    Notifications (releases via `release_page` then `_on_release_page`, security alerts via
    `NOTIFICATION_VIEWS`), Activity. `*_opens_here` say which, for the details text.
    `_open_item_here(item, repo, number)`: a fork is refused aloud (`fork_said`).
  - Ctrl+O: `on_open_browser` (also caught in `on_char_hook`, so it works from every pane
    and speaks where the menu item is greyed). Repo-list focus → the repository. `_web_target`
    gives a release file's release, a publish's commit. `CTRL_O_LABELS` renames the menu
    item per view (None in Artifacts: greyed, "An artifact has no page…" told).
  - Backspace: `_back_label(lower)` names where it goes and `_go_back` does it (list key and
    File ▸ Back); `_set_view_status` replaces any "Backspace=" hint with `_back_label`'s.
    In the details panel, `on_char_hook` sends Backspace to `_back_to_row` and Enter to
    `_enter_from_details` (the list's Enter, except in READ_VIEWS and on a file in Files).
  - Menus: the Actions menu's first item is `_act_enter` (ID_CTX_OPEN, "<label> (Enter)"),
    so the context menu leads with it; `_act_back`, `_act_clear_filter`, Next/Previous
    Pane (F6) items; `EVT_MENU_OPEN` refreshes labels/enables. Bare keys are "(Key)" in a
    label, never accelerators. tests/test_consistent_keys.py asserts every `ord("X")` and
    WXK_RETURN/BACK/ESCAPE/INSERT/DELETE/F6 a handler acts on appears in a menu label.
  - Bare Insert/Delete in `on_char_hook` act only with no modifiers; J only in Workflow Runs.
- **Files (`VIEW_CODE`) and File History (`VIEW_HISTORY`)** keep their own navigation, not
  `PARENT_VIEW`: `_code_ref`/`_code_at` (the branch, tag or SHA and how it is said: "on main",
  "at tag v1", "at commit abc12345"), `_code_path` (the folder; "" is the top), `_code_stack`
  (folders Enter went in from, so Backspace lands on the one you left), `_code_land` (the path
  to select when a folder arrives), `_code_back` (the Changed Files snapshot when W opened it),
  `_code_folders` (folders read this visit), `_code_blame` (the file whose blame is showing).
  `_reset_code` clears them all whenever `_switch_view` leaves Files; going on to History or
  Changed Files saves a snapshot dict (`_code_snapshot`, `_history_back`, `_files_back` with
  `history_of`/`history_back`) that the Backspace handlers (`_code_up`, `_back_from_history`,
  `_back_from_files`, `_back_from_code`) restore after their own `_switch_view`. Chains nest:
  Files → H → History → Enter → Changed Files → W → Files.
- **Read README** (Actions, Ctrl+Shift+R, repo-list context menu; #88) is Files, not a window
  of its own: `_read_readme` sets `_code_readme` to the repository in front of you and opens
  it on Files (`_open_repo_from_list` from a row, so Backspace returns). The next `_load_items`
  of Files takes `_code_readme` (one load only; `_reset_code` doesn't clear it), asks
  `fetch_readme_path`, opens that folder and passes the path to `_on_code_loaded(readme=)`,
  which lands on it and, via `_read_readme_text`, puts focus in the details panel at the top:
  at once when the text is cached, else when `_on_blob_fetched` draws it (`_readme_focus`,
  honoured once, only while focus is still on the list; moving off the row clears it in
  `_show_code_details`; a failed read is spoken).
  No README: the top, and the note says so.
- Details that arrive later (a file's text, a history commit's patch) are fetched 250 ms after
  the row is selected, carry `_detail_gen` (bumped in every `_show_details`), and are drawn only
  if `_shows(view, item, gen)`; what arrives is cached either way (`_blob_cache` by blob SHA,
  `_patch_cache` by (sha, path)), since neither can change.
- Alt+N/Alt+P's noun comes from `_nav_noun`: change (Changed Files, History), heading or run
  (Files, run while blame shows), comment elsewhere; "change or comment" in a PR's Changed Files.
  A `_comment_positions` entry may carry a third item, its kind ("change"/"comment"); then
  `_navigate_comment` counts each kind on its own ("Comment 1 of 3").
- `diffview.file_view(f, style, comments)` renders a changed file and returns a `FileView`:
  `text`, `stops` (line, nlines, kind) and per-line `targets` — ("RIGHT"|"LEFT", line number)
  for a line that can take a comment, else the spoken reason M refuses with. It works out each
  rendered line's old/new numbers from the hunk header, following difftext's order
  (`_order` mirrors the CHANGED style's pairing; a test checks it against `difftext._marked`).
  Comments go after their line (replies after them), outdated ones under "Earlier comments".
  `file_text` is the comment-less wrapper File History uses.
- M in Changed Files (`_comment_on_line`, only in the details panel, only for a PR): the caret's
  line (`_caret_line`) → `_file_view.target`, a TextEntryDialog, then head SHA + post + refetch
  in a thread; `_on_line_comment_done` re-attaches comments, redraws rows, re-renders and puts
  the caret back on the same line (comments go after it, so its index doesn't move).
- **People** (`VIEW_PEOPLE`, `VIEW_USER_REPOS`, and `VIEW_ACTIVITY` with `_activity_of`).
  `_people = (kind, login)`: kind following/followers (login "" is you, the two repo-list entries
  `PEOPLE_ENTRIES`, both mapped to VIEW_PEOPLE in `ENTRY_VIEWS`; `_view_entry` says which),
  "user" (View User's list of one) or stargazers/watchers (login is OWNER/NAME).
  `_user_repos = (kind, login)`: repos, starred or forks. **`_people_trail`** is the way back:
  every drill (O/W/S/A/Enter on a person, View User, Stargazers/Watchers/Forks) pushes
  `_people_snapshot()` and `_go_back` pops it (`_people_back`) while `_in_people()`. People
  views come back from their cached items; any other view (View User from Issues, Files…) via
  `_restore_view`: repo, `_VIEW_CONTEXT` attributes, `_restore_code` for Files, or a reload
  landing on the item by pending kind "url" (silent). None of `_people`, `_user_repos`,
  `_activity_of` or the trail is cleared by `_switch_view`, so `_return_to_list` back into them
  works. `_open_my_people` and `_on_account_switched` clear the trail (the latter the three
  attributes too), `_select_category(VIEW_ACTIVITY)` clears `_activity_of`, and `_push_people`
  starts a new trail from outside People (except in a repository opened from someone's
  repositories); bounded at 50, keeping the first step. A step saved mid-load has items None
  and is reloaded on Backspace (`_landed_token`, set in `_populate_filtered_list`). A "url"
  pending target that misses lands on `_url_fallback_row`.
  Keys O/W/S/A/Insert/Delete are in `on_char_hook` (work from the profile);
  `peopleview.person_keys` names only those that work (an organization: A). `_current_entry`
  keeps the trail's root entry selected in the repo list.
- `on_select_branch` — Ctrl+B branch picker dialog for Commits view; in Files,
  `_choose_code_ref` (branches, then tags marked "(tag)"), which keeps the folder and entry. Its first entry, "All branches", sets `commit_branch` to `ALL_BRANCHES` ("*"), which `fetch_commits` hands to `fetch_all_branch_commits` (GraphQL, newest 100 commits of up to 100 branches, merged).
- **The Labels view is a view of the Issues view, not a drill-down.** Enter on a label
  sets `label_filter` and loads Issues & PRs restricted to it, which keeps the state
  filter, columns, sorting, and every issue action working. It is deliberately *not* in
  `PARENT_VIEW` — the parent map is keyed by view mode and the drilled-into view here is
  `VIEW_ISSUES`, which has no single parent. Backspace is handled as its own case in
  `on_list_key_down`, guarded on `label_filter` being set, and `on_view_issues` clears
  the filter when you ask for Issues & PRs by name (Ctrl+1) even though the mode does
  not change.
- `NewLabelDialog` — name/description/colour form. Colour is validated as 6 hex digits
  before `gh` is called, and may be left blank for GitHub to choose.
- `_on_label_action_done` — refresh after a label create/delete. Separate from
  `_on_action_done` because a label can be created from any view via the File menu, and
  refreshing the current view would hide the label just made.
- **The Actions menu is the home for anything that acts on the listed item**, whichever
  view it belongs to. `_update_actions_menu` re-labels and enables its entries for the
  current view and is called from `_update_menu_checks` (so every `_switch_view` covers
  it) plus `_select_repo` / `_select_favorites`, where the repo changes without the view
  doing so. A new action belongs there, with an entry in that method.
- **Open Repository or Address** (Ctrl+Shift+O) — `parse_github_url` (pure, module
  level) turns an address into a `GitHubTarget(repo, kind, ref)`. `_open_address` picks
  the view, calls `_select_repo(repo, view)` and then `_set_pending_target(view, kind,
  ref)`, which records the **fetch token of the load just started**. `_on_items_loaded`
  and `_on_git_items_loaded` pass their items and token through `_take_pending_row`: the
  target is consumed by the first load that lands, and only acts if that load is the one
  it was set for — otherwise the user moved on and it is dropped, never fired later.
  Fallbacks: `_goto_issue` for an issue not in the list (or hidden by the filter),
  `_goto_commit` for a commit; both capture repo (and token, for commits) on the UI thread
  and drop stale results. Any other async path that wants to land on an item after a
  load should use `_set_pending_target` the same way (New Issue and Notifications do).
  `parse_github_url` only reads github.com; a page inside a repo GHManage has no view for
  is kind `inside`, which opens the repo **without pinning** — only kind `repo` pins.
- **New Issue** (Ctrl+N / N) — `NewIssueDialog` (title + multiline Markdown body,
  Ctrl+Enter submits). `create_issue` sends the body on **stdin** (`--body-file -`,
  `_run_gh(args, stdin=…)`) because a long body on the command line can exceed the
  Windows limit; it resolves the fork's upstream like every other issue action, and the
  dialog names that repo. Unsent text lives in `_issue_drafts[repo]` until created.
  After creation the list reloads with `_pending_target` on the new number.
- **Notifications** (`VIEW_NOTIFICATIONS`, Ctrl+Shift+N, entry second in the repo list,
  counted as "(N unread)"). Data: `fetch_notifications(limit, include_read)` pages **50**
  at a time (GitHub's cap), `Notification` maps the subject's API address to a github.com
  page and number (`_notification_url`). Enter on an issue/PR opens it via
  `_open_repo_from_list` + `_pending_target`, so Backspace returns; anything else opens the
  browser; both mark read. M/U/I/G live in `on_char_hook` (work from the details panel);
  Delete/Ctrl+D is "Mark as Done" through `_delete_focused_item`. Changes run through
  `_run_notification_change`, which looks the gh_data function up **by name at call time**
  (`_NOTIFICATION_CHANGES`) — a dict of the functions themselves bound them at import and
  a test stub of `mark_notification_read` did not take, which marked a real notification
  read. Keep it by name. Read rows stay put until refresh; done rows leave at once.
- **Switch GitHub Account** (File, Ctrl+Shift+K) — `list_accounts` (`gh auth status --json
  hosts`, github.com only) and `switch_account` (`gh auth switch`, also resets the cached
  login). `_on_account_switched` drops everything tied to the old account (repo, return
  path, pending target, drafts, counts), reloads the repo list and lands on Notifications.
- **Watch Settings** (Actions, Ctrl+Shift+U) — `get_watch_level`/`set_watch_level` on
  `repos/{r}/subscription` (404 = participating, the default; DELETE sets it). These need
  gh's **notifications** scope, which `gh auth login` does not request: `_scope_error`
  turns gh's "needs the X scope" message into `MissingScope(scope)`, whose text gives the
  `gh auth refresh` command. Use `MissingScope` for any future feature that needs an extra
  scope (Follow needs `user:follow`, Projects `read:project`).
- **Search / My Work / saved searches** — `search_issues`/`search_repos` call the REST
  `search/*` endpoints with `-f q=<query as typed>`: **not** `gh search`, which splits and
  re-quotes arguments and breaks qualifiers like `review-requested:@me`. Results are
  `Item`s carrying `repo` (and `why` for My Work) or `RepoEntry`s. `ITEM_VIEWS` (Issues,
  My Work, Search issues) all show issue details and keep their rows in `self.items`; only
  `VIEW_ISSUES` has the repo-bound actions (close/reopen/comment). Enter in the cross-repo
  views goes through `_open_repo_from_list` + `_set_pending_target`, so Backspace returns;
  `_open_repo_from_list` snapshots `_view_source()`. `fetch_my_work` runs `MY_WORK_QUERIES`
  in priority order, dedups by URL and reports reasons that hit the 100 cap. Saved searches
  (`saved_searches.py`) are repo-list entries with client data `SEARCH_ENTRY_PREFIX+name`;
  use `is_repo_entry()` wherever a repo-list entry is treated as a repository.
- **Workflow run jobs / logs / rerun / cancel** — `VIEW_JOBS` is a drill-down of
  `VIEW_WORKFLOW` (J; `jobs_run` cleared on leaving). Logs come from `gh run view
  --log-failed` / `--job ID --log`, whose lines are `job TAB step TAB stamped text`;
  `parse_run_log` groups them and `clean_log_line` strips colour codes, timestamps and
  turns `##[error]` into "ERROR:". `format_failure_report` / `format_job_log` are pure and
  tested. Annotations: a job's id is its check run's id (`check-runs/{id}/annotations`).
  J/L/E/X are in `on_char_hook` so they work from the details panel.
- **Pull request actions** (Actions ▸ Pull Request; K/V/D in the issues list, list only
  like C/O/M) — gh_data `fetch_pr_checks` reads `gh pr checks --json` **whatever gh exits
  with** (1 = a check failed, 8 = still running); `review_pr` sends the message on stdin.
  Every PR call takes the PR's **address** (`pr.url`), never number + repo: resolving a
  fork's upstream can fail and fall back to the fork, where the same number is another PR.
  `merge_pr` reports what happened ("merged", "auto" when GitHub enabled auto-merge,
  "queued") from `gh pr view --json state,autoMergeRequest`. K/V/D live in `on_char_hook`
  (they work from the details panel); D asks first. `format_checks` is pure.
- **Context menus** — the item list's is **built from the Actions menu** each time
  (`_context_entries` walks `_actions_menu`, keeping enabled items and submenus; its first
  item is Enter's own, `_act_enter`), so a new action belongs in the Actions menu and
  `_update_actions_menu` only. Bound to `EVT_CONTEXT_MENU` on Windows (not
  `EVT_LIST_ITEM_RIGHT_CLICK`, which is mouse-only) so the Applications key and Shift+F10
  work. The repo list's is `_repo_context_entries`.
- **Repository actions** (New Issue Ctrl+N, Search This Repository Ctrl+Shift+S, Watch
  Settings Ctrl+Shift+U) are **always enabled** and act on `_repo_in_front()`: the repo
  selected in the repo list when it has focus; in a repoless view, the selected row's
  repo (RepoEntry.name, Item/Notification/ActivityEvent.repo, FavoriteEntry.repo); else
  the open repo. New Issue opens that repo on its issues first when it isn't the open one
  (via `_open_repo_from_list` from cross-repo lists, so Backspace returns).
- **Copy** (Actions ▸ Copy, Ctrl+Shift+C/L/T/I/D) — `copy_values(item)` is a pure,
  module-level function returning a `CopyValues` (link, title, ident, ident_noun, text)
  for every item type, so it is tested without a window. `_COPY_IDENT_NOUNS` names
  the fourth entry per view and must agree with the `ident_noun` the view's items
  give; a new view needs an entry there. With focus in the repo list the commands
  act on that repository instead (`_copy_target`).
- `_delete_focused_item` is the single dispatcher behind Delete, Ctrl+D, and the Actions
  menu entry, so the key and the menu cannot disagree about what Delete means in a view.
  Add new deletable views there and in `_update_actions_menu`.
- **Bare Insert/Delete are handled in `on_char_hook`** — a frame-level `EVT_CHAR_HOOK` —
  **not** in `on_list_key_down` and **not** as accelerators. `EVT_LIST_KEY_DOWN` only
  fires while the list has focus, which made the keys unusable from the details panel,
  and that panel is where the text describing them is read. A bare Delete *accelerator*
  is not an option either: it would swallow the Delete key everywhere in the window.
  Their Ctrl+I / Ctrl+D twins are ordinary accelerators on the Actions menu items, which
  is why those need nothing in the hook. The hook skips everything else, so focused
  controls keep first claim on their own keys, and it ignores the repo list, where
  Delete reads as "remove this repo".
- Status-bar hints are per-view for a reason: a key named in the status bar has to work
  in that view. `Ctrl+B=select branch` is Commits-only — `on_select_branch` refuses
  everywhere else.
- **Pages views** (Ctrl+0 → `VIEW_PAGES`, Enter → `VIEW_PAGEFILES`). Pages lists publishes,
  Enter drills into the pages the site serves, Enter there opens one in the default browser,
  `S` opens the site root from either. Enter in the Pages view ignores which publish is
  selected — the file list is the site as it stands now, and GitHub keeps no per-publish
  snapshot to browse. Pages sits at Ctrl+0 on the end of the menu rather than beside the
  other repo views: inserting it mid-menu would renumber every shortcut below it, which
  is what happened to Favorites when Labels took Ctrl+8.
- `_show_pages_disabled` — Pages off is a real answer, so it says so in the details panel.
  An empty list alone reads the same as a site that has never published.
- `_on_pages_loaded` / `_on_pagefiles_loaded` call `_update_actions_menu` themselves.
  Whether there is a site to open is only known after the fetch, and by then the
  `_switch_view` that would normally refresh the menu has long since run.
- `WorkflowInputsDialog` — the "Run workflow" form, generated at runtime from a
  `DispatchSpec`. choice/environment → `wx.Choice`, boolean → `wx.CheckBox`, everything else
  → `wx.TextCtrl`. Because it is generated rather than hand-written, **labelling is manual**:
  each control gets a preceding `wx.StaticText` *and* a matching `SetName`, so the accessible
  name is right whichever the screen reader picks up. A checkbox carries its own label and so
  gets the name only — a StaticText too would read it twice.
- The manual-run flow is **branch first, then inputs** (`_run_workflow_flow` →
  `_on_workflow_branches_ready` → `_on_workflow_dispatch_ready`). Inputs are declared in the
  workflow file, so they must be read from the branch being run. Reading them first would
  show the default branch's form and silently drop values on any branch that differs.

## Conventions

### Screen-reader friendliness

- **Status bar is the announcement channel.** Use `self._announce(msg)`, which sets the
  status bar's message item. Never call `SetStatusText` directly.
- **The status bar is a `NavStatusBar` of named items** — `message`, `keys`, `filter`, `mode`,
  `update` — set with `status_bar.set_item(key, text)`; empty text takes an item off the bar.
  A view's summary and key hints go through `_set_view_status(message, keys)`; a load in
  progress passes no keys so the last view's keys don't linger. Each item is a focusable
  control laid over its native field (read-only text, or a button for the update) so F6 and
  Left/Right can reach it; the native field keeps the same text for the screen reader's
  read-status-bar command. The controls refuse *keyboard* focus (`AcceptsFocusFromKeyboard`)
  so Tab never lands on them.
- **F6 loop** — `_cycle_pane` in `on_char_hook`: repo list → item list → details → status bar,
  wrapping; Shift+F6 reverses. A new pane goes in `_focus_panes`.
- **Full mode** prefixes field names in list rows: `"208, PR, OPEN, Title: ..."` (never the first column, `names_cell`).
  Every column is described once in `gh_columns.py` (`ColumnDef`: heading, kind, width), and
  each view's columns are a `ColumnSet` there. A new column needs a `CATALOG` entry with a
  heading in plain words ("Commit", not "sha"). Make it `STATE` when its value says what it is
  ("open", "success") so Full mode doesn't name it; Yes/No columns stay `TEXT`, since "Yes"
  means nothing without its name. `columns.py` builds the cells and rows (`cell_text`,
  `row_text`) and knows nothing about GitHub or wx, so it can move into app-kit.
- **Spoken results** (#65). `self._tell(msg, category)` writes the status bar and hands the
  message to `announce.announcer`, which filters it by category (`RESULT` interrupts,
  `STATUS` and `HINT` queue, `SILENT` is never spoken) and the user's settings
  (`settings.load_announcements`, View ▸ Speak Results). `_announce` stays status-bar only.
  `speech.py` delivers it: on Windows a UIA notification raised from a minimal ctypes
  `IRawElementProviderSimple` that a hidden child window (`_speech_window`) serves through
  `WM_GETOBJECT`. A notification from `UiaHostProviderFromHwnd` alone is never delivered,
  and serving the provider from the frame takes over the frame's UIA name, so don't do
  either. On a Mac, a VoiceOver announcement. UI thread only (`_tell` hops there). Dialogs take a
  `say` callable, which tests replace; wording that comes from a rule, like the Columns
  dialog's, lives beside the rule (`LayoutEditor.said`) and is tested there.
- **Name controls with `_name(ctrl, label)`**, never `SetName` alone (#69). On Windows it is
  just `SetName`; on a Mac, where `SetName` reaches nothing native, it also calls
  `speech.set_label` to put the label on the native view VoiceOver reads.
  `tests/test_mac_labels.py` reads every dialog's labels back from AppKit on the macOS CI job.
- **Keyboard first.** Every action has a keybinding. Never add a feature that requires mouse-only access.
- **No key instructions in content.** The details panel, a file's, diff's or gist's text,
  reports (what failed, checks) and result announcements describe the item only: never
  "Press Enter to…", "Ctrl+O opens it on GitHub", "Backspace goes back…" or a key table.
  Keys go on the menus (key in the label), the status bar's key hints (`_set_view_status`
  keys), Keyboard Shortcuts (`commands.LIST_KEYS`) and the user guide. An empty or error state
  may say what would help ("…press R in a moment"); a refusal for a key pressed may name the
  key that works. `tests/test_no_instructions_in_content.py` runs every details formatter on
  samples and scans the formatters' source; an allowed empty state goes in its `ALLOWED`.
- **No patronizing hand-holding.** Don't add "Welcome!" dialogs or verbose tooltips. Power users want speed.
- **Comment navigation** uses Alt+N/Alt+P with position tracking via `_comment_positions`.

### Code style

- Type hints everywhere (`from __future__ import annotations`).
- Dataclasses for data models.
- `Optional[str]` for `repo` (None = detect from current directory).
- Section dividers with `# ── Name ──` in both files.
- `GhError` is the only exception type for data-layer failures.

### `gh` CLI usage

- Issues/PRs: use `gh issue list` / `gh pr list` / `gh issue view` / `gh pr view` with `--json`.
- Actions: `gh issue close` / `gh issue reopen` / `gh issue comment` (same for `pr`).
- Repos: one GraphQL `viewer` query (`list_repos` → `RepoListing`): your own repos, your organizations with repo counts, and a count of repos shared with you outside them. Organization repos aren't mixed into the list (a big org buried people's own, #40); they are under the My Organizations entry (`VIEW_ORGS`, `fetch_orgs`, `OrgEntry`), whose Enter drills into one org's repos (`VIEW_ORG`, `fetch_org_repos`, Backspace via `PARENT_VIEW`); no emoji on these labels. Shared With Me (`VIEW_SHARED`, `fetch_shared_repos`, REST `affiliation=collaborator`) shows only when non-empty. / `gh repo view`.
- Git metadata: use `gh api` (REST API) — branches, commits, tags, compare, releases, workflow runs.
- Always pass `--repo OWNER/NAME` when `repo` is not None.
- `gh` returns newest-first by default for issue/pr lists.

### GitHub REST API endpoints used

| Purpose | Endpoint |
|---------|----------|
| Branches | `repos/{owner}/{repo}/branches` |
| Branch detail | `repos/{owner}/{repo}/branches/{branch}` |
| Commits | `repos/{owner}/{repo}/commits` |
| Commit detail | `repos/{owner}/{repo}/commits/{sha}` |
| Tags | `repos/{owner}/{repo}/tags` |
| Compare | `repos/{owner}/{repo}/compare/{base}...{head}` |
| Releases (assets inline) | `repos/{owner}/{repo}/releases` |
| Release assets | `repos/{owner}/{repo}/releases/{id}/assets` |
| Workflow runs | `repos/{owner}/{repo}/actions/runs` |
| Contributors | `repos/{owner}/{repo}/contributors` |
| Workflow file (for inputs) | `repos/{owner}/{repo}/contents/{path}?ref={ref}` |
| Environments | `repos/{owner}/{repo}/environments` |
| Manual run | `POST repos/{owner}/{repo}/actions/workflows/{id}/dispatches` |
| Pages config | `repos/{owner}/{repo}/pages` (404 = Pages off) |
| Pages builds (legacy sites) | `repos/{owner}/{repo}/pages/builds` |
| Pages deployments (Actions sites) | `repos/{owner}/{repo}/deployments?environment=github-pages` |
| Deployment state | `repos/{owner}/{repo}/deployments/{id}/statuses` |
| Published file list | `repos/{owner}/{repo}/git/trees/{branch}?recursive=1` |
| Starred repos (Starred view) | `user/starred?per_page=&page=` |
| Watched repos (Watched view) | `user/subscriptions?per_page=&page=` |
| Signed-in login | `user` (`-q .login`, cached) |
| Search | `GET search/issues`, `GET search/repositories` with `-f q=` (30/min, 1,000 max) |
| Notifications | `notifications?all=false|true&per_page=50&page=` |
| Mark read / done / unsubscribe | `PATCH`/`DELETE notifications/threads/{id}`, `DELETE …/{id}/subscription` |
| Mark all read | `PUT notifications -F read=true` |
| Milestones | `repos/{owner}/{repo}/milestones?state=`; their issues `gh issue list --milestone N`, PRs `gh pr list --search 'milestone:"T"'` |
| Discussions | GraphQL `repository.discussions`, `discussion(number:).comments{replies}`, mutation `addDiscussionComment` |
| Security alerts | `repos/{owner}/{repo}/dependabot/alerts` (cursor paging), `…/code-scanning/alerts`, `…/secret-scanning/alerts?hide_secret=true` |
| Activity feed | `users/{login}/received_events?per_page=100&page=` (max 3 pages; page 4 is HTTP 422; pages are not reliably full) |
| A person's activity | `users/{login}/events/public?per_page=100&page=`; an organization's `orgs/{login}/events` (`_activity_org`; under users/ it has few or none) |
| People, stargazers, watchers | GraphQL `viewer`/`user(login:)` `followers`/`following`, `repository` `stargazers`/`watchers`; `repositoryOwner(login:)` for one profile |
| A person's repositories, stars | `users/{u}/repos?type=owner&sort=pushed` (yours: `user/repos?affiliation=owner`), `users/{u}/starred` |
| Forks | `repos/{r}/forks?sort=newest` |
| Follow / unfollow | `PUT` / `DELETE user/following/{login}` (needs `user:follow`) |
| PR titles for the feed | GraphQL `repository(owner,name){ pN: pullRequest(number:N){title body} }`, batched, per repo on error |

## Tests

`python -m pytest` from the repo root (pytest is in the `dev` extras). Nothing
in `tests/` talks to GitHub:

- `fake_gh` (in `tests/conftest.py`) replaces `gh_data._run_gh`, the one function
  every gh call goes through. Route replies by a fragment of the command line;
  an unrouted call fails the test. Reply shapes should match what real `gh`
  prints — `gh issue/pr view` give one object, the `list` commands an array.
- `app_data` points favorites and pinned repos at a temp folder.
- An autouse fixture covers every test regardless: `_run_gh` fails if called
  without `fake_gh`, and `APPDATA`/`HOME` point at a temp folder. Tests of
  `_run_gh` itself take `real_run_gh` and patch `subprocess.run`.
- `test_ghviewer.py` calls frame methods (details panel, comment navigation,
  favorites) on a `SimpleNamespace` stand-in, so no window is opened. It needs
  wx importable and skips otherwise.

Add tests alongside any change; CI runs them before building.

## CI/CD

- `.github/workflows/ghmanage.yml` — runs the tests on Windows and on macOS, then builds `ghmanage.exe` and the Mac app with PyInstaller.
- Triggers on push to `main`, `v*` tags, and PRs to `main`.
- On tag push: creates a GitHub Release with `ghmanage.exe` attached.
- Release notes read from `docs/release-notes-<tag>.md`.
- Uses `softprops/action-gh-release@v3`.

## Release process

The `release` project skill (`.claude/skills/release/SKILL.md`) walks through all of this,
including the checks either side. The short version:

1. Update `__version__` in `version.py`. (`pyproject.toml` reads it from there; CI fails the
   build if the tag and `version.py` disagree.)
2. Create `docs/release-notes-vX.Y.Z.md`. **Required** — the workflow passes it to both
   `vpk pack --releaseNotes` and the release body, so a missing file fails the release.
3. Commit: `git commit -m "Description (vX.Y.Z)"`.
4. Tag: `git tag vX.Y.Z`.
5. Push: `git push origin main && git push origin vX.Y.Z`.
6. CI auto-builds and creates the release.

## Current versions

- v0.1.0 — initial release
- v0.1.1 — fixed missing issues (paging), added View More
- v0.1.2 — git views: branches, commits, tags, releases, workflow runs
- v0.1.3 — branch-specific commits: Enter on a branch switches to its commits, Ctrl+B branch picker
- v0.1.4 — open repos by URL, pinned repos, fork-aware issue fetching, informative window title, default load 100
- *(v0.1.5–v0.3.0 not recorded here — see `docs/release-notes-v*.md` for each)*
- v0.4.0 — Run Workflow collects `workflow_dispatch` inputs
- v0.5.0 — Ctrl+1..Ctrl+8 switch views
- v0.6.0 — Labels view (Ctrl+8): browse by label, create and delete labels.
  Favorites moved to Ctrl+9 to keep the numbers matching the menu order.
- v0.6.1 — Actions menu gathers every item action; Ctrl+I / Ctrl+D alongside
  Insert/Delete; bare Insert/Delete work from the details panel too.
- v0.6.2 — first signed release (Azure Trusted Signing). No code changes.
- v0.6.3 — a slow fetch can no longer land in a view you have already left.
- v0.7.0 — GitHub Pages view (Ctrl+0): publish history and the pages a site serves
- v0.7.1 — first macOS release (signed and notarized .dmg). No Windows changes.
- v0.8.0 — F6 loop through the panes and the status bar; the status bar split into items
  you arrow between, with a persistent update button
- v0.8.1 — web addresses in the details panel on a line of their own; comment navigation lands on the right comment
- v0.8.2 — Go To Issue fetches items not in the list (it never finished before), PRs as PRs, real errors instead of "not found"; first test suite, run in CI
- v0.8.5 — Activity view (Ctrl+Shift+A) plus Starred and Watched Repositories, each an entry at the top of the repo list; user guide published to GitHub Pages (Help ▸ User Guide, F1); quick-filter rows now map to the right item
- v0.9.0 — a major release: GHManage becomes a much fuller GitHub client. Notifications (Ctrl+Shift+N), My Work (Ctrl+Shift+M), Search GitHub (Ctrl+Shift+F) with saved searches; open any GitHub address (Ctrl+Shift+O); New Issue; Copy commands; PR checks/review/merge/draft; workflow run jobs, logs, what failed, rerun, cancel; watch settings; account switching; context menus everywhere; repository actions act on the repo in front of you
- v0.9.1 — repository list includes organization repos (GraphQL, own and org listed separately); repo moved to TheIdeaPlace/GHManage
- v0.9.2 — My Organizations entry (orgs with role and counts; Enter lists an org's repos) instead of org repos in the main list; Shared With Me; favorite repos from the repo list and open them here; no beep after list letter keys
- v0.9.3 — Activity Enter opens issues/PRs, releases, commits and branches here (Backspace back); Search Operators help (F1 in the search dialog, search_help.py); Copy HTTPS/SSH clone URL; Go To submenu on repository context menus; View More on item context menus; list letters shown in menus
- v0.9.4 — Delete removes any repo from the list (hidden_repos.json; File ▸ Hidden Repositories); Help ▸ Keyboard Shortcuts (Ctrl+F1) and Command Palette (Ctrl+Shift+P), commands.py; palette filter summary as the edit's accessible description; search dialog: "Search" box, Search Qualifiers on Alt+Q (Insert Qualifier…), F1 opens the guide's searching page
- v0.9.5 — View ▸ Columns… dialog (order, show/hide, Speak column names) replaces the Columns submenu; columns per kind of list and list mode remembered (settings.py, settings.json); plain-word headings and Full mode names only text columns after the first (columns.py, gh_columns.py); Commits: All branches and a Branches column
- v0.9.6 — File ▸ Archive or Unarchive Repository… and Delete Repository from GitHub… (typed-name confirmation, admin check, delete_repo scope via MissingScope); spoken results through UIA notifications from a served provider (announce.py, speech.py), View ▸ Speak Results; Search dialog examples in a read-only box, not dialog text; Mac labels through _name/speech.set_label, macOS CI runs the tests
- v0.9.7 — Changed Files (VIEW_FILES): Enter on a commit or H on a PR lists its files; each file's lines marked by app-kit's difftext (diffview.py) in a style from View > Mark Changed Lines With; Alt+N/Alt+P between hunks; Copy Diff and Open Diff in Default App
- v0.9.8 — Files (VIEW_CODE): browse a repository at a branch, tag or commit, read a file one line out per line in (codeview.py), Alt+N/Alt+P between Markdown headings, Ctrl+B Select Branch or Tag; B blame in runs; H File History (VIEW_HISTORY), each commit's change to the file in the chosen marking style, Enter to Changed Files; W in Changed Files opens the file whole; a PR's review comments after their lines in Changed Files, Alt+N/Alt+P stop at them, M comments on the caret's line, Comments column (#84); Security Alerts (VIEW_SECURITY, alertview.py): Dependabot, code scanning and secret scanning alerts, most severe first (#85); Discussions (VIEW_DISCUSSIONS, discussionview.py): list, read with comments and replies, M comments, opened here from Notifications/Activity/addresses (#86); Milestones (VIEW_MILESTONES, milestoneview.py): progress, Enter for their issues and PRs, Backspace back (#87); Read README Ctrl+Shift+R (#88); Insights (VIEW_INSIGHTS, insightview.py): traffic and contributors (#89); Gists (VIEW_GISTS, gistview.py) (#90); Enter goes in / Ctrl+O to GitHub / Backspace back in every view, Actions menu starts with the Enter action, every key on a menu (#101); opening an address goes into the item (#103); Copy Diff Ctrl+Shift+X, Open Diff Ctrl+Shift+E, .../pull/N/files and .diff addresses (#104); details describe the item only, no key instructions (#105); Help > Report a Bug (#106); JAWS hears Alt+N/Alt+P via speech.jaws_running (#107); details text named Details on Windows, empty lists and Alt+N edges spoken (#110)

## Roadmap

- **Branch comparison** — compare two branches or tags, show commits and file changes.
- **Multi-repo dashboard** — watch multiple repos at once.
- **Workflow run filtering** — filter workflow runs by branch.