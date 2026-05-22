"use client";

import { useCallback, useEffect, useState } from "react";
import { api, WorkflowSummary } from "@/lib/api";
import Button from "@/components/ui/Button";

// Dashboard quick-run strip — one button per workflow with trigger.button.
export default function RoutineButtons({ pulse }: { pulse: number }) {
  const [routines, setRoutines] = useState<WorkflowSummary[]>([]);
  const [running, setRunning] = useState<string | null>(null);
  const [flash, setFlash] = useState<string>("");

  const load = useCallback(() => {
    api
      .workflows()
      .then((all) => setRoutines(all.filter((w) => w.trigger?.button)))
      .catch(() => {});
  }, []);

  useEffect(() => {
    load();
  }, [load]);
  // A workflows_changed event bumps pulse — refetch so new routines appear.
  useEffect(() => {
    if (pulse > 0) load();
  }, [pulse, load]);

  const run = async (name: string) => {
    setRunning(name);
    setFlash("");
    try {
      const res = await api.runWorkflow(name);
      setFlash(`${name.replace(/_/g, " ")} — ${res.ok ? "done" : "ran with issues"}`);
    } catch (e) {
      setFlash(`${name.replace(/_/g, " ")} — ${String(e)}`);
    } finally {
      setRunning(null);
      setTimeout(() => setFlash(""), 4000);
    }
  };

  if (routines.length === 0) return null;

  return (
    <div className="shrink-0 flex items-center gap-2 flex-wrap">
      <p className="label text-glow/60">ROUTINES</p>
      {routines.map((r) => (
        <Button
          key={r.name}
          variant="ghost"
          disabled={running === r.name}
          onClick={() => run(r.name)}
          title={r.description}
        >
          {running === r.name ? "running…" : r.name.replace(/_/g, " ")}
        </Button>
      ))}
      {flash && <span className="text-[11px] text-glow/70">▸ {flash}</span>}
    </div>
  );
}
