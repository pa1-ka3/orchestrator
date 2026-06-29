"""Step executor — runs external commands as subprocesses."""

import logging
import subprocess
import time
from typing import List

from .models import StepConfig, StepResult, StepStatus

logger = logging.getLogger(__name__)


def _build_command_line(step: StepConfig) -> List[str]:
    """Assemble the full command line from step configuration."""
    cmd = [step.command]
    cmd.extend(step.args)
    for key, value in step.kwargs.items():
        cmd.append(f"--{key}")
        cmd.append(value)
    return cmd


def execute_step(step: StepConfig) -> StepResult:
    """Execute a single pipeline step as a subprocess.

    Returns a StepResult with status, exit code, and captured output.
    """
    cmd = _build_command_line(step)
    logger.info("Executing step '%s': %s", step.name, " ".join(cmd))

    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=step.timeout_seconds,
            shell=False,
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
