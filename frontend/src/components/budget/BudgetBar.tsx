import { cx } from "@/components/ui";
import type { Budget } from "@/types/api";
import { inr } from "@/utils/format";

export const CATS: { key: string; label: string; color: string }[] = [
  { key: "accommodation", label: "Stay", color: "#0F5C5A" },
  { key: "food", label: "Food", color: "#6F8040" },
  { key: "transport", label: "Transport", color: "#B7791F" },
  { key: "activities", label: "Activities", color: "#C8553D" },
  { key: "other", label: "Other", color: "#BFB095" },
];

/** One stacked bar against the limit. No donuts, no fake analytics. */
export function BudgetBar({ b, legend = true }: { b: Budget; legend?: boolean }) {
  const total = Number(b.total), cap = b.cap ? Number(b.cap) : null;
  const scale = Math.max(total, cap ?? 0) || 1;
  const segs = CATS.map((c) => ({ ...c, v: Number(b.by_category[c.key] ?? 0) })).filter((s) => s.v > 0);
  return (
    <div>
      <div role="img" aria-label={`${inr(b.total)} estimated${cap ? ` against a limit of ${inr(cap)}` : ""}`}
        className="relative h-3.5 w-full overflow-visible rounded bg-sand-light">
        <div className="flex h-full overflow-hidden rounded" style={{ width: `${(total / scale) * 100}%` }}>
          {segs.map((s) => <div key={s.key} style={{ width: `${(s.v / total) * 100}%`, background: s.color }} />)}
        </div>
        {cap !== null && <div className="absolute -top-1 h-6 w-0.5 bg-ink" style={{ left: `calc(${(cap / scale) * 100}% - 1px)` }} title={`Limit ${inr(cap)}`} />}
      </div>
      {legend && <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm text-ink-soft">
        {segs.map((s) => <li key={s.key} className="flex items-center gap-1.5"><span aria-hidden className="size-2.5 rounded-sm" style={{ background: s.color }} />{s.label} {inr(s.v)}</li>)}
      </ul>}
    </div>
  );
}

export function budgetSentence(b: Budget): { text: string; tone: "ok" | "warn" | "bad" | "none" } {
  switch (b.status) {
    case "no_budget": return { text: "No budget limit is set yet, so there's nothing to check this against.", tone: "none" };
    case "within": return { text: `Comfortably inside your ${inr(b.cap)} budget, with ${inr(b.remaining)} to spare.`, tone: "ok" };
    case "tight": return { text: `It fits your ${inr(b.cap)} budget, with only ${inr(b.remaining)} of room.`, tone: "warn" };
    default: return { text: `${inr(b.over_by)} over your ${inr(b.cap)} budget. Raising it, or shortening the trip, would sort that.`, tone: "bad" };
  }
}

export const toneClass = (t: ReturnType<typeof budgetSentence>["tone"]) =>
  cx(t === "ok" && "text-olive", t === "warn" && "text-amber", t === "bad" && "text-terracotta-dark", t === "none" && "text-ink-soft");
