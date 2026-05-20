"use client";

import { useCallback, useEffect, useState } from "react";
import { api, Idea } from "@/lib/api";
import Card from "@/components/ui/Card";

const VERDICT_STYLE: Record<string, string> = {
  escalated: "border-accent/55 text-accent",
  needs_work: "border-amber-400/55 text-amber-300",
  borderline: "border-glow/50 text-glow",
  killed: "border-rose-500/35 text-rose-300/70",
  proposed: "border-edge text-slate-300",
};

export default function IdeaBoard({ pulse }: { pulse: number }) {
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .ideas()
      .then((d) => {
        setIdeas(d);
        setErr(null);
      })
      .catch((e) => setErr(String(e)));
  }, []);

  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (pulse > 0) load();
  }, [pulse, load]);

  // Show the interesting ones first: escalated, needs_work, borderline.
  const rank: Record<string, number> = {
    escalated: 0,
    needs_work: 1,
    borderline: 2,
    proposed: 3,
    killed: 4,
  };
  const sorted = [...ideas].sort(
    (a, b) => (rank[a.status] ?? 9) - (rank[b.status] ?? 9),
  );

  return (
    <Card title="IDEA BOARD" className="min-h-0 h-full">
      {err && <p className="text-rose-400 text-xs">{err}</p>}
      {!err && ideas.length === 0 && (
        <p className="text-slate-500 text-xs">No ideas yet — run the proposer.</p>
      )}
      <div className="flex flex-col gap-2 overflow-y-auto">
        {sorted.map((idea) => {
          const v = idea.evaluator_verdict ?? idea.status;
          return (
            <div
              key={idea.id}
              className={`rounded-lg border bg-ink/60 px-3 py-2 ${
                VERDICT_STYLE[v] ?? "border-edge text-slate-300"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] uppercase tracking-wide">
                  #{idea.id} · {v}
                </span>
                <span className="text-[10px]">
                  {idea.evaluator_score != null
                    ? `${idea.evaluator_score}/100`
                    : "—"}
                </span>
              </div>
              <p className="text-xs text-slate-200 mt-0.5 line-clamp-3">
                {idea.idea_text}
              </p>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
