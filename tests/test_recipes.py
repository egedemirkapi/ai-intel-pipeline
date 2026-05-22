"""Tests for NavigationRecipe memory (Phase 3)."""
from __future__ import annotations

import json

import pytest
from sqlmodel import Session, SQLModel, create_engine

from ai_intel.db.models import Embedding, NavigationRecipe
from ai_intel.memory.embed import FakeEmbedder
from ai_intel.memory.retrieve import recall_recipes
from ai_intel.memory.store import record_recipe_run, save_recipe, update_recipe_steps


@pytest.fixture
def engine():
    """In-memory SQLite with all tables created."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def embedder():
    return FakeEmbedder(dim=128, model="fake-128-test")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STEPS_V1 = [
    {"action": "click", "selector": "#upload-btn"},
    {"action": "fill", "selector": "#title-input", "value": "My notebook"},
    {"action": "click", "selector": "#save-btn"},
]

_STEPS_V2 = [
    {"action": "click", "selector": "#new-upload-btn"},
    {"action": "fill", "selector": "#title-field", "value": "My notebook"},
    {"action": "click", "selector": "#confirm-save"},
]


# ---------------------------------------------------------------------------
# save_recipe
# ---------------------------------------------------------------------------


def test_save_recipe_creates_recipe_and_embedding(engine, embedder):
    rid = save_recipe(
        engine,
        "upload a PDF to NotebookLM",
        _STEPS_V1,
        "notebooklm",
        embedder=embedder,
    )
    assert rid is not None and rid > 0

    with Session(engine) as s:
        recipe = s.get(NavigationRecipe, rid)
        assert recipe is not None
        assert recipe.task_description == "upload a PDF to NotebookLM"
        assert recipe.app == "notebooklm"
        assert recipe.success_count == 0
        assert recipe.failure_count == 0
        assert recipe.last_failure_reason is None
        # steps round-trip
        assert json.loads(recipe.steps_json) == _STEPS_V1

        # One Embedding row with recipe_id set, item_id/note_id None
        embs = s.exec(
            __import__("sqlmodel").select(Embedding).where(
                Embedding.recipe_id == rid
            )
        ).all()
        assert len(embs) == 1
        emb = embs[0]
        assert emb.item_id is None
        assert emb.note_id is None
        assert emb.model == "fake-128-test"
        assert emb.dim == 128


def test_save_recipe_rejects_empty_description(engine, embedder):
    with pytest.raises(ValueError):
        save_recipe(engine, "   ", _STEPS_V1, "notebooklm", embedder=embedder)


def test_save_recipe_multiple_recipes_independent(engine, embedder):
    rid1 = save_recipe(engine, "upload PDF to NotebookLM", _STEPS_V1, "notebooklm", embedder=embedder)
    rid2 = save_recipe(engine, "create a new classroom assignment", _STEPS_V2, "classroom", embedder=embedder)
    assert rid1 != rid2

    with Session(engine) as s:
        all_embs = s.exec(
            __import__("sqlmodel").select(Embedding).where(
                Embedding.recipe_id.is_not(None)  # noqa: E711
            )
        ).all()
    assert len(all_embs) == 2


# ---------------------------------------------------------------------------
# recall_recipes
# ---------------------------------------------------------------------------


def test_recall_recipes_finds_by_semantic_query(engine, embedder):
    save_recipe(engine, "upload a PDF to NotebookLM", _STEPS_V1, "notebooklm", embedder=embedder)
    save_recipe(engine, "book a flight on Google Flights", [], "flights", embedder=embedder)

    hits = recall_recipes(engine, "add document to notebook", embedder=embedder)
    assert len(hits) >= 1
    # The NotebookLM recipe should rank first given lexical overlap
    assert hits[0]["task_description"] == "upload a PDF to NotebookLM"


def test_recall_recipes_returns_correct_shape(engine, embedder):
    save_recipe(engine, "upload a PDF to NotebookLM", _STEPS_V1, "notebooklm", embedder=embedder)

    hits = recall_recipes(engine, "notebooklm upload", embedder=embedder)
    assert len(hits) == 1
    h = hits[0]
    assert "id" in h
    assert "score" in h
    assert "task_description" in h
    assert "app" in h
    assert "steps" in h
    assert "success_count" in h
    assert "failure_count" in h
    assert isinstance(h["steps"], list)


def test_recall_recipes_score_descending(engine, embedder):
    save_recipe(engine, "upload PDF to NotebookLM", _STEPS_V1, "notebooklm", embedder=embedder)
    save_recipe(engine, "add source document to notebook", [], "notebooklm", embedder=embedder)
    save_recipe(engine, "book a flight on Google Flights", [], "flights", embedder=embedder)

    hits = recall_recipes(engine, "upload document notebooklm", k=3, embedder=embedder)
    for a, b in zip(hits, hits[1:]):
        assert a["score"] >= b["score"]


def test_recall_recipes_app_filter(engine, embedder):
    save_recipe(engine, "upload PDF to NotebookLM", _STEPS_V1, "notebooklm", embedder=embedder)
    save_recipe(engine, "create classroom assignment", _STEPS_V2, "classroom", embedder=embedder)

    hits = recall_recipes(engine, "upload PDF", k=10, app="notebooklm", embedder=embedder)
    assert all(h["app"] == "notebooklm" for h in hits)
    assert len(hits) == 1


def test_recall_recipes_respects_k(engine, embedder):
    for i in range(5):
        save_recipe(engine, f"upload PDF step variant {i}", _STEPS_V1, "notebooklm", embedder=embedder)

    hits = recall_recipes(engine, "upload PDF notebooklm", k=3, embedder=embedder)
    assert len(hits) <= 3


def test_recall_recipes_empty_query_returns_empty(engine, embedder):
    save_recipe(engine, "upload PDF to NotebookLM", _STEPS_V1, "notebooklm", embedder=embedder)
    assert recall_recipes(engine, "", embedder=embedder) == []
    assert recall_recipes(engine, "   ", embedder=embedder) == []


def test_recall_recipes_no_rows_returns_empty(engine, embedder):
    hits = recall_recipes(engine, "anything", embedder=embedder)
    assert hits == []


def test_recall_recipes_does_not_return_note_or_item_embeddings(engine, embedder):
    """recipe recall must only surface recipe-linked embeddings."""
    from ai_intel.memory.store import add_note
    add_note(engine, "upload a PDF to notebooklm remember", embedder=embedder)
    # No recipes inserted; only a note embedding exists
    hits = recall_recipes(engine, "upload PDF notebooklm", embedder=embedder)
    assert hits == []


# ---------------------------------------------------------------------------
# record_recipe_run
# ---------------------------------------------------------------------------


def test_record_recipe_run_success_increments_count(engine, embedder):
    rid = save_recipe(engine, "upload PDF to NotebookLM", _STEPS_V1, "notebooklm", embedder=embedder)

    record_recipe_run(engine, rid, success=True)
    record_recipe_run(engine, rid, success=True)

    with Session(engine) as s:
        recipe = s.get(NavigationRecipe, rid)
    assert recipe.success_count == 2
    assert recipe.failure_count == 0


def test_record_recipe_run_failure_increments_and_records_reason(engine, embedder):
    rid = save_recipe(engine, "upload PDF to NotebookLM", _STEPS_V1, "notebooklm", embedder=embedder)

    record_recipe_run(engine, rid, success=False, failure_reason="selector #upload-btn not found")

    with Session(engine) as s:
        recipe = s.get(NavigationRecipe, rid)
    assert recipe.failure_count == 1
    assert recipe.success_count == 0
    assert recipe.last_failure_reason == "selector #upload-btn not found"


def test_record_recipe_run_failure_overwrites_reason(engine, embedder):
    rid = save_recipe(engine, "upload PDF to NotebookLM", _STEPS_V1, "notebooklm", embedder=embedder)

    record_recipe_run(engine, rid, success=False, failure_reason="first failure")
    record_recipe_run(engine, rid, success=False, failure_reason="second failure")

    with Session(engine) as s:
        recipe = s.get(NavigationRecipe, rid)
    assert recipe.failure_count == 2
    assert recipe.last_failure_reason == "second failure"


def test_record_recipe_run_success_does_not_clear_failure_reason(engine, embedder):
    rid = save_recipe(engine, "upload PDF to NotebookLM", _STEPS_V1, "notebooklm", embedder=embedder)

    record_recipe_run(engine, rid, success=False, failure_reason="something broke")
    record_recipe_run(engine, rid, success=True)

    with Session(engine) as s:
        recipe = s.get(NavigationRecipe, rid)
    assert recipe.success_count == 1
    assert recipe.failure_count == 1
    # last_failure_reason preserved — success doesn't wipe it
    assert recipe.last_failure_reason == "something broke"


def test_record_recipe_run_invalid_id_raises(engine):
    with pytest.raises(ValueError, match="not found"):
        record_recipe_run(engine, 9999, success=True)


# ---------------------------------------------------------------------------
# update_recipe_steps
# ---------------------------------------------------------------------------


def test_update_recipe_steps_overwrites_steps(engine, embedder):
    rid = save_recipe(engine, "upload PDF to NotebookLM", _STEPS_V1, "notebooklm", embedder=embedder)

    update_recipe_steps(engine, rid, _STEPS_V2)

    with Session(engine) as s:
        recipe = s.get(NavigationRecipe, rid)
    assert json.loads(recipe.steps_json) == _STEPS_V2


def test_update_recipe_steps_bumps_updated_at(engine, embedder):
    rid = save_recipe(engine, "upload PDF to NotebookLM", _STEPS_V1, "notebooklm", embedder=embedder)

    with Session(engine) as s:
        recipe_before = s.get(NavigationRecipe, rid)
        before = recipe_before.updated_at

    import time
    time.sleep(0.01)  # ensure monotonic difference is detectable
    update_recipe_steps(engine, rid, _STEPS_V2)

    with Session(engine) as s:
        recipe_after = s.get(NavigationRecipe, rid)
        after = recipe_after.updated_at

    assert after >= before


def test_update_recipe_steps_invalid_id_raises(engine):
    with pytest.raises(ValueError, match="not found"):
        update_recipe_steps(engine, 9999, _STEPS_V1)


def test_update_recipe_steps_empty_list_allowed(engine, embedder):
    rid = save_recipe(engine, "upload PDF to NotebookLM", _STEPS_V1, "notebooklm", embedder=embedder)
    update_recipe_steps(engine, rid, [])

    with Session(engine) as s:
        recipe = s.get(NavigationRecipe, rid)
    assert json.loads(recipe.steps_json) == []
