"""Navigator agent — drives the browser step by step to complete a task.

The navigator is Jarvis's in-app hands. Given a natural-language task
("create a new notebook in NotebookLM"), it:

  1. Recalls a saved *recipe* for the task — if a good one exists it
     replays the stored steps (fast, no LLM per step) and only falls
     back to live navigation on a step that no longer works.
  2. Otherwise it runs an observe -> decide -> act loop: snapshot the
     page's interactive elements, ask the LLM for the next action,
     execute it, repeat — until the task is done.
  3. On success it saves / updates the recipe, so the next run is fast.
     That is the "gets better over time."

Safety: every *consequential* action (submit / send / post / buy /
delete) pauses and waits for the user's approval before it runs.
"""
from __future__ import annotations

import json
import logging
import time

from ai_intel.agents.decorator import agent
from ai_intel.agents.runtime import call_llm
from ai_intel.agents.saturator import _parse_llm_json
from ai_intel.browser import BrowserError, BrowserSession
from ai_intel.jarvis.permissions import is_allowed, list_approvals, request_approval
from ai_intel.memory import (
    recall_recipes,
    record_recipe_run,
    save_recipe,
    update_recipe_steps,
)

logger = logging.getLogger(__name__)

MAX_STEPS_DEFAULT = 25
APPROVAL_TIMEOUT_S = 180.0
APPROVAL_POLL_S = 3.0
SETTLE_MS = 600  # let the page settle after an action before the next snapshot

# Keyword backstop for the risky-action classifier — even if the LLM does
# not tag an action risky, a target element whose label matches one of
# these is treated as consequential and gated.
_RISKY_KEYWORDS = (
    "submit", "send", "post", "publish", "buy", "purchase", "pay",
    "order", "checkout", "delete", "remove", "confirm", "sign out",
    "log out", "unsubscribe", "deactivate", "transfer",
)

_DECIDE_PROMPT = """You are Jarvis's browser navigator. You drive a real browser to complete a task for the user.

TASK: {task}

CURRENT PAGE:
{page}

ACTIONS SO FAR:
{history}

Decide the SINGLE next action. Reply with ONLY a JSON object:
{{
  "thought": "<one short sentence of reasoning>",
  "action": "click" | "type" | "press" | "scroll" | "goto" | "done" | "give_up",
  "index": <element number, for click/type>,
  "text": "<text to type, for type>",
  "key": "<key name e.g. Enter, for press>",
  "url": "<url, for goto>",
  "dy": <pixels to scroll, for scroll>,
  "risky": <true if this action SENDS, SUBMITS, POSTS, BUYS, DELETES or otherwise has a real consequence; else false>,
  "summary": "<for done/give_up only: what was accomplished, or why you are stuck>"
}}

Rules:
- Choose "done" only when the task is genuinely complete.
- Choose "give_up" if you are stuck after trying — explain why in summary.
- Use the element NUMBERS shown in CURRENT PAGE for index.
- To enter text: "type" into a field, then "press" Enter or "click" a save/submit button.
- Be honest about "risky": anything that commits an action the user would care about must be true.
"""


def _app_from_url(url: str) -> str:
    """Best-effort app tag from a URL host (used to key recipes)."""
    if not url:
        return "web"
    try:
        host = url.split("//", 1)[-1].split("/", 1)[0].lower()
    except Exception:
        return "web"
    if "notebooklm" in host:
        return "notebooklm"
    if "classroom.google" in host:
        return "classroom"
    if "mail.google" in host:
        return "gmail"
    parts = host.replace("www.", "").split(".")
    return parts[0] if parts and parts[0] else "web"


def _is_risky(action: dict, snapshot) -> bool:
    """True if the action is consequential — by the LLM's own flag or a
    keyword match on the target element's label."""
    if action.get("risky") is True:
        return True
    if action.get("action") not in ("click", "press"):
        return False
    label = ""
    idx = action.get("index")
    if isinstance(idx, int) and snapshot is not None:
        for el in snapshot.elements:
            if el.index == idx:
                label = (el.label or "").lower()
                break
    blob = f"{label} {action.get('key', '')}".lower()
    return any(kw in blob for kw in _RISKY_KEYWORDS)


def _await_approval(approval_id: str, *, timeout_s: float = APPROVAL_TIMEOUT_S) -> bool:
    """Block until the approval is resolved. True if approved; False if
    rejected or timed out."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for entry in list_approvals(status=None):
            if entry.get("id") == approval_id:
                status = entry.get("status")
                if status == "approved":
                    return True
                if status == "rejected":
                    return False
        time.sleep(APPROVAL_POLL_S)
    logger.warning("navigator: approval %s timed out", approval_id)
    return False


def _find_element(snapshot, role: str, label: str) -> int | None:
    """Find the current element index matching a recipe step's role + label
    — exact label match first, then case-insensitive contains."""
    label_l = (label or "").strip().lower()
    for el in snapshot.elements:
        if el.role == role and (el.label or "").strip().lower() == label_l:
            return el.index
    for el in snapshot.elements:
        if el.role == role and label_l and label_l in (el.label or "").lower():
            return el.index
    return None


async def _execute(session: BrowserSession, action: dict, snapshot) -> dict:
    """Run one LLM-chosen action; return a stable, replayable step dict."""
    act = action.get("action")
    if act == "goto":
        url = action.get("url", "")
        await session.goto(url)
        return {"action": "goto", "url": url, "desc": f"goto {url}"}
    if act == "scroll":
        dy = int(action.get("dy", 600) or 600)
        await session.scroll(dy)
        return {"action": "scroll", "dy": dy, "desc": f"scroll {dy}px"}
    if act == "press":
        key = action.get("key", "Enter")
        await session.press(key)
        return {"action": "press", "key": key, "desc": f"press {key}"}
    # click / type — resolve the element by index
    idx = int(action.get("index"))
    el = next((e for e in snapshot.elements if e.index == idx), None)
    if el is None:
        raise BrowserError(f"no element with index {idx}")
    if act == "click":
        await session.click(idx)
        return {"action": "click", "role": el.role, "label": el.label,
                "desc": f"click {el.role} '{el.label}'"}
    if act == "type":
        text = action.get("text", "")
        await session.type_text(idx, text)
        return {"action": "type", "role": el.role, "label": el.label,
                "text": text, "desc": f"type into {el.role} '{el.label}'"}
    raise BrowserError(f"unknown action: {act!r}")


async def _replay_recipe(session: BrowserSession, steps: list[dict]):
    """Replay saved recipe steps. Returns (success, completed_steps,
    failure_reason). On any failed step, stop and report — the navigator
    then falls back to live LLM navigation from there."""
    done: list[dict] = []
    for i, step in enumerate(steps):
        act = step.get("action")
        try:
            if act == "goto":
                await session.goto(step.get("url", ""))
            elif act == "scroll":
                await session.scroll(int(step.get("dy", 600) or 600))
            elif act == "press":
                await session.press(step.get("key", "Enter"))
            elif act in ("click", "type"):
                snap = await session.snapshot()
                idx = _find_element(snap, step.get("role", ""), step.get("label", ""))
                if idx is None:
                    return False, done, f"step {i + 1}: '{step.get('label')}' not found"
                if act == "click":
                    await session.click(idx)
                else:
                    await session.type_text(idx, step.get("text", ""))
            else:
                return False, done, f"step {i + 1}: unknown action {act!r}"
            done.append(step)
            await session.page.wait_for_timeout(SETTLE_MS)
        except BrowserError as exc:
            return False, done, f"step {i + 1}: {exc}"
    return True, done, ""


def _persist_recipe(engine, recipe_id: int | None, task: str,
                    steps: list[dict], app: str) -> int | None:
    """Save a new recipe, or update an existing one's steps (self-heal)."""
    if not steps:
        return recipe_id
    try:
        if recipe_id is not None:
            update_recipe_steps(engine, recipe_id, steps)
            record_recipe_run(engine, recipe_id, success=True)
            return recipe_id
        new_id = save_recipe(engine, task, steps, app)
        record_recipe_run(engine, new_id, success=True)
        return new_id
    except Exception as exc:  # pragma: no cover — persistence is best-effort
        logger.warning("navigator: could not persist recipe: %s", exc)
        return recipe_id


@agent("navigator")
async def navigator(engine, *, task: str = "", url: str = "",
                    max_steps: int = MAX_STEPS_DEFAULT):
    """Drive the browser to complete `task`, learning a recipe as it goes.

    Args:
        task: natural-language task, e.g. "create a new notebook in NotebookLM".
        url:  optional starting URL; if omitted the LLM navigates there itself.
        max_steps: cap on observe -> decide -> act iterations.

    Returns an AgentResult dict (summary + token/cost totals).
    """
    # Coarse capability gate — the user enables browser navigation once.
    if not is_allowed("browser.navigate"):
        aid = request_approval(
            "browser.navigate", {"task": task},
            reason="browser navigation is denied by default — enable it once",
        )
        return {"summary": (
            "Browser navigation is disabled. Enable 'browser.navigate' in "
            f"~/.jarvis/tools.toml, or approve request {aid}."
        )}

    task = (task or "").strip()
    if not task:
        return {"summary": "navigator: no task given"}

    steps_taken: list[dict] = []
    history: list[str] = []
    total_pt = total_ct = 0
    cost = 0.0
    auth_mode = "oauth"
    app = _app_from_url(url)

    session = BrowserSession()
    try:
        try:
            await session.connect()
        except BrowserError as exc:
            return {"summary": (
                f"navigator: couldn't connect to your browser ({exc}). "
                "Close other Edge windows so Jarvis can launch a debuggable one."
            )}

        if url:
            await session.goto(url)

        # --- Recipe-first: replay a known-good path if we have one --------
        recipe_id: int | None = None
        recipes = recall_recipes(engine, task, k=3)
        match = next(
            (r for r in recipes
             if r.get("score", 0) >= 0.78 and r.get("success_count", 0) > 0),
            None,
        )
        if match is not None:
            recipe_id = match["id"]
            ok, done_steps, fail_reason = await _replay_recipe(session, match["steps"])
            if ok:
                record_recipe_run(engine, recipe_id, success=True)
                return {"summary": f"replayed saved recipe for: {task}",
                        "output_pointer": json.dumps(
                            {"recipe_id": recipe_id, "replayed": True})}
            logger.info("navigator: recipe #%s replay failed (%s) — exploring live",
                        recipe_id, fail_reason)
            history.append(f"(saved recipe failed: {fail_reason} — continuing live)")
            steps_taken = list(done_steps)

        # --- Live observe -> decide -> act loop ---------------------------
        for step_no in range(1, max_steps + 1):
            snapshot = await session.snapshot()
            prompt = _DECIDE_PROMPT.format(
                task=task,
                page=snapshot.to_prompt(),
                history="\n".join(history[-12:]) or "(none yet)",
            )
            resp = call_llm(
                [{"role": "user", "content": prompt}],
                prefer="oauth", model="claude-sonnet-4-6",
                max_tokens=700, temperature=0.2,
            )
            total_pt += resp.prompt_tokens
            total_ct += resp.completion_tokens
            cost += resp.cost_usd
            auth_mode = resp.auth_mode

            try:
                action = _parse_llm_json(resp.text)
            except Exception as exc:  # noqa: BLE001 — unparseable, skip & retry
                history.append(f"step {step_no}: (unparseable LLM reply: {exc})")
                continue

            act = action.get("action")

            if act == "done":
                _persist_recipe(engine, recipe_id, task, steps_taken, app)
                summary = action.get("summary") or f"completed: {task}"
                return {"summary": summary[:480],
                        "prompt_tokens": total_pt, "completion_tokens": total_ct,
                        "cost_usd": cost, "auth_mode": auth_mode,
                        "output_pointer": json.dumps({"steps": len(steps_taken)})}

            if act == "give_up":
                if recipe_id is not None:
                    record_recipe_run(engine, recipe_id, success=False,
                                      failure_reason=action.get("summary"))
                why = action.get("summary") or task
                return {"summary": f"navigator gave up: {why}"[:480],
                        "prompt_tokens": total_pt, "completion_tokens": total_ct,
                        "cost_usd": cost, "auth_mode": auth_mode}

            # Risky-action gate — pause for the user before consequences.
            if _is_risky(action, snapshot):
                aid = request_approval(
                    "browser.act", {"task": task, "action": action},
                    reason=f"navigator wants to: {action.get('thought') or act}",
                )
                logger.info("navigator: risky action — awaiting approval %s", aid)
                if not _await_approval(aid):
                    return {"summary": (
                        "navigator stopped: a consequential action was not "
                        f"approved ({action.get('thought') or act})")[:480],
                        "prompt_tokens": total_pt, "completion_tokens": total_ct,
                        "cost_usd": cost, "auth_mode": auth_mode}

            try:
                stable = await _execute(session, action, snapshot)
            except BrowserError as exc:
                history.append(f"step {step_no}: {act} FAILED — {exc}")
                continue

            steps_taken.append(stable)
            history.append(f"step {step_no}: {stable.get('desc')}")
            await session.page.wait_for_timeout(SETTLE_MS)

        if recipe_id is not None:
            record_recipe_run(engine, recipe_id, success=False,
                              failure_reason="step limit reached")
        return {"summary": f"navigator hit the {max_steps}-step limit on: {task}"[:480],
                "prompt_tokens": total_pt, "completion_tokens": total_ct,
                "cost_usd": cost, "auth_mode": auth_mode}
    finally:
        await session.close()
