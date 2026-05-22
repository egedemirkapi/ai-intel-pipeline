"use client";

import { useCallback, useEffect, useState } from "react";
import { api, Brief, Interest } from "@/lib/api";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";

// The Briefing — the dashboard's hero panel. It answers "what should I
// act on right now": a spoken summary, today's agenda, and — leading —
// the interest-matched For-You suggestions.
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

  const suggestions = brief?.suggestions ?? [];
  const news = brief?.news ?? [];

  return (
    <Card
      hero
      title="BRIEFING"
      className="shrink-0"
      right={
        <div className="flex gap-2">
          <Button variant="ghost" onClick={() => setShowInterests((s) => !s)}>
            {showInterests ? "Hide" : `Interests · ${interests.length}`}
          </Button>
          <Button variant="ghost" onClick={loadBrief} disabled={loading}>
            {loading ? "…" : "↻"}
          </Button>
        </div>
      }
    >
      {err && <p className="text-error text-xs mb-2">{err}</p>}

      {/* Spoken summary — the brief's voice */}
      {brief?.spoken && (
        <p className="text-md text-primary border-l-2 border-accent/60 pl-3 mb-4">
          {brief.spoken}
        </p>
      )}

      {/* Today — compact agenda */}
      <div className="grid grid-cols-2 gap-2 mb-4">
        <div className="bg-surface/60 border border-edge rounded-lg px-3 py-2">
          <p className="label text-glow/60 mb-1.5">Calendar</p>
          <p className="text-xs text-secondary line-clamp-2">
            {brief?.calendar.summary || "—"}
          </p>
        </div>
        <div className="bg-surface/60 border border-edge rounded-lg px-3 py-2">
          <p className="label text-glow/60 mb-1.5">Homework</p>
          <p className="text-xs text-secondary line-clamp-2">
            {brief?.homework.summary || "—"}
          </p>
        </div>
      </div>

      {/* For You — the promoted suggestions feed */}
      <div className="flex items-center justify-between mb-2">
        <p className="label text-accent">For you</p>
        {suggestions.length > 0 && (
          <span className="text-2xs text-muted">{suggestions.length} matched</span>
        )}
      </div>
      <div className="flex flex-col gap-1.5 mb-4">
        {suggestions.slice(0, 8).map((s) => (
          <a
            key={s.id}
            href={s.url}
            target="_blank"
            rel="noreferrer"
            className="group bg-surface/50 border border-edge hover:border-accent/45 rounded-lg px-3 py-2 transition-colors"
          >
            <p className="text-sm text-primary group-hover:text-accent line-clamp-2">
              {s.title}
            </p>
            <div className="flex items-center gap-2 mt-1.5">
              <span className="text-2xs uppercase text-glow/60">{s.source}</span>
              <span className="h-1 w-1 rounded-full bg-edge-strong" />
              <span className="text-2xs text-muted">interest match</span>
            </div>
          </a>
        ))}
        {brief && suggestions.length === 0 && (
          <div className="bg-surface/40 border border-dashed border-edge rounded-lg px-3 py-4 text-center">
            <p className="text-xs text-secondary mb-2">
              {interests.length === 0
                ? "No suggestions yet — tell Jarvis what you care about."
                : "No matches yet — the feed is still filling up."}
            </p>
            {interests.length === 0 && (
              <Button variant="ghost" onClick={() => setShowInterests(true)}>
                Add interests →
              </Button>
            )}
          </div>
        )}
      </div>

      {/* Top news — supporting */}
      <p className="label text-glow/60 mb-2">Top news</p>
      <div className="flex flex-col gap-1.5">
        {news.slice(0, 5).map((n) => (
          <a
            key={n.id}
            href={n.url}
            target="_blank"
            rel="noreferrer"
            className="flex gap-2 text-xs text-secondary hover:text-accent"
          >
            <span className="text-2xs uppercase text-glow/50 shrink-0 w-16 truncate">
              {n.source}
            </span>
            <span className="line-clamp-1">{n.title}</span>
          </a>
        ))}
        {brief && news.length === 0 && (
          <span className="text-xs text-muted">No recent news.</span>
        )}
      </div>

      {/* Interests editor — collapsible; these seed the suggestions */}
      {showInterests && (
        <div className="mt-4 bg-surface/60 border border-edge rounded-lg p-3">
          <p className="label text-glow/60 mb-2">
            Your interests — these seed suggestions
          </p>
          <div className="flex flex-wrap gap-1.5 mb-2">
            {interests.length === 0 && (
              <span className="text-xs text-muted">
                None yet — add a few topics you care about.
              </span>
            )}
            {interests.map((it) => (
              <span
                key={it.id}
                className="flex items-center gap-1.5 text-2xs bg-accent/10 border border-accent/30 text-accent rounded-full px-2 py-1"
              >
                {it.text}
                <button
                  type="button"
                  onClick={() => removeInterest(it.id)}
                  className="text-muted hover:text-error"
                  aria-label={`Remove ${it.text}`}
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
    </Card>
  );
}
