"use client";

import { useCallback, useEffect, useState } from "react";
import { api, Trend } from "@/lib/api";
import Card from "@/components/ui/Card";
import TrendFreshness from "@/components/TrendFreshness";

// Momentum → semantic colour. A rising trend reads as positive signal,
// a slowing one as a warning — instead of everything painted in accent.
const MOMENTUM_STYLE: Record<string, string> = {
  rising_fast: "text-accent glow-aqua",
  steady_rising: "text-success",
  stable: "text-muted",
  slowing: "text-warn",
};

export default function TrendsPanel({ pulse = 0 }: { pulse?: number }) {
  const [trends, setTrends] = useState<Trend[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .trends()
      .then((d) => {
        setTrends(d);
        setErr(null);
      })
      .catch((e) => setErr(String(e)));
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [load]);
  useEffect(() => {
    if (pulse > 0) load();
  }, [pulse, load]);

  return (
    <Card
      title="EMERGING TRENDS"
      className="min-h-0 h-full"
      right={<TrendFreshness pulse={pulse} />}
    >
      {err && <p className="text-error text-xs">{err}</p>}
      {!err && trends.length === 0 && (
        <p className="text-muted text-xs">No trends yet — run the synthesizer.</p>
      )}
      <div className="flex flex-col gap-2 overflow-y-auto">
        {trends.map((t) => (
          <div
            key={t.id}
            className="bg-surface/50 border border-edge rounded-lg px-3 py-2"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium text-primary">
                {t.cluster_label}
              </span>
              <span
                className={`text-2xs uppercase shrink-0 ${
                  MOMENTUM_STYLE[t.momentum ?? "stable"] ?? "text-muted"
                }`}
              >
                {(t.momentum ?? "").replace(/_/g, " ")}
              </span>
            </div>
            {t.new_capability && (
              <p className="text-xs text-secondary mt-1 line-clamp-2">
                {t.new_capability}
              </p>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}
