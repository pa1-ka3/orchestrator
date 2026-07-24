"""Unit tests for orchestrator.lock (single-instance Windows mutex)."""

import sys

import pytest

from orchestrator.lock import InstanceLock, _mutex_name

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("win"),
    reason="InstanceLock relies on the Windows kernel32 named-mutex API.",
)


def test_mutex_name_is_deterministic(tmp_path):
    config = tmp_path / "cfg.json"
    config.write_text("{}", encoding="utf-8")
    assert _mutex_name(str(config)) == _mutex_name(str(config))


def test_mutex_name_differs_per_config(tmp_path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text("{}", encoding="utf-8")
    b.write_text("{}", encoding="utf-8")
    assert _mutex_name(str(a)) != _mutex_name(str(b))


def test_mutex_name_is_case_insensitive_on_path(tmp_path):
    config = tmp_path / "Cfg.json"
    config.write_text("{}", encoding="utf-8")
    assert _mutex_name(str(config)) == _mutex_name(str(config).upper())


def test_acquire_and_release(tmp_path):
    config = tmp_path / "cfg.json"
    config.write_text("{}", encoding="utf-8")
    lock = InstanceLock(str(config))
    assert lock.acquire() is True
    try:
        assert lock._handle is not None
    finally:
        lock.release()
        assert lock._handle is None


def test_second_instance_cannot_acquire(tmp_path):
    config = tmp_path / "cfg.json"
    config.write_text("{}", encoding="utf-8")
    first = InstanceLock(str(config))
    second = InstanceLock(str(config))
    assert first.acquire() is True
    try:
        assert second.acquire() is False
    finally:
        first.release()


def test_context_manager_raises_when_already_held(tmp_path):
    config = tmp_path / "cfg.json"
    config.write_text("{}", encoding="utf-8")
    holder = InstanceLock(str(config))
    assert holder.acquire() is True
    try:
        with pytest.raises(RuntimeError, match="Cannot acquire instance lock"):
            with InstanceLock(str(config)):
                pass
    finally:
        holder.release()


def test_context_manager_releases_on_exit(tmp_path):
    config = tmp_path / "cfg.json"
    config.write_text("{}", encoding="utf-8")
    with InstanceLock(str(config)) as lock:
        assert lock._handle is not None
    assert lock._handle is None
    # After release a fresh acquisition must succeed again.
    again = InstanceLock(str(config))
    assert again.acquire() is True
    again.release()
