"""Checkpoint manager — persistence for recovery points.

Checkpoints are stored inside a caller-provided directory, namely
``<working_folder>/current/pipeline_checkpoints`` for the active run.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import CheckpointState, PipelineStatus

logger = logging.getLogger(__name__)


def _checkpoint_file(checkpoint_dir: Path, config_path: str) -> Path:
    """Derive the checkpoint file path within ``checkpoint_dir``."""
    stem = Path(config_path).resolve().stem
    return checkpoint_dir / f"{stem}.checkpoint.json"


def save_checkpoint(state: CheckpointState, checkpoint_dir: Path) -> None:
    """Persist the current pipeline state to disk."""
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    path = _checkpoint_file(checkpoint_dir, state.config_path)
    state.timestamp = datetime.now(timezone.utc).isoformat()
    data = {
        "config_path": state.config_path,
        "config_hash": state.config_hash,
        "pipeline_status": state.pipeline_status.value,
        "last_completed_step": state.last_completed_step,
        "step_statuses": state.step_statuses,
        "quarantined_steps": state.quarantined_steps,
        "run_id": state.run_id,
        "timestamp": state.timestamp,
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)  # atomic on Windows (same volume)
    logger.debug("Checkpoint saved: %s", path)


def load_checkpoint(config_path: str, checkpoint_dir: Path) -> Optional[CheckpointState]:
    """Load a previously saved checkpoint, if it exists."""
    path = _checkpoint_file(checkpoint_dir, config_path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return CheckpointState(
            config_path=data["config_path"],
            config_hash=data["config_hash"],
            pipeline_status=PipelineStatus(data["pipeline_status"]),
            last_completed_step=data.get("last_completed_step"),
            step_statuses={k: v for k, v in data.get("step_statuses", {}).items()},
            quarantined_steps=data.get("quarantined_steps", []),
            run_id=data.get("run_id", ""),
            timestamp=data.get("timestamp", ""),
        )
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("Corrupt checkpoint at %s: %s — starting fresh.", path, exc)
        return None


def clear_checkpoint(config_path: str, checkpoint_dir: Path) -> None:
    """Remove the checkpoint file after successful completion."""
    path = _checkpoint_file(checkpoint_dir, config_path)
    if path.exists():
        path.unlink()
        logger.info("Checkpoint cleared: %s", path)
