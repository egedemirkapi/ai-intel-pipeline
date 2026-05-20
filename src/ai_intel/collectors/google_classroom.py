"""Google Classroom collector — coursework + announcements as Items.

Powers the "what's my homework this week?" use case. Read-only:
classroom.courses.readonly, classroom.coursework.me.readonly,
classroom.announcements.readonly.

Each piece of coursework becomes a RawItem:
    title  = "[Course] Assignment Title"
    body   = description + due date + course + work state
    url    = the Classroom alternateLink
    source = "gclassroom" (set by the runner from .name)

Graceful degradation: if the user hasn't run setup_google_auth.py,
``has_token()`` is False and fetch_since returns [] with a warning —
the pipeline keeps running, just without Classroom data.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ai_intel.collectors.base import Collector, RawItem

logger = logging.getLogger(__name__)


def _parse_due(coursework: dict) -> str | None:
    """Classroom splits due date + due time. Recombine to an ISO date."""
    d = coursework.get("dueDate")
    if not d:
        return None
    y, m, day = d.get("year"), d.get("month"), d.get("day")
    if not (y and m and day):
        return None
    t = coursework.get("dueTime") or {}
    hh = t.get("hours", 23)
    mm = t.get("minutes", 59)
    return f"{y:04d}-{m:02d}-{day:02d}T{hh:02d}:{mm:02d}"


def _coursework_to_item(course_name: str, cw: dict) -> RawItem:
    title = cw.get("title", "(untitled)")
    desc = cw.get("description", "")
    due = _parse_due(cw)
    state = cw.get("state", "PUBLISHED")
    work_type = cw.get("workType", "ASSIGNMENT")
    url = cw.get("alternateLink") or f"classroom-coursework://{cw.get('id', '')}"
    created = cw.get("creationTime")
    try:
        published = (
            datetime.fromisoformat(created.replace("Z", "+00:00"))
            if created else datetime.now(timezone.utc)
        )
    except (ValueError, AttributeError):
        published = datetime.now(timezone.utc)

    body_lines = [
        f"Course: {course_name}",
        f"Type: {work_type}",
        f"State: {state}",
    ]
    if due:
        body_lines.append(f"Due: {due}")
    else:
        body_lines.append("Due: (no due date)")
    if desc:
        body_lines.append("")
        body_lines.append(desc)

    return RawItem(
        url=url,
        title=f"[{course_name}] {title}",
        published_at=published,
        body="\n".join(body_lines),
        author=course_name,
        raw={
            "kind": "assignment",
            "course": course_name,
            "due_date": due,
            "work_type": work_type,
            "state": state,
            "coursework_id": cw.get("id"),
        },
    )


def _announcement_to_item(course_name: str, ann: dict) -> RawItem:
    text = ann.get("text", "")
    url = ann.get("alternateLink") or f"classroom-announcement://{ann.get('id', '')}"
    created = ann.get("creationTime")
    try:
        published = (
            datetime.fromisoformat(created.replace("Z", "+00:00"))
            if created else datetime.now(timezone.utc)
        )
    except (ValueError, AttributeError):
        published = datetime.now(timezone.utc)
    first_line = (text or "").strip().splitlines()[0] if text else "(announcement)"
    return RawItem(
        url=url,
        title=f"[{course_name}] Announcement: {first_line[:80]}",
        published_at=published,
        body=f"Course: {course_name}\n\n{text}",
        author=course_name,
        raw={"kind": "announcement", "course": course_name, "announcement_id": ann.get("id")},
    )


class GoogleClassroomCollector(Collector):
    """Fetch active-course coursework + announcements as RawItems."""

    name = "gclassroom"

    def __init__(self, *, max_courses: int = 20, max_per_course: int = 40) -> None:
        self.max_courses = max_courses
        self.max_per_course = max_per_course

    async def fetch_since(self, since: datetime) -> list[RawItem]:
        from ai_intel.google_auth import build_service, has_token

        if not has_token():
            logger.warning(
                "gclassroom: no Google token — run scripts/setup_google_auth.py. "
                "Skipping Classroom collection."
            )
            return []

        try:
            service = build_service("classroom", "v1")
        except Exception as exc:
            logger.error("gclassroom: could not build service: %s", exc)
            return []

        items: list[RawItem] = []
        try:
            courses_resp = (
                service.courses()
                .list(courseStates=["ACTIVE"], pageSize=self.max_courses)
                .execute()
            )
        except Exception as exc:
            logger.error("gclassroom: courses().list failed: %s", exc)
            return []

        for course in courses_resp.get("courses", []):
            cid = course.get("id")
            cname = course.get("name", "Course")
            if not cid:
                continue
            # Coursework (assignments)
            try:
                cw_resp = (
                    service.courses()
                    .courseWork()
                    .list(courseId=cid, pageSize=self.max_per_course)
                    .execute()
                )
                for cw in cw_resp.get("courseWork", []):
                    items.append(_coursework_to_item(cname, cw))
            except Exception as exc:
                logger.warning("gclassroom: coursework for %s failed: %s", cname, exc)
            # Announcements
            try:
                ann_resp = (
                    service.courses()
                    .announcements()
                    .list(courseId=cid, pageSize=self.max_per_course)
                    .execute()
                )
                for ann in ann_resp.get("announcements", []):
                    items.append(_announcement_to_item(cname, ann))
            except Exception as exc:
                logger.warning("gclassroom: announcements for %s failed: %s", cname, exc)

        logger.info("gclassroom: collected %d items", len(items))
        return items
