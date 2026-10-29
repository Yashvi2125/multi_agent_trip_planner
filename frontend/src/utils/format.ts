/** ₹1,25,000 — Indian digit grouping, no decimals. Accepts the decimal strings the API sends. */
export function inr(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Math.round(Number(v));
  if (!Number.isFinite(n)) return "—";
  const s = String(Math.abs(n));
  let out = s;
  if (s.length > 3) {
    let head = s.slice(0, -3);
    const parts: string[] = [];
    while (head.length > 2) { parts.unshift(head.slice(-2)); head = head.slice(0, -2); }
    if (head) parts.unshift(head);
    out = [...parts, s.slice(-3)].join(",");
  }
  return `${n < 0 ? "-" : ""}₹${out}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const parts = (iso: string) => { const [y, m, d] = iso.split("-").map(Number); return { y, m, d }; };

/** "10–14 Dec", "28 Dec – 2 Jan", or "Dates not set". */
export function dateRange(start: string | null, end: string | null): string {
  if (!start || !end) return "Dates not set";
  const a = parts(start), b = parts(end);
  if (start === end) return `${a.d} ${MONTHS[a.m - 1]}`;
  return a.m === b.m ? `${a.d}–${b.d} ${MONTHS[a.m - 1]}` : `${a.d} ${MONTHS[a.m - 1]} – ${b.d} ${MONTHS[b.m - 1]}`;
}

export function dayLabel(iso: string | null): string {
  if (!iso) return "";
  const { y, m, d } = parts(iso);
  const wd = new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", { weekday: "short", timeZone: "UTC" });
  return `${wd} ${d} ${MONTHS[m - 1]}`;
}

export function nightsBetween(start: string | null, end: string | null): number | null {
  if (!start || !end) return null;
  return Math.round((Date.parse(end) - Date.parse(start)) / 86_400_000);
}

export function timeAgo(iso: string, now = Date.now()): string {
  const s = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86_400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86_400)} d ago`;
}

export function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

export const initials = (name: string) =>
  name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join("") || "?";

export const firstName = (name: string) => name.split(/\s+/)[0] ?? name;

export const pct = (part: number, whole: number) => (whole > 0 ? Math.min(100, Math.max(0, (part / whole) * 100)) : 0);

export function duration(min: number): string {
  const h = Math.floor(min / 60), m = min % 60;
  return h ? (m ? `${h} h ${m} min` : `${h} h`) : `${m} min`;
}
