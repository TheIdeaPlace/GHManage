"""A module-level name defined twice is a quiet bug: the later one wins.

gh_data once had a ``_login`` helper (security alerts) defined over the
``_login`` cache that ``current_login`` returns, so Activity asked GitHub for
the events of "<function _login …>"; and a second ``_login_of`` (discussions)
replaced the Activity one, turning a missing person into "ghost".
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MODULES = sorted(p.name for p in ROOT.glob("*.py"))


def _top_level_names(tree: ast.Module) -> list[str]:
    names = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names += [t.id for t in targets if isinstance(t, ast.Name)]
    return names


@pytest.mark.parametrize("name", MODULES)
def test_no_function_or_class_takes_over_another_top_level_name(name):
    tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
    defs = [n.name for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    names = Counter(_top_level_names(tree))
    clashes = sorted(d for d in set(defs) if names[d] > 1)
    assert not clashes, f"{name}: defined more than once: {clashes}"


def test_the_signed_in_login_cache_is_not_a_function():
    import gh_data
    assert gh_data._login is None or isinstance(gh_data._login, str)
    assert gh_data._login_of(None) == "" and gh_data._author_login(None) == "ghost"
