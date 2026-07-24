"""Unit tests for orchestrator.quarantine (isolating failed-step data)."""

import json

from orchestrator.quarantine import (
    QUARANTINE_DIR_NAME,
    _quarantine_root,
    quarantine_step,
)
from orchestrator.models import StepConfig, StepResult, StepStatus


def _step(**overrides):
    base = dict(
        name="critical_step",
        order=1,
        is_active=True,
        is_critical=True,
        command="python",
        args=["x.py"],
        kwargs={},
        timeout_seconds=None,
    )
    base.update(overrides)
    return StepConfig(**base)


def _result(**overrides):
    base = dict(
        step_name="critical_step",
        status=StepStatus.FAILED,
        exit_code=2,
        stdout="",
        stderr="traceback ...",
        error_message="Process exited with code 2",
    )
    base.update(overrides)
    return StepResult(**base)


def test_quarantine_root_next_to_config(tmp_path):
    config = tmp_path / "cfg.json"
    config.write_text("{}", encoding="utf-8")
    root = _quarantine_root(str(config))
    assert root == tmp_path / QUARANTINE_DIR_NAME


def test_quarantine_step_creates_entry_and_report(tmp_path):
    config = tmp_path / "cfg.json"
    config.write_text("{}", encoding="utf-8")

    entry = quarantine_step(str(config), _step(), _result(), run_id="run42")

    assert entry.is_dir()
    assert entry.parent == tmp_path / QUARANTINE_DIR_NAME
    assert "run42" in entry.name
    assert "critical_step" in entry.name

    report_path = entry / "failure_report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["run_id"] == "run42"
    assert report["step_name"] == "critical_step"
    assert report["exit_code"] == 2
    assert report["error_message"] == "Process exited with code 2"
    assert report["stderr"] == "traceback ..."


def test_quarantine_step_copies_data_file(tmp_path):
    config = tmp_path / "cfg.json"
    config.write_text("{}", encoding="utf-8")
    data_file = tmp_path / "payload.csv"
    data_file.write_text("id,value\n1,2\n", encoding="utf-8")

    entry = quarantine_step(
        str(config), _step(), _result(), run_id="run7", data_path=str(data_file)
    )

    copied = entry / "payload.csv"
    assert copied.exists()
    assert copied.read_text(encoding="utf-8") == "id,value\n1,2\n"


def test_quarantine_step_copies_data_directory(tmp_path):
    config = tmp_path / "cfg.json"
    config.write_text("{}", encoding="utf-8")
    data_dir = tmp_path / "batch"
    data_dir.mkdir()
    (data_dir / "a.txt").write_text("a", encoding="utf-8")
    (data_dir / "b.txt").write_text("b", encoding="utf-8")

    entry = quarantine_step(
        str(config), _step(), _result(), run_id="run9", data_path=str(data_dir)
    )

    copied = entry / "batch"
    assert (copied / "a.txt").read_text(encoding="utf-8") == "a"
    assert (copied / "b.txt").read_text(encoding="utf-8") == "b"


def test_quarantine_step_missing_data_path_is_tolerated(tmp_path):
    config = tmp_path / "cfg.json"
    config.write_text("{}", encoding="utf-8")

    entry = quarantine_step(
        str(config),
        _step(),
        _result(),
        run_id="run11",
        data_path=str(tmp_path / "does_not_exist.csv"),
    )

    # Report is still written; no data file copied.
    assert (entry / "failure_report.json").exists()
    assert not (entry / "does_not_exist.csv").exists()


def test_quarantine_step_truncates_long_stderr(tmp_path):
    config = tmp_path / "cfg.json"
    config.write_text("{}", encoding="utf-8")
    long_stderr = "x" * 5000

    entry = quarantine_step(
        str(config), _step(), _result(stderr=long_stderr), run_id="run13"
    )
    report = json.loads((entry / "failure_report.json").read_text(encoding="utf-8"))
    assert len(report["stderr"]) == 2000
