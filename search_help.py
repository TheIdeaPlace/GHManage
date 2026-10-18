"""The search operators the Search dialog's help lists (#45).

GitHub's search takes qualifiers such as ``is:open`` and ``label:bug``, and
the Search dialog passes them through untouched. These tables are the ones
worth knowing, with what each means and an example, so they can be found
without leaving GHManage. They are not every qualifier GitHub has; the
documentation links go to the full reference.
"""

from __future__ import annotations

from dataclasses import dataclass

from saved_searches import KIND_ISSUES, KIND_REPOS


@dataclass(frozen=True)
class Operator:
    op: str        # as typed: "is:open", or "label:" when a value follows
    meaning: str
    example: str

    @property
    def insert(self) -> str:
        """What goes into the query: the operator, ready for its value, or
        followed by a space when it is complete on its own."""
        return self.op if self.op.endswith(":") else self.op + " "


ISSUE_OPERATORS = [
    Operator("is:open", "Open issues and pull requests", "is:open"),
    Operator("is:closed", "Closed ones", "is:closed"),
    Operator("is:issue", "Issues only", "is:issue"),
    Operator("is:pr", "Pull requests only", "is:pr"),
    Operator("is:merged", "Pull requests that were merged", "is:pr is:merged"),
    Operator("is:unmerged", "Pull requests closed without merging, or still open", "is:pr is:unmerged"),
    Operator("is:draft", "Draft pull requests", "is:pr is:draft"),
    Operator("repo:", "In one repository", "repo:nvaccess/nvda"),
    Operator("org:", "In any repository of an organization", "org:nvaccess"),
    Operator("user:", "In any repository a person owns", "user:kellylford"),
    Operator("author:", "Opened by someone; @me is you", "author:@me"),
    Operator("assignee:", "Assigned to someone", "assignee:@me"),
    Operator("no:assignee", "Assigned to nobody", "is:open no:assignee"),
    Operator("mentions:", "Mentions someone", "mentions:@me"),
    Operator("commenter:", "Someone has commented", "commenter:@me"),
    Operator("involves:", "Opened by, assigned to, mentioning or commented on by someone",
             "involves:@me"),
    Operator("label:", "Has a label; quote a name with spaces", 'label:"needs triage"'),
    Operator("-label:", "Does not have a label. A minus before any qualifier excludes it",
             "-label:duplicate"),
    Operator("no:label", "Has no labels", "is:open no:label"),
    Operator("milestone:", "In a milestone", 'milestone:"2026.1"'),
    Operator("no:milestone", "In no milestone", "no:milestone"),
    Operator("in:title", "The words must be in the title", "crash in:title"),
    Operator("in:body", "The words must be in the description", "braille in:body"),
    Operator("in:comments", "The words must be in a comment", "focus in:comments"),
    Operator("created:", "Opened on, before or after a date", "created:>2026-01-01"),
    Operator("updated:", "Last updated on, before or after a date", "updated:>2026-09-01"),
    Operator("closed:", "Closed on, before or after a date", "closed:<2026-06-01"),
    Operator("comments:", "Number of comments", "comments:>20"),
    Operator("reactions:", "Number of reactions", "reactions:>10"),
    Operator("interactions:", "Comments and reactions together", "interactions:>50"),
    Operator("reason:", "Why an issue was closed", 'reason:completed  or  reason:"not planned"'),
    Operator("linked:", "Linked to a pull request, or to an issue", "is:issue linked:pr"),
    Operator("review-requested:", "A review is asked of someone", "review-requested:@me"),
    Operator("reviewed-by:", "Reviewed by someone", "reviewed-by:@me"),
    Operator("review:", "Review state: none, required, approved or changes_requested",
             "review:approved"),
    Operator("status:", "Checks: success, failure or pending", "is:pr status:failure"),
    Operator("base:", "Pull requests into a branch", "base:main"),
    Operator("head:", "Pull requests from a branch", "head:fix-focus"),
    Operator("language:", "In repositories written mainly in a language", "language:python"),
    Operator("archived:", "In archived repositories, or not", "archived:false"),
]

REPO_OPERATORS = [
    Operator("in:name", "The words must be in the name", "nvda in:name"),
    Operator("in:description", "The words must be in the description", "screen reader in:description"),
    Operator("in:readme", "The words must be in the README", "braille in:readme"),
    Operator("user:", "Repositories a person owns", "user:kellylford"),
    Operator("org:", "Repositories of an organization", "org:nvaccess"),
    Operator("repo:", "One repository by name", "repo:nvaccess/nvda"),
    Operator("language:", "Written mainly in a language", "language:python"),
    Operator("topic:", "Tagged with a topic", "topic:accessibility"),
    Operator("stars:", "Number of stars", "stars:>100"),
    Operator("forks:", "Number of forks", "forks:>10"),
    Operator("pushed:", "Last pushed on, before or after a date", "pushed:>2026-09-01"),
    Operator("created:", "Created on, before or after a date", "created:>2025-01-01"),
    Operator("license:", "Under a license", "license:mit"),
    Operator("archived:", "Archived, or not", "archived:false"),
    Operator("fork:", "Include forks (true), or only forks (only)", "fork:true"),
    Operator("is:public", "Public repositories", "is:public"),
    Operator("is:private", "Private repositories you can see", "is:private"),
    Operator("good-first-issues:", "Number of issues labelled good first issue",
             "good-first-issues:>2"),
    Operator("help-wanted-issues:", "Number of issues labelled help wanted",
             "help-wanted-issues:>2"),
]

# Ranges and dates work the same for every qualifier that takes them.
GENERAL_NOTE = (
    "Numbers and dates take >, >=, < and <=, or a range with two dots, such as "
    "created:2026-01-01..2026-03-31. A minus before a qualifier excludes it, "
    "and quotes keep words with spaces together."
)

DOCS = {
    KIND_ISSUES: "https://docs.github.com/en/search-github/searching-on-github/"
                 "searching-issues-and-pull-requests",
    KIND_REPOS: "https://docs.github.com/en/search-github/searching-on-github/"
                "searching-for-repositories",
}


def operators_for(kind: str) -> list[Operator]:
    return REPO_OPERATORS if kind == KIND_REPOS else ISSUE_OPERATORS


def matching(operators: list[Operator], text: str) -> list[Operator]:
    """The operators whose operator, meaning or example contains ``text``."""
    text = text.strip().lower()
    if not text:
        return list(operators)
    return [o for o in operators
            if text in o.op.lower() or text in o.meaning.lower() or text in o.example.lower()]


def insert_operator(query: str, at: int, op: Operator) -> tuple[str, int]:
    """``query`` with ``op`` put in at position ``at``, and the position just
    after it. A space goes before it unless it starts the query or follows one."""
    at = max(0, min(at, len(query)))
    before, after = query[:at], query[at:]
    lead = "" if not before or before.endswith(" ") else " "
    text = lead + op.insert
    if after.startswith(" ") and text.endswith(" "):
        text = text[:-1]  # one space between, not two
    return before + text + after, len(before) + len(text)
