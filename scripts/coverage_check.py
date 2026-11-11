"""Compare a coverage run with the saved baseline, and flag where it dropped (#135).

    python scripts/coverage_check.py coverage.json                  # compare; exit 3 on a drop
    python scripts/coverage_check.py coverage.json --report out.md  # and write what it found
    python scripts/coverage_check.py coverage.json --accept         # make this run the baseline

``coverage.json`` is ``coverage json`` output from the weekly Coverage workflow, which measures
the tests on Windows and macOS and combines the two. The baseline,
``scripts/coverage-baseline.json``, changes only when someone accepts a run. Comparing with last
week instead would let a file lose a few points every week and never be flagged.

A drop is flagged when:
- the whole app's coverage falls more than TOTAL_DROP points;
- a file of at least MIN_STATEMENTS statements falls more than FILE_DROP points (in a small
  file one line is several points, so those are left to the next rule);
- any file, new ones included, gains MISSING_GROWTH or more statements no test runs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "scripts" / "coverage-baseline.json"

TOTAL_DROP = 1.0
FILE_DROP = 5.0
MIN_STATEMENTS = 50
MISSING_GROWTH = 25

# Not 1, which is also what Python exits with on an uncaught exception: the
# workflow must not take a crash for a drop.
EXIT_DROPPED = 3


def summarize(coverage_json: dict) -> dict:
    """The parts of ``coverage json`` output the baseline keeps."""
    def entry(summary: dict) -> dict:
        return {"statements": summary["num_statements"],
                "missing": summary["missing_lines"],
                "percent": round(summary["percent_covered"], 2)}
    return {"total": entry(coverage_json["totals"]),
            "files": {name.replace("\\", "/"): entry(data["summary"])
                      for name, data in sorted(coverage_json["files"].items())}}


def compare(baseline: dict, current: dict) -> tuple[list, list]:
    """(drops, gains): each a list of (file, before, after, why) lines for the report.

    ``before`` is None for a file the baseline doesn't have.
    """
    drops, gains = [], []
    before_total, after_total = baseline["total"], current["total"]
    if after_total["percent"] < before_total["percent"] - TOTAL_DROP:
        drops.append(("All files", before_total, after_total,
                      f"fell more than {TOTAL_DROP:g} point"))
    for name, after in current["files"].items():
        before = baseline["files"].get(name)
        old_missing = before["missing"] if before else 0
        if after["missing"] - old_missing >= MISSING_GROWTH:
            why = (f"{after['missing'] - old_missing} more statements untested" if before
                   else f"new file with {after['missing']} statements untested")
            drops.append((name, before, after, why))
        elif (before and before["statements"] >= MIN_STATEMENTS
              and after["percent"] < before["percent"] - FILE_DROP):
            drops.append((name, before, after, f"fell more than {FILE_DROP:g} points"))
        elif before and after["percent"] > before["percent"] + FILE_DROP:
            gains.append((name, before, after, "rose"))
    return drops, gains


def _percent(entry) -> str:
    return "new" if entry is None else f"{entry['percent']:.1f}%"


def report(drops: list, gains: list, baseline: dict, current: dict, run_url: str = "") -> str:
    lines = []
    total_before, total_after = baseline["total"]["percent"], current["total"]["percent"]
    lines.append(f"Coverage is **{total_after:.1f}%** (baseline {total_before:.1f}%, "
                 f"from {baseline.get('measured', 'an earlier run')}).")
    if run_url:
        lines.append(f"\nRun: {run_url} (the per-line HTML report is its `coverage-report` "
                     "download)")
    if drops:
        lines.append("\n## Dropped\n\n| File | Baseline | Now | Why |\n|---|---|---|---|")
        lines += [f"| `{n}` | {_percent(b)} | {_percent(a)} | {why} |"
                  for n, b, a, why in drops]
        gone = sorted(set(baseline["files"]) - set(current["files"]))
        if gone and any(b is None for _, b, _, _ in drops):
            lines.append("\nGone since the baseline, so a \"new\" file above may only have "
                         "moved: " + ", ".join(f"`{n}`" for n in gone) + ".")
        lines.append("\nAdd tests for the new code, or, if the drop is expected (code moved, "
                     "or tests removed on purpose), accept this run as the new baseline: "
                     "see COPILOT.md, \"Test coverage\". Tracked in #135.")
    else:
        lines.append("\nNo file dropped past the thresholds.")
    if gains:
        lines.append("\n## Rose\n\n| File | Baseline | Now |\n|---|---|---|")
        lines += [f"| `{n}` | {_percent(b)} | {_percent(a)} |" for n, b, a, _ in gains]
        lines.append("\nAccepting this run would raise the bar for these files.")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("coverage_json", type=Path)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--report", type=Path, help="write the findings here as markdown")
    parser.add_argument("--run-url", default="", help="the workflow run, for the report")
    parser.add_argument("--accept", action="store_true",
                        help="save this run as the baseline instead of comparing")
    parser.add_argument("--measured", default="",
                        help="with --accept: what was measured (commit, date)")
    args = parser.parse_args(argv)

    current = summarize(json.loads(args.coverage_json.read_text(encoding="utf-8")))
    if args.accept:
        if args.measured:
            current = {"measured": args.measured, **current}
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(json.dumps(current, indent=1) + "\n", encoding="utf-8")
        print(f"Baseline saved: {current['total']['percent']:.1f}% over "
              f"{len(current['files'])} files.")
        return 0

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    drops, gains = compare(baseline, current)
    text = report(drops, gains, baseline, current, args.run_url)
    if args.report:
        args.report.write_text(text, encoding="utf-8")
    print(text)
    return EXIT_DROPPED if drops else 0


if __name__ == "__main__":
    sys.exit(main())
