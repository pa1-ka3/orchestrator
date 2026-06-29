"""Configuration loader and validator."""

import hashlib
import json
import logging
from pathlib import Path
from typing import Dict, List

from .models import PipelineConfig, StepConfig

logger = logging.getLogger(__name__)


def _normalize_kwargs(raw_kwargs) -> Dict[str, str]:
    """Convert kwargs from list-of-dicts or dict format to a flat dict.

    Supports both formats:
      - Original: [{"input": "path"}, {"output": "path"}]
      - Improved:  {"input": "path", "output": "path"}
    """
    if isinstance(raw_kwargs, dict):
        return {str(k): str(v) for k, v in raw_kwargs.items()}
    if isinstance(raw_kwargs, list):
        merged: Dict[str, str] = {}
        for item in raw_kwargs:
            if isinstance(item, dict):
                for k, v in item.items():
                    if k in merged:
                        logger.warning("Duplicate kwarg key '%s' — last value wins.", k)
                    merged[str(k)] = str(v)
        return merged
    return {}


def _parse_steps_from_object(data: dict) -> List[StepConfig]:
    """Parse the original dict-of-steps format (step1, step2, ..., stepN)."""
    steps = []
    for order, (name, step_data) in enumerate(data.items(), start=1):
        if not isinstance(step_data, dict):
            raise ValueError(f"Step '{name}' must be a JSON object, got {type(step_data).__name__}")
        steps.append(StepConfig(
            name=name,
            order=order,
            is_active=step_data.get("is_active", True),
            is_critical=step_data.get("is_critical", False),
            command=step_data["command_to_run"],
            args=step_data.get("args", []),
            kwargs=_normalize_kwargs(step_data.get("kwargs", {})),
            timeout_seconds=step_data.get("timeout_seconds"),
        ))
    return steps


def _parse_steps_from_array(data: dict) -> List[StepConfig]:
    """Parse the improved array-of-steps format."""
    steps = []
    for item in data["steps"]:
        steps.append(StepConfig(
            name=item["name"],
            order=item.get("order", 0),
            is_active=item.get("is_active", True),
            is_critical=item.get("is_critical", False),
            command=item["command_to_run"],
            args=item.get("args", []),
            kwargs=_normalize_kwargs(item.get("kwargs", {})),
            timeout_seconds=item.get("timeout_seconds"),
        ))
    steps.sort(key=lambda s: s.order)
    return steps


def _compute_hash(config_path: Path) -> str:
    """SHA-256 hash of the config file for change detection."""
    return hashlib.sha256(config_path.read_bytes()).hexdigest()


def load_config(config_path: str) -> PipelineConfig:
    """Load and validate a pipeline configuration file.

    Accepts both the original dict-of-steps format and the improved array format.
    """
    path = Path(config_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)

    if not isinstance(data, dict):
        raise ValueError("Config must be a JSON object at the top level.")

    # Detect format
    if "steps" in data and isinstance(data["steps"], list):
        steps = _parse_steps_from_array(data)
        name = data.get("pipeline", {}).get("name", path.stem)
    else:
        steps = _parse_steps_from_object(data)
        name = path.stem

    if not steps:
        raise ValueError("Config contains no steps.")

    # Validate commands are not empty
    for step in steps:
        if not step.command.strip():
            raise ValueError(f"Step '{step.name}' has an empty command.")

    config = PipelineConfig(
        name=name,
        config_path=str(path),
        config_hash=_compute_hash(path),
        steps=steps,
    )

    active = [s for s in steps if s.is_active]
    logger.info(
        "Loaded config '%s': %d total steps, %d active.",
        config.name, len(steps), len(active),
    )
    return config
