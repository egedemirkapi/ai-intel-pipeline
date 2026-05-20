"use client";

import { useCallback, useEffect, useState } from "react";
import { api, Brief, Interest } from "@/lib/api";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";

// The Briefing card — "what should I care about right now": top news,
// today's calendar + homework, and interest-based suggestions.
export default function BriefingPanel() {
  const [brief, setBrief] = useState<Brief | null>(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);
  const [showInterests, setShowInterests] = useState(false);
  const [interests, setInterests] = useState<Interest[]>([]);
  const [newInterest, setNewInterest] = useState("");

  const loadBrief = useCallback(() => {
    setLoading(true);
    setErr("");
    api
      .brief()
      .then(setBrief)
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
  }, []);

  const loadInterests = useCallback(() => {
    api.interests().then(setInterests).catch(() => {});
  }, []);

  useEffect(() => {
    loadBrief();
    loadInterests();
  }, [loadBrief, loadInterests]);

  const addInterest = async () => {
    const t = newInterest.trim();
    if (!t) return;
    setNewInterest("");
    try {
      await api.addInterest(t);
      loadInterests();
    } catch (e) {
      setErr(String(e));
    }
  };

  const removeInterest = async (id: number) => {
    try {
      await api.deleteInterest(id);
      loadInterests();
    } catch (e) {
      setErr(String(e));
    }
  };

  return (
    <Card
      title="BRIEFING"
      className="shrink-0"
      right={
        <div className="flex gap-2">
          <Button variant="ghost" onClick={() => setShowInterests((s) => !s)}>
            {showInterests ? "Hide interests" : `Interests (${interests.length})`}
          </Button>
          <Button variant="ghost" onClick={loadBrief} disabled={loading}>
            {loading ? "…" : "↻ Refresh"}
          </Button>
        </div>
      }
    >
      {err && <p className="text-rose-400 text-xs mb-2">{err}</p>}

      {brief?.spoken && (
        <p className="text-xs text-slate-400 italic mb-3 border-l-2 border-accent/40 pl-3">
          {brief.spoken}
        </p>
      )}

      {showInterests && (
        <div className="mb-3 bg-ink/50 border border-edge/60 rounded-lg p-3">
          <p className="text-[11px] tracking-[0.16em] text-accent mb-2">
            YOUR INTERESTS — these seed the suggestions
          </p>
          <div className="flex flex-wrap gap-1.5 mb-2">
            {interests.length === 0 && (
              <span className="text-xs text-slate-500">
                None yet — add a few topics you care about.
              </span>
            )}
            {interests.map((it) => (
              <span
                key={it.id}
                className="text-[11px] bg-accent/10 border border-accent/30 text-accent rounded-full px-2 py-0.5"
              >
                {it.text}
                <button
                  type="button"
                  onClick={() => removeInterest(it.id)}
                  className="ml-1.5 text-slate-400 hover:text-rose-300"
                >
                  ×
                </button>
              </span>
            ))}
          </div>
          <div className="flex gap-2">
            <Input
              value={newInterest}
              onChange={(e) => setNewInterest(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addInterest()}
              placeholder="e.g. AI agents, robotics, dev tools"
              className="flex-1"
            />
            <Button variant="ghost" onClick={addInterest}>
              Add
            </Button>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Today */}
        <div>
          <p className="text-[11px] tracking-[0.16em] text-glow/80 mb-2">TODAY</p>
          <p className="text-xs text-slate-300 mb-1.5">
            📅 {brief?.calendar.summary || "—"}
          </p>
          <p className="text-xs text-slate-300">
            🎓 {brief?.homework.summary || "—"}
          </p>
        </div>

        {/* Top news */}
        <div>
          <p className="text-[11px] tracking-[0.16em] text-glow/80 mb-2">
            TOP NEWS
          </p>
          <div className="flex flex-col gap-1.5">
            {(brief?.news ?? []).slice(0, 5).map((n) => (
              <a
                key={n.id}
                href={n.url}
                target="_blank"
                rel="noreferrer"
                className="text-xs text-slate-200 hover:text-accent line-clamp-2"
              >
                <span className="text-[10px] uppercase text-glow/60 mr-1">
                  {n.source}
                </span>
                {n.title}
              </a>
            ))}
            {brief && brief.news.length === 0 && (
              <span className="text-xs text-slate-500">No recent news.</span>
            )}
          </div>
        </div>

        {/* For you */}
        <div>
          <p className="text-[11px] tracking-[0.16em] text-glow/80 mb-2">
            FOR YOU
          </p>
          <div className="flex flex-col gap-1.5">
            {(brief?.suggestions ?? []).slice(0, 5).map((s) => (
              <a
                key={s.id}
                href={s.url}
                target="_blank"
                rel="noreferrer"
                className="text-xs text-slate-200 hover:text-accent line-clamp-2"
              >
                {s.title}
              </a>
            ))}
            {brief && brief.suggestions.length === 0 && (
              <span className="text-xs text-slate-500">
                {interests.length === 0
                  ? "Add interests to get suggestions →"
                  : "No matches yet — the feed is still filling up."}
              </span>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}
