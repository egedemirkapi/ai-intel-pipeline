"""Register a Windows Task Scheduler entry that runs the pipeline every
2 hours, so intel + enrichment + digest keep flowing even when no
PowerShell window is open.

What gets registered:
- Task name:   ai-intel-pipeline
- Trigger:     at user login + every 2 hours while the machine is awake
- Action:      <repo>/.venv/Scripts/python.exe -m ai_intel --once
- Working dir: <repo>
- Run as:      current user (no admin elevation needed)

This is a "good enough" 24/7 approximation on a personal Windows laptop:
the pipeline runs whenever the machine is awake. For TRUE 24/7 (laptop
sleeping is a problem), do the Phase-2 cloud deploy on Fly.io.

Run:
    python scripts/install_windows_scheduler.py
    python scripts/install_windows_scheduler.py --remove

Idempotent — re-running it updates the existing task in place.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

TASK_NAME = "ai-intel-pipeline"


def repo_root() -> Path:
    """The directory containing this scripts/ folder's parent."""
    return Path(__file__).resolve().parent.parent


def venv_python() -> Path:
    """Path to the project's venv python.exe — falls back to current
    interpreter if no venv is found."""
    candidate = repo_root() / ".venv" / "Scripts" / "python.exe"
    if candidate.exists():
        return candidate
    return Path(sys.executable)


def schtasks(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["schtasks.exe", *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def install() -> int:
    root = repo_root()
    py = venv_python()
    # `cmd /c cd /d <root> && py.exe -m ai_intel --once`  — wrapping in a
    # cmd shell lets us set the working directory inline, which Task
    # Scheduler's /TR doesn't natively expose (the /TR can't take a
    # working dir argument; only the action string).
    tr = f'cmd /c cd /d "{root}" && "{py}" -m ai_intel --once'

    print(f"Installing task '{TASK_NAME}'")
    print(f"  repo:    {root}")
    print(f"  python:  {py}")
    print(f"  action:  {tr}")

    # Build the schtasks command. /SC HOURLY /MO 2 = every 2 hours.
    # /RL LIMITED = run as standard user (no UAC). /F = force overwrite
    # if a task with this name already exists.
    args = [
        "/Create",
        "/TN", TASK_NAME,
        "/TR", tr,
        "/SC", "HOURLY",
        "/MO", "2",
        "/RL", "LIMITED",
        "/F",
    ]
    res = schtasks(*args, check=False)
    if res.returncode != 0:
        print("schtasks.exe failed:", file=sys.stderr)
        print(res.stdout, file=sys.stderr)
        print(res.stderr, file=sys.stderr)
        return res.returncode

    print(res.stdout.strip())
    print()
    print(f"Done. The pipeline will now run every 2 hours while this")
    print(f"machine is awake, even with no terminal open.")
    print()
    print(f"Verify:    schtasks.exe /Query /TN {TASK_NAME}")
    print(f"Run now:   schtasks.exe /Run /TN {TASK_NAME}")
    print(f"Remove:    python scripts/install_windows_scheduler.py --remove")
    return 0


def remove() -> int:
    print(f"Removing task '{TASK_NAME}'")
    res = schtasks("/Delete", "/TN", TASK_NAME, "/F", check=False)
    if res.returncode != 0:
        print(res.stdout, file=sys.stderr)
        print(res.stderr, file=sys.stderr)
        return res.returncode
    print(res.stdout.strip())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Register the pipeline as a Windows scheduled task")
    parser.add_argument("--remove", action="store_true", help="Delete the task instead of installing")
    args = parser.parse_args(argv)
    if os.name != "nt":
        print("This script is Windows-only (uses schtasks.exe).", file=sys.stderr)
        return 2
    return remove() if args.remove else install()


if __name__ == "__main__":
    raise SystemExit(main())
