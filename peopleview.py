"""A person's profile as text to read in the details panel (no wx), and the
names of the People lists.

People I Follow, My Followers, someone's followers and the people they
follow, and View User (#25) all list Person rows; this is what selecting one
shows. One line out per line in, the address alone on the line after "URL:"
as everywhere else in GHManage.
"""

from __future__ import annotations

import re

from gh_data import BlameRange, Commit, Person

RULE = "─" * 60


def _n(value) -> str:
    return f"{value:,}"


def connection_sentence(p: Person) -> str:
    """How you and they are connected, as a sentence; "" for an
    organization, where following isn't shown."""
    if p.is_org:
        return ""
    if p.is_viewer:
        return "This is you."
    return {
        "you follow each other": "You follow each other.",
        "you follow them": "You follow them.",
        "follows you": "They follow you.",
    }.get(p.connection, "You don't follow each other.")


def person_details(p: Person) -> str:
    lines = [f"{'Organization' if p.is_org else 'User'}: {p.title}"]
    if p.pronouns:
        lines.append(f"Pronouns: {p.pronouns}")
    if p.status:
        lines.append(f"Status: {p.status}")
    said = connection_sentence(p)
    if said:
        lines.append(said)
    if p.company:
        lines.append(f"Company: {p.company}")
    if p.location:
        lines.append(f"Location: {p.location}")
    if p.website:
        lines.append(f"Website: {p.website}")
    if p.twitter:
        lines.append(f"X (Twitter): @{p.twitter}")
    if p.email:
        lines.append(f"Email: {p.email}")
    if p.followers is not None:
        lines.append(f"Followers: {_n(p.followers)}")
    if p.following is not None:
        lines.append(f"Following: {_n(p.following)}")
    # Yours, from your profile, count the private ones too.
    lines.append(f"Repositories: {_n(p.repos)}{' public' if p.repos_public else ''}")
    if p.starred is not None:
        lines.append(f"Starred: {_n(p.starred)}")
    if p.created_at:
        lines.append(f"Joined: {p.created_at[:10]}")
    lines.append("URL:")
    lines.append(p.url or "(none)")
    lines.append("")
    lines.append(RULE)
    lines.append("")
    lines.extend(p.bio.splitlines() or ["(no bio)" if not p.is_org else "(no description)"])
    return "\n".join(lines)


def possessive(login: str) -> str:
    """``alice's``; ``james'`` for a name ending in s."""
    return f"{login}'" if login.lower().endswith("s") else f"{login}'s"


def people_label(kind: str, login: str = "", lower: bool = False) -> str:
    """The name of a list of people: People I Follow, My Followers,
    alice's Followers, People alice Follows; for View User ("user"), the
    person. ``lower`` for "back to …", keeping the login as it is."""
    if kind == "user":
        return login
    if kind in ("stargazers", "watchers"):
        what = kind if lower else kind.capitalize()
        return f"{what} of {login}"
    if not login:
        label = "People I Follow" if kind == "following" else "My Followers"
        if lower:
            return "people you follow" if kind == "following" else "your followers"
        return label
    if kind == "following":
        return f"people {login} follows" if lower else f"People {login} Follows"
    return f"{possessive(login)} {'followers' if lower else 'Followers'}"


def repos_label(kind: str, login: str, lower: bool = False, mine: bool = False) -> str:
    """``alice's Repositories``, ``alice's Starred Repositories``; a
    repository's forks, ``Forks of o/r``."""
    if kind == "forks":
        return f"{'forks' if lower else 'Forks'} of {login}"
    whose = "your" if mine and lower else ("Your" if mine else possessive(login))
    what = "Starred Repositories" if kind == "starred" else "Repositories"
    return f"{whose} {what.lower() if lower else what}"


def activity_label(login: str, lower: bool = False) -> str:
    """``alice's Activity``: what one person has done in public lately."""
    return f"{possessive(login)} {'activity' if lower else 'Activity'}"


def person_keys(people: list[Person]) -> str:
    """The status bar's hints for the keys that work on these people: none
    of an organization's but A, and no Insert or Delete on yourself alone."""
    if not people:
        return ""
    if all(p.is_org for p in people):
        return "A=activity"
    keys = "O=followers  W=following  S=starred  A=activity"
    if any(not p.is_org and not p.is_viewer for p in people):
        keys += "  Insert=follow  Delete=unfollow"
    return keys


def empty_text(kind: str, login: str = "") -> str:
    """What an empty list of people says."""
    if kind == "stargazers":
        return f"Nobody has starred {login}."
    if kind == "watchers":
        return f"Nobody watches {login}."
    if kind == "following":
        return f"{login} doesn't follow anyone." if login else "You don't follow anyone yet."
    return f"Nobody follows {login} yet." if login else "Nobody follows you yet."


def status_message(kind: str, login: str, people: list[Person], limit: int) -> str:
    """``People I Follow — 94 people.``, with the way to more when a full
    page came back."""
    label = people_label(kind, login)
    n = len(people)
    if kind == "user":
        if not people:
            return f"There's no GitHub user called {login}."
        p = people[0]
        return f"{'Organization' if p.is_org else 'User'} {p.title}."
    if not n:
        return f"{label} — {empty_text(kind, login)}"
    more = " Ctrl++ loads more." if n >= limit else ""
    return f"{label} — {n:,} {'person' if n == 1 else 'people'}.{more}"


# A GitHub login: letters, digits and single hyphens, up to 39, no hyphen first.
_LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")


def is_login(text: str) -> bool:
    """Whether ``text`` could be a GitHub user name."""
    return bool(_LOGIN.fullmatch(text or ""))


def people_of(item, repo: str = "") -> list[tuple[str, str]]:
    """The people an item names, for View User to offer: (login, what they
    are to it), the first the likeliest, each once. Display names (a commit's
    author) aren't logins and are left out; with nobody on the item, the
    repository's owner."""
    found: list[tuple[str, str]] = []

    def add(login, role: str) -> None:
        login = (login or "").strip().lstrip("@")
        if is_login(login) and login.lower() not in ("ghost", "unknown") and all(
                login.lower() != have.lower() for have, _ in found):
            found.append((login, role))

    login = getattr(item, "login", "")
    if isinstance(login, str):
        add(login, "")
    if not isinstance(item, (Commit, BlameRange)):
        # A commit's author is the name in git, not a GitHub user name:
        # "Kelly" would open a stranger's profile.
        add(getattr(item, "author", ""), "author")
    add(getattr(item, "actor", ""), "")
    add(getattr(item, "creator", ""), "creator")
    add(getattr(item, "pusher", ""), "pushed it")
    add(getattr(item, "answer_author", ""), "answered")
    for who in getattr(item, "assignees", None) or []:
        add(who, "assigned")
    for comment in getattr(item, "comment_list", None) or []:
        add(comment.get("author", "") if isinstance(comment, dict) else "", "commented")
    # A discussion's comments; an issue's "comments" is only their count.
    comments = getattr(item, "comments", None)
    for comment in comments if isinstance(comments, list) else []:
        add(getattr(comment, "author", ""), "commented")
        for reply in getattr(comment, "replies", None) or []:
            add(getattr(reply, "author", ""), "replied")
    if getattr(item, "section", "") == "Contributor":
        add(getattr(item, "name", ""), "contributor")
    owner = getattr(item, "owner", "")
    if isinstance(owner, str):
        add(owner, "owner")
    item_repo = getattr(item, "repo", "")
    for name in (item_repo if isinstance(item_repo, str) else "", repo or ""):
        if "/" in name:
            add(name.split("/", 1)[0], "owner")
    return found
