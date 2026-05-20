"use client";

import { useEffect, useState } from "react";
import { api, Trend } from "@/lib/api";
import Card from "@/components/ui/Card";

const MOMENTUM_STYLE: Record<string, string> = {
  rising_fast: "text-accent glow-aqua",
  steady_rising: "text-glow",
  stable: "text-slate-400",
  slowing: "text-rose-300/70",
};

export default function TrendsPanel() {
  const [trends, setTrends] = useState<Trend[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const load = () =>
      api
        .trends()
        .then((d) => {
          setTrends(d);
          setErr(null);
        })
        .catch((e) => setErr(String(e)));
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, []);

  return (
    <Card title="EMERGING TRENDS" className="min-h-0 h-full">
      {err && <p className="text-rose-400 text-xs">{err}</p>}
      {!err && trends.length === 0 && (
        <p className="text-slate-500 text-xs">No trends — run the synthesizer.</p>
      )}
      <div className="flex flex-col gap-2 overflow-y-auto">
        {trends.map((t) => (
          <div
            key={t.id}
            className="bg-ink/60 border border-edge/50 rounded-lg px-3 py-2"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-medium text-slate-100">
                {t.cluster_label}
              </span>
              <span
                className={`text-[10px] ${
                  MOMENTUM_STYLE[t.momentum ?? "stable"] ?? "text-slate-400"
                }`}
              >
                {t.momentum}
              </span>
            </div>
            {t.new_capability && (
              <p className="text-[11px] text-slate-400 mt-1 line-clamp-2">
                {t.new_capability}
              </p>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}
