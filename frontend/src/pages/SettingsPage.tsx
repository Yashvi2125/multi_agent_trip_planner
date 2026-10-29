import { ExternalLink } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { Badge, Button, ErrorBanner, Field, Input, SectionTitle, Skeleton } from "@/components/ui";
import { CopyField } from "@/components/ui/CopyField";
import { api, ApiError } from "@/services/api";
import { useAuth } from "@/store/auth";
import { useTrip } from "@/store/trip";
import type { LinkCode, TelegramStatus, TripDetail, TripUpdate } from "@/types/api";

const msg = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

function TripDetails({ trip }: { trip: TripDetail }) {
  const { me, refresh } = useTrip();
  const creator = trip.members.find((m) => m.role === "creator");
  const canEdit = trip.creator_id === me || creator?.user.id === me;
  const planExists = trip.current_itinerary_version > 0;
  const [f, setF] = useState({ name: trip.name, destination: trip.destination, start: trip.start_date ?? "",
    end: trip.end_date ?? "", budget: trip.group_budget ? String(Math.round(Number(trip.group_budget))) : "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => { setF((s) => ({ ...s, [k]: e.target.value })); setSaved(null); };

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null); setFieldErrors({}); setSaved(null);
    if (f.start && f.end && f.end < f.start) { setFieldErrors({ end_date: "The trip can't end before it starts." }); return; }
    const changes: TripUpdate = {};
    if (f.name.trim() !== trip.name) changes.name = f.name.trim();
    if (!planExists && f.destination.trim() !== trip.destination) changes.destination = f.destination.trim();
    if ((f.start || null) !== trip.start_date) changes.start_date = f.start || null;
    if ((f.end || null) !== trip.end_date) changes.end_date = f.end || null;
    const before = trip.group_budget ? String(Math.round(Number(trip.group_budget))) : "";
    if (f.budget !== before) changes.group_budget = f.budget ? f.budget : null;
    if (Object.keys(changes).length === 0) { setSaved("Nothing to change."); return; }
    setBusy(true);
    try {
      await api.trips.update(trip.id, changes);
      await refresh.trip();
      setSaved(planExists && ("start_date" in changes || "end_date" in changes || "group_budget" in changes)
        ? "Saved. Say “@planner update the plan” in the chat to refresh the itinerary."
        : "Saved.");
    } catch (err) {
      setError(msg(err, "We couldn't save that. Please try again."));
      if (err instanceof ApiError) setFieldErrors(Object.fromEntries(err.fields.map((x) => [x.field, x.issue])));
    } finally { setBusy(false); }
  }

  return (
    <section aria-labelledby="details">
      <SectionTitle><span id="details">Trip details</span></SectionTitle>
      {!canEdit && <p role="note" className="mb-4 rounded bg-sand-light px-3 py-2 text-sm text-ink-soft">
        Only {creator?.user.name ?? "the person who created the trip"} can change these details.</p>}
      <form onSubmit={submit} className="max-w-lg space-y-4" noValidate>
        <Field label="Trip name" error={fieldErrors.name}>{(id) => <Input id={id} value={f.name} onChange={set("name")} disabled={!canEdit} maxLength={120} />}</Field>
        <Field label="Destination" error={fieldErrors.destination}
          hint={planExists ? "Locked once a plan exists. Start a new trip to go somewhere else." : undefined}>
          {(id) => <Input id={id} value={f.destination} onChange={set("destination")} disabled={!canEdit || planExists} />}</Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Starts" error={fieldErrors.start_date}>{(id) => <Input id={id} type="date" value={f.start} onChange={set("start")} disabled={!canEdit} />}</Field>
          <Field label="Ends" error={fieldErrors.end_date}>{(id) => <Input id={id} type="date" value={f.end} onChange={set("end")} disabled={!canEdit} min={f.start || undefined} />}</Field>
        </div>
        <Field label="Group budget (₹)" error={fieldErrors.group_budget} hint="The total for everyone. Leave empty for no limit.">
          {(id) => <Input id={id} type="number" inputMode="numeric" min={1} step={500} value={f.budget} onChange={set("budget")} disabled={!canEdit} />}</Field>
        {error && <ErrorBanner message={error} />}
        {saved && <p role="status" className="text-sm text-olive">{saved}</p>}
        {canEdit && <Button type="submit" variant="primary" busy={busy}>Save changes</Button>}
      </form>
    </section>
  );
}

function Invite({ trip }: { trip: TripDetail }) {
  return (
    <section aria-labelledby="invite">
      <SectionTitle><span id="invite">Invite friends</span></SectionTitle>
      <p className="mb-3 max-w-lg text-ink-soft">Anyone with the code can join, from the web or from Telegram. They all end up on the same trip.</p>
      <div className="max-w-lg space-y-3">
        <CopyField label="trip code" value={trip.code} />
        <CopyField label="invite link" value={`${window.location.origin}/join/${trip.code}`} mono={false} />
      </div>
    </section>
  );
}

function TelegramPanel({ trip }: { trip: TripDetail }) {
  const { user } = useAuth();
  const [status, setStatus] = useState<TelegramStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [code, setCode] = useState<LinkCode | null>(null);
  const [codeError, setCodeError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const load = () => { setStatusError(null); api.telegram.status().then(setStatus).catch((e) => setStatusError(msg(e, "Couldn't check Telegram."))); };
  useEffect(load, []);

  async function getCode() {
    setBusy(true); setCodeError(null);
    try { setCode(await api.telegram.linkCode()); } catch (e) { setCodeError(msg(e, "Couldn't create a link code.")); } finally { setBusy(false); }
  }
  const bot = status?.bot_username ? `@${status.bot_username}` : "the Wayfare bot";

  return (
    <section aria-labelledby="telegram">
      <SectionTitle aside={status?.configured ? <Badge tone={trip.telegram_connected ? "olive" : "amber"}>{trip.telegram_connected ? "Group connected" : "No group yet"}</Badge> : undefined}>
        <span id="telegram">Telegram</span></SectionTitle>
      {statusError ? <ErrorBanner message={statusError} onRetry={load} />
        : !status ? <Skeleton className="h-24 max-w-lg" />
        : !status.configured ? (
          <p className="max-w-lg text-ink-soft">The Telegram bot isn't switched on for this server yet. Whoever runs Wayfare can enable it by setting a bot token. Everything else works without it.</p>
        ) : (
          <div className="max-w-lg space-y-8">
            <div>
              <h3 className="text-[17px]">Connect a group chat</h3>
              <ol className="mt-2 list-decimal space-y-1.5 pl-5 text-[15px] text-ink-soft">
                <li>Add {bot} to your Telegram group.</li>
                <li>Send <code className="rounded bg-sand-light px-1.5 py-0.5 font-mono text-ink">/join {trip.code}</code> in the group.</li>
                <li>Everyone who writes there joins this trip, and chat stays in sync with the web.</li>
              </ol>
              <p className="mt-3 text-sm text-ink-faint">If the bot doesn't seem to hear everyone, turn off its privacy mode in BotFather (<code className="font-mono">/setprivacy</code> → Disable), then re-add it to the group.</p>
              {status.bot_username && <a href={`https://t.me/${status.bot_username}`} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1.5 text-sm font-semibold text-lagoon underline underline-offset-2">Open {bot} in Telegram<ExternalLink size={13} aria-hidden /></a>}
            </div>
            <div>
              <h3 className="text-[17px]">Link your Telegram account</h3>
              {user?.telegram_username
                ? <p className="mt-1.5 text-[15px] text-ink-soft">Linked as <span className="font-semibold text-ink">@{user.telegram_username}</span>. Your Telegram messages show up under your name here.</p>
                : <p className="mt-1.5 text-[15px] text-ink-soft">If you already chatted with the bot before making an account, link them so everything is under one name.</p>}
              {!code
                ? <Button className="mt-3" onClick={getCode} busy={busy}>Get a link code</Button>
                : <div className="mt-3 space-y-2">
                    <CopyField label="link command" value={`/link ${code.code}`} />
                    <p className="text-sm text-ink-faint">Send this to {bot} in a private chat within {Math.round(code.expires_in_seconds / 60)} minutes. It works once.</p>
                  </div>}
              {codeError && <div className="mt-3"><ErrorBanner message={codeError} /></div>}
            </div>
          </div>
        )}
    </section>
  );
}

export default function SettingsPage() {
  const { trip } = useTrip();
  if (!trip) return null;
  return <div className="space-y-12"><TripDetails trip={trip} /><Invite trip={trip} /><TelegramPanel trip={trip} /></div>;
}
