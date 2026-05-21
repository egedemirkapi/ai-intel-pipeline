// Cron helpers for the routine editor's schedule field.
//
// Workflows store a 5-field cron string. The dashboard exposes a
// friendly Daily / Weekdays / Weekly picker; these convert between that
// and the cron string. Day-of-week is emitted as NAMES (mon, tue, ...)
// — APScheduler's crontab parser numbers weekdays differently from
// classic cron, so names keep it unambiguous.

export const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const DOW_CRON = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];

export interface CronParts {
  freq: "none" | "daily" | "weekdays" | "weekly" | "custom";
  time: string; // "HH:MM"
  dow: number; // 0=Sun .. 6=Sat
}

export function parseCron(cron: string): CronParts {
  const parts = (cron || "").trim().split(/\s+/);
  if (parts.length !== 5) return { freq: "none", time: "08:00", dow: 1 };
  const [m, h, dom, mon, dow] = parts;
  const numeric = /^\d+$/.test(m) && /^\d+$/.test(h);
  if (!numeric || dom !== "*" || mon !== "*") {
    return { freq: "custom", time: "08:00", dow: 1 };
  }
  const time = `${h.padStart(2, "0")}:${m.padStart(2, "0")}`;
  if (dow === "*") return { freq: "daily", time, dow: 1 };
  if (dow.toLowerCase() === "mon-fri" || dow === "1-5") {
    return { freq: "weekdays", time, dow: 1 };
  }
  const named = DOW_CRON.indexOf(dow.toLowerCase());
  if (named >= 0) return { freq: "weekly", time, dow: named };
  if (/^[0-6]$/.test(dow)) return { freq: "weekly", time, dow: Number(dow) };
  return { freq: "custom", time: "08:00", dow: 1 };
}

export function buildCron(freq: string, time: string, dow: number): string {
  const [h, m] = (time || "08:00").split(":");
  const hh = String(Number(h) || 0);
  const mm = String(Number(m) || 0);
  if (freq === "daily") return `${mm} ${hh} * * *`;
  if (freq === "weekdays") return `${mm} ${hh} * * mon-fri`;
  if (freq === "weekly") return `${mm} ${hh} * * ${DOW_CRON[dow] ?? "mon"}`;
  return "";
}

// A short human label for a cron string — used on routine cards.
export function cronLabel(cron: string): string {
  const p = parseCron(cron);
  if (p.freq === "daily") return `daily ${p.time}`;
  if (p.freq === "weekdays") return `weekdays ${p.time}`;
  if (p.freq === "weekly") return `${WEEKDAYS[p.dow]} ${p.time}`;
  return cron;
}
