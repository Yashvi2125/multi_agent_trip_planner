import { Car, HelpCircle, Wallet } from "lucide-react";
import { useState } from "react";
import { Badge, Button, cx } from "@/components/ui";
import { DAY_COLORS } from "@/components/map/TripMap";
import { ApiError } from "@/services/api";
import { useTrip } from "@/store/trip";
import type { ItineraryDay, ItineraryItem } from "@/types/api";
import { dayLabel, duration, inr } from "@/utils/format";

function Why({ item }: { item: ItineraryItem }) {
  const { ask, answers } = useTrip();
  const [open, setOpen] = useState(false);
  const [qid, setQid] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const detail = qid ? answers[qid] : null;

  async function more() {
    setErr(null);
    try { setQid(await ask(`Why is ${item.name} in the plan?`)); }
    catch (e) { setErr(e instanceof ApiError ? e.message : "Couldn't ask the planner just now."); }
  }
  return (
    <div className="mt-1">
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="inline-flex items-center gap-1 text-sm font-semibold text-lagoon hover:underline"><HelpCircle size={14} aria-hidden />Why this?</button>
      {open && (
        <div className="mt-2 max-w-prose animate-rise rounded border border-sand bg-paper p-3 text-sm text-ink-soft shadow-pop">
          <p>{item.why || "A well-rounded stop for this area."}</p>
          {item.serves.length > 0 && <p className="mt-1">Chosen with {item.serves.join(", ")} in mind.</p>}
          {detail ? <p className="mt-2 border-l-2 border-lagoon/50 pl-3 text-ink">{detail}</p>
            : <Button size="sm" variant="ghost" className="mt-2 -ml-3" busy={qid !== null} onClick={more}>Ask the planner for more</Button>}
          {err && <p role="alert" className="mt-1 text-terracotta-dark">{err}</p>}
        </div>
      )}
    </div>
  );
}

export function DayTimeline({ days, compact = false, focus, onFocus }: {
  days: ItineraryDay[]; compact?: boolean; focus?: number | null; onFocus?: (d: number) => void;
}) {
  return (
    <ol className="space-y-9">
      {days.map((d) => {
        const color = DAY_COLORS[(d.index - 1) % DAY_COLORS.length];
        return (
          <li key={d.index} className={cx("scroll-mt-24", focus === d.index && "rounded outline outline-1 outline-offset-8 outline-sand-dark")}>
            <header className="flex items-baseline gap-3 border-b border-sand pb-2" onClick={() => onFocus?.(d.index)}>
              <span className="text-xs font-bold uppercase tracking-widest" style={{ color }}>Day {d.index}</span>
              <h3 className="text-xl">{d.title || "Free day"}</h3>
              <span className="ml-auto text-sm text-ink-faint">{dayLabel(d.date)}</span>
            </header>
            {d.note && <p className="mt-3 rounded bg-amber-tint px-3 py-2 text-sm text-amber">{d.note}</p>}
            {d.items.length === 0 ? (
              <p className="mt-3 text-ink-soft">Nothing scheduled, so it's open for rest or something spontaneous.</p>
            ) : (
              <ul className="mt-3">
                {d.items.map((it, n) => (
                  <li key={it.place_id} className="grid grid-cols-[3.75rem_1fr] gap-x-3">
                    <p className="pt-0.5 text-right text-sm tabular-nums text-ink-soft">{it.start}<br /><span className="text-ink-faint">{it.end}</span></p>
                    <div className="relative border-l border-sand-dark pb-6 pl-5 last:pb-1">
                      <span aria-hidden className="absolute -left-[5px] top-1.5 size-2.5 rounded-full ring-4 ring-paper" style={{ background: color }} />
                      {it.travel_min_from_prev > 0 && n > 0 && <p className="mb-1 flex items-center gap-1 text-xs text-ink-faint"><Car size={12} aria-hidden />{it.travel_min_from_prev} min from the last stop</p>}
                      <p className="flex flex-wrap items-center gap-2"><span className="font-semibold">{it.name}</span>
                        {it.optional && <Badge tone="amber">Optional</Badge>}</p>
                      <p className="mt-0.5 flex flex-wrap items-center gap-x-3 text-sm text-ink-soft">
                        <span>{duration(it.duration_min)}</span>
                        <span className="inline-flex items-center gap-1"><Wallet size={13} aria-hidden />{it.cost_pp ? `${inr(it.cost_pp)} each` : "Free"}</span>
                        {it.serves.length > 0 && <span>For {it.serves.join(", ")}</span>}
                      </p>
                      {!compact && <Why item={it} />}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </li>
        );
      })}
    </ol>
  );
}
