"use client";

import { useCallback, useEffect, useState } from "react";
import { api, Idea } from "@/lib/api";
import Card from "@/components/ui/Card";

const VERDICT_STYLE: Record<string, string> = {
  escalated: "border-accent/55 text-success",
  needs_work: "border-warn/55 text-warn",
  borderline: "border-glow/50 text-glow",
  killed: "border-error/35 text-error/70",
  proposed: "border-edge text-info",
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
      {err && <p className="text-error text-xs">{err}</p>}
      {!err && ideas.length === 0 && (
        <div className="bg-surface/40 border border-dashed border-edge rounded-lg px-3 py-4 text-center">
          <p className="text-secondary text-xs">No ideas yet — run the proposer to generate the first batch.</p>
        </div>
      )}
      <div className="flex flex-col gap-2 overflow-y-auto">
        {sorted.map((idea) => {
          const v = idea.evaluator_verdict ?? idea.status;
          return (
            <div
              key={idea.id}
              className={`rounded-lg border bg-surface/50 px-3 py-2 ${
                VERDICT_STYLE[v] ?? "border-edge text-secondary"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="label">
                  #{idea.id} · {v}
                </span>
                <span className="text-2xs font-mono">
                  {idea.evaluator_score != null
                    ? `${idea.evaluator_score}/100`
                    : "—"}
                </span>
              </div>
              <p className="text-xs text-primary mt-0.5 line-clamp-3">
                {idea.idea_text}
              </p>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
