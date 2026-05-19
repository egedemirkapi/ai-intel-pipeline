"""Pluggable embedding providers.

Default is `fake` — deterministic hash-based vectors that let the rest of
the memory layer (store + retrieve + tests) run with zero credentials.
Switch to `voyage` by setting JARVIS_EMBEDDING_PROVIDER=voyage and
VOYAGE_API_KEY in env.
"""
from __future__ import annotations

import hashlib
import os
from typing import Protocol

import numpy as np


class Embedder(Protocol):
    """Anything that turns a string into a fixed-dim float32 vector."""
    model: str
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray:
        """Return shape (len(texts), self.dim) float32."""
        ...


class FakeEmbedder:
    """Deterministic hash-based embedder for tests and offline dev.

    Not semantically meaningful — but stable: same text always produces
    the same vector, similar lexical content produces somewhat similar
    vectors (because we mix multiple n-gram hashes). Good enough to
    exercise the retrieve code path.
    """

    def __init__(self, dim: int = 256, model: str = "fake-256") -> None:
        self.dim = dim
        self.model = model

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            out[i] = self._one(t)
        return out

    def _one(self, text: str) -> np.ndarray:
        text = (text or "").lower()
        vec = np.zeros(self.dim, dtype=np.float32)
        # Mix unigrams and bigrams so similar texts have similar vectors
        tokens = text.split()
        bigrams = [" ".join(p) for p in zip(tokens, tokens[1:])]
        for piece in tokens + bigrams:
            h = hashlib.sha256(piece.encode("utf-8")).digest()
            idx = int.from_bytes(h[:4], "big") % self.dim
            sign = 1.0 if h[4] & 1 else -1.0
            vec[idx] += sign
        # L2 normalize so cosine == dot product
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec


class VoyageEmbedder:
    """Voyage AI embeddings via their HTTP API.

    Defaults to ``voyage-3`` (~$0.06 / 1M tokens, dim=1024). Requires
    ``VOYAGE_API_KEY`` in env. Uses httpx (already a project dep) so we
    don't take on the voyageai SDK as a hard dependency.

    Handles 429s with exponential backoff so we respect free-tier limits
    (3 RPM, 10K TPM) without manual baby-sitting.
    """
    API_URL = "https://api.voyageai.com/v1/embeddings"
    # Free tier: 3 RPM, 10K TPM (use VOYAGE_MIN_SECONDS_BETWEEN_REQUESTS=22).
    # Paid tier 2+: 2000 RPM, 1M TPM (default 0.5s is fine).
    # The env var lets you tune without code changes.
    MIN_SECONDS_BETWEEN_REQUESTS = float(
        os.getenv("VOYAGE_MIN_SECONDS_BETWEEN_REQUESTS", "0.5")
    )
    MAX_RETRIES = 6

    def __init__(
        self,
        model: str = "voyage-3",
        dim: int = 1024,
        api_key: str | None = None,
    ) -> None:
        self.model = model
        self.dim = dim
        self._api_key = api_key or os.getenv("VOYAGE_API_KEY", "")
        if not self._api_key:
            raise RuntimeError(
                "VoyageEmbedder requires VOYAGE_API_KEY. "
                "Get one at https://dash.voyageai.com (free tier covers ~50M tokens)."
            )
        self._last_request_at: float = 0.0

    def _throttle(self) -> None:
        import time
        elapsed = time.monotonic() - self._last_request_at
        wait = self.MIN_SECONDS_BETWEEN_REQUESTS - elapsed
        if wait > 0:
            time.sleep(wait)

    def embed(self, texts: list[str]) -> np.ndarray:
        import time

        import httpx  # already a project dep

        attempt = 0
        while True:
            self._throttle()
            self._last_request_at = time.monotonic()
            resp = httpx.post(
                self.API_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "input": texts,
                    "model": self.model,
                    "input_type": "document",
                },
                timeout=60.0,
            )
            if resp.status_code == 429:
                attempt += 1
                if attempt > self.MAX_RETRIES:
                    raise RuntimeError(
                        f"Voyage 429 after {self.MAX_RETRIES} retries — "
                        f"upgrade tier or wait. Body: {resp.text[:200]}"
                    )
                # Respect Retry-After if present, else exponential backoff
                retry_after = resp.headers.get("retry-after")
                wait = float(retry_after) if retry_after else min(60.0, 5.0 * (2 ** (attempt - 1)))
                time.sleep(wait)
                continue
            resp.raise_for_status()
            break

        data = resp.json()["data"]
        vecs = np.array([d["embedding"] for d in data], dtype=np.float32)
        # Normalize for cosine-via-dot-product
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vecs / norms


def get_embedder() -> Embedder:
    """Factory. Reads JARVIS_EMBEDDING_PROVIDER (default: ``fake``)."""
    provider = os.getenv("JARVIS_EMBEDDING_PROVIDER", "fake").lower()
    if provider == "voyage":
        return VoyageEmbedder()
    if provider == "fake":
        return FakeEmbedder()
    raise ValueError(
        f"Unknown JARVIS_EMBEDDING_PROVIDER={provider!r}. Expected 'voyage' or 'fake'."
    )
