"""Jarvis memory layer (Phase 1).

Semantic recall over the existing intel feed + user notes. Embeddings
live in a dedicated table; cosine similarity runs in numpy (fast enough
through ~100k items).

Provider abstraction at ai_intel.memory.embed picks an embedder based
on environment:
    JARVIS_EMBEDDING_PROVIDER=voyage  → real Voyage API (VOYAGE_API_KEY req'd)
    JARVIS_EMBEDDING_PROVIDER=fake    → deterministic hash-vec (tests, dev)
    unset                              → fake (so the pipeline works without
                                         an extra credential)
"""
from ai_intel.memory.embed import Embedder, FakeEmbedder, VoyageEmbedder, get_embedder
from ai_intel.memory.retrieve import RecallResult, recall, recall_recipes
from ai_intel.memory.store import (
    add_note,
    embed_pending,
    embed_text,
    record_recipe_run,
    save_recipe,
    update_recipe_steps,
)

__all__ = [
    "Embedder",
    "FakeEmbedder",
    "VoyageEmbedder",
    "get_embedder",
    "RecallResult",
    "recall",
    "recall_recipes",
    "add_note",
    "embed_pending",
    "embed_text",
    "save_recipe",
    "update_recipe_steps",
    "record_recipe_run",
]
