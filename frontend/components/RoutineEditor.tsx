"use client";

import { useEffect, useRef, useState } from "react";
import { load as yamlLoad, dump as yamlDump } from "js-yaml";
import { api, WorkflowDef, WorkflowStep } from "@/lib/api";
import { buildCron, parseCron, WEEKDAYS } from "@/lib/cron";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Toggle from "@/components/ui/Toggle";
import AppPicker from "@/components/AppPicker";

const ACTIONS = [
  "tabs.open_set",
  "news.open",
  "news.email_digest",
  "apps.launch",
  "agent.run",
  "classroom.check",
  "calendar.check",
  "email.check",
  "brief.compose",
  "speak",
  "notify",
] as const;
const AGENTS = ["saturator", "synthesizer", "proposer", "evaluator", "weekly_ideation"];

interface EditStep {
  action: string;
  args: Record<string, unknown>;
}

function defaultArgs(action: string): Record<string, unknown> {
  switch (action) {
    case "tabs.open_set":
      return { urls: [""] };
    case "news.open":
      return { count: 5 };
    case "news.email_digest":
      return { window_hours: 48 };
    case "apps.launch":
      return { app_id: "", name: "" };
    case "agent.run":
      return { agent_id: "synthesizer" };
    case "classroom.check":
      return { days_ahead: 7 };
    case "calendar.check":
      return { days_ahead: 7 };
    case "email.check":
      return { max_messages: 15 };
    case "brief.compose":
      return {};
    case "speak":
      return { text: "" };
    default:
      return { title: "Jarvis", body: "" };
  }
}

function toEditSteps(steps: WorkflowStep[]): EditStep[] {
  return (steps || []).map((s) => {
    const action = Object.keys(s)[0] ?? "notify";
    return { action, args: { ...(s[action] || {}) } };
  });
}

function fromEditSteps(steps: EditStep[]): WorkflowStep[] {
  return steps.map((s) => ({ [s.action]: s.args }));
}

// trigger.on_app may be a string or a list — the editor edits it as a
// single comma-joined string.
function asAppString(v: unknown): string {
  if (typeof v === "string") return v;
  if (Array.isArray(v)) return v.filter((x) => typeof x === "string").join(", ");
  return "";
}

export default function RoutineEditor({
  name,
  initial,
  isNew,
  onClose,
}: {
  name: string;
  initial: WorkflowDef | null;
  isNew: boolean;
  onClose: (saved: boolean) => void;
}) {
  const [wfName, setWfName] = useState(name);
  const [description, setDescription] = useState(initial?.description ?? "");
  const [trgButton, setTrgButton] = useState(!!initial?.trigger?.button);
  const [trgClap, setTrgClap] = useState(!!initial?.trigger?.clap);
  const [hotkey, setHotkey] = useState(initial?.trigger?.hotkey ?? "");
  const [phrases, setPhrases] = useState<string[]>(
    initial?.trigger?.voice_phrases ?? [],
  );
  const [phraseInput, setPhraseInput] = useState("");
  const [onApp, setOnApp] = useState(asAppString(initial?.trigger?.on_app));
  const _sched = parseCron(initial?.trigger?.schedule ?? "");
  const [schedFreq, setSchedFreq] = useState<string>(
    initial?.trigger?.schedule ? _sched.freq : "none",
  );
  const [schedTime, setSchedTime] = useState(_sched.time);
  const [schedDow, setSchedDow] = useState(_sched.dow);
  const [schedRaw, setSchedRaw] = useState(initial?.trigger?.schedule ?? "");
  const [steps, setSteps] = useState<EditStep[]>(
    initial ? toEditSteps(initial.steps) : [{ action: "notify", args: defaultArgs("notify") }],
  );
  const [mode, setMode] = useState<"builder" | "yaml">("builder");
  const [yamlText, setYamlText] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const validateTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // The schedule cron from the current picker state ("" = no schedule).
  const scheduleCron = (): string => {
    if (schedFreq === "none") return "";
    if (schedFreq === "custom") return schedRaw.trim();
    return buildCron(schedFreq, schedTime, schedDow);
  };

  // Assemble the current builder state into a workflow definition.
  const buildDef = (): WorkflowDef => ({
    description: description.trim(),
    trigger: {
      button: trgButton,
      clap: trgClap,
      hotkey: hotkey.trim() || null,
      voice_phrases: phrases,
      on_app: onApp.trim() || null,
      schedule: scheduleCron() || null,
    },
    steps: fromEditSteps(steps),
  });

  // Push a parsed definition back into the builder fields.
  const applyDef = (def: WorkflowDef) => {
    setDescription(def.description ?? "");
    setTrgButton(!!def.trigger?.button);
    setTrgClap(!!def.trigger?.clap);
    setHotkey(def.trigger?.hotkey ?? "");
    setPhrases(def.trigger?.voice_phrases ?? []);
    setOnApp(asAppString(def.trigger?.on_app));
    const sp = parseCron(def.trigger?.schedule ?? "");
    setSchedFreq(def.trigger?.schedule ? sp.freq : "none");
    setSchedTime(sp.time);
    setSchedDow(sp.dow);
    setSchedRaw(def.trigger?.schedule ?? "");
    setSteps(toEditSteps(def.steps || []));
  };

  const parseYaml = (text: string): WorkflowDef | null => {
    let parsed: unknown;
    try {
      parsed = yamlLoad(text);
    } catch (e) {
      setErrors([`YAML syntax: ${String(e)}`]);
      return null;
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      setErrors(["YAML must describe a workflow mapping"]);
      return null;
    }
    return parsed as WorkflowDef;
  };

  // Live semantic validation while editing raw YAML (debounced).
  useEffect(() => {
    if (mode !== "yaml") return;
    if (validateTimer.current) clearTimeout(validateTimer.current);
    validateTimer.current = setTimeout(() => {
      const def = parseYaml(yamlText);
      if (!def) return;
      api
        .validateWorkflow(def)
        .then((r) => setErrors(r.errors))
        .catch(() => {});
    }, 500);
    return () => {
      if (validateTimer.current) clearTimeout(validateTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [yamlText, mode]);

  const switchToYaml = () => {
    setYamlText(yamlDump(buildDef(), { sortKeys: false }));
    setErrors([]);
    setMode("yaml");
  };

  const switchToBuilder = () => {
    const def = parseYaml(yamlText);
    if (!def) return; // errors already shown
    applyDef(def);
    setErrors([]);
    setMode("builder");
  };

  const save = async () => {
    const def = mode === "yaml" ? parseYaml(yamlText) : buildDef();
    if (!def) return;
    setSaving(true);
    setErrors([]);
    try {
      const check = await api.validateWorkflow(def);
      if (!check.valid) {
        setErrors(check.errors);
        setSaving(false);
        return;
      }
      if (isNew) {
        await api.createWorkflow(wfName.trim(), def);
      } else {
        await api.updateWorkflow(wfName.trim(), def);
      }
      onClose(true);
    } catch (e) {
      setErrors([String(e)]);
      setSaving(false);
    }
  };

  // ─── step mutation helpers ────────────────────────────────────────
  const updateStep = (i: number, next: EditStep) =>
    setSteps((s) => s.map((st, idx) => (idx === i ? next : st)));
  const removeStep = (i: number) =>
    setSteps((s) => s.filter((_, idx) => idx !== i));
  const moveStep = (i: number, dir: -1 | 1) =>
    setSteps((s) => {
      const j = i + dir;
      if (j < 0 || j >= s.length) return s;
      const copy = [...s];
      [copy[i], copy[j]] = [copy[j], copy[i]];
      return copy;
    });
  const addStep = () =>
    setSteps((s) => [...s, { action: "notify", args: defaultArgs("notify") }]);

  const addPhrase = () => {
    const p = phraseInput.trim();
    if (p && !phrases.includes(p)) setPhrases((ps) => [...ps, p]);
    setPhraseInput("");
  };

  return (
    <Card
      title={isNew ? "NEW ROUTINE" : `EDIT · ${name}`}
      className="min-h-0 overflow-y-auto"
      right={
        <div className="flex gap-2">
          <Button
            variant="ghost"
            onClick={mode === "builder" ? switchToYaml : switchToBuilder}
          >
            {mode === "builder" ? "</> Edit YAML" : "▤ Builder"}
          </Button>
          <Button variant="ghost" onClick={() => onClose(false)}>
            Cancel
          </Button>
          <Button onClick={save} disabled={saving}>
            {saving ? "saving…" : "Save routine"}
          </Button>
        </div>
      }
    >
      {errors.length > 0 && (
        <ul className="mb-3 text-xs text-rose-300 bg-rose-500/10 border border-rose-500/30 rounded-lg px-3 py-2 list-disc list-inside">
          {errors.map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ul>
      )}

      {mode === "yaml" ? (
        <textarea
          value={yamlText}
          onChange={(e) => setYamlText(e.target.value)}
          spellCheck={false}
          className="w-full h-[60vh] bg-ink/80 border border-edge rounded-lg p-3 text-xs font-mono text-slate-100 outline-none focus:border-accent/60"
        />
      ) : (
        <div className="flex flex-col gap-4">
          {/* identity */}
          <div className="flex flex-col gap-2">
            <label className="text-[11px] tracking-wide text-slate-500">
              NAME
            </label>
            <Input
              value={wfName}
              disabled={!isNew}
              onChange={(e) => setWfName(e.target.value)}
              placeholder="study_setup"
            />
            <label className="text-[11px] tracking-wide text-slate-500 mt-1">
              DESCRIPTION
            </label>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What this routine does"
            />
          </div>

          {/* triggers */}
          <div className="flex flex-col gap-3 border border-edge/60 rounded-lg p-3">
            <span className="text-[11px] tracking-[0.16em] text-accent">
              TRIGGERS
            </span>
            <div className="flex gap-6">
              <Toggle checked={trgButton} onChange={setTrgButton} label="Dashboard button" />
              <Toggle checked={trgClap} onChange={setTrgClap} label="Two-clap" />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[11px] text-slate-500">
                Global hotkey (e.g. ctrl+alt+s — blank for none)
              </label>
              <Input
                value={hotkey}
                onChange={(e) => setHotkey(e.target.value)}
                placeholder="ctrl+alt+s"
                className="w-56"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[11px] text-slate-500">
                When this app opens (process or window name — blank for none)
              </label>
              <Input
                value={onApp}
                onChange={(e) => setOnApp(e.target.value)}
                placeholder="e.g. Code.exe, cursor, chrome"
                className="w-56"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[11px] text-slate-500">Voice phrases</label>
              <div className="flex gap-2">
                <Input
                  value={phraseInput}
                  onChange={(e) => setPhraseInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      addPhrase();
                    }
                  }}
                  placeholder="say a phrase, press Enter"
                  className="flex-1"
                />
                <Button variant="ghost" onClick={addPhrase}>
                  Add
                </Button>
              </div>
              {phrases.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mt-1">
                  {phrases.map((p) => (
                    <span
                      key={p}
                      className="text-[11px] bg-accent/10 border border-accent/30 text-accent rounded-full px-2 py-0.5"
                    >
                      {p}
                      <button
                        type="button"
                        onClick={() =>
                          setPhrases((ps) => ps.filter((x) => x !== p))
                        }
                        className="ml-1.5 text-slate-400 hover:text-rose-300"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              )}
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[11px] text-slate-500">
                Run automatically on a schedule
              </label>
              <div className="flex flex-wrap items-center gap-2">
                <Select
                  value={schedFreq}
                  onChange={(e) => setSchedFreq(e.target.value)}
                  className="w-44"
                >
                  <option value="none">No schedule</option>
                  <option value="daily">Every day</option>
                  <option value="weekdays">Every weekday</option>
                  <option value="weekly">Every week</option>
                  <option value="custom">Custom cron</option>
                </Select>
                {(schedFreq === "daily" ||
                  schedFreq === "weekdays" ||
                  schedFreq === "weekly") && (
                  <Input
                    type="time"
                    value={schedTime}
                    onChange={(e) => setSchedTime(e.target.value)}
                    className="w-32"
                  />
                )}
                {schedFreq === "weekly" && (
                  <Select
                    value={String(schedDow)}
                    onChange={(e) => setSchedDow(Number(e.target.value))}
                    className="w-32"
                  >
                    {WEEKDAYS.map((d, i) => (
                      <option key={d} value={i}>
                        {d}
                      </option>
                    ))}
                  </Select>
                )}
                {schedFreq === "custom" && (
                  <Input
                    value={schedRaw}
                    onChange={(e) => setSchedRaw(e.target.value)}
                    placeholder="0 8 * * *"
                    className="w-40"
                  />
                )}
              </div>
              {schedFreq !== "none" && (
                <span className="text-[10px] text-slate-500">
                  runs in your local time
                  {schedFreq !== "custom" &&
                    ` · cron: ${buildCron(schedFreq, schedTime, schedDow)}`}
                </span>
              )}
            </div>
          </div>

          {/* steps */}
          <div className="flex flex-col gap-2">
            <span className="text-[11px] tracking-[0.16em] text-accent">
              STEPS
            </span>
            {steps.map((step, i) => (
              <StepRow
                key={i}
                index={i}
                step={step}
                isFirst={i === 0}
                isLast={i === steps.length - 1}
                onChange={(next) => updateStep(i, next)}
                onRemove={() => removeStep(i)}
                onMove={(dir) => moveStep(i, dir)}
              />
            ))}
            <div>
              <Button variant="ghost" onClick={addStep}>
                + Add step
              </Button>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}

// ─── one step ─────────────────────────────────────────────────────

function StepRow({
  index,
  step,
  isFirst,
  isLast,
  onChange,
  onRemove,
  onMove,
}: {
  index: number;
  step: EditStep;
  isFirst: boolean;
  isLast: boolean;
  onChange: (next: EditStep) => void;
  onRemove: () => void;
  onMove: (dir: -1 | 1) => void;
}) {
  const setAction = (action: string) =>
    onChange({ action, args: defaultArgs(action) });
  const setArg = (key: string, value: unknown) =>
    onChange({ ...step, args: { ...step.args, [key]: value } });

  return (
    <div className="bg-ink/60 border border-edge/60 rounded-lg p-3 flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className="text-[10px] text-slate-500 w-6">#{index + 1}</span>
        <Select
          value={step.action}
          onChange={(e) => setAction(e.target.value)}
          className="flex-1"
        >
          {ACTIONS.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </Select>
        <button
          type="button"
          onClick={() => onMove(-1)}
          disabled={isFirst}
          className="text-slate-500 hover:text-accent disabled:opacity-30 px-1"
        >
          ↑
        </button>
        <button
          type="button"
          onClick={() => onMove(1)}
          disabled={isLast}
          className="text-slate-500 hover:text-accent disabled:opacity-30 px-1"
        >
          ↓
        </button>
        <button
          type="button"
          onClick={onRemove}
          className="text-slate-500 hover:text-rose-300 px-1"
        >
          ✕
        </button>
      </div>
      <StepArgs step={step} setArg={setArg} />
    </div>
  );
}

function StepArgs({
  step,
  setArg,
}: {
  step: EditStep;
  setArg: (key: string, value: unknown) => void;
}) {
  const a = step.args;

  if (step.action === "tabs.open_set") {
    const urls = Array.isArray(a.urls) ? (a.urls as string[]) : [""];
    return (
      <div className="flex flex-col gap-1.5">
        {urls.map((u, i) => (
          <div key={i} className="flex gap-2">
            <Input
              value={u}
              onChange={(e) => {
                const next = [...urls];
                next[i] = e.target.value;
                setArg("urls", next);
              }}
              placeholder="https://…"
              className="flex-1"
            />
            <button
              type="button"
              onClick={() => setArg("urls", urls.filter((_, j) => j !== i))}
              className="text-slate-500 hover:text-rose-300 px-2"
            >
              ✕
            </button>
          </div>
        ))}
        <Button variant="ghost" onClick={() => setArg("urls", [...urls, ""])}>
          + Add URL
        </Button>
      </div>
    );
  }

  if (step.action === "apps.launch") {
    return (
      <AppPicker
        appId={(a.app_id as string) || ""}
        name={(a.name as string) || ""}
        onPick={(appId, name) => {
          setArg("app_id", appId);
          setArg("name", name);
        }}
      />
    );
  }

  if (step.action === "agent.run") {
    return (
      <Select
        value={(a.agent_id as string) || "synthesizer"}
        onChange={(e) => setArg("agent_id", e.target.value)}
      >
        {AGENTS.map((g) => (
          <option key={g} value={g}>
            {g}
          </option>
        ))}
      </Select>
    );
  }

  if (step.action === "classroom.check" || step.action === "calendar.check") {
    return (
      <div className="flex items-center gap-2">
        <label className="text-xs text-slate-400">days ahead</label>
        <Input
          type="number"
          value={String(a.days_ahead ?? 7)}
          onChange={(e) => setArg("days_ahead", Number(e.target.value) || 0)}
          className="w-24"
        />
      </div>
    );
  }

  if (step.action === "email.check") {
    return (
      <div className="flex items-center gap-2">
        <label className="text-xs text-slate-400">max messages</label>
        <Input
          type="number"
          value={String(a.max_messages ?? 15)}
          onChange={(e) => setArg("max_messages", Number(e.target.value) || 0)}
          className="w-24"
        />
      </div>
    );
  }

  if (step.action === "brief.compose") {
    return (
      <p className="text-xs text-slate-500">
        Assembles the briefing — no arguments.
      </p>
    );
  }

  if (step.action === "speak") {
    return (
      <Input
        value={(a.text as string) || ""}
        onChange={(e) => setArg("text", e.target.value)}
        placeholder="What Jarvis should say"
      />
    );
  }

  if (step.action === "news.open") {
    return (
      <div className="flex items-center gap-2">
        <label className="text-xs text-slate-400">articles to open</label>
        <Input
          type="number"
          value={String(a.count ?? 5)}
          onChange={(e) => setArg("count", Number(e.target.value) || 1)}
          className="w-24"
        />
      </div>
    );
  }

  if (step.action === "news.email_digest") {
    return (
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-400">news window (hours)</label>
          <Input
            type="number"
            value={String(a.window_hours ?? 48)}
            onChange={(e) => setArg("window_hours", Number(e.target.value) || 24)}
            className="w-24"
          />
        </div>
        <p className="text-[11px] text-slate-500">
          Summarizes recent tech news into a PDF and emails it. Leave the
          window at 48 for today + yesterday.
        </p>
      </div>
    );
  }

  // notify
  return (
    <div className="flex flex-col gap-1.5">
      <Input
        value={(a.title as string) || ""}
        onChange={(e) => setArg("title", e.target.value)}
        placeholder="Notification title"
      />
      <Input
        value={(a.body as string) || ""}
        onChange={(e) => setArg("body", e.target.value)}
        placeholder="Notification body"
      />
    </div>
  );
}
