"use client";

// The living Jarvis orb — a glowing bioluminescent presence that
// animates by state. It breathes when idle, ripples while listening,
// shimmers while thinking, and wobbles while speaking. Pure CSS
// transforms (see globals.css .orb-*) — cheap, and reduced-motion aware.

export type OrbState = "idle" | "listening" | "thinking" | "speaking";

const CAPTION: Record<OrbState, string> = {
  idle: "online",
  listening: "listening",
  thinking: "thinking",
  speaking: "speaking",
};

export default function JarvisOrb({
  state = "idle",
  size = 260,
}: {
  state?: OrbState;
  size?: number;
}) {
  return (
    <div className="flex flex-col items-center gap-3 select-none">
      <div
        className="relative"
        style={{ width: size, height: size }}
        aria-label={`Jarvis is ${CAPTION[state]}`}
        role="img"
      >
        <div className={`orb-ring orb-ring-1 orb-${state}`} />
        <div className={`orb-ring orb-ring-2 orb-${state}`} />
        <div className={`orb-core orb-${state}`} />
      </div>
      <div className="flex items-center gap-2">
        <span
          className={`h-1.5 w-1.5 rounded-full ${
            state === "idle" ? "bg-glow/60" : "bg-accent animate-pulse-glow"
          }`}
        />
        <span className="text-[11px] tracking-[0.34em] uppercase text-accent/80">
          {CAPTION[state]}
        </span>
      </div>
    </div>
  );
}
