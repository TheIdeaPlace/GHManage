"""The GitHub permissions GHManage can use beyond those gh asks for at sign-in
(#129), what each is for, and the one command that adds the missing ones.
No wx: Help > GitHub Permissions and the Permission Needed boxes show it.

gh signs in with repo, read:org, gist and workflow. Some of GHManage's
features need more, and without this list each one said so in its own box,
one at a time, as you came to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import gh_data


@dataclass(frozen=True)
class Permission:
    scope: str             # as gh and GitHub name it
    what: str              # what it lets GHManage do
    covered_by: tuple = ()  # broader scopes that include it
    optional: bool = False  # left out of the command unless asked for


PERMISSIONS = (
    Permission("project", "Set an issue's or pull request's projects, and show them in the list"),
    Permission("notifications", "Watch Settings: how GitHub notifies you about a repository"),
    Permission("user:follow", "Follow and unfollow people", ("user",)),
    # repo, which gh asks for at sign-in, includes it (both read here with
    # repo alone); listed for a sign-in without repo.
    Permission(gh_data.SECURITY_SCOPE, "Security alerts: code scanning and secret scanning",
               ("repo",)),
    Permission("delete_repo", "Delete a repository from GitHub", optional=True),
)

BY_SCOPE = {p.scope: p for p in PERMISSIONS}


def has(scopes: set, permission: Permission) -> bool:
    return permission.scope in scopes or any(s in scopes for s in permission.covered_by)


def missing(scopes: Optional[set], include_optional: bool = False) -> list[Permission]:
    """The permissions gh lacks, in the order listed. With ``scopes`` None
    (gh's token doesn't say), all of them: asking for one gh has is harmless."""
    return [p for p in PERMISSIONS
            if (include_optional or not p.optional) and (scopes is None or not has(scopes, p))]


def command(scopes: list[str]) -> str:
    """The gh command that adds ``scopes``, or "" for none."""
    return f"gh auth refresh -h github.com -s {','.join(scopes)}" if scopes else ""


def parse_scopes(raw: str) -> Optional[set]:
    """The scopes in the X-OAuth-Scopes header of ``gh api -i`` output, or
    None when there is no such header: a fine-grained token, or one from
    GH_TOKEN, has permissions but doesn't list them this way."""
    for line in raw.splitlines():
        if not line.strip():
            break  # the headers end at the first blank line
        name, _, value = line.partition(":")
        if name.strip().lower() == "x-oauth-scopes":
            return {s.strip() for s in value.split(",") if s.strip()}
    return None


def fetch_scopes() -> Optional[set]:
    """The scopes gh's sign-in has, or None when GitHub doesn't say."""
    try:
        return parse_scopes(gh_data._run_gh(["api", "-i", "user"]))
    except gh_data.GhError:
        return None


def summary(scopes: Optional[set], include_optional: bool) -> str:
    """The Permissions box's text: one line a permission, then what to do."""
    lines = []
    if scopes is None:
        lines.append("GitHub doesn't say which permissions gh's sign-in has (it may use "
                     "a token). The command below asks for all of them; any it has "
                     "already are left as they are.")
        lines.append("")
    for p in PERMISSIONS:
        if scopes is None:
            state = "unknown"
        else:
            state = "has it" if has(scopes, p) else "missing"
        extra = ", optional" if p.optional else ""
        lines.append(f"{p.scope}: {state}{extra}. {p.what}.")
    need = missing(scopes, include_optional)
    lines.append("")
    if not need:
        lines.append("gh has every permission GHManage uses.")
    else:
        lines.append(f"Missing: {', '.join(p.scope for p in need)}.")
    return "\n".join(lines)
