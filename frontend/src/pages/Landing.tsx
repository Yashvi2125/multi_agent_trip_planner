import { ArrowRight } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button, Input } from "@/components/ui";
import { api } from "@/services/api";
import { useAuth } from "@/store/auth";
import type { Destination } from "@/types/api";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const STEPS = [
  ["Everyone says what they want", "In Telegram or on the web, in plain words. \"No nightlife for me.\" \"Keep it under ₹12,000.\" The planner quietly keeps track."],
  ["Disagreements get settled, not buried", "When two people want different things, the planner names the clash, suggests a middle path, and the group votes."],
  ["A plan you can question", "Day-by-day timings, travel time and costs. Ask why any stop is there, change your mind, and watch the plan update."],
];

function RouteArt() {
  return (
    <svg aria-hidden viewBox="0 0 420 320" className="w-full max-w-md text-lagoon" fill="none">
      <rect x="1" y="1" width="418" height="318" rx="10" fill="#F3EDE2" stroke="#E9DFCF" strokeWidth="2" />
      {[60, 120, 180, 240].map((y) => <path key={y} d={`M0 ${y}c70-20 120 22 210 0s150-18 210 0`} stroke="#E4D8C3" strokeWidth="1.5" />)}
      <path d="M52 250c40-90 90 20 150-60s60-90 110-70 50 8 60-40" stroke="#0F5C5A" strokeWidth="3" strokeLinecap="round" strokeDasharray="2 9" />
      {[[52, 250], [202, 190], [312, 120]].map(([x, y], i) => <circle key={i} cx={x} cy={y} r="7" fill="#0F5C5A" stroke="#FAF7F2" strokeWidth="3" />)}
      <circle cx="372" cy="80" r="9" fill="#C8553D" stroke="#FAF7F2" strokeWidth="3" />
      <text x="36" y="282" fontFamily="Fraunces, serif" fontSize="15" fill="#4A5A54">Arrive</text>
      <text x="326" y="64" fontFamily="Fraunces, serif" fontSize="15" fill="#4A5A54">Day 5</text>
    </svg>
  );
}

export default function Landing() {
  const { status } = useAuth();
  const nav = useNavigate();
  const [dests, setDests] = useState<Destination[] | null>(null);
  const [code, setCode] = useState("");
  useEffect(() => { api.destinations().then(setDests).catch(() => setDests([])); }, []);
  const join = (e: FormEvent) => { e.preventDefault(); if (code.trim()) nav(`/join/${code.trim().toUpperCase()}`); };

  return (
    <main>
      <section className="mx-auto grid max-w-6xl items-center gap-10 px-4 pb-14 pt-12 md:grid-cols-[1.1fr_1fr] md:pt-20">
        <div>
          <h1 className="text-[40px] leading-[1.08] sm:text-5xl">Plan the trip together, wherever everyone's chatting.</h1>
          <p className="mt-5 max-w-xl text-lg text-ink-soft">Wayfare turns a messy group chat into one shared plan. Friends on Telegram and friends on the web are on the same trip, with the same itinerary and budget.</p>
          <div className="mt-7 flex flex-wrap items-center gap-3">
            <Link to={status === "authed" ? "/create" : "/register"}><Button variant="primary" className="px-5 py-3">Start a trip<ArrowRight size={17} aria-hidden /></Button></Link>
            <form onSubmit={join} className="flex gap-2" aria-label="Join a trip with a code">
              <Input value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder="Trip code, e.g. GOA-4X7" aria-label="Trip code" className="w-52 font-mono uppercase tracking-wider" maxLength={12} />
              <Button type="submit" disabled={!code.trim()}>Join</Button>
            </form>
          </div>
        </div>
        <div className="flex justify-center md:justify-end"><RouteArt /></div>
      </section>

      <section className="border-y border-sand bg-sand-light/60">
        <ol className="mx-auto grid max-w-6xl gap-x-10 gap-y-8 px-4 py-12 md:grid-cols-3">
          {STEPS.map(([title, body], i) => (
            <li key={title}><span className="font-display text-3xl text-terracotta">{i + 1}</span><h2 className="mt-1 text-xl">{title}</h2><p className="mt-2 text-ink-soft">{body}</p></li>))}
        </ol>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-14">
        <h2 className="text-3xl">Places the planner knows well</h2>
        <p className="mt-2 max-w-2xl text-ink-soft">Plans are built from verified places, opening hours and travel times, never invented attractions. Other destinations can be created, but can't be planned yet.</p>
        <ul className="mt-8 grid gap-x-10 gap-y-6 md:grid-cols-3">
          {dests === null ? [0, 1, 2].map((i) => <li key={i} className="skeleton h-28" />) : dests.map((d) => (
            <li key={d.id} className="border-t border-sand-dark pt-4">
              <h3 className="text-2xl">{d.name}</h3>
              <p className="mt-1 text-sm text-ink-faint">{d.places} places · best in {d.dry_months.length ? `${MONTHS[d.dry_months[0] - 1]}–${MONTHS[d.dry_months[d.dry_months.length - 1] - 1]}` : "any season"}</p>
              <p className="mt-2 text-ink-soft">{d.highlights.join(" · ")}</p>
            </li>))}
        </ul>
      </section>
      <footer className="border-t border-sand py-8 text-center text-sm text-ink-faint">Wayfare · a multi-agent group trip planner · JG University minor project</footer>
    </main>
  );
}
