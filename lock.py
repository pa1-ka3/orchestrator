"""Single-instance lock using Windows named mutex (ctypes).

Ensures only one orchestrator instance runs per config file.
The OS releases the mutex automatically if the process crashes.
"""

import ctypes
import ctypes.wintypes
import hashlib
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Windows API constants
_ERROR_ALREADY_EXISTS = 183

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_CreateMutexW = _kernel32.CreateMutexW
_CreateMutexW.argtypes = [ctypes.wintypes.LPVOID, ctypes.wintypes.BOOL, ctypes.wintypes.LPCWSTR]
_CreateMutexW.restype = ctypes.wintypes.HANDLE

_CloseHandle = _kernel32.CloseHandle
_CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
_CloseHandle.restype = ctypes.wintypes.BOOL


def _mutex_name(config_path: str) -> str:
    """Generate a deterministic mutex name from the config file path."""
    normalized = str(Path(config_path).resolve()).lower()
    path_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"Global\\PipelineOrchestrator_{path_hash}"


class InstanceLock:
    """Context manager that holds a Windows named mutex for the duration of a pipeline run."""

    def __init__(self, config_path: str):
        self._config_path = config_path
        self._mutex_name = _mutex_name(config_path)
        self._handle: Optional[int] = None

    def acquire(self) -> bool:
        """Try to acquire the mutex. Returns True if acquired, False if already held."""
        handle = _CreateMutexW(None, True, self._mutex_name)
        last_error = ctypes.get_last_error()

        if handle == 0 or handle is None:
            logger.error("Failed to create mutex '%s', error=%d", self._mutex_name, last_error)
            return False

        if last_error == _ERROR_ALREADY_EXISTS:
            _CloseHandle(handle)
            logger.warning(
                "Another instance is already running for config '%s'.",
                self._config_path,
            )
            return False

        self._handle = handle
        logger.info("Instance lock acquired: %s", self._mutex_name)
        return True

    def release(self) -> None:
        """Release the mutex."""
        if self._handle is not None:
            _CloseHandle(self._handle)
            self._handle = None
            logger.info("Instance lock released: %s", self._mutex_name)

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError(
                f"Cannot acquire instance lock for '{self._config_path}'. "
                "Another instance may be running."
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False
