import { type FormEvent, useEffect, useState } from "react";
import { DayTimeline } from "@/components/itinerary/DayTimeline";
import { DAY_COLORS, TripMap } from "@/components/map/TripMap";
import { Badge, Button, cx, EmptyState, ErrorBanner, Skeleton } from "@/components/ui";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { api, ApiError } from "@/services/api";
import { useTrip } from "@/store/trip";
import type { ItineraryOut } from "@/types/api";
import { inr, timeAgo } from "@/utils/format";
import { usePlanAction } from "./Overview";

export default function ItineraryPage() {
  const t = useTrip();
  const act = usePlanAction();
  const wide = useMediaQuery("(min-width: 1024px)");
  const [view, setView] = useState<number | null>(null);
  const [older, setOlder] = useState<ItineraryOut | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [mapDay, setMapDay] = useState<number | null>(null);
  const [showMap, setShowMap] = useState(false);
  const [q, setQ] = useState("");
  const [qid, setQid] = useState<number | null>(null);
  const [askErr, setAskErr] = useState<string | null>(null);

  useEffect(() => {
    if (view === null || view === t.plan?.version) { setOlder(null); return; }
    let alive = true;
    setLoadErr(null);
    api.plan.itinerary(t.id, view).then((p) => alive && setOlder(p)).catch((e) => alive && setLoadErr(e instanceof ApiError ? e.message : "Couldn't load that version."));
    return () => { alive = false; };
  }, [view, t.id, t.plan?.version]);

  async function ask(e: FormEvent) {
    e.preventDefault();
    if (q.trim().length < 3) return;
    setAskErr(null); setQid(null);
    try { setQid(await t.ask(q.trim())); } catch (x) { setAskErr(x instanceof ApiError ? x.message : "Couldn't ask the planner just now."); }
  }

  if (!t.ready) return <div className="space-y-4"><Skeleton className="h-6 w-2/3" /><Skeleton className="h-64" /></div>;
  if (!t.plan) {
    return <EmptyState title="No itinerary yet." action={<Button variant="primary" busy={act.busy} onClick={act.run}>Build the first plan</Button>}>
      Tell the group what kind of trip you want, and I'll build the first version.{act.error && <><br /><span className="text-terracotta-dark">{act.error}</span></>}</EmptyState>;
  }
  const shown = older ?? t.plan, it = shown.itinerary, viewingOld = shown.version !== t.plan.version;

  return (
    <div className="lg:grid lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] lg:gap-10">
      <div className="min-w-0">
        <div className="mb-6 space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <label className="sr-only" htmlFor="ver">Plan version</label>
            <select id="ver" value={shown.version} onChange={(e) => setView(Number(e.target.value))} className="rounded border border-sand-dark bg-surface px-2.5 py-1.5 text-sm font-semibold">
              {[...t.versions].reverse().map((v) => <option key={v.version} value={v.version}>Version {v.version}{v.version === t.plan!.version ? " (latest)" : ""}</option>)}</select>
            <span className="text-sm text-ink-soft">updated {timeAgo(shown.created_at)}</span>
            <span className="flex-1" />
            <Button busy={act.busy} onClick={act.run}>Update the plan</Button>
          </div>
          {shown.change_summary && <p className="text-[15px]"><span className="font-semibold">{shown.version === 1 ? "" : "What changed: "}</span>{shown.change_summary}</p>}
          {viewingOld && <p className="rounded bg-amber-tint px-3 py-2 text-sm text-amber">You're looking at an earlier version. <button className="font-semibold underline" onClick={() => setView(null)}>Back to the latest</button></p>}
          {it.used_fallback && <p className="text-sm text-ink-faint"><Badge tone="neutral">Rule-based</Badge> The AI model wasn't available for this version, so the choices are plainer than usual.</p>}
          {loadErr && <ErrorBanner message={loadErr} />}{act.error && <ErrorBanner message={act.error} />}
          {it.stay && <p className="border-l-2 border-sand-dark pl-3 text-[15px] text-ink-soft"><span className="font-semibold text-ink">Stay: </span>{it.stay.why} About {inr(it.stay.nightly_per_room)} a room a night, {it.stay.rooms} room{it.stay.rooms === 1 ? "" : "s"}, {it.stay.nights} night{it.stay.nights === 1 ? "" : "s"}.</p>}
        </div>

        <DayTimeline days={it.days} focus={mapDay} onFocus={(d) => setMapDay((cur) => (cur === d ? null : d))} />

        <form onSubmit={ask} className="mt-10 border-t border-sand pt-6">
          <label htmlFor="ask" className="text-lg font-display">Ask about the plan</label>
          <div className="mt-2 flex gap-2"><input id="ask" value={q} onChange={(e) => setQ(e.target.value)} maxLength={500} placeholder="Why is the hotel in North Goa? Why was something moved?" className="min-w-0 flex-1 rounded border border-sand-dark bg-surface px-3 py-2.5 text-[15px] placeholder:text-ink-faint focus:border-lagoon" />
            <Button type="submit" disabled={q.trim().length < 3}>Ask</Button></div>
          {askErr && <p role="alert" className="mt-2 text-sm text-terracotta-dark">{askErr}</p>}
          {qid !== null && <p aria-live="polite" className="mt-3 border-l-2 border-lagoon/50 pl-3 text-[15px]">{t.answers[qid] ?? <span className="text-lagoon dots">Looking at the plan</span>}</p>}
        </form>
      </div>

      <aside aria-label="Map" className="mt-10 lg:mt-0">
        <div className="lg:sticky lg:top-20">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <button onClick={() => setMapDay(null)} className={cx("rounded-sm px-2.5 py-1 text-sm font-semibold", mapDay === null ? "bg-ink text-paper" : "bg-sand-light text-ink-soft")}>All days</button>
            {it.days.map((d) => <button key={d.index} onClick={() => setMapDay(d.index)} aria-pressed={mapDay === d.index} className={cx("rounded-sm px-2.5 py-1 text-sm font-semibold", mapDay === d.index ? "text-white" : "bg-sand-light text-ink-soft")} style={mapDay === d.index ? { background: DAY_COLORS[(d.index - 1) % DAY_COLORS.length] } : undefined}>Day {d.index}</button>)}
            {!wide && <button onClick={() => setShowMap((s) => !s)} className="ml-auto text-sm font-semibold text-lagoon">{showMap ? "Hide map" : "Show map"}</button>}
          </div>
          {(wide || showMap) && <TripMap days={it.days} onlyDay={mapDay} height={wide ? 460 : 320} />}
        </div>
      </aside>
    </div>
  );
}
