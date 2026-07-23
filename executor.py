"""Step executor — runs external commands as subprocesses."""

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import List, Optional

from .models import StepConfig, StepResult, StepStatus

logger = logging.getLogger(__name__)

# Placeholder that steps may use in args/kwargs to refer to the current run
# directory (e.g. {"output": "{current_dir}\\out.csv"}).
CURRENT_DIR_PLACEHOLDER = "{current_dir}"


def _substitute(value: str, current_dir: Optional[Path]) -> str:
    """Replace the current-dir placeholder in a single argument value."""
    if current_dir is not None and CURRENT_DIR_PLACEHOLDER in value:
        return value.replace(CURRENT_DIR_PLACEHOLDER, str(current_dir))
    return value


def _build_command_line(step: StepConfig, current_dir: Optional[Path] = None) -> List[str]:
    """Assemble the full command line from step configuration."""
    cmd = [step.command]
    cmd.extend(_substitute(a, current_dir) for a in step.args)
    for key, value in step.kwargs.items():
        cmd.append(f"--{key}")
        cmd.append(_substitute(value, current_dir))
    return cmd


def execute_step(step: StepConfig, current_dir: Optional[Path] = None) -> StepResult:
    """Execute a single pipeline step as a subprocess.

    When ``current_dir`` is provided, the subprocess runs with that directory as
    its working directory and receives ``PIPELINE_CURRENT_DIR`` in its
    environment so the step can write logs and temporary data there.

    Returns a StepResult with status, exit code, and captured output.
    """
    cmd = _build_command_line(step, current_dir)
    logger.info("Executing step '%s': %s", step.name, " ".join(cmd))

    cwd = None
    env = None
    if current_dir is not None:
        cwd = str(current_dir)
        env = os.environ.copy()
        env["PIPELINE_CURRENT_DIR"] = str(current_dir)

    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=step.timeout_seconds,
            shell=False,
            cwd=cwd,
            env=env,
        )
        elapsed = time.monotonic() - start

        if proc.returncode == 0:
            logger.info("Step '%s' completed successfully in %.1fs.", step.name, elapsed)
            return StepResult(
                step_name=step.name,
                status=StepStatus.COMPLETED,
                exit_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
            )
        else:
            logger.error(
                "Step '%s' failed with exit code %d in %.1fs.\nstderr: %s",
                step.name, proc.returncode, elapsed, proc.stderr[:500],
            )
            return StepResult(
                step_name=step.name,
                status=StepStatus.FAILED,
                exit_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                error_message=f"Process exited with code {proc.returncode}",
            )

    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        msg = f"Step '{step.name}' timed out after {step.timeout_seconds}s."
        logger.error(msg)
        return StepResult(
            step_name=step.name,
            status=StepStatus.FAILED,
            error_message=msg,
        )

    except FileNotFoundError:
        msg = f"Command not found: {step.command}"
        logger.error(msg)
        return StepResult(
            step_name=step.name,
            status=StepStatus.FAILED,
            error_message=msg,
        )

    except OSError as exc:
        msg = f"OS error executing step '{step.name}': {exc}"
        logger.error(msg)
        return StepResult(
            step_name=step.name,
            status=StepStatus.FAILED,
            error_message=msg,
        )
