"use client";

import { useRef, useState } from "react";
import { api } from "@/lib/api";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import { OrbState } from "@/components/JarvisOrb";

interface Turn {
  role: "user" | "jarvis";
  text: string;
  tools?: string[];
}

export default function ChatBox({
  onState,
}: {
  onState?: (s: OrbState) => void;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  // Brain conversation history (assistant + tool blocks) for context.
  const historyRef = useRef<unknown[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const idleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const send = async () => {
    const msg = input.trim();
    if (!msg || busy) return;
    setInput("");
    setTurns((t) => [...t, { role: "user", text: msg }]);
    setBusy(true);
    onState?.("thinking"); // the orb shimmers while Jarvis works
    try {
      const res = await api.chat(msg, historyRef.current);
      historyRef.current = (res.history as unknown[]) ?? [];
      const tools = (res.tool_calls ?? []).map((c) => c.name);
      setTurns((t) => [
        ...t,
        { role: "jarvis", text: res.reply || "(no reply)", tools },
      ]);
      onState?.("speaking"); // a brief wobble as the reply lands
      if (idleTimer.current) clearTimeout(idleTimer.current);
      idleTimer.current = setTimeout(() => onState?.("idle"), 2400);
    } catch (e) {
      setTurns((t) => [...t, { role: "jarvis", text: `Error: ${String(e)}` }]);
      onState?.("idle");
    } finally {
      setBusy(false);
      setTimeout(() => {
        scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
      }, 50);
    }
  };

  return (
    <Card title="CONVERSATION" className="min-h-0 h-full">
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto flex flex-col gap-2 mb-3"
      >
        {turns.length === 0 && (
          <div className="bg-surface/40 border border-dashed border-edge rounded-lg px-3 py-4 text-center">
            <p className="text-secondary text-sm leading-relaxed">
              Ask anything — &quot;what&apos;s the fleet doing&quot;, &quot;open
              Spotify&quot;, &quot;run the process and give me 3 ideas&quot;,
              &quot;what&apos;s my briefing&quot;.
            </p>
          </div>
        )}
        {turns.map((t, i) => {
          const isError =
            t.role === "jarvis" && t.text.startsWith("Error:");
          const isRefused =
            t.tools?.some((name) =>
              name.toLowerCase().includes("refus")
            ) ?? false;

          return (
            <div
              key={i}
              className={`rounded-lg px-3 py-2 text-sm ${
                t.role === "user"
                  ? "bg-accent/10 border border-accent/25 text-primary self-end max-w-[85%]"
                  : isError
                  ? "bg-surface/50 border border-error/30 text-error self-start max-w-[92%]"
                  : "bg-surface/50 border border-edge text-secondary self-start max-w-[92%]"
              }`}
            >
              <p className="whitespace-pre-wrap">{t.text}</p>
              {t.tools && t.tools.length > 0 && (
                <p className={`label mt-1.5 ${isRefused ? "text-error" : "text-glow/60"}`}>
                  used: {t.tools.join(", ")}
                </p>
              )}
            </div>
          );
        })}
        {busy && (
          <div className="bg-surface/50 border border-edge rounded-lg px-3 py-2 text-sm text-muted self-start">
            thinking…
          </div>
        )}
      </div>
      <div className="flex gap-2 shrink-0">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="Type or speak to Jarvis…"
          disabled={busy}
          className="flex-1"
        />
        <Button onClick={send} disabled={busy}>
          Send
        </Button>
      </div>
    </Card>
  );
}
