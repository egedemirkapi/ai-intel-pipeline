"use client";

import { useCallback, useEffect, useState } from "react";
import { api, AgentStatus } from "@/lib/api";
import Card from "@/components/ui/Card";
import StatusDot from "@/components/ui/StatusDot";

type Tone = "online" | "busy" | "error" | "idle";
const STATUS_TONE: Record<string, Tone> = {
  completed: "online",
  running: "busy",
  failed: "error",
  pending: "idle",
};

export default function AgentFleetPanel({ pulse }: { pulse: number }) {
  const [agents, setAgents] = useState<Record<string, AgentStatus>>({});
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .agentsStatus()
      .then((d) => {
        setAgents(d);
        setErr(null);
      })
      .catch((e) => setErr(String(e)));
  }, []);

  // Reload on mount, every 20s, and whenever a fleet event pulses.
  useEffect(() => {
    load();
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, [load]);
  useEffect(() => {
    if (pulse > 0) load();
  }, [pulse, load]);

  const names = Object.keys(agents).sort();

  return (
    <Card title="AGENT FLEET">
      {err && <p className="text-rose-400 text-xs">{err}</p>}
      {!err && names.length === 0 && (
        <p className="text-slate-500 text-xs">No agent runs yet.</p>
      )}
      <div className="flex flex-col gap-2 overflow-y-auto">
        {names.map((name) => {
          const a = agents[name];
          const st = a.latest?.status ?? "pending";
          return (
            <div
              key={name}
              className="flex items-start gap-3 bg-ink/60 border border-edge/50 rounded-lg px-3 py-2"
            >
              <span className="mt-1">
                <StatusDot tone={STATUS_TONE[st] ?? "idle"} title={st} />
              </span>
              <div className="min-w-0">
                <div className="flex items-baseline gap-2">
                  <span className="text-sm font-medium text-slate-100">
                    {name}
                  </span>
                  <span className="text-[10px] text-slate-500">
                    {a.total_runs} runs
                  </span>
                </div>
                <p className="text-xs text-slate-400 truncate">
                  {a.latest?.summary ?? "—"}
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
