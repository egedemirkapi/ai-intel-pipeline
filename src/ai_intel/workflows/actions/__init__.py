"""Workflow action handlers.

Each action is an async function ``(engine, **kwargs) -> dict``. The
``ACTION_REGISTRY`` maps the dotted action name (which is ALSO the
capability-layer key) to its handler.

Adding a new action:
    1. Write the handler in one of the action modules.
    2. Register it in ``ACTION_REGISTRY`` below.
    3. Add an allow/deny entry in ``defaults/tools.toml``.
"""
from ai_intel.workflows.actions.agent import action_agent_run
from ai_intel.workflows.actions.apps import action_apps_launch
from ai_intel.workflows.actions.brief import action_brief_compose
from ai_intel.workflows.actions.calendar import action_calendar_check
from ai_intel.workflows.actions.classroom import action_classroom_check
from ai_intel.workflows.actions.gmail import action_email_check
from ai_intel.workflows.actions.notify import action_notify
from ai_intel.workflows.actions.tabs import action_tabs_open_set

# Dotted name -> handler. The name is the capability key checked
# against ~/.jarvis/tools.toml before the handler runs.
ACTION_REGISTRY = {
    "tabs.open_set":     action_tabs_open_set,
    "apps.launch":       action_apps_launch,
    "agent.run":         action_agent_run,
    "classroom.check":   action_classroom_check,
    "calendar.check":    action_calendar_check,
    "email.check":       action_email_check,
    "brief.compose":     action_brief_compose,
    "notify":            action_notify,
}

__all__ = ["ACTION_REGISTRY"]
