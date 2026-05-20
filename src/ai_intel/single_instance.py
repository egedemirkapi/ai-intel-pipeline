"""Single-instance process guard.

Stops a second copy of a long-running process (the voice tray, the Brain)
from starting when one is already running — the root of the "six PowerShell
windows, which one is which" confusion.

On Windows it uses a named kernel mutex (``CreateMutexW``): the OS releases
it automatically when the process dies, so there are no stale locks. On
POSIX it falls back to an exclusive PID lockfile in the temp directory and
treats a lockfile owned by a dead PID as stale.

Usage::

    from ai_intel.single_instance import acquire_single_instance

    if not acquire_single_instance("jarvis-voice-tray"):
        print("Already running.")
        raise SystemExit(0)
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Keep acquired OS handles referenced for the process lifetime so they are
# not garbage-collected (which would release the lock early).
_HELD: list = []


def acquire_single_instance(name: str) -> bool:
    """Return ``True`` if this is the only instance, ``False`` otherwise.

    ``name`` must be stable for a given logical process (e.g.
    ``"jarvis-voice-tray"``). The lock is held until the process exits.
    """
    if sys.platform == "win32":
        return _acquire_windows(name)
    return _acquire_posix(name)


def _acquire_windows(name: str) -> bool:
    import ctypes

    ERROR_ALREADY_EXISTS = 183
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    # "Local\\" namespace = per-user session, which is what we want.
    handle = kernel32.CreateMutexW(None, False, f"Local\\{name}")
    last_error = kernel32.GetLastError()
    if not handle:
        # Could not create the mutex at all — fail open (allow start).
        return True
    if last_error == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _HELD.append(handle)
    return True


def _acquire_posix(name: str) -> bool:
    lock_path = Path(tempfile.gettempdir()) / f"{name}.lock"
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        # A lockfile exists — is its owner still alive?
        try:
            pid = int(lock_path.read_text().strip() or "0")
        except (ValueError, OSError):
            pid = 0
        if pid and _pid_alive(pid):
            return False
        # Stale lock — reclaim it.
        try:
            lock_path.unlink()
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except OSError:
            return False
    os.write(fd, str(os.getpid()).encode())
    _HELD.append(fd)
    return True


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
