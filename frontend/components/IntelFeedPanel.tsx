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
        <p className="text-2xs font-mono text-muted mb-3">
          {stats.last_24h.toLocaleString()} collected in 24h ·{" "}
          {stats.total_items.toLocaleString()} total · last run{" "}
          {ago(stats.minutes_since_last)}
        </p>
      ) : (
        <p className="text-2xs font-mono text-muted mb-3">loading stats…</p>
      )}
      {err && <p className="text-error text-xs mb-2">{err}</p>}
      <div className="flex flex-col gap-1.5 overflow-y-auto">
        {items.length === 0 && !err && (
          <div className="bg-surface/40 border border-dashed border-edge rounded-lg px-3 py-4 text-center">
            <p className="text-secondary text-sm">No intel items yet — collector may still be warming up.</p>
          </div>
        )}
        {items.map((it) => (
          <a
            key={it.id}
            href={it.url}
            target="_blank"
            rel="noreferrer"
            className="block bg-surface/50 border border-edge hover:border-accent/45 rounded-lg px-3 py-2 transition-colors"
          >
            <div className="flex items-center gap-2">
              <span className="label text-glow/70 shrink-0">
                {it.source}
              </span>
              {it.ai_relevance != null && (
                <span className="text-2xs font-mono text-muted">
                  {(it.ai_relevance * 100).toFixed(0)}%
                </span>
              )}
            </div>
            <p className="text-xs text-secondary line-clamp-2">{it.title}</p>
          </a>
        ))}
      </div>
    </Card>
  );
}
