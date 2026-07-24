"""Unit tests for orchestrator.checkpoint (persistence and recovery)."""

from orchestrator.checkpoint import (
    _checkpoint_file,
    clear_checkpoint,
    load_checkpoint,
    save_checkpoint,
)
from orchestrator.models import CheckpointState, PipelineStatus


def _make_state(config_path):
    return CheckpointState(
        config_path=str(config_path),
        config_hash="abc123",
        pipeline_status=PipelineStatus.IN_PROGRESS,
        last_completed_step="step_a",
        step_statuses={"step_a": "completed", "step_b": "running"},
        quarantined_steps=[],
        run_id="run0001",
    )


def test_checkpoint_file_name_derived_from_config_stem(tmp_path):
    config = tmp_path / "nightly.json"
    config.write_text("{}", encoding="utf-8")
    path = _checkpoint_file(tmp_path, str(config))
    assert path.name == "nightly.checkpoint.json"


def test_save_and_load_roundtrip(tmp_path):
    config = tmp_path / "cfg.json"
    config.write_text("{}", encoding="utf-8")
    state = _make_state(config)

    save_checkpoint(state, tmp_path)
    loaded = load_checkpoint(str(config), tmp_path)

    assert loaded is not None
    assert loaded.config_hash == "abc123"
    assert loaded.pipeline_status == PipelineStatus.IN_PROGRESS
    assert loaded.last_completed_step == "step_a"
    assert loaded.step_statuses == {"step_a": "completed", "step_b": "running"}
    assert loaded.run_id == "run0001"


def test_save_checkpoint_sets_timestamp(tmp_path):
    config = tmp_path / "cfg.json"
    config.write_text("{}", encoding="utf-8")
    state = _make_state(config)
    assert state.timestamp == ""
    save_checkpoint(state, tmp_path)
    assert state.timestamp  # populated with an ISO timestamp


def test_save_checkpoint_is_atomic_no_tmp_left(tmp_path):
    config = tmp_path / "cfg.json"
    config.write_text("{}", encoding="utf-8")
    save_checkpoint(_make_state(config), tmp_path)
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert tmp_files == []


def test_save_checkpoint_creates_missing_directory(tmp_path):
    config = tmp_path / "cfg.json"
    config.write_text("{}", encoding="utf-8")
    nested = tmp_path / "a" / "b" / "checkpoints"
    save_checkpoint(_make_state(config), nested)
    assert nested.is_dir()
    assert load_checkpoint(str(config), nested) is not None


def test_load_checkpoint_missing_returns_none(tmp_path):
    config = tmp_path / "cfg.json"
    config.write_text("{}", encoding="utf-8")
    assert load_checkpoint(str(config), tmp_path) is None


def test_load_checkpoint_corrupt_json_returns_none(tmp_path):
    config = tmp_path / "cfg.json"
    config.write_text("{}", encoding="utf-8")
    bad = _checkpoint_file(tmp_path, str(config))
    bad.write_text("{ not valid json", encoding="utf-8")
    assert load_checkpoint(str(config), tmp_path) is None


def test_load_checkpoint_missing_required_key_returns_none(tmp_path):
    config = tmp_path / "cfg.json"
    config.write_text("{}", encoding="utf-8")
    bad = _checkpoint_file(tmp_path, str(config))
    bad.write_text('{"config_path": "x"}', encoding="utf-8")
    assert load_checkpoint(str(config), tmp_path) is None


def test_clear_checkpoint_removes_file(tmp_path):
    config = tmp_path / "cfg.json"
    config.write_text("{}", encoding="utf-8")
    save_checkpoint(_make_state(config), tmp_path)
    assert load_checkpoint(str(config), tmp_path) is not None

    clear_checkpoint(str(config), tmp_path)
    assert load_checkpoint(str(config), tmp_path) is None


def test_clear_checkpoint_noop_when_absent(tmp_path):
    config = tmp_path / "cfg.json"
    config.write_text("{}", encoding="utf-8")
    # Should not raise even if there is nothing to remove.
    clear_checkpoint(str(config), tmp_path)
