"""Google Workspace read-only auth + token storage.

Max-privacy posture:
- OAuth refresh tokens live in the OS keyring (Windows Credential
  Manager), never in plaintext files in the repo.
- Scopes are read-only ONLY. No write/send/modify scope is ever
  requested, so even a compromised token cannot mutate the user's
  Google data.
- The OAuth client secret (downloaded from Google Cloud Console) is
  the only file on disk, and per Google's own guidance for installed
  apps it is not treated as a high-value secret (the refresh token is
  what matters, and that goes to keyring).

Public surface:
    SCOPES            — the exact read-only scope list
    get_credentials() — load + auto-refresh stored credentials
    build_service()   — construct a Google API client
    store_token() / load_token() / clear_token() — keyring ops
"""
from ai_intel.google_auth.oauth import (
    SCOPES,
    build_service,
    get_credentials,
    run_oauth_flow,
)
from ai_intel.google_auth.storage import (
    clear_token,
    has_token,
    load_token,
    store_token,
)

__all__ = [
    "SCOPES",
    "build_service",
    "get_credentials",
    "run_oauth_flow",
    "clear_token",
    "has_token",
    "load_token",
    "store_token",
]
