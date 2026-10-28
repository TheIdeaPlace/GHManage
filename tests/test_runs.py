"""Workflow runs: jobs, readable logs, what failed, rerun and cancel."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import gh_data
from gh_data import Annotation, JobStep, WorkflowJob, WorkflowRun


def test_clean_log_line():
    assert gh_data.clean_log_line("2026-08-17T14:56:22.3828850Z hello") == "hello"
    assert gh_data.clean_log_line("﻿2026-08-17T14:56:22.38Z ##[group]Run tests") == "Run tests"
    assert gh_data.clean_log_line("[command]/usr/bin/git fetch") == "Command: /usr/bin/git fetch"
    assert gh_data.clean_log_line("2026-08-17T14:56:22Z ##[error]Process completed with exit code 1.") == \
        "ERROR: Process completed with exit code 1."
    assert gh_data.clean_log_line("\x1b[36;1mif [ x ]; then\x1b[0m") == "if [ x ]; then"
    assert gh_data.clean_log_line("^[[36;1mfi^[[0m") == "fi"
    # Cursor and line codes progress bars use, which a screen reader reads out
    assert gh_data.clean_log_line("^[[?25l^[[2Kdone^[[?25h") == "done"
    assert gh_data.clean_log_line("\x1b[38:5:208mtext\x1b(B") == "text"
    assert gh_data.clean_log_line("\x1b]8;;https://x\x1b\\link\x1b]8;;\x1b\\") == "link"


def test_parse_run_log_groups_by_job_and_step():
    text = "\n".join([
        "build\tSet up\t2026-01-01T00:00:00Z one",
        "build\tSet up\t2026-01-01T00:00:01Z two",
        "build\tTest\t2026-01-01T00:00:02Z ##[error]boom\x0cafter a form feed",
        "the rest of a line a tool broke",
        "lint\tRun\t2026-01-01T00:00:03Z ok\r",
    ])
    assert gh_data.parse_run_log(text) == [
        ("build", "Set up", ["one", "two"]),
        ("build", "Test", ["ERROR: boom\x0cafter a form feed", "the rest of a line a tool broke"]),
        ("lint", "Run", ["ok"]),
    ]


def test_fetch_run_jobs(fake_gh):
    fake_gh.route("actions/runs/7/jobs", {"total_count": 1, "jobs": [{
        "id": 11, "name": "build", "status": "completed", "conclusion": "failure",
        "started_at": "2026-01-01T00:00:00Z", "completed_at": "2026-01-01T00:01:12Z",
        "html_url": "u", "steps": [
            {"number": 1, "name": "Set up", "status": "completed", "conclusion": "success"},
            {"number": 2, "name": "Test", "status": "completed", "conclusion": "failure"},
        ]}]})
    jobs = gh_data.fetch_run_jobs("o/r", 7)
    assert fake_gh.calls[0][-1] == "repos/o/r/actions/runs/7/jobs?per_page=100&page=1"
    job = jobs[0]
    assert (job.duration, job.to_row(["failed step"])["failed step"]) == ("1m 12s", "Test")


def test_fetch_run_jobs_reads_every_page(fake_gh):
    def page(args):
        n = int(args[-1].rsplit("=", 1)[1])
        count = 100 if n == 1 else 30
        return {"total_count": 130, "jobs": [{"id": n * 1000 + i, "name": f"j{i}"} for i in range(count)]}
    fake_gh.route("actions/runs/7/jobs", page)
    assert len(gh_data.fetch_run_jobs("o/r", 7)) == 130 and len(fake_gh.calls) == 2


def test_fetch_workflow_run(fake_gh):
    fake_gh.route("actions/runs/7", {"id": 7, "name": "CI", "status": "in_progress",
                                     "conclusion": None, "head_branch": "main", "run_number": 42})
    run = gh_data.fetch_workflow_run("o/r", 7)
    assert (run.status, run.conclusion, run.branch, run.run_number) == ("in_progress", "", "main", 42)


def test_failed_log_with_no_log_is_empty(fake_gh):
    fake_gh.route("--log-failed", gh_data.GhError("log not found: 7"))
    assert gh_data.fetch_failed_log("o/r", 7) == []


@pytest.mark.parametrize("fn, args, expected", [
    (gh_data.rerun_workflow_run, ("o/r", 7), ["run", "rerun", "7", "-R", "o/r"]),
    (gh_data.rerun_workflow_run, ("o/r", 7, True), ["run", "rerun", "7", "-R", "o/r", "--failed"]),
    (gh_data.cancel_workflow_run, ("o/r", 7), ["run", "cancel", "7", "-R", "o/r"]),
])
def test_rerun_and_cancel(fake_gh, fn, args, expected):
    fake_gh.route("run ", "")
    fn(*args)
    assert fake_gh.calls == [expected]


def test_annotations_failing_is_not_an_error(fake_gh):
    fake_gh.route("annotations", gh_data.GhError("HTTP 403"))
    assert gh_data.fetch_job_annotations("o/r", 11) == []


# ── Reports ─────────────────────────────────────────────────────────────

if os.environ.get("CI"):
    import wx  # noqa: F401
else:
    pytest.importorskip("wx")

import ghviewer  # noqa: E402

Frame = ghviewer.GhViewerFrame

RUN = WorkflowRun("CI", "completed", "failure", "main", "push", "", run_number=42, run_id=7)


def _job(name, conclusion, failed_step=None, id=1):
    steps = [JobStep(1, "Set up", "completed", "success")]
    if failed_step:
        steps.append(JobStep(2, failed_step, "completed", "failure"))
    return WorkflowJob(id, name, "completed", conclusion, "2026-01-01T00:00:00Z",
                       "2026-01-01T00:00:30Z", steps=steps)


def test_failure_report():
    jobs = [_job("build", "failure", "Test", id=1), _job("lint", "success", id=2)]
    notes = {1: [Annotation("failure", "exit code 1", ".github", 323),
                 Annotation("warning", "Node 20 is deprecated"),
                 Annotation("failure", "assert 1 == 2", "tests/test_x.py", 12, "test_x")]}
    log = [("build", "Test", [f"line {i}" for i in range(100)] + ["ERROR: exit code 1"]),
           ("lint", "Run", ["unrelated"])]
    text = ghviewer.format_failure_report(RUN, jobs, notes, log)
    lines = text.splitlines()
    assert lines[0] == "Run #42 CI on main — failure"
    assert lines[1] == "1 of 2 jobs failed: build."
    assert 'Job build — failure at step "Test" after 30s' in lines
    assert "  exit code 1" in lines            # ".github" line numbers point into the raw log
    assert "  tests/test_x.py line 12: test_x: assert 1 == 2" in lines
    assert not any("Node 20" in ln for ln in lines)          # warnings left out
    assert 'Last 40 lines of "Test":' in lines
    assert lines.count("  ERROR: exit code 1") == 1 and "  line 60" not in lines
    assert "unrelated" not in text                             # lint didn't fail


def test_failure_report_with_nothing_failed():
    text = ghviewer.format_failure_report(RUN, [_job("build", "success")], {}, [])
    assert text.splitlines()[1] == "No job failed."


def test_job_log_opens_at_the_first_error():
    job = _job("build", "failure", "Test")
    text, line = ghviewer.format_job_log(job, [("build", "Set up", ["ok 🎉"]),
                                               ("build", "Test", ["running", "ERROR: boom"])])
    assert text.splitlines()[line] == "ERROR: boom"
    assert "── Step: Test ──" in text


def test_a_long_job_log_keeps_its_end(monkeypatch):
    monkeypatch.setattr(ghviewer, "JOB_LOG_MAX_LINES", 10)
    job = _job("build", "success")
    text, line = ghviewer.format_job_log(job, [("build", "S", [f"l{i}" for i in range(50)])])
    assert "left out" in text.splitlines()[1] and text.endswith("l49") and line == 0


# ── Guards ──────────────────────────────────────────────────────────────


def _frame(view, item):
    f = SimpleNamespace(view_mode=view, jobs_run=None, repo="o/r", announced=[])
    f._announce = f.announced.append
    f._focused_item = lambda: item
    f._focused_run = lambda: Frame._focused_run(f)
    return f


def test_cancel_a_finished_run_says_so():
    f = _frame(ghviewer.VIEW_WORKFLOW, RUN)
    Frame._cancel_run(f)
    assert f.announced == ["Run #42 has already finished."]


def test_rerun_a_running_run_says_so():
    running = WorkflowRun("CI", "in_progress", "", "main", "push", "", run_number=43, run_id=8)
    f = _frame(ghviewer.VIEW_WORKFLOW, running)
    Frame._rerun_run(f)
    assert f.announced == ["Run #43 hasn't finished; cancel it (X) or wait."]


def test_what_failed_on_a_success_needs_no_report():
    ok = WorkflowRun("CI", "completed", "success", "main", "push", "", run_number=44, run_id=9)
    f = _frame(ghviewer.VIEW_WORKFLOW, ok)
    Frame._show_what_failed(f)
    assert f.announced == ["Nothing failed in run #44 — it succeeded."]


def test_in_jobs_the_run_is_the_one_drilled_into():
    f = _frame(ghviewer.VIEW_JOBS, _job("build", "failure"))
    f.jobs_run = RUN
    assert Frame._focused_run(f) is RUN


def test_jobs_view_is_a_drill_down_of_runs():
    assert ghviewer.PARENT_VIEW[ghviewer.VIEW_JOBS] == ghviewer.VIEW_WORKFLOW


def test_cancelled_jobs_are_not_failures():
    jobs = [_job("test (3.12)", "failure", "Run", id=1)] + [
        _job(f"test ({v})", "cancelled", id=10 + i) for i, v in enumerate(["3.10", "3.11"])]
    lines = ghviewer.format_failure_report(RUN, jobs, {}, []).splitlines()
    assert lines[1] == "1 of 3 jobs failed: test (3.12)."
    assert lines[2].startswith("2 cancelled, often because another job failed first: test (3.10)")
    assert sum(1 for ln in lines if ln.startswith("Job ")) == 1


def test_a_run_with_no_jobs():
    text = ghviewer.format_failure_report(RUN, [], {}, [])
    assert "before any job started" in text.splitlines()[1]


def test_unknown_step_is_named_for_what_it_is():
    job = _job("build", "failure", "Test")
    log = [("build", ghviewer.UNKNOWN_STEP, ["a", "ERROR: x"])]
    report = ghviewer.format_failure_report(RUN, [job], {}, log)
    assert 'the job\'s log (it failed at "Test")' in report
    text, line = ghviewer.format_job_log(job, log)
    assert "UNKNOWN STEP" not in text and text.splitlines()[line] == "ERROR: x"


def test_a_short_step_with_blank_lines_is_shown_whole():
    job = _job("build", "failure", "Test")
    report = ghviewer.format_failure_report(RUN, [job], {}, [("build", "Test", ["a", "", "b"])])
    assert 'Log of "Test":' in report


def test_enter_on_a_skipped_job_says_so():
    f = _frame(ghviewer.VIEW_JOBS, None)
    f.jobs_run = RUN
    f._tell = lambda msg, *a, **k: f.announced.append(msg)
    Frame._show_job_log(f, _job("release", "skipped"))
    assert f.announced == ["release was skipped, so it has no log."]


def test_a_second_report_waits_for_the_first():
    f = _frame(ghviewer.VIEW_WORKFLOW, RUN)
    f._report_busy = True
    Frame._show_what_failed(f)
    assert f.announced == ["Still putting the last report together."]


def test_jobs_load_takes_the_run_as_it_is_now():
    f = SimpleNamespace(jobs_run=RUN, events=[])
    f._fetch_is_current = lambda t: True
    f._on_git_items_loaded = lambda t, jobs, kind: f.events.append(kind)
    fresh = WorkflowRun("CI", "in_progress", "", "main", "push", "", run_number=42, run_id=7)
    Frame._on_jobs_loaded(f, 1, [], fresh)
    assert f.jobs_run is fresh and f.events == ["jobs"]
