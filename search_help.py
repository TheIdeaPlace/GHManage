"""The search qualifiers the Search dialog's help lists (#45).

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
class Qualifier:
    op: str        # as typed: "is:open", or "label:" when a value follows
    meaning: str
    example: str

    @property
    def insert(self) -> str:
        """What goes into the query: the qualifier, ready for its value, or
        followed by a space when it is complete on its own."""
        return self.op if self.op.endswith(":") else self.op + " "


ISSUE_QUALIFIERS = [
    Qualifier("is:open", "Open issues and pull requests", "is:open"),
    Qualifier("is:closed", "Closed ones", "is:closed"),
    Qualifier("is:issue", "Issues only", "is:issue"),
    Qualifier("is:pr", "Pull requests only", "is:pr"),
    Qualifier("is:merged", "Pull requests that were merged", "is:pr is:merged"),
    Qualifier("is:unmerged", "Pull requests closed without merging, or still open", "is:pr is:unmerged"),
    Qualifier("is:draft", "Draft pull requests", "is:pr is:draft"),
    Qualifier("repo:", "In one repository", "repo:nvaccess/nvda"),
    Qualifier("org:", "In any repository of an organization", "org:nvaccess"),
    Qualifier("user:", "In any repository a person owns", "user:kellylford"),
    Qualifier("author:", "Opened by someone; @me is you", "author:@me"),
    Qualifier("assignee:", "Assigned to someone", "assignee:@me"),
    Qualifier("no:assignee", "Assigned to nobody", "is:open no:assignee"),
    Qualifier("mentions:", "Mentions someone", "mentions:@me"),
    Qualifier("commenter:", "Someone has commented", "commenter:@me"),
    Qualifier("involves:", "Opened by, assigned to, mentioning or commented on by someone",
             "involves:@me"),
    Qualifier("label:", "Has a label; quote a name with spaces", 'label:"needs triage"'),
    Qualifier("-label:", "Does not have a label. A minus before any qualifier excludes it",
             "-label:duplicate"),
    Qualifier("no:label", "Has no labels", "is:open no:label"),
    Qualifier("milestone:", "In a milestone", 'milestone:"2026.1"'),
    Qualifier("no:milestone", "In no milestone", "no:milestone"),
    Qualifier("in:title", "The words must be in the title", "crash in:title"),
    Qualifier("in:body", "The words must be in the description", "braille in:body"),
    Qualifier("in:comments", "The words must be in a comment", "focus in:comments"),
    Qualifier("created:", "Opened on, before or after a date", "created:>2026-01-01"),
    Qualifier("updated:", "Last updated on, before or after a date", "updated:>2026-09-01"),
    Qualifier("closed:", "Closed on, before or after a date", "closed:<2026-06-01"),
    Qualifier("comments:", "Number of comments", "comments:>20"),
    Qualifier("reactions:", "Number of reactions", "reactions:>10"),
    Qualifier("interactions:", "Comments and reactions together", "interactions:>50"),
    Qualifier("reason:", "Why an issue was closed", 'reason:completed  or  reason:"not planned"'),
    Qualifier("linked:", "Linked to a pull request, or to an issue", "is:issue linked:pr"),
    Qualifier("review-requested:", "A review is asked of someone", "review-requested:@me"),
    Qualifier("reviewed-by:", "Reviewed by someone", "reviewed-by:@me"),
    Qualifier("review:", "Review state: none, required, approved or changes_requested",
             "review:approved"),
    Qualifier("status:", "Checks: success, failure or pending", "is:pr status:failure"),
    Qualifier("base:", "Pull requests into a branch", "base:main"),
    Qualifier("head:", "Pull requests from a branch", "head:fix-focus"),
    Qualifier("language:", "In repositories written mainly in a language", "language:python"),
    Qualifier("archived:", "In archived repositories, or not", "archived:false"),
]

REPO_QUALIFIERS = [
    Qualifier("in:name", "The words must be in the name", "nvda in:name"),
    Qualifier("in:description", "The words must be in the description", "screen reader in:description"),
    Qualifier("in:readme", "The words must be in the README", "braille in:readme"),
    Qualifier("user:", "Repositories a person owns", "user:kellylford"),
    Qualifier("org:", "Repositories of an organization", "org:nvaccess"),
    Qualifier("repo:", "One repository by name", "repo:nvaccess/nvda"),
    Qualifier("language:", "Written mainly in a language", "language:python"),
    Qualifier("topic:", "Tagged with a topic", "topic:accessibility"),
    Qualifier("stars:", "Number of stars", "stars:>100"),
    Qualifier("forks:", "Number of forks", "forks:>10"),
    Qualifier("pushed:", "Last pushed on, before or after a date", "pushed:>2026-09-01"),
    Qualifier("created:", "Created on, before or after a date", "created:>2025-01-01"),
    Qualifier("license:", "Under a license", "license:mit"),
    Qualifier("archived:", "Archived, or not", "archived:false"),
    Qualifier("fork:", "Include forks (true), or only forks (only)", "fork:true"),
    Qualifier("is:public", "Public repositories", "is:public"),
    Qualifier("is:private", "Private repositories you can see", "is:private"),
    Qualifier("good-first-issues:", "Number of issues labelled good first issue",
             "good-first-issues:>2"),
    Qualifier("help-wanted-issues:", "Number of issues labelled help wanted",
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


def qualifiers_for(kind: str) -> list[Qualifier]:
    return REPO_QUALIFIERS if kind == KIND_REPOS else ISSUE_QUALIFIERS


def matching(qualifiers: list[Qualifier], text: str) -> list[Qualifier]:
    """The qualifiers whose qualifier, meaning or example contains ``text``."""
    text = text.strip().lower()
    if not text:
        return list(qualifiers)
    return [o for o in qualifiers
            if text in o.op.lower() or text in o.meaning.lower() or text in o.example.lower()]


def insert_qualifier(query: str, at: int, op: Qualifier) -> tuple[str, int]:
    """``query`` with ``op`` put in at position ``at``, and the cursor's place
    after it, ready for a value when it takes one.

    In the middle of a word it goes after the word, not into it. It always
    stands apart from the words either side, so "label:" never joins onto
    the next word and becomes "label:crash".
    """
    at = max(0, min(at, len(query)))
    while 0 < at < len(query) and query[at] != " " and query[at - 1] != " ":
        at += 1  # inside a word: to its end
    before, after = query[:at], query[at:]
    lead = "" if not before or before.endswith(" ") else " "
    text = lead + op.insert
    cursor = len(before) + len(text)
    if after and not after.startswith(" ") and not text.endswith(" "):
        text += " "  # "label: crash": the value is typed before the space
    elif after.startswith(" ") and text.endswith(" "):
        text = text[:-1]  # one space between, not two
        cursor -= 1
    return before + text + after, cursor
