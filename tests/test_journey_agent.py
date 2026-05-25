"""Tests for the journey agent — multi-step browser orchestrator.

The decomposer LLM call and the navigator agent are both mocked, so
the journey agent's wiring (decompose → run-each-substep → thread
files between them) is verified without a browser or live LLM call.
"""
from __future__ import annotations

import asyncio
import importlib
import json

import pytest
from sqlmodel import SQLModel, create_engine

# The journey *module* (not the re-exported function from
# `ai_intel.agents.__init__` — that namespace shadows the submodule
# with `from ai_intel.agents.journey import journey`). Going through
# importlib bypasses the shadowing so monkeypatch.setattr targets
# module attributes (`call_llm`, `_journey_dir`) cleanly.
journey_mod = importlib.import_module("ai_intel.agents.journey")
nav_mod = importlib.import_module("ai_intel.agents.navigator")


class _FakeLLMResponse:
    """Just enough of an LLMResponse for the decomposer to consume."""

    def __init__(self, text: str):
        self.text = text
        self.prompt_tokens = 100
        self.completion_tokens = 50
        self.cost_usd = 0.001
        self.auth_mode = "oauth"


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


def test_journey_decomposes_then_executes_each_substep(engine, monkeypatch, tmp_path):
    """Happy path: decomposer returns 3 substeps; the journey runs the
    navigator once per substep, threads downloaded files between them,
    and shares one per-journey save_dir across the whole chain.

    This is the flagship-path wiring: *"Classroom → download → NotebookLM"*."""
    decomposer_response = json.dumps({
        "substeps": [
            {
                "task": "Open Classroom Chemistry class",
                "url": "https://classroom.google.com",
                "expects": ["class_url"],
            },
            {
                "task": "Download exam PDFs from the exam post",
                "url": "",
                "expects": ["pdf_paths"],
            },
            {
                "task": "Create NotebookLM notebook and upload the PDFs",
                "url": "https://notebooklm.google.com",
                "expects": ["notebook_url"],
            },
        ]
    })
    monkeypatch.setattr(
        journey_mod, "call_llm",
        lambda *a, **kw: _FakeLLMResponse(decomposer_response),
    )
    # Pin the journey dir to a predictable tmp path so we can verify
    # save_dir is shared across substeps.
    monkeypatch.setattr(journey_mod, "_journey_dir", lambda: tmp_path)

    calls: list[dict] = []

    async def fake_navigator(
        _engine, *, task, url, save_dir=None, available_files=None, **_kw,
    ):
        calls.append({
            "task": task,
            "url": url,
            "save_dir": str(save_dir) if save_dir else None,
            "available_files": [str(p) for p in (available_files or [])],
        })
        # Substep 2 "downloads" a PDF; substep 3 must see it.
        downloads: list[str] = []
        if "download" in task.lower():
            pdf = tmp_path / "chemistry_exam.pdf"
            pdf.write_bytes(b"%PDF-fake")
            downloads = [str(pdf)]
        return {
            "summary": f"OK: {task[:40]}",
            "prompt_tokens": 200,
            "completion_tokens": 100,
            "cost_usd": 0.002,
            "auth_mode": "oauth",
            "output_pointer": json.dumps({"downloaded_files": downloads}),
        }

    # The journey does `from ai_intel.agents.navigator import navigator`
    # lazily inside the function — patching the module attribute makes
    # that bound `navigator` name resolve to our fake.
    monkeypatch.setattr(nav_mod, "navigator", fake_navigator)

    result = asyncio.run(journey_mod.journey(
        engine, task="Classroom exam to NotebookLM",
    ))

    # 3 substeps decomposed → 3 navigator calls in order.
    assert len(calls) == 3
    assert calls[0]["task"].startswith("Open Classroom")
    assert calls[1]["task"].startswith("Download")
    assert calls[2]["task"].startswith("Create NotebookLM")

    # File threading: substep 3 sees the PDF that substep 2 produced.
    assert calls[0]["available_files"] == []
    assert calls[1]["available_files"] == []
    assert len(calls[2]["available_files"]) == 1
    assert calls[2]["available_files"][0].endswith("chemistry_exam.pdf")

    # save_dir is the same dir across all substeps.
    save_dirs = {c["save_dir"] for c in calls}
    assert save_dirs == {str(tmp_path)}

    # The aggregate result records 3/3 with the PDF + costs rolled up.
    ptr = json.loads(result["output_pointer"])
    assert ptr["substep_count"] == 3
    assert ptr["completed"] == 3
    assert ptr["stopped_early"] is False
    assert len(ptr["downloaded_files"]) == 1
    assert ptr["downloaded_files"][0].endswith("chemistry_exam.pdf")
    assert "journey complete: 3/3 substep(s)" in result["summary"]
    # 3 navigator calls at 0.002 + 1 decompose at 0.001 = 0.007.
    assert result["cost_usd"] == pytest.approx(0.007, abs=1e-6)


def test_journey_refuses_empty_task(engine):
    """An empty / whitespace task is rejected without touching the LLM."""
    result = asyncio.run(journey_mod.journey(engine, task="   "))
    assert "no task given" in result["summary"]


def test_journey_reports_decomposer_failure(engine, monkeypatch):
    """If the decomposer returns no substeps, the journey surfaces a
    clear error rather than silently doing nothing."""
    monkeypatch.setattr(
        journey_mod, "call_llm",
        lambda *a, **kw: _FakeLLMResponse('{"substeps": []}'),
    )
    result = asyncio.run(journey_mod.journey(engine, task="something weird"))
    assert "couldn't decompose" in result["summary"]


def test_journey_stops_on_stalled_substep(engine, monkeypatch, tmp_path):
    """When a substep reports 'gave up', the journey stops and returns
    a partial result — substep 3 never runs."""
    monkeypatch.setattr(
        journey_mod, "call_llm",
        lambda *a, **kw: _FakeLLMResponse(json.dumps({
            "substeps": [
                {"task": "step 1", "url": "", "expects": []},
                {"task": "step 2", "url": "", "expects": []},
                {"task": "step 3", "url": "", "expects": []},
            ]
        })),
    )
    monkeypatch.setattr(journey_mod, "_journey_dir", lambda: tmp_path)

    n_calls = {"count": 0}

    async def stalling_navigator(
        _engine, *, task, url, save_dir=None, available_files=None, **_kw,
    ):
        n_calls["count"] += 1
        if task == "step 2":
            return {"summary": "gave up after 25 steps", "output_pointer": "{}"}
        return {"summary": f"ok {task}", "output_pointer": "{}"}

    monkeypatch.setattr(nav_mod, "navigator", stalling_navigator)

    result = asyncio.run(journey_mod.journey(engine, task="three-step task"))
    ptr = json.loads(result["output_pointer"])
    assert ptr["stopped_early"] is True
    assert ptr["completed"] == 2     # step 1 ran fully, step 2 stalled
    assert n_calls["count"] == 2     # step 3 never executed
    assert "partial" in result["summary"]


def test_journey_dir_is_unique_per_call(tmp_path):
    """Two journeys must not share a save_dir — concurrent journeys
    must not see each other's downloads."""
    a = journey_mod._journey_dir(root=tmp_path)
    b = journey_mod._journey_dir(root=tmp_path)
    assert a != b
    assert a.exists() and b.exists()
