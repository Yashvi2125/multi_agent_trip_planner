import { ChevronRight, Plus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, EmptyState, ErrorBanner } from "@/components/ui";
import { api, ApiError } from "@/services/api";
import type { Trip } from "@/types/api";
import { dateRange, inr } from "@/utils/format";

const STATUS = { planning: ["Gathering ideas", "amber"], researching: ["Researching", "amber"], planned: ["Plan ready", "olive"], locked: ["Locked in", "teal"] } as const;

export default function Trips() {
  const [trips, setTrips] = useState<Trip[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => { setError(null); api.trips.list().then(setTrips).catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't load your trips.")); }, []);
  useEffect(load, [load]);

  return (
    <main className="mx-auto max-w-4xl px-4 py-10">
      <div className="mb-6 flex items-end justify-between gap-4"><h1 className="text-4xl">Your trips</h1>
        {trips && trips.length > 0 && <div className="flex gap-2"><Link to="/join"><Button>Join with a code</Button></Link><Link to="/create"><Button variant="primary"><Plus size={16} aria-hidden />New trip</Button></Link></div>}</div>
      {error && <ErrorBanner message={error} onRetry={load} />}
      {!error && trips === null && <div className="space-y-px">{[0, 1, 2].map((i) => <div key={i} className="skeleton h-20" />)}</div>}
      {trips?.length === 0 && (
        <EmptyState title="No trips yet" action={<><Link to="/join"><Button>Join with a code</Button></Link><Link to="/create"><Button variant="primary">Start a trip</Button></Link></>}>
          Start one for your group, or join a friend's with the trip code they shared.</EmptyState>)}
      {trips && trips.length > 0 && (
        <ul className="divide-y divide-sand border-y border-sand">
          {trips.map((t) => { const [label, tone] = STATUS[t.status]; return (
            <li key={t.id}><Link to={`/trip/${t.id}`} className="group flex items-center gap-4 py-4 hover:bg-sand-light/60 sm:px-2">
              <span aria-hidden className="grid size-14 shrink-0 place-items-center rounded bg-lagoon-tint font-display text-2xl text-lagoon">{t.destination[0]}</span>
              <span className="min-w-0 flex-1"><span className="block truncate font-display text-xl">{t.name}</span>
                <span className="block truncate text-sm text-ink-soft">{t.destination} · {dateRange(t.start_date, t.end_date)} · {t.member_count} traveller{t.member_count === 1 ? "" : "s"}{t.group_budget ? ` · ${inr(t.group_budget)}` : ""}</span></span>
              <Badge tone={tone} className="hidden sm:inline-flex">{label}</Badge>
              <span className="hidden font-mono text-sm text-ink-faint sm:block">{t.code}</span>
              <ChevronRight size={18} className="text-ink-faint transition-transform group-hover:translate-x-0.5" aria-hidden />
            </Link></li>); })}
        </ul>)}
    </main>
  );
}
