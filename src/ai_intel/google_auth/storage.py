"""Keyring-backed storage for the Google OAuth token.

The token (a JSON blob containing the refresh token, access token,
scopes, expiry) is stored in the OS keyring under a fixed service +
username. On Windows this is the Credential Manager — encrypted at
rest, tied to the user account.

Why keyring instead of a file: the refresh token is the one durable
secret in the whole Google integration. A file in the repo (even
gitignored) is readable by any process running as the user and ends
up in backups. The keyring is the OS's purpose-built secret store.
"""
from __future__ import annotations

import json
import logging

import keyring

logger = logging.getLogger(__name__)

# Keyring coordinates. One token blob for all Google APIs (they share
# scopes under a single consent).
_SERVICE = "jarvis-google-oauth"
_USERNAME = "default"


def store_token(token_json: str) -> None:
    """Persist the OAuth token JSON blob into the OS keyring."""
    keyring.set_password(_SERVICE, _USERNAME, token_json)
    logger.info("google_auth: token stored in OS keyring")


def load_token() -> str | None:
    """Return the stored token JSON blob, or None if not set up."""
    try:
        return keyring.get_password(_SERVICE, _USERNAME)
    except Exception as exc:  # keyring backend issues — fail soft
        logger.warning("google_auth: keyring read failed: %s", exc)
        return None


def has_token() -> bool:
    return load_token() is not None


def clear_token() -> None:
    """Remove the stored token. Used by `setup_google_auth.py --reset`."""
    try:
        keyring.delete_password(_SERVICE, _USERNAME)
        logger.info("google_auth: token cleared from keyring")
    except keyring.errors.PasswordDeleteError:
        pass  # already absent — fine


def parse_token(token_json: str) -> dict:
    """Parse a token blob; raises ValueError on malformed JSON."""
    try:
        return json.loads(token_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"stored Google token is not valid JSON: {exc}") from exc
