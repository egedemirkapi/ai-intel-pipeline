"""Make the AI-intel collector run 24/7 — auto-start at every logon.

Runs the pipeline **daemon** (`python -m ai_intel`) — the continuous
collect / enrich / digest loop that fills the vault the idea-finder
reads. It starts automatically every time you log in and runs hidden in
the background, so tech news flows in 24/7 with no terminal open.

Uses a Startup-folder launcher (no admin needed). Creating a Windows
*scheduled task* requires administrator rights on this machine; the
Startup folder does not, and is just as "always-on" for a personal
laptop. The daemon's single-instance guard stops it double-running.

Run:
    python scripts/install_windows_scheduler.py            # install + start now
    python scripts/install_windows_scheduler.py --status
    python scripts/install_windows_scheduler.py --remove
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

LAUNCHER_NAME = "ai-intel-collector.vbs"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def venv_python() -> Path:
    candidate = repo_root() / ".venv" / "Scripts" / "python.exe"
    return candidate if candidate.exists() else Path(sys.executable)


def startup_dir() -> Path:
    return (
        Path(os.environ["APPDATA"])
        / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    )


def launcher_path() -> Path:
    return startup_dir() / LAUNCHER_NAME


def log_path() -> Path:
    return repo_root() / "data" / "collector.log"


def _vbs_body() -> str:
    """A .vbs that launches the daemon hidden, logging to data/collector.log."""
    root, py, log = repo_root(), venv_python(), log_path()
    inner = f'cmd /c cd /d "{root}" && "{py}" -m ai_intel >> "{log}" 2>&1'
    # In VBScript string literals, embedded double-quotes are doubled.
    arg = inner.replace('"', '""')
    return (
        "' AI-intel collector — 24/7 tech-news daemon. Auto-starts at logon.\r\n"
        'Set sh = CreateObject("WScript.Shell")\r\n'
        f'sh.Run "{arg}", 0, False\r\n'
    )


def install() -> int:
    root = repo_root()
    lp = launcher_path()
    print("Installing the always-on AI-intel collector")
    print(f"  repo:     {root}")
    print(f"  launcher: {lp}")
    print(f"  log:      {log_path()}")

    log_path().parent.mkdir(parents=True, exist_ok=True)
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text(_vbs_body(), encoding="utf-8")
    print("  -> installed to the Startup folder (runs at every logon)")

    # Start it now so the collector is running immediately.
    try:
        subprocess.Popen(["wscript.exe", str(lp)], cwd=str(root))
        print("  -> started now — the collector is running in the background.")
    except Exception as exc:
        print(f"  -> installed; will start at next logon (couldn't start now: {exc})")

    print()
    print("It now runs 24/7. Check it any time with:")
    print("  python scripts/install_windows_scheduler.py --status")
    return 0


def status() -> int:
    lp = launcher_path()
    print(f"autostart launcher: {'INSTALLED' if lp.exists() else 'not installed'}")
    lg = log_path()
    if lg.exists() and lg.stat().st_size > 0:
        print(f"\nlast lines of {lg}:")
        lines = lg.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines[-12:]:
            print(f"  {line}")
    else:
        print("collector.log is empty/missing — the daemon may not have run yet.")
    return 0


def remove() -> int:
    lp = launcher_path()
    if lp.exists():
        lp.unlink()
        print(f"removed {lp}")
        print("(a collector already running will keep running until reboot/logoff)")
    else:
        print("autostart launcher was not installed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Make the AI-intel collector run 24/7 (auto-start at logon)",
    )
    parser.add_argument("--remove", action="store_true", help="Remove the autostart")
    parser.add_argument("--status", action="store_true", help="Show autostart + recent log")
    args = parser.parse_args(argv)
    if os.name != "nt":
        print("This script is Windows-only.", file=sys.stderr)
        return 2
    if args.remove:
        return remove()
    if args.status:
        return status()
    return install()


if __name__ == "__main__":
    raise SystemExit(main())
