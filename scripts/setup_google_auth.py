"""One-time Google OAuth setup for Jarvis (read-only access).

PREREQUISITE — you do this once in the Google Cloud Console (~5 min):

  1. Go to https://console.cloud.google.com/ and create a project
     (any name, e.g. "jarvis-personal").
  2. APIs & Services → Library → enable:
       - Google Classroom API
       - Google Calendar API
       - Gmail API
  3. APIs & Services → OAuth consent screen:
       - User type: External
       - Add yourself as a Test user (your Gmail address)
  4. APIs & Services → Credentials → Create Credentials →
     OAuth client ID → Application type: "Desktop app".
  5. Download the JSON. Save it to:
       credentials/google_oauth_client.json
     (relative to the repo root — the path is gitignored)

THEN run this script:

    python scripts/setup_google_auth.py

It opens your browser, you click through Google's consent screen
(read-only access), and the resulting refresh token is stored in the
Windows Credential Manager — never in a plaintext file.

    python scripts/setup_google_auth.py --reset    # forget the token
    python scripts/setup_google_auth.py --status   # check if set up
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_CLIENT_SECRET = Path("credentials") / "google_oauth_client.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Set up Google OAuth for Jarvis")
    parser.add_argument(
        "--client-secret",
        default=str(DEFAULT_CLIENT_SECRET),
        help=f"Path to the OAuth client JSON (default: {DEFAULT_CLIENT_SECRET})",
    )
    parser.add_argument("--reset", action="store_true", help="Delete the stored token")
    parser.add_argument("--status", action="store_true", help="Report whether set up")
    args = parser.parse_args(argv)

    from ai_intel.google_auth.storage import clear_token, has_token, store_token
    from ai_intel.google_auth.oauth import SCOPES, run_oauth_flow

    if args.status:
        if has_token():
            print("Google OAuth: CONFIGURED (token in keyring).")
        else:
            print("Google OAuth: NOT configured. Run without --status to set up.")
        return 0

    if args.reset:
        clear_token()
        print("Google OAuth token cleared from keyring.")
        return 0

    client_path = Path(args.client_secret)
    if not client_path.exists():
        print(
            f"ERROR: OAuth client JSON not found at {client_path}\n"
            f"Follow the steps in the docstring at the top of this file:\n"
            f"  python scripts/setup_google_auth.py --help",
            file=sys.stderr,
        )
        return 1

    print("Requesting READ-ONLY access to these Google scopes:")
    for s in SCOPES:
        print(f"  - {s}")
    print("\nOpening your browser for consent ...")

    try:
        creds = run_oauth_flow(str(client_path))
    except Exception as exc:
        print(f"ERROR: OAuth flow failed: {exc}", file=sys.stderr)
        return 1

    store_token(creds.to_json())
    print(
        "\nDone. Token stored in the Windows Credential Manager.\n"
        "Jarvis can now read your Classroom, Calendar, and Gmail (read-only).\n"
        "Verify: python scripts/setup_google_auth.py --status"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
