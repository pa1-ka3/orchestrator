"""Quarantine handler — isolates data blocks that failed on critical steps."""

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import StepConfig, StepResult

logger = logging.getLogger(__name__)

QUARANTINE_DIR_NAME = "quarantine"


def _quarantine_root(config_path: str) -> Path:
    """Quarantine directory lives next to the config file."""
    return Path(config_path).resolve().parent / QUARANTINE_DIR_NAME


def quarantine_step(
    config_path: str,
    step: StepConfig,
    result: StepResult,
    run_id: str,
    data_path: Optional[str] = None,
) -> Path:
    """Move relevant data to quarantine and write a failure report.

    Returns the path to the quarantine entry directory.
    """
    root = _quarantine_root(config_path)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    entry_dir = root / f"{run_id}_{step.name}_{timestamp}"
    entry_dir.mkdir(parents=True, exist_ok=True)

    # Write failure report
    report = {
        "run_id": run_id,
        "step_name": step.name,
        "command": step.command,
        "exit_code": result.exit_code,
        "error_message": result.error_message,
        "stderr": result.stderr[:2000] if result.stderr else "",
        "timestamp": timestamp,
    }
    report_path = entry_dir / "failure_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # Copy data files to quarantine if a path is provided
    if data_path:
        src = Path(data_path)
        if src.exists():
            dst = entry_dir / src.name
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
            logger.info("Data copied to quarantine: %s -> %s", src, dst)

    logger.warning(
        "Step '%s' quarantined in '%s'. Reason: %s",
        step.name, entry_dir, result.error_message,
    )
    return entry_dir
