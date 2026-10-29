import { Check, Copy, MessageCircle, Settings, X } from "lucide-react";
import { useState } from "react";
import { Link, NavLink, Outlet, useLocation, useParams } from "react-router-dom";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { Avatar, Button, cx, EmptyState, Skeleton } from "@/components/ui";
import { TripProvider, useTrip } from "@/store/trip";
import { dateRange, inr } from "@/utils/format";

const TABS = [
  { to: "", label: "Overview", end: true }, { to: "itinerary", label: "Plan" }, { to: "chat", label: "Chat" },
  { to: "budget", label: "Budget" }, { to: "members", label: "People" },
];

function CopyCode({ code }: { code: string }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(code); setDone(true); setTimeout(() => setDone(false), 1600); } catch { /* clipboard blocked: the code is still visible */ }
  };
  return (
    <button onClick={copy} aria-label={`Copy trip code ${code}`} title="Copy trip code"
      className="inline-flex items-center gap-1.5 rounded border border-sand-dark bg-surface px-2 py-1 font-mono text-sm font-semibold tracking-wider hover:bg-sand-light">
      {code}{done ? <Check size={13} className="text-olive" aria-hidden /> : <Copy size={13} className="text-ink-faint" aria-hidden />}
    </button>
  );
}

function Shell() {
  const t = useTrip();
  const { pathname } = useLocation();
  const [drawer, setDrawer] = useState(false);
  const onChat = pathname.endsWith("/chat");

  if (t.loadError && !t.trip) {
    return <main className="mx-auto max-w-6xl px-4 py-10"><EmptyState title="We couldn't open this trip" action={<Link to="/trips"><Button variant="secondary">Back to my trips</Button></Link>}>{t.loadError}</EmptyState></main>;
  }
  if (!t.trip) {
    return <main className="mx-auto max-w-6xl space-y-4 px-4 py-8"><Skeleton className="h-10 w-72" /><Skeleton className="w-96" /><Skeleton className="mt-8 h-64" /></main>;
  }
  const trip = t.trip, base = `/trip/${trip.id}`;
  return (
    <div className="mx-auto max-w-6xl px-4 pb-24 md:pb-10">
      <div className="flex flex-wrap items-end gap-x-6 gap-y-3 pb-4 pt-6">
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-[32px] leading-tight sm:text-4xl">{trip.destination}</h1>
          <p className="mt-1 text-ink-soft">{dateRange(trip.start_date, trip.end_date)} · {trip.member_count} traveller{trip.member_count === 1 ? "" : "s"}{trip.group_budget ? ` · ${inr(trip.group_budget)} group budget` : ""}</p>
        </div>
        <div className="flex items-center gap-3">
          <ul className="flex -space-x-2" aria-label="Travellers">{trip.members.slice(0, 5).map((m) => <li key={m.user.id} className="rounded-full ring-2 ring-paper"><Avatar name={m.user.name} id={m.user.id} via={m.joined_via === "system" ? null : m.joined_via} /></li>)}
            {trip.members.length > 5 && <li className="grid size-8 place-items-center rounded-full bg-sand text-xs font-semibold ring-2 ring-paper">+{trip.members.length - 5}</li>}</ul>
          <CopyCode code={trip.code} />
          <Link to={`${base}/settings`} aria-label="Trip settings" className="rounded p-2 text-ink-soft hover:bg-sand-light"><Settings size={18} /></Link>
          {!onChat && <button onClick={() => setDrawer(true)} className="hidden items-center gap-1.5 rounded border border-sand-dark bg-surface px-3 py-1.5 text-sm font-semibold md:inline-flex lg:hidden"><MessageCircle size={16} aria-hidden />Chat</button>}
        </div>
      </div>

      <nav aria-label="Trip sections" className="mb-6 hidden gap-1 border-b border-sand md:flex">
        {TABS.map((tab) => <NavLink key={tab.label} to={tab.to ? `${base}/${tab.to}` : base} end={tab.end}
          className={({ isActive }) => cx("-mb-px border-b-2 px-4 py-2.5 text-[15px] font-semibold", isActive ? "border-terracotta text-ink" : "border-transparent text-ink-soft hover:text-ink")}>{tab.label}</NavLink>)}
      </nav>

      {t.conn === "offline" && <p role="status" className="mb-4 rounded bg-amber-tint px-3 py-2 text-sm text-amber">You're offline. Reconnecting, and I'll catch up on anything you missed.</p>}

      <div className={cx(!onChat && "lg:grid lg:grid-cols-[minmax(0,1fr)_380px] lg:gap-10")}>
        <main className="min-w-0"><Outlet /></main>
        {!onChat && <aside aria-label="Group chat" className="hidden border-l border-sand lg:sticky lg:top-20 lg:block lg:h-[calc(100dvh-7rem)]"><ChatPanel className="h-full" /></aside>}
      </div>

      {drawer && (
        <div className="fixed inset-0 z-50 flex justify-end bg-ink/40" onClick={() => setDrawer(false)}>
          <aside onClick={(e) => e.stopPropagation()} className="flex h-full w-[min(420px,92vw)] animate-rise flex-col bg-surface shadow-pop" aria-label="Group chat">
            <div className="flex items-center justify-between border-b border-sand px-4 py-3"><h2 className="text-lg">Group chat</h2>
              <button onClick={() => setDrawer(false)} aria-label="Close chat" className="rounded p-1.5 hover:bg-sand-light"><X size={18} /></button></div>
            <ChatPanel className="min-h-0 flex-1" />
          </aside>
        </div>)}

      <nav aria-label="Trip sections" className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-sand bg-paper md:hidden" style={{ paddingBottom: "env(safe-area-inset-bottom)" }}>
        {TABS.map((tab) => <NavLink key={tab.label} to={tab.to ? `${base}/${tab.to}` : base} end={tab.end}
          className={({ isActive }) => cx("py-3 text-center text-[13px] font-semibold", isActive ? "text-terracotta" : "text-ink-soft")}>{tab.label}</NavLink>)}
      </nav>
    </div>
  );
}

export default function TripLayout() {
  const id = Number(useParams().tripId);
  if (!Number.isInteger(id) || id < 1) return <main className="mx-auto max-w-6xl px-4 py-10"><EmptyState title="That trip link doesn't look right" action={<Link to="/trips"><Button>My trips</Button></Link>} /></main>;
  return <TripProvider id={id}><Shell /></TripProvider>;
}
