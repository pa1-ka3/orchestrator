"""Working-folder lifecycle management for pipeline runs.

Layout under the configured ``working_folder`` (e.g. ``C:\\work\\pipeline_1``)::

    C:\\work\\pipeline_1\\
        current\\                       # active run (reused on resume)
            pipeline_checkpoints\\      # recovery points for the active run
            ...                         # step logs / temp data
        2026_07_20\\                    # archived successful run
        2026_07_21\\                    # archived successful run

On a successful run ``current`` is renamed to ``yyyy_MM_dd`` (completion date)
and the folder is trimmed to at most ``current`` plus ``MAX_ARCHIVED_RUNS``
dated directories.
"""

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

CURRENT_DIR_NAME = "current"
CHECKPOINT_DIR_NAME = "pipeline_checkpoints"
DATE_FORMAT = "%Y_%m_%d"
# Maximum number of archived (dated) run directories to keep. Together with
# the "current" directory this yields at most 3 directories on disk.
MAX_ARCHIVED_RUNS = 2


@dataclass
class Workspace:
    """Resolved directories for a single pipeline run."""

    base_dir: Path
    current_dir: Path
    checkpoint_dir: Path


def prepare_workspace(working_folder: str) -> Workspace:
    """Ensure the base and ``current`` directories exist and return their paths.

    If ``current`` already exists (an interrupted previous run), it is reused so
    that the checkpoint inside it enables recovery.

    Raises ``ValueError`` if ``working_folder`` is empty and ``OSError`` if the
    path is not a valid or accessible location on disk or the network.
    """
    if not working_folder or not str(working_folder).strip():
        raise ValueError("'working_folder' is not set.")

    base = Path(working_folder).expanduser()
    current = base / CURRENT_DIR_NAME
    checkpoint_dir = current / CHECKPOINT_DIR_NAME
    try:
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OSError(
            f"'working_folder' path '{working_folder}' is not a valid or "
            f"accessible location: {exc}"
        ) from exc
    logger.info("Using working folder '%s' (current run: '%s').", base, current)
    return Workspace(base_dir=base, current_dir=current, checkpoint_dir=checkpoint_dir)


def _archive_target(base: Path, completion: datetime) -> Path:
    """Pick a non-existing ``yyyy_MM_dd`` target for the finished run.

    If a run already completed on the same day, a time-based suffix is appended
    so a previous successful run is never overwritten.
    """
    name = completion.strftime(DATE_FORMAT)
    target = base / name
    if not target.exists():
        return target

    suffix = completion.strftime("%H%M%S")
    candidate = base / f"{name}_{suffix}"
    counter = 1
    while candidate.exists():
        counter += 1
        candidate = base / f"{name}_{suffix}_{counter}"
    logger.info("A run already exists for %s; archiving as '%s'.", name, candidate.name)
    return candidate


def finalize_workspace(workspace: Workspace, completion: Optional[datetime] = None) -> Path:
    """Rename ``current`` to a dated directory and trim old runs.

    Returns the path of the archived directory.
    """
    completion = completion or datetime.now()
    target = _archive_target(workspace.base_dir, completion)
    workspace.current_dir.rename(target)
    logger.info("Archived completed run: '%s' -> '%s'.", workspace.current_dir, target)
    cleanup_old_runs(workspace.base_dir)
    return target


def _archived_runs(base: Path) -> List[Path]:
    """Return archived (dated) run directories sorted oldest-first by name."""
    return sorted(
        (
            p for p in base.iterdir()
            if p.is_dir() and p.name != CURRENT_DIR_NAME
        ),
        key=lambda p: p.name,
    )


def cleanup_old_runs(base: Path, keep: int = MAX_ARCHIVED_RUNS) -> None:
    """Delete the oldest archived runs so at most ``keep`` remain."""
    archived = _archived_runs(base)
    excess = len(archived) - keep
    for old in archived[:max(0, excess)]:
        shutil.rmtree(old, ignore_errors=True)
        logger.info("Removed old run directory: '%s'.", old)
