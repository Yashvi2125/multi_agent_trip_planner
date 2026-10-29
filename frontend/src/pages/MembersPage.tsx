import { ConflictBlock } from "@/components/trip/ConflictBlock";
import { Avatar, Badge, EmptyState, SectionTitle, Skeleton } from "@/components/ui";
import { useTrip } from "@/store/trip";
import type { Constraint, Preference } from "@/types/api";
import { describeConstraint } from "@/utils/describe";
import { firstName, timeAgo } from "@/utils/format";

const byWeight = (a: Preference, b: Preference) => b.weight - a.weight || a.value.localeCompare(b.value);

function Chips({ items, tone }: { items: Preference[]; tone: "teal" | "neutral" }) {
  return <>{[...items].sort(byWeight).map((p) => <Badge key={`${p.category}:${p.value}`} tone={tone}>{p.value}</Badge>)}</>;
}

/** People, what each of them said they want, and the disagreements the group still has to settle. */
export default function MembersPage() {
  const { trip, prefs, conflicts, ready, me } = useTrip();
  if (!trip) return null;
  const open = conflicts.filter((c) => c.status === "open");
  const closed = conflicts.filter((c) => c.status !== "open");
  const all = prefs?.preferences ?? [];
  const constraints = prefs?.constraints ?? [];
  const groupWide = constraints.filter((c: Constraint) => c.user_id === null);
  const nobodySaidAnything = ready && all.length === 0 && constraints.length === 0;

  return (
    <div className="space-y-10">
      {open.length > 0 && (
        <section aria-labelledby="needs-decision">
          <SectionTitle aside={<Badge tone="amber">{open.length} open</Badge>}><span id="needs-decision">Needs a decision</span></SectionTitle>
          <div className="space-y-6">{open.map((c) => <ConflictBlock key={c.id} conflict={c} />)}</div>
        </section>
      )}

      <section aria-labelledby="travellers">
        <SectionTitle aside={<span className="text-sm text-ink-faint">{trip.members.length} on this trip</span>}><span id="travellers">Travellers</span></SectionTitle>
        {!ready && <div className="space-y-3"><Skeleton className="h-14" /><Skeleton className="h-14" /></div>}
        <ul className="divide-y divide-sand">
          {trip.members.map((m) => {
            const mine = all.filter((p) => p.user_id === m.user.id);
            const likes = mine.filter((p) => p.category !== "dislike");
            const dislikes = mine.filter((p) => p.category === "dislike");
            const limits = constraints.filter((c) => c.user_id === m.user.id);
            return (
              <li key={m.user.id} className="flex gap-4 py-4">
                <Avatar name={m.user.name} id={m.user.id} size={40} via={m.joined_via === "system" ? null : m.joined_via} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-[17px]">{m.user.name}</h3>
                    {m.user.id === me && <Badge tone="teal">You</Badge>}
                    {m.role === "creator" && <Badge>Trip creator</Badge>}
                    <span className="text-sm text-ink-faint">
                      joined {m.joined_via === "telegram" ? "from Telegram" : "on the web"} · {timeAgo(m.joined_at)}
                    </span>
                  </div>
                  {likes.length + dislikes.length + limits.length === 0 ? (
                    <p className="mt-1.5 text-sm text-ink-faint">{firstName(m.user.name)} hasn't shared any preferences yet.</p>
                  ) : (
                    <div className="mt-2 space-y-2">
                      {likes.length > 0 && <p className="flex flex-wrap items-center gap-1.5 text-sm"><span className="text-ink-soft">Into</span><Chips items={likes} tone="teal" /></p>}
                      {dislikes.length > 0 && <p className="flex flex-wrap items-center gap-1.5 text-sm"><span className="text-ink-soft">Not keen on</span><Chips items={dislikes} tone="neutral" /></p>}
                      {limits.length > 0 && (
                        <ul className="space-y-0.5 text-sm text-ink">
                          {limits.map((c, i) => <li key={i} className="flex gap-2"><span aria-hidden className="text-terracotta">•</span>{describeConstraint(c)}</li>)}
                        </ul>
                      )}
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
        {nobodySaidAnything && (
          <EmptyState title="Nobody has shared preferences yet">
            Just say what you're after in the chat, like “I'd love a beach day” or “I can't spend more than ₹12,000”, and I'll pick it up.
          </EmptyState>
        )}
      </section>

      {groupWide.length > 0 && (
        <section aria-labelledby="group-rules">
          <SectionTitle><span id="group-rules">For the whole group</span></SectionTitle>
          <ul className="space-y-1 text-[15px]">{groupWide.map((c, i) => <li key={i} className="flex gap-2"><span aria-hidden className="text-terracotta">•</span>{describeConstraint(c)}</li>)}</ul>
        </section>
      )}

      {closed.length > 0 && (
        <section aria-labelledby="earlier">
          <details>
            <summary className="cursor-pointer text-xl"><span id="earlier">Earlier decisions</span> <span className="text-sm text-ink-faint">({closed.length})</span></summary>
            <div className="mt-4 space-y-6">{closed.map((c) => <ConflictBlock key={c.id} conflict={c} compact />)}</div>
          </details>
        </section>
      )}
    </div>
  );
}
