// React hook: subscribe to the Brain's WebSocket /events stream.
//
// Reconnects with exponential backoff (handles phone sleep/wake and
// Brain restarts). Each event fires the supplied callback so panels
// can refresh themselves live.
"use client";

import { useEffect, useRef, useState } from "react";
import { brainWsBase } from "./api";

export interface FleetEvent {
  type: string;
  ts: number;
  agent_id?: string | null;
  run_id?: number | null;
  summary?: string | null;
  payload?: Record<string, unknown> | null;
}

export function useEvents(onEvent: (e: FleetEvent) => void) {
  const [connected, setConnected] = useState(false);
  const cbRef = useRef(onEvent);
  cbRef.current = onEvent;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let backoff = 1000;
    let closed = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (closed) return;
      ws = new WebSocket(`${brainWsBase()}/events`);
      ws.onopen = () => {
        setConnected(true);
        backoff = 1000; // reset backoff on a good connection
      };
      ws.onmessage = (msg) => {
        try {
          const data = JSON.parse(msg.data);
          if (data && data.type && data.type !== "hello") {
            cbRef.current(data as FleetEvent);
          }
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (closed) return;
        timer = setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, 15000);
      };
      ws.onerror = () => ws?.close();
    };

    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      ws?.close();
    };
  }, []);

  return { connected };
}
