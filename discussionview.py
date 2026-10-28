"""A discussion as text to read in the details panel (no wx).

The Discussions view (#86) lists a repository's discussions; this is what
selecting one shows: the fields, the body, then each comment under a heading
like the issues' "Comment 2 of 5 — alice (2026-10-01):", its replies indented
under it. One line out per line in, so the positions returned for Alt+N and
Alt+P count the same lines the panel does.
"""

from __future__ import annotations

from commands import READ_KEYS
from gh_data import Discussion, DiscussionComment, Discussions, _local_time

RULE = "─" * 60
COMMENT_INDENT = "  "
REPLY_INDENT = "      "


def _day(stamp: str) -> str:
    return stamp[:10] if stamp else ""


def _plural(n: int, word: str, words: str = "") -> str:
    return f"{n} {word if n == 1 else (words or word + 's')}"


def _answer_place(comments: list[DiscussionComment]) -> str:
    """Where the answer is among the comments: "comment 3", "reply 1 to
    comment 3", or "" when none of those read is marked."""
    for i, c in enumerate(comments, 1):
        if c.is_answer:
            return f"comment {i}"
        for j, r in enumerate(c.replies, 1):
            if r.is_answer:
                return f"reply {j} to comment {i}"
    return ""


def answer_line(d: Discussion) -> str:
    """The "Answered:" line, or "" for a category that takes no answer."""
    if not d.answerable:
        return ""
    if not d.answered:
        return "Answered: No"
    parts = ["Answered: Yes"]
    if d.answer_author:
        parts.append(f"by {d.answer_author}")
    if d.comments:
        place = _answer_place(d.comments)
        if place:
            parts.append(f"in {place}")
    if d.answer_chosen_at:
        parts.append(f"(chosen {_day(d.answer_chosen_at)})")
    return " ".join(parts)


def _heading(c: DiscussionComment, what: str) -> str:
    extra = ""
    if c.is_answer:
        extra = ", the answer"
    elif c.minimized:
        extra = ", hidden on GitHub"
    return f"{what} — {c.author} ({_day(c.created_at)}){extra}:"


def _body_lines(c: DiscussionComment, indent: str) -> list[str]:
    if c.minimized:
        return [f"{indent}(hidden on GitHub)"]
    return [f"{indent}{line}" for line in (c.body.splitlines() or [""])]


def discussion_details(d: Discussion) -> tuple[str, list[tuple[int, int, str]]]:
    """The details panel's text for ``d``, and a stop for Alt+N / Alt+P at
    each comment and each reply: (first line, lines, "comment" or "reply")."""
    lines: list[str] = [f"#{d.number} [{d.category or 'Discussion'}] {d.title}"]
    lines.append(f"Category: {d.category}" if d.category else "Category: (none)")
    lines.append(f"State: {d.state_display}")
    lines.append(f"Author: {d.author}")
    lines.append(f"Created: {_local_time(d.created_at)}")
    lines.append(f"Updated: {_local_time(d.updated_at)}")
    answered = answer_line(d)
    if answered:
        lines.append(answered)
    if d.upvotes:
        lines.append(f"Upvotes: {d.upvotes}")
    lines.append(f"Comments: {d.comment_count}")
    lines.append("URL:")
    lines.append(d.url or "(none)")
    lines.append(READ_KEYS)
    lines.append("")
    lines.append(RULE)
    lines.append("")
    lines.extend(d.body.splitlines() or ["(no description)"])
    positions: list[tuple[int, int, str]] = []
    if d.comments is None:
        if d.comment_count:
            lines.append("")
            lines.append(f"Getting the {_plural(d.comment_count, 'comment')}…")
        return "\n".join(lines), positions
    if not d.comments:
        return "\n".join(lines), positions
    replies = sum(len(c.replies) for c in d.comments)
    lines.append("")
    lines.append(RULE)
    with_replies = f", with {_plural(replies, 'reply', 'replies')}" if replies else ""
    lines.append(f"Comments ({len(d.comments)}{with_replies}):")
    lines.append(RULE)
    # Cut short, the count is GitHub's, not the number read.
    total = max(len(d.comments), d.comment_count) if d.comments_cut else len(d.comments)
    for i, c in enumerate(d.comments, 1):
        lines.append("")
        start = len(lines)
        lines.append(COMMENT_INDENT + _heading(c, f"Comment {i} of {total}"))
        lines.extend(_body_lines(c, COMMENT_INDENT * 2))
        positions.append((start, len(lines) - start, "comment"))
        for j, r in enumerate(c.replies, 1):
            start = len(lines)
            lines.append(REPLY_INDENT + _heading(r, f"Reply {j} of {c.reply_count} "
                                                   f"to comment {i}"))
            lines.extend(_body_lines(r, REPLY_INDENT + COMMENT_INDENT))
            positions.append((start, len(lines) - start, "reply"))
        unread = c.reply_count - len(c.replies)
        if unread > 0:
            lines.append(f"{REPLY_INDENT}{_plural(unread, 'more reply', 'more replies')} "
                         "on GitHub.")
    if d.comments_cut:
        lines.append("")
        lines.append("More comments on GitHub: Ctrl+O opens the discussion there.")
    return "\n".join(lines), positions


def empty_text(result: Discussions, repo: str, state: str) -> str:
    """What the details panel says when there are no discussions to list."""
    if not result.enabled:
        return f"{repo} has discussions turned off."
    which = {"open": "open ", "closed": "closed "}.get(state, "")
    return f"{repo} has no {which}discussions."


def status_message(result: Discussions, repo: str, state: str, limit: int) -> str:
    """The Discussions status line."""
    if not result.enabled:
        return f"{repo} has discussions turned off."
    which = {"open": "open ", "closed": "closed "}.get(state, "")
    n = len(result.items)
    message = f"{repo} — {n} {which}discussion{'' if n == 1 else 's'}"
    if result.more and result.total > n:
        message += f" of {result.total}, most recently active first. Ctrl++ shows more."
    else:
        message += ", most recently active first." if n > 1 else "."
    return message
