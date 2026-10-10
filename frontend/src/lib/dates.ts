const pad = (n: number) => String(n).padStart(2, "0");

/** Today on this device as YYYY-MM-DD, in local time like the health worker's calendar. */
export function todayIso(now: Date = new Date()): string {
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export function addDays(iso: string, days: number): string {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day + days)).toISOString().slice(0, 10);
}

/** A backend UTC timestamp ("YYYY-MM-DD HH:MM:SS") as a Date. */
export function fromUtcStamp(stamp: string): Date {
  return new Date(`${stamp.replace(" ", "T").slice(0, 19)}Z`);
}

/** Short local time for an activity line: "08:15" today, otherwise "2026-10-08 08:15". */
export function shortStamp(stamp: string, now: Date = new Date()): string {
  const when = fromUtcStamp(stamp);
  if (Number.isNaN(when.getTime())) return stamp;
  const time = `${pad(when.getHours())}:${pad(when.getMinutes())}`;
  return todayIso(when) === todayIso(now) ? time : `${todayIso(when)} ${time}`;
}
