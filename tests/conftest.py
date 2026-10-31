"""Shared fixtures.

Nothing here talks to GitHub. ``fake_gh`` replaces ``gh_data._run_gh`` — the
single point every gh call goes through — with a scripted responder, and
``app_data`` points favorites and pinned repos at a temporary folder so the
tests never read or overwrite the real ones in %APPDATA%.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gh_data  # noqa: E402
import settings  # noqa: E402

# Kept before any fixture swaps it out, for the tests of _run_gh itself.
_REAL_RUN_GH = gh_data._run_gh
_REAL_GRAPHQL = gh_data._graphql


class FakeGh:
    """Stands in for the gh CLI.

    ``route(match, reply)`` registers a reply for any call whose arguments,
    joined with spaces, contain ``match``. The reply is a string, something
    JSON-serialisable, an exception to raise, or a callable taking the args.
    Routes are tried in the order added, then the fallbacks. A call nothing
    matches fails the test. Every call is kept in ``calls``.
    """

    def __init__(self) -> None:
        self.routes: list[tuple[str, object]] = []
        self.fallbacks: list[tuple[str, object]] = []
        self.calls: list[list[str]] = []
        self.stdin: list[Optional[str]] = []  # what each call was fed, in step with calls

    def route(self, match: str, reply: object) -> "FakeGh":
        self.routes.append((match, reply))
        return self

    def __call__(self, args: list[str], stdin: Optional[str] = None) -> str:
        self.calls.append(list(args))
        self.stdin.append(stdin)
        joined = " ".join(args)
        for match, reply in self.routes + self.fallbacks:
            if match in joined:
                if callable(reply) and not isinstance(reply, BaseException):
                    reply = reply(args)
                if isinstance(reply, BaseException):
                    raise reply
                if isinstance(reply, str):
                    return reply
                return json.dumps(reply)
        raise AssertionError(f"unexpected gh call: gh {joined}")

    def called_with(self, fragment: str) -> list[list[str]]:
        return [c for c in self.calls if fragment in " ".join(c)]


def _no_real_gh(args, stdin=None):
    raise AssertionError(
        f"test reached the real gh CLI: gh {' '.join(args)} — use the fake_gh fixture"
    )


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path_factory):
    """Applies to every test: no real gh, no real %APPDATA%.

    A test that forgets ``fake_gh`` fails loudly instead of running the
    signed-in gh on the developer's machine, and anything that writes
    favorites, pinned repos or the update log lands in a temp folder.
    """
    monkeypatch.setattr(gh_data, "_run_gh", _no_real_gh)
    # GraphQL bypasses _run_gh (it needs the output of a failed run), so it
    # is shut off separately: it answers with no data, which leaves PR titles
    # blank. Tests about titles install their own via the `graphql` fixture.
    monkeypatch.setattr(gh_data, "_graphql", lambda query: {"data": {}})
    monkeypatch.setattr(gh_data, "_gh_exe", None)
    monkeypatch.setattr(gh_data, "_default_branches", {})  # looked up afresh per test
    monkeypatch.setattr(settings, "_session", {})  # each test starts with no choices made
    monkeypatch.delenv("GHMANAGE_GH_PATH", raising=False)
    # Not whichever screen reader the developer happens to be running.
    import speech
    monkeypatch.setattr(speech, "jaws_running", lambda: False)
    home = tmp_path_factory.mktemp("appdata")
    monkeypatch.setenv("APPDATA", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))


@pytest.fixture
def real_run_gh():
    """The genuine _run_gh. Only for tests that also patch subprocess.run."""
    return _REAL_RUN_GH


@pytest.fixture
def real_graphql():
    """The genuine _graphql. Only for tests that also patch subprocess.run."""
    return _REAL_GRAPHQL


@pytest.fixture
def fake_gh(monkeypatch) -> FakeGh:
    fake = FakeGh()
    # Every issue/PR/label call first asks whether the repo is a fork. Say no
    # unless the test routes that call itself.
    fake.fallbacks.append(("isFork,parent", {"isFork": False}))
    monkeypatch.setattr(gh_data, "_run_gh", fake)
    return fake


@pytest.fixture
def app_data(monkeypatch, tmp_path) -> Path:
    import favorites
    import pinned_repos

    monkeypatch.setattr(favorites, "_app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(pinned_repos, "_app_data_dir", lambda: tmp_path)
    return tmp_path
