"use client";

import { useCallback, useEffect, useState } from "react";
import { api, CollectorStatus, IntelItem } from "@/lib/api";
import Card from "@/components/ui/Card";
import StatusDot from "@/components/ui/StatusDot";

function ago(minutes: number | null): string {
  if (minutes == null) return "never";
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const h = Math.floor(minutes / 60);
  return `${h}h ${minutes % 60}m ago`;
}

export default function IntelFeedPanel({ pulse = 0 }: { pulse?: number }) {
  const [items, setItems] = useState<IntelItem[]>([]);
  const [stats, setStats] = useState<CollectorStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .intel(24)
      .then((d) => {
        setItems(d);
        setErr(null);
      })
      .catch((e) => setErr(String(e)));
    api.collectorStatus().then(setStats).catch(() => {});
  }, []);

  // Mount + a slow safety poll.
  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [load]);

  // Live: refetch the instant a fleet event pulses (an intel_collected
  // event fires here within ~1s of the collector ingesting news).
  useEffect(() => {
    if (pulse > 0) load();
  }, [pulse, load]);

  // The collector runs every 2h via Task Scheduler. Flag "stale" if the
  // last collection was over 3h ago — means the scheduler/daemon may
  // not be running.
  const stale =
    stats?.minutes_since_last != null && stats.minutes_since_last > 180;

  return (
    <Card
      title="INTEL FEED"
      className="min-h-0 h-full"
      right={
        <StatusDot
          tone={stale ? "busy" : "online"}
          title={stale ? "collector idle >3h" : "collector healthy"}
        />
      }
    >
      {stats ? (
        <p className="text-[10px] text-slate-500 mb-3">
          {stats.last_24h.toLocaleString()} collected in 24h ·{" "}
          {stats.total_items.toLocaleString()} total · last run{" "}
          {ago(stats.minutes_since_last)}
        </p>
      ) : (
        <p className="text-[10px] text-slate-600 mb-3">loading stats…</p>
      )}
      {err && <p className="text-rose-400 text-xs">{err}</p>}
      <div className="flex flex-col gap-1.5 overflow-y-auto">
        {items.map((it) => (
          <a
            key={it.id}
            href={it.url}
            target="_blank"
            rel="noreferrer"
            className="block bg-ink/60 border border-edge/40 hover:border-glow/30 rounded-lg px-3 py-2 transition-colors"
          >
            <div className="flex items-center gap-2">
              <span className="text-[10px] uppercase text-glow/80 shrink-0">
                {it.source}
              </span>
              {it.ai_relevance != null && (
                <span className="text-[10px] text-slate-500">
                  {(it.ai_relevance * 100).toFixed(0)}%
                </span>
              )}
            </div>
            <p className="text-xs text-slate-200 line-clamp-2">{it.title}</p>
          </a>
        ))}
      </div>
    </Card>
  );
}
