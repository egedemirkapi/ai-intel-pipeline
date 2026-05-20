"""Google OAuth — installed-app flow + credential loading.

Read-only scopes only. The flow:

  First time   →  run_oauth_flow(client_secret_path)
                   opens a browser, user consents, returns Credentials,
                   caller stores them via storage.store_token().

  Every use    →  get_credentials()
                   loads the token blob from keyring, refreshes the
                   access token if expired, returns live Credentials.

  API client   →  build_service("classroom", "v1")
                   returns a googleapiclient Resource ready to call.
"""
from __future__ import annotations

import json
import logging
import os

# Google often grants a slightly different scope set than requested —
# e.g. it swaps classroom.coursework.me.readonly for
# classroom.student-submissions.me.readonly. oauthlib treats ANY
# difference between requested and granted scopes as a fatal error;
# this env var tells it to accept whatever Google actually grants.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from ai_intel.google_auth.storage import load_token, store_token

logger = logging.getLogger(__name__)

# READ-ONLY scopes. Never add a write/send/modify scope here — the
# capability layer denies those tools anyway, but defense-in-depth
# means we also never even REQUEST the permission.
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.me.readonly",
    "https://www.googleapis.com/auth/classroom.announcements.readonly",
]


def run_oauth_flow(client_secret_path: str) -> Credentials:
    """Run the interactive installed-app OAuth flow.

    Opens the system browser for Google's consent screen, captures the
    redirect on a localhost port, and returns live Credentials. The
    caller is responsible for persisting them via storage.store_token().

    ``client_secret_path`` points at the OAuth client JSON downloaded
    from Google Cloud Console (Desktop-app credential type).
    """
    flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
    # port=0 lets the OS pick a free localhost port for the redirect.
    creds = flow.run_local_server(port=0, prompt="consent")
    return creds


def get_credentials() -> Credentials:
    """Load stored credentials, refresh if expired, return them.

    Raises RuntimeError if no token is stored (user hasn't run
    ``scripts/setup_google_auth.py`` yet).
    """
    blob = load_token()
    if not blob:
        raise RuntimeError(
            "No Google token stored. Run `python scripts/setup_google_auth.py` "
            "to grant read-only access first."
        )
    info = json.loads(blob)
    creds = Credentials.from_authorized_user_info(info, SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Persist the refreshed access token back to keyring
            store_token(creds.to_json())
            logger.info("google_auth: refreshed access token")
        else:
            raise RuntimeError(
                "Google credentials invalid and not refreshable — "
                "re-run `python scripts/setup_google_auth.py`."
            )
    return creds


def build_service(api_name: str, version: str):
    """Construct a Google API client for the given API.

    Examples:
        build_service("classroom", "v1")
        build_service("calendar", "v3")
        build_service("gmail", "v1")
    """
    creds = get_credentials()
    # cache_discovery=False avoids a noisy warning + a stale on-disk cache
    return build(api_name, version, credentials=creds, cache_discovery=False)
