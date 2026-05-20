"use client";

import { useEffect, useState } from "react";
import { api, InstalledApp } from "@/lib/api";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";

// Picks an installed Windows app for an apps.launch step. Selecting an
// app also adds it to the launch allowlist (POST /apps/allow) so the
// workflow can actually run it.
export default function AppPicker({
  name,
  onPick,
}: {
  appId?: string;
  name?: string;
  onPick: (appId: string, name: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [apps, setApps] = useState<InstalledApp[]>([]);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const load = (refresh = false) => {
    setLoading(true);
    setErr("");
    api
      .appsInstalled(refresh)
      .then(setApps)
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (open && apps.length === 0) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const pick = async (a: InstalledApp) => {
    try {
      await api.allowApp(a.app_id, a.name);
    } catch {
      /* allowlisting is best-effort; the step still records the app */
    }
    onPick(a.app_id, a.name);
    setOpen(false);
  };

  const filtered = apps
    .filter((a) => a.name.toLowerCase().includes(q.toLowerCase()))
    .slice(0, 80);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full text-left bg-ink/70 border border-edge rounded-lg px-3 py-2 text-sm text-slate-100 hover:border-accent/50 transition-colors"
      >
        {name ? `▸ ${name}` : "Choose an app…"}
      </button>
      {open && (
        <div className="absolute z-30 mt-1 w-72 glass rounded-lg p-2 flex flex-col gap-2">
          <div className="flex gap-2">
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search installed apps…"
              className="flex-1"
              autoFocus
            />
            <Button
              variant="ghost"
              onClick={() => load(true)}
              title="Rescan installed apps"
            >
              ⟳
            </Button>
          </div>
          {loading && <p className="text-xs text-slate-500">scanning…</p>}
          {err && <p className="text-xs text-rose-400">{err}</p>}
          {!loading && !err && apps.length === 0 && (
            <p className="text-xs text-slate-500">
              No apps found (scan only works on Windows).
            </p>
          )}
          <div className="overflow-y-auto max-h-56 flex flex-col">
            {filtered.map((a) => (
              <button
                key={a.app_id}
                type="button"
                onClick={() => pick(a)}
                className="text-left text-xs text-slate-200 hover:bg-accent/10 rounded px-2 py-1.5 truncate"
                title={a.app_id}
              >
                {a.name}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
