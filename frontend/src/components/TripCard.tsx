import { ArrowUpRight, CalendarDays, LogOut, MapPin, Trash2, Users, Wallet } from "lucide-react";
import { Link } from "react-router-dom";
import { dateRange, dayCount, money } from "../lib/format";
import type { TripSummary } from "../lib/types";
import { Badge } from "./ui";

export const statusLabel = (s: string) => (s === "itinerary_ready" ? "Itinerary ready" : "Planning");

export function TripCard({ trip, onDelete, onLeave }: { trip: TripSummary; onDelete?: (trip: TripSummary) => void; onLeave?: (trip: TripSummary) => void }) {
  const budget = trip.budget_total ?? (trip.budget_per_person ? trip.budget_per_person * trip.travelers_count : null);
  const ready = trip.status === "itinerary_ready";
  const initial = (trip.destination ?? trip.name).trim().charAt(0).toUpperCase() || "T";
  const rows = [
    { icon: CalendarDays, label: "Dates", text: `${dateRange(trip.start_date, trip.end_date)} · ${dayCount(trip.start_date, trip.end_date)} days` },
    { icon: Users, label: "Participants", text: `${trip.member_count} joined · ${trip.travelers_count} travelling${trip.my_role === "owner" ? " · you organise" : ""}` },
    ...(budget !== null ? [{ icon: Wallet, label: "Budget", text: `${money(budget, trip.currency)} group budget` }] : []),
  ];
  return (
    <article className="card card-hover group relative flex flex-col overflow-hidden p-5">
      <span className={`absolute inset-x-0 top-0 h-1 ${ready ? "bg-gradient-to-r from-lagoon-500 to-lagoon-200" : "bg-gradient-to-r from-sun-500 to-sun-100"}`} aria-hidden />
      <div className="flex items-start gap-3">
        <span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl font-display text-lg font-bold ${ready ? "bg-lagoon-50 text-lagoon-700" : "bg-sun-100 text-sun-700"}`} aria-hidden>{initial}</span>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-lg font-semibold leading-tight">{trip.name}</h3>
          <p className="mt-0.5 flex items-center gap-1.5 truncate text-sm text-ink-500"><MapPin className="h-3.5 w-3.5 shrink-0 text-lagoon-600" aria-hidden />{trip.destination ?? "Destination undecided"}</p>
        </div>
        {trip.my_role === "owner" && onDelete && (
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onDelete(trip);
            }}
            className="-mr-1 -mt-1 flex min-h-[44px] min-w-[44px] shrink-0 items-center justify-center rounded-xl text-coral-500 transition-colors hover:bg-coral-100 hover:text-coral-700"
            title={`Delete ${trip.name}`}
            aria-label={`Delete ${trip.name}`}
          >
            <Trash2 className="h-4 w-4" />
          </button>
        )}
        {trip.my_role === "member" && onLeave && (
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onLeave(trip);
            }}
            className="-mr-1 -mt-1 flex min-h-[44px] min-w-[44px] shrink-0 items-center justify-center rounded-xl text-coral-500 transition-colors hover:bg-coral-100 hover:text-coral-700"
            title={`Leave ${trip.name}`}
            aria-label={`Leave ${trip.name}`}
          >
            <LogOut className="h-4 w-4" />
          </button>
        )}
      </div>
      <div className="mt-3"><Badge tone={ready ? "teal" : "amber"}>{statusLabel(trip.status)}</Badge></div>
      <dl className="mt-4 space-y-2 border-t border-sand-200/80 pt-4 text-sm text-ink-700">
        {rows.map(({ icon: Icon, label, text }) => (
          <div key={label} className="flex items-center gap-2.5">
            <Icon className="h-4 w-4 shrink-0 text-ink-400" aria-hidden />
            <dt className="sr-only">{label}</dt>
            <dd className="min-w-0">{text}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-auto flex flex-wrap gap-2 pt-5">
        <Link to={`/app/trips/${trip.id}/chat`} className="btn-primary !py-2">View Trip<ArrowUpRight className="h-4 w-4" aria-hidden /></Link>
        <Link to={`/app/trips/${trip.id}/itinerary`} className="btn-secondary !py-2">Itinerary</Link>
      </div>
    </article>
  );
}