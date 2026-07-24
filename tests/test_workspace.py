"""Unit tests for orchestrator.workspace (run-folder lifecycle)."""

from datetime import datetime

import pytest

from orchestrator.workspace import (
    CHECKPOINT_DIR_NAME,
    CURRENT_DIR_NAME,
    MAX_ARCHIVED_RUNS,
    Workspace,
    _archive_target,
    _archived_runs,
    cleanup_old_runs,
    finalize_workspace,
    prepare_workspace,
)


# --------------------------- prepare_workspace --------------------------- #

def test_prepare_workspace_creates_current_and_checkpoint(working_folder):
    ws = prepare_workspace(str(working_folder))
    assert ws.base_dir == working_folder
    assert ws.current_dir == working_folder / CURRENT_DIR_NAME
    assert ws.checkpoint_dir == working_folder / CURRENT_DIR_NAME / CHECKPOINT_DIR_NAME
    assert ws.current_dir.is_dir()
    assert ws.checkpoint_dir.is_dir()


def test_prepare_workspace_reuses_existing_current(working_folder):
    ws1 = prepare_workspace(str(working_folder))
    marker = ws1.current_dir / "marker.txt"
    marker.write_text("keep me", encoding="utf-8")
    ws2 = prepare_workspace(str(working_folder))
    assert ws2.current_dir == ws1.current_dir
    assert marker.exists()


def test_prepare_workspace_empty_raises():
    with pytest.raises(ValueError, match="not set"):
        prepare_workspace("   ")


# --------------------------- _archive_target --------------------------- #

def test_archive_target_uses_date_when_free(tmp_path):
    completion = datetime(2026, 7, 20, 3, 30, 0)
    target = _archive_target(tmp_path, completion)
    assert target == tmp_path / "2026_07_20"


def test_archive_target_adds_suffix_on_collision(tmp_path):
    completion = datetime(2026, 7, 20, 3, 30, 15)
    (tmp_path / "2026_07_20").mkdir()
    target = _archive_target(tmp_path, completion)
    assert target.name == "2026_07_20_033015"


# --------------------------- finalize_workspace --------------------------- #

def test_finalize_workspace_renames_current_to_date(working_folder):
    ws = prepare_workspace(str(working_folder))
    (ws.current_dir / "log.txt").write_text("data", encoding="utf-8")
    completion = datetime(2026, 7, 21, 1, 0, 0)
    archived = finalize_workspace(ws, completion=completion)
    assert archived == working_folder / "2026_07_21"
    assert archived.is_dir()
    assert (archived / "log.txt").read_text(encoding="utf-8") == "data"
    assert not ws.current_dir.exists()


def test_finalize_workspace_default_completion_is_now(working_folder):
    ws = prepare_workspace(str(working_folder))
    archived = finalize_workspace(ws)
    expected = working_folder / datetime.now().strftime("%Y_%m_%d")
    # allow for the possibility of a suffix if the date dir pre-existed
    assert archived.name.startswith(expected.name)


# --------------------------- cleanup / retention --------------------------- #

def test_archived_runs_sorted_oldest_first(working_folder):
    working_folder.mkdir(parents=True)
    for name in ["2026_07_22", "2026_07_20", "2026_07_21"]:
        (working_folder / name).mkdir()
    (working_folder / CURRENT_DIR_NAME).mkdir()
    runs = _archived_runs(working_folder)
    assert [p.name for p in runs] == ["2026_07_20", "2026_07_21", "2026_07_22"]


def test_cleanup_old_runs_keeps_only_max(working_folder):
    working_folder.mkdir(parents=True)
    for name in ["2026_07_18", "2026_07_19", "2026_07_20", "2026_07_21"]:
        (working_folder / name).mkdir()
    cleanup_old_runs(working_folder)
    remaining = sorted(p.name for p in working_folder.iterdir())
    assert len(remaining) == MAX_ARCHIVED_RUNS
    # oldest ones removed, newest kept
    assert remaining == ["2026_07_20", "2026_07_21"]


def test_cleanup_old_runs_noop_when_under_limit(working_folder):
    working_folder.mkdir(parents=True)
    (working_folder / "2026_07_20").mkdir()
    cleanup_old_runs(working_folder)
    assert (working_folder / "2026_07_20").exists()


def test_full_lifecycle_retains_current_plus_two(working_folder):
    """End-to-end retention: after several runs, keep current + 2 dated dirs."""
    dates = [datetime(2026, 7, d, 2, 0, 0) for d in (18, 19, 20, 21)]
    for completion in dates:
        ws = prepare_workspace(str(working_folder))
        finalize_workspace(ws, completion=completion)
    # Re-create current for the next (in-progress) run
    prepare_workspace(str(working_folder))
    names = sorted(p.name for p in working_folder.iterdir())
    assert CURRENT_DIR_NAME in names
    dated = [n for n in names if n != CURRENT_DIR_NAME]
    assert len(dated) == MAX_ARCHIVED_RUNS
    assert dated == ["2026_07_20", "2026_07_21"]
