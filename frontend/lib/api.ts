// API client for the Jarvis Brain.
//
// The Brain runs on port 9999 on the SAME host serving this page.
// Deriving the base URL from window.location.hostname means the
// dashboard works identically on localhost AND over Tailscale —
// load it from `laptop:3000`, it talks to `laptop:9999`; load it
// from a tailnet name, it talks to that name on 9999. No config.

export function brainBase(): string {
  if (typeof window === "undefined") return "http://127.0.0.1:9999";
  const host = window.location.hostname || "127.0.0.1";
  return `http://${host}:9999`;
}

export function brainWsBase(): string {
  if (typeof window === "undefined") return "ws://127.0.0.1:9999";
  const host = window.location.hostname || "127.0.0.1";
  return `ws://${host}:9999`;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${brainBase()}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

async function sendJson<T>(
  method: "POST" | "PUT" | "DELETE",
  path: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(`${brainBase()}${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      if (j?.detail) detail = String(j.detail);
    } catch {
      /* keep the status-code message */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

// ─── Typed shapes (mirror brain/app.py converters) ──────────────────

export interface AgentStatus {
  total_runs: number;
  latest: AgentRun | null;
}
export interface AgentRun {
  id: number;
  agent_id: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  cost_estimate_usd: number;
  summary: string | null;
  error: string | null;
}
export interface Idea {
  id: number;
  proposed_at: string | null;
  idea_text: string;
  tech_basis: string | null;
  evaluator_score: number | null;
  evaluator_verdict: string | null;
  status: string;
}
export interface Trend {
  id: number;
  cluster_label: string;
  underlying_shift: string | null;
  new_capability: string | null;
  momentum: string | null;
  member_count: number;
}
export interface IntelItem {
  id: number;
  source: string;
  title: string;
  url: string;
  collected_at: string | null;
  ai_relevance: number | null;
}
export interface ChatResult {
  reply: string;
  history: unknown[];
  tool_calls: { name: string; refused: boolean }[];
}
export interface CollectorStatus {
  total_items: number;
  last_24h: number;
  last_2h: number;
  last_collected_at: string | null;
  minutes_since_last: number | null;
}

// ─── Workflows / routines ───────────────────────────────────────────

export interface WorkflowTrigger {
  button?: boolean;
  clap?: boolean;
  hotkey?: string | null;
  voice_phrases?: string[];
}
// A step is a single-key map {action: args}.
export type WorkflowStep = Record<string, Record<string, unknown>>;
export interface WorkflowDef {
  description?: string;
  trigger?: WorkflowTrigger;
  steps: WorkflowStep[];
}
export interface WorkflowSummary {
  name: string;
  description: string;
  trigger: WorkflowTrigger;
  step_count: number;
  is_builtin: boolean;
  is_overridden: boolean;
}
export interface ValidateResult {
  valid: boolean;
  errors: string[];
}
export interface WorkflowRunResult {
  workflow?: string;
  ok?: boolean;
  steps?: Record<string, unknown>[];
  error?: string;
}

// ─── Installed apps ─────────────────────────────────────────────────

export interface InstalledApp {
  name: string;
  app_id: string;
}
export interface AllowedApp {
  app_id: string;
  name: string;
  added_at?: string;
}

// ─── Briefing + interests ───────────────────────────────────────────

export interface BriefNews {
  id: number;
  title: string;
  url: string;
  source: string;
  ai_relevance: number | null;
}
export interface BriefEvent {
  title: string;
  start: string | null;
  location: string | null;
}
export interface BriefAssignment {
  title: string;
  course: string | null;
  due_date: string | null;
}
export interface BriefSuggestion {
  id: number;
  title: string;
  url: string;
  source: string;
  score: number;
}
export interface Brief {
  generated_at: string;
  news: BriefNews[];
  calendar: { summary: string; events: BriefEvent[] };
  homework: { summary: string; assignments: BriefAssignment[] };
  suggestions: BriefSuggestion[];
  spoken: string;
}
export interface Interest {
  id: number;
  text: string;
  created_at: string | null;
}

// ─── Endpoints ──────────────────────────────────────────────────────

export const api = {
  agentsStatus: () => getJson<Record<string, AgentStatus>>("/agents/status"),
  collectorStatus: () => getJson<CollectorStatus>("/collector/status"),
  ideas: (status?: string) =>
    getJson<Idea[]>(`/ideas${status ? `?status=${status}` : ""}`),
  trends: () => getJson<Trend[]>("/trends"),
  intel: (hours = 24) => getJson<IntelItem[]>(`/intel?hours=${hours}&limit=60`),
  chat: async (message: string, history?: unknown[]): Promise<ChatResult> => {
    const res = await fetch(`${brainBase()}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history }),
    });
    if (!res.ok) throw new Error(`/chat → HTTP ${res.status}`);
    return res.json();
  },

  // Workflows / routines
  workflows: () => getJson<WorkflowSummary[]>("/workflows"),
  workflow: (name: string) =>
    getJson<{ name: string; definition: WorkflowDef }>(
      `/workflows/${encodeURIComponent(name)}`,
    ),
  createWorkflow: (name: string, definition: WorkflowDef) =>
    sendJson<{ name: string; definition: WorkflowDef }>("POST", "/workflows", {
      name,
      definition,
    }),
  updateWorkflow: (name: string, definition: WorkflowDef) =>
    sendJson<{ name: string; definition: WorkflowDef }>(
      "PUT",
      `/workflows/${encodeURIComponent(name)}`,
      { definition },
    ),
  deleteWorkflow: (name: string) =>
    sendJson<{ deleted: string }>(
      "DELETE",
      `/workflows/${encodeURIComponent(name)}`,
    ),
  validateWorkflow: (definition: WorkflowDef) =>
    sendJson<ValidateResult>("POST", "/workflows/validate", { definition }),
  runWorkflow: (name: string) =>
    sendJson<WorkflowRunResult>(
      "POST",
      `/workflow/${encodeURIComponent(name)}`,
    ),

  // Installed apps + launch allowlist
  appsInstalled: (refresh = false) =>
    getJson<InstalledApp[]>(`/apps/installed${refresh ? "?refresh=1" : ""}`),
  appsAllowed: () => getJson<AllowedApp[]>("/apps/allowed"),
  allowApp: (app_id: string, name: string) =>
    sendJson<{ allowed: AllowedApp }>("POST", "/apps/allow", { app_id, name }),
  disallowApp: (app_id: string) =>
    sendJson<{ removed: string }>(
      "DELETE",
      `/apps/allow/${encodeURIComponent(app_id)}`,
    ),

  // Briefing + interests
  brief: () => getJson<Brief>("/brief"),
  interests: () => getJson<Interest[]>("/interests"),
  addInterest: (text: string) =>
    sendJson<{ id: number; text: string }>("POST", "/interests", { text }),
  deleteInterest: (id: number) =>
    sendJson<{ deleted: number }>("DELETE", `/interests/${id}`),
};
