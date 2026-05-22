"use client";

import { useState } from "react";
import Link from "next/link";
import AgentFleetPanel from "@/components/AgentFleetPanel";
import ChatBox from "@/components/ChatBox";
import IdeaBoard from "@/components/IdeaBoard";
import IntelFeedPanel from "@/components/IntelFeedPanel";
import TrendsPanel from "@/components/TrendsPanel";
import BriefingPanel from "@/components/BriefingPanel";
import CollectorHeartbeat from "@/components/CollectorHeartbeat";
import RoutineButtons from "@/components/RoutineButtons";
import JarvisOrb, { OrbState } from "@/components/JarvisOrb";
import StatusDot from "@/components/ui/StatusDot";
import { useEvents } from "@/lib/useEvents";

// Mission Control — three zones around the living Jarvis orb. The right
// zone leads: the Briefing hero answers "what should I act on now"; the
// left zone carries the fleet and what it produced; the centre is the
// orb + conversation. Panels reveal in a short staggered cascade.
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
      <header className="flex items-center justify-between shrink-0 animate-fade-rise">
        <div className="flex items-baseline gap-3">
          <h1 className="font-mono text-lg font-semibold tracking-[0.2em] text-primary glow-cyan">
            JARVIS<span className="text-accent">.</span>
          </h1>
          <span className="label text-muted">mission control</span>
        </div>
        <div className="flex items-center gap-3">
          <CollectorHeartbeat pulse={pulse} />
          <Link
            href="/routines"
            className="label text-muted hover:text-accent border border-edge hover:border-accent/50 rounded-lg px-3 py-2 transition-colors"
          >
            Routines
          </Link>
          <div className="flex items-center gap-2 border border-edge rounded-lg px-3 py-2">
            <StatusDot tone={connected ? "online" : "error"} />
            <span className="label text-muted">
              {connected ? "live" : "reconnecting"}
            </span>
          </div>
        </div>
      </header>

      {/* Quick-run routine buttons */}
      <RoutineButtons pulse={pulse} />

      {/* Body — three zones; the right zone (Briefing) carries the weight */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-[18rem_1fr_24rem] gap-4 min-h-0">
        {/* Left — the fleet + what it produced */}
        <div
          className="flex flex-col gap-3 min-h-0 overflow-y-auto animate-fade-rise"
          style={{ animationDelay: "60ms" }}
        >
          <AgentFleetPanel pulse={pulse} />
          <div className="flex-1 min-h-0">
            <IdeaBoard pulse={pulse} />
          </div>
          <div className="flex-1 min-h-0">
            <TrendsPanel pulse={pulse} />
          </div>
        </div>

        {/* Centre — the living orb + the conversation */}
        <div
          className="flex flex-col items-center min-h-0 gap-3 animate-fade-rise"
          style={{ animationDelay: "120ms" }}
        >
          <div className="shrink-0 pt-2">
            <JarvisOrb state={jarvisState} />
          </div>
          {lastEvent && (
            <div className="shrink-0 font-mono text-2xs text-glow/55 truncate max-w-full">
              ▸ {lastEvent}
            </div>
          )}
          <div className="flex-1 min-h-0 w-full">
            <ChatBox onState={setJarvisState} />
          </div>
        </div>

        {/* Right — what Jarvis knows: the Briefing hero + live news */}
        <div
          className="flex flex-col gap-3 min-h-0 overflow-y-auto animate-fade-rise"
          style={{ animationDelay: "180ms" }}
        >
          <BriefingPanel />
          <div className="flex-1 min-h-0">
            <IntelFeedPanel pulse={pulse} />
          </div>
        </div>
      </div>
    </main>
  );
}
