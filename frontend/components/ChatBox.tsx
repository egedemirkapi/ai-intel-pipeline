"use client";

import { useRef, useState } from "react";
import { api } from "@/lib/api";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";

interface Turn {
  role: "user" | "jarvis";
  text: string;
  tools?: string[];
}

export default function ChatBox() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  // Brain conversation history (assistant + tool blocks) for context.
  const historyRef = useRef<unknown[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  const send = async () => {
    const msg = input.trim();
    if (!msg || busy) return;
    setInput("");
    setTurns((t) => [...t, { role: "user", text: msg }]);
    setBusy(true);
    try {
      const res = await api.chat(msg, historyRef.current);
      historyRef.current = (res.history as unknown[]) ?? [];
      const tools = (res.tool_calls ?? []).map((c) => c.name);
      setTurns((t) => [
        ...t,
        { role: "jarvis", text: res.reply || "(no reply)", tools },
      ]);
    } catch (e) {
      setTurns((t) => [...t, { role: "jarvis", text: `Error: ${String(e)}` }]);
    } finally {
      setBusy(false);
      setTimeout(() => {
        scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
      }, 50);
    }
  };

  return (
    <Card title="TALK TO JARVIS" className="min-h-0 h-full">
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto flex flex-col gap-2 mb-3"
      >
        {turns.length === 0 && (
          <p className="text-slate-500 text-xs">
            Ask anything — &quot;what&apos;s the fleet doing&quot;, &quot;show
            me borderline ideas&quot;, &quot;run my morning brief&quot;.
          </p>
        )}
        {turns.map((t, i) => (
          <div
            key={i}
            className={`rounded-lg px-3 py-2 text-sm ${
              t.role === "user"
                ? "bg-accent/10 border border-accent/25 text-slate-100 self-end max-w-[85%]"
                : "bg-ink/70 border border-edge/50 text-slate-200 self-start max-w-[92%]"
            }`}
          >
            <p className="whitespace-pre-wrap">{t.text}</p>
            {t.tools && t.tools.length > 0 && (
              <p className="text-[10px] text-glow/70 mt-1">
                used: {t.tools.join(", ")}
              </p>
            )}
          </div>
        ))}
        {busy && (
          <div className="bg-ink/70 border border-edge/50 text-slate-400 rounded-lg px-3 py-2 text-sm self-start">
            thinking…
          </div>
        )}
      </div>
      <div className="flex gap-2 shrink-0">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="Message Jarvis…"
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
