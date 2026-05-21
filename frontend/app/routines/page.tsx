"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, WorkflowDef, WorkflowSummary } from "@/lib/api";
import { cronLabel } from "@/lib/cron";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import RoutineEditor from "@/components/RoutineEditor";

type EditTarget = {
  name: string;
  initial: WorkflowDef | null;
  isNew: boolean;
} | null;

function triggerBadges(w: WorkflowSummary): string[] {
  const t = w.trigger || {};
  const out: string[] = [];
  if (t.schedule) out.push(`⏰ ${cronLabel(t.schedule)}`);
  if (t.button) out.push("button");
  if (t.clap) out.push("clap");
  if (t.hotkey) out.push(`⌨ ${t.hotkey}`);
  if (t.voice_phrases && t.voice_phrases.length) out.push("voice");
  if (t.on_app) out.push("on-app");
  return out;
}

export default function RoutinesPage() {
  const [routines, setRoutines] = useState<WorkflowSummary[]>([]);
  const [err, setErr] = useState("");
  const [editing, setEditing] = useState<EditTarget>(null);
  const [busy, setBusy] = useState("");
  const [flash, setFlash] = useState("");

  const load = useCallback(() => {
    api
      .workflows()
      .then((d) => {
        setRoutines(d);
        setErr("");
      })
      .catch((e) => setErr(String(e)));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const openEdit = async (name: string) => {
    try {
      const wf = await api.workflow(name);
      setEditing({ name, initial: wf.definition, isNew: false });
    } catch (e) {
      setErr(String(e));
    }
  };

  const run = async (name: string) => {
    setBusy(name);
    setFlash("");
    try {
      const res = await api.runWorkflow(name);
      setFlash(`${name} — ${res.ok ? "done" : "ran with issues"}`);
    } catch (e) {
      setFlash(`${name} — ${String(e)}`);
    } finally {
      setBusy("");
      setTimeout(() => setFlash(""), 4000);
    }
  };

  const del = async (w: WorkflowSummary) => {
    const verb = w.is_overridden ? "Reset" : "Delete";
    if (!window.confirm(`${verb} routine "${w.name}"?`)) return;
    setBusy(w.name);
    try {
      await api.deleteWorkflow(w.name);
      load();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy("");
    }
  };

  if (editing) {
    return (
      <main className="min-h-screen p-4">
        <RoutineEditor
          name={editing.name}
          initial={editing.initial}
          isNew={editing.isNew}
          onClose={(saved) => {
            setEditing(null);
            if (saved) load();
          }}
        />
      </main>
    );
  }

  return (
    <main className="min-h-screen flex flex-col p-4 gap-4">
      <header className="flex items-center justify-between shrink-0">
        <div className="flex items-baseline gap-3">
          <h1 className="text-xl font-bold tracking-[0.18em] text-glow glow-cyan">
            ROUTINES
          </h1>
          <span className="text-xs text-slate-500">
            triggers · steps · automations
          </span>
        </div>
        <div className="flex items-center gap-3">
          <Button onClick={() => setEditing({ name: "", initial: null, isNew: true })}>
            + New routine
          </Button>
          <Link
            href="/"
            className="text-xs text-slate-300 hover:text-accent border border-edge hover:border-accent/50 rounded-lg px-3 py-1.5 transition-colors"
          >
            ← Dashboard
          </Link>
        </div>
      </header>

      {err && <p className="text-rose-400 text-xs">{err}</p>}
      {flash && <p className="text-glow/70 text-xs">▸ {flash}</p>}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {routines.map((w) => (
          <Card key={w.name} className="glass-hover">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-slate-100">
                    {w.name}
                  </span>
                  {w.is_builtin && (
                    <span className="text-[9px] uppercase tracking-wide text-slate-500 border border-edge rounded px-1">
                      {w.is_overridden ? "builtin · edited" : "builtin"}
                    </span>
                  )}
                  {w.name === "clap_default" && (
                    <span className="text-[9px] uppercase tracking-wide text-glow border border-glow/40 rounded px-1">
                      wake-up · edit the tabs here
                    </span>
                  )}
                </div>
                <p className="text-xs text-slate-400 mt-0.5">
                  {w.description || "—"}
                </p>
                <div className="flex flex-wrap gap-1.5 mt-2">
                  <span className="text-[10px] text-slate-500">
                    {w.step_count} step{w.step_count === 1 ? "" : "s"}
                  </span>
                  {triggerBadges(w).map((b) => (
                    <span
                      key={b}
                      className="text-[10px] text-accent bg-accent/10 border border-accent/25 rounded-full px-2"
                    >
                      {b}
                    </span>
                  ))}
                </div>
              </div>
            </div>
            <div className="flex gap-2 mt-3">
              <Button
                variant="ghost"
                disabled={busy === w.name}
                onClick={() => run(w.name)}
              >
                {busy === w.name ? "running…" : "Run"}
              </Button>
              <Button variant="ghost" onClick={() => openEdit(w.name)}>
                Edit
              </Button>
              {(!w.is_builtin || w.is_overridden) && (
                <Button variant="danger" onClick={() => del(w)}>
                  {w.is_overridden ? "Reset" : "Delete"}
                </Button>
              )}
            </div>
          </Card>
        ))}
      </div>

      {routines.length === 0 && !err && (
        <p className="text-slate-500 text-sm">
          No routines yet — create one with “New routine”.
        </p>
      )}
    </main>
  );
}
