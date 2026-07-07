"""Pipeline orchestrator — main entry point."""

import argparse
import logging
import sys
import uuid
from typing import List, Optional

from .checkpoint import clear_checkpoint, load_checkpoint, save_checkpoint
from .config import load_config
from .executor import execute_step
from .lock import InstanceLock
from .models import (
    CheckpointState,
    PipelineConfig,
    PipelineStatus,
    StepConfig,
    StepResult,
    StepStatus,
)
from .quarantine import quarantine_step

logger = logging.getLogger(__name__)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
    logging.basicConfig(level=level, format=fmt, handlers=[
        logging.StreamHandler(sys.stdout),
    ])


def _active_steps(config: PipelineConfig) -> List[StepConfig]:
    """Return only active steps, sorted by order."""
    return [s for s in config.steps if s.is_active]


def _determine_resume_index(
    steps: List[StepConfig],
    checkpoint: Optional[CheckpointState],
    config: PipelineConfig,
) -> int:
    """Determine which step to resume from based on the checkpoint.

    Returns the index into `steps` to start execution at.
    """
    if checkpoint is None:
        return 0

    # Config changed since last run — start over
    if checkpoint.config_hash != config.config_hash:
        logger.warning("Config has changed since last checkpoint — restarting pipeline.")
        return 0

    if checkpoint.pipeline_status in (PipelineStatus.COMPLETED, PipelineStatus.QUARANTINED):
        logger.info("Previous run already finished (status=%s). Starting fresh.", checkpoint.pipeline_status.value)
        return 0

    if checkpoint.last_completed_step is None:
        return 0

    # Find the step after the last completed one
    for i, step in enumerate(steps):
        if step.name == checkpoint.last_completed_step:
            resume_idx = i + 1
            if resume_idx < len(steps):
                logger.info(
                    "Resuming from step '%s' (index %d).",
                    steps[resume_idx].name, resume_idx,
                )
            return resume_idx

    logger.warning("Last completed step '%s' not found in active steps — restarting.", checkpoint.last_completed_step)
    return 0


def run_pipeline(config_path: str, dry_run: bool = False) -> bool:
    """Execute the pipeline defined by the given config file.

    Returns True if all steps completed successfully, False otherwise.
    """
    config = load_config(config_path)
    steps = _active_steps(config)

    if not steps:
        logger.warning("No active steps in config '%s'. Nothing to do.", config.name)
        return True

    logger.info(
        "Pipeline '%s': %d active steps — %s",
        config.name,
        len(steps),
        " → ".join(s.name for s in steps),
    )

    # Load existing checkpoint for recovery
    checkpoint = load_checkpoint(config_path)
    run_id = checkpoint.run_id if checkpoint and checkpoint.pipeline_status == PipelineStatus.IN_PROGRESS else str(uuid.uuid4())[:8]
    start_index = _determine_resume_index(steps, checkpoint, config)

    if start_index >= len(steps):
        logger.info("All steps already completed in previous run.")
        clear_checkpoint(config_path)
        return True

    # Initialize checkpoint state
    state = CheckpointState(
        config_path=str(config.config_path),
        config_hash=config.config_hash,
        pipeline_status=PipelineStatus.IN_PROGRESS,
        last_completed_step=checkpoint.last_completed_step if checkpoint else None,
        step_statuses=checkpoint.step_statuses if checkpoint else {},
        quarantined_steps=checkpoint.quarantined_steps if checkpoint else [],
        run_id=run_id,
    )

    # Mark skipped inactive steps
    for step in config.steps:
        if not step.is_active and step.name not in state.step_statuses:
            state.step_statuses[step.name] = StepStatus.SKIPPED #.value

    success = True
    for i in range(start_index, len(steps)):
        step = steps[i]
        logger.info("--- Step %d/%d: '%s' ---", i + 1, len(steps), step.name)

        if dry_run:
            logger.info("[DRY RUN] Would execute: %s %s", step.command, " ".join(step.args))
            state.step_statuses[step.name] = StepStatus.COMPLETED #.value
            state.last_completed_step = step.name
            continue

        # Mark step as running and save checkpoint (recovery point)
        state.step_statuses[step.name] = StepStatus.RUNNING #.value
        save_checkpoint(state)

        result: StepResult = execute_step(step)

        if result.status == StepStatus.COMPLETED:
            state.step_statuses[step.name] = StepStatus.COMPLETED #.value
            state.last_completed_step = step.name
            save_checkpoint(state)
        else:
            # Step failed
            if step.is_critical:
                logger.error(
                    "CRITICAL step '%s' failed — quarantining and stopping pipeline.",
                    step.name,
                )
                state.step_statuses[step.name] = StepStatus.QUARANTINED #.value
                state.quarantined_steps.append(step.name)
                state.pipeline_status = PipelineStatus.QUARANTINED

                # Quarantine data (use output kwarg as data path if available)
                data_path = step.kwargs.get("output") or step.kwargs.get("input")
                quarantine_step(config_path, step, result, run_id, data_path)

                save_checkpoint(state)
                return False
            else:
                logger.warning(
                    "Non-critical step '%s' failed — logging and continuing.",
                    step.name,
                )
                state.step_statuses[step.name] = StepStatus.FAILED  # .value
                save_checkpoint(state)
                success = False

    state.pipeline_status = PipelineStatus.COMPLETED if success else PipelineStatus.FAILED
    save_checkpoint(state)

    if success:
        logger.info("Pipeline '%s' completed successfully.", config.name)
        clear_checkpoint(config_path)
    else:
        logger.warning("Pipeline '%s' completed with non-critical failures.", config.name)

    return success


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pipeline-orchestrator",
        description="Sequential pipeline orchestrator with recovery points.",
    )
    parser.add_argument(
        "config",
        help="Path to the pipeline configuration JSON file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be executed without running anything.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )

    args = parser.parse_args()
    _setup_logging(args.verbose)

    try:
        with InstanceLock(args.config):
            ok = run_pipeline(args.config, dry_run=args.dry_run)
            sys.exit(0 if ok else 1)
    except RuntimeError as exc:
        logger.error(str(exc))
        sys.exit(2)
    except KeyboardInterrupt:
        logger.info("Pipeline interrupted by user.")
        sys.exit(130)
    except Exception as exc:
        logger.exception("Unexpected error: %s", exc)
        sys.exit(3)
