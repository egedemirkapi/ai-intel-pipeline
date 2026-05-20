"use client";

import { useState } from "react";
import Link from "next/link";
import AgentFleetPanel from "@/components/AgentFleetPanel";
import ChatBox from "@/components/ChatBox";
import IdeaBoard from "@/components/IdeaBoard";
import IntelFeedPanel from "@/components/IntelFeedPanel";
import TrendsPanel from "@/components/TrendsPanel";
import RoutineButtons from "@/components/RoutineButtons";
import StatusDot from "@/components/ui/StatusDot";
import { useEvents } from "@/lib/useEvents";

export default function Dashboard() {
  // `pulse` increments on every fleet event. Panels that care
  // (fleet, ideas) re-fetch when it changes — live updates without polling.
  const [pulse, setPulse] = useState(0);
  const [lastEvent, setLastEvent] = useState<string>("");

  const { connected } = useEvents((e) => {
    setPulse((p) => p + 1);
    setLastEvent(
      `${e.type}${e.agent_id ? ` · ${e.agent_id}` : ""}${
        e.summary ? ` — ${e.summary}` : ""
      }`,
    );
  });

  return (
    <main className="h-screen flex flex-col p-4 gap-4">
      {/* Header */}
      <header className="flex items-center justify-between shrink-0">
        <div className="flex items-baseline gap-3">
          <h1 className="text-xl font-bold tracking-[0.18em] text-glow glow-cyan">
            JARVIS
          </h1>
          <span className="text-xs text-slate-500">
            mission control over the agent fleet
          </span>
        </div>
        <div className="flex items-center gap-4">
          <Link
            href="/routines"
            className="text-xs text-slate-300 hover:text-accent border border-edge hover:border-accent/50 rounded-lg px-3 py-1.5 transition-colors"
          >
            Routines
          </Link>
          <div className="flex items-center gap-2">
            <StatusDot tone={connected ? "online" : "error"} />
            <span className="text-xs text-slate-500">
              {connected ? "live" : "reconnecting…"}
            </span>
          </div>
        </div>
      </header>

      {lastEvent && (
        <div className="shrink-0 text-[11px] text-glow/70 -mt-2">
          ▸ {lastEvent}
        </div>
      )}

      {/* Quick-run routine buttons */}
      <RoutineButtons pulse={pulse} />

      {/* Body: left column = fleet+trends, middle = ideas+intel, right = chat */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-3 gap-4 min-h-0">
        <div className="flex flex-col gap-4 min-h-0">
          <AgentFleetPanel pulse={pulse} />
          <div className="flex-1 min-h-0">
            <TrendsPanel />
          </div>
        </div>
        <div className="flex flex-col gap-4 min-h-0">
          <div className="flex-1 min-h-0">
            <IdeaBoard pulse={pulse} />
          </div>
          <div className="flex-1 min-h-0">
            <IntelFeedPanel />
          </div>
        </div>
        <div className="min-h-0">
          <ChatBox />
        </div>
      </div>
    </main>
  );
}
