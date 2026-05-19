"""Honest system status. Inventories what's in the DB right now."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlmodel import Session, func, select

from ai_intel.db.models import (
    AgentRun, Digest, Embedding, IdeaCandidate, Item,
    MemoryQuery, PainCluster, PersonalNote, SaturationAssessment,
)
from ai_intel.db.session import get_engine, init_db
from ai_intel.personas import KNOWN_PERSONAS


def main():
    engine = get_engine(Path("data/items.db"))
    init_db(engine)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    def _ago(t):
        if t is None:
            return None
        t = t.replace(tzinfo=None) if t.tzinfo else t
        return now - t

    with Session(engine) as s:
        # --- Intel feed (the "vault") ---
        total_items = s.exec(select(func.count(Item.id))).first()
        by_source = list(s.exec(
            select(Item.source, func.count(Item.id))
            .group_by(Item.source)
            .order_by(func.count(Item.id).desc())
        ))
        last_24h = s.exec(
            select(func.count(Item.id)).where(
                Item.collected_at >= now - timedelta(hours=24)
            )
        ).first()
        last_2h = s.exec(
            select(func.count(Item.id)).where(
                Item.collected_at >= now - timedelta(hours=2)
            )
        ).first()
        newest = s.exec(
            select(Item).order_by(Item.collected_at.desc()).limit(1)
        ).first()

        # --- Memory ---
        total_embeds = s.exec(select(func.count(Embedding.id))).first()
        by_model = list(s.exec(
            select(Embedding.model, func.count(Embedding.id))
            .group_by(Embedding.model)
        ))
        embed_coverage = (total_embeds / total_items) if total_items else 0

        # --- Personal notes ---
        n_notes = s.exec(select(func.count(PersonalNote.id))).first()

        # --- Agent runs ---
        runs_by_agent = list(s.exec(
            select(AgentRun.agent_id, AgentRun.status, func.count(AgentRun.id))
            .group_by(AgentRun.agent_id, AgentRun.status)
        ))

        # --- Saturator assessments ---
        n_sat = s.exec(select(func.count(SaturationAssessment.id))).first()

        # --- Ideas ---
        n_ideas = s.exec(select(func.count(IdeaCandidate.id))).first()
        ideas_by_status = list(s.exec(
            select(IdeaCandidate.status, func.count(IdeaCandidate.id))
            .group_by(IdeaCandidate.status)
        ))

        # --- Pain clusters ---
        n_pain = s.exec(select(func.count(PainCluster.id))).first()

        # --- Digests sent ---
        n_digests = s.exec(select(func.count(Digest.id))).first()
        last_digest = s.exec(
            select(Digest).order_by(Digest.sent_at.desc().nullslast()).limit(1)
        ).first()

    print("=" * 64)
    print("JARVIS SYSTEM STATUS")
    print("=" * 64)

    print(f"\n[INTEL FEED — the vault]  total items: {total_items}")
    print(f"  embedded:        {total_embeds}  ({embed_coverage:.0%} coverage)")
    print(f"  collected 24h:   {last_24h}")
    print(f"  collected 2h:    {last_2h}")
    if newest:
        age = _ago(newest.collected_at)
        mins = int(age.total_seconds() // 60) if age else 0
        print(f"  newest item:     {mins} min ago - '{newest.title[:60]}'")
    print("  by source:")
    for src, n in by_source[:12]:
        print(f"    {src:<24} {n:>5}")
    if len(by_source) > 12:
        print(f"    (+{len(by_source) - 12} more sources)")

    print(f"\n[EMBEDDINGS]  by model:")
    for m, n in by_model:
        print(f"    {m:<20} {n:>5}")

    print(f"\n[PERSONAL NOTES]  count: {n_notes}")

    print(f"\n[PERSONAS — evaluator skills]")
    print(f"  loaded: {len(KNOWN_PERSONAS)} — {', '.join(KNOWN_PERSONAS)}")

    print(f"\n[AGENT FLEET RUNS]  by (agent, status):")
    if not runs_by_agent:
        print("    (no runs yet)")
    for aid, status, n in runs_by_agent:
        print(f"    {aid:<14} {status:<12} {n:>4}")

    print(f"\n[SATURATOR]  assessments: {n_sat}")
    print(f"\n[PROPOSER + EVALUATOR]  IdeaCandidates: {n_ideas}")
    for st, n in ideas_by_status:
        print(f"    {st:<14} {n:>4}")

    print(f"\n[PAIN CLUSTERS]  count: {n_pain}")

    print(f"\n[EMAIL DIGESTS]  sent: {n_digests}")
    if last_digest and last_digest.sent_at:
        age = _ago(last_digest.sent_at)
        age_h = age.total_seconds() / 3600 if age else 0
        print(f"  last sent: {age_h:.1f}h ago")
    print()


if __name__ == "__main__":
    main()
