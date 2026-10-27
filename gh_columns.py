"""GHManage's columns: their headings, the names spoken before their values,
their widths, and which lists show which.

The ids are the keys each item's ``to_row`` fills in. The headings are what
people see and hear — "Commit", not "sha"; "Changes", not "+/-".
"""

from __future__ import annotations

from columns import STATE, ColumnDef, ColumnSet
from gh_data import (
    ACTIVITY_COLUMNS, ACTIVITY_DEFAULT_COLUMNS,
    ALL_COLUMNS, DEFAULT_COLUMNS,
    ARTIFACT_COLUMNS, ARTIFACT_DEFAULT_COLUMNS,
    ASSET_COLUMNS, ASSET_DEFAULT_COLUMNS,
    BRANCH_COLUMNS, BRANCH_DEFAULT_COLUMNS,
    CHANGED_FILE_COLUMNS, CHANGED_FILE_DEFAULT_COLUMNS,
    COMMIT_COLUMNS, COMMIT_DEFAULT_COLUMNS,
    JOB_COLUMNS, JOB_DEFAULT_COLUMNS,
    LABEL_COLUMNS, LABEL_DEFAULT_COLUMNS,
    MY_WORK_COLUMNS, MY_WORK_DEFAULT_COLUMNS,
    NOTIFICATION_COLUMNS, NOTIFICATION_DEFAULT_COLUMNS,
    ORG_COLUMNS, ORG_DEFAULT_COLUMNS,
    PAGEFILE_COLUMNS, PAGEFILE_DEFAULT_COLUMNS,
    PAGES_COLUMNS, PAGES_DEFAULT_COLUMNS,
    RELEASE_COLUMNS, RELEASE_DEFAULT_COLUMNS,
    REPO_COLUMNS, REPO_DEFAULT_COLUMNS,
    SEARCH_ITEM_COLUMNS, SEARCH_ITEM_DEFAULT_COLUMNS,
    TAG_COLUMNS, TAG_DEFAULT_COLUMNS,
    WORKFLOW_COLUMNS, WORKFLOW_DEFAULT_COLUMNS,
    WORKFLOW_DEF_COLUMNS, WORKFLOW_DEF_DEFAULT_COLUMNS,
)

FAVORITES_COLUMNS = ["type", "repo", "title", "subtitle"]
FAVORITES_DEFAULT_COLUMNS = ["type", "repo", "title", "subtitle"]


def _c(col_id: str, heading: str, width: int = 100, kind: str = "text") -> ColumnDef:
    return ColumnDef(col_id, heading, kind=kind, width=width)


# Every column once. A list where a column means something else, or wants a
# different width, says so in its set below.
CATALOG: dict[str, ColumnDef] = {c.id: c for c in [
    # Issues and pull requests
    _c("number", "Number", 60),
    _c("type", "Type", 60, STATE),
    _c("state", "State", 90, STATE),
    _c("title", "Title", 400),
    _c("author", "Author", 120),
    _c("created", "Created", 100),
    _c("updated", "Updated", 100),
    _c("labels", "Labels", 150),
    _c("assignees", "Assignees", 120),
    _c("comments", "Comments", 70),
    _c("draft", "Draft", 50),
    _c("review", "Review", 100),
    _c("+/-", "Changes", 90),
    _c("files", "Files", 50),
    _c("base", "Base branch", 100),
    _c("head", "Head branch", 100),
    _c("repo", "Repository", 180),
    _c("why", "Why", 100),
    # Branches, commits, tags
    _c("branch", "Branch", 150),
    _c("last commit", "Last commit", 400),
    _c("date", "Date", 100),
    _c("protected", "Protected", 70),
    _c("ahead", "Ahead", 60),
    _c("behind", "Behind", 60),
    _c("sha", "Commit", 80),
    _c("message", "Message", 400),
    _c("tag", "Tag", 100),
    _c("commit", "Commit", 80),
    # Releases, actions, Pages
    _c("name", "Name", 150),
    _c("downloads", "Downloads", 100),
    _c("size", "Size", 90),
    _c("#", "ID", 50),
    _c("assets", "Assets", 100),
    _c("prerelease", "Pre-release", 70),
    _c("status", "Status", 100, STATE),
    _c("result", "Result", 100, STATE),
    _c("event", "Event", 100),
    _c("expired", "Expired", 70),
    _c("path", "Path", 320),
    _c("pusher", "Pushed by", 100),
    _c("duration", "Duration", 100),
    _c("kind", "Kind", 100),
    _c("error", "Error", 100),
    _c("page", "Page", 100),
    _c("url", "Address", 100),
    _c("failed step", "Failed step", 100),
    # Changed files
    _c("added", "Added", 70),
    _c("removed", "Removed", 70),
    # Labels, organizations, repositories
    _c("label", "Label", 180),
    _c("description", "Description", 340),
    _c("color", "Color", 80),
    _c("default", "Default", 70),
    _c("organization", "Organization", 100),
    _c("role", "Role", 100),
    _c("repositories", "Repositories", 100),
    _c("language", "Language", 100),
    _c("stars", "Stars", 100),
    _c("pushed", "Pushed", 100),
    _c("owner", "Owner", 100),
    # Activity, notifications, favorites
    _c("actor", "Actor", 100),
    _c("action", "Action", 100),
    _c("reason", "Reason", 100),
    _c("subtitle", "Subtitle", 250),
]}


def _set(set_id: str, name: str, ids: list[str], defaults: list[str],
         overrides: dict[str, dict] | None = None) -> ColumnSet:
    """A set of catalog columns; ``overrides`` maps a column id to the fields
    that differ in this list."""
    overrides = overrides or {}
    cols = []
    for col_id in ids:
        col = CATALOG.get(col_id) or ColumnDef(col_id, col_id)
        changes = overrides.get(col_id)
        cols.append(col.with_(**changes) if changes else col)
    return ColumnSet(set_id, name, tuple(cols), tuple(defaults))

ISSUE_SET = _set("issues", "Issues and pull requests", ALL_COLUMNS, DEFAULT_COLUMNS)
LABEL_SET = _set("labels", "Labels", LABEL_COLUMNS, LABEL_DEFAULT_COLUMNS)
ORG_SET = _set("organizations", "Organizations", ORG_COLUMNS, ORG_DEFAULT_COLUMNS, {
    "organization": {"width": 240}, "role": {"width": 100},
    "repositories": {"width": 110}})
REPO_SET = _set("repositories", "Repositories", REPO_COLUMNS, REPO_DEFAULT_COLUMNS, {
    "repo": {"width": 240}, "description": {"width": 380},
    "language": {"width": 100}, "stars": {"width": 80},
    "pushed": {"width": 100}, "owner": {"width": 140}})
BRANCH_SET = _set("branches", "Branches", BRANCH_COLUMNS, BRANCH_DEFAULT_COLUMNS)
# A commit's branch cell can name several: "main, dev, fix and 4 more".
COMMIT_SET = _set("commits", "Commits", COMMIT_COLUMNS, COMMIT_DEFAULT_COLUMNS,
                  {"branch": {"heading": "Branches"}})
TAG_SET = _set("tags", "Tags", TAG_COLUMNS, TAG_DEFAULT_COLUMNS)
ASSET_SET = _set("assets", "Release assets", ASSET_COLUMNS, ASSET_DEFAULT_COLUMNS)
CHANGED_FILE_SET = _set("changed_files", "Changed files", CHANGED_FILE_COLUMNS,
                        CHANGED_FILE_DEFAULT_COLUMNS, {"path": {"heading": "File", "width": 400}})
RELEASE_SET = _set("releases", "Releases", RELEASE_COLUMNS, RELEASE_DEFAULT_COLUMNS)
WORKFLOW_RUN_SET = _set("workflow_runs", "Workflow runs", WORKFLOW_COLUMNS,
                        WORKFLOW_DEFAULT_COLUMNS, {"#": {"heading": "Run"}})
ARTIFACT_SET = _set("artifacts", "Artifacts", ARTIFACT_COLUMNS, ARTIFACT_DEFAULT_COLUMNS)
WORKFLOW_SET = _set("workflows", "Workflows", WORKFLOW_DEF_COLUMNS,
                    WORKFLOW_DEF_DEFAULT_COLUMNS)
PAGES_SET = _set("pages", "Pages deployments", PAGES_COLUMNS, PAGES_DEFAULT_COLUMNS)
PAGEFILE_SET = _set("page_files", "Published pages", PAGEFILE_COLUMNS,
                    PAGEFILE_DEFAULT_COLUMNS)
# Same names as elsewhere, different contents: the date carries a time, and
# the title shares the row with an action.
ACTIVITY_SET = _set("activity", "Activity", ACTIVITY_COLUMNS, ACTIVITY_DEFAULT_COLUMNS, {
    "actor": {"width": 130}, "action": {"width": 240},
    "title": {"width": 300}, "date": {"width": 130}})
NOTIFICATION_SET = _set("notifications", "Notifications", NOTIFICATION_COLUMNS,
                        NOTIFICATION_DEFAULT_COLUMNS, {
    "status": {"width": 70}, "reason": {"width": 130}, "type": {"width": 80},
    "title": {"width": 420}, "repo": {"width": 220}, "updated": {"width": 130}})
_SEARCH_WIDTHS = {"why": {"width": 130}, "repo": {"width": 200}, "title": {"width": 380}}
SEARCH_ITEM_SET = _set("search_items", "Issue and pull request search",
                       SEARCH_ITEM_COLUMNS, SEARCH_ITEM_DEFAULT_COLUMNS, _SEARCH_WIDTHS)
MY_WORK_SET = _set("my_work", "My Work", MY_WORK_COLUMNS, MY_WORK_DEFAULT_COLUMNS,
                   _SEARCH_WIDTHS)
JOB_SET = _set("jobs", "Jobs", JOB_COLUMNS, JOB_DEFAULT_COLUMNS)
FAVORITES_SET = _set("favorites", "Favorites", FAVORITES_COLUMNS,
                     FAVORITES_DEFAULT_COLUMNS)

COLUMN_SETS: list[ColumnSet] = [
    ISSUE_SET, LABEL_SET, ORG_SET, REPO_SET, BRANCH_SET, COMMIT_SET, TAG_SET,
    ASSET_SET, RELEASE_SET, WORKFLOW_RUN_SET, ARTIFACT_SET, WORKFLOW_SET,
    PAGES_SET, PAGEFILE_SET, ACTIVITY_SET, NOTIFICATION_SET, SEARCH_ITEM_SET,
    MY_WORK_SET, JOB_SET, FAVORITES_SET, CHANGED_FILE_SET,
]
