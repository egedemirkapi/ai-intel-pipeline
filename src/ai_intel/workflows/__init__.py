"""Workflow engine — YAML-defined automations triggered by voice,
claps, the frontend, or Jarvis chat.

A workflow is a named sequence of steps. Each step names an action
(``tabs.open_set``, ``apps.launch``, ``agent.run``, ``classroom.check``,
``notify``) and its arguments. The engine runs steps in order, gating
each action through the capability layer.

User workflows live in ``~/.jarvis/workflows.yaml`` (created by
``jarvis init``). The engine ships sane defaults for clap_default,
homework_check, and morning_brief.

Public surface:
    run_workflow(engine, name)  — execute one workflow by name
    load_workflows()            — parse the YAML
    list_workflows()            — names + descriptions + triggers
    ACTION_REGISTRY             — name -> action handler

Editing (dashboard routine editor):
    list_workflow_defs(), get_workflow(), create_workflow(),
    update_workflow(), delete_workflow(), validate_def()

Trigger resolution:
    workflows_with_trigger(), hotkey_map(), match_voice()
"""
from ai_intel.workflows.engine import (
    list_workflows,
    load_workflows,
    run_workflow,
)
from ai_intel.workflows.persist import (
    WorkflowError,
    create_workflow,
    delete_workflow,
    get_workflow,
    list_workflow_defs,
    update_workflow,
    validate_def,
)
from ai_intel.workflows.triggers import (
    hotkey_map,
    match_app,
    match_voice,
    workflows_with_trigger,
)

__all__ = [
    "list_workflows",
    "load_workflows",
    "run_workflow",
    "WorkflowError",
    "create_workflow",
    "delete_workflow",
    "get_workflow",
    "list_workflow_defs",
    "update_workflow",
    "validate_def",
    "hotkey_map",
    "match_app",
    "match_voice",
    "workflows_with_trigger",
]
