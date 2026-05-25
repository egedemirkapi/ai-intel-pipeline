"""Journey agent — multi-step orchestrator above the navigator.

A *journey* is a user task that spans more than one logical macro-step
with state flowing between them — typically files. Example:

    "Go to Google Classroom, navigate to my Chemistry class, find the
     exam details, download the materials, and create a new NotebookLM
     notebook with those materials."

The single-task navigator (25-step budget, one observe-decide-act loop)
can't reliably do this end-to-end. The journey agent:

  1. Decomposes the task into 2-6 substeps via one upfront LLM call.
  2. Creates a per-journey tmp dir under ``data/journeys/<id>/`` so
     downloaded files persist across substeps.
  3. Runs each substep via the navigator, threading ``save_dir`` and
     ``available_files`` so:
       - Substep N's downloads land in the shared dir.
       - Substep N+1 sees them in its AVAILABLE FILES block and can
         reference them by name in ``upload`` actions.
  4. Surfaces the per-substep results + aggregate downloads in the
     final ``output_pointer``.

Recipe replay is free here: the navigator persists a recipe per
substep keyed by the substep's task description. The next time the
journey decomposer produces similar substep tasks (or the same), each
navigator call resolves its recipe via semantic recall and replays
instantly instead of re-exploring. The journey itself doesn't need
its own recipe table; composition gives that for free.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from ai_intel.agents.decorator import agent
from ai_intel.agents.runtime import call_llm
from ai_intel.agents.saturator import _parse_llm_json

logger = logging.getLogger(__name__)


_DECOMPOSE_PROMPT = """You are decomposing a high-level web-automation task into a sequence of substeps for a single-task navigator agent.

USER TASK: {task}

STARTING URL (optional, "(none)" means navigator picks):
{url}

The navigator can within ONE substep:
  - goto / click / type / press / scroll
  - download — clicks an element that triggers a file save
  - upload  — pushes files (from a shared journey tmp dir) into a file input

State flows between substeps via that shared dir:
  - Downloads in earlier substeps become AVAILABLE FILES for later substeps.
  - The journey orchestrator threads paths automatically; you just describe
    the substep tasks naturally.

Decompose the task into 2-6 substeps. Each substep should be ONE coherent
macro-task the navigator can handle in under 25 atomic steps. Don't pack
too much into one substep — *navigate, then act* is two substeps. State
ALWAYS makes sense — a "create notebook and upload PDFs" substep is
fine because by then the PDFs are already downloaded into the shared dir.

For each substep provide:
  - task: clear natural-language instruction for the navigator (1-2 sentences)
  - url: optional starting URL (deep-link the right tab when possible);
         empty string to inherit the current browser state from the
         previous substep
  - expects: optional list of short tags describing what this substep
             produces ("class_url", "pdf_paths", "notebook_url") —
             informational only, the orchestrator threads files
             automatically

Reply with ONLY a JSON object:
{{
  "substeps": [
    {{"task": "...", "url": "...", "expects": ["..."]}},
    ...
  ]
}}

Example — for *"Go to Classroom, find Chemistry exam, download materials, create NotebookLM notebook with them"*:
{{
  "substeps": [
    {{"task": "Open the Chemistry class on Google Classroom and locate the exam announcement post", "url": "https://classroom.google.com/u/1/", "expects": ["exam_post_url"]}},
    {{"task": "Open the exam post and click each attached PDF link to download all attached materials", "url": "", "expects": ["pdf_paths"]}},
    {{"task": "Open NotebookLM, create a new notebook called 'Chemistry Exam Prep', and upload all the downloaded PDFs as sources", "url": "https://notebooklm.google.com", "expects": ["notebook_url"]}}
  ]
}}
"""


async def _decompose_task(
    task: str,
    url: str,
    *,
    model: str = "claude-haiku-4-5",
) -> tuple[list[dict], int, int, float, str | None]:
    """Decompose ``task`` into 2-6 navigator-executable substeps.

    Returns ``(substeps, prompt_tokens, completion_tokens, cost_usd,
    auth_mode)``. Empty substeps list on parse/LLM failure — caller
    returns a clear error rather than executing nothing.
    """
    prompt = _DECOMPOSE_PROMPT.format(task=task, url=url or "(none)")
    try:
        resp = call_llm(
            [{"role": "user", "content": prompt}],
            prefer="oauth", model=model,
            max_tokens=1500, temperature=0.3,
        )
    except Exception as exc:  # noqa: BLE001 — bubble up as empty plan
        logger.warning("journey: decompose LLM call failed (%s)", exc)
        return [], 0, 0, 0.0, None
    try:
        parsed = _parse_llm_json(resp.text)
    except Exception:  # noqa: BLE001
        return [], resp.prompt_tokens, resp.completion_tokens, resp.cost_usd, resp.auth_mode

    raw = parsed.get("substeps") or []
    if not isinstance(raw, list):
        return [], resp.prompt_tokens, resp.completion_tokens, resp.cost_usd, resp.auth_mode

    cleaned: list[dict] = []
    for entry in raw[:8]:
        if not isinstance(entry, dict):
            continue
        sub_task = str(entry.get("task") or "").strip()
        if not sub_task:
            continue
        sub_url = str(entry.get("url") or "").strip()
        expects = entry.get("expects") or []
        if not isinstance(expects, list):
            expects = []
        cleaned.append({
            "task": sub_task[:600],
            "url": sub_url[:400],
            "expects": [str(x)[:60] for x in expects if isinstance(x, str)][:6],
        })
    return cleaned, resp.prompt_tokens, resp.completion_tokens, resp.cost_usd, resp.auth_mode


def _journey_dir(root: Path = Path("data/journeys")) -> Path:
    """Create a fresh per-journey working dir.

    Format: ``data/journeys/<YYYYMMDD-HHMMSS>-<uuid12>/``. The timestamp
    prefix makes the dir listing chronological; the UUID suffix avoids
    collisions on rapid same-second calls.
    """
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    short_id = uuid.uuid4().hex[:12]
    out = root / f"{ts}-{short_id}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _summarise_substep_result(idx: int, sub_task: str, result: dict) -> str:
    """One-line summary of one navigator substep for the journey log."""
    summary = (result or {}).get("summary") or "(no summary)"
    return f"[{idx}] {sub_task[:80]} → {summary[:140]}"


@agent("journey")
async def journey(
    engine,
    *,
    task: str = "",
    url: str = "",
    model: str = "claude-haiku-4-5",
):
    """Run a multi-step browser journey.

    Args:
        task: high-level natural-language task ("go to Classroom, find
            exam, download PDFs, create NotebookLM notebook with them").
        url:  optional starting URL hint for the first substep.
        model: LLM for the decomposer (and the navigator's macro-planning,
            decide loop, etc.).

    Returns an AgentResult dict. ``output_pointer`` JSON carries:
        - ``journey_id``: short identifier
        - ``save_dir``:   path of the shared per-journey dir
        - ``substeps``:   per-substep records (task + summary + cost)
        - ``downloaded_files``: paths of files produced across the journey
    """
    task = (task or "").strip()
    if not task:
        return {"summary": "journey: no task given"}

    # Lazy import so the navigator module load doesn't fight with journey
    # at package init.
    from ai_intel.agents.navigator import navigator

    total_pt = total_ct = 0
    cost = 0.0
    auth_mode: str | None = None

    # --- Decompose ---------------------------------------------------------
    substeps, dpt, dct, dcost, d_auth = await _decompose_task(
        task, url, model=model,
    )
    total_pt += dpt
    total_ct += dct
    cost += dcost
    if d_auth:
        auth_mode = d_auth
    if not substeps:
        return {
            "summary": (
                "journey: couldn't decompose the task into substeps. "
                "Try rephrasing it as 'do X, then Y, then Z' with clearer "
                "stage breaks."
            ),
            "prompt_tokens": total_pt,
            "completion_tokens": total_ct,
            "cost_usd": cost,
            "auth_mode": auth_mode,
        }

    logger.info(
        "journey: decomposed into %d substep(s): %s",
        len(substeps),
        " · ".join(s["task"][:60] for s in substeps),
    )

    # --- Per-journey working dir ------------------------------------------
    save_dir = _journey_dir()
    available_files: list[Path] = []
    substep_results: list[dict] = []
    summary_lines: list[str] = []
    stopped_early = False
    stop_reason = ""

    # --- Execute substeps in order, threading file state ------------------
    for i, substep in enumerate(substeps, 1):
        sub_task = substep["task"]
        sub_url = substep["url"] or (url if i == 1 else "")
        try:
            result = await navigator(
                engine,
                task=sub_task,
                url=sub_url,
                save_dir=save_dir,
                available_files=list(available_files),
            )
        except Exception as exc:  # noqa: BLE001 — surface and stop
            logger.warning("journey: substep %d crashed (%s)", i, exc)
            substep_results.append({
                "substep": i,
                "task": sub_task,
                "error": f"{type(exc).__name__}: {exc}",
            })
            summary_lines.append(f"[{i}] {sub_task[:60]} → CRASHED: {exc}")
            stopped_early = True
            stop_reason = f"substep {i} raised {type(exc).__name__}"
            break

        # Roll up cost / tokens.
        total_pt += result.get("prompt_tokens", 0) or 0
        total_ct += result.get("completion_tokens", 0) or 0
        cost += result.get("cost_usd", 0.0) or 0.0
        if result.get("auth_mode"):
            auth_mode = result["auth_mode"]

        summary_lines.append(_summarise_substep_result(i, sub_task, result))

        # Pull downloaded files out of the navigator's output_pointer and
        # add them to available_files for subsequent substeps' upload
        # actions.
        ptr_raw = result.get("output_pointer")
        new_files: list[Path] = []
        if ptr_raw:
            try:
                ptr_data = json.loads(ptr_raw)
                for p in ptr_data.get("downloaded_files") or []:
                    new_files.append(Path(p))
            except (json.JSONDecodeError, TypeError):
                pass
        available_files.extend(new_files)

        substep_results.append({
            "substep": i,
            "task": sub_task,
            "url": sub_url,
            "summary": (result.get("summary") or "")[:240],
            "downloaded_files": [str(p) for p in new_files],
            "cost_usd": result.get("cost_usd", 0.0),
        })

        # Stop the journey if the navigator gave up or hit its step limit.
        sub_summary = (result.get("summary") or "").lower()
        if "gave up" in sub_summary or "hit the" in sub_summary and "limit" in sub_summary:
            stopped_early = True
            stop_reason = f"substep {i} stalled — {result.get('summary')}"
            break

    # --- Compose final summary --------------------------------------------
    head = (
        f"journey {'partial' if stopped_early else 'complete'}: "
        f"{len(substep_results)}/{len(substeps)} substep(s)"
    )
    if stopped_early and stop_reason:
        head += f" — {stop_reason}"
    if available_files:
        head += f" · {len(available_files)} file(s) collected"

    final_summary = (head + "\n" + "\n".join(summary_lines))[:480]

    return {
        "summary": final_summary,
        "prompt_tokens": total_pt,
        "completion_tokens": total_ct,
        "cost_usd": cost,
        "auth_mode": auth_mode,
        "output_pointer": json.dumps({
            "save_dir": str(save_dir),
            "substep_count": len(substeps),
            "completed": len(substep_results),
            "stopped_early": stopped_early,
            "downloaded_files": [str(p) for p in available_files],
            "substeps": substep_results,
        }),
    }
