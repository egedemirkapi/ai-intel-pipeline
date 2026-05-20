"""Cost-aware LLM router.

Two paths, picked at call time:
    "oauth"    → HTTP POST to a laptop-side OpenJarvis bridge that wraps
                 the Claude Code SDK + OAuth subscription. Cost = $0.
    "api_key"  → standard Anthropic API via the existing ai_intel.llm
                 client. Cost is recorded per the published per-token
                 pricing table (Haiku / Sonnet).

Routing rule:
    prefer="oauth" and the bridge is reachable  → oauth
    prefer="oauth" but bridge unreachable       → fall back to api_key
    prefer="api_key"                            → api_key

The bridge URL comes from env: JARVIS_OAUTH_BRIDGE_URL (e.g.
"http://192.168.1.5:9777/jask"). Health probe results are cached for
~60s to avoid hammering the laptop on every call.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Iterable, Literal

import httpx

logger = logging.getLogger(__name__)

AuthMode = Literal["oauth", "api_key"]
DEFAULT_BRIDGE_URL = os.getenv("JARVIS_OAUTH_BRIDGE_URL", "")

# Published per-million-token prices (USD). Haiku and Sonnet IDs match
# what the cloud engine in ai_intel.llm sees from console.anthropic.com.
PRICING: dict[str, tuple[float, float]] = {
    # (input_per_M, output_per_M)
    "claude-haiku-4-5":       (1.00, 5.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-sonnet-4-6":      (3.00, 15.00),
    "claude-opus-4-6":        (5.00, 25.00),
    "claude-opus-4-7":        (5.00, 25.00),
}

DEFAULT_MODEL = "claude-haiku-4-5"

# Cached bridge health: (last_probe_ts, was_up). Guarded by ``_HEALTH_LOCK``
# because multiple agents (proposer, evaluator, synthesizer, ideation) run
# concurrently under asyncio + the @agent decorator and would otherwise
# race on the check-then-set pattern, producing spurious bridge-down
# warnings (or worse — using a stale-True cache to call an unreachable
# bridge).
_BRIDGE_HEALTH: tuple[float, bool] = (0.0, False)
_HEALTH_LOCK = threading.Lock()
_HEALTH_TTL_S = 60.0


@dataclass
class LLMResponse:
    text: str
    prompt_tokens: int
    completion_tokens: int
    auth_mode: AuthMode
    model: str
    cost_usd: float

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Return cost in USD per Anthropic's published prices. Unknown
    models default to Haiku-level pricing so we never under-count."""
    in_per_m, out_per_m = PRICING.get(model, PRICING[DEFAULT_MODEL])
    return (prompt_tokens / 1_000_000.0) * in_per_m + (
        completion_tokens / 1_000_000.0
    ) * out_per_m


def _bridge_url(override: str | None) -> str:
    return override or DEFAULT_BRIDGE_URL or ""


def _is_bridge_reachable(bridge_url: str, *, force_probe: bool = False) -> bool:
    """Cheap health probe with TTL cache. Returns True if /healthz responds
    200 within 2s. Cached for ``_HEALTH_TTL_S`` (60s).

    Thread-safe: the cache read + write are serialized via ``_HEALTH_LOCK``
    so concurrent agents don't race on the check-then-set pattern. We
    release the lock before the HTTP probe (so a slow probe doesn't
    block other readers), then re-acquire to publish the result — at
    worst two callers probe at once, but neither sees torn state.
    """
    global _BRIDGE_HEALTH
    if not bridge_url:
        return False
    now = time.time()
    with _HEALTH_LOCK:
        last_ts, last_up = _BRIDGE_HEALTH
        if not force_probe and now - last_ts < _HEALTH_TTL_S:
            return last_up
    health_url = bridge_url.rstrip("/").rsplit("/", 1)[0] + "/healthz"
    try:
        r = httpx.get(health_url, timeout=2.0)
        up = r.status_code == 200
    except Exception:
        up = False
    with _HEALTH_LOCK:
        _BRIDGE_HEALTH = (now, up)
    return up


def _call_oauth_bridge(
    bridge_url: str,
    messages: list[dict],
    *,
    timeout: float = 90.0,
) -> LLMResponse:
    """Send a chat-completion-style payload to the laptop bridge.

    Validates the response shape. If the bridge returns malformed JSON,
    an explicit error payload, or a missing/empty ``text`` field, raises
    ``RuntimeError`` so ``call_llm()`` can fall back to the API-key path
    rather than silently treating it as a free zero-token success.
    """
    r = httpx.post(
        bridge_url,
        json={"messages": messages},
        timeout=timeout,
    )
    r.raise_for_status()
    try:
        data = r.json()
    except ValueError as exc:
        raise RuntimeError(f"bridge returned non-JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"bridge response not a dict: {type(data).__name__}")
    if "error" in data:
        raise RuntimeError(f"bridge returned error: {data['error']!r}")
    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("bridge response missing or empty 'text' field")
    return LLMResponse(
        text=text,
        prompt_tokens=int(data.get("prompt_tokens", 0)),
        completion_tokens=int(data.get("completion_tokens", 0)),
        auth_mode="oauth",
        model=data.get("model", "claude-via-oauth"),
        cost_usd=0.0,  # subscription path = no marginal cost
    )


def _call_api_key(
    messages: list[dict],
    *,
    model: str,
    max_tokens: int,
    temperature: float,
    max_retries: int = 5,
) -> LLMResponse:
    """Standard Anthropic API call via the existing project client.

    Adds explicit 429 backoff on top of the SDK's built-in retries because
    Anthropic Tier 1 (new accounts) has tight Sonnet caps and a long
    evaluator chain hits them fast.
    """
    import time

    import anthropic

    from ai_intel.llm import get_anthropic_client

    client = get_anthropic_client()
    attempt = 0
    while True:
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=messages,
            )
            break
        except anthropic.RateLimitError as exc:
            attempt += 1
            if attempt > max_retries:
                raise
            # Honor Retry-After if present, else exponential backoff
            wait = 5.0 * (2 ** (attempt - 1))
            retry_after = None
            response = getattr(exc, "response", None)
            if response is not None:
                ra = response.headers.get("retry-after")
                if ra:
                    try:
                        retry_after = float(ra)
                    except ValueError:
                        retry_after = None
            wait = retry_after if retry_after is not None else min(wait, 60.0)
            logger.warning(
                "Anthropic 429 (attempt %d/%d) — sleeping %.1fs",
                attempt, max_retries, wait,
            )
            time.sleep(wait)

    text = ""
    if resp.content:
        first = resp.content[0]
        text = getattr(first, "text", "") or ""
    pt = getattr(resp.usage, "input_tokens", 0) or 0
    ct = getattr(resp.usage, "output_tokens", 0) or 0
    return LLMResponse(
        text=text,
        prompt_tokens=pt,
        completion_tokens=ct,
        auth_mode="api_key",
        model=model,
        cost_usd=estimate_cost_usd(model, pt, ct),
    )


def call_llm(
    messages: Iterable[dict],
    *,
    prefer: AuthMode = "oauth",
    model: str = DEFAULT_MODEL,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    bridge_url: str | None = None,
) -> LLMResponse:
    """Route an LLM call.

    Args:
        messages: anthropic-style [{role, content}, ...].
        prefer:   "oauth" (free, subscription) preferred; if bridge is
                  unreachable, falls through to API key. "api_key" skips
                  the bridge probe.
        model:    only used in the api_key path (oauth = whatever the
                  bridge picks).
        max_tokens / temperature: api_key path only.
        bridge_url: override JARVIS_OAUTH_BRIDGE_URL for tests.
    """
    msgs = list(messages)
    if prefer == "oauth":
        url = _bridge_url(bridge_url)
        if url and _is_bridge_reachable(url):
            try:
                return _call_oauth_bridge(url, msgs)
            except Exception as exc:
                logger.warning("OAuth bridge call failed (%s); falling back", exc)
        # Fall through

    return _call_api_key(
        msgs,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )
