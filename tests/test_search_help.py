"""The Search dialog's qualifier help (#45)."""

from __future__ import annotations

import pytest

import search_help
from saved_searches import KIND_ISSUES, KIND_REPOS


@pytest.mark.parametrize("kind", [KIND_ISSUES, KIND_REPOS])
def test_every_qualifier_has_a_meaning_and_an_example_that_uses_it(kind):
    ops = search_help.qualifiers_for(kind)
    assert ops and len({o.op for o in ops}) == len(ops)
    for o in ops:
        assert o.meaning
        assert o.op.lstrip("-").rstrip(":") in o.example


def test_each_kind_has_its_own_qualifiers_and_documentation():
    issue_ops = {o.op for o in search_help.qualifiers_for(KIND_ISSUES)}
    repo_ops = {o.op for o in search_help.qualifiers_for(KIND_REPOS)}
    assert "review-requested:" in issue_ops and "review-requested:" not in repo_ops
    assert "stars:" in repo_ops and "stars:" not in issue_ops
    assert search_help.DOCS[KIND_ISSUES] != search_help.DOCS[KIND_REPOS]


def test_filter_matches_qualifier_meaning_or_example():
    ops = search_help.qualifiers_for(KIND_ISSUES)
    assert [o.op for o in search_help.matching(ops, "REVIEW")][:1] == ["review-requested:"]
    assert any(o.op == "-label:" for o in search_help.matching(ops, "excludes"))
    assert search_help.matching(ops, "  ") == ops


LABEL = search_help.Qualifier("label:", "Has a label", "label:bug")
OPEN = search_help.Qualifier("is:open", "Open", "is:open")


@pytest.mark.parametrize("query, at, op, expected, cursor", [
    ("", 0, OPEN, "is:open ", 8),
    ("crash", 5, LABEL, "crash label:", 12),       # a space before, value to type after
    ("crash ", 6, OPEN, "crash is:open ", 14),
    ("crash repo:o/r", 5, OPEN, "crash is:open repo:o/r", 13),
    ("x", 99, LABEL, "x label:", 8),             # past the end: at the end
    # The whole last query selected: Windows puts the cursor at its start
    ("crash", 0, LABEL, "label: crash", 6),
    # Inside a word: after the word, not into it
    ("braille", 4, OPEN, "braille is:open ", 16),
])
def test_insert_qualifier_at_the_cursor(query, at, op, expected, cursor):
    assert search_help.insert_qualifier(query, at, op) == (expected, cursor)


def test_f1_in_the_search_dialog_is_help_not_qualifiers(monkeypatch):
    # F1 is help everywhere; the qualifiers are Alt+Q (Insert Qualifier…).
    import os
    from types import SimpleNamespace
    if not os.environ.get("CI"):
        pytest.importorskip("wx")
    import ghviewer
    opened, shown = [], []
    monkeypatch.setattr(ghviewer.webbrowser, "open", lambda url: opened.append(url))
    d = SimpleNamespace(_show_qualifiers=lambda: shown.append(1))
    event = SimpleNamespace(GetKeyCode=lambda: ghviewer.wx.WXK_F1,
                            HasAnyModifiers=lambda: False, Skip=lambda: None)
    ghviewer.SearchDialog._on_char_hook(d, event)
    assert opened == [ghviewer.USER_GUIDE_URL + "#searching-github"] and shown == []
