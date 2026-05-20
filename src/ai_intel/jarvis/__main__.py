"""``python -m ai_intel.jarvis`` — Jarvis admin + memory CLI.

Subcommands:
    tools list                List every policy (source-tagged).
    tools check <name>        Show the resolved decision for one tool.
    approve list              Pending approval requests.
    approve <id>              Approve a pending request.
    approve <id> --reject     Reject a pending request.
    init                      Write the bundled default to ~/.jarvis/tools.toml.
    recall <query>            Semantic top-k recall over memory.
    note <text>               Add a personal note to memory.
    interest [<text>]         Add an interest, or list them (seeds the briefing).

This entrypoint deliberately does NOT touch the running daemon — it only
inspects/edits user-level policy, the approval queue, and the memory store.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from ai_intel.jarvis.permissions import (
    USER_CONFIG_PATH,
    ensure_user_config,
    is_allowed,
    list_approvals,
    load_policy,
    request_approval,
    resolve_approval,
)

# Pick up ANTHROPIC_API_KEY / VOYAGE_API_KEY / etc. from the project .env
# so the CLI works the same whether invoked from PowerShell or WSL.
load_dotenv()

DEFAULT_DB_PATH = Path("data") / "items.db"


def _cmd_tools_list(_args: argparse.Namespace) -> int:
    policy = load_policy()
    if not policy:
        print("(no policies loaded — try `python -m ai_intel.jarvis init`)")
        return 0
    rows = sorted(policy.values(), key=lambda r: (r.decision, r.name))
    name_w = max(len(r.name) for r in rows)
    src_w = max(len(r.source) for r in rows)
    print(f"{'TOOL':<{name_w}}  {'DECISION':<8}  {'SOURCE':<{src_w}}")
    print(f"{'-' * name_w}  {'-' * 8}  {'-' * src_w}")
    for r in rows:
        print(f"{r.name:<{name_w}}  {r.decision:<8}  {r.source:<{src_w}}")
    return 0


def _cmd_tools_check(args: argparse.Namespace) -> int:
    allowed = is_allowed(args.name)
    print(f"{args.name}: {'ALLOW' if allowed else 'DENY'}")
    return 0 if allowed else 1


def _cmd_approve_list(_args: argparse.Namespace) -> int:
    pending = list_approvals(status="pending")
    if not pending:
        print("(no pending approvals)")
        return 0
    for e in pending:
        args_json = json.dumps(e.get("args", {}), default=str)
        if len(args_json) > 70:
            args_json = args_json[:67] + "..."
        print(f"{e['id']}  {e['tool']:<30}  {args_json}")
        if e.get("reason"):
            print(f"             reason: {e['reason']}")
    return 0


def _cmd_approve(args: argparse.Namespace) -> int:
    decision = "rejected" if args.reject else "approved"
    try:
        entry = resolve_approval(args.id, decision)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"{entry['id']}: {entry['status']} (tool={entry['tool']})")
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    path = ensure_user_config(force=args.force)
    print(f"wrote {path}")
    return 0


def _open_engine(db_path: Path):
    """Lazy import so `tools list` etc. don't pay sqlmodel import cost."""
    from ai_intel.db.session import get_engine, init_db
    engine = get_engine(db_path)
    init_db(engine)
    return engine


def _cmd_recall(args: argparse.Namespace) -> int:
    # Capability gate
    if not is_allowed("memory.recall"):
        aid = request_approval(
            "memory.recall",
            {"query": args.query, "k": args.k, "source": args.source, "entity": args.entity},
            reason="memory.recall is denied in tools.toml",
        )
        print(f"memory.recall is DENIED. Approval queued: {aid}", file=sys.stderr)
        return 2

    from ai_intel.memory import recall

    db_path = Path(args.db) if args.db else DEFAULT_DB_PATH
    if not db_path.exists():
        print(f"error: no db at {db_path} — run the pipeline at least once", file=sys.stderr)
        return 1

    engine = _open_engine(db_path)
    hits = recall(
        engine,
        args.query,
        k=args.k,
        source=args.source,
        entity=args.entity,
    )

    if args.json:
        out = [{
            "hit_type": h.hit_type,
            "id": h.id,
            "score": round(h.score, 4),
            "title": h.title,
            "snippet": h.snippet,
            "source": h.source,
            "url": h.url,
            "published_at": h.published_at.isoformat() if h.published_at else None,
        } for h in hits]
        print(json.dumps(out, indent=2))
        return 0

    if not hits:
        print("(no hits)")
        return 0
    for h in hits:
        when = h.published_at.strftime("%Y-%m-%d") if h.published_at else "—"
        print(f"{h.score:+.3f}  [{h.hit_type}]  {when}  {h.source:<14}  {h.title[:80]}")
        if h.url:
            print(f"           {h.url}")
    return 0


def _cmd_note(args: argparse.Namespace) -> int:
    # Capability gate
    if not is_allowed("memory.add_note"):
        aid = request_approval(
            "memory.add_note",
            {"text_preview": args.text[:80]},
            reason="memory.add_note is denied in tools.toml",
        )
        print(f"memory.add_note is DENIED. Approval queued: {aid}", file=sys.stderr)
        return 2

    from ai_intel.memory import add_note

    db_path = Path(args.db) if args.db else DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = _open_engine(db_path)
    note_id = add_note(engine, args.text, source=args.source)
    print(f"saved note #{note_id} ({len(args.text)} chars, source={args.source})")
    return 0


def _cmd_interest(args: argparse.Namespace) -> int:
    """Add an interest (with text) or list all interests (without)."""
    from ai_intel.think.interests import add_interest, list_interests

    db_path = Path(args.db) if args.db else DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = _open_engine(db_path)

    if args.text:
        new_id = add_interest(engine, args.text)
        print(f"added interest #{new_id}: {args.text}")
        return 0

    interests = list_interests(engine)
    if not interests:
        print('(no interests yet — add one: jarvis interest "AI agents")')
        return 0
    for it in interests:
        print(f"#{it['id']}  {it['text']}")
    return 0


def _cmd_agents_status(args: argparse.Namespace) -> int:
    from ai_intel.agents.observability import summary_for_user

    db_path = Path(args.db) if args.db else DEFAULT_DB_PATH
    if not db_path.exists():
        print(f"error: no db at {db_path} — run the pipeline at least once", file=sys.stderr)
        return 1
    engine = _open_engine(db_path)
    print(summary_for_user(engine, window_hours=args.window))
    return 0


def _cmd_agents_tail(args: argparse.Namespace) -> int:
    from ai_intel.agents.observability import last_completed, recent_runs

    db_path = Path(args.db) if args.db else DEFAULT_DB_PATH
    if not db_path.exists():
        print(f"error: no db at {db_path}", file=sys.stderr)
        return 1
    engine = _open_engine(db_path)

    if args.completed_only:
        last = last_completed(engine, args.agent_id)
        rows = [last] if last else []
    else:
        rows = recent_runs(engine, agent_id=args.agent_id, limit=args.limit)

    if not rows:
        print(f"(no runs for agent {args.agent_id!r})")
        return 0

    for r in rows:
        dur = "—"
        if r.finished_at:
            dur = f"{(r.finished_at - r.started_at).total_seconds():.1f}s"
        print(
            f"#{r.id}  {r.started_at.strftime('%Y-%m-%d %H:%M:%S UTC')}  "
            f"{r.status:<10}  {dur:>7}  "
            f"tokens={r.prompt_tokens}+{r.completion_tokens}  "
            f"${r.cost_estimate_usd:.4f}  "
            f"auth={r.auth_mode or '—'}"
        )
        if r.summary:
            print(f"     summary: {r.summary}")
        if r.error:
            first_line = r.error.splitlines()[0] if r.error else ""
            print(f"     error:   {first_line[:200]}")
    return 0


def _cmd_agents_run(args: argparse.Namespace) -> int:
    """Trigger one agent manually for testing."""
    import asyncio
    from ai_intel.agents import AGENT_REGISTRY

    if args.agent_id not in AGENT_REGISTRY:
        print(
            f"error: unknown agent {args.agent_id!r}. "
            f"known: {', '.join(sorted(AGENT_REGISTRY))}",
            file=sys.stderr,
        )
        return 1

    db_path = Path(args.db) if args.db else DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = _open_engine(db_path)
    fn = AGENT_REGISTRY[args.agent_id]

    # Build kwargs from CLI flags. Each agent reads what it needs.
    kw: dict = {}
    if args.topic:
        kw["topic"] = args.topic
    if args.persona:
        kw["persona_id"] = args.persona
    if args.candidate_id is not None:
        kw["candidate_id"] = args.candidate_id
    if args.batch_limit is not None:
        kw["batch_limit"] = args.batch_limit
    if getattr(args, "n_candidates", None) is not None:
        kw["n_candidates"] = args.n_candidates
    if getattr(args, "days", None) is not None:
        kw["days"] = args.days
    if getattr(args, "max_items", None) is not None:
        kw["max_items"] = args.max_items
    if getattr(args, "no_synthesis", False):
        kw["use_synthesis"] = False
    if args.model:
        kw["model"] = args.model

    try:
        result = asyncio.run(fn(engine, **kw))
    except TypeError as exc:
        print(f"error: agent {args.agent_id!r} rejected kwargs: {exc}", file=sys.stderr)
        return 1
    print(f"agent {args.agent_id!r} done.")
    if result:
        for k, v in result.items():
            print(f"  {k}: {v}")
    return 0


def _cmd_ideas_list(args: argparse.Namespace) -> int:
    """Show IdeaCandidate rows, filtered by score/status."""
    import json as _json
    from ai_intel.db.models import IdeaCandidate
    from sqlmodel import Session, desc, select

    db_path = Path(args.db) if args.db else DEFAULT_DB_PATH
    if not db_path.exists():
        print(f"error: no db at {db_path}", file=sys.stderr)
        return 1
    engine = _open_engine(db_path)

    with Session(engine) as s:
        q = select(IdeaCandidate).order_by(desc(IdeaCandidate.proposed_at))
        if args.status:
            q = q.where(IdeaCandidate.status == args.status)
        rows = list(s.exec(q.limit(args.limit)))

    if args.min_score is not None:
        rows = [
            r for r in rows
            if r.evaluator_score is not None and r.evaluator_score >= args.min_score
        ]

    if not rows:
        print("(no ideas match those filters)")
        return 0

    for r in rows:
        score_str = f"{r.evaluator_score}/100" if r.evaluator_score is not None else "  —/100"
        verdict = r.evaluator_verdict or r.status
        when = r.proposed_at.strftime("%Y-%m-%d %H:%M") if r.proposed_at else "—"
        print(f"#{r.id}  {when}  {score_str}  {verdict:<10}  {r.idea_text[:120]}")
        if args.verbose and r.persona_critiques_json:
            try:
                blob = _json.loads(r.persona_critiques_json)
            except _json.JSONDecodeError:
                continue
            detail = blob.pop("_proposer_detail", {})
            # Entrepreneurial reasoning chain — the WHY behind the proposal
            if detail.get("pattern_recognized"):
                print(f"     pattern:   {detail['pattern_recognized']}")
            if detail.get("gap_identified"):
                print(f"     gap:       {detail['gap_identified']}")
            if detail.get("failure_pattern_avoided"):
                print(f"     avoids:    {detail['failure_pattern_avoided']}")
            if detail.get("wedge"):
                print(f"     wedge:     {detail['wedge']}")
            if detail.get("validation_step"):
                print(f"     validate:  {detail['validation_step']}")
            for pid, critique in blob.items():
                if isinstance(critique, dict) and "subscore" in critique:
                    print(
                        f"     {pid:<14} {critique.get('subscore', '?')}/100  "
                        f"{(critique.get('critique', '') or '')[:120]}"
                    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ai_intel.jarvis",
        description="Jarvis capability-layer admin",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    tools = sub.add_parser("tools", help="Inspect tool policies")
    tools_sub = tools.add_subparsers(dest="tools_cmd", required=True)

    tlist = tools_sub.add_parser("list", help="Show all policies")
    tlist.set_defaults(func=_cmd_tools_list)

    tcheck = tools_sub.add_parser("check", help="Resolve one tool name")
    tcheck.add_argument("name")
    tcheck.set_defaults(func=_cmd_tools_check)

    approve = sub.add_parser("approve", help="Manage approval queue")
    approve_sub = approve.add_subparsers(dest="approve_cmd", required=False)

    alist = approve_sub.add_parser("list", help="Show pending approvals")
    alist.set_defaults(func=_cmd_approve_list)

    # `approve <id>` without a sub-action resolves it (with optional --reject).
    approve.add_argument("id", nargs="?", help="Approval id to resolve")
    approve.add_argument(
        "--reject", action="store_true", help="Reject instead of approve"
    )
    approve.set_defaults(func=_cmd_approve)

    init = sub.add_parser("init", help=f"Write defaults to {USER_CONFIG_PATH}")
    init.add_argument("--force", action="store_true", help="Overwrite if present")
    init.set_defaults(func=_cmd_init)

    recall_p = sub.add_parser("recall", help="Semantic top-k recall over memory")
    recall_p.add_argument("query", help="Search query (natural language)")
    recall_p.add_argument("-k", "--k", type=int, default=10, help="How many hits")
    recall_p.add_argument("--source", help="Restrict to this Item.source")
    recall_p.add_argument("--entity", help="Substring match in entities_json")
    recall_p.add_argument("--db", help=f"Path to items.db (default: {DEFAULT_DB_PATH})")
    recall_p.add_argument("--json", action="store_true", help="Emit JSON, not table")
    recall_p.set_defaults(func=_cmd_recall)

    note = sub.add_parser("note", help="Add a personal note to memory")
    note.add_argument("text", help="The note text (quote it)")
    note.add_argument("--source", default="user_note", help="Tag (default: user_note)")
    note.add_argument("--db", help=f"Path to items.db (default: {DEFAULT_DB_PATH})")
    note.set_defaults(func=_cmd_note)

    interest = sub.add_parser(
        "interest", help="Add an interest, or list them (seeds the briefing)"
    )
    interest.add_argument("text", nargs="?", help="Interest text to add; omit to list")
    interest.add_argument("--db", help=f"Path to items.db (default: {DEFAULT_DB_PATH})")
    interest.set_defaults(func=_cmd_interest)

    agents = sub.add_parser("agents", help="Observe the agent fleet")
    agents_sub = agents.add_subparsers(dest="agents_cmd", required=True)

    astatus = agents_sub.add_parser("status", help="Fleet status summary")
    astatus.add_argument("--window", type=int, default=24, help="Hours back to scan (default 24)")
    astatus.add_argument("--db", help=f"Path to items.db (default: {DEFAULT_DB_PATH})")
    astatus.set_defaults(func=_cmd_agents_status)

    atail = agents_sub.add_parser("tail", help="Recent runs of one agent")
    atail.add_argument("agent_id", help="The agent_id (e.g. saturator, proposer)")
    atail.add_argument("-n", "--limit", type=int, default=5)
    atail.add_argument("--completed-only", action="store_true", help="Only the latest completed run")
    atail.add_argument("--db", help=f"Path to items.db (default: {DEFAULT_DB_PATH})")
    atail.set_defaults(func=_cmd_agents_tail)

    arun = agents_sub.add_parser("run", help="Trigger one agent manually")
    arun.add_argument("agent_id", help="saturator | synthesizer | proposer | evaluator | weekly_ideation")
    arun.add_argument("--topic", help="(saturator) topic to assess")
    arun.add_argument("--persona", help="(proposer) persona_id to use, e.g. paul_graham")
    arun.add_argument("--candidate-id", type=int, help="(evaluator) specific IdeaCandidate id")
    arun.add_argument("--batch-limit", type=int, help="(evaluator) max candidates per run")
    arun.add_argument("--n-candidates", type=int, help="(weekly_ideation) ideas to attempt")
    arun.add_argument("--days", type=int, help="(synthesizer) days back to analyze")
    arun.add_argument("--max-items", type=int, help="(synthesizer) cap items fed to LLM")
    arun.add_argument("--no-synthesis", action="store_true",
                      help="(weekly_ideation) opt out of trend-mode and force "
                           "single-item-per-candidate proposer behavior")
    arun.add_argument("--model", help="Override the LLM model id (e.g. claude-sonnet-4-6)")
    arun.add_argument("--db", help=f"Path to items.db (default: {DEFAULT_DB_PATH})")
    arun.set_defaults(func=_cmd_agents_run)

    ideas = sub.add_parser("ideas", help="Inspect IdeaCandidate rows")
    ideas_sub = ideas.add_subparsers(dest="ideas_cmd", required=True)

    ilist = ideas_sub.add_parser("list", help="List candidate ideas")
    ilist.add_argument("-n", "--limit", type=int, default=20)
    ilist.add_argument("--status", help="proposed | killed | needs_work | escalated")
    ilist.add_argument("--min-score", type=int, help="Only show ideas at or above this evaluator score")
    ilist.add_argument("-v", "--verbose", action="store_true", help="Show full critique chain")
    ilist.add_argument("--db", help=f"Path to items.db (default: {DEFAULT_DB_PATH})")
    ilist.set_defaults(func=_cmd_ideas_list)

    brain = sub.add_parser("brain", help="Run the Jarvis Brain service (FastAPI)")
    brain_sub = brain.add_subparsers(dest="brain_cmd", required=True)
    bserve = brain_sub.add_parser("serve", help="Start the Brain HTTP service")
    bserve.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    bserve.add_argument("--port", type=int, default=9999, help="Bind port (default: 9999)")
    bserve.add_argument("--reload", action="store_true", help="Auto-reload on code change (dev only)")
    bserve.add_argument("--db", help=f"Path to items.db (default: {DEFAULT_DB_PATH})")
    bserve.set_defaults(func=_cmd_brain_serve)

    workflow = sub.add_parser("workflow", help="Run / inspect automation workflows")
    workflow_sub = workflow.add_subparsers(dest="workflow_cmd", required=True)
    wlist = workflow_sub.add_parser("list", help="List available workflows")
    wlist.set_defaults(func=_cmd_workflow_list)
    wrun = workflow_sub.add_parser("run", help="Run a workflow by name")
    wrun.add_argument("name", help="Workflow name (e.g. clap_default, morning_brief)")
    wrun.add_argument("--db", help=f"Path to items.db (default: {DEFAULT_DB_PATH})")
    wrun.set_defaults(func=_cmd_workflow_run)

    return p


def _cmd_workflow_list(_args: argparse.Namespace) -> int:
    from ai_intel.workflows import list_workflows
    rows = list_workflows()
    if not rows:
        print("(no workflows defined)")
        return 0
    for w in rows:
        print(f"  {w['name']:<20} {w['step_count']} steps — {w['description']}")
    return 0


def _cmd_workflow_run(args: argparse.Namespace) -> int:
    import asyncio
    from ai_intel.workflows import run_workflow

    db_path = Path(args.db) if args.db else DEFAULT_DB_PATH
    engine = _open_engine(db_path)
    result = asyncio.run(run_workflow(engine, args.name))
    if "error" in result:
        print(f"error: {result['error']}", file=sys.stderr)
        if result.get("available"):
            print(f"available: {', '.join(result['available'])}", file=sys.stderr)
        return 1
    status = "ok" if result.get("ok") else "partial (some steps failed/refused)"
    print(f"workflow {args.name!r} — {status}")
    for i, step in enumerate(result.get("steps", [])):
        action = step.get("action", "?")
        if "error" in step:
            print(f"  [{i}] {action}: ERROR {step['error']}")
        elif "refused" in step:
            print(f"  [{i}] {action}: REFUSED ({step.get('approval_id')})")
        else:
            print(f"  [{i}] {action}: {step.get('summary', 'done')}")
    return 0


def _cmd_brain_serve(args: argparse.Namespace) -> int:
    """Start the Brain FastAPI service via uvicorn."""
    import uvicorn

    # Refuse to start a second Brain — overlapping copies were a source of
    # the "which window is which" confusion. (uvicorn would also fail to
    # bind the port, but this gives a clean message instead of a traceback.)
    from ai_intel.single_instance import acquire_single_instance

    if not acquire_single_instance(f"jarvis-brain-{args.port}"):
        print(
            f"A Jarvis Brain is already running on port {args.port} — "
            "not starting a second copy.",
            file=sys.stderr,
        )
        return 0

    # Tell the app which db to use via env var so create_app picks it up
    if args.db:
        import os as _os
        _os.environ["JARVIS_DB_PATH"] = str(Path(args.db))
    elif "JARVIS_DB_PATH" not in __import__("os").environ:
        import os as _os
        _os.environ["JARVIS_DB_PATH"] = str(DEFAULT_DB_PATH)
    print(f"Jarvis Brain serving on http://{args.host}:{args.port}")
    print(f"  DB:      {__import__('os').environ['JARVIS_DB_PATH']}")
    print(f"  Reload:  {args.reload}")
    print("  Endpoints: /, /agents/status, /ideas, /trends, /intel, /chat, /events (WS)")
    uvicorn.run(
        "ai_intel.brain.app:create_app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        factory=True,
        log_level="info",
    )
    return 0


def _force_utf8_stdio() -> None:
    """Reconfigure stdout/stderr to UTF-8 on Windows.

    Default Windows console code page is cp1252; printing the unicode
    arrows/borders/em-dashes the agents emit (e.g. evaluator summary
    "#11: mean=56 min=48 → killed") crashes with UnicodeEncodeError.
    `reconfigure()` was added to TextIOWrapper in 3.7 and is the
    documented fix.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            # Non-TextIOWrapper (e.g. captured by pytest) — leave it alone.
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)

    # `approve list` should route to _cmd_approve_list, not _cmd_approve.
    if args.cmd == "approve":
        if args.approve_cmd == "list":
            return _cmd_approve_list(args)
        if not getattr(args, "id", None):
            parser.error("approve: provide an id or use `approve list`")

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
