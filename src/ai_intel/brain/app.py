"""Jarvis Brain — FastAPI service.

Binds to 127.0.0.1:9999. Provides read-only views of the fleet for the
frontend dashboard, a conversational /chat endpoint, and a WebSocket
/events stream so the frontend re-renders live when agents fire.

Routes:
    GET  /                  health probe + version
    GET  /agents/status     fleet summary (one row per agent_id)
    GET  /agents/runs       recent AgentRun rows (paginated)
    GET  /ideas             paginated IdeaCandidate list, status filter
    GET  /ideas/{id}        full critique chain for one candidate
    GET  /trends            active TrendSynthesis rows
    GET  /intel             recent Item rows excluding corpus/founder_brain
    POST /chat              conversational LLM with tool use
    GET  /workflows         list workflows (with triggers)
    GET  /workflows/{name}  one workflow's full definition
    POST /workflows         create a workflow
    PUT  /workflows/{name}  update a workflow
    DEL  /workflows/{name}  delete a workflow
    POST /workflows/validate  check a definition without saving
    POST /workflow/{name}   run a YAML workflow by name (Phase 14)
    GET  /brief             assemble the daily briefing
    GET  /interests         list the user's interests
    POST /interests         add an interest
    DEL  /interests/{id}    remove an interest
    POST /speak             queue an utterance for the voice tray
    GET  /speak/pending     drain the speak queue (voice tray polls this)
    POST /context/app       report the foreground app (fires on_app workflows)
    GET  /context           the current foreground-app context
    WS   /events            live FleetEvent stream

Everything is read-only by default; writes happen via the /chat tool
calls or /workflow endpoint, both of which go through the capability
layer.
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlmodel import Session, desc, select

from ai_intel.brain.chat import run_chat
from ai_intel.brain.events import FleetEvent, get_event_bus
from ai_intel.brain.speak import get_speak_queue, narration_for
from ai_intel.db.models import (
    AgentRun,
    IdeaCandidate,
    Item,
    TrendSynthesis,
)
from ai_intel.db.session import get_engine, init_db


class ChatRequest(BaseModel):
    message: str
    history: list[dict] | None = None
    model: str = "claude-haiku-4-5"


class WorkflowCreate(BaseModel):
    name: str
    definition: dict


class WorkflowUpdate(BaseModel):
    definition: dict


class WorkflowValidate(BaseModel):
    definition: dict


class AppAllow(BaseModel):
    app_id: str = ""
    name: str = ""


class VoiceTrigger(BaseModel):
    transcript: str


class InterestCreate(BaseModel):
    text: str


class SpeakRequest(BaseModel):
    text: str
    kind: str = "manual"


class ContextUpdate(BaseModel):
    process: str = ""
    title: str = ""


class IntelEvent(BaseModel):
    count: int = 0
    sources: list[str] = []


class VoiceStateUpdate(BaseModel):
    state: str  # idle | listening | thinking | speaking

logger = logging.getLogger(__name__)

# Engine path resolved at startup. Override via env JARVIS_DB_PATH for tests.
import os
_DB_PATH = Path(os.getenv("JARVIS_DB_PATH", "data/items.db"))


async def _narrator_loop(bus, speak_queue) -> None:
    """Subscribe to the fleet event bus and push narration-worthy events
    into the speak queue so the voice tray can announce them."""
    q = await bus.subscribe()
    try:
        while True:
            event = await q.get()
            phrase = narration_for(event)
            if phrase:
                speak_queue.push(phrase, kind="narration")
    except asyncio.CancelledError:
        pass
    finally:
        await bus.unsubscribe(q)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Initialize the SQLite engine once at startup."""
    engine = get_engine(_DB_PATH)
    init_db(engine)
    app.state.engine = engine
    app.state.bus = get_event_bus()
    app.state.speak_queue = get_speak_queue()
    narrator = asyncio.create_task(_narrator_loop(app.state.bus, app.state.speak_queue))
    logger.info("brain: engine ready at %s; bus subscribers=%d",
                _DB_PATH, app.state.bus.subscriber_count)
    yield
    narrator.cancel()
    # No engine.dispose() needed for SQLite + WAL; connections close with process.


def _session(app: FastAPI) -> Session:
    return Session(app.state.engine)


def _require_capability(tool: str) -> None:
    """Raise 403 unless the capability layer allows ``tool``."""
    from ai_intel.jarvis.permissions import is_allowed

    if not is_allowed(tool):
        raise HTTPException(status_code=403, detail=f"{tool} denied by policy")


def _publish_workflows_changed(app: FastAPI, summary: str) -> None:
    """Emit a workflows_changed event so the dashboard refreshes and the
    voice tray rebinds hotkeys."""
    app.state.bus.publish(FleetEvent(
        type="workflows_changed",
        summary=f"routines: {summary}",
        payload={"change": summary},
    ))


def create_app() -> FastAPI:
    app = FastAPI(
        title="Jarvis Brain",
        description="Conversational + introspection layer over the agent fleet.",
        version="0.1.0",
        lifespan=_lifespan,
    )
    # CORS — allow any origin. The Brain is reachable only on localhost
    # + the Tailscale tailnet; Tailscale device-identity is the real
    # security boundary, so CORS doesn't need to be the gate. This lets
    # the frontend (served from laptop:3000 OR a tailnet hostname) talk
    # to the Brain without per-origin allowlisting.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    # ─── Health / version ───────────────────────────────────────────
    @app.get("/")
    def root() -> dict[str, Any]:
        return {
            "service": "jarvis-brain",
            "version": "0.1.0",
            "db_path": str(_DB_PATH),
            "bus_subscribers": app.state.bus.subscriber_count,
        }

    # ─── Agent fleet ────────────────────────────────────────────────
    @app.get("/agents/status")
    def agents_status() -> dict[str, Any]:
        """One row per agent_id: latest run + counts by status."""
        from sqlmodel import func
        with _session(app) as s:
            agent_ids = list(s.exec(select(AgentRun.agent_id).distinct()).all())
            out = {}
            for aid in agent_ids:
                latest = s.exec(
                    select(AgentRun)
                    .where(AgentRun.agent_id == aid)
                    .order_by(desc(AgentRun.started_at))
                    .limit(1)
                ).first()
                count = s.exec(
                    select(func.count(AgentRun.id))
                    .where(AgentRun.agent_id == aid)
                ).first()
                out[aid] = {
                    "latest": _agent_run_dict(latest) if latest else None,
                    "total_runs": int(count or 0),
                }
        return out

    @app.get("/agents/runs")
    def agents_runs(
        agent_id: str | None = None,
        limit: int = Query(20, ge=1, le=200),
    ) -> list[dict[str, Any]]:
        with _session(app) as s:
            q = select(AgentRun).order_by(desc(AgentRun.started_at)).limit(limit)
            if agent_id:
                q = q.where(AgentRun.agent_id == agent_id)
            rows = list(s.exec(q))
        return [_agent_run_dict(r) for r in rows]

    # ─── Ideas ──────────────────────────────────────────────────────
    @app.get("/ideas")
    def ideas_list(
        status: str | None = None,
        min_score: int | None = None,
        limit: int = Query(50, ge=1, le=200),
    ) -> list[dict[str, Any]]:
        with _session(app) as s:
            q = select(IdeaCandidate).order_by(desc(IdeaCandidate.proposed_at))
            if status:
                q = q.where(IdeaCandidate.status == status)
            if min_score is not None:
                q = q.where(IdeaCandidate.evaluator_score >= min_score)
            rows = list(s.exec(q.limit(limit)))
        return [_idea_dict(r) for r in rows]

    @app.get("/ideas/{cid}")
    def ideas_show(cid: int) -> dict[str, Any]:
        with _session(app) as s:
            r = s.get(IdeaCandidate, cid)
        if r is None:
            raise HTTPException(status_code=404, detail=f"no idea with id={cid}")
        return _idea_dict(r, full=True)

    # ─── Trends ─────────────────────────────────────────────────────
    @app.get("/trends")
    def trends_latest(
        status: str = "active",
        limit: int = Query(20, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        with _session(app) as s:
            rows = list(s.exec(
                select(TrendSynthesis)
                .where(TrendSynthesis.status == status)
                .order_by(desc(TrendSynthesis.generated_at))
                .limit(limit)
            ))
        return [_trend_dict(r) for r in rows]

    # ─── Intel feed ────────────────────────────────────────────────
    @app.get("/intel")
    def intel_recent(
        hours: int = Query(24, ge=1, le=720),
        source: str | None = None,
        limit: int = Query(100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        with _session(app) as s:
            q = (
                select(Item)
                .where(Item.collected_at >= cutoff)
                .where(Item.source != "founder_brain")
                .where(Item.source != "failure_corpus")
                .order_by(desc(Item.collected_at))
                .limit(limit)
            )
            if source:
                q = q.where(Item.source == source)
            rows = list(s.exec(q))
        return [_item_dict(r) for r in rows]

    # ─── Conversational chat ────────────────────────────────────────
    @app.post("/chat")
    async def chat(req: ChatRequest) -> dict[str, Any]:
        """Run a conversational turn against the LLM with tool use."""
        if not req.message.strip():
            raise HTTPException(status_code=400, detail="empty message")
        try:
            result = await run_chat(
                app.state.engine,
                req.message,
                model=req.model,
                history=req.history,
            )
        except Exception as exc:
            logger.exception("chat failed: %s", exc)
            raise HTTPException(status_code=500, detail=f"chat failed: {exc}")
        return result

    # ─── Collector status ──────────────────────────────────────────
    @app.get("/collector/status")
    def collector_status() -> dict[str, Any]:
        """Real collection stats — total items, last-24h count, last
        collection time. The collector is NOT an @agent so it doesn't
        appear in /agents; this endpoint surfaces it explicitly."""
        from datetime import datetime, timezone, timedelta
        from sqlmodel import func
        now = datetime.now(timezone.utc)
        intel_filter = Item.source.not_in(("founder_brain", "failure_corpus"))
        with _session(app) as s:
            total = s.exec(select(func.count(Item.id)).where(intel_filter)).first()
            last_24h = s.exec(
                select(func.count(Item.id))
                .where(Item.collected_at >= now - timedelta(hours=24))
                .where(intel_filter)
            ).first()
            last_2h = s.exec(
                select(func.count(Item.id))
                .where(Item.collected_at >= now - timedelta(hours=2))
                .where(intel_filter)
            ).first()
            latest = s.exec(
                select(func.max(Item.collected_at)).where(intel_filter)
            ).first()
        minutes_since = None
        if latest is not None:
            lt = latest if latest.tzinfo else latest.replace(tzinfo=timezone.utc)
            minutes_since = int((now - lt).total_seconds() / 60)
        return {
            "total_items": int(total or 0),
            "last_24h": int(last_24h or 0),
            "last_2h": int(last_2h or 0),
            "last_collected_at": latest.isoformat() if latest else None,
            "minutes_since_last": minutes_since,
        }

    # ─── Workflows: list + CRUD (routine editor) ────────────────────
    @app.get("/workflows")
    def workflows_list() -> list[dict[str, Any]]:
        from ai_intel.workflows import list_workflow_defs
        return list_workflow_defs()

    @app.get("/workflows/{name}")
    def workflow_get(name: str) -> dict[str, Any]:
        from ai_intel.workflows import get_workflow
        wf = get_workflow(name)
        if wf is None:
            raise HTTPException(status_code=404, detail=f"unknown workflow {name!r}")
        return {"name": name, "definition": wf}

    @app.post("/workflows/validate")
    def workflows_validate(req: WorkflowValidate) -> dict[str, Any]:
        from ai_intel.workflows import validate_def
        errors = validate_def(req.definition)
        return {"valid": not errors, "errors": errors}

    @app.post("/workflows")
    def workflow_create(req: WorkflowCreate) -> dict[str, Any]:
        _require_capability("workflow.edit")
        from ai_intel.workflows import WorkflowError, create_workflow
        try:
            saved = create_workflow(req.name, req.definition)
        except WorkflowError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        _publish_workflows_changed(app, f"created {req.name}")
        return {"name": req.name, "definition": saved}

    @app.put("/workflows/{name}")
    def workflow_update(name: str, req: WorkflowUpdate) -> dict[str, Any]:
        _require_capability("workflow.edit")
        from ai_intel.workflows import WorkflowError, update_workflow
        try:
            saved = update_workflow(name, req.definition)
        except WorkflowError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        _publish_workflows_changed(app, f"updated {name}")
        return {"name": name, "definition": saved}

    @app.delete("/workflows/{name}")
    def workflow_delete(name: str) -> dict[str, Any]:
        _require_capability("workflow.edit")
        from ai_intel.workflows import WorkflowError, delete_workflow
        try:
            delete_workflow(name)
        except WorkflowError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        _publish_workflows_changed(app, f"deleted {name}")
        return {"deleted": name}

    @app.post("/workflow/{name}")
    async def workflow_run(name: str) -> dict[str, Any]:
        """Execute a YAML workflow by name. Used by the voice tray's
        clap handler and the frontend's workflow buttons."""
        from ai_intel.workflows import run_workflow
        result = await run_workflow(app.state.engine, name)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        # Emit a workflow_finished event so the frontend can react
        app.state.bus.publish(FleetEvent(
            type="workflow_finished",
            summary=f"workflow {name}: {'ok' if result.get('ok') else 'partial'}",
            payload={"workflow": name, "ok": result.get("ok")},
        ))
        return result

    # ─── Triggers: clap + voice-phrase → workflow ───────────────────
    @app.post("/trigger/clap")
    async def trigger_clap() -> dict[str, Any]:
        """Fire every workflow whose trigger.clap is set. Called by the
        voice tray when a deliberate two-clap gesture is detected."""
        from ai_intel.workflows import (
            get_workflow,
            run_workflow,
            workflows_with_trigger,
        )
        names = workflows_with_trigger("clap")
        # Back-compat: a workflow named "clap_default" that predates the
        # trigger schema still fires on a clap even without trigger.clap.
        if not names and get_workflow("clap_default") is not None:
            names = ["clap_default"]
        results = []
        for name in names:
            result = await run_workflow(app.state.engine, name)
            ok = result.get("ok")
            results.append({"workflow": name, "ok": ok})
            app.state.bus.publish(FleetEvent(
                type="workflow_finished",
                summary=f"clap → {name}: {'ok' if ok else 'partial'}",
                payload={"workflow": name, "ok": ok, "trigger": "clap"},
            ))
        return {"fired": names, "results": results}

    @app.post("/trigger/voice")
    async def trigger_voice(req: VoiceTrigger) -> dict[str, Any]:
        """Match a spoken transcript against workflow voice_phrases. If a
        workflow matches, run it; otherwise report no match so the caller
        falls through to the conversational /chat path."""
        from ai_intel.workflows import match_voice, run_workflow
        name = match_voice(req.transcript)
        if name is None:
            return {"matched": False}
        result = await run_workflow(app.state.engine, name)
        ok = result.get("ok")
        app.state.bus.publish(FleetEvent(
            type="workflow_finished",
            summary=f"voice → {name}: {'ok' if ok else 'partial'}",
            payload={"workflow": name, "ok": ok, "trigger": "voice"},
        ))
        return {"matched": True, "workflow": name, "result": result}

    # ─── Context awareness — foreground-app tracking ────────────────
    @app.post("/context/app")
    async def context_app(req: ContextUpdate) -> dict[str, Any]:
        """The voice tray reports the user switched apps. Records the
        context and fires any workflow with a matching on_app trigger."""
        from ai_intel.brain.context import set_current_context
        from ai_intel.workflows import match_app, run_workflow

        set_current_context(req.process, req.title)
        fired = []
        for name in match_app(req.process, req.title):
            result = await run_workflow(app.state.engine, name)
            ok = result.get("ok")
            fired.append({"workflow": name, "ok": ok})
            app.state.bus.publish(FleetEvent(
                type="workflow_finished",
                summary=f"app context → {name}",
                payload={"workflow": name, "ok": ok, "trigger": "on_app"},
            ))
        return {
            "context": {"process": req.process, "title": req.title},
            "fired": fired,
        }

    @app.get("/context")
    def context_get() -> dict[str, Any]:
        """The current foreground-app context."""
        from ai_intel.brain.context import get_current_context
        return {"context": get_current_context() or None}

    # ─── Installed apps + launch allowlist ──────────────────────────
    @app.get("/apps/installed")
    def apps_installed(refresh: bool = False) -> list[dict[str, str]]:
        """Apps installed on this machine (cached; ?refresh=1 rescans)."""
        from ai_intel.workflows.app_scanner import list_installed_apps
        return list_installed_apps(refresh=refresh)

    @app.get("/apps/allowed")
    def apps_allowed() -> list[dict[str, str]]:
        """Apps the user has approved for apps.launch."""
        from ai_intel.workflows.app_scanner import get_allowlist
        return get_allowlist()

    @app.post("/apps/allow")
    def apps_allow(req: AppAllow) -> dict[str, Any]:
        """Add an app to the launch allowlist."""
        from ai_intel.workflows.app_scanner import add_to_allowlist
        if not req.app_id and not req.name:
            raise HTTPException(status_code=400, detail="provide app_id or name")
        entry = add_to_allowlist(req.app_id, req.name)
        return {"allowed": entry}

    @app.delete("/apps/allow/{app_id:path}")
    def apps_disallow(app_id: str) -> dict[str, Any]:
        """Remove an app from the launch allowlist (by app_id or name)."""
        from ai_intel.workflows.app_scanner import remove_from_allowlist
        removed = remove_from_allowlist(app_id)
        if not removed:
            raise HTTPException(status_code=404, detail=f"{app_id!r} not on allowlist")
        return {"removed": app_id}

    # ─── Briefing + interests ───────────────────────────────────────
    @app.get("/brief")
    async def brief() -> dict[str, Any]:
        """Assemble the briefing — news, calendar, homework, suggestions."""
        from ai_intel.think.brief import build_brief
        return await build_brief(app.state.engine)

    @app.get("/interests")
    def interests_list() -> list[dict[str, Any]]:
        from ai_intel.think.interests import list_interests
        return list_interests(app.state.engine)

    @app.post("/interests")
    def interest_add(req: InterestCreate) -> dict[str, Any]:
        from ai_intel.think.interests import add_interest
        text = req.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="interest text is empty")
        new_id = add_interest(app.state.engine, text)
        return {"id": new_id, "text": text}

    @app.delete("/interests/{note_id}")
    def interest_delete(note_id: int) -> dict[str, Any]:
        from ai_intel.think.interests import delete_interest
        if not delete_interest(app.state.engine, note_id):
            raise HTTPException(status_code=404, detail=f"no interest id={note_id}")
        return {"deleted": note_id}

    # ─── Proactive speech (Brain → voice tray reverse channel) ──────
    @app.post("/speak")
    def speak_push(req: SpeakRequest) -> dict[str, Any]:
        """Queue an utterance for the voice tray to speak."""
        queued = app.state.speak_queue.push(req.text, kind=req.kind)
        return {"queued": queued, "pending": app.state.speak_queue.pending}

    @app.get("/speak/pending")
    def speak_pending() -> dict[str, Any]:
        """Drain the speak queue — the voice tray polls this."""
        items = app.state.speak_queue.drain()
        return {"utterances": [u.to_dict() for u in items]}

    # ─── Voice presence (drives the dashboard orb) ──────────────────
    @app.post("/voice/state")
    def voice_state(req: VoiceStateUpdate) -> dict[str, Any]:
        """The voice tray reports its state (idle/listening/thinking/
        speaking). Re-broadcast so the dashboard's Jarvis orb animates."""
        app.state.bus.publish(FleetEvent(
            type="voice_state",
            summary=f"voice: {req.state}",
            payload={"state": req.state},
        ))
        return {"ok": True}

    # ─── Live intel signal ──────────────────────────────────────────
    @app.post("/events/intel")
    def events_intel(req: IntelEvent) -> dict[str, Any]:
        """The collector (a separate process) calls this when it ingests
        new intel — the Brain re-broadcasts it on the event bus so the
        dashboard's news feed refreshes live."""
        if req.count > 0:
            app.state.bus.publish(FleetEvent(
                type="intel_collected",
                summary=f"{req.count} new intel item(s)",
                payload={"count": req.count, "sources": req.sources},
            ))
        return {"published": req.count > 0}

    # ─── WebSocket /events ──────────────────────────────────────────
    @app.websocket("/events")
    async def events_ws(ws: WebSocket):
        await ws.accept()
        bus = app.state.bus
        q = await bus.subscribe()
        try:
            # Send a hello so the client knows the connection is alive
            await ws.send_json({"type": "hello", "subscribers": bus.subscriber_count})
            while True:
                evt: FleetEvent = await q.get()
                await ws.send_json(evt.to_dict())
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.warning("events_ws error: %s", exc)
        finally:
            await bus.unsubscribe(q)

    return app


# ─── Row→dict converters (kept private; not part of public API) ──────


def _agent_run_dict(r: AgentRun) -> dict[str, Any]:
    return {
        "id": r.id,
        "agent_id": r.agent_id,
        "status": r.status,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "prompt_tokens": r.prompt_tokens,
        "completion_tokens": r.completion_tokens,
        "cost_estimate_usd": r.cost_estimate_usd,
        "auth_mode": r.auth_mode,
        "summary": r.summary,
        "error": r.error,
    }


def _idea_dict(r: IdeaCandidate, *, full: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": r.id,
        "proposed_at": r.proposed_at.isoformat() if r.proposed_at else None,
        "idea_text": r.idea_text,
        "tech_basis": r.tech_basis,
        "evaluator_score": r.evaluator_score,
        "evaluator_verdict": r.evaluator_verdict,
        "status": r.status,
        "trend_synthesis_id": r.trend_synthesis_id,
    }
    if full:
        try:
            blob = json.loads(r.persona_critiques_json or "{}")
        except (json.JSONDecodeError, TypeError):
            blob = {}
        out["proposer_detail"] = blob.pop("_proposer_detail", {})
        out["persona_critiques"] = blob
    return out


def _trend_dict(r: TrendSynthesis) -> dict[str, Any]:
    try:
        members = json.loads(r.member_item_ids_json or "[]")
    except (json.JSONDecodeError, TypeError):
        members = []
    try:
        convergence = json.loads(r.convergence_with_json or "[]")
    except (json.JSONDecodeError, TypeError):
        convergence = []
    return {
        "id": r.id,
        "generated_at": r.generated_at.isoformat() if r.generated_at else None,
        "cluster_label": r.cluster_label,
        "underlying_shift": r.underlying_shift,
        "new_capability": r.new_capability,
        "momentum": r.momentum,
        "convergence_with": convergence,
        "member_count": len(members),
        "status": r.status,
    }


def _item_dict(r: Item) -> dict[str, Any]:
    return {
        "id": r.id,
        "source": r.source,
        "title": r.title,
        "url": r.url,
        "author": r.author,
        "collected_at": r.collected_at.isoformat() if r.collected_at else None,
        "ai_relevance": r.ai_relevance,
        "classification": r.classification,
    }
