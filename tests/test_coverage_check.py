"""Tests for scripts/coverage_check.py, the weekly coverage check's comparison with
its baseline (#135)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "coverage_check", ROOT / "scripts" / "coverage_check.py")
coverage_check = importlib.util.module_from_spec(_spec)
sys.modules["coverage_check"] = coverage_check
_spec.loader.exec_module(coverage_check)


def _summary(statements, missing):
    covered = statements - missing
    return {"num_statements": statements, "missing_lines": missing,
            "percent_covered": 100.0 * covered / statements if statements else 100.0}


def _coverage_json(files):
    """``coverage json`` output with {name: (statements, missing)}."""
    total_statements = sum(s for s, _ in files.values())
    total_missing = sum(m for _, m in files.values())
    return {"totals": _summary(total_statements, total_missing),
            "files": {name: {"summary": _summary(s, m)} for name, (s, m) in files.items()}}


def _check(before, after):
    return coverage_check.compare(coverage_check.summarize(_coverage_json(before)),
                                  coverage_check.summarize(_coverage_json(after)))


BIG = {"gh_data.py": (1000, 100), "ghviewer.py": (2000, 0)}


def test_no_change_flags_nothing():
    assert _check(BIG, BIG) == ([], [])


def test_large_file_falling_more_than_five_points_is_flagged():
    files = {"mid.py": (200, 20), "other.py": (20000, 0)}
    worse = dict(files, **{"mid.py": (200, 32)})  # 90% to 84%, 12 more missing
    drops, _ = _check(files, worse)
    assert [(name, why) for name, _, _, why in drops] == [
        ("mid.py", "fell more than 5 points")]


def test_small_file_dropping_a_line_or_two_is_not_flagged():
    files = {"tiny.py": (10, 0), "other.py": (5000, 0)}
    drops, _ = _check(files, dict(files, **{"tiny.py": (10, 3)}))
    assert drops == []


def test_many_new_untested_statements_are_flagged_even_in_a_small_drop():
    files = {"huge.py": (5000, 100), "other.py": (50000, 0)}
    drops, _ = _check(files, dict(files, **{"huge.py": (5100, 130)}))
    assert [why for *_, why in drops] == ["30 more statements untested"]


def test_new_file_is_flagged_only_with_much_untested():
    with_new = dict(BIG, **{"new.py": (40, 30)})
    drops, _ = _check(BIG, with_new)
    assert [(name, before, why) for name, before, _, why in drops] == [
        ("new.py", None, "new file with 30 statements untested")]
    assert _check(BIG, dict(BIG, **{"new.py": (40, 5)})) == ([], [])


def test_total_falling_more_than_a_point_is_flagged():
    files = {f"m{i}.py": (40, 0) for i in range(50)}
    worse = {name: (40, 4) for name in files}  # each small file loses 10 points
    drops, _ = _check(files, worse)
    assert [name for name, *_ in drops] == ["All files"]


def test_removed_file_is_ignored_and_gains_are_reported():
    better = {"gh_data.py": (1000, 10)}
    drops, gains = _check(BIG, better)
    assert drops == []
    assert [name for name, *_ in gains] == ["gh_data.py"]


def test_windows_paths_match_the_baseline():
    current = coverage_check.summarize(_coverage_json({"sub\\x.py": (10, 1)}))
    assert list(current["files"]) == ["sub/x.py"]


def test_accept_then_compare_round_trip(tmp_path, capsys):
    run = tmp_path / "coverage.json"
    baseline = tmp_path / "baseline.json"
    run.write_text(json.dumps(_coverage_json(BIG)), encoding="utf-8")
    assert coverage_check.main([str(run), "--baseline", str(baseline), "--accept",
                                "--measured", "abc1234, 2026-11-11"]) == 0
    assert json.loads(baseline.read_text(encoding="utf-8"))["measured"] == "abc1234, 2026-11-11"

    run.write_text(json.dumps(_coverage_json({"gh_data.py": (1000, 200),
                                              "ghviewer.py": (2000, 0)})),
                   encoding="utf-8")
    out = tmp_path / "report.md"
    assert coverage_check.main([str(run), "--baseline", str(baseline), "--report", str(out),
                                "--run-url", "https://example.invalid/run/1"]
                               ) == coverage_check.EXIT_DROPPED
    text = out.read_text(encoding="utf-8")
    assert "`gh_data.py`" in text and "abc1234, 2026-11-11" in text
    assert "https://example.invalid/run/1" in text


def test_report_names_files_gone_when_a_new_one_is_flagged():
    moved = {"moved.py": (1000, 100), "ghviewer.py": (2000, 0)}
    baseline = coverage_check.summarize(_coverage_json(BIG))
    current = coverage_check.summarize(_coverage_json(moved))
    drops, gains = coverage_check.compare(baseline, current)
    assert [why for *_, why in drops] == ["new file with 100 statements untested"]
    assert "may only have moved: `gh_data.py`" in coverage_check.report(
        drops, gains, baseline, current)
