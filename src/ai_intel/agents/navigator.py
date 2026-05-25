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

The navigator executes every action it decides on directly — no
per-action confirmation. The user can watch the visible browser and
intervene; `browser.navigate` can be set to "deny" in tools.toml to
switch the whole capability off.
"""
from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

from ai_intel.agents.decorator import agent
from ai_intel.agents.runtime import call_llm
from ai_intel.agents.saturator import _parse_llm_json
from ai_intel.browser import BrowserError, BrowserSession
from ai_intel.memory import (
    recall_recipes,
    record_recipe_run,
    save_recipe,
    update_recipe_steps,
)

logger = logging.getLogger(__name__)

MAX_STEPS_DEFAULT = 25
SETTLE_MS = 600  # let the page settle after an action before the next snapshot
# Decide-step model. Haiku 4.5 is capable for stepwise UI decisions and sits
# on a higher rate-limit tier than Sonnet — which matters for this call-heavy
# loop. With the OAuth bridge configured, prefer="oauth" routes around it.
DECIDE_MODEL = "claude-haiku-4-5"

_PLAN_PROMPT = """You are Jarvis's browser navigator, planning a multi-step navigation BEFORE you start clicking.

TASK: {task}

CURRENT PAGE (your starting point):
{page}
{files_block}
Plan the 3-8 HIGH-LEVEL steps to complete this task. Each step is ONE
clear stage a person could describe ("Click the Chemistry class card",
"Find the exam-related post", "Click each PDF attachment to download").
Stay at the macro level — don't pick element indices yet; the
step-by-step loop will resolve those.

If the page already looks like the task is partway done (e.g. you're
already on the right Classroom page), reflect that in step 1 ("Page
is already on Chemistry class — start by clicking Classwork tab").

Reply with ONLY a JSON object:
{{
  "steps": ["<step 1>", "<step 2>", ...]
}}
"""


_DECIDE_PROMPT = """You are Jarvis's browser navigator. You drive a real browser to complete a task for the user.

TASK: {task}
{macro_plan}
CURRENT PAGE:
{page}

ACTIONS SO FAR:
{history}
{files_block}
Decide the SINGLE next action. Reply with ONLY a JSON object:
{{
  "thought": "<one short sentence of reasoning>",
  "action": "click" | "type" | "press" | "scroll" | "goto" | "download" | "upload" | "done" | "give_up",
  "index": <element number — for click/type/download/upload>,
  "text": "<text to type, for type>",
  "key": "<key name e.g. Enter, for press>",
  "url": "<url, for goto>",
  "dy": <pixels to scroll, for scroll>,
  "save_as": "<optional suggested filename for download — browser usually provides one>",
  "files": ["<filename>", ...] OR "*",  // for upload — filenames from AVAILABLE FILES, or "*" for all
  "summary": "<for done/give_up only: what was accomplished, or why you are stuck>"
}}

Rules:
- Choose "done" only when the task is genuinely complete.
- Choose "give_up" if you are stuck after trying — explain why in summary.
- Use the element NUMBERS shown in CURRENT PAGE for index.
- To enter text: "type" into a field, then "press" Enter or "click" a save/submit button.
- "download" clicks an element that triggers a file save (a PDF link, a Download button, a "save as" affordance). The file lands in the journey's save_dir automatically; you do NOT need to choose a location.
- "upload" pushes one or more files to a file-input or upload control. Reference files by NAME from AVAILABLE FILES (use "*" for all). For sites where the visible "Add source" / "Upload" button isn't itself the input, this still works — Jarvis handles the file-picker dialog. If you don't see an upload-capable element on the current page, "click" the affordance that opens the picker first, then re-snapshot.
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


def _resolve_upload_files(
    spec, available: list[Path],
) -> list[str]:
    """Resolve the upload action's `files` field to absolute string paths.

    Accepts "*" / ["*"] (all available), a list of filenames (matched by
    basename or full-path suffix), or a list of integer indices into
    ``available``. Returns deduplicated absolute paths.
    """
    if spec == "*" or spec == ["*"]:
        return [str(Path(p).resolve()) for p in available]
    if not isinstance(spec, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for name in spec:
        match: Path | None = None
        if isinstance(name, int) and 0 <= name < len(available):
            match = Path(available[name])
        elif isinstance(name, str):
            for p in available:
                p_obj = Path(p)
                if p_obj.name == name or str(p_obj).endswith(name):
                    match = p_obj
                    break
        if match is not None:
            resolved = str(match.resolve())
            if resolved not in seen:
                seen.add(resolved)
                out.append(resolved)
    return out


def _format_files_block(
    save_dir: Path, files: list[Path],
) -> str:
    """Render an AVAILABLE FILES section for the decide-step prompt.

    Lists files available for upload (with size when readable) and the
    target dir downloads will land in. Returns a leading newline so the
    block visually separates from the preceding ACTIONS SO FAR section.
    """
    if files:
        lines = [
            "",
            "AVAILABLE FILES (reference by filename in `files` for upload):",
        ]
        for p in files:
            path = Path(p)
            try:
                size_kb = path.stat().st_size // 1024
                lines.append(f"  - {path.name} ({size_kb} KB) — {path}")
            except OSError:
                lines.append(f"  - {path.name} — {path}")
        lines.append(f"(downloads land in: {save_dir})")
        return "\n".join(lines) + "\n"
    return f"\n(downloads land in: {save_dir})\n"


def _format_macro_plan(plan: list[str]) -> str:
    """Render the macro plan for injection into the decide-step prompt.

    Empty plan → empty string (the decide-step works without a plan, same
    as pre-macro-planning navigator behavior). Otherwise a numbered list
    the decide-LLM can read as strategic context for picking each next
    atomic action.
    """
    if not plan:
        return ""
    lines = ["", "MACRO PLAN (the high-level shape you committed to at the start):"]
    for i, step in enumerate(plan, 1):
        lines.append(f"  {i}. {step}")
    lines.append(
        "(Use this as a guide. If the page state suggests jumping a step "
        "or revising, do that — the plan is scaffolding, not a contract.)"
    )
    return "\n".join(lines) + "\n"


async def _plan_macro_steps(
    task: str,
    snapshot,
    available_files: list[Path],
    save_dir: Path,
    *,
    model: str = DECIDE_MODEL,
) -> tuple[list[str], int, int, float, str | None]:
    """One upfront LLM call to plan the high-level substeps.

    The decide-step LLM then sees this plan in every subsequent prompt,
    so atomic clicks/types/downloads are made with the macro strategy in
    context rather than reasoning from page state alone — this is what
    keeps the navigator from wandering on complex UIs.

    Returns ``(steps, prompt_tokens, completion_tokens, cost_usd,
    auth_mode)``. Empty step list on failure — the navigator falls
    back to step-by-step deciding without a plan, which is the
    pre-macro-planning behavior (still works, just less coherent).
    """
    prompt = _PLAN_PROMPT.format(
        task=task,
        page=snapshot.to_prompt(),
        files_block=_format_files_block(save_dir, available_files),
    )
    try:
        resp = call_llm(
            [{"role": "user", "content": prompt}],
            prefer="oauth", model=model,
            max_tokens=600, temperature=0.3,
        )
    except Exception as exc:  # noqa: BLE001 — plan is best-effort
        logger.warning(
            "navigator: macro-planning call failed (%s) — "
            "proceeding without a plan", exc,
        )
        return [], 0, 0, 0.0, None
    try:
        parsed = _parse_llm_json(resp.text)
    except Exception:  # noqa: BLE001
        return [], resp.prompt_tokens, resp.completion_tokens, resp.cost_usd, resp.auth_mode
    raw_steps = parsed.get("steps") or []
    if not isinstance(raw_steps, list):
        return [], resp.prompt_tokens, resp.completion_tokens, resp.cost_usd, resp.auth_mode
    cleaned = [str(s).strip()[:240] for s in raw_steps if str(s).strip()][:10]
    return cleaned, resp.prompt_tokens, resp.completion_tokens, resp.cost_usd, resp.auth_mode


async def _execute(
    session: BrowserSession,
    action: dict,
    snapshot,
    *,
    save_dir: Path,
    available_files: list[Path],
) -> dict:
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

    # All remaining actions take an element index. Resolve it now so we
    # have the role+label for replay-keyed recipes (recipes find elements
    # by role+label, not by index — indices shift between sessions).
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
    if act == "download":
        path = await session.download(idx, save_dir)
        return {"action": "download", "role": el.role, "label": el.label,
                "path": str(path),
                "desc": f"download '{el.label}' → {path.name}"}
    if act == "upload":
        files_spec = action.get("files", "*")
        paths = _resolve_upload_files(files_spec, available_files)
        if not paths:
            raise BrowserError(
                f"upload: no files match spec {files_spec!r} "
                f"(available: {[Path(p).name for p in available_files]})"
            )
        await session.upload(idx, paths)
        return {"action": "upload", "role": el.role, "label": el.label,
                "files": [Path(p).name for p in paths],
                "desc": f"upload {len(paths)} file(s) to '{el.label}'"}
    raise BrowserError(f"unknown action: {act!r}")


async def _replay_recipe(
    session: BrowserSession,
    steps: list[dict],
    *,
    save_dir: Path,
    available_files: list[Path],
):
    """Replay saved recipe steps.

    Returns ``(success, completed_steps, failure_reason, downloads)``.
    On any failed step, stops and reports — the navigator then falls
    back to live LLM navigation from there. ``downloads`` lists any
    files saved during the replay so the caller (the journey
    orchestrator, typically) can thread them into subsequent substeps.
    """
    done: list[dict] = []
    downloads: list[Path] = []
    # Track files that become available mid-replay (downloads from earlier
    # steps in the same recipe).
    runtime_available: list[Path] = list(available_files)
    for i, step in enumerate(steps):
        act = step.get("action")
        try:
            if act == "goto":
                await session.goto(step.get("url", ""))
            elif act == "scroll":
                await session.scroll(int(step.get("dy", 600) or 600))
            elif act == "press":
                await session.press(step.get("key", "Enter"))
            elif act in ("click", "type", "download", "upload"):
                snap = await session.snapshot()
                idx = _find_element(snap, step.get("role", ""), step.get("label", ""))
                if idx is None:
                    return (
                        False, done,
                        f"step {i + 1}: '{step.get('label')}' not found",
                        downloads,
                    )
                if act == "click":
                    await session.click(idx)
                elif act == "type":
                    await session.type_text(idx, step.get("text", ""))
                elif act == "download":
                    path = await session.download(idx, save_dir)
                    downloads.append(path)
                    runtime_available.append(path)
                elif act == "upload":
                    paths = _resolve_upload_files(
                        step.get("files", "*"), runtime_available,
                    )
                    if not paths:
                        return (
                            False, done,
                            f"step {i + 1}: upload had no files to attach",
                            downloads,
                        )
                    await session.upload(idx, paths)
            else:
                return (
                    False, done,
                    f"step {i + 1}: unknown action {act!r}",
                    downloads,
                )
            done.append(step)
            await session.page.wait_for_timeout(SETTLE_MS)
        except BrowserError as exc:
            return False, done, f"step {i + 1}: {exc}", downloads
    return True, done, "", downloads


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
async def navigator(
    engine,
    *,
    task: str = "",
    url: str = "",
    max_steps: int = MAX_STEPS_DEFAULT,
    save_dir: Path | str | None = None,
    available_files: list[Path | str] | None = None,
):
    """Drive the browser to complete `task`, learning a recipe as it goes.

    Args:
        task: natural-language task, e.g. "create a new notebook in NotebookLM".
        url:  optional starting URL; if omitted the LLM navigates there itself.
        max_steps: cap on observe -> decide -> act iterations.
        save_dir: where downloaded files should land. Defaults to a fresh
            ``tempfile.mkdtemp()`` per navigator call; the journey
            orchestrator passes its own per-journey dir so files persist
            across substeps.
        available_files: files the journey orchestrator (or caller) has
            staged for upload steps. The decide-step LLM sees these in
            the AVAILABLE FILES block of the prompt and references them
            by filename in `upload` actions. Downloads made during this
            run are appended to this list automatically, so a single
            navigator run can download-then-upload within itself.

    Returns an AgentResult dict (summary + token/cost totals). The
    ``output_pointer`` JSON includes ``downloaded_files`` (absolute
    paths) and ``save_dir`` so the journey orchestrator can thread
    file paths into subsequent substeps.
    """
    task = (task or "").strip()
    if not task:
        return {"summary": "navigator: no task given"}

    # Resolve save_dir. A per-run tempdir when none is passed keeps single
    # navigator invocations self-contained; journeys override this with a
    # per-journey dir so downloads survive across substeps.
    if save_dir is None:
        save_dir = Path(tempfile.mkdtemp(prefix="jarvis-nav-"))
    else:
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)

    available: list[Path] = [Path(p) for p in (available_files or [])]
    downloaded: list[Path] = []

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
        # Recipe memory is an optimization — a failure here (a DB hiccup,
        # a stale schema) must never block the actual navigation.
        recipe_id: int | None = None
        try:
            recipes = recall_recipes(engine, task, k=3)
        except Exception as exc:  # noqa: BLE001
            logger.warning("navigator: recipe recall failed (%s) — "
                            "navigating live", exc)
            recipes = []
        match = next(
            (r for r in recipes
             if r.get("score", 0) >= 0.78 and r.get("success_count", 0) > 0),
            None,
        )
        if match is not None:
            recipe_id = match["id"]
            ok, done_steps, fail_reason, replay_downloads = await _replay_recipe(
                session, match["steps"],
                save_dir=save_dir, available_files=available,
            )
            downloaded.extend(replay_downloads)
            available.extend(replay_downloads)
            if ok:
                record_recipe_run(engine, recipe_id, success=True)
                return {"summary": f"replayed saved recipe for: {task}",
                        "output_pointer": json.dumps({
                            "recipe_id": recipe_id, "replayed": True,
                            "downloaded_files": [str(p) for p in downloaded],
                            "save_dir": str(save_dir),
                        })}
            logger.info("navigator: recipe #%s replay failed (%s) — exploring live",
                        recipe_id, fail_reason)
            history.append(f"(saved recipe failed: {fail_reason} — continuing live)")
            steps_taken = list(done_steps)

        # --- Macro-planning: one upfront LLM call to sketch the shape ----
        # Every subsequent decide-step gets this plan in its prompt, so
        # atomic clicks are made with strategy in context — not just page
        # state. This is what kills the wandering on complex UIs.
        first_snapshot = await session.snapshot()
        plan, ppt, pct, pcost, p_auth = await _plan_macro_steps(
            task, first_snapshot, available, save_dir,
        )
        total_pt += ppt
        total_ct += pct
        cost += pcost
        if p_auth:
            auth_mode = p_auth
        plan_block = _format_macro_plan(plan)
        if plan:
            logger.info(
                "navigator: macro plan (%d steps): %s",
                len(plan), " · ".join(plan),
            )
            history.append(f"(macro plan: {len(plan)} steps committed)")

        # --- Live observe -> decide -> act loop ---------------------------
        # Reuse first_snapshot for step 1 to avoid a redundant snapshot.
        pending_snapshot = first_snapshot
        for step_no in range(1, max_steps + 1):
            if pending_snapshot is not None:
                snapshot = pending_snapshot
                pending_snapshot = None
            else:
                snapshot = await session.snapshot()
            prompt = _DECIDE_PROMPT.format(
                task=task,
                macro_plan=plan_block,
                page=snapshot.to_prompt(),
                history="\n".join(history[-12:]) or "(none yet)",
                files_block=_format_files_block(save_dir, available),
            )
            try:
                resp = call_llm(
                    [{"role": "user", "content": prompt}],
                    prefer="oauth", model=DECIDE_MODEL,
                    max_tokens=700, temperature=0.2,
                )
            except Exception as exc:  # noqa: BLE001 — LLM rate-limited / unreachable
                logger.warning(
                    "navigator: decide-step LLM call failed — %s", exc)
                return {
                    "summary": (
                        f"navigator paused on '{task}' — the AI service "
                        f"is rate-limited or unreachable "
                        f"({type(exc).__name__}). Got through "
                        f"{len(steps_taken)} step(s); try again shortly."
                    )[:480],
                    "prompt_tokens": total_pt,
                    "completion_tokens": total_ct,
                    "cost_usd": cost,
                    "auth_mode": auth_mode,
                }
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
                        "output_pointer": json.dumps({
                            "steps": len(steps_taken),
                            "downloaded_files": [str(p) for p in downloaded],
                            "save_dir": str(save_dir),
                        })}

            if act == "give_up":
                if recipe_id is not None:
                    record_recipe_run(engine, recipe_id, success=False,
                                      failure_reason=action.get("summary"))
                why = action.get("summary") or task
                return {"summary": f"navigator gave up: {why}"[:480],
                        "prompt_tokens": total_pt, "completion_tokens": total_ct,
                        "cost_usd": cost, "auth_mode": auth_mode,
                        "output_pointer": json.dumps({
                            "downloaded_files": [str(p) for p in downloaded],
                            "save_dir": str(save_dir),
                        })}

            try:
                stable = await _execute(
                    session, action, snapshot,
                    save_dir=save_dir, available_files=available,
                )
            except BrowserError as exc:
                history.append(f"step {step_no}: {act} FAILED — {exc}")
                continue

            steps_taken.append(stable)
            history.append(f"step {step_no}: {stable.get('desc')}")
            # Track downloads so subsequent upload actions in the same run
            # see them in AVAILABLE FILES.
            if stable.get("action") == "download" and stable.get("path"):
                p = Path(stable["path"])
                downloaded.append(p)
                available.append(p)
            await session.page.wait_for_timeout(SETTLE_MS)

        if recipe_id is not None:
            record_recipe_run(engine, recipe_id, success=False,
                              failure_reason="step limit reached")
        return {"summary": f"navigator hit the {max_steps}-step limit on: {task}"[:480],
                "prompt_tokens": total_pt, "completion_tokens": total_ct,
                "cost_usd": cost, "auth_mode": auth_mode,
                "output_pointer": json.dumps({
                    "steps": len(steps_taken),
                    "downloaded_files": [str(p) for p in downloaded],
                    "save_dir": str(save_dir),
                })}
    finally:
        await session.close()
