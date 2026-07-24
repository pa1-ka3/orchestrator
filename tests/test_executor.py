"""Unit tests for orchestrator.executor (command building & subprocess run)."""

import subprocess
from pathlib import Path
from unittest import mock

from orchestrator.executor import (
    CURRENT_DIR_PLACEHOLDER,
    _build_command_line,
    _substitute,
    execute_step,
)
from orchestrator.models import StepConfig, StepStatus


def _step(**overrides):
    base = dict(
        name="s1",
        order=1,
        is_active=True,
        is_critical=False,
        command="mytool",
        args=[],
        kwargs={},
        timeout_seconds=None,
    )
    base.update(overrides)
    return StepConfig(**base)


# --------------------------- _substitute --------------------------- #

def test_substitute_replaces_placeholder():
    value = f"{CURRENT_DIR_PLACEHOLDER}\\out.csv"
    result = _substitute(value, Path("C:/work/current"))
    assert result == "C:\\work\\current\\out.csv" or result.endswith("out.csv")
    assert CURRENT_DIR_PLACEHOLDER not in result


def test_substitute_noop_without_current_dir():
    value = f"{CURRENT_DIR_PLACEHOLDER}\\out.csv"
    assert _substitute(value, None) == value


def test_substitute_leaves_plain_value():
    assert _substitute("plain", Path("C:/work")) == "plain"


# --------------------------- _build_command_line --------------------------- #

def test_build_command_line_orders_command_args_kwargs():
    step = _step(command="python", args=["script.py", "-v"], kwargs={"input": "in.csv"})
    cmd = _build_command_line(step)
    assert cmd == ["python", "script.py", "-v", "--input", "in.csv"]


def test_build_command_line_substitutes_current_dir(tmp_path):
    step = _step(
        command="python",
        args=[f"{CURRENT_DIR_PLACEHOLDER}\\a.py"],
        kwargs={"output": f"{CURRENT_DIR_PLACEHOLDER}\\out.csv"},
    )
    cmd = _build_command_line(step, tmp_path)
    assert str(tmp_path) in cmd[1]
    assert str(tmp_path) in cmd[-1]
    assert CURRENT_DIR_PLACEHOLDER not in " ".join(cmd)


# --------------------------- execute_step (mocked subprocess) ------------- #

def test_execute_step_success():
    step = _step()
    completed = subprocess.CompletedProcess(
        args=["mytool"], returncode=0, stdout="ok", stderr=""
    )
    with mock.patch("orchestrator.executor.subprocess.run", return_value=completed) as run:
        result = execute_step(step)
    assert result.status == StepStatus.COMPLETED
    assert result.exit_code == 0
    assert result.stdout == "ok"
    run.assert_called_once()


def test_execute_step_nonzero_exit_is_failure():
    step = _step()
    completed = subprocess.CompletedProcess(
        args=["mytool"], returncode=3, stdout="", stderr="boom"
    )
    with mock.patch("orchestrator.executor.subprocess.run", return_value=completed):
        result = execute_step(step)
    assert result.status == StepStatus.FAILED
    assert result.exit_code == 3
    assert "code 3" in result.error_message


def test_execute_step_timeout_is_failure():
    step = _step(timeout_seconds=5)
    with mock.patch(
        "orchestrator.executor.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="mytool", timeout=5),
    ):
        result = execute_step(step)
    assert result.status == StepStatus.FAILED
    assert "timed out" in result.error_message


def test_execute_step_command_not_found_is_failure():
    step = _step(command="does-not-exist")
    with mock.patch(
        "orchestrator.executor.subprocess.run", side_effect=FileNotFoundError()
    ):
        result = execute_step(step)
    assert result.status == StepStatus.FAILED
    assert "Command not found" in result.error_message


def test_execute_step_os_error_is_failure():
    step = _step()
    with mock.patch(
        "orchestrator.executor.subprocess.run", side_effect=OSError("perm denied")
    ):
        result = execute_step(step)
    assert result.status == StepStatus.FAILED
    assert "OS error" in result.error_message


def test_execute_step_passes_cwd_and_env(tmp_path):
    step = _step()
    completed = subprocess.CompletedProcess(
        args=["mytool"], returncode=0, stdout="", stderr=""
    )
    with mock.patch("orchestrator.executor.subprocess.run", return_value=completed) as run:
        execute_step(step, tmp_path)
    _, kwargs = run.call_args
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["env"]["PIPELINE_CURRENT_DIR"] == str(tmp_path)
    assert kwargs["shell"] is False


def test_execute_step_no_current_dir_uses_defaults():
    step = _step()
    completed = subprocess.CompletedProcess(
        args=["mytool"], returncode=0, stdout="", stderr=""
    )
    with mock.patch("orchestrator.executor.subprocess.run", return_value=completed) as run:
        execute_step(step)
    _, kwargs = run.call_args
    assert kwargs["cwd"] is None
    assert kwargs["env"] is None
