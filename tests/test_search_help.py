"""The Search dialog's operator help (#45)."""

from __future__ import annotations

import pytest

import search_help
from saved_searches import KIND_ISSUES, KIND_REPOS


@pytest.mark.parametrize("kind", [KIND_ISSUES, KIND_REPOS])
def test_every_operator_has_a_meaning_and_an_example_that_uses_it(kind):
    ops = search_help.operators_for(kind)
    assert ops and len({o.op for o in ops}) == len(ops)
    for o in ops:
        assert o.meaning
        assert o.op.lstrip("-").rstrip(":") in o.example


def test_each_kind_has_its_own_operators_and_documentation():
    issue_ops = {o.op for o in search_help.operators_for(KIND_ISSUES)}
    repo_ops = {o.op for o in search_help.operators_for(KIND_REPOS)}
    assert "review-requested:" in issue_ops and "review-requested:" not in repo_ops
    assert "stars:" in repo_ops and "stars:" not in issue_ops
    assert search_help.DOCS[KIND_ISSUES] != search_help.DOCS[KIND_REPOS]


def test_filter_matches_operator_meaning_or_example():
    ops = search_help.operators_for(KIND_ISSUES)
    assert [o.op for o in search_help.matching(ops, "REVIEW")][:1] == ["review-requested:"]
    assert any(o.op == "-label:" for o in search_help.matching(ops, "excludes"))
    assert search_help.matching(ops, "  ") == ops


LABEL = search_help.Operator("label:", "Has a label", "label:bug")
OPEN = search_help.Operator("is:open", "Open", "is:open")


@pytest.mark.parametrize("query, at, op, expected, cursor", [
    ("", 0, OPEN, "is:open ", 8),
    ("crash", 5, LABEL, "crash label:", 12),       # a space before, value to type after
    ("crash ", 6, OPEN, "crash is:open ", 14),
    ("crash repo:o/r", 5, OPEN, "crash is:open repo:o/r", 13),
    ("x", 99, LABEL, "x label:", 8),             # past the end: at the end
])
def test_insert_operator_at_the_cursor(query, at, op, expected, cursor):
    assert search_help.insert_operator(query, at, op) == (expected, cursor)
