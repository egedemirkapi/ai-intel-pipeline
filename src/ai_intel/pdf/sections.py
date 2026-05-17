from sqlmodel import Session, select

from ai_intel.db.models import Item

SECTION_ORDER = ["Funding", "Launches", "Research", "Viral", "Hires", "Misc"]
CLASS_TO_SECTION = {
    "funding": "Funding",
    "launch": "Launches",
    "research": "Research",
    "viral": "Viral",
    "hire": "Hires",
    "misc": "Misc",
}


def build_sections(engine, top_items: list[dict]) -> dict:
    item_ids = [t["item_id"] for t in top_items]
    if not item_ids:
        return {}
    with Session(engine) as s:
        items_by_id = {
            i.id: i for i in s.exec(select(Item).where(Item.id.in_(item_ids))).all()
        }

    out: dict[str, list[dict]] = {name: [] for name in SECTION_ORDER}
    for t in top_items:
        item = items_by_id.get(t["item_id"])
        if not item:
            continue
        sec = CLASS_TO_SECTION.get(item.classification or "misc", "Misc")
        out[sec].append({
            "title": item.title,
            "url": item.url,
            "source": item.source,
            "published_at": item.published_at.strftime("%Y-%m-%d %H:%M"),
            "why_it_matters": t.get("why_it_matters", ""),
        })
    # Drop empty sections
    return {k: v for k, v in out.items() if v}
