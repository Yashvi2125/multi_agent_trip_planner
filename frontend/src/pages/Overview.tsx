import { Link } from "react-router-dom";
import { useState } from "react";
import { BudgetBar, budgetSentence, toneClass } from "@/components/budget/BudgetBar";
import { DayTimeline } from "@/components/itinerary/DayTimeline";
import { Checklist } from "@/components/trip/Checklist";
import { ConflictBlock } from "@/components/trip/ConflictBlock";
import { WeatherStrip } from "@/components/trip/WeatherStrip";
import { Button, EmptyState, ErrorBanner, SectionTitle, Skeleton } from "@/components/ui";
import { ApiError } from "@/services/api";
import { useTrip } from "@/store/trip";
import { timeAgo } from "@/utils/format";

export function usePlanAction() {
  const { regenerate, aiStatus } = useTrip();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async () => {
    setBusy(true); setError(null);
    try { await regenerate(); } catch (e) { setError(e instanceof ApiError ? e.message : "Couldn't start the plan. Please try again."); }
    finally { setTimeout(() => setBusy(false), 1500); }   // the planner answers asynchronously; keep the button calm meanwhile
  };
  return { run, busy: busy || !!aiStatus, error };
}

export default function Overview() {
  const t = useTrip();
  const act = usePlanAction();
  const open = t.conflicts.filter((c) => c.status === "open");
  const sharers = new Set(t.prefs?.preferences.map((p) => p.user_id)).size;
  const base = `/trip/${t.id}`;

  return (
    <div className="space-y-12">
      {open.length > 0 && (
        <section aria-labelledby="needs">
          <SectionTitle>{<span id="needs">Needs a decision</span>}</SectionTitle>
          <div className="space-y-6">{open.map((c) => <ConflictBlock key={c.id} conflict={c} />)}</div>
        </section>)}

      <section aria-labelledby="plan-h">
        <SectionTitle aside={t.plan && <Link to={`${base}/itinerary`} className="text-sm font-semibold text-lagoon hover:underline">Full plan →</Link>}><span id="plan-h">The plan</span></SectionTitle>
        {!t.ready ? <div className="space-y-3"><Skeleton className="h-6 w-1/2" /><Skeleton className="h-24" /></div>
          : !t.plan ? (
            <EmptyState title="No itinerary yet." action={<Button variant="primary" busy={act.busy} onClick={act.run}>Build the first plan</Button>}>
              Tell the group what kind of trip you want, and I'll build the first version.
              {t.trip && sharers > 0 && <><br /><span className="text-sm text-ink-faint">{sharers} of {t.trip.member_count} travellers have shared preferences so far.</span></>}
              {act.error && <><br /><span className="text-terracotta-dark">{act.error}</span></>}
            </EmptyState>)
          : (<>
            <p className="mb-5 text-ink-soft">Version {t.plan.version} · updated {timeAgo(t.plan.created_at)}{t.plan.change_summary && t.plan.version > 1 ? ` · ${t.plan.change_summary}` : ""}</p>
            <DayTimeline days={t.plan.itinerary.days.slice(0, 2)} compact />
            <div className="mt-6 flex items-center gap-4"><Button busy={act.busy} onClick={act.run}>Update the plan</Button>
              {t.plan.itinerary.days.length > 2 && <Link to={`${base}/itinerary`} className="text-sm font-semibold text-lagoon hover:underline">+ {t.plan.itinerary.days.length - 2} more days</Link>}</div>
            {act.error && <div className="mt-3"><ErrorBanner message={act.error} /></div>}
          </>)}
      </section>

      <section aria-labelledby="bud-h" className="border-t border-sand pt-8">
        <SectionTitle aside={t.budget && <Link to={`${base}/budget`} className="text-sm font-semibold text-lagoon hover:underline">Breakdown →</Link>}><span id="bud-h">Budget</span></SectionTitle>
        {t.budget ? (() => { const s = budgetSentence(t.budget); return (<>
          <p className="mb-4"><span className="font-display text-3xl">{Number(t.budget.per_person).toLocaleString("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 })}</span> <span className="text-ink-soft">each · {Number(t.budget.total).toLocaleString("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 })} for {t.budget.travelers}</span></p>
          <BudgetBar b={t.budget} /><p className={`mt-3 ${toneClass(s.tone)}`}>{s.text}</p></>); })()
          : <p className="text-ink-soft">The cost estimate appears as soon as the first plan is built.</p>}
      </section>

      <section aria-labelledby="wx-h" className="border-t border-sand pt-8">
        <SectionTitle><span id="wx-h">Weather</span></SectionTitle>
        {t.weather ? <WeatherStrip w={t.weather} /> : <p className="text-ink-soft">{t.ready ? "Weather appears once the trip has dates and a destination we know." : <Skeleton className="w-64" />}</p>}
      </section>

      <section aria-labelledby="chk-h" className="border-t border-sand pt-8">
        <SectionTitle><span id="chk-h">Before you go</span></SectionTitle>
        <Checklist />
      </section>
    </div>
  );
}
