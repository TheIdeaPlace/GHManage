"""The GitHub permissions GHManage can use beyond those gh asks for at sign-in
(#129), what each is for, and the one command that adds the missing ones.
No wx: Help > GitHub Permissions and the Permission Needed boxes show it.

gh signs in with repo, read:org, gist and workflow. Some of GHManage's
features need more, and without this list each one said so in its own box,
one at a time, as you came to it.

``gh auth refresh -s`` adds scopes to the ones gh has, for the account gh
is using. It can't change a token given to gh in GH_TOKEN or GITHUB_TOKEN;
gh refuses, and that token's permissions are changed on GitHub instead.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
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
TOKEN_VARS = ("GH_TOKEN", "GITHUB_TOKEN")
TOKEN_SETTINGS = "https://github.com/settings/tokens"


@dataclass
class State:
    """What is known about gh's sign-in. ``scopes`` None: GitHub didn't say
    (a token that doesn't list them). ``error``: gh couldn't be asked at all
    (not installed, signed out, offline). ``token_var``: gh is using a token
    from that environment variable, which the command can't change."""
    scopes: Optional[set] = None
    login: str = ""
    error: str = ""
    token_var: str = ""

    @property
    def can_refresh(self) -> bool:
        """Whether gh auth refresh can add permissions here."""
        return not self.error and not self.token_var


def env_token() -> str:
    """The environment variable gh takes its token from, or ""."""
    return next((v for v in TOKEN_VARS if os.environ.get(v)), "")


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


def parse_reply(raw: str) -> tuple[Optional[set], str]:
    """The scopes in the X-OAuth-Scopes header of ``gh api -i user`` output
    (None with no such header: a fine-grained token has permissions but
    doesn't list them this way), and the login in its body."""
    head, _, body = raw.replace("\r\n", "\n").partition("\n\n")
    scopes = None
    for line in head.splitlines():
        name, _, value = line.partition(":")
        if name.strip().lower() == "x-oauth-scopes":
            scopes = {s.strip() for s in value.split(",") if s.strip()}
    try:
        login = (json.loads(body) or {}).get("login") or ""
    except (ValueError, AttributeError):
        login = ""
    return scopes, login


def parse_scopes(raw: str) -> Optional[set]:
    return parse_reply(raw)[0]


def fetch_state() -> State:
    """Ask GitHub, through gh, what its sign-in may do."""
    token_var = env_token()
    try:
        raw = gh_data._run_gh(["api", "-i", "user"])
    except gh_data.GhError as exc:
        first = str(exc).strip().splitlines()[0] if str(exc).strip() else "gh failed"
        return State(error=first, token_var=token_var)
    scopes, login = parse_reply(raw)
    return State(scopes=scopes, login=login, token_var=token_var)


def fetch_scopes() -> Optional[set]:
    """The scopes gh's sign-in has, or None when GitHub doesn't say."""
    return fetch_state().scopes


def summary(state: State, include_optional: bool) -> str:
    """The Permissions box's text: who, one line a permission, then what to do."""
    if state.error:
        return ("Couldn't ask GitHub which permissions gh has:\n" + state.error + "\n\n"
                "gh needs to be installed and signed in (gh auth login) first.")
    lines = []
    if state.login:
        lines.append(f"Account: {state.login}, the one gh is using now.")
    if state.token_var:
        lines.append(f"gh is using the token in the {state.token_var} environment variable, so "
                     "its permissions can't be added with gh. Change the token's permissions on "
                     f"GitHub instead, at {TOKEN_SETTINGS}.")
    elif state.scopes is None:
        lines.append("GitHub doesn't say which permissions gh's sign-in has, which happens "
                     "when gh signed in with a token. If it signed in through the browser, the "
                     "command below adds any it lacks and keeps the rest. If it uses a token, "
                     f"change the token's permissions on GitHub, at {TOKEN_SETTINGS}.")
    if lines:
        lines.append("")
    for p in PERMISSIONS:
        state_word = "unknown" if state.scopes is None else (
            "has it" if has(state.scopes, p) else "missing")
        extra = ", optional" if p.optional else ""
        lines.append(f"{p.scope}: {state_word}{extra}. {p.what}.")
    need = missing(state.scopes, include_optional)
    lines.append("")
    if not need:
        lines.append("gh has every permission GHManage uses.")
    elif state.scopes is not None:
        lines.append(f"Missing: {', '.join(p.scope for p in need)}.")
    return "\n".join(lines)


def refresh_command(state: State, include_optional: bool) -> str:
    """The command for the box, or "" where it can't help."""
    if not state.can_refresh:
        return ""
    return command([p.scope for p in missing(state.scopes, include_optional)])


def needed_text(doing: str, scope: str, detail: str = "", token_var: str = "") -> str:
    """The Permission Needed box's text. ``detail``: what GitHub said, when
    it may not be the permission at all (a 404 on following someone)."""
    lines = [detail or (f"{doing}. That needs gh's \"{scope}\" permission, which gh "
                        "doesn't ask for when you sign in.")]
    if token_var:
        lines += ["", f"gh is using the token in the {token_var} environment variable, so add "
                      f"the \"{scope}\" permission to that token on GitHub, at {TOKEN_SETTINGS}."]
    else:
        lines += ["", "Add it by running this in a terminal, then try again:", command([scope])]
    lines += ["", "Other features need permissions of their own. All Permissions lists them, "
                  "with one command for every one gh is missing."]
    return "\n".join(lines)
