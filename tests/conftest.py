"""Shared pytest fixtures and path setup for the orchestrator test suite.

The ``orchestrator`` package uses intra-package relative imports (``.models``
etc.), so it must be imported as a package. This file ensures the directory
that *contains* the ``orchestrator`` package is on ``sys.path`` so that
``import orchestrator`` resolves regardless of the working directory pytest is
invoked from.
"""

import json
import sys
from pathlib import Path

import pytest

# tests/ -> orchestrator/ -> <parent that contains the package>
_PACKAGE_PARENT = Path(__file__).resolve().parents[2]
if str(_PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_PARENT))


@pytest.fixture
def working_folder(tmp_path):
    """A dedicated working folder path for a pipeline run (not yet created)."""
    return tmp_path / "work" / "pipeline_1"


def _array_config_dict(working_folder, steps=None):
    """Build a minimal valid config dict in the array format."""
    if steps is None:
        steps = [
            {
                "name": "step_a",
                "order": 1,
                "is_active": True,
                "is_critical": True,
                "command_to_run": "python",
                "args": ["-c", "print('a')"],
                "kwargs": {"output": "out_a.txt"},
                "timeout_seconds": 60,
            },
            {
                "name": "step_b",
                "order": 2,
                "is_active": True,
                "is_critical": False,
                "command_to_run": "python",
                "args": ["-c", "print('b')"],
                "kwargs": {},
            },
        ]
    return {
        "pipeline": {
            "name": "nightly_etl",
            "working_folder": str(working_folder),
        },
        "steps": steps,
    }


@pytest.fixture
def make_config(tmp_path, working_folder):
    """Factory that writes a config JSON file and returns its path.

    Usage::

        path = make_config()                     # default two-step config
        path = make_config(steps=[...])          # custom steps
        path = make_config(raw={...})            # arbitrary raw dict
    """

    counter = {"n": 0}

    def _make(steps=None, raw=None, wf=None):
        counter["n"] += 1
        target_wf = wf if wf is not None else working_folder
        if raw is None:
            data = _array_config_dict(target_wf, steps=steps)
        else:
            data = raw
        config_path = tmp_path / f"config_{counter['n']}.json"
        config_path.write_text(json.dumps(data), encoding="utf-8")
        return config_path

    return _make


@pytest.fixture
def config_dict_factory(working_folder):
    """Return the raw-dict builder so tests can tweak before writing."""

    def _make(steps=None, wf=None):
        return _array_config_dict(wf if wf is not None else working_folder, steps=steps)

    return _make
