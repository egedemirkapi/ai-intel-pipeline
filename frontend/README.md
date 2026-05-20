# Jarvis Dashboard

Live web view over the startup-ideation fleet — agent status, intel
feed, idea board, emerging trends, and a chat box that talks to Jarvis.

## Run it

The dashboard is a pure client of the **Jarvis Brain** API. Start the
Brain first:

```powershell
# from the repo root
.\.venv\Scripts\python.exe -m ai_intel.jarvis brain serve --host 0.0.0.0
```

Then the dashboard:

```powershell
cd frontend
npm install      # first time only
npm run dev      # http://localhost:3100
```

Port **3100** is used deliberately — it dodges any other dev server
(or a stale service worker) you might have on the usual port 3000.

## Phone access via Tailscale

1. Install Tailscale on your laptop and phone, sign in with the same
   account on both.
2. The dashboard is served on `0.0.0.0:3100` and the Brain on
   `0.0.0.0:9999` — both reachable over your tailnet.
3. On your phone, open `http://<laptop-tailscale-name>:3100`.

The dashboard derives the Brain URL from the hostname the page was
loaded from, so the same build works on localhost and over Tailscale
with no config. Tailscale's device identity is the security boundary —
only your own devices can reach the services.

## What you see

- **Agent Fleet** — one row per agent, live status dot (green=done,
  amber=running, red=failed). Re-fetches on every fleet event.
- **Emerging Trends** — the synthesizer's current META-patterns.
- **Idea Board** — IdeaCandidates ranked escalated → killed.
- **Intel Feed** — items collected in the last 24h.
- **Talk to Jarvis** — conversational box; Jarvis can introspect the
  fleet, run agents, list ideas, fire workflows.

The green/red dot in the header shows the WebSocket connection state.
