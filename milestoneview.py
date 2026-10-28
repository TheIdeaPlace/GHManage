"""A milestone as text to read in the details panel (no wx).

The Milestones view (#87) lists a repository's milestones with their
progress; this is what selecting one shows. One line out per line in, the
address alone on the line after "URL:" as everywhere else in GHManage.
"""

from __future__ import annotations

from gh_data import Milestone, _local_time

RULE = "─" * 60


def _day(stamp: str) -> str:
    return stamp[:10] if stamp else ""


def progress(m: Milestone) -> str:
    """"12 of 16 closed, 75% done", or "Nothing in it yet"."""
    if not m.total:
        return "Nothing in it yet"
    return f"{m.closed_issues} of {m.total} closed, {m.done_display} done"


def milestone_details(m: Milestone) -> str:
    lines = [f"Milestone: {m.title}"]
    lines.append(f"State: {m.state_display}")
    lines.append(f"Due: {_day(m.due_on) or 'no due date'}")
    lines.append(f"Progress: {progress(m)}")
    lines.append(f"Open: {m.open_issues}")
    lines.append(f"Closed: {m.closed_issues}")
    if m.creator:
        lines.append(f"Created by: {m.creator}")
    lines.append(f"Created: {_local_time(m.created_at)}")
    lines.append(f"Updated: {_local_time(m.updated_at)}")
    if m.closed_at:
        lines.append(f"Closed on: {_local_time(m.closed_at)}")
    lines.append("URL:")
    lines.append(m.url or "(none)")
    lines.append("")
    lines.append(RULE)
    lines.append("")
    lines.extend(m.description.splitlines() or ["(no description)"])
    lines.append("")
    # Enter works in the list, not here; Ctrl+O works from both.
    lines.append("Enter in the list shows its issues and pull requests. "
                 "Ctrl+O opens it on GitHub.")
    return "\n".join(lines)


def status_message(repo: str, milestones: list[Milestone], state: str) -> str:
    which = {"open": "open ", "closed": "closed "}.get(state, "")
    n = len(milestones)
    return f"{repo} — {n} {which}milestone{'' if n == 1 else 's'}."
