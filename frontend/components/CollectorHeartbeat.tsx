"use client";

import { useCallback, useEffect, useState } from "react";
import { api, CollectorStatus } from "@/lib/api";
import StatusDot from "@/components/ui/StatusDot";

// A live heartbeat for the 24/7 AI-news collector. The collector runs
// hidden in the background, so without this the user has no way to see
// it working — and assumes it is dead. This makes it undeniably visible:
// a green dot + a count that ticks up every cycle.
export default function CollectorHeartbeat({ pulse }: { pulse: number }) {
  const [s, setS] = useState<CollectorStatus | null>(null);

  const load = useCallback(() => {
    api.collectorStatus().then(setS).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, [load]);

  // Re-check the moment new intel lands (the /events/intel pulse).
  useEffect(() => {
    if (pulse > 0) load();
  }, [pulse, load]);

  if (!s) return null;
  const mins = s.minutes_since_last;
  // The collector cycles every 5 min; >20 min quiet means it stalled.
  const stale = mins == null || mins > 20;
  const ago =
    mins == null
      ? "no data yet"
      : mins < 1
        ? "just now"
        : `${Math.round(mins)}m ago`;

  return (
    <div
      className="flex items-center gap-2"
      title={`${s.total_items.toLocaleString()} items in the vault · ${s.last_24h} today`}
    >
      <StatusDot tone={stale ? "error" : "online"} />
      <span className="text-xs text-slate-500">
        collector · {s.last_2h} in 2h · {ago}
      </span>
    </div>
  );
}
