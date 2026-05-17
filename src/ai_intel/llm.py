import os

from anthropic import Anthropic


def get_anthropic_client() -> Anthropic:
    """Return a configured Anthropic client.

    Reads ANTHROPIC_API_KEY from env. Works with both pay-per-token keys
    and MAX-plan OAuth tokens (sk-ant-oat-...) set by `claude setup-token`.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Run `claude setup-token` to authenticate."
        )
    return Anthropic(api_key=api_key)
