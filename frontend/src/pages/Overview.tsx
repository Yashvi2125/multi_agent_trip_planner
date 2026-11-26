import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CalendarDays, KeyRound, Luggage, Map, Plus, Users } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { DeleteTripDialog } from "../components/DeleteTripDialog";
import { LeaveTripDialog } from "../components/LeaveTripDialog";
import { TripCard } from "../components/TripCard";
import { EmptyState, PageLoader, QueryError } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { api } from "../lib/api";
import { todayISO } from "../lib/format";
import type { TripSummary } from "../lib/types";

function Section({ title, trips, onDelete, onLeave }: { title: string; trips: TripSummary[]; onDelete: (t: TripSummary) => void; onLeave: (t: TripSummary) => void }) {
  if (!trips.length) return null;
  return (
    <section className="mt-7 sm:mt-9">
      <div className="mb-5 flex items-center gap-3">
        <h2 className="text-xl font-semibold">{title}</h2>
        <span className="rounded-full bg-lagoon-50 px-2.5 py-0.5 text-xs font-bold text-lagoon-700 ring-1 ring-inset ring-lagoon-200">{trips.length}</span>
        <span className="h-px flex-1 bg-gradient-to-r from-sand-300 to-transparent" aria-hidden />
      </div>
      <div className="grid gap-4 sm:gap-5 md:grid-cols-2 xl:grid-cols-3">{trips.map((t) => <TripCard key={t.id} trip={t} onDelete={onDelete} onLeave={onLeave} />)}</div>
    </section>
  );
}

function Stat({ icon: Icon, label, value }: { icon: typeof Map; label: string; value: number }) {
  return (
    <div className="flex items-center justify-center gap-2.5 rounded-2xl bg-white/90 px-3 py-2 shadow-sm ring-1 ring-sand-200/80 sm:justify-start">
      <span className="hidden h-8 w-8 items-center justify-center rounded-lg bg-lagoon-50 text-lagoon-700 sm:flex"><Icon className="h-4 w-4" aria-hidden /></span>
      <div><p className="font-display text-lg font-bold leading-none text-ink-900">{value}</p><p className="mt-0.5 text-[11px] font-medium text-ink-500">{label}</p></div>
    </div>
  );
}

export default function Overview() {
  const { user } = useAuth();
  const q = useQuery({ queryKey: ["trips"], queryFn: () => api<TripSummary[]>("/api/trips") });
  const [tripToDelete, setTripToDelete] = useState<TripSummary | null>(null);
  const [tripToLeave, setTripToLeave] = useState<TripSummary | null>(null);
  const today = todayISO();
  const trips = q.data ?? [];
  const upcoming = trips.filter((t) => t.end_date >= today);
  const joined = trips.filter((t) => t.my_role === "member");
  const recent = [...trips].filter((t) => t.last_accessed_at).sort((a, b) => b.last_accessed_at!.localeCompare(a.last_accessed_at!)).slice(0, 3);

  return (
    <div>
      <section className="surface-soft rounded-2xl px-4 py-3.5 sm:rounded-3xl sm:px-6 sm:py-4">
        <div className="pointer-events-none absolute inset-0 bg-dots-dark opacity-60" aria-hidden />
        <div className="pointer-events-none absolute -right-6 -top-10 h-28 w-28 rounded-full bg-sun-500/80" aria-hidden style={{ boxShadow: "0 0 60px 16px rgba(233,162,59,.25)" }} />
        <div className="relative flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
          <div className="min-w-0">
            <h1 className="text-xl font-bold sm:text-3xl">Hello, {user!.name.split(" ")[0]}</h1>
            <p className="mt-0.5 text-[13px] text-ink-700 sm:text-sm">Create a trip, invite your group, and let MileMates AI help you agree on a plan.</p>
          </div>
          <div className="flex w-full flex-wrap items-center gap-2.5 sm:w-auto">
            {trips.length > 0 && (<div className="grid w-full grid-cols-3 gap-2 sm:flex sm:w-auto sm:gap-2.5">
              <Stat icon={Map} label="Trips" value={trips.length} />
              <Stat icon={CalendarDays} label="Upcoming" value={upcoming.length} />
              <Stat icon={Users} label="Joined" value={joined.length} />
            </div>)}
            <Link to="/app/trips/new" className="btn-primary !py-2.5 max-sm:hidden"><Plus className="h-4 w-4" />Create New Trip</Link>
          </div>
        </div>
      </section>

      <div className="mt-3 grid grid-cols-3 gap-2 sm:mt-4 sm:gap-3">
        {([
          [Plus, "Start a new trip", "Set dates, budget and interests", "/app/trips/new", "bg-lagoon-50 text-lagoon-700"],
          [KeyRound, "Join with a code", "Got an invite? Hop in", "/app/join", "bg-sun-100 text-sun-700"],
          [Map, "Browse my trips", "Everything in one place", "/app/trips", "bg-coral-100 text-coral-700"],
        ] as const).map(([Icon, t, d, to, tone]) => (
          <Link key={to} to={to} className="card card-hover group flex flex-col items-center gap-2 p-3 text-center sm:flex-row sm:gap-3 sm:text-left">
            <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl transition-transform sm:h-12 sm:w-12 duration-300 group-hover:-rotate-6 group-hover:scale-110 ${tone}`}><Icon className="h-5 w-5" aria-hidden /></span>
            <span className="min-w-0 sm:flex-1"><span className="block text-[13px] font-semibold leading-tight text-ink-900 sm:text-base">{t}</span><span className="hidden truncate text-sm text-ink-500 sm:block">{d}</span></span>
            <ArrowRight className="hidden h-4 w-4 shrink-0 text-ink-400 transition-all group-hover:translate-x-1 group-hover:text-lagoon-700 sm:block" aria-hidden />
          </Link>))}
      </div>

      {q.isLoading ? <PageLoader /> : q.error ? <div className="mt-8"><QueryError error={q.error} retry={() => q.refetch()} /></div> :
        trips.length === 0 ? (
          <div className="mt-8">
            <EmptyState icon={<Luggage className="h-7 w-7" />} title="No adventures planned yet."
              text="Create your first group trip and invite your friends — or join one with a trip code."
              action={<div className="flex flex-wrap justify-center gap-3"><Link to="/app/trips/new" className="btn-primary">Create Your First Trip</Link><Link to="/app/join" className="btn-secondary">Join a Trip</Link></div>} />
          </div>
        ) : (
          <>
            <Section title="Upcoming trips" trips={upcoming} onDelete={setTripToDelete} onLeave={setTripToLeave} />
            <Section title="Trips you’ve joined" trips={joined} onDelete={setTripToDelete} onLeave={setTripToLeave} />
            <Section title="Recently opened" trips={recent} onDelete={setTripToDelete} onLeave={setTripToLeave} />
            {upcoming.length === 0 && <p className="mt-8 text-ink-500">All your trips have already ended. <Link className="inline-flex items-center gap-1 font-semibold text-lagoon-700 underline" to="/app/trips">See them in My Trips<ArrowRight className="h-3.5 w-3.5" aria-hidden /></Link>.</p>}
          </>
        )}
      {tripToDelete && <DeleteTripDialog trip={tripToDelete} onClose={() => setTripToDelete(null)} />}
      {tripToLeave && <LeaveTripDialog trip={tripToLeave} onClose={() => setTripToLeave(null)} />}
    </div>
  );
}