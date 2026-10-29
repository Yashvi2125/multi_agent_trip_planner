import { Check, Copy } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Button, cx, ErrorBanner, Field, Input } from "@/components/ui";
import { api, ApiError } from "@/services/api";
import type { Destination, DestinationLookup, Trip } from "@/types/api";

const STEPS = ["Where", "When", "Budget", "Review"];

function Done({ trip }: { trip: Trip }) {
  const link = `${window.location.origin}/join/${trip.code}`;
  const [copied, setCopied] = useState<string | null>(null);
  const copy = async (what: string, text: string) => { try { await navigator.clipboard.writeText(text); setCopied(what); setTimeout(() => setCopied(null), 1600); } catch { /* shown on screen anyway */ } };
  return (
    <main className="mx-auto max-w-xl px-4 py-14">
      <p className="text-sm font-bold uppercase tracking-widest text-olive">Trip created</p>
      <h1 className="mt-1 text-4xl">{trip.destination} is on.</h1>
      <p className="mt-2 text-ink-soft">Share this code. Anyone who joins, from Telegram or the web, lands on the same trip.</p>
      <div className="mt-6 flex items-center gap-3 border-y border-sand py-5">
        <span className="font-mono text-4xl font-semibold tracking-[0.18em]" aria-label={`Trip code ${trip.code}`}>{trip.code}</span>
        <Button size="sm" onClick={() => copy("code", trip.code)}>{copied === "code" ? <Check size={14} aria-hidden /> : <Copy size={14} aria-hidden />}Copy</Button>
      </div>
      <dl className="mt-5 space-y-4 text-[15px]">
        <div><dt className="font-semibold">On the web</dt><dd className="mt-1 flex items-center gap-2 text-ink-soft"><span className="break-all">{link}</span><button className="shrink-0 font-semibold text-lagoon underline" onClick={() => copy("link", link)}>{copied === "link" ? "Copied" : "Copy link"}</button></dd></div>
        <div><dt className="font-semibold">On Telegram</dt><dd className="mt-1 text-ink-soft">Add the Wayfare bot to your group chat, then send <code className="rounded bg-sand-light px-1.5 py-0.5 font-mono text-sm">/join {trip.code}</code>. Everyone who writes in that group joins automatically.</dd></div>
      </dl>
      <Link to={`/trip/${trip.id}`} className="mt-8 inline-block"><Button variant="primary" className="px-5 py-3">Open the trip</Button></Link>
    </main>
  );
}

export default function CreateTrip() {
  const [step, setStep] = useState(0);
  const [dests, setDests] = useState<Destination[]>([]);
  const [destination, setDestination] = useState("");
  const [custom, setCustom] = useState(false);
  const [start, setStart] = useState(""), [end, setEnd] = useState(""), [budget, setBudget] = useState(""), [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<Trip | null>(null);
  useEffect(() => { api.destinations().then(setDests).catch(() => setDests([])); }, []);

  const supported = dests.some((d) => d.name.toLowerCase() === destination.trim().toLowerCase());
  const [lookup, setLookup] = useState<DestinationLookup | null>(null);
  useEffect(() => {          // a gentle hint while typing; it never blocks creating a trip
    setLookup(null);
    const q = destination.trim();
    if (!custom || q.length < 3 || supported) return;
    let live = true;
    const t = setTimeout(() => { api.lookupDestination(q).then((r) => live && setLookup(r)).catch(() => undefined); }, 500);
    return () => { live = false; clearTimeout(t); };
  }, [destination, custom, supported]);
  const destinationHint = !custom || destination.trim().length < 2 ? undefined
    : supported ? "We have hand-checked data for this one."
    : lookup?.status === "curated" ? "We have hand-checked data for this one."
    : lookup?.status === "found" ? `We'll research ${lookup.name}${lookup.country ? `, ${lookup.country}` : ""} for you. Places and weather come from real map data, and prices are estimates.`
    : lookup?.status === "not_found" ? "We couldn't find that on the map. Check the spelling. You can still create the trip."
    : lookup?.status === "too_broad" ? "That looks like a whole country or region. A city or area inside it will plan much better."
    : "You can plan a trip anywhere. We'll look it up and research it when you build the plan.";
  const datesBad = !!start && !!end && end < start;
  const budgetNum = budget ? Number(budget.replace(/[,₹\s]/g, "")) : null;
  const budgetBad = budget !== "" && (!Number.isFinite(budgetNum) || (budgetNum ?? 0) <= 0);
  const valid = [destination.trim().length >= 2, !datesBad && (!!start === !!end), !budgetBad, true][step];

  async function create(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try {
      setCreated(await api.trips.create({ name: name.trim() || `${destination.trim()} trip`, destination: destination.trim(),
        start_date: start || null, end_date: end || null, group_budget: budgetNum ? String(budgetNum) : null }));
    } catch (x) { setError(x instanceof ApiError ? x.message : "Couldn't create the trip. Please try again."); } finally { setBusy(false); }
  }
  if (created) return <Done trip={created} />;

  return (
    <main className="mx-auto max-w-2xl px-4 py-10">
      <h1 className="text-4xl">Start a trip</h1>
      <ol className="mt-5 flex gap-6 border-b border-sand text-sm font-semibold" aria-label="Progress">
        {STEPS.map((s, i) => <li key={s} aria-current={i === step ? "step" : undefined} className={cx("-mb-px border-b-2 pb-2", i === step ? "border-terracotta text-ink" : i < step ? "border-transparent text-lagoon" : "border-transparent text-ink-faint")}>{i + 1}. {s}</li>)}
      </ol>
      <form onSubmit={create} className="mt-8 space-y-6">
        {error && <ErrorBanner message={error} />}
        {step === 0 && (
          <fieldset>
            <legend className="mb-3 text-xl">Where are you headed?</legend>
            <ul className="divide-y divide-sand border-y border-sand">
              {dests.map((d) => (
                <li key={d.id}><button type="button" onClick={() => { setDestination(d.name); setCustom(false); }} aria-pressed={!custom && destination === d.name}
                  className={cx("flex w-full items-baseline gap-4 px-2 py-3.5 text-left hover:bg-sand-light/60", !custom && destination === d.name && "bg-lagoon-tint")}>
                  <span className="font-display text-xl">{d.name}</span><span className="flex-1 truncate text-sm text-ink-soft">{d.highlights.slice(0, 3).join(" · ")}</span>
                  {!custom && destination === d.name && <Check size={16} className="text-lagoon" aria-hidden />}</button></li>))}
              <li><button type="button" onClick={() => { setCustom(true); setDestination(""); }} aria-pressed={custom} className={cx("w-full px-2 py-3.5 text-left hover:bg-sand-light/60", custom && "bg-lagoon-tint")}>Somewhere else</button></li>
            </ul>
            {custom && <div className="mt-4"><Field label="Destination" hint={destinationHint}>
              {(id) => <Input id={id} value={destination} onChange={(e) => setDestination(e.target.value)} autoFocus maxLength={120} />}</Field></div>}
          </fieldset>)}
        {step === 1 && (
          <div className="space-y-4"><h2 className="text-xl">When are you going?</h2>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="First day">{(id) => <Input id={id} type="date" value={start} onChange={(e) => { setStart(e.target.value); if (end && e.target.value > end) setEnd(""); }} />}</Field>
              <Field label="Last day" error={datesBad ? "The trip can't end before it starts." : null}>{(id) => <Input id={id} type="date" min={start || undefined} value={end} onChange={(e) => setEnd(e.target.value)} />}</Field></div>
            <p className="text-sm text-ink-faint">Skip this for now if the group hasn't decided. The planner will ask before building anything.</p></div>)}
        {step === 2 && (
          <div className="space-y-4"><h2 className="text-xl">Is there a group budget?</h2>
            <Field label="Total for the whole group (₹)" hint="Optional. Individuals can still set their own limit in the chat, and the strictest one wins." error={budgetBad ? "Enter a number greater than zero." : null}>
              {(id) => <Input id={id} inputMode="numeric" value={budget} onChange={(e) => setBudget(e.target.value)} placeholder="60000" />}</Field></div>)}
        {step === 3 && (
          <div className="space-y-5"><h2 className="text-xl">Ready to go</h2>
            <Field label="Trip name">{(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} placeholder={`${destination} trip`} maxLength={120} />}</Field>
            <dl className="divide-y divide-sand border-y border-sand text-[15px]">
              {[["Destination", destination], ["Dates", start && end ? `${start} to ${end}` : "Not decided yet"], ["Group budget", budgetNum ? `₹${budgetNum.toLocaleString("en-IN")}` : "Not set"]].map(([k, v]) => <div key={k} className="flex justify-between py-2.5"><dt className="text-ink-soft">{k}</dt><dd className="font-semibold">{v}</dd></div>)}</dl></div>)}
        <div className="flex justify-between pt-2">
          <Button type="button" variant="ghost" onClick={() => setStep((s) => s - 1)} disabled={step === 0}>Back</Button>
          {step < 3 ? <Button type="button" variant="primary" disabled={!valid} onClick={() => setStep((s) => s + 1)}>Continue</Button>
            : <Button type="submit" variant="primary" busy={busy}>Create trip</Button>}
        </div>
      </form>
    </main>
  );
}
