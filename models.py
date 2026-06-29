"""Data models for the pipeline orchestrator."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    QUARANTINED = "quarantined"


class PipelineStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    QUARANTINED = "quarantined"


@dataclass
class StepConfig:
    name: str
    order: int
    is_active: bool
    is_critical: bool
    command: str
    args: List[str] = field(default_factory=list)
    kwargs: Dict[str, str] = field(default_factory=dict)
    timeout_seconds: Optional[int] = None


@dataclass
class PipelineConfig:
    name: str
    config_path: str
    config_hash: str
    steps: List[StepConfig] = field(default_factory=list)


@dataclass
class StepResult:
    step_name: str
    status: StepStatus
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    error_message: str = ""


@dataclass
class CheckpointState:
    config_path: str
    config_hash: str
    pipeline_status: PipelineStatus = PipelineStatus.NOT_STARTED
    last_completed_step: Optional[str] = None
    step_statuses: Dict[str, str] = field(default_factory=dict)
    quarantined_steps: List[str] = field(default_factory=list)
    run_id: str = ""
    timestamp: str = ""
