import os

from anthropic import Anthropic


def get_anthropic_client() -> Anthropic:
    """Return a configured Anthropic client.

    Auto-detects auth mode by token prefix:
      - sk-ant-oat...    OAuth token from `claude setup-token` (Bearer auth + oauth beta header)
      - sk-ant-api...    Standard API key from console.anthropic.com (x-api-key header)

    Reads ANTHROPIC_API_KEY from env.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Get a real API key from console.anthropic.com "
            "(recommended) or run `claude setup-token` to use MAX-plan OAuth."
        )

    # max_retries=5 (up from SDK default of 2) to survive transient DNS /
    # network hiccups — APIConnectionError was tanking digests when the
    # user's Windows network had brief getaddrinfo failures.
    if api_key.startswith("sk-ant-oat"):
        # OAuth tokens need Bearer auth + the oauth beta header. The SDK's
        # `auth_token` param routes the token via Authorization: Bearer instead
        # of x-api-key (which is what was causing the 401s).
        return Anthropic(
            auth_token=api_key,
            default_headers={"anthropic-beta": "oauth-2025-04-20"},
            max_retries=5,
        )
    return Anthropic(api_key=api_key, max_retries=5)
