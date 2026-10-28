"""A security alert as text to read in the details panel (no wx).

The Security Alerts view (#85) lists a repository's Dependabot, code scanning
and secret scanning alerts; this is what selecting one shows. One line out
per line in, field names first, addresses alone on the line after "URL:" as
everywhere else in GHManage.
"""

from __future__ import annotations

import re

from commands import READ_KEYS
from gh_data import ALERT_CODE, ALERT_DEPENDABOT, ALERT_SECRET, SecurityAlert, SecurityAlerts

# An advisory's description can run to pages; the rest is a keypress away.
MAX_DESCRIPTION_LINES = 40
MAX_DESCRIPTION_CHARS = 4000
RULE = "─" * 60


def _day(stamp: str) -> str:
    return stamp[:10] if stamp else ""


def _words(value: str) -> str:
    """GitHub's tokens as words: "tolerable_risk" → "tolerable risk"."""
    return value.replace("_", " ").strip()


def trim_text(text: str, max_lines: int = MAX_DESCRIPTION_LINES,
              max_chars: int = MAX_DESCRIPTION_CHARS) -> str:
    """``text`` cut to its first ``max_lines`` lines and ``max_chars``
    characters, at a line, with a line saying the rest is on GitHub."""
    text = re.sub(r"\n{3,}", "\n\n", (text or "").replace("\r\n", "\n").strip())
    lines = text.splitlines()
    kept: list[str] = []
    size = 0
    for line in lines:
        if len(kept) >= max_lines or size + len(line) > max_chars:
            break
        kept.append(line)
        size += len(line) + 1
    if len(kept) < len(lines):
        if not kept:  # one enormous line
            kept = [lines[0][:max_chars].rstrip()]
        kept.append("(More on GitHub: Ctrl+O opens the alert.)")
    return "\n".join(kept)


def _closed_lines(alert: SecurityAlert) -> list[str]:
    """When and why a closed alert was closed."""
    info = alert.info
    out: list[str] = []
    if info.get("dismissed_at"):
        who = f" by {info['dismissed_by']}" if info.get("dismissed_by") else ""
        out.append(f"Dismissed: {_day(info['dismissed_at'])}{who}")
        if info.get("dismissed_reason"):
            out.append(f"Dismissed because: {_words(info['dismissed_reason'])}")
        if info.get("dismissed_comment"):
            out.append(f"Dismissal comment: {info['dismissed_comment']}")
    if info.get("auto_dismissed_at"):
        out.append(f"Dismissed automatically: {_day(info['auto_dismissed_at'])}")
    if info.get("fixed_at"):
        out.append(f"Fixed: {_day(info['fixed_at'])}")
    if info.get("resolved_at") or info.get("resolution"):
        who = f" by {info['resolved_by']}" if info.get("resolved_by") else ""
        when = _day(info.get("resolved_at", ""))
        out.append(f"Resolved: {when}{who}".rstrip())
        if info.get("resolution"):
            out.append(f"Resolved as: {_words(info['resolution'])}")
        if info.get("resolution_comment"):
            out.append(f"Resolution comment: {info['resolution_comment']}")
    return out


def _dependabot_lines(alert: SecurityAlert) -> tuple[list[str], str]:
    info = alert.info
    lines = []
    if alert.package:
        lines.append(f"Package: {alert.package}")
    if alert.where:
        lines.append(f"Manifest: {alert.where}")
    scope = " ".join(x for x in (info.get("scope"), info.get("relationship")) if x)
    if scope:
        lines.append(f"Dependency: {_words(scope)}")
    if info.get("range"):
        lines.append(f"Affected versions: {info['range']}")
    lines.append(f"First patched version: {info.get('patched') or 'none yet'}")
    if info.get("ghsa"):
        lines.append(f"GHSA: {info['ghsa']}")
    if info.get("cve"):
        lines.append(f"CVE: {info['cve']}")
    if info.get("cvss"):
        lines.append(f"CVSS score: {info['cvss']}")
    return lines, info.get("description", "")


def _code_lines(alert: SecurityAlert) -> tuple[list[str], str]:
    info = alert.info
    lines = []
    if alert.package:
        lines.append(f"Rule: {alert.package}")
    tool_sev = info.get("tool_severity")
    if tool_sev and tool_sev != alert.severity:
        lines.append(f"Tool severity: {tool_sev}")
    if info.get("tool"):
        lines.append(f"Tool: {info['tool']}")
    if info.get("path"):
        start, end = info.get("start_line") or 0, info.get("end_line") or 0
        at = (f", lines {start} to {end}" if end and end != start
              else f", line {start}" if start else "")
        lines.append(f"Location: {info['path']}{at}")
    if info.get("ref"):
        lines.append(f"Branch: {info['ref'].removeprefix('refs/heads/')}")
    if info.get("classifications"):
        lines.append(f"Classified as: {', '.join(info['classifications'])}")
    cwes = [t.rsplit("/", 1)[1].upper() for t in info.get("tags", [])
            if t.startswith("external/cwe/")]
    if cwes:
        lines.append(f"CWE: {', '.join(cwes)}")
    if info.get("message"):
        lines.append(f"Message: {info['message']}")
    return lines, info.get("rule_description", "")


def _secret_lines(alert: SecurityAlert) -> tuple[list[str], str]:
    info = alert.info
    lines = []
    if alert.package:
        lines.append(f"Secret type: {alert.package}")
    if info.get("validity"):
        lines.append(f"Validity: {info['validity']}")
    if info.get("path"):
        line = info.get("start_line")
        more = " (and elsewhere)" if info.get("more_locations") else ""
        lines.append(f"Found in: {info['path']}{f', line {line}' if line else ''}{more}")
    if info.get("publicly_leaked"):
        lines.append("Publicly leaked: Yes")
    if info.get("bypassed"):
        who = f" by {info['bypassed_by']}" if info.get("bypassed_by") else ""
        when = f" on {_day(info['bypassed_at'])}" if info.get("bypassed_at") else ""
        lines.append(f"Push protection bypassed{who}{when}")
    return lines, ""


_KIND_LINES = {
    ALERT_DEPENDABOT: _dependabot_lines,
    ALERT_CODE: _code_lines,
    ALERT_SECRET: _secret_lines,
}


def alert_details(alert: SecurityAlert) -> str:
    """Everything useful about ``alert``, for the details panel."""
    head = f"{alert.kind_display} alert #{alert.number}" if alert.number else (
        f"{alert.kind_display} alert")
    lines = [f"{head}: {alert.summary}" if alert.summary else head]
    if alert.severity:
        lines.append(f"Severity: {alert.severity}")
    lines.append(f"State: {alert.state_display}")
    kind_lines, description = _KIND_LINES.get(alert.kind, lambda a: ([], ""))(alert)
    lines.extend(kind_lines)
    if alert.created_at:
        lines.append(f"Created: {_day(alert.created_at)}")
    if alert.updated_at and _day(alert.updated_at) != _day(alert.created_at):
        lines.append(f"Updated: {_day(alert.updated_at)}")
    lines.extend(_closed_lines(alert))
    lines.append("URL:")
    lines.append(alert.url or "(none)")
    advisory = alert.info.get("advisory_url")
    if advisory:
        lines.append("Advisory URL:")
        lines.append(advisory)
    lines.append(READ_KEYS)
    if description.strip():
        lines += ["", RULE, "", trim_text(description)]
    return "\n".join(lines)


def _state_words(state: str) -> str:
    return {"open": "open ", "closed": "closed "}.get(state, "")


def empty_text(report: SecurityAlerts, state: str) -> str:
    """The details panel when no alert is listed: why, kind by kind."""
    notes = report.notes()
    lines = [f"No {_state_words(state)}security alerts."]
    if notes:
        lines.append("")
        lines.extend(notes)
    return "\n".join(lines)
