"""Insights as text to read (no wx): what selecting a row shows, and the
status line.

The Insights view (#89) is one list whose rows are the figures themselves:
the last 14 days' views and clones with a row for each day, the sites people
came from, the pages they read, and the contributors with their commits. The
Section column says which a row is, and each count says what it counts, so a
row reads whole on its own: "Views, Last 14 days, 1,234 views, 210 unique
visitors".
"""

from __future__ import annotations

from commands import READ_KEYS
from gh_data import InsightRow, Insights

SECTIONS = ("Views", "Clones", "Referrer", "Page", "Contributor")


def _total(insights: Insights, section: str) -> InsightRow | None:
    return next((r for r in insights.section(section) if r.name == "Last 14 days"), None)


def insight_details(row: InsightRow) -> str:
    """One row, said in full."""
    lines: list[str] = []
    if row.section in ("Views", "Clones"):
        what = "Views" if row.section == "Views" else "Clones"
        if row.name == "Last 14 days":
            lines.append(f"{what}, last 14 days" + (f" ({row.detail})" if row.detail else ""))
        else:
            lines.append(f"{what} on {row.name}")
        lines.append(f"{row.count_display}, {row.uniques_display}.")
        lines.append("GitHub keeps 14 days of traffic, counted by day in UTC.")
    elif row.section == "Referrer":
        lines.append(f"Referring site: {row.name}")
        lines.append(f"{row.count_display}, {row.uniques_display}, in the last 14 days.")
    elif row.section == "Page":
        lines.append(f"Popular page: {row.name}")
        if row.detail and row.detail != row.name:
            lines.append(f"Path: {row.detail}")
        lines.append(f"{row.count_display}, {row.uniques_display}, in the last 14 days.")
    elif row.section == "Contributor":
        lines.append(f"Contributor: {row.name}")
        lines.append(f"{row.count_display} on the default branch.")
    else:
        lines.append(f"{row.section}: {row.name}")
    lines.append("URL:")
    lines.append(row.url or "(none)")
    lines.append("")
    lines.append(READ_KEYS)
    return "\n".join(lines)


def notes(insights: Insights) -> list[str]:
    """What is missing and why, a sentence each."""
    out: list[str] = []
    if insights.traffic_error:
        out.append(insights.traffic_error)
    if insights.contributors_pending:
        out.append("GitHub is still counting the contributors; press R in a moment.")
    elif insights.contributors_error:
        out.append(insights.contributors_error)
    return out


def status_message(repo: str, insights: Insights, most: int = 0) -> str:
    """``o/r — 1,234 views (210 unique) and 56 clones in the last 14 days,
    12 contributors.`` and then anything missing. ``most``: the most
    contributors listed, said when that many are."""
    parts: list[str] = []
    views, clones = _total(insights, "Views"), _total(insights, "Clones")
    if views and clones:
        parts.append(f"{views.count:,} views ({views.uniques:,} unique) and "
                     f"{clones.count:,} clones ({clones.uniques:,} unique) in the last 14 days")
    people = len(insights.section("Contributor"))
    if not insights.contributors_pending and not insights.contributors_error:
        parts.append(f"{people:,} contributor{'' if people == 1 else 's'}")
    said = f"{repo} — {', '.join(parts)}." if parts else f"{repo} — no insights to show."
    if most and people >= most:
        said += f" These are the {most:,} with most commits."
    extra = notes(insights)
    return " ".join([said] + extra)
