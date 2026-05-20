"use client";

import { useState } from "react";
import Link from "next/link";
import AgentFleetPanel from "@/components/AgentFleetPanel";
import ChatBox from "@/components/ChatBox";
import IdeaBoard from "@/components/IdeaBoard";
import IntelFeedPanel from "@/components/IntelFeedPanel";
import TrendsPanel from "@/components/TrendsPanel";
import BriefingPanel from "@/components/BriefingPanel";
import RoutineButtons from "@/components/RoutineButtons";
import JarvisOrb, { OrbState } from "@/components/JarvisOrb";
import StatusDot from "@/components/ui/StatusDot";
import { useEvents } from "@/lib/useEvents";

// Mission Control — the Jarvis orb is the centerpiece; the live panels
// orbit it. The orb's animation is driven by Jarvis's actual state:
// text chat (ChatBox) and the voice tray (voice_state events) both feed it.
export default function Dashboard() {
  // `pulse` increments on every fleet event — panels re-fetch on it.
  const [pulse, setPulse] = useState(0);
  const [lastEvent, setLastEvent] = useState<string>("");
  const [jarvisState, setJarvisState] = useState<OrbState>("idle");

  const { connected } = useEvents((e) => {
    setPulse((p) => p + 1);
    if (e.type === "voice_state") {
      const s = (e.payload?.state as OrbState) || "idle";
      if (["idle", "listening", "thinking", "speaking"].includes(s)) {
        setJarvisState(s);
      }
    }
    setLastEvent(
      `${e.type}${e.agent_id ? ` · ${e.agent_id}` : ""}${
        e.summary ? ` — ${e.summary}` : ""
      }`,
    );
  });

  return (
    <main className="h-screen flex flex-col p-4 gap-3 overflow-hidden">
      {/* Header */}
      <header className="flex items-center justify-between shrink-0">
        <div className="flex items-baseline gap-3">
          <h1 className="text-xl font-bold tracking-[0.34em] text-glow glow-cyan">
            JARVIS
          </h1>
          <span className="text-xs text-slate-500">mission control</span>
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

      {/* Quick-run routine buttons */}
      <RoutineButtons pulse={pulse} />

      {/* Body — orb at the center, panels orbiting */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-[19rem_1fr_21rem] gap-4 min-h-0">
        {/* Left — the fleet + what it produced */}
        <div className="flex flex-col gap-3 min-h-0 overflow-y-auto">
          <AgentFleetPanel pulse={pulse} />
          <div className="flex-1 min-h-0">
            <IdeaBoard pulse={pulse} />
          </div>
          <div className="flex-1 min-h-0">
            <TrendsPanel />
          </div>
        </div>

        {/* Center — the living orb + the conversation */}
        <div className="flex flex-col items-center min-h-0 gap-3">
          <div className="shrink-0 pt-3">
            <JarvisOrb state={jarvisState} />
          </div>
          {lastEvent && (
            <div className="shrink-0 text-[11px] text-glow/55 truncate max-w-full">
              ▸ {lastEvent}
            </div>
          )}
          <div className="flex-1 min-h-0 w-full">
            <ChatBox onState={setJarvisState} />
          </div>
        </div>

        {/* Right — what Jarvis knows: briefing + live news */}
        <div className="flex flex-col gap-3 min-h-0 overflow-y-auto">
          <BriefingPanel />
          <div className="flex-1 min-h-0">
            <IntelFeedPanel pulse={pulse} />
          </div>
        </div>
      </div>
    </main>
  );
}
