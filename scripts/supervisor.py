"""Supervisor that keeps all three Jarvis services alive 24/7.

Monitors and restarts three always-on services:
  - Brain      (FastAPI on :9999)  python -m ai_intel.jarvis brain serve
  - Collector  (news daemon)       python -m ai_intel
  - Voice tray (system-tray UI)    pythonw -m voice.jarvis_voice

The supervisor itself is installed as a hidden .vbs launcher in the Windows
Startup folder so it autostarts at every logon. It also removes the old
collector-only launcher (ai-intel-collector.vbs) if present, so the
collector is no longer double-managed.

Each service has a single-instance guard; launching a service that is already
running exits cleanly and harmlessly. The supervisor still prefers polling its
own Popen handles so it does not spawn needlessly.

Run:
    python scripts/supervisor.py                   # install + start now
    python scripts/supervisor.py --remove
    python scripts/supervisor.py --status
    python scripts/supervisor.py --run             # foreground loop (advanced)
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPERVISOR_LAUNCHER_NAME = "jarvis-supervisor.vbs"
OLD_COLLECTOR_LAUNCHER_NAME = "ai-intel-collector.vbs"
POLL_INTERVAL = 30  # seconds between liveness checks

# Service definitions: (label, python_variant, module_args, log_filename)
# python_variant is "python" or "pythonw" (no console window).
_SERVICES = [
    ("Brain",     "python",  ["-m", "ai_intel.jarvis", "brain", "serve"], "brain.log"),
    ("Collector", "python",  ["-m", "ai_intel"],                           "collector.log"),
    ("Voice",     "pythonw", ["-m", "voice.jarvis_voice"],                 "voice.log"),
]


# ---------------------------------------------------------------------------
# Path helpers  (mirrors install_windows_scheduler.py)
# ---------------------------------------------------------------------------

def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def venv_python(variant: str = "python") -> Path:
    """Return the venv python(.exe) or pythonw.exe, falling back to sys.executable."""
    exe = f"{variant}.exe"
    candidate = repo_root() / ".venv" / "Scripts" / exe
    if candidate.exists():
        return candidate
    # Fallback: same directory as the running interpreter.
    return Path(sys.executable).parent / exe


def startup_dir() -> Path:
    return (
        Path(os.environ["APPDATA"])
        / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    )


def supervisor_launcher_path() -> Path:
    return startup_dir() / SUPERVISOR_LAUNCHER_NAME


def old_collector_launcher_path() -> Path:
    return startup_dir() / OLD_COLLECTOR_LAUNCHER_NAME


# ---------------------------------------------------------------------------
# .vbs body — hidden launcher for the supervisor itself
# ---------------------------------------------------------------------------

def _supervisor_vbs_body() -> str:
    """Return a VBScript that starts the supervisor hidden via pythonw."""
    root = repo_root()
    py = venv_python("pythonw")
    log = root / "data" / "supervisor.log"
    script = root / "scripts" / "supervisor.py"
    # --run skips the install flow and goes straight to the supervise loop.
    inner = (
        f'cmd /c cd /d "{root}" && "{py}" "{script}" --run '
        f'>> "{log}" 2>&1'
    )
    # VBScript string literals: double up embedded quotes.
    arg = inner.replace('"', '""')
    return (
        "' Jarvis supervisor — keeps Brain, Collector, and Voice alive.\r\n"
        "' Auto-starts at logon via the Startup folder.\r\n"
        'Set sh = CreateObject("WScript.Shell")\r\n'
        f'sh.Run "{arg}", 0, False\r\n'
    )


# ---------------------------------------------------------------------------
# install / remove / status CLI actions
# ---------------------------------------------------------------------------

def install() -> int:
    root = repo_root()
    lp = supervisor_launcher_path()

    print("Installing the Jarvis supervisor (Brain + Collector + Voice)")
    print(f"  repo:     {root}")
    print(f"  launcher: {lp}")

    # Ensure data/ exists (logs land here).
    (root / "data").mkdir(parents=True, exist_ok=True)

    # Write the supervisor .vbs.
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text(_supervisor_vbs_body(), encoding="utf-8")
    print("  -> supervisor launcher installed to the Startup folder")

    # Remove the old collector-only launcher if present.
    old_lp = old_collector_launcher_path()
    if old_lp.exists():
        old_lp.unlink()
        print(f"  -> removed superseded collector launcher: {old_lp.name}")

    # Start the supervisor now so services come up immediately.
    try:
        subprocess.Popen(["wscript.exe", str(lp)], cwd=str(root))
        print("  -> supervisor started now — Brain, Collector, and Voice are starting.")
    except Exception as exc:
        print(f"  -> installed; will start at next logon (couldn't start now: {exc})")

    print()
    print("All three services are now supervised. Check status any time:")
    print("  python scripts/supervisor.py --status")
    return 0


def remove() -> int:
    lp = supervisor_launcher_path()
    if lp.exists():
        lp.unlink()
        print(f"removed {lp}")
        print("(running services will keep running until reboot/logoff)")
    else:
        print("Supervisor launcher was not installed.")
    return 0


def status() -> int:
    lp = supervisor_launcher_path()
    installed = lp.exists()
    print(f"supervisor launcher: {'INSTALLED' if installed else 'not installed'}")
    old_lp = old_collector_launcher_path()
    if old_lp.exists():
        print(f"  WARNING: old collector launcher still present: {old_lp}")

    root = repo_root()
    log_names = [
        ("supervisor", "supervisor.log"),
        ("brain",      "brain.log"),
        ("collector",  "collector.log"),
        ("voice",      "voice.log"),
    ]
    for label, fname in log_names:
        lg = root / "data" / fname
        print()
        if not lg.exists() or lg.stat().st_size == 0:
            print(f"{label}: {fname} is empty/missing")
            continue
        print(f"{label} — last lines of {lg}:")
        lines = lg.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines[-10:]:
            print(f"  {line}")
    return 0


# ---------------------------------------------------------------------------
# Supervise loop
# ---------------------------------------------------------------------------

def _open_log(root: Path, fname: str):
    """Open a log file in append mode, creating it if necessary."""
    log = root / "data" / fname
    log.parent.mkdir(parents=True, exist_ok=True)
    return open(log, "a", encoding="utf-8")  # noqa: WPS515  (kept open by caller)


def _launch(root: Path, variant: str, module_args: list[str], log_fh) -> subprocess.Popen:
    """Start a service subprocess, returning its Popen handle."""
    py = venv_python(variant)
    cmd = [str(py)] + module_args
    return subprocess.Popen(
        cmd,
        cwd=str(root),
        stdout=log_fh,
        stderr=log_fh,
        # Prevent inheriting the supervisor's own console (if any).
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )


def supervise() -> None:
    """Main loop — poll every POLL_INTERVAL seconds; relaunch dead services."""
    root = repo_root()
    # Open one persistent log file handle per service.
    log_handles = {
        label: _open_log(root, fname)
        for label, _, _, fname in _SERVICES
    }
    handles: dict[str, subprocess.Popen | None] = {
        label: None for label, _, _, _ in _SERVICES
    }

    # Honour Ctrl+C / SIGTERM: stop the loop, leave services running.
    _running = [True]

    def _stop(signum=None, frame=None) -> None:  # noqa: ANN001
        print("[supervisor] signal received — stopping loop (services left running)")
        _running[0] = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    print(f"[supervisor] started (poll interval {POLL_INTERVAL}s)")

    while _running[0]:
        for label, variant, module_args, _fname in _SERVICES:
            handle = handles[label]
            alive = handle is not None and handle.poll() is None
            if alive:
                continue  # already running — nothing to do

            exit_code = handle.poll() if handle is not None else None
            if handle is not None:
                print(
                    f"[supervisor] {label} exited (code={exit_code}) — relaunching"
                )
            else:
                print(f"[supervisor] {label} not started — launching")

            try:
                handles[label] = _launch(root, variant, module_args, log_handles[label])
                print(f"[supervisor] {label} launched (pid={handles[label].pid})")
            except Exception as exc:
                print(f"[supervisor] {label} failed to launch: {exc}")
                # Leave handles[label] as None; will retry next cycle.
                handles[label] = None

        # Flush log files so tailed logs stay up-to-date.
        for fh in log_handles.values():
            try:
                fh.flush()
            except Exception:
                pass

        # Sleep in small increments so SIGINT is noticed promptly.
        deadline = time.monotonic() + POLL_INTERVAL
        while _running[0] and time.monotonic() < deadline:
            time.sleep(1)

    print("[supervisor] loop exited cleanly")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Jarvis supervisor — keeps Brain, Collector, and Voice tray alive 24/7"
        ),
    )
    parser.add_argument(
        "--remove",
        action="store_true",
        help="Remove the supervisor's Startup launcher",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show whether the launcher is installed and tail the service logs",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Run the supervise loop directly (used by the .vbs launcher)",
    )
    args = parser.parse_args(argv)

    if os.name != "nt":
        print("This script is Windows-only.", file=sys.stderr)
        return 2

    if args.remove:
        return remove()
    if args.status:
        return status()
    if args.run:
        supervise()
        return 0
    # Default: install + start now.
    return install()


if __name__ == "__main__":
    raise SystemExit(main())
