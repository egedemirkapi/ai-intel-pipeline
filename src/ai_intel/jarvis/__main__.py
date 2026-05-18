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

This entrypoint deliberately does NOT touch the running daemon — it only
inspects/edits user-level policy, the approval queue, and the memory store.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ai_intel.jarvis.permissions import (
    USER_CONFIG_PATH,
    ensure_user_config,
    is_allowed,
    list_approvals,
    load_policy,
    request_approval,
    resolve_approval,
)

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

    return p


def main(argv: list[str] | None = None) -> int:
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
