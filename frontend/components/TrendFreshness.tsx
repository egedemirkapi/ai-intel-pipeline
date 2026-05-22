"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

// Surfaces when the synthesizer last ran. The idea-finder reasons about
// TrendSynthesis rows; if nothing refreshes them it silently degrades to
// stale data. This badge makes that visible — read from the synthesizer's
// latest run in /agents/status.
const STALE_AFTER_H = 18;

function hoursSince(iso: string | null): number | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  return (Date.now() - t) / 3_600_000;
}

export default function TrendFreshness({ pulse = 0 }: { pulse?: number }) {
  const [age, setAge] = useState<number | null>(null);
  const [known, setKnown] = useState(false);

  const load = useCallback(() => {
    api
      .agentsStatus()
      .then((d) => {
        const latest = d["synthesizer"]?.latest;
        setAge(hoursSince(latest?.finished_at ?? latest?.started_at ?? null));
        setKnown(true);
      })
      .catch(() => setKnown(true));
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 120_000);
    return () => clearInterval(t);
  }, [load]);
  useEffect(() => {
    if (pulse > 0) load();
  }, [pulse, load]);

  if (!known) return null;

  if (age === null) {
    return (
      <span className="label text-warn" title="The synthesizer has never run">
        ◴ never run
      </span>
    );
  }

  const stale = age >= STALE_AFTER_H;
  const text =
    age < 1
      ? "just now"
      : age < 24
        ? `${Math.round(age)}h ${stale ? "old" : "ago"}`
        : `${Math.round(age / 24)}d old`;

  return (
    <span
      className={`label ${stale ? "text-warn" : "text-muted"}`}
      title={
        stale
          ? `Trends are ${Math.round(age)}h old — the idea-finder is reasoning on stale data. Run daily_trend_refresh.`
          : `Trend synthesis is current (${Math.round(age)}h old).`
      }
    >
      {stale ? "⚠ " : "● "}
      {text}
    </span>
  );
}
