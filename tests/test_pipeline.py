"""Integration tests for orchestrator.pipeline.run_pipeline.

These exercise the full orchestration flow end to end, spawning real
subprocesses via ``sys.executable`` (small ``python -c`` snippets) and asserting
on the resulting on-disk state: workspace archival, checkpoints and quarantine.
"""

import json
import sys
from pathlib import Path

import pytest

from orchestrator.checkpoint import load_checkpoint, save_checkpoint
from orchestrator.config import load_config
from orchestrator.models import CheckpointState, PipelineStatus, StepStatus
from orchestrator.pipeline import run_pipeline
from orchestrator.workspace import (
    CHECKPOINT_DIR_NAME,
    CURRENT_DIR_NAME,
)


# --------------------------- step builders --------------------------- #

_APPEND_CODE = (
    "import sys,pathlib;"
    "pathlib.Path(sys.argv[1]).open('a',encoding='utf-8').write(sys.argv[2]+'\\n')"
)
_FAIL_CODE = "import sys; sys.exit(2)"


def _append_step(name, marker, *, order, critical=False, active=True, output=None):
    kwargs = {}
    if output is not None:
        kwargs["output"] = str(output)
    return {
        "name": name,
        "order": order,
        "is_active": active,
        "is_critical": critical,
        "command_to_run": sys.executable,
        "args": ["-c", _APPEND_CODE, str(marker), name],
        "kwargs": kwargs,
    }


def _fail_step(name, *, order, critical, active=True, output=None):
    kwargs = {}
    if output is not None:
        kwargs["output"] = str(output)
    return {
        "name": name,
        "order": order,
        "is_active": active,
        "is_critical": critical,
        "command_to_run": sys.executable,
        "args": ["-c", _FAIL_CODE],
        "kwargs": kwargs,
    }


def _marker_lines(marker: Path):
    if not marker.exists():
        return []
    return [ln for ln in marker.read_text(encoding="utf-8").splitlines() if ln]


def _dated_dirs(working_folder: Path):
    return sorted(
        p.name
        for p in working_folder.iterdir()
        if p.is_dir() and p.name != CURRENT_DIR_NAME
    )


# --------------------------- happy path --------------------------- #

def test_full_pipeline_success(make_config, working_folder, tmp_path):
    marker = tmp_path / "marker.txt"
    steps = [
        _append_step("step_a", marker, order=1),
        _append_step("step_b", marker, order=2),
        _append_step("step_c", marker, order=3),
    ]
    path = make_config(steps=steps)

    ok = run_pipeline(str(path))

    assert ok is True
    assert _marker_lines(marker) == ["step_a", "step_b", "step_c"]
    # current archived to a dated directory; current removed
    assert not (working_folder / CURRENT_DIR_NAME).exists()
    assert len(_dated_dirs(working_folder)) == 1
    # checkpoint cleared on success
    ck_dir = working_folder / _dated_dirs(working_folder)[0] / CHECKPOINT_DIR_NAME
    assert load_checkpoint(str(path), ck_dir) is None


def test_inactive_steps_are_skipped(make_config, working_folder, tmp_path):
    marker = tmp_path / "marker.txt"
    steps = [
        _append_step("step_a", marker, order=1),
        _append_step("step_b", marker, order=2, active=False),
        _append_step("step_c", marker, order=3),
    ]
    path = make_config(steps=steps)

    ok = run_pipeline(str(path))

    assert ok is True
    assert _marker_lines(marker) == ["step_a", "step_c"]


def test_no_active_steps_returns_true_without_workspace(make_config, working_folder, tmp_path):
    marker = tmp_path / "marker.txt"
    steps = [_append_step("only", marker, order=1, active=False)]
    path = make_config(steps=steps)

    ok = run_pipeline(str(path))

    assert ok is True
    assert _marker_lines(marker) == []
    # nothing to do -> no working folder created
    assert not working_folder.exists()


# --------------------------- failure handling --------------------------- #

def test_critical_failure_quarantines_and_stops(make_config, working_folder, tmp_path):
    marker = tmp_path / "marker.txt"
    data_file = tmp_path / "payload.csv"
    data_file.write_text("bad,data\n", encoding="utf-8")
    steps = [
        _append_step("step_a", marker, order=1),
        _fail_step("step_bad", order=2, critical=True, output=data_file),
        _append_step("step_c", marker, order=3),
    ]
    path = make_config(steps=steps)

    ok = run_pipeline(str(path))

    assert ok is False
    # step_c must NOT have run
    assert _marker_lines(marker) == ["step_a"]
    # current is retained (not archived) for inspection
    assert (working_folder / CURRENT_DIR_NAME).exists()

    # checkpoint reflects the quarantined state
    ck_dir = working_folder / CURRENT_DIR_NAME / CHECKPOINT_DIR_NAME
    ck = load_checkpoint(str(path), ck_dir)
    assert ck is not None
    assert ck.pipeline_status == PipelineStatus.QUARANTINED
    assert "step_bad" in ck.quarantined_steps

    # quarantine entry with report + copied data next to the config file
    quarantine_root = path.parent / "quarantine"
    entries = list(quarantine_root.iterdir())
    assert len(entries) == 1
    entry = entries[0]
    assert (entry / "failure_report.json").exists()
    assert (entry / "payload.csv").exists()
    report = json.loads((entry / "failure_report.json").read_text(encoding="utf-8"))
    assert report["step_name"] == "step_bad"
    assert report["exit_code"] == 2


def test_noncritical_failure_continues_but_reports_false(make_config, working_folder, tmp_path):
    marker = tmp_path / "marker.txt"
    steps = [
        _append_step("step_a", marker, order=1),
        _fail_step("step_soft", order=2, critical=False),
        _append_step("step_c", marker, order=3),
    ]
    path = make_config(steps=steps)

    ok = run_pipeline(str(path))

    assert ok is False
    # subsequent steps still run despite the non-critical failure
    assert _marker_lines(marker) == ["step_a", "step_c"]
    # pipeline failed -> not archived, current retained
    assert (working_folder / CURRENT_DIR_NAME).exists()
    ck_dir = working_folder / CURRENT_DIR_NAME / CHECKPOINT_DIR_NAME
    ck = load_checkpoint(str(path), ck_dir)
    assert ck is not None
    assert ck.pipeline_status == PipelineStatus.FAILED
    assert ck.step_statuses["step_soft"] == StepStatus.FAILED


# --------------------------- dry run --------------------------- #

def test_dry_run_executes_no_steps_and_does_not_archive(make_config, working_folder, tmp_path):
    marker = tmp_path / "marker.txt"
    steps = [
        _append_step("step_a", marker, order=1),
        _append_step("step_b", marker, order=2),
    ]
    path = make_config(steps=steps)

    ok = run_pipeline(str(path), dry_run=True)

    assert ok is True
    # no subprocess is spawned during a dry run
    assert _marker_lines(marker) == []
    # nothing is archived into a dated directory
    assert _dated_dirs(working_folder) == []


@pytest.mark.xfail(
    reason=(
        "KNOWN BUG: run_pipeline saves a checkpoint at the end even for a dry "
        "run, so the working folder is created despite the 'disk left untouched' "
        "contract documented in pipeline.run_pipeline / prepare_workspace."
    ),
    strict=True,
)
def test_dry_run_should_not_touch_disk(make_config, working_folder, tmp_path):
    marker = tmp_path / "marker.txt"
    steps = [_append_step("step_a", marker, order=1)]
    path = make_config(steps=steps)

    run_pipeline(str(path), dry_run=True)

    assert not working_folder.exists()


# --------------------------- recovery / resume --------------------------- #

def test_resume_from_checkpoint_skips_completed_steps(make_config, working_folder, tmp_path):
    marker = tmp_path / "marker.txt"
    steps = [
        _append_step("step_a", marker, order=1),
        _append_step("step_b", marker, order=2),
        _append_step("step_c", marker, order=3),
    ]
    path = make_config(steps=steps)
    config = load_config(str(path))

    # Simulate an interrupted run: step_a already completed, IN_PROGRESS.
    ck_dir = working_folder / CURRENT_DIR_NAME / CHECKPOINT_DIR_NAME
    ck_dir.mkdir(parents=True)
    state = CheckpointState(
        config_path=str(path),
        config_hash=config.config_hash,
        pipeline_status=PipelineStatus.IN_PROGRESS,
        last_completed_step="step_a",
        step_statuses={"step_a": StepStatus.COMPLETED},
        run_id="resume01",
    )
    save_checkpoint(state, ck_dir)

    ok = run_pipeline(str(path))

    assert ok is True
    # step_a is NOT re-executed; only step_b and step_c run this time.
    assert _marker_lines(marker) == ["step_b", "step_c"]


def test_changed_config_restarts_from_beginning(make_config, working_folder, tmp_path):
    marker = tmp_path / "marker.txt"
    steps = [
        _append_step("step_a", marker, order=1),
        _append_step("step_b", marker, order=2),
    ]
    path = make_config(steps=steps)

    # Checkpoint with a stale hash -> config considered changed -> full restart.
    ck_dir = working_folder / CURRENT_DIR_NAME / CHECKPOINT_DIR_NAME
    ck_dir.mkdir(parents=True)
    state = CheckpointState(
        config_path=str(path),
        config_hash="stale-hash-does-not-match",
        pipeline_status=PipelineStatus.IN_PROGRESS,
        last_completed_step="step_a",
        step_statuses={"step_a": StepStatus.COMPLETED},
        run_id="stale01",
    )
    save_checkpoint(state, ck_dir)

    ok = run_pipeline(str(path))

    assert ok is True
    # Both steps run because the checkpoint is discarded.
    assert _marker_lines(marker) == ["step_a", "step_b"]


def test_completed_checkpoint_finalizes_when_all_steps_done(make_config, working_folder, tmp_path):
    marker = tmp_path / "marker.txt"
    steps = [
        _append_step("step_a", marker, order=1),
        _append_step("step_b", marker, order=2),
    ]
    path = make_config(steps=steps)
    config = load_config(str(path))

    # last_completed_step is the final step -> resume index past the end.
    ck_dir = working_folder / CURRENT_DIR_NAME / CHECKPOINT_DIR_NAME
    ck_dir.mkdir(parents=True)
    state = CheckpointState(
        config_path=str(path),
        config_hash=config.config_hash,
        pipeline_status=PipelineStatus.IN_PROGRESS,
        last_completed_step="step_b",
        step_statuses={
            "step_a": StepStatus.COMPLETED,
            "step_b": StepStatus.COMPLETED,
        },
        run_id="done01",
    )
    save_checkpoint(state, ck_dir)

    ok = run_pipeline(str(path))

    assert ok is True
    # No step re-executed; workspace archived, current gone.
    assert _marker_lines(marker) == []
    assert not (working_folder / CURRENT_DIR_NAME).exists()
    assert len(_dated_dirs(working_folder)) == 1
