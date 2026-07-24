"""Unit tests for orchestrator.config (loading, parsing, validation)."""

import json

import pytest

from orchestrator.config import (
    _compute_hash,
    _normalize_kwargs,
    _parse_steps_from_array,
    _parse_steps_from_object,
    load_config,
)


# --------------------------- _normalize_kwargs --------------------------- #

def test_normalize_kwargs_from_dict():
    result = _normalize_kwargs({"input": "a", "output": "b"})
    assert result == {"input": "a", "output": "b"}


def test_normalize_kwargs_from_list_of_dicts():
    result = _normalize_kwargs([{"input": "a"}, {"output": "b"}])
    assert result == {"input": "a", "output": "b"}


def test_normalize_kwargs_stringifies_values():
    result = _normalize_kwargs({"timeout": 60, "retries": 3})
    assert result == {"timeout": "60", "retries": "3"}


def test_normalize_kwargs_duplicate_key_last_wins(caplog):
    result = _normalize_kwargs([{"k": "first"}, {"k": "second"}])
    assert result == {"k": "second"}


def test_normalize_kwargs_unsupported_type_returns_empty():
    assert _normalize_kwargs("not-a-mapping") == {}
    assert _normalize_kwargs(None) == {}


# --------------------------- parse helpers --------------------------- #

def test_parse_steps_from_object_assigns_sequential_order():
    data = {
        "step1": {"command_to_run": "python", "is_active": True},
        "step2": {"command_to_run": "python", "is_critical": True},
    }
    steps = _parse_steps_from_object(data)
    assert [s.name for s in steps] == ["step1", "step2"]
    assert [s.order for s in steps] == [1, 2]
    assert steps[0].is_active is True
    assert steps[1].is_critical is True


def test_parse_steps_from_object_rejects_non_dict_step():
    with pytest.raises(ValueError, match="must be a JSON object"):
        _parse_steps_from_object({"step1": "oops"})


def test_parse_steps_from_array_sorts_by_order():
    data = {
        "steps": [
            {"name": "b", "order": 2, "command_to_run": "python"},
            {"name": "a", "order": 1, "command_to_run": "python"},
        ]
    }
    steps = _parse_steps_from_array(data)
    assert [s.name for s in steps] == ["a", "b"]


# --------------------------- _compute_hash --------------------------- #

def test_compute_hash_is_stable_and_content_sensitive(tmp_path):
    f = tmp_path / "c.json"
    f.write_text("hello", encoding="utf-8")
    h1 = _compute_hash(f)
    h2 = _compute_hash(f)
    assert h1 == h2
    f.write_text("world", encoding="utf-8")
    assert _compute_hash(f) != h1


# --------------------------- load_config --------------------------- #

def test_load_config_array_format(make_config, working_folder):
    path = make_config()
    config = load_config(str(path))
    assert config.name == "nightly_etl"
    assert config.working_folder == str(working_folder)
    assert len(config.steps) == 2
    assert config.config_hash
    assert config.config_path == str(path.resolve())


def test_load_config_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_config("nonexistent_config_file.json")


def test_load_config_top_level_not_object(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(["a", "b"]), encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object at the top level"):
        load_config(str(path))


def test_load_config_no_steps_raises(tmp_path, working_folder):
    path = tmp_path / "empty.json"
    path.write_text(
        json.dumps({"pipeline": {"working_folder": str(working_folder)}, "steps": []}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no steps"):
        load_config(str(path))


def test_load_config_empty_command_raises(make_config):
    steps = [
        {"name": "s", "order": 1, "command_to_run": "   ", "is_active": True},
    ]
    path = make_config(steps=steps)
    with pytest.raises(ValueError, match="empty command"):
        load_config(str(path))


def test_load_config_missing_working_folder_raises(tmp_path):
    data = {
        "pipeline": {"name": "no_wf"},
        "steps": [{"name": "s", "order": 1, "command_to_run": "python"}],
    }
    path = tmp_path / "no_wf.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="working_folder"):
        load_config(str(path))


def test_load_config_blank_working_folder_raises(tmp_path):
    data = {
        "pipeline": {"name": "blank", "working_folder": "   "},
        "steps": [{"name": "s", "order": 1, "command_to_run": "python"}],
    }
    path = tmp_path / "blank.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="working_folder"):
        load_config(str(path))


def test_load_config_original_object_format_requires_working_folder(tmp_path):
    # The original object format has no place for a "pipeline" section (every
    # top-level key is treated as a step), so the now-mandatory working_folder
    # cannot be supplied and loading must fail cleanly.
    data = {
        "step1": {"command_to_run": "python", "is_active": True, "is_critical": True},
        "step2": {"command_to_run": "python", "is_active": False},
    }
    path = tmp_path / "orig.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="working_folder"):
        load_config(str(path))


def test_load_config_name_defaults_to_stem_when_absent(tmp_path, working_folder):
    data = {
        "pipeline": {"working_folder": str(working_folder)},
        "steps": [{"name": "s", "order": 1, "command_to_run": "python"}],
    }
    path = tmp_path / "my_pipeline.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    config = load_config(str(path))
    assert config.name == "my_pipeline"
